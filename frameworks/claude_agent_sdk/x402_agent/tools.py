"""The agent's tool surface: three free tools, three paid ones.

Every paid tool states its price, because that description is the only cost signal
the model gets before deciding to spend. Free tools say "Free." for the same reason.

The descriptions come from `x402_core`, shared verbatim with the LangGraph and
Google ADK agents. That is deliberate: the three agents exist to be compared, and
they stop being comparable the moment their models are shown different text about
what things cost.
"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import quote as urlquote

from claude_agent_sdk import create_sdk_mcp_server, tool

from x402_core import DESCRIPTIONS

from .buyer import PaymentFailed, SpendCapExceeded, X402Buyer
from .telemetry import RunTelemetry, ToolEvent

SERVER_NAME = "x402"


def _text(payload: Any) -> dict[str, Any]:
    body = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"))
    return {"content": [{"type": "text", "text": body}]}


def _error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "is_error": True}


def build_x402_tools(buyer: X402Buyer, telemetry: RunTelemetry) -> tuple[Any, list[str]]:
    """Build the in-process MCP server. Returns (server_config, allowed_tool_names)."""

    def record(
        name: str,
        args: dict[str, Any],
        started: float,
        ok: bool,
        detail: str,
        paid_usd: float = 0.0,
        transaction: str | None = None,
    ) -> None:
        telemetry.record_tool(
            ToolEvent(
                name=name,
                args=args,
                ok=ok,
                detail=detail,
                paid_usd=paid_usd,
                transaction=transaction,
                elapsed_s=round(time.time() - started, 3),
            )
        )

    # --- free ------------------------------------------------------------
    @tool(
        "list_catalog",
        DESCRIPTIONS["list_catalog"],
        {},
    )
    async def list_catalog(args: dict[str, Any]) -> dict[str, Any]:
        started = time.time()
        try:
            data = await buyer.get_free("/catalog")
            record("list_catalog", {}, started, True, "catalogue read")
            return _text(data)
        except Exception as exc:
            record("list_catalog", {}, started, False, str(exc))
            return _error(f"Could not read the catalogue: {exc}")

    @tool(
        "check_budget",
        DESCRIPTIONS["check_budget"],
        {},
    )
    async def check_budget(args: dict[str, Any]) -> dict[str, Any]:
        started = time.time()
        snapshot = buyer.budget_snapshot()
        snapshot["budgetKind"] = "USDC payment budget for buying data (not LLM tokens)"
        record("check_budget", {}, started, True, f"remaining ${snapshot['remainingUsd']:.6f}")
        return _text(snapshot)

    @tool(
        "quote_endpoint",
        DESCRIPTIONS["quote_endpoint"],
        {"path": str},
    )
    async def quote_endpoint(args: dict[str, Any]) -> dict[str, Any]:
        started = time.time()
        path = str(args.get("path") or "").strip()
        if not path.startswith("/"):
            path = "/" + path
        try:
            quote = await buyer.quote(path)
            if quote is None:
                record("quote_endpoint", {"path": path}, started, True, "not paywalled")
                return _text({"path": path, "note": "No 402 returned -- this endpoint is free."})
            record(
                "quote_endpoint",
                {"path": path},
                started,
                True,
                f"quoted ${quote.price_usd:.6f}",
            )
            return _text(quote.as_dict())
        except Exception as exc:
            record("quote_endpoint", {"path": path}, started, False, str(exc))
            return _error(f"Could not quote {path}: {exc}")

    # --- paid ------------------------------------------------------------
    async def _buy(name: str, path: str, args: dict[str, Any]) -> dict[str, Any]:
        started = time.time()
        try:
            call = await buyer.get_paid(path)
        except SpendCapExceeded as exc:
            record(name, args, started, False, f"spend cap: {exc}")
            return _error(
                f"{exc} Do not retry this purchase. Work with the data you already have, "
                "or report that the budget is exhausted."
            )
        except PaymentFailed as exc:
            record(name, args, started, False, f"payment failed: {exc}")
            return _error(
                f"{exc} This is a wallet/facilitator problem at the payment layer, so it "
                "affects EVERY paid endpoint equally. Do not retry this tool and do not try "
                "a different paid tool -- they will all fail the same way and you will only "
                "burn tokens. Stop now and report this as the reason the task cannot be "
                "completed."
            )
        except Exception as exc:
            # AEGL refusals arrive as GovernanceRefused. Matched by class name so
            # tools.py needs no aegl import and works with the layer absent.
            # Must sit in the generic clause, *after* the specific ones, or it
            # would swallow SpendCapExceeded and PaymentFailed.
            if type(exc).__name__ == "GovernanceRefused":
                record(name, args, started, False, f"governance refused: {exc}")
                return _error(
                    f"The economic governance layer refused this purchase. {exc} "
                    "This is a policy decision, not a transient failure: retrying the "
                    "same purchase will be refused identically. Either work with data "
                    "you already have, or report that governance blocked the spend."
                )
            record(name, args, started, False, str(exc))
            return _error(f"Request to {path} failed: {exc}")

        if call.payment_status != "settled":
            record(
                name,
                args,
                started,
                False,
                f"HTTP {call.status}, not charged",
            )
            return _text(
                {
                    "path": path,
                    "status": call.status,
                    "charged": False,
                    "note": "Non-2xx response; the seller cancelled the payment, so this was free.",
                    "body": call.body,
                }
            )

        record(
            name,
            args,
            started,
            True,
            f"paid ${call.spent_usd:.6f}",
            paid_usd=float(call.spent_usd),
            transaction=call.transaction,
        )
        return _text(call.as_dict(include_body=True))

    @tool(
        "buy_market_snapshot",
        DESCRIPTIONS["buy_market_snapshot"],
        {},
    )
    async def buy_market_snapshot(args: dict[str, Any]) -> dict[str, Any]:
        return await _buy("buy_market_snapshot", "/market/snapshot", {})

    @tool(
        "buy_market_signals",
        DESCRIPTIONS["buy_market_signals"],
        {},
    )
    async def buy_market_signals(args: dict[str, Any]) -> dict[str, Any]:
        return await _buy("buy_market_signals", "/market/signal", {})

    @tool(
        "buy_ohlcv_history",
        DESCRIPTIONS["buy_ohlcv_history"],
        {"symbol": str},
    )
    async def buy_ohlcv_history(args: dict[str, Any]) -> dict[str, Any]:
        symbol = str(args.get("symbol") or "").strip()
        if not symbol:
            return _error("A symbol is required, for example BTC-USD.")
        return await _buy(
            "buy_ohlcv_history",
            f"/market/ohlcv/{urlquote(symbol, safe='')}",
            {"symbol": symbol},
        )

    handlers = [
        list_catalog,
        check_budget,
        quote_endpoint,
        buy_market_snapshot,
        buy_market_signals,
        buy_ohlcv_history,
    ]

    server = create_sdk_mcp_server(name=SERVER_NAME, version="1.0.0", tools=handlers)
    names = [
        "list_catalog",
        "check_budget",
        "quote_endpoint",
        "buy_market_snapshot",
        "buy_market_signals",
        "buy_ohlcv_history",
    ]
    allowed = [f"mcp__{SERVER_NAME}__{n}" for n in names]
    return server, allowed
