"""x402 buying agent on LangGraph, driven by OpenAI.

Same six tools, same prompt, same seller as the Claude Agent SDK and Google ADK
versions. Only the harness and the model differ -- which is the point: the three
exist to be compared, and to show the governance layer is not coupled to one
framework.

Framework notes worth knowing:

* `create_react_agent(model, tools, prompt=...)` from `langgraph.prebuilt` supplies
  the whole tool loop. For an agent this shape there is no graph to wire by hand.
* Tools are `StructuredTool`s over the shared async operations, so LangChain awaits
  the coroutine directly -- no thread hop, no event-loop juggling.
* Usage arrives on each `AIMessage.usage_metadata`, but **only if the model is
  constructed with `stream_usage=True`**. Without it a streamed run reports zero
  tokens, which reads as a free agent rather than an unmeasured one.
* LangGraph has `recursion_limit` (a step ceiling) and **no cost ceiling**. Unlike
  the Claude Agent SDK there is no `max_budget_usd`, so the only spend guards here
  are the x402 spend cap and the step limit. Worth remembering when comparing: the
  frameworks do not offer the same safety rails.
"""

from __future__ import annotations

import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

# x402_core is a sibling package in this repo, not a published one.
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

FRAMEWORK = "langgraph"
PROVIDER = "openai"
DEFAULT_MODEL = "gpt-4o-mini"
MODELS = ("gpt-4o-mini", "gpt-4.1-mini", "gpt-4o")

# LangGraph is provider-agnostic, so the harness can be driven by a different
# model without changing the agent. Kept as a real option rather than a test hook:
# it separates "the LangGraph integration is broken" from "this account cannot
# serve requests", and it is what makes a framework x provider matrix possible.
ALT_PROVIDERS = {
    "openai": ("gpt-4o-mini", "OPENAI_API_KEY"),
    "gemini": ("gemini-flash-latest", "GEMINI_API_KEY"),
}


def build_tools(toolset: X402Toolset) -> list[Any]:
    """Wrap the shared operations as LangChain tools.

    The wrappers exist so LangChain can infer an argument schema from a signature;
    the descriptions come from `x402_core` so all three agents present identical
    price information to their models.
    """
    from langchain_core.tools import StructuredTool  # noqa: PLC0415

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

    return [
        StructuredTool.from_function(
            coroutine=fn, name=fn.__name__, description=DESCRIPTIONS[fn.__name__]
        )
        for fn in (
            list_catalog,
            check_budget,
            quote_endpoint,
            buy_market_snapshot,
            buy_market_signals,
            buy_ohlcv_history,
        )
    ]


def build_chat_model(model: str, provider: str, api_key: str | None) -> Any:
    """The only provider-specific code in this agent."""
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI  # noqa: PLC0415

        return ChatGoogleGenerativeAI(
            model=model, google_api_key=api_key, temperature=0
        )

    from langchain_openai import ChatOpenAI  # noqa: PLC0415

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        temperature=0,
        stream_usage=True,  # see the module docstring -- without this, cost reads as 0
    )


def build_agent(
    model: str,
    toolset: X402Toolset,
    api_key: str | None = None,
    provider: str = PROVIDER,
) -> Any:
    from langgraph.prebuilt import create_react_agent  # noqa: PLC0415

    llm = build_chat_model(model, provider, api_key)
    return create_react_agent(model=llm, tools=build_tools(toolset), prompt=SYSTEM_PROMPT)


async def run(
    task: str = DEFAULT_TASK,
    model: str = DEFAULT_MODEL,
    max_steps: int = 12,
    api_key: str | None = None,
    config: WalletConfig | None = None,
    provider: str = PROVIDER,
    governor: Any | None = None,
    budget_usd: float | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Drive one run, yielding events in the shape every agent here uses.

    `governor` is optional and duck-typed — anything exposing `authorize_run`,
    `wrap`, `check_spend` and `settle_run`. Passing one gives this agent a **cost
    ceiling LangGraph does not have**: `recursion_limit` caps steps, and a step is
    not a dollar. Passing nothing leaves the run exactly as it was.
    """
    import os

    cfg = config or load_wallet_config()
    default_model, env_var = ALT_PROVIDERS.get(provider, ALT_PROVIDERS["openai"])
    if provider != PROVIDER and model == DEFAULT_MODEL:
        model = default_model  # asked for another provider without naming a model
    key = api_key or os.environ.get(env_var) or (
        os.environ.get("GOOGLE_API_KEY") if provider == "gemini" else None
    )
    telemetry = RunTelemetry(framework=FRAMEWORK, provider=provider, model=model)

    if not key:
        telemetry.error = f"{env_var} is not set in the repo-root .env"
        telemetry.finished_at = time.time()
        yield {"kind": "error", "message": telemetry.error}
        yield {"kind": "done", "telemetry": telemetry.as_dict(), "cumulative_usd": 0.0}
        return

    guard = RunGuard(governor, budget_usd=budget_usd)
    allowed, refusal = guard.authorize(model=model, provider=provider)
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
    agent = build_agent(model, toolset, api_key=key, provider=provider)

    yield {
        "kind": "start",
        "framework": FRAMEWORK,
        "provider": provider,
        "model": model,
        "wallet": buyer.address,
        "governed": guard.active,
    }

    seen: set[str] = set()
    try:
        # Held by name so `aclose()` can run in this task rather than leaving the
        # stream to the garbage collector -- the same discipline the ADK agent
        # needs, applied here before it bites.
        stream = agent.astream(
            {"messages": [{"role": "user", "content": task}]},
            config={"recursion_limit": max_steps * 2},
            stream_mode="values",
        )
        try:
            async for chunk in stream:
                messages = chunk.get("messages") or []
                if not messages:
                    continue
                message = messages[-1]
                key_id = getattr(message, "id", None) or str(id(message))
                if key_id in seen:
                    continue
                seen.add(key_id)
                for event in translate(message, telemetry):
                    yield event

                # The cost ceiling LangGraph does not ship. Checked after each
                # message, because that is when the token count has moved.
                if guard.check(telemetry.llm_cost_usd):
                    telemetry.stop_reason = guard.stop_reason
                    yield {"kind": "governance_stop", "detail": guard.stop.as_dict()}
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


def translate(message: Any, telemetry: RunTelemetry) -> list[dict[str, Any]]:
    """One LangChain message -> zero or more framework-neutral events."""
    events: list[dict[str, Any]] = []
    kind = type(message).__name__

    if kind == "AIMessage":
        telemetry.steps += 1
        usage = getattr(message, "usage_metadata", None) or {}
        telemetry.add_usage(usage.get("input_tokens"), usage.get("output_tokens"))

        for call in getattr(message, "tool_calls", None) or []:
            telemetry.tool_calls += 1
            events.append(
                {
                    "kind": "tool_use",
                    "name": call.get("name", "?"),
                    "input": call.get("args") or {},
                }
            )

        text = message.content
        if isinstance(text, list):  # content-block form
            text = "".join(b.get("text", "") for b in text if isinstance(b, dict))
        if isinstance(text, str) and text.strip():
            telemetry.transcript.append(text)
            events.append({"kind": "text", "text": text})

        finish = (getattr(message, "response_metadata", None) or {}).get("finish_reason")
        telemetry.stop_reason = finish or telemetry.stop_reason

    elif kind == "ToolMessage":
        events.append(
            {
                "kind": "tool_result",
                "name": getattr(message, "name", "?"),
                "is_error": getattr(message, "status", "") == "error",
            }
        )

    return events
