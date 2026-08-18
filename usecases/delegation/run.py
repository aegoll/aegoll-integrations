"""Delegation: a sub-agent can never claim more than its parent.

C5.3, and the case with the sharpest history in this repository. AEGS-0.1-ID-4 says a delegate's
effective authority is the **narrower** of its own and its delegator's. The reference
implementation compared instead of clamping, which is not the same requirement — and the
difference was a live escalation reachable by leaving a field out.

A child that declared a *larger* limit was refused. A child that declared **no** limit was
neither refused nor constrained: there was nothing to compare, and the child had no ceiling of
its own to trip. Declaring nothing was strictly more permissive than declaring a large number.
A $1.00 payment was approved under a parent capped at $0.002.

This case walks all four shapes, including the one that used to escape.

    python usecases/delegation/run.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _harness import Story, main, policy  # noqa: E402


def story(case: Story) -> int:
    case.say("A parent agent spawns sub-agents. Each one's authority is clamped to its")
    case.say("delegator's, and the interesting case is the child that declares nothing.")

    case.heading("1. the parent, capped at $0.50 per action")
    case.gov.register_identity(
        agent_id="parent", controller="acme-ltd", purpose="run the research desk",
        per_action_usd="0.50",
    )
    case.say("  parent registered, per-action ceiling $0.50")

    case.heading("2. four children, four ways of declaring authority")
    children = [
        ("tighter", "0.10", "declares less than its parent"),
        ("equal", "0.50", "declares exactly its parent's ceiling"),
        ("greedy", "5.00", "declares MORE than its parent"),
        ("silent", None, "declares NOTHING -- the one that used to escape"),
    ]
    for name, limit, note in children:
        case.gov.register_identity(
            agent_id=name, controller="acme-ltd", parent_id="parent",
            purpose="a sub-task", per_action_usd=limit,
        )
        declared = f"${limit}" if limit else "no limit"
        case.say(f"  {name:9} {declared:11} {note}")

    case.heading("3. each child tries to spend $1.00")
    case.say("  The parent's ceiling is $0.50, so every one of these must be refused --")
    case.say("  including `silent`, which declared no ceiling to be refused by.")
    case.say()

    from aegoll.engines.evidence import identity as identity_engine
    from aegoll.domain import Vendor

    layer = case.gov._layer
    parent = layer.identities.get("parent")
    refused, escaped = [], []

    for name, _, _ in children:
        request = layer.build_request(
            resource="/research/report", amount_usd="1.00",
            vendor=Vendor(id="data-co", name="data-co"),
        )
        verdict = identity_engine.evaluate(
            request, layer.identities.get(name), now=layer.clock.now(), parent=parent
        )
        codes = sorted({r.code for r in verdict.reasons if r.source == "identity"})
        ok = verdict.verdict.value == "APPROVE"
        (escaped if ok else refused).append(name)
        case.say(f"  {'ESCAPED' if ok else verdict.verdict.value:9} {name:9} "
                 f"{'  '.join(codes) or '(nothing objected)'}")

    case.heading("4. the clamp, stated as numbers")
    from aegoll.engines.evidence.identity import narrower_limit

    for child, parent_limit, label in (
        (100_000, 500_000, "child $0.10, parent $0.50"),
        (5_000_000, 500_000, "child $5.00, parent $0.50"),
        (None, 500_000, "child none,  parent $0.50"),
        (100_000, None, "child $0.10, parent none"),
    ):
        effective = narrower_limit(child, parent_limit)
        shown = f"${effective / 1e6:.2f}" if effective is not None else "no limit"
        case.say(f"  {label:30} -> effective {shown}")
    case.say()
    case.say("  The third line is the one that was wrong. `I declare no limit` is not")
    case.say("  `I am unlimited` when somebody above you declared one.")

    case.heading("5. and a payment through the governed path")
    case.ask(
        label="$1.00 as the silent child", amount_usd="1.00",
        vendor="data-co", resource="/research/report",
    )

    if escaped:
        case.heading("this case failed")
        case.say(f"  These children escaped their parent's ceiling: {escaped}")
        return 1

    return case.finish(expect_refusal_from="treasury")


if __name__ == "__main__":
    # A tight per-transaction ceiling so the final governed call is refused by treasury rather
    # than sailing through -- the identity clamp is demonstrated directly above it.
    main("delegation", story, pack=policy(per_transaction_usd="0.50"))
