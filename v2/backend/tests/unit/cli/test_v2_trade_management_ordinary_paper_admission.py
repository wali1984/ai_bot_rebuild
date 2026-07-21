from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop
from v2.backend.tests.unit.services.test_ordinary_paper_admission import (
    _assess,
    ordinary_source,
)


class _AtomicPipeline:
    def __init__(self, client: _AtomicRedis) -> None:
        self.client = client
        self.commands: list[tuple[str, str]] = []

    def get(self, key: str) -> _AtomicPipeline:
        self.commands.append(("get", key))
        return self

    def ttl(self, key: str) -> _AtomicPipeline:
        self.commands.append(("ttl", key))
        return self

    def execute(self) -> list[Any]:
        self.client.executed_transactions.append(list(self.commands))
        assert len(self.commands) == 2
        assert self.commands[0][0] == "get"
        assert self.commands[1] == ("ttl", self.commands[0][1])
        key = self.commands[0][1]
        payload = self.client.payloads.get(key)
        raw = json.dumps(payload, sort_keys=True) if payload is not None else None
        return [raw, self.client.ttls.get(key, -2)]


class _AtomicRedis:
    def __init__(
        self,
        payloads: dict[str, dict[str, Any]],
        ttls: dict[str, int],
    ) -> None:
        self.payloads = deepcopy(payloads)
        self.ttls = dict(ttls)
        self.executed_transactions: list[list[tuple[str, str]]] = []

    def pipeline(self, *, transaction: bool) -> _AtomicPipeline:
        assert transaction is True
        return _AtomicPipeline(self)

    def get(self, key: str) -> str | None:
        payload = self.payloads.get(key)
        return json.dumps(payload, sort_keys=True) if payload is not None else None

    def ttl(self, key: str) -> int:
        return self.ttls.get(key, -2)


def _transported_ordinary_signal(
    *,
    market_score: float = 69.0,
    trust_score: float = 0.5,
    sweep_risk: float = 0.2,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], _AtomicRedis]:
    source, replay = ordinary_source(
        confidence=0.4,
        coverage=40.0,
        edge_bps=1.0,
        microstructure_trust_score=trust_score,
        sweep_risk_score=sweep_risk,
    )
    assessment = _assess(
        source,
        replay,
        market_score=market_score,
        trust_score=trust_score,
        sweep_risk=sweep_risk,
        action="REDUCE_SIZE",
        current_ttl=300,
    )
    assert assessment.accepted is True
    signal = {
        **deepcopy(source),
        **assessment.transport_payload(),
        # Historical fields deliberately disagree with the scale-free result.
        "market_state_integrity_score": market_score,
        "valid_for_paper": False,
        "paper_fill_allowed": False,
    }
    redis_client = _AtomicRedis(
        {
            str(source["source_redis_key"]): deepcopy(source),
            str(source["replay_snapshot_key"]): deepcopy(replay),
        },
        {
            str(source["source_redis_key"]): 299,
            str(source["replay_snapshot_key"]): 299,
        },
    )
    return source, replay, signal, redis_client


def _real_router_and_proof(
    signal: dict[str, Any],
    gate: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    router_input = {
        "market_state_envelope": {
            **deepcopy(signal),
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "microstructure_trust_score": 0.4,
            "microstructure_action": "REDUCE_SIZE",
            "sweep_risk_score": 0.5,
            "confidence_calibrated": 0.4,
        },
        "masa_predictions": [deepcopy(signal)],
        "ppo_proposed_action": "long",
        "current_position_state": "FLAT",
        "recent_execution_success_metrics": {
            "execution_success_probability": 0.4,
            "closed_trade_outcome_count": 10,
            "clean_closed_trade_outcome_count": 10,
        },
        "volatility_liquidity_state": {
            "volatility": 0.1,
            "liquidity_score": 0.4,
            "bid_ask_spread_bps": 1.0,
        },
        "data_quality_score": 60.0,
        "current_drawdown_risk_state": {"current_drawdown_bps": 100.0},
    }
    raw_router = paper_loop.route_strategy(**deepcopy(router_input))
    proof = paper_loop._paper_ordinary_strategy_router_interpretation_proof(  # noqa: SLF001
        router_result=raw_router,
        router_input_material=router_input,
        ordinary_admission=gate["_ordinary_paper_admission_result"],
        proposed_action="long",
        current_position_state="FLAT",
    )
    return raw_router, proof, router_input


def _intent_with_router_proof(
    signal: dict[str, Any],
    gate: dict[str, Any],
    proof: dict[str, Any],
) -> dict[str, Any]:
    return {
        **deepcopy(signal),
        **deepcopy(gate["ordinary_paper_transport"]),
        **paper_loop._paper_ordinary_router_proof_fields(proof),  # noqa: SLF001
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "selected_action": "long",
        "entry_price": 100.0,
        "confidence_calibrated": 0.4,
        "expected_move_after_cost_bps": 1.0,
    }


def _minimal_final_intent(
    signal: dict[str, Any],
    gate: dict[str, Any],
    proof: dict[str, Any],
) -> dict[str, Any]:
    intent = _intent_with_router_proof(signal, gate, proof)
    intent.update(
        {
            "decision": "ACCEPTED_PAPER_FILL",
            "paper_fill_allowed": True,
            "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
            "adaptive_allocation": {},
        }
    )
    return intent


def _coherently_reseal_router_proof(proof: dict[str, Any]) -> None:
    interpretation = proof["interpretation"]
    binding_material = {
        "admission_evidence_sha256": interpretation["admission_evidence_sha256"],
        "router_result_sha256": interpretation["router_result_sha256"],
        "router_input_material_sha256": interpretation["router_input_material_sha256"],
        "source_identity_sha256": interpretation["admission_source_identity_sha256"],
        "point_in_time_clocks_sha256": interpretation["admission_point_in_time_clocks_sha256"],
        "proposed_action": proof["proposed_action"],
        "current_position_state": proof["current_position_state"],
    }
    interpretation["authoritative_binding_sha256"] = paper_loop._paper_canonical_sha256(
        binding_material
    )  # noqa: SLF001
    proof_material = dict(proof)
    proof_material.pop("proof_sha256", None)
    proof["proof_sha256"] = paper_loop._paper_canonical_sha256(  # noqa: SLF001
        proof_material
    )


def _build_test_allocation_input(
    *,
    intent: dict[str, Any],
    signal: dict[str, Any],
    continuous_weight: Any,
):
    return paper_loop._build_allocation_input(  # noqa: SLF001
        intent=intent,
        signal=signal,
        prediction={"features": {}},
        portfolio_context={
            "equity": 10_000.0,
            "available_margin": 9_000.0,
            "wallet_balance": 10_000.0,
            "drawdown_bps": 0.0,
        },
        symbol_exposures={},
        total_exposure=0.0,
        market_microstructure={
            "bid_ask_spread_bps": 1.0,
            "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK",
            "orderbook_depth_usd": 100_000.0,
            "orderbook_depth_source": "orderbook_top5",
            "microstructure_trust_score": 0.4,
            "microstructure_trust_status": "MICROSTRUCTURE_TRUST_SCORE_FOUND",
        },
        ordinary_paper_effective_sizing_weight=continuous_weight,
    )


def test_paper_gate_accepts_exact_ordinary_transport_below_legacy_score_cliff() -> None:
    _, _, signal, redis_client = _transported_ordinary_signal()

    gate = paper_loop._paper_signal_integrity_gate(  # noqa: SLF001
        signal,
        redis_client,
    )

    assert gate["allowed"] is True
    assert gate["ordinary_paper_claimed"] is True
    assert gate["ordinary_paper_revalidated"] is True
    assert gate["legacy_integrity_threshold_controls_admission"] is False
    assert gate["valid_for_paper"] is False
    assert 0.0 < gate["ordinary_paper_effective_sizing_weight"] < 1.0
    assert [commands[0][1] for commands in redis_client.executed_transactions] == [
        signal["replay_snapshot_key"],
        signal["source_redis_key"],
    ]


@pytest.mark.parametrize(
    ("key_kind", "ttl", "expected_reason"),
    [
        ("source", 0, "ordinary_paper_current_prediction_ttl_invalid"),
        ("source", -1, "ordinary_paper_current_prediction_ttl_invalid"),
        ("source", -2, "ordinary_paper_current_prediction_ttl_invalid"),
        ("replay", 0, "ordinary_paper_current_replay_ttl_invalid"),
        ("replay", -1, "ordinary_paper_current_replay_ttl_invalid"),
        ("replay", -2, "ordinary_paper_current_replay_ttl_invalid"),
    ],
)
def test_paper_gate_fails_closed_for_expired_or_persistent_exact_sources(
    key_kind: str,
    ttl: int,
    expected_reason: str,
) -> None:
    _, _, signal, redis_client = _transported_ordinary_signal()
    key = signal["source_redis_key"] if key_kind == "source" else signal["replay_snapshot_key"]
    redis_client.ttls[str(key)] = ttl
    if ttl == -2:
        redis_client.payloads.pop(str(key), None)

    gate = paper_loop._paper_signal_integrity_gate(  # noqa: SLF001
        signal,
        redis_client,
    )

    assert gate["allowed"] is False
    assert gate["ordinary_paper_effective_sizing_weight"] is None
    assert expected_reason in gate["reasons"]


def test_paper_gate_fails_closed_for_transport_tampering() -> None:
    _, _, signal, redis_client = _transported_ordinary_signal()
    signal["ordinary_paper_effective_sizing_weight"] = 1.0

    gate = paper_loop._paper_signal_integrity_gate(  # noqa: SLF001
        signal,
        redis_client,
    )

    assert gate["allowed"] is False
    assert "ordinary_paper_transport_effective_weight_mismatch" in gate["reasons"]


def test_nonordinary_signal_keeps_legacy_score_and_validity_gate() -> None:
    signal = {
        "market_state_id": "mstate_legacy",
        "market_state_integrity_score": 70.0 - 1e-9,
        "valid_for_paper": True,
    }

    gate = paper_loop._paper_signal_integrity_gate(signal, None)  # noqa: SLF001

    assert gate["allowed"] is False
    assert gate["ordinary_paper_claimed"] is False
    assert gate["legacy_integrity_threshold_controls_admission"] is True
    assert "MARKET_STATE_INTEGRITY_SCORE_BELOW_PAPER_MIN" in gate["reasons"]


def test_loaded_prediction_index_is_bounded_pit_and_finality_safe() -> None:
    source, _ = ordinary_source()
    safe_rows: list[dict[str, Any]] = []
    for index in range(20):
        row = deepcopy(source)
        row["prediction_id"] = f"pred-safe-{index}"
        row["timeframe"] = "1m"
        safe_rows.append(row)
    unfinished = deepcopy(source)
    unfinished["prediction_id"] = "pred-unfinished"
    unfinished["candle_closed_confirmed"] = False
    future = deepcopy(source)
    future["prediction_id"] = "pred-future"
    future["decision_time"] = "2026-07-18T00:03:00Z"

    index = paper_loop._build_bounded_pit_final_prediction_index(  # noqa: SLF001
        [*safe_rows, unfinished, future],
        observed_at="2026-07-18T00:02:00Z",
    )

    assert list(index) == ["BTCUSDT"]
    assert len(index["BTCUSDT"]) == (paper_loop.PAPER_STRATEGY_PREDICTION_INDEX_MAX_ROWS_PER_SYMBOL)
    indexed_ids = {row["prediction_id"] for row in index["BTCUSDT"]}
    assert "pred-unfinished" not in indexed_ids
    assert "pred-future" not in indexed_ids


def test_real_route_strategy_shape_is_continuously_interpreted_after_readback() -> None:
    _, _, signal, redis_client = _transported_ordinary_signal(
        market_score=60.0,
        trust_score=0.4,
        sweep_risk=0.5,
    )
    gate = paper_loop._paper_signal_integrity_gate(  # noqa: SLF001
        signal,
        redis_client,
    )
    raw_router, proof, _ = _real_router_and_proof(signal, gate)
    interpretation = proof["interpretation"]
    effective = paper_loop._paper_effective_strategy_router_from_ordinary_proof(  # noqa: SLF001
        raw_router,
        proof,
    )

    assert raw_router["selected_mode"] == "no_trade_mode"
    assert raw_router["block_reason"] == "DATA_QUALITY_BELOW_THRESHOLD"
    assert "DATA_QUALITY_BELOW_THRESHOLD" in raw_router["reason_codes"]
    assert interpretation["original_router_telemetry"] == raw_router
    assert interpretation["strategy_trade_allowed"] is True
    assert interpretation["hard_reasons"] == []
    assert "DATA_QUALITY_BELOW_THRESHOLD" in interpretation["softened_reasons"]
    assert (
        0.0 < interpretation["continuous_weight"] < (gate["ordinary_paper_effective_sizing_weight"])
    )
    assert interpretation["continuous_factors"]["base_weight"] == pytest.approx(
        gate["ordinary_paper_effective_sizing_weight"]
    )
    assert effective["selected_mode"] == "reduce_size_mode"
    assert effective["block_reason"] is None
    assert effective["allowed_actions"] == ["hold", "long"]
    assert effective["size_multiplier"] == 1.0
    assert (
        paper_loop._paper_ordinary_router_proof_rejection_reasons(  # noqa: SLF001
            proof,
            expected_admission_evidence_sha256=gate["ordinary_paper_admission_evidence_sha256"],
            expected_continuous_weight=interpretation["continuous_weight"],
        )
        == []
    )


def test_allocator_input_binds_effective_weight_and_evidence_hash() -> None:
    _, _, signal, redis_client = _transported_ordinary_signal(
        market_score=60.0,
        trust_score=0.4,
        sweep_risk=0.5,
    )
    gate = paper_loop._paper_signal_integrity_gate(  # noqa: SLF001
        signal,
        redis_client,
    )
    assert gate["allowed"] is True
    _, proof, _ = _real_router_and_proof(signal, gate)
    intent = _intent_with_router_proof(signal, gate, proof)
    continuous_weight = proof["interpretation"]["continuous_weight"]

    allocation_input = _build_test_allocation_input(
        intent=intent,
        signal=signal,
        continuous_weight=continuous_weight,
    )

    assert allocation_input.paper_quality_sizing_weight == pytest.approx(continuous_weight)
    assert continuous_weight < gate["ordinary_paper_effective_sizing_weight"]
    assert (
        allocation_input.lineage_ids["ordinary_paper_admission_evidence_sha256"]
        == gate["ordinary_paper_admission_evidence_sha256"]
    )
    assert (
        allocation_input.lineage_ids[paper_loop.ORDINARY_PAPER_ROUTER_LINEAGE_KEY]
        == proof["proof_sha256"]
    )
    assert intent["paper_allocator_ordinary_paper_claimed"] is True


def test_allocator_fails_closed_on_router_weight_mismatch() -> None:
    _, _, signal, redis_client = _transported_ordinary_signal(
        market_score=60.0,
        trust_score=0.4,
        sweep_risk=0.5,
    )
    gate = paper_loop._paper_signal_integrity_gate(  # noqa: SLF001
        signal,
        redis_client,
    )
    _, proof, _ = _real_router_and_proof(signal, gate)
    intent = _intent_with_router_proof(signal, gate, proof)
    continuous_weight = float(proof["interpretation"]["continuous_weight"])

    allocation_input = _build_test_allocation_input(
        intent=intent,
        signal=signal,
        continuous_weight=continuous_weight * 0.5,
    )

    assert allocation_input.risk_veto is True
    assert "ORDINARY_PAPER_ROUTER_CONTINUOUS_WEIGHT_MISMATCH" in (
        allocation_input.risk_veto_reason or ""
    )


def test_allocator_fails_closed_on_router_admission_lineage_mismatch() -> None:
    _, _, signal, redis_client = _transported_ordinary_signal(
        market_score=60.0,
        trust_score=0.4,
        sweep_risk=0.5,
    )
    gate = paper_loop._paper_signal_integrity_gate(  # noqa: SLF001
        signal,
        redis_client,
    )
    _, proof, _ = _real_router_and_proof(signal, gate)
    intent = _intent_with_router_proof(signal, gate, proof)
    intent["ordinary_paper_admission_evidence_sha256"] = "f" * 64

    allocation_input = _build_test_allocation_input(
        intent=intent,
        signal=signal,
        continuous_weight=proof["interpretation"]["continuous_weight"],
    )

    assert allocation_input.risk_veto is True
    assert "ORDINARY_PAPER_ROUTER_ADMISSION_LINEAGE_MISMATCH" in (
        allocation_input.risk_veto_reason or ""
    )


def test_final_append_rereads_exact_ordinary_source_and_replay() -> None:
    _, _, signal, redis_client = _transported_ordinary_signal(
        market_score=60.0,
        trust_score=0.4,
        sweep_risk=0.5,
    )
    gate = paper_loop._paper_signal_integrity_gate(  # noqa: SLF001
        signal,
        redis_client,
    )
    raw_router, proof, router_input = _real_router_and_proof(signal, gate)
    intent = _minimal_final_intent(signal, gate, proof)
    redis_client.executed_transactions.clear()

    appended = paper_loop._paper_append_accepted_with_halted_probe_finalization(  # noqa: SLF001
        [],
        intent,
        None,
        redis_client=redis_client,
        authoritative_ordinary_router_result=raw_router,
        authoritative_ordinary_router_input_material=router_input,
        authoritative_current_position_state="FLAT",
    )

    assert appended is False  # Minimal fixture intentionally misses other final contracts.
    assert [commands[0][1] for commands in redis_client.executed_transactions] == [
        signal["replay_snapshot_key"],
        signal["source_redis_key"],
    ]
    assert intent["ordinary_paper_final_boundary_revalidated"] is True
    assert intent["ordinary_paper_strategy_router_final_boundary_revalidated"] is True
    ordinary_bound = intent["paper_final_admission_contract"]["bound_material"][
        "ordinary_paper_contract"
    ]
    assert ordinary_bound["strategy_router_interpretation_proof"] == proof
    assert ordinary_bound["strategy_router_interpretation_proof_sha256"] == proof["proof_sha256"]
    assert (
        ordinary_bound["strategy_router_continuous_formula"]
        == (proof["interpretation"]["continuous_formula"])
    )
    assert (
        ordinary_bound["strategy_router_continuous_factors"]
        == (proof["interpretation"]["continuous_factors"])
    )
    assert (
        ordinary_bound["strategy_router_softened_reasons"]
        == (proof["interpretation"]["softened_reasons"])
    )


def test_final_append_fails_closed_when_exact_source_changes() -> None:
    _, _, signal, redis_client = _transported_ordinary_signal(
        market_score=60.0,
        trust_score=0.4,
        sweep_risk=0.5,
    )
    gate = paper_loop._paper_signal_integrity_gate(  # noqa: SLF001
        signal,
        redis_client,
    )
    raw_router, proof, router_input = _real_router_and_proof(signal, gate)
    intent = _minimal_final_intent(signal, gate, proof)
    redis_client.payloads[str(signal["source_redis_key"])]["expected_move_after_cost_bps"] = 999.0
    redis_client.executed_transactions.clear()

    appended = paper_loop._paper_append_accepted_with_halted_probe_finalization(  # noqa: SLF001
        [],
        intent,
        None,
        redis_client=redis_client,
        authoritative_ordinary_router_result=raw_router,
        authoritative_ordinary_router_input_material=router_input,
        authoritative_current_position_state="FLAT",
    )

    assert appended is False
    contract = intent["paper_final_admission_contract"]
    assert intent["ordinary_paper_final_boundary_revalidated"] is False
    assert any(
        reason.startswith("FINAL_ORDINARY_PAPER_TRANSPORT_REVALIDATION:")
        for reason in contract["rejection_reasons"]
    )
    assert [commands[0][1] for commands in redis_client.executed_transactions] == [
        signal["replay_snapshot_key"],
        signal["source_redis_key"],
    ]


def test_final_boundary_uses_authoritative_position_not_proof_claim() -> None:
    _, _, signal, redis_client = _transported_ordinary_signal(
        market_score=60.0,
        trust_score=0.4,
        sweep_risk=0.5,
    )
    gate = paper_loop._paper_signal_integrity_gate(signal, redis_client)  # noqa: SLF001
    raw_router, proof, router_input = _real_router_and_proof(signal, gate)
    intent = _minimal_final_intent(signal, gate, proof)

    appended = paper_loop._paper_append_accepted_with_halted_probe_finalization(  # noqa: SLF001
        [],
        intent,
        None,
        redis_client=redis_client,
        authoritative_ordinary_router_result=raw_router,
        authoritative_ordinary_router_input_material=router_input,
        authoritative_current_position_state="LONG",
    )

    assert appended is False
    assert intent["ordinary_paper_strategy_router_final_boundary_revalidated"] is False
    assert any(
        "ORDINARY_PAPER_ROUTER_PROOF_NOT_REPLAYABLE_FROM_FINAL_READBACK" in reason
        for reason in intent["paper_final_admission_contract"]["rejection_reasons"]
    )


def test_final_boundary_rejects_coherently_resealed_router_telemetry() -> None:
    _, _, signal, redis_client = _transported_ordinary_signal(
        market_score=60.0,
        trust_score=0.4,
        sweep_risk=0.5,
    )
    gate = paper_loop._paper_signal_integrity_gate(signal, redis_client)  # noqa: SLF001
    raw_router, proof, router_input = _real_router_and_proof(signal, gate)
    forged = deepcopy(proof)
    telemetry = forged["interpretation"]["original_router_telemetry"]
    telemetry["block_reason"] = None
    telemetry["reason_codes"] = []
    telemetry["selected_mode"] = "trend_mode"
    forged["interpretation"]["router_result_sha256"] = paper_loop._paper_canonical_sha256(telemetry)  # noqa: SLF001
    _coherently_reseal_router_proof(forged)
    intent = _minimal_final_intent(signal, gate, forged)

    appended = paper_loop._paper_append_accepted_with_halted_probe_finalization(  # noqa: SLF001
        [],
        intent,
        None,
        redis_client=redis_client,
        authoritative_ordinary_router_result=raw_router,
        authoritative_ordinary_router_input_material=router_input,
        authoritative_current_position_state="FLAT",
    )

    assert appended is False
    assert intent["ordinary_paper_strategy_router_final_boundary_revalidated"] is False
    assert any(
        "ORDINARY_PAPER_ROUTER_PROOF_NOT_REPLAYABLE_FROM_FINAL_READBACK" in reason
        for reason in intent["paper_final_admission_contract"]["rejection_reasons"]
    )


@pytest.mark.parametrize(
    ("field", "value", "expected_fragment"),
    [
        ("symbol", "ETHUSDT", "SOURCE_IDENTITY_MISMATCH:symbol"),
        (
            "decision_time",
            "2026-07-18T00:00:59Z",
            "PIT_IDENTITY_MISMATCH:decision_time",
        ),
    ],
)
def test_final_boundary_rejects_authoritative_source_or_time_mismatch(
    field: str,
    value: str,
    expected_fragment: str,
) -> None:
    _, _, signal, redis_client = _transported_ordinary_signal(
        market_score=60.0,
        trust_score=0.4,
        sweep_risk=0.5,
    )
    gate = paper_loop._paper_signal_integrity_gate(signal, redis_client)  # noqa: SLF001
    _, proof, router_input = _real_router_and_proof(signal, gate)
    authoritative_input = deepcopy(router_input)
    authoritative_input["market_state_envelope"][field] = value
    authoritative_router = paper_loop.route_strategy(**deepcopy(authoritative_input))
    intent = _minimal_final_intent(signal, gate, proof)

    appended = paper_loop._paper_append_accepted_with_halted_probe_finalization(  # noqa: SLF001
        [],
        intent,
        None,
        redis_client=redis_client,
        authoritative_ordinary_router_result=authoritative_router,
        authoritative_ordinary_router_input_material=authoritative_input,
        authoritative_current_position_state="FLAT",
    )

    assert appended is False
    final_reasons = intent["ordinary_paper_strategy_router_final_boundary_rejection_reasons"]
    assert any(expected_fragment in reason for reason in final_reasons)


def test_allocator_input_fails_closed_if_claimed_weight_is_missing() -> None:
    _, _, signal, _ = _transported_ordinary_signal()
    signal.pop("ordinary_paper_effective_sizing_weight", None)
    intent = {
        **deepcopy(signal),
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "entry_price": 100.0,
        "confidence_calibrated": 0.4,
        "expected_move_after_cost_bps": 1.0,
    }

    allocation_input = paper_loop._build_allocation_input(  # noqa: SLF001
        intent=intent,
        signal=signal,
        prediction={"features": {}},
        portfolio_context={
            "equity": 10_000.0,
            "available_margin": 9_000.0,
            "wallet_balance": 10_000.0,
            "drawdown_bps": 0.0,
        },
        symbol_exposures={},
        total_exposure=0.0,
        market_microstructure={
            "bid_ask_spread_bps": 1.0,
            "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK",
            "orderbook_depth_usd": 100_000.0,
            "orderbook_depth_source": "orderbook_top5",
            "microstructure_trust_score": 0.4,
            "microstructure_trust_status": "MICROSTRUCTURE_TRUST_SCORE_FOUND",
        },
    )

    assert allocation_input.risk_veto is True
    assert "ORDINARY_PAPER_EFFECTIVE_SIZING_WEIGHT_INVALID" in (
        allocation_input.risk_veto_reason or ""
    )
