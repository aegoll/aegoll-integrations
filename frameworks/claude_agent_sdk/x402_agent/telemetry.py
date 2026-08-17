"""Run telemetry: tool calls, token usage, LLM cost, x402 receipts.

Two budgets are tracked here and they are not the same thing:

  * **LLM cost** -- Anthropic tokens, real money, capped per run by the Agent
    SDK's `max_budget_usd` and cumulatively by a ledger on disk.
  * **USDC spend** -- x402 payments on Base Sepolia, testnet play money, capped
    by `X402Buyer.spend_cap_usd`.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from .config import SPEND_LEDGER_PATH


@dataclass
class ToolEvent:
    name: str
    args: dict[str, Any]
    ok: bool
    detail: str
    paid_usd: float = 0.0
    transaction: str | None = None
    elapsed_s: float = 0.0
    at: float = field(default_factory=time.time)


@dataclass
class RunTelemetry:
    """Accumulates everything one agent run produced."""

    model: str
    run_budget_usd: float
    tool_events: list[ToolEvent] = field(default_factory=list)
    assistant_steps: dict[str, dict[str, int]] = field(default_factory=dict)
    transcript: list[dict[str, Any]] = field(default_factory=list)

    llm_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    model_usage: dict[str, Any] | None = None
    num_turns: int | None = None
    duration_s: float | None = None
    subtype: str | None = None
    stop_reason: str | None = None
    error: str | None = None
    budget_stopped: bool = False

    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    # --- recording ---------------------------------------------------------
    def record_tool(self, event: ToolEvent) -> None:
        self.tool_events.append(event)

    def record_step_usage(self, message_id: str | None, usage: dict[str, Any] | None) -> None:
        """Per-step token counts, deduplicated by message id.

        Parallel tool calls emit several assistant messages sharing one id with
        identical usage -- counting each would inflate the totals.
        """
        if not usage:
            return
        key = message_id or f"anon-{len(self.assistant_steps)}"
        self.assistant_steps[key] = {
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "cache_read_input_tokens": int(usage.get("cache_read_input_tokens") or 0),
            "cache_creation_input_tokens": int(usage.get("cache_creation_input_tokens") or 0),
        }

    def record_text(self, text: str) -> None:
        self.transcript.append({"role": "assistant", "text": text})

    # --- derived -----------------------------------------------------------
    @property
    def steps(self) -> int:
        return len(self.assistant_steps)

    @property
    def step_token_totals(self) -> dict[str, int]:
        """Sum of the per-step counts we saw on assistant messages.

        Useful as a live progress readout, but it is not authoritative: not every
        assistant message carries usage, and it excludes subagent activity.
        """
        totals = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        for step in self.assistant_steps.values():
            for key in totals:
                totals[key] += step.get(key, 0)
        return totals

    @property
    def token_totals(self) -> dict[str, int]:
        """Authoritative token totals, best source first.

        `model_usage` counts subagent requests too and is the only whole-tree
        figure; `usage` on the result message covers the top-level loop; the
        per-step sum is the last resort (and is what the live view shows before
        the result message arrives).
        """
        keys = (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        )
        if self.model_usage:
            camel = {
                "input_tokens": "inputTokens",
                "output_tokens": "outputTokens",
                "cache_read_input_tokens": "cacheReadInputTokens",
                "cache_creation_input_tokens": "cacheCreationInputTokens",
            }
            totals = dict.fromkeys(keys, 0)
            for entry in self.model_usage.values():
                if not isinstance(entry, dict):
                    continue
                for snake, camel_key in camel.items():
                    totals[snake] += int(entry.get(camel_key) or 0)
            if any(totals.values()):
                return totals

        if self.usage:
            totals = {k: int(self.usage.get(k) or 0) for k in keys}
            if any(totals.values()):
                return totals

        return self.step_token_totals

    @property
    def token_source(self) -> str:
        if self.model_usage:
            return "model_usage (includes subagents)"
        if self.usage:
            return "result usage (top-level loop)"
        return "per-step sum (partial)"

    @property
    def usdc_spent(self) -> float:
        return round(sum(e.paid_usd for e in self.tool_events), 8)

    @property
    def paid_calls(self) -> int:
        return sum(1 for e in self.tool_events if e.paid_usd > 0)

    @property
    def failed_tools(self) -> int:
        return sum(1 for e in self.tool_events if not e.ok)

    @property
    def wall_clock_s(self) -> float:
        end = self.finished_at or time.time()
        return round(end - self.started_at, 2)

    @property
    def budget_used_pct(self) -> float:
        if not self.run_budget_usd or self.llm_cost_usd is None:
            return 0.0
        return min(100.0, 100.0 * self.llm_cost_usd / self.run_budget_usd)


# --- cumulative ledger, persisted so the $0.25 cap survives restarts -------


def _read_ledger(path: Path = SPEND_LEDGER_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"total_llm_cost_usd": 0.0, "runs": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("total_llm_cost_usd", 0.0)
        data.setdefault("runs", [])
        return data
    except Exception:
        return {"total_llm_cost_usd": 0.0, "runs": []}


def total_llm_spend_usd(path: Path = SPEND_LEDGER_PATH) -> float:
    return float(_read_ledger(path).get("total_llm_cost_usd") or 0.0)


def run_history(limit: int = 50, path: Path = SPEND_LEDGER_PATH) -> list[dict[str, Any]]:
    runs = _read_ledger(path).get("runs") or []
    return list(reversed(runs))[:limit]


def append_run(telemetry: RunTelemetry, path: Path = SPEND_LEDGER_PATH) -> float:
    """Journal a finished run. Returns the new cumulative LLM total."""
    ledger = _read_ledger(path)
    cost = float(telemetry.llm_cost_usd or 0.0)
    new_total = round(float(ledger["total_llm_cost_usd"]) + cost, 8)

    ledger["total_llm_cost_usd"] = new_total
    ledger["runs"].append(
        {
            "at": telemetry.started_at,
            "model": telemetry.model,
            "llm_cost_usd": cost,
            "usdc_spent": telemetry.usdc_spent,
            "paid_calls": telemetry.paid_calls,
            "turns": telemetry.num_turns,
            "steps": telemetry.steps,
            "tokens": telemetry.token_totals,
            "subtype": telemetry.subtype,
            "stop_reason": telemetry.stop_reason,
            "error": telemetry.error,
            "budget_stopped": telemetry.budget_stopped,
            "wall_clock_s": telemetry.wall_clock_s,
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    return new_total


def reset_ledger(path: Path = SPEND_LEDGER_PATH) -> None:
    if path.exists():
        path.unlink()


def remaining_total_budget(cap_usd: float, path: Path = SPEND_LEDGER_PATH) -> float:
    return max(0.0, round(cap_usd - total_llm_spend_usd(path), 8))


def as_decimal(value: float) -> Decimal:
    return Decimal(str(value))
