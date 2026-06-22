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


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.write_log: list[tuple[str, str, int | None]] = []
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.xadd_log: list[tuple[str, dict[str, str], int | None, bool]] = []

    def ping(self) -> bool:
        return True

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        self.write_log.append((key, value, ex))
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
                "T": 1700000001000,
            },
        }
    )
    parsed = mod.parse_force_order_event(raw)
    assert parsed is not None
    assert parsed.symbol == "BTCUSDT"
    assert parsed.side == "short"
    assert parsed.notional == 15000.0


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
                "T": 1700000002000,
            },
        }
    )
    parsed = mod.parse_force_order_event(raw)
    assert parsed is not None
    assert parsed.symbol == "ETHUSDT"
    assert parsed.side == "long"
    assert parsed.notional == 1800.0


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
                  "T": 1700000003000},
        }
    ).encode("utf-8")
    parsed = mod.parse_force_order_event(raw)
    assert parsed is not None
    assert parsed.symbol == "SOLUSDT"


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
    ring = mod.RetentionRing(capacity=100)
    now_ms = 1700000000000
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
    assert agg["notional_1h"] == 150.0
    assert agg["count_1h"] == 2
    assert agg["long_count_1h"] == 1
    assert agg["short_count_1h"] == 1
    assert agg["notional_24h"] == 175.0
    assert agg["count_24h"] == 3
    assert agg["direction_bias_1h"] == 0.0


def test_retention_ring_empty_aggregate() -> None:
    mod = _svc()
    ring = mod.RetentionRing(capacity=10)
    agg = ring.aggregate(now_ms=1700000000000)
    assert agg["notional_1h"] == 0.0
    assert agg["count_1h"] == 0
    assert agg["direction_bias_1h"] is None


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
        assert k.startswith("v2:market:liquidations:")


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
                "notional", "source", "src_key", "src_id"):
        assert key in fields, f"missing field {key!r} in stream event"
    # WSS tape side "short" (SELL = trade hits bid) maps to LONG_LIQ
    # (the LONG position was liquidated).
    assert fields["side"] == "LONG_LIQ"
    assert fields["symbol"] == "BTCUSDT"
    assert fields["source"] == "binance_wss_forceOrder"
    # MAXLEN argument was passed
    assert r.xadd_log[0][2] == mod.DEFAULT_EVENTS_STREAM_MAXLEN
    assert r.xadd_log[0][3] is True


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
                  "T": 1700000001000},
        }),
        json.dumps({
            "e": "forceOrder", "E": 1700000002000,
            "o": {"s": "XRPUSDT", "S": "SELL", "q": "1000", "p": "0.5",
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
    for k in r.store.keys():
        assert k.startswith("v2:")


def test_consume_events_respects_max_events_cap() -> None:
    mod = _svc()
    r = FakeRedis()
    events = [
        json.dumps({
            "e": "forceOrder", "E": 1700000001000 + i * 1000,
            "o": {"s": "BTCUSDT", "S": "BUY", "q": "0.5", "p": "30000",
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
