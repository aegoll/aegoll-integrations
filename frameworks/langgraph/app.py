"""LangGraph + OpenAI cockpit.

    agents> .venv\Scripts\streamlit run langgraph\app.py --server.port 8503 --server.address 127.0.0.1

Thin by design: everything visual comes from `cockpit_kit`, so this file holds only
what is genuinely specific to this agent -- which provider options it supports, and
which key it needs.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _sub in (_HERE, _HERE.parent / "x402_core", _HERE.parent / "cockpit_kit"):
    if str(_sub) not in sys.path:
        sys.path.insert(0, str(_sub))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="LangGraph x402 agent", page_icon="🕸", layout="wide")

import langgraph_x402  # noqa: E402
from cockpit_kit import build_cockpit  # noqa: E402

PROVIDERS = {
    "openai": ("gpt-4o-mini", "gpt-4.1-mini", "gpt-4o"),
    "gemini": ("gemini-flash-lite-latest", "gemini-flash-latest", "gemini-3.6-flash"),
}


def key_present(_config) -> bool:
    import os

    # Either provider can drive this harness, so the cockpit is usable if *some*
    # key exists; the run itself reports precisely which one is missing.
    return bool(
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
    )


build_cockpit(
    langgraph_x402,
    title="LangGraph x402 agent",
    caption=(
        "`create_react_agent` from `langgraph.prebuilt`, buying market data over "
        "x402. LangGraph ships a step ceiling but **no cost ceiling** -- the only "
        "money guard here is the x402 spend cap."
    ),
    key_name="OPENAI_API_KEY",
    key_present=key_present,
    provider_options=PROVIDERS,
)
