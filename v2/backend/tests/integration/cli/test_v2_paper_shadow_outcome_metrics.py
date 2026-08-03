"""Tests for V2 paper shadow-outcome metrics.

Paper-only. No real network. No torch. No legacy reads. No PnL impact.
"""
from __future__ import annotations

import datetime as dt
import importlib
import json
import sys


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


def _svc():
    return importlib.import_module(
        "v2.backend.app.services.paper_shadow_outcome_metrics.service"
    )


def _cli():
    return importlib.import_module("v2.backend.app.cli.v2_paper_shadow_outcome_metrics")


def test_read_v2_current_price_uses_market_first(monkeypatch) -> None:
    svc = _svc()
    r = FakeRedis()
    r.store["v2:market:prices:BTCUSDT"] = json.dumps({"ticker_24hr": {"lastPrice": "60000.5"}, "fetched_utc": "2026-05-18T19:00:00Z"})
    px, src, src_utc = svc.read_v2_current_price(r, "BTCUSDT")
    assert px == 60000.5
    assert src == svc.SOURCE_V2_MARKET_LAST
    assert src_utc == "2026-05-18T19:00:00Z"


def test_read_v2_current_price_falls_back_only_when_features_current(monkeypatch) -> None:
    svc = _svc()
    r = FakeRedis()
    r.store["v2:features:latest:BTCUSDT:1m"] = json.dumps({
        "feature_freshness_state": "CURRENT",
        "features": {"close_price": "55000.0"},
        "generated_at": "2026-05-18T19:01:00Z",
    })
    px, src, _ = svc.read_v2_current_price(r, "BTCUSDT")
    assert px == 55000.0
    assert src == svc.SOURCE_V2_FEATURES_FRESH_CLOSE


def test_read_v2_current_price_refuses_stale_features() -> None:
    svc = _svc()
    r = FakeRedis()
    r.store["v2:features:latest:BTCUSDT:1m"] = json.dumps({
        "feature_freshness_state": "STALE",
        "features": {"close_price": "55000.0"},
    })
    px, src, _ = svc.read_v2_current_price(r, "BTCUSDT")
    assert px is None
    assert src == svc.MISSING_CURRENT_PRICE_BLOCKER


def test_read_v2_current_price_emits_missing_blocker_when_no_inputs() -> None:
    svc = _svc()
    px, src, _ = svc.read_v2_current_price(FakeRedis(), "XRPUSDT")
    assert px is None
    assert src == svc.MISSING_CURRENT_PRICE_BLOCKER


def test_safe_redis_set_refuses_anything_outside_shadow_outcome_namespace() -> None:
    svc = _svc()
    r = FakeRedis()
    assert svc._safe_redis_set(r, "v2:paper:shadow_outcome:BTCUSDT", "x", ex=600) is True
    assert svc._safe_redis_set(r, "v2:paper:shadow_outcome:heartbeat", "x", ex=600) is True
    # Refuse anything else, including accepted-position keys and legacy.
    assert svc._safe_redis_set(r, "v2:paper:positions", "x", ex=600) is False
    assert svc._safe_redis_set(r, "v2:paper:ledger", "x", ex=600) is False
    assert svc._safe_redis_set(r, "v2:paper:heartbeat", "x", ex=600) is False
    assert svc._safe_redis_set(r, "prediction:BTCUSDT", "x", ex=600) is False
    assert svc._safe_redis_set(r, "signals:trading:primary", "x", ex=600) is False


def test_build_shadow_outcome_long_with_favourable_move_flags_false_block(monkeypatch) -> None:
    svc = _svc()
    r = FakeRedis()
    r.store["v2:market:prices:BTCUSDT"] = json.dumps({"ticker_24hr": {"lastPrice": "61000.0"}, "fetched_utc": "2026-05-18T19:30:00Z"})
    now = dt.datetime(2026, 5, 18, 19, 30, 0, tzinfo=dt.timezone.utc)
    outcome = svc.build_shadow_outcome(
        redis_client=r,
        symbol="BTCUSDT",
        side="long",
        decision_label=svc.LABEL_SHADOW,
        block_reason="UPSTREAM_PAPER_FILL_GATE_DENIED",
        shadow_entry_price=60000.0,
        shadow_entry_price_source="V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE",
        shadow_entry_price_utc="2026-05-18T19:00:00Z",
        prediction={"selected_action": "long"},
        now=now,
        fee_round_trip_bps=10.0,
        direction_consistency_threshold_bps=5.0,
    )
    assert outcome.decision_label == "SHADOW_OUTCOME_ONLY"
    # 60000 -> 61000 long: +1000/60000 ~ 166.67 bps; after 10 bps cost ~156.67 bps.
    assert outcome.missed_move_bps is not None and outcome.missed_move_bps > 100
    assert outcome.missed_move_after_cost_bps is not None and outcome.missed_move_after_cost_bps > 100
    assert outcome.direction_consistent_with_prediction is True
    assert outcome.no_trade_correct is False
    assert outcome.false_block_candidate is True
    assert outcome.time_since_shadow_seconds == 30 * 60
    assert outcome.classification_horizon_ready is True
    assert outcome.classification_blockers == []
    payload = outcome.as_payload()
    # Invariants on every payload row.
    assert payload["counted_as_accepted_position"] is False
    assert payload["counted_as_fill"] is False
    assert payload["affects_pnl_ledger"] is False
    assert payload["opens_paper_fill_gate"] is False
    assert payload["approves_real" if "approves_real" in payload else "approves_live"] is False
    assert payload["writes_legacy_redis"] is False
    assert payload["writes_exchange_orders"] is False
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["places_real_order"] is False


def test_build_shadow_outcome_long_with_adverse_move_flags_no_trade_correct(monkeypatch) -> None:
    svc = _svc()
    r = FakeRedis()
    r.store["v2:market:prices:BTCUSDT"] = json.dumps({
        "ticker_24hr": {"lastPrice": "59000.0"},
        "fetched_utc": "2026-05-18T19:30:00Z",
    })
    now = dt.datetime(2026, 5, 18, 19, 30, 0, tzinfo=dt.timezone.utc)
    outcome = svc.build_shadow_outcome(
        redis_client=r,
        symbol="BTCUSDT",
        side="long",
        decision_label=svc.LABEL_SHADOW,
        block_reason="UPSTREAM_PAPER_FILL_GATE_DENIED",
        shadow_entry_price=60000.0,
        shadow_entry_price_source="V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE",
        shadow_entry_price_utc="2026-05-18T19:00:00Z",
        prediction={"selected_action": "long"},
        now=now,
    )
    # Long shadow but price dropped 1000/60000 ~ -166.67 bps in favour-of-long terms.
    assert outcome.missed_move_bps is not None and outcome.missed_move_bps < -100
    assert outcome.direction_consistent_with_prediction is False
    assert outcome.no_trade_correct is True
    assert outcome.false_block_candidate is False
    assert outcome.classification_horizon_ready is True


def test_build_shadow_outcome_before_counterfactual_horizon_stays_unclassified() -> None:
    svc = _svc()
    r = FakeRedis()
    r.store["v2:market:prices:BTCUSDT"] = json.dumps({
        "ticker_24hr": {"lastPrice": "61000.0"},
        "fetched_utc": "2026-05-18T19:04:00Z",
    })
    now = dt.datetime(2026, 5, 18, 19, 4, 0, tzinfo=dt.timezone.utc)
    outcome = svc.build_shadow_outcome(
        redis_client=r,
        symbol="BTCUSDT",
        side="long",
        decision_label=svc.LABEL_SHADOW,
        block_reason="BLOCK_NO_EDGE",
        shadow_entry_price=60000.0,
        shadow_entry_price_source="V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE",
        shadow_entry_price_utc="2026-05-18T19:00:00Z",
        prediction={"selected_action": "long"},
        now=now,
        fee_round_trip_bps=10.0,
        direction_consistency_threshold_bps=5.0,
    )

    assert outcome.missed_move_after_cost_bps is not None and outcome.missed_move_after_cost_bps > 100
    assert outcome.direction_consistent_with_prediction is None
    assert outcome.no_trade_correct is None
    assert outcome.false_block_candidate is None
    assert outcome.classification_horizon_ready is False
    assert svc.IMMATURE_SHADOW_OUTCOME_FLAG in outcome.classification_blockers
    assert svc.CURRENT_PRICE_BEFORE_HORIZON_FLAG in outcome.classification_blockers
    assert svc.IMMATURE_SHADOW_OUTCOME_FLAG in outcome.stale_flags


def test_build_shadow_outcome_missing_current_price_emits_blocker() -> None:
    svc = _svc()
    r = FakeRedis()  # no market price, no features
    outcome = svc.build_shadow_outcome(
        redis_client=r,
        symbol="XRPUSDT",
        side="long",
        decision_label=svc.LABEL_SHADOW,
        block_reason="UPSTREAM_PAPER_FILL_GATE_DENIED",
        shadow_entry_price=2.50,
        shadow_entry_price_source="V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE",
        shadow_entry_price_utc="2026-05-18T19:00:00Z",
        prediction=None,
    )
    assert outcome.current_price is None
    assert outcome.current_price_source == svc.MISSING_CURRENT_PRICE_BLOCKER
    assert outcome.missed_move_bps is None
    assert outcome.missed_move_after_cost_bps is None
    assert outcome.no_trade_correct is None
    assert outcome.false_block_candidate is None
    assert svc.MISSING_CURRENT_PRICE_BLOCKER in outcome.missing_flags


def test_build_shadow_outcome_missing_shadow_entry_price_carries_missing_flag() -> None:
    svc = _svc()
    r = FakeRedis()
    r.store["v2:market:prices:XRPUSDT"] = json.dumps({"ticker_24hr": {"lastPrice": "2.55"}})
    outcome = svc.build_shadow_outcome(
        redis_client=r,
        symbol="XRPUSDT",
        side="long",
        decision_label=svc.LABEL_SHADOW,
        block_reason="UPSTREAM_PAPER_FILL_GATE_DENIED",
        shadow_entry_price=None,
        shadow_entry_price_source="MISSING_V2_MARKET_PRICE_FOR_FILL",
        shadow_entry_price_utc=None,
        prediction=None,
    )
    assert outcome.shadow_entry_price is None
    assert outcome.missed_move_bps is None
    assert "MISSING_SHADOW_ENTRY_PRICE" in outcome.missing_flags
    assert "MISSING_SHADOW_ENTRY_UTC" in outcome.missing_flags


def test_held_outcome_carries_block_reason_from_orchestrator_row() -> None:
    cli = _cli()
    svc = _svc()
    r = FakeRedis()
    r.store["v2:paper:intents_held_by_paper_fill_gate"] = json.dumps([{
        "symbol": "SOLUSDT",
        "selected_action_upstream": "hold",
        "paper_fill_gate_block_reasons": [
            "NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK",
            "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED",
        ],
        "entry_price": None,
        "entry_price_source": "MISSING_V2_MARKET_PRICE_FOR_FILL",
    }])
    r.store["v2:market:prices:SOLUSDT"] = json.dumps({"ticker_24hr": {"lastPrice": "85.0"}})
    payload = cli.run_once(redis_client=r)
    assert payload["outcome_count"] == 1
    out = payload["outcomes"][0]
    assert out["decision_label"] == svc.LABEL_HELD
    assert "NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK" in out["block_reason"]
    assert "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED" in out["block_reason"]
    assert out["counted_as_accepted_position"] is False
    assert out["affects_pnl_ledger"] is False


def test_cli_only_writes_shadow_outcome_keys() -> None:
    cli = _cli()
    r = FakeRedis()
    r.store["v2:paper:shadow_observations"] = json.dumps([{
        "symbol": "BTCUSDT",
        "side": "long",
        "decision": "SHADOW_OBSERVATION_ONLY",
        "entry_price": 60000.0,
        "entry_price_source": "V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE",
        "entry_price_utc": "2026-05-18T19:00:00Z",
    }])
    r.store["v2:market:prices:BTCUSDT"] = json.dumps({"ticker_24hr": {"lastPrice": "60500.0"}})
    cli.run_once(redis_client=r)
    keys_written = {key for (key, _v, _ex) in r.write_log}
    assert keys_written
    for key in keys_written:
        assert key == "v2:paper:shadow_outcome:heartbeat" or key.startswith("v2:paper:shadow_outcome:")
    # MUST NOT write to v2:paper:positions, v2:paper:ledger, etc.
    assert "v2:paper:positions" not in keys_written
    assert "v2:paper:ledger" not in keys_written
    assert "v2:paper:heartbeat" not in keys_written


def test_cli_does_not_open_paper_fill_gate_or_modify_accepted_positions() -> None:
    cli = _cli()
    r = FakeRedis()
    # Seed an empty v2:paper:positions so we can prove the CLI does not touch it.
    r.store["v2:paper:positions"] = json.dumps([])
    r.store["v2:paper:shadow_observations"] = json.dumps([{
        "symbol": "BTCUSDT",
        "side": "long",
        "decision": "SHADOW_OBSERVATION_ONLY",
        "entry_price": 60000.0,
        "entry_price_source": "V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE",
        "entry_price_utc": "2026-05-18T19:00:00Z",
    }])
    r.store["v2:market:prices:BTCUSDT"] = json.dumps({"ticker_24hr": {"lastPrice": "60500.0"}})
    cli.run_once(redis_client=r)
    # v2:paper:positions value MUST remain unchanged (empty list).
    assert json.loads(r.store["v2:paper:positions"]) == []
    # No write was attempted to v2:paper:positions.
    for key, _v, _ex in r.write_log:
        assert key != "v2:paper:positions"


def test_recorder_module_does_not_import_shadow_outcome_module() -> None:
    """The position price tracking recorder must not consume the shadow
    outcome service. Shadow outcomes are a separate, no-PnL surface.
    """
    import inspect
    recorder = importlib.import_module(
        "v2.backend.app.services.rl_core.position_price_tracking_recorder"
    )
    src = inspect.getsource(recorder)
    assert "paper_shadow_outcome_metrics" not in src
    assert "shadow_outcome" not in src.lower() or "v2:paper:shadow_outcome" not in src


def test_status_payload_pins_all_safety_invariants() -> None:
    cli = _cli()
    r = FakeRedis()
    payload = cli.run_once(redis_client=r)
    for field in (
        "schema_version",
        "generated_utc",
        "go_no_go",
        "outcome_count",
        "outcomes",
        "allowed_redis_writes",
        "counted_as_accepted_position",
        "counted_as_fill",
        "affects_pnl_ledger",
        "opens_paper_fill_gate",
        "no_synthetic_price",
        "no_legacy_redis_read",
        "writes_legacy_redis",
        "writes_exchange_orders",
        "approves_real",
        "approves_canary",
        "approves_legacy_shutdown",
        "approves_redis_trim",
        "live_gate",
        "live_symbols",
    ):
        assert field in payload, f"missing field {field}"
    assert payload["go_no_go"] == "V2_SHADOW_OBSERVATION_OUTCOME_METRICS_READY"
    assert payload["counted_as_accepted_position"] is False
    assert payload["counted_as_fill"] is False
    assert payload["affects_pnl_ledger"] is False
    assert payload["opens_paper_fill_gate"] is False
    assert payload["no_synthetic_price"] is True
    assert payload["no_legacy_redis_read"] is True
    assert payload["writes_legacy_redis"] is False
    assert payload["writes_exchange_orders"] is False
    assert payload["approves_real"] is False
    assert payload["approves_canary"] is False
    assert payload["approves_legacy_shutdown"] is False
    assert payload["approves_redis_trim"] is False
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []


def test_status_payload_summarizes_shadow_false_blocks_without_trade_implication() -> None:
    cli = _cli()
    r = FakeRedis()
    r.store["v2:paper:shadow_observations"] = json.dumps(
        [
            {
                "symbol": "BTCUSDT",
                "side": "long",
                "decision": "SHADOW_OBSERVATION_ONLY",
                "shadow_observation_reason": "BLOCK_NO_EDGE",
                "entry_price": 60000.0,
                "entry_price_source": "V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE",
                "entry_price_utc": "2026-05-18T19:00:00Z",
            },
            {
                "symbol": "ETHUSDT",
                "side": "long",
                "decision": "SHADOW_OBSERVATION_ONLY",
                "entry_price": 3000.0,
                "entry_price_source": "V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE",
                "entry_price_utc": "2026-05-18T19:00:00Z",
            },
            {
                "symbol": "XRPUSDT",
                "side": "short",
                "decision": "SHADOW_OBSERVATION_ONLY",
                "entry_price": 2.50,
                "entry_price_source": "V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE",
                "entry_price_utc": "2026-05-18T19:00:00Z",
            },
        ]
    )
    r.store["v2:market:prices:BTCUSDT"] = json.dumps(
        {"ticker_24hr": {"lastPrice": "61000.0"}, "fetched_utc": "2026-05-18T19:30:00Z"}
    )
    r.store["v2:market:prices:ETHUSDT"] = json.dumps(
        {"ticker_24hr": {"lastPrice": "2900.0"}, "fetched_utc": "2026-05-18T19:30:00Z"}
    )

    payload = cli.run_once(redis_client=r)

    assert payload["outcome_count"] == 3
    assert payload["shadow_horizon_ready_count"] == 2
    assert payload["shadow_horizon_pending_count"] == 1
    assert payload["classified_shadow_outcome_count"] == 2
    assert payload["shadow_false_block_candidate_count"] == 1
    assert payload["shadow_no_trade_correct_count"] == 1
    assert payload["shadow_unclassified_outcome_count"] == 1
    assert payload["shadow_false_block_candidate_rate"] == 0.5
    assert payload["outcomes"][0]["block_reason"] == "BLOCK_NO_EDGE"
    summary = payload["shadow_outcome_summary"]
    assert summary["counts_as_a_grade_evidence"] is False
    assert summary["a_grade_promotion_allowed"] is False
    assert summary["live_ready_implication"] is False
    assert summary["counted_as_fill"] is False
    assert summary["affects_pnl_ledger"] is False
    assert payload["counted_as_fill"] is False
    assert payload["affects_pnl_ledger"] is False


def test_no_exchange_mutation_surface_in_modules() -> None:
    import inspect
    svc = _svc()
    cli = _cli()
    forbidden = (
        "create" + "_order",
        "place" + "_order",
        "cancel" + "_order",
        "modify" + "_order",
        "set" + "_leverage",
        "set" + "_margin" + "_mode",
        "futures" + "_create" + "_order",
    )
    for mod in (svc, cli):
        src = inspect.getsource(mod)
        for token in forbidden:
            assert token not in src, f"forbidden token in module: {token}"


def test_no_torch_imported_in_shadow_outcome_modules() -> None:
    sys.modules.pop("torch", None)
    importlib.import_module(
        "v2.backend.app.services.paper_shadow_outcome_metrics.service"
    )
    importlib.import_module("v2.backend.app.cli.v2_paper_shadow_outcome_metrics")
    assert "torch" not in sys.modules


def test_no_pickle_deserialization_in_shadow_outcome_modules() -> None:
    import inspect
    for name in (
        "v2.backend.app.services.paper_shadow_outcome_metrics.service",
        "v2.backend.app.cli.v2_paper_shadow_outcome_metrics",
    ):
        mod = importlib.import_module(name)
        src = inspect.getsource(mod)
        assert "pickle.load" not in src
        assert "pickle.loads" not in src
