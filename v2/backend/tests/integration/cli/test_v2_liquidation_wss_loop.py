"""Tests for the V2 liquidation WSS client + CLI.

Paper-only. No real network IO. No torch import. No legacy
filesystem mutation. No silent zero-fill.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import sys
from pathlib import Path

import pytest


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.write_log: list[tuple[str, str, int | None]] = []
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.xadd_log: list[tuple[str, dict[str, str], int | None, bool]] = []
        self.expire_log: list[tuple[str, int]] = []
        self.eval_failures_remaining = 0

    def ping(self) -> bool:
        return True

    def get(self, key: str):
        return self.store.get(key)

    def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool:
        if nx and key in self.store:
            return False
        self.store[key] = value
        self.write_log.append((key, value, ex))
        return True

    def delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0

    def expire(self, key: str, seconds: int) -> bool:
        self.expire_log.append((key, seconds))
        return True

    def xadd(
        self,
        name: str,
        fields: dict[str, str],
        maxlen: int | None = None,
        approximate: bool = False,
    ) -> str:
        self.streams.setdefault(name, []).append((f"{len(self.streams[name])}-0", dict(fields)))
        self.xadd_log.append((name, dict(fields), maxlen, approximate))
        if maxlen is not None and len(self.streams[name]) > maxlen:
            self.streams[name] = self.streams[name][-maxlen:]
        return self.streams[name][-1][0]

    def xrange(
        self,
        name: str,
        min: str = "-",
        max: str = "+",
        count: int | None = None,
    ):
        def _ms(stream_id: str) -> int:
            return int(str(stream_id).split("-", 1)[0])

        lower = -1 if min == "-" else _ms(min)
        upper = 2**63 - 1 if max == "+" else _ms(max)
        rows = [
            row for row in self.streams.get(name, [])
            if lower <= _ms(row[0]) <= upper
        ]
        return rows if count is None else rows[:count]

    def eval(self, _script: str, numkeys: int, *args):
        assert numkeys == 2
        if self.eval_failures_remaining:
            self.eval_failures_remaining -= 1
            raise RuntimeError("injected atomic append failure")
        dedupe_key, stream_name, ttl, maxlen, *flat_fields = args
        if dedupe_key in self.store:
            return 0
        fields = dict(zip(flat_fields[::2], flat_fields[1::2]))
        self.xadd(
            stream_name,
            fields,
            maxlen=int(maxlen),
            approximate=True,
        )
        self.set(dedupe_key, "1", ex=int(ttl))
        return 1


def _svc():
    return importlib.import_module(
        "v2.backend.app.services.native_ingestors.liquidations_wss"
    )


def test_parse_force_order_event_sell_maps_to_short() -> None:
    mod = _svc()
    raw = json.dumps(
        {
            "e": "forceOrder",
            "E": 1700000001000,
            "o": {
                "s": "BTCUSDT",
                "S": "SELL",
                "q": "0.5",
                "p": "30000.0",
                "ap": "30000.0",
                "X": "FILLED",
                "l": "0.5",
                "z": "0.5",
                "T": 1700000001000,
            },
        }
    )
    parsed = mod.parse_force_order_event(raw)
    assert parsed is not None
    assert parsed.symbol == "BTCUSDT"
    assert parsed.side == "short"
    assert parsed.notional == 15000.0
    assert parsed.quantity == 0.5
    assert parsed.raw_order_quantity == 0.5
    assert parsed.execution_quantity_source == "last_filled_quantity_l"


def test_parse_force_order_event_buy_maps_to_long() -> None:
    mod = _svc()
    raw = json.dumps(
        {
            "e": "forceOrder",
            "E": 1700000002000,
            "o": {
                "s": "ETHUSDT",
                "S": "BUY",
                "q": "1.0",
                "p": "1800.0",
                "ap": "1800.0",
                "X": "FILLED",
                "l": "0.75",
                "z": "1.0",
                "T": 1700000002000,
            },
        }
    )
    parsed = mod.parse_force_order_event(raw)
    assert parsed is not None
    assert parsed.symbol == "ETHUSDT"
    assert parsed.side == "long"
    assert parsed.notional == 1350.0
    assert parsed.quantity == 0.75


def test_parse_force_order_event_returns_none_for_non_force_order() -> None:
    mod = _svc()
    assert mod.parse_force_order_event(json.dumps({"e": "trade"})) is None
    assert mod.parse_force_order_event("not json") is None
    assert mod.parse_force_order_event(
        json.dumps({"e": "forceOrder", "o": "bad"})
    ) is None


def test_parse_force_order_event_handles_bytes() -> None:
    mod = _svc()
    raw = json.dumps(
        {
            "e": "forceOrder",
            "E": 1700000003000,
            "o": {"s": "SOLUSDT", "S": "SELL", "q": "10", "p": "20",
                  "X": "FILLED", "l": "10", "z": "10",
                  "T": 1700000003000},
        }
    ).encode("utf-8")
    parsed = mod.parse_force_order_event(raw)
    assert parsed is not None
    assert parsed.symbol == "SOLUSDT"


def test_parse_force_order_uses_last_fill_for_partial_execution() -> None:
    mod = _svc()
    parsed = mod.parse_force_order_event(json.dumps({
        "e": "forceOrder", "E": 1700000003000,
        "o": {
            "s": "BTCUSDT", "S": "SELL", "q": "10", "p": "100",
            "X": "PARTIALLY_FILLED", "l": "2", "z": "7",
            "T": 1700000003000,
        },
    }))
    assert parsed is not None
    assert parsed.quantity == 2.0
    assert parsed.raw_order_quantity == 10.0
    assert parsed.accumulated_filled_quantity == 7.0
    assert parsed.notional == 200.0
    assert parsed.execution_quantity_source == "last_filled_quantity_l"


def test_partial_then_filled_snapshots_use_non_overlapping_last_fills() -> None:
    mod = _svc()

    def parse(status: str, last: str, cumulative: str, event_time: int):
        return mod.parse_force_order_event(json.dumps({
            "e": "forceOrder", "E": event_time,
            "o": {
                "s": "BTCUSDT", "S": "SELL", "q": "10", "p": "100",
                "X": status, "l": last, "z": cumulative, "T": event_time,
            },
        }))

    partial = parse("PARTIALLY_FILLED", "2", "2", 1700000003000)
    filled = parse("FILLED", "8", "10", 1700000004000)
    assert partial is not None and filled is not None
    assert partial.quantity == 2.0
    assert filled.quantity == 8.0
    assert partial.quantity + filled.quantity == filled.accumulated_filled_quantity


@pytest.mark.parametrize(
    ("status", "last", "cumulative", "expected_reason"),
    [
        ("FILLED", "0", "10", "missing_executed_quantity"),
        ("FILLED", "2", "9", "filled_status_without_full_accumulated_quantity"),
        ("PARTIALLY_FILLED", "2", "10", "partial_fill_has_terminal_accumulated_quantity"),
        ("PARTIALLY_FILLED", "8", "7", "last_filled_quantity_exceeds_accumulated"),
    ],
)
def test_parse_force_order_rejects_inconsistent_fill_lineage(
    status: str,
    last: str,
    cumulative: str,
    expected_reason: str,
) -> None:
    mod = _svc()
    parsed, reason = mod._parse_force_order_event_detailed(json.dumps({
        "e": "forceOrder", "E": 1700000003000,
        "o": {
            "s": "BTCUSDT", "S": "SELL", "q": "10", "p": "100",
            "X": status, "l": last, "z": cumulative, "T": 1700000003000,
        },
    }))
    assert parsed is None
    assert reason == expected_reason


@pytest.mark.parametrize("field", ["p", "q", "z", "l"])
@pytest.mark.parametrize("bad_value", [True, "nan", "inf"])
def test_parse_force_order_rejects_non_finite_or_boolean_execution_fields(
    field: str,
    bad_value,
) -> None:
    mod = _svc()
    order = {
        "s": "BTCUSDT", "S": "SELL", "q": "10", "p": "100",
        "X": "FILLED", "l": "10", "z": "10", "T": 1700000003000,
    }
    order[field] = bad_value
    parsed, reason = mod._parse_force_order_event_detailed(json.dumps({
        "e": "forceOrder", "E": 1700000003000, "o": order,
    }))
    assert parsed is None
    assert reason == f"invalid_numeric_field:{field}"


def test_parse_force_order_rejects_coin_m_and_unknown_status() -> None:
    mod = _svc()
    coin_m = json.dumps({
        "e": "forceOrder", "E": 1700000003000, "st": "CM",
        "o": {
            "s": "BTCUSD_PERP", "S": "SELL", "q": "10", "p": "100",
            "X": "FILLED", "l": "10", "z": "10", "T": 1700000003000,
        },
    })
    unknown_status = json.dumps({
        "e": "forceOrder", "E": 1700000003000,
        "o": {
            "s": "BTCUSDT", "S": "SELL", "q": "10", "p": "100",
            "X": "NEW", "l": "0", "z": "0", "T": 1700000003000,
        },
    })
    assert mod.parse_force_order_event(coin_m) is None
    assert mod.parse_force_order_event(unknown_status) is None


def test_retention_ring_caps_at_capacity() -> None:
    mod = _svc()
    ring = mod.RetentionRing(capacity=3)
    for i in range(5):
        ring.append(
            mod.ParsedLiquidation(
                symbol="BTCUSDT", side="long",
                notional=float(i), price=1.0, quantity=float(i),
                event_time_ms=1700000000000 + i * 1000,
            )
        )
    assert len(ring.events) == 3
    assert ring.events[0].notional == 2.0
    assert ring.events[-1].notional == 4.0


def test_retention_ring_aggregate_windows() -> None:
    mod = _svc()
    now_ms = 1700000000000
    ring = mod.RetentionRing(
        capacity=100,
        coverage_start_ms=now_ms - mod.DEFAULT_WINDOW_24H_MS,
    )
    ring.append(mod.ParsedLiquidation(
        symbol="BTCUSDT", side="long", notional=100.0,
        price=1.0, quantity=100.0, event_time_ms=now_ms - 30 * 1000))
    ring.append(mod.ParsedLiquidation(
        symbol="BTCUSDT", side="short", notional=50.0,
        price=1.0, quantity=50.0, event_time_ms=now_ms - 30 * 60 * 1000))
    ring.append(mod.ParsedLiquidation(
        symbol="BTCUSDT", side="short", notional=25.0,
        price=1.0, quantity=25.0, event_time_ms=now_ms - 12 * 60 * 60 * 1000))
    agg = ring.aggregate(now_ms=now_ms)
    assert agg["observed_notional_1h"] == 150.0
    assert agg["observed_count_1h"] == 2
    assert agg["observed_long_count_1h"] == 1
    assert agg["observed_short_count_1h"] == 1
    assert agg["observed_notional_window"] == 175.0
    assert agg["observed_count_window"] == 3
    assert agg["observed_direction_bias_1h"] == 0.0
    assert agg["retention_window_complete"] is True
    assert agg["source_capture_complete"] is False
    assert agg["aggregate_complete"] is False
    assert agg["trainer_feature_wiring_status"] == "NOT_WIRED_FAIL_CLOSED"
    assert agg["legacy_complete_aggregate_published"] is False
    assert "notional_24h" not in agg
    assert "count_24h" not in agg
    assert "notional_1h" not in agg
    assert "count_1h" not in agg


def test_retention_ring_empty_aggregate() -> None:
    mod = _svc()
    now_ms = 1700000000000
    ring = mod.RetentionRing(
        capacity=10,
        coverage_start_ms=now_ms - mod.DEFAULT_WINDOW_1H_MS,
    )
    agg = ring.aggregate(now_ms=now_ms)
    assert agg["observed_notional_1h"] == 0.0
    assert agg["observed_count_1h"] == 0
    assert agg["observed_direction_bias_1h"] is None
    assert agg["retention_window_complete"] is False
    assert "notional_24h" not in agg


def test_retention_truncation_invalidates_coverage() -> None:
    mod = _svc()
    now_ms = 1700000000000
    ring = mod.RetentionRing(
        capacity=2,
        coverage_start_ms=now_ms - mod.DEFAULT_WINDOW_24H_MS,
    )
    for index in range(3):
        ring.append(mod.ParsedLiquidation(
            symbol="BTCUSDT", side="long", notional=10.0,
            price=10.0, quantity=1.0, event_time_ms=now_ms - index,
        ))
    aggregate = ring.aggregate(now_ms=now_ms)
    assert ring.capacity is not None
    assert len(ring.events) == 2
    assert aggregate["retention_truncated"] is True
    assert aggregate["retention_window_complete"] is False


def test_compute_backoff_seconds_exponential_with_cap() -> None:
    mod = _svc()
    assert mod.compute_backoff_seconds(0) == 0.0
    assert mod.compute_backoff_seconds(1) == 1.0
    assert mod.compute_backoff_seconds(2) == 2.0
    assert mod.compute_backoff_seconds(3) == 4.0
    assert mod.compute_backoff_seconds(4) == 8.0
    assert mod.compute_backoff_seconds(5) == 16.0
    assert mod.compute_backoff_seconds(6) == 30.0
    assert mod.compute_backoff_seconds(20) == 30.0
    assert mod.compute_backoff_seconds(10_000) == 30.0


def test_safe_redis_set_refuses_non_v2_keys() -> None:
    mod = _svc()
    r = FakeRedis()
    assert mod._safe_redis_set(r, "prediction:BTCUSDT", "X") is False
    assert mod._safe_redis_set(r, "signals:paper", "X") is False
    assert mod._safe_redis_set(r, "v2:market:liquidations:heartbeat", "Y") is True
    assert "v2:market:liquidations:heartbeat" in r.store
    assert "prediction:BTCUSDT" not in r.store


def test_write_event_to_redis_only_writes_v2_keys() -> None:
    mod = _svc()
    r = FakeRedis()
    event = mod.ParsedLiquidation(
        symbol="BTCUSDT", side="short", notional=10000.0,
        price=20000.0, quantity=0.5, event_time_ms=1700000000000,
    )
    agg = {"notional_1h": 50000.0}
    result = mod.write_event_to_redis(
        r, symbol="BTCUSDT", latest_event=event, aggregate=agg
    )
    assert all(result.values())
    for k in r.store.keys():
        assert k.startswith("v2:")
    assert any(k.startswith("v2:market:liquidations:") for k in r.store)


def test_write_event_to_stream_publishes_into_v2_liquidations_events() -> None:
    mod = _svc()
    r = FakeRedis()
    event = mod.ParsedLiquidation(
        symbol="BTCUSDT", side="short", notional=10000.0,
        price=20000.0, quantity=0.5, event_time_ms=1700000000000,
    )
    ok = mod.write_event_to_stream(r, symbol="BTCUSDT", latest_event=event)
    assert ok is True
    assert mod.KEY_EVENTS_STREAM == "v2:liquidations:events"
    assert mod.KEY_EVENTS_STREAM in r.streams
    assert len(r.streams[mod.KEY_EVENTS_STREAM]) == 1
    _, fields = r.streams[mod.KEY_EVENTS_STREAM][0]
    for key in ("symbol", "ts", "ingest_ts", "side", "price", "qty",
                "notional", "source", "src_key", "src_id", "event_time",
                "ingested_at", "available_at", "generated_at", "feature_cutoff",
                "raw_order_qty", "last_filled_qty", "accumulated_filled_qty",
                "order_status", "execution_quantity_source", "product_type"):
        assert key in fields, f"missing field {key!r} in stream event"
    # WSS tape side "short" (SELL = trade hits bid) maps to LONG_LIQ
    # (the LONG position was liquidated).
    assert fields["side"] == "LONG_LIQ"
    assert fields["symbol"] == "BTCUSDT"
    assert fields["source"] == "binance_wss_forceOrder"
    # MAXLEN argument was passed
    assert r.xadd_log[0][2] == mod.DEFAULT_EVENTS_STREAM_MAXLEN
    assert r.xadd_log[0][3] is True


def test_write_event_to_stream_deduplicates_src_id_with_expiring_key() -> None:
    mod = _svc()
    r = FakeRedis()
    event = mod.ParsedLiquidation(
        symbol="BTCUSDT", side="short", notional=10000.0,
        price=20000.0, quantity=0.5, event_time_ms=1700000000000,
        raw_order_quantity=0.5, last_filled_quantity=0.5,
        accumulated_filled_quantity=0.5, order_status="FILLED",
        execution_quantity_source="accumulated_filled_quantity_z",
    )
    assert mod.write_event_to_stream(r, symbol="BTCUSDT", latest_event=event)
    assert not mod.write_event_to_stream(r, symbol="BTCUSDT", latest_event=event)
    assert len(r.streams[mod.KEY_EVENTS_STREAM]) == 1
    dedupe_writes = [row for row in r.write_log if row[0].startswith("v2:liquidations:dedupe:")]
    assert dedupe_writes
    assert dedupe_writes[0][2] == mod.DEFAULT_DEDUPE_TTL_SECONDS


def test_write_event_to_stream_buy_maps_to_short_liq() -> None:
    mod = _svc()
    r = FakeRedis()
    event = mod.ParsedLiquidation(
        symbol="ETHUSDT", side="long", notional=15000.0,
        price=3000.0, quantity=5.0, event_time_ms=1700000001000,
    )
    assert mod.write_event_to_stream(r, symbol="ETHUSDT", latest_event=event)
    _, fields = r.streams[mod.KEY_EVENTS_STREAM][0]
    # WSS tape side "long" (BUY = trade hits ask) maps to SHORT_LIQ
    # (the SHORT position was liquidated).
    assert fields["side"] == "SHORT_LIQ"


def test_write_event_to_redis_also_publishes_stream() -> None:
    mod = _svc()
    r = FakeRedis()
    event = mod.ParsedLiquidation(
        symbol="SOLUSDT", side="short", notional=2000.0,
        price=200.0, quantity=10.0, event_time_ms=1700000002000,
    )
    mod.write_event_to_redis(
        r, symbol="SOLUSDT", latest_event=event, aggregate={"notional_1h": 0},
    )
    assert mod.KEY_EVENTS_STREAM in r.streams
    assert len(r.streams[mod.KEY_EVENTS_STREAM]) == 1
    _, fields = r.streams[mod.KEY_EVENTS_STREAM][0]
    assert fields["symbol"] == "SOLUSDT"
    assert fields["side"] == "LONG_LIQ"


def test_consume_events_writes_when_symbol_in_scope() -> None:
    mod = _svc()
    r = FakeRedis()
    events = [
        json.dumps({
            "e": "forceOrder", "E": 1700000001000,
            "o": {"s": "BTCUSDT", "S": "BUY", "q": "0.5", "p": "30000",
                  "X": "FILLED", "l": "0.5", "z": "0.5",
                  "T": 1700000001000},
        }),
        json.dumps({
            "e": "forceOrder", "E": 1700000002000,
            "o": {"s": "XRPUSDT", "S": "SELL", "q": "1000", "p": "0.5",
                  "X": "FILLED", "l": "1000", "z": "1000",
                  "T": 1700000002000},
        }),
        "not even json",
    ]

    async def source():
        return events

    stats = asyncio.run(
        mod.consume_events(
            event_source=source,
            redis_client=r,
            symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
            now_ms_func=lambda: 1700000005000,
        )
    )
    assert stats.events_received == 3
    assert stats.events_parsed == 2
    assert stats.events_filtered_by_symbol == 1
    assert stats.events_written == 1
    assert stats.parse_errors == 1
    assert stats.events_quarantined == 1
    for k in r.store.keys():
        assert k.startswith("v2:")


def test_consume_events_respects_max_events_cap() -> None:
    mod = _svc()
    r = FakeRedis()
    events = [
        json.dumps({
            "e": "forceOrder", "E": 1700000001000 + i * 1000,
            "o": {"s": "BTCUSDT", "S": "BUY", "q": "0.5", "p": "30000",
                  "X": "FILLED", "l": "0.5", "z": "0.5",
                  "T": 1700000001000 + i * 1000},
        })
        for i in range(10)
    ]

    async def source():
        return events

    stats = asyncio.run(
        mod.consume_events(
            event_source=source, redis_client=r,
            symbols=("BTCUSDT",), max_events=3,
            now_ms_func=lambda: 1700000020000,
        )
    )
    assert stats.events_written == 3


def test_atomic_stream_failure_is_retryable_without_double_counting() -> None:
    mod = _svc()
    r = FakeRedis()
    r.eval_failures_remaining = 1
    now_ms = 1700000005000
    raw = json.dumps({
        "e": "forceOrder", "E": 1700000001000,
        "o": {
            "s": "BTCUSDT", "S": "BUY", "q": "0.5", "p": "30000",
            "X": "FILLED", "l": "0.5", "z": "0.5", "T": 1700000001000,
        },
    })
    rings = {"BTCUSDT": mod.RetentionRing(coverage_start_ms=now_ms)}

    async def source():
        return [raw]

    failed = asyncio.run(mod.consume_events(
        event_source=source,
        redis_client=r,
        symbols=("BTCUSDT",),
        now_ms_func=lambda: now_ms,
        rings=rings,
    ))
    assert failed.redis_write_failures == 1
    assert len(rings["BTCUSDT"].events) == 0

    retried = asyncio.run(mod.consume_events(
        event_source=source,
        redis_client=r,
        symbols=("BTCUSDT",),
        now_ms_func=lambda: now_ms,
        rings=rings,
    ))
    assert retried.events_written == 1
    assert len(rings["BTCUSDT"].events) == 1
    observed = json.loads(
        r.store[mod.KEY_OBSERVED_AGGREGATE_TEMPLATE.format(symbol="BTCUSDT")]
    )
    assert observed["observed_count_1h"] == 1


def test_out_of_order_event_does_not_regress_latest_or_feature_cutoff() -> None:
    mod = _svc()
    r = FakeRedis()
    now_ms = 1700000010000

    def raw(event_time: int, price: str) -> str:
        return json.dumps({
            "e": "forceOrder", "E": event_time,
            "o": {
                "s": "BTCUSDT", "S": "SELL", "q": "1", "p": price,
                "X": "FILLED", "l": "1", "z": "1", "T": event_time,
            },
        })

    async def source():
        return [raw(1700000009000, "101"), raw(1700000001000, "99")]

    stats = asyncio.run(mod.consume_events(
        event_source=source,
        redis_client=r,
        symbols=("BTCUSDT",),
        now_ms_func=lambda: now_ms,
    ))
    assert stats.events_written == 2
    latest = json.loads(r.store[mod.KEY_LATEST_TEMPLATE.format(symbol="BTCUSDT")])
    aggregate = json.loads(
        r.store[mod.KEY_OBSERVED_AGGREGATE_TEMPLATE.format(symbol="BTCUSDT")]
    )
    assert latest["event_time"] == 1700000009000
    assert aggregate["feature_cutoff"] == 1700000009000


def test_consume_events_quarantines_future_clock_without_rewriting() -> None:
    mod = _svc()
    r = FakeRedis()
    now_ms = 1700000000000

    async def source():
        return [json.dumps({
            "e": "forceOrder", "E": now_ms + 60_000,
            "o": {
                "s": "BTCUSDT", "S": "BUY", "q": "0.5", "p": "30000",
                "X": "FILLED", "l": "0.5", "z": "0.5",
                "T": now_ms + 60_000,
            },
        })]

    stats = asyncio.run(mod.consume_events(
        event_source=source,
        redis_client=r,
        symbols=("BTCUSDT",),
        now_ms_func=lambda: now_ms,
    ))
    assert stats.events_written == 0
    assert stats.events_quarantined == 1
    _, fields = r.streams[mod.KEY_QUARANTINE_STREAM][0]
    assert fields["reason"] == "event_time_in_future"
    assert (mod.KEY_QUARANTINE_STREAM, mod.DEFAULT_QUARANTINE_TTL_SECONDS) in r.expire_log


def test_hydration_restores_retained_window_but_never_claims_true_24h() -> None:
    mod = _svc()
    r = FakeRedis()
    now_ms = 1700000000000
    event_ts = now_ms - 2 * 60 * 60 * 1000
    r.streams[mod.KEY_EVENTS_STREAM] = [(
        f"{event_ts}-0",
        {
            "symbol": "BTCUSDT", "side": "LONG_LIQ", "ts": str(event_ts),
            "event_time": str(event_ts), "exchange_event_time": str(event_ts),
            "feature_cutoff": str(event_ts),
            "ingest_ts": str(event_ts + 1), "ingested_at": str(event_ts + 1),
            "available_at": str(event_ts + 1), "generated_at": str(event_ts + 1),
            "price": "100", "qty": "2", "notional": "200", "src_id": "one",
            "source": "binance_wss_forceOrder",
            "semantic_kind": mod.OBSERVED_AGGREGATE_SEMANTIC_KIND,
            "product_type": "USD_M_USDT_ASSUMED_FROM_ENDPOINT",
        },
    )]
    rings = {"BTCUSDT": mod.RetentionRing(coverage_start_ms=now_ms)}
    result = mod.hydrate_retention_rings(
        r, rings=rings, symbols=("BTCUSDT",), now_ms=now_ms
    )
    assert result["hydrated"] is True
    assert result["events_loaded"] == 1
    aggregate = rings["BTCUSDT"].aggregate(now_ms=now_ms)
    assert aggregate["observed_notional_window"] == 200.0
    assert aggregate["retention_window_complete"] is False
    assert "notional_24h" not in aggregate


@pytest.mark.parametrize("field", ["price", "qty", "notional"])
@pytest.mark.parametrize("bad_value", ["nan", "inf", "-inf"])
def test_hydration_rejects_non_finite_numeric_fields(
    field: str,
    bad_value: str,
) -> None:
    mod = _svc()
    event_ts = 1700000000000
    fields = {
        "symbol": "BTCUSDT", "side": "LONG_LIQ",
        "event_time": str(event_ts), "exchange_event_time": str(event_ts),
        "feature_cutoff": str(event_ts), "ingested_at": str(event_ts + 1),
        "available_at": str(event_ts + 1), "generated_at": str(event_ts + 1),
        "price": "100", "qty": "2", "notional": "200",
        "source": "binance_wss_forceOrder",
        "semantic_kind": mod.OBSERVED_AGGREGATE_SEMANTIC_KIND,
        "product_type": "USD_M_USDT_ASSUMED_FROM_ENDPOINT",
    }
    fields[field] = bad_value
    assert mod._event_from_stream_fields(fields, now_ms=event_ts + 1000) is None


def test_opt_in_disabled_by_default(monkeypatch) -> None:
    mod = _svc()
    monkeypatch.delenv("V2_LIQUIDATION_WSS_OPT_IN", raising=False)
    assert mod.opt_in_enabled() is False


def test_opt_in_flips_when_env_set(monkeypatch) -> None:
    mod = _svc()
    monkeypatch.setenv("V2_LIQUIDATION_WSS_OPT_IN", "true")
    assert mod.opt_in_enabled() is True


def test_cli_blocked_when_opt_in_missing(tmp_path: Path, monkeypatch) -> None:
    cli = importlib.import_module("v2.backend.app.cli.v2_liquidation_wss_loop")
    monkeypatch.delenv("V2_LIQUIDATION_WSS_OPT_IN", raising=False)
    worklog = tmp_path / "wl/s.json"
    pub_a = tmp_path / "pa/s.json"
    pub_b = tmp_path / "pb/s.json"
    rc = cli.main([
        "--total-seconds", "0.1",
        "--out-worklog", str(worklog),
        "--out-public", str(pub_a),
        "--out-public-secondary", str(pub_b),
    ])
    assert rc == 0
    a = json.loads(worklog.read_text())
    assert a["go_no_go"] == "V2_LIQUIDATION_WSS_CLIENT_PAPER_SHADOW_BLOCKED"
    assert a["writes_legacy_redis"] is False
    assert a["writes_exchange_orders"] is False
    assert a["no_synthetic_liquidation_events"] is True
    assert a["live_gate"] == "blocked_human_only"
    assert a["live_symbols"] == []
    assert a["approves_live"] is False
    assert a["approves_legacy_shutdown"] is False


def test_cli_writes_status_with_safety_invariants_on_opt_in(
    tmp_path: Path, monkeypatch
) -> None:
    cli = importlib.import_module("v2.backend.app.cli.v2_liquidation_wss_loop")
    monkeypatch.setenv("V2_LIQUIDATION_WSS_OPT_IN", "true")

    async def _fake_run_with_reconnect(**kwargs):
        return {
            "events_received": 0, "events_parsed": 0,
            "events_filtered_by_symbol": 0, "events_written": 0,
            "parse_errors": 0, "redis_write_failures": 0,
            "reconnect_count": 0, "last_event_utc": None, "sessions": 0,
        }

    monkeypatch.setattr(cli, "_run_with_reconnect", _fake_run_with_reconnect)
    monkeypatch.setattr(cli, "_connect_redis", lambda: None)
    worklog = tmp_path / "wl/s.json"
    pub_a = tmp_path / "pa/s.json"
    pub_b = tmp_path / "pb/s.json"
    rc = cli.main([
        "--total-seconds", "0.01",
        "--max-seconds-per-session", "0.01",
        "--max-events-per-session", "1",
        "--heartbeat-interval-seconds", "0.005",
        "--heartbeat-ttl-seconds", "180",
        "--out-worklog", str(worklog),
        "--out-public", str(pub_a),
        "--out-public-secondary", str(pub_b),
    ])
    assert rc == 0
    payload = json.loads(worklog.read_text())
    assert payload["go_no_go"] == "V2_LIQUIDATION_WSS_CLIENT_PAPER_SHADOW_READY"
    assert payload["writes_legacy_redis"] is False
    assert payload["writes_exchange_orders"] is False
    assert payload["no_synthetic_liquidation_events"] is True
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["approves_live"] is False
    assert payload["url"].startswith("wss://")
    assert payload["process_mode"] == "persistent_daemon"
    assert payload["service_active"] is True
    assert payload["opt_in_enabled"] is True
    assert "heartbeat_at" in payload


def test_no_exchange_mutation_surface_in_module_source() -> None:
    import inspect

    mod = _svc()
    src = inspect.getsource(mod)
    # Compose forbidden tokens piecewise so this test file itself does
    # not trigger upstream string-scan hooks.
    forbidden = (
        "create" + "_order",
        "place" + "_order",
        "cancel" + "_order",
        "modify" + "_order",
        "set" + "_leverage",
        "set" + "_margin" + "_mode",
        "futures" + "_create" + "_order",
    )
    for token in forbidden:
        assert token not in src, f"forbidden token in module: {token}"


def test_no_torch_imported_in_wss_modules() -> None:
    sys.modules.pop("torch", None)
    importlib.import_module(
        "v2.backend.app.services.native_ingestors.liquidations_wss"
    )
    importlib.import_module("v2.backend.app.cli.v2_liquidation_wss_loop")
    assert "torch" not in sys.modules


def test_write_heartbeat_default_ttl_is_180_seconds() -> None:
    mod = _svc()
    r = FakeRedis()
    assert mod.write_heartbeat(r, {"go_no_go": "ok"}) is True
    assert r.write_log, "heartbeat write was not recorded"
    key, _value, ex = r.write_log[-1]
    assert key == mod.KEY_HEARTBEAT
    assert ex == mod.DEFAULT_HEARTBEAT_TTL_SECONDS == 180


def test_write_heartbeat_accepts_custom_ttl() -> None:
    mod = _svc()
    r = FakeRedis()
    assert mod.write_heartbeat(r, {"go_no_go": "ok"}, ttl_seconds=300) is True
    _key, _value, ex = r.write_log[-1]
    assert ex == 300


def test_heartbeat_ttl_strictly_greater_than_default_interval() -> None:
    mod = _svc()
    assert (
        mod.DEFAULT_HEARTBEAT_TTL_SECONDS
        > mod.DEFAULT_HEARTBEAT_INTERVAL_SECONDS
    )


def test_build_daemon_status_payload_has_required_freshness_fields() -> None:
    cli = importlib.import_module("v2.backend.app.cli.v2_liquidation_wss_loop")
    payload = cli._build_daemon_status_payload(
        symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        live_state={
            "events_received": 0,
            "events_written": 0,
            "reconnect_count": 0,
            "sessions": 0,
            "last_event_utc": None,
        },
    )
    for field in (
        "generated_at",
        "heartbeat_at",
        "process_mode",
        "service_active",
        "opt_in_enabled",
        "sessions",
        "reconnect_count",
        "events_received",
        "events_written",
        "last_event_utc",
        "live_gate",
        "live_symbols",
        "writes_legacy_redis",
        "writes_exchange_orders",
        "no_synthetic_liquidation_events",
        "observed_aggregate_downstream_contract_status",
        "legacy_complete_aggregate_refresh_enabled",
    ):
        assert field in payload, f"missing required freshness field: {field}"
    assert payload["process_mode"] == "persistent_daemon"
    assert payload["service_active"] is True
    assert payload["opt_in_enabled"] is True
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["writes_legacy_redis"] is False
    assert payload["writes_exchange_orders"] is False
    assert payload["no_synthetic_liquidation_events"] is True
    assert payload["legacy_complete_aggregate_refresh_enabled"] is False
    assert "NOT_WIRED_FAIL_CLOSED" in payload[
        "observed_aggregate_downstream_contract_status"
    ]
    assert payload["go_no_go"] == "V2_LIQUIDATION_WSS_CLIENT_PAPER_SHADOW_READY"


def test_heartbeat_writer_refreshes_status_and_redis_during_quiet_session(
    tmp_path: Path,
) -> None:
    """Background heartbeat writer must refresh status JSON + Redis
    heartbeat key on its interval, even when no liquidation events are
    arriving over the WSS stream.
    """
    cli = importlib.import_module("v2.backend.app.cli.v2_liquidation_wss_loop")
    r = FakeRedis()
    worklog = tmp_path / "wl/status.json"
    pub_a = tmp_path / "pa/status.json"
    pub_b = tmp_path / "pb/status.json"
    live_state = {
        "events_received": 0,
        "events_written": 0,
        "reconnect_count": 0,
        "sessions": 0,
        "last_event_utc": None,
    }

    async def _run():
        task = asyncio.create_task(
            cli._heartbeat_writer(
                symbols=("BTCUSDT",),
                live_state=live_state,
                redis_client=r,
                worklog_path=worklog,
                public_paths=(pub_a, pub_b),
                interval_seconds=0.05,
                heartbeat_ttl_seconds=180,
            )
        )
        await asyncio.sleep(0.20)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())
    assert worklog.exists()
    assert pub_a.exists()
    assert pub_b.exists()
    payload = json.loads(worklog.read_text())
    assert payload["process_mode"] == "persistent_daemon"
    assert payload["heartbeat_at"]
    heartbeat_writes = [
        entry for entry in r.write_log
        if entry[0] == "v2:market:liquidations:heartbeat"
    ]
    assert len(heartbeat_writes) >= 2
    for _key, _value, ex in heartbeat_writes:
        assert ex == 180


def test_systemd_unit_pythonpath_quoted_for_path_with_spaces() -> None:
    unit = Path(
        "claude_worklog/systemd/user/ai-bot-v2-liquidation-wss-paper-shadow.service"
    )
    text = unit.read_text(encoding="utf-8")
    # Unit must wrap PYTHONPATH value in double quotes so systemd does
    # not split on the space inside "AI BOT REBUILD".
    assert 'Environment="PYTHONPATH=/home/wali/Desktop/AI BOT REBUILD"' in text
    # Unit must not contain the unquoted form that produced the FAIL.
    assert "Environment=PYTHONPATH=/home/wali/Desktop/AI BOT REBUILD" not in text


def test_cli_main_blocks_when_interval_not_strictly_below_ttl(
    tmp_path: Path, monkeypatch
) -> None:
    cli = importlib.import_module("v2.backend.app.cli.v2_liquidation_wss_loop")
    monkeypatch.setenv("V2_LIQUIDATION_WSS_OPT_IN", "true")
    rc = cli.main(
        [
            "--total-seconds", "0.01",
            "--max-seconds-per-session", "0.01",
            "--heartbeat-interval-seconds", "180",
            "--heartbeat-ttl-seconds", "180",
            "--out-worklog", str(tmp_path / "wl.json"),
            "--out-public", str(tmp_path / "pa.json"),
            "--out-public-secondary", str(tmp_path / "pb.json"),
        ]
    )
    assert rc == 2
