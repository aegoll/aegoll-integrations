"""Headless runner: `python -m x402_agent.cli [--task "..."] [--budget 0.04]`.

Same code path as the Streamlit app, minus the UI. Useful for a cheap smoke test
and for checking the guardrails without a browser.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .agent import DEFAULT_TASK, PreflightError, RunSettings, build_buyer, preflight, run_agent
from .config import (
    DEFAULT_API_TIMEOUT_MS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_TURNS,
    DEFAULT_MODEL,
    DEFAULT_RUN_BUDGET_USD,
    DEFAULT_TOTAL_BUDGET_USD,
    load_config,
)
from .telemetry import RunTelemetry, remaining_total_budget, total_llm_spend_usd


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="x402 buyer agent (headless)")
    p.add_argument("--task", default=DEFAULT_TASK)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument(
        "--budget",
        type=float,
        default=DEFAULT_RUN_BUDGET_USD,
        help="per-run LLM budget in USD",
    )
    p.add_argument(
        "--total-budget",
        type=float,
        default=DEFAULT_TOTAL_BUDGET_USD,
        help="lifetime LLM cap in USD",
    )
    p.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    p.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES)
    p.add_argument("--timeout-ms", type=int, default=DEFAULT_API_TIMEOUT_MS)
    p.add_argument("--usdc-cap", type=float, default=0.05, help="x402 spend cap in USD")
    p.add_argument("--no-hard-stop", action="store_true", help="ignore the lifetime LLM cap")
    p.add_argument("--balance", action="store_true", help="print wallet balances and exit")
    return p.parse_args()


async def _main() -> int:
    args = _parse()
    config = load_config()

    settings = RunSettings(
        model=args.model,
        run_budget_usd=args.budget,
        total_budget_usd=args.total_budget,
        max_turns=args.max_turns,
        max_retries=args.max_retries,
        api_timeout_ms=args.timeout_ms,
        usdc_cap_usd=args.usdc_cap,
        task=args.task,
        hard_stop_on_total_budget=not args.no_hard_stop,
    )

    if args.balance:
        if not config.wallet_configured:
            print("BUYER_PRIVATE_KEY is not set to a real key.", file=sys.stderr)
            return 1
        buyer = build_buyer(config, settings)
        try:
            info = await buyer.usdc_balance(config.seller_address)
            print(json.dumps(info, indent=2))
            seller = info.get("seller")
            if seller and seller["isSelfTransfer"]:
                print(
                    "\nnote: SELLER_ADDRESS equals the buyer address, so payments are "
                    "self-transfers. They settle for real on-chain, but the buyer balance "
                    "will not move. Set a different SELLER_ADDRESS to see it drop.",
                    file=sys.stderr,
                )
        finally:
            await buyer.aclose()
        return 0

    try:
        for warning in preflight(config, settings):
            print(f"warning: {warning}", file=sys.stderr)
    except PreflightError as exc:
        print(f"blocked: {exc}", file=sys.stderr)
        return 1

    print(f"lifetime LLM spend so far: ${total_llm_spend_usd():.6f}")
    print(f"remaining under the ${settings.total_budget_usd:.2f} cap: "
          f"${remaining_total_budget(settings.total_budget_usd):.6f}")

    buyer = build_buyer(config, settings)
    telemetry = RunTelemetry(model=settings.model, run_budget_usd=settings.run_budget_usd)

    print(f"wallet {buyer.address}")
    print(f"seller {config.data_api_url}")
    print(f"model  {settings.model}  |  run budget ${settings.run_budget_usd:.4f}")
    print("-" * 72)

    try:
        async for event in run_agent(config, settings, buyer, telemetry):
            kind = event["kind"]
            if kind == "text":
                print(event["text"])
            elif kind == "tool_use":
                print(f"  [tool] {event['name']} {json.dumps(event['input'])}")
            elif kind == "error":
                print(f"  [error] {event['message']}", file=sys.stderr)
            elif kind == "result":
                print("-" * 72)
                print(f"LLM cost estimate: ${event['cost_usd'] or 0:.6f}  "
                      f"turns={event['num_turns']}  subtype={event['subtype']}")
            elif kind == "done":
                print(f"cumulative LLM spend: ${event['cumulative_llm_usd']:.6f}")
    finally:
        await buyer.aclose()

    print()
    print("x402 ledger:")
    for call in buyer.calls:
        print(f"  {call.path}  ${call.spent_usd:.6f}  tx={call.transaction}")
    print(f"  total USDC spent: ${buyer.total_spent_usd:.6f} "
          f"of ${buyer.spend_cap_usd:.6f}")
    print(f"  tokens ({telemetry.token_source}): {telemetry.token_totals}")
    if telemetry.model_usage:
        print(f"  per-model: {json.dumps(telemetry.model_usage)}")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
