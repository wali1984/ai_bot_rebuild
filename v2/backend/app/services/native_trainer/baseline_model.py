"""V2 native trainer baseline model (paper / shadow only).

Pure stdlib implementation. No checkpoint compatibility claim, no
policy-architecture parity claim, no live or canary approval. Used
solely to:

* train a small logistic-style classifier on V2-native dataset rows
* evaluate the trained classifier against held-out V2 rows
* evaluate fixed baselines for comparison:
    - hold baseline (always "no trade")
    - contract-only publisher baseline (constant low confidence)
    - simple V2-native baseline (EMA spread / RSI deviation)
    - legacy reference action if the V2 mirror provides one (mirror-only)

The model is intentionally tiny and deterministic. It is NOT the
production trainer. Predictions emitted from it always carry
``trainer_source=V2_NATIVE_BASELINE_PAPER_SHADOW``,
``model_source=BASELINE_NOT_PRODUCTION``,
``model_readiness=NOT_PRODUCTION_READY``,
``paper_fill_allowed=False``,
``live_gate=blocked_human_only``,
``live_symbols=[]``.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from .dataset_builder import (
    ALTDATA_NUMERIC_FEATURES,
    ALTDATA_PROVIDER_FLAGS,
    DatasetRow,
    LIVE_GATE_BLOCKED,
    ROW_HELD_OUT_VALIDATION,
    ROW_TRAINABLE,
    _safety_block,
)


SCHEMA_VERSION = "v2_native_trainer_baseline_model_v1"

POSITIVE_LABELS = {"true_positive_after_cost_gain"}
NEGATIVE_LABELS = {
    "false_negative_after_cost_loss",
    "false_block_negative_outcome",
}
NEUTRAL_LABELS = {"neutral_no_edge", "correct_no_trade"}
NON_TRAINABLE_LABELS_FOR_CALIBRATION = frozenset({
    "insufficient_evidence",
    "label_missing",
})
FALLBACK_ROUND_TRIP_COST_BPS = 7.0
DEFAULT_CALIBRATION_BIN_COUNT = 5

ACTION_LONG = "LONG"
ACTION_FLAT = "FLAT"

BASE_FEATURE_NAMES = (
    "ema_spread",
    "rsi_14_dev",
    "macd_minus_signal",
    "atr_14",
    "vol_zscore",
)
ALTDATA_MODEL_FEATURE_NAMES = (
    tuple(ALTDATA_NUMERIC_FEATURES)
    + tuple(f"provider_available_{provider}" for provider in ALTDATA_PROVIDER_FLAGS)
    + tuple(f"input_present_{provider}" for provider in ALTDATA_PROVIDER_FLAGS)
)
FEATURE_NAMES = BASE_FEATURE_NAMES + ALTDATA_MODEL_FEATURE_NAMES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _row_feature_vector(row: DatasetRow) -> list[float]:
    v = row.feature_vector
    base_values = {
        "ema_spread": float(v.get("ema_spread") or 0.0),
        "rsi_14_dev": float((v.get("rsi_14") or 50.0) - 50.0),
        "macd_minus_signal": float(
            (v.get("macd") or 0.0) - (v.get("macd_signal") or 0.0)
        ),
        "atr_14": float(v.get("atr_14") or 0.0),
        "vol_zscore": float(v.get("vol_zscore") or 0.0),
    }
    out: list[float] = []
    for name in FEATURE_NAMES:
        if name in base_values:
            out.append(base_values[name])
        else:
            out.append(float(v.get(name) or 0.0))
    return out


def _row_is_positive(row: DatasetRow) -> int:
    return 1 if row.label in POSITIVE_LABELS else 0


def _row_after_cost(row: DatasetRow) -> float | None:
    return row.after_cost_return_bps


# ---------------------------------------------------------------------------
# Baseline strategies
# ---------------------------------------------------------------------------


@dataclass
class BaselineMetrics:
    name: str
    sample_count: int = 0
    train_count: int = 0
    validation_count: int = 0
    action_long_count: int = 0
    action_flat_count: int = 0
    after_cost_expectancy_bps: float | None = None
    false_positive_rate: float | None = None
    false_negative_rate: float | None = None
    downside_pre_cascade_recall: float | None = None
    precision: float | None = None
    drawdown_bps: float | None = None
    action_match_vs_legacy: float | None = None
    improvement_vs_hold_baseline: float | None = None
    improvement_vs_contract_only_baseline: float | None = None

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sample_count": self.sample_count,
            "train_count": self.train_count,
            "validation_count": self.validation_count,
            "action_long_count": self.action_long_count,
            "action_flat_count": self.action_flat_count,
            "after_cost_expectancy_bps": self.after_cost_expectancy_bps,
            "false_positive_rate": self.false_positive_rate,
            "false_negative_rate": self.false_negative_rate,
            "downside_pre_cascade_recall": self.downside_pre_cascade_recall,
            "precision": self.precision,
            "drawdown_bps": self.drawdown_bps,
            "action_match_vs_legacy": self.action_match_vs_legacy,
            "improvement_vs_hold_baseline": self.improvement_vs_hold_baseline,
            "improvement_vs_contract_only_baseline":
                self.improvement_vs_contract_only_baseline,
        }


def _evaluate_strategy(
    *,
    name: str,
    rows: Sequence[DatasetRow],
    decide_action: Any,
    train_count: int,
    validation_count: int,
) -> BaselineMetrics:
    """Score a strategy by its (action, label, outcome) over rows.

    ``decide_action(row)`` returns "LONG" or "FLAT".
    """
    long_count = 0
    flat_count = 0
    realized_pnls: list[float] = []
    drawdowns: list[float] = []
    legacy_match = 0
    legacy_total = 0
    fp = 0  # predicted long, actual negative
    fn = 0  # predicted flat, actual positive
    tp = 0  # predicted long, actual positive
    tn = 0  # predicted flat, actual not positive
    downside_total = 0
    downside_caught = 0

    for row in rows:
        if row.classification not in {ROW_TRAINABLE, ROW_HELD_OUT_VALIDATION}:
            continue
        action = decide_action(row)
        if action == ACTION_LONG:
            long_count += 1
        else:
            flat_count += 1
        after_cost = _row_after_cost(row)
        if after_cost is not None:
            realized = float(after_cost) if action == ACTION_LONG else 0.0
            realized_pnls.append(realized)
            if row.max_adverse_bps is not None:
                drawdowns.append(float(row.max_adverse_bps))
        if row.legacy_reference_action is not None:
            legacy_total += 1
            legacy_action = str(row.legacy_reference_action).upper()
            if (
                (legacy_action == "LONG" and action == ACTION_LONG)
                or (legacy_action in {"FLAT", "NONE", "NO_TRADE"} and action == ACTION_FLAT)
            ):
                legacy_match += 1
        positive = _row_is_positive(row)
        if action == ACTION_LONG and positive == 1:
            tp += 1
        elif action == ACTION_LONG and positive == 0:
            fp += 1
        elif action == ACTION_FLAT and positive == 1:
            fn += 1
        else:
            tn += 1
        if row.label in NEGATIVE_LABELS:
            downside_total += 1
            if action == ACTION_FLAT:
                downside_caught += 1

    sample_count = long_count + flat_count
    after_cost_expectancy = (
        sum(realized_pnls) / len(realized_pnls) if realized_pnls else None
    )
    drawdown = max(drawdowns) if drawdowns else None
    precision = (
        tp / (tp + fp) if (tp + fp) > 0 else None
    )
    fp_rate = (
        fp / (fp + tn) if (fp + tn) > 0 else None
    )
    fn_rate = (
        fn / (fn + tp) if (fn + tp) > 0 else None
    )
    downside_recall = (
        downside_caught / downside_total if downside_total > 0 else None
    )
    legacy_match_rate = (
        legacy_match / legacy_total if legacy_total > 0 else None
    )
    return BaselineMetrics(
        name=name,
        sample_count=sample_count,
        train_count=train_count,
        validation_count=validation_count,
        action_long_count=long_count,
        action_flat_count=flat_count,
        after_cost_expectancy_bps=after_cost_expectancy,
        false_positive_rate=fp_rate,
        false_negative_rate=fn_rate,
        downside_pre_cascade_recall=downside_recall,
        precision=precision,
        drawdown_bps=drawdown,
        action_match_vs_legacy=legacy_match_rate,
    )


def _hold_baseline_action(_row: DatasetRow) -> str:
    return ACTION_FLAT


def _contract_only_baseline_action(_row: DatasetRow) -> str:
    return ACTION_FLAT


def _simple_v2_native_baseline_action(row: DatasetRow) -> str:
    v = row.feature_vector
    spread = v.get("ema_spread")
    rsi = v.get("rsi_14")
    if spread is not None and spread > 0.0:
        return ACTION_LONG
    if rsi is not None and rsi > 55.0:
        return ACTION_LONG
    return ACTION_FLAT


# ---------------------------------------------------------------------------
# Logistic regression
# ---------------------------------------------------------------------------


@dataclass
class LogisticModel:
    weights: list[float] = field(default_factory=lambda: [0.0] * len(FEATURE_NAMES))
    bias: float = 0.0
    feature_names: list[str] = field(
        default_factory=lambda: list(FEATURE_NAMES)
    )
    epochs_trained: int = 0
    train_sample_count: int = 0
    classifier_threshold: float = 0.55

    def predict_proba(self, x: Sequence[float]) -> float:
        z = self.bias + sum(w * float(xi) for w, xi in zip(self.weights, x))
        return _sigmoid(z)

    def decide_action(self, row: DatasetRow) -> str:
        x = _row_feature_vector(row)
        p = self.predict_proba(x)
        return ACTION_LONG if p >= self.classifier_threshold else ACTION_FLAT

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "weights": list(self.weights),
            "bias": self.bias,
            "feature_names": list(self.feature_names),
            "epochs_trained": self.epochs_trained,
            "train_sample_count": self.train_sample_count,
            "classifier_threshold": self.classifier_threshold,
            "model_source": "BASELINE_NOT_PRODUCTION",
            "model_readiness": "NOT_PRODUCTION_READY",
        }


def train_logistic_model(
    train_rows: Sequence[DatasetRow],
    *,
    learning_rate: float = 0.05,
    epochs: int = 200,
    l2_lambda: float = 0.001,
    classifier_threshold: float = 0.55,
) -> LogisticModel:
    model = LogisticModel(classifier_threshold=classifier_threshold)
    if not train_rows:
        return model
    xs = [_row_feature_vector(r) for r in train_rows]
    ys = [_row_is_positive(r) for r in train_rows]
    feature_count = len(FEATURE_NAMES)
    means = [0.0] * feature_count
    stds = [1.0] * feature_count
    n = len(xs)
    for j in range(feature_count):
        col = [row[j] for row in xs]
        m = sum(col) / n
        means[j] = m
        var = sum((v - m) ** 2 for v in col) / n
        stds[j] = math.sqrt(var) if var > 1e-9 else 1.0
    norm_xs = [
        [(row[j] - means[j]) / stds[j] for j in range(feature_count)]
        for row in xs
    ]

    weights = [0.0] * feature_count
    bias = 0.0
    for _ in range(epochs):
        grad_w = [0.0] * feature_count
        grad_b = 0.0
        for x, y in zip(norm_xs, ys):
            z = bias + sum(w * xi for w, xi in zip(weights, x))
            p = _sigmoid(z)
            err = p - float(y)
            for j in range(feature_count):
                grad_w[j] += err * x[j]
            grad_b += err
        for j in range(feature_count):
            grad_w[j] = grad_w[j] / n + l2_lambda * weights[j]
            weights[j] -= learning_rate * grad_w[j]
        bias -= learning_rate * (grad_b / n)
    final_weights: list[float] = []
    final_bias = bias
    for j in range(feature_count):
        if stds[j] <= 1e-9:
            final_weights.append(0.0)
            continue
        final_weights.append(weights[j] / stds[j])
        final_bias -= weights[j] * (means[j] / stds[j])
    model.weights = final_weights
    model.bias = final_bias
    model.epochs_trained = epochs
    model.train_sample_count = n
    return model


# ---------------------------------------------------------------------------
# Evaluation orchestration
# ---------------------------------------------------------------------------


@dataclass
class EvaluationResult:
    train_count: int
    validation_count: int
    label_distribution_train: dict[str, int]
    label_distribution_validation: dict[str, int]
    minimum_sample_satisfied: bool
    minimum_train_rows: int
    metrics: list[BaselineMetrics] = field(default_factory=list)
    trained_model: LogisticModel | None = None
    publishable_baseline_available: bool = False

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "train_count": self.train_count,
            "validation_count": self.validation_count,
            "label_distribution_train": dict(
                sorted(self.label_distribution_train.items())
            ),
            "label_distribution_validation": dict(
                sorted(self.label_distribution_validation.items())
            ),
            "minimum_sample_satisfied": self.minimum_sample_satisfied,
            "minimum_train_rows": self.minimum_train_rows,
            "metrics": [m.to_jsonable() for m in self.metrics],
            "trained_model": (
                self.trained_model.to_jsonable() if self.trained_model else None
            ),
            "publishable_baseline_available": (
                self.publishable_baseline_available
            ),
        }


def evaluate_all_baselines(
    rows: Sequence[DatasetRow],
    *,
    minimum_train_rows: int = 64,
    classifier_threshold: float = 0.55,
) -> EvaluationResult:
    train_rows = [r for r in rows if r.classification == ROW_TRAINABLE]
    validation_rows = [
        r for r in rows if r.classification == ROW_HELD_OUT_VALIDATION
    ]
    label_dist_train: dict[str, int] = {}
    for r in train_rows:
        label_dist_train[r.label] = label_dist_train.get(r.label, 0) + 1
    label_dist_val: dict[str, int] = {}
    for r in validation_rows:
        label_dist_val[r.label] = label_dist_val.get(r.label, 0) + 1

    eval_rows = list(train_rows) + list(validation_rows)

    metrics: list[BaselineMetrics] = []
    hold = _evaluate_strategy(
        name="hold_baseline",
        rows=eval_rows,
        decide_action=_hold_baseline_action,
        train_count=len(train_rows),
        validation_count=len(validation_rows),
    )
    metrics.append(hold)

    contract_only = _evaluate_strategy(
        name="contract_only_publisher_baseline",
        rows=eval_rows,
        decide_action=_contract_only_baseline_action,
        train_count=len(train_rows),
        validation_count=len(validation_rows),
    )
    metrics.append(contract_only)

    simple_native = _evaluate_strategy(
        name="simple_v2_native_baseline_ema_or_rsi",
        rows=eval_rows,
        decide_action=_simple_v2_native_baseline_action,
        train_count=len(train_rows),
        validation_count=len(validation_rows),
    )
    metrics.append(simple_native)

    def _legacy_mirror_action(row: DatasetRow) -> str:
        action = (row.legacy_reference_action or "").upper()
        if action == "LONG":
            return ACTION_LONG
        return ACTION_FLAT

    legacy_mirror = _evaluate_strategy(
        name="legacy_reference_action_mirror_only",
        rows=eval_rows,
        decide_action=_legacy_mirror_action,
        train_count=len(train_rows),
        validation_count=len(validation_rows),
    )
    metrics.append(legacy_mirror)

    trained_model: LogisticModel | None = None
    publishable = False
    if len(train_rows) >= minimum_train_rows:
        trained_model = train_logistic_model(
            train_rows,
            classifier_threshold=classifier_threshold,
        )
        trained = _evaluate_strategy(
            name="v2_native_logistic_baseline_trained",
            rows=eval_rows,
            decide_action=trained_model.decide_action,
            train_count=len(train_rows),
            validation_count=len(validation_rows),
        )
        metrics.append(trained)
        if (
            trained.after_cost_expectancy_bps is not None
            and trained.after_cost_expectancy_bps > 0
            and (
                hold.after_cost_expectancy_bps is None
                or trained.after_cost_expectancy_bps
                > hold.after_cost_expectancy_bps
            )
            and len(validation_rows) > 0
        ):
            publishable = True

    hold_exp = hold.after_cost_expectancy_bps
    contract_exp = contract_only.after_cost_expectancy_bps
    for m in metrics:
        if m.after_cost_expectancy_bps is None:
            continue
        if hold_exp is not None:
            m.improvement_vs_hold_baseline = (
                m.after_cost_expectancy_bps - hold_exp
            )
        if contract_exp is not None:
            m.improvement_vs_contract_only_baseline = (
                m.after_cost_expectancy_bps - contract_exp
            )

    return EvaluationResult(
        train_count=len(train_rows),
        validation_count=len(validation_rows),
        label_distribution_train=label_dist_train,
        label_distribution_validation=label_dist_val,
        minimum_sample_satisfied=len(train_rows) >= minimum_train_rows,
        minimum_train_rows=minimum_train_rows,
        metrics=metrics,
        trained_model=trained_model,
        publishable_baseline_available=publishable,
    )


# ---------------------------------------------------------------------------
# Prediction payload emitter (paper / shadow only)
# ---------------------------------------------------------------------------


REQUIRED_PUBLISHABLE_FIELDS = (
    "prediction_id",
    "symbol",
    "timeframe",
    "generated_at",
    "feature_snapshot_id",
    "trainer_source",
    "model_source",
    "model_readiness",
    "confidence_calibrated",
    "expected_move_bps",
    "expected_move_after_cost_bps",
    "paper_fill_allowed",
    "paper_fill_gate_status",
    "live_gate",
    "live_symbols",
    "approves_live",
    "approves_canary",
    "approves_legacy_shutdown",
    "approves_redis_trim",
)


def _stable_baseline_prediction_id(symbol: str, tf: str, snapshot_id: str) -> str:
    digest = hashlib.sha256(
        f"{symbol}|{tf}|{snapshot_id}|baseline".encode("utf-8")
    ).hexdigest()[:32]
    return f"v2_baseline_pred_{digest}"


def build_baseline_prediction(
    *,
    row: DatasetRow,
    model: LogisticModel,
) -> dict[str, Any]:
    p = model.predict_proba(_row_feature_vector(row))
    confidence_calibrated = float(min(0.55, max(0.45, 0.45 + (p - 0.5) * 0.1)))
    expected_move_bps = float(max(-25.0, min(25.0, (p - 0.5) * 50.0)))
    expected_move_after_cost_bps = float(expected_move_bps - FALLBACK_ROUND_TRIP_COST_BPS)
    payload = {
        "prediction_id": _stable_baseline_prediction_id(
            row.symbol, row.timeframe, row.feature_snapshot_id
        ),
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "generated_at": _utc_now_iso(),
        "feature_snapshot_id": row.feature_snapshot_id,
        "trainer_source": "V2_NATIVE_BASELINE_PAPER_SHADOW",
        "model_source": "BASELINE_NOT_PRODUCTION",
        "model_readiness": "NOT_PRODUCTION_READY",
        "prediction_source_classification": "BASELINE_LOGISTIC_PAPER_SHADOW",
        "confidence_raw": float(p),
        "confidence_calibrated": confidence_calibrated,
        "expected_move_bps": expected_move_bps,
        "expected_move_after_cost_bps": expected_move_after_cost_bps,
        "feature_freshness_state": row.feature_freshness_state,
        "missing_feature_flags": row.missing_feature_flags,
        "stale_feature_flags": row.stale_feature_flags,
        "checkpoint_id": None,
        "checkpoint_blocker": (
            "OPERATOR_DECISION_REQUIRED_NATIVE_TRAINER_CHECKPOINT"
        ),
        "model_blockers": [
            "baseline_signal_is_not_an_edge_proof",
            "native_trainer_not_implemented",
            "checkpoint_operator_decision_required",
        ],
        "paper_fill_allowed": False,
        "paper_fill_gate_status": "BLOCKED_BASELINE_NOT_PRODUCTION",
        "paper_fill_gate_block_reasons": [
            "baseline_signal_is_not_an_edge_proof",
            "native_trainer_not_implemented",
            "checkpoint_operator_decision_required",
            "live_gate_blocked_human_only",
        ],
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
    return payload


def is_baseline_prediction_publishable(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    for f in REQUIRED_PUBLISHABLE_FIELDS:
        if f not in payload:
            return False
    if payload["trainer_source"] != "V2_NATIVE_BASELINE_PAPER_SHADOW":
        return False
    if payload["model_source"] != "BASELINE_NOT_PRODUCTION":
        return False
    if payload["model_readiness"] != "NOT_PRODUCTION_READY":
        return False
    if payload["paper_fill_allowed"] is not False:
        return False
    if payload["live_gate"] != LIVE_GATE_BLOCKED:
        return False
    if payload["live_symbols"] != []:
        return False
    return True


# ---------------------------------------------------------------------------
# V2-only publisher (refuses non-v2:* keys)
# ---------------------------------------------------------------------------


@dataclass
class BaselinePublisherAudit:
    redis_connected: bool = False
    writes_attempted: int = 0
    writes_succeeded: int = 0
    writes_failed: int = 0
    old_redis_write_attempts: int = 0
    keys_written: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class V2BaselinePublisher:
    """Publishes baseline predictions to ``v2:prediction:*`` only.

    Refuses to overwrite stronger existing predictions (anything whose
    ``trainer_source`` starts with ``V2_NATIVE_TRAINER`` or
    ``V2_NATIVE_TRAINER_READY``).
    """

    PRESERVE_STRONGER_TOKEN = "V2_NATIVE_TRAINER"

    def __init__(self, client: Any = None) -> None:
        self._client = client
        self.audit = BaselinePublisherAudit(redis_connected=client is not None)

    def _existing(self, key: str) -> dict[str, Any] | None:
        if not key.startswith("v2:"):
            raise ValueError(f"non_v2_read_rejected:{key}")
        if self._client is None:
            return None
        try:
            raw = self._client.get(key)
        except Exception:  # noqa: BLE001
            return None
        if raw is None:
            return None
        try:
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8")
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    def should_preserve(self, existing: dict[str, Any] | None) -> bool:
        if not existing:
            return False
        src = str(existing.get("trainer_source") or "").upper()
        if self.PRESERVE_STRONGER_TOKEN in src and src not in {
            "V2_NATIVE_BASELINE_PAPER_SHADOW",
            "V2_NATIVE_CONTRACT_ONLY",
        }:
            return True
        return False

    def publish(self, key: str, payload: dict[str, Any]) -> bool:
        self.audit.writes_attempted += 1
        if not key.startswith("v2:"):
            self.audit.old_redis_write_attempts += 1
            self.audit.writes_failed += 1
            self.audit.errors.append(f"blocked_non_v2_key:{key}")
            return False
        if not is_baseline_prediction_publishable(payload):
            self.audit.writes_failed += 1
            self.audit.errors.append(f"not_publishable:{key}")
            return False
        existing = self._existing(key)
        if self.should_preserve(existing):
            self.audit.writes_failed += 1
            self.audit.errors.append(f"preserved_stronger:{key}")
            return False
        if self._client is None:
            self.audit.writes_failed += 1
            self.audit.errors.append(f"no_client:{key}")
            return False
        try:
            self._client.set(
                key, json.dumps(payload, sort_keys=True, default=str)
            )
        except Exception as exc:  # noqa: BLE001
            self.audit.writes_failed += 1
            self.audit.errors.append(f"{key}:{type(exc).__name__}")
            return False
        self.audit.writes_succeeded += 1
        self.audit.keys_written.append(key)
        return True


def publish_baseline_predictions(
    *,
    rows: Sequence[DatasetRow],
    model: LogisticModel,
    publisher: V2BaselinePublisher,
    timeframes: Iterable[str] = ("1m", "5m"),
) -> dict[str, Any]:
    timeframes_list = list(timeframes)
    published: list[dict[str, Any]] = []
    preserved: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in rows:
        if row.classification not in {ROW_TRAINABLE, ROW_HELD_OUT_VALIDATION}:
            continue
        if row.timeframe not in timeframes_list:
            continue
        payload = build_baseline_prediction(row=row, model=model)
        key = f"v2:prediction:{row.symbol}:{row.timeframe}"
        existing = publisher._existing(key)
        if publisher.should_preserve(existing):
            preserved.append({"symbol": row.symbol, "timeframe": row.timeframe})
            continue
        ok = publisher.publish(key, payload)
        if ok:
            published.append({"symbol": row.symbol, "timeframe": row.timeframe})
        else:
            rejected.append({"symbol": row.symbol, "timeframe": row.timeframe})
    return {
        "published_count": len(published),
        "preserved_count": len(preserved),
        "rejected_count": len(rejected),
        "published_rows_head": published[:32],
        "preserved_rows_head": preserved[:32],
        "rejected_rows_head": rejected[:32],
        "old_redis_write_attempts": publisher.audit.old_redis_write_attempts,
        "writes_succeeded": publisher.audit.writes_succeeded,
        "writes_failed": publisher.audit.writes_failed,
    }


# ---------------------------------------------------------------------------
# Atomic writes + status renderers
# ---------------------------------------------------------------------------


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def render_baseline_status(
    *,
    eval_result: EvaluationResult,
    publisher_result: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_status",
        "generated_at": _utc_now_iso(),
        "evaluation": eval_result.to_jsonable(),
        "publisher": publisher_result,
        "model_readiness": "NOT_PRODUCTION_READY",
        "trainer_native_readiness_claimed": False,
        "v2_native_trainer_ready": False,
        "checkpoint_compatibility_claimed": False,
        "model_parity_claimed": False,
        **_safety_block(),
    }


def render_baseline_metrics(eval_result: EvaluationResult) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_metrics",
        "generated_at": _utc_now_iso(),
        "metrics": [m.to_jsonable() for m in eval_result.metrics],
        "minimum_sample_satisfied": eval_result.minimum_sample_satisfied,
        "minimum_train_rows": eval_result.minimum_train_rows,
        "publishable_baseline_available": (
            eval_result.publishable_baseline_available
        ),
        **_safety_block(),
    }


def render_baseline_report_markdown(
    *,
    eval_result: EvaluationResult,
    publisher_result: dict[str, Any] | None,
) -> str:
    lines = []
    lines.append("# V2 Native Trainer Dataset + Baseline Model Report\n\n")
    lines.append(
        "live_gate=blocked_human_only. live_symbols=[]. approves_live=false."
        " trainer_native_readiness_claimed=false."
        " v2_native_trainer_ready=false."
        " checkpoint_compatibility_claimed=false."
        " model_parity_claimed=false.\n\n"
    )
    lines.append("## Evaluation\n")
    lines.append(f"- train_count: {eval_result.train_count}\n")
    lines.append(f"- validation_count: {eval_result.validation_count}\n")
    lines.append(
        f"- minimum_sample_satisfied: {eval_result.minimum_sample_satisfied}"
        f" (threshold {eval_result.minimum_train_rows})\n"
    )
    lines.append(
        f"- publishable_baseline_available: "
        f"{eval_result.publishable_baseline_available}\n\n"
    )
    lines.append("## Baseline metrics\n")
    for m in eval_result.metrics:
        lines.append(
            f"- {m.name}: "
            f"after_cost_expectancy_bps={m.after_cost_expectancy_bps},"
            f" precision={m.precision},"
            f" false_positive_rate={m.false_positive_rate},"
            f" false_negative_rate={m.false_negative_rate},"
            f" downside_pre_cascade_recall={m.downside_pre_cascade_recall},"
            f" drawdown_bps={m.drawdown_bps},"
            f" action_match_vs_legacy={m.action_match_vs_legacy},"
            f" improvement_vs_hold={m.improvement_vs_hold_baseline},"
            f" improvement_vs_contract_only="
            f"{m.improvement_vs_contract_only_baseline}\n"
        )
    if publisher_result is not None:
        lines.append("\n## Baseline publisher\n")
        for k, v in sorted(publisher_result.items()):
            if k.endswith("_head"):
                continue
            lines.append(f"- {k}: {v}\n")
    lines.append("\n## What this packet did NOT do\n")
    lines.append(
        "- Did not claim V2_NATIVE_TRAINER_READY or V2_NATIVE_TRAINER_ACTIVE.\n"
        "- Did not claim checkpoint compatibility.\n"
        "- Did not claim policy-architecture parity.\n"
        "- Did not register the baseline as production.\n"
        "- Did not weaken the paper-fill gate.\n"
        "- Did not write any non-v2:* Redis key.\n"
        "- Did not call the exchange.\n"
        "- Did not enable production trading or canary.\n"
        "- Did not approve legacy shutdown or Redis trim.\n"
        "- Did not modify legacy or V2 runtime.\n"
        "- Did not load or log any API credential value.\n"
        "- Did not use raw legacy Redis as current truth.\n"
    )
    return "".join(lines)
