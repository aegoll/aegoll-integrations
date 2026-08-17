"""The six x402 operations as plain async functions, plus their descriptions.

This module is the reason three agents on three frameworks can be compared. The
*behaviour* of an x402 buying agent is framework-independent: the same endpoints,
the same prices, the same meaning for each failure. Only the wrapper differs.

    x402_core.toolset  ->  @tool decorator          (Claude Agent SDK)
                       ->  StructuredTool           (LangGraph)
                       ->  plain callable           (Google ADK)

The descriptions live here too. They carry the price signal a model reads before
deciding to spend, so if each agent wrote its own the three would no longer be
measuring the same thing.

Every method returns a JSON **string** -- the one return type all three frameworks
accept without translation.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote as urlquote

from .buyer import X402Buyer
from .config import WalletConfig

DESCRIPTIONS: dict[str, str] = {
    "list_catalog": (
        "Free. Machine-readable catalogue of every endpoint with its price in USD. "
        "Call this first -- it costs nothing and tells you what each purchase would cost."
    ),
    "check_budget": (
        "Free. The authoritative remaining USDC payment budget for buying data. This is "
        "the only source of truth for what you can afford to purchase -- it is NOT your "
        "LLM token budget, and the two are unrelated."
    ),
    "quote_endpoint": (
        "Free. Ask an endpoint what it charges, without paying. Reads the HTTP 402 quote "
        "and discards it. Use this to price a purchase before committing to it. Example "
        "path: /market/snapshot"
    ),
    "buy_market_snapshot": (
        "PAID ($0.001 USDC). Buys the full market snapshot: exact live quotes (last, bid, "
        "ask, spread, 24h volume and change) for every instrument in the feed."
    ),
    "buy_market_signals": (
        "PAID ($0.01 USDC -- the most expensive endpoint). Buys derived analytics for "
        "every instrument: trend, momentum percent, realized volatility percent and "
        "liquidity score. One purchase covers all instruments, so buy it at most once."
    ),
    "buy_ohlcv_history": (
        "PAID ($0.005 USDC per symbol -- charged separately for each symbol you request). "
        "Buys hourly OHLCV candle history for one instrument. Requesting an unknown "
        "symbol returns 404 and costs nothing."
    ),
}

TOOL_NAMES: tuple[str, ...] = tuple(DESCRIPTIONS)

SYSTEM_PROMPT = """\
You are a market-data buying agent. The real data behind this API costs stablecoin
(USDC) over the x402 protocol.

Your USDC payment budget comes from exactly one place: the check_budget tool. It is
unrelated to any token budget you may have. Never infer it from anything else.

Work in this order:
1. Call list_catalog first. Free, and it lists every endpoint with its price.
2. Use quote_endpoint (also free) to confirm a price before buying.
3. Buy only what the task needs. Each paid tool is a real on-chain payment: no
   refunds, and no retries once settled.
4. Before an expensive purchase, call check_budget.

Cost discipline:
- buy_market_signals costs $0.01 and covers every instrument at once. Buy it at most
  once per run. Never twice.
- buy_ohlcv_history costs $0.005 per symbol. Buy candles only for the symbols the
  task requires, never for the whole feed.
- If a paid tool fails, do not retry it and do not try a different paid endpoint
  hoping it behaves differently. A payment-layer failure affects all of them.

Keep interim output short -- one sentence between tool calls, or none. Save your
writing for the final answer: plain prose backed by figures you actually purchased,
closing with one line stating what you spent and on what.
"""

DEFAULT_TASK = (
    "Identify the riskiest and the calmest instrument in this feed. Back the call with "
    "volatility and liquidity figures you have actually purchased, then inspect the "
    "candle history of the riskiest one to say whether the risk is trending up or down. "
    "Stay inside the budget."
)


def build_buyer(config: WalletConfig) -> X402Buyer:
    if not config.wallet_configured:
        raise RuntimeError(
            "BUYER_PRIVATE_KEY is not a usable key (the repo ships the stub `0x`). Run "
            "`npm run wallet:new` in the repo root, paste the key into .env, and fund it "
            "with test USDC on Base Sepolia."
        )
    assert config.buyer_private_key is not None
    return X402Buyer(
        private_key=config.buyer_private_key,
        base_url=config.data_api_url,
        spend_cap_usd=config.usdc_cap_usd,
        rpc_url=config.rpc_url,
    )


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    ok: bool
    detail: str
    paid_usd: float = 0.0
    transaction: str | None = None
    elapsed_s: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.name,
            "args": self.args,
            "ok": self.ok,
            "detail": self.detail,
            "paidUsd": self.paid_usd,
            "transaction": self.transaction,
            "seconds": round(self.elapsed_s, 3),
        }


@dataclass
class X402Toolset:
    """The six operations, plus a ledger of everything they did."""

    buyer: X402Buyer
    calls: list[ToolCall] = field(default_factory=list)
    purchases: list[dict[str, Any]] = field(default_factory=list)

    # --- bookkeeping -----------------------------------------------------
    def _record(
        self,
        name: str,
        args: dict[str, Any],
        started: float,
        ok: bool,
        detail: str,
        paid_usd: float = 0.0,
        transaction: str | None = None,
    ) -> None:
        self.calls.append(
            ToolCall(
                name=name, args=args, ok=ok, detail=detail, paid_usd=paid_usd,
                transaction=transaction, elapsed_s=time.time() - started,
            )
        )

    @property
    def usdc_spent(self) -> float:
        return round(sum(c.paid_usd for c in self.calls), 8)

    @property
    def paid_calls(self) -> int:
        return sum(1 for c in self.calls if c.paid_usd > 0)

    @property
    def failed_calls(self) -> int:
        return sum(1 for c in self.calls if not c.ok)

    @staticmethod
    def _json(payload: Any) -> str:
        return json.dumps(payload, separators=(",", ":"), default=str)

    # --- free ------------------------------------------------------------
    async def list_catalog(self) -> str:
        started = time.time()
        try:
            data = await self.buyer.get_free("/catalog")
            self._record("list_catalog", {}, started, True, "catalogue read")
            return self._json(data)
        except Exception as exc:
            self._record("list_catalog", {}, started, False, str(exc))
            return self._json({"error": f"could not read the catalogue: {exc}"})

    async def check_budget(self) -> str:
        started = time.time()
        snapshot = self.buyer.budget_snapshot()
        snapshot["budgetKind"] = "USDC payment budget for buying data (not LLM tokens)"
        self._record(
            "check_budget", {}, started, True, f"remaining ${snapshot['remainingUsd']:.6f}"
        )
        return self._json(snapshot)

    async def quote_endpoint(self, path: str) -> str:
        started = time.time()
        path = path if str(path).startswith("/") else "/" + str(path)
        try:
            quote = await self.buyer.quote(path)
            if quote is None:
                self._record("quote_endpoint", {"path": path}, started, True, "not paywalled")
                return self._json(
                    {"path": path, "note": "No 402 returned -- this endpoint is free."}
                )
            self._record(
                "quote_endpoint", {"path": path}, started, True,
                f"quoted ${quote.price_usd:.6f}",
            )
            return self._json(quote.as_dict())
        except Exception as exc:
            self._record("quote_endpoint", {"path": path}, started, False, str(exc))
            return self._json({"error": f"could not quote {path}: {exc}"})

    # --- paid ------------------------------------------------------------
    async def _buy(self, name: str, path: str, args: dict[str, Any]) -> str:
        started = time.time()
        try:
            call = await self.buyer.get_paid(path)
        except Exception as exc:
            kind = type(exc).__name__
            self._record(name, args, started, False, f"{kind}: {exc}")
            return self._json(
                {
                    "error": str(exc),
                    "type": kind,
                    "guidance": (
                        "Do not retry. This is a policy or payment-layer failure, not a "
                        "transient one, and it affects every paid endpoint equally. Work "
                        "with data you already have, or report why you cannot continue."
                    ),
                }
            )

        if getattr(call, "payment_status", "") != "settled":
            self._record(name, args, started, False, f"HTTP {call.status}, not charged")
            return self._json(
                {
                    "path": path,
                    "status": call.status,
                    "charged": False,
                    "note": "Non-2xx response; the seller cancelled the payment, so this "
                    "was free.",
                    "body": call.body,
                }
            )

        spent = float(call.spent_usd)
        self._record(
            name, args, started, True, f"paid ${spent:.6f}",
            paid_usd=spent, transaction=call.transaction,
        )
        payload = call.as_dict(include_body=True)
        self.purchases.append(payload)
        return self._json(payload)

    async def buy_market_snapshot(self) -> str:
        return await self._buy("buy_market_snapshot", "/market/snapshot", {})

    async def buy_market_signals(self) -> str:
        return await self._buy("buy_market_signals", "/market/signal", {})

    async def buy_ohlcv_history(self, symbol: str) -> str:
        symbol = str(symbol or "").strip()
        if not symbol:
            return self._json({"error": "a symbol is required, for example BTC-USD"})
        return await self._buy(
            "buy_ohlcv_history",
            f"/market/ohlcv/{urlquote(symbol, safe='')}",
            {"symbol": symbol},
        )

    # --- reporting -------------------------------------------------------
    def ledger(self) -> dict[str, Any]:
        return {
            "usdcSpent": self.usdc_spent,
            "paidCalls": self.paid_calls,
            "failedCalls": self.failed_calls,
            "capUsd": float(self.buyer.spend_cap_usd),
            "address": self.buyer.address,
            "calls": [c.as_dict() for c in self.calls],
            "purchases": self.purchases,
        }
