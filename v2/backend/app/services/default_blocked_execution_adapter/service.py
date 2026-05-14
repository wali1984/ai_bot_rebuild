"""Default blocked execution adapter — fail-closed V2 worker-layer stub.

Every mutation method on :class:`DefaultBlockedExecutionAdapter` raises
:class:`BlockedGateNotApprovedError` (code ``BLOCKED_GATE_NOT_APPROVED``)
immediately. The adapter holds no exchange client; the module has no
Binance, ccxt, or Redis imports; the public surface is intentionally
incapable of placing, cancelling, leverage-changing, or
margin-mode-changing an order on any exchange.

Legacy baseline:
    claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/
    workers/v2_p2_default_blocked_execution_adapter_stub_LEGACY_BASELINE_ANALYSIS.md

This worker-layer refusal sits *above* the API-layer
``LiveBlockGuardMiddleware`` (``v2/backend/app/api/middleware/live_block_guard.py``).
The live gate is permanently ``blocked_human_only``; this module exposes
no codepath that can flip it. To permit live execution, a real adapter
must *replace* this class — there is no flag to toggle.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple


ERROR_CODE = "BLOCKED_GATE_NOT_APPROVED"
LIVE_GATE_STATUS = "blocked_human_only"

STATE_DISABLED = "DISABLED"
STATE_BLOCKED = "BLOCKED"
ALLOWED_STUB_STATES: Tuple[str, ...] = (STATE_DISABLED, STATE_BLOCKED)

MUTATION_METHODS: Tuple[str, ...] = (
    "place_order",
    "cancel",
    "change_leverage",
    "change_margin_mode",
)


class BlockedGateNotApprovedError(RuntimeError):
    """Raised by every mutation method on the default blocked adapter.

    The ``code`` class attribute is the canonical machine-readable code
    that downstream consumers and the audit ledger key on.
    """

    code: str = ERROR_CODE

    def __init__(self, method: str, *, message: str = "") -> None:
        self.method = method
        super().__init__(
            message
            or f"{ERROR_CODE}: '{method}' refused by default blocked execution adapter"
        )


class DefaultBlockedExecutionAdapter:
    """Fail-closed execution adapter stub.

    The adapter is constructed in the ``DISABLED`` state and cannot
    transition to ``ACTIVE``. Every mutation method raises
    :class:`BlockedGateNotApprovedError` before evaluating any
    argument. Counters are incremented inside the refusal path so the
    GUI and audit ledger can observe attempted invocations.

    The class deliberately holds no exchange client attribute. The
    accompanying test suite asserts that no Binance, ccxt, or Redis
    import — and no exchange-client attribute name — is reachable.
    """

    state: str = STATE_DISABLED
    live_gate: str = LIVE_GATE_STATUS

    def __init__(self) -> None:
        if self.state not in ALLOWED_STUB_STATES:
            raise BlockedGateNotApprovedError(
                "__init__",
                message=(
                    f"{ERROR_CODE}: stub state must be one of "
                    f"{ALLOWED_STUB_STATES}, got {self.state!r}"
                ),
            )
        self._blocked_call_attempts_total: int = 0
        self._blocked_call_breakdown_by_method: Dict[str, int] = {
            method: 0 for method in MUTATION_METHODS
        }

    def _refuse(self, method: str) -> None:
        self._blocked_call_attempts_total += 1
        self._blocked_call_breakdown_by_method[method] = (
            self._blocked_call_breakdown_by_method.get(method, 0) + 1
        )
        raise BlockedGateNotApprovedError(method)

    # -- mutation surface (every method raises immediately) --

    def place_order(self, *_args: Any, **_kwargs: Any) -> None:
        self._refuse("place_order")

    def cancel(self, *_args: Any, **_kwargs: Any) -> None:
        self._refuse("cancel")

    def change_leverage(self, *_args: Any, **_kwargs: Any) -> None:
        self._refuse("change_leverage")

    def change_margin_mode(self, *_args: Any, **_kwargs: Any) -> None:
        self._refuse("change_margin_mode")

    # -- observability (no exchange data; only stub state) --

    @property
    def blocked_call_attempts_total(self) -> int:
        return self._blocked_call_attempts_total

    @property
    def blocked_call_breakdown_by_method(self) -> Dict[str, int]:
        return dict(self._blocked_call_breakdown_by_method)

    def state_snapshot(self) -> Dict[str, Any]:
        return {
            "stub_state_one_of_DISABLED_OR_BLOCKED_NEVER_ACTIVE": self.state,
            "allowed_stub_states": list(ALLOWED_STUB_STATES),
            "mutation_methods": list(MUTATION_METHODS),
            "blocked_call_attempts_total": self._blocked_call_attempts_total,
            "blocked_call_breakdown_by_method": dict(
                self._blocked_call_breakdown_by_method
            ),
            "live_gate": self.live_gate,
            "live_gate_invariant": LIVE_GATE_STATUS,
            "exchange_client_present": False,
            "error_code_on_call": ERROR_CODE,
        }
