"""Data marketplace: the baseline. An agent buys market data per call, inside a budget.

C5.1, and the case everything else varies from. Nothing clever happens here — that is the point.
An agent shops, the layer decides, the cheap things go through and the expensive one does not,
and every step lands in a verifiable record.

Read this one first. The other cases each change exactly one thing about it:

| case | what it changes |
|---|---|
| `intent-drift` | the purchase is ordinary, but not what the agent was *sent* to do |
| `delegation` | the buyer is a sub-agent, clamped to its parent |
| `budget-exhaustion` | the money runs out mid-run, on the internal channel |
| `aml-structuring` | the purchases are small enough that nothing objects — an open gap |
| `prompt-injection` | the counterparty's text tries to talk its way past the layer |

    python usecases/data-marketplace/run.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _harness import Story, main  # noqa: E402

#: What is for sale, and what it costs in atomic units. Prices ascend, so the run walks from
#: comfortably-affordable to obviously-not.
CATALOGUE = [
    ("/market/snapshot", 10_000, "a price snapshot"),
    ("/market/depth", 50_000, "order book depth"),
    ("/market/history", 250_000, "a month of history"),
    ("/research/report", 2_500_000, "an analyst report"),
    ("/research/dataset", 25_000_000, "the whole dataset"),
]


def story(case: Story) -> int:
    case.say("An agent with a shopping list and a budget. The layer decides each item.")

    case.heading("1. the catalogue")
    for path, atomic, description in CATALOGUE:
        case.say(f"  ${atomic / 1e6:>10.6f}  {path:22} {description}")

    case.heading("2. the run")
    bought = 0
    for path, atomic, _ in CATALOGUE:
        decision = case.ask(label=path, amount_usd=atomic, vendor="data-co", resource=path)
        if decision.approved:
            case.settle(decision, success=True)
            bought += 1

    case.heading("3. what governed it")
    report = case.gov.report()
    case.say(f"  bought    : {bought} of {len(CATALOGUE)}")
    case.say(f"  spent     : ${report.spent_usd}")
    case.say()
    case.say("  by attributed control -- what actually governed this agent:")
    for control, count in sorted(report.by_attributed_control.items(), key=lambda kv: -kv[1]):
        case.say(f"    {control:12} {count}")
    case.say()
    case.say("  Counts by verdict would say what happened. This says what decided, which is")
    case.say("  the question anyone debugging a stopped agent actually has.")

    case.heading("4. where the money stands")
    for envelope in report.envelopes["external"]:
        if not envelope.limit_usd:
            continue
        if envelope.cumulative:
            marker = " <- tightest" if envelope.tightest else ""
            case.say(f"  {envelope.name:18} ${envelope.used_usd} of ${envelope.limit_usd}"
                     f"  headroom ${envelope.headroom_usd}{marker}")
        else:
            case.say(f"  {envelope.name:18} ceiling ${envelope.limit_usd}  (per call, never "
                     f"accumulates)")
    case.say()
    case.say("  A per-call ceiling shows no `used`, because the concept does not apply to it.")
    case.say("  Rendering `$0.00 of $10.00` beside the cumulative rows would read as `nothing")
    case.say("  was spent`, which was a real defect in an earlier version of the report.")

    return case.finish(expect_refusal_from="treasury")


if __name__ == "__main__":
    main("data-marketplace", story)
