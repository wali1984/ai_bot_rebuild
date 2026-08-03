"""P0.2F trainer output contract (paper-only, native source).

Emits a single trainer prediction record per native feature snapshot.

Fields:

- prediction_id
- feature_snapshot_id
- trainer_source = V2_NATIVE_RL_CORE
- checkpoint_id or explicit blocker
- expected_move_bps         (from real policy head, not legacy log)
- expected_move_after_cost_bps  (= expected_move_bps - assumed_round_trip_cost_bps)
- confidence_raw            (from softmax over native policy logits)
- confidence_calibrated     (temperature scaling on selected-action logit)
- top_positive_features     (sensitivity attribution; method honestly labeled)
- top_negative_features
- missing_feature_flags
- stale_feature_flags
- policy_action_probabilities

Confidence is computed from the V2-native policy softmax + temperature
calibration. It is never derived from legacy log lines.

Feature attribution is computed by ``simple_sensitivity_attribution``
(finite-difference impact on the selected-action probability). The
method is labeled honestly in the output (attribution_method field).

If trainer output is missing or malformed, ``validate_for_paper_fill_gate``
returns ``BLOCKED_BY_TRAINER_OUTPUT_MISSING``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from v2.backend.app.services.market_state_integrity import (
    build_market_state_envelope_from_snapshot,
)

from .observation_builder import (
    OBSERVATION_FEATURE_ORDER,
    build_observation_from_snapshot,
)
from .policy import (
    ACTION_LABELS,
    HEDGE_ACTION_CLASSIFICATION,
    POLICY_OBSERVATION_DIM,
    V2NativeCPUPolicy,
)
from .service import calibrate_confidence

TRAINER_SOURCE = "V2_NATIVE_RL_CORE"
ATTRIBUTION_METHOD = "simple_sensitivity_finite_difference_on_selected_action_prob"
DEFAULT_ROUND_TRIP_COST_BPS = 12.0  # 2 * (5 fee + 1 slippage)

BLOCKED_BY_TRAINER_OUTPUT_MISSING = "BLOCKED_BY_TRAINER_OUTPUT_MISSING"
BLOCKED_BY_TRAINER_OUTPUT_MALFORMED = "BLOCKED_BY_TRAINER_OUTPUT_MALFORMED"
PAPER_FILL_GATE_OK = "TRAINER_OUTPUT_PRESENT_PAPER_FILL_GATE_OPEN"

DEFAULT_EDGE_AFTER_COST_MIN_BPS = 8.0
FEATURE_FRESHNESS_CURRENT = "CURRENT"

BLOCK_MISSING_PREDICTION_ID = "MISSING_PREDICTION_ID_BLOCK"
BLOCK_MISSING_FEATURE_SNAPSHOT_ID = "MISSING_FEATURE_SNAPSHOT_ID_BLOCK"
BLOCK_MISSING_TRAINER_SOURCE = "MISSING_TRAINER_SOURCE_BLOCK"
BLOCK_MISSING_EXPECTED_MOVE_AFTER_COST = "MISSING_EXPECTED_MOVE_AFTER_COST_BLOCK"
BLOCK_NEGATIVE_EXPECTED_MOVE_AFTER_COST = "NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK"
BLOCK_EDGE_AFTER_COST_BELOW_THRESHOLD = "EDGE_AFTER_COST_BELOW_THRESHOLD_BLOCK"
BLOCK_FEATURE_FRESHNESS_NOT_CURRENT = "FEATURE_FRESHNESS_NOT_CURRENT_BLOCK"
BLOCK_MISSING_FEATURE_FLAGS = "MISSING_FEATURE_FLAGS_BLOCK"
BLOCK_STALE_FEATURE_FLAGS = "STALE_FEATURE_FLAGS_BLOCK"
BLOCK_CONFIDENCE_MISSING_OR_INVALID = "CONFIDENCE_MISSING_OR_INVALID_BLOCK"
BLOCK_LIVE_GATE_NOT_BLOCKED = "LIVE_GATE_NOT_BLOCKED_BLOCK"
BLOCK_LIVE_SYMBOLS_NOT_EMPTY = "LIVE_SYMBOLS_NOT_EMPTY_BLOCK"

ALL_BLOCK_REASONS: tuple[str, ...] = (
    BLOCK_MISSING_PREDICTION_ID,
    BLOCK_MISSING_FEATURE_SNAPSHOT_ID,
    BLOCK_MISSING_TRAINER_SOURCE,
    BLOCK_MISSING_EXPECTED_MOVE_AFTER_COST,
    BLOCK_NEGATIVE_EXPECTED_MOVE_AFTER_COST,
    BLOCK_EDGE_AFTER_COST_BELOW_THRESHOLD,
    BLOCK_FEATURE_FRESHNESS_NOT_CURRENT,
    BLOCK_MISSING_FEATURE_FLAGS,
    BLOCK_STALE_FEATURE_FLAGS,
    BLOCK_CONFIDENCE_MISSING_OR_INVALID,
    BLOCK_LIVE_GATE_NOT_BLOCKED,
    BLOCK_LIVE_SYMBOLS_NOT_EMPTY,
)


@dataclass(frozen=True)
class FeatureAttribution:
    feature_name: str
    sensitivity: float


@dataclass(frozen=True)
class TrainerOutputRecord:
    prediction_id: str
    feature_snapshot_id: str
    trainer_source: str
    checkpoint_id: Optional[str]
    checkpoint_blocker: Optional[str]
    expected_move_bps: float
    expected_move_after_cost_bps: float
    confidence_raw: float
    confidence_calibrated: float
    confidence_temperature: float
    confidence_used_calibration: bool
    top_positive_features: tuple[FeatureAttribution, ...]
    top_negative_features: tuple[FeatureAttribution, ...]
    attribution_method: str
    missing_feature_flags: tuple[str, ...]
    stale_feature_flags: tuple[str, ...]
    policy_action_labels: tuple[str, ...]
    policy_action_probabilities: tuple[float, ...]
    hedge_action_classification: str
    selected_action: str
    generated_utc: str
    feature_freshness_state: str = "MISSING"
    prediction_live_gate: str = "blocked_human_only"
    prediction_live_symbols: tuple[str, ...] = ()
    scope: str = "PAPER_ONLY_NATIVE_TRAINER_OUTPUT"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def simple_sensitivity_attribution(
    policy: V2NativeCPUPolicy,
    *,
    base_tensor: list[float],
    epsilon: float = 0.01,
) -> list[FeatureAttribution]:
    """Finite-difference sensitivity attribution.

    For each feature index, perturb the input by +epsilon and -epsilon,
    measure the resulting change in the selected-action probability,
    and record the centered finite-difference as the sensitivity.
    """
    base = policy.forward(base_tensor)
    sel = base.selected_action_index
    base_prob = base.action_probabilities[sel]
    out: list[FeatureAttribution] = []
    for i, name in enumerate(OBSERVATION_FEATURE_ORDER):
        plus = list(base_tensor)
        plus[i] = plus[i] + epsilon
        minus = list(base_tensor)
        minus[i] = minus[i] - epsilon
        p_plus = policy.forward(plus).action_probabilities[sel]
        p_minus = policy.forward(minus).action_probabilities[sel]
        grad = (p_plus - p_minus) / (2 * epsilon)
        out.append(FeatureAttribution(feature_name=name, sensitivity=float(grad)))
    return out


def emit_trainer_output(
    snapshot: dict,
    *,
    policy: Optional[V2NativeCPUPolicy] = None,
    checkpoint_id: Optional[str] = None,
    checkpoint_blocker: Optional[str] = None,
    temperature: float = 1.5,
    round_trip_cost_bps: float = DEFAULT_ROUND_TRIP_COST_BPS,
    top_k: int = 3,
) -> TrainerOutputRecord:
    """Emit one trainer output record for the snapshot.

    If ``checkpoint_id`` is None, ``checkpoint_blocker`` MUST be set;
    if neither is set, the default blocker
    ``CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED`` is recorded.
    """
    if checkpoint_id is None and checkpoint_blocker is None:
        checkpoint_blocker = "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED"
    obs = build_observation_from_snapshot(
        snapshot,
        market_state_envelope=build_market_state_envelope_from_snapshot(snapshot),
    )
    if len(obs.tensor) != POLICY_OBSERVATION_DIM:
        raise ValueError("observation tensor dim mismatch with policy")
    p = policy or V2NativeCPUPolicy()
    fr = p.forward(obs.tensor, feature_snapshot_id=obs.feature_snapshot_id)
    sel = fr.selected_action_index
    confidence_raw = fr.action_probabilities[sel]
    # Convert prob to logit so temperature scaling works.
    import math
    logit = math.log(max(confidence_raw, 1e-12) / max(1.0 - confidence_raw, 1e-12))
    cal = calibrate_confidence(logit, temperature, calibration_enabled=True)
    confidence_calibrated = float(cal["calibrated_prob"])
    expected_move_bps = float(fr.expected_move_bps_head or 0.0)
    expected_move_after_cost_bps = expected_move_bps - float(round_trip_cost_bps)
    attributions = simple_sensitivity_attribution(p, base_tensor=list(obs.tensor))
    sorted_pos = sorted(attributions, key=lambda a: a.sensitivity, reverse=True)
    sorted_neg = sorted(attributions, key=lambda a: a.sensitivity)
    top_pos = tuple(sorted_pos[:top_k])
    top_neg = tuple(sorted_neg[:top_k])
    prediction_id = "v2_native_pred_" + obs.feature_snapshot_id[-32:] + "_" + fr.policy_id[-16:]
    return TrainerOutputRecord(
        prediction_id=prediction_id,
        feature_snapshot_id=obs.feature_snapshot_id,
        trainer_source=TRAINER_SOURCE,
        checkpoint_id=checkpoint_id,
        checkpoint_blocker=checkpoint_blocker,
        expected_move_bps=float(expected_move_bps),
        expected_move_after_cost_bps=float(expected_move_after_cost_bps),
        confidence_raw=float(confidence_raw),
        confidence_calibrated=float(confidence_calibrated),
        confidence_temperature=float(cal["temperature"]),
        confidence_used_calibration=bool(cal["used_calibration"]),
        top_positive_features=top_pos,
        top_negative_features=top_neg,
        attribution_method=ATTRIBUTION_METHOD,
        missing_feature_flags=tuple(obs.missing_feature_flags),
        stale_feature_flags=tuple(obs.stale_feature_flags),
        policy_action_labels=tuple(ACTION_LABELS),
        policy_action_probabilities=tuple(fr.action_probabilities),
        hedge_action_classification=HEDGE_ACTION_CLASSIFICATION,
        selected_action=fr.selected_action,
        generated_utc=_utc_iso(),
        feature_freshness_state=str(obs.feature_freshness_state or "MISSING"),
        prediction_live_gate=str(snapshot.get("live_gate") or "blocked_human_only"),
        prediction_live_symbols=tuple(snapshot.get("live_symbols") or ()),
    )


def validate_for_paper_fill_gate(
    record: Optional[TrainerOutputRecord],
    *,
    expected_move_after_cost_min_bps: float = DEFAULT_EDGE_AFTER_COST_MIN_BPS,
) -> dict:
    """Decide whether the trainer output meets the paper fill gate contract.

    Strict P0.2F remediation: every required field must be present AND the
    after-cost edge must meet the configured minimum AND the snapshot must
    be CURRENT AND feature flag lists must be empty AND the prediction's
    live_gate/live_symbols must remain blocked_human_only / [].
    """
    if record is None:
        return {
            "paper_fill_gate_status": BLOCKED_BY_TRAINER_OUTPUT_MISSING,
            "paper_fill_allowed": False,
            "paper_fill_gate_block_reasons": (BLOCK_MISSING_PREDICTION_ID,),
            "blockers": ("trainer_output_record_missing",),
            "expected_move_after_cost_min_bps": float(expected_move_after_cost_min_bps),
        }
    block_reasons: list[str] = []
    if not record.prediction_id:
        block_reasons.append(BLOCK_MISSING_PREDICTION_ID)
    if not record.feature_snapshot_id:
        block_reasons.append(BLOCK_MISSING_FEATURE_SNAPSHOT_ID)
    if not record.trainer_source or record.trainer_source != TRAINER_SOURCE:
        block_reasons.append(BLOCK_MISSING_TRAINER_SOURCE)

    em_after_cost = record.expected_move_after_cost_bps
    if em_after_cost is None or (isinstance(em_after_cost, float) and em_after_cost != em_after_cost):
        block_reasons.append(BLOCK_MISSING_EXPECTED_MOVE_AFTER_COST)
    else:
        em_val = float(em_after_cost)
        if em_val < 0.0:
            block_reasons.append(BLOCK_NEGATIVE_EXPECTED_MOVE_AFTER_COST)
        elif em_val < float(expected_move_after_cost_min_bps):
            block_reasons.append(BLOCK_EDGE_AFTER_COST_BELOW_THRESHOLD)

    if record.feature_freshness_state != FEATURE_FRESHNESS_CURRENT:
        block_reasons.append(BLOCK_FEATURE_FRESHNESS_NOT_CURRENT)
    if record.missing_feature_flags:
        block_reasons.append(BLOCK_MISSING_FEATURE_FLAGS)
    if record.stale_feature_flags:
        block_reasons.append(BLOCK_STALE_FEATURE_FLAGS)

    conf_cal = record.confidence_calibrated
    if (
        conf_cal is None
        or not isinstance(conf_cal, (int, float))
        or (isinstance(conf_cal, float) and conf_cal != conf_cal)
        or conf_cal <= 0.0
        or conf_cal > 1.0
    ):
        block_reasons.append(BLOCK_CONFIDENCE_MISSING_OR_INVALID)

    if record.prediction_live_gate != "blocked_human_only":
        block_reasons.append(BLOCK_LIVE_GATE_NOT_BLOCKED)
    if record.prediction_live_symbols != ():
        block_reasons.append(BLOCK_LIVE_SYMBOLS_NOT_EMPTY)

    if block_reasons:
        return {
            "paper_fill_gate_status": BLOCKED_BY_TRAINER_OUTPUT_MALFORMED,
            "paper_fill_allowed": False,
            "paper_fill_gate_block_reasons": tuple(block_reasons),
            "blockers": tuple(block_reasons),
            "expected_move_after_cost_min_bps": float(expected_move_after_cost_min_bps),
        }
    return {
        "paper_fill_gate_status": PAPER_FILL_GATE_OK,
        "paper_fill_allowed": True,
        "paper_fill_gate_block_reasons": (),
        "blockers": (),
        "expected_move_after_cost_min_bps": float(expected_move_after_cost_min_bps),
    }


def trainer_output_invariants_snapshot() -> dict:
    return {
        "trainer_source": TRAINER_SOURCE,
        "attribution_method": ATTRIBUTION_METHOD,
        "round_trip_cost_bps_default": DEFAULT_ROUND_TRIP_COST_BPS,
        "confidence_derivation_source": "v2_native_policy_softmax_plus_temperature_scaling",
        "expected_move_derivation_source": "v2_native_policy_expected_move_scalar_head",
        "imports_torch": False,
        "loads_legacy_log_lines_for_confidence": False,
        "writes_legacy_redis": False,
        "places_exchange_orders": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
    }
