"""Tests for V2 paper position-history persistent tracker.

All tests use ``FakeRedis``; no test reaches a real Redis instance.
"""
from __future__ import annotations

import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.write_log: list[tuple[str, str, int | None]] = []

    def ping(self) -> bool:
        return True

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        self.write_log.append((key, value, ex))
        return True


def _service():
    return importlib.import_module(
        "v2.backend.app.services.rl_core.position_history_persistent_tracker"
    )


def _cli():
    return importlib.import_module(
        "v2.backend.app.cli.v2_position_history_persistent_tracker"
    )


def _seed_paper_inputs(
    redis: FakeRedis,
    *,
    paper_positions: list[dict] | None = None,
    paper_ledger: dict | None = None,
    paper_intents: list[dict] | None = None,
    paper_intents_held: list[dict] | None = None,
    market_price: dict | None = None,
    symbol: str = "BTCUSDT",
) -> None:
    if paper_positions is not None:
        redis.set("v2:paper:positions", json.dumps(paper_positions))
    if paper_ledger is not None:
        redis.set("v2:paper:ledger", json.dumps(paper_ledger))
    if paper_intents is not None:
        redis.set("v2:paper:intents", json.dumps(paper_intents))
    if paper_intents_held is not None:
        redis.set(
            "v2:paper:intents_held_by_paper_fill_gate",
            json.dumps(paper_intents_held),
        )
    if market_price is not None:
        redis.set(f"v2:market:prices:{symbol}", json.dumps(market_price))


def _market(symbol: str, last_price: str, fetched_utc: str) -> dict:
    return {
        "symbol": symbol,
        "ticker_24hr": {"lastPrice": last_price},
        "fetched_utc": fetched_utc,
    }


# --------------------------------------------------------------------------- #
# NO_OPEN_POSITION behaviour                                                  #
# --------------------------------------------------------------------------- #


def test_no_open_position_explicit_state_when_paper_positions_empty(tmp_path: Path) -> None:
    cli = _cli()
    redis = FakeRedis()
    now = datetime(2026, 5, 21, 4, 0, 0, tzinfo=timezone.utc)
    _seed_paper_inputs(
        redis,
        paper_positions=[],
        paper_ledger={},
        paper_intents=[],
        paper_intents_held=[],
        market_price=_market("BTCUSDT", "100.00", "2026-05-21T04:00:00Z"),
        symbol="BTCUSDT",
    )
    payload = cli.run_once(
        symbols=("BTCUSDT",),
        redis_client=redis,
        write_artifacts=False,
        now=now,
    )
    assert payload["go_no_go"] == cli.GO_READY
    history_raw = redis.get("v2:paper:position_history:BTCUSDT")
    assert history_raw is not None
    history = json.loads(history_raw)
    assert history["position_state"] == "NO_OPEN_POSITION"
    assert history["side"] is None
    assert history["max_favorable_bps"] is None
    assert history["max_adverse_bps"] is None
    assert history["unrealized_bps"] is None
    assert history["accepted_intent_count"] == 0
    assert history["held_intent_count"] == 0
    assert history["block_reason_count"] == 0
    assert history["full_observation_consumption_allowed"] is False
    assert payload["open_position_symbol_count"] == 0
    assert payload["no_open_position_symbol_count"] == 1
    assert payload["no_open_position_state_token"] == "NO_OPEN_POSITION"


def test_no_open_position_does_not_synthesize_accepted_or_excursion_metrics(
    tmp_path: Path,
) -> None:
    cli = _cli()
    redis = FakeRedis()
    now = datetime(2026, 5, 21, 4, 0, 0, tzinfo=timezone.utc)
    # Even with a populated ledger of held + blocked + shadow rows, no
    # position row means the tracker MUST emit NO_OPEN_POSITION and
    # zero accepted.
    ledger = {
        "accepted": [],
        "held_by_paper_fill_gate": [
            {"symbol": "BTCUSDT", "ledger_action": "HELD"}
        ],
        "blocked": [
            {"symbol": "BTCUSDT", "block_reason": "STRICT_PAPER_FILL_GATE"}
        ],
        "shadow_observations": [
            {"symbol": "BTCUSDT", "paper_result": "SHADOW_OBSERVATION"}
        ],
    }
    _seed_paper_inputs(
        redis,
        paper_positions=[],
        paper_ledger=ledger,
        paper_intents=[],
        paper_intents_held=[],
        market_price=_market("BTCUSDT", "100.00", "2026-05-21T04:00:00Z"),
        symbol="BTCUSDT",
    )
    cli.run_once(
        symbols=("BTCUSDT",), redis_client=redis, write_artifacts=False, now=now
    )
    history = json.loads(redis.get("v2:paper:position_history:BTCUSDT"))
    assert history["position_state"] == "NO_OPEN_POSITION"
    assert history["accepted_intent_count"] == 0
    assert history["held_intent_count"] == 1
    assert history["shadow_observation_count"] == 1
    assert history["block_reason_count"] == 1
    assert history["block_reasons"] == ["STRICT_PAPER_FILL_GATE"]
    assert history["max_favorable_bps"] is None
    assert history["max_adverse_bps"] is None
    assert history["unrealized_bps"] is None
    assert history["no_synthesized_accepted_positions"] is True
    assert history["no_fabricated_excursion_metrics"] is True
    assert history["no_shadow_observations_counted_as_accepted"] is True


# --------------------------------------------------------------------------- #
# OPEN position MFE/MAE/unrealized                                            #
# --------------------------------------------------------------------------- #


def test_open_position_computes_mfe_mae_unrealized_and_carries_first_seen(
    tmp_path: Path,
) -> None:
    cli = _cli()
    redis = FakeRedis()
    now = datetime(2026, 5, 21, 4, 0, 0, tzinfo=timezone.utc)
    _seed_paper_inputs(
        redis,
        paper_positions=[
            {
                "intent_id": "i1",
                "symbol": "BTCUSDT",
                "side": "long",
                "entry_price": 100.0,
                "generated_utc": "2026-05-21T03:00:00Z",
            }
        ],
        paper_ledger={
            "accepted": [
                {"symbol": "BTCUSDT", "entry_price": 100.0, "intent_id": "i1"}
            ]
        },
        paper_intents=[],
        paper_intents_held=[],
        market_price=_market("BTCUSDT", "110.00", "2026-05-21T04:00:00Z"),
        symbol="BTCUSDT",
    )
    payload_first = cli.run_once(
        symbols=("BTCUSDT",), redis_client=redis, write_artifacts=False, now=now
    )
    history_first = json.loads(redis.get("v2:paper:position_history:BTCUSDT"))
    assert history_first["position_state"] == "OPEN_TRACKING"
    assert history_first["side"] == "long"
    assert history_first["entry_price_proxy"] == 100.0
    assert history_first["max_favorable_bps"] == pytest.approx(1000.0)
    assert history_first["max_adverse_bps"] == pytest.approx(0.0)
    assert history_first["unrealized_bps"] == pytest.approx(1000.0)
    assert history_first["accepted_intent_count"] == 1
    assert history_first["first_seen_utc"] == "2026-05-21T04:00:00Z"
    assert history_first["last_seen_utc"] == "2026-05-21T04:00:00Z"
    assert history_first["hold_time_seconds"] == pytest.approx(3600.0)

    # Second cycle a minute later: price drops below entry. MAE should
    # widen, MFE should remain pinned to the prior maximum, and
    # ``first_seen_utc`` should carry over while ``last_seen_utc``
    # advances.
    now_2 = now + timedelta(seconds=60)
    redis.set(
        f"v2:market:prices:BTCUSDT",
        json.dumps(_market("BTCUSDT", "95.00", "2026-05-21T04:01:00Z")),
    )
    cli.run_once(
        symbols=("BTCUSDT",),
        redis_client=redis,
        write_artifacts=False,
        now=now_2,
        cycle_count=2,
    )
    history_second = json.loads(redis.get("v2:paper:position_history:BTCUSDT"))
    assert history_second["first_seen_utc"] == "2026-05-21T04:00:00Z"
    assert history_second["last_seen_utc"] == "2026-05-21T04:01:00Z"
    assert history_second["max_favorable_bps"] == pytest.approx(1000.0)
    assert history_second["max_adverse_bps"] == pytest.approx(-500.0)
    assert history_second["unrealized_bps"] == pytest.approx(-500.0)


# --------------------------------------------------------------------------- #
# Intent counting policy                                                      #
# --------------------------------------------------------------------------- #


def test_shadow_and_held_intents_are_not_counted_as_accepted(tmp_path: Path) -> None:
    service = _service()
    counts = service.compute_intent_counts(
        symbol_upper="BTCUSDT",
        paper_ledger={
            "accepted": [
                {"symbol": "BTCUSDT"},
                {"symbol": "BTCUSDT", "paper_result": "SHADOW_OBSERVATION"},
                {"symbol": "BTCUSDT", "ledger_action": "HELD_BY_PAPER_FILL_GATE"},
            ],
            "held_by_paper_fill_gate": [{"symbol": "BTCUSDT"}],
            "blocked": [
                {"symbol": "BTCUSDT", "block_reason": "STRICT_PAPER_FILL_GATE"},
                {"symbol": "BTCUSDT", "reason": "STRICT_PAPER_FILL_GATE"},
            ],
            "shadow_observations": [{"symbol": "BTCUSDT"}],
        },
        paper_intents=[
            {"symbol": "BTCUSDT", "paper_result": "SHADOW"},
        ],
        paper_intents_held=[{"symbol": "BTCUSDT"}],
    )
    # accepted: exactly 1 (the bare accepted row, not the shadow/held
    # variants masquerading as accepted)
    assert counts.accepted_intent_count == 1
    # held: ledger 'accepted' row tagged HELD + ledger held_by_paper_fill_gate
    # + paper_intents_held list = 3
    assert counts.held_intent_count == 3
    # shadow: ledger 'accepted' row tagged SHADOW_OBSERVATION
    # + ledger shadow_observations + paper_intents shadow = 3
    assert counts.shadow_observation_count == 3
    # blocked: ledger 'blocked' list (2 rows)
    assert counts.block_reason_count == 2
    assert counts.block_reasons == ("STRICT_PAPER_FILL_GATE",)


def test_other_symbol_rows_are_ignored() -> None:
    service = _service()
    counts = service.compute_intent_counts(
        symbol_upper="BTCUSDT",
        paper_ledger={
            "accepted": [
                {"symbol": "ETHUSDT"},
                {"symbol": "SOLUSDT"},
            ]
        },
        paper_intents=[{"symbol": "ETHUSDT"}],
        paper_intents_held=[{"symbol": "ETHUSDT"}],
    )
    assert counts.accepted_intent_count == 0
    assert counts.held_intent_count == 0
    assert counts.shadow_observation_count == 0
    assert counts.block_reason_count == 0


# --------------------------------------------------------------------------- #
# Redis write allowlist                                                       #
# --------------------------------------------------------------------------- #


def test_only_allowed_v2_paper_keys_are_written() -> None:
    cli = _cli()
    redis = FakeRedis()
    _seed_paper_inputs(
        redis,
        paper_positions=[],
        paper_ledger={},
        paper_intents=[],
        paper_intents_held=[],
        market_price=_market("BTCUSDT", "100.00", "2026-05-21T04:00:00Z"),
        symbol="BTCUSDT",
    )
    cli.run_once(
        symbols=("BTCUSDT",),
        redis_client=redis,
        write_artifacts=False,
        now=datetime(2026, 5, 21, 4, 0, 0, tzinfo=timezone.utc),
    )
    written_keys = {entry[0] for entry in redis.write_log}
    # Seed keys (which we set ourselves) are filtered out — we only
    # want to see what the tracker WROTE on top.
    seeded = {
        "v2:paper:positions",
        "v2:paper:ledger",
        "v2:paper:intents",
        "v2:paper:intents_held_by_paper_fill_gate",
        "v2:market:prices:BTCUSDT",
    }
    tracker_writes = written_keys - seeded
    expected = {
        "v2:paper:position_price_track:BTCUSDT",
        "v2:paper:position_history:BTCUSDT",
        "v2:paper:position_history:heartbeat",
    }
    assert tracker_writes == expected
    forbidden_prefixes = (
        "order_intent:",
        "order_execution:",
        "trader:positions",
        "trainer_state:",
        "live_kill_switch",
    )
    for key in tracker_writes:
        for prefix in forbidden_prefixes:
            assert not key.startswith(prefix), key


def test_safe_redis_set_refuses_non_allowlisted_keys() -> None:
    service = importlib.import_module(
        "v2.backend.app.services.rl_core.position_price_tracking_recorder"
    )
    redis = FakeRedis()
    # Non-allowlisted key (even within v2:) must be refused.
    assert service.safe_redis_set(redis, "v2:paper:something_else:BTCUSDT", {"x": 1}) is False
    # Legacy key prefix must be refused too.
    assert service.safe_redis_set(redis, "order_intent:BTCUSDT", {"x": 1}) is False
    # Allowed keys still go through.
    assert service.safe_redis_set(
        redis, "v2:paper:position_history:BTCUSDT", {"x": 1}
    ) is True
    assert service.safe_redis_set(
        redis, "v2:paper:position_price_track:BTCUSDT", {"x": 1}
    ) is True
    assert service.safe_redis_set(
        redis, "v2:paper:position_history:heartbeat", {"x": 1}
    ) is True


# --------------------------------------------------------------------------- #
# Heartbeat / safety invariants                                               #
# --------------------------------------------------------------------------- #


def test_heartbeat_payload_pins_safety_invariants() -> None:
    cli = _cli()
    redis = FakeRedis()
    _seed_paper_inputs(
        redis,
        paper_positions=[],
        paper_ledger={},
        paper_intents=[],
        paper_intents_held=[],
        market_price=_market("BTCUSDT", "100.00", "2026-05-21T04:00:00Z"),
        symbol="BTCUSDT",
    )
    payload = cli.run_once(
        symbols=("BTCUSDT",),
        redis_client=redis,
        write_artifacts=False,
        now=datetime(2026, 5, 21, 4, 0, 0, tzinfo=timezone.utc),
    )
    heartbeat = json.loads(redis.get("v2:paper:position_history:heartbeat"))
    for view in (payload, heartbeat):
        assert view["live_gate"] == "blocked_human_only"
        assert view["live_symbols"] == []
        assert view["writes_legacy_redis"] is False
        assert view["writes_exchange_orders"] is False
        assert view["no_synthesized_accepted_positions"] is True
        assert view["no_fabricated_excursion_metrics"] is True
        assert view["no_shadow_observations_counted_as_accepted"] is True
        assert view["full_observation_consumption_allowed"] is False
    assert payload["places_real_order"] is False
    assert payload["leverage_changed"] is False
    assert payload["margin_mode_changed"] is False
    assert payload["raw_credential_in_payload"] == "NEVER"
    assert payload["may_authorize_live"] is False
    assert payload["may_override_strict_paper_fill_gate"] is False


# --------------------------------------------------------------------------- #
# Persistent-daemon loop                                                      #
# --------------------------------------------------------------------------- #


def test_persistent_loop_refreshes_heartbeat_each_cycle(monkeypatch) -> None:
    cli = _cli()
    redis = FakeRedis()
    _seed_paper_inputs(
        redis,
        paper_positions=[],
        paper_ledger={},
        paper_intents=[],
        paper_intents_held=[],
        market_price=_market("BTCUSDT", "100.00", "2026-05-21T04:00:00Z"),
        symbol="BTCUSDT",
    )
    sleep_calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    # Drive monotonic time so the loop terminates after a few cycles.
    monotonic_state = {"t": 0.0}

    def fake_monotonic() -> float:
        return monotonic_state["t"]

    real_monotonic = cli.time.monotonic
    cli.time.monotonic = fake_monotonic
    try:
        # Each fake_sleep call also advances monotonic time.
        def advancing_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)
            monotonic_state["t"] += max(seconds, 1.0)

        payload = cli.run_loop(
            symbols=("BTCUSDT",),
            redis_client=redis,
            total_seconds=10,
            max_seconds_per_session=10,
            cycle_interval_seconds=2,
            heartbeat_ttl_seconds=300,
            track_ttl_seconds=900,
            sleep=advancing_sleep,
            write_artifacts=False,
            now_factory=lambda: datetime(2026, 5, 21, 4, 0, 0, tzinfo=timezone.utc),
        )
    finally:
        cli.time.monotonic = real_monotonic
    assert payload["process_mode"] == "persistent_daemon"
    assert payload["cycle_count"] >= 2
    # Heartbeat key was set at least once per cycle.
    heartbeat_writes = [
        e for e in redis.write_log if e[0] == "v2:paper:position_history:heartbeat"
    ]
    assert len(heartbeat_writes) >= payload["cycle_count"]


def test_persistent_loop_refuses_when_heartbeat_ttl_too_short() -> None:
    cli = _cli()
    redis = FakeRedis()
    with pytest.raises(ValueError):
        cli.run_loop(
            symbols=("BTCUSDT",),
            redis_client=redis,
            total_seconds=10,
            max_seconds_per_session=10,
            cycle_interval_seconds=120,
            heartbeat_ttl_seconds=120,  # not enough headroom over interval
            track_ttl_seconds=300,
            sleep=lambda s: None,
            write_artifacts=False,
        )


# --------------------------------------------------------------------------- #
# Live override refusal                                                       #
# --------------------------------------------------------------------------- #


def test_main_refuses_live_gate_override(monkeypatch) -> None:
    cli = _cli()
    monkeypatch.setenv("V2_LIVE_GATE_OVERRIDE", "live_canary_operator_approved")
    with pytest.raises(SystemExit):
        cli.main(["--once"])


def test_main_accepts_blocked_human_only_override(monkeypatch, tmp_path) -> None:
    cli = _cli()
    monkeypatch.setenv("V2_LIVE_GATE_OVERRIDE", "blocked_human_only")
    # We don't want to actually hit redis or write the workspace.
    redis = FakeRedis()
    _seed_paper_inputs(
        redis,
        paper_positions=[],
        paper_ledger={},
        paper_intents=[],
        paper_intents_held=[],
        market_price=_market("BTCUSDT", "100.00", "2026-05-21T04:00:00Z"),
        symbol="BTCUSDT",
    )
    monkeypatch.setattr(cli, "_connect_redis", lambda: redis)
    monkeypatch.setattr(cli, "_write_status_mirrors", lambda payload: None)
    monkeypatch.setattr(cli, "_write_go_no_go", lambda token: None)
    rc = cli.main(["--once", "--symbols", "BTCUSDT"])
    assert rc == 0
