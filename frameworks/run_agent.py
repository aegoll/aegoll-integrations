"""Run any of the framework agents from one command.

    python run_agent.py langgraph  --task "..."   # OpenAI
    python run_agent.py adk        --model gemini-flash-latest
    python run_agent.py --list

Deliberately thin. Each agent is self-contained and importable on its own; this
only exists so the three can be driven identically when comparing them.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for sub in ("x402_core", "langgraph", "google_adk"):
    p = str(HERE / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

from x402_core import DEFAULT_TASK, load_wallet_config, total_spend_usd  # noqa: E402

AGENTS = {
    "langgraph": ("langgraph_x402", "LangGraph + OpenAI"),
    "adk": ("adk_x402", "Google ADK + Gemini"),
}


def _load(name: str):
    module_name, label = AGENTS[name]
    module = __import__(module_name, fromlist=["run"])
    return module, label


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Run an x402 buying agent")
    parser.add_argument("agent", nargs="?", choices=sorted(AGENTS), help="which framework")
    parser.add_argument("--task", default=DEFAULT_TASK)
    parser.add_argument("--model", default=None)
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument(
        "--provider",
        default=None,
        help="override the provider (langgraph only: openai | gemini). Useful to prove the harness works when one account cannot serve requests.",
    )
    parser.add_argument("--json", action="store_true", help="emit the final report as JSON")
    parser.add_argument("--list", action="store_true", help="list agents and exit")
    parser.add_argument(
        "--govern", action="store_true",
        help="run under AEGL: authorize the token budget, govern payments, "
             "enforce a mid-run cost ceiling",
    )
    parser.add_argument(
        "--budget", type=float, default=None, metavar="USD",
        help="token budget for this run; with --govern it becomes an enforced "
             "ceiling, which LangGraph and the ADK do not otherwise have",
    )
    parser.add_argument("--policy", default=None, help="AEGL policy bundle name")
    args = parser.parse_args()

    if args.list or not args.agent:
        print(f"{'key':12} {'framework':24} default model")
        for key in sorted(AGENTS):
            module, label = _load(key)
            print(f"{key:12} {label:24} {module.DEFAULT_MODEL}")
        print(f"\nlifetime spend across these agents: ${total_spend_usd():.6f}")
        return 0

    module, label = _load(args.agent)
    model = args.model or module.DEFAULT_MODEL
    cfg = load_wallet_config()

    shown_provider = args.provider or getattr(module, "PROVIDER", "?")
    # Resolve the model the same way the agent will. `--provider gemini` with no
    # `--model` makes the agent pick that provider's default, so printing the
    # agent-level default here would name a model the run never used.
    shown_model = model
    if args.provider and not args.model:
        alt = getattr(module, "ALT_PROVIDERS", {}).get(args.provider)
        shown_model = alt[0] if alt else model
    if not args.json:
        # Label from the *actual* provider, not the agent default -- otherwise a
        # --provider override prints a header that contradicts the result.
        print(f"{module.FRAMEWORK} + {shown_provider}  |  model {shown_model}")
        print(f"seller {cfg.data_api_url}  |  usdc cap ${cfg.usdc_cap_usd}")
        print("-" * 72)

    # `tesoro` is imported *here*, not by any agent: the agents take a governor, they
    # never reach for one. `run_agent.py` is the host that supplies it, which is the
    # inverted dependency the whole design turns on.
    #
    # Installed from PyPI, not found by a path. The `sys.path.insert` this replaces
    # pointed at a sibling `aegl/` that does not exist in this repository, so `--govern`
    # raised ModuleNotFoundError rather than governing anything.
    governor = None
    if args.govern:
        from tesoro.plugin import Governor  # noqa: PLC0415

        governor = Governor(policy=args.policy, framework=module.FRAMEWORK)
        if not args.json:
            spec = governor.advisor_spec
            print(f"tesoro      : policy {governor.bundle.name} "
                  f"({governor.bundle.hash[:8]})  advisor "
                  f"{'/'.join(spec) if spec else 'deterministic only'}")

    final = None
    kwargs = {"task": args.task, "max_steps": args.max_steps, "config": cfg}
    if governor is not None:
        kwargs["governor"] = governor
    if args.budget is not None:
        kwargs["budget_usd"] = args.budget
    if args.provider:
        kwargs["provider"] = args.provider
        if not args.model:
            model = None  # let the agent pick its default for that provider
    if model:
        kwargs["model"] = model

    async for event in module.run(**kwargs):
        kind = event.get("kind")
        if kind == "start" and not args.json:
            print(f"wallet {event.get('wallet')}")
        elif kind == "text" and not args.json:
            print(event["text"])
        elif kind == "tool_use" and not args.json:
            print(f"  [tool] {event['name']} {json.dumps(event.get('input') or {})}")
        elif kind == "error" and not args.json:
            print(f"  [error] {event['message']}", file=sys.stderr)
        elif kind == "governance_stop" and not args.json:
            print(f"  [tesoro] {event['detail'].get('reason', 'spend ceiling reached')}")
        elif kind == "done":
            final = event

    if governor is not None:
        governor.close()

    if final is None:
        print("no result", file=sys.stderr)
        return 1

    telemetry = final["telemetry"]
    if args.json:
        print(json.dumps(final, indent=2, default=str))
        return 0 if not telemetry.get("error") else 1

    x402 = telemetry.get("x402") or {}
    print("-" * 72)
    print(f"framework   : {telemetry['framework']} ({telemetry['provider']}/{telemetry['model']})")
    print(f"llm cost    : ${telemetry['llmCostUsd']:.6f}  "
          f"({telemetry['inputTokens']} in / {telemetry['outputTokens']} out)")
    print(f"usdc spent  : ${x402.get('usdcSpent', 0):.6f} over {x402.get('paidCalls', 0)} paid calls")
    print(f"steps/tools : {telemetry['steps']} / {telemetry['toolCalls']}")
    print(f"wall clock  : {telemetry['wallClockS']}s   stop: {telemetry.get('stopReason')}")
    if telemetry.get("error"):
        print(f"error       : {telemetry['error']}")
    for call in x402.get("calls", []):
        if call["paidUsd"]:
            print(f"  paid ${call['paidUsd']:.6f}  {call['tool']}  tx={call.get('transaction')}")
    gov = final.get("governance") or {}
    if gov.get("governed"):
        stopped = gov.get("stopped")
        print(f"aegl        : budget ${gov.get('budgetUsd')}  "
              f"authorized={gov.get('authorized')}  "
              + (f"STOPPED at ${stopped['spentUsd']:.6f}" if stopped else "not stopped"))
    print(f"cumulative across agents: ${final['cumulative_usd']:.6f}")
    return 0 if not telemetry.get("error") else 1


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
