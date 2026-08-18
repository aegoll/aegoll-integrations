"""Budget exhaustion: why an exhausted token budget must REJECT and not REVIEW.

C5.4. The two channels are not the same money and they do not fail the same way.

An **external** payout that breaches a limit can reasonably go to REVIEW: a human can look at
it, and the agent can wait. REVIEW means pausable, and a payout is pausable.

An **internal** token budget is not. There is no human in the loop of a running agent, so
`pause and ask` becomes `hang` — and the tokens already spent are spent. Worse, starting a step
that cannot finish wastes the budget that is already short. So the right answer is REJECT: stop,
now, and say which limit.

That asymmetry is why the two channels never share an envelope. It is not tidy bookkeeping; the
same breach has a different correct response depending on which money it was.

    python usecases/budget-exhaustion/run.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _harness import Story, main  # noqa: E402


def story(case: Story) -> int:
    case.say("The internal channel here gets $0.04 per run and $0.08 a day: two runs is the")
    case.say("day, and the third has nowhere to come from. The velocity limit is raised out of")
    case.say("the way on purpose -- the first draft of this case hit *that* instead, and")
    case.say("narrated a day running out when what actually happened was a rate limit.")

    from aegoll.adapters.base import RunGuard

    case.heading("1. two ceilings guard a run, and they are not the same ceiling")
    case.say("  run budget : what this caller declared for this run")
    case.say("  envelopes  : what the policy pack allows across all runs")
    case.say()
    case.say("  A guard that only checked the first would miss the day running out. A guard")
    case.say("  that only checked the second would ignore the number the caller passed.")

    case.heading("2. the run budget, hit mid-run")
    guard = RunGuard(case.gov, budget_usd="0.02")
    allowed, why = guard.start(model="gpt-4o-mini", provider="openai")
    case.say(f"  authorised to start: {allowed}")

    spent = 0
    for step in range(1, 7):
        spent += 5_000
        stop = guard.should_stop(spent)
        case.say(f"  step {step}  spent ${spent / 1e6:.6f}   "
                 f"{'STOP' if stop else 'continue'}")
        if stop:
            break

    stopped = guard.stopped
    assert stopped, "the declared run budget did not stop the run"
    case.say()
    case.say(f"  stopped by : {stopped['stoppedBy']}")
    case.say(f"  reason     : {stopped['reason']}")
    case.say(f"  verdict    : {stopped['verdict']}  <- None, and that is correct:")
    case.say("               the caller's own ceiling is not a policy verdict, and dressing")
    case.say("               it as one would borrow authority it does not have.")

    case.heading("3. now spend the day")
    spent_runs = 0
    while spent_runs < 5:
        run = RunGuard(case.gov, budget_usd="0.04")
        ok, refusal = run.start(model="gpt-4o-mini", provider="openai")
        if not ok:
            case.say(f"  run {spent_runs + 1}: REFUSED BEFORE STARTING")
            case.say(f"           {refusal}")
            break
        run.finish("0.04")
        spent_runs += 1
        case.say(f"  run {spent_runs}: spent $0.040000 and settled")

    internal = {e.name: e for e in case.gov.report().envelopes["internal"]}
    daily = internal.get("daily")
    if daily:
        case.say()
        case.say(f"  internal daily: ${daily.used_usd} of ${daily.limit_usd}  "
                 f"headroom ${daily.headroom_usd}")

    case.heading("4. the verdict on an exhausted token budget")
    exhausted = case.ask(
        label="one more run's token budget", amount_usd="0.04",
        vendor="openai", resource="model:gpt-4o-mini", channel="internal",
    )
    case.say()
    case.say(f"  verdict: {exhausted.verdict.value}")
    case.say("  REJECT, not REVIEW. There is no human to ask, so a pause would be a hang.")

    case.heading("5. the same breach on the external channel")
    case.say("  A payout can wait for a person. Same kind of breach, different right answer.")
    case.say()
    # $20, not $500. Both breach the per-call ceiling, but $500 also exceeds the treasury
    # balance -- and a payment with no money behind it is REJECT, which would have hidden the
    # asymmetry this case is about. The first draft used $500 and demonstrated nothing.
    payout = case.ask(
        label="a payout over the per-call ceiling", amount_usd="20.00",
        vendor="data-co", resource="/premium/feed", channel="external",
    )

    case.heading("6. and the channels never shared an envelope")
    report = case.gov.report()
    for channel in ("internal", "external"):
        rows = {e.name: e for e in report.envelopes.get(channel, ())}
        row = rows.get("daily")
        if row:
            case.say(f"  {channel:9} daily  limit ${row.limit_usd}  used ${row.used_usd}")
    case.say()
    case.say("  The internal channel is spent; the external one is untouched. An exhausted")
    case.say("  token budget does not stop the agent paying a vendor, and a spent payout")
    case.say("  budget does not stop it thinking.")

    case.heading("the asymmetry, in one line each")
    case.say(f"  internal  ${'0.04':>7}  budget exhausted   "
             f"{exhausted.verdict.value:9} {exhausted.attributed_control}"
             f"  (binding: {exhausted.budget.binding})")
    case.say(f"  external  ${'20.00':>7}  over the ceiling   "
             f"{payout.verdict.value:9} {payout.attributed_control}"
             f"  (binding: {payout.budget.binding})")

    failures = []
    if exhausted.verdict.value != "REJECT":
        failures.append(
            f"an exhausted token budget returned {exhausted.verdict.value}, not REJECT -- "
            "C5.4's whole claim is that it must reject, because there is no human to ask"
        )
    if payout.verdict.value != "REVIEW":
        failures.append(
            f"an over-ceiling payout returned {payout.verdict.value}, not REVIEW -- if both "
            "channels answer the same way, this case demonstrates no asymmetry at all"
        )
    if failures:
        case.say()
        for problem in failures:
            case.say(f"  FAILED: {problem}")
        return 1

    return case.finish(expect_refusal_from="treasury")


if __name__ == "__main__":
    from _harness import policy

    # `daily_usd` here is the *internal* one -- the second occurrence in the pack, under
    # `treasury_internal`. The velocity limit is raised so the day is what runs out.
    pack = policy()
    pack = pack.replace('    daily_usd: "0.15"', '    daily_usd: "0.08"')
    pack = pack.replace("    velocity_60s: 3 ", "    velocity_60s: 99")
    main("budget-exhaustion", story, pack=pack)
