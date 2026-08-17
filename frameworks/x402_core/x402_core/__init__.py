"""x402 protocol layer: wallet, the six operations, and shared telemetry.

Framework-agnostic and provider-agnostic by design. It knows how to pay for data
over x402 and nothing about how an agent decides to. Three agents built on three
different harnesses depend on this; none depends on another.
"""

from .buyer import PaidCall, PaymentFailed, Quote, SpendCapExceeded, X402Buyer
from .governance import RunGuard
from .config import (
    EXPLORER_TX,
    FAUCET_URL,
    NETWORK,
    REPO_ROOT,
    USDC_ADDRESS,
    WalletConfig,
    load_env,
    load_wallet_config,
)
from .telemetry import (
    PRICING,
    RunTelemetry,
    append_run,
    cost_usd,
    run_history,
    total_spend_usd,
)
from .toolset import (
    DEFAULT_TASK,
    DESCRIPTIONS,
    SYSTEM_PROMPT,
    TOOL_NAMES,
    ToolCall,
    X402Toolset,
    build_buyer,
)

__all__ = [
    "DEFAULT_TASK",
    "DESCRIPTIONS",
    "EXPLORER_TX",
    "FAUCET_URL",
    "NETWORK",
    "PRICING",
    "PaidCall",
    "PaymentFailed",
    "Quote",
    "REPO_ROOT",
    "RunGuard",
    "RunTelemetry",
    "SYSTEM_PROMPT",
    "SpendCapExceeded",
    "TOOL_NAMES",
    "ToolCall",
    "USDC_ADDRESS",
    "WalletConfig",
    "X402Buyer",
    "X402Toolset",
    "append_run",
    "build_buyer",
    "cost_usd",
    "load_env",
    "load_wallet_config",
    "run_history",
    "total_spend_usd",
]

__version__ = "0.1.0"
