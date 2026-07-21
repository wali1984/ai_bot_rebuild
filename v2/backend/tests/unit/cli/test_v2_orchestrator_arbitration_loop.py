from __future__ import annotations

import json
from typing import Any

import pytest

from v2.backend.app.cli import v2_orchestrator_arbitration_loop as loop
from v2.backend.app.services.orchestrator_arbitration import Proposal, score_proposal
from v2.backend.tests.unit.services.test_ordinary_paper_admission import (
    ordinary_source,
)


class _FakeRedis:
    def __init__(self, prediction: dict[str, Any]) -> None:
        self.store: dict[str, str] = {
            f"v2:prediction:{prediction['symbol']}:{prediction['timeframe']}": json.dumps(
                prediction
            )
        }

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,  # noqa: ARG002
        nx: bool = False,
    ) -> bool:
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    def scan(
        self,
        cursor: int = 0,  # noqa: ARG002
        match: str | None = None,
        count: int = 1000,  # noqa: ARG002
    ) -> tuple[int, list[str]]:
        prefix = (match or "").rstrip("*")
        keys = [key for key in self.store if not match or key.startswith(prefix)]
        return 0, keys

    def ttl(self, key: str) -> int:  # noqa: ARG002
        return 300


class _MarketStateOk:
    def to_dict(self) -> dict[str, Any]:
        return {
            "market_state_id": "ms_test",
            "market_state_integrity_score": 100.0,
            "valid_for_prediction": True,
            "valid_for_risk": True,
            "valid_for_orchestrator": True,
            "valid_for_paper": True,
            "valid_for_live": False,
            "reject_reasons": [],
        }


class _MarketStateDegraded:
    def __init__(self, market_state_id: str) -> None:
        self.market_state_id = market_state_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "market_state_id": self.market_state_id,
            "market_state_integrity_score": 79.999999,
            "valid_for_prediction": True,
            "valid_for_risk": False,
            "valid_for_orchestrator": False,
            "valid_for_paper": True,
            "valid_for_live": False,
            "reject_reasons": [
                "LATENCY_ABOVE_GATE",
                "MAJOR_SOURCE_DISAGREEMENT",
            ],
        }


def _prediction(
    *,
    action: str = "long",
    edge_bps: float = 12.0,
    symbol: str = "BTCUSDT",
) -> dict[str, Any]:
    return {
        "prediction_id": f"pred_{symbol}_{action}",
        "decision_id": f"upstream_decision_{symbol}_{action}",
        "feature_snapshot_id": f"fs_{symbol}_{action}",
        "symbol": symbol,
        "timeframe": "1m",
        "selected_action": action,
        "expected_move_bps": edge_bps,
        "expected_move_after_cost_bps": edge_bps,
        "confidence_raw": 0.75,
        "confidence_calibrated": 0.75,
        "data_coverage_percent": 100.0,
        "model_version": "model_test",
        "trainer_source": "V2_NATIVE_TEST_TRAINER",
        "checkpoint_id": "ckpt_test",
        "routes_to_orchestrator": True,
        "paper_fill_allowed": True,
        "paper_fill_gate_status": "UPSTREAM_PAPER_GATE_OPEN",
        "paper_fill_gate_block_reasons": [],
        "feature_cutoff": "2026-07-17T11:58:00Z",
        "available_at": "2026-07-17T11:58:05Z",
        "decision_time": "2026-07-17T11:59:00Z",
        "candle_closed_confirmed": True,
        "candle_close_time": "2026-07-17T11:58:00Z",
        "masa_feature_cutoff": "2026-07-17T11:58:00Z",
        "ppo_feature_cutoff": "2026-07-17T11:58:00Z",
        "ppo_decision_time": "2026-07-17T11:59:00Z",
        "feature_vector_hash": f"hash_{symbol}_{action}",
        "input_feature_hash": f"hash_{symbol}_{action}",
        "trust_gate_result": {
            "allowed": True,
            "reject_reasons": [],
            "warnings": [],
        },
        "generated_utc": "2026-07-17T12:00:00Z",
    }


def _run(
    monkeypatch: pytest.MonkeyPatch,
    prediction: dict[str, Any],
    *,
    market_state: Any | None = None,
    extra_store: dict[str, Any] | None = None,
) -> tuple[dict, _FakeRedis]:
    return _run_many(
        monkeypatch,
        [prediction],
        market_state=market_state,
        extra_store=extra_store,
    )


def _run_many(
    monkeypatch: pytest.MonkeyPatch,
    predictions: list[dict[str, Any]],
    *,
    market_state: Any | None = None,
    extra_store: dict[str, Any] | None = None,
) -> tuple[dict, _FakeRedis]:
    if not predictions:
        raise ValueError("predictions must not be empty")
    fake = _FakeRedis(predictions[0])
    for prediction in predictions[1:]:
        fake.store[
            f"v2:prediction:{prediction['symbol']}:{prediction['timeframe']}"
        ] = json.dumps(prediction)
    for key, value in (extra_store or {}).items():
        fake.store[key] = json.dumps(value)
    monkeypatch.setattr(loop, "_connect_redis", lambda: fake)
    monkeypatch.setattr(loop, "_prediction_age_seconds", lambda _prediction: 5.0)
    monkeypatch.setattr(
        loop,
        "score_market_state",
        lambda _row: market_state or _MarketStateOk(),
    )
    monkeypatch.setattr(
        loop,
        "_live_context",
        lambda _redis: {
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "execution_live_symbols": [],
            "runtime_validation": {"valid": True},
            "runtime_source": "unit_test",
        },
    )
    return loop.run_once(), fake


@pytest.mark.parametrize("action", ["hold", "flat", "close"])
def test_non_routeable_actions_are_held_without_direction_synthesis(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    status, fake = _run(monkeypatch, _prediction(action=action, edge_bps=80.0))

    assert status["proposals_arbitrated"] == 0
    assert status["bucket_winners_count"] == 0
    assert status["skipped_malformed_prediction_count"] == 0
    assert json.loads(fake.store["v2:signals:paper"]) == []
    held = status["held_by_paper_fill_gate"][0]
    assert held["selected_action"] == action
    assert held["side"] == "flat"
    assert held["decision"] == "HELD_BY_NON_ROUTEABLE_ACTION"
    assert held["paper_fill_allowed"] is False
    assert held["routes_to_risk_gateway"] is False
    assert held["risk_decision_id"] is None
    assert f"NON_ROUTEABLE_SELECTED_ACTION:{action.upper()}" in held[
        "paper_fill_gate_block_reasons"
    ]


def test_published_signal_uses_canonical_risk_decision_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from v2.backend.app.cli.v2_risk_gateway_live_loop import _winner_to_decision

    status, fake = _run(monkeypatch, _prediction())

    assert status["bucket_winners_count"] == 1
    winner = json.loads(fake.store["v2:orchestrator:decisions"])["bucket_winners"][0]
    signal = json.loads(fake.store["v2:signals:paper"])[0]
    gateway_decision = _winner_to_decision(winner, now_ms=1_000)
    assert signal["orchestrator_decision_id"] == gateway_decision.decision_id
    assert signal["risk_decision_id"] == f"rd_{gateway_decision.decision_id}"
    assert signal["risk_decision_id"] == "rd_dec_pred_BTCUSDT_long"
    record = json.loads(
        fake.store[
            "v2:decision:orchestrator:dec_pred_BTCUSDT_long"
        ]
    )
    assert record["producer"] == "v2_orchestrator_arbitration_loop"
    assert record["orchestrator_action"] == "proceed_long"
    assert record["prediction_id"] == signal["prediction_id"]
    assert record["signal_id"] == signal["signal_id"]
    assert record["expires_at"]


def test_published_signal_cannot_claim_fill_permission_before_risk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, fake = _run(monkeypatch, _prediction())

    signal = json.loads(fake.store["v2:signals:paper"])[0]
    assert signal["upstream_paper_fill_allowed"] is True
    assert signal["paper_fill_allowed"] is False
    assert signal["paper_fill_gate_status"] == "RISK_PENDING"
    assert signal["risk_state"] == "PENDING_RISK_GATEWAY_DECISION"
    assert signal["paper_fill_gate_block_reasons"] == [
        "RISK_GATEWAY_DECISION_PENDING"
    ]
    assert signal["routes_to_risk_gateway"] is True
    assert signal["places_real_order"] is False


def test_deconflict_telemetry_is_independent_per_symbol_without_filtering_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    btc_long = _prediction(action="long", edge_bps=12.0, symbol="BTCUSDT")
    btc_long["signal_id"] = "sig_btc_long_lineage"
    eth_short = _prediction(action="short", edge_bps=-18.0, symbol="ETHUSDT")
    eth_short["signal_id"] = "sig_eth_short_lineage"
    eth_short["confidence_raw"] = 0.85
    eth_short["confidence_calibrated"] = 0.85

    status, fake = _run_many(monkeypatch, [btc_long, eth_short])

    decisions = json.loads(fake.store["v2:orchestrator:decisions"])
    paper_signals = json.loads(fake.store["v2:signals:paper"])
    by_symbol = decisions["deconflict_by_symbol"]
    assert decisions["deconflict_scope"] == "PER_SYMBOL_TELEMETRY_ONLY"
    assert decisions["deconflict_scope_applies_to"] == "deconflict_by_symbol"
    assert decisions["deconflict_by_symbol_scope"] == "PER_SYMBOL_TELEMETRY_ONLY"
    assert decisions["deconflict_controls_publication"] is False
    assert set(by_symbol) == {"BTCUSDT", "ETHUSDT"}
    assert by_symbol["BTCUSDT"] == {
        "scope": "PER_SYMBOL_TELEMETRY_ONLY",
        "telemetry_only": True,
        "controls_publication": False,
        "selected_side": "long",
        "selected_signal_id": "sig_btc_long_lineage",
        "selected_source_prediction_id": "pred_BTCUSDT_long",
        "conflict_reason": "ALL_SIGNALS_AGREE_ON_SIDE",
        "long_aggregate_confidence": 0.75,
        "short_aggregate_confidence": 0.0,
        "considered_count": 1,
    }
    assert by_symbol["ETHUSDT"]["selected_side"] == "short"
    assert by_symbol["ETHUSDT"]["selected_signal_id"] == "sig_eth_short_lineage"
    assert by_symbol["ETHUSDT"]["selected_source_prediction_id"] == (
        "pred_ETHUSDT_short"
    )
    assert decisions["legacy_global_deconflict"]["scope"] == (
        "GLOBAL_CROSS_SYMBOL_LEGACY_DIAGNOSTIC_ONLY"
    )
    assert decisions["legacy_global_deconflict"]["controls_publication"] is False
    assert decisions["legacy_global_deconflict_flat_fields_scope"] == (
        "GLOBAL_CROSS_SYMBOL_LEGACY_DIAGNOSTIC_ONLY"
    )
    assert decisions["deconflict_selected_signal_id"] == "sig_eth_short_lineage"
    assert decisions["deconflict_selected_source_prediction_id"] == (
        "pred_ETHUSDT_short"
    )

    assert status["deconflict_by_symbol"] == by_symbol
    assert status["deconflict_scope_applies_to"] == "deconflict_by_symbol"
    assert status["legacy_global_deconflict_flat_fields_scope"] == (
        "GLOBAL_CROSS_SYMBOL_LEGACY_DIAGNOSTIC_ONLY"
    )
    assert status["deconflict_controls_publication"] is False
    assert status["bucket_winners_count"] == 2
    assert [row["winner_proposal_id"] for row in decisions["bucket_winners"]] == [
        "pred_BTCUSDT_long",
        "pred_ETHUSDT_short",
    ]
    assert [row["signal_id"] for row in paper_signals] == [
        "sig_btc_long_lineage",
        "sig_eth_short_lineage",
    ]
    assert all(row["paper_fill_allowed"] is False for row in paper_signals)
    assert all(row["places_real_order"] is False for row in paper_signals)
    assert all(row["valid_for_live"] is False for row in paper_signals)
    assert status["approves_live"] is False


def test_opposing_sides_select_telemetry_but_preserve_both_paper_winner_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    btc_long = _prediction(action="long", edge_bps=12.0, symbol="BTCUSDT")
    btc_long["signal_id"] = "sig_btc_long"
    btc_short = _prediction(action="short", edge_bps=-20.0, symbol="BTCUSDT")
    btc_short.update(
        {
            "timeframe": "5m",
            "feature_snapshot_id": "fs_BTCUSDT_short_5m",
            "signal_id": "sig_btc_short",
            "confidence_raw": 0.85,
            "confidence_calibrated": 0.85,
        }
    )

    status, fake = _run_many(monkeypatch, [btc_long, btc_short])

    proposals = json.loads(fake.store["v2:orchestrator:proposals"])
    decisions = json.loads(fake.store["v2:orchestrator:decisions"])
    paper_signals = json.loads(fake.store["v2:signals:paper"])
    telemetry = decisions["deconflict_by_symbol"]["BTCUSDT"]
    assert telemetry["selected_side"] == "short"
    assert telemetry["selected_signal_id"] == "sig_btc_short"
    assert telemetry["selected_source_prediction_id"] == "pred_BTCUSDT_short"
    assert telemetry["conflict_reason"] == (
        "OPPOSITE_SIDES_DOMINANT_CONFIDENCE_WINS"
    )
    assert telemetry["controls_publication"] is False

    winner_ids = [row["winner_proposal_id"] for row in decisions["bucket_winners"]]
    signal_ids = [row["signal_id"] for row in paper_signals]
    assert [row["proposal_id"] for row in proposals] == [
        "pred_BTCUSDT_long",
        "pred_BTCUSDT_short",
    ]
    assert winner_ids == ["pred_BTCUSDT_long", "pred_BTCUSDT_short"]
    assert signal_ids == ["sig_btc_long", "sig_btc_short"]
    assert status["bucket_winners_count"] == 2
    assert status["arbitration_bucket_winners_before_canonical_store"] == 2
    assert all(row["paper_fill_allowed"] is False for row in paper_signals)
    assert all(row["places_real_order"] is False for row in paper_signals)
    assert all(row["routes_to_risk_gateway"] is True for row in paper_signals)
    assert all(row["risk_state"] == "PENDING_RISK_GATEWAY_DECISION" for row in paper_signals)
    assert all("deconflict_by_symbol" not in row for row in proposals)
    assert all(
        "deconflict_by_symbol" not in row for row in decisions["bucket_winners"]
    )
    assert all("deconflict_by_symbol" not in row for row in paper_signals)
    for winner in decisions["bucket_winners"]:
        canonical = json.loads(
            fake.store[
                f"v2:decision:orchestrator:{winner['orchestrator_decision_id']}"
            ]
        )
        assert canonical["paper_only"] is True
        assert canonical["routes_to_live"] is False
        assert canonical["places_real_order"] is False
        assert canonical["live_gate"] == "blocked_human_only"
        assert "deconflict_by_symbol" not in canonical


def test_signed_short_and_long_edges_are_symmetric_for_arbitration() -> None:
    long_pair = loop._prediction_to_proposal_and_signal(
        _prediction(action="long", edge_bps=14.5, symbol="BTCUSDT")
    )
    short_pair = loop._prediction_to_proposal_and_signal(
        _prediction(action="short", edge_bps=-14.5, symbol="ETHUSDT")
    )

    assert long_pair is not None
    assert short_pair is not None
    long_proposal, long_signal = long_pair
    short_proposal, short_signal = short_pair
    assert long_proposal["expected_move_after_cost_bps"] == 14.5
    assert short_proposal["expected_move_after_cost_bps"] == 14.5
    assert long_signal["expected_move_after_cost_bps_signed"] == 14.5
    assert short_signal["expected_move_after_cost_bps_signed"] == -14.5
    assert long_signal["expected_move_after_cost_bps_directional"] == 14.5
    assert short_signal["expected_move_after_cost_bps_directional"] == 14.5
    assert score_proposal(Proposal(**long_proposal)) == pytest.approx(
        score_proposal(Proposal(**short_proposal))
    )
    assert not any(
        reason.startswith("HPPM_LOW_EXPECTED_MOVE")
        for reason in loop._hppm_gate(_prediction(action="short", edge_bps=-14.5))
    )


def test_feature_available_after_decision_is_held_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prediction = _prediction()
    prediction["available_at"] = "2026-07-17T11:59:30Z"

    status, fake = _run(monkeypatch, prediction)

    assert status["proposals_arbitrated"] == 0
    assert json.loads(fake.store["v2:signals:paper"]) == []
    held = status["held_by_paper_fill_gate"][0]
    assert "FEATURE_AVAILABLE_AFTER_DECISION_TIME" in held[
        "paper_fill_gate_block_reasons"
    ]
    assert held["paper_fill_allowed"] is False


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("masa_feature_cutoff", "MASA_FEATURE_CUTOFF_MISSING_OR_INVALID"),
        ("ppo_decision_time", "PPO_DECISION_TIME_MISSING_OR_INVALID"),
    ],
)
def test_directional_route_requires_explicit_cross_model_temporal_fields(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    reason: str,
) -> None:
    prediction = _prediction()
    prediction.pop(field)

    status, fake = _run(monkeypatch, prediction)

    assert status["bucket_winners_count"] == 0
    assert json.loads(fake.store["v2:signals:paper"]) == []
    assert reason in status["held_by_paper_fill_gate"][0][
        "paper_fill_gate_block_reasons"
    ]


def test_naive_temporal_timestamp_is_rejected() -> None:
    prediction = _prediction()
    prediction["ppo_decision_time"] = "2026-07-17T11:59:00"

    assert "PPO_DECISION_TIME_MISSING_OR_INVALID" in (
        loop._prediction_temporal_rejection_reasons(prediction)  # noqa: SLF001
    )


def test_missing_explicit_orchestrator_route_is_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prediction = _prediction()
    prediction.pop("routes_to_orchestrator")

    status, fake = _run(monkeypatch, prediction)

    assert status["proposals_arbitrated"] == 0
    assert json.loads(fake.store["v2:signals:paper"]) == []
    held = status["held_by_paper_fill_gate"][0]
    assert "ROUTES_TO_ORCHESTRATOR_NOT_EXPLICIT_TRUE" in held[
        "paper_fill_gate_block_reasons"
    ]


def test_latest_feature_enrichment_requires_exact_snapshot_identity() -> None:
    prediction = _prediction()
    fake = _FakeRedis(prediction)
    fake.store["v2:features:latest:BTCUSDT:1m"] = json.dumps(
        {
            "feature_snapshot_id": "different_snapshot",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "features": {"close": 999.0},
            "feature_cutoff": "2026-07-17T11:58:00Z",
            "available_at": "2026-07-17T11:58:05Z",
        }
    )

    merged = loop._prediction_integrity_input(fake, prediction)

    assert "features" not in merged
    assert "integrity_feature_snapshot_exact_match" not in merged


def test_proposal_uses_measured_prediction_age(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(loop, "_prediction_age_seconds", lambda _row: 37.25)

    pair = loop._prediction_to_proposal_and_signal(_prediction())

    assert pair is not None
    proposal, signal = pair
    assert proposal["freshness_seconds"] == pytest.approx(37.25)
    assert signal["freshness_seconds"] == pytest.approx(37.25)


def _ordinary_orchestrator_prediction() -> tuple[dict[str, Any], dict[str, Any]]:
    prediction, replay = ordinary_source(
        microstructure_trust_score=0.45 - 1e-6,
        sweep_risk_score=0.75 + 1e-6,
        microstructure_action="SHADOW_ONLY",
        latency_within_bound=False,
    )
    prediction.update(
        {
            "confidence_raw": prediction["confidence_calibrated"],
        }
    )
    return prediction, replay


def test_ordinary_scale_free_candidate_crosses_legacy_cliffs_with_smaller_weight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prediction, replay = _ordinary_orchestrator_prediction()
    replay_key = str(prediction["replay_snapshot_key"])
    market_state = _MarketStateDegraded(str(prediction["market_state_id"]))
    monkeypatch.setenv("V2_HIGH_PRECISION_PAPER_MODE", "1")

    status, fake = _run(
        monkeypatch,
        prediction,
        market_state=market_state,
        extra_store={replay_key: replay},
    )

    assert status["bucket_winners_count"] == 1
    proposal = json.loads(fake.store["v2:orchestrator:proposals"])[0]
    winner = json.loads(fake.store["v2:orchestrator:decisions"])[
        "bucket_winners"
    ][0]
    signal = json.loads(fake.store["v2:signals:paper"])[0]
    canonical = json.loads(
        fake.store[
            f"v2:decision:orchestrator:{winner['orchestrator_decision_id']}"
        ]
    )
    evidence_hash = signal["ordinary_paper_admission_evidence_sha256"]
    for row in (proposal, winner, signal, canonical):
        assert row["ordinary_scale_free_paper_admission_revalidated"] is True
        assert row["ordinary_paper_admission_evidence_sha256"] == evidence_hash
        assert row["paper_quality_sizing_weight"] == pytest.approx(
            prediction["paper_quality_sizing_weight"]
        )
        assert 0.0 < row["ordinary_paper_effective_sizing_weight"] < row[
            "paper_quality_sizing_weight"
        ]
        assert row["ordinary_paper_raw_microstructure_action"] == "SHADOW_ONLY"
        assert row["ordinary_paper_effective_microstructure_action"] == (
            "REDUCE_SIZE"
        )
    assert signal["valid_for_paper"] is True
    assert signal["paper_fill_allowed"] is False
    assert signal["paper_fill_gate_status"] == "RISK_PENDING"


@pytest.mark.parametrize("redis_snapshot", [None, {"tampered": True}])
def test_ordinary_replay_uses_independent_redis_readback_not_embedded_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    redis_snapshot: dict[str, Any] | None,
) -> None:
    prediction, replay = _ordinary_orchestrator_prediction()
    prediction["replay_snapshot"] = replay
    replay_key = str(prediction["replay_snapshot_key"])
    market_state = _MarketStateDegraded(str(prediction["market_state_id"]))
    extra_store = {replay_key: redis_snapshot} if redis_snapshot is not None else {}

    status, fake = _run(
        monkeypatch,
        prediction,
        market_state=market_state,
        extra_store=extra_store,
    )

    assert status["bucket_winners_count"] == 0
    assert json.loads(fake.store["v2:signals:paper"]) == []
    reasons = status["held_by_paper_fill_gate"][0][
        "paper_fill_gate_block_reasons"
    ]
    expected = (
        "ordinary_paper_replay_snapshot_readback_missing"
        if redis_snapshot is None
        else "ordinary_paper_replay_snapshot_readback_hash_mismatch"
    )
    assert expected in reasons
