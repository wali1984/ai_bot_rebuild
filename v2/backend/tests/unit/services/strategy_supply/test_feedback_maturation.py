from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    V2HybridTrainerDataLoader,
    _trainer_feedback_row_usable,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.safety import V2OnlyJsonIO
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import FEATURE_SPEC
from v2.backend.app.services.market_state_integrity.sample_rejection import classify_training_sample
from v2.backend.app.services.strategy_supply import feedback_maturation as maturation


class FakeRedis:
    def __init__(self, payloads: dict[str, Any] | None = None) -> None:
        self.payloads = dict(payloads or {})

    def get(self, key: str) -> Any:
        value = self.payloads.get(key)
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        return value

    def set(self, key: str, value: Any) -> None:
        self.payloads[key] = value


def _pending_row(**overrides: Any) -> dict[str, Any]:
    feature_values = {name: 1.0 for name, _source in FEATURE_SPEC[:90]}
    feature_values.update(
        {
            "open": 99.8,
            "high": 101.0,
            "low": 99.5,
            "close": 100.0,
            "orderbook_depth_usd": 50000.0,
            "funding_bps": 2.5,
            "funding_rate": 0.00025,
            "observed_spread_bps": 3.0,
        }
    )
    row = {
        "schema_version": "strategy_supply_pending_evidence_v1",
        "hypothesis_id": "hyp-1",
        "candidate_id": "cand-1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "strategy_id": "supply-long",
        "strategy_family": "breakout_after_compression",
        "strategy_subtype": "compression_long",
        "decision_time": "2026-06-21T12:00:00Z",
        "feature_cutoff": "2026-06-21T11:59:50Z",
        "available_at": "2026-06-21T11:59:59Z",
        "expected_net_pnl_usd": 8.5,
        "expected_gross_pnl_usd": 10.0,
        "expected_cost_usd": 1.0,
        "expected_fees_usd": 0.25,
        "expected_slippage_usd": 0.5,
        "expected_funding_usd": 0.25,
        "expected_max_loss_usd": 5.0,
        "notional_usd": 1000.0,
        "margin_usd": 1000.0,
        "entry_price": 100.0,
        "current_price": 100.0,
        "entry_price_source": "v2:market:current_price:BTCUSDT",
        "entry_price_utc": "2026-06-21T11:59:59Z",
        "feature_snapshot_id": "fs-entry-1",
        "entry_feature_snapshot_id": "fs-entry-1",
        "entry_feature_snapshot": {
            "feature_snapshot_id": "fs-entry-1",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "available_at": "2026-06-21T11:59:59Z",
            "generated_at": "2026-06-21T11:59:59Z",
            "feature_cutoff": "2026-06-21T11:59:50Z",
            "feature_freshness_state": "CURRENT",
            "candle_closed_confirmed": True,
            "features": feature_values,
        },
        "provider_hashes": {"coinank": "hash-coinank"},
        "source_hashes": {"coinank": "hash-coinank"},
        "preemptive_decision_id": "preemptive-1",
        "allocator_decision_id": "allocator-1",
        "risk_decision_id": "risk-1",
        "orchestrator_decision_id": "orchestrator-1",
        "guardian_decision_id": "guardian-1",
        "orderbook_depth_usd": 50000.0,
        "liquidation_buffer_bps": 800.0,
        "observed_bid_ask_spread_bps": 3.0,
        "expected_funding_bps": 2.5,
        "market_regime": "trend",
        "counts_as_a_plus": False,
        "counts_as_live_ready": False,
    }
    row.update(overrides)
    return row


def _exit_snapshot(close: float = 101.0) -> dict[str, Any]:
    return {
        "feature_snapshot_id": "fs-exit-1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "available_at": "2026-06-21T12:01:01Z",
        "generated_at": "2026-06-21T12:01:01Z",
        "feature_cutoff": "2026-06-21T12:01:00Z",
        "feature_freshness_state": "CURRENT",
        "candle_closed_confirmed": True,
        "features": {"close": close},
    }


def _write_pending(path: Path, row: dict[str, Any]) -> None:
    maturation.append_jsonl(path, row)


def test_strategy_supply_feedback_maturation_publishes_trainer_consumable_row(tmp_path: Path) -> None:
    pending_path = tmp_path / "strategy_supply_pending_evidence.jsonl"
    matured_path = tmp_path / "strategy_supply_matured_evidence.jsonl"
    rejected_path = tmp_path / "strategy_supply_rejected_evidence.jsonl"
    status_path = tmp_path / "status.json"
    _write_pending(pending_path, _pending_row())
    redis = FakeRedis({"v2:features:latest:BTCUSDT:1m": _exit_snapshot()})

    status = maturation.mature_strategy_supply_feedback(
        pending_path=pending_path,
        matured_path=matured_path,
        rejected_path=rejected_path,
        status_path=status_path,
        redis_client=redis,
        now=datetime(2026, 6, 21, 12, 1, 2, tzinfo=timezone.utc),
        publish_to_redis=True,
    )

    assert status["matured_rows"] == 1
    assert status["positive_outcomes"] == 1
    assert status["future_leakage_violations"] == 0
    assert status["trainer_feedback_rows_ready"] == 1
    assert status["trainer_feedback_rows_published_to_redis"] == 1
    payload = json.loads(redis.payloads[maturation.TRAINER_FEEDBACK_REDIS_KEY])
    feedback_row = payload[0]
    assert feedback_row["trainer_feedback_source"] == maturation.FEEDBACK_SOURCE
    assert feedback_row["directional_outcome"] == "UP"
    assert feedback_row["future_labels_used_as_features"] is False
    assert feedback_row["counts_as_a_plus"] is False
    assert feedback_row["entry_feature_snapshot"]["missing_feature_count"] == 0
    assert feedback_row["features"]["bid_ask_spread_bps"] == 3.0
    assert feedback_row["features"]["funding_rate"] == 0.00025
    assert feedback_row["accepted_for_training"] is True
    assert feedback_row["reject_reasons"] == []
    assert _trainer_feedback_row_usable(feedback_row) is True
    loader = V2HybridTrainerDataLoader(io=V2OnlyJsonIO(client=redis))
    examples = loader.load_training_examples(
        symbols=[],
        timeframes=[],
        trusted_only=True,
        closed_trade_only=True,
        limit=10,
    )
    assert len(examples) == 1
    assert examples[0].row_classification == "TRAINABLE"
    sample = classify_training_sample(dict(examples[0].trust_row))
    assert sample["accepted_for_training"] is True
    assert sample["reject_reasons"] == []


def test_strategy_supply_feedback_maturation_rejects_future_leaking_entry_snapshot(tmp_path: Path) -> None:
    pending_path = tmp_path / "strategy_supply_pending_evidence.jsonl"
    matured_path = tmp_path / "strategy_supply_matured_evidence.jsonl"
    rejected_path = tmp_path / "strategy_supply_rejected_evidence.jsonl"
    row = _pending_row(
        entry_feature_snapshot={
            **_pending_row()["entry_feature_snapshot"],
            "available_at": "2026-06-21T12:00:01Z",
        }
    )
    _write_pending(pending_path, row)

    status = maturation.mature_strategy_supply_feedback(
        pending_path=pending_path,
        matured_path=matured_path,
        rejected_path=rejected_path,
        redis_client=FakeRedis({"v2:features:latest:BTCUSDT:1m": _exit_snapshot()}),
        now=datetime(2026, 6, 21, 12, 1, 2, tzinfo=timezone.utc),
        publish_to_redis=True,
    )

    assert status["matured_rows"] == 0
    assert status["dirty_rows_excluded"] == 1
    assert status["future_leakage_violations"] == 1
    rejected = maturation.load_jsonl(rejected_path)
    assert "ENTRY_AVAILABLE_AT_AFTER_DECISION_TIME" in rejected[0]["reasons"]


def test_strategy_supply_feedback_maturation_waits_for_label_window(tmp_path: Path) -> None:
    pending_path = tmp_path / "strategy_supply_pending_evidence.jsonl"
    matured_path = tmp_path / "strategy_supply_matured_evidence.jsonl"
    rejected_path = tmp_path / "strategy_supply_rejected_evidence.jsonl"
    _write_pending(pending_path, _pending_row())

    status = maturation.mature_strategy_supply_feedback(
        pending_path=pending_path,
        matured_path=matured_path,
        rejected_path=rejected_path,
        redis_client=FakeRedis({"v2:features:latest:BTCUSDT:1m": _exit_snapshot()}),
        now=datetime(2026, 6, 21, 12, 0, 30, tzinfo=timezone.utc),
        publish_to_redis=True,
    )

    assert status["matured_rows"] == 0
    assert status["pending_rows_waiting_for_label"] == 1
    assert not matured_path.exists()


def test_strategy_supply_feedback_maturation_republishes_existing_matured_rows(
    tmp_path: Path,
) -> None:
    pending_path = tmp_path / "strategy_supply_pending_evidence.jsonl"
    matured_path = tmp_path / "strategy_supply_matured_evidence.jsonl"
    rejected_path = tmp_path / "strategy_supply_rejected_evidence.jsonl"
    _write_pending(pending_path, _pending_row())
    redis = FakeRedis({"v2:features:latest:BTCUSDT:1m": _exit_snapshot()})

    first_status = maturation.mature_strategy_supply_feedback(
        pending_path=pending_path,
        matured_path=matured_path,
        rejected_path=rejected_path,
        redis_client=redis,
        now=datetime(2026, 6, 21, 12, 1, 2, tzinfo=timezone.utc),
        publish_to_redis=True,
    )
    redis.payloads[maturation.TRAINER_FEEDBACK_REDIS_KEY] = "[]"

    second_status = maturation.mature_strategy_supply_feedback(
        pending_path=pending_path,
        matured_path=matured_path,
        rejected_path=rejected_path,
        redis_client=redis,
        now=datetime(2026, 6, 21, 12, 2, 2, tzinfo=timezone.utc),
        publish_to_redis=True,
    )

    assert first_status["matured_rows"] == 1
    assert second_status["matured_rows"] == 1
    assert second_status["new_matured_rows_appended"] == 0
    assert second_status["existing_matured_trainer_feedback_rows_ready"] == 1
    assert second_status["trainer_feedback_rows_published_to_redis"] == 1
    payload = json.loads(redis.payloads[maturation.TRAINER_FEEDBACK_REDIS_KEY])
    assert payload[0]["trainer_feedback_source"] == maturation.FEEDBACK_SOURCE
    assert payload[0]["accepted_for_training"] is True
    assert payload[0]["reject_reasons"] == []
