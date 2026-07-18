from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services import all_timeframe_prediction_signal_price_target_publisher as publisher
from v2.backend.app.services.continuous_edge_guardian.pit_prediction_counter import (
    consume_durable_guardian_pit_archive,
)
from v2.backend.app.services.durable_paper_evidence_archive import (
    ArchiveIdentityConflictError,
    DurablePaperEvidenceArchive,
)
from v2.backend.tests.unit.services.test_ordinary_paper_admission import (
    _assess as assess_ordinary,
)
from v2.backend.tests.unit.services.test_ordinary_paper_admission import (
    ordinary_source,
)


class FakePipeline:
    def __init__(self, client: "FakeRedis") -> None:
        self.client = client
        self.operations: list[tuple[str, str]] = []

    def get(self, key: str) -> "FakePipeline":
        self.operations.append(("get", key))
        return self

    def ttl(self, key: str) -> "FakePipeline":
        self.operations.append(("ttl", key))
        return self

    def execute(self) -> list[object]:
        return [
            self.client.get(key) if operation == "get" else self.client.ttl(key)
            for operation, key in self.operations
        ]


class FakeRedis:
    def __init__(
        self,
        payloads: dict[str, Any],
        *,
        ttls: dict[str, int] | None = None,
    ) -> None:
        self.payloads = {
            key: json.dumps(value)
            for key, value in payloads.items()
        }
        self.lists: dict[str, list[str]] = {}
        self.ltrim_calls: list[tuple[str, int, int]] = []
        self.ttls = dict(ttls or {})

    def get(self, key: str) -> str | None:
        return self.payloads.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.payloads[key] = value
        if ex is not None:
            self.ttls[key] = int(ex)

    def ttl(self, key: str) -> int:
        if key not in self.payloads:
            return -2
        return self.ttls.get(key, -1)

    def pipeline(self, *, transaction: bool) -> FakePipeline:
        assert transaction is True
        return FakePipeline(self)

    def rpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).append(value)

    def llen(self, key: str) -> int:
        return len(self.lists.get(key, []))

    def lrange(self, key: str, start: int, stop: int) -> list[str]:
        values = self.lists.get(key, [])
        length = len(values)
        normalized_start = max(0, length + start) if start < 0 else start
        normalized_stop = length + stop if stop < 0 else stop
        normalized_stop = min(length - 1, normalized_stop)
        if normalized_start >= length or normalized_stop < normalized_start:
            return []
        return values[normalized_start : normalized_stop + 1]

    def ltrim(self, key: str, start: int, stop: int) -> None:
        self.ltrim_calls.append((key, start, stop))
        self.lists[key] = self.lrange(key, start, stop)


class FailFirstRpushRedis(FakeRedis):
    def __init__(self, payloads: dict[str, Any]) -> None:
        super().__init__(payloads)
        self.rpush_attempts = 0

    def rpush(self, key: str, value: str) -> None:
        self.rpush_attempts += 1
        if self.rpush_attempts == 1:
            raise RuntimeError("injected_transient_rpush_failure")
        super().rpush(key, value)


class _FreshAdaptiveCost:
    round_trip_cost_bps = 2.0
    is_fresh = True

    @staticmethod
    def to_payload() -> dict[str, object]:
        return {"orderbook_key": "v2:orderbook:features:binance:BTCUSDT"}


def _ordinary_derived_fixture(
    *,
    market_score: float = 79.999999,
    trust_score: float = 0.449999,
    sweep_risk: float = 0.750001,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Any]:
    source, replay = ordinary_source(
        microstructure_trust_score=trust_score,
        sweep_risk_score=sweep_risk,
        microstructure_action="SHADOW_ONLY",
    )
    assessment = assess_ordinary(
        source,
        replay,
        market_score=market_score,
        trust_score=trust_score,
        sweep_risk=sweep_risk,
        action="SHADOW_ONLY",
    )
    assert assessment.accepted is True
    prediction = dict(assessment.evidence or {})
    prediction.update(
        {
            "trainer_source": publisher.TRAINER_SOURCE_REQUIRED,
            "model_source": publisher.MODEL_SOURCE_REQUIRED,
            "expected_move_bps": 2.1,
            "market_state_integrity_score": market_score,
            "valid_for_training": False,
            "valid_for_prediction": False,
            "valid_for_risk": False,
            "valid_for_orchestrator": False,
            "valid_for_paper": False,
            "valid_for_live": False,
            "market_state_reject_reasons": ["LATENCY_ABOVE_GATE"],
        }
    )
    risk = {
        **assessment.transport_payload(),
        "prediction_id": prediction["prediction_id"],
        "risk_decision_id": f"risk_{prediction['prediction_id']}",
        "orchestrator_decision_id": f"orch_{prediction['prediction_id']}",
        "risk_action": "allow",
    }
    return prediction, replay, risk, assessment


def _ordinary_prediction_row(prediction: dict[str, Any]) -> dict[str, Any]:
    return publisher.build_prediction_row(
        symbol="BTCUSDT",
        timeframe="1m",
        prediction=prediction,
        price_payload={"last_price": 100.0},
        feature_payload=None,
        stale_seconds=10**9,
        cost_estimate=_FreshAdaptiveCost(),
    )


def test_ordinary_derived_row_bypasses_only_legacy_magnitude_cliffs() -> None:
    prediction, _replay, _risk, _assessment = _ordinary_derived_fixture()

    row = _ordinary_prediction_row(prediction)

    assert row["status"] == "PRESENT_CURRENT"
    assert row["expected_move_after_cost_bps"] == pytest.approx(0.1)
    assert row["paper_fill_gate_cost_regate"]["adaptive_edge_narrow_blocked"] is False
    assert row["paper_fill_allowed"] is True
    assert row["routes_to_orchestrator"] is True
    assert row["ordinary_paper_derived_lane_integrity_structurally_valid"] is True
    assert row["paper_quality_sizing_weight"] == prediction[
        "paper_quality_sizing_weight"
    ]

    malformed = dict(prediction)
    malformed["market_state_reject_reasons"] = ["UNCLOSED_CANDLE"]
    malformed_row = _ordinary_prediction_row(malformed)
    assert malformed_row["paper_fill_allowed"] is False
    assert "UNCLOSED_CANDLE" in malformed_row["paper_fill_gate_block_reasons"]


def test_ordinary_derived_signal_requires_exact_transport_and_current_ttls(
    tmp_path: Path,
) -> None:
    prediction, replay, risk, assessment = _ordinary_derived_fixture()
    row = _ordinary_prediction_row(prediction)
    source_key = str((assessment.evidence or {})["source_redis_key"])
    replay_key = str((assessment.evidence or {})["replay_snapshot_key"])
    redis = FakeRedis(
        {
            source_key: prediction,
            replay_key: replay,
            "v2:risk:gateway:decisions": [risk],
            "v2:risk:decisions": [],
        },
        ttls={source_key: 250, replay_key: 240},
    )
    store = publisher.V2KeyValueStore(redis)

    signal_status = publisher.build_signal_status([row], store)
    signal = signal_status["published_signals"][0]

    assert signal["paper_fill_allowed"] is True
    assert signal["ordinary_paper_derived_lane_transport_accepted"] is True
    assert signal["ordinary_paper_effective_sizing_weight"] == pytest.approx(
        assessment.effective_sizing_weight
    )
    assert signal["ordinary_paper_admission_evidence_sha256"] == (
        assessment.evidence_sha256
    )
    audit = publisher.publish_v2_keys(
        store,
        {"prediction_rows": [], "stale_threshold_seconds": 900},
        signal_status,
        guardian_archive_path=tmp_path / "ordinary-derived-guardian.sqlite3",
    )
    derived_key = publisher.signal_paper_key("BTCUSDT", "1m")
    assert derived_key in redis.payloads
    assert redis.ttl(derived_key) == 240
    assert audit["ordinary_signal_publish_suppressed"] == 0


def test_ordinary_derived_signal_fails_closed_on_tamper_expiry_and_pit() -> None:
    prediction, replay, risk, assessment = _ordinary_derived_fixture()
    source_key = str((assessment.evidence or {})["source_redis_key"])
    replay_key = str((assessment.evidence or {})["replay_snapshot_key"])
    tampered_risk = json.loads(json.dumps(risk))
    tampered_risk["ordinary_paper_admission_evidence"][
        "paper_quality_sizing_weight"
    ] *= 2.0
    store = publisher.V2KeyValueStore(
        FakeRedis(
            {
                source_key: prediction,
                replay_key: replay,
                "v2:risk:gateway:decisions": [tampered_risk],
                "v2:risk:decisions": [],
            },
            ttls={source_key: 250, replay_key: -1},
        )
    )
    signal = publisher.build_signal_status(
        [_ordinary_prediction_row(prediction)], store
    )["published_signals"][0]
    assert signal["paper_fill_allowed"] is False
    assert signal["ordinary_paper_derived_lane_transport_accepted"] is False
    assert any(
        "ordinary_paper_evidence_hash_mismatch" in reason
        or "ordinary_paper_current_replay_ttl_invalid" in reason
        for reason in signal["paper_fill_gate_block_reasons"]
    )

    future = dict(prediction)
    future["available_at"] = "2026-07-18T00:02:00Z"
    future_row = _ordinary_prediction_row(future)
    assert future_row["status"] == "PREDICTION_TEMPORAL_ORDER_INVALID"
    assert future_row["paper_fill_allowed"] is False


def test_ordinary_derived_signal_preserves_monotonic_effective_sizing() -> None:
    low_prediction, _replay, low_risk, low = _ordinary_derived_fixture(
        market_score=55.0,
        trust_score=0.2,
        sweep_risk=0.8,
    )
    high_prediction, _replay, high_risk, high = _ordinary_derived_fixture(
        market_score=95.0,
        trust_score=0.8,
        sweep_risk=0.1,
    )
    low_signal = publisher.build_signal_from_row(
        _ordinary_prediction_row(low_prediction),
        low_risk,
        ordinary_assessment=low,
    )
    high_signal = publisher.build_signal_from_row(
        _ordinary_prediction_row(high_prediction),
        high_risk,
        ordinary_assessment=high,
    )

    assert 0.0 < low_signal["ordinary_paper_effective_sizing_weight"]
    assert low_signal["ordinary_paper_effective_sizing_weight"] < high_signal[
        "ordinary_paper_effective_sizing_weight"
    ]
    assert high_signal["ordinary_paper_effective_sizing_weight"] <= high_signal[
        "publisher_paper_quality_sizing_weight"
    ]


def _consume_guardian_archive(
    archive_path: Path,
    *,
    coverage_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    consumed: list[dict[str, Any]] = []
    status: dict[str, Any] = {}
    for _ in range(10):
        rows, status = consume_durable_guardian_pit_archive(
            source_archive_path=archive_path,
            guardian_coverage_archive_path=coverage_path,
            batch_rows=100,
        )
        consumed.extend(rows)
        if status.get("archive_consumption_complete_verified") is True:
            return consumed, status
    raise AssertionError(status)


def test_runtime_paper_signal_row_missing_thesis_timeframe_is_shadow_blocked() -> None:
    store = publisher.V2KeyValueStore(
        FakeRedis(
            {
                "v2:signals:paper": [
                    {
                        "symbol": "BTCUSDT",
                        "side": "long",
                        "prediction_id": "pred_missing_tf",
                        "confidence_calibrated": 0.8,
                        "expected_move_bps": 20.0,
                        "expected_move_after_cost_bps": 15.0,
                        "paper_fill_allowed": True,
                        "paper_fill_gate_block_reasons": [],
                    }
                ],
                "v2:risk:gateway:decisions": [
                    {
                        "prediction_id": "pred_missing_tf",
                        "risk_decision_id": "risk_missing_tf",
                        "orchestrator_decision_id": "orch_missing_tf",
                    }
                ],
                "v2:paper:intents": [
                    {
                        "intent_id": "intent_missing_tf",
                        "prediction_id": "pred_missing_tf",
                        "symbol": "BTCUSDT",
                        "paper_fill_allowed": True,
                    }
                ],
                "v2:paper:ledger": {
                    "generated_at": "2026-06-22T13:00:00Z",
                    "accepted": [],
                    "shadow_observations": [],
                },
                "v2:orchestrator:decisions": {"generated_at": "2026-06-22T13:00:00Z"},
                "v2:market:prices:BTCUSDT": {"last_price": 100.0},
            }
        )
    )

    rows = publisher.build_runtime_paper_signal_rows(store)

    assert len(rows) == 1
    row = rows[0]
    assert row["timeframe"] == publisher.UNKNOWN_THESIS_TIMEFRAME
    assert row["thesis_timeframe"] == publisher.UNKNOWN_THESIS_TIMEFRAME
    assert row["timeframe_attribution_status"] == "MISSING_THESIS_TIMEFRAME"
    assert row["paper_fill_allowed"] is False
    assert row["blocked_reason"] == publisher.MISSING_THESIS_TIMEFRAME_BLOCK_REASON
    assert publisher.MISSING_THESIS_TIMEFRAME_BLOCK_REASON in row["paper_fill_gate_block_reasons"]


def test_runtime_paper_signal_row_marks_hold_zeroed_after_cost_edge() -> None:
    store = publisher.V2KeyValueStore(
        FakeRedis(
            {
                "v2:signals:paper": [
                    {
                        "symbol": "BTCUSDT",
                        "timeframe": "1m",
                        "side": "hold",
                        "prediction_id": "pred_hold_zeroed",
                        "confidence_calibrated": 0.8,
                        "expected_move_bps": -20.0,
                        "expected_move_after_cost_bps": 0.0,
                        "actual_observed_spread_entry_bps": 1.0,
                        "expected_slippage_bps": 1.0,
                        "fee_bps": 2.0,
                        "expected_funding_bps": 0.5,
                        "target_notional_usd": 100.0,
                        "paper_fill_allowed": False,
                        "paper_fill_gate_block_reasons": [
                            "NON_ACTIONABLE_EXPECTED_MOVE_OR_ACTION"
                        ],
                    }
                ],
                "v2:risk:gateway:decisions": [
                    {
                        "prediction_id": "pred_hold_zeroed",
                        "risk_decision_id": "risk_hold_zeroed",
                        "orchestrator_decision_id": "orch_hold_zeroed",
                    }
                ],
                "v2:paper:intents": [],
                "v2:paper:ledger": {
                    "generated_at": "2026-06-22T13:00:00Z",
                    "accepted": [],
                    "shadow_observations": [],
                },
                "v2:orchestrator:decisions": {"generated_at": "2026-06-22T13:00:00Z"},
                "v2:market:prices:BTCUSDT": {"last_price": 100.0},
            }
        )
    )

    rows = publisher.build_runtime_paper_signal_rows(store)

    assert len(rows) == 1
    row = rows[0]
    assert row["paper_fill_allowed"] is False
    assert row["selected_action_expected_move_bps_sign"] == "negative"
    assert row["hold_action_with_directional_expected_move_bps"] is True
    assert row["hold_action_directional_expected_move_bps"] == -20.0
    assert row["expected_move_after_cost_zeroed_by_hold_action"] is True
    assert row["expected_long_net_edge_bps"] == -24.5
    assert row["expected_short_net_edge_bps"] == 15.5
    assert row["expected_long_net_pnl_usd"] == -0.245
    assert row["expected_short_net_pnl_usd"] == 0.155
    assert row["long_expected_gross_pnl_usd"] == -0.2
    assert row["long_expected_cost_usd"] == 0.045
    assert row["long_expected_net_pnl_usd"] == -0.245
    assert row["short_expected_gross_pnl_usd"] == 0.2
    assert row["short_expected_cost_usd"] == 0.045
    assert row["short_expected_net_pnl_usd"] == 0.155
    assert row["best_side"] == "short"
    assert row["best_side_expected_net_pnl_usd"] == 0.155
    assert row["selected_action"] == "hold"
    assert row["hold_no_trade_reason"] == "MODEL_SELECTED_HOLD_DESPITE_DIRECTIONAL_EXPECTED_MOVE"
    assert row["why_best_side_rejected"] == "selected_hold_best_side_short_net_edge_15.500000bps"
    assert (
        row["paper_non_actionable_diagnostic_reason"]
        == "HOLD_ACTION_WITH_DIRECTIONAL_EXPECTED_MOVE_ZERO_AFTER_COST_EDGE"
    )


def test_publish_v2_keys_archives_then_caches_guardian_pit_without_live_mutation(
    tmp_path: Path,
) -> None:
    redis = FakeRedis({})
    store = publisher.V2KeyValueStore(redis)
    prediction_row = {
        "prediction_id": "pred-pit-1",
        "prediction_redis_key": "v2:prediction:BTCUSDT:1m",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "status": "PRESENT_CURRENT",
        "selected_action": "long",
        "decision_time": "2026-07-09T20:40:00Z",
        "feature_cutoff": "2026-07-09T20:39:59Z",
        "available_at": "2026-07-09T20:39:59Z",
        "candle_close_time": "2026-07-09T20:39:59Z",
        "candle_closed_confirmed": True,
        "generated_est": "2026-07-09T16:40:00-04:00",
        "feature_vector_hash": "hash-pit-1",
        "prediction_temporal_block_reasons": [],
    }

    audit = publisher.publish_v2_keys(
        store,
        {"prediction_rows": [prediction_row], "stale_threshold_seconds": 900},
        {"published_signals": []},
        guardian_archive_path=tmp_path / "guardian.sqlite3",
        guardian_hot_cache_max_rows=2,
        guardian_migration_batch_rows=2,
    )

    rows = redis.lists[publisher.GUARDIAN_PIT_OBSERVATION_LIST_KEY]
    assert audit["guardian_pit_observation_appends"] == 1
    assert audit["guardian_pit_observation_list_key"] == publisher.GUARDIAN_PIT_OBSERVATION_LIST_KEY
    assert audit["guardian_pit_observation_list_role"] == (
        "BOUNDED_HOT_CACHE_NOT_APPEND_ONLY_DURABLE_EVIDENCE"
    )
    archive_status = audit["guardian_pit_archive_hot_cache"]
    assert archive_status["status"] == "DURABLE_ARCHIVE_READY_REDIS_BOUNDED_HOT_CACHE"
    assert archive_status["durable_archive_total_unique_rows"] == 1
    assert archive_status["redis_hot_cache_rows_after_cycle"] == 1
    assert archive_status["redis_hot_cache_bounded"] is True
    assert archive_status["archive_write_precedes_redis_hot_append"] is True
    assert archive_status["durable_archive_integrity_verified"] is True
    assert archive_status["redis_hot_cache_trim_safe"] is False
    assert (
        "DURABLE_ARCHIVE_CONSUMER_NOT_CAUGHT_UP"
        in archive_status["redis_hot_cache_trim_gate_reasons"]
    )
    assert archive_status["counts_as_a_plus"] is False
    assert len(rows) == 1
    payload = json.loads(rows[0])
    assert payload["schema_version"] == "v2_guardian_pit_prediction_observation_append_v1"
    assert payload["prediction_id"] == "pred-pit-1"
    assert payload["decision_time"] == "2026-07-09T20:40:00Z"
    assert payload["feature_cutoff"] == "2026-07-09T20:39:59Z"
    assert payload["available_at"] == "2026-07-09T20:39:59Z"
    assert payload["counts_as_a_grade_evidence"] is False
    assert payload["counts_as_a_plus"] is False
    assert payload["places_real_order"] is False
    assert payload["routes_to_live"] is False
    assert payload["test_order_submitted"] is False


def test_guardian_legacy_list_is_fully_archived_before_hot_cache_trim(tmp_path: Path) -> None:
    redis = FakeRedis({})
    legacy_rows = []
    for index in range(3):
        legacy = {
            "schema_version": "v2_guardian_pit_prediction_observation_append_v1",
            "producer": publisher.SERVICE_ID,
            "source": "all_timeframe_prediction_signal_price_target_publisher",
            "prediction_id": f"legacy-{index}",
            "source_redis_key": f"v2:prediction:BTCUSDT:{index}m",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "selected_action": "long",
            "decision_time": f"2026-07-09T20:4{index}:00Z",
            "feature_cutoff": f"2026-07-09T20:3{index}:59Z",
            "available_at": f"2026-07-09T20:3{index}:59Z",
            "candle_close_time": f"2026-07-09T20:3{index}:59Z",
            "candle_closed_confirmed": True,
            "generated_at": f"2026-07-09T20:4{index}:00Z",
            "future_labels_used_as_features": False,
            "counts_as_a_grade_evidence": False,
            "counts_as_a_plus": False,
            "counts_as_live_ready": False,
            "places_real_order": False,
            "routes_to_live": False,
            "test_order_submitted": False,
            "leverage_mutation": False,
            "margin_mode_mutation": False,
        }
        legacy_rows.append(json.dumps(legacy, sort_keys=True))
    redis.lists[publisher.GUARDIAN_PIT_OBSERVATION_LIST_KEY] = legacy_rows
    store = publisher.V2KeyValueStore(redis)
    archive_path = tmp_path / "guardian.sqlite3"
    current = {
        "prediction_id": "current-1",
        "prediction_redis_key": "v2:prediction:ETHUSDT:1m",
        "symbol": "ETHUSDT",
        "timeframe": "1m",
        "status": "PRESENT_CURRENT",
        "selected_action": "short",
        "decision_time": "2026-07-09T20:50:00Z",
        "feature_cutoff": "2026-07-09T20:49:59Z",
        "available_at": "2026-07-09T20:49:59Z",
        "candle_close_time": "2026-07-09T20:49:59Z",
        "candle_closed_confirmed": True,
        "generated_est": "2026-07-09T16:50:00-04:00",
        "prediction_temporal_block_reasons": [],
    }

    first = publisher.append_guardian_pit_observations(
        store,
        [current],
        archive_path=archive_path,
        hot_cache_max_rows=2,
        migration_batch_rows=2,
    )

    assert first["status"] == "LEGACY_REDIS_MIGRATION_IN_PROGRESS_NO_TRIM_ALLOWED"
    assert first["legacy_migration_cursor_after"] == 2
    assert first["legacy_migration_complete"] is False
    assert first["durable_archive_total_unique_rows"] == 3
    assert first["durable_archive_total_observations"] == 2
    assert first["redis_hot_cache_rows_after_cycle"] == 4
    assert first["redis_hot_cache_bounded"] is False
    assert redis.ltrim_calls == []

    second = publisher.append_guardian_pit_observations(
        store,
        [current],
        archive_path=archive_path,
        hot_cache_max_rows=2,
        migration_batch_rows=2,
    )

    assert (
        second["status"]
        == "DURABLE_ARCHIVE_CONSUMER_CATCHUP_REQUIRED_NO_TRIM_ALLOWED"
    )
    assert second["legacy_migration_cursor_after"] == 4
    assert second["legacy_migration_complete"] is True
    assert second["durable_archive_total_unique_rows"] == 4
    assert second["durable_archive_total_observations"] == 5
    assert second["redis_hot_cache_rows_after_cycle"] == 4
    assert second["redis_hot_cache_rows_evicted_after_archive"] == 0
    assert second["redis_hot_cache_bounded"] is False
    assert second["redis_hot_cache_trim_safe"] is False
    assert redis.ltrim_calls == []

    consumed, consumer_status = _consume_guardian_archive(
        archive_path,
        coverage_path=tmp_path / "guardian-coverage.jsonl",
    )
    assert len(consumed) == 4
    assert consumer_status["archive_consumption_complete_verified"] is True

    third = publisher.append_guardian_pit_observations(
        store,
        [current],
        archive_path=archive_path,
        hot_cache_max_rows=2,
        migration_batch_rows=2,
    )

    assert third["status"] == "DURABLE_ARCHIVE_READY_REDIS_BOUNDED_HOT_CACHE"
    assert third["redis_hot_cache_trim_safe"] is True
    assert third["redis_hot_cache_rows_after_cycle"] == 2
    assert third["redis_hot_cache_rows_evicted_after_archive"] == 2
    assert third["redis_hot_cache_bounded"] is True
    assert redis.ltrim_calls == [
        (publisher.GUARDIAN_PIT_OBSERVATION_LIST_KEY, -2, -1)
    ]
    retained = [
        json.loads(raw)["prediction_id"]
        for raw in redis.lists[publisher.GUARDIAN_PIT_OBSERVATION_LIST_KEY]
    ]
    assert retained == ["legacy-2", "current-1"]


def test_guardian_invalid_legacy_row_is_quarantined_then_trimmed_only_after_consumption(
    tmp_path: Path,
) -> None:
    redis = FakeRedis({})
    redis.lists[publisher.GUARDIAN_PIT_OBSERVATION_LIST_KEY] = [
        json.dumps({"prediction_id": "invalid", "non_finite": float("inf")})
    ]
    store = publisher.V2KeyValueStore(redis)
    current = {
        "prediction_id": "current-1",
        "prediction_redis_key": "v2:prediction:BTCUSDT:1m",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "status": "PRESENT_CURRENT",
        "selected_action": "long",
        "decision_time": "2026-07-09T20:50:00Z",
        "feature_cutoff": "2026-07-09T20:49:59Z",
        "available_at": "2026-07-09T20:49:59Z",
        "candle_close_time": "2026-07-09T20:49:59Z",
        "candle_closed_confirmed": True,
        "generated_est": "2026-07-09T16:50:00-04:00",
        "prediction_temporal_block_reasons": [],
    }

    archive_path = tmp_path / "guardian.sqlite3"
    audit = publisher.publish_v2_keys(
        store,
        {"prediction_rows": [current], "stale_threshold_seconds": 900},
        {"published_signals": []},
        guardian_archive_path=archive_path,
        guardian_hot_cache_max_rows=1,
        guardian_migration_batch_rows=10,
    )

    contract = audit["guardian_pit_archive_hot_cache"]
    assert (
        contract["status"]
        == "DURABLE_ARCHIVE_CONSUMER_CATCHUP_REQUIRED_NO_TRIM_ALLOWED"
    )
    assert contract["new_hot_cache_appends"] == 1
    assert contract["redis_hot_cache_bounded"] is False
    assert len(redis.lists[publisher.GUARDIAN_PIT_OBSERVATION_LIST_KEY]) == 2
    assert redis.ltrim_calls == []

    archive = DurablePaperEvidenceArchive(
        archive_path,
        stream_id=publisher.GUARDIAN_PIT_ARCHIVE_STREAM_ID,
    )
    archived_rows = archive.latest_rows(10)
    quarantined = [
        row for row in archived_rows if row.get("valid_guardian_observation") is False
    ]
    assert len(quarantined) == 1
    assert quarantined[0]["schema_version"] == (
        "guardian_pit_invalid_legacy_redis_record_archive_v1"
    )
    assert quarantined[0]["raw_redis_value_utf8"] is not None
    assert "Infinity" in quarantined[0]["raw_redis_value_utf8"]
    assert quarantined[0]["counts_as_a_grade_evidence"] is False
    assert quarantined[0]["counts_as_a_plus"] is False

    consumed, consumer_status = _consume_guardian_archive(
        archive_path,
        coverage_path=tmp_path / "quarantine-coverage.jsonl",
    )
    assert [row["prediction_id"] for row in consumed] == ["current-1"]
    assert consumer_status["archive_consumption_complete_verified"] is True
    assert consumer_status["quarantined_unique_rows"] == 1

    compacted = publisher.append_guardian_pit_observations(
        store,
        [],
        archive_path=archive_path,
        hot_cache_max_rows=1,
        migration_batch_rows=10,
    )
    assert compacted["redis_hot_cache_trim_safe"] is True
    assert compacted["redis_hot_cache_rows_after_cycle"] == 1
    assert redis.ltrim_calls == [
        (publisher.GUARDIAN_PIT_OBSERVATION_LIST_KEY, -1, -1)
    ]
    retained = redis.lists[publisher.GUARDIAN_PIT_OBSERVATION_LIST_KEY]
    assert json.loads(retained[0])["prediction_id"] == "current-1"


def test_guardian_archived_row_retries_hot_cache_delivery_after_rpush_failure(
    tmp_path: Path,
) -> None:
    redis = FailFirstRpushRedis({})
    store = publisher.V2KeyValueStore(redis)
    archive_path = tmp_path / "guardian.sqlite3"
    current = {
        "prediction_id": "retry-current-1",
        "prediction_redis_key": "v2:prediction:BTCUSDT:1m",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "status": "PRESENT_CURRENT",
        "selected_action": "long",
        "decision_time": "2026-07-09T20:50:00Z",
        "feature_cutoff": "2026-07-09T20:49:59Z",
        "available_at": "2026-07-09T20:49:59Z",
        "candle_close_time": "2026-07-09T20:49:59Z",
        "candle_closed_confirmed": True,
        "generated_est": "2026-07-09T16:50:00-04:00",
        "prediction_temporal_block_reasons": [],
    }

    first = publisher.append_guardian_pit_observations(
        store,
        [current],
        archive_path=archive_path,
        hot_cache_max_rows=2,
        migration_batch_rows=2,
    )

    assert first["durable_archive_total_unique_rows"] == 1
    assert first["new_hot_cache_appends"] == 0
    assert first["hot_cache_delivery_failures"] == 1
    assert first["hot_cache_pending_deliveries_after_cycle"] == 1
    assert first["redis_hot_cache_bounded"] is False
    assert first["status"] == "DURABLE_ARCHIVE_OR_HOT_CACHE_FAIL_CLOSED"
    assert redis.lists.get(publisher.GUARDIAN_PIT_OBSERVATION_LIST_KEY, []) == []

    second = publisher.append_guardian_pit_observations(
        store,
        [current],
        archive_path=archive_path,
        hot_cache_max_rows=2,
        migration_batch_rows=2,
    )

    assert second["new_archive_inserted_unique_rows"] == 0
    assert second["new_archive_duplicate_rows"] == 1
    assert second["new_hot_cache_appends"] == 1
    assert second["hot_cache_delivery_acknowledged"] == 1
    assert second["hot_cache_pending_deliveries_after_cycle"] == 0
    assert second["redis_hot_cache_bounded"] is True
    assert second["status"] == "DURABLE_ARCHIVE_READY_REDIS_BOUNDED_HOT_CACHE"
    retained = redis.lists[publisher.GUARDIAN_PIT_OBSERVATION_LIST_KEY]
    assert len(retained) == 1
    assert json.loads(retained[0])["prediction_id"] == "retry-current-1"


def test_guardian_payload_rejects_naive_or_misordered_evidence_clocks() -> None:
    row = {
        "prediction_id": "clock-current-1",
        "prediction_redis_key": "v2:prediction:BTCUSDT:1m",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "status": "PRESENT_CURRENT",
        "selected_action": "long",
        "decision_time": "2026-07-09T20:50:00Z",
        "feature_cutoff": "2026-07-09T20:49:59Z",
        "available_at": "2026-07-09T20:49:59Z",
        "candle_close_time": "2026-07-09T20:49:59Z",
        "candle_closed_confirmed": True,
        "generated_est": "2026-07-09T16:50:00-04:00",
        "prediction_temporal_block_reasons": [],
    }
    assert publisher.guardian_pit_observation_payload(row) is not None

    for clock in (
        "decision_time",
        "feature_cutoff",
        "available_at",
        "candle_close_time",
        "generated_est",
    ):
        naive = dict(row)
        naive[clock] = str(naive[clock]).replace("Z", "").replace("-04:00", "")
        assert publisher.guardian_pit_observation_payload(naive) is None

    available_before_feature = dict(row, available_at="2026-07-09T20:49:58Z")
    assert publisher.guardian_pit_observation_payload(available_before_feature) is None
    unfinished_at_decision = dict(
        row,
        feature_cutoff="2026-07-09T20:50:00Z",
        candle_close_time="2026-07-09T20:50:00Z",
    )
    assert publisher.guardian_pit_observation_payload(unfinished_at_decision) is None


def test_guardian_migration_identity_conflict_rolls_back_records_counts_and_cursor(
    tmp_path: Path,
) -> None:
    archive = DurablePaperEvidenceArchive(
        tmp_path / "guardian.sqlite3",
        stream_id=publisher.GUARDIAN_PIT_ARCHIVE_STREAM_ID,
    )
    original = {
        "schema_version": "v2_guardian_pit_prediction_observation_append_v1",
        "producer": publisher.SERVICE_ID,
        "source": "all_timeframe_prediction_signal_price_target_publisher",
        "prediction_id": "immutable-1",
        "source_redis_key": "v2:prediction:BTCUSDT:1m",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "selected_action": "long",
        "decision_time": "2026-07-09T20:50:00Z",
        "feature_cutoff": "2026-07-09T20:49:59Z",
        "available_at": "2026-07-09T20:49:59Z",
        "candle_close_time": "2026-07-09T20:49:59Z",
        "candle_closed_confirmed": True,
        "generated_at": "2026-07-09T20:50:00Z",
        "future_labels_used_as_features": False,
        "counts_as_a_grade_evidence": False,
        "counts_as_a_plus": False,
        "counts_as_live_ready": False,
        "places_real_order": False,
        "routes_to_live": False,
        "test_order_submitted": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
    }
    original_candidate = publisher._guardian_pit_archive_candidate(original)
    archive.append_unique([original_candidate])
    rewritten = dict(original, selected_action="short")
    rewritten_candidate = publisher._guardian_pit_archive_candidate(rewritten)
    second = dict(
        original,
        prediction_id="immutable-2",
        source_redis_key="v2:prediction:ETHUSDT:1m",
        symbol="ETHUSDT",
    )
    second_candidate = publisher._guardian_pit_archive_candidate(second)
    assert rewritten_candidate.record_id == original_candidate.record_id

    with pytest.raises(ArchiveIdentityConflictError):
        archive.append_migration_batch(
            [rewritten_candidate, second_candidate],
            expected_cursor=0,
            new_cursor=2,
            observed_redis_length=2,
        )

    integrity = archive.verify_integrity()
    assert integrity["total_unique_rows"] == 1
    assert integrity["total_occurrences"] == 0
    assert archive.metadata("redis_legacy_migration_cursor", "0") == "0"
    assert archive.metadata("redis_legacy_migration_complete", "false") == "false"
    assert archive.latest_rows(10)[0]["selected_action"] == "long"


def test_guardian_invalid_utf8_legacy_row_preserves_exact_bytes_in_quarantine() -> None:
    raw = b"\xff\xfeguardian\x00"
    candidate = publisher._guardian_legacy_archive_candidate(raw, list_index=7)
    payload = dict(candidate.payload)
    assert payload["valid_guardian_observation"] is False
    assert payload["raw_redis_value_utf8"] is None
    assert payload["raw_redis_value_base64"] == "//5ndWFyZGlhbgA="
    assert len(payload["raw_redis_value_sha256"]) == 64
    assert payload["legacy_list_index"] == 7


def test_guardian_archive_integrity_failure_blocks_trim_after_consumer_catchup(
    tmp_path: Path,
) -> None:
    redis = FakeRedis({})
    store = publisher.V2KeyValueStore(redis)
    archive_path = tmp_path / "guardian.sqlite3"
    first = {
        "prediction_id": "tamper-1",
        "prediction_redis_key": "v2:prediction:BTCUSDT:1m",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "status": "PRESENT_CURRENT",
        "selected_action": "long",
        "decision_time": "2026-07-09T20:50:00Z",
        "feature_cutoff": "2026-07-09T20:49:59Z",
        "available_at": "2026-07-09T20:49:59Z",
        "candle_close_time": "2026-07-09T20:49:59Z",
        "candle_closed_confirmed": True,
        "generated_est": "2026-07-09T16:50:00-04:00",
        "prediction_temporal_block_reasons": [],
    }
    second = dict(
        first,
        prediction_id="tamper-2",
        prediction_redis_key="v2:prediction:ETHUSDT:1m",
        symbol="ETHUSDT",
        selected_action="short",
    )
    before = publisher.append_guardian_pit_observations(
        store,
        [first, second],
        archive_path=archive_path,
        hot_cache_max_rows=1,
        migration_batch_rows=10,
    )
    assert before["redis_hot_cache_rows_after_cycle"] == 2
    assert before["redis_hot_cache_trim_performed"] is False
    _consume_guardian_archive(
        archive_path,
        coverage_path=tmp_path / "tamper-coverage.jsonl",
    )

    with sqlite3.connect(str(archive_path)) as connection:
        connection.execute(
            """
            UPDATE evidence_records
            SET payload_json = '{"tampered":true}'
            WHERE stream_id = ? AND sequence = 1
            """,
            (publisher.GUARDIAN_PIT_ARCHIVE_STREAM_ID,),
        )
        connection.commit()

    after = publisher.append_guardian_pit_observations(
        store,
        [],
        archive_path=archive_path,
        hot_cache_max_rows=1,
        migration_batch_rows=10,
    )
    assert after["status"] == "DURABLE_ARCHIVE_OR_HOT_CACHE_FAIL_CLOSED"
    assert after["durable_archive_integrity_verified"] is False
    assert after["redis_hot_cache_trim_performed"] is False
    assert len(redis.lists[publisher.GUARDIAN_PIT_OBSERVATION_LIST_KEY]) == 2
    assert redis.ltrim_calls == []


def _runtime_lane_payloads(lane_row: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payloads: dict[str, Any] = {
        "v2:signals:paper": [lane_row],
        "v2:risk:gateway:decisions": [],
        "v2:paper:intents": [],
        "v2:paper:ledger": {
            "generated_at": "2026-06-22T13:00:00Z",
            "accepted": [],
            "shadow_observations": [],
        },
        "v2:orchestrator:decisions": {"generated_at": "2026-06-22T13:00:00Z"},
        "v2:market:prices:AXSUSDT": {"last_price": 1.0},
    }
    payloads.update(extra or {})
    return payloads


def test_runtime_paper_row_adopts_prediction_coverage_on_prediction_id_match() -> None:
    # Zero-coverage-symbols incident (2026-07-16): the paper lane never carries
    # data_coverage_percent, so runtime rows clobbered per-symbol signal keys
    # with null coverage while the trainer tensor was healthy.
    store = publisher.V2KeyValueStore(
        FakeRedis(
            _runtime_lane_payloads(
                {
                    "symbol": "AXSUSDT",
                    "timeframe": "1h",
                    "side": "long",
                    "prediction_id": "pred_cov_match",
                    "confidence_calibrated": 0.8,
                },
                {
                    "v2:prediction:AXSUSDT:1h": {
                        "prediction_id": "pred_cov_match",
                        "feature_snapshot_id": "snap_a",
                        "data_coverage_percent": 73.5,
                        "missing_feature_count": 2,
                        "stale_feature_count": 1,
                        "generated_utc": "1970-01-01T00:00:00Z",
                    },
                },
            )
        )
    )

    rows = publisher.build_runtime_paper_signal_rows(store)

    assert len(rows) == 1
    row = rows[0]
    assert row["data_coverage_percent"] == 73.5
    assert row["data_coverage_source"].startswith("V2_PREDICTION_ROW_PREDICTION_ID_MATCH")
    assert row["data_coverage_prediction_id"] == "pred_cov_match"
    assert row["missing_feature_count"] == 2
    assert row["stale_feature_count"] == 1


def test_runtime_paper_row_adopts_prediction_coverage_on_snapshot_id_match() -> None:
    # Prediction ids rotate every trainer cycle; the feature snapshot id ties
    # the lane row to the identical tensor inputs even after id rotation.
    store = publisher.V2KeyValueStore(
        FakeRedis(
            _runtime_lane_payloads(
                {
                    "symbol": "AXSUSDT",
                    "timeframe": "1h",
                    "side": "long",
                    "prediction_id": "pred_old_rotated",
                    "feature_snapshot_id": "snap_shared",
                    "confidence_calibrated": 0.8,
                },
                {
                    "v2:prediction:AXSUSDT:1h": {
                        "prediction_id": "pred_new_current",
                        "feature_snapshot_id": "snap_shared",
                        "data_coverage_percent": 74.25,
                        "generated_utc": "1970-01-01T00:00:00Z",
                    },
                },
            )
        )
    )

    rows = publisher.build_runtime_paper_signal_rows(store)

    assert len(rows) == 1
    row = rows[0]
    assert row["data_coverage_percent"] == 74.25
    assert row["data_coverage_source"].startswith("V2_PREDICTION_ROW_FEATURE_SNAPSHOT_ID_MATCH")


def test_runtime_paper_row_leaves_coverage_null_when_no_lineage_match_and_stale() -> None:
    # No id match + stale prediction row: adopting coverage would echo stale
    # evidence, so the field stays honest-null with a provenance reason.
    store = publisher.V2KeyValueStore(
        FakeRedis(
            _runtime_lane_payloads(
                {
                    "symbol": "AXSUSDT",
                    "timeframe": "1h",
                    "side": "long",
                    "prediction_id": "pred_old_rotated",
                    "feature_snapshot_id": "snap_old",
                    "confidence_calibrated": 0.8,
                },
                {
                    "v2:prediction:AXSUSDT:1h": {
                        "prediction_id": "pred_new_current",
                        "feature_snapshot_id": "snap_new",
                        "data_coverage_percent": 74.25,
                        "generated_utc": "1970-01-01T00:00:00Z",
                    },
                },
            )
        )
    )

    rows = publisher.build_runtime_paper_signal_rows(store)

    assert len(rows) == 1
    row = rows[0]
    assert row["data_coverage_percent"] is None
    assert row["data_coverage_source"] == "COVERAGE_UNAVAILABLE_STALE_PREDICTION_ROW_NO_LINEAGE_MATCH"


def test_runtime_paper_row_keeps_own_numeric_coverage() -> None:
    store = publisher.V2KeyValueStore(
        FakeRedis(
            _runtime_lane_payloads(
                {
                    "symbol": "AXSUSDT",
                    "timeframe": "1h",
                    "side": "long",
                    "prediction_id": "pred_self",
                    "data_coverage_percent": 55.5,
                    "confidence_calibrated": 0.8,
                },
                {
                    "v2:prediction:AXSUSDT:1h": {
                        "prediction_id": "pred_self",
                        "data_coverage_percent": 99.9,
                        "generated_utc": "1970-01-01T00:00:00Z",
                    },
                },
            )
        )
    )

    rows = publisher.build_runtime_paper_signal_rows(store)

    assert len(rows) == 1
    row = rows[0]
    assert row["data_coverage_percent"] == 55.5
    assert row["data_coverage_source"] == "RUNTIME_PAPER_SIGNAL_FIELD"


def test_runtime_paper_row_fresh_symbol_tf_fallback_is_labelled() -> None:
    import datetime as _dt

    fresh_ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    store = publisher.V2KeyValueStore(
        FakeRedis(
            _runtime_lane_payloads(
                {
                    "symbol": "AXSUSDT",
                    "timeframe": "1h",
                    "side": "long",
                    "prediction_id": "pred_old_rotated",
                    "feature_snapshot_id": "snap_old",
                    "confidence_calibrated": 0.8,
                },
                {
                    "v2:prediction:AXSUSDT:1h": {
                        "prediction_id": "pred_new_current",
                        "feature_snapshot_id": "snap_new",
                        "data_coverage_percent": 71.0,
                        "generated_utc": fresh_ts,
                    },
                },
            )
        )
    )

    rows = publisher.build_runtime_paper_signal_rows(store)

    assert len(rows) == 1
    row = rows[0]
    assert row["data_coverage_percent"] == 71.0
    assert row["data_coverage_source"].startswith("V2_PREDICTION_ROW_CURRENT_SYMBOL_TF_FALLBACK")
    assert row["data_coverage_prediction_id"] == "pred_new_current"
