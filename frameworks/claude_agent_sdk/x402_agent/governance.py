"""Optional AEGL, for this cockpit.

This used to be 409 lines of glue: its own `GovernanceLayer`, its own event
dataclass, its own decision-to-dict translation. All of that now lives in
`aegl.plugin` — because it was never Claude-specific, and while it sat here the
other two agents could not use it.

What is left is the only genuinely host-shaped concern: **AEGL is optional**. If
`aegl` is not importable, this cockpit runs exactly as it did before governance
existed. That keeps the governance layer a layer rather than a dependency, and it
is why `AEGL_AVAILABLE` is checked rather than assumed.

The catalogue helpers below are thin passthroughs so `app.py` and `byok_ui.py`
have one import site to reach for, and degrade to empty lists rather than raising
when AEGL is absent. They add no behaviour of their own.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# aegl lives beside `agents/` in the repo; neither is a published package.
_AEGL_DIR = Path(__file__).resolve().parents[3] / "aegl"

AEGL_AVAILABLE = False
_IMPORT_ERROR: str | None = None

try:
    if str(_AEGL_DIR) not in sys.path:
        sys.path.insert(0, str(_AEGL_DIR))
    from aegl.adapters.x402_python import GovernanceRefused  # noqa: E402,F401
    from aegl.advisors import (  # noqa: E402
        available_models,
        estimate_call_cost_usd,
        providers as advisor_providers,
    )
    from aegl.config import available_bundles  # noqa: E402
    from aegl.plugin import NOT_RECOMMENDED, RECOMMENDED_ADVISOR, Governor  # noqa: E402,F401

    AEGL_AVAILABLE = True
except Exception as exc:  # pragma: no cover - exercised by absence
    _IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
    GovernanceRefused = RuntimeError  # type: ignore[assignment,misc]
    Governor = None  # type: ignore[assignment]
    NOT_RECOMMENDED: dict[str, str] = {}  # type: ignore[no-redef]
    RECOMMENDED_ADVISOR = None  # type: ignore[assignment]


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
