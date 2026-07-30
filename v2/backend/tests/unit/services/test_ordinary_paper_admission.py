from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.confidence import (
    CONFIDENCE_HEAD_ACTIONS,
    CONFIDENCE_HEAD_SCHEMA_VERSION,
    CONFIDENCE_LABEL_SEMANTICS,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.on_policy_behavior import (
    build_exact_cost_provenance,
    canonical_sha256,
)
from v2.backend.app.services.ordinary_paper_admission import (
    ORDINARY_PAPER_ADMISSION_MODE,
    ORDINARY_PAPER_ADMISSION_SCHEMA_VERSION,
    ORDINARY_PAPER_QUALITY_FORMULA,
    OrdinaryPaperAdmissionIntegrityError,
    OrdinaryPaperAdmissionResult,
    assess_ordinary_paper_candidate,
    build_microstructure_trust_evidence,
    ordinary_paper_admission_result_rejection_reasons,
    revalidate_ordinary_paper_transport,
)

_TENSOR_ID = "v2_hybrid_tensor_" + ("d" * 32)
_TENSOR_SOURCE_LINEAGE_HASH = "e" * 64


def _bind_microstructure_evidence(
    source: dict[str, object],
    *,
    trust_score: float,
    sweep_risk: float,
    action: str,
    latency_within_bound: bool,
    book_sequence_gap: bool = False,
    sequence_gap_free: bool = True,
    sweep_direction_uncertain: bool = False,
    feed_integrity_pass: bool = True,
    missing_components: list[str] | None = None,
) -> None:
    symbol = str(source["symbol"])
    timeframe = str(source["timeframe"])
    source_payload = {
        "schema_version": "microstructure_trust_score_v2",
        "symbol": symbol,
        "timeframe": timeframe,
        "available_at": "2026-07-18T00:00:20Z",
        "decision_time": "2026-07-18T00:00:30Z",
        "generated_at": "2026-07-18T00:00:31Z",
        "microstructure_trust_score": trust_score,
        "composite_microstructure_trust_score": trust_score,
        "microstructure_action": action,
        "sweep_risk": sweep_risk,
        "sweep_risk_score": sweep_risk,
        "book_sequence_gap": book_sequence_gap,
        "sequence_gap_flag": int(book_sequence_gap),
        "feed_integrity_pass": feed_integrity_pass,
        "latency_within_bound": latency_within_bound,
        "sequence_gap_free": sequence_gap_free,
        "sweep_direction_uncertain": sweep_direction_uncertain,
        "missing_components": list(missing_components or []),
    }
    evidence = build_microstructure_trust_evidence(
        source_payload=source_payload,
        source_payload_readback=source_payload,
        source_key=f"v2:microstructure:trust_score:{symbol}:{timeframe}",
        source_observed_ttl_seconds=60,
        tensor_id=_TENSOR_ID,
        feature_snapshot_id=str(source["feature_snapshot_id"]),
        tensor_source_lineage_hash=_TENSOR_SOURCE_LINEAGE_HASH,
        tensor_decision_time="2026-07-18T00:00:55Z",
        symbol=symbol,
        timeframe=timeframe,
    )
    source["microstructure_trust_evidence"] = evidence
    source["microstructure_trust_evidence_sha256"] = evidence["evidence_sha256"]
    source_hashes = source.setdefault("source_hashes", {})
    assert isinstance(source_hashes, dict)
    source_hashes.update(
        {
            "feature_tensor_id": _TENSOR_ID,
            "tensor_source_lineage_hash": _TENSOR_SOURCE_LINEAGE_HASH,
            "microstructure_trust_evidence_sha256": evidence["evidence_sha256"],
            "microstructure_trust_source_payload_sha256": evidence["source_payload_sha256"],
        }
    )


def _cost_provenance(symbol: str) -> dict[str, object]:
    orderbook = {
        "schema_version": "v2_orderbook_features_v1",
        "symbol": symbol,
        "event_time": "2026-07-18T00:00:00Z",
        "available_at": "2026-07-18T00:00:01Z",
        "generated_at": "2026-07-18T00:00:02Z",
        "spread_bps": 0.5,
        "depth_5_bid_usd": 100.0,
        "depth_5_ask_usd": 120.0,
        "sequence_gap_flag": 0,
    }
    fee_evidence = {
        "schema_version": "paper_cost_fee_schedule_evidence_v1",
        "configuration_kind": "CONFIGURED_TAKER_FEE_BPS_PER_SIDE",
        "taker_fee_bps_per_side": 0.5,
        "fee_source": "unit:paper_fee_schedule",
    }
    notional_evidence = {
        "schema_version": "paper_cost_notional_configuration_evidence_v1",
        "configuration_kind": "COST_MODEL_REFERENCE_NOTIONAL_USD",
        "notional_usd": 100.0,
        "notional_source": "UNIT_EXPLICIT_COST_MODEL_NOTIONAL_USD",
    }
    source = {
        "symbol": symbol,
        "round_trip_cost_bps": 2.0,
        "taker_fee_bps_per_side": 0.5,
        "fee_source": "unit:paper_fee_schedule",
        "fee_schedule_evidence": fee_evidence,
        "fee_schedule_evidence_sha256": canonical_sha256(fee_evidence),
        "spread_bps": 0.5,
        "spread_source": "orderbook_features_binance_live_spread_bps",
        "spread_age_seconds": 39.0,
        "impact_per_side_bps": 0.25,
        "impact_source": "notional_over_top5_depth_times_half_spread",
        "depth_used_usd": 100.0,
        "notional_usd_assumed": 100.0,
        "notional_configuration_evidence": notional_evidence,
        "notional_configuration_evidence_sha256": canonical_sha256(notional_evidence),
        "freshness_status": "FRESH_ORDERBOOK",
        "conservative_floor_applied": False,
        "flat_baseline_round_trip_bps": 12.0,
        "orderbook_key": f"v2:orderbook:features:binance:{symbol}",
        "computed_utc": "2026-07-18T00:00:40Z",
        "available_at": "2026-07-18T00:00:40Z",
        "orderbook_schema_version": "v2_orderbook_features_v1",
        "orderbook_source_payload_sha256": canonical_sha256(orderbook),
        "orderbook_source_payload": orderbook,
        "orderbook_observed_at": "2026-07-18T00:00:00Z",
        "orderbook_available_at": "2026-07-18T00:00:01Z",
        "orderbook_generated_at": "2026-07-18T00:00:02Z",
        "orderbook_source_clock_field": "available_at",
        "orderbook_sequence_gap_flag": False,
        "source_future_clock_invalid": False,
        "adaptive_max_age_seconds": 120.0,
        "adaptive_freshness_sample_count": 3,
        "adaptive_freshness_method": ("RECENT_DISTINCT_SOURCE_INTERVAL_MEDIAN_PLUS_MAD"),
        "adaptive_freshness_proven": True,
        "expires_at": "2026-07-18T00:02:01Z",
        "publication_ttl_seconds": 81,
        "estimator_version": "adaptive_cost_model_v1",
        "notes": [],
        "scope": "PAPER_ONLY_ADAPTIVE_COST_MODEL",
    }
    return build_exact_cost_provenance(
        source_key=f"v2:costs:round_trip_bps:{symbol}",
        source_payload=source,
        consumer_observed_at="2026-07-18T00:00:50Z",
    )


def ordinary_source(
    *,
    symbol: str = "BTCUSDT",
    confidence: float = 0.2,
    coverage: float = 10.0,
    edge_bps: float = 0.1,
    microstructure_trust_score: float = 0.5,
    sweep_risk_score: float = 0.2,
    microstructure_action: str = "REDUCE_SIZE",
    selected_action: str = "long",
    latency_within_bound: bool = True,
) -> tuple[dict[str, object], dict[str, object]]:
    prediction_id = f"pred_ordinary_{symbol}"
    replay_snapshot = {
        "schema_version": "v2_test_replay_snapshot_v1",
        "decision_id": prediction_id,
        "replay_snapshot_id": prediction_id,
        "symbol": symbol,
        "feature_vector_hash": "a" * 64,
    }
    relative_edge = abs(edge_bps) / (abs(edge_bps) + 2.0)
    weight = (coverage / 100.0) * confidence * relative_edge
    calibration = {
        "calibration_fitted": True,
        "probability_semantics_valid": True,
        "label_semantics": CONFIDENCE_LABEL_SEMANTICS,
        "confidence_head_schema_version": CONFIDENCE_HEAD_SCHEMA_VERSION,
        "confidence_head_actions": list(CONFIDENCE_HEAD_ACTIONS),
        "selected_action_is_directional": True,
        "selected_action": selected_action,
        "model_parameter_fingerprint": "c" * 64,
    }
    source: dict[str, object] = {
        "prediction_id": prediction_id,
        "generated_utc": "2026-07-18T00:01:00Z",
        "signal_id": f"sig_{prediction_id}",
        "decision_id": prediction_id,
        "market_state_id": f"mstate_{prediction_id}",
        "symbol": symbol,
        "timeframe": "1m",
        "selected_action": selected_action,
        "feature_snapshot_id": f"fs_{prediction_id}",
        "feature_vector_hash": "a" * 64,
        "input_feature_hash": "a" * 64,
        "checkpoint_id": "ckpt_test",
        "model_version": "v2_hybrid_cuda_masa_ppo",
        "cycle_id": "cycle_test",
        "process_instance_id": "process_test",
        "candidate_policy_fingerprint": "c" * 64,
        "ordinary_paper_admission_schema_version": (ORDINARY_PAPER_ADMISSION_SCHEMA_VERSION),
        "ordinary_paper_quality_schema_version": (ORDINARY_PAPER_ADMISSION_SCHEMA_VERSION),
        "ordinary_paper_admission_mode": ORDINARY_PAPER_ADMISSION_MODE,
        "ordinary_paper_fill_allowed": True,
        "ordinary_paper_admission_rejection_reasons": [],
        "ordinary_paper_gate_block_reasons": [],
        "paper_quality_sizing_formula": ORDINARY_PAPER_QUALITY_FORMULA,
        "paper_quality_sizing_weight": weight,
        "paper_quality_coverage_component": coverage / 100.0,
        "paper_quality_calibrated_probability_component": confidence,
        "paper_quality_relative_after_cost_edge_component": relative_edge,
        "paper_quality_zero_boundary_semantics": (
            "EXACT_ZERO_IS_STRUCTURAL_NO_INFORMATION_AND_BLOCKS;"
            "EVERY_FINITE_POSITIVE_VALUE_IS_CONTINUOUSLY_WEIGHTED"
        ),
        "paper_quality_market_static_threshold_used": False,
        "paper_quality_paper_only": True,
        "paper_quality_routes_to_live": False,
        "paper_quality_places_real_order": False,
        "legacy_static_thresholds_telemetry_only": {
            "controls_ordinary_paper_fill": False,
            "controls_ordinary_orchestrator_handoff": False,
            "controls_ordinary_risk_handoff": False,
        },
        "data_coverage_percent": coverage,
        "confidence_calibrated": confidence,
        "confidence_calibration_fitted": True,
        "confidence_calibration": calibration,
        "expected_move_after_cost_bps": edge_bps,
        "round_trip_cost_bps": 2.0,
        "exact_cost_provenance": _cost_provenance(symbol),
        "exact_cost_provenance_valid": True,
        "exact_cost_provenance_rejection_reasons": [],
        "on_policy_sampling_selected": False,
        "trust_row_accepted_for_training": True,
        "trust_row_valid_for_training": True,
        "trust_row_trainer_consumable": True,
        "row_classification": "TRAINABLE",
        "training_trust_reject_reasons": [],
        "backfilled": False,
        "is_backfilled": False,
        "missing_feature_count": 0,
        "stale_feature_count": 0,
        "missing_feature_names": [],
        "stale_feature_names": [],
        "feature_freshness_state": "CURRENT",
        "missing_candle_count": 0,
        "duplicate_event_count": 0,
        "out_of_order_event_count": 0,
        "decision_time": "2026-07-18T00:01:00Z",
        "feature_cutoff": "2026-07-18T00:00:10Z",
        "available_at": "2026-07-18T00:00:50Z",
        "candle_closed_confirmed": True,
        "candle_open_time": "2026-07-17T23:59:10Z",
        "candle_close_time": "2026-07-18T00:00:10Z",
        "source_event_time_est": "2026-07-18T00:00:00Z",
        "source_received_time_est": "2026-07-18T00:00:01Z",
        "source_available_time": "2026-07-18T00:00:50Z",
        "masa_feature_cutoff": "2026-07-18T00:00:10Z",
        "ppo_feature_cutoff": "2026-07-18T00:00:10Z",
        "ppo_decision_time": "2026-07-18T00:01:00Z",
        "all_tf_candle_timestamps": ["2026-07-18T00:00:10Z"],
        "all_source_event_times": ["2026-07-18T00:00:00Z"],
        "source_candle_timestamps": ["2026-07-18T00:00:10Z"],
        "mtf_snapshot_id": f"mtf_{prediction_id}",
        "mtf_snapshot_valid": True,
        "replay_snapshot_id": prediction_id,
        "replay_snapshot_key": f"v2:replay:snapshots:{prediction_id}",
        "replay_snapshot_ready": True,
        "replay_snapshot_write_success": True,
        "replay_snapshot_write_acknowledged": True,
        "replay_snapshot_readback_verified": True,
        "replay_snapshot_content_sha256": canonical_sha256(replay_snapshot),
        "replay_snapshot_ttl_seconds": 86_400,
        "trust_schema_version": "pipeline_trust_v3",
        "trust_gate_result": {"allowed": True, "reject_reasons": []},
        "source_hashes": {"feature_vector_hash": "a" * 64},
        "source_availability": {"ohlcv": 1},
        "source_availability_vector": [1],
        "paper_fill_allowed": True,
        "routes_to_orchestrator": True,
        "prediction_eligible": True,
        "risk_eligible": True,
        "paper_eligible": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "exchange_mutation": False,
        "trainer_direct_trading": False,
        "source_redis_key": f"v2:prediction_by_id:{prediction_id}",
        "source_prediction_observed_ttl_seconds": 300,
    }
    _bind_microstructure_evidence(
        source,
        trust_score=microstructure_trust_score,
        sweep_risk=sweep_risk_score,
        action=microstructure_action,
        latency_within_bound=latency_within_bound,
    )
    return source, replay_snapshot


def _assess(
    source: dict[str, object],
    replay_snapshot: dict[str, object],
    *,
    market_score: float,
    trust_score: float,
    sweep_risk: float,
    action: str,
    latency_within_bound: bool = True,
    current_ttl: int = 300,
):
    source = deepcopy(source)
    _bind_microstructure_evidence(
        source,
        trust_score=trust_score,
        sweep_risk=sweep_risk,
        action=action,
        latency_within_bound=latency_within_bound,
    )
    return assess_ordinary_paper_candidate(
        source,
        market_state_integrity_score=market_score,
        market_state_reject_reasons=[],
        market_state_quality_reasons=(["LATENCY_ABOVE_GATE"] if not latency_within_bound else []),
        microstructure_trust_score=trust_score,
        sweep_risk_score=sweep_risk,
        microstructure_action=action,
        book_sequence_gap=False,
        feed_integrity_pass=True,
        latency_within_bound=latency_within_bound,
        sequence_gap_free=True,
        sweep_direction_uncertain=False,
        microstructure_missing_components=[],
        legacy_microstructure_block_reasons=[
            f"LEGACY_ACTION_{action}",
            "LEGACY_SCORE_BAND",
        ],
        replay_snapshot=replay_snapshot,
        replay_snapshot_observed_ttl_seconds=current_ttl,
    )


def test_admission_result_requires_factory_and_dataclass_replace_cannot_reseal() -> None:
    source, replay = ordinary_source()
    assessment = _assess(
        source,
        replay,
        market_score=80.0,
        trust_score=0.5,
        sweep_risk=0.2,
        action="REDUCE_SIZE",
    )
    assert (
        ordinary_paper_admission_result_rejection_reasons(
            assessment,
            require_accepted=True,
        )
        == []
    )

    with pytest.raises(
        OrdinaryPaperAdmissionIntegrityError,
        match="ORDINARY_PAPER_ADMISSION_RESULT_FACTORY_REQUIRED",
    ):
        OrdinaryPaperAdmissionResult(
            claimed=True,
            accepted=True,
            rejection_reasons=(),
            publisher_sizing_weight=assessment.publisher_sizing_weight,
            effective_sizing_weight=assessment.effective_sizing_weight,
            evidence_sha256=assessment.evidence_sha256,
            _evidence_json="{}",
        )
    with pytest.raises(
        OrdinaryPaperAdmissionIntegrityError,
        match="ORDINARY_PAPER_ADMISSION_RESULT_FACTORY_REQUIRED",
    ):
        replace(assessment, accepted=False)


def test_admission_evidence_access_is_a_fresh_hash_bound_copy() -> None:
    source, replay = ordinary_source()
    assessment = _assess(
        source,
        replay,
        market_score=80.0,
        trust_score=0.5,
        sweep_risk=0.2,
        action="REDUCE_SIZE",
    )
    first = assessment.evidence
    second = assessment.evidence
    assert first is not None and second is not None and first is not second
    first["symbol"] = "FORGED"

    assert assessment.evidence is not None
    assert assessment.evidence["symbol"] == source["symbol"]
    assert (
        ordinary_paper_admission_result_rejection_reasons(
            assessment,
            require_accepted=True,
        )
        == []
    )


def test_legacy_threshold_epsilon_pair_is_continuous_not_a_cliff() -> None:
    source, replay = ordinary_source()

    below = _assess(
        source,
        replay,
        market_score=80.0 - 1e-6,
        trust_score=0.45 - 1e-6,
        sweep_risk=0.75 + 1e-6,
        action="SHADOW_ONLY",
    )
    above = _assess(
        source,
        replay,
        market_score=80.0 + 1e-6,
        trust_score=0.45 + 1e-6,
        sweep_risk=0.75 - 1e-6,
        action="REDUCE_SIZE",
    )

    assert below.accepted is True
    assert above.accepted is True
    assert 0.0 < below.effective_sizing_weight < above.effective_sizing_weight
    assert above.effective_sizing_weight <= above.publisher_sizing_weight
    transport = below.transport_payload()
    assert transport["ordinary_paper_raw_microstructure_action"] == "SHADOW_ONLY"
    assert transport["ordinary_paper_effective_microstructure_action"] == ("REDUCE_SIZE")


def test_latency_false_is_degraded_evidence_not_an_admission_cliff() -> None:
    source, replay = ordinary_source()

    degraded = _assess(
        source,
        replay,
        market_score=72.0,
        trust_score=0.6,
        sweep_risk=0.2,
        action="REDUCE_SIZE",
        latency_within_bound=False,
    )
    current = _assess(
        source,
        replay,
        market_score=92.0,
        trust_score=0.6,
        sweep_risk=0.2,
        action="REDUCE_SIZE",
        latency_within_bound=True,
    )

    assert degraded.accepted is True
    assert current.accepted is True
    assert degraded.effective_sizing_weight <= current.effective_sizing_weight


@pytest.mark.parametrize("observed_ttl", [None, -2, -1, 0, 301])
def test_replay_ttl_must_be_current_positive_and_never_refreshed(
    observed_ttl: int | None,
) -> None:
    source, replay = ordinary_source()
    assessment = _assess(
        source,
        replay,
        market_score=80.0,
        trust_score=0.5,
        sweep_risk=0.2,
        action="REDUCE_SIZE",
        current_ttl=300,
    )
    assert assessment.accepted is True
    transport = assessment.transport_payload()

    revalidated = revalidate_ordinary_paper_transport(
        transport,
        replay_snapshot=replay,
        replay_snapshot_observed_ttl_seconds=observed_ttl,
        expected_identity=source,
    )

    assert revalidated.accepted is False
    assert "ordinary_paper_current_replay_ttl_invalid" in (revalidated.rejection_reasons)


def test_transport_hash_and_weight_tampering_fail_closed() -> None:
    source, replay = ordinary_source()
    assessment = _assess(
        source,
        replay,
        market_score=79.0,
        trust_score=0.44,
        sweep_risk=0.76,
        action="SHADOW_ONLY",
    )
    assert assessment.accepted is True
    tampered = deepcopy(assessment.transport_payload())
    tampered["ordinary_paper_admission_evidence"]["paper_quality_sizing_weight"] = 1.0

    revalidated = revalidate_ordinary_paper_transport(
        tampered,
        replay_snapshot=replay,
        replay_snapshot_observed_ttl_seconds=299,
        expected_identity=source,
    )

    assert revalidated.accepted is False
    assert "ordinary_paper_evidence_hash_mismatch" in revalidated.rejection_reasons
    assert revalidated.effective_sizing_weight is None


@pytest.mark.parametrize(
    ("mutation", "assessment_override", "expected_reason"),
    [
        (
            {"candle_closed_confirmed": False},
            {},
            "ordinary_paper_candle_closed_confirmed_not_proven",
        ),
        (
            {"available_at": "2026-07-18T00:01:01Z"},
            {},
            "ordinary_paper_feature_clock_order_invalid",
        ),
        (
            {},
            {"book_sequence_gap": True},
            "ordinary_paper_book_sequence_continuity_not_proven",
        ),
        (
            {},
            {"sequence_gap_free": False},
            "ordinary_paper_orchestrator_sequence_gap_free_not_proven",
        ),
    ],
)
def test_pit_finality_and_sequence_invariants_remain_hard_failures(
    mutation: dict[str, object],
    assessment_override: dict[str, object],
    expected_reason: str,
) -> None:
    source, replay = ordinary_source()
    source.update(mutation)
    kwargs = {
        "market_state_integrity_score": 80.0,
        "market_state_reject_reasons": [],
        "market_state_quality_reasons": [],
        "microstructure_trust_score": 0.5,
        "sweep_risk_score": 0.2,
        "microstructure_action": "REDUCE_SIZE",
        "book_sequence_gap": False,
        "feed_integrity_pass": True,
        "latency_within_bound": True,
        "sequence_gap_free": True,
        "sweep_direction_uncertain": False,
        "microstructure_missing_components": [],
        "legacy_microstructure_block_reasons": [],
        "replay_snapshot": replay,
        "replay_snapshot_observed_ttl_seconds": 300,
    }
    kwargs.update(assessment_override)

    assessment = assess_ordinary_paper_candidate(source, **kwargs)

    assert assessment.accepted is False
    assert expected_reason in assessment.rejection_reasons
