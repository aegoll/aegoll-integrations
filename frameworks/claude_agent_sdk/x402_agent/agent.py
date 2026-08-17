"""The Claude Agent SDK runner.

The agent has no filesystem, no bash and no web access -- `tools=[]` strips the
built-in toolset, so the only way it can learn anything about the market is to
call the x402 tools, and the only way to get the good data is to pay for it.
That is the point of the demo, and it also keeps Haiku's context small.

Three independent guardrails:

  1. `max_budget_usd`  -- Agent SDK stops the run when estimated LLM cost hits it.
  2. `max_turns`       -- hard ceiling on agentic round trips.
  3. spend cap         -- `X402Buyer` refuses to sign a payment it cannot afford.

Plus a cumulative gate in `preflight()` that refuses to start at all once the
journalled lifetime LLM spend reaches the total cap.
"""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    query,
)

from .buyer import X402Buyer
from .config import REPO_ROOT, AgentConfig, DEFAULT_MODEL, FAUCET_URL
from .telemetry import RunTelemetry, append_run, remaining_total_budget
from .tools import build_x402_tools

AGENT_DIR: Path = REPO_ROOT / "agents" / "claude_agent_sdk"

SYSTEM_PROMPT = """\
You are a market-data buying agent. The real data behind this API costs stablecoin
(USDC) over the x402 protocol.

## Two different budgets -- do not confuse them

You may see a remaining-token-budget figure in your context. That is your **LLM
token budget**, which has nothing to do with buying data. Never reason about
purchases using it, and never quote it as your payment budget.

Your **USDC payment budget** comes from exactly one place: the `check_budget`
tool. It is the only authority on what you can afford to buy. If you want to know
what is left to spend on data, call `check_budget` -- do not infer it.

## Order of work

1. Call `list_catalog` first. Free, and it lists every endpoint with its price.
2. Use `quote_endpoint` (also free) to confirm a price before buying.
3. Buy only what the task needs. Each paid tool is a real on-chain payment: no
   refunds, and no retries once settled.
4. Before an expensive purchase, call `check_budget`. Stop buying when the
   remaining USDC will not cover the next call.

## Cost discipline

- `buy_market_signals` costs $0.01 and covers every instrument at once. Buy it at
  most once per run. Never twice.
- `buy_ohlcv_history` costs $0.005 per symbol. Buy candles only for the symbols
  the task actually requires, never for the whole feed.
- If a paid tool fails, do not retry it and do not try a different paid endpoint
  hoping it behaves differently. A payment-layer failure affects all of them.
  Stop and report it.

## Keep your output short

Your token budget is small, and every word you write spends it. Between tool
calls, write at most one short sentence -- or nothing at all. Do not restate your
plan, do not narrate what you are about to do, and do not tally budgets in prose.
Save your writing for the final answer.

The final answer is plain prose backed by figures you actually purchased. Name
the numbers. Close with one line stating what you spent and on what.
"""

DEFAULT_TASK = (
    "Identify the riskiest and the calmest instrument in this feed. Back the call with "
    "volatility and liquidity figures you have actually purchased, then inspect the candle "
    "history of the riskiest one to say whether the risk is trending up or down. Stay inside "
    "the budget."
)


@dataclass
class RunSettings:
    """Everything the UI can dial."""

    model: str = DEFAULT_MODEL
    run_budget_usd: float = 0.02
    total_budget_usd: float = 0.25
    max_turns: int = 12
    max_retries: int = 2
    api_timeout_ms: int = 120_000
    usdc_cap_usd: float = 0.05
    task: str = DEFAULT_TASK
    hard_stop_on_total_budget: bool = True
    # AEGL: the governance layer between the agent and both kinds of spending.
    governance_enabled: bool = True
    governance_policy: str | None = None
    # Phase 2: (provider, model) for the BYOK advisor, or None for
    # deterministic-only governance.
    governance_advisor: tuple[str, str] | None = None
    # Set only by an explicit human click in the override window. The refusal is
    # still recorded; this decides whether it is also obeyed.
    governance_override: bool = False


class PreflightError(RuntimeError):
    """A guardrail refused to start the run."""


def preflight(config: AgentConfig, settings: RunSettings) -> list[str]:
    """Raise if the run cannot start. Returns non-fatal warnings."""
    if not config.anthropic_api_key:
        raise PreflightError(
            "ANTHROPIC_API_KEY is not set. Add it to the repo-root .env before running."
        )

    if not config.wallet_configured:
        raise PreflightError(
            "BUYER_PRIVATE_KEY is not a valid key (the repo ships the stub `0x`). "
            "Run `npm run wallet:new` in the repo root, paste the key into .env, then fund "
            f"the address with test USDC on Base Sepolia at {FAUCET_URL}."
        )

    if settings.hard_stop_on_total_budget:
        remaining = remaining_total_budget(settings.total_budget_usd)
        if remaining <= 0:
            raise PreflightError(
                f"Cumulative LLM spend has reached the ${settings.total_budget_usd:.4f} cap. "
                "Raise the total budget or reset the spend ledger to continue."
            )
        if remaining < settings.run_budget_usd:
            raise PreflightError(
                f"Only ${remaining:.4f} of the ${settings.total_budget_usd:.4f} total budget "
                f"remains, which is less than this run's ${settings.run_budget_usd:.4f} ceiling. "
                "Lower the per-run budget or raise the total."
            )

    warnings: list[str] = []
    if settings.model != DEFAULT_MODEL:
        warnings.append(
            f"Model is {settings.model}, not {DEFAULT_MODEL}. Output tokens cost "
            "3-5x more, so the per-run budget will go much less far."
        )
    return warnings


def build_buyer(config: AgentConfig, settings: RunSettings) -> X402Buyer:
    assert config.buyer_private_key is not None  # guaranteed by preflight
    return X402Buyer(
        private_key=config.buyer_private_key,
        base_url=config.data_api_url,
        spend_cap_usd=Decimal(str(settings.usdc_cap_usd)),
        rpc_url=config.rpc_url,
    )


def _blocks(message: Any) -> list[Any]:
    content = getattr(message, "content", None)
    return content if isinstance(content, list) else []


def _usage_dict(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage
    for attr in ("model_dump", "dict", "__dict__"):
        holder = getattr(usage, attr, None)
        if callable(holder):
            try:
                return dict(holder())
            except Exception:
                continue
        if isinstance(holder, dict):
            return dict(holder)
    return None


async def run_agent(
    config: AgentConfig,
    settings: RunSettings,
    buyer: X402Buyer,
    telemetry: RunTelemetry,
    governance: Any | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Drive one agent run, yielding UI events as they happen.

    When `governance` is supplied, both spend channels pass through AEGL:
    the internal (token) budget is authorized before the run starts, and the
    external (x402) buyer is wrapped so no payment can settle without a decision.
    """

    # --- AEGL: internal channel, before a single token is spent ----------
    if governance is not None:
        auth = governance.authorize_run(
            model=settings.model,
            provider="anthropic",
            budget_usd=settings.run_budget_usd,
        )
        yield {
            "kind": "governance",
            "event": auth.as_dict(),
            "channel": "internal",
        }
        if not auth.allowed and not settings.governance_override:
            telemetry.error = (
                f"AEGL refused the run's token budget ({auth.decision.verdict.value}): "
                + "; ".join(auth.decision.explain())
            )
            telemetry.finished_at = time.time()
            yield {"kind": "error", "message": telemetry.error}
            yield {"kind": "done", "cumulative_llm_usd": append_run(telemetry)}
            return

        if not auth.allowed and settings.governance_override:
            # Overridden by a human. The refusal above is already journalled; this
            # run proceeds anyway, and the Agent SDK's own max_budget_usd remains
            # the backstop.
            yield {
                "kind": "governance_override",
                "channel": "internal",
                "verdict": auth.decision.verdict.value,
                "engine": auth.blocking_engine,
                "message": (
                    f"Human override: proceeding despite AEGL returning "
                    f"{auth.decision.verdict.value} on the token budget."
                ),
            }

        # --- AEGL: external channel -- the buyer now needs approval to pay
        buyer = governance.wrap(buyer)

    server, allowed = build_x402_tools(buyer, telemetry)

    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = config.anthropic_api_key or ""
    # Retry / timeout behaviour of the underlying Claude Code process.
    env["CLAUDE_CODE_MAX_RETRIES"] = str(settings.max_retries)
    env["API_TIMEOUT_MS"] = str(settings.api_timeout_ms)

    options = ClaudeAgentOptions(
        model=settings.model,
        system_prompt=SYSTEM_PROMPT,
        # Strip every built-in tool. The x402 MCP tools below are the whole world.
        tools=[],
        mcp_servers={"x402": server},
        allowed_tools=allowed,
        # Safe because `tools=[]` leaves nothing dangerous to approve, and a
        # permission prompt would deadlock a headless Streamlit run.
        permission_mode="bypassPermissions",
        # Do not inherit the repo's CLAUDE.md / settings into the agent's context.
        setting_sources=[],
        max_turns=settings.max_turns,
        max_budget_usd=settings.run_budget_usd,
        cwd=str(AGENT_DIR),
        env=env,
    )

    yield {"kind": "start", "model": settings.model, "task": settings.task}

    try:
        async for message in query(prompt=settings.task, options=options):
            for event in _translate(message, telemetry):
                yield event

            # The same mid-run ceiling the other two agents use. Here it is
            # belt-and-braces -- the Agent SDK enforces `max_budget_usd` itself --
            # but running the identical check on all three is what makes a
            # governed-vs-ungoverned comparison across frameworks like-for-like.
            if governance is not None:
                check = governance.check_spend(float(telemetry.llm_cost_usd or 0.0))
                if check.should_stop:
                    telemetry.stop_reason = "aegl_spend_ceiling"
                    yield {"kind": "governance_stop", "detail": check.as_dict()}
                    break
    except Exception as exc:  # the SDK raises after yielding an error result
        telemetry.error = f"{type(exc).__name__}: {exc}"
        yield {"kind": "error", "message": telemetry.error}

    telemetry.finished_at = time.time()

    # --- AEGL: record what the run actually cost --------------------------
    if governance is not None:
        governance.settle_run(float(telemetry.llm_cost_usd or 0.0))

    new_total = append_run(telemetry)
    yield {"kind": "done", "cumulative_llm_usd": new_total}


def _translate(message: Any, telemetry: RunTelemetry) -> list[dict[str, Any]]:
    """Turn one SDK message into zero or more UI events."""
    events: list[dict[str, Any]] = []
    name = type(message).__name__

    if name == "AssistantMessage":
        telemetry.record_step_usage(
            getattr(message, "message_id", None),
            _usage_dict(getattr(message, "usage", None)),
        )
        for block in _blocks(message):
            kind = type(block).__name__
            if kind == "TextBlock":
                text = getattr(block, "text", "") or ""
                if text.strip():
                    telemetry.record_text(text)
                    events.append({"kind": "text", "text": text})
            elif kind == "ThinkingBlock":
                events.append({"kind": "thinking"})
            elif kind == "ToolUseBlock":
                events.append(
                    {
                        "kind": "tool_use",
                        "name": getattr(block, "name", "?"),
                        "input": getattr(block, "input", {}) or {},
                    }
                )

    elif name == "UserMessage":
        for block in _blocks(message):
            if type(block).__name__ == "ToolResultBlock":
                events.append(
                    {
                        "kind": "tool_result",
                        "is_error": bool(getattr(block, "is_error", False)),
                    }
                )

    elif name == "ResultMessage":
        telemetry.llm_cost_usd = getattr(message, "total_cost_usd", None) or 0.0
        telemetry.usage = _usage_dict(getattr(message, "usage", None))
        telemetry.model_usage = _usage_dict(getattr(message, "model_usage", None))
        telemetry.num_turns = getattr(message, "num_turns", None)
        duration_ms = getattr(message, "duration_ms", None)
        telemetry.duration_s = round(duration_ms / 1000, 2) if duration_ms else None
        telemetry.subtype = getattr(message, "subtype", None)
        telemetry.stop_reason = getattr(message, "stop_reason", None) or getattr(
            message, "terminal_reason", None
        )

        subtype = str(telemetry.subtype or "")
        # The SDK returns subtype `error_max_budget_usd` when max_budget_usd trips.
        if "budget" in subtype.lower():
            telemetry.budget_stopped = True

        if getattr(message, "is_error", False) and not telemetry.error:
            errors = getattr(message, "errors", None) or []
            detail = "; ".join(str(e) for e in errors) if errors else subtype or "unknown"
            telemetry.error = f"run ended with an error ({detail})"

        events.append(
            {
                "kind": "result",
                "cost_usd": telemetry.llm_cost_usd,
                "num_turns": telemetry.num_turns,
                "subtype": telemetry.subtype,
            }
        )

    return events
