"""Governance is optional by design, and absent by accident is a different thing.

Every agent here runs ungoverned if `tesoro` is not importable, and that is deliberate — it
is what makes the layer a *layer* rather than a dependency. The cost of that design is this:
**absence is indistinguishable from breakage** unless something checks.

It was broken. `frameworks/claude_agent_sdk/x402_agent/governance.py` resolved
`parents[3] / "aegl"` — the prototype's layout, where the layer sat beside `agents/` in one
repository. That path does not exist here, so the import failed, `AEGL_AVAILABLE` stayed
`False`, and the agent ran with no governance at all. Nothing failed. No test noticed. The
suite was green.

That is PLAN.md F-C1 for the third time: a path that resolves to nothing does not raise, it
quietly means *no*.

So these tests assert the **positive**: with `tesoro` installed, governance is live. They are
the reason the ungoverned state cannot come back silently — and they fail loudly rather than
skip, because a skip here would reproduce exactly the failure they exist to catch.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENTS_DIR = Path(__file__).resolve().parents[1]
for sub in ("claude_agent_sdk", "x402_core"):
    p = str(AGENTS_DIR / sub)
    if p not in sys.path:
        sys.path.insert(0, p)


def test_tesoro_is_installed():
    """The premise of every test below. From PyPI, not from a sibling checkout.

    Two version lines, because they answer different questions: `__version__` is what the
    implementation is, and the AEGS version is which specification it implements. A record
    carrying only the first cannot be audited later.

    The spec version is read from `tesoro.record` rather than the top level, because **0.1.0
    shipped without exporting it** -- `tesoro.AEGS_VERSION` raises `AttributeError` even though
    PLAN.md W0.7 claims it. Found by this test, on its first run. Tighten this to the top-level
    name once 0.1.1 is out; asserting it now would be asserting against a package that does not
    exist yet.
    """
    import tesoro
    from tesoro.record import AEGS_VERSION

    assert tesoro.__version__, "tesoro is importable but reports no version"
    assert AEGS_VERSION, "no specification version"


def test_tesoro_is_not_being_imported_from_a_sibling_checkout():
    """An example that only works from one directory layout is not an example.

    The whole defect this file exists for came from resolving a path instead of installing a
    package. If the import is satisfied by `../tesoro/src`, these tests would pass here and
    fail for every user — which is the same class of lie, one level up.
    """
    import tesoro

    location = Path(tesoro.__file__).resolve()
    repo_parent = Path(__file__).resolve().parents[2]
    assert repo_parent not in location.parents, (
        f"tesoro is being imported from {location}, inside the workspace at {repo_parent}. "
        "Install it (`pip install tesoro`) rather than reaching for a checkout."
    )


def test_the_claude_agent_reports_governance_as_available():
    """The exact assertion whose absence let the agent run ungoverned."""
    from x402_agent import governance

    assert governance.TESORO_AVAILABLE is True, (
        f"governance is not available, so this agent runs ungoverned: "
        f"{governance.import_error()}"
    )
    assert governance.import_error() is None
    assert governance.Governor is not None, "no Governor class to govern with"


def test_the_agent_can_see_real_policies():
    """Available is not the same as usable. A governance layer that reports itself present
    and offers no policy would satisfy the test above and govern nothing."""
    from x402_agent import governance

    policies = governance.list_policies()
    assert policies, "governance is available but names no policy packs"
    assert "default" in policies, policies


def test_a_governor_actually_refuses_something():
    """The load-bearing test in this file.

    Importable, configured, and offering policies still does not prove it *governs*. A spend
    cap that has never refused anything has not been demonstrated — so this asks for a payment
    far outside the starter pack's ceilings and requires a non-approval.
    """
    from x402_agent.governance import Governor

    governor = Governor(policy="default", advisor=None)
    try:
        decision = governor.tesoro.decide(
            governor.tesoro.build_request(
                resource="/expensive",
                amount_usd="5000",
                vendor=_a_vendor(),
            )
        )
        assert not decision.approved, "a $5000 payment was approved by the starter policy"
        assert decision.attributed_control, "a refusal with no attributable cause"
    finally:
        governor.close()


def test_the_run_guard_is_inert_without_a_governor():
    """The other half of the contract, and why absence is a supported state at all.

    `RunGuard(None)` must allow everything, so an agent written against it behaves exactly as
    it did before governance existed. If this ever started refusing, "optional" would be false
    and every ungoverned example would break.
    """
    from x402_core import RunGuard

    guard = RunGuard(None, budget_usd=0.40)
    assert guard.active is False
    assert guard.authorize(model="m", provider="p") == (True, "")
    assert guard.check(999_999.0) is False


def _a_vendor():
    from tesoro import Vendor

    return Vendor(id="test-seller", name="test-seller")
