"""x402 buyer -- re-exported from the shared protocol layer.

This module used to hold its own copy of the buyer. That copy and
`x402_core/buyer.py` were byte-identical, which is the worst place in the repo to
carry a fork: two implementations of the code that signs payments.

The implementation now lives in `x402_core`, which every agent shares and no agent
owns. The names are re-exported here so existing imports keep working.
"""

from __future__ import annotations

# `x402_agent/__init__.py` puts the shared protocol layer on the path.
from x402_core.buyer import (  # noqa: F401
    PaidCall,
    PaymentFailed,
    Quote,
    SpendCapExceeded,
    X402Buyer,
    atomic_to_usd,
)

__all__ = [
    "PaidCall",
    "PaymentFailed",
    "Quote",
    "SpendCapExceeded",
    "X402Buyer",
    "atomic_to_usd",
]
