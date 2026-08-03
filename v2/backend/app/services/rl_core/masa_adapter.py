"""MASA-shape adapter for P0.2B (paper-only)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Sequence

from v2.backend.app.services.market_state_integrity import (
    EventTimeAligner,
    TrustGateRejectedError,
    build_market_state_envelope_from_snapshot,
    coerce_market_state_envelope,
    parse_timestamp,
    persist_decision_replay,
    stable_hash,
)

from .policy import (
    ACTION_LABELS,
    HEDGE_ACTION_CLASSIFICATION,
    MISSING_POLICY_COMPONENTS,
    MODEL_SOURCE_CLASSIFICATION,
    PolicyForwardResult,
    V2NativeCPUPolicy,
)

LEGACY_MASA_AGENT_SHA256 = "0c7496336ca00c0f006d9a294ea67e736e2c3f2a3e4202b98cd6925dff891080"


@dataclass(frozen=True)
class MASAActionValueResult:
    decision_id: str
    masa_prediction_id: str
    selected_action: str
    selected_action_index: int
    action_logits: tuple[float, ...]
    action_probabilities: tuple[float, ...]
    value_estimate_bps: float
    policy_id: str
    feature_snapshot_id: str
    hedge_action_classification: str
    model_source_classification: str
    missing_policy_components: tuple[str, ...]
    is_finite: bool
    model_version: str
    generated_at: str
    trained_until: str
    feature_cutoff: str
    forecast_horizon: str
    confidence: float
    validity_until: str
    input_feature_hash: str
    trust_gate_result: Any


class V2MASAAdapter:
    def __init__(self, *, policy: V2NativeCPUPolicy | None = None) -> None:
        self._policy = policy or V2NativeCPUPolicy()

    @property
    def policy_id(self) -> str:
        return self._policy.policy_id

    def get_action_and_value(
        self,
        observation_tensor: Sequence[float],
        *,
        feature_snapshot_id: str = "",
        observation_contract: Any | None = None,
        market_state_envelope: Any | None = None,
        forecast_horizon: str = "1m",
        trusted_test_override: bool = False,
    ) -> MASAActionValueResult:
        if observation_contract is None and market_state_envelope is None and not trusted_test_override:
            raise ValueError("verified observation_contract or market_state_envelope required")
        if observation_contract is not None:
            trust_gate_result = observation_contract.trust_gate_result
            market_state_envelope = observation_contract.market_state_envelope
            feature_snapshot_id = (
                feature_snapshot_id or observation_contract.feature_snapshot_id
            )
            feature_cutoff = observation_contract.feature_cutoff
            decision_time = observation_contract.observation_time
            input_feature_hash = observation_contract.input_feature_hash
            decision_id = observation_contract.decision_id
        else:
            if market_state_envelope is None:
                market_state_envelope = build_market_state_envelope_from_snapshot(
                    {
                        "symbol": "UNKNOWN",
                        "exchange": "binance",
                        "decision_time": "1970-01-01T00:00:00Z",
                        "feature_cutoff": "1970-01-01T00:00:00Z",
                    }
                )
            market_state_envelope = coerce_market_state_envelope(market_state_envelope)
            trust_gate_result = EventTimeAligner().evaluate(envelope=market_state_envelope)
            feature_cutoff = market_state_envelope.feature_cutoff
            decision_time = market_state_envelope.decision_time
            input_feature_hash = market_state_envelope.feature_hash
            decision_id = market_state_envelope.decision_id or (
                "masa_" + stable_hash({"feature_snapshot_id": feature_snapshot_id})[:24]
            )
        feature_cutoff_dt = parse_timestamp(feature_cutoff)
        decision_dt = parse_timestamp(decision_time)
        if feature_cutoff_dt is None or decision_dt is None:
            trust_gate_result = EventTimeAligner().evaluate(
                envelope=market_state_envelope,
                masa_feature_cutoff=feature_cutoff,
            )
        else:
            trust_gate_result = EventTimeAligner().evaluate(
                envelope=market_state_envelope,
                masa_feature_cutoff=feature_cutoff,
            )
        if not trust_gate_result.accepted:
            persist_decision_replay(
                decision_id=decision_id,
                market_state_envelope=market_state_envelope,
                observation=observation_contract,
                block_reason="trust_gate_rejected",
                trust_gate_result=trust_gate_result,
                extra={"feature_snapshot_id": feature_snapshot_id},
            )
            raise TrustGateRejectedError(
                "masa_adapter_trust_gate_rejected",
                decision_id=decision_id,
                trust_gate_result=trust_gate_result,
            )
        fr: PolicyForwardResult = self._policy.forward(
            observation_tensor, feature_snapshot_id=feature_snapshot_id
        )
        value_bps = fr.expected_move_bps_head if fr.expected_move_bps_head is not None else 0.0
        finite_check = all(
            (
                isinstance(v, (int, float))
                and v == v
                and float("-inf") < v < float("inf")
            )
            for v in fr.action_logits + (value_bps,)
        )
        generated_at_dt = decision_dt if decision_dt is not None else feature_cutoff_dt
        if generated_at_dt is None:
            generated_at_dt = parse_timestamp("1970-01-01T00:00:00Z")
        if feature_cutoff_dt is not None and generated_at_dt < feature_cutoff_dt:
            generated_at_dt = feature_cutoff_dt
        validity_until_dt = generated_at_dt
        forecast_seconds = 60
        if market_state_envelope is not None:
            forecast_seconds = 60
            if forecast_horizon in getattr(market_state_envelope, "timeframe_cutoffs", {}):
                forecast_seconds = {
                    "1m": 60,
                    "5m": 300,
                    "15m": 900,
                    "1h": 3600,
                    "4h": 14400,
                }.get(forecast_horizon, 60)
        validity_until_dt = generated_at_dt + timedelta(seconds=forecast_seconds)
        masa_prediction_id = "masa_" + stable_hash(
            {
                "decision_id": decision_id,
                "feature_snapshot_id": feature_snapshot_id,
                "feature_cutoff": feature_cutoff,
                "input_feature_hash": input_feature_hash,
            }
        )[:24]
        confidence = float(
            fr.action_probabilities[fr.selected_action_index]
            if 0 <= fr.selected_action_index < len(fr.action_probabilities)
            else 0.0
        )
        result = MASAActionValueResult(
            decision_id=decision_id,
            masa_prediction_id=masa_prediction_id,
            selected_action=fr.selected_action,
            selected_action_index=fr.selected_action_index,
            action_logits=fr.action_logits,
            action_probabilities=fr.action_probabilities,
            value_estimate_bps=float(value_bps),
            policy_id=fr.policy_id,
            feature_snapshot_id=fr.observation_feature_snapshot_id,
            hedge_action_classification=fr.hedge_action_classification,
            model_source_classification=fr.model_source_classification,
            missing_policy_components=fr.missing_policy_components,
            is_finite=bool(finite_check),
            model_version=self.policy_id,
            generated_at=generated_at_dt.isoformat(timespec="seconds").replace("+00:00", "Z"),
            trained_until=feature_cutoff,
            feature_cutoff=feature_cutoff,
            forecast_horizon=forecast_horizon,
            confidence=confidence,
            validity_until=validity_until_dt.isoformat(timespec="seconds").replace("+00:00", "Z"),
            input_feature_hash=input_feature_hash,
            trust_gate_result=trust_gate_result,
        )
        persist_decision_replay(
            decision_id=decision_id,
            market_state_envelope=market_state_envelope,
            observation=observation_contract,
            masa_output=result,
            ppo_action=fr.selected_action,
            position_before=getattr(observation_contract, "position_state", None),
            position_after=getattr(observation_contract, "position_state", None),
            trust_gate_result=trust_gate_result,
            extra={"feature_snapshot_id": feature_snapshot_id},
        )
        return result


def masa_invariants_snapshot() -> dict:
    return {
        "action_labels": list(ACTION_LABELS),
        "hedge_action_classification": HEDGE_ACTION_CLASSIFICATION,
        "model_source_classification": MODEL_SOURCE_CLASSIFICATION,
        "missing_policy_components": list(MISSING_POLICY_COMPONENTS),
        "legacy_masa_agent_sha256": LEGACY_MASA_AGENT_SHA256,
        "imports_torch": False,
        "imports_numpy": False,
        "loads_checkpoint_weights": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }
