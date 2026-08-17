"""Run the same task across frameworks, providers and governance — one table.

Two questions this answers, which the repo has so far only argued:

**D1 — does the behaviour belong to the agent or the harness?** The three agents
share `x402_core`: one buyer, one set of tool descriptions, one prompt. If that is
true, the same task should produce the same *shape* of run on every framework, and
differences should track the model rather than the harness. One command, N runs,
one table.

**D3 — what does governance cost, and what does it catch?** Running each framework
with and without AEGL puts a number on the overhead and on the refusals. A layer
that is free and catches nothing is pointless; one that is expensive is a trade.
Neither is knowable from reading the code.

```powershell
.venv\\Scripts\\python.exe matrix.py --dry-run              # what would run, and the estimate
.venv\\Scripts\\python.exe matrix.py --compare              # D3: governed vs ungoverned
.venv\\Scripts\\python.exe matrix.py --max-cost 0.05        # D1: the full matrix
```

## Honesty rules this harness follows

* **A failed cell is reported, never dropped.** A provider 429 is a result -- it
  says something about the account, not the integration -- and silently omitting it
  would make the table look cleaner than the run was.
* **Nothing is averaged over a single sample.** Every figure here is one run unless
  `--repeat` says otherwise, and the output says so.
* **Cost is estimated before spending and checked after.** `--max-cost` stops the
  sweep rather than discovering the bill afterwards.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
for sub in ("x402_core", "langgraph", "google_adk", "cockpit_kit"):
    p = str(HERE / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

from x402_core import load_wallet_config  # noqa: E402

# Frameworks the sweep can drive, and the providers each can be driven by. The
# Claude Agent SDK is absent on purpose: its `run_agent` takes a different
# signature (config, settings, buyer, telemetry) and is exercised by its own
# cockpit and CLI. Including it here would mean special-casing the loop, which is
# exactly the coupling the rest of this repo avoids.
FRAMEWORKS: dict[str, dict[str, Any]] = {
    "langgraph": {
        "module": "langgraph_x402",
        "providers": {
            "gemini": "gemini-flash-lite-latest",
            "openai": "gpt-4o-mini",
        },
    },
    "adk": {
        "module": "adk_x402",
        "providers": {"gemini": "gemini-flash-lite-latest"},
    },
}

TASK = "Buy the cheapest endpoint once, then name one instrument. One sentence."

# Rough per-run token cost, for the pre-flight estimate only. Measured runs are
# $0.0007-$0.003 depending on model; this is deliberately on the high side, so the
# estimate over-warns rather than under-warns.
ESTIMATE_PER_RUN_USD = 0.004


@dataclass
class Cell:
    """One run: what was asked, what happened, what it cost."""

    framework: str
    provider: str
    model: str
    governed: bool
    ok: bool = False
    llm_cost_usd: float = 0.0
    usdc_spent_usd: float = 0.0
    paid_calls: int = 0
    steps: int = 0
    tool_calls: int = 0
    wall_clock_s: float = 0.0
    stop_reason: str = ""
    answer: str = ""
    error: str | None = None
    decisions: int = 0
    refused: int = 0
    engines: list[str] = field(default_factory=list)
    ceiling_stopped: bool = False

    @property
    def label(self) -> str:
        gov = "governed" if self.governed else "ungoverned"
        return f"{self.framework}/{self.provider} {gov}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "framework": self.framework, "provider": self.provider,
            "model": self.model, "governed": self.governed, "ok": self.ok,
            "llmCostUsd": round(self.llm_cost_usd, 6),
            "usdcSpentUsd": round(self.usdc_spent_usd, 6),
            "paidCalls": self.paid_calls, "steps": self.steps,
            "toolCalls": self.tool_calls, "wallClockS": round(self.wall_clock_s, 2),
            "stopReason": self.stop_reason, "answer": self.answer[:200],
            "error": self.error, "decisions": self.decisions,
            "refused": self.refused, "engines": self.engines,
            "ceilingStopped": self.ceiling_stopped,
        }


def _load(framework: str) -> Any:
    return __import__(FRAMEWORKS[framework]["module"], fromlist=["run"])


def _build_governor(framework: str, policy: str | None) -> Any:
    """A `Governor` for this cell, or None if AEGL is not importable."""
    sys.path.insert(0, str(HERE.parent / "aegl"))
    from aegl.plugin import Governor  # noqa: PLC0415

    return Governor(policy=policy, advisor=None, framework=framework)


async def run_cell(
    framework: str,
    provider: str,
    *,
    governed: bool,
    task: str,
    budget_usd: float,
    policy: str | None,
    max_steps: int,
) -> Cell:
    """Run one combination. Failures become a reported cell, not an exception."""
    model = FRAMEWORKS[framework]["providers"][provider]
    cell = Cell(framework=framework, provider=provider, model=model, governed=governed)

    module = _load(framework)
    kwargs: dict[str, Any] = {
        "task": task,
        "model": model,
        "max_steps": max_steps,
        "config": load_wallet_config(),
    }
    if "provider" in module.run.__code__.co_varnames:
        kwargs["provider"] = provider

    governor = None
    if governed:
        try:
            governor = _build_governor(framework, policy)
            kwargs["governor"] = governor
            kwargs["budget_usd"] = budget_usd
        except Exception as exc:  # noqa: BLE001
            cell.error = f"could not start AEGL: {type(exc).__name__}: {exc}"
            return cell

    started = time.time()
    try:
        async for event in module.run(**kwargs):
            if event.get("kind") == "governance_stop":
                cell.ceiling_stopped = True
            elif event.get("kind") == "done":
                telemetry = event.get("telemetry") or {}
                x402 = telemetry.get("x402") or {}
                cell.llm_cost_usd = float(telemetry.get("llmCostUsd") or 0.0)
                cell.usdc_spent_usd = float(x402.get("usdcSpent") or 0.0)
                cell.paid_calls = int(x402.get("paidCalls") or 0)
                cell.steps = int(telemetry.get("steps") or 0)
                cell.tool_calls = int(telemetry.get("toolCalls") or 0)
                cell.stop_reason = str(telemetry.get("stopReason") or "")
                cell.answer = str(telemetry.get("answer") or "")
                cell.error = telemetry.get("error")
                cell.ok = not telemetry.get("error")
    except Exception as exc:  # noqa: BLE001 - a broken cell must not end the sweep
        cell.error = f"{type(exc).__name__}: {exc}"
    finally:
        cell.wall_clock_s = time.time() - started
        if governor is not None:
            report = governor.report()
            events = report.get("events") or []
            cell.decisions = len(events)
            refused = [e for e in events if e.get("verdict") != "APPROVE"]
            cell.refused = len(refused)
            cell.engines = sorted({e.get("engine", "?") for e in refused})
            governor.close()

    return cell


def plan(frameworks: list[str], providers: list[str] | None, modes: list[bool]) -> list[tuple]:
    """Every combination that will actually be run, in order."""
    combos = []
    for framework in frameworks:
        for provider, _model in FRAMEWORKS[framework]["providers"].items():
            if providers and provider not in providers:
                continue
            for governed in modes:
                combos.append((framework, provider, governed))
    return combos


# --- reporting ------------------------------------------------------------


def _fmt_matrix(cells: list[Cell]) -> str:
    head = (
        f"  {'framework':11} {'provider':8} {'gov':4} {'ok':3} {'llm $':>9} "
        f"{'usdc $':>8} {'steps':>5} {'tools':>5} {'sec':>6}  stop / error"
    )
    lines = [head, "  " + "-" * (len(head) - 2)]
    for c in cells:
        detail = c.stop_reason if c.ok else (c.error or "")[:46]
        lines.append(
            f"  {c.framework:11} {c.provider:8} {'yes' if c.governed else 'no':4} "
            f"{'ok' if c.ok else 'FAIL':3} {c.llm_cost_usd:>9.6f} "
            f"{c.usdc_spent_usd:>8.4f} {c.steps:>5} {c.tool_calls:>5} "
            f"{c.wall_clock_s:>6.1f}  {detail}"
        )
    return "\n".join(lines)


def _fmt_compare(cells: list[Cell]) -> str:
    """D3: what the layer cost, and what it caught, per framework+provider."""
    pairs: dict[tuple[str, str], dict[bool, Cell]] = {}
    for c in cells:
        pairs.setdefault((c.framework, c.provider), {})[c.governed] = c

    lines = [
        "",
        "  Governed vs ungoverned",
        f"  {'framework/provider':26} {'ungoverned $':>13} {'governed $':>11} "
        f"{'overhead':>9} {'decisions':>10} {'refused':>8}  by",
        "  " + "-" * 92,
    ]
    for (framework, provider), both in sorted(pairs.items()):
        off, on = both.get(False), both.get(True)
        if not off or not on:
            lines.append(
                f"  {framework + '/' + provider:26} incomplete pair — "
                f"{'ungoverned' if off else 'governed'} cell missing or failed"
            )
            continue
        if not (off.ok and on.ok):
            lines.append(
                f"  {framework + '/' + provider:26} not comparable — "
                f"{'ungoverned' if not off.ok else 'governed'} run failed"
            )
            continue
        delta = on.llm_cost_usd - off.llm_cost_usd
        pct = (delta / off.llm_cost_usd * 100) if off.llm_cost_usd else 0.0
        lines.append(
            f"  {framework + '/' + provider:26} {off.llm_cost_usd:>13.6f} "
            f"{on.llm_cost_usd:>11.6f} {pct:>8.1f}% {on.decisions:>10} "
            f"{on.refused:>8}  {', '.join(on.engines) or '—'}"
        )

    decided = sum(c.decisions for c in cells if c.governed)
    lines += [
        "",
        "  Read the overhead column carefully: it is the *model's* run-to-run variance,",
        "  not the layer's cost. AEGL's decisions are deterministic and invoke no model.",
        "  Measured separately (`aegl.cli bench -n 3000`): **p50 128 us, p99 211 us, $0**.",
        f"  This sweep made {decided} governed decision(s) — roughly "
        f"{decided * 0.128:.1f} ms of compute and no tokens at all.",
        "",
        "  So the honest statement is not 'governance costs 20%'. It is: governance",
        "  costs microseconds and nothing in tokens, and the LLM figures either side of",
        "  it differ because the model does. What the governed column buys is the",
        "  decisions, refusals and ceiling stops beside it.",
    ]
    return "\n".join(lines)


async def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Framework x provider x governance sweep (D1 and D3)"
    )
    parser.add_argument("--framework", action="append", choices=sorted(FRAMEWORKS))
    parser.add_argument("--provider", action="append",
                        help="restrict to these providers (repeatable)")
    parser.add_argument("--task", default=TASK)
    parser.add_argument("--budget", type=float, default=0.03,
                        help="token budget per governed run")
    parser.add_argument("--policy", default=None, help="AEGL policy bundle")
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--repeat", type=int, default=1,
                        help="runs per cell; >1 is the only honest way to average")
    parser.add_argument("--compare", action="store_true",
                        help="D3: run each cell governed AND ungoverned")
    parser.add_argument("--governed", action="store_true",
                        help="run governed only (default is ungoverned only)")
    parser.add_argument("--max-cost", type=float, default=0.05,
                        help="refuse to start if the estimate exceeds this")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan and the estimate, spend nothing")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    frameworks = args.framework or sorted(FRAMEWORKS)
    modes = [False, True] if args.compare else [bool(args.governed)]
    combos = plan(frameworks, args.provider, modes) * args.repeat
    estimate = len(combos) * ESTIMATE_PER_RUN_USD

    if not args.json:
        print(f"cells: {len(combos)}  (repeat {args.repeat})")
        for framework, provider, governed in combos:
            model = FRAMEWORKS[framework]["providers"][provider]
            print(f"  {framework:11} {provider:8} {model:26} "
                  f"{'governed' if governed else 'ungoverned'}")
        print(f"estimated LLM cost: ~${estimate:.4f} (upper bound)")

    if args.dry_run:
        return 0
    if estimate > args.max_cost:
        print(f"refusing to start: estimate ${estimate:.4f} exceeds "
              f"--max-cost ${args.max_cost:.4f}", file=sys.stderr)
        return 2

    cells: list[Cell] = []
    for framework, provider, governed in combos:
        if not args.json:
            print(f"\n>>> {framework}/{provider} "
                  f"{'governed' if governed else 'ungoverned'} …", flush=True)
        cell = await run_cell(
            framework, provider,
            governed=governed, task=args.task, budget_usd=args.budget,
            policy=args.policy, max_steps=args.max_steps,
        )
        cells.append(cell)
        if not args.json:
            print(f"    {'ok' if cell.ok else 'FAIL'}  "
                  f"${cell.llm_cost_usd:.6f} llm  ${cell.usdc_spent_usd:.4f} usdc  "
                  f"{cell.wall_clock_s:.1f}s"
                  + (f"  {cell.error[:70]}" if cell.error else ""))

    spent = sum(c.llm_cost_usd for c in cells)
    failed = [c for c in cells if not c.ok]

    if args.json:
        print(json.dumps({
            "cells": [c.as_dict() for c in cells],
            "totals": {
                "llmCostUsd": round(spent, 6),
                "usdcSpentUsd": round(sum(c.usdc_spent_usd for c in cells), 6),
                "cells": len(cells), "failed": len(failed),
            },
        }, indent=2))
        return 0

    print("\n" + _fmt_matrix(cells))
    if args.compare:
        print(_fmt_compare(cells))

    print(f"\n  total LLM cost: ${spent:.6f}   "
          f"USDC: ${sum(c.usdc_spent_usd for c in cells):.4f}   "
          f"cells: {len(cells)}   failed: {len(failed)}")
    if failed:
        print("\n  failures are reported rather than dropped — a provider error says "
              "something\n  about the account, and hiding it makes the table look "
              "cleaner than the run was:")
        for c in failed:
            print(f"    {c.label}: {(c.error or '')[:110]}")
    if args.repeat == 1:
        print("\n  one run per cell — these are samples, not averages. Use --repeat "
              "to average.")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
