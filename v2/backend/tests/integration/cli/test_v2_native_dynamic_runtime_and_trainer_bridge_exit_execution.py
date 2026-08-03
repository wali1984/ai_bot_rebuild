"""Tests for V2 native dynamic runtime + trainer bridge-exit execution."""
from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.services.native_dynamic_runtime.execution import (
    BinancePublicReadError,
    BinanceUsdMPublicClient,
    KNOWN_UNIVERSE,
    TIMEFRAMES,
    V2RedisPublisher,
    default_paths,
    execute_dynamic_runtime,
    run_execution_packet,
)
from v2.backend.app.services.native_runtime_migration.safety import (
    LIVE_GATE_BLOCKED,
    V2_NATIVE_ACTIVE_SYMBOLS,
)


def _synthetic_klines(symbol: str, timeframe: str, *, limit: int = 60):
    """Build deterministic candles so the executor has a real input."""
    base_ms = 1_700_000_000_000
    step_ms_by_tf = {
        "1m": 60_000,
        "5m": 300_000,
        "15m": 900_000,
        "1h": 3_600_000,
    }
    step = step_ms_by_tf.get(timeframe, 60_000)
    candles = []
    for i in range(limit):
        open_time = base_ms + i * step
        candles.append({
            "open_time_ms": open_time,
            "open": 100.0 + i * 0.1,
            "high": 100.5 + i * 0.1,
            "low": 99.5 + i * 0.1,
            "close": 100.2 + i * 0.1,
            "volume": 10.0 + i,
            "close_time_ms": open_time + step - 1,
        })
    return candles


def _synthetic_depth(symbol: str, *, limit: int = 100):
    bids = [[100.0 - i * 0.01, 1.0 + i] for i in range(limit)]
    asks = [[100.1 + i * 0.01, 1.0 + i] for i in range(limit)]
    return {"last_update_id": 12345, "bids": bids, "asks": asks, "fetched_ms": 1_700_000_000_000}


class _StubClient(BinanceUsdMPublicClient):
    """Bypass HTTP; return deterministic synthetic market data."""

    def klines(self, symbol, timeframe, *, limit=60):
        if not symbol or not timeframe:
            raise BinancePublicReadError("empty")
        return _synthetic_klines(symbol, timeframe, limit=limit)

    def depth(self, symbol, *, limit=100):
        if not symbol:
            raise BinancePublicReadError("empty")
        return _synthetic_depth(symbol, limit=limit)


def _stub_publisher():
    """Publisher with no Redis client - rejects all writes, audits them."""
    return V2RedisPublisher(client=None)


# ---------------------------------------------------------------------------
# Core executor
# ---------------------------------------------------------------------------


def test_execute_dynamic_runtime_populates_native_status_with_stub_inputs():
    client = _StubClient()
    publisher = _stub_publisher()
    native, trainer, coverage = execute_dynamic_runtime(
        client=client, publisher=publisher,
    )
    # Universe coverage.
    assert coverage["target_symbol_count"] == len(KNOWN_UNIVERSE)
    # OHLCV populated for every symbol x timeframe.
    expected_ohlcv = len(KNOWN_UNIVERSE) * len(TIMEFRAMES)
    assert sum(native["ohlcv_status_counts"].values()) == expected_ohlcv
    assert native["ohlcv_status_counts"].get("V2_NATIVE_POPULATED") == expected_ohlcv
    # Orderbook populated for every symbol.
    assert sum(native["orderbook_status_counts"].values()) == len(KNOWN_UNIVERSE)
    assert native["orderbook_status_counts"].get("V2_NATIVE_POPULATED") == len(KNOWN_UNIVERSE)


def test_executor_does_not_claim_native_trainer_readiness():
    client = _StubClient()
    publisher = _stub_publisher()
    _, trainer, _ = execute_dynamic_runtime(client=client, publisher=publisher)
    # trainer_source must be V2_NATIVE_CONTRACT_ONLY or V2_BRIDGE_FROM_LEGACY_REDIS.
    assert trainer["trainer_source"] in (
        "V2_NATIVE_CONTRACT_ONLY",
        "V2_BRIDGE_FROM_LEGACY_REDIS",
    )
    assert trainer["trainer_source"] != "V2_NATIVE_TRAINER_READY"
    # Predictions must carry block reasons; not tradeable.
    blob = json.dumps(trainer)
    assert "V2_NATIVE_TRAINER_READY" not in blob
    assert "V2_NATIVE_TRAINER_ACTIVE" not in blob


def test_v2_redis_publisher_rejects_non_v2_keys():
    pub = V2RedisPublisher(client=None)
    ok = pub.set_json("legacy:foo:bar", {"x": 1})
    assert ok is False
    assert pub.audit.old_redis_write_attempts == 1
    assert any("blocked_non_v2_key" in e for e in pub.audit.errors)


def test_v2_redis_publisher_accepts_v2_keys_when_no_client_present_records_failure():
    pub = V2RedisPublisher(client=None)
    # Even v2:* writes record as attempted (and fail since no client).
    pub.set_json("v2:test:probe", {"x": 1})
    assert pub.audit.writes_attempted == 1
    assert pub.audit.old_redis_write_attempts == 0


def test_executor_propagates_missing_source_when_fetcher_raises():
    class FailingClient(BinanceUsdMPublicClient):
        def klines(self, symbol, timeframe, *, limit=60):
            raise BinancePublicReadError("simulated_failure")

        def depth(self, symbol, *, limit=100):
            raise BinancePublicReadError("simulated_failure")

    native, _, _ = execute_dynamic_runtime(
        client=FailingClient(), publisher=_stub_publisher(),
    )
    # Every OHLCV row should be MISSING_SOURCE.
    expected = len(KNOWN_UNIVERSE) * len(TIMEFRAMES)
    assert native["ohlcv_status_counts"].get("MISSING_SOURCE") == expected
    # Every orderbook row should be MISSING_SOURCE.
    assert native["orderbook_status_counts"].get("MISSING_SOURCE") == len(KNOWN_UNIVERSE)


# ---------------------------------------------------------------------------
# End-to-end packet
# ---------------------------------------------------------------------------


def test_run_execution_packet_emits_required_artifacts(tmp_path: Path):
    paths = default_paths(tmp_path)
    result = run_execution_packet(
        paths,
        client=_StubClient(),
        publisher=_stub_publisher(),
    )
    assert result.go_no_go == (
        "V2_NATIVE_DYNAMIC_RUNTIME_AND_TRAINER_BRIDGE_EXIT_EXECUTION_READY"
    )
    for required in [
        "GO_NO_GO.md",
        "V2_NATIVE_DYNAMIC_RUNTIME_AND_TRAINER_BRIDGE_EXIT_EXECUTION_REPORT.md",
        "native_dynamic_runtime_status.json",
        "trainer_bridge_exit_execution_status.json",
        "dynamic_symbol_coverage_status.json",
        "operator_dashboard_payload.json",
    ]:
        assert (paths.packet_dir / required).exists(), required
    for required in [
        "native_dynamic_runtime_status.json",
        "trainer_bridge_exit_execution_status.json",
        "dynamic_symbol_coverage_status.json",
        "operator_dashboard_payload.json",
    ]:
        assert (paths.public_dir / required).exists(), required
    # Coverage payload also refreshed into the startup-runtime packet.
    assert (paths.startup_runtime_dir / "dynamic_symbol_paper_runtime_coverage.json").exists()
    assert (paths.startup_runtime_public_dir / "dynamic_symbol_paper_runtime_coverage.json").exists()


def test_emitted_artifacts_carry_no_truthy_approval_or_native_trainer_claims(tmp_path: Path):
    paths = default_paths(tmp_path)
    run_execution_packet(
        paths,
        client=_StubClient(),
        publisher=_stub_publisher(),
    )
    forbidden = [
        '"approves_live": true',
        '"approves_canary": true',
        '"approves_legacy_shutdown": true',
        '"approves_redis_trim": true',
        '"trainer_native_readiness_claimed": true',
        '"full_migration_claimed": true',
        '"bridge_data_labeled_as_v2_native": true',
        '"v2_native_trainer_ready": true',
        '"trainer_source": "V2_NATIVE_TRAINER_READY"',
        '"trainer_source": "V2_NATIVE_TRAINER_ACTIVE"',
    ]
    for f in (
        list(paths.packet_dir.rglob("*"))
        + list(paths.public_dir.rglob("*"))
        + list(paths.startup_runtime_dir.rglob("*"))
        + list(paths.startup_runtime_public_dir.rglob("*"))
    ):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            assert token not in text, f"{token} in {f}"


def test_dashboard_payload_keeps_live_blocked_and_no_controls(tmp_path: Path):
    paths = default_paths(tmp_path)
    run_execution_packet(
        paths,
        client=_StubClient(),
        publisher=_stub_publisher(),
    )
    dashboard = json.loads(
        (paths.public_dir / "operator_dashboard_payload.json").read_text(encoding="utf-8")
    )
    assert dashboard["live_gate"] == LIVE_GATE_BLOCKED
    assert dashboard["live_symbols"] == []
    assert dashboard["approves_live"] is False
    assert dashboard["approves_canary"] is False
    assert dashboard["approves_legacy_shutdown"] is False
    assert dashboard["approves_redis_trim"] is False
    assert dashboard["trainer_native_readiness_claimed"] is False
    assert dashboard["full_migration_claimed"] is False
    assert dashboard["bridge_data_labeled_as_v2_native"] is False
    assert dashboard["controls_present"] is False
    assert dashboard["fake_readiness"] is False
