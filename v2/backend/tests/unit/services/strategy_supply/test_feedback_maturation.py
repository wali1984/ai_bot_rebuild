from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.cli import v2_strategy_supply_feedback_maturation as feedback_cli
from v2.backend.app.services.market_state_integrity.canonical_candles import (
    canonical_from_binance_rest,
)
from v2.backend.app.services.market_state_integrity.sample_rejection import classify_training_sample
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    V2HybridTrainerDataLoader,
    _trainer_feedback_row_usable,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.safety import V2OnlyJsonIO
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import FEATURE_SPEC
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    TIMEFRAME_DURATION_MS,
)
from v2.backend.app.services.strategy_supply import feedback_maturation as maturation


class FakeRedis:
    def __init__(self, payloads: dict[str, Any] | None = None) -> None:
        self.payloads = dict(payloads or {})
        self.read_keys: list[str] = []

    def get(self, key: str) -> Any:
        self.read_keys.append(key)
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


def _canonical_exit_window(
    close: float = 101.0,
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "1m",
    label_boundary: datetime = datetime(
        2026, 6, 21, 12, 1, tzinfo=timezone.utc
    ),
) -> bytes:
    duration_ms = TIMEFRAME_DURATION_MS[timeframe]
    latest_close_ms = int(label_boundary.timestamp() * 1000) - 1
    rows: list[dict[str, Any]] = []
    for index in range(5):
        close_time = latest_close_ms - (4 - index) * duration_ms
        open_time = close_time - duration_ms + 1
        selected_close = close if index == 4 else close - (4 - index) * 0.25
        open_price = selected_close - 0.1
        volume = 1_000.0 + index
        source_row = [
            open_time,
            str(open_price),
            str(selected_close + 0.5),
            str(open_price - 0.5),
            str(selected_close),
            str(volume),
            close_time,
            str(volume * selected_close),
            100 + index,
            str(volume / 2.0),
            str((volume / 2.0) * selected_close),
            "0",
        ]
        rows.append(
            canonical_from_binance_rest(
                source_row,
                symbol=symbol,
                timeframe=timeframe,
                ingested_at=close_time + 1,
            ).to_dict()
        )
    return json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()


def _exit_redis(close: float = 101.0) -> FakeRedis:
    return FakeRedis(
        {
            "v2:market:ohlcv_closed:binance:BTCUSDT:1m": (
                _canonical_exit_window(close)
            )
        }
    )


def _write_pending(path: Path, row: dict[str, Any]) -> None:
    maturation.append_jsonl(path, row)


def test_strategy_supply_feedback_maturation_publishes_trainer_consumable_row(tmp_path: Path) -> None:
    pending_path = tmp_path / "strategy_supply_pending_evidence.jsonl"
    matured_path = tmp_path / "strategy_supply_matured_evidence.jsonl"
    rejected_path = tmp_path / "strategy_supply_rejected_evidence.jsonl"
    status_path = tmp_path / "status.json"
    _write_pending(pending_path, _pending_row())
    redis = _exit_redis()

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
        redis_client=_exit_redis(),
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
        redis_client=_exit_redis(),
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
    redis = _exit_redis()

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


def test_feedback_maturation_ignores_forged_latest_feature_snapshot(
    tmp_path: Path,
) -> None:
    pending_path = tmp_path / "strategy_supply_pending_evidence.jsonl"
    matured_path = tmp_path / "strategy_supply_matured_evidence.jsonl"
    rejected_path = tmp_path / "strategy_supply_rejected_evidence.jsonl"
    _write_pending(pending_path, _pending_row())
    redis = _exit_redis(close=101.0)
    redis.payloads["v2:features:latest:BTCUSDT:1m"] = _exit_snapshot(
        close=9_999.0
    )

    status = maturation.mature_strategy_supply_feedback(
        pending_path=pending_path,
        matured_path=matured_path,
        rejected_path=rejected_path,
        redis_client=redis,
        now=datetime(2026, 6, 21, 12, 1, 2, tzinfo=timezone.utc),
        publish_to_redis=False,
    )

    assert status["matured_rows"] == 1
    assert "v2:features:latest:BTCUSDT:1m" not in redis.read_keys
    matured = maturation.load_jsonl(matured_path)
    assert matured[0]["exit_price"] == 101.0
    assert matured[0]["exit_feature_cutoff"] == "2026-06-21T12:00:59.999Z"
    feedback = matured[0]["trainer_feedback_row"]
    assert feedback["exit_label_boundary_exact_candle_selected"] is True
    assert feedback["exit_cached_latest_feature_snapshot_consumed"] is False
    assert maturation.canonical_exit_lineage_rejection_reasons(feedback) == []
    assert (
        feedback["source_hashes"]["canonical_exit_ohlcv_exact_bytes"]
        == matured[0]["exit_source_exact_payload_sha256"]
    )
    forged_horizon = dict(feedback)
    forged_horizon["exit_label_close_time"] = "2026-06-21T12:00:00.000Z"
    assert "EXIT_LABEL_HORIZON_BOUNDARY_MISMATCH" in (
        maturation.canonical_exit_lineage_rejection_reasons(forged_horizon)
    )


def test_feedback_exit_label_requires_exact_binary_canonical_source() -> None:
    key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    decoded = _canonical_exit_window().decode()

    snapshot, reason = maturation.canonical_exit_snapshot(
        FakeRedis({key: decoded}),
        "BTCUSDT",
        "1m",
        label_close_time=datetime(2026, 6, 21, 12, 1, tzinfo=timezone.utc),
        now=datetime(2026, 6, 21, 12, 1, 2, tzinfo=timezone.utc),
    )

    assert snapshot is None
    assert reason == "EXACT_BINARY_EXIT_OHLCV_UNAVAILABLE"


def test_feedback_exit_label_does_not_substitute_a_later_candle() -> None:
    key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    later_window = _canonical_exit_window(
        label_boundary=datetime(2026, 6, 21, 12, 2, tzinfo=timezone.utc)
    )
    rows = json.loads(later_window)
    rows = [
        row
        for row in rows
        if row["candle_close_time"]
        != int(datetime(2026, 6, 21, 12, 1, tzinfo=timezone.utc).timestamp() * 1000)
        - 1
    ]
    exact_bytes = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()

    snapshot, reason = maturation.canonical_exit_snapshot(
        FakeRedis({key: exact_bytes}),
        "BTCUSDT",
        "1m",
        label_close_time=datetime(2026, 6, 21, 12, 1, tzinfo=timezone.utc),
        now=datetime(2026, 6, 21, 12, 2, 2, tzinfo=timezone.utc),
    )

    assert snapshot is None
    assert reason == "CANONICAL_EXIT_LABEL_CANDLE_UNAVAILABLE"


def test_feedback_exit_label_rejects_future_available_selected_candle() -> None:
    key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    rows = json.loads(_canonical_exit_window())
    future_available = int(
        datetime(2026, 6, 21, 12, 2, tzinfo=timezone.utc).timestamp() * 1000
    )
    rows[-1]["ingested_at"] = future_available
    rows[-1]["available_at"] = future_available
    exact_bytes = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()

    snapshot, reason = maturation.canonical_exit_snapshot(
        FakeRedis({key: exact_bytes}),
        "BTCUSDT",
        "1m",
        label_close_time=datetime(2026, 6, 21, 12, 1, tzinfo=timezone.utc),
        now=datetime(2026, 6, 21, 12, 1, 2, tzinfo=timezone.utc),
    )

    assert snapshot is None
    assert reason == "CANONICAL_EXIT_CANDLE_AVAILABLE_AFTER_MATURATION_TIME"


def test_feedback_exit_label_uses_first_completed_boundary_after_unaligned_horizon() -> None:
    key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    as_of = datetime(2026, 6, 21, 12, 2, 2, tzinfo=timezone.utc)
    requested_horizon = datetime(
        2026, 6, 21, 12, 1, 30, tzinfo=timezone.utc
    )
    exact_bytes = _canonical_exit_window(
        label_boundary=datetime(2026, 6, 21, 12, 2, tzinfo=timezone.utc)
    )

    snapshot, reason = maturation.canonical_exit_snapshot(
        FakeRedis({key: exact_bytes}),
        "BTCUSDT",
        "1m",
        label_close_time=requested_horizon,
        now=as_of,
        observation_time=as_of,
    )

    assert reason is None
    assert snapshot is not None
    assert snapshot["candle_close_boundary"] == "2026-06-21T12:02:00.000Z"
    assert maturation.exit_snapshot_rejection_reasons(
        snapshot,
        label_close_time=requested_horizon,
        now=as_of,
    ) == []


def test_forged_generic_exit_snapshot_is_noncanonical() -> None:
    reasons = maturation.exit_snapshot_rejection_reasons(
        _exit_snapshot(),
        label_close_time=datetime(2026, 6, 21, 12, 1, tzinfo=timezone.utc),
        now=datetime(2026, 6, 21, 12, 1, 2, tzinfo=timezone.utc),
    )

    assert reasons == ["NONCANONICAL_EXIT_FEATURE_SNAPSHOT"]


def test_feedback_cli_redis_client_preserves_exact_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import redis

    captured: dict[str, object] = {}

    class Client:
        pass

    def from_url(url: str, **kwargs: object) -> Client:
        captured["url"] = url
        captured.update(kwargs)
        return Client()

    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(from_url))

    client = feedback_cli._redis_client("redis://example.invalid:6379/8")

    assert isinstance(client, Client)
    assert captured["decode_responses"] is False


def test_feedback_redis_merge_quarantines_legacy_noncanonical_strategy_row() -> None:
    unrelated = {
        "trainer_feedback_source": "OTHER_FEEDBACK_SOURCE",
        "trainer_feedback_id": "other-1",
    }
    legacy = {
        "trainer_feedback_source": maturation.FEEDBACK_SOURCE,
        "trainer_feedback_id": "legacy-latest-derived",
        "trainer_consumable": True,
    }
    redis = FakeRedis(
        {maturation.TRAINER_FEEDBACK_REDIS_KEY: [unrelated, legacy]}
    )

    added, quarantined = maturation.merge_feedback_rows_into_redis(redis, [])

    assert added == 0
    assert quarantined == 1
    retained = json.loads(redis.payloads[maturation.TRAINER_FEEDBACK_REDIS_KEY])
    assert retained == [unrelated]


def test_legacy_noncanonical_matured_row_does_not_block_canonical_repair(
    tmp_path: Path,
) -> None:
    pending_path = tmp_path / "strategy_supply_pending_evidence.jsonl"
    matured_path = tmp_path / "strategy_supply_matured_evidence.jsonl"
    rejected_path = tmp_path / "strategy_supply_rejected_evidence.jsonl"
    pending = _pending_row()
    _write_pending(pending_path, pending)
    maturation.append_jsonl(
        matured_path,
        {
            **pending,
            "schema_version": "strategy_supply_matured_evidence_v1",
            "trainer_feedback_row": {
                "trainer_feedback_source": maturation.FEEDBACK_SOURCE,
                "trainer_feedback_id": "legacy-latest-derived",
                "trainer_consumable": True,
            },
        },
    )

    status = maturation.mature_strategy_supply_feedback(
        pending_path=pending_path,
        matured_path=matured_path,
        rejected_path=rejected_path,
        redis_client=_exit_redis(),
        now=datetime(2026, 6, 21, 12, 1, 2, tzinfo=timezone.utc),
        publish_to_redis=False,
    )

    assert status["existing_noncanonical_exit_rows_quarantined"] == 1
    assert status["new_matured_rows_appended"] == 1
    assert status["matured_rows"] == 1
    assert status["matured_ledger_rows_total"] == 2
    ledger = maturation.load_jsonl(matured_path)
    assert len(ledger) == 2
    assert maturation.canonical_exit_lineage_rejection_reasons(
        ledger[-1]["trainer_feedback_row"]
    ) == []
