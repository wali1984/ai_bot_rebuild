"""Tests for the strict P0.2F paper-fill gate block-reason passthrough:
prediction -> orchestrator decision -> paper intent -> comparator.

Loop spec: ensure SOLUSDT (and any gate-blocked symbol) surfaces its exact
block reasons through every layer without changing gate behavior, without
loosening thresholds, and without producing fills.
"""
from __future__ import annotations

import importlib
import json
from typing import Any


class FakeRedis:
    """Minimal in-memory stand-in for the small subset of redis-py we use:
    get/set/scan_iter. Keys are strings; values are strings.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {
            "v2:live_gate:state": json.dumps({"live_gate": "blocked_human_only"})
        }

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        # ex (ttl) is ignored in the in-memory fake.
        self.store[key] = value
        return True

    def scan_iter(self, match: str | None = None, count: int = 500):  # noqa: ARG002
        if match is None:
            yield from list(self.store.keys())
            return
        # Trivial glob support for "v2:prediction:*"
        prefix = match.rstrip("*")
        for k in list(self.store.keys()):
            if match.endswith("*"):
                if k.startswith(prefix):
                    yield k
            elif k == match:
                yield k

    def type(self, key: str) -> str:
        return "string" if key in self.store else "none"

    def ttl(self, key: str) -> int:  # noqa: ARG002
        return 300


def _patch_connect(monkeypatch, module_path: str, fake: FakeRedis) -> None:
    mod = importlib.import_module(module_path)
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)


def _make_blocked_prediction(symbol: str, block_reasons: list[str]) -> dict[str, Any]:
    return {
        "prediction_id": f"pred_{symbol}",
        "feature_snapshot_id": f"fs_{symbol}",
        "symbol": symbol,
        "timeframe": "1m",
        "trainer_source": "v2_native_policy_cpu_forward_v1",
        "checkpoint_id": "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED",
        "checkpoint_blocker": "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED",
        "expected_move_bps": -3.0,
        "expected_move_after_cost_bps": -5.0,
        "confidence_raw": 0.4,
        "confidence_calibrated": 0.4,
        "feature_freshness_state": "fresh",
        "routes_to_orchestrator": True,
        "selected_action": "hold",
        "policy_action_probabilities": [0.5, 0.1, 0.1, 0.2, 0.1],
        "hedge_action_classification": "no_hedge",
        "paper_fill_gate_status": "BLOCKED_BY_TRAINER_OUTPUT_MALFORMED",
        "paper_fill_allowed": False,
        "paper_fill_gate_block_reasons": list(block_reasons),
        "generated_utc": "2026-05-17T05:00:00Z",
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }


def test_orchestrator_emits_held_by_paper_fill_gate_with_reasons(monkeypatch) -> None:
    fake = FakeRedis()
    reasons = ["BLOCK_NEGATIVE_EXPECTED_MOVE_AFTER_COST"]
    fake.store["v2:prediction:SOLUSDT:1m"] = json.dumps(
        _make_blocked_prediction("SOLUSDT", reasons)
    )
    orch = importlib.import_module("v2.backend.app.cli.v2_orchestrator_arbitration_loop")
    _patch_connect(monkeypatch, "v2.backend.app.cli.v2_orchestrator_arbitration_loop", fake)
    monkeypatch.setattr(orch, "_prediction_age_seconds", lambda _prediction: 5.0)
    status = orch.run_once()
    # Held passthrough is reflected in heartbeat status.
    assert status["predictions_held_by_paper_fill_gate"] == 1
    held = status["held_by_paper_fill_gate"]
    assert len(held) == 1
    assert held[0]["symbol"] == "SOLUSDT"
    assert held[0]["decision"] == "HELD_BY_PAPER_FILL_GATE"
    assert reasons[0] in held[0]["paper_fill_gate_block_reasons"]
    assert held[0]["places_real_order"] is False
    # The Redis-emitted decisions payload mirrors the same reasons.
    decisions = json.loads(fake.store["v2:orchestrator:decisions"])
    assert decisions["held_by_paper_fill_gate_count"] == 1
    assert reasons[0] in decisions["held_by_paper_fill_gate"][0]["paper_fill_gate_block_reasons"]
    assert status["live_gate"] == "blocked_human_only"
    assert status["live_symbols"] == []
    assert status["writes_legacy_redis"] is False


def test_orchestrator_ignores_rl_core_sidecar_predictions_for_primary_paper_signals(monkeypatch) -> None:
    fake = FakeRedis()
    fake.store["v2:prediction:rl_core:BTCUSDT:1m"] = json.dumps(
        {
            "prediction_id": "rl_core_sidecar_btc",
            "feature_snapshot_id": "fs_rl_core_btc",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "trainer_source": "V2_NATIVE_RL_CORE",
            "checkpoint_id": "rl_core_ckpt",
            "expected_move_bps": 100.0,
            "expected_move_after_cost_bps": 80.0,
            "confidence_raw": 0.8,
            "confidence_calibrated": 0.8,
            "routes_to_orchestrator": True,
            "selected_action": "long",
            "paper_fill_allowed": True,
            "generated_utc": "2026-05-17T05:00:00Z",
        }
    )
    orch = importlib.import_module("v2.backend.app.cli.v2_orchestrator_arbitration_loop")
    _patch_connect(monkeypatch, "v2.backend.app.cli.v2_orchestrator_arbitration_loop", fake)
    monkeypatch.setattr(orch, "_prediction_age_seconds", lambda _prediction: 5.0)

    status = orch.run_once()

    assert status["proposals_arbitrated"] == 0
    assert status["bucket_winners_count"] == 0
    assert json.loads(fake.store["v2:signals:paper"]) == []


def test_paper_loop_emits_held_intent_without_fill(monkeypatch) -> None:
    fake = FakeRedis()
    reasons = [
        "BLOCK_NEGATIVE_EXPECTED_MOVE_AFTER_COST",
        "BLOCK_FEATURE_FRESHNESS_NOT_CURRENT",
    ]
    # Seed orchestrator decisions with the held entry the paper loop reads.
    fake.store["v2:orchestrator:decisions"] = json.dumps({
        "schema_version": "v2_orchestrator_decisions_v2",
        "generated_utc": "2026-05-17T05:00:00Z",
        "considered_count": 0,
        "bucket_winners": [],
        "stale_proposal_ids": [],
        "held_by_paper_fill_gate": [{
            "symbol": "SOLUSDT",
            "timeframe": "1m",
            "prediction_id": "pred_SOLUSDT",
            "feature_snapshot_id": "fs_SOLUSDT",
            "selected_action": "hold",
            "paper_fill_gate_status": "BLOCKED_BY_TRAINER_OUTPUT_MALFORMED",
            "paper_fill_gate_block_reasons": reasons,
            "checkpoint_blocker": "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED",
            "decision": "HELD_BY_PAPER_FILL_GATE",
            "places_real_order": False,
            "generated_utc": "2026-05-17T05:00:00Z",
        }],
        "held_by_paper_fill_gate_count": 1,
    })
    # No paper signals -> no fills attempted.
    fake.store["v2:signals:paper"] = json.dumps([])
    _patch_connect(monkeypatch, "v2.backend.app.cli.v2_trade_management_paper_loop", fake)
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    status = paper.run_once()
    assert status["intents_held_by_paper_fill_gate"] == 1
    held_intent = status["held_by_paper_fill_gate"][0]
    assert held_intent["symbol"] == "SOLUSDT"
    assert held_intent["paper_fill_gate_block_reasons"] == reasons
    assert held_intent["places_real_order"] is False
    assert held_intent["decision"] == "HELD_BY_PAPER_FILL_GATE"
    # Confirm Redis got the held-intents key under v2:* and no positions
    # were created for the held symbol.
    held_raw = fake.store["v2:paper:intents_held_by_paper_fill_gate"]
    assert json.loads(held_raw)[0]["paper_fill_gate_block_reasons"] == reasons
    positions = json.loads(fake.store["v2:paper:positions"])
    assert positions == []
    assert status["places_real_order"] is False
    assert status["writes_legacy_redis"] is False
    assert status["live_gate"] == "blocked_human_only"
    assert status["live_symbols"] == []


def test_paper_loop_reads_per_symbol_paper_signal_keys(monkeypatch) -> None:
    fake = FakeRedis()
    fake.store["v2:signals:paper"] = json.dumps([])
    fake.store["v2:signals:paper:BTCUSDT:1m"] = json.dumps(
        {
                "signal_id": "signal-btc-1m",
                "prediction_id": "prediction-btc-1m",
                "feature_snapshot_id": "fs-btc-1m",
                "risk_decision_id": "risk-btc-1m",
                "orchestrator_decision_id": "orch-btc-1m",
            "symbol": "BTCUSDT",
            "timeframe": "15m",  # Phase 3 entry gate allows 15m/1h/4h; 1m blocked by default
            "side": "long",
                "expected_move_after_cost_bps": 20.0,
                "confidence_calibrated": 0.66,
                "bid_ask_spread_bps": 1.2,
                "slippage_bps": 0.8,
                "market_state_id": "mstate_btc_1m",
            "market_state_integrity_score": 95.0,
            "valid_for_paper": True,
            "market_state_reject_reasons": [],
            "paper_fill_allowed": True,
            "paper_fill_gate_status": "PAPER_FILL_ALLOWED",
        }
    )
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(
        {
            "ticker_24hr": {"lastPrice": "100.0"},
            "fetched_utc": "2026-06-08T21:00:00Z",
        }
    )
    fake.store["v2:portfolio:state"] = json.dumps(
        {
            "equity": 10_000.0,
            "available_margin": 10_000.0,
            "wallet_balance": 10_000.0,
        }
    )
    _patch_connect(monkeypatch, "v2.backend.app.cli.v2_trade_management_paper_loop", fake)
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")

    status = paper.run_once()

    assert status["paper_signals_seen"] == 1
    assert status["intents_built"] == 1
    assert status["intents_accepted"] == 1
    ledger = json.loads(fake.store["v2:paper:ledger"])
    assert ledger["accepted_count"] == 1
    assert ledger["accepted"][0]["signal_id"] == "signal-btc-1m"
    assert ledger["accepted"][0]["prediction_id"] == "prediction-btc-1m"
    assert ledger["accepted"][0]["intent_id"] == "signal-btc-1m"
    assert ledger["accepted"][0]["source_intent_id"] == "signal-btc-1m"
    assert ledger["accepted"][0]["risk_decision_id"] == "risk-btc-1m"
    assert ledger["accepted"][0]["orchestrator_decision_id"] == "orch-btc-1m"
    assert ledger["accepted"][0]["paper_fill_allowed"] is True
    assert ledger["accepted"][0]["places_real_order"] is False
    assert status["places_real_order"] is False
    assert status["writes_legacy_redis"] is False


def test_paper_loop_skips_stale_per_symbol_paper_signal_keys() -> None:
    fake = FakeRedis()
    fake.store["v2:signals:paper"] = json.dumps([])
    fake.store["v2:signals:paper:BTCUSDT:1m"] = json.dumps(
        {
            "signal_id": "signal-stale-btc-1m",
            "prediction_id": "prediction-stale-btc-1m",
            "feature_snapshot_id": "fs-stale-btc-1m",
            "risk_decision_id": "risk-stale-btc-1m",
            "orchestrator_decision_id": "orch-stale-btc-1m",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "side": "long",
            "expected_move_after_cost_bps": 20.0,
            "confidence_calibrated": 0.66,
            "market_state_id": "mstate_stale_btc_1m",
            "market_state_integrity_score": 95.0,
            "valid_for_paper": True,
            "paper_fill_allowed": True,
            "paper_fill_gate_status": "PAPER_FILL_ALLOWED",
            "generated_est": "2000-01-01T00:00:00-05:00",
        }
    )
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")

    assert paper._read_paper_signals(fake) == []


def test_paper_loop_dedupes_aggregate_and_per_symbol_signal_by_prediction_id() -> None:
    fake = FakeRedis()
    aggregate = {
        "signal_id": "signal-aggregate",
        "prediction_id": "prediction-shared",
        "risk_decision_id": "risk-shared",
        "orchestrator_decision_id": "orch-shared",
        "winner_proposal_id": "winner-shared",
        "feature_snapshot_id": "fs-shared",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "expected_move_after_cost_bps": 20.0,
        "confidence_calibrated": 0.66,
        "market_state_id": "mstate-shared",
        "market_state_integrity_score": 95.0,
        "valid_for_paper": True,
        "paper_fill_allowed": True,
        "paper_fill_gate_status": "PAPER_FILL_ALLOWED",
        "generated_utc": "2026-06-19T10:00:00Z",
    }
    per_symbol = {
        **aggregate,
        "signal_id": "signal-per-symbol",
        "winner_proposal_id": None,
    }
    fake.store["v2:signals:paper"] = json.dumps([aggregate])
    fake.store["v2:signals:paper:BTCUSDT:1m"] = json.dumps(per_symbol)
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")

    rows = paper._read_paper_signals(fake)  # noqa: SLF001

    assert len(rows) == 1
    assert rows[0]["prediction_id"] == "prediction-shared"
    assert rows[0]["signal_id"] == "signal-aggregate"


def test_comparator_attaches_passthrough_integrity_note() -> None:
    comp = importlib.import_module("v2.backend.app.cli.v2_production_equivalence_comparator")
    reasons = ["BLOCK_NEGATIVE_EXPECTED_MOVE_AFTER_COST"]
    per_symbol = [{
        "symbol": "SOLUSDT",
        "timeframe": "1m",
        "legacy": {"exists": True, "action": "open_long"},
        "v2": {
            "exists": True,
            "selected_action": "hold",
            "paper_fill_allowed": False,
            "paper_fill_gate_block_reasons": reasons,
        },
        "match": False,
        "notes": [],
    }]
    orch_held = [{
        "symbol": "SOLUSDT",
        "paper_fill_gate_block_reasons": reasons,
    }]
    paper_held = [{
        "symbol": "SOLUSDT",
        "paper_fill_gate_block_reasons": reasons,
    }]
    comp._attach_held_passthrough(per_symbol, orch_held, paper_held)
    notes = per_symbol[0]["notes"]
    passthrough_note = next(
        (n for n in notes if n.startswith("block_reasons_passthrough:")), None
    )
    assert passthrough_note is not None
    body = json.loads(passthrough_note.split("block_reasons_passthrough:", 1)[1])
    assert body["prediction"] == reasons
    assert body["orchestrator_held"] == reasons
    assert body["paper_intent_held"] == reasons
    assert body["orchestrator_matches_prediction"] is True
    assert body["paper_intent_matches_prediction"] is True


def test_comparator_flags_missing_passthrough_when_layer_drops_reasons() -> None:
    comp = importlib.import_module("v2.backend.app.cli.v2_production_equivalence_comparator")
    reasons = ["BLOCK_FEATURE_FRESHNESS_NOT_CURRENT"]
    per_symbol = [{
        "symbol": "SOLUSDT",
        "timeframe": "1m",
        "legacy": {"exists": True, "action": "open_long"},
        "v2": {
            "exists": True,
            "selected_action": "hold",
            "paper_fill_allowed": False,
            "paper_fill_gate_block_reasons": reasons,
        },
        "match": False,
        "notes": [],
    }]
    # Orchestrator did NOT pass through any held entry.
    comp._attach_held_passthrough(per_symbol, [], [])
    body = json.loads(per_symbol[0]["notes"][-1].split("block_reasons_passthrough:", 1)[1])
    assert body["prediction"] == reasons
    assert body["orchestrator_emitted"] is False
    assert body["paper_intent_emitted"] is False
    assert body["orchestrator_matches_prediction"] is False
    assert body["paper_intent_matches_prediction"] is False


def test_no_old_redis_writes_in_held_passthrough(monkeypatch) -> None:
    fake = FakeRedis()
    fake.store["v2:prediction:SOLUSDT:1m"] = json.dumps(
        _make_blocked_prediction("SOLUSDT", ["BLOCK_LIVE_GATE_NOT_BLOCKED"])
    )
    _patch_connect(monkeypatch, "v2.backend.app.cli.v2_orchestrator_arbitration_loop", fake)
    orch = importlib.import_module("v2.backend.app.cli.v2_orchestrator_arbitration_loop")
    orch.run_once()
    # All new keys must be under v2: namespace.
    for k in fake.store.keys():
        assert k.startswith("v2:"), f"Unexpected non-v2 redis write: {k}"


def test_gate_block_reasons_in_continuous_remediation_gap_matrix(monkeypatch) -> None:
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[5]
    path = root / "claude_worklog/tools/v2_continuous_legacy_log_to_rebuild_remediation.py"
    spec = importlib.util.spec_from_file_location("v2_cont_remed_mod", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    enriched = {
        "per_symbol": [{
            "symbol": "SOLUSDT",
            "mismatch_causes_classified": ["v2_paper_fill_gate_blocked"],
            "match": False,
            "v2_action": "hold",
            "v2_paper_fill_allowed": False,
            "v2_paper_fill_gate_block_reasons": ["BLOCK_NEGATIVE_EXPECTED_MOVE_AFTER_COST"],
            "legacy_redis_action": "OPEN_LONG",
            "legacy_log_action": None,
        }]
    }
    gaps = mod._classify_gaps(enriched)
    assert len(gaps) == 1
    assert gaps[0]["cause"] == "v2_paper_fill_gate_blocked"
    assert gaps[0]["gap_id"] == "paper_fill_gate_blocked_with_reason"
    assert gaps[0]["paper_fill_gate_block_reasons"] == ["BLOCK_NEGATIVE_EXPECTED_MOVE_AFTER_COST"]
    assert gaps[0]["severity"] == "NO_ACTION_REQUIRED_SAFE_BLOCK"
