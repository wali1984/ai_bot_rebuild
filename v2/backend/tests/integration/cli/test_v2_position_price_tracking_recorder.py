"""Tests for V2 paper position price-tracking recorder."""
from __future__ import annotations

import importlib
import json


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


def _recorder():
    return importlib.import_module(
        "v2.backend.app.services.rl_core.position_price_tracking_recorder"
    )


def _cli():
    return importlib.import_module("v2.backend.app.cli.v2_position_price_tracking_recorder")


def _aggregator():
    return importlib.import_module(
        "v2.backend.app.services.rl_core.position_history_aggregator"
    )


def _position(entry_price=None) -> dict:
    row = {
        "intent_id": "i1",
        "symbol": "BTCUSDT",
        "side": "long",
        "generated_utc": "2026-05-18T05:00:00Z",
        "paper_only": True,
        "places_real_order": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }
    if entry_price is not None:
        row["entry_price"] = entry_price
    return row


def _market(last_price: str = "105.00") -> dict:
    return {
        "symbol": "BTCUSDT",
        "ticker_24hr": {"lastPrice": last_price},
        "fetched_utc": "2026-05-18T05:01:00Z",
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }


def test_missing_entry_price_is_explicit_and_does_not_compute_excursions() -> None:
    mod = _recorder()
    track = mod.build_position_track(
        symbol="BTCUSDT",
        paper_positions=[_position()],
        paper_ledger={},
        market_price=_market(),
    )
    payload = track.as_payload()
    assert payload["position_state"] == "OPEN_MISSING_PRICE_INPUTS"
    assert payload["latest_price"] == 105.0
    assert payload["entry_price"] is None
    assert payload["mfe_bps"] is None
    assert payload["mae_bps"] is None
    assert payload["roe_bps"] is None
    assert "MISSING_ENTRY_PRICE" in payload["missing_flags"]
    assert payload["no_fake_price_tracks"] is True


def test_valid_long_position_computes_mfe_mae_roe_from_v2_prices() -> None:
    mod = _recorder()
    track = mod.build_position_track(
        symbol="BTCUSDT",
        paper_positions=[_position(entry_price=100.0)],
        paper_ledger={},
        market_price=_market("105.00"),
    )
    payload = track.as_payload()
    assert payload["position_state"] == "OPEN_TRACKING"
    assert payload["entry_price"] == 100.0
    assert payload["latest_price"] == 105.0
    assert payload["min_price_since_entry"] == 100.0
    assert payload["max_price_since_entry"] == 105.0
    assert payload["mfe_bps"] == 500.0
    assert payload["mae_bps"] == 0.0
    assert payload["roe_bps"] == 500.0


def test_previous_track_extends_min_max_without_resetting() -> None:
    mod = _recorder()
    previous = {
        "symbol": "BTCUSDT",
        "entry_price": 100.0,
        "min_price_since_entry": 98.0,
        "max_price_since_entry": 103.0,
        "source": "V2_POSITION_PRICE_TRACKING_RECORDER",
        "no_fake_price_tracks": True,
    }
    track = mod.build_position_track(
        symbol="BTCUSDT",
        paper_positions=[_position(entry_price=100.0)],
        paper_ledger={},
        market_price=_market("105.00"),
        previous_track=previous,
    )
    assert track.min_price_since_entry == 98.0
    assert track.max_price_since_entry == 105.0
    assert track.mfe_bps == 500.0
    assert track.mae_bps == -200.0


def test_flat_symbol_emits_flat_state_without_fake_prices() -> None:
    mod = _recorder()
    track = mod.build_position_track(
        symbol="SOLUSDT",
        paper_positions=[_position(entry_price=100.0)],
        paper_ledger={},
        market_price=_market("105.00"),
    )
    payload = track.as_payload()
    assert payload["position_state"] == "FLAT"
    assert payload["entry_price"] is None
    assert payload["latest_price"] is None
    assert "FLAT_NO_OPEN_POSITION" in payload["missing_flags"]


def test_safe_redis_set_refuses_old_and_unrelated_keys() -> None:
    mod = _recorder()
    fake = FakeRedis()
    assert mod.safe_redis_set(fake, "v2:paper:position_price_track:BTCUSDT", {"ok": True})
    assert mod.safe_redis_set(fake, "v2:paper:position_history:BTCUSDT", {"ok": True})
    assert mod.safe_redis_set(fake, "v2:paper:position_history:heartbeat", {"ok": True})
    assert not mod.safe_redis_set(fake, "prediction:BTCUSDT", {"bad": True})
    assert not mod.safe_redis_set(fake, "v2:altdata:symbol_score:BTCUSDT", {"bad": True})


def test_cli_writes_only_allowed_v2_position_history_keys() -> None:
    cli = _cli()
    fake = FakeRedis()
    fake.store["v2:paper:positions"] = json.dumps([_position()])
    fake.store["v2:paper:ledger"] = json.dumps({})
    fake.store["v2:paper:intents"] = json.dumps([])
    fake.store["v2:paper:intents_held_by_paper_fill_gate"] = json.dumps([])
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market())
    payload = cli.run_once(
        symbols=("BTCUSDT",),
        redis_client_override=fake,
        write_redis=True,
    )
    assert payload["go_no_go"] == "V2_POSITION_PRICE_TRACKING_RECORDER_READY"
    keys = sorted(k for k, _v, _ex in fake.write_log)
    assert keys == [
        "v2:paper:position_history:BTCUSDT",
        "v2:paper:position_history:heartbeat",
        "v2:paper:position_price_track:BTCUSDT",
    ]
    assert payload["writes_legacy_redis"] is False
    assert payload["writes_exchange_orders"] is False
    assert payload["live_symbols"] == []


def test_aggregator_consumes_v2_price_track_when_present() -> None:
    rec = _recorder()
    agg = _aggregator()
    track = rec.build_position_track(
        symbol="BTCUSDT",
        paper_positions=[_position(entry_price=100.0)],
        paper_ledger={},
        market_price=_market("105.00"),
    ).as_payload()
    history = agg.aggregate_symbol(
        symbol="BTCUSDT",
        paper_positions=[_position(entry_price=100.0)],
        paper_intents=[],
        paper_intents_held=[],
        paper_ledger={},
        position_price_track=track,
    )
    assert history.mfe_bps_v2 == 500.0
    assert history.mae_bps_v2 == 0.0
    assert history.roe_bps_v2 == 500.0
    assert history.mfe_source == "V2_POSITION_PRICE_TRACKING_RECORDER"
    assert history.mae_source == "V2_POSITION_PRICE_TRACKING_RECORDER"
    assert history.roe_source == "V2_POSITION_PRICE_TRACKING_RECORDER"


# ---------------------------------------------------------------------------
# V2_POSITION_PRICE_TRACKING_ENTRY_PRICE_AND_EXIT_HISTORY_BURNDOWN_READY
# ---------------------------------------------------------------------------


def test_entry_price_recovered_from_paper_ledger_accepted_fill_price() -> None:
    mod = _recorder()
    ledger = {
        "accepted": [
            {"intent_id": "i1", "symbol": "BTCUSDT", "fill_price": 100.0},
        ],
        "blocked": [],
        "held_by_paper_fill_gate": [],
    }
    track = mod.build_position_track(
        symbol="BTCUSDT",
        paper_positions=[_position()],
        paper_ledger=ledger,
        market_price=_market("105.00"),
    )
    payload = track.as_payload()
    assert payload["position_state"] == "OPEN_TRACKING"
    assert payload["entry_price"] == 100.0
    assert payload["entry_price_source"] == "V2_PAPER_LEDGER_ACCEPTED"
    assert payload["roe_bps"] == 500.0
    assert payload["mfe_bps"] == 500.0
    assert "MISSING_ENTRY_PRICE" not in payload["missing_flags"]


def test_entry_price_recovered_from_paper_intents_fill_price() -> None:
    mod = _recorder()
    track = mod.build_position_track(
        symbol="BTCUSDT",
        paper_positions=[_position()],
        paper_ledger={},
        market_price=_market("105.00"),
        paper_intents=[
            {"intent_id": "i1", "symbol": "BTCUSDT", "fill_price": 100.0},
        ],
    )
    payload = track.as_payload()
    assert payload["entry_price"] == 100.0
    assert payload["entry_price_source"] == "V2_PAPER_INTENTS"
    assert payload["roe_bps"] == 500.0


def test_entry_price_recovered_from_ledger_last_closed_position() -> None:
    mod = _recorder()
    ledger = {
        "last_closed_position": {
            "symbol": "BTCUSDT",
            "entry_price": 100.0,
            "exit_price": 110.0,
            "closed_at": "2026-05-18T06:00:00Z",
        }
    }
    track = mod.build_position_track(
        symbol="BTCUSDT",
        paper_positions=[_position()],
        paper_ledger=ledger,
        market_price=_market("105.00"),
    )
    payload = track.as_payload()
    assert payload["entry_price"] == 100.0
    assert payload["entry_price_source"] == "V2_PAPER_LEDGER_LAST_CLOSED_POSITION"


def test_entry_price_source_marks_missing_when_no_v2_evidence_present() -> None:
    mod = _recorder()
    track = mod.build_position_track(
        symbol="BTCUSDT",
        paper_positions=[_position()],
        paper_ledger={},
        market_price=_market("105.00"),
    )
    payload = track.as_payload()
    assert payload["entry_price"] is None
    assert payload["entry_price_source"] == "MISSING_ENTRY_PRICE_FROM_V2_PAPER_INPUTS"
    assert "MISSING_ENTRY_PRICE" in payload["missing_flags"]


def test_realized_exit_recovered_from_paper_ledger_close_event() -> None:
    mod = _recorder()
    ledger = {
        "last_closed_position": {
            "symbol": "BTCUSDT",
            "entry_price": 100.0,
            "exit_price": 110.0,
            "closed_at": "2026-05-18T06:00:00Z",
            "ledger_action": "PAPER_POSITION_CLOSED",
        }
    }
    track = mod.build_position_track(
        symbol="BTCUSDT",
        paper_positions=[],
        paper_ledger=ledger,
        market_price=_market("105.00"),
    )
    payload = track.as_payload()
    assert payload["position_state"] == "CLOSED_REALIZED"
    assert payload["realized_exit_price"] == 110.0
    assert payload["realized_exit_source"] == "V2_PAPER_LEDGER_LAST_CLOSED_POSITION"


def test_realized_exit_recovered_from_close_event_with_carryover_entry() -> None:
    mod = _recorder()
    previous = {
        "symbol": "BTCUSDT",
        "entry_price": 100.0,
        "min_price_since_entry": 99.0,
        "max_price_since_entry": 108.0,
        "side": "long",
        "source": "V2_POSITION_PRICE_TRACKING_RECORDER",
        "no_fake_price_tracks": True,
    }
    ledger = {
        "closed": [
            {
                "symbol": "BTCUSDT",
                "ledger_action": "PAPER_POSITION_CLOSED",
                "paper_result": "POSITION_CLOSED_PAPER_ONLY",
                "exit_price": 110.0,
                "closed_at": "2026-05-18T06:00:00Z",
            }
        ]
    }
    track = mod.build_position_track(
        symbol="BTCUSDT",
        paper_positions=[],
        paper_ledger=ledger,
        market_price=_market("105.00"),
        previous_track=previous,
    )
    payload = track.as_payload()
    assert payload["position_state"] == "CLOSED_REALIZED"
    assert payload["realized_exit_price"] == 110.0
    assert payload["realized_exit_source"] == "V2_PAPER_LEDGER_CLOSE_EVENT"
    assert payload["entry_price"] == 100.0
    assert payload["entry_price_source"] == "V2_PREVIOUS_TRACK_RECORDER_CARRYOVER"
    assert payload["roe_bps"] == 1000.0
    assert payload["mfe_bps"] == 1000.0
    assert payload["mae_bps"] == -100.0


def test_realized_exit_persists_via_previous_track_when_symbol_flat() -> None:
    mod = _recorder()
    previous = {
        "symbol": "BTCUSDT",
        "entry_price": 100.0,
        "realized_exit_price": 110.0,
        "realized_exit_utc": "2026-05-18T06:00:00Z",
        "source": "V2_POSITION_PRICE_TRACKING_RECORDER",
        "no_fake_price_tracks": True,
    }
    track = mod.build_position_track(
        symbol="BTCUSDT",
        paper_positions=[],
        paper_ledger={},
        market_price=_market("105.00"),
        previous_track=previous,
    )
    payload = track.as_payload()
    assert payload["position_state"] == "CLOSED_REALIZED"
    assert payload["realized_exit_price"] == 110.0
    assert payload["realized_exit_source"] == "V2_PREVIOUS_TRACK_RECORDER_CARRYOVER"
    assert payload["entry_price"] == 100.0


def test_flat_without_any_exit_history_remains_flat() -> None:
    mod = _recorder()
    track = mod.build_position_track(
        symbol="SOLUSDT",
        paper_positions=[],
        paper_ledger={},
        market_price=_market("105.00"),
    )
    payload = track.as_payload()
    assert payload["position_state"] == "FLAT"
    assert payload["realized_exit_price"] is None
    assert payload["realized_exit_source"] == "NO_REALIZED_EXIT_RECORDED_YET"


def test_cli_emits_burndown_partial_progress_when_entry_recovered() -> None:
    cli = _cli()
    fake = FakeRedis()
    fake.store["v2:paper:positions"] = json.dumps([_position()])
    fake.store["v2:paper:ledger"] = json.dumps(
        {
            "accepted": [
                {"intent_id": "i1", "symbol": "BTCUSDT", "fill_price": 100.0},
            ],
            "blocked": [],
            "held_by_paper_fill_gate": [],
        }
    )
    fake.store["v2:paper:intents"] = json.dumps([])
    fake.store["v2:paper:intents_held_by_paper_fill_gate"] = json.dumps([])
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market())
    payload = cli.run_once(
        symbols=("BTCUSDT",),
        redis_client_override=fake,
        write_redis=False,
    )
    assert (
        payload["burndown_go_no_go"]
        == "V2_POSITION_PRICE_TRACKING_ENTRY_EXIT_HISTORY_BURNDOWN_READY_PARTIAL_PROGRESS"
    )
    assert payload["symbols_with_entry_recovered"] == ["BTCUSDT"]
    assert payload["symbols_still_blocked"] == []
    assert payload["any_entry_recovered"] is True
    assert payload["writes_legacy_redis"] is False


def test_cli_emits_burndown_blocked_when_no_entry_or_exit_evidence() -> None:
    cli = _cli()
    fake = FakeRedis()
    fake.store["v2:paper:positions"] = json.dumps([_position()])
    fake.store["v2:paper:ledger"] = json.dumps({})
    fake.store["v2:paper:intents"] = json.dumps([])
    fake.store["v2:paper:intents_held_by_paper_fill_gate"] = json.dumps([])
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market())
    payload = cli.run_once(
        symbols=("BTCUSDT",),
        redis_client_override=fake,
        write_redis=False,
    )
    assert (
        payload["burndown_go_no_go"]
        == "V2_POSITION_PRICE_TRACKING_ENTRY_EXIT_HISTORY_BURNDOWN_BLOCKED"
    )
    assert payload["symbols_with_entry_recovered"] == []
    assert payload["symbols_still_blocked"] == ["BTCUSDT"]


def test_recorder_never_writes_unrelated_keys_even_with_close_event() -> None:
    cli = _cli()
    fake = FakeRedis()
    fake.store["v2:paper:positions"] = json.dumps([])
    fake.store["v2:paper:ledger"] = json.dumps(
        {
            "closed": [
                {
                    "symbol": "BTCUSDT",
                    "exit_price": 110.0,
                    "ledger_action": "PAPER_POSITION_CLOSED",
                    "closed_at": "2026-05-18T06:00:00Z",
                }
            ]
        }
    )
    fake.store["v2:paper:intents"] = json.dumps([])
    fake.store["v2:paper:intents_held_by_paper_fill_gate"] = json.dumps([])
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market())
    cli.run_once(symbols=("BTCUSDT",), redis_client_override=fake, write_redis=True)
    keys = sorted(k for k, _v, _ex in fake.write_log)
    assert keys == [
        "v2:paper:position_history:BTCUSDT",
        "v2:paper:position_history:heartbeat",
        "v2:paper:position_price_track:BTCUSDT",
    ]


def test_heartbeat_surfaces_per_symbol_provenance_maps() -> None:
    mod = _recorder()
    track = mod.build_position_track(
        symbol="BTCUSDT",
        paper_positions=[_position(entry_price=100.0)],
        paper_ledger={},
        market_price=_market("105.00"),
    )
    hb = mod.build_heartbeat_payload({"BTCUSDT": track})
    assert hb["entry_price_source_by_symbol"]["BTCUSDT"] == "V2_PAPER_POSITION_ROW"
    assert hb["realized_exit_source_by_symbol"]["BTCUSDT"] == "NO_REALIZED_EXIT_RECORDED_YET"
    assert hb["realized_exit_price_by_symbol"]["BTCUSDT"] is None
