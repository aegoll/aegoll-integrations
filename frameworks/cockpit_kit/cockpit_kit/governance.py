"""Optional AEGL, for the cockpits built by this kit.

The split this file sits on: **hosts wire AEGL up, agents do not**. The LangGraph
and ADK agent packages never import `aegoll` — they accept a duck-typed governor via
`x402_core.RunGuard`. The cockpit is the host, so it is allowed to know AEGL exists,
construct a `Governor`, and hand it in.

Deliberately a near-copy of `claude_agent_sdk/x402_agent/governance.py`. A shared
shim would have to live in a package both hosts import, and the only candidate is
`x402_core` — which must stay ignorant of governance, or the protocol layer starts
depending on the layer above it. Two ~50-line shims that each handle absence
independently is the cheaper price.

If `aegoll` is not importable, `available()` is False and every cockpit runs exactly
as it did before governance existed.
"""

from __future__ import annotations

from typing import Any

# `aegoll` is an installed package, found the way any consumer finds it. The
# prototype did
#
#     _AEGL_DIR = Path(__file__).resolve().parents[3] / "aegl"
#     sys.path.insert(0, str(_AEGL_DIR))
#
# because the layer sat beside `agents/` in one repository and neither was
# published. Every example here pins `aegoll` from PyPI instead: an example that
# only works from a particular checkout layout is not an example.

AEGL_AVAILABLE = False
_IMPORT_ERROR: str | None = None

try:
    from aegoll import ui as aegl_ui
    from aegoll import ui_keys as aegl_ui_keys
    from aegoll.advisors import available_models, estimate_call_cost_usd
    from aegoll.config import available_bundles
    from aegoll.plugin import NOT_RECOMMENDED, Governor

    AEGL_AVAILABLE = True
except Exception as exc:  # pragma: no cover - exercised by absence
    _IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
    aegl_ui = None  # type: ignore[assignment]
    aegl_ui_keys = None  # type: ignore[assignment]
    Governor = None  # type: ignore[assignment]
    NOT_RECOMMENDED: dict[str, str] = {}  # type: ignore[no-redef]


def available() -> bool:
    return AEGL_AVAILABLE


def import_error() -> str | None:
    return _IMPORT_ERROR


def policies() -> list[str]:
    return [p.stem for p in available_bundles()] if AEGL_AVAILABLE else []


def advisors() -> list[tuple[str, str]]:
    """Every (provider, model) with a usable key, cheapest first."""
    return available_models() if AEGL_AVAILABLE else []


def advisor_cost(model: str) -> float:
    return estimate_call_cost_usd(model) if AEGL_AVAILABLE else 0.0


def advisor_warning(model: str) -> str | None:
    """Whether a model was measured as unusable for advice. See aegoll `docs/eval.md`."""
    return NOT_RECOMMENDED.get(model) if AEGL_AVAILABLE else None


def build(
    policy: str | None,
    advisor: tuple[str, str] | None,
    framework: str | None = None,
) -> Any:
    """The cockpit's `Governor`.

    `advisor=None` is passed through rather than as `"auto"`: the user chose
    deterministic-only, and an explicit choice must not be silently upgraded into
    a model call.

    `framework` stamps each journalled decision, which is what lets the AEGL
    cockpit show every framework on one page. It is a label, not `agent_id` --
    treasury envelopes are agent-scoped, so using `agent_id` would split one
    shared budget into one per framework as a side effect.
    """
    if not AEGL_AVAILABLE:
        raise RuntimeError(
            "aegoll is not importable, so the cockpit cannot govern anything: "
            f"{_IMPORT_ERROR}\n  pip install aegoll"
        )
    return Governor(policy=policy, advisor=advisor, framework=framework)


def apply_session_keys() -> None:
    """Reload BYOK keys held in this browser session.

    Must run before anything reads a key -- Streamlit reruns the whole script on
    every interaction, so without it the key store reflects only whichever rerun
    last touched the form.
    """
    if aegl_ui_keys is not None:
        aegl_ui_keys.apply_session_keys()


def render_keys() -> None:
    """The BYOK panel that ships with AEGL. Same panel in every cockpit."""
    if aegl_ui_keys is not None:
        aegl_ui_keys.render()


def render(report: dict[str, Any] | None) -> None:
    """The panel that ships with AEGL. Identical call in every cockpit."""
    if aegl_ui is None:  # pragma: no cover - exercised by absence
        import streamlit as st

        st.info("AEGL is not installed, so there is nothing to govern with.")
        return
    aegl_ui.render(report)
