"""Intent drift: the purchase every other control approves.

C5.2, and the case that justifies having an intent engine at all.

An agent is sent to buy market data. Later — repurposed, prompt-injected, or just wrong — it
buys a follower count instead. **Same amount. Same counterparty. Same resource shape.** Every
economic control is satisfied, because economically nothing is wrong: it is one cent to a
counterparty with the same trust score as a moment ago, well inside every envelope.

Treasury says yes. Trust says yes. Risk says yes. Policy says yes.

Only intent knows what the agent was *sent to do*, and it is the only control that can object.
That is the whole argument for declaring intent up front: without it, "spending within budget"
and "doing the job" are the same question, and they are not.

    python usecases/intent-drift/run.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _harness import Story, main  # noqa: E402


def story(case: Story) -> int:
    case.say(__doc__.strip().split("\n\n")[1])

    case.heading("1. the agent declares what it was sent to do")
    intent_id = case.gov.declare_intent(
        purpose="collect market pricing data for the morning report",
        budget_usd="10",
        expires_in_s=3600,
        resources=["/market/snapshot", "/market/depth"],
    )
    case.say(f"  intent {intent_id}")
    case.say("  budget $10.00, scope: /market/snapshot, /market/depth")

    case.heading("2. it does the job")
    for resource in ("/market/snapshot", "/market/depth"):
        decision = case.ask(
            label=resource, amount_usd=10_000, vendor="data-co", resource=resource
        )
        if decision.approved:
            case.settle(decision, success=True)

    case.heading("3. it drifts")
    case.say("  Identical amount. Identical counterparty. Nothing economic has changed.")
    case.say()
    drifted = case.ask(
        label="/social/followers", amount_usd=10_000, vendor="data-co",
        resource="/social/followers",
    )

    case.heading("4. what each control thought")
    case.say("  This is the part worth reading. The refusal is not a budget problem, and no")
    case.say("  amount of tightening a budget would have caught it.")
    case.say()
    budget = drifted.budget
    case.say(f"  treasury : ok={budget.ok}  binding={budget.binding or 'nothing'}")
    case.say(f"  trust    : {drifted.trust.value:.4f}  {list(drifted.trust.flags) or 'no flags'}")
    case.say(f"  risk     : {drifted.risk.value:.4f}  {list(drifted.risk.flags) or 'no flags'}")
    case.say(f"  policy   : matched rule {drifted.matched_rule!r}")
    case.say(f"  intent   : {drifted.reason}")
    case.say()
    case.say(f"  attributed to: {drifted.attributed_control}")

    case.heading("5. and revoking the intent removes the authority")
    case.say("  Not deleting the record of it having been granted -- revoking is an event, and")
    case.say("  the journal keeps both.")
    case.say()
    case.gov.revoke_intent(intent_id)
    case.ask(
        label="/market/snapshot (after revoke)", amount_usd=10_000, vendor="data-co",
        resource="/market/snapshot",
    )

    return case.finish(expect_refusal_from="intent")


if __name__ == "__main__":
    main("intent-drift", story)
