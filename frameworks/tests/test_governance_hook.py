"""The governance hook every agent shares, and the import it must never make.

`RunGuard` is how an agent accepts governance without depending on it. These tests
use a stub governor, so they prove the *contract* rather than any particular
implementation of it -- which is what "universal plugin" has to mean.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

AGENTS_DIR = Path(__file__).resolve().parents[1]

#: The cockpit kit left `frameworks/` for `cockpit/` when the package shed its UI
#: (PLAN.md A2, C4). Asserted rather than assumed: a path that resolves to nothing makes
#: a scanning test pass by checking zero files. See PLAN.md F-C1.
COCKPIT_KIT = AGENTS_DIR.parent / "cockpit" / "cockpit_kit" / "cockpit_kit"
assert COCKPIT_KIT.is_dir(), f"{COCKPIT_KIT} is not there; the layout changed"
for sub in ("x402_core",):
    p = str(AGENTS_DIR / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

from x402_core import RunGuard  # noqa: E402


class StubCheck:
    def __init__(self, should_stop: bool) -> None:
        self.should_stop = should_stop

    def as_dict(self) -> dict:
        return {"shouldStop": self.should_stop}


class StubAuth:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed
        self.decision = self


class StubGovernor:
    """The four calls an agent makes, and nothing else.

    Deliberately not `aegl.plugin.Governor`: if these tests passed only against
    the real one, the surface would be a shared implementation rather than a
    contract anything can satisfy.
    """

    def __init__(self, *, allow: bool = True, stop_at: float | None = None) -> None:
        self.allow = allow
        self.stop_at = stop_at
        self.authorized: dict | None = None
        self.settled: float | None = None
        self.wrapped: object | None = None
        self.checks: list[float] = []

    def authorize_run(self, *, model, provider, budget_usd):
        self.authorized = {"model": model, "provider": provider, "budget": budget_usd}
        return StubAuth(self.allow)

    def wrap(self, client):
        self.wrapped = client
        return ("governed", client)

    def check_spend(self, spent_usd):
        self.checks.append(spent_usd)
        return StubCheck(self.stop_at is not None and spent_usd >= self.stop_at)

    def settle_run(self, actual_cost_usd):
        self.settled = actual_cost_usd


# --- ungoverned runs must be untouched ------------------------------------


def test_an_absent_governor_is_completely_inert():
    """Adding the hook must not change how an ungoverned agent behaves."""
    guard = RunGuard(None)
    assert guard.active is False
    assert guard.authorize(model="m", provider="p") == (True, "")
    assert guard.check(9_999.0) is False
    assert guard.wrap("buyer") == "buyer"  # the raw client, not a wrapper
    guard.settle(1.0)  # must not raise


def test_a_governor_with_no_budget_does_not_invent_a_ceiling():
    """`budget_usd=None` means the caller named no ceiling. Do not fabricate one."""
    gov = StubGovernor(stop_at=0.0)
    guard = RunGuard(gov, budget_usd=None)

    assert guard.authorize(model="m", provider="p") == (True, "")
    assert gov.authorized is None, "authorized a run the caller never budgeted"
    assert guard.check(500.0) is False, "enforced a ceiling that was never set"


# --- the internal channel -------------------------------------------------


def test_a_refused_run_reports_why():
    class Refused(StubAuth):
        def __init__(self):
            super().__init__(False)
            self.verdict = type("V", (), {"value": "REJECT"})()

        def explain(self):
            return ["[treasury/envelope] daily envelope exhausted"]

    gov = StubGovernor(allow=False)
    gov.authorize_run = lambda **kw: Refused()
    guard = RunGuard(gov, budget_usd=0.04)

    allowed, reason = guard.authorize(model="m", provider="p")
    assert allowed is False
    assert "REJECT" in reason and "daily envelope exhausted" in reason


def test_the_governor_is_told_which_provider_is_being_billed():
    """Providers are separate counterparties; conflating them corrupts history."""
    gov = StubGovernor()
    RunGuard(gov, budget_usd=0.04).authorize(model="gpt-4o-mini", provider="openai")
    assert gov.authorized == {
        "model": "gpt-4o-mini", "provider": "openai", "budget": 0.04
    }


# --- the mid-run ceiling: what the frameworks lack ------------------------


def test_the_ceiling_stops_the_run_once_spend_passes_it():
    gov = StubGovernor(stop_at=0.03)
    guard = RunGuard(gov, budget_usd=0.03)
    guard.authorize(model="m", provider="p")

    assert guard.check(0.01) is False
    assert guard.check(0.029) is False
    assert guard.check(0.03) is True
    assert guard.stop_reason == "aegl_spend_ceiling"


def test_no_ceiling_applies_before_a_run_is_authorized():
    """A check before `authorize()` has nothing to compare against."""
    guard = RunGuard(StubGovernor(stop_at=0.0), budget_usd=0.03)
    assert guard.check(99.0) is False


def test_the_run_settles_what_was_actually_spent():
    gov = StubGovernor()
    guard = RunGuard(gov, budget_usd=0.04)
    guard.authorize(model="m", provider="p")
    guard.settle(0.0123)
    assert gov.settled == pytest.approx(0.0123)


def test_an_unauthorized_run_settles_nothing():
    """Nothing was reserved, so there is nothing to settle."""
    gov = StubGovernor()
    guard = RunGuard(gov, budget_usd=None)
    guard.settle(0.05)
    assert gov.settled is None


# --- the external channel -------------------------------------------------


def test_the_payment_client_is_handed_to_the_governor():
    gov = StubGovernor()
    guard = RunGuard(gov, budget_usd=0.04)
    wrapped = guard.wrap("raw-buyer")
    assert gov.wrapped == "raw-buyer"
    assert wrapped != "raw-buyer", "the agent kept an ungoverned handle on the signer"


def test_the_report_says_whether_the_run_was_governed():
    gov = StubGovernor(stop_at=0.01)
    guard = RunGuard(gov, budget_usd=0.04)
    guard.authorize(model="m", provider="p")
    guard.check(0.02)

    report = guard.as_dict()
    assert report["governed"] is True
    assert report["authorized"] is True
    assert report["stopped"] == {"shouldStop": True}


# --- the structural claim -------------------------------------------------


AGENT_PACKAGES = {
    "langgraph": AGENTS_DIR / "langgraph" / "langgraph_x402",
    "google_adk": AGENTS_DIR / "google_adk" / "adk_x402",
}


@pytest.mark.parametrize("name", sorted(AGENT_PACKAGES))
def test_a_governed_agent_still_does_not_import_the_governance_layer(name):
    """The whole claim in one assertion.

    If these agents imported `aegl`, "AEGL is a plugin you can install into any
    framework" would be indistinguishable from "AEGL is a dependency these agents
    were built around". They accept a governor; they never reach for one.

    The Claude agent is excluded on purpose, and stays excluded. It is AEGL's
    *host*: it owns the sidebar that picks a policy and an advisor, the
    unjournalled pre-check that warns before a run starts, and the human-override
    flow. Those need the `Governor` itself, not the four-method subset `RunGuard`
    models, so it imports `aegl.plugin` and `aegl.ui` directly.

    The asymmetry is the point rather than a gap: one host wires AEGL up, and two
    agents get governed without knowing AEGL exists.
    """
    offenders = []
    for path in AGENT_PACKAGES[name].rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for module in names:
                if module.split(".")[0] == "aegl":
                    offenders.append(f"{path.name}:{node.lineno} imports {module}")

    assert not offenders, (
        f"the {name} agent depends on the governance layer:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("name", sorted(AGENT_PACKAGES))
def test_every_agent_accepts_a_governor_and_a_budget(name):
    """One surface, or the comparison between frameworks is not like-for-like."""
    import importlib

    sys.path.insert(0, str(AGENT_PACKAGES[name].parent))
    module = importlib.import_module(f"{AGENT_PACKAGES[name].name}.agent")
    params = module.run.__code__.co_varnames[: module.run.__code__.co_argcount]
    assert "governor" in params, f"{name}.run() cannot be governed"
    assert "budget_usd" in params, f"{name}.run() takes no cost ceiling"


def test_the_guard_itself_imports_no_governance_layer():
    """`RunGuard` lives in the protocol layer and must stay ignorant of AEGL."""
    source = AGENTS_DIR / "x402_core" / "x402_core" / "governance.py"
    text = source.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            assert all(a.name.split(".")[0] != "aegl" for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] != "aegl"


# --- the cockpit host wires what the agents accept ------------------------
#
# Two sides of one contract, and nothing else checks they still match: the
# cockpit sends `governor=` and `budget_usd=`, the agents declare them. A rename
# on either side would fail only when a user pressed Run under governance, which
# is the worst place to find out.


def test_the_cockpit_sends_exactly_the_kwargs_the_agents_declare():
    import ast

    source = COCKPIT_KIT / "app.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))

    # Collect the string keys assigned into `kwargs[...]` in build_cockpit.
    sent = {
        node.slice.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "kwargs"
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    }
    assert {"governor", "budget_usd"} <= sent, (
        f"the cockpit no longer hands governance to the agent; it sends {sorted(sent)}"
    )

    import importlib

    # Only the governance kwargs are checked against *every* agent. `provider` is
    # sent conditionally, when an app passes `provider_options` -- LangGraph is
    # provider-agnostic, ADK is Gemini-only, and that asymmetry is correct.
    governance_kwargs = {"governor", "budget_usd"}
    for name, pkg in AGENT_PACKAGES.items():
        sys.path.insert(0, str(pkg.parent))
        module = importlib.import_module(f"{pkg.name}.agent")
        params = set(module.run.__code__.co_varnames[: module.run.__code__.co_argcount])
        missing = governance_kwargs - params
        assert not missing, f"{name}.run() would reject {sorted(missing)} from the cockpit"


def test_a_broken_governance_layer_raises_rather_than_reading_as_absent(tmp_path):
    """Absent degrades to ungoverned. Broken must not.

    The shims caught `Exception` around their `tesoro` imports, so an installed governance
    layer that failed to import for any reason -- a missing dependency of its own, a syntax
    error, an import-time assertion -- set `AEGL_AVAILABLE = False` and the host carried on
    with no spend control. That is the four-states rule applied to the layer itself: *absent*
    and *broken* are different, and only one of them is safe to continue on.

    Shadowing the real package with one that raises on import is the honest way to produce the
    broken case; monkeypatching a flag would test the flag, not the guard.
    """
    import subprocess
    import textwrap

    shadow = tmp_path / "shadow"
    (shadow / "tesoro").mkdir(parents=True)
    (shadow / "tesoro" / "__init__.py").write_text(
        "import a_dependency_that_is_not_installed", encoding="utf-8"
    )

    code = textwrap.dedent(
        """
        import sys
        sys.path.insert(0, sys.argv[1])   # the broken tesoro, ahead of the real one
        sys.path.insert(0, sys.argv[2])   # cockpit_kit
        try:
            from cockpit_kit import governance
        except ModuleNotFoundError as exc:
            print("RAISED", exc.name)
        else:
            print("DEGRADED", governance.available(), governance.import_error())
        """
    )
    done = subprocess.run(
        [sys.executable, "-c", code, str(shadow), str(COCKPIT_KIT.parent)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = done.stdout.strip()
    assert out.startswith("RAISED"), f"a broken tesoro was treated as absent: {out or done.stderr}"
    assert "a_dependency_that_is_not_installed" in out


def test_the_governance_shim_imports_without_the_ui_framework():
    """The shim must not drag Streamlit in.

    `cockpit_kit/__init__.py` used to import `.app` eagerly, so importing the governance
    shim required Streamlit -- and the test below, which proves a cockpit degrades to
    ungoverned rather than crashing, could not run in the `decoupling` CI job at all. It
    errored on a missing UI dependency and read as a governance failure.

    Run in a subprocess because the check is *what got imported*, and this process has
    already imported plenty. Asserting on `sys.modules` in-process would pass or fail on
    test ordering.
    """
    import subprocess

    code = (
        "import sys; sys.path.insert(0, %r);"
        "from cockpit_kit import governance;"
        "assert 'streamlit' not in sys.modules, sorted(m for m in sys.modules if 'stream' in m);"
        "assert hasattr(governance, 'AEGL_AVAILABLE');"
        "print('clean')" % str(COCKPIT_KIT.parent)
    )
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert done.returncode == 0, done.stderr
    assert "clean" in done.stdout


def test_the_lazy_names_still_resolve():
    """Laziness must not remove the public surface it was hiding."""
    sys.path.insert(0, str(COCKPIT_KIT.parent))
    pytest.importorskip("streamlit", reason="build_cockpit needs the UI framework by design")
    import cockpit_kit

    assert callable(cockpit_kit.build_cockpit)
    assert callable(cockpit_kit.stream_agent)
    assert "build_cockpit" in dir(cockpit_kit)


def test_the_cockpit_shim_degrades_when_aegl_is_absent(monkeypatch):
    """A cockpit must run ungoverned if AEGL is not installed, not crash."""
    sys.path.insert(0, str(COCKPIT_KIT.parent))
    from cockpit_kit import governance as shim

    monkeypatch.setattr(shim, "AEGL_AVAILABLE", False)
    assert shim.available() is False
    assert shim.policies() == []
    assert shim.advisors() == []
    assert shim.advisor_cost("anything") == 0.0
    assert shim.advisor_warning("llama-3.1-8b-instant") is None
    with pytest.raises(RuntimeError):
        shim.build(None, None)


def test_the_cockpit_shim_finds_aegl_here():
    """And when it *is* installed, it must actually find it."""
    sys.path.insert(0, str(COCKPIT_KIT.parent))
    from cockpit_kit import governance as shim

    assert shim.available(), f"cockpit cannot import aegl: {shim.import_error()}"
    assert "default" in shim.policies()
    assert shim.advisor_warning("llama-3.1-8b-instant"), "the D2 warning is not surfaced"
    gov = shim.build("default", None)
    try:
        assert gov.bundle.name == "default"
    finally:
        gov.close()


def test_the_byok_panel_is_not_duplicated():
    """One key panel, shipped with AEGL.

    It used to live in the Claude cockpit, where the other three hosts could not
    reach it -- the same shape of problem as the duplicated buyer. A second copy
    is how the security properties (mask-only rendering, explicit persistence,
    newline refusal) drift apart between hosts.
    """
    claude = AGENTS_DIR / "claude_agent_sdk" / "x402_agent"
    assert not (claude / "byok_ui.py").exists(), "the key panel was duplicated again"

    app = (claude / "app.py").read_text(encoding="utf-8")
    assert "ui_keys" in app, "the Claude cockpit no longer offers key entry"

    kit = (COCKPIT_KIT / "governance.py").read_text(
        encoding="utf-8"
    )
    assert "ui_keys" in kit, "the shared cockpits no longer offer key entry"
