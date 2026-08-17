"""x402 buying agent on Google ADK, driven by Gemini.

Same six tools, same prompt, same seller as the LangGraph and Claude Agent SDK
versions. Only the harness and the model differ.

Framework notes worth knowing:

* ADK builds tool declarations by **introspecting plain Python functions** -- name,
  signature and docstring. There is no decorator and no schema object, so the
  shared descriptions from `x402_core` are injected as `__doc__` on thin wrappers.
* `Agent` is an alias for `LlmAgent`. `InMemoryRunner` supplies a session service;
  a session must be created before `run_async`, and creating it is a coroutine.
* Everything comes back as `Event`s carrying `google.genai` `Content`. Function
  calls and their responses are `Part`s, not separate event types, so the
  translation below inspects parts rather than event classes.
* Usage is on `event.usage_metadata` with `prompt_token_count` /
  `candidates_token_count` -- Gemini's names, not OpenAI's.
* Like LangGraph and unlike the Claude Agent SDK, ADK has **no cost ceiling**. The
  spend guards here are the x402 cap and `max_llm_calls`.
* Model choice matters: the pinned `gemini-2.x` ids return 404 "no longer available
  to new users" on a fresh key, so the moving `-latest` aliases are the defaults.
"""

from __future__ import annotations

import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

_X402_CORE = str(Path(__file__).resolve().parents[2] / "x402_core")
if _X402_CORE not in sys.path:
    sys.path.insert(0, _X402_CORE)

from x402_core import (  # noqa: E402
    DEFAULT_TASK,
    DESCRIPTIONS,
    SYSTEM_PROMPT,
    RunGuard,
    RunTelemetry,
    WalletConfig,
    X402Toolset,
    append_run,
    build_buyer,
    load_wallet_config,
)

FRAMEWORK = "google-adk"
PROVIDER = "gemini"
DEFAULT_MODEL = "gemini-flash-latest"
MODELS = ("gemini-flash-lite-latest", "gemini-flash-latest", "gemini-3.6-flash")

APP_NAME = "x402_adk_agent"
USER_ID = "agent-1"


def build_tools(toolset: X402Toolset) -> list[Any]:
    """Plain async callables, which is exactly what ADK wants.

    ADK reads the function's name, signature and docstring to build the tool
    declaration, so the shared description is assigned to `__doc__`. Keeping the
    text identical across frameworks is what makes the three agents comparable.
    """

    async def list_catalog() -> str:
        return await toolset.list_catalog()

    async def check_budget() -> str:
        return await toolset.check_budget()

    async def quote_endpoint(path: str) -> str:
        return await toolset.quote_endpoint(path)

    async def buy_market_snapshot() -> str:
        return await toolset.buy_market_snapshot()

    async def buy_market_signals() -> str:
        return await toolset.buy_market_signals()

    async def buy_ohlcv_history(symbol: str) -> str:
        return await toolset.buy_ohlcv_history(symbol)

    functions = [
        list_catalog,
        check_budget,
        quote_endpoint,
        buy_market_snapshot,
        buy_market_signals,
        buy_ohlcv_history,
    ]
    for fn in functions:
        fn.__doc__ = DESCRIPTIONS[fn.__name__]
    return functions


def build_agent(model: str, toolset: X402Toolset) -> Any:
    from google.adk.agents import Agent  # noqa: PLC0415

    return Agent(
        name="x402_market_buyer",
        model=model,
        description="Buys market data over the x402 protocol, within a USDC budget.",
        instruction=SYSTEM_PROMPT,
        tools=build_tools(toolset),
    )


async def run(
    task: str = DEFAULT_TASK,
    model: str = DEFAULT_MODEL,
    max_steps: int = 12,
    api_key: str | None = None,
    config: WalletConfig | None = None,
    governor: Any | None = None,
    budget_usd: float | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Drive one run, yielding events in the shape every agent here uses.

    `governor` is optional and duck-typed -- anything exposing `authorize_run`,
    `wrap`, `check_spend` and `settle_run`. Passing one gives this agent a **cost
    ceiling the ADK does not have**: `max_llm_calls` caps calls, and a call is not
    a dollar. Passing nothing leaves the run exactly as it was.
    """
    import os

    cfg = config or load_wallet_config()
    key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    telemetry = RunTelemetry(framework=FRAMEWORK, provider=PROVIDER, model=model)

    if not key:
        telemetry.error = "GEMINI_API_KEY (or GOOGLE_API_KEY) is not set in the .env"
        telemetry.finished_at = time.time()
        yield {"kind": "error", "message": telemetry.error}
        yield {"kind": "done", "telemetry": telemetry.as_dict(), "cumulative_usd": 0.0}
        return

    # The ADK reads the key from the environment rather than a constructor arg.
    os.environ.setdefault("GOOGLE_API_KEY", key)
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "0"

    from google.adk.runners import InMemoryRunner  # noqa: PLC0415
    from google.genai import types as genai_types  # noqa: PLC0415

    guard = RunGuard(governor, budget_usd=budget_usd)
    allowed, refusal = guard.authorize(model=model, provider=PROVIDER)
    if not allowed:
        telemetry.error = refusal
        telemetry.stop_reason = "aegl_refused"
        telemetry.finished_at = time.time()
        yield {"kind": "error", "message": refusal}
        yield {"kind": "done", "telemetry": telemetry.as_dict(), "cumulative_usd": 0.0}
        return

    buyer = build_buyer(cfg)
    # Governed, the wrapped client is the only thing holding the signer, so the
    # agent cannot pay without a decision.
    toolset = X402Toolset(buyer=guard.wrap(buyer))
    agent = build_agent(model, toolset)
    runner = InMemoryRunner(agent=agent, app_name=APP_NAME)

    yield {
        "kind": "start",
        "framework": FRAMEWORK,
        "provider": PROVIDER,
        "model": model,
        "wallet": buyer.address,
        "governed": guard.active,
    }

    try:
        session = await runner.session_service.create_session(
            app_name=APP_NAME, user_id=USER_ID
        )
        message = genai_types.Content(
            role="user", parts=[genai_types.Part.from_text(text=task)]
        )
        # Held by name so it can be closed explicitly below. Abandoning an ADK
        # event stream mid-iteration leaves it to be finalised by the garbage
        # collector, which runs `contextvars.reset()` from a different context
        # and raises `ValueError: <Token ...> was created in a different Context`
        # onto stderr. Harmless to the result, alarming to read, and avoidable.
        stream = runner.run_async(
            user_id=USER_ID, session_id=session.id, new_message=message
        )
        try:
            async for event in stream:
                for translated in translate(event, telemetry):
                    yield translated

                # The cost ceiling the ADK does not ship. `max_steps` below is
                # the framework's kind of limit; this one is denominated in money.
                if guard.check(telemetry.llm_cost_usd):
                    telemetry.stop_reason = guard.stop_reason
                    yield {"kind": "governance_stop", "detail": guard.stop.as_dict()}
                    break
                if telemetry.steps >= max_steps:
                    telemetry.stop_reason = "max_steps"
                    break
        finally:
            await stream.aclose()
    except Exception as exc:
        telemetry.error = f"{type(exc).__name__}: {exc}"
        yield {"kind": "error", "message": telemetry.error}
    finally:
        telemetry.finished_at = time.time()
        ledger = toolset.ledger()
        guard.settle(telemetry.llm_cost_usd)
        await buyer.aclose()

    total = append_run(telemetry, ledger)
    yield {
        "kind": "done",
        "telemetry": telemetry.as_dict(ledger),
        "cumulative_usd": total,
        "governance": guard.as_dict(),
    }


def translate(event: Any, telemetry: RunTelemetry) -> list[dict[str, Any]]:
    """One ADK event -> zero or more framework-neutral events.

    Partial events are skipped: ADK streams incremental text, and counting those
    would inflate both the step count and the transcript.
    """
    events: list[dict[str, Any]] = []

    if getattr(event, "partial", False):
        return events

    usage = getattr(event, "usage_metadata", None)
    if usage is not None:
        telemetry.add_usage(
            getattr(usage, "prompt_token_count", 0),
            getattr(usage, "candidates_token_count", 0),
        )

    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    counted_step = False

    for part in parts:
        call = getattr(part, "function_call", None)
        if call is not None:
            telemetry.tool_calls += 1
            events.append(
                {
                    "kind": "tool_use",
                    "name": getattr(call, "name", "?"),
                    "input": dict(getattr(call, "args", None) or {}),
                }
            )
            continue

        response = getattr(part, "function_response", None)
        if response is not None:
            events.append(
                {
                    "kind": "tool_result",
                    "name": getattr(response, "name", "?"),
                    "is_error": False,
                }
            )
            continue

        text = getattr(part, "text", None)
        if text and text.strip():
            if not counted_step:
                telemetry.steps += 1
                counted_step = True
            telemetry.transcript.append(text)
            events.append({"kind": "text", "text": text})

    finish = getattr(event, "finish_reason", None)
    if finish:
        telemetry.stop_reason = str(finish)
    if getattr(event, "error_message", None):
        telemetry.error = str(event.error_message)
        events.append({"kind": "error", "message": telemetry.error})

    return events
