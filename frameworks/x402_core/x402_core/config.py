"""Chain constants and environment loading for the x402 protocol layer.

No framework, no LLM provider, no agent. This module knows about Base Sepolia and
the repo-root `.env`, and nothing else -- which is what lets three agents built on
three different frameworks share it without depending on each other.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

# x402_core/x402_core/config.py -> x402_core -> agents -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]

# --- chain constants, mirrored from src/shared/config.ts -------------------
NETWORK = "eip155:84532"  # Base Sepolia, CAIP-2
CHAIN_ID = 84532
USDC_ADDRESS = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
USDC_DECIMALS = 6
FAUCET_URL = "https://faucet.circle.com"
EXPLORER_TX = "https://sepolia.basescan.org/tx/"


def load_env(path: Path | None = None) -> None:
    """Read the repo-root `.env`. Existing environment variables always win.

    Dependency-free on purpose: the protocol layer should install with nothing but
    the x402 SDK, so that an agent using it inherits no opinion about config
    libraries.
    """
    env = path or (REPO_ROOT / ".env")
    if not env.exists():
        return
    try:
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip("'\"")
            if key and value and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


load_env()


@dataclass(frozen=True)
class WalletConfig:
    """Everything needed to pay over x402. Nothing about models or frameworks."""

    buyer_private_key: str | None
    data_api_url: str
    rpc_url: str
    usdc_cap_usd: Decimal
    seller_address: str | None = None

    @property
    def wallet_configured(self) -> bool:
        """True when the key looks like a real 32-byte private key.

        The repo ships `BUYER_PRIVATE_KEY=0x` as a stub, which would otherwise fail
        deep inside eth_account with an unhelpful error.
        """
        key = self.buyer_private_key
        if not key:
            return False
        body = key[2:] if key.lower().startswith("0x") else key
        if len(body) != 64:
            return False
        try:
            return int(body, 16) != 0
        except ValueError:
            return False


def load_wallet_config() -> WalletConfig:
    key = (os.environ.get("BUYER_PRIVATE_KEY") or "").strip()
    if key and not key.lower().startswith("0x"):
        key = "0x" + key

    raw_cap = (os.environ.get("AGENT_SPEND_CAP_USD") or "0.05").strip()
    try:
        cap = Decimal(raw_cap)
    except Exception:
        cap = Decimal("0.05")

    seller = (os.environ.get("SELLER_ADDRESS") or "").strip()
    if seller and int(seller, 16) == 0:
        seller = ""  # the shipped placeholder is the zero address

    return WalletConfig(
        buyer_private_key=key or None,
        data_api_url=(os.environ.get("DATA_API_URL") or "http://localhost:4021").rstrip("/"),
        rpc_url=os.environ.get("BASE_SEPOLIA_RPC_URL") or "https://sepolia.base.org",
        usdc_cap_usd=cap,
        seller_address=seller or None,
    )
