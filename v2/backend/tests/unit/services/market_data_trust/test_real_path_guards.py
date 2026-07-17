from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.cli import run_recorded_state_verification as recorded_cli
from v2.backend.app.services.native_trainer.dataset_builder import (
    ROW_MARKET_STATE_REJECTED,
    LabelRow,
    build_dataset_row,
    build_rows_from_replay_bundles,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    V2HybridTrainerDataLoader,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.safety import (
    V2OnlyJsonIO,
)


class _MemoryClient:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str):
        self.store[key] = value
        return True


def _label_row(snapshot_id: str, label: str, after_cost: float | None) -> LabelRow:
    return LabelRow(
        feature_snapshot_id=snapshot_id,
        symbol="BTCUSDT",
        timeframe="1m",
        label=label,
        after_cost_return_bps=after_cost,
        max_favorable_bps=None,
        max_adverse_bps=None,
        paper_gate_status=None,
        paper_gate_block_reasons=[],
        risk_decision_context=None,
        legacy_reference_action=None,
    )


def _seed_loader(
    client: _MemoryClient,
    *,
    feature_overrides: dict[str, object] | None = None,
    prediction_overrides: dict[str, object] | None = None,
) -> None:
    latest = {
        "feature_snapshot_id": "v2_fsnap_BTCUSDT_1m_market_trust_test",
        "feature_freshness_state": "CURRENT",
        "freshness_state": "FRESH",
        "generated_at": "2026-06-11T00:01:00Z",
        "feature_cutoff": "2026-06-11T00:01:00Z",
        "available_at": "2026-06-11T00:01:00Z",
        "source_event_time": "2026-06-11T00:01:00Z",
        "source_available_time": "2026-06-11T00:01:00Z",
        "decision_time": "2026-06-11T00:01:05Z",
        "candle_closed_confirmed": True,
        "candle_open_time": "2026-06-11T00:00:00Z",
        "candle_close_time": "2026-06-11T00:01:00Z",
        "all_tf_candle_timestamps": ["2026-06-11T00:01:00Z"],
        "all_source_event_times": ["2026-06-11T00:01:00Z"],
        "features": {
            "ret_pct": 0.001,
            "log_return": 0.001,
            "range_pct": 0.004,
            "body_pct": 0.001,
            "true_range_pct": 0.005,
            "ema_12": 101.0,
            "ema_26": 100.0,
            "rsi_14": 56.0,
            "macd": 0.08,
            "macd_signal": 0.04,
            "macd_hist": 0.04,
            "bb_width_pct": 0.012,
            "htf_ret_pct": 0.002,
            "htf_rsi_14": 58.0,
            "bid_ask_spread_bps": 3.0,
            "depth_imbalance": 0.15,
            "micro_price": 101.0,
            "toxicity_proxy": 0.1,
            "paper_position_present": 0,
        },
        "missing_feature_flags": [],
        "stale_feature_flags": [],
    }
    if feature_overrides:
        latest.update(feature_overrides)

    prediction = {
        "prediction_id": "pred_btc_1m",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "masa_feature_cutoff": "2026-06-11T00:01:00Z",
        "ppo_feature_cutoff": "2026-06-11T00:01:00Z",
        "source_mode": "paper",
    }
    if prediction_overrides:
        prediction.update(prediction_overrides)

    client.set("v2:features:latest:BTCUSDT:1m", json.dumps(latest))
    client.set(
        "v2:features:ta:BTCUSDT:1m",
        json.dumps({"indicators": {"ema_12": 101.0, "ema_26": 100.0, "rsi_14": 56.0}}),
    )
    client.set("v2:prediction:BTCUSDT:1m", json.dumps(prediction))
    client.set("v2:market:prices:BTCUSDT", json.dumps({"price": 101.0}))
    client.set(
        "v2:market:ohlcv:binance:BTCUSDT:1m",
        json.dumps({"open": 100.0, "high": 101.0, "low": 99.5, "close": 101.0, "volume": 1000.0}),
    )
    client.set("v2:market:orderbook:BTCUSDT", json.dumps({"spread_bps": 3.0, "depth_imbalance": 0.15}))
    client.set("v2:market:funding:BTCUSDT", json.dumps({"funding_rate": 0.0001}))
    client.set("v2:market:open_interest:BTCUSDT", json.dumps({"open_interest": 1000000.0}))
    client.set("v2:market:open_interest_hist:BTCUSDT:5m", json.dumps({"change_pct": 0.01}))
    client.set(
        "v2:market:long_short:BTCUSDT",
        json.dumps(
            {
                "long_short_ratio": 1.5,
                "long_account_ratio": 0.6,
                "short_account_ratio": 0.4,
            }
        ),
    )
    client.set("v2:market:microstructure:BTCUSDT", json.dumps({"micro_price": 101.0, "toxicity_proxy": 0.1}))
    client.set("v2:market:liquidation_levels:BTCUSDT", json.dumps({"nearest_distance_bps": 150.0}))
    client.set("v2:altdata:public_intel:symbol:BTCUSDT", json.dumps({"public_intel_score": 0.5}))
    client.set(
        "v2:altdata:whale_walls:symbol:BTCUSDT",
        json.dumps({"whale_wall_score": 0.8, "whale_bid_pressure_score": 0.85}),
    )
    client.set(
        "v2:altdata:symbol_score:BTCUSDT",
        json.dumps(
            {
                "altdata_symbol_score": 0.5,
                "provider_availability_score": 1.0,
                "altdata_freshness_score": 1.0,
                "public_intel_score": 0.5,
                "coingecko_discovery_score": 0.6,
                "defillama_liquidity_score": 0.4,
                "whale_wall_score": 0.8,
                "whale_bid_pressure_score": 0.85,
                "provider_available": {"whale_walls": True},
                "input_presence": {"whale_walls": True},
            }
        ),
    )
    client.set("v2:liquidations:events", json.dumps({"count_5m": 1}))
    client.set("v2:risk:decisions", json.dumps({"recent_allow_rate": 0.0}))
    client.set("v2:orchestrator:decisions", json.dumps({"recent_allow_rate": 0.0}))
    client.set("v2:paper:positions", json.dumps({"position_present": 0, "unrealized_bps": 0.0}))
    client.set("v2:paper:ledger", json.dumps({"entries": []}))
    client.set("v2:paper:position_history", json.dumps({"entries": []}))


def _clean_records() -> dict[str, list[dict[str, object]]]:
    return {
        "candles": [
            {
                "exchange": "binance",
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "open_time": 1_700_000_000_000,
                "close_time": 1_700_000_060_000,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 10.0,
                "closed_candle": True,
            }
        ],
        "features": [
            {
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "generated_at": "2026-06-11T00:01:00Z",
                "feature_cutoff": "2026-06-11T00:01:00Z",
                "available_at": "2026-06-11T00:01:00Z",
                "feature_hash": "feature-hash-p1",
                "input_feature_hash": "feature-hash-p1",
                "mtf_snapshot_id": "mtf-p1",
                "all_tf_candle_timestamps": ["2026-06-11T00:01:00Z"],
                "source_candle_timestamps": ["2026-06-11T00:01:00Z"],
                "features": {"ret_pct": 0.01},
            }
        ],
        "masa_ppo": [
            {
                "prediction_id": "p1",
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "decision_time": "2026-06-11T00:01:05Z",
                "masa_generated_at": "2026-06-11T00:01:00Z",
                "masa_feature_cutoff": "2026-06-11T00:01:00Z",
                "masa_forecast_horizon": "1m",
                "ppo_observation_time": "2026-06-11T00:01:00Z",
                "ppo_feature_cutoff": "2026-06-11T00:01:00Z",
                "feature_cutoff": "2026-06-11T00:01:00Z",
                "available_at": "2026-06-11T00:01:00Z",
                "input_feature_hash": "feature-hash-p1",
                "all_tf_candle_timestamps": ["2026-06-11T00:01:00Z"],
                "mtf_snapshot_id": "mtf-p1",
                "selected_action": "hold",
                "masa_signal": 0.5,
                "replay_snapshot_id": "snap-p1",
                "replay_snapshot_key": "v2:replay:snapshots:snap-p1",
                "replay_snapshot_write_success": True,
            }
        ],
        "training_samples": [
            {
                "sample_id": "s1",
                "row_classification": "TRAINABLE",
                "used_for_training": True,
                "accepted_for_training": True,
                "feature_cutoff": "2026-06-11T00:01:00Z",
                "available_at": "2026-06-11T00:01:00Z",
                "input_feature_hash": "feature-hash-p1",
                "all_tf_candle_timestamps": ["2026-06-11T00:01:00Z"],
                "mtf_snapshot_id": "mtf-p1",
                "replay_snapshot_id": "snap-p1",
                "label_start_time": "2026-06-11T00:01:00Z",
                "label_end_time": "2026-06-11T00:02:00Z",
                "prediction_horizon_seconds": 60,
                "features": {"ret_pct": 0.01},
                "fee_bps": 5,
                "slippage_bps": 2,
            }
        ],
        "execution_records": [
            {
                "position_before": "flat",
                "requested_action": "hold",
                "position_after": "flat",
                "fill_status": "hold",
            }
        ],
        "positions": [{"symbol": "BTCUSDT", "local_position": "flat", "exchange_position": "flat"}],
        "config_admin": [{"live_gate": "blocked_human_only"}],
        "replay_snapshots": [
            {
                "decision_id": "p1",
                "prediction_id": "p1",
                "replay_snapshot_id": "snap-p1",
                "mtf_snapshot_id": "mtf-p1",
                "input_feature_hash": "feature-hash-p1",
                "all_tf_candle_timestamps": ["2026-06-11T00:01:00Z"],
            }
        ],
    }


def _write_records(tmp_path: Path, records: dict[str, list[dict[str, object]]]) -> Path:
    run_dir = tmp_path / "recorded"
    run_dir.mkdir(parents=True, exist_ok=True)
    file_names = {
        "candles": "candles.jsonl",
        "features": "features.jsonl",
        "masa_ppo": "masa_ppo.jsonl",
        "training_samples": "training_samples.jsonl",
        "execution_records": "execution_records.jsonl",
        "positions": "positions.jsonl",
        "config_admin": "config_admin.jsonl",
        "replay_snapshots": "replay_snapshots.jsonl",
    }
    for category, rows in records.items():
        with (run_dir / file_names[category]).open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(
                    json.dumps(
                        {
                            "redis_key": f"v2:test:{category}",
                            "category": category,
                            "value": row,
                        }
                    )
                    + "\n"
                )
    return run_dir


def test_dataset_builder_rejects_feature_available_after_decision_time() -> None:
    row = build_dataset_row(
        symbol="BTCUSDT",
        timeframe="1m",
        features={
            "feature_snapshot_id": "fs-trust-1",
            "freshness_state": "FRESH",
            "generated_at": "2026-06-11T00:01:00Z",
            "feature_cutoff": "2026-06-11T00:01:00Z",
            "available_at": "2026-06-11T00:01:06Z",
            "source_event_time": "2026-06-11T00:01:00Z",
            "source_available_time": "2026-06-11T00:01:06Z",
            "decision_time": "2026-06-11T00:01:05Z",
            "candle_closed_confirmed": True,
            "candle_open_time": "2026-06-11T00:00:00Z",
            "candle_close_time": "2026-06-11T00:01:00Z",
        },
        ta={"indicators": {"ema_9": 100.0, "ema_21": 99.5, "rsi_14": 55.0}},
        altdata=None,
        risk_decision=None,
        label_row=_label_row("fs-trust-1", "true_positive_after_cost_gain", 10.0),
    )

    assert row.classification == ROW_MARKET_STATE_REJECTED
    assert row.accepted_for_training is False
    assert "source_available_after_decision_cutoff" in row.training_reject_reasons


def test_replay_bundle_builder_rejects_unfinished_higher_timeframe_bundle(tmp_path: Path) -> None:
    bundles_path = tmp_path / "replay_outcome_bundles.jsonl"
    bundles_path.write_text(
        json.dumps(
            {
                "feature_snapshot_id": "BTCUSDT:15m:replay:1",
                "symbol": "BTCUSDT",
                "timeframe": "15m",
                "label": "true_positive_after_cost_gain",
                "generated_at": "2026-06-11T00:15:00Z",
                "feature_cutoff": "2026-06-11T00:15:00Z",
                "available_at": "2026-06-11T00:15:00Z",
                "source_event_time": "2026-06-11T00:15:00Z",
                "source_available_time": "2026-06-11T00:15:00Z",
                "decision_time": "2026-06-11T00:15:05Z",
                "candle_closed_confirmed": False,
                "candle_open_time": "2026-06-11T00:00:00Z",
                "candle_close_time": "2026-06-11T00:15:00Z",
                "future_outcomes": {"15m": {"after_cost_return_bps": 12.0}},
                "orchestrator_decision": {
                    "bucket_winners": [
                        {
                            "symbol": "BTCUSDT",
                            "winner_confidence_calibrated": 0.71,
                            "winner_expected_move_after_cost_bps": 12.0,
                            "winner_freshness_seconds": 5.0,
                        }
                    ]
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    rows = build_rows_from_replay_bundles(bundles_path)

    assert len(rows) == 1
    assert rows[0].classification == ROW_MARKET_STATE_REJECTED
    assert "UNCLOSED_CANDLE" in rows[0].training_reject_reasons


def test_data_loader_trusted_only_filters_future_masa_cutoff() -> None:
    client = _MemoryClient()
    _seed_loader(
        client,
        prediction_overrides={"masa_feature_cutoff": "2026-06-11T00:01:06Z"},
    )
    loader = V2HybridTrainerDataLoader(io=V2OnlyJsonIO(client=client))

    example = loader.build_example(symbol="BTCUSDT", timeframe="1m")
    trusted = loader.load_training_examples(symbols=("BTCUSDT",), timeframes=("1m",), trusted_only=True)

    assert example.row_classification == "MARKET_STATE_REJECTED"
    assert "MASA_FEATURE_CUTOFF_AFTER_DECISION_TIME" in (example.trust_row or {}).get("reject_reasons", [])
    assert trusted == []


def test_data_loader_tensor_consumes_whale_walls_altdata() -> None:
    client = _MemoryClient()
    _seed_loader(client)
    loader = V2HybridTrainerDataLoader(io=V2OnlyJsonIO(client=client))

    example = loader.build_example(symbol="BTCUSDT", timeframe="1m")
    values = dict(zip(example.tensor.feature_names, example.tensor.values))

    assert values["whale_wall_score"] == 0.8
    assert values["whale_bid_pressure_score"] == 0.85
    assert values["public_intel_score"] == 0.5
    assert "v2:altdata:whale_walls:symbol:BTCUSDT" in example.payload_keys


def test_data_loader_trusted_only_filters_backfilled_live_example() -> None:
    client = _MemoryClient()
    _seed_loader(
        client,
        feature_overrides={"backfilled": True},
        prediction_overrides={"source_mode": "live"},
    )
    loader = V2HybridTrainerDataLoader(io=V2OnlyJsonIO(client=client))

    example = loader.build_example(symbol="BTCUSDT", timeframe="1m")
    trusted = loader.load_training_examples(symbols=("BTCUSDT",), timeframes=("1m",), trusted_only=True)

    assert example.row_classification == "MARKET_STATE_REJECTED"
    assert "BACKFILLED_DATA_MARKED_LIVE" in (example.trust_row or {}).get("reject_reasons", [])
    assert trusted == []


def test_snapshot_fast_path_derives_closed_higher_timeframe_candles_from_raw_ohlcv() -> None:
    client = _MemoryClient()
    _seed_loader(client)
    rows_by_timeframe = {
        "1m": [1781136000000, "100", "101", "99", "100.5", "10", 1781136059999, "1000", 10, "5", "500", "0"],
        "5m": [1781135700000, "100", "101", "99", "100.5", "10", 1781135999999, "1000", 10, "5", "500", "0"],
        "15m": [1781135100000, "100", "101", "99", "100.5", "10", 1781135999999, "1000", 10, "5", "500", "0"],
        "1h": [1781132400000, "100", "101", "99", "100.5", "10", 1781135999999, "1000", 10, "5", "500", "0"],
        "4h": [1781121600000, "100", "101", "99", "100.5", "10", 1781135999999, "1000", 10, "5", "500", "0"],
    }
    for timeframe, row in rows_by_timeframe.items():
        client.set(f"v2:market:ohlcv:binance:BTCUSDT:{timeframe}", json.dumps([row]))
    loader = V2HybridTrainerDataLoader(io=V2OnlyJsonIO(client=client))

    example = loader.build_example(symbol="BTCUSDT", timeframe="1m", snapshot_fast_path=True)
    trust_row = example.trust_row or {}

    assert trust_row["mtf_snapshot_valid"] is True
    assert len(trust_row["all_tf_candle_timestamps"]) == 5
    assert "MTF_SNAPSHOT:MISSING_CLOSED_CANDLE_1h" not in trust_row.get("reject_reasons", [])
    assert "MTF_SNAPSHOT:MISSING_CLOSED_CANDLE_4h" not in trust_row.get("reject_reasons", [])
    assert "v2:market:ohlcv:binance:BTCUSDT:1h" in example.payload_keys
    assert "v2:market:ohlcv:binance:BTCUSDT:4h" in example.payload_keys


def test_recorded_state_verification_passes_clean_export(tmp_path: Path) -> None:
    run_dir = _write_records(tmp_path, _clean_records())
    output_dir = tmp_path / "out-clean"

    exit_code = recorded_cli.main(["--input", str(run_dir), "--output-dir", str(output_dir)])

    assert exit_code == 0
    payload = json.loads((output_dir / "recorded_state_verification_report.json").read_text(encoding="utf-8"))
    assert payload["metrics"]["future_feature_leak_count"] == 0
    assert payload["metrics"]["masa_ppo_cutoff_mismatch_count"] == 0
    assert payload["metrics"]["position_transition_reject_count"] == 0


def test_recorded_state_verification_fails_on_replay_gap_and_invalid_transition(tmp_path: Path) -> None:
    records = _clean_records()
    records["masa_ppo"][0]["replay_snapshot_id"] = None
    records["masa_ppo"][0]["replay_snapshot_write_success"] = False
    records["execution_records"][0] = {
        "position_before": "LONG",
        "requested_action": "short",
        "position_after": "SHORT",
        "fill_status": "filled",
        "strategy_router_block_reason": "DATA_QUALITY_BELOW_THRESHOLD",
    }
    run_dir = _write_records(tmp_path, records)
    output_dir = tmp_path / "out-dirty"

    exit_code = recorded_cli.main(["--input", str(run_dir), "--output-dir", str(output_dir)])

    assert exit_code == 1
    payload = json.loads((output_dir / "recorded_state_verification_report.json").read_text(encoding="utf-8"))
    assert payload["metrics"]["position_transition_reject_count"] == 1
    assert payload["metrics"]["trades_blocked_by_data_quality"] >= 1
    assert (output_dir / "recorded_state_verification_report.txt").exists()


def test_recorded_state_verification_ignores_non_consumable_microfeature_rows(tmp_path: Path) -> None:
    records = _clean_records()
    records["features"].append(
        {
            "symbol": "GALAUSDT",
            "timeframe": "1m",
            "generated_at": "2026-06-11T00:01:00Z",
            "available_at": "2026-06-11T00:01:00Z",
            "feature_cutoff": "2026-06-11T00:01:00Z",
            "features": {
                "churn_score": None,
                "fast_move_score": None,
                "p_false_move": None,
            },
        }
    )
    run_dir = _write_records(tmp_path, records)
    output_dir = tmp_path / "out-microfeat"

    exit_code = recorded_cli.main(["--input", str(run_dir), "--output-dir", str(output_dir)])

    assert exit_code == 0
    payload = json.loads((output_dir / "recorded_state_verification_report.json").read_text(encoding="utf-8"))
    assert payload["metrics"]["invalid_state_count"] == 0


def test_recorded_state_verification_fails_on_consumable_invalid_feature_row(tmp_path: Path) -> None:
    records = _clean_records()
    records["features"][0]["trainer_consumable"] = True
    records["features"][0]["features"] = {"ret_pct": None}
    run_dir = _write_records(tmp_path, records)
    output_dir = tmp_path / "out-consumable-invalid"

    exit_code = recorded_cli.main(["--input", str(run_dir), "--output-dir", str(output_dir)])

    assert exit_code == 0
    payload = json.loads((output_dir / "recorded_state_verification_report.json").read_text(encoding="utf-8"))
    assert payload["metrics"]["invalid_state_count"] == 1


def test_recorded_state_verification_ignores_preview_and_manifest_records(tmp_path: Path) -> None:
    records = _clean_records()
    records["training_samples"].extend(
        [
            {
                "schema_version": "v2_native_dynamic_runtime_trainer_bridge_exit_execution_v1_trainer_dataset_manifest",
                "generated_utc": "2026-05-24T00:27:22Z",
                "trainer_source": "V2_NATIVE_CONTRACT_ONLY",
                "training_dispatched": False,
            },
            {
                "decision_id": "dec_preview",
                "prediction_id": "pred_preview",
                "feature_snapshot_id": "fs_preview",
                "risk_action": "deny",
                "symbol": "ZROUSDT",
            },
            {
                "decision_id": "dec_preview",
                "prediction_id": "pred_preview",
                "feature_snapshot_id": "fs_preview",
                "decision_action": "abstain",
                "symbol": "ZROUSDT",
            },
        ]
    )
    run_dir = _write_records(tmp_path, records)
    output_dir = tmp_path / "out-preview-manifest"

    exit_code = recorded_cli.main(["--input", str(run_dir), "--output-dir", str(output_dir)])

    assert exit_code == 0
    payload = json.loads((output_dir / "recorded_state_verification_report.json").read_text(encoding="utf-8"))
    assert payload["metrics"]["invalid_state_count"] == 0
