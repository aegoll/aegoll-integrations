"""Shared Streamlit cockpit for framework-diverse x402 agents.

One UI implementation, three agents. An agent only has to expose `FRAMEWORK`,
`PROVIDER`, `DEFAULT_MODEL`, `MODELS` and an async `run()` generator; everything
else -- wallet, run controls, transcript, receipts, purchased data, history -- comes
from here.
"""

# `build_cockpit` and `stream_agent` are resolved on first attribute access rather than
# imported here, because `.app` imports Streamlit at module scope.
#
# Importing them eagerly made `from cockpit_kit import governance` -- the *governance shim*,
# whose own imports are `typing` and nothing else -- require the UI framework. The shim exists
# so a cockpit degrades to ungoverned when AEGL is missing, and the test proving it does that
# could not run without Streamlit installed. A decoupling boundary that only holds when every
# optional dependency is present is not a boundary.
#
# PEP 562. The public surface is unchanged; `dir()` and both names still work.

__all__ = ["build_cockpit", "stream_agent"]
__version__ = "0.1.0"

_LAZY = {"build_cockpit": ".app", "stream_agent": ".runner"}


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module, __name__), name)
    globals()[name] = value  # imported once, not on every access
    return value


def __dir__() -> list:
    return sorted(set(globals()) | set(_LAZY))
