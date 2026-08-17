"""x402 buyer: free price discovery, a hard spend cap, and a receipt ledger.

Mirrors the design of `src/reference-buyer/x402-client.ts` so both agents behave the same
way against the same seller:

  * `quote()` costs nothing -- it reads the 402 and throws the response away.
  * `get_paid()` checks the advertised price against the remaining budget
    *before* signing, so the agent never signs an authorization it cannot afford.
  * every settled call is appended to a ledger with its transaction hash.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import httpx
from eth_account import Account
from x402 import x402Client
from x402.http import x402HTTPClient
from x402.http.constants import PAYMENT_REQUIRED_HEADER, PAYMENT_RESPONSE_HEADER
from x402.http.clients.httpx import wrapHttpxWithPayment
from x402.http.utils import decode_payment_required_header, decode_payment_response_header
from x402.mechanisms.evm.exact import register_exact_evm_client
from x402.mechanisms.evm.signers import EthAccountSigner

from .config import EXPLORER_TX, FAUCET_URL, USDC_ADDRESS, USDC_DECIMALS

_ATOMIC = Decimal(10) ** USDC_DECIMALS

_ERC20_BALANCE_ABI = [
    {
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    }
]


class SpendCapExceeded(RuntimeError):
    """The advertised price does not fit in the remaining USDC budget."""


class PaymentFailed(RuntimeError):
    """The facilitator refused to verify or settle the payment."""


def atomic_to_usd(amount: str | int) -> Decimal:
    """`"1000"` (atomic USDC, 6 decimals) -> `Decimal("0.001")`."""
    return Decimal(int(amount)) / _ATOMIC


@dataclass
class Quote:
    path: str
    price_usd: Decimal
    asset: str
    network: str
    pay_to: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "priceUsd": float(self.price_usd),
            "asset": self.asset,
            "network": self.network,
            "payTo": self.pay_to,
        }


@dataclass
class PaidCall:
    path: str
    status: int
    payment_status: str
    spent_usd: Decimal
    transaction: str | None = None
    body: Any = None

    def as_dict(self, include_body: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "path": self.path,
            "status": self.status,
            "paymentStatus": self.payment_status,
            "spentUsd": float(self.spent_usd),
            "transaction": self.transaction,
        }
        if self.transaction:
            out["explorer"] = EXPLORER_TX + self.transaction
        if include_body:
            out["data"] = self.body
        return out


@dataclass
class X402Buyer:
    """Wallet + paying HTTP client + spend ledger."""

    private_key: str
    base_url: str
    spend_cap_usd: Decimal
    rpc_url: str

    address: str = field(init=False)
    _spent_usd: Decimal = field(init=False, default=Decimal(0))
    _ledger: list[PaidCall] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        account = Account.from_key(self.private_key)
        self.address = account.address

        # `eip155:*` registers the exact scheme for every EVM chain the seller
        # may quote, so the agent is not pinned to one chain id.
        client = x402Client()
        register_exact_evm_client(client, EthAccountSigner(account))

        self._client = client
        self._http_client = x402HTTPClient(client)
        self._paying = wrapHttpxWithPayment(client, timeout=45.0)
        self._plain = httpx.AsyncClient(timeout=20.0)

    # --- budget ------------------------------------------------------------
    @property
    def total_spent_usd(self) -> Decimal:
        return self._spent_usd

    @property
    def remaining_usd(self) -> Decimal:
        return max(Decimal(0), self.spend_cap_usd - self._spent_usd)

    @property
    def calls(self) -> list[PaidCall]:
        return list(self._ledger)

    def budget_snapshot(self) -> dict[str, Any]:
        return {
            "capUsd": float(self.spend_cap_usd),
            "spentUsd": float(self._spent_usd),
            "remainingUsd": float(self.remaining_usd),
            "callsMade": len(self._ledger),
        }

    # --- free --------------------------------------------------------------
    async def get_free(self, path: str) -> Any:
        response = await self._plain.get(f"{self.base_url}{path}")
        response.raise_for_status()
        return response.json()

    async def quote(self, path: str) -> Quote | None:
        """Read the advertised price without paying. Returns None if not paywalled."""
        response = await self._plain.get(f"{self.base_url}{path}")
        if response.status_code != 402:
            return None

        body: Any = None
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError):
            pass

        payment_required = self._http_client.get_payment_required_response(
            response.headers.get, body
        )
        accepts = getattr(payment_required, "accepts", None) or []
        if not accepts:
            return None

        requirement = accepts[0]
        return Quote(
            path=path,
            price_usd=atomic_to_usd(requirement.get_amount()),
            asset=requirement.asset,
            network=str(requirement.network),
            pay_to=requirement.pay_to,
        )

    # --- paid --------------------------------------------------------------
    async def get_paid(self, path: str) -> PaidCall:
        url = f"{self.base_url}{path}"

        advertised = await self.quote(path)
        if advertised is not None and advertised.price_usd > self.remaining_usd:
            raise SpendCapExceeded(
                f"Spend cap reached: {path} costs ${advertised.price_usd:.6f} but only "
                f"${self.remaining_usd:.6f} of the ${self.spend_cap_usd:.6f} budget remains."
            )

        response = await self._paying.get(url)

        settle = self._decode_settlement(response)
        body = self._decode_body(response)

        # Still 402 after signing: the facilitator refused to verify.
        if response.status_code == 402:
            raise PaymentFailed(self._explain_refusal(response, path))

        if settle is not None and not settle.success:
            reason = (
                getattr(settle, "error_message", None)
                or getattr(settle, "error_reason", None)
                or "unknown"
            )
            raise PaymentFailed(f"Payment settlement failed for {path}: {reason}")

        if settle is not None and settle.success:
            reported = getattr(settle, "amount", None)
            spent = (
                atomic_to_usd(reported)
                if reported is not None
                else (advertised.price_usd if advertised else Decimal(0))
            )
            self._spent_usd += spent
            call = PaidCall(
                path=path,
                status=response.status_code,
                payment_status="settled",
                spent_usd=spent,
                transaction=getattr(settle, "transaction", None),
                body=body,
            )
            self._ledger.append(call)
            return call

        # No settlement header: a 4xx/5xx from the handler. The middleware
        # cancels the verified authorization on non-2xx, so this is free.
        return PaidCall(
            path=path,
            status=response.status_code,
            payment_status="none",
            spent_usd=Decimal(0),
            body=body,
        )

    # --- helpers -----------------------------------------------------------
    @staticmethod
    def _decode_body(response: httpx.Response) -> Any:
        try:
            return response.json()
        except (json.JSONDecodeError, ValueError):
            return response.text

    @staticmethod
    def _decode_settlement(response: httpx.Response) -> Any | None:
        header = response.headers.get(PAYMENT_RESPONSE_HEADER)
        if not header:
            return None
        try:
            return decode_payment_response_header(header)
        except Exception:
            return None

    def _explain_refusal(self, response: httpx.Response, path: str) -> str:
        reason = "unknown"
        header = response.headers.get(PAYMENT_REQUIRED_HEADER)
        if header:
            try:
                decoded = decode_payment_required_header(header)
                reason = getattr(decoded, "error", None) or reason
            except Exception:
                pass
        hint = ""
        if "insufficient_balance" in str(reason):
            hint = (
                f" The buyer wallet {self.address} holds no test USDC. "
                f"Fund it on Base Sepolia at {FAUCET_URL}."
            )
        return f"Payment was verified-and-rejected for {path}: {reason}.{hint}"

    async def usdc_balance(self, seller_address: str | None = None) -> dict[str, Any]:
        """Read ETH and USDC for the buyer, and USDC for the seller when known.

        Showing both sides matters: if buyer and seller are the same address the
        payment is a self-transfer, and the buyer's balance will not move even
        though the settlement is real and on-chain.
        """
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        usdc = w3.eth.contract(
            address=Web3.to_checksum_address(USDC_ADDRESS), abi=_ERC20_BALANCE_ABI
        )

        buyer = Web3.to_checksum_address(self.address)
        eth_wei = w3.eth.get_balance(buyer)
        buyer_atomic = usdc.functions.balanceOf(buyer).call()

        out: dict[str, Any] = {
            "address": self.address,
            "eth": float(Decimal(eth_wei) / (Decimal(10) ** 18)),
            "usdc": float(atomic_to_usd(buyer_atomic)),
            "usdcAtomic": int(buyer_atomic),
        }

        if seller_address:
            seller = Web3.to_checksum_address(seller_address)
            seller_atomic = usdc.functions.balanceOf(seller).call()
            out["seller"] = {
                "address": seller,
                "usdc": float(atomic_to_usd(seller_atomic)),
                "isSelfTransfer": seller == buyer,
            }
        return out

    async def aclose(self) -> None:
        await self._plain.aclose()
        await self._paying.aclose()
