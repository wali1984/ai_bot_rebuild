from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from v2.backend.app.cli import v2_ingestors_status_publisher as publisher


def test_default_output_and_evidence_paths_are_repo_rooted(monkeypatch, tmp_path: Path) -> None:
    """The systemd unit may start outside the repository."""

    monkeypatch.chdir(tmp_path)
    expected_root = Path(publisher.__file__).resolve().parents[4]
    expected_public_root = expected_root / "v2/frontend/public"

    assert publisher.REPO_ROOT == expected_root
    assert publisher.PUBLIC_ROOT == expected_public_root
    assert publisher.DEFAULT_PAYLOAD_PATH == (
        expected_public_root
        / "operator_runtime/v2_ingestors_status/latest/v2_ingestors_status.json"
    )
    assert all(path.is_absolute() for path in publisher.PUBLIC_STATUS_PATHS.values())
    assert all(
        path.is_relative_to(expected_public_root) for path in publisher.PUBLIC_STATUS_PATHS.values()
    )


class FakePipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self.redis = redis
        self.keys: list[str] = []

    def pttl(self, key: str) -> FakePipeline:
        self.keys.append(key)
        return self

    def execute(self) -> list[int]:
        return [self.redis.pttls.get(key, -2) for key in self.keys]


class FakeRedis:
    def __init__(
        self,
        store: dict[str, Any],
        *,
        pttls: dict[str, int] | None = None,
        scan_rows: tuple[int, list[str]] = (0, []),
    ) -> None:
        self.store = store
        self.pttls = {key: 300_000 for key in store} | (pttls or {})
        self.scan_rows = scan_rows
        self.eval_calls: list[tuple[str, int]] = []
        self.scan_calls = 0

    def eval(self, _script: str, _key_count: int, key: str, maximum_bytes: int) -> list[Any]:
        self.eval_calls.append((key, maximum_bytes))
        value = self.store.get(key)
        if value is None:
            return ["none", -2, 0, None]
        raw = value if isinstance(value, str | bytes) else json.dumps(value)
        encoded = raw if isinstance(raw, bytes) else raw.encode("utf-8")
        if len(encoded) > maximum_bytes:
            return ["string", self.pttls.get(key, -1), len(encoded), None]
        return ["string", self.pttls.get(key, -1), len(encoded), raw]

    def scan(
        self,
        *,
        cursor: int,
        match: str,
        count: int,
    ) -> tuple[int, list[str]]:
        del cursor, match, count
        self.scan_calls += 1
        return self.scan_rows

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def test_ingestors_status_merges_public_provider_payload_counts(monkeypatch) -> None:
    now_text = _utc_text(datetime.now(UTC))
    redis = FakeRedis(
        {
            "v2:market:kucoin:heartbeat": {
                "worker_id": "v2_kucoin_ingestor",
                "generated_utc": now_text,
            },
            "v2:market:coinapi:ohlcv:heartbeat": {
                "worker_id": "v2_coinapi_rest_ingestor",
                "generated_utc": now_text,
            },
            "v2:market:coinapi:rest:heartbeat": {
                "worker_id": "v2_coinapi_rest_ingestor",
                "generated_utc": now_text,
            },
            "v2:market:coinapi:wsds:heartbeat": {
                "worker_id": "v2_coinapi_wsds_loop",
                "generated_utc": now_text,
            },
        }
    )
    statuses = {
        "kucoin": {
            "classification": "NATIVE_V2_PUBLIC_REST_OK",
            "generated_utc": now_text,
            "symbols_v2": ["BTCUSDT", "ETHUSDT"],
            "v2_redis_keys_written_count": 8,
        },
        "coinapi_rest": {
            "classification": "V2_COINAPI_REST_OPTIONAL_RAW_QUARANTINE_READY",
            "generated_utc": now_text,
            "symbols": ["BTCUSDT", "ETHUSDT"],
            "fetch": {"symbols_fetched": 2, "symbols_requested": 2},
            "v2_redis_keys_written_count": 9,
            "optional_source": True,
            "required_for_trainer_admission": False,
        },
        "coinapi_wsds": {
            "classification": "V2_COINAPI_WSDS_RAW_QUARANTINE_READY",
            "generated_utc": now_text,
            "symbols_count": 2,
            "stats": {"snapshots_written": 10, "microfeatures_written": 30},
            "optional_source": True,
            "required_for_trainer_admission": False,
        },
        "coinank": {
            "generated_utc": now_text,
            "symbols": ["BTCUSDT", "ETHUSDT"],
            "v2_redis_feature_input": {"symbols_with_any_input": 2},
            "v2_redis_global_keys_written_count": 11,
            "global_aggregate_result": {"n_symbols_observed": 2, "total_oi": 1000.0},
        },
    }
    monkeypatch.setattr(publisher, "_connect_redis", lambda: redis)
    monkeypatch.setattr(publisher, "_read_public_status", lambda name: statuses.get(name))

    payload = publisher.run_once()
    entries = {entry["name"]: entry for entry in payload["ingestors"]}

    assert entries["KuCoin Native Public REST"]["symbols_count"] == 2
    assert entries["KuCoin Native Public REST"]["keys_written_count"] == 8
    assert entries["CoinAPI Native REST Orderbook"]["symbols_count"] == 2
    assert entries["CoinAPI Native REST Orderbook"]["keys_written_count"] == 9
    assert entries["CoinAPI Native REST Orderbook"]["optional_source"] is True
    assert entries["CoinAPI Native REST Orderbook"]["absence_blocks_trainer"] is False
    assert entries["CoinAPI Native WSDS"]["symbols_count"] == 2
    assert entries["CoinAPI Native WSDS"]["keys_written_count"] == 30
    assert entries["CoinAPI Native WSDS"]["optional_source"] is True
    assert entries["CoinAPI Native WSDS"]["trainer_consumable"] is False
    assert entries["CoinAnk Direct Global Aggregator"]["symbols_count"] == 2
    assert entries["CoinAnk Direct Global Aggregator"]["keys_written_count"] == 11
    assert entries["CoinAnk Direct Global Aggregator"]["status"] == "V2_COINANK_GLOBAL_AGGREGATE_OK"
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["trainer_admission_authorized"] is False
    assert payload["live_decision_input_enabled"] is False
    assert payload["live_symbols"] == []


def test_stale_coinapi_artifact_and_persistent_key_do_not_become_current() -> None:
    now = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    stale = _utc_text(now - timedelta(days=1))
    heartbeat_key = "v2:market:coinapi:rest:heartbeat"
    redis = FakeRedis(
        {
            heartbeat_key: {
                "generated_utc": stale,
                "classification": "V2_COINAPI_REST_OPTIONAL_RAW_QUARANTINE_READY",
            }
        },
        pttls={heartbeat_key: -1},
    )

    entry = publisher._ingestor_entry(
        "CoinAPI Native REST Orderbook",
        "ai-bot-v2-coinapi-rest-fallback-loop.service",
        heartbeat_key,
        None,
        redis,
        evidence_payloads=[
            {
                "generated_utc": stale,
                "classification": "V2_COINAPI_REST_OPTIONAL_RAW_QUARANTINE_READY",
            }
        ],
        now=now,
    )

    assert entry["active"] is False
    assert entry["heartbeat_current"] is False
    assert entry["status_artifact_current"] is False
    assert entry["heartbeat_ttl_seconds"] == -1
    assert entry["persistent_heartbeat_is_never_current_by_presence"] is True
    assert entry["status"] == "STALE_OR_MISSING"
    assert entry["stale_evidence_ignored_count"] == 2
    assert entry["optional_source"] is True
    assert entry["absence_blocks_trainer"] is False


def test_positive_ttl_without_a_producer_clock_does_not_claim_current() -> None:
    now = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    heartbeat_key = "v2:market:coinapi:wsds:heartbeat"
    redis = FakeRedis(
        {heartbeat_key: {"classification": "V2_COINAPI_WSDS_OPTIONAL_CONNECTED_NO_DATA"}},
        pttls={heartbeat_key: 120_000},
    )

    entry = publisher._ingestor_entry(
        "CoinAPI Native WSDS",
        "ai-bot-v2-coinapi-wsds-loop.service",
        heartbeat_key,
        None,
        redis,
        now=now,
        heartbeat_max_age_seconds=180,
    )

    assert entry["active"] is False
    assert entry["heartbeat_current"] is False
    assert entry["heartbeat_ttl_seconds"] == 120
    assert entry["heartbeat_ttl_is_storage_retention_only"] is True
    assert entry["last_generated_utc"] is None


def test_finished_at_is_an_explicit_operational_heartbeat_clock() -> None:
    now = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    heartbeat_key = "v2:features:pipeline:heartbeat"
    finished_at = _utc_text(now - timedelta(seconds=5))
    redis = FakeRedis(
        {
            heartbeat_key: {
                "started_at": _utc_text(now - timedelta(seconds=30)),
                "finished_at": finished_at,
                "classification": "NATIVE_V2_SNAPSHOTS_BUILT_CONSUMERS_HELD",
            }
        }
    )

    entry = publisher._ingestor_entry(
        "Feature Pipeline (TA + Features)",
        "ai-bot-v2-feature-pipeline-native-loop.service",
        heartbeat_key,
        None,
        redis,
        requirement_class=publisher.REQUIREMENT_CORE_DATA_PLANE,
        heartbeat_max_age_seconds=300,
        now=now,
    )

    assert entry["heartbeat_current"] is True
    assert entry["status_artifact_current"] is False
    assert entry["active"] is True
    assert entry["last_generated_utc"] == finished_at


def test_source_event_clock_does_not_become_an_operational_artifact_clock() -> None:
    now = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    entry = publisher._ingestor_entry(
        "Optional source",
        "optional.service",
        "v2:optional:heartbeat",
        None,
        FakeRedis({}),
        evidence_payloads=[{"stats": {"last_message_utc": _utc_text(now)}}],
        now=now,
    )

    assert entry["heartbeat_current"] is False
    assert entry["status_artifact_current"] is False
    assert entry["active"] is False
    assert entry["last_generated_utc"] is None


def test_dynamic_discovery_uses_its_provider_safe_availability_envelope(
    monkeypatch,
) -> None:
    now = datetime.now(UTC)
    generated = _utc_text(now - timedelta(hours=6, minutes=15))
    key = "v2:symbol_universe:dynamic_discovery_status"
    redis = FakeRedis(
        {
            key: {
                "generated_utc": generated,
                "producer_interval_seconds": 21_600,
                "redis_retention_seconds": 28_800,
                "redis_retention_headroom_seconds": 7_200,
                "redis_retention_is_storage_availability_not_event_freshness": True,
            }
        },
        pttls={key: 6_000_000},
    )
    monkeypatch.setattr(publisher, "_connect_redis", lambda: redis)
    monkeypatch.setattr(publisher, "_read_public_status", lambda _name: None)

    payload = publisher.run_once()
    dynamic = next(
        row for row in payload["ingestors"] if row["name"] == "Dynamic Symbol Discovery"
    )

    assert dynamic["heartbeat_max_age_seconds"] == (
        publisher.DYNAMIC_DISCOVERY_REDIS_RETENTION_SECONDS
    )
    assert dynamic["heartbeat_current"] is True
    assert dynamic["heartbeat_ttl_is_storage_retention_only"] is True


def test_optional_provider_absence_does_not_degrade_current_core_heartbeats(
    monkeypatch,
) -> None:
    now_text = _utc_text(datetime.now(UTC))
    redis = FakeRedis(
        {
            key: {"generated_utc": now_text, "worker_id": "current-core-worker"}
            for key in (
                "v2:market:ingestor:heartbeat",
                "v2:features:pipeline:heartbeat",
                "v2:features:ta:heartbeat",
                "v2:market:ohlcv:binance:kline_wss:heartbeat",
            )
        }
    )
    monkeypatch.setattr(publisher, "_connect_redis", lambda: redis)
    monkeypatch.setattr(publisher, "_read_public_status", lambda _name: None)

    payload = publisher.run_once()
    entries = {entry["name"]: entry for entry in payload["ingestors"]}

    assert payload["core_data_plane_current"] is True
    assert payload["core_heartbeats_current"] is True
    assert payload["core_heartbeat_current_count"] == 4
    assert payload["classification"] == (
        "INGESTOR_CORE_HEARTBEATS_CURRENT_OPTIONAL_EVIDENCE_DEGRADED"
    )
    assert payload["optional_source_absence_blocks_core"] is False
    assert payload["optional_source_absence_blocks_trainer"] is False
    assert payload["trainer_admission_authorized"] is False
    assert payload["prediction_authorized"] is False
    assert entries["CoinAPI Native OHLCV"]["active"] is False
    assert entries["CoinAPI Native OHLCV"]["optional_source"] is True
    assert entries["CoinAPI Native WSDS"]["required_for_trainer_admission"] is False


def test_public_status_artifact_cannot_substitute_for_a_core_heartbeat(monkeypatch) -> None:
    now_text = _utc_text(datetime.now(UTC))
    redis = FakeRedis(
        {
            key: {"generated_utc": now_text}
            for key in (
                "v2:market:ingestor:heartbeat",
                "v2:features:pipeline:heartbeat",
                "v2:features:ta:heartbeat",
            )
        }
    )
    monkeypatch.setattr(publisher, "_connect_redis", lambda: redis)
    monkeypatch.setattr(
        publisher,
        "_read_public_status",
        lambda name: (
            {"generated_utc": now_text, "classification": "V2_BINANCE_KLINE_WSS_CONNECTED"}
            if name == "binance_kline_wss"
            else None
        ),
    )

    payload = publisher.run_once()
    binance = next(
        entry for entry in payload["ingestors"] if entry["name"] == "Binance USD-M Kline WSS"
    )

    assert binance["heartbeat_current"] is False
    assert binance["status_artifact_current"] is True
    assert payload["core_heartbeat_current_count"] == 3
    assert payload["core_heartbeats_current"] is False
    assert payload["core_data_plane_current"] is False
    assert payload["classification"] == "INGESTOR_CORE_HEARTBEATS_DEGRADED"


def test_explicit_false_core_health_dominates_a_current_heartbeat(monkeypatch) -> None:
    now_text = _utc_text(datetime.now(UTC))
    core_keys = (
        "v2:market:ingestor:heartbeat",
        "v2:features:pipeline:heartbeat",
        "v2:features:ta:heartbeat",
        "v2:market:ohlcv:binance:kline_wss:heartbeat",
    )
    store = {key: {"generated_utc": now_text} for key in core_keys}
    store["v2:market:ingestor:heartbeat"] = {
        "generated_utc": now_text,
        "classification": "BLOCKED_NO_SOURCE_DATA",
        "live_data_enabled": False,
    }
    redis = FakeRedis(store)
    monkeypatch.setattr(publisher, "_connect_redis", lambda: redis)
    monkeypatch.setattr(publisher, "_read_public_status", lambda _name: None)

    payload = publisher.run_once()
    native = next(
        entry
        for entry in payload["ingestors"]
        if entry["name"] == "Native Ingestors (Binance USDM)"
    )

    assert native["heartbeat_current"] is True
    assert native["heartbeat_healthy"] is False
    assert native["reported_data_available"] is False
    assert native["explicit_false_health_fields"] == ["live_data_enabled"]
    assert payload["core_heartbeats_current"] is True
    assert payload["core_data_plane_current_count"] == 3
    assert payload["core_data_plane_current"] is False
    assert payload["live_data_enabled"] is False
    assert payload["classification"] == "INGESTOR_CORE_HEALTH_DEGRADED"


def test_redis_unavailable_never_claims_data_or_trainer_authority(monkeypatch) -> None:
    monkeypatch.setattr(publisher, "_connect_redis", lambda: None)
    monkeypatch.setattr(publisher, "_read_public_status", lambda _name: None)

    payload = publisher.run_once()

    assert payload["classification"] == "INGESTOR_OBSERVABILITY_UNAVAILABLE"
    assert payload["redis_observation_available"] is False
    assert payload["live_data_enabled"] is False
    assert payload["trainer_orchestrator_risk_path_enabled"] is False
    assert payload["trainer_admission_authorized"] is False
    assert payload["paper_trading_authorized"] is False
    assert payload["trader_execution_enabled"] is False


def test_status_json_rejects_nonfinite_huge_duplicate_and_oversized_values() -> None:
    assert publisher._decode_status_json('{"x":1e999}') is None
    assert publisher._decode_status_json('{"x":9223372036854775808}') is None
    assert publisher._decode_status_json('{"x":1,"x":2}') is None
    assert publisher._decode_status_json('{"x":"abcd"}', maximum_bytes=4) is None


def test_status_counts_require_exact_bounded_nonnegative_integers() -> None:
    assert publisher._payload_symbols_count({"symbols_count": 1e308}) == 0
    assert publisher._payload_symbols_count({"symbols_count": "1e3"}) == 0
    assert publisher._payload_symbols_count({"symbols_count": 1.5}) == 0
    assert publisher._payload_symbols_count({"symbols_count": -1}) == 0
    assert publisher._payload_symbols_count({"symbols_count": "42"}) == 42
    assert publisher._payload_symbols_count({"symbols_count": 42.0}) == 42
    assert publisher._payload_symbols_count({"symbols_count": publisher.MAX_STATUS_COUNT + 1}) == 0


def test_bounded_redis_read_does_not_materialize_an_oversized_value() -> None:
    redis = FakeRedis({"oversized": "x" * 100})

    raw, ttl_ms = publisher._bounded_redis_string(
        redis,
        "oversized",
        maximum_bytes=10,
    )

    assert raw is None
    assert ttl_ms == 300_000
    assert redis.eval_calls == [("oversized", 10)]


def test_bounded_scan_reports_truncation_and_never_calls_ttl_freshness(
    monkeypatch,
) -> None:
    now_text = _utc_text(datetime.now(UTC))
    redis = FakeRedis(
        {
            key: {"generated_utc": now_text}
            for key in (
                "v2:market:ingestor:heartbeat",
                "v2:features:pipeline:heartbeat",
                "v2:features:ta:heartbeat",
                "v2:market:ohlcv:binance:kline_wss:heartbeat",
            )
        },
        pttls={"row-a": 10_000, "row-b": -1},
        scan_rows=(77, ["row-a", "row-b", "row-c"]),
    )
    monkeypatch.setattr(publisher, "MAX_STATUS_SCAN_KEYS", 2)
    monkeypatch.setattr(publisher, "_connect_redis", lambda: redis)
    monkeypatch.setattr(publisher, "_read_public_status", lambda _name: None)

    payload = publisher.run_once()
    row = payload["redis_freshness"]["prices"]

    assert row["observed_key_count"] == 2
    assert row["storage_ttl_positive_count"] == 1
    assert row["persistent_key_count"] == 1
    assert row["scan_complete"] is False
    assert row["scan_cursor"] == 77
    assert row["scan_iteration_count"] == 1
    assert row["scan_stop_reason"] == "KEY_LIMIT"
    assert row["source_event_freshness_inferred_from_ttl"] is False
    assert row["trainer_admission_authorized"] is False


def test_scan_work_is_bounded_even_when_no_keys_match(monkeypatch) -> None:
    class AdvancingScanRedis(FakeRedis):
        def scan(
            self,
            *,
            cursor: int,
            match: str,
            count: int,
        ) -> tuple[int, list[str]]:
            del match, count
            self.scan_calls += 1
            return cursor + 1, []

    redis = AdvancingScanRedis({})
    monkeypatch.setattr(publisher, "MAX_STATUS_SCAN_ITERATIONS", 3)
    monkeypatch.setattr(publisher, "_connect_redis", lambda: redis)
    monkeypatch.setattr(publisher, "_read_public_status", lambda _name: None)

    payload = publisher.run_once()
    rows = list(payload["redis_freshness"].values())

    assert rows
    assert redis.scan_calls == len(rows) * 3
    assert all(row["scan_iteration_count"] == 3 for row in rows)
    assert all(row["scan_stop_reason"] == "ITERATION_LIMIT" for row in rows)
    assert all(row["scan_complete"] is False for row in rows)


def test_scan_repeated_nonzero_cursor_is_stopped_as_a_cycle(monkeypatch) -> None:
    redis = FakeRedis({}, scan_rows=(7, []))
    monkeypatch.setattr(publisher, "_connect_redis", lambda: redis)
    monkeypatch.setattr(publisher, "_read_public_status", lambda _name: None)

    payload = publisher.run_once()
    rows = list(payload["redis_freshness"].values())

    assert rows
    assert redis.scan_calls == len(rows) * 2
    assert all(row["scan_iteration_count"] == 2 for row in rows)
    assert all(row["scan_stop_reason"] == "CURSOR_CYCLE" for row in rows)
    assert all(row["scan_complete"] is False for row in rows)


def test_final_scan_batch_cannot_override_key_or_row_truncation(monkeypatch) -> None:
    monkeypatch.setattr(publisher, "_read_public_status", lambda _name: None)

    key_limited = FakeRedis({}, scan_rows=(0, ["a", "b", "c"]))
    monkeypatch.setattr(publisher, "MAX_STATUS_SCAN_KEYS", 2)
    monkeypatch.setattr(publisher, "MAX_STATUS_SCAN_ROWS_INSPECTED", 100)
    monkeypatch.setattr(publisher, "_connect_redis", lambda: key_limited)
    key_payload = publisher.run_once()
    key_row = key_payload["redis_freshness"]["prices"]
    assert key_row["observed_key_count"] == 2
    assert key_row["scan_cursor"] == 0
    assert key_row["scan_stop_reason"] == "KEY_LIMIT"
    assert key_row["scan_complete"] is False

    row_limited = FakeRedis({}, scan_rows=(0, ["a", "b", "c"]))
    monkeypatch.setattr(publisher, "MAX_STATUS_SCAN_KEYS", 100)
    monkeypatch.setattr(publisher, "MAX_STATUS_SCAN_ROWS_INSPECTED", 2)
    monkeypatch.setattr(publisher, "_connect_redis", lambda: row_limited)
    row_payload = publisher.run_once()
    row = row_payload["redis_freshness"]["prices"]
    assert row["observed_key_count"] == 2
    assert row["scan_rows_inspected"] == 2
    assert row["scan_cursor"] == 0
    assert row["scan_stop_reason"] == "ROW_INSPECTION_LIMIT"
    assert row["scan_complete"] is False


def test_all_optional_public_artifacts_are_named_evidence_not_heartbeats(monkeypatch) -> None:
    now_text = _utc_text(datetime.now(UTC))
    redis = FakeRedis(
        {
            **{
                key: {"generated_utc": now_text}
                for key in (
                    "v2:market:ingestor:heartbeat",
                    "v2:features:pipeline:heartbeat",
                    "v2:features:ta:heartbeat",
                    "v2:market:ohlcv:binance:kline_wss:heartbeat",
                )
            },
            "v2:altdata:public_intel:status": {"generated_utc": now_text},
        }
    )
    public_rows = {
        name: {"generated_utc": now_text, "classification": "CURRENT_OBSERVABILITY_ARTIFACT"}
        for name in (
            "kucoin",
            "coinapi_rest",
            "coinapi_wsds",
            "coinank",
            "liquidation_wss",
            "liquidation_levels",
        )
    }
    monkeypatch.setattr(publisher, "_connect_redis", lambda: redis)
    monkeypatch.setattr(publisher, "_read_public_status", lambda name: public_rows.get(name))

    payload = publisher.run_once()

    assert payload["optional_enrichment_count"] == 9
    assert payload["optional_enrichment_current_count"] == 9
    assert payload["optional_enrichment_heartbeat_current_count"] == 1
    assert payload["classification"] == (
        "INGESTOR_CORE_HEARTBEATS_CURRENT_OPTIONAL_EVIDENCE_CURRENT"
    )
