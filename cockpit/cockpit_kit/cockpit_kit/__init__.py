"""Shared Streamlit cockpit for framework-diverse x402 agents.

One UI implementation, three agents. An agent only has to expose `FRAMEWORK`,
`PROVIDER`, `DEFAULT_MODEL`, `MODELS` and an async `run()` generator; everything
else -- wallet, run controls, transcript, receipts, purchased data, history -- comes
from here.
"""

from .app import build_cockpit
from .runner import stream_agent

__all__ = ["build_cockpit", "stream_agent"]
__version__ = "0.1.0"
