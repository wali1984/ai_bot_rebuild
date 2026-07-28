"""Train signed-release-bound research challengers across predeclared slices.

This worker is deliberately non-authoritative.  It consumes the exact in-memory
dataset object returned by signed release authentication, fits only on the
chronological training partition, selects comparable architectures only on the
validation partition, and reports holdout evidence after selection.  It cannot
write either model registry, Redis, paper orders, or live authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import pickle
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from v2.backend.app.contracts.runtime_v2.candidate_decision_outcome_v2 import (
    CandidateOutcomeContractError,
    CounterfactualScenarioV2,
)
from v2.backend.app.services.adaptive_system import escalation_supervisor_v2 as supervisor
from v2.backend.app.services.native_trainer.trusted_replay.dataset import (
    target_action_from_net_edges,
)

SCHEMA_VERSION = "adaptive_diversified_challenger_v2"
OUTPUT_NAME = "adaptive_diversified_challenger_v2.json"
MODES = ("horizon", "symbol_regime", "architecture", "hedged_relative_value")
ACTION_ORDER = ("hold", "long", "short")
ACTION_INDEX = {action: index for index, action in enumerate(ACTION_ORDER)}
MIN_SPLIT_ROWS = 20
MAX_SYMBOL_CANDIDATES = 12
RANDOM_STATE = 1729
HEDGE_CONTRACT = "FULLY_DELTA_NEUTRAL_ZERO_GROSS_RETURN_DOUBLE_EXECUTION_DRAG"
HEDGE_COMPARISON = "RELATIVE_LOSS_AVOIDANCE_VS_UNHEDGED"
_HEDGE_DERIVATION_KEYS = frozenset(
    {
        "actual_accounting_effect",
        "candidate_id",
        "comparison_semantics",
        "counterfactual_counts_as_realized_paper_profit",
        "cross_sectional_relative_value_label_present",
        "derivation_sha256",
        "hedge_advantage_bps",
        "hedge_contract",
        "hedged_after_cost_pnl_bps",
        "hedged_after_cost_positive",
        "hedged_scenario",
        "hedged_scenario_sha256",
        "proposed_action",
        "schema_version",
        "target_hedge_vs_unhedged",
        "unhedged_after_cost_pnl_bps",
        "unhedged_scenario",
        "unhedged_scenario_sha256",
    }
)
_SCENARIO_KEYS = frozenset(
    {
        "action_sha256",
        "actual_accounting_effect",
        "after_cost_pnl_bps",
        "counts_as_paper_profit",
        "fees_bps",
        "finality_proven",
        "funding_bps",
        "gross_pnl_bps",
        "market_impact_bps",
        "producer_generated_at_ms",
        "record_available_at_ms",
        "scenario_id",
        "schema_version",
        "slippage_bps",
        "source_event_time_ms",
        "source_receipt_sha256s",
        "spread_bps",
    }
)


class AdaptiveDiversifiedChallengerError(RuntimeError):
    pass


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AdaptiveDiversifiedChallengerError("STRICT_JSON_REQUIRED") from exc


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise AdaptiveDiversifiedChallengerError(f"{field}:FINITE_NUMBER_REQUIRED")
    result = float(value)
    if not math.isfinite(result):
        raise AdaptiveDiversifiedChallengerError(f"{field}:FINITE_NUMBER_REQUIRED")
    return result


def _utc(value: object, field: str) -> datetime:
    if type(value) is not str or not value:
        raise AdaptiveDiversifiedChallengerError(f"{field}:UTC_TIMESTAMP_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdaptiveDiversifiedChallengerError(
            f"{field}:UTC_TIMESTAMP_REQUIRED"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AdaptiveDiversifiedChallengerError(f"{field}:UTC_TIMESTAMP_REQUIRED")
    return parsed.astimezone(timezone.utc)


def _scenario(value: object, field: str) -> CounterfactualScenarioV2:
    if type(value) is not dict or set(value) != _SCENARIO_KEYS:
        raise AdaptiveDiversifiedChallengerError(
            f"{field}:EXACT_COUNTERFACTUAL_SCENARIO_REQUIRED"
        )
    material = dict(value)
    receipts = material.get("source_receipt_sha256s")
    if type(receipts) is not list:
        raise AdaptiveDiversifiedChallengerError(
            f"{field}:EXACT_COUNTERFACTUAL_SCENARIO_REQUIRED"
        )
    material["source_receipt_sha256s"] = tuple(receipts)
    try:
        return CounterfactualScenarioV2(**material)
    except (CandidateOutcomeContractError, TypeError) as exc:
        raise AdaptiveDiversifiedChallengerError(
            f"{field}:COUNTERFACTUAL_SCENARIO_INVALID"
        ) from exc


@dataclass(frozen=True)
class ValidatedRow:
    split: str
    symbol: str
    timeframe: str
    features: tuple[float, ...]
    action_index: int
    long_net_bps: float
    short_net_bps: float
    decision_time: datetime
    label_available_at: datetime
    hedge_target_index: int | None
    unhedged_after_cost_pnl_bps: float | None
    hedged_after_cost_pnl_bps: float | None


def _validated_rows(
    dataset: Mapping[str, Any],
    release_projection: Mapping[str, Any],
) -> tuple[tuple[str, ...], tuple[ValidatedRow, ...]]:
    if dataset.get("dataset_sha256") != release_projection.get("dataset_sha256"):
        raise AdaptiveDiversifiedChallengerError("dataset:RELEASE_IDENTITY_MISMATCH")
    ordered = dataset.get("ordered_feature_names")
    if (
        type(ordered) is not list
        or not ordered
        or any(type(name) is not str or not name for name in ordered)
        or len(set(ordered)) != len(ordered)
    ):
        raise AdaptiveDiversifiedChallengerError(
            "dataset.ordered_feature_names:CANONICAL_UNIQUE_LIST_REQUIRED"
        )
    rows = dataset.get("rows")
    if type(rows) is not list or not rows:
        raise AdaptiveDiversifiedChallengerError("dataset.rows:NONEMPTY_LIST_REQUIRED")
    validated: list[ValidatedRow] = []
    for index, raw in enumerate(rows):
        if type(raw) is not dict:
            raise AdaptiveDiversifiedChallengerError(
                f"dataset.rows[{index}]:OBJECT_REQUIRED"
            )
        split = raw.get("split")
        symbol = raw.get("symbol")
        timeframe = raw.get("timeframe")
        if split not in {"train", "validation", "holdout"}:
            raise AdaptiveDiversifiedChallengerError(
                f"dataset.rows[{index}].split:INVALID"
            )
        if type(symbol) is not str or not symbol:
            raise AdaptiveDiversifiedChallengerError(
                f"dataset.rows[{index}].symbol:INVALID"
            )
        if type(timeframe) is not str or not timeframe:
            raise AdaptiveDiversifiedChallengerError(
                f"dataset.rows[{index}].timeframe:INVALID"
            )
        values = raw.get("feature_values")
        mask = raw.get("missing_mask")
        if (
            type(values) is not list
            or len(values) != len(ordered)
            or type(mask) is not list
            or len(mask) != len(ordered)
            or any(type(flag) is not int or flag not in {0, 1} for flag in mask)
            or any(mask)
        ):
            raise AdaptiveDiversifiedChallengerError(
                f"dataset.rows[{index}]:FEATURE_VECTOR_CONTRACT_INVALID"
            )
        features = tuple(
            _finite(value, f"dataset.rows[{index}].feature_values")
            for value in values
        )
        long_net = _finite(
            raw.get("long_net_bps"), f"dataset.rows[{index}].long_net_bps"
        )
        short_net = _finite(
            raw.get("short_net_bps"), f"dataset.rows[{index}].short_net_bps"
        )
        action = raw.get("target_action")
        if action not in ACTION_INDEX:
            raise AdaptiveDiversifiedChallengerError(
                f"dataset.rows[{index}].target_action:INVALID"
            )
        if target_action_from_net_edges(
            long_net_bps=long_net,
            short_net_bps=short_net,
        ) != action:
            raise AdaptiveDiversifiedChallengerError(
                f"dataset.rows[{index}].target_action:NET_EDGE_MISMATCH"
            )
        decision_time = _utc(
            raw.get("decision_time"), f"dataset.rows[{index}].decision_time"
        )
        label_available_at = _utc(
            raw.get("label_available_at"),
            f"dataset.rows[{index}].label_available_at",
        )
        if label_available_at <= decision_time:
            raise AdaptiveDiversifiedChallengerError(
                f"dataset.rows[{index}]:LABEL_NOT_AFTER_DECISION"
            )
        hedge = raw.get("hedge_label_derivation")
        hedge_target: int | None = None
        unhedged_after_cost: float | None = None
        hedged_after_cost: float | None = None
        if hedge is not None:
            if type(hedge) is not dict or set(hedge) != _HEDGE_DERIVATION_KEYS:
                raise AdaptiveDiversifiedChallengerError(
                    f"dataset.rows[{index}].hedge_label_derivation:EXACT_SCHEMA_REQUIRED"
                )
            unhedged_after_cost = _finite(
                hedge.get("unhedged_after_cost_pnl_bps"),
                f"dataset.rows[{index}].hedge.unhedged_after_cost_pnl_bps",
            )
            hedged_after_cost = _finite(
                hedge.get("hedged_after_cost_pnl_bps"),
                f"dataset.rows[{index}].hedge.hedged_after_cost_pnl_bps",
            )
            advantage = _finite(
                hedge.get("hedge_advantage_bps"),
                f"dataset.rows[{index}].hedge.hedge_advantage_bps",
            )
            target = hedge.get("target_hedge_vs_unhedged")
            derivation_material = {
                key: value
                for key, value in hedge.items()
                if key != "derivation_sha256"
            }
            scenario_shas = (
                hedge.get("unhedged_scenario_sha256"),
                hedge.get("hedged_scenario_sha256"),
            )
            unhedged_scenario = _scenario(
                hedge.get("unhedged_scenario"),
                f"dataset.rows[{index}].hedge.unhedged_scenario",
            )
            hedged_scenario = _scenario(
                hedge.get("hedged_scenario"),
                f"dataset.rows[{index}].hedge.hedged_scenario",
            )
            directional = raw.get("directional_label_derivation")
            proposed_action = hedge.get("proposed_action")
            selected_unhedged_net = (
                long_net
                if proposed_action == "LONG"
                else short_net
                if proposed_action == "SHORT"
                else math.nan
            )
            physical_cost_fields = (
                "fees_bps",
                "spread_bps",
                "slippage_bps",
                "market_impact_bps",
            )
            if (
                hedge.get("schema_version")
                != "candidate_hedge_label_derivation_v2"
                or type(hedge.get("candidate_id")) is not str
                or not hedge.get("candidate_id")
                or hedge.get("hedge_contract") != HEDGE_CONTRACT
                or hedge.get("comparison_semantics") != HEDGE_COMPARISON
                or not isinstance(directional, Mapping)
                or directional.get("proposed_action") != proposed_action
                or proposed_action not in {"LONG", "SHORT"}
                or directional.get("unhedged_scenario_sha256s")
                != [scenario_shas[0]]
                or _sha256(_canonical_bytes(hedge.get("unhedged_scenario")))
                != scenario_shas[0]
                or _sha256(_canonical_bytes(hedge.get("hedged_scenario")))
                != scenario_shas[1]
                or not math.isclose(
                    unhedged_after_cost,
                    selected_unhedged_net,
                    rel_tol=0.0,
                    abs_tol=1e-9,
                )
                or not math.isclose(
                    unhedged_after_cost,
                    unhedged_scenario.after_cost_pnl_bps,
                    rel_tol=0.0,
                    abs_tol=1e-9,
                )
                or not math.isclose(
                    hedged_after_cost,
                    hedged_scenario.after_cost_pnl_bps,
                    rel_tol=0.0,
                    abs_tol=1e-9,
                )
                or not math.isclose(
                    hedged_scenario.gross_pnl_bps,
                    0.0,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
                or not math.isclose(
                    hedged_scenario.funding_bps,
                    0.0,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
                or any(
                    not math.isclose(
                        getattr(hedged_scenario, cost_field),
                        2.0 * getattr(unhedged_scenario, cost_field),
                        rel_tol=0.0,
                        abs_tol=1e-9,
                    )
                    for cost_field in physical_cost_fields
                )
                or hedged_scenario.source_event_time_ms
                != unhedged_scenario.source_event_time_ms
                or hedged_scenario.producer_generated_at_ms
                != unhedged_scenario.producer_generated_at_ms
                or hedged_scenario.record_available_at_ms
                != unhedged_scenario.record_available_at_ms
                or hedged_scenario.source_receipt_sha256s
                != unhedged_scenario.source_receipt_sha256s
                or hedged_scenario.action_sha256 == unhedged_scenario.action_sha256
                or not math.isclose(
                    advantage,
                    hedged_after_cost - unhedged_after_cost,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
                or type(target) is not bool
                or target is not (advantage > 0.0)
                or hedge.get("hedged_after_cost_positive")
                is not (hedged_after_cost > 0.0)
                or hedge.get("cross_sectional_relative_value_label_present")
                is not False
                or hedge.get("counterfactual_counts_as_realized_paper_profit")
                is not False
                or hedge.get("actual_accounting_effect") is not False
                or any(
                    type(value) is not str
                    or len(value) != 64
                    or any(character not in "0123456789abcdef" for character in value)
                    for value in scenario_shas
                )
                or scenario_shas[0] == scenario_shas[1]
                or hedge.get("derivation_sha256")
                != _sha256(_canonical_bytes(derivation_material))
            ):
                raise AdaptiveDiversifiedChallengerError(
                    f"dataset.rows[{index}].hedge_label_derivation:SEMANTICS_INVALID"
                )
            hedge_target = int(target)
        validated.append(
            ValidatedRow(
                split=str(split),
                symbol=symbol,
                timeframe=timeframe,
                features=features,
                action_index=ACTION_INDEX[str(action)],
                long_net_bps=long_net,
                short_net_bps=short_net,
                decision_time=decision_time,
                label_available_at=label_available_at,
                hedge_target_index=hedge_target,
                unhedged_after_cost_pnl_bps=unhedged_after_cost,
                hedged_after_cost_pnl_bps=hedged_after_cost,
            )
        )
    for split in ("train", "validation", "holdout"):
        if not any(row.split == split for row in validated):
            raise AdaptiveDiversifiedChallengerError(
                f"dataset.{split}:NONEMPTY_REQUIRED"
            )
    return tuple(ordered), tuple(validated)


def _algorithm(name: str) -> Any:
    if name == "multinomial_logistic":
        return Pipeline(
            (
                ("scale", StandardScaler()),
                (
                    "model",
                    LogisticRegression(
                        C=0.5,
                        class_weight="balanced",
                        max_iter=400,
                        random_state=RANDOM_STATE,
                    ),
                ),
            )
        )
    if name == "hist_gradient_boosting":
        return HistGradientBoostingClassifier(
            learning_rate=0.05,
            max_iter=120,
            max_leaf_nodes=15,
            l2_regularization=1.0,
            random_state=RANDOM_STATE,
        )
    if name == "small_neural_network":
        return Pipeline(
            (
                ("scale", StandardScaler()),
                (
                    "model",
                    MLPClassifier(
                        hidden_layer_sizes=(32, 16),
                        activation="relu",
                        alpha=0.01,
                        batch_size="auto",
                        early_stopping=True,
                        validation_fraction=0.15,
                        n_iter_no_change=12,
                        max_iter=200,
                        random_state=RANDOM_STATE,
                    ),
                ),
            )
        )
    raise AdaptiveDiversifiedChallengerError(f"algorithm:UNSUPPORTED:{name}")


def _algorithm_contract(name: str) -> dict[str, Any]:
    contracts = {
        "multinomial_logistic": {
            "estimator": "sklearn.linear_model.LogisticRegression",
            "preprocessing": "StandardScaler_fit_on_train_only",
            "C": 0.5,
            "class_weight": "balanced",
            "max_iter": 400,
            "random_state": RANDOM_STATE,
        },
        "hist_gradient_boosting": {
            "estimator": "sklearn.ensemble.HistGradientBoostingClassifier",
            "learning_rate": 0.05,
            "max_iter": 120,
            "max_leaf_nodes": 15,
            "l2_regularization": 1.0,
            "random_state": RANDOM_STATE,
        },
        "small_neural_network": {
            "estimator": "sklearn.neural_network.MLPClassifier",
            "preprocessing": "StandardScaler_fit_on_train_only",
            "hidden_layer_sizes": [32, 16],
            "activation": "relu",
            "alpha": 0.01,
            "batch_size": "auto",
            "early_stopping": True,
            "validation_fraction": 0.15,
            "n_iter_no_change": 12,
            "max_iter": 200,
            "random_state": RANDOM_STATE,
        },
    }
    try:
        return dict(contracts[name])
    except KeyError as exc:
        raise AdaptiveDiversifiedChallengerError(
            f"algorithm:UNSUPPORTED:{name}"
        ) from exc


def _aligned_probabilities(model: Any, values: np.ndarray) -> np.ndarray:
    raw = np.asarray(model.predict_proba(values), dtype=np.float64)
    classes = tuple(int(value) for value in model.classes_)
    result = np.zeros((values.shape[0], len(ACTION_ORDER)), dtype=np.float64)
    for source, action_index in enumerate(classes):
        if action_index not in range(len(ACTION_ORDER)):
            raise AdaptiveDiversifiedChallengerError("model:CLASS_ID_INVALID")
        result[:, action_index] = raw[:, source]
    if (
        not np.all(np.isfinite(result))
        or np.any(result < 0.0)
        or not np.allclose(np.sum(result, axis=1), 1.0, rtol=0.0, atol=1e-9)
    ):
        raise AdaptiveDiversifiedChallengerError("model:PROBABILITY_SEMANTICS_INVALID")
    return result


def _metrics(
    probabilities: np.ndarray,
    targets: np.ndarray,
    net_edges: np.ndarray,
) -> dict[str, Any]:
    one_hot = np.eye(len(ACTION_ORDER), dtype=np.float64)[targets]
    predicted = np.argmax(probabilities, axis=1)
    chosen_net = np.where(
        predicted == ACTION_INDEX["long"],
        net_edges[:, 0],
        np.where(predicted == ACTION_INDEX["short"], net_edges[:, 1], 0.0),
    )
    clipped = np.clip(probabilities, 1e-12, 1.0)
    result = {
        "rows": int(targets.shape[0]),
        "multiclass_brier": float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1))),
        "negative_log_likelihood": float(
            -np.mean(np.log(clipped[np.arange(targets.shape[0]), targets]))
        ),
        "target_action_accuracy": float(np.mean(predicted == targets)),
        "predicted_directional_rate": float(np.mean(predicted != ACTION_INDEX["hold"])),
        "counterfactual_after_cost_expectancy_bps": float(np.mean(chosen_net)),
        "counterfactual_positive_net_rate": float(np.mean(chosen_net > 0.0)),
        "counterfactual_counts_as_realized_paper_profit": False,
    }
    if any(not math.isfinite(float(value)) for key, value in result.items() if key not in {"rows", "counterfactual_counts_as_realized_paper_profit"}):
        raise AdaptiveDiversifiedChallengerError("metrics:NONFINITE")
    return result


def _partition(
    rows: Sequence[ValidatedRow],
    predicate: Callable[[ValidatedRow], bool],
) -> dict[str, tuple[ValidatedRow, ...]]:
    return {
        split: tuple(row for row in rows if row.split == split and predicate(row))
        for split in ("train", "validation", "holdout")
    }


def _arrays(rows: Sequence[ValidatedRow]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return (
        np.asarray([row.features for row in rows], dtype=np.float64),
        np.asarray([row.action_index for row in rows], dtype=np.int64),
        np.asarray(
            [(row.long_net_bps, row.short_net_bps) for row in rows],
            dtype=np.float64,
        ),
    )


def _eligible_partition(
    partitions: Mapping[str, Sequence[ValidatedRow]],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    for split in ("train", "validation", "holdout"):
        count = len(partitions[split])
        if count < MIN_SPLIT_ROWS:
            reasons.append(f"{split.upper()}_ROWS_BELOW_{MIN_SPLIT_ROWS}:{count}")
    train_actions = {row.action_index for row in partitions["train"]}
    if train_actions != set(range(len(ACTION_ORDER))):
        reasons.append("TRAIN_DIRECTIONAL_AND_HOLD_LABELS_REQUIRED")
    return not reasons, reasons


def _base_probabilities(targets: np.ndarray, rows: int) -> np.ndarray:
    counts = np.bincount(targets, minlength=len(ACTION_ORDER)).astype(np.float64)
    probabilities = counts / float(np.sum(counts))
    return np.repeat(probabilities.reshape(1, -1), rows, axis=0)


def _fit_candidate(
    *,
    algorithm: str,
    group_kind: str,
    group_value: str,
    partitions: Mapping[str, Sequence[ValidatedRow]],
    eligible_symbols: Sequence[str],
    eligible_timeframes: Sequence[str],
    dataset_sha256: str,
) -> dict[str, Any]:
    train_x, train_y, train_net = _arrays(partitions["train"])
    validation_x, validation_y, validation_net = _arrays(partitions["validation"])
    holdout_x, holdout_y, holdout_net = _arrays(partitions["holdout"])
    model = _algorithm(algorithm)
    model.fit(train_x, train_y)
    try:
        model_parameter_fingerprint = _sha256(pickle.dumps(model, protocol=5))
    except (pickle.PickleError, TypeError, ValueError) as exc:
        raise AdaptiveDiversifiedChallengerError(
            "model:PARAMETER_FINGERPRINT_FAILED"
        ) from exc
    train_probabilities = _aligned_probabilities(model, train_x)
    validation_probabilities = _aligned_probabilities(model, validation_x)
    holdout_probabilities = _aligned_probabilities(model, holdout_x)
    validation_baseline = _base_probabilities(train_y, validation_y.shape[0])
    holdout_baseline = _base_probabilities(train_y, holdout_y.shape[0])
    durations = np.asarray(
        [
            (row.label_available_at - row.decision_time).total_seconds()
            for row in partitions["train"]
        ],
        dtype=np.float64,
    )
    declaration = {
        "strategy_family": "after_cost_directional_profitability_research",
        "algorithm_family": algorithm,
        "eligible_symbols": list(eligible_symbols),
        "eligible_timeframes": list(eligible_timeframes),
        "required_data": [
            "ServingFeatureABIV2 exact feature vector",
            "point-in-time matured long/short after-cost labels",
            "chronological purged train/validation/holdout split",
        ],
        "expected_holding_horizon": {
            "basis": "TRAIN_LABEL_MATURATION_DELAY_SECONDS",
            "minimum": float(np.min(durations)),
            "median": float(np.median(durations)),
            "maximum": float(np.max(durations)),
        },
        "execution_assumptions": {
            "costs_already_reflected_in_net_labels": True,
            "venue_executability_not_assumed": True,
            "requires_hard_validator_before_any_paper_action": True,
        },
        "risk_behavior": "RESEARCH_ONLY_NO_SIZING_LEVERAGE_MARGIN_OR_ROUTE_AUTHORITY",
    }
    model_contract = _algorithm_contract(algorithm)
    identity = {
        "dataset_sha256": dataset_sha256,
        "algorithm_contract": model_contract,
        "group_kind": group_kind,
        "group_value": group_value,
        "declaration": declaration,
    }
    result = {
        "candidate_id": "adaptive_diversified_" + _sha256(_canonical_bytes(identity))[:24],
        "dataset_sha256": dataset_sha256,
        "algorithm": algorithm,
        "algorithm_contract": model_contract,
        "model_parameter_fingerprint": model_parameter_fingerprint,
        "runtime_versions": {
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "group_kind": group_kind,
        "group_value": group_value,
        "declaration": declaration,
        "split_rows": {split: len(partitions[split]) for split in partitions},
        "train_target_action_counts": dict(
            sorted(Counter(ACTION_ORDER[row.action_index] for row in partitions["train"]).items())
        ),
        "train_metrics": _metrics(train_probabilities, train_y, train_net),
        "validation_metrics": _metrics(
            validation_probabilities, validation_y, validation_net
        ),
        "validation_train_base_rate_baseline": _metrics(
            validation_baseline, validation_y, validation_net
        ),
        "holdout_metrics": _metrics(holdout_probabilities, holdout_y, holdout_net),
        "holdout_train_base_rate_baseline": _metrics(
            holdout_baseline, holdout_y, holdout_net
        ),
        "fit_partition": "TRAIN_ONLY",
        "selection_partition": "VALIDATION_ONLY_WHEN_CANDIDATES_COMPARABLE",
        "holdout_used_for_selection": False,
    }
    result["validation_brier_improves_baseline"] = (
        result["validation_metrics"]["multiclass_brier"]
        < result["validation_train_base_rate_baseline"]["multiclass_brier"]
    )
    result["validation_after_cost_positive"] = (
        result["validation_metrics"]["counterfactual_after_cost_expectancy_bps"] > 0.0
    )
    result["validation_research_screening_pass"] = (
        result["validation_brier_improves_baseline"]
        and result["validation_after_cost_positive"]
    )
    return result


def _eligible_hedge_partition(
    partitions: Mapping[str, Sequence[ValidatedRow]],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    for split in ("train", "validation", "holdout"):
        count = len(partitions[split])
        if count < MIN_SPLIT_ROWS:
            reasons.append(f"{split.upper()}_HEDGE_ROWS_BELOW_{MIN_SPLIT_ROWS}:{count}")
    train_targets = {
        row.hedge_target_index for row in partitions["train"]
    }
    if train_targets != {0, 1}:
        reasons.append("TRAIN_HEDGE_AND_UNHEDGED_LABELS_REQUIRED")
    return not reasons, reasons


def _hedge_arrays(
    rows: Sequence[ValidatedRow],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if any(
        row.hedge_target_index is None
        or row.unhedged_after_cost_pnl_bps is None
        or row.hedged_after_cost_pnl_bps is None
        for row in rows
    ):
        raise AdaptiveDiversifiedChallengerError(
            "hedge_partition:COMPLETE_HEDGE_LABELS_REQUIRED"
        )
    return (
        np.asarray([row.features for row in rows], dtype=np.float64),
        np.asarray([row.hedge_target_index for row in rows], dtype=np.int64),
        np.asarray(
            [
                (
                    row.unhedged_after_cost_pnl_bps,
                    row.hedged_after_cost_pnl_bps,
                )
                for row in rows
            ],
            dtype=np.float64,
        ),
    )


def _hedge_probability(model: Any, values: np.ndarray) -> np.ndarray:
    raw = np.asarray(model.predict_proba(values), dtype=np.float64)
    classes = tuple(int(value) for value in model.classes_)
    if set(classes) != {0, 1}:
        raise AdaptiveDiversifiedChallengerError(
            "hedge_model:BOTH_BINARY_CLASSES_REQUIRED"
        )
    probability = raw[:, classes.index(1)]
    if (
        probability.shape != (values.shape[0],)
        or not np.all(np.isfinite(probability))
        or np.any(probability < 0.0)
        or np.any(probability > 1.0)
    ):
        raise AdaptiveDiversifiedChallengerError(
            "hedge_model:PROBABILITY_SEMANTICS_INVALID"
        )
    return probability


def _hedge_metrics(
    probabilities: np.ndarray,
    targets: np.ndarray,
    after_cost_outcomes: np.ndarray,
) -> dict[str, Any]:
    predicted_hedge = probabilities >= 0.5
    chosen_after_cost = np.where(
        predicted_hedge,
        after_cost_outcomes[:, 1],
        after_cost_outcomes[:, 0],
    )
    clipped = np.clip(probabilities, 1e-12, 1.0 - 1e-12)
    result = {
        "rows": int(targets.shape[0]),
        "binary_brier": float(np.mean((probabilities - targets) ** 2)),
        "negative_log_likelihood": float(
            -np.mean(
                targets * np.log(clipped)
                + (1 - targets) * np.log(1.0 - clipped)
            )
        ),
        "target_hedge_accuracy": float(np.mean(predicted_hedge == targets)),
        "predicted_hedge_rate": float(np.mean(predicted_hedge)),
        "counterfactual_selected_after_cost_expectancy_bps": float(
            np.mean(chosen_after_cost)
        ),
        "counterfactual_selected_positive_rate": float(
            np.mean(chosen_after_cost > 0.0)
        ),
        "counterfactual_counts_as_realized_paper_profit": False,
        "actual_accounting_effect": False,
    }
    if any(
        not math.isfinite(float(value))
        for key, value in result.items()
        if key
        not in {
            "rows",
            "counterfactual_counts_as_realized_paper_profit",
            "actual_accounting_effect",
        }
    ):
        raise AdaptiveDiversifiedChallengerError("hedge_metrics:NONFINITE")
    return result


def _fit_hedge_candidate(
    *,
    partitions: Mapping[str, Sequence[ValidatedRow]],
    eligible_symbols: Sequence[str],
    eligible_timeframes: Sequence[str],
    dataset_sha256: str,
) -> dict[str, Any]:
    arrays = {split: _hedge_arrays(partitions[split]) for split in partitions}
    model = _algorithm("multinomial_logistic")
    model.fit(arrays["train"][0], arrays["train"][1])
    try:
        model_parameter_fingerprint = _sha256(pickle.dumps(model, protocol=5))
    except (pickle.PickleError, TypeError, ValueError) as exc:
        raise AdaptiveDiversifiedChallengerError(
            "hedge_model:PARAMETER_FINGERPRINT_FAILED"
        ) from exc
    probabilities = {
        split: _hedge_probability(model, values[0])
        for split, values in arrays.items()
    }
    train_rate = float(np.mean(arrays["train"][1]))
    baselines = {
        split: np.full(values[1].shape[0], train_rate, dtype=np.float64)
        for split, values in arrays.items()
    }
    declaration = {
        "strategy_family": "predeclared_delta_neutral_loss_avoidance_research",
        "hedge_contract": HEDGE_CONTRACT,
        "comparison_semantics": HEDGE_COMPARISON,
        "eligible_symbols": list(eligible_symbols),
        "eligible_timeframes": list(eligible_timeframes),
        "required_data": [
            "ServingFeatureABIV2 exact feature vector",
            "authenticated matured unhedged after-cost counterfactual",
            "authenticated matured fully delta-neutral after-cost counterfactual",
            "chronological purged train/validation/holdout split",
        ],
        "relative_value_supported": False,
        "relative_value_block_reason": (
            "NO_SYNCHRONIZED_PAIR_OR_BASKET_LABEL_BINDINGS"
        ),
        "execution_assumptions": {
            "counterfactual_costs_reflected_in_labels": True,
            "venue_executability_not_assumed": True,
            "requires_hard_validator_before_any_future_paper_action": True,
        },
        "risk_behavior": (
            "RESEARCH_ONLY_NO_SIZING_LEVERAGE_MARGIN_HEDGE_OR_ROUTE_AUTHORITY"
        ),
    }
    contract = _algorithm_contract("multinomial_logistic")
    identity = {
        "dataset_sha256": dataset_sha256,
        "algorithm_contract": contract,
        "declaration": declaration,
    }
    result = {
        "candidate_id": "adaptive_hedge_" + _sha256(_canonical_bytes(identity))[:24],
        "dataset_sha256": dataset_sha256,
        "algorithm": "multinomial_logistic",
        "algorithm_contract": contract,
        "model_parameter_fingerprint": model_parameter_fingerprint,
        "runtime_versions": {
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "group_kind": "complete_eligible_hedge_label_universe",
        "group_value": "PREDECLARED_DELTA_NEUTRAL_ARM",
        "declaration": declaration,
        "split_rows": {split: len(partitions[split]) for split in partitions},
        "train_target_hedge_counts": dict(
            sorted(Counter(str(row.hedge_target_index) for row in partitions["train"]).items())
        ),
        "train_metrics": _hedge_metrics(
            probabilities["train"], arrays["train"][1], arrays["train"][2]
        ),
        "validation_metrics": _hedge_metrics(
            probabilities["validation"],
            arrays["validation"][1],
            arrays["validation"][2],
        ),
        "validation_train_base_rate_baseline": _hedge_metrics(
            baselines["validation"],
            arrays["validation"][1],
            arrays["validation"][2],
        ),
        "holdout_metrics": _hedge_metrics(
            probabilities["holdout"], arrays["holdout"][1], arrays["holdout"][2]
        ),
        "holdout_train_base_rate_baseline": _hedge_metrics(
            baselines["holdout"],
            arrays["holdout"][1],
            arrays["holdout"][2],
        ),
        "fit_partition": "TRAIN_ONLY",
        "selection_partition": "VALIDATION_ONLY",
        "holdout_used_for_selection": False,
        "selected_by_validation": False,
    }
    result["validation_brier_improves_baseline"] = (
        result["validation_metrics"]["binary_brier"]
        < result["validation_train_base_rate_baseline"]["binary_brier"]
    )
    result["validation_after_cost_positive"] = (
        result["validation_metrics"][
            "counterfactual_selected_after_cost_expectancy_bps"
        ]
        > 0.0
    )
    result["validation_research_screening_pass"] = (
        result["validation_brier_improves_baseline"]
        and result["validation_after_cost_positive"]
    )
    return result


def _regime_predicates(
    ordered_features: Sequence[str],
    rows: Sequence[ValidatedRow],
) -> tuple[dict[str, Callable[[ValidatedRow], bool]], dict[str, float]]:
    if "true_range_pct" not in ordered_features:
        return {}, {}
    position = ordered_features.index("true_range_pct")
    train_values = np.asarray(
        [row.features[position] for row in rows if row.split == "train"],
        dtype=np.float64,
    )
    low, high = (float(value) for value in np.quantile(train_values, (1.0 / 3.0, 2.0 / 3.0)))
    if not math.isfinite(low) or not math.isfinite(high) or high <= low:
        return {}, {}
    return {
        "LOW_TRAIN_VOLATILITY": lambda row: row.features[position] <= low,
        "MID_TRAIN_VOLATILITY": lambda row: low < row.features[position] <= high,
        "HIGH_TRAIN_VOLATILITY": lambda row: row.features[position] > high,
    }, {"train_q33": low, "train_q67": high}


def build_challenger_evidence(
    *,
    mode: str,
    dataset: Mapping[str, Any],
    release_projection: Mapping[str, Any],
    release_source: Mapping[str, Any],
) -> dict[str, Any]:
    if mode not in MODES:
        raise AdaptiveDiversifiedChallengerError(f"mode:INVALID:{mode}")
    ordered, rows = _validated_rows(dataset, release_projection)
    symbols = tuple(sorted({row.symbol for row in rows}))
    timeframes = tuple(sorted({row.timeframe for row in rows}))
    specifications: list[
        tuple[str, str, str, Callable[[ValidatedRow], bool], tuple[str, ...], tuple[str, ...]]
    ] = []
    selection_scope = "PREDECLARED_NONCOMPARABLE_SLICES"
    regime_thresholds: dict[str, float] = {}
    if mode == "horizon":
        for timeframe in timeframes:
            specifications.append(
                (
                    "multinomial_logistic",
                    "timeframe",
                    timeframe,
                    lambda row, value=timeframe: row.timeframe == value,
                    symbols,
                    (timeframe,),
                )
            )
    elif mode == "symbol_regime":
        train_counts = Counter(row.symbol for row in rows if row.split == "train")
        ranked_symbols = sorted(
            symbols,
            key=lambda symbol: (-train_counts[symbol], symbol),
        )[:MAX_SYMBOL_CANDIDATES]
        for symbol in ranked_symbols:
            symbol_timeframes = tuple(
                sorted({row.timeframe for row in rows if row.symbol == symbol})
            )
            specifications.append(
                (
                    "multinomial_logistic",
                    "symbol",
                    symbol,
                    lambda row, value=symbol: row.symbol == value,
                    (symbol,),
                    symbol_timeframes,
                )
            )
        predicates, regime_thresholds = _regime_predicates(ordered, rows)
        for regime, predicate in predicates.items():
            specifications.append(
                (
                    "multinomial_logistic",
                    "train_frozen_volatility_regime",
                    regime,
                    predicate,
                    symbols,
                    timeframes,
                )
            )
    elif mode == "architecture":
        selection_scope = "COMPARABLE_FULL_UNIVERSE_VALIDATION_BRIER"
        for algorithm in (
            "multinomial_logistic",
            "hist_gradient_boosting",
            "small_neural_network",
        ):
            specifications.append(
                (
                    algorithm,
                    "complete_eligible_universe",
                    "ALL",
                    lambda _row: True,
                    symbols,
                    timeframes,
                )
            )
    else:
        selection_scope = "PREDECLARED_HEDGE_LOSS_AVOIDANCE_VALIDATION_BRIER"

    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    if mode == "hedged_relative_value":
        hedge_partitions = _partition(
            rows,
            lambda row: row.hedge_target_index is not None,
        )
        hedge_eligible, hedge_reasons = _eligible_hedge_partition(
            hedge_partitions
        )
        if hedge_eligible:
            candidates.append(
                _fit_hedge_candidate(
                    partitions=hedge_partitions,
                    eligible_symbols=symbols,
                    eligible_timeframes=timeframes,
                    dataset_sha256=str(release_projection["dataset_sha256"]),
                )
            )
        else:
            rejected.append(
                {
                    "algorithm": "multinomial_logistic",
                    "group_kind": "complete_eligible_hedge_label_universe",
                    "group_value": "PREDECLARED_DELTA_NEUTRAL_ARM",
                    "split_rows": {
                        split: len(hedge_partitions[split])
                        for split in hedge_partitions
                    },
                    "exact_reasons": hedge_reasons,
                }
            )
    for algorithm, group_kind, group_value, predicate, eligible_symbols, eligible_timeframes in specifications:
        partitions = _partition(rows, predicate)
        eligible, reasons = _eligible_partition(partitions)
        if not eligible:
            rejected.append(
                {
                    "algorithm": algorithm,
                    "group_kind": group_kind,
                    "group_value": group_value,
                    "split_rows": {split: len(partitions[split]) for split in partitions},
                    "exact_reasons": reasons,
                }
            )
            continue
        candidates.append(
            _fit_candidate(
                algorithm=algorithm,
                group_kind=group_kind,
                group_value=group_value,
                partitions=partitions,
                eligible_symbols=eligible_symbols,
                eligible_timeframes=eligible_timeframes,
                dataset_sha256=str(release_projection["dataset_sha256"]),
            )
        )

    selected_candidate_id: str | None = None
    if mode == "architecture" and candidates:
        selected_candidate_id = min(
            candidates,
            key=lambda candidate: (
                candidate["validation_metrics"]["multiclass_brier"],
                candidate["candidate_id"],
            ),
        )["candidate_id"]
    for candidate in candidates:
        candidate["selected_by_validation"] = (
            mode == "architecture"
            and candidate["candidate_id"] == selected_candidate_id
        )
    screening_candidate_ids = [
        candidate["candidate_id"]
        for candidate in candidates
        if candidate["validation_research_screening_pass"]
    ]
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_RESEARCH_CHALLENGERS_TRAINED" if candidates else "PASS_NO_ELIGIBLE_SLICE",
        "mode": mode,
        "dataset_release": dict(release_projection),
        "source_matured_revision_count": release_source.get("matured_revision_count"),
        "source_terminal_chain_sha256": release_source.get("terminal_chain_sha256"),
        "feature_abi_sha256": dataset.get("feature_abi_sha256"),
        "feature_builder_sha256": dataset.get("feature_builder_sha256"),
        "ordered_feature_names": list(ordered),
        "selection_scope": selection_scope,
        "fit_partition": "TRAIN_ONLY",
        "holdout_used_for_selection": False,
        "regime_thresholds_fit_on_train_only": regime_thresholds,
        "trained_candidate_count": len(candidates),
        "rejected_slice_count": len(rejected),
        "candidates": candidates,
        "rejected_slices": rejected,
        "selected_candidate_id": selected_candidate_id,
        "validation_research_screening_candidate_ids": screening_candidate_ids,
        "statistical_superiority_proven": False,
        "hedge_contract": (
            HEDGE_CONTRACT if mode == "hedged_relative_value" else None
        ),
        "hedge_comparison_semantics": (
            HEDGE_COMPARISON if mode == "hedged_relative_value" else None
        ),
        "relative_value_supported": False,
        "relative_value_block_reason": (
            "NO_SYNCHRONIZED_PAIR_OR_BASKET_LABEL_BINDINGS"
        ),
        "unsupported_families": [
            {
                "family": "sequence_model",
                "exact_reason": "SIGNED_RELEASE_HAS_INDEPENDENT_ROWS_WITHOUT_AUTHENTICATED_SEQUENCE_BINDINGS",
            },
            {
                "family": "offline_reinforcement_learning",
                "exact_reason": "SIGNED_RELEASE_HAS_NO_AUTHENTICATED_STATE_TRANSITION_TRAJECTORIES",
            },
            {
                "family": "cross_sectional_relative_value",
                "exact_reason": "SIGNED_RELEASE_HAS_NO_SYNCHRONIZED_PAIR_OR_BASKET_LABEL_BINDINGS",
            },
        ],
        "counterfactual_counts_as_realized_paper_profit": False,
        "serving_abi_changed": False,
        "registry_write_attempted": False,
        "activation_eligible": False,
        "checkpoint_promotable": False,
        "paper_only": True,
        "live_eligible": False,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    result["evidence_id"] = "adaptive_diversified_evidence_" + _sha256(
        _canonical_bytes(result)
    )[:24]
    unsigned = dict(result)
    result["payload_sha256"] = _sha256(_canonical_bytes(unsigned))
    return result


def run_once(
    *,
    mode: str,
    dataset_release_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    projection, source, dataset = supervisor._authenticated_dataset_release_snapshot(  # noqa: SLF001
        dataset_release_root
    )
    evidence = build_challenger_evidence(
        mode=mode,
        dataset=dataset,
        release_projection=projection,
        release_source=source,
    )
    data = json.dumps(
        evidence,
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    try:
        output_sha256 = supervisor._write_immutable_private_bytes(  # noqa: SLF001
            output_dir / OUTPUT_NAME,
            data,
        )
    except (OSError, ValueError) as exc:
        raise AdaptiveDiversifiedChallengerError("output:IMMUTABLE_WRITE_FAILED") from exc
    return {**evidence, "output_file_sha256": output_sha256}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--dataset-release-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_once(
        mode=args.mode,
        dataset_release_root=args.dataset_release_root,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
