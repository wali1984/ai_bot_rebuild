from __future__ import annotations

import json
from collections import deque
from types import SimpleNamespace

import pytest

from v2.backend.app.cli import v2_liquidation_levels_engine as mod


class FakeRedis:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = values or {}
        self.quarantine_writes: list[tuple[str, dict, int, bool]] = []
        self.expirations: list[tuple[str, int]] = []
        self.acked: list[str] = []
        self.pending: list[tuple[str, dict[str, str]]] = []
        self.claim_calls: list[dict] = []
        self.group_lag = 0
        self.pending_count = 0
        self.hset_calls: list[tuple[str, dict]] = []
        self.hdel_calls: list[tuple[str, tuple[str, ...]]] = []
        self.set_calls: list[tuple[str, str, int | None]] = []

    def get(self, key: str):
        return self.values.get(key)

    def set(self, key: str, value: str, ex: int | None = None):
        self.values[key] = value
        self.set_calls.append((key, value, ex))
        return True

    def pipeline(self):
        return self

    def hset(self, key: str, *, mapping: dict):
        self.hset_calls.append((key, dict(mapping)))
        return 1

    def hdel(self, key: str, *fields: str):
        self.hdel_calls.append((key, tuple(fields)))
        return len(fields)

    def execute(self):
        return []

    def xadd(self, key: str, fields: dict, *, maxlen: int, approximate: bool):
        self.quarantine_writes.append((key, dict(fields), maxlen, approximate))
        return "1-0"

    def expire(self, key: str, ttl: int):
        self.expirations.append((key, ttl))
        return True

    def xack(self, _stream: str, _group: str, *message_ids: str):
        self.acked.extend(str(message_id) for message_id in message_ids)
        return len(message_ids)

    def xautoclaim(
        self,
        name: str,
        group: str,
        consumer: str,
        *,
        min_idle_time: int,
        start_id: str,
        count: int,
    ):
        self.claim_calls.append({
            "name": name,
            "group": group,
            "consumer": consumer,
            "min_idle_time": min_idle_time,
            "start_id": start_id,
            "count": count,
        })
        return ("0-0", list(self.pending), [])

    def xinfo_groups(self, _stream: str):
        return [{"name": mod.GROUP_NAME, "lag": self.group_lag}]

    def xpending(self, _stream: str, _group: str):
        return {"pending": self.pending_count}


def _engine(*, redis_values: dict[str, str] | None = None):
    engine = object.__new__(mod.LevelEngine)
    engine.config = SimpleNamespace(
        max_retention_seconds=7 * 24 * 3600,
        timeframes=("1m",),
        batch_size=100,
        ttl_seconds=900,
        explicit_symbols=None,
        smoke_test=False,
        symbol_refresh_sec=60,
    )
    engine.redis = FakeRedis(redis_values)
    engine.stream_name = "v2:liquidations:events"
    engine.state = {
        "BTCUSDT": {
            tf: deque(maxlen=mod.MAX_EVENTS_PER_SYMBOL_TIMEFRAME)
            for tf in mod.DEFAULT_TIMEFRAMES
        }
    }
    engine.state_truncated = {
        "BTCUSDT": {tf: False for tf in mod.DEFAULT_TIMEFRAMES}
    }
    engine.seen_src_ids = {"BTCUSDT": set()}
    engine.seen_src_id_order = {"BTCUSDT": deque()}
    engine.liquidation_event_price_ewma = {"BTCUSDT": None}
    engine.intensity_history = {
        "BTCUSDT": {tf: deque(maxlen=720) for tf in mod.DEFAULT_TIMEFRAMES}
    }
    engine.intensity_history_last_sample_ms = {
        "BTCUSDT": {tf: 0 for tf in mod.DEFAULT_TIMEFRAMES}
    }
    engine.events_quarantined = 0
    engine.events_processed = 0
    engine.events_ignored = 0
    engine.events_deduplicated = 0
    engine.reject_reasons = {}
    engine.pending_messages_recovered = 0
    engine.pending_recovery_supported = None
    engine.capture_start_ms = 0
    engine.capture_start_ms_by_symbol = {"BTCUSDT": 0}
    engine.capture_observed_through_ms = 0
    engine.capture_caught_up = True
    engine.capture_gap_detected = False
    engine.capture_group_lag = None
    engine.capture_pending_count = None
    engine.capture_status_error = None
    engine.last_publish = {}
    engine.symbols = ("BTCUSDT",)
    engine.last_symbol_refresh = 0.0
    return engine


def _event(
    *,
    ts: int,
    price: float,
    side: str,
    notional: float = 1000.0,
) -> dict:
    return {
        "symbol": "BTCUSDT",
        "ts": ts,
        "event_time": ts,
        "ingested_at": ts + 100,
        "available_at": ts + 100,
        "source_generated_at": ts + 100,
        "feature_cutoff": ts,
        "price": price,
        "qty": notional / price,
        "notional": notional,
        "side": side,
        "src_id": f"{side}:{ts}:{price}",
    }


def test_observation_windows_are_distinct_for_default_timeframes() -> None:
    windows = [
        mod.observation_window_seconds(tf, 7 * 24 * 3600)
        for tf in mod.DEFAULT_TIMEFRAMES
    ]
    assert windows == [3600, 6000, 18000, 72000, 288000]
    assert len(windows) == len(set(windows))


def test_event_clock_rejections_do_not_rewrite_time() -> None:
    now_ms = 1_800_000_000_000
    engine = _engine()
    base = {
        "symbol": "BTCUSDT",
        "ts": str(now_ms - 1000),
        "ingest_ts": str(now_ms - 500),
        "available_at": str(now_ms - 500),
        "generated_at": str(now_ms - 500),
        "feature_cutoff": str(now_ms - 1000),
        "price": "100",
        "qty": "2",
        "notional": "200",
        "side": "LONG_LIQ",
        "source": "binance_wss_forceOrder",
        "src_id": "base-event",
    }
    parsed, reason = engine._parse_event(base, now_ms=now_ms)
    assert reason is None
    assert parsed["event_time"] == now_ms - 1000
    assert parsed["ingested_at"] == now_ms - 500

    old = dict(base, ts=str(now_ms - engine.config.max_retention_seconds * 1000 - 1))
    old["feature_cutoff"] = old["ts"]
    rejected, reason = engine._parse_event(old, now_ms=now_ms)
    assert rejected == {}
    assert reason == "event_time_too_old"

    future_ts = now_ms + mod.MAX_FUTURE_CLOCK_SKEW_MS + 1
    future = dict(
        base,
        ts=str(future_ts),
        ingest_ts=str(future_ts),
        available_at=str(future_ts),
        generated_at=str(future_ts),
        feature_cutoff=str(future_ts),
    )
    rejected, reason = engine._parse_event(future, now_ms=now_ms)
    assert rejected == {}
    assert reason == "event_time_in_future"

    missing_generated = dict(base, generated_at="0")
    rejected, reason = engine._parse_event(missing_generated, now_ms=now_ms)
    assert rejected == {}
    assert reason == "missing_clock_lineage"

    cutoff_before_event = dict(base, feature_cutoff=str(now_ms - 1001))
    rejected, reason = engine._parse_event(cutoff_before_event, now_ms=now_ms)
    assert rejected == {}
    assert reason == "feature_cutoff_before_event"

    for missing_field in ("available_at", "generated_at", "feature_cutoff"):
        missing = dict(base)
        missing.pop(missing_field)
        rejected, reason = engine._parse_event(missing, now_ms=now_ms)
        assert rejected == {}
        assert reason == "missing_clock_lineage"

    missing_source_id = dict(base)
    missing_source_id.pop("src_id")
    rejected, reason = engine._parse_event(missing_source_id, now_ms=now_ms)
    assert rejected == {}
    assert reason == "missing_source_lineage"


def test_fresh_resolver_price_precedes_separately_named_liquidation_ewma(
    monkeypatch,
) -> None:
    monkeypatch.setattr(mod, "resolve_current_price", lambda _redis, _symbol: {
        "price": 100.0,
        "source": "mark_price",
        "staleness_seconds": 1.5,
        "execution_grade": True,
        "fallback_used": False,
        "reason_if_missing": None,
    })
    engine = _engine()
    engine.liquidation_event_price_ewma["BTCUSDT"] = 91.0

    reference = engine._get_latest_price("BTCUSDT")
    assert reference["price"] == 100.0
    assert reference["source"] == "current_price_resolver:mark_price"
    assert reference["staleness_seconds"] == 1.5
    assert reference["execution_grade"] is True


def test_stale_resolver_price_is_rejected_to_explicit_ewma_fallback(
    monkeypatch,
) -> None:
    monkeypatch.setattr(mod, "resolve_current_price", lambda _redis, _symbol: {
        "price": 100.0,
        "source": "rest_ticker_24hr_fallback",
        "staleness_seconds": 300.0,
        "execution_grade": False,
        "fallback_used": True,
        "reason_if_missing": "FEED_STALE",
    })
    engine = _engine()
    engine.liquidation_event_price_ewma["BTCUSDT"] = 91.0
    reference = engine._get_latest_price("BTCUSDT")
    assert reference["price"] == 91.0
    assert reference["source"] == "liquidation_event_price_ewma_fallback"
    assert reference["execution_grade"] is False
    assert reference["resolver_reason"] == "FEED_STALE"


def test_bucket_prices_are_centers_not_floor_edges() -> None:
    engine = _engine()
    assert engine._extract_levels({10: 5.0}, 2.0) == [
        {"price": 21.0, "strength": 5.0}
    ]


def test_mapping_enforces_direction_and_preserves_lineage_semantics(
    monkeypatch,
) -> None:
    now_ms = 1_800_000_000_000
    monkeypatch.setattr(mod, "resolve_current_price", lambda _redis, _symbol: {
        "price": 100.0, "source": "mark_price", "staleness_seconds": 1.0,
        "execution_grade": True, "fallback_used": False,
        "reason_if_missing": None,
    })
    engine = _engine()
    events = [
        _event(ts=now_ms - 3600_000, price=90.0, side="LONG_LIQ"),
        _event(ts=now_ms - 3000, price=110.0, side="LONG_LIQ"),
        _event(ts=now_ms - 2000, price=110.0, side="SHORT_LIQ"),
        _event(ts=now_ms - 1000, price=90.0, side="SHORT_LIQ"),
    ]
    engine.state["BTCUSDT"]["1m"].extend(events)
    for event in events:
        engine._update_liquidation_event_price_ewma(event)
    ewma_before = engine.liquidation_event_price_ewma["BTCUSDT"]

    mapping = engine._compute_mapping("BTCUSDT", "1m", now_ms)
    assert mapping is not None
    assert 0 < mapping["observed_forced_liquidation_cluster_long_price"] < 100.0
    assert mapping["observed_forced_liquidation_cluster_short_price"] > 100.0
    levels = json.loads(mapping["observed_forced_liquidation_clusters_json"])
    assert all(row["price"] < 100.0 for row in levels["observed_clusters_long"])
    assert all(row["price"] > 100.0 for row in levels["observed_clusters_short"])
    assert mapping["liquidation_semantic_kind"] == mod.OBSERVATION_SEMANTIC_KIND
    assert mapping["liquidation_semantic_type"] == mod.OBSERVATION_SEMANTIC_TYPE
    assert mapping["liquidation_current_price_source"] == "current_price_resolver:mark_price"
    assert mapping["liquidation_current_price_execution_grade"] == 1
    assert mapping["event_time"] == now_ms - 1000
    assert mapping["feature_cutoff"] == mapping["event_time"]
    assert mapping["ingested_at"] == now_ms - 900
    assert mapping["available_at"] == now_ms
    assert mapping["generated_at"] == now_ms
    assert mapping["liquidation_observation_coverage_complete"] == 1
    assert mapping["liquidation_is_stale"] == 0

    engine._compute_mapping("BTCUSDT", "1m", now_ms)
    assert engine.liquidation_event_price_ewma["BTCUSDT"] == ewma_before


def test_staleness_uses_last_event_not_heartbeat_generation_time(
    monkeypatch,
) -> None:
    now_ms = 1_800_000_000_000
    monkeypatch.setattr(mod, "resolve_current_price", lambda _redis, _symbol: {
        "price": 100.0, "source": "mark_price", "staleness_seconds": 1.0,
        "execution_grade": True, "fallback_used": False,
        "reason_if_missing": None,
    })
    engine = _engine()
    stale_event = _event(
        ts=now_ms - mod.STALENESS_STALE_MS - 1,
        price=90.0,
        side="LONG_LIQ",
    )
    engine.state["BTCUSDT"]["1m"].append(stale_event)
    engine._update_liquidation_event_price_ewma(stale_event)

    mapping = engine._compute_mapping("BTCUSDT", "1m", now_ms)
    assert mapping is not None
    assert mapping["generated_at"] == now_ms
    assert mapping["liquidation_last_event_ts"] == stale_event["ts"]
    assert mapping["liquidation_is_stale"] == 1


def test_no_fresh_market_reference_publishes_no_directional_levels(
    monkeypatch,
) -> None:
    now_ms = 1_800_000_000_000
    monkeypatch.setattr(mod, "resolve_current_price", lambda _redis, _symbol: {
        "price": None, "source": None, "staleness_seconds": None,
        "execution_grade": False, "fallback_used": False,
        "reason_if_missing": "FEED_STALE",
    })
    engine = _engine()
    observed = _event(ts=now_ms - 1000, price=90.0, side="LONG_LIQ")
    engine.state["BTCUSDT"]["1m"].append(observed)
    engine._update_liquidation_event_price_ewma(observed)

    mapping = engine._compute_mapping("BTCUSDT", "1m", now_ms)
    assert mapping is not None
    assert mapping["liquidation_current_price_source"] == "liquidation_event_price_ewma_fallback"
    assert mapping["liquidation_current_price_execution_grade"] == 0
    assert mapping["liquidation_no_fresh_market_reference"] == 1
    assert mapping["observed_forced_liquidation_cluster_long_price"] is None
    assert mapping["observed_forced_liquidation_cluster_short_price"] is None
    assert not (mod.FUTURE_LIQUIDATION_ALIAS_FIELDS & mapping.keys())
    assert mapping["liquidation_is_stale"] == 1


@pytest.mark.parametrize("field", ["price", "qty", "notional"])
@pytest.mark.parametrize("bad_value", ["nan", "inf", "-inf"])
def test_event_parser_rejects_non_finite_numeric_values(
    field: str,
    bad_value: str,
) -> None:
    now_ms = 1_800_000_000_000
    engine = _engine()
    fields = {
        "symbol": "BTCUSDT", "ts": str(now_ms - 1000),
        "ingest_ts": str(now_ms - 500), "available_at": str(now_ms - 500),
        "generated_at": str(now_ms - 500), "feature_cutoff": str(now_ms - 1000),
        "price": "100", "qty": "2", "notional": "200", "side": "LONG_LIQ",
        "source": "binance_wss_forceOrder", "src_id": "numeric-event",
    }
    fields[field] = bad_value
    parsed, reason = engine._parse_event(fields, now_ms=now_ms)
    assert parsed == {}
    assert reason == "invalid_numeric_value"


def test_quarantine_is_bounded_and_expiring() -> None:
    engine = _engine()
    engine._quarantine_event(
        msg_id="1-0",
        fields={"ts": "bad"},
        reason="malformed_event",
        now_ms=1_800_000_000_000,
    )
    assert engine.events_quarantined == 1
    key, fields, maxlen, approximate = engine.redis.quarantine_writes[0]
    assert key == mod.QUARANTINE_STREAM
    assert fields["reason"] == "malformed_event"
    assert maxlen == mod.QUARANTINE_MAXLEN
    assert approximate is True
    assert engine.redis.expirations == [
        (mod.QUARANTINE_STREAM, mod.QUARANTINE_TTL_SECONDS)
    ]


def _stream_fields(now_ms: int) -> dict[str, str]:
    return {
        "symbol": "BTCUSDT", "ts": str(now_ms - 1000),
        "ingest_ts": str(now_ms - 500), "available_at": str(now_ms - 500),
        "generated_at": str(now_ms - 500), "feature_cutoff": str(now_ms - 1000),
        "price": "100", "qty": "2", "notional": "200", "side": "LONG_LIQ",
        "source": "binance_wss_forceOrder", "src_id": "stream-event",
    }


def test_accepted_stream_event_is_not_acked_when_derived_publish_fails() -> None:
    now_ms = 1_800_000_000_000
    engine = _engine()

    def fail_publish(_dirty):
        raise RuntimeError("redis mapping publication failed")

    engine._publish_updates = fail_publish
    with pytest.raises(RuntimeError, match="publication failed"):
        engine._process_stream_items(
            [("1-0", _stream_fields(now_ms))],
            now_ms=now_ms,
        )
    assert engine.redis.acked == []


def test_accepted_stream_event_is_acked_only_after_derived_publish() -> None:
    now_ms = 1_800_000_000_000
    engine = _engine()
    publication_observations: list[list[str]] = []

    def publish(_dirty):
        publication_observations.append(list(engine.redis.acked))

    engine._publish_updates = publish
    engine._process_stream_items(
        [("2-0", _stream_fields(now_ms))],
        now_ms=now_ms,
    )
    assert publication_observations == [[]]
    assert engine.redis.acked == ["2-0"]


def test_stale_pending_recovery_is_bounded_and_counted() -> None:
    engine = _engine()
    engine.redis.pending = [("3-0", {"symbol": "BTCUSDT"})]
    recovered = engine._claim_stale_pending()
    assert recovered == engine.redis.pending
    assert engine.pending_messages_recovered == 1
    assert engine.pending_recovery_supported is True
    assert engine.redis.claim_calls[0]["count"] == engine.config.batch_size
    assert engine.redis.claim_calls[0]["min_idle_time"] == mod.PENDING_MIN_IDLE_MS


def test_capture_is_complete_only_when_group_lag_and_pending_are_zero() -> None:
    engine = _engine()
    engine.redis.group_lag = 0
    engine.redis.pending_count = 1
    assert engine._refresh_capture_status(now_ms=1000) is False
    assert engine.capture_caught_up is False
    assert engine.capture_observed_through_ms == 0

    engine.redis.pending_count = 0
    assert engine._refresh_capture_status(now_ms=2000) is True
    assert engine.capture_group_lag == 0
    assert engine.capture_pending_count == 0
    assert engine.capture_observed_through_ms == 2000

    engine.redis.group_lag = 1
    assert engine._refresh_capture_status(now_ms=3000) is False


def test_sparse_capture_can_be_complete_and_gap_fails_closed() -> None:
    engine = _engine()
    now_ms = 1_800_000_000_000
    window_ms = mod.observation_window_seconds("1m", engine.config.max_retention_seconds) * 1000
    engine.capture_start_ms = now_ms - window_ms
    engine.capture_start_ms_by_symbol["BTCUSDT"] = now_ms - window_ms
    engine.capture_caught_up = True
    start, ratio, complete, truncated = engine._observation_coverage(
        "BTCUSDT", "1m", now_ms=now_ms, window_ms=window_ms
    )
    assert start == now_ms - window_ms
    assert ratio == 1.0
    assert complete is True
    assert truncated is False

    engine.capture_gap_detected = True
    assert engine._observation_coverage(
        "BTCUSDT", "1m", now_ms=now_ms, window_ms=window_ms
    )[2] is False


def test_dynamic_symbol_admission_gets_its_own_capture_start(monkeypatch) -> None:
    engine = _engine()
    admission_ms = 1_800_000_000_000
    monkeypatch.setattr(mod, "resolve_symbols", lambda **_kwargs: [
        "BTCUSDT", "ETHUSDT"
    ])
    monkeypatch.setattr(mod.time, "time", lambda: admission_ms / 1000)
    engine.refresh_symbols(force=True)
    assert engine.capture_start_ms_by_symbol["BTCUSDT"] == 0
    assert engine.capture_start_ms_by_symbol["ETHUSDT"] == admission_ms
    window_ms = mod.observation_window_seconds("1m", engine.config.max_retention_seconds) * 1000
    _, ratio, complete, _ = engine._observation_coverage(
        "ETHUSDT", "1m", now_ms=admission_ms, window_ms=window_ms
    )
    assert ratio == 0.0
    assert complete is False


def test_fixed_cadence_cascade_history_includes_sparse_zero_activity(
    monkeypatch,
) -> None:
    now_ms = 1_800_000_000_000
    monkeypatch.setattr(mod, "resolve_current_price", lambda _redis, _symbol: {
        "price": 100.0, "source": "mark_price", "staleness_seconds": 1.0,
        "execution_grade": True, "fallback_used": False,
        "reason_if_missing": None,
    })
    engine = _engine()
    window_ms = mod.observation_window_seconds("1m", engine.config.max_retention_seconds) * 1000
    engine.capture_start_ms = now_ms - window_ms
    engine.capture_start_ms_by_symbol["BTCUSDT"] = now_ms - window_ms

    mappings = []
    for sample_index in range(21):
        sample_now = now_ms + sample_index * mod.CASCADE_HISTORY_SAMPLE_INTERVAL_MS
        mappings.append(engine._compute_mapping("BTCUSDT", "1m", sample_now))
        engine._compute_mapping("BTCUSDT", "1m", sample_now)

    history = engine.intensity_history["BTCUSDT"]["1m"]
    assert len(history) == 21
    assert set(history) == {0.0}
    assert all(mapping is not None for mapping in mappings)
    assert mappings[19]["liquidation_cascade_risk"] is None
    assert mappings[20]["liquidation_cascade_risk"] == 0.0


def test_duplicate_src_id_is_acked_but_counted_once() -> None:
    now_ms = 1_800_000_000_000
    engine = _engine()
    engine._publish_updates = lambda _dirty: None
    fields = dict(_stream_fields(now_ms), src_id="same-source-event")
    engine._process_stream_items(
        [("1-0", fields), ("2-0", dict(fields))],
        now_ms=now_ms,
    )
    assert engine.events_processed == 1
    assert engine.events_deduplicated == 1
    assert len(engine.state["BTCUSDT"]["1m"]) == 1
    assert engine.redis.acked == ["2-0", "1-0"]


def test_bounded_state_marks_truncated_coverage() -> None:
    engine = _engine()
    engine.state["BTCUSDT"]["1m"] = deque(maxlen=2)
    for index in range(3):
        engine._append_event(
            "BTCUSDT",
            "1m",
            _event(ts=1000 + index, price=100.0, side="LONG_LIQ"),
        )
    assert len(engine.state["BTCUSDT"]["1m"]) == 2
    assert engine.state_truncated["BTCUSDT"]["1m"] is True


def test_wrong_side_top_buckets_cannot_hide_valid_directional_level(
    monkeypatch,
) -> None:
    now_ms = 1_800_000_000_000
    monkeypatch.setattr(mod, "resolve_current_price", lambda _redis, _symbol: {
        "price": 100.0, "source": "mark_price", "staleness_seconds": 1.0,
        "execution_grade": True, "fallback_used": False,
        "reason_if_missing": None,
    })
    engine = _engine()
    engine.state["BTCUSDT"]["1m"].append(
        _event(ts=now_ms - 1000, price=90.0, side="LONG_LIQ", notional=100.0)
    )
    for index in range(21):
        engine.state["BTCUSDT"]["1m"].append(_event(
            ts=now_ms - 2000 - index,
            price=105.0 + index,
            side="LONG_LIQ",
            notional=10_000.0 + index,
        ))
    mapping = engine._compute_mapping("BTCUSDT", "1m", now_ms)
    assert mapping is not None
    assert 0 < mapping["observed_forced_liquidation_cluster_long_price"] < 100.0


def test_late_expired_event_is_removed_even_when_appended_last(
    monkeypatch,
) -> None:
    now_ms = 1_800_000_000_000
    monkeypatch.setattr(mod, "resolve_current_price", lambda _redis, _symbol: {
        "price": 100.0, "source": "mark_price", "staleness_seconds": 1.0,
        "execution_grade": True, "fallback_used": False,
        "reason_if_missing": None,
    })
    engine = _engine()
    fresh = _event(ts=now_ms - 1000, price=90.0, side="LONG_LIQ", notional=100.0)
    expired = _event(ts=now_ms - 2 * 3600_000, price=80.0, side="LONG_LIQ", notional=900.0)
    engine.state["BTCUSDT"]["1m"].extend([fresh, expired])
    mapping = engine._compute_mapping("BTCUSDT", "1m", now_ms)
    assert mapping is not None
    assert len(engine.state["BTCUSDT"]["1m"]) == 1
    assert mapping["liquidation_volume"] == 100.0
    assert mapping["event_time"] == fresh["ts"]


def test_unified_hash_keeps_liquidation_clocks_namespaced() -> None:
    engine = _engine()
    mapping = {
        "event_time": 10,
        "ingested_at": 11,
        "available_at": 12,
        "generated_at": 12,
        "feature_cutoff": 10,
        "liquidation_volume": 100.0,
    }
    engine._publish_mapping("BTCUSDT", "1m", mapping, now_ms=12)
    assert len(engine.redis.hset_calls) == 2
    for _key, hash_mapping in engine.redis.hset_calls:
        for generic_clock in (
            "event_time", "ingested_at", "available_at", "generated_at", "feature_cutoff"
        ):
            assert generic_clock not in hash_mapping
            assert hash_mapping[f"liquidation_{generic_clock}"] == mapping[generic_clock]
    level_payload = json.loads(engine.redis.set_calls[0][1])
    assert level_payload["event_time"] == 10
    assert level_payload["liquidation_event_time"] == 10


def test_future_threshold_aliases_are_absent_and_cleared_from_hashes(
    monkeypatch,
) -> None:
    now_ms = 1_800_000_000_000
    monkeypatch.setattr(mod, "resolve_current_price", lambda _redis, _symbol: {
        "price": 100.0, "source": "mark_price", "staleness_seconds": 1.0,
        "execution_grade": True, "fallback_used": False,
        "reason_if_missing": None,
    })
    engine = _engine()
    engine.state["BTCUSDT"]["1m"].extend([
        _event(ts=now_ms - 1000, price=90.0, side="LONG_LIQ"),
        _event(ts=now_ms - 900, price=110.0, side="SHORT_LIQ"),
    ])
    mapping = engine._compute_mapping("BTCUSDT", "1m", now_ms)
    assert mapping is not None
    assert not (mod.FUTURE_LIQUIDATION_ALIAS_FIELDS & mapping.keys())
    engine._publish_mapping("BTCUSDT", "1m", mapping, now_ms)
    assert len(engine.redis.hdel_calls) == 2
    for _key, deleted_fields in engine.redis.hdel_calls:
        assert mod.FUTURE_LIQUIDATION_ALIAS_FIELDS <= set(deleted_fields)
    for _key, hash_mapping in engine.redis.hset_calls:
        assert not (mod.FUTURE_LIQUIDATION_ALIAS_FIELDS & hash_mapping.keys())
    persisted = json.loads(engine.redis.set_calls[0][1])
    assert not (mod.FUTURE_LIQUIDATION_ALIAS_FIELDS & persisted.keys())
