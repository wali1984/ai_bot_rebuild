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
    fake = _FakeRedis(prediction)
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
