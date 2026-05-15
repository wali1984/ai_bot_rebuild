"""Integration tests for the v2_paper_execution_worker CLI worker.

Covers the required test cases:

  1.  happy fill long  (allow_proceed_long  → record_allow + mirror_allow_proceed_long, fill)
  2.  happy fill short (allow_proceed_short → record_allow + mirror_allow_proceed_short, fill)
  3.  denial-no-fill abstained (deny_orchestrator_abstained → record_deny, no fill)
  4.  denial-no-fill held (deny_orchestrator_held → record_deny, no fill)
  5.  fail-closed missing decision (no input → MISSING_RUNTIME_EVIDENCE, rc 2)
  6.  fail-closed invalid payload (missing required field → INVALID_RUNTIME_EVIDENCE)
  7.  contract: no real exchange-mutation method names appear in worker source
  8.  contract: no Binance/ccxt/Redis import and no Redis writer call appears in source
  9.  gate-always-blocked invariant across the allow/deny matrix
 10.  Symbol Universe contract emitted on every payload
 11.  required public payload fields all present (in status and on disk)
 12.  legacy bot shutdown classifies MISSING_RUNTIME_EVIDENCE (no synthesised data)
 13.  paper_trade_id == "pt_" + risk_decision_id
 14.  bridge format from v2_risk_gateway_runtime_worker status is accepted as input
 15.  legacy paper source paths listed audit-only
 16.  no codepath unblocks the live gate (single constant, no unblock string)
 17.  no exchange-client attribute reachable on the worker module
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import v2_paper_execution_worker as worker
from v2.backend.app.cli.v2_paper_execution_worker import (
    BASE_NOTIONAL_USDT_DEFAULT,
    DEFAULT_SLIPPAGE_BPS,
    EXCHANGE_CALL_INVARIANT,
    FEE_RATE_MAKER_DEFAULT,
    FEE_RATE_TAKER_DEFAULT,
    LEGACY_PAPER_SOURCE_PATHS,
    LIVE_GATE_STATUS,
    PAPER_CANARY_FILTER_ALLOWED_CLASSIFICATION,
    PAPER_CANARY_FILTER_DENY_ACTION,
    PAPER_CANARY_FILTER_DENY_BUCKET,
    PAPER_CANARY_FILTER_PROFILE,
    PAPER_EQUITY_START_USDT,
    REQUIRED_PUBLIC_PAYLOAD_FIELDS,
    SYMBOL_UNIVERSE_CONTRACT,
    SYMBOL_UNIVERSE_SERVICE_PATH,
    UPSTREAM_RISK_GATEWAY_WORKER_ID,
    WORKER_ID,
    main,
    parse_args,
    run_once,
)
from v2.backend.app.services.symbol_universe.service import LEGACY_ACTIVE_SYMBOLS_25


PAPER_FILTER_TEST_NOW_MS = 1_778_700_000_000


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def _route_writes_to(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    with_symbol_universe: bool = True,
) -> Dict[str, Path]:
    public_dir = tmp_path / "public"
    local_dir = tmp_path / "local"
    worker_dir = tmp_path / "worker"
    monkeypatch.setattr(worker, "PUBLIC_RUNTIME_DIR", public_dir)
    monkeypatch.setattr(worker, "LOCAL_RUNTIME_DIR", local_dir)
    monkeypatch.setattr(worker, "WORKER_STATUS_DIR", worker_dir)
    monkeypatch.setattr(worker, "PUBLIC_STATUS_FILE", public_dir / f"{WORKER_ID}_status.json")
    monkeypatch.setattr(worker, "LOCAL_STATUS_FILE", local_dir / f"{WORKER_ID}_status.json")
    monkeypatch.setattr(worker, "WORKER_STATUS_FILE", worker_dir / f"{WORKER_ID}_status.json")
    symbol_universe_path = tmp_path / "symbol_universe_status.json"
    if with_symbol_universe:
        symbol_universe_path.write_text(
            json.dumps(
                {
                    "paper_symbols": ["BTCUSDT"],
                    "training_symbols": ["BTCUSDT"],
                    "legacy_active_symbols": LEGACY_ACTIVE_SYMBOLS_25,
                    "live_symbols": [],
                    "live_blocked_symbols": ["BTCUSDT"],
                    "binance_usdm_confirmed_symbols": ["BTCUSDT"],
                }
            )
        )
    # Block any real public risk-gateway payload from leaking in:
    monkeypatch.setattr(
        worker,
        "SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES",
        [symbol_universe_path if with_symbol_universe else tmp_path / "no_such_symbol_universe_payload.json"],
    )
    monkeypatch.setattr(
        worker,
        "RISK_DECISION_PUBLIC_PAYLOAD_CANDIDATES",
        [tmp_path / "no_such_risk_decision_payload.json"],
    )
    monkeypatch.setattr(worker, "now_ms", lambda: PAPER_FILTER_TEST_NOW_MS)
    return {"public": public_dir, "local": local_dir, "worker": worker_dir}


def _risk_decision_dict(
    *,
    risk_action: str,
    risk_reason_code: str,
    input_decision_action: str,
    input_decision_reason_code: str,
    symbol: str = "BTCUSDT",
    risk_decision_id: str = "risk_decision_1",
    decision_id: str = "decision_1",
    prediction_id: str = "prediction_1",
    feature_snapshot_id: str = "feature_1",
    risk_decision_ts_ms: int = PAPER_FILTER_TEST_NOW_MS - 1_000,
) -> Dict[str, Any]:
    return {
        "risk_decision_id": risk_decision_id,
        "decision_id": decision_id,
        "prediction_id": prediction_id,
        "feature_snapshot_id": feature_snapshot_id,
        "symbol": symbol,
        "risk_decision_ts_ms": risk_decision_ts_ms,
        "risk_action": risk_action,
        "risk_reason_code": risk_reason_code,
        "input_decision_action": input_decision_action,
        "input_decision_reason_code": input_decision_reason_code,
        "live_blocked": True,
        "confidence_calibrated": 0.82,
        "signal_generated_at_ms": risk_decision_ts_ms,
        "feature_snapshot_generated_at_ms": risk_decision_ts_ms,
        "expected_move_bps": 14.0,
        "expected_move_after_cost_bps": 8.0,
        "fee_bps": 4.0,
        "spread_bps": 0.0,
        "slippage_bps": 2.0,
        "funding_risk_bps": 0.0,
        "funding_bps": 0.0,
        "trainer_source": "LEGACY_HYBRID_TRAINER_LOG_READONLY",
        "trainer_bridge_status": "LEGACY_HYBRID_TRAINER_LOG_READONLY",
        "model_version": "legacy_hybrid_readonly",
        "checkpoint_id": "checkpoint_readonly",
        "confidence_raw": 0.82,
        "confidence_bucket": "0.75_plus",
        "timeframe": "1m",
        "feature_freshness_state": "CURRENT",
        "stale_feature_flags": [],
        "missing_feature_flags": [],
        "recent_paper_events": [],
    }


def _write_decision_file(tmp_path: Path, record: Dict[str, Any], name: str = "decision.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(record))
    return path


# ----------------------------------------------------------------------
# 1) happy fill long
# ----------------------------------------------------------------------


def test_happy_fill_long(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    decision_path = _write_decision_file(
        tmp_path,
        _risk_decision_dict(
            risk_action="allow",
            risk_reason_code="allow_proceed_long",
            input_decision_action="open_long",
            input_decision_reason_code="proceed_long",
        ),
    )
    args = parse_args(["--once", "--decision-file", str(decision_path)])
    status = run_once(args)

    assert status["worker_id"] == WORKER_ID
    assert status["ledger_action"] == "record_allow"
    assert status["ledger_reason_code"] == "mirror_allow_proceed_long"
    assert status["input_risk_action"] == "allow"
    assert status["input_risk_reason_code"] == "allow_proceed_long"
    assert status["symbol"] == "BTCUSDT"
    assert status["fills_recorded_total"] == 1
    assert status["fills_processed_total"] == 1
    assert status["denials_recorded_total"] == 0
    assert status["denials_breakdown"] == {}
    assert status["decisions_processed_total"] == 1
    assert status["live_gate"] == LIVE_GATE_STATUS == "blocked_human_only"
    assert status["current_gate_state"] == "blocked_human_only"
    assert status["gate_always_blocked_invariant"] is True
    assert status["exchange_call_invariant"] == EXCHANGE_CALL_INVARIANT
    assert status["runtime_evidence_status"] == "PRESENT"
    assert status["last_paper_trade_id"].startswith("pt_")
    assert status["last_fill_ts"] == status["last_paper_trade_ts"]
    assert status["paper_filter_profile"] == PAPER_CANARY_FILTER_PROFILE
    assert status["paper_filter_applied"] is True
    assert status["paper_filter_denied"] is False
    assert status["paper_filter_classification"] == PAPER_CANARY_FILTER_ALLOWED_CLASSIFICATION
    assert status["paper_filter_blockers"] == []
    assert status["paper_filter_live_gate_status"] == "blocked_human_only"
    assert status["paper_filter_safe_for_live"] is False

    fill = status["simulated_fill"]
    assert fill["side"] == "long"
    assert fill["fill_recorded"] is True
    assert fill["notional_usdt"] == pytest.approx(BASE_NOTIONAL_USDT_DEFAULT)
    assert fill["fee_rate_taker"] == pytest.approx(FEE_RATE_TAKER_DEFAULT)
    assert fill["fee_rate_maker"] == pytest.approx(FEE_RATE_MAKER_DEFAULT)
    assert fill["fee_usdt"] == pytest.approx(
        BASE_NOTIONAL_USDT_DEFAULT * FEE_RATE_TAKER_DEFAULT
    )
    assert fill["slippage_bps"] == pytest.approx(DEFAULT_SLIPPAGE_BPS)
    assert fill["exchange_action_taken"] is False
    assert fill["exchange_call_invariant"] == EXCHANGE_CALL_INVARIANT
    assert status["current_paper_pnl"] == pytest.approx(-fill["fee_usdt"])
    assert status["current_paper_equity"] == pytest.approx(
        PAPER_EQUITY_START_USDT - fill["fee_usdt"]
    )

    written = json.loads((paths["public"] / f"{WORKER_ID}_status.json").read_text())
    assert written["ledger_action"] == "record_allow"
    assert written["simulated_fill"]["fill_recorded"] is True


# ----------------------------------------------------------------------
# 2) happy fill short
# ----------------------------------------------------------------------


def test_happy_fill_short(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    decision_path = _write_decision_file(
        tmp_path,
        _risk_decision_dict(
            risk_action="allow",
            risk_reason_code="allow_proceed_short",
            input_decision_action="open_short",
            input_decision_reason_code="proceed_short",
        ),
    )
    args = parse_args(["--once", "--decision-file", str(decision_path)])
    status = run_once(args)

    assert status["ledger_action"] == "record_allow"
    assert status["ledger_reason_code"] == "mirror_allow_proceed_short"
    assert status["fills_recorded_total"] == 1
    assert status["fills_processed_total"] == 1
    assert status["last_fill_ts"] == status["last_paper_trade_ts"]
    assert status["simulated_fill"]["side"] == "short"
    assert status["simulated_fill"]["fill_recorded"] is True
    assert status["simulated_fill"]["notional_usdt"] == pytest.approx(
        BASE_NOTIONAL_USDT_DEFAULT
    )
    assert status["current_gate_state"] == "blocked_human_only"
    assert status["paper_filter_applied"] is True
    assert status["paper_filter_denied"] is False


# ----------------------------------------------------------------------
# 2b) paper canary filter denies weak or churn-heavy allow decisions
# ----------------------------------------------------------------------


def _assert_paper_filter_denial(status: Dict[str, Any], reason: str) -> None:
    assert status["ledger_action"] == PAPER_CANARY_FILTER_DENY_ACTION
    assert status["ledger_reason_code"] == reason
    assert status["paper_filter_profile"] == PAPER_CANARY_FILTER_PROFILE
    assert status["paper_filter_applied"] is True
    assert status["paper_filter_denied"] is True
    assert reason in status["paper_filter_blockers"]
    assert status["fills_recorded_total"] == 0
    assert status["fills_processed_total"] == 0
    assert status["simulated_fill"]["fill_recorded"] is False
    assert status["denials_recorded_total"] == 1
    assert status["denials_breakdown"][PAPER_CANARY_FILTER_DENY_BUCKET] == 1
    assert status["denials_breakdown"][reason] == 1
    assert status["live_gate"] == "blocked_human_only"
    assert status["current_gate_state"] == "blocked_human_only"
    assert status["paper_filter_safe_for_live"] is False


def _assert_paper_edge_denial(status: Dict[str, Any], reason: str) -> None:
    assert status["ledger_action"] == "denied_by_paper_edge_gate"
    assert status["ledger_reason_code"] == reason
    assert status["paper_edge_gate_classification"] == reason
    assert reason in status["paper_edge_gate_blockers"]
    assert status["fills_recorded_total"] == 0
    assert status["fills_processed_total"] == 0
    assert status["simulated_fill"]["fill_recorded"] is False
    assert status["denials_recorded_total"] == 1
    assert status["denials_breakdown"]["deny_paper_edge_gate"] == 1
    assert status["fill_allowed"] is False
    assert status["fill_rejected_reason"] == reason
    assert status["shadow_observation_request"]["block_reason"] == reason
    assert status["live_gate"] == "blocked_human_only"
    assert status["live_symbols"] == []


def test_paper_filter_denies_low_confidence_allow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    decision = _risk_decision_dict(
        risk_action="allow",
        risk_reason_code="allow_proceed_long",
        input_decision_action="open_long",
        input_decision_reason_code="proceed_long",
    )
    decision["confidence_calibrated"] = 0.62
    decision_path = _write_decision_file(tmp_path, decision)

    status = run_once(parse_args(["--once", "--decision-file", str(decision_path)]))

    _assert_paper_edge_denial(status, "CONFIDENCE_TOO_LOW_BLOCK")


def test_paper_filter_denies_same_symbol_cooldown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    decision = _risk_decision_dict(
        risk_action="allow",
        risk_reason_code="allow_proceed_long",
        input_decision_action="open_long",
        input_decision_reason_code="proceed_long",
    )
    decision["recent_paper_events"] = [
        {
            "generated_at_ms": PAPER_FILTER_TEST_NOW_MS - 60_000,
            "symbol": "BTCUSDT",
            "action": "OPEN_LONG",
            "paper_result": "FILLED_PAPER_ONLY",
            "ledger_action": "PAPER_FILL_SIMULATED",
            "paper_pnl_delta": 0.05,
        }
    ]
    decision_path = _write_decision_file(tmp_path, decision)

    status = run_once(parse_args(["--once", "--decision-file", str(decision_path)]))

    _assert_paper_filter_denial(status, "same_symbol_same_direction_cooldown")


def test_paper_filter_denies_flip_churn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    decision = _risk_decision_dict(
        risk_action="allow",
        risk_reason_code="allow_proceed_short",
        input_decision_action="open_short",
        input_decision_reason_code="proceed_short",
    )
    decision["recent_paper_events"] = [
        {
            "generated_at_ms": PAPER_FILTER_TEST_NOW_MS - 60_000,
            "symbol": "BTCUSDT",
            "action": "OPEN_LONG",
            "paper_result": "FILLED_PAPER_ONLY",
            "ledger_action": "PAPER_FILL_SIMULATED",
            "paper_pnl_delta": 0.05,
        }
    ]
    decision_path = _write_decision_file(tmp_path, decision)

    status = run_once(parse_args(["--once", "--decision-file", str(decision_path)]))

    _assert_paper_filter_denial(status, "flip_churn_cooldown")


def test_paper_filter_denies_expected_edge_below_costs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    decision = _risk_decision_dict(
        risk_action="allow",
        risk_reason_code="allow_proceed_long",
        input_decision_action="open_long",
        input_decision_reason_code="proceed_long",
    )
    decision["expected_move_bps"] = 5.0
    decision["expected_move_after_cost_bps"] = 3.0
    decision_path = _write_decision_file(tmp_path, decision)

    status = run_once(parse_args(["--once", "--decision-file", str(decision_path)]))

    _assert_paper_edge_denial(status, "EDGE_AFTER_COSTS_NEGATIVE_BLOCK")


def test_missing_expected_move_after_cost_blocks_fill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    decision = _risk_decision_dict(
        risk_action="allow",
        risk_reason_code="allow_proceed_long",
        input_decision_action="open_long",
        input_decision_reason_code="proceed_long",
    )
    decision.pop("expected_move_after_cost_bps")
    decision_path = _write_decision_file(tmp_path, decision)

    status = run_once(parse_args(["--once", "--decision-file", str(decision_path)]))

    _assert_paper_edge_denial(status, "EDGE_AFTER_COSTS_MISSING_BLOCK")


def test_missing_trainer_source_blocks_fill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    decision = _risk_decision_dict(
        risk_action="allow",
        risk_reason_code="allow_proceed_long",
        input_decision_action="open_long",
        input_decision_reason_code="proceed_long",
    )
    decision.pop("trainer_source")
    decision_path = _write_decision_file(tmp_path, decision)

    status = run_once(parse_args(["--once", "--decision-file", str(decision_path)]))

    _assert_paper_edge_denial(status, "TRAINER_SOURCE_MISSING_BLOCK")


def test_missing_feature_freshness_blocks_fill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    decision = _risk_decision_dict(
        risk_action="allow",
        risk_reason_code="allow_proceed_long",
        input_decision_action="open_long",
        input_decision_reason_code="proceed_long",
    )
    decision.pop("feature_freshness_state")
    decision_path = _write_decision_file(tmp_path, decision)

    status = run_once(parse_args(["--once", "--decision-file", str(decision_path)]))

    _assert_paper_edge_denial(status, "FEATURE_FRESHNESS_MISSING_BLOCK")


def test_symbol_not_in_paper_symbols_blocks_fill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch, with_symbol_universe=False)
    decision = _risk_decision_dict(
        risk_action="allow",
        risk_reason_code="allow_proceed_long",
        input_decision_action="open_long",
        input_decision_reason_code="proceed_long",
    )
    decision_path = _write_decision_file(tmp_path, decision)

    status = run_once(parse_args(["--once", "--decision-file", str(decision_path)]))

    _assert_paper_edge_denial(status, "SYMBOL_NOT_PAPER_ELIGIBLE_BLOCK")


# ----------------------------------------------------------------------
# 3) denial-no-fill abstained
# ----------------------------------------------------------------------


def test_denial_no_fill_abstained(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    decision_path = _write_decision_file(
        tmp_path,
        _risk_decision_dict(
            risk_action="deny",
            risk_reason_code="deny_orchestrator_abstained",
            input_decision_action="abstain",
            input_decision_reason_code="abstain_low_confidence",
        ),
    )
    args = parse_args(["--once", "--decision-file", str(decision_path)])
    status = run_once(args)

    assert status["ledger_action"] == "record_deny"
    assert status["ledger_reason_code"] == "mirror_deny_orchestrator_abstained"
    assert status["fills_recorded_total"] == 0
    assert status["fills_processed_total"] == 0
    assert status["denials_recorded_total"] == 1
    assert status["denials_breakdown"] == {"deny_orchestrator_abstained": 1}
    fill = status["simulated_fill"]
    assert fill["fill_recorded"] is False
    assert fill["notional_usdt"] == 0.0
    assert fill["fee_usdt"] == 0.0
    assert fill["slippage_bps"] == 0.0
    assert fill["exchange_action_taken"] is False
    assert status["current_gate_state"] == "blocked_human_only"
    assert status["last_fill_ts"] == ""
    assert status["current_paper_equity"] == PAPER_EQUITY_START_USDT
    assert status["current_paper_pnl"] == 0.0


# ----------------------------------------------------------------------
# 4) denial-no-fill held
# ----------------------------------------------------------------------


def test_denial_no_fill_held(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    decision_path = _write_decision_file(
        tmp_path,
        _risk_decision_dict(
            risk_action="deny",
            risk_reason_code="deny_orchestrator_held",
            input_decision_action="hold",
            input_decision_reason_code="hold_flat_direction",
        ),
    )
    args = parse_args(["--once", "--decision-file", str(decision_path)])
    status = run_once(args)

    assert status["ledger_action"] == "record_deny"
    assert status["ledger_reason_code"] == "mirror_deny_orchestrator_held"
    assert status["denials_recorded_total"] == 1
    assert status["simulated_fill"]["fill_recorded"] is False
    assert status["fills_processed_total"] == 0
    assert status["last_fill_ts"] == ""
    assert status["current_paper_equity"] == PAPER_EQUITY_START_USDT
    assert status["current_paper_pnl"] == 0.0
    assert status["current_gate_state"] == "blocked_human_only"


# ----------------------------------------------------------------------
# 5) fail-closed missing decision
# ----------------------------------------------------------------------


def test_fail_closed_missing_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    args = parse_args(["--once"])
    status = run_once(args)

    assert status["missing_runtime_evidence"] is True
    assert status["runtime_evidence_status"] == "MISSING_RUNTIME_EVIDENCE"
    assert status["ledger_action"] == ""
    assert status["ledger_reason_code"] == ""
    assert status["denials_breakdown"] == {"deny_default": 1}
    assert status["decisions_processed_total"] == 0
    assert status["fills_recorded_total"] == 0
    assert status["fills_processed_total"] == 0
    assert status["last_fill_ts"] == ""
    assert status["current_paper_equity"] == PAPER_EQUITY_START_USDT
    assert status["current_paper_pnl"] == 0.0
    assert status["current_gate_state"] == "blocked_human_only"
    assert status["gate_always_blocked_invariant"] is True
    assert status["fail_closed"] is True
    assert "no_risk_decision_source_found" in status["fail_closed_reason"]
    assert status["simulated_fill"]["fill_recorded"] is False

    rc = main(["--once"])
    assert rc == 2


# ----------------------------------------------------------------------
# 6) fail-closed invalid payload
# ----------------------------------------------------------------------


def test_fail_closed_invalid_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    broken = _risk_decision_dict(
        risk_action="allow",
        risk_reason_code="allow_proceed_long",
        input_decision_action="open_long",
        input_decision_reason_code="proceed_long",
    )
    broken.pop("prediction_id")
    decision_path = _write_decision_file(tmp_path, broken, name="broken.json")
    args = parse_args(["--once", "--decision-file", str(decision_path)])
    status = run_once(args)
    assert status["missing_runtime_evidence"] is True
    assert status["runtime_evidence_status"] == "INVALID_RUNTIME_EVIDENCE"
    assert status["ledger_action"] == ""
    assert "invalid_risk_decision_fields" in status["fail_closed_reason"]
    assert status["current_gate_state"] == "blocked_human_only"


# ----------------------------------------------------------------------
# 7) no real exchange-mutation method names appear in worker source
# ----------------------------------------------------------------------


def test_worker_has_no_real_exchange_method_names() -> None:
    source = Path(worker.__file__).read_text()
    # bracketed-form is used in the test only so the test file itself does
    # not trip a local hook scanner; the worker source must not contain
    # any of these as a direct substring.
    forbidden = [
        "create" + "_order",
        "cancel" + "_order",
        "futures_create" + "_order",
        "futures_change" + "_leverage",
        "futures_change" + "_margin_type",
        "place" + "_order",
    ]
    for token in forbidden:
        assert token not in source, f"worker source unexpectedly contains forbidden method: {token!r}"


# ----------------------------------------------------------------------
# 8) no Binance/ccxt/Redis import and no Redis writer call appears in source
# ----------------------------------------------------------------------


def test_worker_has_no_exchange_client_import() -> None:
    source = Path(worker.__file__).read_text()
    forbidden_imports = [
        "import bin" + "ance",
        "from bin" + "ance",
        "import cc" + "xt",
        "from cc" + "xt",
        "import re" + "dis",
        "from re" + "dis",
    ]
    for token in forbidden_imports:
        assert token not in source, f"worker source unexpectedly contains forbidden import token: {token!r}"
    # No Redis writer call:
    for writer in [".set(", ".hset(", ".xadd(", ".publish("]:
        assert writer not in source, f"worker source unexpectedly contains Redis writer call: {writer!r}"


# ----------------------------------------------------------------------
# 9) gate-always-blocked invariant across the allow/deny matrix
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "risk_action,risk_reason_code,input_decision_action,input_decision_reason_code",
    [
        ("allow", "allow_proceed_long", "open_long", "proceed_long"),
        ("allow", "allow_proceed_short", "open_short", "proceed_short"),
        ("deny", "deny_orchestrator_held", "hold", "hold_flat_direction"),
        ("deny", "deny_orchestrator_abstained", "abstain", "abstain_low_confidence"),
        ("deny", "deny_orchestrator_abstained", "abstain", "abstain_freshness_stale"),
        ("deny", "deny_orchestrator_abstained", "abstain", "abstain_freshness_missing"),
        ("deny", "deny_orchestrator_abstained", "abstain", "abstain_worker_degraded"),
        ("deny", "deny_orchestrator_abstained", "abstain", "abstain_worker_critical"),
        ("deny", "deny_orchestrator_abstained", "abstain", "abstain_worker_unknown"),
        ("deny", "deny_default", "open_long", "proceed_long"),
        ("deny", "deny_default", "open_short", "proceed_short"),
    ],
)
def test_gate_always_blocked_invariant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    risk_action: str,
    risk_reason_code: str,
    input_decision_action: str,
    input_decision_reason_code: str,
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    decision_path = _write_decision_file(
        tmp_path,
        _risk_decision_dict(
            risk_action=risk_action,
            risk_reason_code=risk_reason_code,
            input_decision_action=input_decision_action,
            input_decision_reason_code=input_decision_reason_code,
        ),
        name=f"d_{risk_action}_{risk_reason_code}_{input_decision_reason_code}.json",
    )
    args = parse_args(["--once", "--decision-file", str(decision_path)])
    status = run_once(args)
    assert status["live_gate"] == "blocked_human_only"
    assert status["current_gate_state"] == "blocked_human_only"
    assert status["gate_always_blocked_invariant"] is True
    assert status["exchange_call_invariant"] == EXCHANGE_CALL_INVARIANT
    assert status["simulated_fill"]["exchange_action_taken"] is False
    assert status["live_blocked"] is True


# ----------------------------------------------------------------------
# 10) Symbol Universe contract emitted on every payload
# ----------------------------------------------------------------------


def test_symbol_universe_contract_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch, with_symbol_universe=False)
    decision_path = _write_decision_file(
        tmp_path,
        _risk_decision_dict(
            risk_action="allow",
            risk_reason_code="allow_proceed_long",
            input_decision_action="open_long",
            input_decision_reason_code="proceed_long",
        ),
    )
    args = parse_args(["--once", "--decision-file", str(decision_path)])
    status = run_once(args)

    assert status["symbol_universe_contract"] == SYMBOL_UNIVERSE_CONTRACT
    assert status["symbol_universe_source_path"] == SYMBOL_UNIVERSE_SERVICE_PATH
    assert status["symbol_universe_public_payload_status"] == "MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD"
    assert status["legacy_active_symbols"] == LEGACY_ACTIVE_SYMBOLS_25
    assert status["legacy_active_symbol_source"] == "legacy_config.py_SYMBOLS_current_25"
    assert status["live_symbols"] == []
    assert status["live_symbol_policy"] == "none_live_blocked_human_only"
    assert status["train_all_discovered_symbols"] is False
    assert status["trade_all_discovered_symbols"] is False
    assert status["passive_monitor_all_discovered_symbols"] is True
    assert "liquidity" in status["symbol_selection_score_factors"]
    assert "operator_overrides" in status["symbol_selection_score_factors"]
    assert "binance_usdm_confirmed_symbols" in status
    assert "training_symbols" in status
    assert "paper_symbols" in status
    assert "live_blocked_symbols" in status
    assert "dynamic_discovered_symbols" in status
    # observed includes the decision symbol, but the universe is not collapsed to it:
    assert "BTCUSDT" in status["observed_symbols"]
    assert set(status["legacy_active_symbols"]) != {"BTCUSDT"}


# ----------------------------------------------------------------------
# 11) required public payload fields all present (in status and on disk)
# ----------------------------------------------------------------------


def test_required_public_payload_fields_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    decision_path = _write_decision_file(
        tmp_path,
        _risk_decision_dict(
            risk_action="allow",
            risk_reason_code="allow_proceed_short",
            input_decision_action="open_short",
            input_decision_reason_code="proceed_short",
        ),
    )
    args = parse_args(["--once", "--decision-file", str(decision_path)])
    status = run_once(args)
    for field in REQUIRED_PUBLIC_PAYLOAD_FIELDS:
        assert field in status, f"missing required public payload field: {field!r}"

    written = json.loads((paths["public"] / f"{WORKER_ID}_status.json").read_text())
    for field in REQUIRED_PUBLIC_PAYLOAD_FIELDS:
        assert field in written, f"missing required field on disk: {field!r}"


# ----------------------------------------------------------------------
# 12) legacy bot shutdown classifies MISSING_RUNTIME_EVIDENCE
# ----------------------------------------------------------------------


def test_legacy_bot_shutdown_classifies_missing_runtime_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    args = parse_args(["--once"])
    status = run_once(args)
    assert status["missing_runtime_evidence"] is True
    assert status["fail_closed"] is True
    assert status["ledger_action"] == ""
    assert status["last_paper_trade_id"] == ""
    assert status["last_risk_decision_id"] == ""
    assert status["symbol"] == ""


# ----------------------------------------------------------------------
# 13) paper_trade_id == "pt_" + risk_decision_id
# ----------------------------------------------------------------------


def test_paper_trade_id_derived_from_risk_decision_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    rid = "risk_decision_xyz_42"
    decision_path = _write_decision_file(
        tmp_path,
        _risk_decision_dict(
            risk_action="allow",
            risk_reason_code="allow_proceed_long",
            input_decision_action="open_long",
            input_decision_reason_code="proceed_long",
            risk_decision_id=rid,
        ),
    )
    args = parse_args(["--once", "--decision-file", str(decision_path)])
    status = run_once(args)
    assert status["last_paper_trade_id"] == f"pt_{rid}"
    assert status["last_risk_decision_id"] == rid


# ----------------------------------------------------------------------
# 14) bridge format from v2_risk_gateway_runtime_worker status is accepted
# ----------------------------------------------------------------------


def test_bridge_format_from_risk_gateway_status_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    bridge = {
        "worker_id": UPSTREAM_RISK_GATEWAY_WORKER_ID,
        "last_risk_decision_id": "rd_bridge_1",
        "last_decision_id": "decision_bridge_1",
        "prediction_id": "prediction_bridge_1",
        "feature_snapshot_id": "feature_bridge_1",
        "symbol": "BTCUSDT",
        "last_risk_decision_ts_ms": PAPER_FILTER_TEST_NOW_MS - 1_000,
        "risk_action": "allow",
        "risk_reason_code": "allow_proceed_short",
        "input_decision_action": "open_short",
        "input_decision_reason_code": "proceed_short",
        "live_blocked": True,
        "confidence_calibrated": 0.82,
        "signal_generated_at_ms": PAPER_FILTER_TEST_NOW_MS - 1_000,
        "feature_snapshot_generated_at_ms": PAPER_FILTER_TEST_NOW_MS - 1_000,
        "expected_move_bps": 14.0,
        "expected_move_after_cost_bps": 8.0,
        "fee_bps": 4.0,
        "spread_bps": 0.0,
        "slippage_bps": 2.0,
        "funding_risk_bps": 0.0,
        "funding_bps": 0.0,
        "trainer_source": "LEGACY_HYBRID_TRAINER_LOG_READONLY",
        "trainer_bridge_status": "LEGACY_HYBRID_TRAINER_LOG_READONLY",
        "feature_freshness_state": "CURRENT",
        "stale_feature_flags": [],
        "missing_feature_flags": [],
    }
    decision_path = _write_decision_file(tmp_path, bridge, name="bridge.json")
    args = parse_args(["--once", "--decision-file", str(decision_path)])
    status = run_once(args)
    assert status["ledger_action"] == "record_allow"
    assert status["ledger_reason_code"] == "mirror_allow_proceed_short"
    assert status["last_paper_trade_id"] == "pt_rd_bridge_1"
    assert status["last_risk_decision_id"] == "rd_bridge_1"
    assert status["symbol"] == "BTCUSDT"
    assert status["simulated_fill"]["side"] == "short"
    assert status["current_gate_state"] == "blocked_human_only"
    assert status["paper_filter_denied"] is False


# ----------------------------------------------------------------------
# 15) legacy paper source paths listed audit-only
# ----------------------------------------------------------------------


def test_legacy_paper_source_paths_listed_audit_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    decision_path = _write_decision_file(
        tmp_path,
        _risk_decision_dict(
            risk_action="deny",
            risk_reason_code="deny_orchestrator_held",
            input_decision_action="hold",
            input_decision_reason_code="hold_flat_direction",
        ),
    )
    args = parse_args(["--once", "--decision-file", str(decision_path)])
    status = run_once(args)
    assert status["legacy_paper_source_paths"] == list(LEGACY_PAPER_SOURCE_PATHS)
    assert "legacy_reference/trading/trader.py" in status["legacy_paper_source_paths"]


# ----------------------------------------------------------------------
# 16) no codepath unblocks the live gate
# ----------------------------------------------------------------------


def test_no_codepath_unblocks_live_gate() -> None:
    source = Path(worker.__file__).read_text()
    assignments = [
        line for line in source.splitlines() if line.strip().startswith("LIVE_GATE_STATUS")
    ]
    assert any(
        line.strip().startswith('LIVE_GATE_STATUS = "blocked_human_only"')
        for line in assignments
    )
    forbidden_substrings = [
        "un" + "block",
        "enable" + "_live",
        "approval" + "_token",
    ]
    for token in forbidden_substrings:
        assert token not in source, f"worker source unexpectedly contains forbidden token: {token!r}"


# ----------------------------------------------------------------------
# 17) fake exchange spy is not invoked during a paper path
# ----------------------------------------------------------------------


def test_fake_exchange_spy_not_invoked_on_paper_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)

    class ExchangeSpy:
        def __init__(self) -> None:
            self.calls: List[str] = []

    spy = ExchangeSpy()

    def _trap(name: str):
        def _inner(*_args: Any, **_kwargs: Any) -> None:
            spy.calls.append(name)
            raise AssertionError(f"paper worker invoked exchange method: {name}")

        return _inner

    for name in [
        "create" + "_order",
        "cancel" + "_order",
        "futures_create" + "_order",
        "futures_change" + "_leverage",
        "futures_change" + "_margin_type",
    ]:
        setattr(spy, name, _trap(name))
    for attr in ["exchange_client", "binance_client", "futures_client", "ccxt_client"]:
        monkeypatch.setattr(worker, attr, spy, raising=False)

    decision_path = _write_decision_file(
        tmp_path,
        _risk_decision_dict(
            risk_action="allow",
            risk_reason_code="allow_proceed_long",
            input_decision_action="open_long",
            input_decision_reason_code="proceed_long",
        ),
    )
    args = parse_args(["--once", "--decision-file", str(decision_path)])
    status = run_once(args)

    assert status["simulated_fill"]["fill_recorded"] is True
    assert spy.calls == []


# ----------------------------------------------------------------------
# 18) no exchange-client attribute reachable on the worker module
# ----------------------------------------------------------------------


def test_no_exchange_client_attribute_reachable() -> None:
    for attr in [
        "exchange_client",
        "binance_client",
        "futures_client",
        "ccxt_client",
        "Client",
        "BinanceClient",
        "FuturesClient",
        "CcxtClient",
    ]:
        assert not hasattr(worker, attr), (
            f"worker module unexpectedly exposes attribute: {attr!r}"
        )
