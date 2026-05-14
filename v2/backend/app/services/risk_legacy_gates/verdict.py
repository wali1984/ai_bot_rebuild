from __future__ import annotations

from dataclasses import dataclass

from .errors import RiskLegacyGatesServiceError


GATE_NAME_KILL_SWITCH = "kill_switch"
GATE_NAME_HALT_MANAGER = "halt_manager"
GATE_NAME_REDUCE_ONLY_LATCH = "reduce_only_latch"
GATE_NAME_INTELLIGENT_CLOSE_GUARD = "intelligent_close_guard"
GATE_NAME_AUTO_DELEVERAGER = "auto_deleverager"
GATE_NAME_SHARED_RISK_GATE = "shared_risk_gate"
GATE_NAME_MARGIN_GOVERNOR = "margin_governor"
GATE_NAME_PHASE_CONTROLLER = "phase_controller"
GATE_NAME_MICROSTRUCTURE_TOXICITY = "microstructure_toxicity"

LEGACY_GATE_ACTION_ALLOW = "allow"
LEGACY_GATE_ACTION_DENY = "deny"
LEGACY_GATE_ACTION_CLOSE_ONLY = "close_only"

_ALLOWED_GATE_NAMES = frozenset(
    {
        GATE_NAME_KILL_SWITCH,
        GATE_NAME_HALT_MANAGER,
        GATE_NAME_REDUCE_ONLY_LATCH,
        GATE_NAME_INTELLIGENT_CLOSE_GUARD,
        GATE_NAME_AUTO_DELEVERAGER,
        GATE_NAME_SHARED_RISK_GATE,
        GATE_NAME_MARGIN_GOVERNOR,
        GATE_NAME_PHASE_CONTROLLER,
        GATE_NAME_MICROSTRUCTURE_TOXICITY,
    }
)

_ALLOWED_ACTIONS = frozenset(
    {
        LEGACY_GATE_ACTION_ALLOW,
        LEGACY_GATE_ACTION_DENY,
        LEGACY_GATE_ACTION_CLOSE_ONLY,
    }
)

LEGACY_GATE_REASON_CODES = frozenset(
    {
        "allow_kill_switch_inactive",
        "deny_kill_switch_active_global",
        "deny_kill_switch_active_account",
        "deny_kill_switch_active_symbol",
        "deny_kill_switch_corrupt",
        "deny_kill_switch_evidence_missing",
        "allow_halt_inactive",
        "deny_halt_active",
        "deny_halt_fail_storm",
        "deny_halt_mu_breach_sustained",
        "deny_halt_evidence_missing",
        "allow_latch_inactive",
        "close_only_latch_active",
        "deny_latch_evidence_missing",
        "allow_close_guard_allow_close",
        "deny_close_guard_defer_close",
        "close_only_close_guard_emergency_bypass",
        "deny_close_guard_evidence_missing",
        "allow_adl_inactive",
        "close_only_adl_account_cap_breach",
        "close_only_adl_mu_cap_breach",
        "close_only_adl_symbol_cap_breach",
        "deny_adl_evidence_missing",
        "allow_budget_within_limits",
        "deny_budget_cadence_block",
        "deny_budget_max_symbols_block",
        "deny_budget_reversal_block",
        "deny_budget_emergency_margin_block",
        "deny_budget_evidence_missing",
        "allow_margin_within_caps",
        "deny_margin_account_breach",
        "deny_margin_symbol_breach",
        "close_only_margin_deleverage_required",
        "deny_margin_evidence_missing",
        "allow_phase_within_ramp_limits",
        "deny_phase_max_mu_exceeded",
        "deny_phase_min_free_margin_violated",
        "deny_phase_max_positions_exceeded",
        "deny_phase_per_symbol_margin_exceeded",
        "deny_phase_equity_missing_or_nan",
        "deny_phase_evidence_missing",
        "allow_toxicity_within_threshold",
        "deny_toxicity_extreme_block",
        "deny_toxicity_evidence_missing",
    }
)


@dataclass(frozen=True, slots=True)
class LegacyGateVerdict:
    gate_name: str
    action: str
    reason_code: str
    legacy_source_path: str
    legacy_source_sha256: str
    evaluated_at_ms: int
    live_blocked: bool

    def __post_init__(self) -> None:
        if not isinstance(self.gate_name, str):
            raise RiskLegacyGatesServiceError("must_be_str", field="gate_name")
        if self.gate_name not in _ALLOWED_GATE_NAMES:
            raise RiskLegacyGatesServiceError(
                "invalid_gate_name", field="gate_name"
            )
        if not isinstance(self.action, str):
            raise RiskLegacyGatesServiceError("must_be_str", field="action")
        if self.action not in _ALLOWED_ACTIONS:
            raise RiskLegacyGatesServiceError("invalid_action", field="action")
        if not isinstance(self.reason_code, str):
            raise RiskLegacyGatesServiceError("must_be_str", field="reason_code")
        if self.reason_code not in LEGACY_GATE_REASON_CODES:
            raise RiskLegacyGatesServiceError(
                "invalid_reason_code", field="reason_code"
            )
        if self.action == LEGACY_GATE_ACTION_ALLOW:
            if not self.reason_code.startswith("allow_"):
                raise RiskLegacyGatesServiceError(
                    "allow_requires_allow_prefix_reason", field="reason_code"
                )
        elif self.action == LEGACY_GATE_ACTION_DENY:
            if not self.reason_code.startswith("deny_"):
                raise RiskLegacyGatesServiceError(
                    "deny_requires_deny_prefix_reason", field="reason_code"
                )
        elif self.action == LEGACY_GATE_ACTION_CLOSE_ONLY:
            if not self.reason_code.startswith("close_only_"):
                raise RiskLegacyGatesServiceError(
                    "close_only_requires_close_only_prefix_reason",
                    field="reason_code",
                )
        if not isinstance(self.legacy_source_path, str):
            raise RiskLegacyGatesServiceError(
                "must_be_str", field="legacy_source_path"
            )
        if self.legacy_source_path == "":
            raise RiskLegacyGatesServiceError(
                "must_be_non_empty", field="legacy_source_path"
            )
        if not isinstance(self.legacy_source_sha256, str):
            raise RiskLegacyGatesServiceError(
                "must_be_str", field="legacy_source_sha256"
            )
        if len(self.legacy_source_sha256) != 64:
            raise RiskLegacyGatesServiceError(
                "must_be_64_hex_chars", field="legacy_source_sha256"
            )
        for ch in self.legacy_source_sha256:
            if ch not in "0123456789abcdef":
                raise RiskLegacyGatesServiceError(
                    "must_be_lowercase_hex", field="legacy_source_sha256"
                )
        if not isinstance(self.evaluated_at_ms, int) or isinstance(
            self.evaluated_at_ms, bool
        ):
            raise RiskLegacyGatesServiceError(
                "must_be_int", field="evaluated_at_ms"
            )
        if self.evaluated_at_ms < 0:
            raise RiskLegacyGatesServiceError(
                "must_be_nonnegative", field="evaluated_at_ms"
            )
        if not isinstance(self.live_blocked, bool):
            raise RiskLegacyGatesServiceError(
                "must_be_bool", field="live_blocked"
            )
        if self.live_blocked is not True:
            raise RiskLegacyGatesServiceError(
                "must_be_true", field="live_blocked"
            )
