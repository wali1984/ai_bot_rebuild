from __future__ import annotations

import json

from v2.backend.app.services.continuous_edge_guardian.pit_prediction_counter import (
    REDIS_APPEND_ONLY_OBSERVATION_KEY,
    blocker_projection,
    collect_append_only_prediction_rows,
    collect_prediction_rows,
    coverage_status,
    dedupe_records,
    dedupe_new_records,
    update_holdout_manifest,
)
from tools import guardian_pit_prediction_counter as pit_counter_cli


class FakeRedis:
    def __init__(self, payloads: dict[str, dict]) -> None:
        self.payloads = payloads
        self.lists: dict[str, list[str]] = {}

    def get(self, key: str) -> str | None:
        payload = self.payloads.get(key)
        if payload is None:
            return None
        return json.dumps(payload)

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        rows = self.lists.get(key, [])
        if start < 0:
            start = max(0, len(rows) + start)
        if end < 0:
            end = len(rows) + end
        return rows[start : end + 1]


def _prediction(**overrides):
    row = {
        "prediction_id": "pred_1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "selected_action": "hold",
        "feature_cutoff": "2026-07-09T18:44:59.999Z",
        "available_at": "2026-07-09T18:45:20.000Z",
        "decision_time": "2026-07-09T18:48:10.000Z",
        "generated_at": "2026-07-09T18:48:10.000Z",
        "future_labels_used_as_features": False,
    }
    row.update(overrides)
    return row


def test_collect_prediction_rows_counts_only_pit_valid_predictions() -> None:
    client = FakeRedis({"v2:prediction:BTCUSDT:1m": _prediction()})

    valid, rejected = collect_prediction_rows(client, symbols=["BTCUSDT"], timeframes=("1m",))

    assert rejected == []
    assert len(valid) == 1
    assert valid[0]["selected_policy_action"] == "NO_TRADE"
    assert valid[0]["feature_cutoff_before_or_at_decision_time"] is True
    assert valid[0]["counts_as_a_grade_evidence"] is False
    assert valid[0]["counts_as_a_plus"] is False


def test_collect_prediction_rows_rejects_future_leaking_predictions() -> None:
    client = FakeRedis(
        {
            "v2:prediction:BTCUSDT:1m": _prediction(
                feature_cutoff="2026-07-09T18:50:00.000Z",
                future_labels_used_as_features=True,
            )
        }
    )

    valid, rejected = collect_prediction_rows(client, symbols=["BTCUSDT"], timeframes=("1m",))

    assert valid == []
    reasons = set(rejected[0]["reasons"])
    assert "FEATURE_CUTOFF_AFTER_DECISION_TIME" in reasons
    assert "FUTURE_LABELS_USED_AS_FEATURES" in reasons


def test_coverage_status_dedupes_and_projects_remaining_predictions(tmp_path) -> None:
    client = FakeRedis(
        {
            "v2:prediction:BTCUSDT:1m": _prediction(),
            "v2:prediction:ETHUSDT:1m": _prediction(prediction_id="pred_2", symbol="ETHUSDT", selected_action="long"),
        }
    )
    valid, rejected = collect_prediction_rows(client, symbols=["BTCUSDT", "ETHUSDT"], timeframes=("1m",))
    new_rows = dedupe_new_records([], valid)
    status = coverage_status(
        archive_rows=new_rows,
        current_valid_rows=valid,
        rejected_rows=rejected,
        new_rows_appended=len(new_rows),
        generated_utc="2026-07-09T18:50:00.000Z",
    )
    projection = blocker_projection(status, generated_utc="2026-07-09T18:50:00.000Z")

    assert status["point_in_time_valid_prediction_count"] == 2
    assert status["selected_policy_action_counts"]["NO_TRADE"] == 1
    assert status["selected_policy_action_counts"]["LONG"] == 1
    assert status["counts_as_a_grade_evidence"] is False
    assert projection["exact_blocker"] == "INSUFFICIENT_UNTOUCHED_HOLDOUT_PIT_VALID_PREDICTIONS"

    manifest_path = tmp_path / "out_of_sample_holdout_reverify_rows.jsonl.manifest.json"
    manifest = update_holdout_manifest(manifest_path, status, generated_utc="2026-07-09T18:50:00.000Z")
    assert manifest["holdout_prediction_coverage_status"]["point_in_time_valid_prediction_count"] == 2
    assert manifest["counts_as_a_grade_evidence"] is False


def test_cli_default_symbols_unions_positive_summary_with_runtime_universe(monkeypatch) -> None:
    class SummaryRedis:
        def get(self, key: str) -> str | None:
            if key == "v2:strategy_supply:latest_positive_summary":
                return json.dumps({"positive_symbols": ["BTCUSDT", "ETHUSDT"]})
            return None

    from v2.backend.app.services import v2_symbol_runtime_universe

    monkeypatch.setattr(
        v2_symbol_runtime_universe,
        "resolve_symbols",
        lambda: ["ETHUSDT", "NEARUSDT", "PAXGUSDT"],
    )

    assert pit_counter_cli._default_symbols(SummaryRedis()) == [
        "BTCUSDT",
        "ETHUSDT",
        "NEARUSDT",
        "PAXGUSDT",
    ]


def test_append_only_prediction_rows_are_collected_and_deduped_with_latest_keys() -> None:
    client = FakeRedis({"v2:prediction:BTCUSDT:1m": _prediction()})
    client.lists[REDIS_APPEND_ONLY_OBSERVATION_KEY] = [
        json.dumps(
            {
                "prediction_id": "pred_1",
                "source_redis_key": "v2:prediction:BTCUSDT:1m",
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "selected_action": "hold",
                "feature_cutoff": "2026-07-09T18:44:59.999Z",
                "available_at": "2026-07-09T18:45:20.000Z",
                "decision_time": "2026-07-09T18:48:10.000Z",
                "generated_at": "2026-07-09T18:48:10.000Z",
                "future_labels_used_as_features": False,
                "counts_as_a_grade_evidence": False,
                "counts_as_a_plus": False,
            }
        ),
        json.dumps(
            {
                "prediction_id": "pred_3",
                "source_redis_key": "v2:prediction:ETHUSDT:1m",
                "symbol": "ETHUSDT",
                "timeframe": "1m",
                "selected_action": "short",
                "feature_cutoff": "2026-07-09T18:44:59.999Z",
                "available_at": "2026-07-09T18:45:20.000Z",
                "decision_time": "2026-07-09T18:48:10.000Z",
                "generated_at": "2026-07-09T18:48:10.000Z",
                "future_labels_used_as_features": False,
                "counts_as_a_grade_evidence": False,
                "counts_as_a_plus": False,
            }
        ),
    ]

    latest, latest_rejected = collect_prediction_rows(client, symbols=["BTCUSDT"], timeframes=("1m",))
    appended, append_rejected = collect_append_only_prediction_rows(client, timeframes=("1m",))
    combined = dedupe_records([*latest, *appended])

    assert latest_rejected == []
    assert append_rejected == []
    assert len(latest) == 1
    assert len(appended) == 2
    assert len(combined) == 2
    assert {row["prediction_id"] for row in combined} == {"pred_1", "pred_3"}
    assert all(row["counts_as_a_grade_evidence"] is False for row in combined)
    assert all(row["counts_as_a_plus"] is False for row in combined)
