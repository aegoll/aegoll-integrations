"""Google ADK + Gemini cockpit.

    agents> .venv\Scripts\streamlit run google_adk\app.py --server.port 8504 --server.address 127.0.0.1

ADK ships its own developer UI (`adk web`) for inspecting agents and traces. This
is a different thing: it shows x402 receipts, the USDC ledger and the data actually
purchased, which a framework dev tool has no reason to know about.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _sub in (_HERE, _HERE.parent / "x402_core", _HERE.parent / "cockpit_kit"):
    if str(_sub) not in sys.path:
        sys.path.insert(0, str(_sub))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="Google ADK x402 agent", page_icon="🔷", layout="wide")

import adk_x402  # noqa: E402
from cockpit_kit import build_cockpit  # noqa: E402


def key_present(_config) -> bool:
    import os

    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


build_cockpit(
    adk_x402,
    title="Google ADK x402 agent",
    caption=(
        "`google.adk.agents.Agent` with `InMemoryRunner`, buying market data over "
        "x402. ADK ships a call ceiling but **no cost ceiling** -- the only money "
        "guard here is the x402 spend cap."
    ),
    key_name="GEMINI_API_KEY",
    key_present=key_present,
)
