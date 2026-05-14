"""Binance USD-M futures adapter stub — fail-closed V2 worker-layer stub.

Every mutation method on :class:`BinanceUsdmAdapter` raises
:class:`BlockedGateNotApprovedError` (code ``BLOCKED_GATE_NOT_APPROVED``)
immediately, before evaluating any argument. The five refused mutation
methods are ``place_order``, ``change_initial_leverage``,
``change_margin_type``, ``change_position_mode``, and ``cancel``.

The two read-only methods (``account_info_v3``, ``position_risk``) are
callable but never make a real exchange call: they return only a
structural presence-of-credentials observation. They never read the
credential *value* into a stored variable; they only check the *presence*
of the env keys ``BINANCE_LIVE_API_KEY`` and ``BINANCE_LIVE_API_SECRET``
as a boolean. They never return, log, echo, or persist the secret value.

The live gate is permanently ``blocked_human_only``. Read-only access
does NOT unlock the gate; no codepath in this module can change the gate.

Legacy baseline:
    claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/
    workers/v2_p2_binance_usdm_adapter_stub_LEGACY_BASELINE_ANALYSIS.md

This worker-layer refusal sits above the API-layer
``LiveBlockGuardMiddleware``
(``v2/backend/app/api/middleware/live_block_guard.py``). To permit live
execution, this stub must be *replaced* by a real adapter — there is no
flag to toggle.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Tuple


ERROR_CODE = "BLOCKED_GATE_NOT_APPROVED"
LIVE_GATE_STATUS = "blocked_human_only"

STATE_DISABLED = "DISABLED"
STATE_BLOCKED = "BLOCKED"
ALLOWED_STUB_STATES: Tuple[str, ...] = (STATE_DISABLED, STATE_BLOCKED)

MUTATION_METHODS: Tuple[str, ...] = (
    "place_order",
    "cancel",
    "change_initial_leverage",
    "change_margin_type",
    "change_position_mode",
)

READ_ONLY_METHODS: Tuple[str, ...] = (
    "account_info_v3",
    "position_risk",
)

CREDENTIAL_ENV_KEYS: Tuple[str, ...] = (
    "BINANCE_LIVE_API_KEY",
    "BINANCE_LIVE_API_SECRET",
)

# Documented audit-only legacy REST paths. The stub never opens a
# network connection to these endpoints; they appear here as audit
# strings so the GUI and audit ledger can link the refusal surface to
# the legacy operation it replaces.
LEGACY_READONLY_REST_PATHS: Tuple[str, ...] = (
    "/fapi/v3/account",
    "/fapi/v2/positionRisk",
)


class BlockedGateNotApprovedError(RuntimeError):
    """Raised by every mutation method on the Binance USD-M adapter stub.

    The ``code`` class attribute is the canonical machine-readable code
    that downstream consumers and the audit ledger key on.
    """

    code: str = ERROR_CODE

    def __init__(self, method: str, *, message: str = "") -> None:
        self.method = method
        super().__init__(
            message
            or f"{ERROR_CODE}: '{method}' refused by Binance USD-M adapter stub"
        )


def credentials_present_in_env() -> bool:
    """Return True iff every credential env key has a non-empty value.

    This function reads the env keys only long enough to compute a
    boolean. The secret value is never assigned to a module-level or
    class-level variable, never returned, and never logged.
    """
    for env_key in CREDENTIAL_ENV_KEYS:
        value = os.environ.get(env_key, "")
        if not value or not value.strip():
            return False
    return True


class BinanceUsdmAdapter:
    """Fail-closed Binance USD-M futures adapter stub.

    Mutation surface:
        * ``place_order`` — raises
        * ``cancel`` — raises
        * ``change_initial_leverage`` — raises
        * ``change_margin_type`` — raises
        * ``change_position_mode`` — raises

    Read-only surface (callable; never makes a real exchange call):
        * ``account_info_v3`` — returns presence-only observation
        * ``position_risk`` — returns presence-only observation

    The class deliberately holds no exchange client attribute and no
    credential value. The accompanying test suite asserts that no
    Binance / ccxt / Redis import — and no exchange-client attribute
    name — is reachable on the module or the instance, and that no
    secret value is ever returned or logged.
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
        self._readonly_call_attempts_total: int = 0
        self._readonly_call_breakdown_by_method: Dict[str, int] = {
            method: 0 for method in READ_ONLY_METHODS
        }

    def _refuse(self, method: str) -> None:
        self._blocked_call_attempts_total += 1
        self._blocked_call_breakdown_by_method[method] = (
            self._blocked_call_breakdown_by_method.get(method, 0) + 1
        )
        raise BlockedGateNotApprovedError(method)

    def _record_readonly(self, method: str) -> None:
        self._readonly_call_attempts_total += 1
        self._readonly_call_breakdown_by_method[method] = (
            self._readonly_call_breakdown_by_method.get(method, 0) + 1
        )

    # -- mutation surface (every method raises immediately) --

    def place_order(self, *_args: Any, **_kwargs: Any) -> None:
        self._refuse("place_order")

    def cancel(self, *_args: Any, **_kwargs: Any) -> None:
        self._refuse("cancel")

    def change_initial_leverage(self, *_args: Any, **_kwargs: Any) -> None:
        self._refuse("change_initial_leverage")

    def change_margin_type(self, *_args: Any, **_kwargs: Any) -> None:
        self._refuse("change_margin_type")

    def change_position_mode(self, *_args: Any, **_kwargs: Any) -> None:
        self._refuse("change_position_mode")

    # -- read-only surface (callable; no real exchange call; no secret returned) --

    def _readonly_observation(self, method: str) -> Dict[str, Any]:
        self._record_readonly(method)
        creds_present = credentials_present_in_env()
        return {
            "method": method,
            "stub_mode": True,
            "exchange_call_taken": False,
            "credentials_present_in_env": creds_present,
            "credentials_returned": False,
            "credentials_logged": False,
            "live_gate": LIVE_GATE_STATUS,
            "live_gate_unlocked_by_this_call": False,
            "snapshot_unavailable_without_credentials": not creds_present,
            "snapshot_unavailable_because_stub_makes_no_exchange_call": True,
        }

    def account_info_v3(self, *_args: Any, **_kwargs: Any) -> Dict[str, Any]:
        return self._readonly_observation("account_info_v3")

    def position_risk(self, *_args: Any, **_kwargs: Any) -> Dict[str, Any]:
        return self._readonly_observation("position_risk")

    # -- observability (no exchange data; only stub state) --

    @property
    def blocked_call_attempts_total(self) -> int:
        return self._blocked_call_attempts_total

    @property
    def blocked_call_breakdown_by_method(self) -> Dict[str, int]:
        return dict(self._blocked_call_breakdown_by_method)

    @property
    def readonly_call_attempts_total(self) -> int:
        return self._readonly_call_attempts_total

    @property
    def readonly_call_breakdown_by_method(self) -> Dict[str, int]:
        return dict(self._readonly_call_breakdown_by_method)

    def state_snapshot(self) -> Dict[str, Any]:
        return {
            "stub_state_one_of_DISABLED_OR_BLOCKED_NEVER_ACTIVE": self.state,
            "allowed_stub_states": list(ALLOWED_STUB_STATES),
            "mutation_methods": list(MUTATION_METHODS),
            "readonly_methods": list(READ_ONLY_METHODS),
            "blocked_call_attempts_total": self._blocked_call_attempts_total,
            "blocked_call_breakdown_by_method": dict(
                self._blocked_call_breakdown_by_method
            ),
            "readonly_call_attempts_total": self._readonly_call_attempts_total,
            "readonly_call_breakdown_by_method": dict(
                self._readonly_call_breakdown_by_method
            ),
            "credentials_present_in_env": credentials_present_in_env(),
            "credential_env_keys_checked": list(CREDENTIAL_ENV_KEYS),
            "credentials_returned_by_any_method": False,
            "credentials_logged_by_any_method": False,
            "live_gate": self.live_gate,
            "live_gate_invariant": LIVE_GATE_STATUS,
            "live_gate_unlocked_by_readonly_access": False,
            "exchange_client_present": False,
            "exchange_call_taken": False,
            "legacy_readonly_rest_paths_documented_only": list(
                LEGACY_READONLY_REST_PATHS
            ),
            "error_code_on_call": ERROR_CODE,
        }
