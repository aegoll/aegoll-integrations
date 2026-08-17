"""Streamlit components shared by every agent cockpit.

Nothing here knows which framework it is rendering. Each panel takes plain data --
the wallet config, a telemetry dict, an x402 ledger -- so the same code serves
LangGraph, ADK and anything added later.

Keeping these shared is not only about duplication: four cockpits that drift into
four dialects would make the agents look different when the only real difference
is the harness.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

EXPLORER_TX = "https://sepolia.basescan.org/tx/"
FAUCET_URL = "https://faucet.circle.com"


def money(value: float | None, places: int = 6) -> str:
    return f"${(value or 0.0):.{places}f}"


# --- status ---------------------------------------------------------------


def seller_status(base_url: str) -> tuple[bool, Any]:
    import httpx  # noqa: PLC0415

    try:
        response = httpx.get(f"{base_url}/health", timeout=3.0)
        response.raise_for_status()
        return True, response.json()
    except Exception as exc:
        return False, str(exc)


def header(
    *,
    title: str,
    framework: str,
    provider: str,
    caption: str,
    seller_url: str,
    key_present: bool,
    key_name: str,
) -> bool:
    """Title plus the four facts that decide whether a run can even start."""
    st.title(title)
    st.caption(caption)

    ok, detail = seller_status(seller_url)
    cols = st.columns(4)
    cols[0].metric("Framework", framework)
    cols[1].metric("Provider", provider, key_name if key_present else "key missing")
    cols[2].metric("Seller", "up" if ok else "down", seller_url.replace("http://", ""))
    cols[3].metric("Network", "Base Sepolia", "eip155:84532")

    if not ok:
        st.error(
            f"The seller is not reachable at {seller_url}. Start it from the repo root "
            f"with `npm run server`. Detail: {detail}"
        )
    if not key_present:
        st.error(
            f"`{key_name}` is not set in the repo-root `.env`. The agent cannot call "
            "its model without it."
        )
    return ok and key_present


def wallet_panel(config: Any) -> None:
    """Buyer and seller balances, with the self-transfer trap called out."""
    with st.expander("Wallet", expanded=False):
        if st.button("Check balances on Base Sepolia", key="ck_balances"):
            st.session_state["ck_balances_data"] = _read_balances(config)

        balances = st.session_state.get("ck_balances_data")
        if isinstance(balances, str):
            st.error(balances)
            return
        if not balances:
            st.caption("Not checked yet.")
            return

        seller = balances.get("seller") or {}
        cols = st.columns(3)
        cols[0].metric("Buyer USDC", f"{balances['usdc']:.6f}")
        cols[1].metric("Buyer ETH", f"{balances['eth']:.6f}")
        if seller:
            cols[2].metric("Seller USDC", f"{seller.get('usdc', 0):.6f}")

        st.caption(f"buyer `{balances['address']}`")
        if seller:
            st.caption(f"seller `{seller.get('address')}`")
            if seller.get("isSelfTransfer"):
                st.warning(
                    "`SELLER_ADDRESS` equals the buyer address, so payments are "
                    "**self-transfers**. They settle for real and produce an on-chain "
                    "receipt, but the buyer balance will not move."
                )
        if balances["usdc"] == 0:
            st.warning(
                f"No test USDC. The facilitator will reject payment with "
                f"`invalid_exact_evm_insufficient_balance`. Fund at {FAUCET_URL} "
                "(Base Sepolia)."
            )
        st.caption(
            "`ETH: 0` is correct — under the `exact` scheme the buyer only signs "
            "off-chain and the facilitator pays the gas."
        )


def _read_balances(config: Any) -> Any:
    import asyncio  # noqa: PLC0415

    from x402_core import build_buyer  # noqa: PLC0415

    async def go() -> Any:
        buyer = build_buyer(config)
        try:
            return await buyer.usdc_balance(config.seller_address)
        finally:
            await buyer.aclose()

    try:
        return asyncio.run(go())
    except Exception as exc:
        return f"Balance check failed: {exc}"


# --- live run -------------------------------------------------------------


def live_metrics(container: Any) -> dict[str, Any]:
    """Placeholders updated as the run streams."""
    with container:
        cols = st.columns(4)
        return {
            "steps": cols[0].empty(),
            "tokens": cols[1].empty(),
            "usdc": cols[2].empty(),
            "tools": cols[3].empty(),
        }


def paint_live(
    slots: dict[str, Any],
    *,
    steps: int,
    tool_calls: int,
    usdc: float,
    paid: int,
    elapsed: float,
) -> None:
    slots["steps"].metric("Steps", steps, f"{elapsed:.0f}s")
    slots["tokens"].metric("Tool calls", tool_calls)
    slots["usdc"].metric("USDC spent", money(usdc), f"{paid} paid")
    slots["tools"].metric("Status", "running")


# --- results --------------------------------------------------------------


def telemetry_metrics(telemetry: dict[str, Any]) -> None:
    x402 = telemetry.get("x402") or {}
    cols = st.columns(5)
    cols[0].metric("LLM cost", money(telemetry.get("llmCostUsd")))
    cols[1].metric(
        "USDC spent",
        money(x402.get("usdcSpent")),
        f"{x402.get('paidCalls', 0)} paid calls",
    )
    cols[2].metric(
        "Tokens in/out",
        f"{telemetry.get('inputTokens', 0):,}/{telemetry.get('outputTokens', 0):,}",
    )
    cols[3].metric(
        "Steps / tools",
        f"{telemetry.get('steps', 0)} / {telemetry.get('toolCalls', 0)}",
    )
    cols[4].metric("Wall clock", f"{telemetry.get('wallClockS', 0)}s")

    st.caption(
        "LLM cost is computed from a local price table, not billed usage. USDC spend "
        "is testnet money on Base Sepolia."
    )
    if telemetry.get("error"):
        st.error(f"Run ended with an error: {telemetry['error']}")


def answer_panel(telemetry: dict[str, Any]) -> None:
    st.markdown(telemetry.get("answer") or "_no output_")


def tool_timeline(x402: dict[str, Any]) -> None:
    calls = x402.get("calls") or []
    if not calls:
        st.info("No tool calls.")
        return
    st.dataframe(
        [
            {
                "tool": c["tool"],
                "args": ", ".join(f"{k}={v}" for k, v in (c.get("args") or {}).items()) or "-",
                "ok": "yes" if c["ok"] else "no",
                "paid USD": f"{c['paidUsd']:.6f}" if c["paidUsd"] else "-",
                "seconds": c["seconds"],
                "detail": c["detail"],
            }
            for c in calls
        ],
        width="stretch",
        hide_index=True,
    )


def receipts_panel(x402: dict[str, Any]) -> None:
    paid = [c for c in (x402.get("calls") or []) if c.get("paidUsd")]
    if not paid:
        st.info("The agent bought nothing this run.")
    else:
        st.dataframe(
            [
                {
                    "tool": c["tool"],
                    "paid USD": f"{c['paidUsd']:.6f}",
                    "tx": (c.get("transaction") or "-")[:22],
                }
                for c in paid
            ],
            width="stretch",
            hide_index=True,
        )
        for c in paid:
            if c.get("transaction"):
                st.markdown(
                    f"- [{c['transaction'][:18]}…]({EXPLORER_TX}{c['transaction']})"
                )
    st.metric(
        "USDC spent / cap",
        f"{money(x402.get('usdcSpent'))} / {money(x402.get('capUsd'))}",
    )
    if x402.get("address"):
        st.caption(f"buyer `{x402['address']}`")


def purchases_panel(x402: dict[str, Any]) -> None:
    """The actual data the agent paid for."""
    purchases = x402.get("purchases") or []
    if not purchases:
        st.info("Nothing purchased.")
        return
    for purchase in purchases:
        data = purchase.get("data") or {}
        st.markdown(f"**`{purchase['path']}`** — paid {money(purchase['spentUsd'])}")
        if "quotes" in data:
            st.dataframe(data["quotes"], width="stretch", hide_index=True)
        elif "signals" in data:
            st.dataframe(data["signals"], width="stretch", hide_index=True)
        elif "candles" in data:
            candles = data["candles"]
            st.dataframe(candles, width="stretch", hide_index=True)
            closes = [c.get("c") for c in candles if isinstance(c, dict)]
            if len(closes) > 1:
                st.line_chart({"close": closes})
        else:
            st.json(data, expanded=False)


def history_panel(limit: int = 25) -> None:
    from x402_core import run_history  # noqa: PLC0415

    runs = run_history(limit)
    if not runs:
        st.info("No runs journalled yet.")
        return
    import time as _time  # noqa: PLC0415

    st.dataframe(
        [
            {
                "when": _time.strftime("%H:%M:%S", _time.localtime(r.get("at", 0))),
                "framework": r.get("framework"),
                "provider": r.get("provider"),
                "model": r.get("model"),
                "LLM USD": f"{r.get('llmCostUsd', 0):.6f}",
                "USDC": f"{(r.get('x402') or {}).get('usdcSpent', 0):.6f}",
                "steps": r.get("steps"),
                "tools": r.get("toolCalls"),
                "error": (r.get("error") or "-")[:40],
            }
            for r in runs
        ],
        width="stretch",
        hide_index=True,
    )
    st.caption(
        "Shared across every agent in `agents/`, so frameworks can be compared "
        "directly on the same task."
    )
