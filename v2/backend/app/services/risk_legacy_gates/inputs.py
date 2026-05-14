from __future__ import annotations

from dataclasses import dataclass

from .errors import RiskLegacyGatesServiceError


_KILL_SWITCH_SCOPES = frozenset({"", "GLOBAL", "ACCOUNT", "SYMBOL"})
_HALT_CODES = frozenset(
    {"", "kill_switch_active", "fail_storm", "mu_breach_sustained"}
)
_CLOSE_GUARD_ACTIONS = frozenset(
    {"", "allow_close", "defer_close", "emergency_bypass"}
)
_ADL_CAP_BREACHES = frozenset({"", "account", "mu", "symbol"})
_BUDGET_BLOCK_CODES = frozenset(
    {"", "cadence", "max_symbols", "reversal", "emergency_margin"}
)
_MARGIN_VERDICT_ACTIONS = frozenset(
    {"", "allow", "block_account", "block_symbol", "deleverage"}
)
_PHASE_RAMP_BREACHES = frozenset(
    {
        "",
        "max_mu",
        "min_free_margin_ratio",
        "max_positions",
        "per_symbol_margin",
        "equity_missing_or_nan",
    }
)


def _check_bool(value: object, *, field: str) -> None:
    if not isinstance(value, bool):
        raise RiskLegacyGatesServiceError("must_be_bool", field=field)


def _check_str(value: object, *, field: str) -> None:
    if not isinstance(value, str):
        raise RiskLegacyGatesServiceError("must_be_str", field=field)


def _check_str_in(value: object, allowed: frozenset, *, field: str) -> None:
    _check_str(value, field=field)
    if value not in allowed:
        raise RiskLegacyGatesServiceError("invalid_value", field=field)


def _check_finite_float(value: object, *, field: str) -> None:
    if isinstance(value, bool):
        raise RiskLegacyGatesServiceError("must_be_float", field=field)
    if not isinstance(value, (int, float)):
        raise RiskLegacyGatesServiceError("must_be_float", field=field)
    f = float(value)
    if f != f:
        raise RiskLegacyGatesServiceError("must_not_be_nan", field=field)
    if f in (float("inf"), float("-inf")):
        raise RiskLegacyGatesServiceError("must_be_finite", field=field)


@dataclass(frozen=True, slots=True)
class KillSwitchState:
    evidence_present: bool
    active: bool
    scope: str
    payload_corrupt: bool
    account: str
    account_query: str
    symbol: str
    symbol_query: str

    def __post_init__(self) -> None:
        _check_bool(self.evidence_present, field="evidence_present")
        _check_bool(self.active, field="active")
        _check_str(self.scope, field="scope")
        scope = self.scope.upper()
        if scope not in _KILL_SWITCH_SCOPES:
            scope = "UNKNOWN"
        object.__setattr__(self, "scope", scope)
        _check_bool(self.payload_corrupt, field="payload_corrupt")
        _check_str(self.account, field="account")
        _check_str(self.account_query, field="account_query")
        _check_str(self.symbol, field="symbol")
        _check_str(self.symbol_query, field="symbol_query")


@dataclass(frozen=True, slots=True)
class HaltState:
    evidence_present: bool
    halted: bool
    halt_code: str

    def __post_init__(self) -> None:
        _check_bool(self.evidence_present, field="evidence_present")
        _check_bool(self.halted, field="halted")
        _check_str_in(self.halt_code, _HALT_CODES, field="halt_code")
        if self.halted and self.halt_code == "":
            raise RiskLegacyGatesServiceError(
                "halt_code_required_when_halted", field="halt_code"
            )


@dataclass(frozen=True, slots=True)
class LatchState:
    evidence_present: bool
    latch_active: bool
    is_risk_add: bool

    def __post_init__(self) -> None:
        _check_bool(self.evidence_present, field="evidence_present")
        _check_bool(self.latch_active, field="latch_active")
        _check_bool(self.is_risk_add, field="is_risk_add")


@dataclass(frozen=True, slots=True)
class CloseGuardState:
    evidence_present: bool
    guard_action: str

    def __post_init__(self) -> None:
        _check_bool(self.evidence_present, field="evidence_present")
        _check_str_in(
            self.guard_action, _CLOSE_GUARD_ACTIONS, field="guard_action"
        )
        if self.evidence_present and self.guard_action == "":
            raise RiskLegacyGatesServiceError(
                "guard_action_required_when_evidence_present",
                field="guard_action",
            )


@dataclass(frozen=True, slots=True)
class AutoDeleveragerState:
    evidence_present: bool
    cap_breach: str

    def __post_init__(self) -> None:
        _check_bool(self.evidence_present, field="evidence_present")
        _check_str_in(
            self.cap_breach, _ADL_CAP_BREACHES, field="cap_breach"
        )


@dataclass(frozen=True, slots=True)
class BudgetState:
    evidence_present: bool
    is_risk_add: bool
    is_reduce: bool
    block_code: str

    def __post_init__(self) -> None:
        _check_bool(self.evidence_present, field="evidence_present")
        _check_bool(self.is_risk_add, field="is_risk_add")
        _check_bool(self.is_reduce, field="is_reduce")
        _check_str_in(
            self.block_code, _BUDGET_BLOCK_CODES, field="block_code"
        )


@dataclass(frozen=True, slots=True)
class MarginGovernorState:
    evidence_present: bool
    verdict_action: str

    def __post_init__(self) -> None:
        _check_bool(self.evidence_present, field="evidence_present")
        _check_str_in(
            self.verdict_action,
            _MARGIN_VERDICT_ACTIONS,
            field="verdict_action",
        )
        if self.evidence_present and self.verdict_action == "":
            raise RiskLegacyGatesServiceError(
                "verdict_action_required_when_evidence_present",
                field="verdict_action",
            )


@dataclass(frozen=True, slots=True)
class PhaseGateState:
    evidence_present: bool
    ramp_limit_breach: str

    def __post_init__(self) -> None:
        _check_bool(self.evidence_present, field="evidence_present")
        _check_str_in(
            self.ramp_limit_breach,
            _PHASE_RAMP_BREACHES,
            field="ramp_limit_breach",
        )


@dataclass(frozen=True, slots=True)
class ToxicityState:
    evidence_present: bool
    is_risk_add: bool
    score: float
    extreme_threshold: float

    def __post_init__(self) -> None:
        _check_bool(self.evidence_present, field="evidence_present")
        _check_bool(self.is_risk_add, field="is_risk_add")
        _check_finite_float(self.score, field="score")
        _check_finite_float(
            self.extreme_threshold, field="extreme_threshold"
        )
        if float(self.score) < 0.0 or float(self.score) > 1.0:
            raise RiskLegacyGatesServiceError(
                "must_be_between_0_and_1", field="score"
            )
        if (
            float(self.extreme_threshold) < 0.0
            or float(self.extreme_threshold) > 1.0
        ):
            raise RiskLegacyGatesServiceError(
                "must_be_between_0_and_1", field="extreme_threshold"
            )
