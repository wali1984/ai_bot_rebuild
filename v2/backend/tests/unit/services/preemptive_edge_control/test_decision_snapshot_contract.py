from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime

import pytest
import redis

import v2.backend.app.services.preemptive_edge_control.decision as decision_module
from v2.backend.app.services.preemptive_edge_control.candidate_loss_risk import (
    adaptive_microstructure_trust_threshold,
    assess_candidate_loss_risk,
)
from v2.backend.app.services.preemptive_edge_control.decision import (
    PreemptiveReplayError,
    adaptive_loss_probability_threshold,
    evaluate_candidate,
    replay_preemptive_decision,
)

DECISION_TIME = "2026-07-17T16:00:00.000000Z"
GUARDIAN = {
    "status": "ACTIVE",
    "a_grade_new_entries_allowed": True,
    "new_entries_allowed": True,
}
TUNING_STATE = {
    "schema_version": "adaptive_gate_tuning_v2",
    "adaptive_loss_probability_threshold": 0.82,
    "adaptive_microstructure_trust_threshold": 0.41,
    "enable_b_grade": True,
    "generated_at": "2026-07-17T15:59:59Z",
    "nested_evidence": {"revision": 7},
}
ALTDATA = {
    "actual_payload_present": True,
    "feature_cutoff": "2026-07-17T15:59:57Z",
    "available_at": "2026-07-17T15:59:58Z",
    "providers_present": ["coinglass", "moralis"],
    "features": {
        "altdata_trade_block_score": 0.1,
        "altdata_reduce_size_score": 0.1,
        "altdata_hedge_required_score": 0.1,
    },
}


def _candidate(**overrides: object) -> dict[str, object]:
    candidate: dict[str, object] = {
        "candidate_id": "candidate-1",
        "prediction_id": "prediction-1",
        "signal_id": "signal-1",
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "side": "long",
        "strategy_id": "trend_mode",
        "market_regime": "TREND",
        "decision_time": "2024-01-01T00:00:00Z",
        "feature_cutoff": "2026-07-17T15:59:50Z",
        "available_at": "2026-07-17T15:59:55Z",
        "confidence_raw": 0.72,
        "confidence_calibrated": 0.70,
        "expected_move_bps": 24.0,
        "expected_move_after_cost_bps": 18.0,
        "composite_microstructure_trust_score": 0.78,
        "stop_distance_bps": 45.0,
        "ATR_bps": 18.0,
        "observed_spread_bps": 2.0,
        "expected_slippage_bps": 2.0,
        "pre_trade_fee_bps": 1.5,
        "funding_bps": 0.2,
        "gross_notional_usd": 1000.0,
        "risk_budget_usd": 8.0,
        "orderbook_depth_usd": 50_000.0,
        "advanced_indicator_event_time": "2026-07-17T15:59:56Z",
        "advanced_indicator_available_at": "2026-07-17T15:59:58Z",
        "advanced_indicator_context": {
            "bullish_fvg_present": False,
            "bearish_fvg_present": False,
            "sweep_risk_long_side": 0.15,
            "trade_tape_confirmation_score": 0.72,
            "fvg_orderbook_trust_confluence": 0.78,
            "fvg_expected_edge_after_cost": 18.0,
            "distance_to_vwap_bps": 4.0,
            "cvd_slope": 0.2,
        },
    }
    candidate.update(overrides)
    return candidate


def _evaluate(
    candidate: dict[str, object] | None = None,
    *,
    tuning_state: object = TUNING_STATE,
    altdata: dict[str, object] | None = None,
    decision_time: object = DECISION_TIME,
) -> dict[str, object]:
    return evaluate_candidate(
        candidate or _candidate(),
        closed_rows=[],
        continuous_edge_guardian_gate=GUARDIAN,
        adaptive_tuning_state=tuning_state,  # type: ignore[arg-type]
        altdata_confluence=altdata or copy.deepcopy(ALTDATA),
        decision_time=decision_time,  # type: ignore[arg-type]
    )


def _healthy_bucket_health() -> dict[str, dict[str, object]]:
    return {
        "symbol:BTCUSDT": {
            "count": 5,
            "wins": 4,
            "losses": 1,
            "gross_win_usd": 8.0,
            "gross_loss_usd": 2.0,
            "net_sum_usd": 6.0,
            "notional_sum_usd": 5_000.0,
            "profit_factor": 4.0,
            "win_rate": 0.8,
            "notional_weighted_expectancy_bps": 12.0,
            "high_confidence_loss_rate": 0.0,
            "atr_stop_rate": 0.0,
        }
    }


def _allow_decision() -> dict[str, object]:
    return evaluate_candidate(
        _candidate(
            expected_move_bps=70.0,
            expected_move_after_cost_bps=60.0,
            trade_tape_confirmation_score=0.8,
            cross_venue_confirmation_score=0.8,
        ),
        bucket_health=_healthy_bucket_health(),
        continuous_edge_guardian_gate=GUARDIAN,
        adaptive_tuning_state=TUNING_STATE,
        altdata_confluence=copy.deepcopy(ALTDATA),
        decision_time=DECISION_TIME,
    )


def test_exact_zero_loss_probability_is_not_replaced_by_missing_evidence_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        decision_module,
        "assess_candidate_loss_risk",
        lambda **_kwargs: {
            "pre_trade_loss_probability": 0.0,
            "pre_trade_loss_risk_reasons": [],
        },
    )

    result = _allow_decision()

    assert result["pre_trade_loss_probability"] == 0.0
    assert result["preemptive_decision"] == "ALLOW"
    assert result["allow_paper_fill"] is True


def test_explicit_aware_decision_time_overrides_candidate_model_clock() -> None:
    result = _evaluate(decision_time="2026-07-17T12:00:00-04:00")

    assert result["preemptive_decision_time"] == DECISION_TIME
    assert result["preemptive_decision_time_source"] == "EXPLICIT_ARGUMENT"
    assert result["preemptive_decision_time_input_valid"] is True
    assert result["preemptive_decision_time"] != _candidate()["decision_time"]
    assert len(str(result["preemptive_input_hash"])) == 64
    int(str(result["preemptive_input_hash"]), 16)


def test_omitted_decision_time_captures_aware_runtime_clock_not_candidate_time() -> None:
    before = datetime.now().astimezone()
    result = evaluate_candidate(
        _candidate(),
        continuous_edge_guardian_gate=GUARDIAN,
        adaptive_tuning_state=TUNING_STATE,
    )
    after = datetime.now().astimezone()
    resolved = datetime.fromisoformat(
        str(result["preemptive_decision_time"]).replace("Z", "+00:00")
    )

    assert result["preemptive_decision_time_source"] == "RUNTIME_CLOCK"
    assert result["preemptive_decision_time_input_valid"] is True
    assert result["preemptive_decision_time"] != _candidate()["decision_time"]
    assert before <= resolved.astimezone() <= after


@pytest.mark.parametrize(
    "invalid_time",
    ["2026-07-17T16:00:00", "not-a-clock", True, 1_721_232_000],
)
def test_invalid_explicit_decision_time_fails_entry_closed(
    invalid_time: object,
) -> None:
    result = _evaluate(decision_time=invalid_time)

    assert result["preemptive_decision"] == "NO_TRADE"
    assert result["allow_paper_fill"] is False
    assert result["preemptive_decision_time_input_valid"] is False
    assert result["preemptive_decision_time_source"] == (
        "INVALID_EXPLICIT_ARGUMENT_RUNTIME_CLOCK_BLOCK"
    )
    assert "PREEMPTIVE_DECISION_TIME_INVALID" in result["preemptive_decision_reasons"]
    assert result["preemptive_decision_time"] != _candidate()["decision_time"]


def test_unmaterializable_candidate_fails_closed() -> None:
    class Unmaterializable:
        def __deepcopy__(self, memo: dict[int, object]) -> object:
            raise RuntimeError("source changed during snapshot")

    result = _evaluate(_candidate(adversarial_value=Unmaterializable()))

    assert result["preemptive_decision"] == "NO_TRADE"
    assert result["allow_paper_fill"] is False
    assert "CANDIDATE_PAYLOAD_MISSING" in result["preemptive_decision_reasons"]


def test_explicit_replay_time_and_mapping_order_are_canonical() -> None:
    reordered_tuning = dict(reversed(list(TUNING_STATE.items())))
    utc_result = _evaluate(tuning_state=TUNING_STATE, decision_time=DECISION_TIME)
    offset_result = _evaluate(
        tuning_state=reordered_tuning,
        decision_time="2026-07-17T12:00:00-04:00",
    )

    assert utc_result["preemptive_input_hash"] == offset_result["preemptive_input_hash"]
    assert utc_result["preemptive_decision_id"] == offset_result["preemptive_decision_id"]
    expected_tuning_hash = hashlib.sha256(
        json.dumps(
            TUNING_STATE,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    assert utc_result["adaptive_tuning_state_hash"] == expected_tuning_hash


def test_input_hash_binds_advanced_altdata_cost_tuning_and_clock_inputs() -> None:
    baseline = _evaluate()
    hashes = {baseline["preemptive_input_hash"]}

    advanced_candidate = _candidate()
    advanced_context = copy.deepcopy(advanced_candidate["advanced_indicator_context"])
    assert isinstance(advanced_context, dict)
    advanced_context["cvd_slope"] = -0.3
    advanced_candidate["advanced_indicator_context"] = advanced_context
    hashes.add(_evaluate(advanced_candidate)["preemptive_input_hash"])

    altdata = copy.deepcopy(ALTDATA)
    altdata["features"]["altdata_trade_block_score"] = 0.9  # type: ignore[index]
    hashes.add(_evaluate(altdata=altdata)["preemptive_input_hash"])

    hashes.add(_evaluate(_candidate(observed_spread_bps=7.0))["preemptive_input_hash"])

    tuning = copy.deepcopy(TUNING_STATE)
    tuning["adaptive_loss_probability_threshold"] = 0.79
    hashes.add(_evaluate(tuning_state=tuning)["preemptive_input_hash"])

    hashes.add(_evaluate(decision_time="2026-07-17T16:00:00.000001Z")["preemptive_input_hash"])

    assert len(hashes) == 6


def test_tuning_and_candidate_are_materialized_once_before_evaluation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_candidate = _candidate()
    baseline_tuning = copy.deepcopy(TUNING_STATE)
    baseline = _evaluate(baseline_candidate, tuning_state=baseline_tuning)

    adversarial_candidate = _candidate()
    adversarial_tuning = copy.deepcopy(TUNING_STATE)
    original_assessor = decision_module.assess_candidate_loss_risk

    def mutate_external_sources_then_assess(**kwargs: object) -> dict[str, object]:
        adversarial_candidate["observed_spread_bps"] = 999.0
        adversarial_candidate["advanced_indicator_context"] = {"cvd_slope": -999.0}
        adversarial_tuning["adaptive_loss_probability_threshold"] = 0.01
        adversarial_tuning["adaptive_microstructure_trust_threshold"] = 0.99
        adversarial_tuning["nested_evidence"]["revision"] = 999  # type: ignore[index]
        return original_assessor(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        decision_module,
        "assess_candidate_loss_risk",
        mutate_external_sources_then_assess,
    )
    adversarial = _evaluate(
        adversarial_candidate,
        tuning_state=adversarial_tuning,
    )

    assert adversarial_tuning["adaptive_loss_probability_threshold"] == 0.01
    assert adversarial_candidate["observed_spread_bps"] == 999.0
    assert adversarial["adaptive_loss_probability_threshold_used"] == 0.82
    assert adversarial["adaptive_microstructure_trust_threshold_used"] == 0.41
    assert adversarial["preemptive_input_hash"] == baseline["preemptive_input_hash"]
    assert adversarial["preemptive_decision_id"] == baseline["preemptive_decision_id"]


def test_evaluation_performs_no_redis_read(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden_redis_read(*args: object, **kwargs: object) -> object:
        raise AssertionError("preemptive evaluation must not read Redis")

    monkeypatch.setattr(redis.Redis, "get", forbidden_redis_read)

    result = _evaluate()

    assert result["adaptive_tuning_state_status"] == "VALID_EXPLICIT_SNAPSHOT"


def test_replay_round_trip_allow_uses_retained_bucket_health() -> None:
    original = _allow_decision()
    material = original["preemptive_input_material"]
    assert isinstance(material, dict)

    replayed = replay_preemptive_decision(
        material,
        expected_input_hash=str(original["preemptive_input_hash"]),
    )

    assert original["preemptive_decision"] == "ALLOW"
    assert original["allow_paper_fill"] is True
    assert material["schema_version"] == "preemptive_edge_control_input_v2"
    assert material["resolved_bucket_health_snapshot"] == _healthy_bucket_health()
    assert replayed == original


def test_replay_round_trip_preserves_blocked_decision() -> None:
    original = evaluate_candidate(
        _candidate(
            expected_move_bps=2.0,
            expected_move_after_cost_bps=-1.0,
            trade_tape_confirmation_score=0.8,
            cross_venue_confirmation_score=0.8,
        ),
        bucket_health=_healthy_bucket_health(),
        continuous_edge_guardian_gate=GUARDIAN,
        adaptive_tuning_state=TUNING_STATE,
        altdata_confluence=copy.deepcopy(ALTDATA),
        decision_time=DECISION_TIME,
    )

    replayed = replay_preemptive_decision(
        original["preemptive_input_material"],  # type: ignore[arg-type]
        expected_input_hash=str(original["preemptive_input_hash"]),
    )

    assert original["preemptive_decision"] == "NO_TRADE"
    assert original["allow_paper_fill"] is False
    assert replayed == original


def test_replay_rejects_tampered_derived_material_without_external_reads() -> None:
    original = _allow_decision()
    material = copy.deepcopy(original["preemptive_input_material"])
    assert isinstance(material, dict)
    bucket_assessment = material["bucket_assessment"]
    assert isinstance(bucket_assessment, dict)
    bucket_assessment["bucket_negative"] = True

    with pytest.raises(PreemptiveReplayError) as exc_info:
        replay_preemptive_decision(material)

    assert exc_info.value.reason == ("PREEMPTIVE_REPLAY_MATERIAL_REGENERATION_MISMATCH")


def test_replay_rejects_legacy_material_as_unreplayable() -> None:
    original = _allow_decision()
    material = copy.deepcopy(original["preemptive_input_material"])
    assert isinstance(material, dict)
    material["schema_version"] = "preemptive_edge_control_input_v1"
    material.pop("resolved_bucket_health_snapshot")

    with pytest.raises(PreemptiveReplayError) as exc_info:
        replay_preemptive_decision(material)

    assert exc_info.value.reason == "PREEMPTIVE_REPLAY_UNSUPPORTED_INPUT_SCHEMA"


def test_replay_performs_no_redis_read(monkeypatch: pytest.MonkeyPatch) -> None:
    original = _allow_decision()

    def forbidden_redis_read(*args: object, **kwargs: object) -> object:
        raise AssertionError("preemptive replay must not read Redis")

    monkeypatch.setattr(redis.Redis, "get", forbidden_redis_read)
    monkeypatch.setattr(redis, "from_url", forbidden_redis_read)

    replayed = replay_preemptive_decision(
        original["preemptive_input_material"],  # type: ignore[arg-type]
        expected_input_hash=str(original["preemptive_input_hash"]),
    )

    assert replayed == original


@pytest.mark.parametrize(
    ("invalid_state", "expected_status"),
    [
        (None, "ABSENT_CONSERVATIVE_DEFAULTS"),
        ({}, "EMPTY_CONSERVATIVE_DEFAULTS"),
        ("not-a-mapping", "INVALID_CONSERVATIVE_DEFAULTS"),
        (
            {
                "adaptive_loss_probability_threshold": float("nan"),
                "adaptive_microstructure_trust_threshold": float("inf"),
                "enable_b_grade": True,
            },
            "VALID_EXPLICIT_SNAPSHOT",
        ),
        (
            {
                "adaptive_loss_probability_threshold": "0.90",
                "adaptive_microstructure_trust_threshold": "0.30",
                "enable_b_grade": True,
            },
            "VALID_EXPLICIT_SNAPSHOT",
        ),
    ],
)
def test_absent_or_invalid_tuning_uses_conservative_thresholds(
    invalid_state: object,
    expected_status: str,
) -> None:
    result = _evaluate(tuning_state=invalid_state)

    assert result["adaptive_tuning_state_status"] == expected_status
    assert result["adaptive_loss_probability_threshold_used"] == 0.80
    assert result["adaptive_microstructure_trust_threshold_used"] == 0.45
    assert result["adaptive_loss_probability_threshold_source"] == (
        "CONSERVATIVE_DEFAULT_ABSENT_OR_INVALID"
    )
    assert str(result["adaptive_microstructure_trust_threshold_source"]).startswith(
        "CONSERVATIVE_DEFAULT"
    )


def test_candidate_loss_risk_uses_only_supplied_tuning_snapshot() -> None:
    kwargs = {
        "cost_edge": {"expected_edge_after_cost_bps": 10.0},
        "confidence": {"confidence_overstatement_risk": 0.1},
        "bucket": {},
        "regime": {"regime_compatibility_score": 0.8},
        "exit_plan": {"exit_feasibility_score": 0.8},
        "microstructure_trust_score": 0.40,
    }

    conservative = assess_candidate_loss_risk(**kwargs)
    b_grade_snapshot = assess_candidate_loss_risk(
        **kwargs,
        adaptive_tuning_state={"enable_b_grade": True},
    )
    invalid_explicit = assess_candidate_loss_risk(
        **kwargs,
        adaptive_tuning_state={
            "enable_b_grade": True,
            "adaptive_microstructure_trust_threshold": "invalid",
        },
    )

    assert "MICROSTRUCTURE_TRUST_LOW" in conservative["pre_trade_loss_risk_reasons"]
    assert "MICROSTRUCTURE_TRUST_LOW" not in b_grade_snapshot["pre_trade_loss_risk_reasons"]
    assert "MICROSTRUCTURE_TRUST_LOW" in invalid_explicit["pre_trade_loss_risk_reasons"]
    assert adaptive_microstructure_trust_threshold(None) == 0.45
    assert adaptive_loss_probability_threshold(None) == 0.80
