"""Tests for V2 paper position acceptance-state schema normalization.

Codex required: v2:paper:positions must carry ONLY accepted paper fills
(paper_fill_allowed=true). Intents that pass local pre-trade/fee/churn
gates but whose upstream paper-fill gate withheld the fill MUST land in
v2:paper:shadow_observations only when runtime market evidence is present,
and NEVER feed accepted-position MFE/MAE/ROE. Missing runtime price/spread
evidence fails closed into blocked[]. Held intents from the orchestrator
stay in their own key.

Paper-only. No real network. No torch. No legacy reads.
"""
from __future__ import annotations

import importlib
import json
import sys
from datetime import UTC, datetime, timedelta


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


def _mod():
    return importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")


def _binding_pit_fields() -> dict[str, object]:
    decision = datetime.now(UTC)
    current_15m_open = decision.replace(
        minute=(decision.minute // 15) * 15,
        second=0,
        microsecond=0,
    )
    feature_cutoff = current_15m_open - timedelta(minutes=15)
    available_at = decision - timedelta(seconds=2)
    return {
        "decision_time": decision.isoformat().replace("+00:00", "Z"),
        "entry_feature_decision_time": decision.isoformat().replace("+00:00", "Z"),
        "feature_cutoff": feature_cutoff.isoformat().replace("+00:00", "Z"),
        "entry_feature_cutoff": feature_cutoff.isoformat().replace("+00:00", "Z"),
        "available_at": available_at.isoformat().replace("+00:00", "Z"),
        "entry_feature_available_at": available_at.isoformat().replace("+00:00", "Z"),
        "entry_feature_candle_closed_confirmed": True,
        "expected_funding_bps": 0.0,
    }


def _seed_binding_runtime_evidence(
    r: FakeRedis,
    *,
    symbol: str,
    price: float,
    pit: dict[str, object],
) -> None:
    available_at = str(pit["available_at"])
    decision_time = str(pit["decision_time"])
    bid = price * 0.99999
    ask = price * 1.00001
    r.store[f"v2:orderbook:features:binance:{symbol}"] = json.dumps(
        {
            "best_bid": bid,
            "best_ask": ask,
            "bids": [[bid, 10.0]],
            "asks": [[ask, 10.0]],
            "estimated_price_impact_bps": 0.1,
            "available_at": available_at,
            "received_at": available_at,
            "event_time": available_at,
        }
    )
    r.store[f"v2:microstructure:trust_score:{symbol}:15m"] = json.dumps(
        {
            "microstructure_trust_score": 0.90,
            "orderbook_trust_score": 0.90,
            "orderbook_trust_tier": "HIGH_TRUST",
            "microstructure_action": "ALLOW",
            "adaptive_minimum": 0.65,
            "orderbook_latency_ms": 10.0,
            "book_sequence_gap": False,
            "book_depth_persistence_score": 0.90,
            "book_cancel_pressure_score": 0.10,
            "trade_tape_confirmation_score": 0.80,
            "cross_venue_confirmation_score": 0.80,
            "sweep_risk_score": 0.10,
            "available_at": available_at,
            "generated_at": available_at,
            "decision_time": decision_time,
        }
    )
    r.store[f"v2:market:funding:{symbol}"] = json.dumps(
        {
            "markPrice": price,
            "indexPrice": price,
            "fundingRate": 0.0,
            "time": available_at,
        }
    )


def _signal(symbol: str, paper_fill_allowed: bool, em: float = 80.0, side: str = "long") -> dict:
    return {
        "symbol": symbol,
        "side": side,
        "timeframe": "15m",  # Phase 3 entry gate allows 15m/1h/4h; 1m is blocked by default
        "expected_move_after_cost_bps": em,
        "confidence_calibrated": 0.9,
        "bid_ask_spread_bps": 1.2,
        "slippage_bps": 0.8,
        "paper_fill_allowed": paper_fill_allowed,
        "winner_proposal_id": f"v2_paper_{symbol}_test",
        "prediction_id": f"prd_{symbol}_test",
        "feature_snapshot_id": f"fs_{symbol}_test",
        "risk_decision_id": f"risk_prd_{symbol}_test",
        "orchestrator_decision_id": f"orch_prd_{symbol}_test",
        "signal_id": f"sig_prd_{symbol}_test",
        "market_state_id": f"mstate_{symbol}_test",
        "market_state_integrity_score": 95.0,
        "valid_for_paper": True,
        **_binding_pit_fields(),
    }


def test_upstream_fill_flag_cannot_bypass_missing_canonical_authority(monkeypatch) -> None:
    mod = _mod()
    r = FakeRedis()
    sig = {**_signal("BTCUSDT", paper_fill_allowed=True), "paper_major_move_candidate": True}
    r.store["v2:signals:paper"] = json.dumps([sig])
    r.store["v2:market:prices:BTCUSDT"] = json.dumps({"ticker_24hr": {"lastPrice": "60000.0"}})
    r.store["v2:portfolio:state"] = json.dumps({"equity": 10000.0, "available_margin": 8000.0, "wallet_balance": 10000.0})
    _seed_binding_runtime_evidence(r, symbol="BTCUSDT", price=60000.0, pit=sig)
    monkeypatch.setattr(mod, "_connect_redis", lambda: r)
    monkeypatch.setattr(mod, "_paper_policy_owner_open_rejection_reasons", lambda intent: [])
    monkeypatch.setattr(mod, "_paper_runtime_market_evidence_rejection_reasons", lambda intent, **kw: [])
    monkeypatch.setattr(mod, "_read_lifecycle_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_accepted_fill_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_continuous_edge_guardian_gate", lambda r: {})
    mod.run_once()
    positions = json.loads(r.store["v2:paper:positions"])
    ledger = json.loads(r.store["v2:paper:ledger"])
    assert positions == []
    assert ledger["accepted"] == []
    assert ledger["blocked_count"] == 1
    assert ledger["blocked"][0]["paper_fill_allowed"] is False
    assert ledger["blocked"][0]["places_real_order"] is False


def test_paper_fill_allowed_false_goes_to_shadow_observations_not_positions(monkeypatch) -> None:
    mod = _mod()
    r = FakeRedis()
    # em=0.0 forces NO_TRADE tier (edge not favorable for long), which triggers
    # the non_executable_shadow path before blocking — creating the shadow row.
    r.store["v2:signals:paper"] = json.dumps([_signal("BTCUSDT", paper_fill_allowed=False, em=0.0)])
    r.store["v2:market:prices:BTCUSDT"] = json.dumps({"ticker_24hr": {"lastPrice": "60000.0"}})
    monkeypatch.setattr(mod, "_connect_redis", lambda: r)
    monkeypatch.setattr(mod, "_paper_policy_owner_open_rejection_reasons", lambda intent: [])
    monkeypatch.setattr(mod, "_paper_runtime_market_evidence_rejection_reasons", lambda intent, **kw: [])
    monkeypatch.setattr(mod, "_read_lifecycle_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_accepted_fill_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_continuous_edge_guardian_gate", lambda r: {})
    mod.run_once()
    positions = json.loads(r.store["v2:paper:positions"])
    shadow = json.loads(r.store["v2:paper:shadow_observations"])
    assert positions == []
    assert len(shadow) == 1
    s = shadow[0]
    assert s["decision"] == "SHADOW_OBSERVATION_ONLY"
    assert s["paper_fill_allowed"] is False
    assert s["places_real_order"] is False
    assert s["counted_as_accepted_position"] is False
    assert s["counted_as_fill"] is False
    assert s["counted_as_open_position"] is False
    # Provenance is still observed on shadow rows for no-trade outcome
    # analysis, but the shadow row is NOT a fill.
    assert s["entry_price_provenance_observed"] is True
    assert s["entry_price"] == 60000.0


def test_missing_market_price_blocks_instead_of_shadow_observation(monkeypatch) -> None:
    mod = _mod()
    r = FakeRedis()
    # paper_major_move_candidate + major_move_evidence_score put the signal in
    # breakout_mode so the entry gate passes; the missing market price is then
    # what blocks the fill and sets PAPER_RUNTIME_EVIDENCE_BLOCK_REASON.
    sig = {
        **_signal("XRPUSDT", paper_fill_allowed=False),
        "paper_major_move_candidate": True,
        "major_move_evidence_score": 0.75,
    }
    r.store["v2:signals:paper"] = json.dumps([sig])
    # No v2:market:prices:XRPUSDT, no fresh feature snapshot.
    monkeypatch.setattr(mod, "_connect_redis", lambda: r)
    # Patch policy-owner only so that the runtime evidence check can detect the
    # missing price (entry_price_provenance_present=False).
    monkeypatch.setattr(mod, "_paper_policy_owner_open_rejection_reasons", lambda intent: [])
    monkeypatch.setattr(mod, "_read_lifecycle_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_accepted_fill_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_continuous_edge_guardian_gate", lambda r: {})
    mod.run_once()
    ledger = json.loads(r.store["v2:paper:ledger"])
    shadow = json.loads(r.store["v2:paper:shadow_observations"])
    assert shadow == []
    assert ledger["blocked_count"] == 1
    s = ledger["blocked"][0]
    # entry_price is not in COMPACT_ACCEPTED_FILL_FIELDS; verify via provenance fields instead.
    assert s["entry_price_provenance_present"] is False
    assert s["entry_price_blocker"] == mod.ENTRY_PRICE_BLOCKER_MISSING_FILL
    assert "MISSING_V2_MARKET_PRICE_FOR_FILL" in s[
        "paper_runtime_market_evidence_rejection_reasons"
    ]
    assert "MISSING_V2_MARKET_PRICE_FOR_FILL" in s[
        "paper_fill_gate_block_reasons"
    ]


def test_missing_timeframe_blocks_only_its_row_and_cycle_continues(monkeypatch) -> None:
    mod = _mod()
    r = FakeRedis()
    missing_timeframe = _signal("BTCUSDT", paper_fill_allowed=True)
    missing_timeframe.pop("timeframe")
    following = _signal("ETHUSDT", paper_fill_allowed=True)
    r.store["v2:signals:paper"] = json.dumps([missing_timeframe, following])
    r.store["v2:portfolio:state"] = json.dumps(
        {
            "equity": 10_000.0,
            "available_margin": 8_000.0,
            "wallet_balance": 10_000.0,
        }
    )
    monkeypatch.setattr(mod, "_connect_redis", lambda: r)
    monkeypatch.setattr(mod, "_read_lifecycle_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_accepted_fill_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_continuous_edge_guardian_gate", lambda _r: {})

    status = mod.run_once()
    ledger = json.loads(r.store["v2:paper:ledger"])

    assert status["intents_built"] == 2
    assert {row["symbol"] for row in ledger["blocked"]} == {
        "BTCUSDT",
        "ETHUSDT",
    }
    missing_row = next(
        row for row in ledger["blocked"] if row["symbol"] == "BTCUSDT"
    )
    assert mod.MISSING_THESIS_TIMEFRAME_BLOCK_REASON in (
        missing_row["paper_fill_gate_block_reasons"]
    )


def test_local_gate_failure_goes_to_blocked_not_positions_or_shadow(monkeypatch) -> None:
    mod = _mod()
    r = FakeRedis()
    # em=0 forces the fee_gate ratio (fee/em) to infinity, so the local
    # fee-ratio gate blocks the intent before it can become a position
    # or shadow observation.
    r.store["v2:signals:paper"] = json.dumps([
        _signal("BTCUSDT", paper_fill_allowed=True, em=0.0)
    ])
    r.store["v2:market:prices:BTCUSDT"] = json.dumps({"ticker_24hr": {"lastPrice": "60000.0"}})
    monkeypatch.setattr(mod, "_connect_redis", lambda: r)
    mod.run_once()
    positions = json.loads(r.store["v2:paper:positions"])
    shadow = json.loads(r.store["v2:paper:shadow_observations"])
    ledger = json.loads(r.store["v2:paper:ledger"])
    assert positions == []
    assert shadow == []
    assert ledger["blocked_count"] == 1


def test_held_by_orchestrator_gate_never_in_positions(monkeypatch) -> None:
    mod = _mod()
    r = FakeRedis()
    r.store["v2:signals:paper"] = json.dumps([])
    r.store["v2:orchestrator:decisions"] = json.dumps({
        "held_by_paper_fill_gate": [{
            "symbol": "SOLUSDT",
            "paper_fill_gate_status": "BLOCKED_BY_TRAINER_OUTPUT_MALFORMED",
            "paper_fill_gate_block_reasons": ["NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK"],
            "checkpoint_blocker": "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED",
            "selected_action": "hold",
            "prediction_id": "prd_sol_held",
        }]
    })
    monkeypatch.setattr(mod, "_connect_redis", lambda: r)
    mod.run_once()
    positions = json.loads(r.store["v2:paper:positions"])
    held = json.loads(r.store["v2:paper:intents_held_by_paper_fill_gate"])
    shadow = json.loads(r.store["v2:paper:shadow_observations"])
    assert positions == []
    assert shadow == []
    assert len(held) == 1
    assert held[0]["symbol"] == "SOLUSDT"
    assert held[0]["decision"] == "HELD_BY_PAPER_FILL_GATE"
    assert held[0]["places_real_order"] is False


def test_ledger_carries_three_lists_plus_counts(monkeypatch) -> None:
    mod = _mod()
    r = FakeRedis()
    btc_sig = {**_signal("BTCUSDT", paper_fill_allowed=True), "paper_major_move_candidate": True}
    # em=0.0 forces NO_TRADE tier for ETH (edge not favorable), triggering the
    # non_executable_shadow path that creates a shadow row before blocking.
    eth_sig = _signal("ETHUSDT", paper_fill_allowed=False, em=0.0)
    r.store["v2:signals:paper"] = json.dumps([btc_sig, eth_sig])
    r.store["v2:orchestrator:decisions"] = json.dumps({
        "held_by_paper_fill_gate": [{
            "symbol": "SOLUSDT",
            "paper_fill_gate_status": "BLOCKED",
            "paper_fill_gate_block_reasons": ["EDGE_AFTER_COST_BELOW_THRESHOLD"],
            "selected_action": "hold",
            "prediction_id": "prd_sol_held",
        }]
    })
    r.store["v2:market:prices:BTCUSDT"] = json.dumps({"ticker_24hr": {"lastPrice": "60000.0"}})
    r.store["v2:market:prices:ETHUSDT"] = json.dumps({"ticker_24hr": {"lastPrice": "3000.0"}})
    r.store["v2:portfolio:state"] = json.dumps({"equity": 10000.0, "available_margin": 8000.0, "wallet_balance": 10000.0})
    _seed_binding_runtime_evidence(r, symbol="BTCUSDT", price=60000.0, pit=btc_sig)
    monkeypatch.setattr(mod, "_connect_redis", lambda: r)
    monkeypatch.setattr(mod, "_paper_policy_owner_open_rejection_reasons", lambda intent: [])
    monkeypatch.setattr(mod, "_paper_runtime_market_evidence_rejection_reasons", lambda intent, **kw: [])
    monkeypatch.setattr(mod, "_read_lifecycle_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_accepted_fill_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_continuous_edge_guardian_gate", lambda r: {})
    mod.run_once()
    ledger = json.loads(r.store["v2:paper:ledger"])
    assert ledger["accepted_position_count"] == 0
    assert ledger["blocked_count"] == 2
    assert ledger["shadow_observation_count"] == 2
    assert ledger["held_position_count"] == 1
    assert isinstance(ledger["accepted_intents"], list) and ledger["accepted_intents"] == []
    assert isinstance(ledger["shadow_observations"], list) and len(ledger["shadow_observations"]) == 2
    assert isinstance(ledger["held_by_paper_fill_gate"], list) and len(ledger["held_by_paper_fill_gate"]) == 1
    split = ledger["schema_split"]
    assert split["accepted_positions_must_have_paper_fill_allowed_true"] is True
    assert split["shadow_observations_have_paper_fill_allowed_false"] is True
    assert split["held_by_gate_have_paper_fill_allowed_false"] is True
    assert split["recorder_consumes_v2_paper_positions_only_for_accepted_mfe_mae_roe"] is True


def test_strict_gate_threshold_unchanged_no_unsafe_fill(monkeypatch) -> None:
    """No matter how many shadow observations arrive, the strict
    paper-fill contract is unchanged: an upstream flag cannot substitute for
    authenticated tuning, decision, allocation, and final-admission evidence.
    """
    mod = _mod()
    r = FakeRedis()
    # BTC: paper_fill_allowed=False, em=0.0 → NO_TRADE tier → shadow row only.
    # ETH claims paper_fill_allowed=True but still lacks canonical authority.
    btc_sig = _signal("BTCUSDT", paper_fill_allowed=False, em=0.0)
    eth_sig = {**_signal("ETHUSDT", paper_fill_allowed=True), "paper_major_move_candidate": True}
    r.store["v2:signals:paper"] = json.dumps([btc_sig, eth_sig])
    r.store["v2:market:prices:BTCUSDT"] = json.dumps({"ticker_24hr": {"lastPrice": "60000.0"}})
    r.store["v2:market:prices:ETHUSDT"] = json.dumps({"ticker_24hr": {"lastPrice": "3000.0"}})
    r.store["v2:portfolio:state"] = json.dumps({"equity": 10000.0, "available_margin": 8000.0, "wallet_balance": 10000.0})
    _seed_binding_runtime_evidence(r, symbol="ETHUSDT", price=3000.0, pit=eth_sig)
    monkeypatch.setattr(mod, "_connect_redis", lambda: r)
    monkeypatch.setattr(mod, "_paper_policy_owner_open_rejection_reasons", lambda intent: [])
    monkeypatch.setattr(mod, "_paper_runtime_market_evidence_rejection_reasons", lambda intent, **kw: [])
    monkeypatch.setattr(mod, "_read_lifecycle_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_accepted_fill_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_continuous_edge_guardian_gate", lambda r: {})
    mod.run_once()
    positions = json.loads(r.store["v2:paper:positions"])
    shadow = json.loads(r.store["v2:paper:shadow_observations"])
    # BTC was paper_fill_allowed=false → NOT in positions.
    assert all(p["symbol"] != "BTCUSDT" for p in positions)
    # BTC appears as a shadow observation (NO_TRADE non_executable_shadow path).
    assert any(s["symbol"] == "BTCUSDT" for s in shadow)
    assert positions == []
    assert any(s["symbol"] == "ETHUSDT" for s in shadow)
    assert all(s["decision"] != "ACCEPTED_PAPER_FILL" for s in shadow)
    blocked = json.loads(r.store["v2:paper:ledger"])["blocked"]
    assert {row["symbol"] for row in blocked} == {"BTCUSDT", "ETHUSDT"}
    assert all(row["paper_fill_allowed"] is False for row in blocked)


def test_writer_only_writes_v2_prefixed_keys_after_normalization(monkeypatch) -> None:
    mod = _mod()
    r = FakeRedis()
    r.store["v2:signals:paper"] = json.dumps([
        _signal("BTCUSDT", paper_fill_allowed=False)
    ])
    r.store["v2:market:prices:BTCUSDT"] = json.dumps({"ticker_24hr": {"lastPrice": "60000.0"}})
    monkeypatch.setattr(mod, "_connect_redis", lambda: r)
    mod.run_once()
    for key, _val, _ex in r.write_log:
        assert key.startswith("v2:"), f"non-v2 key written: {key}"
    # Specifically the new shadow_observations key must be a v2:paper:* key.
    assert "v2:paper:shadow_observations" in r.store


def test_no_exchange_mutation_or_approvals_after_normalization(monkeypatch) -> None:
    import inspect
    mod = _mod()
    src = inspect.getsource(mod)
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
        assert token not in src, f"forbidden token in writer: {token}"


def test_no_torch_imported_after_normalization() -> None:
    sys.modules.pop("torch", None)
    importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    assert "torch" not in sys.modules
