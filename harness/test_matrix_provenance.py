"""The measurement harness: does it import, and does every number carry its provenance?

Two things, and the first is embarrassing enough to state plainly.

**`matrix.py` was unimportable.** It resolved the agents under `harness/` — `HERE / "x402_core"`
and so on — which is where they sat in the prototype's single-repository layout and is nowhere
here. So `import matrix` raised `ModuleNotFoundError` and had done since the port, because nothing
imported it. PLAN.md F-C1 for the fifth time: a path that resolves to nothing does not raise when
you append it to `sys.path`, it just quietly fails to help.

**Every result must be stamped** (C6.6). Nothing recorded which policy bundle a measurement ran
against, which is the mistake the prototype's own plan says it learned the hard way — a rule change
would silently invalidate every stored figure with no way to notice.

These two tests are cheap and would both have caught a real failure that shipped.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def test_the_matrix_imports_at_all():
    """The whole sweep is unreachable if this fails, and it did fail, for days."""
    import matrix

    assert callable(matrix.run_cell)
    assert matrix.FRAMEWORKS, "no frameworks declared"


def test_every_path_the_matrix_adds_actually_exists():
    """Asserted in the module itself, and asserted again here so the reason is visible.

    A stale entry on `sys.path` is not an error, it is a no-op — which is exactly why the layout
    could change and nothing complain. The assertions in `matrix._SEARCH` turn silence into a
    failure; this test is what makes sure those assertions are still there.
    """
    import matrix

    assert matrix._SEARCH, "the search table is empty, so nothing is being checked"
    for name, path in matrix._SEARCH.items():
        assert path.is_dir(), f"{name} -> {path} does not exist"


def test_every_measurement_carries_its_provenance():
    """C6.6. A number with no provenance is an anecdote with a decimal point."""
    import matrix

    stamp = matrix.provenance()

    assert stamp["tesoro"], "no implementation version"
    assert stamp["aegs"], "no specification version"
    assert stamp["measuredAt"].endswith("+00:00"), "not UTC, so not comparable across runs"

    policy = stamp["policy"]
    assert policy["name"], "no policy name"
    assert len(policy["hash"]) >= 32, (
        f"the policy hash is {len(policy['hash'])} characters. A label can be reused across "
        "edited rules; a hash cannot, which is the whole reason it is stamped."
    )


def test_the_stamp_changes_when_the_policy_changes(tmp_path, monkeypatch):
    """The property that makes the stamp worth having.

    If two different packs produced the same stamp, a rule change would be invisible in the
    results — which is the failure C6.6 exists to prevent, not a hypothetical one.
    """
    import matrix
    from importlib import resources

    original = (resources.files("tesoro") / "policies" / "default.yaml").read_text(
        encoding="utf-8"
    )
    edited = original.replace('daily_usd: "50"', 'daily_usd: "49"')
    assert edited != original, "the substitution matched nothing, so this test proves nothing"

    pack = tmp_path / "edited.yaml"
    pack.write_text(edited, encoding="utf-8")

    before = matrix.provenance()["policy"]["hash"]
    after = matrix.provenance(str(pack))["policy"]["hash"]

    assert before != after, (
        "editing a rule did not change the policy hash, so a stamped measurement cannot tell "
        "you which rules produced it"
    )


def test_a_missing_policy_raises_rather_than_stamping_a_hole():
    """A stamp with a hole in it invites exactly the interpretation it exists to prevent.

    Degrading to `policy: null` here would let a measurement be published as though its
    provenance were known, which is worse than refusing to produce one.
    """
    import matrix

    with pytest.raises(Exception):
        matrix.provenance("/nonexistent/policy.yaml")
