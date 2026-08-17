"""Build a complete cockpit from any conforming agent module.

The contract an agent must satisfy is deliberately tiny:

    FRAMEWORK: str
    PROVIDER: str
    DEFAULT_MODEL: str
    MODELS: tuple[str, ...]
    async def run(task, model, max_steps, config, **kw) -> AsyncIterator[dict]

Anything meeting that gets a full UI -- wallet, run controls, live transcript,
tool timeline, receipts, purchased data, history -- in one call. Which is the same
argument the governance layer makes: if a capability is truly framework-neutral,
adding it to a new framework should be a line, not a project.
"""

from __future__ import annotations

import time
from typing import Any, Callable

import streamlit as st

from . import governance as gov_shim
from . import panels
from .runner import stream_agent


def governance_sidebar() -> dict[str, Any]:
    """The AEGL controls. Returns what `build_cockpit` needs to construct a run.

    Off by default. Turning it on gives this framework a **cost ceiling it does
    not otherwise have** — `max_steps` above counts steps, and a step is not a
    dollar.
    """
    st.sidebar.divider()
    st.sidebar.subheader("AEGL governance")

    if not gov_shim.available():
        st.sidebar.caption(f"AEGL is not importable: {gov_shim.import_error()}")
        return {"enabled": False}

    # Before anything reads a key: Streamlit reruns the script per interaction.
    gov_shim.apply_session_keys()
    gov_shim.render_keys()

    enabled = st.sidebar.toggle(
        "Route spending through AEGL",
        value=False,
        help="Both channels start needing a decision: the run's token budget "
        "(internal) and every x402 purchase (external).",
    )
    if not enabled:
        return {"enabled": False}

    bundles = gov_shim.policies()
    policy = st.sidebar.selectbox("Policy bundle", bundles, index=0) if bundles else None

    budget = st.sidebar.number_input(
        "Token budget for this run (USD)",
        value=0.03, min_value=0.0, max_value=1.0, step=0.01, format="%.4f",
        help="AEGL authorizes this before the run starts and enforces it "
        "mid-run. Above the bundle's per-transaction envelope ($0.04 in "
        "`default`) the run is refused rather than clamped.",
    )

    pairs = gov_shim.advisors()
    labels = ["none (deterministic only)"] + [
        f"{p} / {m}  (~${gov_shim.advisor_cost(m):.5f})" for p, m in pairs
    ]
    picked = st.sidebar.selectbox(
        "Advisor model (BYOK)", labels, index=0,
        help="A second opinion, consulted only when the EIAP gate agrees the "
        "exposure justifies the cost. It can only tighten a verdict, never widen "
        "one.",
    )
    advisor = None if picked.startswith("none") else pairs[labels.index(picked) - 1]
    if advisor:
        warning = gov_shim.advisor_warning(advisor[1])
        if warning:
            # Measured, not guessed -- see aegl/EVAL.md.
            st.sidebar.warning(f"**Not recommended.** {warning}")

    return {"enabled": True, "policy": policy, "budget": float(budget), "advisor": advisor}


def build_cockpit(
    module: Any,
    *,
    title: str,
    caption: str,
    key_name: str,
    key_present: Callable[[Any], bool],
    provider_options: dict[str, tuple[str, ...]] | None = None,
    extra_sidebar: Callable[[], dict[str, Any]] | None = None,
) -> None:
    """Render the whole app. Call once from an agent's `app.py`."""
    from x402_core import DEFAULT_TASK, load_wallet_config  # noqa: PLC0415

    config = load_wallet_config()

    # --- sidebar -------------------------------------------------------
    st.sidebar.header("Agent controls")

    provider = module.PROVIDER
    models = list(module.MODELS)
    if provider_options:
        provider = st.sidebar.selectbox(
            "Provider",
            list(provider_options),
            index=list(provider_options).index(module.PROVIDER)
            if module.PROVIDER in provider_options
            else 0,
            help="This framework is provider-agnostic, so the harness can be driven "
            "by a different model without changing the agent.",
        )
        models = list(provider_options[provider])

    model = st.sidebar.selectbox("Model", models, index=0)

    max_steps = st.sidebar.slider(
        "Max steps",
        min_value=2,
        max_value=30,
        value=12,
        help="A step ceiling, not a cost ceiling. Neither LangGraph nor Google ADK "
        "ships a spend limit, so without AEGL the only money guards are this and "
        "the x402 cap below -- and a step is not a dollar.",
    )

    st.sidebar.subheader("x402 payment cap")
    st.sidebar.metric("USDC cap per run", panels.money(float(config.usdc_cap_usd)))
    st.sidebar.caption(
        "Set by `AGENT_SPEND_CAP_USD` in the repo-root `.env`. The buyer refuses to "
        "sign a payment that would exceed what is left of it."
    )

    extra: dict[str, Any] = {}
    if extra_sidebar is not None:
        extra = extra_sidebar() or {}

    gov_choice = governance_sidebar()

    st.sidebar.divider()
    from x402_core import total_spend_usd  # noqa: PLC0415

    st.sidebar.metric("Lifetime spend, all agents", panels.money(total_spend_usd(), 4))
    st.sidebar.caption(
        "Shared ledger across every agent in `agents/`, so runs stay comparable."
    )

    # --- header --------------------------------------------------------
    ready = panels.header(
        title=title,
        framework=module.FRAMEWORK,
        provider=provider,
        caption=caption,
        seller_url=config.data_api_url,
        key_present=key_present(config),
        key_name=key_name,
    )
    panels.wallet_panel(config)

    st.divider()
    task = st.text_area("Task for the agent", value=DEFAULT_TASK, height=110)
    run_clicked = st.button(
        "Run agent", type="primary", disabled=not ready or not task.strip()
    )

    live_area = st.container()
    transcript_area = st.container()

    # --- run -----------------------------------------------------------
    if run_clicked:
        kwargs: dict[str, Any] = {
            "task": task,
            "model": model,
            "max_steps": int(max_steps),
            "config": config,
            **extra,
        }
        if provider_options:
            kwargs["provider"] = provider

        # AEGL is constructed here, in the host, and handed to the agent. The
        # agent never imports it. `Store` opens its sqlite connection with
        # `check_same_thread=False`, so the worker thread may use a governor
        # built here -- access is sequential, never concurrent.
        governor = None
        if gov_choice.get("enabled"):
            try:
                governor = gov_shim.build(
                    gov_choice["policy"],
                    gov_choice["advisor"],
                    framework=module.FRAMEWORK,
                )
                kwargs["governor"] = governor
                kwargs["budget_usd"] = gov_choice["budget"]
            except Exception as exc:  # noqa: BLE001
                st.warning(f"AEGL failed to start, running ungoverned: {exc}")

        with live_area:
            slots = panels.live_metrics(st.container())
        with transcript_area:
            st.subheader("Agent output")
            transcript_slot = st.empty()
            st.subheader("Tool calls")
            tools_slot = st.empty()

        transcript: list[str] = []
        tool_lines: list[str] = []
        steps = tool_calls = 0
        final: dict[str, Any] | None = None
        started = time.time()

        def repaint(usdc: float = 0.0, paid: int = 0) -> None:
            panels.paint_live(
                slots,
                steps=steps,
                tool_calls=tool_calls,
                usdc=usdc,
                paid=paid,
                elapsed=time.time() - started,
            )
            transcript_slot.markdown(
                "\n\n".join(transcript) or "_waiting for the first token…_"
            )
            tools_slot.markdown("\n".join(tool_lines) or "_no tool calls yet_")

        repaint()
        for event in stream_agent(module, kwargs):
            kind = event.get("kind")
            if kind == "__tick__":
                repaint()
                continue
            if kind == "text":
                transcript.append(event["text"])
                steps += 1
            elif kind == "tool_use":
                tool_calls += 1
                args = event.get("input") or {}
                shown = ", ".join(f"{k}={v}" for k, v in args.items())
                tool_lines.append(f"- `{event['name']}`" + (f" ({shown})" if shown else ""))
            elif kind == "governance_stop":
                transcript.append(
                    f"> ⛔ **AEGL stopped the run** — "
                    f"{event['detail'].get('reason', '')}"
                )
            elif kind == "error":
                transcript.append(f"> **error:** {event['message']}")
            elif kind == "done":
                final = event
            repaint()

        if final:
            if governor is not None:
                # Read the report on this thread, after the worker is done, and
                # stash plain data -- a `Governor` must not live in session state.
                final = {**final, "aegl": governor.report()}
                governor.close()
            st.session_state["ck_last_run"] = final
        st.rerun()

    # --- results -------------------------------------------------------
    last = st.session_state.get("ck_last_run")
    if last:
        telemetry = last.get("telemetry") or {}
        x402 = telemetry.get("x402") or {}

        st.divider()
        st.subheader("Last run")
        st.caption(
            f"{telemetry.get('framework')} · {telemetry.get('provider')}/"
            f"{telemetry.get('model')} · stop: {telemetry.get('stopReason')}"
        )
        panels.telemetry_metrics(telemetry)

        tabs = st.tabs(
            ["Answer", "AEGL", "Data purchased", "x402 receipts", "Tool timeline",
             "History"]
        )
        with tabs[0]:
            panels.answer_panel(telemetry)
        with tabs[1]:
            # The same `render()` the Claude cockpit and the standalone demo call.
            gov_shim.render(last.get("aegl"))
        with tabs[2]:
            panels.purchases_panel(x402)
        with tabs[3]:
            panels.receipts_panel(x402)
        with tabs[4]:
            panels.tool_timeline(x402)
        with tabs[5]:
            panels.history_panel()
