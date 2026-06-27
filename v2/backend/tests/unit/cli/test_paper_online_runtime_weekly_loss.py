from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import paper_online_runtime as paper_runtime
from v2.backend.app.cli.paper_online_runtime import (
    MarketSnapshot,
    apply_paper_entry_gates,
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


def _production_cost_evidence() -> dict[str, object]:
    return {
        "actual_observed_spread_entry_bps": 1.0,
        "expected_fee_bps": 4.0,
        "depth_price_impact_bps": 1.0,
        "depth_price_impact_source": "unit_test_depth",
        "expected_slippage_bps": 1.0,
        "expected_funding_bps": 0.1,
        "latency_reserve_bps": 0.2,
        "partial_fill_reserve_bps": 0.1,
        "round_trip_cost_bps": 7.4,
        "cost_uncertainty_bps": 0.5,
        "fallback": False,
        "source_timestamp": "2026-05-13T07:29:59Z",
        "evidence_freshness_seconds": 1,
        "expected_gross_edge_bps": 22.0,
    }


def _force_thesis_timeframe(lineage: dict[str, object], timeframe: str) -> None:
    for section_name in (
        "trainer_prediction",
        "signal",
        "orchestrator_decision",
        "risk_decision",
        "execution_intent",
    ):
        section = lineage.get(section_name)
        if isinstance(section, dict):
            section["timeframe"] = timeframe
            section["thesis_timeframe"] = timeframe
            section["execution_timeframe"] = "1m"
    lineage["thesis_timeframe"] = timeframe
    lineage["execution_timeframe"] = "1m"


def _existing_old_policy_position(
    *,
    side: str = "long",
    opened_at: str = "2026-05-13T07:30:00Z",
    policy_activated_at: str = "2026-05-13T07:30:00Z",
    entry_price: float = 100.0,
    notional_usdt: float = 25.0,
    funding_rate: float | None = None,
) -> dict[str, object]:
    funding_bps = None if funding_rate is None else funding_rate * 10_000.0
    funding_status = (
        "READY_FUNDING_PNL_ACCRUED"
        if funding_rate is not None
        else "MISSING_FUNDING_RATE_OR_BPS"
    )
    return {
        "status": "OPEN",
        "opened_at": opened_at,
        "policy_activated_at": policy_activated_at,
        "symbol": "BTCUSDT",
        "side": side,
        "economic_trade_id": "econ_existing_old_policy",
        "economic_thesis_id": "ethesis_existing_old_policy",
        "parent_position_id": "ppos_existing_old_policy",
        "entry_sequence": 1,
        "close_sequence": 0,
        "is_partial_reduce": False,
        "is_partial_close": False,
        "is_full_close": False,
        "is_reversal": False,
        "thesis_prediction_id": "pred_existing_old_policy",
        "execution_snapshot_id": "fs_existing_old_policy",
        "thesis_timeframe": "15m",
        "execution_timeframe": "1m",
        "entry_price": entry_price,
        "notional_usdt": notional_usdt,
        "entry_fee_usdt": round(notional_usdt * 0.0004, 6),
        "fee_rate": 0.0004,
        "funding_pnl_accounting_version": paper_runtime.FUNDING_PNL_ACCOUNTING_VERSION,
        "funding_pnl_accounting_status": funding_status,
        "funding_pnl_usd": 0.0,
        "funding_rate": funding_rate,
        "funding_bps": funding_bps,
        "expected_funding_bps": funding_bps,
        "funding_interval_seconds": 28_800,
        "funding_accrual_intervals": 0.0,
        "funding_notional_usd": notional_usdt,
        "funding_pnl_formula": paper_runtime.FUNDING_PNL_ACCOUNTING_FORMULA,
        "funding_pnl_side_sign": -1.0 if side == "long" else 1.0,
        "funding_pnl_source": (
            "FUNDING_RATE_OR_BPS_FROM_LINEAGE"
            if funding_rate is not None
            else "MISSING_FUNDING_RATE"
        ),
        "take_profit_bps": 8.0,
        "stop_loss_bps": 8.0,
        "minimum_hold_seconds": paper_runtime.PAPER_POSITION_MIN_HOLD_SECONDS,
        "paper_policy_owner": paper_runtime.PAPER_ONLINE_LEGACY_OWNER,
        "policy_id": paper_runtime.PAPER_ONLINE_LEGACY_OWNER,
        "model_source": paper_runtime.PAPER_ONLINE_LEGACY_MODEL_SOURCE,
    }


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


def test_paper_online_redis_writes_do_not_clobber_authoritative_paper_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Diagnostic paper-online output must not overwrite trade-management paper truth."""

    class FakeRedis:
        def __init__(self) -> None:
            self.store: dict[str, str] = {}

        def ping(self) -> bool:
            return True

        def get(self, key: str) -> str | None:
            return self.store.get(key)

        def set(self, key: str, value: str, *args: object, **kwargs: object) -> bool:
            self.store[key] = value
            return True

    fake = FakeRedis()
    monkeypatch.setitem(sys.modules, "redis", SimpleNamespace(Redis=lambda **_: fake))

    payload = {
        "generated_at": "2026-06-18T13:00:00Z",
        "market_feed": {"symbol": "BTCUSDT"},
        "current_signal_lineage": {
            "lineage_ids": {
                "prediction_id": "pred_unit",
                "signal_id": "sig_unit",
                "risk_decision_id": "risk_unit",
                "orchestrator_decision_id": "orch_unit",
                "execution_intent_id": "intent_unit",
            },
            "signal": {"signal_id": "sig_unit", "symbol": "BTCUSDT"},
            "risk_decision": {
                "risk_decision_id": "risk_unit",
                "risk_action": "deny",
                "risk_result": "BLOCKED",
            },
            "orchestrator_decision": {"orchestrator_decision_id": "orch_unit"},
            "execution_intent": {
                "execution_intent_id": "intent_unit",
                "symbol": "BTCUSDT",
                "side": "long",
                "exchange_order_allowed": False,
                "paper_only": True,
            },
        },
        "paper_ledger_tail": [
            {
                "paper_ledger_entry_id": "ledger_unit",
                "paper_result": "NO_FILL_RISK_BLOCKED",
            }
        ],
    }

    paper_runtime._push_decisions_to_redis(payload)

    assert paper_runtime.PAPER_ONLINE_INTENTS_KEY in fake.store
    assert paper_runtime.PAPER_ONLINE_LEDGER_KEY in fake.store
    assert paper_runtime.PAPER_ONLINE_RISK_DECISIONS_KEY in fake.store
    assert paper_runtime.PAPER_ONLINE_RISK_DECISIONS_LATEST_KEY in fake.store
    assert paper_runtime.PAPER_ONLINE_RISK_GATEWAY_DECISIONS_KEY in fake.store
    assert paper_runtime.PAPER_ONLINE_RISK_GATEWAY_DECISIONS_LATEST_KEY in fake.store
    assert "v2:paper:intents" not in fake.store
    assert "v2:paper:ledger" not in fake.store
    assert "v2:risk:decisions" not in fake.store
    assert "v2:risk:decisions:latest" not in fake.store
    assert "v2:risk:gateway:decisions" not in fake.store
    assert "v2:risk:gateway:decisions:latest" not in fake.store


def test_prediction_id_alone_is_not_sufficient_canonical_risk_trust() -> None:
    assert paper_runtime._has_complete_canonical_risk_trust_envelope({
        "prediction_id": "pred_unit",
        "feature_snapshot_id": "fs_unit",
        "symbol": "BTCUSDT",
    }) is False

    assert paper_runtime._has_complete_canonical_risk_trust_envelope({
        "prediction_id": "pred_unit",
        "decision_id": "decision_unit",
        "feature_snapshot_id": "fs_unit",
        "mtf_snapshot_id": "mtf_unit",
        "feature_cutoff": "2026-06-18T12:59:00Z",
        "decision_time": "2026-06-18T13:00:00Z",
        "available_at": "2026-06-18T12:59:30Z",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "selected_action": "long",
        "model_version": "model_v1",
        "checkpoint_id": "ckpt_v1",
        "source_hashes": {"feature_vector_hash": "hash_unit"},
    }) is True


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
                "expected_move_after_cost_bps": 14.0,
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
    assert prediction["raw_output"]["expected_move_after_cost_bps"] == 14.0
    assert prediction["expected_move_after_cost_bps"] == 14.0
    assert prediction["trainer_source"] == "LEGACY_HYBRID_TRAINER_REDIS_READONLY"
    assert lineage["signal"]["expected_move_after_cost_bps"] == 14.0
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


def test_1m_timing_preserves_1h_thesis_runtime_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge_status = tmp_path / "v2_trainer_bridge_status.json"
    monkeypatch.setattr(paper_runtime, "TRAINER_BRIDGE_STATUS_FILE", bridge_status)
    bridge_status.write_text(
        json.dumps(
            {
                "prediction_symbol": "BTCUSDT",
                "prediction_timeframe": "1h",
                "prediction_id": "legacy_redis_pred_1h_unit",
                "prediction_source_type": "LEGACY_HYBRID_TRAINER_REDIS_READONLY",
                "trainer_parity_status": "BLOCKS_LEGACY_SHUTDOWN",
                "model_version": "legacy_hybrid_trainer_live_legacy",
                "checkpoint_id": "legacy_live_checkpoint_unit",
                "expected_move_bps": 22.0,
                "expected_move_after_cost_bps": 15.0,
                "expected_move_source": "native_legacy_trainer_price_target",
                "expected_move_evidence_mode": "NATIVE_FIELD_PRESENT",
                "live_gate": "blocked_human_only",
                "live_symbols": [],
            }
        ),
        encoding="utf-8",
    )
    market = _market()
    feature = build_feature_snapshot(market, "tick_1h")
    prediction = build_trainer_prediction(feature, "tick_1h")
    lineage = build_signal_lineage(
        tick_id="tick_1h",
        generated_at="2026-05-13T07:30:00Z",
        feature_snapshot=feature,
        prediction=prediction,
        market=market,
    )

    assert feature["timeframe"] == "1m"
    assert feature["execution_timeframe"] == "1m"
    assert prediction["timeframe"] == "1h"
    assert prediction["thesis_timeframe"] == "1h"
    assert prediction["execution_timeframe"] == "1m"
    assert prediction["confirmation_timeframes"] == ["1m"]
    assert lineage["thesis_timeframe"] == "1h"
    assert lineage["execution_timeframe"] == "1m"
    assert "thesis_timeframe" in lineage["timeframe_attribution_rule"]
    for section_name in ("trainer_prediction", "signal", "risk_decision", "execution_intent"):
        section = lineage[section_name]
        assert section["timeframe"] == "1h"
        assert section["thesis_timeframe"] == "1h"
        assert section["execution_timeframe"] == "1m"


def test_paper_redis_signal_key_uses_thesis_timeframe(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.values: dict[str, str] = {}

        def ping(self) -> bool:
            return True

        def get(self, key: str) -> str | None:
            return self.values.get(key)

        def set(self, key: str, value: str) -> bool:
            self.values[key] = value
            return True

    fake = FakeRedis()
    monkeypatch.setitem(sys.modules, "redis", SimpleNamespace(Redis=lambda **_: fake))
    payload = {
        "generated_at": "2026-05-13T07:30:00Z",
        "market_feed": {"symbol": "BTCUSDT", "timeframe": "1m"},
        "feature_snapshot": {"execution_timeframe": "1m", "feature_timeframe": "1m"},
        "trainer_prediction": {
            "prediction_id": "pred_1h",
            "timeframe": "1h",
            "prediction_timeframe": "1h",
            "thesis_timeframe": "1h",
            "execution_timeframe": "1m",
        },
        "current_signal_lineage": {
            "lineage_ids": {
                "prediction_id": "pred_1h",
                "feature_snapshot_id": "fs_1m",
                "signal_id": "sig_1h",
            },
            "trainer_prediction": {
                "prediction_id": "pred_1h",
                "timeframe": "1h",
                "thesis_timeframe": "1h",
                "execution_timeframe": "1m",
            },
            "signal": {
                "signal_id": "sig_1h",
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "thesis_timeframe": "1h",
                "execution_timeframe": "1m",
            },
            "risk_decision": {
                "risk_decision_id": "risk_1h",
                "risk_action": "deny",
                "risk_result": "BLOCKED",
            },
            "orchestrator_decision": {"orchestrator_decision_id": "orch_1h"},
            "execution_intent": {
                "execution_intent_id": "pei_1h",
                "symbol": "BTCUSDT",
                "side": "long",
                "thesis_timeframe": "1h",
                "execution_timeframe": "1m",
            },
        },
        "current_risk_decision": {
            "risk_decision_id": "risk_1h",
            "risk_action": "deny",
            "risk_result": "BLOCKED",
        },
        "paper_ledger_tail": [
            {
                "paper_ledger_entry_id": "pledger_1h",
                "paper_result": "NO_FILL_RISK_BLOCKED",
            }
        ],
    }

    paper_runtime._push_decisions_to_redis(payload)

    thesis_key = "v2:signals:paper:BTCUSDT:1h"
    assert thesis_key in fake.values
    assert "v2:signals:paper:BTCUSDT:1m" not in fake.values
    signal = json.loads(fake.values[thesis_key])
    assert signal["timeframe"] == "1h"
    assert signal["thesis_timeframe"] == "1h"
    assert signal["execution_timeframe"] == "1m"


def test_missing_thesis_timeframe_denies_paper_entry() -> None:
    lineage = {
        "signal": {},
        "feature_snapshot": {},
        "trainer_prediction": {},
        "risk_decision": {
            "risk_action": "allow",
            "risk_result": "APPROVED_FOR_PAPER_ONLY",
            "risk_reason_code": "allow_proceed_long",
            "required_blocks_checked": [],
        },
        "execution_intent": {
            "symbol": "BTCUSDT",
            "side": "long",
            "exchange_order_allowed": False,
            "paper_only": True,
        },
    }

    gated = apply_paper_entry_gates(lineage)

    risk = gated["risk_decision"]
    intent = gated["execution_intent"]
    assert paper_runtime._paper_thesis_timeframe({}, {}) == paper_runtime.PAPER_UNKNOWN_THESIS_TIMEFRAME  # noqa: SLF001
    assert risk["risk_action"] == "deny"
    assert risk["risk_reason_code"] == "deny_missing_thesis_timeframe"
    assert risk["thesis_timeframe_gate"]["status"] == "BLOCKED_MISSING_OR_INVALID_THESIS_TIMEFRAME"
    assert "thesis_timeframe_gate" in risk["required_blocks_checked"]
    assert intent["intent_action"] == "paper_noop_blocked"
    assert intent["exchange_order_allowed"] is False
    assert intent["paper_only"] is True


def test_paper_entry_gate_blocks_when_churn_governor_has_no_closed_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from v2.backend.app.services.paper_trade_management import (  # noqa: PLC0415
        anti_market_maker_detector,
        entry_gate,
        high_precision_gate,
    )

    monkeypatch.setattr(
        entry_gate,
        "evaluate_entry_gate",
        lambda **_: {"allowed": True, "reasons": [], "places_real_order": False},
    )
    monkeypatch.setattr(
        high_precision_gate,
        "evaluate_high_precision_gate",
        lambda **_: {"allow": True, "reasons": [], "paper_only": True, "places_real_order": False},
    )
    monkeypatch.setattr(
        anti_market_maker_detector,
        "evaluate_all_detectors",
        lambda _: {"entry_blocked": False, "detectors": {}},
    )
    monkeypatch.setattr(paper_runtime, "_paper_reentry_dedup_runtime_rows", lambda: [])
    monkeypatch.setattr(paper_runtime, "_paper_churn_governor_runtime_rows", lambda: [])
    market = _market()
    feature = build_feature_snapshot(market, "tick_churn")
    feature["data_coverage_percent"] = 100.0
    prediction = build_trainer_prediction(feature, "tick_churn")
    prediction["confidence_calibrated"] = 0.82
    prediction["raw_output"]["side"] = "long"
    lineage = build_signal_lineage(
        tick_id="tick_churn",
        generated_at="2026-05-13T07:30:00Z",
        feature_snapshot=feature,
        prediction=prediction,
        market=market,
    )
    _force_thesis_timeframe(lineage, "1h")
    lineage["execution_intent"]["side"] = "long"
    lineage["risk_decision"]["risk_action"] = "allow"
    lineage["risk_decision"]["risk_result"] = "APPROVED_FOR_PAPER_ONLY"
    lineage["risk_decision"]["risk_reason_code"] = "allow_proceed_long"
    lineage["risk_decision"]["expected_move_after_cost_bps"] = 20.0
    lineage["risk_decision"]["expected_move_bps"] = 22.0
    lineage["risk_decision"]["paper_edge_gate"] = {
        "fee_bps": 4.0,
        "spread_bps": 1.0,
        "slippage_bps": 2.0,
        "funding_risk_bps": 0.0,
    }
    lineage["risk_decision"]["production_cost_evidence"] = _production_cost_evidence()

    gated = apply_paper_entry_gates(lineage)
    ledger, account = build_paper_ledger_entry(
        tick_id="tick_churn",
        generated_at="2026-05-13T07:30:00Z",
        market=market,
        lineage=gated,
        previous_equity=10000.0,
    )

    churn_gate = gated["risk_decision"]["paper_churn_governor"]
    assert gated["risk_decision"]["risk_action"] == "deny"
    assert gated["risk_decision"]["risk_reason_code"] == "deny_paper_churn_governor"
    assert "paper_churn_governor" in gated["risk_decision"]["required_blocks_checked"]
    assert churn_gate["status"] == "BLOCKED_PAPER_CHURN_GOVERNOR_ENTRY_GATE"
    assert churn_gate["runtime_wired_to_entry_gate"] is True
    assert "no_economic_outcome_rows_for_churn_governor" in churn_gate["reasons"]
    assert ledger["paper_result"] == "NO_FILL_RISK_BLOCKED"
    assert account["open_position_count"] == 0
    assert gated["execution_intent"]["exchange_order_allowed"] is False


def test_paper_entry_gate_blocks_missing_production_grade_cost_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from v2.backend.app.services.paper_trade_management import (  # noqa: PLC0415
        entry_gate,
        high_precision_gate,
    )

    monkeypatch.setattr(
        entry_gate,
        "evaluate_entry_gate",
        lambda **_: {"allowed": True, "reasons": [], "places_real_order": False},
    )
    monkeypatch.setattr(
        high_precision_gate,
        "evaluate_high_precision_gate",
        lambda **_: {"allow": True, "reasons": [], "paper_only": True, "places_real_order": False},
    )
    monkeypatch.setattr(paper_runtime, "_paper_reentry_dedup_runtime_rows", lambda: [])
    market = _market()
    feature = build_feature_snapshot(market, "tick_cost")
    feature["data_coverage_percent"] = 100.0
    prediction = build_trainer_prediction(feature, "tick_cost")
    prediction["confidence_calibrated"] = 0.82
    prediction["raw_output"]["side"] = "long"
    lineage = build_signal_lineage(
        tick_id="tick_cost",
        generated_at="2026-05-13T07:30:00Z",
        feature_snapshot=feature,
        prediction=prediction,
        market=market,
    )
    lineage["execution_intent"]["side"] = "long"
    lineage["risk_decision"]["risk_action"] = "allow"
    lineage["risk_decision"]["risk_result"] = "APPROVED_FOR_PAPER_ONLY"
    lineage["risk_decision"]["risk_reason_code"] = "allow_proceed_long"
    lineage["risk_decision"]["expected_move_after_cost_bps"] = 20.0
    lineage["risk_decision"]["expected_move_bps"] = 22.0
    lineage["risk_decision"]["paper_edge_gate"] = {
        "fee_bps": 4.0,
        "spread_bps": 1.0,
        "slippage_bps": 2.0,
        "funding_risk_bps": 0.0,
    }

    gated = apply_paper_entry_gates(lineage)
    ledger, account = build_paper_ledger_entry(
        tick_id="tick_cost",
        generated_at="2026-05-13T07:30:00Z",
        market=market,
        lineage=gated,
        previous_equity=10000.0,
    )

    cost_gate = gated["risk_decision"]["paper_entry_production_cost_gate"]
    assert gated["risk_decision"]["risk_action"] == "deny"
    assert gated["risk_decision"]["risk_reason_code"] == "deny_paper_entry_cost_gate"
    assert "paper_entry_production_cost_gate" in gated["risk_decision"]["required_blocks_checked"]
    assert cost_gate["status"] == "BLOCKED_PAPER_ENTRY_PRODUCTION_COST_GATE"
    assert "missing_production_grade_cost_evidence" in cost_gate["blockers"]
    assert "depth_derived_price_impact" in cost_gate["missing_cost_fields"]
    assert "fallback_flag_false" in cost_gate["missing_cost_fields"]
    assert ledger["paper_result"] == "NO_FILL_RISK_BLOCKED"
    assert account["open_position_count"] == 0
    assert gated["execution_intent"]["exchange_order_allowed"] is False


def test_paper_entry_gate_blocks_duplicate_prediction_before_cost_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from v2.backend.app.services.paper_trade_management import (  # noqa: PLC0415
        entry_gate,
        high_precision_gate,
    )

    monkeypatch.setattr(
        entry_gate,
        "evaluate_entry_gate",
        lambda **_: {"allowed": True, "reasons": [], "places_real_order": False},
    )
    monkeypatch.setattr(
        high_precision_gate,
        "evaluate_high_precision_gate",
        lambda **_: {"allow": True, "reasons": [], "paper_only": True, "places_real_order": False},
    )
    market = _market()
    feature = build_feature_snapshot(market, "tick_dedup")
    feature["data_coverage_percent"] = 100.0
    prediction = build_trainer_prediction(feature, "tick_dedup")
    prediction["confidence_calibrated"] = 0.82
    prediction["raw_output"]["side"] = "long"
    lineage = build_signal_lineage(
        tick_id="tick_dedup",
        generated_at="2026-05-13T07:30:00Z",
        feature_snapshot=feature,
        prediction=prediction,
        market=market,
    )
    lineage["execution_intent"]["side"] = "long"
    lineage["risk_decision"]["risk_action"] = "allow"
    lineage["risk_decision"]["risk_result"] = "APPROVED_FOR_PAPER_ONLY"
    lineage["risk_decision"]["risk_reason_code"] = "allow_proceed_long"
    lineage["risk_decision"]["expected_move_after_cost_bps"] = 20.0
    lineage["risk_decision"]["expected_move_bps"] = 22.0
    previous_row = {
        "paper_result": "FILLED_PAPER_ONLY",
        "exchange_order": False,
        "symbol": "BTCUSDT",
        "timeframe": lineage["trainer_prediction"]["timeframe"],
        "thesis_timeframe": lineage["trainer_prediction"]["thesis_timeframe"],
        "side": "LONG",
        "strategy_id": "paper_runtime_momentum",
        "prediction_id": lineage["trainer_prediction"]["prediction_id"],
        "signal_id": lineage["signal"]["signal_id"],
        "feature_snapshot_id": lineage["feature_snapshot"]["feature_snapshot_id"],
        "risk_decision_id": lineage["risk_decision"]["risk_decision_id"],
        "generated_at": "2026-05-13T07:29:00Z",
    }
    monkeypatch.setattr(paper_runtime, "_paper_reentry_dedup_runtime_rows", lambda: [previous_row])

    gated = apply_paper_entry_gates(lineage)
    ledger, account = build_paper_ledger_entry(
        tick_id="tick_dedup",
        generated_at="2026-05-13T07:30:00Z",
        market=market,
        lineage=gated,
        previous_equity=10000.0,
    )

    dedup_gate = gated["risk_decision"]["paper_reentry_dedup_gate"]
    assert gated["risk_decision"]["risk_action"] == "deny"
    assert gated["risk_decision"]["risk_reason_code"] == "deny_paper_reentry_dedup"
    assert "paper_reentry_dedup_gate" in gated["risk_decision"]["required_blocks_checked"]
    assert dedup_gate["status"] == "BLOCKED_PAPER_REENTRY_DEDUP_GATE"
    assert "same_prediction_id" in dedup_gate["blockers"]
    assert "prediction_id" in dedup_gate["duplicate_identity_fields"]
    assert "paper_entry_production_cost_gate" not in gated["risk_decision"]
    assert ledger["paper_result"] == "NO_FILL_RISK_BLOCKED"
    assert account["open_position_count"] == 0
    assert gated["execution_intent"]["exchange_order_allowed"] is False


def test_paper_entry_gate_blocks_standalone_1m_without_dedicated_strategy_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from v2.backend.app.services.paper_trade_management import (  # noqa: PLC0415
        entry_gate,
        high_precision_gate,
    )

    monkeypatch.setattr(
        entry_gate,
        "evaluate_entry_gate",
        lambda **_: {"allowed": True, "reasons": [], "places_real_order": False},
    )
    monkeypatch.setattr(
        high_precision_gate,
        "evaluate_high_precision_gate",
        lambda **_: {"allow": True, "reasons": [], "paper_only": True, "places_real_order": False},
    )
    monkeypatch.setattr(paper_runtime, "_paper_reentry_dedup_runtime_rows", lambda: [])
    market = _market()
    feature = build_feature_snapshot(market, "tick_1m_gate")
    feature["data_coverage_percent"] = 100.0
    prediction = build_trainer_prediction(feature, "tick_1m_gate")
    prediction["confidence_calibrated"] = 0.82
    prediction["raw_output"]["side"] = "long"
    lineage = build_signal_lineage(
        tick_id="tick_1m_gate",
        generated_at="2026-05-13T07:30:00Z",
        feature_snapshot=feature,
        prediction=prediction,
        market=market,
    )
    lineage["execution_intent"]["side"] = "long"
    lineage["risk_decision"]["risk_action"] = "allow"
    lineage["risk_decision"]["risk_result"] = "APPROVED_FOR_PAPER_ONLY"
    lineage["risk_decision"]["risk_reason_code"] = "allow_proceed_long"
    lineage["risk_decision"]["expected_move_after_cost_bps"] = 20.0
    lineage["risk_decision"]["expected_move_bps"] = 22.0
    lineage["risk_decision"]["paper_edge_gate"] = {
        "fee_bps": 4.0,
        "spread_bps": 1.0,
        "slippage_bps": 2.0,
        "funding_risk_bps": 0.0,
    }
    lineage["risk_decision"]["production_cost_evidence"] = _production_cost_evidence()

    gated = apply_paper_entry_gates(lineage)
    ledger, account = build_paper_ledger_entry(
        tick_id="tick_1m_gate",
        generated_at="2026-05-13T07:30:00Z",
        market=market,
        lineage=gated,
        previous_equity=10000.0,
    )

    one_minute_gate = gated["risk_decision"]["paper_standalone_1m_eligibility"]
    assert gated["risk_decision"]["risk_action"] == "deny"
    assert gated["risk_decision"]["risk_reason_code"] == "deny_paper_standalone_1m_eligibility"
    assert "paper_standalone_1m_eligibility" in gated["risk_decision"]["required_blocks_checked"]
    assert one_minute_gate["status"] == "BLOCKED_PAPER_STANDALONE_1M_ELIGIBILITY"
    assert one_minute_gate["standalone_1m_thesis"] is True
    assert one_minute_gate["dedicated_strategy_bucket"] is False
    assert "standalone_1m_thesis_requires_dedicated_strategy_bucket" in one_minute_gate["blockers"]
    assert "paper_churn_governor" not in gated["risk_decision"]
    assert ledger["paper_result"] == "NO_FILL_RISK_BLOCKED"
    assert account["open_position_count"] == 0
    assert gated["execution_intent"]["exchange_order_allowed"] is False


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
    assert lifecycle["open_position"] is None
    assert open_ledger["paper_result"] == "NO_FILL_RISK_BLOCKED"
    assert open_ledger["paper_entry_owner_gate"]["block_reason"] == (
        paper_runtime.PAPER_ONLINE_NEW_ENTRY_BLOCK_REASON
    )
    assert open_ledger["notional_usdt"] == 0.0
    assert open_account["open_position_count"] == 0
    assert open_account["realized_pnl"] == 0.0
    open_position = _existing_old_policy_position(
        side=gated["execution_intent"]["side"],
        entry_price=100.0,
    )
    open_account = {"realized_pnl": 0.0, "open_position_count": 1}
    assert open_ledger["entry_sequence"] == 0
    assert open_ledger["close_sequence"] == 0
    assert open_ledger["is_partial_reduce"] is False
    assert open_ledger["is_partial_close"] is False
    assert open_ledger["is_full_close"] is False
    assert open_ledger["is_reversal"] is False

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
    assert held_ledger["economic_trade_id"] == open_position["economic_trade_id"]
    assert held_ledger["economic_thesis_id"] == open_position["economic_thesis_id"]
    assert held_ledger["parent_position_id"] == open_position["parent_position_id"]
    assert held_ledger["entry_sequence"] == 1
    assert held_ledger["close_sequence"] == 0
    assert held_ledger["is_full_close"] is False
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
    assert close_ledger["economic_trade_id"] == open_position["economic_trade_id"]
    assert close_ledger["economic_thesis_id"] == open_position["economic_thesis_id"]
    assert close_ledger["parent_position_id"] == open_position["parent_position_id"]
    assert close_ledger["entry_sequence"] == 1
    assert close_ledger["close_sequence"] == 1
    assert close_ledger["is_partial_reduce"] is False
    assert close_ledger["is_partial_close"] is False
    assert close_ledger["is_full_close"] is True
    assert close_ledger["is_reversal"] is False
    assert close_ledger["exchange_order_id"] is None
    assert close_ledger["legacy_redis_write"] is False
    assert close_account["open_position_count"] == 0
    assert close_account["realized_pnl"] > open_account["realized_pnl"]
    assert close_lifecycle["open_position"] is None
    assert close_lifecycle["last_closed_position"]["economic_trade_id"] == open_position["economic_trade_id"]


def test_position_lifecycle_records_policy_activation_and_signed_funding_pnl(
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
                "expected_move_after_cost_bps": 16.0,
                "expected_move_source": "native_legacy_trainer_price_target",
                "expected_move_evidence_mode": "NATIVE_FIELD_PRESENT",
                "live_gate": "blocked_human_only",
                "live_symbols": [],
            }
        )
    )
    market = _market()
    feature = build_feature_snapshot(market, "tick_unit")
    feature["features"]["funding_rate"] = 0.0001
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
    open_position = paper_position_lifecycle_from_entry(
        ledger_entry=open_ledger,
        lineage=gated,
    )["open_position"]
    assert open_ledger["paper_result"] == "NO_FILL_RISK_BLOCKED"
    assert open_ledger["policy_activated_at"] is None
    assert open_position is None
    open_position = _existing_old_policy_position(
        side=gated["execution_intent"]["side"],
        entry_price=100.0,
        funding_rate=0.0001,
    )
    open_account = {"realized_pnl": 0.0, "open_position_count": 1}
    close_market = MarketSnapshot(
        symbol="BTCUSDT",
        price=float(open_position["entry_price"]) * (0.998 if open_position["side"] == "short" else 1.002),
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
        previous_position=open_position,
        previous_account=open_account,
    )
    side_sign = -1.0 if open_position["side"] == "long" else 1.0
    expected_funding = round(25.0 * 0.0001 * (181 / 28800) * side_sign, 6)

    assert open_position["policy_activated_at"] == "2026-05-13T07:30:00Z"
    assert open_position["funding_rate"] == 0.0001
    assert open_position["funding_pnl_accounting_status"] == "READY_FUNDING_PNL_ACCRUED"
    assert close_ledger["policy_activated_at"] == "2026-05-13T07:30:00Z"
    assert close_ledger["funding_pnl_accounting_status"] == "READY_FUNDING_PNL_ACCRUED"
    assert close_ledger["funding_pnl_usd"] == pytest.approx(expected_funding)
    assert close_lifecycle["last_closed_position"]["funding_pnl_usd"] == pytest.approx(expected_funding)
    assert close_account["realized_pnl"] == pytest.approx(
        round(open_account["realized_pnl"] + close_ledger["realized_delta_usdt"], 6)
    )


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


def _base_append_payload(*, result: str = "NO_FILL_RISK_BLOCKED", side: str = "long") -> dict:
    return {
        "generated_at": "2026-06-17T10:00:00Z",
        "paper_loop": {"tick_id": "tick_new_fields"},
        "current_signal_lineage": {
            "lineage_ids": {"prediction_id": "pred_nf", "feature_snapshot_id": "fs_nf"},
            "signal": {"signal_id": "sig_nf"},
            "execution_intent": {"execution_intent_id": "pei_nf", "side": side},
        },
        "current_risk_decision": {
            "risk_action": "deny" if result == "NO_FILL_RISK_BLOCKED" else "allow",
            "risk_result": "BLOCKED" if result == "NO_FILL_RISK_BLOCKED" else "APPROVED_FOR_PAPER_ONLY",
            "risk_reason_code": "deny_canary_profile_tightening" if result == "NO_FILL_RISK_BLOCKED" else "allow_proceed_long",
            "canary_profile_tightening_blockers": [],
        },
        "trainer_prediction": {
            "trainer_source": "LEGACY",
            "trainer_bridge_status": "OK",
            "model_version": "v1",
            "model_checkpoint": "ckpt1",
            "confidence_raw": 0.8,
            "confidence_calibrated": 0.8,
            "timeframe": "15m",
        },
        "feature_snapshot": {
            "freshness_state": "CURRENT",
            "stale_feature_flags": [],
            "missing_feature_flags": [],
        },
        "paper_account": {"equity": 9999.0, "realized_pnl": -1.0},
        "paper_ledger_tail": [
            {
                "paper_ledger_entry_id": "pledger_nf",
                "economic_trade_id": "econ_unit",
                "economic_thesis_id": "ethesis_unit",
                "parent_position_id": "ppos_unit",
                "entry_sequence": 1,
                "close_sequence": 0,
                "is_partial_reduce": False,
                "is_partial_close": False,
                "is_full_close": False,
                "is_reversal": False,
                "thesis_prediction_id": "pred_nf",
                "execution_snapshot_id": "fs_nf",
                "thesis_timeframe": "15m",
                "execution_timeframe": "1m",
                "execution_intent_id": "pei_nf",
                "risk_decision_id": "risk_nf",
                "signal_id": "sig_nf",
                "symbol": "BTCUSDT",
                "ledger_action": "PAPER_INTENT_BLOCKED" if result == "NO_FILL_RISK_BLOCKED" else "PAPER_FILL_SIMULATED",
                "paper_result": result,
                "notional_usdt": 0.0 if result == "NO_FILL_RISK_BLOCKED" else 25.0,
                "fee_usdt": 0.0,
                "slippage_bps": 2.0,
                "funding_assumption": "zero_until_funding_feed_adapter_current",
            }
        ],
    }


def test_append_paper_event_emits_timeframe_and_side(tmp_path: Path) -> None:
    payload = _base_append_payload()
    append_paper_event(tmp_path, payload, {"weekly_loss_gate_required": True, "weekly_loss_breach": False})
    event = json.loads((tmp_path / "paper_events.jsonl").read_text())
    assert event["timeframe"] == "15m"
    assert event["side"] == "long"
    assert event["economic_trade_id"] == "econ_unit"
    assert event["economic_thesis_id"] == "ethesis_unit"
    assert event["parent_position_id"] == "ppos_unit"
    assert event["thesis_timeframe"] == "15m"
    assert event["execution_timeframe"] == "1m"
    assert event["paper_action"] == "paper_long"


def test_append_paper_event_feedback_sent_false_for_blocked(tmp_path: Path) -> None:
    payload = _base_append_payload(result="NO_FILL_RISK_BLOCKED")
    append_paper_event(tmp_path, payload, {"weekly_loss_gate_required": True, "weekly_loss_breach": False})
    event = json.loads((tmp_path / "paper_events.jsonl").read_text())
    assert event["feedback_sent"] is False


def test_append_paper_event_feedback_sent_false_for_fill(tmp_path: Path) -> None:
    payload = _base_append_payload(result="FILLED_PAPER_ONLY")
    append_paper_event(tmp_path, payload, {"weekly_loss_gate_required": True, "weekly_loss_breach": False})
    event = json.loads((tmp_path / "paper_events.jsonl").read_text())
    assert event["feedback_sent"] is False


def test_append_paper_event_feedback_sent_true_for_closed(tmp_path: Path) -> None:
    payload = _base_append_payload(result="POSITION_CLOSED_PAPER_ONLY")
    payload["paper_ledger_tail"][0]["paper_result"] = "POSITION_CLOSED_PAPER_ONLY"
    append_paper_event(tmp_path, payload, {"weekly_loss_gate_required": True, "weekly_loss_breach": False})
    event = json.loads((tmp_path / "paper_events.jsonl").read_text())
    assert event["feedback_sent"] is True


def test_append_paper_event_leverage_recommendation_none_when_absent(tmp_path: Path) -> None:
    payload = _base_append_payload()
    append_paper_event(tmp_path, payload, {"weekly_loss_gate_required": True, "weekly_loss_breach": False})
    event = json.loads((tmp_path / "paper_events.jsonl").read_text())
    assert event["leverage_recommendation"] is None


def test_append_paper_event_leverage_recommendation_present_when_set(tmp_path: Path) -> None:
    payload = _base_append_payload(result="FILLED_PAPER_ONLY")
    payload["current_risk_decision"]["leverage_recommendation"] = {
        "recommended_leverage": 2,
        "margin_mode": "isolated",
        "mutates_exchange": False,
    }
    append_paper_event(tmp_path, payload, {"weekly_loss_gate_required": True, "weekly_loss_breach": False})
    event = json.loads((tmp_path / "paper_events.jsonl").read_text())
    assert isinstance(event["leverage_recommendation"], dict)
    assert event["leverage_recommendation"]["recommended_leverage"] == 2
    assert event["leverage_recommendation"]["mutates_exchange"] is False


def test_append_paper_event_anti_mm_blocked_false_when_absent(tmp_path: Path) -> None:
    payload = _base_append_payload()
    append_paper_event(tmp_path, payload, {"weekly_loss_gate_required": True, "weekly_loss_breach": False})
    event = json.loads((tmp_path / "paper_events.jsonl").read_text())
    assert event["anti_mm_entry_blocked"] is False


def test_append_paper_event_exchange_order_always_false(tmp_path: Path) -> None:
    for result in ("NO_FILL_RISK_BLOCKED", "FILLED_PAPER_ONLY", "POSITION_CLOSED_PAPER_ONLY"):
        payload = _base_append_payload(result=result)
        if result == "POSITION_CLOSED_PAPER_ONLY":
            payload["paper_ledger_tail"][0]["paper_result"] = result
        p = tmp_path / result
        p.mkdir()
        append_paper_event(p, payload, {"weekly_loss_gate_required": True, "weekly_loss_breach": False})
        event = json.loads((p / "paper_events.jsonl").read_text())
        assert event["exchange_order"] is False, f"exchange_order must be False for {result}"
