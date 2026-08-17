"""Configuration for the Python buyer agent.

Reads the repo-root `.env` so this agent shares one wallet and one seller URL
with the TypeScript agent in `src/reference-buyer/`. Nothing is duplicated: the same
variable names documented in `.env.example` are used here.

Runtime knobs (model, budgets, retries) are deliberately *not* env vars — they
are controls in the Streamlit UI, with the defaults below.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

# agents/claude_agent_sdk/x402_agent/config.py -> ... -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
ROOT_ENV = REPO_ROOT / ".env"
LOCAL_ENV = REPO_ROOT / "agents" / "claude_agent_sdk" / ".env"

# Root first, then an optional agent-py/.env that may override it.
load_dotenv(ROOT_ENV)
load_dotenv(LOCAL_ENV, override=True)

# --- chain constants, mirrored from src/shared/config.ts -------------------
NETWORK = "eip155:84532"  # Base Sepolia, CAIP-2
CHAIN_ID = 84532
USDC_ADDRESS = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
USDC_DECIMALS = 6
FAUCET_URL = "https://faucet.circle.com"
EXPLORER_TX = "https://sepolia.basescan.org/tx/"

# --- LLM defaults ---------------------------------------------------------
# Haiku 4.5: $1 / MTok input, $5 / MTok output, 200K context.
DEFAULT_MODEL = "claude-haiku-4-5"
MODEL_CHOICES = [
    "claude-haiku-4-5",
    "claude-sonnet-5",
    "claude-opus-5",
]

# Per-run ceiling handed to the Agent SDK as `max_budget_usd`.
# A measured full run (catalogue -> quote -> 2-3 purchases -> written answer) on
# Haiku 4.5 costs roughly $0.015-0.025, so $0.02 truncates the task about half
# the time. $0.04 leaves headroom without burning the lifetime cap.
DEFAULT_RUN_BUDGET_USD = 0.04
# Cumulative ceiling across every run, persisted to disk (the $0.25 testing cap).
DEFAULT_TOTAL_BUDGET_USD = 0.25
DEFAULT_MAX_TURNS = 12
DEFAULT_MAX_RETRIES = 2
DEFAULT_API_TIMEOUT_MS = 120_000

# Where cumulative LLM spend is journalled so the cap survives restarts.
SPEND_LEDGER_PATH = REPO_ROOT / "agents" / "claude_agent_sdk" / ".spend-ledger.json"


def _optional_decimal(name: str, fallback: str) -> Decimal:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return Decimal(fallback)
    try:
        return Decimal(raw.strip())
    except Exception:
        return Decimal(fallback)


@dataclass(frozen=True)
class AgentConfig:
    """Everything the agent needs that comes from the environment."""

    anthropic_api_key: str | None
    buyer_private_key: str | None
    seller_address: str | None
    data_api_url: str
    rpc_url: str
    usdc_cap_usd: Decimal

    @property
    def wallet_configured(self) -> bool:
        """True when BUYER_PRIVATE_KEY looks like a real 32-byte key.

        The repo ships `BUYER_PRIVATE_KEY=0x` as a stub, which would blow up
        deep inside eth_account with an unhelpful error.
        """
        key = self.buyer_private_key
        if not key:
            return False
        body = key[2:] if key.startswith(("0x", "0X")) else key
        if len(body) != 64:
            return False
        try:
            int(body, 16)
        except ValueError:
            return False
        return int(body, 16) != 0


def load_config() -> AgentConfig:
    key = os.environ.get("BUYER_PRIVATE_KEY", "").strip()
    if key and not key.startswith(("0x", "0X")):
        key = "0x" + key

    seller = (os.environ.get("SELLER_ADDRESS") or "").strip()
    if seller and int(seller, 16) == 0:
        seller = ""  # the shipped placeholder is the zero address

    return AgentConfig(
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        buyer_private_key=key or None,
        seller_address=seller or None,
        data_api_url=(os.environ.get("DATA_API_URL") or "http://localhost:4021").rstrip("/"),
        rpc_url=os.environ.get("BASE_SEPOLIA_RPC_URL") or "https://sepolia.base.org",
        usdc_cap_usd=_optional_decimal("AGENT_SPEND_CAP_USD", "0.05"),
    )
