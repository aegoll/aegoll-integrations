"""Claude Agent SDK x402 buying agent.

Bootstraps the shared protocol layer onto `sys.path` before anything else in the
package imports it. `x402_core` is a sibling package in this repo rather than a
published one, and doing this once here keeps every module free of its own path
juggling.
"""

from __future__ import annotations

import sys
from pathlib import Path

# agents/claude_agent_sdk/x402_agent/__init__.py -> claude_agent_sdk -> agents
_X402_CORE = str(Path(__file__).resolve().parents[2] / "x402_core")
if _X402_CORE not in sys.path:
    sys.path.insert(0, _X402_CORE)
