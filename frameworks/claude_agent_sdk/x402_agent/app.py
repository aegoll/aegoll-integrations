"""Streamlit cockpit for the x402 buyer agent.

Run from the repo root:

    agent-py/.venv/Scripts/streamlit run agent-py/x402_agent/app.py

Two budgets are shown side by side, and they are different kinds of money:

  * **LLM cost (USD)** -- real Anthropic spend on tokens. Capped per run by the
    Agent SDK, and cumulatively by a ledger on disk.
  * **USDC spend (USD)** -- x402 payments on Base Sepolia. Testnet funds from a
    faucet, so it costs nothing real, but the protocol path is identical to
    mainnet.
"""

from __future__ import annotations

import asyncio
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import streamlit as st

# `streamlit run` executes this file as a top-level script, not as a package
# module, so relative imports are unavailable. Put `agent-py/` on the path and
# import absolutely -- this works under both `streamlit run` and `python -m`.
_AGENT_PY_DIR = str(Path(__file__).resolve().parents[1])
if _AGENT_PY_DIR not in sys.path:
    sys.path.insert(0, _AGENT_PY_DIR)

from x402_agent.agent import (  # noqa: E402
    DEFAULT_TASK,
    PreflightError,
    RunSettings,
    build_buyer,
    preflight,
    run_agent,
)
from x402_agent.config import (  # noqa: E402
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_TURNS,
    DEFAULT_MODEL,
    DEFAULT_RUN_BUDGET_USD,
    DEFAULT_TOTAL_BUDGET_USD,
    EXPLORER_TX,
    FAUCET_URL,
    MODEL_CHOICES,
    load_config,
)
from x402_agent.governance import (  # noqa: E402
    AEGOLL_AVAILABLE,
    advisor_catalogue,
    advisor_cost,
    advisor_warning,
    build_layer,
    import_error,
    list_advisors,
    list_policies,
)

# The panels used to ship *inside* the governance layer, as `aegl.ui`. They no longer do:
# the package shed every UI module when it stopped depending on Streamlit (PLAN.md A2), so
# `aegoll` has no `ui` at all and this import could never have succeeded against the
# published package. They live in this repository now, under `cockpit/`, which is where a
# demo surface belongs -- a library that governs payments should not carry a web framework.
if AEGOLL_AVAILABLE:
    try:
        import ui as aegl_ui  # noqa: E402  -- from cockpit/, put on the path by conftest
        import ui_keys as aegl_ui_keys  # noqa: E402
    except ImportError:  # pragma: no cover - the panels are optional, the governance is not
        aegl_ui = None
        aegl_ui_keys = None
else:  # pragma: no cover - exercised by absence
    aegl_ui = None
    aegl_ui_keys = None
from x402_agent.telemetry import (  # noqa: E402
    RunTelemetry,
    remaining_total_budget,
    reset_ledger,
    run_history,
    total_llm_spend_usd,
)

st.set_page_config(page_title="x402 buyer agent", page_icon="🛰", layout="wide")

END = "__end__"
LEDGER = "__ledger__"
GOVERNANCE = "__governance__"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def seller_health(base_url: str) -> tuple[bool, Any]:
    try:
        r = httpx.get(f"{base_url}/health", timeout=3.0)
        r.raise_for_status()
        return True, r.json()
    except Exception as exc:
        return False, str(exc)


def wallet_balances(config, settings) -> tuple[bool, Any]:
    if not config.wallet_configured:
        return False, "BUYER_PRIVATE_KEY is not a valid key."

    async def go():
        buyer = build_buyer(config, settings)
        try:
            return await buyer.usdc_balance(config.seller_address)
        finally:
            await buyer.aclose()

    try:
        return True, asyncio.run(go())
    except Exception as exc:
        return False, str(exc)


def worker(config, settings: RunSettings, telemetry: RunTelemetry, q: "queue.Queue") -> None:
    """Runs the agent on its own event loop, streaming events into `q`."""

    async def go() -> None:
        buyer = build_buyer(config, settings)
        governance = None
        if settings.governance_enabled:
            try:
                governance = build_layer(
                    settings.governance_policy, settings.governance_advisor
                )
                if settings.governance_override:
                    # Journal the bypass beside the refusal it bypasses. An override
                    # that left no trace would make the audit log a record of what
                    # policy *would* have done, not what happened.
                    pre = governance.precheck_run(
                        model=settings.model, budget_usd=settings.run_budget_usd
                    )
                    governance.record_override(pre, seconds_left=0.0)
            except Exception as exc:
                q.put(
                    {
                        "kind": "error",
                        "message": f"AEGL layer failed to start: {exc}",
                    }
                )
        try:
            async for event in run_agent(
                config, settings, buyer, telemetry, governance=governance
            ):
                q.put(event)
        finally:
            if governance is not None:
                # `report()` is the one payload shape the panel reads. This used to
                # hand-build a dict from `vars(event)`, which emitted snake_case
                # keys while the panel expected camelCase -- so every figure on it
                # would have read zero the moment the two drifted.
                q.put({"kind": GOVERNANCE, **governance.report()})
                governance.close()
            q.put(
                {
                    "kind": LEDGER,
                    "calls": [c.as_dict(include_body=True) for c in buyer.calls],
                    "spent_usd": float(buyer.total_spent_usd),
                    "cap_usd": float(buyer.spend_cap_usd),
                    "address": buyer.address,
                }
            )
            await buyer.aclose()

    try:
        asyncio.run(go())
    except Exception as exc:  # pragma: no cover - defensive
        q.put({"kind": "error", "message": f"{type(exc).__name__}: {exc}"})
    finally:
        q.put({"kind": END})


def money(value: float | None, places: int = 6) -> str:
    return f"${(value or 0.0):.{places}f}"


# --------------------------------------------------------------------------
# sidebar controls
# --------------------------------------------------------------------------
config = load_config()

# Re-apply keys typed into this session before any code asks which providers
# are usable. Streamlit reruns the script per interaction, so this has to run
# every time rather than once.
if aegl_ui_keys is not None:
    aegl_ui_keys.apply_session_keys()

st.sidebar.header("Agent controls")

model = st.sidebar.selectbox(
    "Model",
    MODEL_CHOICES,
    index=MODEL_CHOICES.index(DEFAULT_MODEL),
    help="Haiku 4.5 is $1/$5 per million tokens. Sonnet 5 and Opus 5 cost 3-5x more "
    "on output, so the same per-run budget buys far fewer turns.",
)

st.sidebar.subheader("Token spend limits")
run_budget = st.sidebar.number_input(
    "Per-run LLM budget (USD)",
    min_value=0.001,
    max_value=1.0,
    value=DEFAULT_RUN_BUDGET_USD,
    step=0.005,
    format="%.3f",
    help="Passed to the Agent SDK as max_budget_usd. The run stops when the estimated "
    "cost reaches this.",
)
total_budget = st.sidebar.number_input(
    "Lifetime LLM cap (USD)",
    min_value=0.01,
    max_value=25.0,
    value=DEFAULT_TOTAL_BUDGET_USD,
    step=0.05,
    format="%.2f",
    help="Cumulative across every run, journalled to agent-py/.spend-ledger.json so it "
    "survives restarts.",
)
hard_stop = st.sidebar.toggle(
    "Hard stop at the lifetime cap",
    value=True,
    help="On: the run is refused before it starts once the lifetime cap is reached. "
    "Off: only the per-run budget applies.",
)

st.sidebar.subheader("Loop and retries")
max_turns = st.sidebar.slider(
    "Max turns",
    min_value=2,
    max_value=40,
    value=DEFAULT_MAX_TURNS,
    help="Hard ceiling on agentic round trips, independent of cost.",
)
max_retries = st.sidebar.slider(
    "API retries on 429/5xx",
    min_value=0,
    max_value=10,
    value=DEFAULT_MAX_RETRIES,
    help="CLAUDE_CODE_MAX_RETRIES. Retries use exponential backoff and each attempt "
    "that reaches the model is billed.",
)
timeout_ms = st.sidebar.select_slider(
    "Per-request timeout (ms)",
    options=[30_000, 60_000, 120_000, 300_000, 600_000],
    value=120_000,
    help="API_TIMEOUT_MS.",
)

st.sidebar.subheader("x402 payment cap")
usdc_cap = st.sidebar.number_input(
    "USDC spend cap per run (USD)",
    min_value=0.001,
    max_value=1.0,
    value=float(config.usdc_cap_usd),
    step=0.005,
    format="%.3f",
    help="Testnet USDC. The buyer refuses to sign a payment that would exceed what is "
    "left of this.",
)

st.sidebar.subheader("AEGL governance layer")
if AEGL_AVAILABLE:
    governance_on = st.sidebar.toggle(
        "Route spending through AEGL",
        value=True,
        help="On: both channels need a decision before money moves -- internal (LLM "
        "tokens on your API key) and external (USDC via x402). Off: the agent runs "
        "with only its own two hard-coded caps, as it did before.",
    )
    _policies = list_policies()
    governance_policy = st.sidebar.selectbox(
        "Policy bundle",
        _policies,
        index=_policies.index("default") if "default" in _policies else 0,
        disabled=not governance_on,
        help="Envelopes, weights and rules. `strict` is a tighter variant for A/B.",
    ) if _policies else None

    # --- Phase 2: BYOK advisor ---------------------------------------------
    _advisors = list_advisors()
    _labels = ["none (deterministic only)"] + [
        f"{p} / {m}  (~${advisor_cost(m):.5f})" for p, m in _advisors
    ]
    _pick = st.sidebar.selectbox(
        "Advisor model (BYOK)",
        _labels,
        index=0,
        disabled=not governance_on,
        help="Consulted only when the EIAP says the exposure justifies the cost. "
        "The advisor can make a verdict stricter, never more permissive.",
    )
    advisor_spec = None if _pick.startswith("none") else _advisors[_labels.index(_pick) - 1]
    if advisor_spec:
        _warn = advisor_warning(advisor_spec[1])
        if _warn:
            # Measured, not guessed -- see the aegoll repository's docs/eval.md.
            st.sidebar.warning(f"**Not recommended.** {_warn}")
        _c = advisor_cost(advisor_spec[1])
        st.sidebar.caption(
            f"~${_c:.6f} per analysis → consulted only above ~${_c / 0.05:.4f} of "
            "exposure. Below that, asking destroys value and the layer refuses."
        )

    # Key entry lives in its own module. Rendered after the model picker so the
    # dropdown above reflects any key added on the previous rerun.
    if aegl_ui_keys is not None:
        aegl_ui_keys.render(advisor_catalogue())
else:
    governance_on = False
    governance_policy = None
    advisor_spec = None
    st.sidebar.warning(f"aegoll not installed: {import_error()}")

st.sidebar.divider()
spent_total = total_llm_spend_usd()
st.sidebar.metric("Lifetime LLM spend", money(spent_total, 4))
st.sidebar.progress(
    min(1.0, spent_total / total_budget if total_budget else 0.0),
    text=f"{money(remaining_total_budget(total_budget), 4)} left of {money(total_budget, 2)}",
)
if st.sidebar.button("Reset spend ledger", help="Clears the journalled lifetime total."):
    reset_ledger()
    st.rerun()

settings = RunSettings(
    model=model,
    run_budget_usd=float(run_budget),
    total_budget_usd=float(total_budget),
    max_turns=int(max_turns),
    max_retries=int(max_retries),
    api_timeout_ms=int(timeout_ms),
    usdc_cap_usd=float(usdc_cap),
    task=DEFAULT_TASK,
    hard_stop_on_total_budget=bool(hard_stop),
    governance_enabled=bool(governance_on),
    governance_policy=governance_policy,
    governance_advisor=advisor_spec,
)


# --------------------------------------------------------------------------
# header + preflight
# --------------------------------------------------------------------------
st.title("x402 buyer agent")
st.caption(
    "A Claude Agent SDK agent whose only capability is buying market data over the x402 "
    "protocol. Every figure it cites had to be paid for in USDC on Base Sepolia."
)

health_ok, health = seller_health(config.data_api_url)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Seller", "up" if health_ok else "down", config.data_api_url.replace("http://", ""))
c2.metric("Anthropic key", "set" if config.anthropic_api_key else "missing")
c3.metric("Wallet key", "set" if config.wallet_configured else "missing")
c4.metric(
    "AEGL layer",
    "on" if governance_on else "off",
    (governance_policy or "-") if governance_on else "ungoverned",
)

if not health_ok:
    st.error(
        f"The seller is not reachable at {config.data_api_url}. Start it from the repo root "
        f"with `npm run server` (it listens on port 4021). Detail: {health}"
    )

if not config.wallet_configured:
    st.warning(
        "**No buyer wallet yet.** The repo ships `BUYER_PRIVATE_KEY=0x` as a stub, so no "
        "payment can be signed. To get testnet funds:\n\n"
        "1. From the repo root, run `npm run wallet:new` and paste the printed "
        "`BUYER_PRIVATE_KEY=` line into `.env`.\n"
        "2. Set `SELLER_ADDRESS` in `.env` to a real address (reusing the buyer address is "
        "fine — a self-transfer still settles on-chain and produces a real receipt).\n"
        f"3. Open {FAUCET_URL}, choose **Base Sepolia**, paste the buyer address, and request "
        "USDC.\n"
        "4. Confirm it arrived with `npm run wallet:balance` (or the button below).\n\n"
        "`ETH: 0` is expected and fine — under the `exact` scheme the buyer only signs "
        "off-chain and the facilitator pays the gas."
    )
else:
    with st.expander("Wallet", expanded=False):
        if st.button("Check balances on Base Sepolia"):
            ok, balances = wallet_balances(config, settings)
            if ok:
                st.session_state["balances"] = balances
            else:
                st.error(f"Balance check failed: {balances}")
        balances = st.session_state.get("balances")
        if balances:
            seller_info = balances.get("seller")
            b1, b2, b3 = st.columns(3)
            b1.metric("Buyer USDC", f"{balances['usdc']:.6f}")
            b2.metric("Buyer ETH", f"{balances['eth']:.6f}")
            if seller_info:
                b3.metric("Seller USDC", f"{seller_info['usdc']:.6f}")
            st.caption(f"buyer `{balances['address']}`")
            if seller_info:
                st.caption(f"seller `{seller_info['address']}`")
                if seller_info["isSelfTransfer"]:
                    st.warning(
                        "`SELLER_ADDRESS` equals the buyer address, so every payment is a "
                        "**self-transfer**. Settlement is real and produces an on-chain "
                        "receipt, but the buyer balance will not move because the money goes "
                        "back to the same wallet. Set a different `SELLER_ADDRESS` and restart "
                        "the server to watch the balance drop."
                    )
            if balances["usdc"] == 0:
                st.warning(
                    f"The wallet holds no test USDC, so the facilitator will reject payment "
                    f"with `invalid_exact_evm_insufficient_balance`. Fund it at {FAUCET_URL} "
                    "(select Base Sepolia)."
                )

st.divider()

# --------------------------------------------------------------------------
# task + run
# --------------------------------------------------------------------------
task = st.text_area("Task for the agent", value=DEFAULT_TASK, height=110)
settings.task = task

warnings: list[str] = []
blocked: str | None = None
try:
    warnings = preflight(config, settings)
except PreflightError as exc:
    blocked = str(exc)

for warning in warnings:
    st.info(warning)
if blocked:
    st.error(f"Run blocked by a guardrail: {blocked}")

run_clicked = st.button(
    "Run agent",
    type="primary",
    disabled=bool(blocked) or not health_ok or not task.strip(),
)


OVERRIDE_WINDOW_S = 10.0


@st.fragment(run_every="1s")
def override_gate() -> None:
    """Alert + countdown when AEGL refuses a run before it starts.

    Blocking is the default and the safe path: doing nothing leaves the run
    refused. The override exists because a human who understands the refusal
    should be able to proceed -- but it expires, so walking away can never leave
    a permanently-armed bypass.
    """
    block = st.session_state.get("gov_block")
    if not block:
        return

    remaining = OVERRIDE_WINDOW_S - (time.time() - block["at"])

    if remaining <= 0:
        st.error(
            f"**Run blocked by AEGL — {block['verdict']}.** "
            f"The {block['engine']} engine refused the token budget "
            f"(rule `{block['matched_rule']}`"
            + (f", binding `{block['binding']}`" if block.get("binding") else "")
            + "). The override window has expired, so the run did not start. "
            "Lower the per-run budget, switch policy bundle, or press **Run agent** "
            "again for a fresh window."
        )
        with st.expander("Why it was refused"):
            for reason in block["reasons"]:
                st.caption(reason)
        return

    st.error(
        f"**Run blocked by AEGL — {block['verdict']}.** The **{block['engine']} "
        f"engine** refused this run's ${block['budget_usd']:.4f} token budget "
        f"(rule `{block['matched_rule']}`"
        + (f", binding envelope `{block['binding']}`" if block.get("binding") else "")
        + ")."
    )
    st.progress(
        max(0.0, min(1.0, remaining / OVERRIDE_WINDOW_S)),
        text=f"Override available for {remaining:.0f}s — doing nothing keeps it blocked",
    )
    with st.expander("Why it was refused", expanded=True):
        for reason in block["reasons"]:
            st.caption(reason)

    left, right = st.columns([1, 3])
    if left.button(
        f"Allow anyway ({remaining:.0f}s)",
        type="secondary",
        help="Bypasses the governance decision for this run only. The refusal stays "
        "in the audit log, and the override is journalled beside it.",
    ):
        st.session_state["gov_override_go"] = True
        st.session_state["gov_block"] = None
        st.rerun(scope="app")
    right.caption(
        "**Dangerous.** This spends real tokens against a budget the policy says you "
        "do not have. The Agent SDK's own `max_budget_usd` still applies as a "
        "backstop, but the envelope AEGL was protecting will be exceeded."
    )


live_metrics = st.container()
transcript_box = st.container()
timeline_box = st.container()

# An override click arms exactly one run, then disarms itself.
override_go = bool(st.session_state.pop("gov_override_go", False))
settings.governance_override = override_go

run_now = override_go
if run_clicked:
    st.session_state["gov_block"] = None
    run_now = True
    # Ask AEGL up front whether this run may spend its token budget. This is a
    # free, unjournalled preview -- only the real attempt inside the worker is
    # recorded -- so a user who reads the warning and walks away leaves no
    # phantom refusal in the audit trail.
    if settings.governance_enabled and AEGL_AVAILABLE:
        try:
            # advisor=None on the probe: the pre-check is a deterministic
            # preview, and paying a model to preview a refusal would be spending
            # to find out whether spending is allowed.
            _probe = build_layer(settings.governance_policy, None)
            try:
                _pre = _probe.precheck_run(
                    model=settings.model, budget_usd=settings.run_budget_usd
                )
            finally:
                _probe.close()
            if not _pre["allowed"]:
                st.session_state["gov_block"] = {**_pre, "at": time.time()}
                run_now = False
        except Exception as exc:
            st.warning(f"AEGL pre-check failed, running ungoverned: {exc}")

override_gate()

if run_now:
    telemetry = RunTelemetry(model=settings.model, run_budget_usd=settings.run_budget_usd)
    events: "queue.Queue" = queue.Queue()
    thread = threading.Thread(
        target=worker, args=(config, settings, telemetry, events), daemon=True
    )
    thread.start()

    with live_metrics:
        m_cols = st.columns(4)
        m_turns = m_cols[0].empty()
        m_tokens = m_cols[1].empty()
        m_paid = m_cols[2].empty()
        m_tools = m_cols[3].empty()
    with transcript_box:
        st.subheader("Agent output")
        transcript_ph = st.empty()
    with timeline_box:
        st.subheader("Tool timeline")
        timeline_ph = st.empty()

    transcript: list[str] = []
    ledger_payload: dict[str, Any] = {}
    governance_payload: dict[str, Any] = {}
    running = True

    def paint() -> None:
        totals = telemetry.step_token_totals
        m_turns.metric("Steps", telemetry.steps)
        m_tokens.metric(
            "Tokens in/out",
            f"{totals['input_tokens']:,}/{totals['output_tokens']:,}",
            f"cache read {totals['cache_read_input_tokens']:,}",
        )
        m_paid.metric("USDC spent", money(telemetry.usdc_spent), f"{telemetry.paid_calls} paid")
        m_tools.metric(
            "Tool calls",
            len(telemetry.tool_events),
            f"{telemetry.failed_tools} failed" if telemetry.failed_tools else "all ok",
        )
        transcript_ph.markdown("\n\n".join(transcript) or "_waiting for the first token…_")
        rows = [
            {
                "tool": e.name,
                "args": ", ".join(f"{k}={v}" for k, v in e.args.items()) or "-",
                "ok": "yes" if e.ok else "no",
                "paid USD": f"{e.paid_usd:.6f}" if e.paid_usd else "-",
                "seconds": f"{e.elapsed_s:.2f}",
                "detail": e.detail,
            }
            for e in telemetry.tool_events
        ]
        if rows:
            timeline_ph.dataframe(rows, width="stretch", hide_index=True)

    paint()
    while running:
        try:
            event = events.get(timeout=0.25)
        except queue.Empty:
            paint()
            continue

        kind = event.get("kind")
        if kind == END:
            running = False
        elif kind == LEDGER:
            ledger_payload = event
        elif kind == GOVERNANCE:
            governance_payload = event
        elif kind == "governance_override":
            transcript.append(
                f"> ⚠️ **Human override** — proceeding despite AEGL "
                f"`{event['verdict']}` from the {event['engine']} engine."
            )
        elif kind == "governance":
            ev = event["event"]
            transcript.append(
                f"> **AEGL / {event['channel']}** — `{ev['verdict']}` "
                f"({ev.get('matchedRule')})"
            )
        elif kind == "governance_stop":
            transcript.append(
                f"> ⛔ **AEGL stopped the run** — {event['detail'].get('reason', '')}"
            )
        elif kind == "text":
            transcript.append(event["text"])
        elif kind == "error":
            transcript.append(f"> **error:** {event['message']}")
        paint()

    thread.join(timeout=5)
    telemetry.finished_at = telemetry.finished_at or time.time()

    st.session_state["last_run"] = {
        "telemetry": telemetry,
        "transcript": transcript,
        "ledger": ledger_payload,
        "governance": governance_payload,
        "settings": settings,
    }
    st.rerun()


# --------------------------------------------------------------------------
# results
# --------------------------------------------------------------------------
def render_last_run(last: dict[str, Any]) -> None:
    telemetry: RunTelemetry = last["telemetry"]
    ledger = last["ledger"] or {}
    totals = telemetry.token_totals

    st.divider()
    st.subheader("Last run")

    if telemetry.budget_stopped:
        st.warning(
            f"The run hit its per-run LLM budget of {money(telemetry.run_budget_usd, 4)} and "
            "was stopped by the Agent SDK. The answer may be incomplete."
        )
    if telemetry.error:
        st.error(f"Run ended with an error: {telemetry.error}")

    k = st.columns(5)
    k[0].metric(
        "LLM cost (est.)",
        money(telemetry.llm_cost_usd, 6),
        f"{telemetry.budget_used_pct:.0f}% of run budget",
    )
    # The buyer's own ledger is authoritative for USDC; the tool-event sum is a mirror.
    usdc_spent = ledger.get("spent_usd", telemetry.usdc_spent)
    k[1].metric("USDC spent", money(usdc_spent), f"{telemetry.paid_calls} paid calls")
    k[2].metric("Turns", telemetry.num_turns if telemetry.num_turns is not None else "-")
    k[3].metric("Tokens in/out", f"{totals['input_tokens']:,}/{totals['output_tokens']:,}")
    k[4].metric("Wall clock", f"{telemetry.wall_clock_s:.1f}s")

    st.caption(
        "LLM cost is a client-side estimate from the Agent SDK's bundled price table, not "
        "authoritative billing. USDC spend is testnet money on Base Sepolia."
    )

    tabs = st.tabs(
        [
            "Answer",
            "AEGL layer",
            "Data purchased",
            "x402 receipts",
            "Cost & tokens",
            "Tool timeline",
            "History",
        ]
    )

    with tabs[0]:
        text = "\n\n".join(last["transcript"])
        st.markdown(text or "_no output_")

    with tabs[1]:
        # The panel ships with AEGL. Same `render()` the other cockpits call.
        if aegl_ui is not None:
            aegl_ui.render(last.get("governance"))
        else:
            st.info("AEGL is not installed, so there is nothing to govern with.")

    with tabs[2]:
        calls = ledger.get("calls") or []
        if not calls:
            st.info("The agent bought nothing this run.")
        for call in calls:
            data = call.get("data") or {}
            st.markdown(f"**`{call['path']}`** — paid {money(call['spentUsd'])}")
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

    with tabs[3]:
        calls = ledger.get("calls") or []
        if calls:
            st.dataframe(
                [
                    {
                        "path": c["path"],
                        "paid USD": f"{c['spentUsd']:.6f}",
                        "status": c["paymentStatus"],
                        "tx": c.get("transaction") or "-",
                    }
                    for c in calls
                ],
                width="stretch",
                hide_index=True,
            )
            for c in calls:
                if c.get("transaction"):
                    st.markdown(f"- [{c['transaction'][:18]}…]({EXPLORER_TX}{c['transaction']})")
        st.metric(
            "USDC spent / cap",
            f"{money(ledger.get('spent_usd'))} / {money(ledger.get('cap_usd'))}",
        )
        if ledger.get("address"):
            st.caption(f"buyer `{ledger['address']}`")

    with tabs[4]:
        st.write("**Per-step token usage** (deduplicated by message id)")
        st.dataframe(
            [
                {"message": mid[:20], **counts}
                for mid, counts in telemetry.assistant_steps.items()
            ]
            or [{"message": "-", "input_tokens": 0, "output_tokens": 0}],
            width="stretch",
            hide_index=True,
        )
        st.write(f"**Totals** — source: `{telemetry.token_source}`")
        st.json(totals)
        st.caption(
            "The per-step table above deduplicates by message id (parallel tool calls share "
            "one id with identical usage) and is only a partial view — not every assistant "
            "message carries usage. The totals use the result message instead."
        )
        if telemetry.model_usage:
            st.write("**Per-model cost** (includes any subagent activity)")
            st.json(telemetry.model_usage)
        if telemetry.usage:
            st.write("**Result-message usage** (top-level loop only)")
            st.json(telemetry.usage)
        st.write("**Guardrails in force this run**")
        s: RunSettings = last["settings"]
        st.json(
            {
                "model": s.model,
                "max_budget_usd": s.run_budget_usd,
                "max_turns": s.max_turns,
                "lifetime_cap_usd": s.total_budget_usd,
                "hard_stop_on_total_budget": s.hard_stop_on_total_budget,
                "CLAUDE_CODE_MAX_RETRIES": s.max_retries,
                "API_TIMEOUT_MS": s.api_timeout_ms,
                "usdc_cap_usd": s.usdc_cap_usd,
                "result_subtype": telemetry.subtype,
            }
        )

    with tabs[5]:
        st.dataframe(
            [
                {
                    "tool": e.name,
                    "args": ", ".join(f"{k}={v}" for k, v in e.args.items()) or "-",
                    "ok": "yes" if e.ok else "no",
                    "paid USD": f"{e.paid_usd:.6f}" if e.paid_usd else "-",
                    "seconds": f"{e.elapsed_s:.2f}",
                    "detail": e.detail,
                }
                for e in telemetry.tool_events
            ]
            or [{"tool": "-", "detail": "no tool calls"}],
            width="stretch",
            hide_index=True,
        )

    with tabs[6]:
        history = run_history()
        if not history:
            st.info("No runs journalled yet.")
        else:
            st.dataframe(
                [
                    {
                        "when": time.strftime("%H:%M:%S", time.localtime(r["at"])),
                        "model": r["model"],
                        "LLM USD": f"{r['llm_cost_usd']:.6f}",
                        "USDC USD": f"{r['usdc_spent']:.6f}",
                        "paid calls": r["paid_calls"],
                        "turns": r["turns"],
                        "in": (r.get("tokens") or {}).get("input_tokens"),
                        "out": (r.get("tokens") or {}).get("output_tokens"),
                        "budget stop": r.get("budget_stopped"),
                        "error": r.get("error") or "-",
                    }
                    for r in history
                ],
                width="stretch",
                hide_index=True,
            )


_last = st.session_state.get("last_run")
if _last:
    render_last_run(_last)
