"""Optional AEGL, for this cockpit.

This used to be 409 lines of glue: its own `GovernanceLayer`, its own event
dataclass, its own decision-to-dict translation. All of that now lives in
`tesoro.plugin` — because it was never Claude-specific, and while it sat here the
other two agents could not use it.

What is left is the only genuinely host-shaped concern: **tesoro is optional**. If
`tesoro` is not importable, this cockpit runs exactly as it did before governance
existed. That keeps the governance layer a layer rather than a dependency, and it
is why `TESORO_AVAILABLE` is checked rather than assumed.

The catalogue helpers below are thin passthroughs so `app.py` and `byok_ui.py`
have one import site to reach for, and degrade to empty lists rather than raising
when tesoro is absent. They add no behaviour of their own.
"""

from __future__ import annotations

from typing import Any

# `tesoro` is an installed package, found the way any consumer finds it:
#
#     pip install tesoro
#
# The prototype did
#
#     _AEGL_DIR = Path(__file__).resolve().parents[3] / "aegl"
#     sys.path.insert(0, str(_AEGL_DIR))
#
# because the layer sat beside `agents/` in one repository and neither was published. That
# path resolves to nothing here, so the import failed, `AEGL_AVAILABLE` stayed False, and
# **this agent ran ungoverned** -- silently, because absence is a supported state. Nothing
# failed and no test noticed, which is PLAN.md F-C1 for the third time: a path that resolves
# to nothing does not raise, it just quietly means "no".
#
# An example that only works from one checkout layout is not an example.

TESORO_AVAILABLE = False
_IMPORT_ERROR: str | None = None

try:
    from tesoro.adapters.x402_python import GovernanceRefused  # noqa: F401
    from tesoro.advisors import (
        available_models,
        estimate_call_cost_usd,
        providers as advisor_providers,
    )
    from tesoro.config import available_bundles
    from tesoro.plugin import NOT_RECOMMENDED, RECOMMENDED_ADVISOR, Governor  # noqa: F401

    TESORO_AVAILABLE = True
except ModuleNotFoundError as exc:  # pragma: no cover - exercised by absence
    # Narrowed from `except Exception`, and restricted to `tesoro` itself. The sibling shim in
    # `cockpit_kit` caught an unrelated `ModuleNotFoundError` from a UI module and turned
    # governance off over it. `except Exception` here would do the same for any import-time
    # failure inside an installed `tesoro`: a broken governance layer would read as an absent
    # one, and the agent would run ungoverned. Absent degrades; broken raises.
    if (exc.name or "").split(".")[0] != "tesoro":
        raise
    _IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
    GovernanceRefused = RuntimeError  # type: ignore[assignment,misc]
    Governor = None  # type: ignore[assignment]
    NOT_RECOMMENDED: dict[str, str] = {}  # type: ignore[no-redef]
    RECOMMENDED_ADVISOR = None  # type: ignore[assignment]

#: The old name, kept so a reader of the prototype's code finds what they expect. Governance
#: being optional is deliberate and stays; what changed is that its absence now means the
#: package is not installed, rather than a hardcoded path having gone stale.
AEGL_AVAILABLE = TESORO_AVAILABLE


def import_error() -> str | None:
    return _IMPORT_ERROR


def list_policies() -> list[str]:
    if not AEGL_AVAILABLE:
        return []
    return [p.stem for p in available_bundles()]


def list_advisors() -> list[tuple[str, str]]:
    """Every (provider, model) pair with a usable key, cheapest first."""
    if not AEGL_AVAILABLE:
        return []
    return available_models()


def advisor_catalogue() -> list[dict[str, Any]]:
    """Provider metadata for the BYOK panel: key presence, models, source."""
    if not AEGL_AVAILABLE:
        return []
    return [p.as_dict() for p in advisor_providers()]


def advisor_cost(model: str) -> float:
    return estimate_call_cost_usd(model) if AEGL_AVAILABLE else 0.0


def advisor_warning(model: str) -> str | None:
    """Whether a model was measured as unusable for advice. See `aegl/EVAL.md`."""
    return NOT_RECOMMENDED.get(model) if AEGL_AVAILABLE else None


def build_layer(policy: str | None, advisor: tuple[str, str] | None) -> Any:
    """The cockpit's `Governor`, or None when AEGL is not installed.

    `advisor=None` here means the user chose deterministic-only, so it is passed
    through as-is rather than as `"auto"` — an explicit choice must not be
    silently upgraded into a model call.
    """
    if not AEGL_AVAILABLE:
        raise RuntimeError(f"aegl is not importable: {_IMPORT_ERROR}")
    return Governor(policy=policy, advisor=advisor, framework="claude-agent-sdk")
