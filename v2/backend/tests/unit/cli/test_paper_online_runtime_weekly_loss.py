from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import paper_online_runtime as paper_runtime
from v2.backend.app.cli.paper_online_runtime import (
    MarketSnapshot,
    apply_paper_tightening_gate,
    append_paper_event,
    build_feature_snapshot,
    build_paper_ledger_entry,
    build_position_lifecycle_entry,
    build_risk_runtime_payload,
    build_signal_lineage,
    build_trainer_prediction,
    paper_position_lifecycle_from_entry,
)


@pytest.fixture(autouse=True)
def _isolate_trainer_bridge_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        paper_runtime,
        "TRAINER_BRIDGE_STATUS_FILE",
        tmp_path / "missing_v2_trainer_bridge_status.json",
    )
    monkeypatch.setattr(
        paper_runtime,
        "PAPER_SHADOW_OUTCOME_STATUS_FILE",
        tmp_path / "missing_paper_shadow_outcome_observer_status.json",
    )


def _market() -> MarketSnapshot:
    return MarketSnapshot(
        symbol="BTCUSDT",
        price=100.0,
        source_type="READONLY_MARKET_FEED",
        source="unit_test",
        source_pointer="unit_test",
        generated_at="2026-05-13T07:30:00Z",
        last_event_at="2026-05-13T07:29:59Z",
        age_seconds=1,
        freshness_state="CURRENT",
        errors=[],
        candles=[
            {"close": 99.0, "volume": 10},
            {"close": 100.0, "volume": 11},
            {"close": 101.0, "volume": 12},
            {"close": 100.0, "volume": 13},
            {"close": 99.0, "volume": 14},
            {"close": 98.0, "volume": 15},
            {"close": 100.0, "volume": 16},
            {"close": 101.0, "volume": 17},
            {"close": 100.0, "volume": 18},
            {"close": 100.0, "volume": 19},
        ],
    )


def test_paper_runtime_risk_decision_declares_weekly_loss_block() -> None:
    market = _market()
    feature = build_feature_snapshot(market, "tick_unit")
    prediction = build_trainer_prediction(feature, "tick_unit")
    lineage = build_signal_lineage(
        tick_id="tick_unit",
        generated_at="2026-05-13T07:30:00Z",
        feature_snapshot=feature,
        prediction=prediction,
        market=market,
    )

    assert "weekly_loss_breach" in lineage["risk_decision"]["required_blocks_checked"]


def test_risk_runtime_payload_proves_weekly_loss_gate_without_live_side_effects() -> None:
    market = _market()
    feature = build_feature_snapshot(market, "tick_unit")
    prediction = build_trainer_prediction(feature, "tick_unit")
    lineage = build_signal_lineage(
        tick_id="tick_unit",
        generated_at="2026-05-13T07:30:00Z",
        feature_snapshot=feature,
        prediction=prediction,
        market=market,
    )
    ledger, account = build_paper_ledger_entry(
        tick_id="tick_unit",
        generated_at="2026-05-13T07:30:00Z",
        market=market,
        lineage=lineage,
        previous_equity=10000.0,
    )

    payload = build_risk_runtime_payload(
        generated_at="2026-05-13T07:30:00Z",
        lineage=lineage,
        ledger_entry=ledger,
        paper_account=account,
    )

    assert payload["weekly_loss_gate_required"] is True
    assert payload["daily_loss_gate_required"] is True
    assert payload["exchange_order"] is False
    assert payload["legacy_redis_write"] is False
    assert payload["live_gate_status"] == "blocked_human_only"


def test_paper_tightening_blocks_allow_when_expected_edge_is_missing() -> None:
    market = _market()
    feature = build_feature_snapshot(market, "tick_unit")
    prediction = build_trainer_prediction(feature, "tick_unit")
    lineage = build_signal_lineage(
        tick_id="tick_unit",
        generated_at="2026-05-13T07:30:00Z",
        feature_snapshot=feature,
        prediction=prediction,
        market=market,
    )

    assert lineage["risk_decision"]["risk_action"] == "allow"

    gated = apply_paper_tightening_gate(
        lineage,
        generated_at="2026-05-13T07:30:00Z",
        recent_events=[],
        now_ms=1_778_648_401_000,
    )
    ledger, account = build_paper_ledger_entry(
        tick_id="tick_unit",
        generated_at="2026-05-13T07:30:00Z",
        market=market,
        lineage=gated,
        previous_equity=10000.0,
    )

    assert gated["risk_decision"]["risk_action"] == "deny"
    assert gated["risk_decision"]["risk_reason_code"] == "deny_canary_profile_tightening"
    assert "missing_expected_move_after_costs" in gated["risk_decision"]["canary_profile_tightening_blockers"]
    assert ledger["paper_result"] == "NO_FILL_RISK_BLOCKED"
    assert account["realized_pnl"] == 0.0
    assert gated["execution_intent"]["exchange_order_allowed"] is False


def test_paper_outcome_model_status_is_present_when_risk_already_denied() -> None:
    market = _market()
    feature = build_feature_snapshot(market, "tick_unit")
    prediction = build_trainer_prediction(feature, "tick_unit")
    lineage = build_signal_lineage(
        tick_id="tick_unit",
        generated_at="2026-05-13T07:30:00Z",
        feature_snapshot=feature,
        prediction=prediction,
        market=market,
    )
    lineage["risk_decision"]["risk_action"] = "deny"
    lineage["risk_decision"]["risk_result"] = "BLOCKED"
    lineage["risk_decision"]["risk_reason_code"] = "deny_low_confidence"

    gated = apply_paper_tightening_gate(
        lineage,
        generated_at="2026-05-13T07:30:00Z",
        recent_events=[],
    )

    outcome_model = gated["risk_decision"]["paper_outcome_model"]
    assert outcome_model["status"] == "READY"
    assert outcome_model["paper_fill_allowed"] is True
    assert gated["risk_decision"]["paper_outcome_model_blockers"] == []
    assert "paper_outcome_model" in gated["risk_decision"]["required_blocks_checked"]


def test_native_trainer_bridge_expected_move_flows_to_paper_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge_status = tmp_path / "v2_trainer_bridge_status.json"
    monkeypatch.setattr(paper_runtime, "TRAINER_BRIDGE_STATUS_FILE", bridge_status)
    bridge_status.write_text(
        json.dumps(
            {
                "prediction_symbol": "BTCUSDT",
                "prediction_timeframe": "1m",
                "prediction_id": "legacy_redis_pred_unit",
                "prediction_source_type": "LEGACY_HYBRID_TRAINER_REDIS_READONLY",
                "trainer_parity_status": "BLOCKS_LEGACY_SHUTDOWN",
                "model_version": "legacy_hybrid_trainer_live_legacy",
                "checkpoint_id": "legacy_live_checkpoint_unit",
                "expected_move_bps": 20.0,
                "expected_move_source": "native_legacy_trainer_price_target",
                "expected_move_evidence_mode": "NATIVE_FIELD_PRESENT",
                "live_gate": "blocked_human_only",
                "live_symbols": [],
            }
        )
    )
    market = _market()
    feature = build_feature_snapshot(market, "tick_unit")
    prediction = build_trainer_prediction(feature, "tick_unit")
    prediction["confidence_calibrated"] = 0.78
    lineage = build_signal_lineage(
        tick_id="tick_unit",
        generated_at="2026-05-13T07:30:00Z",
        feature_snapshot=feature,
        prediction=prediction,
        market=market,
    )

    gated = apply_paper_tightening_gate(
        lineage,
        generated_at="2026-05-13T07:30:00Z",
        recent_events=[],
        now_ms=1_778_648_401_000,
    )

    assert prediction["raw_output"]["expected_move_bps"] == 20.0
    assert prediction["trainer_source"] == "LEGACY_HYBRID_TRAINER_REDIS_READONLY"
    assert gated["risk_decision"]["expected_move_source"] == "native_trainer_expected_move_bps"
    assert gated["risk_decision"]["expected_move_bps"] == 20.0
    assert gated["risk_decision"]["expected_move_after_cost_bps"] == 14.0
    assert gated["risk_decision"]["paper_edge_gate"]["fill_allowed"] is True
    assert gated["risk_decision"]["paper_edge_gate"]["min_expected_move_after_cost_bps"] == 8.0
    assert "missing_expected_move_after_costs" not in gated["risk_decision"].get(
        "canary_profile_tightening_blockers",
        [],
    )
    assert gated["risk_decision"]["canary_profile_tightening"]["expected_move_bps"] == 20.0
    assert gated["risk_decision"]["canary_profile_tightening"]["safe_for_live"] is False


def test_expected_move_model_review_forces_shadow_only_even_when_edge_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge_status = tmp_path / "v2_trainer_bridge_status.json"
    shadow_status = tmp_path / "paper_shadow_outcome_observer_status.json"
    monkeypatch.setattr(paper_runtime, "TRAINER_BRIDGE_STATUS_FILE", bridge_status)
    monkeypatch.setattr(paper_runtime, "PAPER_SHADOW_OUTCOME_STATUS_FILE", shadow_status)
    bridge_status.write_text(
        json.dumps(
            {
                "prediction_symbol": "BTCUSDT",
                "prediction_timeframe": "1m",
                "prediction_id": "legacy_redis_pred_unit",
                "prediction_source_type": "LEGACY_HYBRID_TRAINER_REDIS_READONLY",
                "trainer_parity_status": "BLOCKS_LEGACY_SHUTDOWN",
                "model_version": "legacy_hybrid_trainer_live_legacy",
                "checkpoint_id": "legacy_live_checkpoint_unit",
                "expected_move_bps": 24.0,
                "expected_move_source": "native_legacy_trainer_price_target",
                "expected_move_evidence_mode": "NATIVE_FIELD_PRESENT",
                "live_gate": "blocked_human_only",
                "live_symbols": [],
            }
        ),
        encoding="utf-8",
    )
    shadow_status.write_text(
        json.dumps(
            {
                "outcome_status": "BLOCKED_INTENTS_BEAT_COSTS_MODEL_REVIEW_REQUIRED",
                "edge_status": "EDGE_PENDING_MODEL_REVIEW_REQUIRED",
                "false_block_count": 3,
                "live_gate": "blocked_human_only",
                "live_symbols": [],
            }
        ),
        encoding="utf-8",
    )
    market = _market()
    feature = build_feature_snapshot(market, "tick_unit")
    prediction = build_trainer_prediction(feature, "tick_unit")
    prediction["confidence_calibrated"] = 0.82
    lineage = build_signal_lineage(
        tick_id="tick_unit",
        generated_at="2026-05-13T07:30:00Z",
        feature_snapshot=feature,
        prediction=prediction,
        market=market,
    )

    gated = apply_paper_tightening_gate(
        lineage,
        generated_at="2026-05-13T07:30:00Z",
        recent_events=[],
        now_ms=1_778_648_401_000,
    )

    assert gated["risk_decision"]["paper_edge_gate"]["fill_allowed"] is True
    assert gated["risk_decision"]["risk_action"] == "deny"
    assert gated["risk_decision"]["risk_reason_code"] == "deny_expected_move_model_review"
    assert "expected_move_model_review_required" in gated["risk_decision"]["canary_profile_tightening_blockers"]
    assert gated["risk_decision"]["expected_move_model_review"]["paper_fill_allowed"] is False
    assert gated["risk_decision"]["expected_move_model_review"]["uses_future_outcome_labels_for_entry"] is False
    assert gated["execution_intent"]["exchange_order_allowed"] is False


def test_native_expected_move_shadows_when_paper_outcome_model_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(paper_runtime, "PAPER_OUTCOME_MODEL_READY", False)
    bridge_status = tmp_path / "v2_trainer_bridge_status.json"
    monkeypatch.setattr(paper_runtime, "TRAINER_BRIDGE_STATUS_FILE", bridge_status)
    bridge_status.write_text(
        json.dumps(
            {
                "prediction_symbol": "BTCUSDT",
                "prediction_timeframe": "1m",
                "prediction_id": "legacy_redis_pred_unit",
                "prediction_source_type": "LEGACY_HYBRID_TRAINER_REDIS_READONLY",
                "trainer_parity_status": "BLOCKS_LEGACY_SHUTDOWN",
                "model_version": "legacy_hybrid_trainer_live_legacy",
                "checkpoint_id": "legacy_live_checkpoint_unit",
                "expected_move_bps": 20.0,
                "expected_move_source": "native_legacy_trainer_price_target",
                "expected_move_evidence_mode": "NATIVE_FIELD_PRESENT",
                "live_gate": "blocked_human_only",
                "live_symbols": [],
            }
        )
    )
    market = _market()
    feature = build_feature_snapshot(market, "tick_unit")
    prediction = build_trainer_prediction(feature, "tick_unit")
    prediction["confidence_calibrated"] = 0.78
    lineage = build_signal_lineage(
        tick_id="tick_unit",
        generated_at="2026-05-13T07:30:00Z",
        feature_snapshot=feature,
        prediction=prediction,
        market=market,
    )

    gated = apply_paper_tightening_gate(
        lineage,
        generated_at="2026-05-13T07:30:00Z",
        recent_events=[],
        now_ms=1_778_648_401_000,
    )
    ledger, account = build_paper_ledger_entry(
        tick_id="tick_unit",
        generated_at="2026-05-13T07:30:00Z",
        market=market,
        lineage=gated,
        previous_equity=10000.0,
    )

    assert gated["risk_decision"]["paper_edge_gate"]["fill_allowed"] is True
    assert gated["risk_decision"]["risk_action"] == "deny"
    assert gated["risk_decision"]["risk_reason_code"] == "deny_paper_outcome_model_missing"
    assert gated["risk_decision"]["paper_outcome_model"]["status"] == "MISSING_EXIT_LIFECYCLE_SIMULATOR"
    assert "paper_outcome_model_missing" in gated["risk_decision"]["paper_outcome_model_blockers"]
    assert "paper_outcome_model" in gated["risk_decision"]["required_blocks_checked"]
    assert ledger["paper_result"] == "NO_FILL_RISK_BLOCKED"
    assert ledger["fee_usdt"] == 0.0
    assert account["realized_pnl"] == 0.0
    assert account["open_position_count"] == 0


def test_paper_outcome_model_opens_and_closes_non_live_position(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge_status = tmp_path / "v2_trainer_bridge_status.json"
    monkeypatch.setattr(paper_runtime, "TRAINER_BRIDGE_STATUS_FILE", bridge_status)
    bridge_status.write_text(
        json.dumps(
            {
                "prediction_symbol": "BTCUSDT",
                "prediction_timeframe": "1m",
                "prediction_id": "legacy_redis_pred_unit",
                "prediction_source_type": "LEGACY_HYBRID_TRAINER_REDIS_READONLY",
                "trainer_parity_status": "BLOCKS_LEGACY_SHUTDOWN",
                "model_version": "legacy_hybrid_trainer_live_legacy",
                "checkpoint_id": "legacy_live_checkpoint_unit",
                "expected_move_bps": 22.0,
                "expected_move_source": "native_legacy_trainer_price_target",
                "expected_move_evidence_mode": "NATIVE_FIELD_PRESENT",
                "live_gate": "blocked_human_only",
                "live_symbols": [],
            }
        )
    )
    market = _market()
    feature = build_feature_snapshot(market, "tick_unit")
    prediction = build_trainer_prediction(feature, "tick_unit")
    prediction["confidence_calibrated"] = 0.8
    lineage = build_signal_lineage(
        tick_id="tick_unit",
        generated_at="2026-05-13T07:30:00Z",
        feature_snapshot=feature,
        prediction=prediction,
        market=market,
    )
    gated = apply_paper_tightening_gate(
        lineage,
        generated_at="2026-05-13T07:30:00Z",
        recent_events=[],
        now_ms=1_778_648_401_000,
    )
    open_ledger, open_account = build_paper_ledger_entry(
        tick_id="tick_open",
        generated_at="2026-05-13T07:30:00Z",
        market=market,
        lineage=gated,
        previous_equity=10000.0,
    )
    lifecycle = paper_position_lifecycle_from_entry(ledger_entry=open_ledger, lineage=gated)
    open_position = lifecycle["open_position"]
    assert open_ledger["paper_result"] == "FILLED_PAPER_ONLY"
    assert open_account["open_position_count"] == 1
    assert open_account["realized_pnl"] == -0.01
    assert open_position["status"] == "OPEN"

    entry = float(open_position["entry_price"])
    close_price = entry * (0.998 if open_position["side"] == "short" else 1.002)
    early_close_market = MarketSnapshot(
        symbol="BTCUSDT",
        price=close_price,
        source_type="READONLY_MARKET_FEED",
        source="unit_test",
        source_pointer="unit_test",
        generated_at="2026-05-13T07:31:00Z",
        last_event_at="2026-05-13T07:30:59Z",
        age_seconds=1,
        freshness_state="CURRENT",
        errors=[],
        candles=[],
    )
    held_ledger, held_account, held_lifecycle = build_position_lifecycle_entry(
        tick_id="tick_hold",
        generated_at="2026-05-13T07:31:00Z",
        market=early_close_market,
        lineage=gated,
        previous_position=open_position,
        previous_account=open_account,
    )

    assert held_ledger["paper_result"] == "POSITION_HELD_PAPER_ONLY"
    assert held_account["open_position_count"] == 1
    assert held_lifecycle["open_position"]["minimum_hold_active"] is True

    close_market = MarketSnapshot(
        symbol="BTCUSDT",
        price=close_price,
        source_type="READONLY_MARKET_FEED",
        source="unit_test",
        source_pointer="unit_test",
        generated_at="2026-05-13T07:33:01Z",
        last_event_at="2026-05-13T07:33:00Z",
        age_seconds=1,
        freshness_state="CURRENT",
        errors=[],
        candles=[],
    )
    close_ledger, close_account, close_lifecycle = build_position_lifecycle_entry(
        tick_id="tick_close",
        generated_at="2026-05-13T07:33:01Z",
        market=close_market,
        lineage=gated,
        previous_position=held_lifecycle["open_position"],
        previous_account=held_account,
    )

    assert close_ledger["paper_result"] == "POSITION_CLOSED_PAPER_ONLY"
    assert close_ledger["exit_reason"] == "TAKE_PROFIT"
    assert close_ledger["exchange_order_id"] is None
    assert close_ledger["legacy_redis_write"] is False
    assert close_account["open_position_count"] == 0
    assert close_account["realized_pnl"] > open_account["realized_pnl"]
    assert close_lifecycle["open_position"] is None


def test_runtime_payload_retains_last_closed_position_after_flat_blocked_tick(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    last_closed = {
        "status": "CLOSED",
        "symbol": "BTCUSDT",
        "closed_at": "2026-05-13T07:31:00Z",
        "realized_delta_usdt": -0.037409,
    }
    (runtime_dir / "paper_runtime_status.json").write_text(
        json.dumps(
            {
                "paper_account": {"equity": 9950.802591, "realized_pnl": -49.197409},
                "paper_loop": {"paper_event_count": 10},
                "paper_position_lifecycle": {
                    "status": "FLAT",
                    "open_position": None,
                    "last_closed_position": last_closed,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(paper_runtime, "LOCAL_RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(paper_runtime, "fetch_market_snapshot", lambda symbol: _market())

    payload, _ = paper_runtime.build_runtime_payload("BTCUSDT", 30)

    assert payload["paper_position_lifecycle"]["last_closed_position"] == last_closed
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []


def test_runtime_uses_last_closed_loss_for_loss_cooldown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    last_closed = {
        "status": "CLOSED",
        "symbol": "BTCUSDT",
        "closed_at": "2026-05-13T06:45:00Z",
        "realized_delta_usdt": -0.031919,
    }
    (runtime_dir / "paper_runtime_status.json").write_text(
        json.dumps(
            {
                "paper_account": {"equity": 9950.771904, "realized_pnl": -49.228096},
                "paper_loop": {"paper_event_count": 10},
                "paper_position_lifecycle": {
                    "status": "FLAT",
                    "open_position": None,
                    "last_closed_position": last_closed,
                },
            }
        ),
        encoding="utf-8",
    )
    bridge_status = tmp_path / "v2_trainer_bridge_status.json"
    monkeypatch.setattr(paper_runtime, "TRAINER_BRIDGE_STATUS_FILE", bridge_status)
    bridge_status.write_text(
        json.dumps(
            {
                "prediction_symbol": "BTCUSDT",
                "prediction_timeframe": "1m",
                "prediction_id": "legacy_redis_pred_unit",
                "prediction_source_type": "LEGACY_HYBRID_TRAINER_REDIS_READONLY",
                "trainer_parity_status": "BLOCKS_LEGACY_SHUTDOWN",
                "model_version": "legacy_hybrid_trainer_live_legacy",
                "checkpoint_id": "legacy_live_checkpoint_unit",
                "expected_move_bps": 24.0,
                "expected_move_source": "native_legacy_trainer_price_target",
                "expected_move_evidence_mode": "NATIVE_FIELD_PRESENT",
                "live_gate": "blocked_human_only",
                "live_symbols": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(paper_runtime, "LOCAL_RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(paper_runtime, "fetch_market_snapshot", lambda symbol: _market())
    monkeypatch.setattr(paper_runtime, "iso_now", lambda: "2026-05-13T07:30:00Z")
    fixed_now = datetime.fromisoformat("2026-05-13T07:30:00+00:00").timestamp()
    monkeypatch.setattr(paper_runtime.time, "time", lambda: fixed_now)

    payload, _ = paper_runtime.build_runtime_payload("BTCUSDT", 30)

    blockers = payload["current_risk_decision"]["canary_profile_tightening_blockers"]
    assert "loss_cooldown_active" in blockers
    assert payload["paper_ledger_tail"][0]["paper_result"] == "NO_FILL_RISK_BLOCKED"
    assert payload["paper_position_lifecycle"]["last_closed_position"] == last_closed
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []


def test_native_expected_move_below_paper_edge_threshold_still_blocks_fill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge_status = tmp_path / "v2_trainer_bridge_status.json"
    monkeypatch.setattr(paper_runtime, "TRAINER_BRIDGE_STATUS_FILE", bridge_status)
    bridge_status.write_text(
        json.dumps(
            {
                "prediction_symbol": "BTCUSDT",
                "prediction_timeframe": "1m",
                "prediction_id": "legacy_redis_pred_unit",
                "prediction_source_type": "LEGACY_HYBRID_TRAINER_REDIS_READONLY",
                "trainer_parity_status": "BLOCKS_LEGACY_SHUTDOWN",
                "model_version": "legacy_hybrid_trainer_live_legacy",
                "checkpoint_id": "legacy_live_checkpoint_unit",
                "expected_move_bps": 10.0,
                "expected_move_source": "native_legacy_trainer_price_target",
                "expected_move_evidence_mode": "NATIVE_FIELD_PRESENT",
                "live_gate": "blocked_human_only",
                "live_symbols": [],
            }
        )
    )
    market = _market()
    feature = build_feature_snapshot(market, "tick_unit")
    prediction = build_trainer_prediction(feature, "tick_unit")
    prediction["confidence_calibrated"] = 0.78
    lineage = build_signal_lineage(
        tick_id="tick_unit",
        generated_at="2026-05-13T07:30:00Z",
        feature_snapshot=feature,
        prediction=prediction,
        market=market,
    )

    gated = apply_paper_tightening_gate(
        lineage,
        generated_at="2026-05-13T07:30:00Z",
        recent_events=[],
        now_ms=1_778_648_401_000,
    )
    ledger, account = build_paper_ledger_entry(
        tick_id="tick_unit",
        generated_at="2026-05-13T07:30:00Z",
        market=market,
        lineage=gated,
        previous_equity=10000.0,
    )

    assert gated["risk_decision"]["expected_move_after_cost_bps"] == 4.0
    assert gated["risk_decision"]["canary_profile_tightening"]["blockers"] == []
    assert gated["risk_decision"]["paper_edge_gate"]["fill_allowed"] is False
    assert "EDGE_AFTER_COSTS_NEGATIVE_BLOCK" in gated["risk_decision"]["paper_edge_gate_blockers"]
    assert gated["risk_decision"]["risk_action"] == "deny"
    assert ledger["paper_result"] == "NO_FILL_RISK_BLOCKED"
    assert account["realized_pnl"] == 0.0


def test_append_paper_event_accepts_signal_confidence_calibrated(tmp_path: Path) -> None:
    payload = {
        "generated_at": "2026-05-13T07:30:00Z",
        "paper_loop": {"tick_id": "tick_unit"},
        "current_signal_lineage": {
            "lineage_ids": {
                "prediction_id": "pred_unit",
                "feature_snapshot_id": "fs_unit",
            },
            "signal": {
                "signal_id": "sig_unit",
                "confidence_calibrated": 0.77,
            },
        },
        "current_risk_decision": {
            "risk_action": "deny",
            "risk_result": "BLOCKED",
            "risk_reason_code": "deny_canary_profile_tightening",
            "canary_profile_tightening_blockers": ["missing_expected_move_after_costs"],
            "expected_move_bps": None,
            "expected_move_after_cost_bps": None,
        },
        "trainer_prediction": {
            "trainer_source": "LEGACY_HYBRID_TRAINER_REDIS_READONLY",
            "trainer_bridge_status": "BLOCKS_LEGACY_SHUTDOWN",
            "model_version": "legacy_hybrid_trainer_live_legacy",
            "model_checkpoint": "legacy_live_checkpoint_unit",
            "confidence_raw": 0.8,
            "confidence_calibrated": 0.77,
        },
        "feature_snapshot": {
            "freshness_state": "CURRENT",
            "stale_feature_flags": [],
            "missing_feature_flags": [],
        },
        "paper_account": {"equity": 10000.0, "realized_pnl": 0.0},
        "paper_ledger_tail": [
            {
                "paper_ledger_entry_id": "pledger_unit",
                "execution_intent_id": "pei_unit",
                "risk_decision_id": "risk_unit",
                "signal_id": "sig_unit",
                "symbol": "BTCUSDT",
                "ledger_action": "PAPER_INTENT_BLOCKED",
                "paper_result": "NO_FILL_RISK_BLOCKED",
                "notional_usdt": 0.0,
                "fee_usdt": 0.0,
                "slippage_bps": 2.0,
                "funding_assumption": "zero_until_funding_feed_adapter_current",
            }
        ],
    }
    risk_runtime = {"weekly_loss_gate_required": True, "weekly_loss_breach": False}

    append_paper_event(tmp_path, payload, risk_runtime)

    event = json.loads((tmp_path / "paper_events.jsonl").read_text())
    assert event["confidence"] == 0.77
    assert event["trainer_source"] == "LEGACY_HYBRID_TRAINER_REDIS_READONLY"
    assert event["feature_freshness_state"] == "CURRENT"
    assert "expected_move_after_cost_bps" in event
    assert event["live_gate"] == "blocked_human_only"
    assert event["live_symbols"] == []
    assert event["canary_profile_tightening_blockers"] == ["missing_expected_move_after_costs"]
    assert event["exchange_order"] is False
