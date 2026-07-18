from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services import all_timeframe_prediction_signal_price_target_publisher as svc
from v2.backend.app.services.all_timeframe_prediction_signal_price_target_publisher import (
    GATE_BLOCKED,
    REQUIRED_TIMEFRAMES,
    V2KeyValueStore,
    build_packet,
    default_paths,
)


class _MemoryClient:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str) -> bool:
        self.store[key] = value
        return True

    def scan_iter(self, match: str | None = None, count: int | None = None):
        del count
        keys = list(self.store)
        if not match:
            yield from keys
            return
        if match.endswith("*"):
            prefix = match[:-1]
            for key in keys:
                if key.startswith(prefix):
                    yield key
            return
        for key in keys:
            if key == match:
                yield key


def _write_symbol_scope(paths: svc.PublisherPaths, symbols: list[str]) -> None:
    paths.symbol_universe_path.parent.mkdir(parents=True, exist_ok=True)
    paths.symbol_universe_path.write_text(
        json.dumps({"generated_at": svc.est_now(), "paper_symbols": symbols, "training_symbols": symbols}),
        encoding="utf-8",
    )


def _seed_price(client: _MemoryClient, symbol: str, price: float = 100.0) -> None:
    client.set(
        f"v2:market:prices:{symbol}",
        json.dumps(
            {
                "symbol": symbol,
                "source": "binance_public_rest",
                "ticker_24hr": {"lastPrice": str(price)},
                "fetched_utc": svc.est_now(),
                "live_gate": "blocked_human_only",
                "live_symbols": [],
            }
        ),
    )


def _seed_closed_price(client: _MemoryClient, symbol: str, price: float = 100.0) -> None:
    client.set(
        f"v2:market:ohlcv_closed:binance:{symbol}:1m",
        json.dumps(
            [
                {
                    "symbol": symbol,
                    "timeframe": "1m",
                    "candle_open_time": 1_781_179_440_000,
                    "candle_close_time": 1_781_179_499_000,
                    "available_at": 1_781_179_500_000,
                    "candle_closed_confirmed": True,
                    "closed_candle": True,
                    "close": price,
                }
            ]
        ),
    )


def test_iso_utc_preserves_millisecond_precision_when_present() -> None:
    assert svc.iso_utc("2026-06-22T07:36:01.914Z") == "2026-06-22T07:36:01.914Z"
    assert svc.iso_utc("2026-06-22T07:36:01Z") == "2026-06-22T07:36:01Z"


def _seed_feature_snapshot(client: _MemoryClient, symbol: str, timeframe: str) -> None:
    client.set(
        svc.feature_latest_key(symbol, timeframe),
        json.dumps(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "feature_snapshot_id": f"fs_{symbol}_{timeframe}",
                "generated_at": svc.est_now(),
                "feature_freshness_state": "CURRENT",
                "trainer_consumable": True,
                "missing_feature_count": 0,
                "stale_feature_count": 0,
                "features": {
                    "open": 99.0,
                    "high": 101.0,
                    "low": 98.0,
                    "close": 100.0,
                },
            }
        ),
    )


def _prediction(symbol: str, timeframe: str, *, generated: str | None = None, expected: Any = 25.0, after: Any = 13.0) -> dict[str, Any]:
    generated_at = generated or svc.est_now()
    return {
        "prediction_id": f"pred_{symbol}_{timeframe}",
        "decision_id": f"decision_{symbol}_{timeframe}",
        "generated_est": generated_at,
        "available_at": generated_at,
        "decision_time": generated_at,
        "feature_cutoff": generated_at,
        "symbol": symbol,
        "timeframe": timeframe,
        "trainer_source": svc.TRAINER_SOURCE_REQUIRED,
        "model_source": svc.MODEL_SOURCE_REQUIRED,
        "model_version": svc.MODEL_SOURCE_REQUIRED,
        "checkpoint_id": f"ckpt_{symbol}_{timeframe}",
        "mtf_snapshot_id": f"mtf_{symbol}_{timeframe}",
        "source_hashes": {
            "feature_vector_hash": f"fv_{symbol}_{timeframe}",
            "input_feature_hash": f"ih_{symbol}_{timeframe}",
            "source_timestamp_hash": f"ts_{symbol}_{timeframe}",
        },
        "selected_action": "long",
        "selected_action_index": 1,
        "policy_action_probabilities": [0.1, 0.8, 0.1],
        "confidence_raw": 0.8,
        "confidence_calibrated": 0.76,
        "expected_move_bps": expected,
        "expected_move_after_cost_bps": after,
        "policy_value": 0.2,
        "masa_signal": 0.1,
        "feature_snapshot_id": f"fs_{symbol}_{timeframe}",
        "data_coverage_percent": 100.0,
        "missing_feature_count": 0,
        "stale_feature_count": 0,
        "confidence_calibration": {"calibration_source": "temperature_plus_data_quality_downrating"},
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }


def _paper_ready_prediction_from_available_at(
    symbol: str,
    timeframe: str,
    *,
    available_at: str,
    decision_time: str | None = None,
    action: str = "long",
) -> dict[str, Any]:
    prediction = _prediction(symbol, timeframe, generated=available_at, expected=25.0, after=13.0)
    prediction.pop("generated_est", None)
    prediction.update(
        {
            "selected_action": action,
            "selected_action_index": {"hold": 0, "long": 1, "short": 2}.get(action, 1),
            "available_at": available_at,
            "decision_time": decision_time or available_at,
            "feature_cutoff": decision_time or available_at,
            "paper_fill_allowed": True,
            "routes_to_orchestrator": True,
            "market_state_id": f"mstate_{symbol}_{timeframe}",
            "market_state_integrity_score": 96.0,
            "valid_for_training": True,
            "valid_for_prediction": True,
            "valid_for_risk": True,
            "valid_for_orchestrator": True,
            "valid_for_paper": True,
            "valid_for_live": False,
            "market_state_reject_reasons": [],
        }
    )
    return prediction


def _utc_now_minus(seconds: int) -> str:
    return (
        svc.dt.datetime.now(svc.dt.timezone.utc)
        - svc.dt.timedelta(seconds=seconds)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")


def _ok_production(monkeypatch) -> None:
    monkeypatch.setattr(
        svc,
        "fetch_production_routes",
        lambda base_url, routes: [
            {"route": route, "url": f"{base_url}{route}", "http_status": 200, "content_hash": "ok", "content_length": 10, "error": None}
            for route in routes
        ],
    )


def test_prediction_row_uses_available_at_as_audited_prediction_timestamp() -> None:
    available_at = _utc_now_minus(30)
    prediction = _paper_ready_prediction_from_available_at("BTCUSDT", "1m", available_at=available_at)

    row = svc.build_prediction_row(
        symbol="BTCUSDT",
        timeframe="1m",
        prediction=prediction,
        price_payload={"ticker_24hr": {"lastPrice": "100.0"}},
        feature_payload=None,
        stale_seconds=900,
    )

    assert row["status"] == "PRESENT_CURRENT"
    assert row["paper_fill_allowed"] is True
    assert row["routes_to_orchestrator"] is True
    assert row["prediction_timestamp_source_field"] == "available_at"
    assert row["available_at"] == available_at
    assert row["decision_time"] == available_at
    assert row["source_lineage"]["prediction_timestamp_source_field"] == "available_at"
    assert row["source_lineage"]["prediction_available_at"] == available_at
    assert row["prediction_temporal_block_reasons"] == []


def test_prediction_row_uses_exact_feature_snapshot_masks_for_missing_lineage() -> None:
    available_at = _utc_now_minus(30)
    prediction = _paper_ready_prediction_from_available_at("BTCUSDT", "1m", available_at=available_at)
    prediction.update(
        {
            "missing_feature_count": 192,
            "missing_feature_names": ["close"],
            "market_state_integrity_score": 87.5,
            "market_state_reject_reasons": ["MISSING_CRITICAL_FEATURE_FAMILY"],
            "market_state_score_components": {
                "data_freshness_score": 100.0,
                "candle_completion_score": 100.0,
                "tf_alignment_score": 100.0,
                "missing_data_score": 0.0,
                "source_disagreement_score": 100.0,
                "latency_score": 100.0,
                "backfill_score": 100.0,
                "execution_fill_quality_score": 100.0,
            },
        }
    )
    feature_payload = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_snapshot_id": prediction["feature_snapshot_id"],
        "missing_feature_count": 192,
        "missing_mask": {"open": False, "high": False, "low": False, "close": False},
        "stale_mask": {"open": False, "close": False},
        "source_availability": {"ohlcv": True, "orderbook": True},
        "features": {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
        },
    }

    row = svc.build_prediction_row(
        symbol="BTCUSDT",
        timeframe="1m",
        prediction=prediction,
        price_payload={"ticker_24hr": {"lastPrice": "100.0"}},
        feature_payload=feature_payload,
        stale_seconds=900,
    )
    signal = svc.build_signal_from_row(
        row,
        existing_signal={
            "risk_decision_id": "risk_1",
            "orchestrator_decision_id": "orch_1",
            "paper_intent_id": "intent_1",
            "paper_ledger_id": "ledger_1",
        },
    )

    assert row["missing_feature_count"] == 0
    assert row["missing_feature_names"] == []
    assert row["missing_mask"]["close"] is False
    assert row["source_availability"] == {"ohlcv": True, "orderbook": True}
    assert "MISSING_CRITICAL_FEATURE_FAMILY" not in row["market_state_reject_reasons"]
    assert row["paper_fill_allowed"] is True
    assert signal["missing_feature_count"] == 0
    assert signal["missing_mask"]["close"] is False
    assert signal["source_availability"] == {"ohlcv": True, "orderbook": True}


def test_prediction_row_preserves_trust_envelope_and_normalizes_epoch_cutoff() -> None:
    now = svc.dt.datetime.now(svc.dt.timezone.utc)
    decision = (now - svc.dt.timedelta(seconds=30)).isoformat(timespec="seconds").replace("+00:00", "Z")
    cutoff_dt = now - svc.dt.timedelta(seconds=90)
    cutoff_ms = int(cutoff_dt.timestamp() * 1000)
    expected_cutoff = (
        svc.dt.datetime.fromtimestamp(cutoff_ms / 1000, tz=svc.dt.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    prediction = _paper_ready_prediction_from_available_at("BTCUSDT", "1h", available_at=decision)
    prediction["feature_cutoff"] = cutoff_ms
    prediction["masa_feature_cutoff"] = cutoff_ms

    row = svc.build_prediction_row(
        symbol="BTCUSDT",
        timeframe="1h",
        prediction=prediction,
        price_payload={"ticker_24hr": {"lastPrice": "100.0"}},
        feature_payload=None,
        stale_seconds=900,
    )
    signal = svc.build_signal_from_row(
        row,
        existing_signal={
            "risk_decision_id": "risk_1",
            "orchestrator_decision_id": "orch_1",
            "paper_intent_id": "intent_1",
            "paper_ledger_id": "ledger_1",
        },
    )

    assert row["feature_cutoff"] == expected_cutoff
    assert row["masa_feature_cutoff"] == expected_cutoff
    assert row["model_version"] == svc.MODEL_SOURCE_REQUIRED
    assert row["checkpoint_id"] == "ckpt_BTCUSDT_1h"
    assert row["mtf_snapshot_id"] == "mtf_BTCUSDT_1h"
    assert row["decision_id"] == "decision_BTCUSDT_1h"
    assert row["signal_id"]
    assert row["source_hashes"] == {
        "feature_vector_hash": "fv_BTCUSDT_1h",
        "input_feature_hash": "ih_BTCUSDT_1h",
        "source_timestamp_hash": "ts_BTCUSDT_1h",
    }
    assert signal["signal_id"] == row["signal_id"]
    assert signal["feature_cutoff"] == expected_cutoff
    assert signal["model_version"] == row["model_version"]
    assert signal["checkpoint_id"] == row["checkpoint_id"]
    assert signal["mtf_snapshot_id"] == row["mtf_snapshot_id"]
    assert signal["decision_id"] == row["decision_id"]
    assert signal["source_hashes"] == row["source_hashes"]


def test_prediction_row_propagates_pit_market_cost_evidence_to_signal() -> None:
    decision_time = _utc_now_minus(30)
    feature_available_at = _utc_now_minus(45)
    prediction = _paper_ready_prediction_from_available_at("BTCUSDT", "1m", available_at=decision_time)
    prediction["expected_slippage_bps"] = 1.25
    prediction["fee_bps"] = 4.0
    feature_payload = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_snapshot_id": prediction["feature_snapshot_id"],
        "available_at": feature_available_at,
        "generated_at": feature_available_at,
        "feature_cutoff": feature_available_at,
        "features": {
            "bid_ask_spread_bps": 1.75,
            "funding_rate": -0.00012,
            "orderbook_depth_usd": 250000.0,
        },
    }

    row = svc.build_prediction_row(
        symbol="BTCUSDT",
        timeframe="1m",
        prediction=prediction,
        price_payload={"ticker_24hr": {"lastPrice": "100.0"}},
        feature_payload=feature_payload,
        stale_seconds=900,
    )
    signal = svc.build_signal_from_row(
        row,
        existing_signal={
            "risk_decision_id": "risk_1",
            "paper_intent_id": "intent_1",
            "paper_ledger_id": "ledger_1",
        },
    )

    assert row["market_cost_evidence_status"] == "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE"
    assert row["actual_observed_spread_entry_bps"] == 1.75
    assert row["expected_slippage_bps"] == 1.25
    assert row["fee_bps"] == 4.0
    assert row["expected_funding_bps"] == 1.2
    assert row["orderbook_depth_usd"] == 250000.0
    assert row["market_cost_evidence_source_fields"] == {
        "actual_observed_spread_entry_bps": "v2:features:latest:BTCUSDT:1m.bid_ask_spread_bps",
        "expected_slippage_bps": "prediction.expected_slippage_bps",
        "fee_bps": "prediction.fee_bps",
        "expected_funding_bps": "v2:features:latest:BTCUSDT:1m.funding_rate",
        "orderbook_depth_usd": "v2:features:latest:BTCUSDT:1m.orderbook_depth_usd",
    }
    assert row["source_lineage"]["market_cost_evidence"]["pit_guard_reject_reasons"] == []
    assert signal["feature_snapshot_id"] == prediction["feature_snapshot_id"]
    assert signal["available_at"] == row["available_at"]
    assert signal["decision_time"] == row["decision_time"]
    assert signal["feature_cutoff"] == row["feature_cutoff"]
    assert signal["confidence_calibrated"] == row["confidence_calibrated"]
    assert signal["expected_move_bps"] == row["expected_move_bps"]
    assert signal["expected_net_edge_bps"] == row["expected_move_after_cost_bps"]
    assert signal["source_prediction_key"] == row["prediction_redis_key"]
    assert signal["source_lineage"]["prediction_redis_key"] == row["prediction_redis_key"]
    assert signal["market_cost_evidence_status"] == row["market_cost_evidence_status"]
    assert signal["actual_observed_spread_entry_bps"] == row["actual_observed_spread_entry_bps"]
    assert signal["expected_slippage_bps"] == row["expected_slippage_bps"]
    assert signal["fee_bps"] == row["fee_bps"]
    assert signal["expected_funding_bps"] == row["expected_funding_bps"]
    assert signal["orderbook_depth_usd"] == row["orderbook_depth_usd"]


def test_prediction_row_converts_rate_and_estimated_alias_market_cost_evidence() -> None:
    decision_time = _utc_now_minus(30)
    feature_available_at = _utc_now_minus(45)
    prediction = _paper_ready_prediction_from_available_at("BTCUSDT", "1m", available_at=decision_time)
    feature_payload = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_snapshot_id": prediction["feature_snapshot_id"],
        "available_at": feature_available_at,
        "generated_at": feature_available_at,
        "feature_cutoff": feature_available_at,
        "features": {
            "bid_ask_spread_bps": 1.5,
            "estimated_slippage_bps": 1.75,
            "fee_rate": 0.0004,
            "expected_funding_rate": -0.000025,
            "depth_total_usd": 250000.0,
        },
    }

    row = svc.build_prediction_row(
        symbol="BTCUSDT",
        timeframe="1m",
        prediction=prediction,
        price_payload={"ticker_24hr": {"lastPrice": "100.0"}},
        feature_payload=feature_payload,
        stale_seconds=900,
    )
    signal = svc.build_signal_from_row(row)

    assert row["market_cost_evidence_status"] == "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE"
    assert row["actual_observed_spread_entry_bps"] == 1.5
    assert row["expected_slippage_bps"] == 1.75
    assert row["fee_bps"] == 4.0
    assert row["expected_funding_bps"] == 0.25
    assert row["orderbook_depth_usd"] == 250000.0
    assert row["market_cost_evidence_source_fields"] == {
        "actual_observed_spread_entry_bps": "v2:features:latest:BTCUSDT:1m.bid_ask_spread_bps",
        "expected_slippage_bps": "v2:features:latest:BTCUSDT:1m.estimated_slippage_bps",
        "fee_bps": "v2:features:latest:BTCUSDT:1m.fee_rate",
        "expected_funding_bps": "v2:features:latest:BTCUSDT:1m.expected_funding_rate",
        "orderbook_depth_usd": "v2:features:latest:BTCUSDT:1m.depth_total_usd",
    }
    assert signal["market_cost_evidence_status"] == row["market_cost_evidence_status"]
    assert signal["fee_bps"] == row["fee_bps"]
    assert signal["expected_funding_bps"] == row["expected_funding_bps"]


def test_prediction_row_does_not_fabricate_missing_fee_and_models_slippage_from_pit_spread() -> None:
    decision_time = _utc_now_minus(30)
    feature_available_at = _utc_now_minus(45)
    prediction = _paper_ready_prediction_from_available_at("ETHUSDT", "5m", available_at=decision_time)
    feature_payload = {
        "symbol": "ETHUSDT",
        "timeframe": "5m",
        "feature_snapshot_id": prediction["feature_snapshot_id"],
        "available_at": feature_available_at,
        "generated_at": feature_available_at,
        "feature_cutoff": feature_available_at,
        "features": {
            "bid_ask_spread_bps": 2.25,
            "funding_rate": 0.00008,
            "depth_total_usd": 125000.0,
        },
    }

    row = svc.build_prediction_row(
        symbol="ETHUSDT",
        timeframe="5m",
        prediction=prediction,
        price_payload={"ticker_24hr": {"lastPrice": "2500.0"}},
        feature_payload=feature_payload,
        stale_seconds=900,
    )
    signal = svc.build_signal_from_row(row)

    assert row["market_cost_evidence_status"] == "PARTIAL_EXPLICIT_MARKET_COST_EVIDENCE"
    assert row["actual_observed_spread_entry_bps"] == 2.25
    assert row["expected_slippage_bps"] == 1.125
    assert row["expected_funding_bps"] == 0.8
    assert row["orderbook_depth_usd"] == 125000.0
    assert "fee_bps" not in row
    assert row["market_cost_evidence_missing_fields"] == ["MISSING_FEES"]
    assert row["market_cost_evidence_source_fields"]["expected_slippage_bps"] == (
        "v2:features:latest:ETHUSDT:5m.MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY(bid_ask_spread_bps)"
    )
    assert signal["expected_slippage_bps"] == row["expected_slippage_bps"]
    assert "fee_bps" not in signal
    assert signal["market_cost_evidence_missing_fields"] == row["market_cost_evidence_missing_fields"]


def test_prediction_row_derives_side_specific_coinapi_book_depth() -> None:
    decision_time = _utc_now_minus(30)
    feature_available_at = _utc_now_minus(45)
    prediction = _paper_ready_prediction_from_available_at("BTCUSDT", "1m", available_at=decision_time, action="long")
    prediction["expected_slippage_bps"] = 0.9
    prediction["fee_bps"] = 4.0
    feature_payload = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_snapshot_id": prediction["feature_snapshot_id"],
        "available_at": feature_available_at,
        "generated_at": feature_available_at,
        "feature_cutoff": feature_available_at,
        "features": {
            "bid_ask_spread_bps": 1.5,
            "funding_rate": -0.0001,
            "coinapi_book_bid_sum_5": 50.0,
            "coinapi_best_bid_px": 99.0,
            "coinapi_book_ask_sum_5": 12.0,
            "coinapi_best_ask_px": 101.5,
        },
    }

    long_row = svc.build_prediction_row(
        symbol="BTCUSDT",
        timeframe="1m",
        prediction=prediction,
        price_payload={"ticker_24hr": {"lastPrice": "100.0"}},
        feature_payload=feature_payload,
        stale_seconds=900,
    )
    short_prediction = dict(prediction, selected_action="short", selected_action_index=2)
    short_row = svc.build_prediction_row(
        symbol="BTCUSDT",
        timeframe="1m",
        prediction=short_prediction,
        price_payload={"ticker_24hr": {"lastPrice": "100.0"}},
        feature_payload=feature_payload,
        stale_seconds=900,
    )
    hold_prediction = dict(prediction, selected_action="hold", selected_action_index=0)
    hold_evidence = svc.build_market_cost_evidence_enrichment(
        prediction=hold_prediction,
        feature_payload=feature_payload,
        feature_source_key=svc.feature_latest_key("BTCUSDT", "1m"),
    )

    assert long_row["market_cost_evidence_status"] == "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE"
    assert long_row["orderbook_depth_usd"] == 1218.0
    assert long_row["market_cost_evidence_source_fields"]["orderbook_depth_usd"] == (
        "v2:features:latest:BTCUSDT:1m.coinapi_book_ask_sum_5*coinapi_best_ask_px"
    )
    assert short_row["market_cost_evidence_status"] == "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE"
    assert short_row["orderbook_depth_usd"] == 4950.0
    assert short_row["market_cost_evidence_source_fields"]["orderbook_depth_usd"] == (
        "v2:features:latest:BTCUSDT:1m.coinapi_book_bid_sum_5*coinapi_best_bid_px"
    )
    assert "orderbook_depth_usd" not in hold_evidence
    assert "MISSING_MARKET_DEPTH" in hold_evidence["market_cost_evidence_missing_fields"]


def test_prediction_row_rejects_feature_cost_evidence_after_decision_time() -> None:
    decision_time = _utc_now_minus(60)
    feature_available_at = _utc_now_minus(30)
    prediction = _paper_ready_prediction_from_available_at("SOLUSDT", "15m", available_at=decision_time)
    feature_payload = {
        "symbol": "SOLUSDT",
        "timeframe": "15m",
        "feature_snapshot_id": prediction["feature_snapshot_id"],
        "available_at": feature_available_at,
        "generated_at": feature_available_at,
        "feature_cutoff": decision_time,
        "features": {
            "bid_ask_spread_bps": 1.1,
            "funding_rate": 0.0001,
            "orderbook_depth_usd": 500000.0,
        },
    }

    row = svc.build_prediction_row(
        symbol="SOLUSDT",
        timeframe="15m",
        prediction=prediction,
        price_payload={"ticker_24hr": {"lastPrice": "150.0"}},
        feature_payload=feature_payload,
        stale_seconds=900,
    )

    assert "actual_observed_spread_entry_bps" not in row
    assert "expected_funding_bps" not in row
    assert "orderbook_depth_usd" not in row
    assert row["market_cost_evidence_missing_fields"] == [
        "MISSING_ACTUAL_SPREAD",
        "MISSING_SLIPPAGE",
        "MISSING_FEES",
        "MISSING_FUNDING",
        "MISSING_MARKET_DEPTH",
    ]
    assert row["market_cost_evidence_pit_reject_reasons"] == [
        "FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME",
        "FEATURE_GENERATED_AT_AFTER_DECISION_TIME",
    ]


def test_prediction_row_accumulates_market_cost_pit_reject_reasons() -> None:
    decision_time = _utc_now_minus(60)
    feature_available_at = _utc_now_minus(30)
    prediction = _paper_ready_prediction_from_available_at("SOLUSDT", "15m", available_at=decision_time)
    feature_payload = {
        "symbol": "SOLUSDT",
        "timeframe": "15m",
        "feature_snapshot_id": "different-feature-snapshot",
        "available_at": feature_available_at,
        "generated_at": feature_available_at,
        "feature_cutoff": _utc_now_minus(120),
        "features": {
            "bid_ask_spread_bps": 3.0,
            "expected_slippage_bps": 1.2,
            "fee_bps": 4.0,
            "funding_rate": 0.00005,
            "orderbook_depth_usd": 50_000.0,
        },
    }

    evidence = svc.build_market_cost_evidence_enrichment(
        prediction=prediction,
        feature_payload=feature_payload,
        feature_source_key=svc.feature_latest_key("SOLUSDT", "15m"),
    )

    assert evidence["market_cost_evidence_status"] == "PARTIAL_EXPLICIT_MARKET_COST_EVIDENCE"
    assert evidence["market_cost_evidence_source_fields"] == {}
    assert evidence["market_cost_evidence_pit_reject_reasons"] == [
        "FEATURE_SNAPSHOT_MISMATCH_FOR_MARKET_COST_EVIDENCE",
        "FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME",
        "FEATURE_GENERATED_AT_AFTER_DECISION_TIME",
    ]


def test_prediction_rows_select_current_prediction_with_available_at_timestamp() -> None:
    client = _MemoryClient()
    store = V2KeyValueStore(client)
    available_at = _utc_now_minus(30)
    _seed_price(client, "BTCUSDT")
    client.set(
        svc.prediction_key("BTCUSDT", "1m"),
        json.dumps(_paper_ready_prediction_from_available_at("BTCUSDT", "1m", available_at=available_at)),
    )

    rows = svc.build_prediction_rows(store=store, symbols=["BTCUSDT"], stale_seconds=900)
    row = next(item for item in rows if item["symbol"] == "BTCUSDT" and item["timeframe"] == "1m")

    assert row["status"] == "PRESENT_CURRENT"
    assert row["paper_fill_allowed"] is True
    assert row["prediction_timestamp_source_field"] == "available_at"


def test_prediction_rows_prefer_exact_archived_feature_snapshot_for_market_cost() -> None:
    client = _MemoryClient()
    store = V2KeyValueStore(client)
    decision_time = _utc_now_minus(30)
    feature_available_at = _utc_now_minus(45)
    _seed_price(client, "BTCUSDT")
    prediction = _paper_ready_prediction_from_available_at("BTCUSDT", "1m", available_at=decision_time)
    prediction["expected_slippage_bps"] = 1.1
    prediction["fee_bps"] = 4.0
    client.set(svc.prediction_key("BTCUSDT", "1m"), json.dumps(prediction))
    client.set(
        svc.feature_latest_key("BTCUSDT", "1m"),
        json.dumps({
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "feature_snapshot_id": "newer-latest-feature-snapshot",
            "available_at": _utc_now_minus(10),
            "generated_at": _utc_now_minus(10),
            "feature_cutoff": feature_available_at,
            "features": {
                "bid_ask_spread_bps": 99.0,
                "funding_rate": 0.0005,
                "orderbook_depth_usd": 1.0,
            },
        }),
    )
    client.set(
        svc.feature_snapshot_key(prediction["feature_snapshot_id"]),
        json.dumps({
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "feature_snapshot_id": prediction["feature_snapshot_id"],
            "available_at": feature_available_at,
            "generated_at": feature_available_at,
            "feature_cutoff": feature_available_at,
            "features": {
                "bid_ask_spread_bps": 1.6,
                "funding_rate": -0.0001,
                "orderbook_depth_usd": 222000.0,
            },
        }),
    )

    rows = svc.build_prediction_rows(store=store, symbols=["BTCUSDT"], timeframes=("1m",), stale_seconds=900)
    row = rows[0]
    snapshot_key = svc.feature_snapshot_key(prediction["feature_snapshot_id"])

    assert row["market_cost_evidence_status"] == "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE"
    assert row["actual_observed_spread_entry_bps"] == 1.6
    assert row["expected_slippage_bps"] == 1.1
    assert row["fee_bps"] == 4.0
    assert row["expected_funding_bps"] == 1.0
    assert row["orderbook_depth_usd"] == 222000.0
    assert row["source_lineage"]["feature_redis_key"] == snapshot_key
    assert row["source_lineage"]["feature_lookup_status"] == "EXACT_ARCHIVED_FEATURE_SNAPSHOT"
    assert row["source_lineage"]["market_cost_evidence"]["feature_source_key"] == snapshot_key
    assert row["market_cost_evidence_source_fields"]["actual_observed_spread_entry_bps"] == (
        f"{snapshot_key}.bid_ask_spread_bps"
    )
    assert row["market_cost_evidence_source_fields"]["orderbook_depth_usd"] == f"{snapshot_key}.orderbook_depth_usd"


def test_runtime_paper_signal_rows_preserve_market_cost_and_pit_context() -> None:
    client = _MemoryClient()
    store = V2KeyValueStore(client)
    decision_time = _utc_now_minus(30)
    feature_cutoff = _utc_now_minus(45)
    _seed_price(client, "BTCUSDT", 100.0)
    client.set(
        "v2:signals:paper",
        json.dumps(
            [
                {
                    "symbol": "BTCUSDT",
                    "timeframe": "5m",
                    "source_prediction_id": "pred_BTCUSDT_5m",
                    "side": "long",
                    "confidence_calibrated": 0.81,
                    "expected_move_bps": 24.0,
                    "expected_move_after_cost_bps": 18.0,
                    "paper_fill_allowed": True,
                    "feature_snapshot_id": "fs_BTCUSDT_5m",
                    "available_at": decision_time,
                    "decision_time": decision_time,
                    "feature_cutoff": feature_cutoff,
                    "entry_observed_spread_bps": 1.9,
                    "expected_slippage_bps": 1.2,
                    "fee_bps": 4.0,
                    "expected_funding_bps": 0.5,
                    "orderbook_depth_usd": 1_000_000.0,
                    "market_cost_evidence_pit_reject_reasons": [],
                    "market_state_id": "mstate_BTCUSDT_1m",
                    "market_state_integrity_score": 98.0,
                    "valid_for_prediction": True,
                    "valid_for_risk": True,
                    "valid_for_orchestrator": True,
                    "valid_for_paper": True,
                    "valid_for_live": False,
                }
            ]
        ),
    )
    client.set(
        "v2:risk:gateway:decisions",
        json.dumps(
            [
                {
                    "prediction_id": "pred_BTCUSDT_5m",
                    "risk_decision_id": "risk_1",
                    "orchestrator_decision_id": "orch_1",
                    "live_blocked": True,
                }
            ]
        ),
    )
    client.set(
        "v2:paper:intents",
        json.dumps(
            [
                {
                    "intent_id": "intent_1",
                    "symbol": "BTCUSDT",
                    "source_prediction_id": "pred_BTCUSDT_5m",
                    "paper_fill_allowed": True,
                }
            ]
        ),
    )
    client.set(
        "v2:paper:ledger",
        json.dumps(
            {
                "accepted": [
                    {
                        "symbol": "BTCUSDT",
                        "source_prediction_id": "pred_BTCUSDT_5m",
                        "paper_ledger_id": "ledger_1",
                    }
                ],
                "shadow_observations": [],
            }
        ),
    )

    rows = svc.build_runtime_paper_signal_rows(store)
    row = rows[0]

    assert row["source_prediction_status"] == "CURRENT_RUNTIME_PAPER_SIGNAL"
    assert row["prediction_id"] == "pred_BTCUSDT_5m"
    assert row["timeframe"] == "5m"
    assert row["feature_snapshot_id"] == "fs_BTCUSDT_5m"
    assert row["lineage_ids"]["feature_snapshot_id"] == "fs_BTCUSDT_5m"
    assert row["available_at"] == decision_time
    assert row["decision_time"] == decision_time
    assert row["feature_cutoff"] == feature_cutoff
    assert row["confidence_calibrated"] == 0.81
    assert row["expected_move_bps"] == 24.0
    assert row["expected_move_after_cost_bps"] == 18.0
    assert row["expected_net_edge_bps"] == 18.0
    assert row["source_lineage"]["paper_signal_redis_key"] == "v2:signals:paper"
    assert row["source_lineage"]["expected_move_after_cost_bps_source_field"] == (
        "paper_signal.expected_move_after_cost_bps"
    )
    assert row["runtime_paper_pit_context_source_fields"]["feature_snapshot_id"] == "paper_signal.feature_snapshot_id"
    assert row["market_cost_evidence_status"] == "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE"
    assert row["actual_observed_spread_entry_bps"] == 1.9
    assert row["expected_slippage_bps"] == 1.2
    assert row["fee_bps"] == 4.0
    assert row["expected_funding_bps"] == 0.5
    assert row["orderbook_depth_usd"] == 1_000_000.0
    assert row["market_cost_evidence_missing_fields"] == []
    assert row["market_cost_evidence_pit_reject_reasons"] == []
    assert row["market_cost_evidence_source_fields"]["actual_observed_spread_entry_bps"] == (
        "paper_signal.entry_observed_spread_bps"
    )


def test_current_hold_prediction_is_not_paper_actionable() -> None:
    available_at = _utc_now_minus(30)
    prediction = _paper_ready_prediction_from_available_at(
        "BTCUSDT",
        "1m",
        available_at=available_at,
        action="hold",
    )
    prediction["expected_move_bps"] = -42.0
    prediction["expected_move_after_cost_bps"] = 0.0
    prediction.update(
        {
            "action_probability_by_label": {"hold": 0.250001, "long": 0.05, "short": 0.25},
            "opening_policy_argmax_action": "hold",
            "opening_policy_argmax_probability": 0.250001,
            "selected_action_probability": 0.250001,
            "counterfactual_directional_action_from_expected_move": "short",
            "counterfactual_directional_expected_move_after_cost_bps": -30.0,
            "counterfactual_directional_action_probability": 0.25,
            "selected_vs_counterfactual_directional_action_probability_gap": 0.000001,
            "selected_hold_with_directional_edge_after_cost": True,
            "selected_hold_directional_edge_diagnostic_reason": (
                "EXPECTED_MOVE_DIRECTIONAL_EDGE_BLOCKED_BY_SELECTED_HOLD"
            ),
        }
    )

    row = svc.build_prediction_row(
        symbol="BTCUSDT",
        timeframe="1m",
        prediction=prediction,
        price_payload={"ticker_24hr": {"lastPrice": "100.0"}},
        feature_payload=None,
        stale_seconds=900,
    )

    assert row["status"] == "PRESENT_CURRENT"
    assert row["paper_fill_allowed"] is False
    assert row["routes_to_orchestrator"] is False
    assert "NON_ACTIONABLE_EXPECTED_MOVE_OR_ACTION" in row["paper_fill_gate_block_reasons"]
    assert row["selected_action_expected_move_bps_sign"] == "negative"
    assert row["hold_action_with_directional_expected_move_bps"] is True
    assert row["hold_action_directional_expected_move_bps"] == -42.0
    assert row["expected_move_after_cost_zeroed_by_hold_action"] is True
    assert (
        row["paper_non_actionable_diagnostic_reason"]
        == "HOLD_ACTION_WITH_DIRECTIONAL_EXPECTED_MOVE_ZERO_AFTER_COST_EDGE"
    )
    assert row["opening_policy_argmax_action"] == "hold"
    assert row["counterfactual_directional_action_from_expected_move"] == "short"
    assert row["counterfactual_directional_expected_move_after_cost_bps"] == -30.0
    assert row["selected_hold_with_directional_edge_after_cost"] is True
    assert (
        row["selected_hold_directional_edge_diagnostic_reason"]
        == "EXPECTED_MOVE_DIRECTIONAL_EDGE_BLOCKED_BY_SELECTED_HOLD"
    )

    signal = svc.build_signal_from_row(row)
    assert signal["selected_action_expected_move_bps_sign"] == "negative"
    assert signal["hold_action_with_directional_expected_move_bps"] is True
    assert signal["hold_action_directional_expected_move_bps"] == -42.0
    assert signal["expected_move_after_cost_zeroed_by_hold_action"] is True
    assert (
        signal["paper_non_actionable_diagnostic_reason"]
        == "HOLD_ACTION_WITH_DIRECTIONAL_EXPECTED_MOVE_ZERO_AFTER_COST_EDGE"
    )
    assert signal["opening_policy_argmax_action"] == "hold"
    assert signal["counterfactual_directional_action_from_expected_move"] == "short"
    assert signal["counterfactual_directional_expected_move_after_cost_bps"] == -30.0
    assert signal["selected_hold_with_directional_edge_after_cost"] is True
    assert (
        signal["selected_hold_directional_edge_diagnostic_reason"]
        == "EXPECTED_MOVE_DIRECTIONAL_EDGE_BLOCKED_BY_SELECTED_HOLD"
    )


def test_stale_allowed_long_prediction_is_not_paper_actionable() -> None:
    stale_available_at = _utc_now_minus(901)
    prediction = _paper_ready_prediction_from_available_at("EIGENUSDT", "1h", available_at=stale_available_at)

    row = svc.build_prediction_row(
        symbol="EIGENUSDT",
        timeframe="1h",
        prediction=prediction,
        price_payload={"ticker_24hr": {"lastPrice": "1.5"}},
        feature_payload=None,
        stale_seconds=900,
    )

    assert row["selected_action"] == "long"
    assert row["status"] == "STALE_TF_PREDICTION"
    assert row["paper_fill_allowed"] is False
    assert row["routes_to_orchestrator"] is False
    assert row["prediction_timestamp_source_field"] == "available_at"
    assert "STALE_GT_900s" in row["paper_fill_gate_block_reasons"]


def test_prediction_available_after_decision_time_is_not_paper_actionable() -> None:
    decision_time = _utc_now_minus(60)
    available_at = _utc_now_minus(30)
    prediction = _paper_ready_prediction_from_available_at(
        "EVAAUSDT",
        "1h",
        available_at=available_at,
        decision_time=decision_time,
    )

    row = svc.build_prediction_row(
        symbol="EVAAUSDT",
        timeframe="1h",
        prediction=prediction,
        price_payload={"ticker_24hr": {"lastPrice": "2.5"}},
        feature_payload=None,
        stale_seconds=900,
    )

    assert row["status"] == "PREDICTION_TEMPORAL_ORDER_INVALID"
    assert row["paper_fill_allowed"] is False
    assert row["routes_to_orchestrator"] is False
    assert row["prediction_temporal_block_reasons"] == ["PREDICTION_AVAILABLE_AT_AFTER_DECISION_TIME"]
    assert "PREDICTION_AVAILABLE_AT_AFTER_DECISION_TIME" in row["paper_fill_gate_block_reasons"]


def test_paper_directional_collapse_guard_blocks_large_current_one_sided_batch() -> None:
    rows = [
        {
            "prediction_id": f"pred_SOLUSDT_{index}",
            "symbol": "SOLUSDT",
            "timeframe": "1m",
            "status": "PRESENT_CURRENT",
            "selected_action": "short",
            "paper_fill_allowed": True,
            "routes_to_orchestrator": True,
            "source_lineage": {},
        }
        for index in range(60)
    ]

    guarded_rows, status = svc.apply_paper_directional_collapse_guard(rows)

    assert status["directional_collapse_detected"] is True
    assert status["majority_side"] == "short"
    assert status["side_counts"] == {"long": 0, "short": 60}
    assert status["blocked_paper_actionability_count"] == 60
    assert all(row["paper_fill_allowed"] is False for row in guarded_rows)
    assert all(row["routes_to_orchestrator"] is False for row in guarded_rows)
    assert all(
        svc.PAPER_DIRECTIONAL_COLLAPSE_BLOCK_REASON in row["paper_fill_gate_block_reasons"]
        for row in guarded_rows
    )
    assert guarded_rows[0]["source_lineage"]["paper_directional_collapse_guard"][
        "blocked_paper_actionability_count"
    ] == 60


def test_paper_directional_collapse_guard_does_not_block_small_fixture() -> None:
    rows = [
        {
            "prediction_id": f"pred_ETHUSDT_{index}",
            "symbol": "ETHUSDT",
            "timeframe": "1m",
            "status": "PRESENT_CURRENT",
            "selected_action": "long",
            "paper_fill_allowed": True,
            "routes_to_orchestrator": True,
        }
        for index in range(5)
    ]

    guarded_rows, status = svc.apply_paper_directional_collapse_guard(rows)

    assert status["directional_collapse_detected"] is False
    assert status["blocked_paper_actionability_count"] == 0
    assert all(row["paper_fill_allowed"] is True for row in guarded_rows)
    assert all(row["routes_to_orchestrator"] is True for row in guarded_rows)


def test_closed_trade_directional_collapse_guard_blocks_majority_side_only() -> None:
    client = _MemoryClient()
    store = V2KeyValueStore(client)
    client.set(
        "v2:paper:closed_trades",
        json.dumps(
            [
                {
                    "close_id": f"close_short_{index}",
                    "symbol": "BTCUSDT",
                    "timeframe": "1m",
                    "side": "short",
                }
                for index in range(60)
            ]
        ),
    )
    rows = [
        {
            "prediction_id": "pred_short",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "status": "PRESENT_CURRENT",
            "selected_action": "short",
            "paper_fill_allowed": True,
            "routes_to_orchestrator": True,
            "source_lineage": {},
        },
        {
            "prediction_id": "pred_long",
            "symbol": "ETHUSDT",
            "timeframe": "1m",
            "status": "PRESENT_CURRENT",
            "selected_action": "long",
            "paper_fill_allowed": True,
            "routes_to_orchestrator": True,
            "source_lineage": {},
        },
    ]

    guarded_rows, status = svc.apply_paper_closed_trade_directional_collapse_guard(rows, store=store)

    assert status["directional_collapse_detected"] is True
    assert status["majority_side"] == "short"
    assert status["side_counts"] == {"long": 0, "short": 60}
    assert status["blocked_paper_actionability_count"] == 1
    assert guarded_rows[0]["paper_fill_allowed"] is False
    assert guarded_rows[0]["routes_to_orchestrator"] is False
    assert svc.PAPER_DIRECTIONAL_COLLAPSE_BLOCK_REASON in guarded_rows[0]["paper_fill_gate_block_reasons"]
    assert guarded_rows[1]["paper_fill_allowed"] is True
    assert guarded_rows[1]["routes_to_orchestrator"] is True


def test_extract_symbols_prefers_training_scope_over_paper_subset() -> None:
    symbols = svc.extract_symbols(
        [
            {
                "paper_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
                "training_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"],
            }
        ],
        fallback=["DOGEUSDT"],
    )

    assert symbols == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]


def test_partial_runtime_truth_writes_blockers_and_signals(tmp_path: Path, monkeypatch) -> None:
    _ok_production(monkeypatch)
    paths = default_paths(tmp_path)
    _write_symbol_scope(paths, ["BTCUSDT", "ETHUSDT"])
    client = _MemoryClient()
    store = V2KeyValueStore(client)
    monkeypatch.setattr(
        svc,
        "trainer_trust_rejects_all_timeframes",
        lambda **kwargs: {
            "symbol": kwargs.get("symbol"),
            "exclude_from_expected_grid": False,
            "status": "TRUST_CHECK_INCONCLUSIVE_TEST_FIXTURE",
        },
    )
    _seed_price(client, "BTCUSDT", 100.0)
    client.set("v2:prediction:BTCUSDT:1m", json.dumps(_prediction("BTCUSDT", "1m", expected=25.0, after=20.0)))
    client.set(
        "v2:prediction:BTCUSDT:5m",
        json.dumps(_prediction("BTCUSDT", "5m", generated="2026-01-01T00:00:00-05:00", expected=30.0, after=18.0)),
    )

    result = build_packet(paths=paths, store=store, stale_seconds=60, production_base_url="https://example.test", routes=["/signals"])

    prediction_status = result.payloads["all_timeframe_prediction_publisher_status.json"]
    price_status = result.payloads["price_target_all_tf_status.json"]
    dynamic_status = result.payloads["dynamic_symbol_full_pipeline_contract_status.json"]
    feature_matrix = result.payloads["unified_feature_field_coverage_matrix.json"]
    assert result.go_no_go == GATE_BLOCKED
    assert prediction_status["prediction_rows_count"] == 10
    assert prediction_status["current_prediction_count"] == 1
    assert prediction_status["stale_prediction_count"] == 1
    assert prediction_status["missing_prediction_count"] == 8
    btc_1m = next(row for row in price_status["target_rows"] if row["symbol"] == "BTCUSDT" and row["timeframe"] == "1m")
    assert btc_1m["price_target"] == 100.25
    assert client.get("v2:prediction:BTCUSDT:15m") is None
    assert json.loads(client.get("v2:signals:paper:BTCUSDT:1m"))["prediction_id"] == "pred_BTCUSDT_1m"
    assert json.loads(client.get("v2:signals:latest:BTCUSDT"))["prediction_id"] == "pred_BTCUSDT_1m"
    assert dynamic_status["dynamic_symbol_count"] == 2
    assert feature_matrix["field_rows_count"] == 2 * len(REQUIRED_TIMEFRAMES) * len(svc.REQUIRED_FEATURE_FIELDS)
    assert store.audit.old_redis_write_attempts == 0

    second_result = build_packet(paths=paths, store=store, stale_seconds=60, production_base_url="https://example.test", routes=["/signals"])
    second_prediction_status = second_result.payloads["all_timeframe_prediction_publisher_status.json"]
    assert second_prediction_status["current_prediction_count"] == 1
    assert second_prediction_status["stale_prediction_count"] == 1
    assert second_prediction_status["missing_prediction_count"] == 8


def test_publisher_retires_stale_routeable_primary_prediction_keys(tmp_path: Path, monkeypatch) -> None:
    _ok_production(monkeypatch)
    paths = default_paths(tmp_path)
    _write_symbol_scope(paths, ["BTCUSDT"])
    client = _MemoryClient()
    store = V2KeyValueStore(client)
    _seed_price(client, "BTCUSDT", 100.0)
    current = _paper_ready_prediction_from_available_at(
        "BTCUSDT",
        "1m",
        available_at=_utc_now_minus(30),
    )
    stale = _paper_ready_prediction_from_available_at(
        "STALEUSDT",
        "1m",
        available_at=_utc_now_minus(3_600),
    )
    client.set("v2:prediction:BTCUSDT:1m", json.dumps(current))
    client.set("v2:prediction:STALEUSDT:1m", json.dumps(stale))

    result = build_packet(
        paths=paths,
        store=store,
        stale_seconds=60,
        production_base_url="https://example.test",
        routes=["/signals"],
    )

    stale_after = json.loads(client.get("v2:prediction:STALEUSDT:1m"))
    current_after = json.loads(client.get("v2:prediction:BTCUSDT:1m"))
    dashboard = result.payloads["operator_dashboard_payload.json"]
    assert stale_after["routes_to_orchestrator"] is False
    assert stale_after["paper_fill_allowed"] is False
    assert stale_after["stale_prediction_retired_by_publisher"] is True
    assert "STALE_PREDICTION_RETIRED_BY_PUBLISHER" in stale_after["paper_fill_gate_block_reasons"]
    assert current_after["routes_to_orchestrator"] is True
    assert current_after["paper_fill_allowed"] is True
    assert "stale_prediction_retired_by_publisher" not in current_after
    assert dashboard["redis_publish_audit"]["retired_stale_prediction_key_writes"] == 1


def test_all_tf_missing_symbol_with_explicit_trainer_trust_rejection_is_removed_from_expected_grid(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _ok_production(monkeypatch)
    paths = default_paths(tmp_path)
    _write_symbol_scope(paths, ["BTCUSDT", "AEROUSDT"])
    client = _MemoryClient()
    store = V2KeyValueStore(client)
    _seed_price(client, "BTCUSDT", 100.0)
    for timeframe in REQUIRED_TIMEFRAMES:
        client.set(f"v2:prediction:BTCUSDT:{timeframe}", json.dumps(_prediction("BTCUSDT", timeframe)))

    def _trust_rejects(*, store: V2KeyValueStore, symbol: str, timeframes: tuple[str, ...] = REQUIRED_TIMEFRAMES) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "exclude_from_expected_grid": symbol == "AEROUSDT",
            "status": "TRAINER_TRUST_REJECTED_ALL_TIMEFRAMES" if symbol == "AEROUSDT" else "TRAINER_TRUST_CONSUMABLE",
            "timeframes": list(timeframes),
            "reasons_by_timeframe": {timeframe: ["UNCLOSED_CANDLE"] for timeframe in timeframes}
            if symbol == "AEROUSDT"
            else {},
        }

    monkeypatch.setattr(svc, "trainer_trust_rejects_all_timeframes", _trust_rejects)

    result = build_packet(paths=paths, store=store, stale_seconds=3600, production_base_url="https://example.test", routes=["/signals"])

    prediction_status = result.payloads["all_timeframe_prediction_publisher_status.json"]
    cuda_prediction_status = result.payloads["all_symbol_all_timeframe_cuda_prediction_status.json"]
    assert prediction_status["prediction_rows_count"] == len(REQUIRED_TIMEFRAMES)
    assert prediction_status["missing_prediction_count"] == 0
    assert prediction_status["current_prediction_count"] == len(REQUIRED_TIMEFRAMES)
    assert prediction_status["symbols_covered"] == ["BTCUSDT"]
    assert prediction_status["previous_symbol_count"] == 2
    assert prediction_status["current_symbol_count"] == 1
    assert prediction_status["removed_symbols"] == ["AEROUSDT"]
    assert prediction_status["symbol_scope_reconciliation_status"] == "SYMBOL_SCOPE_VALID_DYNAMIC_RUNTIME_UNIVERSE"
    assert cuda_prediction_status["previous_symbol_count"] == 2
    assert cuda_prediction_status["current_symbol_count"] == 1
    assert cuda_prediction_status["removed_symbols"] == ["AEROUSDT"]
    assert cuda_prediction_status["removal_reason_by_symbol"]["AEROUSDT"]["status"] == "TRAINER_TRUST_REJECTED_ALL_TIMEFRAMES"
    assert cuda_prediction_status["symbol_scope_reconciliation_status"] == "SYMBOL_SCOPE_VALID_DYNAMIC_RUNTIME_UNIVERSE"


def test_all_tf_runtime_trust_reconciliation_limit_skips_expensive_scope_check(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _ok_production(monkeypatch)
    paths = default_paths(tmp_path)
    _write_symbol_scope(paths, ["BTCUSDT", "AEROUSDT"])
    client = _MemoryClient()
    store = V2KeyValueStore(client)
    _seed_price(client, "BTCUSDT", 100.0)
    for timeframe in REQUIRED_TIMEFRAMES:
        client.set(f"v2:prediction:BTCUSDT:{timeframe}", json.dumps(_prediction("BTCUSDT", timeframe)))

    def _trust_rejects(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("trainer trust scope check should be skipped by the runtime limit")

    monkeypatch.setattr(svc, "trainer_trust_rejects_all_timeframes", _trust_rejects)

    result = build_packet(
        paths=paths,
        store=store,
        stale_seconds=3600,
        production_base_url="https://example.test",
        routes=["/signals"],
        trainer_trust_reconciliation_limit=0,
    )

    prediction_status = result.payloads["all_timeframe_prediction_publisher_status.json"]
    cuda_prediction_status = result.payloads["all_symbol_all_timeframe_cuda_prediction_status.json"]
    assert prediction_status["prediction_rows_count"] == 2 * len(REQUIRED_TIMEFRAMES)
    assert prediction_status["symbols_covered"] == ["AEROUSDT", "BTCUSDT"]
    assert prediction_status["previous_symbol_count"] == 2
    assert prediction_status["current_symbol_count"] == 2
    assert prediction_status["removed_symbols"] == []
    assert prediction_status["trainer_trust_checks_attempted"] == 0
    assert prediction_status["trainer_trust_checks_skipped_count"] == 1
    assert prediction_status["trainer_trust_reconciliation_skipped_symbols"] == ["AEROUSDT"]
    assert (
        prediction_status["symbol_scope_reconciliation_status"]
        == "SYMBOL_SCOPE_VALID_DYNAMIC_RUNTIME_UNIVERSE_PARTIAL_TRUST_CHECK_LIMIT"
    )
    assert cuda_prediction_status["trainer_trust_checks_attempted"] == 0
    assert cuda_prediction_status["trainer_trust_checks_skipped_count"] == 1


def test_build_packet_can_use_prediction_rows_for_runtime_feature_parity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _ok_production(monkeypatch)
    paths = default_paths(tmp_path)
    _write_symbol_scope(paths, ["BTCUSDT"])
    client = _MemoryClient()
    store = V2KeyValueStore(client)
    _seed_price(client, "BTCUSDT", 100.0)
    for timeframe in REQUIRED_TIMEFRAMES:
        client.set(f"v2:prediction:BTCUSDT:{timeframe}", json.dumps(_prediction("BTCUSDT", timeframe)))

    class _FailingLoader:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError("runtime feature parity should use prediction-row summaries")

    monkeypatch.setattr(svc, "V2HybridTrainerDataLoader", _FailingLoader)

    result = build_packet(
        paths=paths,
        store=store,
        stale_seconds=3600,
        production_base_url="https://example.test",
        routes=["/signals"],
        feature_parity_from_prediction_rows=True,
    )

    feature_parity = result.payloads["unified_feature_parity_all_symbols_status.json"]
    feature_matrix = result.payloads["unified_feature_field_coverage_matrix.json"]
    assert feature_parity["feature_parity_evidence_source"] == "prediction_rows_feature_summary"
    assert feature_matrix["feature_parity_evidence_source"] == "prediction_rows_feature_summary"
    assert feature_parity["tensor_rows_count"] == len(REQUIRED_TIMEFRAMES)
    assert feature_matrix["field_rows_count"] == len(REQUIRED_TIMEFRAMES) * len(svc.REQUIRED_FEATURE_FIELDS)


def test_all_tf_stale_symbol_with_explicit_trainer_trust_rejection_is_removed_from_expected_grid(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _ok_production(monkeypatch)
    paths = default_paths(tmp_path)
    _write_symbol_scope(paths, ["BTCUSDT", "EVAAUSDT"])
    client = _MemoryClient()
    store = V2KeyValueStore(client)
    _seed_price(client, "BTCUSDT", 100.0)
    _seed_price(client, "EVAAUSDT", 1.0)
    stale_generated = "2026-01-01T00:00:00Z"
    for timeframe in REQUIRED_TIMEFRAMES:
        client.set(f"v2:prediction:BTCUSDT:{timeframe}", json.dumps(_prediction("BTCUSDT", timeframe)))
        stale_prediction = _prediction("EVAAUSDT", timeframe)
        stale_prediction["generated_utc"] = stale_generated
        stale_prediction["generated_at"] = stale_generated
        client.set(f"v2:prediction:EVAAUSDT:{timeframe}", json.dumps(stale_prediction))

    def _trust_rejects(*, store: V2KeyValueStore, symbol: str, timeframes: tuple[str, ...] = REQUIRED_TIMEFRAMES) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "exclude_from_expected_grid": symbol == "EVAAUSDT",
            "status": "TRAINER_TRUST_REJECTED_ALL_TIMEFRAMES" if symbol == "EVAAUSDT" else "TRAINER_TRUST_CONSUMABLE",
            "timeframes": list(timeframes),
            "reasons_by_timeframe": {timeframe: ["UNCLOSED_CANDLE"] for timeframe in timeframes}
            if symbol == "EVAAUSDT"
            else {},
        }

    monkeypatch.setattr(svc, "trainer_trust_rejects_all_timeframes", _trust_rejects)

    result = build_packet(paths=paths, store=store, stale_seconds=60, production_base_url="https://example.test", routes=["/signals"])

    prediction_status = result.payloads["all_timeframe_prediction_publisher_status.json"]
    assert prediction_status["prediction_rows_count"] == len(REQUIRED_TIMEFRAMES)
    assert prediction_status["stale_prediction_count"] == 0
    assert prediction_status["current_prediction_count"] == len(REQUIRED_TIMEFRAMES)
    assert prediction_status["symbols_covered"] == ["BTCUSDT"]
    assert prediction_status["previous_symbol_count"] == 2
    assert prediction_status["current_symbol_count"] == 1
    assert prediction_status["removed_symbols"] == ["EVAAUSDT"]
    assert prediction_status["symbol_scope_reconciliation_status"] == "SYMBOL_SCOPE_VALID_DYNAMIC_RUNTIME_UNIVERSE"


def test_prediction_grid_marks_stale_symbol_reason(tmp_path: Path, monkeypatch) -> None:
    _ok_production(monkeypatch)
    paths = default_paths(tmp_path)
    _write_symbol_scope(paths, ["BTCUSDT"])
    client = _MemoryClient()
    store = V2KeyValueStore(client)
    _seed_price(client, "BTCUSDT", 100.0)
    stale_prediction = _prediction("BTCUSDT", "1m", generated="2026-01-01T00:00:00Z")
    client.set("v2:prediction:BTCUSDT:1m", json.dumps(stale_prediction))
    monkeypatch.setattr(
        svc,
        "trainer_trust_rejects_all_timeframes",
        lambda **kwargs: {
            "symbol": kwargs.get("symbol"),
            "exclude_from_expected_grid": False,
            "status": "TRAINER_TRUST_CONSUMABLE",
        },
    )

    result = build_packet(paths=paths, store=store, stale_seconds=60, production_base_url="https://example.test", routes=["/signals"])

    prediction_status = result.payloads["all_timeframe_prediction_publisher_status.json"]
    assert prediction_status["stale_prediction_count"] == 1
    assert prediction_status["stale_prediction_symbols"] == ["BTCUSDT"]
    assert prediction_status["stale_prediction_timeframes_by_symbol"] == {"BTCUSDT": ["1m"]}


def test_all_timeframe_publisher_refreshes_valid_symbols(tmp_path: Path, monkeypatch) -> None:
    _ok_production(monkeypatch)
    paths = default_paths(tmp_path)
    _write_symbol_scope(paths, ["BTCUSDT"])
    client = _MemoryClient()
    store = V2KeyValueStore(client)
    _seed_price(client, "BTCUSDT", 100.0)
    for timeframe in REQUIRED_TIMEFRAMES:
        client.set(f"v2:prediction:BTCUSDT:{timeframe}", json.dumps(_prediction("BTCUSDT", timeframe)))
    monkeypatch.setattr(
        svc,
        "trainer_trust_rejects_all_timeframes",
        lambda **kwargs: {
            "symbol": kwargs.get("symbol"),
            "exclude_from_expected_grid": False,
            "status": "TRAINER_TRUST_CONSUMABLE",
        },
    )

    result = build_packet(paths=paths, store=store, stale_seconds=3600, production_base_url="https://example.test", routes=["/signals"])

    prediction_status = result.payloads["all_timeframe_prediction_publisher_status.json"]
    assert prediction_status["current_prediction_count"] == len(REQUIRED_TIMEFRAMES)
    assert prediction_status["stale_prediction_count"] == 0
    assert prediction_status["symbols_covered"] == ["BTCUSDT"]


def test_build_packet_blocks_paper_actionability_for_current_directional_collapse(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _ok_production(monkeypatch)
    paths = default_paths(tmp_path)
    symbols = [
        "ADAUSDT",
        "AVAXUSDT",
        "BNBUSDT",
        "BTCUSDT",
        "DOGEUSDT",
        "DOTUSDT",
        "ETHUSDT",
        "LINKUSDT",
        "LTCUSDT",
        "SOLUSDT",
        "TRXUSDT",
        "XRPUSDT",
    ]
    _write_symbol_scope(paths, symbols)
    client = _MemoryClient()
    store = V2KeyValueStore(client)
    monkeypatch.setattr(
        svc,
        "trainer_trust_rejects_all_timeframes",
        lambda **kwargs: {
            "symbol": kwargs.get("symbol"),
            "exclude_from_expected_grid": False,
            "status": "TRAINER_TRUST_CONSUMABLE",
        },
    )
    available_at = _utc_now_minus(30)
    for symbol in symbols:
        _seed_price(client, symbol, 100.0)
        for timeframe in REQUIRED_TIMEFRAMES:
            _seed_feature_snapshot(client, symbol, timeframe)
            prediction = _paper_ready_prediction_from_available_at(
                symbol,
                timeframe,
                available_at=available_at,
                action="short",
            )
            prediction.update(
                {
                    "expected_move_bps": -25.0,
                    "expected_move_after_cost_bps": -13.0,
                    "policy_action_probabilities": [0.05, 0.05, 0.90],
                }
            )
            client.set(f"v2:prediction:{symbol}:{timeframe}", json.dumps(prediction))

    result = build_packet(
        paths=paths,
        store=store,
        stale_seconds=900,
        production_base_url="https://example.test",
        routes=["/signals"],
        write_redis=False,
    )

    prediction_status = result.payloads["all_timeframe_prediction_publisher_status.json"]
    cuda_prediction_status = result.payloads["all_symbol_all_timeframe_cuda_prediction_status.json"]
    signal_status = result.payloads["all_timeframe_signal_publisher_status.json"]
    guard = prediction_status["paper_directional_collapse_guard_status"]
    row_count = len(symbols) * len(REQUIRED_TIMEFRAMES)

    assert prediction_status["current_prediction_count"] == row_count
    assert guard["directional_collapse_detected"] is True
    assert guard["majority_side"] == "short"
    assert guard["side_counts"] == {"long": 0, "short": row_count}
    assert guard["blocked_paper_actionability_count"] == row_count
    assert cuda_prediction_status["paper_actionability_allowed_rows_count"] == 0
    assert cuda_prediction_status["paper_actionability_blocked_rows_count"] == row_count
    assert cuda_prediction_status["paper_actionability_block_reason_counts"] == {
        svc.PAPER_DIRECTIONAL_COLLAPSE_BLOCK_REASON: row_count
    }
    assert cuda_prediction_status["actionability_status"] == "PAPER_ACTIONABILITY_BLOCKED_BY_GATES"
    assert all(row["status"] == "PRESENT_CURRENT" for row in prediction_status["prediction_rows"])
    assert all(row["paper_fill_allowed"] is False for row in prediction_status["prediction_rows"])
    assert all(signal["paper_fill_allowed"] is False for signal in signal_status["published_signals"])


def test_build_packet_blocks_small_current_short_batch_when_closed_corpus_is_short_collapsed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _ok_production(monkeypatch)
    paths = default_paths(tmp_path)
    _write_symbol_scope(paths, ["BTCUSDT"])
    client = _MemoryClient()
    store = V2KeyValueStore(client)
    _seed_price(client, "BTCUSDT", 100.0)
    client.set(
        "v2:paper:closed_trades",
        json.dumps(
            [
                {
                    "close_id": f"close_short_{index}",
                    "symbol": "BTCUSDT",
                    "timeframe": "1m",
                    "side": "short",
                }
                for index in range(60)
            ]
        ),
    )
    monkeypatch.setattr(
        svc,
        "trainer_trust_rejects_all_timeframes",
        lambda **kwargs: {
            "symbol": kwargs.get("symbol"),
            "exclude_from_expected_grid": False,
            "status": "TRAINER_TRUST_CONSUMABLE",
        },
    )
    available_at = _utc_now_minus(30)
    for timeframe in REQUIRED_TIMEFRAMES:
        _seed_feature_snapshot(client, "BTCUSDT", timeframe)
        prediction = _paper_ready_prediction_from_available_at(
            "BTCUSDT",
            timeframe,
            available_at=available_at,
            action="short",
        )
        prediction.update(
            {
                "expected_move_bps": -25.0,
                "expected_move_after_cost_bps": -13.0,
                "policy_action_probabilities": [0.05, 0.05, 0.90],
            }
        )
        client.set(f"v2:prediction:BTCUSDT:{timeframe}", json.dumps(prediction))

    result = build_packet(
        paths=paths,
        store=store,
        stale_seconds=900,
        production_base_url="https://example.test",
        routes=["/signals"],
        write_redis=False,
    )

    prediction_status = result.payloads["all_timeframe_prediction_publisher_status.json"]
    cuda_prediction_status = result.payloads["all_symbol_all_timeframe_cuda_prediction_status.json"]
    signal_status = result.payloads["all_timeframe_signal_publisher_status.json"]
    current_guard = prediction_status["paper_directional_collapse_guard_status"]
    closed_guard = prediction_status["paper_closed_trade_directional_collapse_guard_status"]

    assert current_guard["directional_collapse_detected"] is False
    assert current_guard["current_directional_count"] == len(REQUIRED_TIMEFRAMES)
    assert closed_guard["directional_collapse_detected"] is True
    assert closed_guard["majority_side"] == "short"
    assert closed_guard["blocked_paper_actionability_count"] == len(REQUIRED_TIMEFRAMES)
    assert cuda_prediction_status["paper_closed_trade_directional_collapse_guard_status"][
        "blocked_paper_actionability_count"
    ] == len(REQUIRED_TIMEFRAMES)
    assert cuda_prediction_status["paper_actionability_allowed_rows_count"] == 0
    assert cuda_prediction_status["paper_actionability_blocked_rows_count"] == len(REQUIRED_TIMEFRAMES)
    assert cuda_prediction_status["paper_actionability_block_reason_counts"] == {
        svc.PAPER_DIRECTIONAL_COLLAPSE_BLOCK_REASON: len(REQUIRED_TIMEFRAMES)
    }
    assert all(row["paper_fill_allowed"] is False for row in prediction_status["prediction_rows"])
    assert all(signal["paper_fill_allowed"] is False for signal in signal_status["published_signals"])


def test_trainer_trust_rejection_with_accepted_flag_still_excludes_scope_symbol(monkeypatch) -> None:
    class _Example:
        row_classification = "MARKET_STATE_REJECTED"

        def __init__(self, timeframe: str) -> None:
            self.trust_row = {
                "accepted_for_training": True,
                "trainer_consumable": False,
                "reject_reasons": [f"MTF_SNAPSHOT:MISSING_CLOSED_CANDLE_{timeframe}"],
            }

    class _Loader:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def build_example(self, *, symbol: str, timeframe: str) -> _Example:
            return _Example(timeframe)

    monkeypatch.setattr(svc, "V2HybridTrainerDataLoader", _Loader)

    trust = svc.trainer_trust_rejects_all_timeframes(
        store=V2KeyValueStore(_MemoryClient()),
        symbol="EVAAUSDT",
        timeframes=REQUIRED_TIMEFRAMES,
    )

    assert trust["exclude_from_expected_grid"] is True
    assert trust["status"] == "TRAINER_TRUST_REJECTED_ALL_TIMEFRAMES"
    assert trust["reasons_by_timeframe"]["1h"] == ["MTF_SNAPSHOT:MISSING_CLOSED_CANDLE_1h"]


def test_prediction_targets_and_lineage_ready_but_full_parity_gate_waits_for_supporting_evidence(tmp_path: Path, monkeypatch) -> None:
    _ok_production(monkeypatch)
    paths = default_paths(tmp_path)
    _write_symbol_scope(paths, ["BTCUSDT"])
    client = _MemoryClient()
    store = V2KeyValueStore(client)
    _seed_price(client, "BTCUSDT", 100.0)
    client.set(
        "v2:signals:paper:BTCUSDT",
        json.dumps(
            {
                "risk_decision_id": "risk_1",
                "orchestrator_decision_id": "orch_1",
                "paper_intent_id": "pei_1",
                "paper_ledger_id": "pledger_1",
            }
        ),
    )
    client.set(
        "v2:risk:gateway:decisions",
        json.dumps(
            [
                {
                    "prediction_id": f"pred_BTCUSDT_{tf}",
                    "risk_decision_id": f"risk_{tf}",
                }
                for tf in REQUIRED_TIMEFRAMES
            ]
        ),
    )
    client.set(
        "v2:paper:intents",
        json.dumps(
            [
                {
                    "intent_id": f"pei_{tf}",
                    "symbol": "BTCUSDT",
                    "source_prediction_id": f"pred_BTCUSDT_{tf}",
                    "paper_fill_allowed": True,
                }
                for tf in REQUIRED_TIMEFRAMES
            ]
        ),
    )
    client.set(
        "v2:paper:ledger",
        json.dumps(
            {
                "accepted": [
                    {
                        "symbol": "BTCUSDT",
                        "source_prediction_id": f"pred_BTCUSDT_{tf}",
                        "paper_ledger_id": f"pledger_{tf}",
                    }
                    for tf in REQUIRED_TIMEFRAMES
                ],
                "shadow_observations": [],
            }
        ),
    )
    for tf in REQUIRED_TIMEFRAMES:
        _seed_feature_snapshot(client, "BTCUSDT", tf)
        prediction = _prediction("BTCUSDT", tf, expected=25.0, after=13.0)
        prediction.update(
            {
                "paper_fill_allowed": True,
                "market_state_id": f"mstate_BTCUSDT_{tf}",
                "market_state_integrity_score": 96.0,
                "valid_for_training": True,
                "valid_for_prediction": True,
                "valid_for_risk": True,
                "valid_for_orchestrator": True,
                "valid_for_paper": True,
                "valid_for_live": False,
                "market_state_reject_reasons": [],
            }
        )
        client.set(f"v2:prediction:BTCUSDT:{tf}", json.dumps(prediction))
        client.set(
            f"v2:signals:paper:BTCUSDT:{tf}",
            json.dumps(
                {
                    "prediction_id": f"pred_BTCUSDT_{tf}",
                    "risk_decision_id": "risk_1",
                    "orchestrator_decision_id": "orch_1",
                    "paper_intent_id": "pei_1",
                    "paper_ledger_id": "pledger_1",
                }
            ),
        )

    result = build_packet(paths=paths, store=store, stale_seconds=3600, production_base_url="https://example.test", routes=["/signals"])

    assert result.go_no_go == GATE_BLOCKED
    prediction_status = result.payloads["all_timeframe_prediction_publisher_status.json"]
    lineage_status = result.payloads["all_timeframe_signal_lineage_status.json"]
    cuda_prediction_status = result.payloads["all_symbol_all_timeframe_cuda_prediction_status.json"]
    resource_status = result.payloads["cuda_cpu_resource_utilization_upgrade_status.json"]
    assert prediction_status["current_prediction_count"] == 5
    assert prediction_status["blocker_count"] == 0
    assert lineage_status["missing_lineage_count"] == 0
    assert cuda_prediction_status["symbols_covered"] == ["BTCUSDT"]
    assert cuda_prediction_status["timeframes_covered"] == list(REQUIRED_TIMEFRAMES)
    assert cuda_prediction_status["symbols_count"] == 1
    assert cuda_prediction_status["timeframes_count"] == len(REQUIRED_TIMEFRAMES)
    assert cuda_prediction_status["prediction_rows_count"] == len(REQUIRED_TIMEFRAMES)
    assert cuda_prediction_status["current_prediction_count"] == len(REQUIRED_TIMEFRAMES)
    assert cuda_prediction_status["expected_prediction_count"] == len(REQUIRED_TIMEFRAMES)
    assert cuda_prediction_status["blocked_prediction_rows_count"] == 0
    assert resource_status["status"] == "CUDA_CPU_RESOURCE_UTILIZATION_UPGRADE_BLOCKED_OR_PARTIAL"


def test_prediction_grid_uses_closed_candle_price_when_price_key_missing(tmp_path: Path, monkeypatch) -> None:
    _ok_production(monkeypatch)
    paths = default_paths(tmp_path)
    _write_symbol_scope(paths, ["BTCUSDT"])
    client = _MemoryClient()
    store = V2KeyValueStore(client)
    _seed_closed_price(client, "BTCUSDT", 101.0)
    for tf in REQUIRED_TIMEFRAMES:
        _seed_feature_snapshot(client, "BTCUSDT", tf)
        client.set(f"v2:prediction:BTCUSDT:{tf}", json.dumps(_prediction("BTCUSDT", tf, expected=25.0, after=13.0)))

    result = build_packet(paths=paths, store=store, stale_seconds=3600, production_base_url="https://example.test", routes=["/signals"])

    prediction_status = result.payloads["all_timeframe_prediction_publisher_status.json"]
    rows = prediction_status["prediction_rows"]
    assert prediction_status["current_prediction_count"] == len(REQUIRED_TIMEFRAMES)
    assert prediction_status["missing_prediction_count"] == 0
    first = rows[0]
    assert first["last_price"] == 101.0
    assert first["price_target"] == 101.2525
    assert first["source_lineage"]["price_source_field"] == "price"


def test_cuda_prediction_status_count_fields_are_backfilled_from_arrays(tmp_path: Path, monkeypatch) -> None:
    _ok_production(monkeypatch)
    paths = default_paths(tmp_path)
    _write_symbol_scope(paths, ["BTCUSDT"])
    client = _MemoryClient()
    store = V2KeyValueStore(client)
    _seed_price(client, "BTCUSDT", 100.0)
    for tf in REQUIRED_TIMEFRAMES:
        _seed_feature_snapshot(client, "BTCUSDT", tf)
        client.set(f"v2:prediction:BTCUSDT:{tf}", json.dumps(_prediction("BTCUSDT", tf)))

    original_builder = svc.build_cuda_prediction_status

    def _builder_without_scalar_counts(prediction_status: dict[str, Any]) -> dict[str, Any]:
        status = original_builder(prediction_status)
        status["symbols_covered"] = []
        status["timeframes_covered"] = []
        status["symbols_count"] = None
        status["timeframes_count"] = None
        status["expected_prediction_count"] = None
        status["top_paper_block_reasons"] = None
        status["top_prediction_paper_gate_block_reasons"] = None
        return status

    monkeypatch.setattr(svc, "build_cuda_prediction_status", _builder_without_scalar_counts)

    result = build_packet(paths=paths, store=store, stale_seconds=3600, production_base_url="https://example.test", routes=["/signals"])

    cuda_prediction_status = result.payloads["all_symbol_all_timeframe_cuda_prediction_status.json"]
    assert cuda_prediction_status["symbols_covered"] == ["BTCUSDT"]
    assert cuda_prediction_status["timeframes_covered"] == list(REQUIRED_TIMEFRAMES)
    assert cuda_prediction_status["symbols_count"] == 1
    assert cuda_prediction_status["timeframes_count"] == len(REQUIRED_TIMEFRAMES)
    assert cuda_prediction_status["expected_prediction_count"] == len(REQUIRED_TIMEFRAMES)
    assert cuda_prediction_status["top_paper_block_reasons"] == cuda_prediction_status[
        "paper_actionability_block_reason_counts"
    ]
    assert cuda_prediction_status["top_prediction_paper_gate_block_reasons"] == cuda_prediction_status[
        "paper_actionability_block_reason_counts"
    ]


def test_cuda_prediction_status_exposes_grid_and_actionability_truth() -> None:
    rows = [
        {
            "prediction_id": "pred_BTCUSDT_1m",
            "generated_est": svc.est_now(),
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "status": "PRESENT_CURRENT",
            "trainer_source": svc.TRAINER_SOURCE_REQUIRED,
            "model_source": svc.MODEL_SOURCE_REQUIRED,
            "selected_action": "hold",
            "expected_move_bps": -12.0,
            "expected_move_after_cost_bps": 0.0,
            "selected_hold_with_directional_edge_after_cost": True,
            "selected_hold_directional_edge_diagnostic_reason": (
                "EXPECTED_MOVE_DIRECTIONAL_EDGE_BLOCKED_BY_SELECTED_HOLD"
            ),
            "paper_fill_allowed": False,
            "paper_fill_gate_block_reasons": ["confidence_below_threshold", "data_coverage_below_threshold"],
        },
        {
            "symbol": "BTCUSDT",
            "timeframe": "5m",
            "status": "STALE_TF_PREDICTION",
        },
        {
            "symbol": "ETHUSDT",
            "timeframe": "1m",
            "status": "MISSING_TF_PREDICTION",
        },
    ]

    status = svc.normalize_cuda_prediction_status_counts(svc.build_cuda_prediction_status({"prediction_rows": rows}))

    assert status["present_current_prediction_rows_count"] == 1
    assert status["missing_prediction_rows_count"] == 1
    assert status["stale_prediction_rows_count"] == 1
    assert status["non_current_prediction_rows_count"] == 2
    assert status["paper_actionability_blocked_rows_count"] == 1
    assert status["paper_actionability_block_reason_counts"] == {
        "confidence_below_threshold": 1,
        "data_coverage_below_threshold": 1,
    }
    assert status["top_paper_block_reasons"] == {
        "confidence_below_threshold": 1,
        "data_coverage_below_threshold": 1,
    }
    assert status["top_prediction_paper_gate_block_reasons"] == {
        "confidence_below_threshold": 1,
        "data_coverage_below_threshold": 1,
    }
    assert status["selected_action_expected_move_bps_sign_counts"] == {
        "hold:negative": 1,
    }
    assert status["hold_with_directional_expected_move_bps_count"] == 1
    assert status["hold_zero_after_cost_with_directional_expected_move_bps_count"] == 1
    assert status["selected_hold_with_directional_edge_after_cost_count"] == 1
    assert status["selected_hold_directional_edge_reason_counts"] == {
        "EXPECTED_MOVE_DIRECTIONAL_EDGE_BLOCKED_BY_SELECTED_HOLD": 1,
    }
    repaired = svc.normalize_cuda_prediction_status_counts(
        {
            **status,
            "top_paper_block_reasons": None,
            "top_prediction_paper_gate_block_reasons": None,
        }
    )
    assert repaired["top_paper_block_reasons"] == {
        "confidence_below_threshold": 1,
        "data_coverage_below_threshold": 1,
    }
    assert repaired["top_prediction_paper_gate_block_reasons"] == {
        "confidence_below_threshold": 1,
        "data_coverage_below_threshold": 1,
    }
    assert status["missing_prediction_symbols"] == ["ETHUSDT"]
    assert status["missing_prediction_timeframes_by_symbol"] == {"ETHUSDT": ["1m"]}
    assert status["stale_prediction_symbols"] == ["BTCUSDT"]
    assert status["stale_prediction_timeframes_by_symbol"] == {"BTCUSDT": ["5m"]}
    assert status["coverage_status"] == "CUDA_PREDICTION_GRID_PARTIAL_MISSING_OR_STALE_TF_ROWS"
    assert status["actionability_status"] == "PAPER_ACTIONABILITY_BLOCKED_BY_GATES"


def test_missing_expected_move_blocks_without_fake_price_target(tmp_path: Path, monkeypatch) -> None:
    _ok_production(monkeypatch)
    paths = default_paths(tmp_path)
    _write_symbol_scope(paths, ["BTCUSDT"])
    client = _MemoryClient()
    store = V2KeyValueStore(client)
    _seed_price(client, "BTCUSDT", 100.0)
    client.set("v2:prediction:BTCUSDT:1m", json.dumps(_prediction("BTCUSDT", "1m", expected=None, after=None)))

    result = build_packet(paths=paths, store=store, stale_seconds=3600, production_base_url="https://example.test", routes=["/signals"])

    assert result.go_no_go == GATE_BLOCKED
    prediction_rows = result.payloads["all_timeframe_prediction_publisher_status.json"]["prediction_rows"]
    row = next(item for item in prediction_rows if item["symbol"] == "BTCUSDT" and item["timeframe"] == "1m")
    assert row["status"] == "EXPECTED_MOVE_TELEMETRY_MISSING"
    assert row["price_target"] is None
    expected_move_status = result.payloads["expected_move_telemetry_status.json"]
    telemetry = next(item for item in expected_move_status["telemetry_rows"] if item["timeframe"] == "1m")
    assert telemetry["missing_reason_if_absent"] == "EXPECTED_MOVE_TELEMETRY_MISSING"


def test_mismatched_existing_paper_lineage_is_not_reused(tmp_path: Path, monkeypatch) -> None:
    _ok_production(monkeypatch)
    paths = default_paths(tmp_path)
    _write_symbol_scope(paths, ["BTCUSDT"])
    client = _MemoryClient()
    store = V2KeyValueStore(client)
    _seed_price(client, "BTCUSDT", 100.0)
    client.set(
        "v2:signals:paper:BTCUSDT",
        json.dumps(
            {
                "trainer_prediction_id": "pred_different",
                "risk_decision_id": "risk_1",
                "orchestrator_decision_id": "orch_1",
                "paper_intent_id": "pei_1",
                "paper_ledger_id": "pledger_1",
            }
        ),
    )
    for tf in REQUIRED_TIMEFRAMES:
        _seed_feature_snapshot(client, "BTCUSDT", tf)
        client.set(f"v2:prediction:BTCUSDT:{tf}", json.dumps(_prediction("BTCUSDT", tf, expected=25.0, after=13.0)))

    result = build_packet(paths=paths, store=store, stale_seconds=3600, production_base_url="https://example.test", routes=["/signals"])

    assert result.go_no_go == GATE_BLOCKED
    lineage_status = result.payloads["all_timeframe_signal_lineage_status.json"]
    first_row = lineage_status["lineage_rows"][0]
    assert first_row["trainer_prediction_exists"] is True
    assert first_row["risk_decision_exists"] is False
    assert first_row["orchestrator_decision_exists"] is False
    assert lineage_status["missing_lineage_count"] == 5


def test_store_rejects_non_v2_writes() -> None:
    store = V2KeyValueStore(_MemoryClient())

    assert store.set_json("legacy:prediction:BTCUSDT:1m", {"x": 1}) is False
    assert store.audit.old_redis_write_attempts == 1


def test_service_source_has_no_exchange_or_legacy_mutation_tokens() -> None:
    source = Path(svc.__file__).read_text(encoding="utf-8")
    forbidden = [
        "create" + "_order",
        "cancel" + "_order",
        "futures" + "_change" + "_leverage",
        "futures" + "_change" + "_margin" + "_type",
        "xtrim",
        "flushdb",
    ]
    for token in forbidden:
        assert token not in source
