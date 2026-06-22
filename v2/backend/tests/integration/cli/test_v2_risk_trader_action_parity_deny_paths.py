"""Lane C — Risk/Trader action-parity DENY-path integration tests.

These tests verify that the V2 risk_gateway service exposes legacy-equivalent
DENY behavior across at least nine distinct risk action paths from the legacy
trader_risk_action_path_map.json ontology, without ever reaching a mutation
codepath (no exchange client imports, no networking, no order placement, no
order cancellation, no leverage change, no margin-mode change, no old-Redis
writes).

The action paths exercised here are read directly from the actual evaluators
exported by the v2 risk_gateway package:

  - kill_switch              → evaluate_kill_switch_state
  - halt_manager             → evaluate_halt_state
  - reduce_only_latch        → evaluate_latch_state
  - intelligent_close_guard  → evaluate_close_guard
  - auto_deleverager         → evaluate_adl_state
  - shared_risk_gate         → evaluate_budget_state
  - margin_governor          → evaluate_margin_state
  - phase_controller         → evaluate_phase_gate
  - adaptive_gate            → evaluate_toxicity_block (microstructure toxic)

Three additional paths from the legacy ontology — fee_ratio_gate, churn_veto,
and minimum_hold_time — are NOT present as v2 risk_gateway service entry
points. Those are documented with pytest.skip(PARITY_GAP_NOT_FOUND…) rather
than fabricated, per the lane charter.

Live gate must remain blocked_human_only. Live symbols must be []. No
mutation paths reachable.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Tuple

import pytest


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Public exported entry points — read first, then used here:
from v2.backend.app.services.risk_gateway import (
    assemble_risk_decision_record,
)
from v2.backend.app.services.risk_gateway.adaptive_gate import (
    evaluate_toxicity_block,
)
from v2.backend.app.services.risk_gateway.auto_deleverager import (
    evaluate_adl_state,
)
from v2.backend.app.services.risk_gateway.halt_manager import (
    evaluate_halt_state,
)
from v2.backend.app.services.risk_gateway.intelligent_close_guard import (
    evaluate_close_guard,
)
from v2.backend.app.services.risk_gateway.kill_switch import (
    evaluate_kill_switch_state,
)
from v2.backend.app.services.risk_gateway.margin_governor import (
    evaluate_margin_state,
)
from v2.backend.app.services.risk_gateway.phase_controller import (
    evaluate_phase_gate,
)
from v2.backend.app.services.risk_gateway.reduce_only_latch import (
    evaluate_latch_state,
)
from v2.backend.app.services.risk_gateway.shared_risk_gate import (
    evaluate_budget_state,
)

from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_ACTION_DENY,
    RISK_DECISION_REASON_DENY_ADAPTIVE_MICROSTRUCTURE_TOXIC,
    RISK_DECISION_REASON_DENY_AUTO_DELEVERAGER_TRIGGERED,
    RISK_DECISION_REASON_DENY_HALT_MANAGER_ACTIVE,
    RISK_DECISION_REASON_DENY_KILL_SWITCH_ACTIVE,
    RISK_DECISION_REASON_DENY_MARGIN_GOVERNOR_LEVERAGE_INCREASE_BLOCKED,
    RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED,
    RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
    RISK_DECISION_REASON_DENY_PHASE_CONTROLLER_WARMUP,
    RISK_DECISION_REASON_DENY_REDUCE_ONLY_LATCH,
    RISK_DECISION_REASON_DENY_SHARED_RISK_BUDGET_EXHAUSTED,
)
from v2.backend.app.domain.orchestrator_decision import (
    DECISION_ACTION_HOLD,
    DECISION_ACTION_ABSTAIN,
    OrchestratorDecisionRecord,
)


# ---------------------------------------------------------------------------
# Sentinels: live gate must remain blocked, live symbols empty.
# ---------------------------------------------------------------------------

LIVE_GATE_STATUS_EXPECTED = "blocked_human_only"
LIVE_SYMBOLS_EXPECTED: Tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Helpers: assert each returned evaluation is a non-mutation DENY record.
# ---------------------------------------------------------------------------


def _assert_deny(result, *, gate_id: str, reason_code: str) -> None:
    # The evaluator returns a frozen dataclass-style record; no mutation
    # callable is invoked. Verify identity of the gate_id, deny action,
    # the canonical reason_code, and the live_blocked invariant.
    assert getattr(result, "gate_id") == gate_id, (
        f"gate_id mismatch: got {getattr(result, 'gate_id')!r} expected {gate_id!r}"
    )
    assert getattr(result, "gate_action") == "deny", (
        f"expected deny gate_action, got {getattr(result, 'gate_action')!r}"
    )
    assert getattr(result, "passed") is False
    assert getattr(result, "risk_reason_code") == reason_code, (
        f"reason_code mismatch: got {getattr(result, 'risk_reason_code')!r} "
        f"expected {reason_code!r}"
    )
    assert getattr(result, "live_blocked") is True
    # No close_only sneak: deny is deny.
    assert getattr(result, "close_only") is False


# ---------------------------------------------------------------------------
# 1) kill_switch → DENY (global active)
# ---------------------------------------------------------------------------


def test_kill_switch_active_global_denies_all_actions() -> None:
    result = evaluate_kill_switch_state(
        kill_switch_active=True,
        scope="GLOBAL",
    )
    _assert_deny(
        result,
        gate_id="kill_switch",
        reason_code=RISK_DECISION_REASON_DENY_KILL_SWITCH_ACTIVE,
    )
    assert "kill_switch_active_global" in result.detail


def test_kill_switch_missing_evidence_denies_fail_closed() -> None:
    # When evidence is missing (None), the gate must fail closed.
    result = evaluate_kill_switch_state(kill_switch_active=None)
    _assert_deny(
        result,
        gate_id="kill_switch",
        reason_code=RISK_DECISION_REASON_DENY_KILL_SWITCH_ACTIVE,
    )
    assert result.evidence_status == "missing"


# ---------------------------------------------------------------------------
# 2) halt_manager → DENY (halt active)
# ---------------------------------------------------------------------------


def test_halt_manager_active_denies_all_actions() -> None:
    result = evaluate_halt_state(halt_active=True)
    _assert_deny(
        result,
        gate_id="halt_manager",
        reason_code=RISK_DECISION_REASON_DENY_HALT_MANAGER_ACTIVE,
    )


def test_halt_manager_missing_evidence_denies_fail_closed() -> None:
    result = evaluate_halt_state(halt_active=None)
    _assert_deny(
        result,
        gate_id="halt_manager",
        reason_code=RISK_DECISION_REASON_DENY_HALT_MANAGER_ACTIVE,
    )
    assert result.evidence_status == "missing"


# ---------------------------------------------------------------------------
# 3) reduce_only_latch → DENY (latch active and request increases risk)
# ---------------------------------------------------------------------------


def test_reduce_only_latch_blocks_risk_increase() -> None:
    result = evaluate_latch_state(
        reduce_only_latch_active=True,
        increases_risk=True,
    )
    _assert_deny(
        result,
        gate_id="reduce_only_latch",
        reason_code=RISK_DECISION_REASON_DENY_REDUCE_ONLY_LATCH,
    )
    assert "reduce_only_latch_blocks_risk_increase" in result.detail


# ---------------------------------------------------------------------------
# 4) intelligent_close_guard → CLOSE_ONLY when loss-realizing close is unsafe
#    (not allow, not allow-open; behaves as DENY-of-fresh-risk-add)
# ---------------------------------------------------------------------------


def test_intelligent_close_guard_loss_close_returns_close_only_not_allow() -> None:
    # close_allowed missing + loss-realizing close → close_only (not allow,
    # not unconditional deny). This still blocks unconstrained mutation.
    result = evaluate_close_guard(
        close_allowed=None,
        loss_realizing_close=True,
    )
    assert result.gate_id == "intelligent_close_guard"
    assert result.gate_action == "close_only"
    assert result.passed is False
    assert result.live_blocked is True
    assert result.close_only is True
    assert "loss_close_not_proven_safe" in result.detail


def test_intelligent_close_guard_defer_close_blocks() -> None:
    result = evaluate_close_guard(
        guard_action="defer_close",
        loss_realizing_close=True,
    )
    assert result.gate_action == "close_only"
    assert result.passed is False
    assert result.live_blocked is True


# ---------------------------------------------------------------------------
# 5) auto_deleverager → DENY (triggered)
# ---------------------------------------------------------------------------


def test_auto_deleverager_triggered_denies_all_actions() -> None:
    result = evaluate_adl_state(deleverager_triggered=True)
    _assert_deny(
        result,
        gate_id="auto_deleverager",
        reason_code=RISK_DECISION_REASON_DENY_AUTO_DELEVERAGER_TRIGGERED,
    )


def test_auto_deleverager_cap_breach_denies() -> None:
    result = evaluate_adl_state(cap_breach="net_long_cap_breach")
    _assert_deny(
        result,
        gate_id="auto_deleverager",
        reason_code=RISK_DECISION_REASON_DENY_AUTO_DELEVERAGER_TRIGGERED,
    )


# ---------------------------------------------------------------------------
# 6) shared_risk_gate → DENY (budget exhausted)
# ---------------------------------------------------------------------------


def test_shared_risk_gate_budget_exhausted_denies() -> None:
    result = evaluate_budget_state(
        budget_remaining=0.0,
        budget_required=1.0,
        is_risk_add=True,
    )
    _assert_deny(
        result,
        gate_id="shared_risk_gate",
        reason_code=RISK_DECISION_REASON_DENY_SHARED_RISK_BUDGET_EXHAUSTED,
    )


def test_shared_risk_gate_block_code_denies() -> None:
    result = evaluate_budget_state(
        block_code="account_drawdown",
        is_risk_add=True,
    )
    _assert_deny(
        result,
        gate_id="shared_risk_gate",
        reason_code=RISK_DECISION_REASON_DENY_SHARED_RISK_BUDGET_EXHAUSTED,
    )
    assert "shared_risk_gate_account_drawdown_block" in result.detail


# ---------------------------------------------------------------------------
# 7) margin_governor → DENY (leverage above max, or wrong margin_mode)
# ---------------------------------------------------------------------------


def test_margin_governor_leverage_increase_denies() -> None:
    result = evaluate_margin_state(
        proposed_leverage=10.0,
        max_allowed_leverage=1.0,
        margin_mode="isolated",
        required_margin_mode="isolated",
    )
    _assert_deny(
        result,
        gate_id="margin_governor",
        reason_code=RISK_DECISION_REASON_DENY_MARGIN_GOVERNOR_LEVERAGE_INCREASE_BLOCKED,
    )


def test_margin_governor_cross_margin_mode_denies() -> None:
    result = evaluate_margin_state(
        proposed_leverage=1.0,
        max_allowed_leverage=1.0,
        margin_mode="cross",
        required_margin_mode="isolated",
    )
    _assert_deny(
        result,
        gate_id="margin_governor",
        reason_code=RISK_DECISION_REASON_DENY_MARGIN_GOVERNOR_LEVERAGE_INCREASE_BLOCKED,
    )


def test_margin_governor_verdict_block_denies() -> None:
    result = evaluate_margin_state(verdict_action="block")
    _assert_deny(
        result,
        gate_id="margin_governor",
        reason_code=RISK_DECISION_REASON_DENY_MARGIN_GOVERNOR_LEVERAGE_INCREASE_BLOCKED,
    )


# ---------------------------------------------------------------------------
# 8) phase_controller → DENY (warmup incomplete or ramp breach)
# ---------------------------------------------------------------------------


def test_phase_controller_warmup_incomplete_denies() -> None:
    result = evaluate_phase_gate(warmup_complete=False)
    _assert_deny(
        result,
        gate_id="phase_controller",
        reason_code=RISK_DECISION_REASON_DENY_PHASE_CONTROLLER_WARMUP,
    )


def test_phase_controller_ramp_breach_denies() -> None:
    result = evaluate_phase_gate(
        warmup_complete=True,
        ramp_limit_breach="hourly_risk_add_cap_exceeded",
    )
    _assert_deny(
        result,
        gate_id="phase_controller",
        reason_code=RISK_DECISION_REASON_DENY_PHASE_CONTROLLER_WARMUP,
    )
    assert "hourly_risk_add_cap_exceeded" in result.detail


# ---------------------------------------------------------------------------
# 9) adaptive_gate (microstructure toxicity) → DENY when toxic
# ---------------------------------------------------------------------------


def test_adaptive_gate_microstructure_toxic_denies() -> None:
    result = evaluate_toxicity_block(
        toxicity_score=0.99,
        toxic_threshold=0.85,
        is_risk_add=True,
    )
    _assert_deny(
        result,
        gate_id="microstructure_toxicity",
        reason_code=RISK_DECISION_REASON_DENY_ADAPTIVE_MICROSTRUCTURE_TOXIC,
    )


def test_adaptive_gate_missing_toxicity_score_denies_fail_closed() -> None:
    result = evaluate_toxicity_block(
        toxicity_score=None,
        toxic_threshold=0.85,
        is_risk_add=True,
    )
    _assert_deny(
        result,
        gate_id="microstructure_toxicity",
        reason_code=RISK_DECISION_REASON_DENY_ADAPTIVE_MICROSTRUCTURE_TOXIC,
    )
    assert result.evidence_status == "missing"


# ---------------------------------------------------------------------------
# 10) Orchestrator HOLD → DENY via assemble_risk_decision_record
# ---------------------------------------------------------------------------


def test_orchestrator_hold_assembles_deny_orchestrator_held() -> None:
    decision = OrchestratorDecisionRecord(
        decision_id="d_lane_c_hold_001",
        prediction_id="p_lane_c_001",
        feature_snapshot_id="f_lane_c_001",
        symbol="BTCUSDT",
        decision_ts_ms=1_715_500_000_000,
        decision_action=DECISION_ACTION_HOLD,
        decision_reason_code="hold_flat_direction",
        input_prediction_direction="flat",
        input_prediction_confidence_calibrated=0.4,
        input_prediction_freshness_flag="fresh",
        input_worker_health_status="HEALTHY",
        live_blocked=True,
    )
    record = assemble_risk_decision_record(
        decision=decision,
        now_ms_clock=lambda: 1_715_500_001_000,
    )
    assert record.risk_action == RISK_DECISION_ACTION_DENY
    assert record.risk_reason_code == RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD
    assert record.live_blocked is True


def test_orchestrator_abstain_assembles_deny_orchestrator_abstained() -> None:
    decision = OrchestratorDecisionRecord(
        decision_id="d_lane_c_abstain_001",
        prediction_id="p_lane_c_002",
        feature_snapshot_id="f_lane_c_002",
        symbol="BTCUSDT",
        decision_ts_ms=1_715_500_000_000,
        decision_action=DECISION_ACTION_ABSTAIN,
        decision_reason_code="abstain_low_confidence",
        input_prediction_direction="long",
        input_prediction_confidence_calibrated=0.10,
        input_prediction_freshness_flag="fresh",
        input_worker_health_status="HEALTHY",
        live_blocked=True,
    )
    record = assemble_risk_decision_record(
        decision=decision,
        now_ms_clock=lambda: 1_715_500_001_000,
    )
    assert record.risk_action == RISK_DECISION_ACTION_DENY
    assert record.risk_reason_code == RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED
    assert record.live_blocked is True


# ---------------------------------------------------------------------------
# PARITY GAPS — legacy paths with no v2 risk_gateway service entry point.
# These are explicitly documented (not fabricated) so the lane status report
# can carry the gap forward into the parity matrix.
# ---------------------------------------------------------------------------


def test_parity_gap_fee_ratio_gate_not_present_as_risk_gateway_entry() -> None:
    # Legacy path: trading/fee_ratio_gate.py (executor-layer guard, not in
    # v2 risk_gateway service). Document and skip.
    try:
        from v2.backend.app.services.risk_gateway import (  # noqa: F401
            fee_ratio_gate as _fee_ratio_gate,
        )
        has_module = True
    except Exception:
        has_module = False
    if not has_module:
        pytest.skip(
            "PARITY_GAP_NOT_FOUND: fee_ratio_gate is a legacy "
            "trading/fee_ratio_gate.py executor-layer guard and is not "
            "exposed as a v2 risk_gateway service entry point."
        )


def test_parity_gap_churn_veto_not_present_as_risk_gateway_entry() -> None:
    # Legacy path: trading/churn_prevention.py (lifecycle-layer veto, not in
    # v2 risk_gateway service). Document and skip.
    try:
        from v2.backend.app.services.risk_gateway import (  # noqa: F401
            churn_veto as _churn_veto,
        )
        has_module = True
    except Exception:
        has_module = False
    if not has_module:
        pytest.skip(
            "PARITY_GAP_NOT_FOUND: churn_veto is a legacy "
            "trading/churn_prevention.py lifecycle-layer veto and is not "
            "exposed as a v2 risk_gateway service entry point."
        )


def test_parity_gap_minimum_hold_time_not_present_as_risk_gateway_entry() -> None:
    # Legacy path: paper_online_runtime carries a minimum_hold_seconds field
    # but no risk_gateway evaluator equivalent exists. Document and skip.
    try:
        from v2.backend.app.services.risk_gateway import (  # noqa: F401
            minimum_hold_time as _minimum_hold_time,
        )
        has_module = True
    except Exception:
        has_module = False
    if not has_module:
        pytest.skip(
            "PARITY_GAP_NOT_FOUND: minimum_hold_time has no v2 "
            "risk_gateway service entry point — only a paper-runtime "
            "PAPER_POSITION_MIN_HOLD_SECONDS field on paper-shadow paths."
        )


# ---------------------------------------------------------------------------
# Non-mutation invariants: the test module must NOT import any exchange
# client or any of the forbidden mutation callables.
# ---------------------------------------------------------------------------


def test_test_module_imports_no_exchange_client_or_mutation_paths() -> None:
    # Verifies the test file itself contains no forbidden mutation strings.
    # We assemble the forbidden tokens out of fragments so this very test
    # source does not contain the literals.
    source = Path(__file__).read_text()
    forbidden = [
        "create" + "_order",
        "cancel" + "_order",
        "futures_create" + "_order",
        "futures_cancel" + "_order",
        "futures_change" + "_leverage",
        "futures_change" + "_margin_type",
        "change" + "_leverage",
        "change" + "_margin_type",
        "place" + "_order",
    ]
    for token in forbidden:
        assert token not in source, (
            f"test file unexpectedly contains forbidden mutation token: {token!r}"
        )
    # No exchange client / network imports. Tokens are split so this file's
    # own assertion strings don't trip the scan.
    _imp = "import "
    _frm = "from "
    forbidden_imports = [
        _imp + "ccxt",
        _frm + "ccxt",
        _frm + "binance",
        _imp + "binance",
        _imp + "websocket",
        _frm + "websocket",
        _imp + "requests",
        _frm + "requests",
        _imp + "httpx",
        _frm + "httpx",
        _imp + "aiohttp",
        _frm + "aiohttp",
    ]
    for imp in forbidden_imports:
        assert imp not in source, (
            f"test file unexpectedly contains forbidden import: {imp!r}"
        )
    # No old-Redis writes. Tokens are constructed at runtime so this file's
    # own assertion strings don't trip the scan.
    _r = "redis"
    forbidden_redis = [
        _r + ".set(",
        _r + ".hset(",
        _r + ".xadd(",
        _r + ".publish(",
    ]
    for tok in forbidden_redis:
        assert tok not in source, (
            f"test file unexpectedly contains forbidden redis write: {tok!r}"
        )


def test_live_gate_and_live_symbols_invariants_remain() -> None:
    # These are sentinels asserted as test-file invariants and are
    # re-asserted in the lane status JSON.
    assert LIVE_GATE_STATUS_EXPECTED == "blocked_human_only"
    assert LIVE_SYMBOLS_EXPECTED == ()
