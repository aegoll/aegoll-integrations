"""Structuring: forty small payments, nothing refused. An open finding, shipped as a demo.

C5.6, and the only case here that **succeeds by failing**.

Every other use case ends in a refusal. This one ends with a run that nothing objected to, and
that is the point: forty payments of a tenth of a cent, paced apart, breach no value envelope
and no velocity limit. In the reference implementation this moved money with *nothing refused*.

AEGS-0.1-SEC-6 records it as open, and the reason is worth stating precisely: catching this needs
a control that examines the **shape of a sequence** rather than the size of any action, and no
amount of tightening an envelope produces one. Tightening makes legitimate use harder without
addressing it at all — which matters, because tightening is what an operator will reach for.

So this ships as a runnable artifact rather than a paragraph in a threat model. A reader can see
the gap, and the day it closes this file starts failing and says so.

    python usecases/aml-structuring/run.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _harness import Story, main, policy  # noqa: E402

#: Forty payments of a tenth of a cent. Four cents in total, which is nothing, and that is
#: exactly why nothing stops it: every envelope is a *size* limit and no single payment is large.
PAYMENTS = 40
EACH_ATOMIC = 1_000  # $0.001


def story(case: Story) -> int:
    case.say(f"{PAYMENTS} payments of ${EACH_ATOMIC / 1e6:.6f}, one at a time.")
    case.say("Each is trivially inside every limit. The question is whether the *sequence* is.")

    case.heading("1. what the limits are")
    report = case.gov.report()
    for envelope in report.envelopes["external"]:
        if envelope.limit_usd:
            kind = "per call" if not envelope.cumulative else envelope.window
            case.say(f"  {envelope.name:18} {kind:24} ${envelope.limit_usd}")
    case.say()
    total = PAYMENTS * EACH_ATOMIC
    case.say(f"  the whole sequence totals ${total / 1e6:.6f} -- under every one of them")

    case.heading("2. the sequence")
    approved = refused = 0
    for i in range(1, PAYMENTS + 1):
        decision = case.gov.authorize(
            amount_usd=EACH_ATOMIC, vendor="data-co", resource="/market/tick"
        )
        case.decisions.append(decision)
        if decision.approved:
            case.gov.settle(decision, success=True)
            approved += 1
        else:
            refused += 1
            case.say(f"  payment {i:2}  REFUSED  [{decision.attributed_control}] "
                     f"{decision.reason}")
        if i % 10 == 0:
            case.say(f"  ...{i} payments: {approved} approved, {refused} refused")

    case.heading("3. what the layer saw")
    report = case.gov.report()
    case.say(f"  decisions : {report.decisions_total}")
    case.say(f"  settled   : {report.settled}")
    case.say(f"  spent     : ${report.spent_usd}")
    case.say(f"  refused   : {refused}")
    case.say()
    daily = next((e for e in report.envelopes["external"] if e.name == "daily"), None)
    if daily:
        case.say(f"  daily envelope: ${daily.used_usd} of ${daily.limit_usd} used "
                 f"-- {float(daily.used_usd) / float(daily.limit_usd) * 100:.2f}% of the day")

    case.heading("4. why no envelope caught it")
    case.say("  Every envelope in this system answers *how much*. This sequence never asks for")
    case.say("  much. The thing that is wrong with it is its **shape** -- many, small, similar,")
    case.say("  to one counterparty -- and shape is not a quantity any of these limits hold.")
    case.say()
    case.say("  Tightening does not help, and it is worth seeing why rather than being told:")
    case.say()
    per_call = next(
        (e for e in report.envelopes["external"] if e.name == "per_transaction"), None
    )
    if per_call:
        case.say(f"    per-call ceiling is ${per_call.limit_usd}. Each payment is "
                 f"${EACH_ATOMIC / 1e6:.6f}.")
        case.say(f"    Lowering it to ${EACH_ATOMIC / 1e6:.6f} would still admit all "
                 f"{PAYMENTS} of them,")
        case.say("    and would refuse every legitimate purchase in the catalogue.")
    case.say()
    case.say("  A velocity limit does not help either. Pacing *at* a rate limit is unbounded")
    case.say("  in total: ten a minute is fourteen thousand a day.")

    case.heading("5. what would catch it")
    case.say("  A control that reads a sequence rather than an action. Candidate signals, none")
    case.say("  of which exist yet:")
    case.say()
    case.say("    - count of payments to one counterparty in a window, independent of value")
    case.say("    - variance of amounts: forty identical payments is not forty decisions")
    case.say("    - the ratio of payment count to distinct resources")
    case.say("    - a cumulative total that ignores how it was divided")
    case.say()
    case.say("  That is A11 in the plan and W7.3 in the master. Until it lands, this is the")
    case.say("  honest state of the layer, and it is written down in AEGS-0.1-SEC-6 rather")
    case.say("  than left for somebody to discover.")

    return case.finish(
        expect_no_refusal_because=(
            f"{PAYMENTS} payments totalling ${total / 1e6:.6f} moved with nothing refused. "
            "This is AEGS-0.1-SEC-6, open by construction: no control here examines the shape "
            "of a sequence."
        )
    )


if __name__ == "__main__":
    # Velocity raised so the *rate* limit is not what refuses -- otherwise this case would
    # demonstrate a working velocity limit and claim to demonstrate a gap. Structuring paced
    # five minutes apart in the real world trips no velocity limit at all; raising it here is
    # how a five-minute pace is simulated in a test that has to finish.
    main("aml-structuring", story, pack=policy(velocity_60s="500", velocity_1h="5000"))
