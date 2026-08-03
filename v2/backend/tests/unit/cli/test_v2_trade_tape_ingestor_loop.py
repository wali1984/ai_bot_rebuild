from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from v2.backend.app.cli import v2_trade_tape_ingestor_loop as ingestor
from v2.backend.app.services.a_plus_trade_gate.service import APlusGateConfig, _tape_check


BASE = 1_780_000_000_000


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None):
        del ex
        self.store[key] = value
        return True


def _trade(ts_ms: int, price: float, qty: float, buyer_is_maker: bool) -> dict:
    return {"T": ts_ms, "p": str(price), "q": str(qty), "m": buyer_is_maker}


def test_trade_tape_run_cycle_publishes_required_artifact_proofs(monkeypatch) -> None:
    fake = FakeRedis()
    base = int(time.time() * 1000) - 45_000
    monkeypatch.setattr(ingestor, "resolve_symbols", lambda: ["BTCUSDT", "ETHUSDT"])
    monkeypatch.setattr(
        ingestor,
        "fetch_binance_agg_trades",
        lambda symbol, limit=1000: [
            *[_trade(base + idx * 1000, 100.0, 2.0, False) for idx in range(30)],
            *[_trade(base + 30_000 + idx * 1000, 100.0, 1.0, True) for idx in range(10)],
        ],
    )

    status = ingestor.run_cycle(fake, rotation_offset=0, max_symbols=1)

    assert status["symbols_ok"] == 1
    assert status["transport_policy"] == "binance_public_agg_trade_websocket_primary_rest_fallback_only"
    assert status["source_counts"][ingestor.WEBSOCKET_PRIMARY_SOURCE] == 1
    assert status["fallback_symbol_count"] == 0
    assert status["ttl_seconds"] == 900
    assert status["symbols_per_cycle"] == 1
    assert status["signal_universe_symbols"] == 2
    assert status["trade_tape_symbols"] == 1
    assert status["trade_tape_coverage_pct"] == 0.5
    assert status["required_fields"] == list(ingestor.REQUIRED_TRADE_TAPE_FIELDS)
    assert status["tensor_field_status"]["trainer_tensor_consumes_trade_tape_fields"] is True
    assert status["all_behavioral_proofs_passed"] is True
    assert status["places_real_order"] is False
    feature_payload = json.loads(fake.store["v2:market:trade_tape_features:BTCUSDT"])
    assert feature_payload["source"] == ingestor.WEBSOCKET_PRIMARY_SOURCE
    assert feature_payload["websocket_primary"] is True
    assert feature_payload["fallback_used"] is False
    assert feature_payload["trade_tape_confirmation_score"] is not None
    assert feature_payload["aggressive_buy_volume"] == 6000.0
    assert feature_payload["aggressive_sell_volume"] == 1000.0


def test_trade_tape_main_writes_public_order_flow_artifact(monkeypatch) -> None:
    fake = FakeRedis()
    status = {
        "generated_utc": "2026-07-06T12:00:00.000Z",
        "universe_size": 3,
        "signal_universe_symbols": 3,
        "trade_tape_symbols": 1,
        "trade_tape_coverage_pct": 1 / 3,
        "ttl_seconds": 900,
        "symbols_per_cycle": 40,
        "symbols_ok": 1,
        "symbols_polled": 1,
        "symbols_with_non_neutral_tape": 1,
        "rotation_offset": 0,
        "btc_order_flow_probe": {"long": {"confirms": True}, "short": {"confirms": False}},
        "hard_rules": ["NO_BREAKOUT_OR_SQUEEZE_TRADE_WITHOUT_TAPE_CONFIRMATION"],
        "behavioral_proofs": [{"name": "breakout_blocks_when_tape_missing", "passed": True}],
        "all_behavioral_proofs_passed": True,
        "tensor_field_status": {"trainer_tensor_consumes_trade_tape_fields": True},
    }
    writes: list[tuple[str, dict]] = []

    monkeypatch.setattr(ingestor, "_redis_client", lambda: fake)
    monkeypatch.setattr(ingestor, "run_cycle", lambda client, rotation_offset, max_symbols: status)
    monkeypatch.setattr(ingestor, "_write_artifact", lambda path, payload: writes.append((str(path), payload)))
    monkeypatch.setattr(ingestor, "_safe_set_json", lambda *args, **kwargs: True)
    monkeypatch.setattr(ingestor.sys, "argv", ["v2_trade_tape_ingestor_loop", "--max-cycles", "1"])

    assert ingestor.main() == 0

    written_paths = {path for path, _ in writes}
    assert str(ingestor.GOAL_STATE_DIR / "order_flow_confirmation_status.json") in written_paths
    assert str(ingestor.GOAL_STATE_DIR / "trade_tape_coverage_status.json") in written_paths
    assert str(ingestor.OPERATOR_RUNTIME_DIR / "order_flow_confirmation_status.json") in written_paths
    assert str(ingestor.OPERATOR_RUNTIME_DIR / "trade_tape_coverage_status.json") in written_paths
    public_payload = dict(writes)[str(ingestor.OPERATOR_RUNTIME_DIR / "order_flow_confirmation_status.json")]
    assert public_payload["all_behavioral_proofs_passed"] is True
    assert public_payload["places_real_order"] is False
    assert public_payload["live_gate"] == "blocked_human_only"
    coverage_payload = dict(writes)[str(ingestor.OPERATOR_RUNTIME_DIR / "trade_tape_coverage_status.json")]
    assert coverage_payload["ttl_seconds"] == 900
    assert coverage_payload["symbols_per_cycle"] == 40
    assert coverage_payload["places_real_order"] is False


def test_a_plus_tape_check_blocks_contradicting_order_flow() -> None:
    now = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
    result = _tape_check(
        trade_tape={
            "generated_utc": "2026-07-06T12:00:00Z",
            "trade_tape_confirmation_state": "TAPE_DATA_OK",
            "trade_tape_confirmation_score": 0.20,
        },
        side="long",
        now=now,
        config=APlusGateConfig(),
    )

    assert result["passed"] is False
    assert "TAPE_CONTRADICTS_LONG" in result["reason"]


def test_a_plus_tape_check_fails_closed_when_tape_missing() -> None:
    now = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
    result = _tape_check(
        trade_tape={},
        side="long",
        now=now,
        config=APlusGateConfig(),
    )

    assert result["passed"] is False
    assert result["missing_evidence"] is True
