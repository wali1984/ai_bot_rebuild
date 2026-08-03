from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, is_dataclass
from typing import Any, Mapping

from .trust import (
    MarketStateEnvelope,
    TrustGateResult,
    coerce_market_state_envelope,
    coerce_trust_gate_result,
    hash_market_state_envelope,
    stable_hash,
)


_REPLAY_STORE: dict[str, dict[str, Any]] = {}


def _payload(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return dict(value.to_dict())
    if is_dataclass(value):
        return asdict(value)
    return {"value": value}


def persist_decision_replay(
    *,
    decision_id: str,
    market_state_envelope: MarketStateEnvelope | Mapping[str, Any] | None = None,
    observation: Any | None = None,
    masa_output: Any | None = None,
    ppo_action: Any | None = None,
    risk_decision: Any | None = None,
    position_before: str | None = None,
    position_after: str | None = None,
    execution_result: Any | None = None,
    block_reason: str | None = None,
    trust_gate_result: TrustGateResult | Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    envelope_payload = None
    envelope_hash = None
    if market_state_envelope is not None:
        envelope = coerce_market_state_envelope(market_state_envelope)
        envelope_payload = envelope.to_dict()
        envelope_hash = hash_market_state_envelope(envelope)
    observation_payload = _payload(observation)
    masa_payload = _payload(masa_output)
    risk_payload = _payload(risk_decision)
    execution_payload = _payload(execution_result)
    trust_payload = None
    if trust_gate_result is not None:
        trust_payload = coerce_trust_gate_result(trust_gate_result).to_dict()
    record = {
        "decision_id": str(decision_id),
        "envelope_hash": envelope_hash,
        "market_state_envelope": envelope_payload,
        "observation_hash": (observation_payload or {}).get("observation_hash"),
        "observation": observation_payload,
        "masa_prediction_id": (masa_payload or {}).get("masa_prediction_id"),
        "masa_prediction_hash": stable_hash(masa_payload or {}),
        "masa_output": masa_payload,
        "ppo_action": ppo_action,
        "risk_decision": risk_payload,
        "position_before": position_before,
        "position_after": position_after,
        "execution_result": execution_payload,
        "block_reason": block_reason,
        "trust_gate_result": trust_payload,
        "extra": dict(extra or {}),
    }
    _REPLAY_STORE[str(decision_id)] = deepcopy(record)
    return deepcopy(record)


def get_decision_replay(decision_id: str) -> dict[str, Any] | None:
    record = _REPLAY_STORE.get(str(decision_id))
    return deepcopy(record) if record is not None else None


def clear_decision_replays() -> None:
    _REPLAY_STORE.clear()
