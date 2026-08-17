"""Optional governance, duck-typed.

Every agent here can be handed a governor object and will then ask permission
before spending — but **no agent imports the governance layer**. They call four
methods on whatever they are given:

    authorize_run(model=, provider=, budget_usd=)  -> has .allowed
    wrap(client)                                   -> a governed payment client
    check_spend(spent_usd)                         -> has .should_stop
    settle_run(actual_cost_usd)

`aegl.plugin.Governor` satisfies that, and so could anything else. Keeping it
structural is the point: if the agents imported `aegl`, "AEGL is a plugin you can
install" would be indistinguishable from "AEGL is a dependency these agents were
built around". `tests/test_decoupling.py` asserts the import never appears.

`RunGuard(None)` is inert, so an ungoverned run costs one attribute check per step
and behaves exactly as it did before.
"""

from __future__ import annotations

from typing import Any


class RunGuard:
    """Wraps an optional governor so agent loops need no `if governor:` branches."""

    def __init__(self, governor: Any | None = None, *, budget_usd: float | None = None):
        self.governor = governor
        self.budget_usd = budget_usd
        self.authorization: Any | None = None
        self.stop: Any | None = None

    @property
    def active(self) -> bool:
        return self.governor is not None

    # --- internal channel: the agent's own token spend --------------------
    def authorize(self, *, model: str, provider: str) -> tuple[bool, str]:
        """Ask permission to start. Returns (allowed, reason-if-not).

        Ungoverned, or governed with no budget named, this always allows — a
        governor should not invent a ceiling the caller never asked for.
        """
        if not self.active or self.budget_usd is None:
            return True, ""
        auth = self.governor.authorize_run(
            model=model, provider=provider, budget_usd=self.budget_usd
        )
        self.authorization = auth
        if auth.allowed:
            return True, ""
        reasons = "; ".join(auth.decision.explain()) if hasattr(auth, "decision") else ""
        return False, (
            f"governance refused this run's token budget of "
            f"${self.budget_usd:.4f} ({auth.decision.verdict.value}). {reasons}"
        )

    def check(self, spent_usd: float) -> bool:
        """The mid-run cost ceiling. True means stop now.

        Call once per step. LangGraph and Google ADK cap *steps*, not spend, and
        one long-context call can cost more than fifty short ones — so without
        this there is nothing between a runaway agent and its provider bill.
        """
        if not self.active or self.authorization is None:
            return False
        result = self.governor.check_spend(spent_usd)
        if result.should_stop:
            self.stop = result
            return True
        return False

    def settle(self, actual_cost_usd: float) -> None:
        if self.active and self.authorization is not None:
            self.governor.settle_run(actual_cost_usd)

    # --- external channel: USDC over x402 ---------------------------------
    def wrap(self, client: Any) -> Any:
        """Put the payment client behind the governor, if there is one."""
        return self.governor.wrap(client) if self.active else client

    @property
    def stop_reason(self) -> str:
        return "aegl_spend_ceiling" if self.stop is not None else ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "governed": self.active,
            "budgetUsd": self.budget_usd,
            "authorized": bool(self.authorization and self.authorization.allowed),
            "stopped": self.stop.as_dict() if self.stop is not None else None,
        }
