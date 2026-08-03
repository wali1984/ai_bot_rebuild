"""V2 Native Observation Tensor Builder (P0.2A).

Builds a deterministic observation tensor (a flat tuple of floats) from
the trainer-consumable native feature snapshot emitted by P0.1.

This is NOT a full unified_feature_builder port. It is a P0.2A
contract: given a snapshot dict from
v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json
(or the public mirror), produce a fixed-shape tensor + per-snapshot
metadata that a future PPO/MASA policy can consume.

Legacy behavior sources consulted (read-only mirrors under
v2/legacy_owned_runtime/):

- rl/obs_schema.py
    sha256=9ec040fa1306ac28f4395aac103b104eb02644866ca8acec5577b155fd925f5f
    size=17346
- rl/unified_feature_builder.py
    sha256=2af5c68d812c0a0a5db2e037204f0b2165d9084dea983d1737e09034e8c739a5
    size=29925

Safety:
- no numpy/torch/SB3 imports (tensor is a plain tuple of floats)
- no Redis read
- absent feature values map to 0.0 with explicit missing flag preserved
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from v2.backend.app.services.market_state_integrity import (
    EventTimeAligner,
    TrustGateRejectedError,
    build_market_state_envelope_from_snapshot,
    persist_decision_replay,
    stable_hash,
)
from v2.backend.app.services.position_state_machine import (
    build_position_action_mask,
    normalize_position_state,
)

LEGACY_SOURCES = {
    "rl/obs_schema.py": {
        "sha256": "9ec040fa1306ac28f4395aac103b104eb02644866ca8acec5577b155fd925f5f",
        "size_bytes": 17346,
        "v2_owned_path": "v2/legacy_owned_runtime/rl/obs_schema.py",
    },
    "rl/unified_feature_builder.py": {
        "sha256": "2af5c68d812c0a0a5db2e037204f0b2165d9084dea983d1737e09034e8c739a5",
        "size_bytes": 29925,
        "v2_owned_path": "v2/legacy_owned_runtime/rl/unified_feature_builder.py",
    },
}

# Fixed feature order in the V2-native observation tensor. The order is
# part of the contract so a downstream policy can rely on it.
OBSERVATION_FEATURE_ORDER: tuple[str, ...] = (
    # OHLCV-derived
    "ret_pct",
    "log_return",
    "range_pct",
    "body_pct",
    "true_range_pct",
    "gap_pct",
    # TA indicators
    "ema_12",
    "ema_26",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "bb_width_pct",
    # Multi-timeframe
    "htf_ret_pct",
    "htf_rsi_14",
    # Microstructure
    "bid_ask_spread_bps",
    "depth_imbalance",
    "micro_price",
    "toxicity_proxy",
    # Funding / OI / liquidation
    "funding_rate",
    "oi_change_pct",
    "last_liq_bps_24h",
    # Portfolio aware
    "paper_position_present",
    "paper_position_notional",
    "paper_unrealized_bps",
    "paper_position_age_seconds",
)


@dataclass(frozen=True)
class ObservationTensor:
    feature_snapshot_id: str
    feature_count: int
    tensor_shape: tuple[int, ...]
    tensor: tuple[float, ...]
    missing_feature_flags: tuple[str, ...]
    stale_feature_flags: tuple[str, ...]
    feature_freshness_state: str  # CURRENT | STALE | MISSING
    categories_present: tuple[str, ...]
    symbol: str
    timeframe: str
    generated_at: str
    decision_id: str
    observation_time: str
    feature_cutoff: str
    observation_hash: str
    included_masa_prediction_id: str
    action_mask: dict[str, bool]
    position_state: str
    input_feature_hash: str
    trust_gate_result: Any
    market_state_envelope: Any
    schema_version: str = "v2_native_observation_tensor_v1"


def _value_to_float(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def build_observation_from_snapshot(
    snapshot: dict[str, Any],
    *,
    market_state_envelope: Any | None = None,
    included_masa_prediction_id: str | None = None,
    action_mask: dict[str, bool] | None = None,
    position_state: str | None = None,
    trusted_test_override: bool = False,
) -> ObservationTensor:
    """Build the V2-native observation tensor from a trainer-consumable snapshot.

    The input is the dict shape produced by
    FeaturePipelineNativeService.emit_trainer_consumable_snapshot().
    Missing/absent feature values map to 0.0 with the missing flag
    preserved in the output.
    """
    if not isinstance(snapshot, dict):
        raise TypeError("snapshot must be a dict")
    if market_state_envelope is None:
        market_state_envelope = snapshot.get("market_state_envelope")
    if market_state_envelope is None and not trusted_test_override:
        raise ValueError("market_state_envelope required")
    if market_state_envelope is None:
        market_state_envelope = build_market_state_envelope_from_snapshot(snapshot)
    features = snapshot.get("features") or {}
    envelope = build_market_state_envelope_from_snapshot(
        {"market_state_envelope": market_state_envelope}
    )
    resolved_position_state = normalize_position_state(
        position_state or snapshot.get("position_state")
    )
    resolved_action_mask = dict(
        action_mask
        or snapshot.get("action_mask")
        or build_position_action_mask(resolved_position_state)
    )
    trust_gate_result = EventTimeAligner().evaluate(
        envelope=envelope,
        features=features if isinstance(features, dict) else {},
        required_feature_names=tuple(
            name for name in OBSERVATION_FEATURE_ORDER if name in (features or {})
        ),
    )
    decision_id = envelope.decision_id or (
        "obs_" + stable_hash(
            {
                "feature_snapshot_id": snapshot.get("feature_snapshot_id"),
                "feature_hash": envelope.feature_hash,
                "decision_time": envelope.decision_time,
            }
        )[:24]
    )
    if not trust_gate_result.accepted:
        persist_decision_replay(
            decision_id=decision_id,
            market_state_envelope=envelope,
            position_before=resolved_position_state,
            position_after=resolved_position_state,
            block_reason="trust_gate_rejected",
            trust_gate_result=trust_gate_result,
            extra={"feature_snapshot_id": str(snapshot.get("feature_snapshot_id") or "")},
        )
        raise TrustGateRejectedError(
            "observation_builder_trust_gate_rejected",
            decision_id=decision_id,
            trust_gate_result=trust_gate_result,
        )
    tensor: list[float] = []
    for name in OBSERVATION_FEATURE_ORDER:
        tensor.append(_value_to_float(features.get(name)))
    observation_hash = stable_hash(
        {
            "feature_snapshot_id": str(snapshot.get("feature_snapshot_id") or ""),
            "feature_cutoff": envelope.feature_cutoff,
            "tensor": tensor,
            "action_mask": resolved_action_mask,
            "position_state": resolved_position_state,
        }
    )
    observation = ObservationTensor(
        feature_snapshot_id=str(snapshot.get("feature_snapshot_id") or ""),
        feature_count=int(snapshot.get("feature_count") or 0),
        tensor_shape=(len(tensor),),
        tensor=tuple(tensor),
        missing_feature_flags=tuple(snapshot.get("missing_feature_flags") or ()),
        stale_feature_flags=tuple(snapshot.get("stale_feature_flags") or ()),
        feature_freshness_state=str(snapshot.get("feature_freshness_state") or "MISSING"),
        categories_present=tuple(snapshot.get("categories_present") or ()),
        symbol=str(snapshot.get("symbol") or ""),
        timeframe=str(snapshot.get("timeframe") or ""),
        generated_at=str(snapshot.get("generated_at") or ""),
        decision_id=decision_id,
        observation_time=envelope.decision_time,
        feature_cutoff=envelope.feature_cutoff,
        observation_hash=observation_hash,
        included_masa_prediction_id=str(
            included_masa_prediction_id
            or snapshot.get("included_masa_prediction_id")
            or ""
        ),
        action_mask=resolved_action_mask,
        position_state=resolved_position_state,
        input_feature_hash=envelope.feature_hash,
        trust_gate_result=trust_gate_result,
        market_state_envelope=envelope,
    )
    persist_decision_replay(
        decision_id=decision_id,
        market_state_envelope=envelope,
        observation=observation,
        position_before=resolved_position_state,
        position_after=resolved_position_state,
        trust_gate_result=trust_gate_result,
        extra={"feature_snapshot_id": observation.feature_snapshot_id},
    )
    return observation


def load_snapshot_from_disk(path: Path) -> dict[str, Any]:
    """Helper that reads a snapshot JSON without importing redis or any
    network client. Returns the parsed dict.
    """
    if not path.exists():
        raise FileNotFoundError(f"snapshot not found at {path}")
    return json.loads(path.read_text())


def observation_metadata(
    snapshot: dict[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """Return the metadata side-band the brief requires."""
    obs = build_observation_from_snapshot(snapshot, **kwargs)
    return {
        "schema_version": obs.schema_version,
        "decision_id": obs.decision_id,
        "feature_snapshot_id": obs.feature_snapshot_id,
        "feature_count": obs.feature_count,
        "tensor_shape": list(obs.tensor_shape),
        "missing_feature_flags": list(obs.missing_feature_flags),
        "stale_feature_flags": list(obs.stale_feature_flags),
        "feature_freshness_state": obs.feature_freshness_state,
        "categories_present": list(obs.categories_present),
        "symbol": obs.symbol,
        "timeframe": obs.timeframe,
        "generated_at": obs.generated_at,
        "observation_time": obs.observation_time,
        "feature_cutoff": obs.feature_cutoff,
        "observation_hash": obs.observation_hash,
        "included_masa_prediction_id": obs.included_masa_prediction_id,
        "action_mask": dict(obs.action_mask),
        "position_state": obs.position_state,
        "input_feature_hash": obs.input_feature_hash,
        "trust_gate_result": obs.trust_gate_result.to_dict(),
        "legacy_behavior_mapping": LEGACY_SOURCES,
    }
