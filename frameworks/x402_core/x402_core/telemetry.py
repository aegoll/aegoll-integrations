"""One telemetry shape, so three frameworks produce comparable numbers.

Each adapter fills this in from whatever its framework exposes. The fields mean the
same thing regardless of harness, which is what makes a cross-framework comparison
meaningful rather than three incompatible reports.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import REPO_ROOT

LEDGER_PATH = REPO_ROOT / "agents" / ".spend-ledger.json"

# USD per million tokens. Lives here rather than in an agent so every framework
# prices the same way; an agent that computed its own cost differently would make
# the comparison meaningless.
PRICING: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    # Google Gemini. The `-latest` aliases are the defaults because the pinned 2.x
    # models are closed to new accounts (verified live 2026-08-14). An alias's price
    # is whatever it currently points at, so these can drift.
    "gemini-flash-latest": (0.30, 2.50),
    "gemini-flash-lite-latest": (0.10, 0.40),
    "gemini-3-flash-preview": (0.30, 2.50),
    "gemini-3.6-flash": (0.30, 2.50),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    # Anthropic, for the Claude Agent SDK agent
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-5": (5.00, 25.00),
}

FALLBACK_PRICE = (1.00, 5.00)


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = PRICING.get(model, FALLBACK_PRICE)
    return input_tokens * pin / 1e6 + output_tokens * pout / 1e6


@dataclass
class RunTelemetry:
    framework: str   # "langgraph" | "google-adk" | "claude-agent-sdk"
    provider: str    # "openai" | "gemini" | "anthropic"
    model: str

    input_tokens: int = 0
    output_tokens: int = 0
    steps: int = 0
    tool_calls: int = 0

    transcript: list[str] = field(default_factory=list)
    error: str | None = None
    stop_reason: str | None = None

    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    @property
    def llm_cost_usd(self) -> float:
        return round(cost_usd(self.model, self.input_tokens, self.output_tokens), 8)

    @property
    def wall_clock_s(self) -> float:
        return round((self.finished_at or time.time()) - self.started_at, 2)

    @property
    def answer(self) -> str:
        return "\n\n".join(self.transcript).strip()

    def add_usage(self, input_tokens: int | None, output_tokens: int | None) -> None:
        self.input_tokens += int(input_tokens or 0)
        self.output_tokens += int(output_tokens or 0)

    def as_dict(self, ledger: dict[str, Any] | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "framework": self.framework,
            "provider": self.provider,
            "model": self.model,
            "llmCostUsd": self.llm_cost_usd,
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "steps": self.steps,
            "toolCalls": self.tool_calls,
            "wallClockS": self.wall_clock_s,
            "stopReason": self.stop_reason,
            "error": self.error,
            "answer": self.answer,
        }
        if ledger is not None:
            out["x402"] = ledger
        return out


def append_run(telemetry: RunTelemetry, ledger: dict[str, Any] | None = None) -> float:
    """Journal a finished run. Returns the new cumulative LLM total."""
    data: dict[str, Any] = {"total_llm_cost_usd": 0.0, "runs": []}
    if LEDGER_PATH.exists():
        try:
            data = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
            data.setdefault("total_llm_cost_usd", 0.0)
            data.setdefault("runs", [])
        except Exception:
            pass

    total = round(float(data["total_llm_cost_usd"]) + telemetry.llm_cost_usd, 8)
    data["total_llm_cost_usd"] = total
    data["runs"].append({"at": telemetry.started_at, **telemetry.as_dict(ledger)})

    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_PATH.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return total


def total_spend_usd() -> float:
    if not LEDGER_PATH.exists():
        return 0.0
    try:
        raw = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
        return float(raw.get("total_llm_cost_usd", 0.0))
    except Exception:
        return 0.0


def run_history(limit: int = 50) -> list[dict[str, Any]]:
    if not LEDGER_PATH.exists():
        return []
    try:
        runs = json.loads(LEDGER_PATH.read_text(encoding="utf-8")).get("runs") or []
    except Exception:
        return []
    return list(reversed(runs))[:limit]
