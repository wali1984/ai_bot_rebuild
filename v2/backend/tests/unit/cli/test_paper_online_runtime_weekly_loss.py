from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli.paper_online_runtime import (
    MarketSnapshot,
    apply_paper_tightening_gate,
    append_paper_event,
    build_feature_snapshot,
    build_paper_ledger_entry,
    build_risk_runtime_payload,
    build_signal_lineage,
    build_trainer_prediction,
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
    assert event["canary_profile_tightening_blockers"] == ["missing_expected_move_after_costs"]
    assert event["exchange_order"] is False
