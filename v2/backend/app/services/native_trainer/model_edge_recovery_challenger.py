"""Trusted-replay champion/challenger edge recovery.

This lane is intentionally paper-only. It trains a small deterministic
challenger on point-in-time durable feature snapshots, selects a trade
threshold on validation rows, evaluates once on the untouched temporal
holdout, and publishes B-grade paper challenger signals only when the holdout
beats the current champion baseline with positive after-cost expectancy.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from v2.backend.app.services.market_state_integrity.sample_rejection import (
    classify_training_sample,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    content_sha256 as archive_content_sha256,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    default_archive_root,
    iter_snapshots,
)
from v2.backend.app.services.native_trainer.trusted_replay.dataset import (
    FUTURE_LABEL_PREFIXES,
    snapshot_to_final_candle,
)

GOAL_ID = "V2_MODEL_EDGE_RECOVERY_CHAMPION_CHALLENGER_AND_A_GRADE_BOOTSTRAP"
ARTIFACT_REL = Path("operator_runtime/v2_model_edge_recovery/latest")
SCHEMA_VERSION = "v2_model_edge_recovery_champion_challenger_v2"
POLICY_VERSION = "v2_model_edge_recovery_validity_policy_v2"
MODEL_SOURCE = "V2_MODEL_EDGE_RECOVERY_TRUSTED_REPLAY_RIDGE_V2"
PAPER_CHALLENGER_TIER = "B_GRADE_EXPLORATION_PAPER"
LIVE_GATE_BLOCKED = "blocked_human_only"
CHAMPION_CHALLENGER_STATUS_REDIS_KEY = "v2:trainer:champion_challenger_status"
# The Redis/API wrapper shape is unchanged; only the underlying evaluation
# artifact and policy contracts are version-bumped in this repair.
CHAMPION_CHALLENGER_STATUS_SCHEMA_VERSION = "v2_trainer_champion_challenger_status_v1"
CHAMPION_CHALLENGER_STATUS_TTL_SECONDS = 3600

ACTION_SPECIFIC_LABEL_SCHEMA_VERSION = "v2_action_specific_counterfactual_net_label_v1"
ACTION_SPECIFIC_COST_POLICY = (
    "explicit_pit_fee_plus_slippage_plus_abs_funding_both_sides_no_static_fallback"
)
TEMPORAL_SPLIT_POLICY = (
    "decision_time_grouped_duration_70_15_15_with_actual_label_availability_and_4h_embargo_v1"
)
CLUSTERED_BOOTSTRAP_POLICY = (
    "nested_decision_time_then_symbol_cluster_bootstrap_one_sided_95_lcb_v1"
)
FUTURE_HORIZON_SECONDS: dict[str, int] = {
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
}
TARGET_HORIZON = "15m"
MAX_FUTURE_HORIZON_SECONDS = max(FUTURE_HORIZON_SECONDS.values())
MIN_TEMPORAL_EMBARGO_SECONDS = MAX_FUTURE_HORIZON_SECONDS
CLUSTERED_BOOTSTRAP_REPLICATES = 400
CLUSTERED_BOOTSTRAP_LCB_QUANTILE = 0.05

CHAMPION_BASELINE = {
    "directional_accuracy": 0.4137,
    "expected_move_mae_bps": 107.7881,
    "false_positive_rate": 0.5824,
    "after_cost_expectancy_bps": -5.1884,
    "a_grade_promotable_buckets": 0,
    "active_strategy_buckets": 0,
}

DEFAULT_RIDGE_LAMBDAS = (0.1, 1.0, 10.0, 100.0, 1000.0)
DEFAULT_THRESHOLDS_BPS = (0.0, 2.0, 4.0, 6.0, 8.0, 10.0, 15.0, 20.0, 30.0, 50.0)
DEFAULT_MODEL_FEATURE_CAP = 32
DEFAULT_TARGET_CLIP_BPS = 50.0
DEFAULT_MIN_VALIDATION_SUPPLY_TRADES = 300
DEFAULT_MIN_VALIDATION_SUPPLY_COVERAGE = 0.03


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _strict_aware_utc(value: Any) -> datetime | None:
    """Parse only explicit timezone-aware timestamps and normalize to UTC."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def stable_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _stable_result_material(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _stable_result_material(item)
            for key, item in value.items()
            if str(key) not in {"generated_utc", "generated_at"}
        }
    if isinstance(value, list):
        return [_stable_result_material(item) for item in value]
    return value


def _feature_name_allowed(name: str) -> bool:
    lowered = str(name).lower()
    return not lowered.startswith(FUTURE_LABEL_PREFIXES)


def numeric_features_from_snapshot(snapshot: Mapping[str, Any]) -> dict[str, float]:
    raw = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
    out: dict[str, float] = {}
    for name, value in raw.items():
        key = str(name)
        if not _feature_name_allowed(key):
            continue
        parsed = finite_float(value)
        if parsed is not None:
            out[key] = parsed
    return out


@dataclass(frozen=True)
class EdgeRecoveryRow:
    sample_id: str
    snapshot_id: str
    symbol: str
    timeframe: str
    decision_time: str
    feature_cutoff: str
    available_at: str
    label_available_at: str
    raw_future_return_bps: float
    long_net_bps: float
    short_net_bps: float
    hold_net_bps: float
    fee_bps: float
    slippage_bps: float
    funding_bps: float
    total_cost_bps: float
    long_total_cost_bps: float
    short_total_cost_bps: float
    cost_evidence_source: str
    cost_evidence_hash: str
    legacy_static_cost_bps_ignored: float | None
    target_action: str
    features: dict[str, float]

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "snapshot_id": self.snapshot_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "decision_time": self.decision_time,
            "feature_cutoff": self.feature_cutoff,
            "available_at": self.available_at,
            "label_available_at": self.label_available_at,
            "raw_future_return_bps": self.raw_future_return_bps,
            "long_net_bps": self.long_net_bps,
            "short_net_bps": self.short_net_bps,
            "hold_net_bps": self.hold_net_bps,
            "fee_bps": self.fee_bps,
            "slippage_bps": self.slippage_bps,
            "funding_bps": self.funding_bps,
            "total_cost_bps": self.total_cost_bps,
            "long_total_cost_bps": self.long_total_cost_bps,
            "short_total_cost_bps": self.short_total_cost_bps,
            "cost_evidence_source": self.cost_evidence_source,
            "cost_evidence_hash": self.cost_evidence_hash,
            "legacy_static_cost_bps_ignored": self.legacy_static_cost_bps_ignored,
            "target_action": self.target_action,
            "feature_count": len(self.features),
            "label_schema_version": ACTION_SPECIFIC_LABEL_SCHEMA_VERSION,
        }


@dataclass(frozen=True)
class DatasetFreeze:
    rows: list[EdgeRecoveryRow]
    manifest: dict[str, Any]
    rejections_by_reason: dict[str, int]


@dataclass(frozen=True)
class ChallengerModel:
    feature_names: list[str]
    means: list[float]
    stds: list[float]
    weights: list[float]
    bias: float
    ridge_lambda: float
    threshold_bps: float
    validation_metrics: dict[str, Any]
    target_transform: str = "raw_future_return_bps_action_specific_net_evaluation"
    target_clip_bps: float | None = None
    feature_count_limit: int | None = None
    feature_set_hash: str | None = None
    hyperparameter_grid_hash: str | None = None

    def predict(self, features: Mapping[str, Any]) -> float:
        total = self.bias
        for name, mean, std, weight in zip(
            self.feature_names, self.means, self.stds, self.weights, strict=False
        ):
            value = finite_float(features.get(name)) or 0.0
            total += ((value - mean) / (std if std > 1e-12 else 1.0)) * weight
        return float(total)

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "model_source": MODEL_SOURCE,
            "feature_names": self.feature_names,
            "means": self.means,
            "stds": self.stds,
            "weights": self.weights,
            "bias": self.bias,
            "ridge_lambda": self.ridge_lambda,
            "threshold_bps": self.threshold_bps,
            "validation_metrics": self.validation_metrics,
            "target_transform": self.target_transform,
            "target_clip_bps": self.target_clip_bps,
            "feature_count_limit": self.feature_count_limit,
            "feature_set_hash": self.feature_set_hash,
            "hyperparameter_grid_hash": self.hyperparameter_grid_hash,
            "selection_policy": {
                "features_selected_from_training_only": True,
                "normalization_fitted_on_training_only": True,
                "hyperparameters_selected_on_validation_only": True,
                "holdout_used_for_feature_or_hyperparameter_selection": False,
            },
        }


def _row_reject_reasons(snapshot: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    features = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
    if not features:
        reasons.append("FEATURES_EMPTY")
    if any(str(name).lower().startswith(FUTURE_LABEL_PREFIXES) for name in features):
        reasons.append("FUTURE_LABEL_PRESENT_IN_FEATURES")
    decision_time = _strict_aware_utc(snapshot.get("decision_time"))
    feature_cutoff = _strict_aware_utc(snapshot.get("feature_cutoff"))
    available_at = _strict_aware_utc(snapshot.get("available_at"))
    if decision_time is None:
        reasons.append("DECISION_TIME_MISSING_INVALID_OR_NAIVE")
    if feature_cutoff is None:
        reasons.append("FEATURE_CUTOFF_MISSING_INVALID_OR_NAIVE")
    if available_at is None:
        reasons.append("AVAILABLE_AT_MISSING_INVALID_OR_NAIVE")
    if feature_cutoff is not None and available_at is not None and feature_cutoff > available_at:
        reasons.append("FEATURE_CUTOFF_AFTER_AVAILABLE_AT")
    if available_at is not None and decision_time is not None and available_at > decision_time:
        reasons.append("AVAILABLE_AT_AFTER_DECISION_TIME")
    if feature_cutoff is not None and decision_time is not None and feature_cutoff > decision_time:
        reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    if snapshot.get("candle_closed_confirmed") is not True:
        reasons.append("OPEN_CANDLE_REJECTED")
    if snapshot.get("latest_unclosed_kline_excluded") is not True:
        reasons.append("LATEST_UNCLOSED_KLINE_EXCLUSION_UNPROVEN")
    if snapshot.get("mtf_snapshot_id") in (None, ""):
        reasons.append("MTF_SNAPSHOT_ID_MISSING")
    expected_hash = snapshot.get("content_sha256")
    if not isinstance(expected_hash, str) or not expected_hash:
        reasons.append("CONTENT_SHA256_MISSING")
    else:
        try:
            if archive_content_sha256(snapshot) != expected_hash:
                reasons.append("CONTENT_SHA256_MISMATCH")
        except (TypeError, ValueError):
            reasons.append("CONTENT_SHA256_UNVERIFIABLE")
    return sorted(set(reasons))


def _explicit_cost_evidence(
    snapshot: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Resolve only explicit PIT cost components; static flat fallbacks are diagnostic."""

    features = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}

    def resolve(field: str) -> tuple[float | None, str | None]:
        for payload, prefix in ((features, "features"), (snapshot, "snapshot")):
            if field not in payload:
                continue
            value = finite_float(payload.get(field))
            return value, f"{prefix}.{field}"
        return None, None

    fee_bps, fee_source = resolve("fee_bps")
    slippage_bps, slippage_source = resolve("expected_slippage_bps")
    funding_bps, funding_source = resolve("expected_funding_bps")
    reasons: list[str] = []
    if fee_bps is None:
        reasons.append("ACTION_SPECIFIC_FEE_EVIDENCE_MISSING_OR_INVALID")
    elif fee_bps < 0.0:
        reasons.append("ACTION_SPECIFIC_FEE_EVIDENCE_NEGATIVE")
    if slippage_bps is None:
        reasons.append("ACTION_SPECIFIC_SLIPPAGE_EVIDENCE_MISSING_OR_INVALID")
    elif slippage_bps < 0.0:
        reasons.append("ACTION_SPECIFIC_SLIPPAGE_EVIDENCE_NEGATIVE")
    if funding_bps is None:
        reasons.append("ACTION_SPECIFIC_FUNDING_EVIDENCE_MISSING_OR_INVALID")
    if reasons:
        return None, sorted(set(reasons))

    assert fee_bps is not None and slippage_bps is not None and funding_bps is not None
    sources = [str(fee_source), str(slippage_source), str(funding_source)]
    total_cost_bps = fee_bps + slippage_bps + abs(funding_bps)
    legacy_static_cost = None
    for payload in (features, snapshot):
        for field in ("round_trip_cost_bps", "cost_bps"):
            if field in payload:
                legacy_static_cost = finite_float(payload.get(field))
                break
        if legacy_static_cost is not None:
            break
    material = {
        "policy_version": ACTION_SPECIFIC_COST_POLICY,
        "snapshot_content_sha256": snapshot.get("content_sha256"),
        "feature_cutoff": snapshot.get("feature_cutoff"),
        "available_at": snapshot.get("available_at"),
        "decision_time": snapshot.get("decision_time"),
        "fee_bps": fee_bps,
        "slippage_bps": slippage_bps,
        "funding_bps": funding_bps,
        "total_cost_bps": total_cost_bps,
        "sources": sources,
    }
    return {
        "fee_bps": float(fee_bps),
        "slippage_bps": float(slippage_bps),
        "funding_bps": float(funding_bps),
        "total_cost_bps": float(total_cost_bps),
        "cost_evidence_source": "+".join(sources),
        "cost_evidence_hash": stable_hash(material),
        "legacy_static_cost_bps_ignored": legacy_static_cost,
        "legacy_static_cost_was_under_explicit_total": bool(
            legacy_static_cost is not None and legacy_static_cost < total_cost_bps
        ),
    }, []


def _future_label_evidence(
    snapshot: Mapping[str, Any],
    *,
    candles: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, list[str]]:
    decision_time = _strict_aware_utc(snapshot.get("decision_time"))
    if decision_time is None:
        return None, ["DECISION_TIME_MISSING_INVALID_OR_NAIVE"]
    features = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
    entry_price = None
    for field in ("close", "last_price", "price_last", "ohlcv_close"):
        candidate = finite_float(features.get(field))
        if candidate is not None and candidate > 0.0:
            entry_price = candidate
            break
    if entry_price is None:
        return None, ["ENTRY_PRICE_MISSING"]

    selected: dict[str, Mapping[str, Any]] = {}
    for horizon, seconds in FUTURE_HORIZON_SECONDS.items():
        target_time = decision_time + timedelta(seconds=seconds)
        for candle in candles:
            close_time = _strict_aware_utc(candle.get("candle_close_time"))
            available_at = _strict_aware_utc(candle.get("available_at"))
            if (
                close_time is not None
                and available_at is not None
                and close_time >= target_time
                and available_at >= close_time
                and candle.get("candle_closed_confirmed") is True
            ):
                selected[horizon] = candle
                break
    missing = [
        f"FUTURE_CANDLE_HORIZON_MISSING_{horizon.upper()}"
        for horizon in FUTURE_HORIZON_SECONDS
        if horizon not in selected
    ]
    if missing:
        return None, missing
    target_candle = selected[TARGET_HORIZON]
    target_close = finite_float(target_candle.get("close"))
    if target_close is None or target_close <= 0.0:
        return None, ["TARGET_HORIZON_CLOSE_PRICE_MISSING"]
    label_times = [_strict_aware_utc(candle.get("available_at")) for candle in selected.values()]
    if any(value is None for value in label_times):
        return None, ["FUTURE_LABEL_AVAILABLE_AT_MISSING_INVALID_OR_NAIVE"]
    label_available_at = max(value for value in label_times if value is not None)
    raw_return_bps = ((target_close - entry_price) / entry_price) * 10_000.0
    return {
        "raw_future_return_bps": float(raw_return_bps),
        "label_available_at": _utc_iso(label_available_at),
        "max_future_horizon_seconds_consumed": MAX_FUTURE_HORIZON_SECONDS,
        "future_horizon_available_at": {
            horizon: _utc_iso(_strict_aware_utc(candle.get("available_at")) or label_available_at)
            for horizon, candle in selected.items()
        },
    }, []


def freeze_dataset_from_archive(
    *,
    archive_root: Path,
    scan_limit: int = 60_000,
    replay_limit: int = 30_000,
) -> DatasetFreeze:
    snapshots = list(iter_snapshots(archive_root, limit=scan_limit))
    archive_candles: dict[tuple[str, str], list[dict[str, Any]]] = {}
    rejections: Counter[str] = Counter()
    pit_eligible_snapshots: list[Mapping[str, Any]] = []
    for snapshot in snapshots:
        reasons = _row_reject_reasons(snapshot)
        if reasons:
            rejections.update(reasons)
            continue
        candle, reasons = snapshot_to_final_candle(snapshot)
        if candle is None:
            rejections.update(reasons)
            continue
        pit_eligible_snapshots.append(snapshot)
        pair = (str(candle.get("symbol") or "").upper(), str(candle.get("timeframe") or ""))
        archive_candles.setdefault(pair, []).append(candle)
    for rows in archive_candles.values():
        rows.sort(key=lambda row: str(row.get("candle_close_time") or ""))

    out: list[EdgeRecoveryRow] = []
    missing_cost_snapshot_count = 0
    explicit_cost_snapshot_count = 0
    legacy_static_cost_ignored_count = 0
    legacy_static_cost_underestimated_count = 0
    for snapshot in pit_eligible_snapshots:
        cost_evidence, cost_reasons = _explicit_cost_evidence(snapshot)
        if cost_evidence is None:
            missing_cost_snapshot_count += 1
            rejections.update(cost_reasons)
            continue
        explicit_cost_snapshot_count += 1
        if cost_evidence.get("legacy_static_cost_bps_ignored") is not None:
            legacy_static_cost_ignored_count += 1
        if cost_evidence.get("legacy_static_cost_was_under_explicit_total") is True:
            legacy_static_cost_underestimated_count += 1
        pair = (str(snapshot.get("symbol") or "").upper(), str(snapshot.get("timeframe") or ""))
        label_evidence, label_reasons = _future_label_evidence(
            snapshot,
            candles=archive_candles.get(pair) or [],
        )
        if label_evidence is None:
            rejections.update(label_reasons)
            continue
        features = numeric_features_from_snapshot(snapshot)
        if not features:
            rejections.update(["NO_NUMERIC_FEATURES"])
            continue
        raw_return_bps = float(label_evidence["raw_future_return_bps"])
        total_cost_bps = float(cost_evidence["total_cost_bps"])
        long_net_bps = raw_return_bps - total_cost_bps
        short_net_bps = -raw_return_bps - total_cost_bps
        target_action = (
            "long"
            if long_net_bps > max(0.0, short_net_bps)
            else "short"
            if short_net_bps > max(0.0, long_net_bps)
            else "hold"
        )
        snapshot_id = str(snapshot.get("snapshot_id") or snapshot.get("feature_snapshot_id") or "")
        decision_time = _strict_aware_utc(snapshot.get("decision_time"))
        feature_cutoff = _strict_aware_utc(snapshot.get("feature_cutoff"))
        available_at = _strict_aware_utc(snapshot.get("available_at"))
        if decision_time is None or feature_cutoff is None or available_at is None:
            # Defensive fail-closed assertion at the materialization boundary;
            # _row_reject_reasons already rejects these before this point.
            rejections.update(["CLOCK_BECAME_INVALID_DURING_MATERIALIZATION"])
            continue
        out.append(
            EdgeRecoveryRow(
                sample_id=f"edge_recovery_v2:{snapshot_id}",
                snapshot_id=snapshot_id,
                symbol=str(snapshot.get("symbol") or "").upper(),
                timeframe=str(snapshot.get("timeframe") or ""),
                decision_time=_utc_iso(decision_time),
                feature_cutoff=_utc_iso(feature_cutoff),
                available_at=_utc_iso(available_at),
                label_available_at=str(label_evidence["label_available_at"]),
                raw_future_return_bps=raw_return_bps,
                long_net_bps=float(long_net_bps),
                short_net_bps=float(short_net_bps),
                hold_net_bps=0.0,
                fee_bps=float(cost_evidence["fee_bps"]),
                slippage_bps=float(cost_evidence["slippage_bps"]),
                funding_bps=float(cost_evidence["funding_bps"]),
                total_cost_bps=total_cost_bps,
                long_total_cost_bps=total_cost_bps,
                short_total_cost_bps=total_cost_bps,
                cost_evidence_source=str(cost_evidence["cost_evidence_source"]),
                cost_evidence_hash=str(cost_evidence["cost_evidence_hash"]),
                legacy_static_cost_bps_ignored=finite_float(
                    cost_evidence.get("legacy_static_cost_bps_ignored")
                ),
                target_action=target_action,
                features=features,
            )
        )
        if replay_limit and len(out) >= int(replay_limit):
            break

    out.sort(key=lambda row: (row.decision_time, row.sample_id))
    manifest = build_split_manifest(out)
    cost_sources = Counter(row.cost_evidence_source for row in out)
    total_costs = [row.total_cost_bps for row in out]
    manifest.update(
        {
            "schema_version": SCHEMA_VERSION + "_dataset_freeze",
            "generated_utc": utc_now(),
            "archive_root": str(archive_root),
            "snapshots_scanned": len(snapshots),
            "pit_hash_finality_admitted_snapshots": len(pit_eligible_snapshots),
            "trusted_replay_rows": len(out),
            "replay_limit": int(replay_limit),
            "scan_limit": int(scan_limit),
            "future_labels_used_as_features": False,
            "policy_version": POLICY_VERSION,
            "label_schema_version": ACTION_SPECIFIC_LABEL_SCHEMA_VERSION,
            "action_specific_cost_policy": ACTION_SPECIFIC_COST_POLICY,
            "max_future_horizon_seconds_consumed": MAX_FUTURE_HORIZON_SECONDS,
            "explicit_cost_snapshot_count": explicit_cost_snapshot_count,
            "missing_cost_snapshot_count": missing_cost_snapshot_count,
            "action_specific_cost_coverage_complete": missing_cost_snapshot_count == 0,
            "legacy_static_cost_ignored_count": legacy_static_cost_ignored_count,
            "legacy_static_cost_underestimated_count": legacy_static_cost_underestimated_count,
            "cost_source_distribution": dict(sorted(cost_sources.items())),
            "total_cost_bps_distribution": {
                "count": len(total_costs),
                "min": min(total_costs) if total_costs else None,
                "max": max(total_costs) if total_costs else None,
                "mean": (sum(total_costs) / len(total_costs)) if total_costs else None,
            },
            "paper_only": True,
            "routes_to_live": False,
        }
    )
    return DatasetFreeze(
        rows=out, manifest=manifest, rejections_by_reason=dict(sorted(rejections.items()))
    )


def _split_window(rows: Sequence[EdgeRecoveryRow]) -> dict[str, Any]:
    decision_times = [
        value for row in rows if (value := _strict_aware_utc(row.decision_time)) is not None
    ]
    label_times = [
        value for row in rows if (value := _strict_aware_utc(row.label_available_at)) is not None
    ]
    return {
        "rows": len(rows),
        "decision_time_groups": len({row.decision_time for row in rows}),
        "start_decision_time": _utc_iso(min(decision_times)) if decision_times else None,
        "end_decision_time": _utc_iso(max(decision_times)) if decision_times else None,
        "label_available_at_max": _utc_iso(max(label_times)) if label_times else None,
    }


def _split_rows(
    rows: Sequence[EdgeRecoveryRow],
) -> tuple[list[EdgeRecoveryRow], list[EdgeRecoveryRow], list[EdgeRecoveryRow], dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: (row.decision_time, row.sample_id))
    reasons: list[str] = []
    parsed_rows: list[tuple[datetime, EdgeRecoveryRow]] = []
    for row in ordered:
        decision_time = _strict_aware_utc(row.decision_time)
        label_available_at = _strict_aware_utc(row.label_available_at)
        if decision_time is None:
            reasons.append("SPLIT_DECISION_TIME_MISSING_INVALID_OR_NAIVE")
            continue
        if label_available_at is None or label_available_at <= decision_time:
            reasons.append("SPLIT_LABEL_AVAILABLE_AT_MISSING_INVALID_OR_NOT_AFTER_DECISION")
            continue
        if label_available_at < decision_time + timedelta(seconds=MAX_FUTURE_HORIZON_SECONDS):
            reasons.append("SPLIT_LABEL_AVAILABLE_BEFORE_MAX_FUTURE_HORIZON")
            continue
        parsed_rows.append((decision_time, row))

    unique_times = sorted({item[0] for item in parsed_rows})
    if len(parsed_rows) != len(ordered):
        parsed_rows = []
    if len(unique_times) < 3:
        reasons.append("INSUFFICIENT_DISTINCT_DECISION_TIME_GROUPS")

    nominal_train: list[EdgeRecoveryRow] = []
    nominal_validation: list[EdgeRecoveryRow] = []
    nominal_holdout: list[EdgeRecoveryRow] = []
    validation_start: datetime | None = None
    holdout_start: datetime | None = None
    if parsed_rows and len(unique_times) >= 3:
        start, end = unique_times[0], unique_times[-1]
        span = end - start
        if span.total_seconds() <= 2 * MIN_TEMPORAL_EMBARGO_SECONDS:
            reasons.append("DECISION_TIME_SPAN_INSUFFICIENT_FOR_TWO_4H_BOUNDARIES")
        validation_target = start + span * 0.70
        holdout_target = start + span * 0.85
        validation_start = next(
            (value for value in unique_times if value >= validation_target), None
        )
        holdout_start = next((value for value in unique_times if value >= holdout_target), None)
        if validation_start is None or holdout_start is None or validation_start >= holdout_start:
            reasons.append("DISTINCT_DURATION_BASED_SPLIT_BOUNDARIES_UNAVAILABLE")
        else:
            for decision_time, row in parsed_rows:
                if decision_time < validation_start:
                    nominal_train.append(row)
                elif decision_time < holdout_start:
                    nominal_validation.append(row)
                else:
                    nominal_holdout.append(row)

    def purged_before(
        candidates: Sequence[EdgeRecoveryRow], boundary: datetime | None
    ) -> tuple[list[EdgeRecoveryRow], int]:
        if boundary is None:
            return [], len(candidates)
        kept: list[EdgeRecoveryRow] = []
        for row in candidates:
            decision_time = _strict_aware_utc(row.decision_time)
            label_available_at = _strict_aware_utc(row.label_available_at)
            if (
                decision_time is not None
                and label_available_at is not None
                and decision_time + timedelta(seconds=MIN_TEMPORAL_EMBARGO_SECONDS) < boundary
                and label_available_at < boundary
            ):
                kept.append(row)
        return kept, len(candidates) - len(kept)

    training, train_purged = purged_before(nominal_train, validation_start)
    validation, validation_purged = purged_before(nominal_validation, holdout_start)
    holdout = list(nominal_holdout)
    if not training:
        reasons.append("TRAINING_ROWS_MISSING_AFTER_4H_PURGE")
    if not validation:
        reasons.append("VALIDATION_ROWS_MISSING_AFTER_4H_PURGE")
    if not holdout:
        reasons.append("HOLDOUT_ROWS_MISSING")

    group_sets = [{row.decision_time for row in part} for part in (training, validation, holdout)]
    repeated_group_overlap = bool(
        group_sets[0] & group_sets[1]
        or group_sets[0] & group_sets[2]
        or group_sets[1] & group_sets[2]
    )
    if repeated_group_overlap:
        reasons.append("DECISION_TIME_GROUP_SPLIT_ACROSS_PARTITIONS")

    def separation_seconds(
        earlier: Sequence[EdgeRecoveryRow], later: Sequence[EdgeRecoveryRow]
    ) -> float | None:
        earlier_times = [
            value for row in earlier if (value := _strict_aware_utc(row.decision_time)) is not None
        ]
        later_times = [
            value for row in later if (value := _strict_aware_utc(row.decision_time)) is not None
        ]
        if not earlier_times or not later_times:
            return None
        return (min(later_times) - max(earlier_times)).total_seconds()

    train_validation_gap = separation_seconds(training, validation)
    validation_holdout_gap = separation_seconds(validation, holdout)
    if train_validation_gap is not None and train_validation_gap <= MIN_TEMPORAL_EMBARGO_SECONDS:
        reasons.append("TRAIN_VALIDATION_EMBARGO_SHORTER_THAN_4H")
    if (
        validation_holdout_gap is not None
        and validation_holdout_gap <= MIN_TEMPORAL_EMBARGO_SECONDS
    ):
        reasons.append("VALIDATION_HOLDOUT_EMBARGO_SHORTER_THAN_4H")

    manifest = {
        "split_method": TEMPORAL_SPLIT_POLICY,
        "split_by_decision_time_group_not_row": True,
        "duration_based_boundaries": True,
        "temporal_overlap": repeated_group_overlap,
        "label_overlap": False if not reasons else None,
        "split_pit_safe": not reasons,
        "split_blocker_reasons": sorted(set(reasons)),
        "max_future_horizon_seconds_consumed": MAX_FUTURE_HORIZON_SECONDS,
        "purge_embargo_seconds": MIN_TEMPORAL_EMBARGO_SECONDS,
        "unique_decision_time_groups": len(unique_times),
        "nominal_training_rows": len(nominal_train),
        "nominal_validation_rows": len(nominal_validation),
        "nominal_holdout_rows": len(nominal_holdout),
        "training_rows_purged": train_purged,
        "validation_rows_purged": validation_purged,
        "train_validation_decision_gap_seconds": train_validation_gap,
        "validation_holdout_decision_gap_seconds": validation_holdout_gap,
        "validation_boundary_decision_time": _utc_iso(validation_start)
        if validation_start
        else None,
        "holdout_boundary_decision_time": _utc_iso(holdout_start) if holdout_start else None,
        "training_window": _split_window(training),
        "validation_window": _split_window(validation),
        "holdout_window": _split_window(holdout),
    }
    return training, validation, holdout, manifest


def build_split_manifest(rows: Sequence[EdgeRecoveryRow]) -> dict[str, Any]:
    return _split_rows(rows)[3]


def select_feature_names(rows: Sequence[EdgeRecoveryRow], *, max_features: int = 256) -> list[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(row.features.keys())
    return [
        name
        for name, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if _feature_name_allowed(name)
    ][:max_features]


def _matrix(rows: Sequence[EdgeRecoveryRow], feature_names: Sequence[str]):
    import numpy as np

    return np.array(
        [[float(row.features.get(name, 0.0)) for name in feature_names] for row in rows],
        dtype=float,
    )


def _targets(rows: Sequence[EdgeRecoveryRow]):
    import numpy as np

    # The Ridge head predicts the raw forward move.  Trading evaluation must use
    # the separate long/short/hold net labels below; a single signed net label
    # cannot be inverted because costs do not change sign with the action.
    return np.array([float(row.raw_future_return_bps) for row in rows], dtype=float)


def _actions_from_predictions(predictions: Any, threshold_bps: float):
    import numpy as np

    threshold = float(threshold_bps)
    return np.where(predictions >= threshold, 1, np.where(predictions <= -threshold, -1, 0))


def _row_label_contract_reasons(row: EdgeRecoveryRow) -> list[str]:
    reasons: list[str] = []
    decision_time = _strict_aware_utc(row.decision_time)
    feature_cutoff = _strict_aware_utc(row.feature_cutoff)
    available_at = _strict_aware_utc(row.available_at)
    label_available_at = _strict_aware_utc(row.label_available_at)
    if decision_time is None:
        reasons.append("ROW_DECISION_TIME_MISSING_INVALID_OR_NAIVE")
    if feature_cutoff is None:
        reasons.append("ROW_FEATURE_CUTOFF_MISSING_INVALID_OR_NAIVE")
    if available_at is None:
        reasons.append("ROW_AVAILABLE_AT_MISSING_INVALID_OR_NAIVE")
    if label_available_at is None:
        reasons.append("ROW_LABEL_AVAILABLE_AT_MISSING_INVALID_OR_NAIVE")
    if feature_cutoff is not None and available_at is not None and feature_cutoff > available_at:
        reasons.append("ROW_FEATURE_CUTOFF_AFTER_AVAILABLE_AT")
    if available_at is not None and decision_time is not None and available_at > decision_time:
        reasons.append("ROW_AVAILABLE_AT_AFTER_DECISION_TIME")
    if feature_cutoff is not None and decision_time is not None and feature_cutoff > decision_time:
        reasons.append("ROW_FEATURE_CUTOFF_AFTER_DECISION_TIME")
    if (
        label_available_at is not None
        and decision_time is not None
        and label_available_at <= decision_time
    ):
        reasons.append("ROW_LABEL_NOT_STRICTLY_FORWARD")
    if (
        label_available_at is not None
        and decision_time is not None
        and label_available_at < decision_time + timedelta(seconds=MAX_FUTURE_HORIZON_SECONDS)
    ):
        reasons.append("ROW_LABEL_AVAILABLE_BEFORE_MAX_FUTURE_HORIZON")

    numeric_fields = {
        "RAW_FUTURE_RETURN": finite_float(row.raw_future_return_bps),
        "LONG_NET": finite_float(row.long_net_bps),
        "SHORT_NET": finite_float(row.short_net_bps),
        "HOLD_NET": finite_float(row.hold_net_bps),
        "FEE": finite_float(row.fee_bps),
        "SLIPPAGE": finite_float(row.slippage_bps),
        "FUNDING": finite_float(row.funding_bps),
        "TOTAL_COST": finite_float(row.total_cost_bps),
    }
    for name, value in numeric_fields.items():
        if value is None:
            reasons.append(f"ROW_{name}_MISSING_OR_NONFINITE")
    fee = numeric_fields["FEE"]
    slippage = numeric_fields["SLIPPAGE"]
    funding = numeric_fields["FUNDING"]
    total_cost = numeric_fields["TOTAL_COST"]
    raw_return = numeric_fields["RAW_FUTURE_RETURN"]
    if fee is not None and fee < 0.0:
        reasons.append("ROW_FEE_NEGATIVE")
    if slippage is not None and slippage < 0.0:
        reasons.append("ROW_SLIPPAGE_NEGATIVE")
    if total_cost is not None and total_cost < 0.0:
        reasons.append("ROW_TOTAL_COST_NEGATIVE")
    long_total_cost = finite_float(row.long_total_cost_bps)
    short_total_cost = finite_float(row.short_total_cost_bps)
    if long_total_cost is None:
        reasons.append("ROW_LONG_TOTAL_COST_MISSING_OR_NONFINITE")
    elif long_total_cost < 0.0:
        reasons.append("ROW_LONG_TOTAL_COST_NEGATIVE")
    if short_total_cost is None:
        reasons.append("ROW_SHORT_TOTAL_COST_MISSING_OR_NONFINITE")
    elif short_total_cost < 0.0:
        reasons.append("ROW_SHORT_TOTAL_COST_NEGATIVE")
    tolerance = 1e-8
    if None not in (
        fee,
        slippage,
        funding,
        total_cost,
        long_total_cost,
        short_total_cost,
    ):
        assert fee is not None and slippage is not None and funding is not None
        assert total_cost is not None
        assert long_total_cost is not None and short_total_cost is not None
        if not math.isclose(
            total_cost,
            max(long_total_cost, short_total_cost),
            rel_tol=0.0,
            abs_tol=tolerance,
        ):
            reasons.append("ROW_TOTAL_COST_CONSERVATIVE_DIRECTIONAL_MISMATCH")
        if (
            math.isclose(
                long_total_cost,
                short_total_cost,
                rel_tol=0.0,
                abs_tol=tolerance,
            )
            and not math.isclose(
                total_cost,
                fee + slippage + abs(funding),
                rel_tol=0.0,
                abs_tol=tolerance,
            )
        ):
            reasons.append("ROW_TOTAL_COST_COMPONENT_MISMATCH")
    if raw_return is not None and None not in (long_total_cost, short_total_cost):
        long_net = numeric_fields["LONG_NET"]
        short_net = numeric_fields["SHORT_NET"]
        hold_net = numeric_fields["HOLD_NET"]
        assert long_total_cost is not None and short_total_cost is not None
        if long_net is not None and not math.isclose(
            long_net, raw_return - long_total_cost, rel_tol=0.0, abs_tol=tolerance
        ):
            reasons.append("ROW_LONG_NET_LABEL_MISMATCH")
        if short_net is not None and not math.isclose(
            short_net, -raw_return - short_total_cost, rel_tol=0.0, abs_tol=tolerance
        ):
            reasons.append("ROW_SHORT_NET_LABEL_MISMATCH")
        if hold_net is not None and not math.isclose(
            hold_net,
            0.0,
            rel_tol=0.0,
            abs_tol=tolerance,
        ):
            reasons.append("ROW_HOLD_NET_LABEL_NOT_ZERO")
    if not str(row.cost_evidence_source or "").strip():
        reasons.append("ROW_COST_EVIDENCE_SOURCE_MISSING")
    if not str(row.cost_evidence_hash or "").strip():
        reasons.append("ROW_COST_EVIDENCE_HASH_MISSING")
    return sorted(set(reasons))


def _bucket_trade_metrics(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    pnl = [float(record["pnl_bps"]) for record in records]
    wins = sum(value > 0.0 for value in pnl)
    losses = sum(value <= 0.0 for value in pnl)
    return {
        "trade_count": len(pnl),
        "true_positive_count": wins,
        "false_positive_count": losses,
        "directional_accuracy": wins / len(pnl) if pnl else None,
        "false_positive_rate": losses / len(pnl) if pnl else None,
        "after_cost_expectancy_bps": sum(pnl) / len(pnl) if pnl else None,
    }


def _clustered_expectancy_lcb(
    records: Sequence[Mapping[str, Any]],
    *,
    seed_material: Mapping[str, Any],
) -> dict[str, Any]:
    decision_times = sorted({str(record["decision_time"]) for record in records})
    symbols = sorted({str(record["symbol"]) for record in records})
    symbol_sets_by_time = {
        decision_time: {
            str(record["symbol"])
            for record in records
            if str(record["decision_time"]) == decision_time
        }
        for decision_time in decision_times
    }
    multi_symbol_decision_time_clusters = sum(
        len(symbol_set) >= 2 for symbol_set in symbol_sets_by_time.values()
    )
    base = {
        "clustered_bootstrap_policy": CLUSTERED_BOOTSTRAP_POLICY,
        "clustered_bootstrap_replicates": CLUSTERED_BOOTSTRAP_REPLICATES,
        "clustered_bootstrap_lcb_quantile": CLUSTERED_BOOTSTRAP_LCB_QUANTILE,
        "decision_time_cluster_count": len(decision_times),
        "symbol_cluster_count": len(symbols),
        "multi_symbol_decision_time_cluster_count": multi_symbol_decision_time_clusters,
        "after_cost_expectancy_clustered_lcb_bps": None,
    }
    if not records:
        return {**base, "clustered_bootstrap_status": "BLOCKED_NO_TRADES"}
    if len(decision_times) < 2:
        return {
            **base,
            "clustered_bootstrap_status": "BLOCKED_INSUFFICIENT_DECISION_TIME_CLUSTERS",
        }
    if len(symbols) < 2:
        return {
            **base,
            "clustered_bootstrap_status": "BLOCKED_INSUFFICIENT_SYMBOL_CLUSTERS",
        }
    if multi_symbol_decision_time_clusters < 2:
        return {
            **base,
            "clustered_bootstrap_status": "BLOCKED_INSUFFICIENT_NESTED_TIME_SYMBOL_CLUSTERS",
        }

    by_time_symbol: dict[tuple[str, str], list[float]] = {}
    symbols_by_time: dict[str, list[str]] = {}
    for record in records:
        decision_time = str(record["decision_time"])
        symbol = str(record["symbol"])
        by_time_symbol.setdefault((decision_time, symbol), []).append(float(record["pnl_bps"]))
    for decision_time in decision_times:
        symbols_by_time[decision_time] = sorted(
            symbol for symbol in symbols if (decision_time, symbol) in by_time_symbol
        )

    seed = int(stable_hash(seed_material)[:16], 16)
    # A fixed non-cryptographic PRNG is intentional: the statistical artifact
    # must be reproducible from its stamped seed material.
    rng = random.Random(seed)  # noqa: S311
    means: list[float] = []
    for _ in range(CLUSTERED_BOOTSTRAP_REPLICATES):
        sampled_pnl: list[float] = []
        for _time_index in decision_times:
            sampled_time = rng.choice(decision_times)
            available_symbols = symbols_by_time[sampled_time]
            for _symbol_index in available_symbols:
                sampled_symbol = rng.choice(available_symbols)
                sampled_pnl.extend(by_time_symbol[(sampled_time, sampled_symbol)])
        if sampled_pnl:
            means.append(sum(sampled_pnl) / len(sampled_pnl))
    if len(means) != CLUSTERED_BOOTSTRAP_REPLICATES:
        return {**base, "clustered_bootstrap_status": "BLOCKED_BOOTSTRAP_INCOMPLETE"}
    ordered_means = sorted(means)
    lcb_index = max(
        0,
        min(
            len(ordered_means) - 1,
            int(math.floor(CLUSTERED_BOOTSTRAP_LCB_QUANTILE * (len(ordered_means) - 1))),
        ),
    )
    return {
        **base,
        "clustered_bootstrap_status": "PASS",
        "clustered_bootstrap_seed_sha256": stable_hash(seed_material),
        "after_cost_expectancy_clustered_lcb_bps": float(ordered_means[lcb_index]),
    }


def evaluate_predictions(
    *,
    rows: Sequence[EdgeRecoveryRow],
    predictions: Sequence[float],
    threshold_bps: float,
    include_uncertainty: bool = True,
) -> dict[str, Any]:
    import numpy as np

    pred = np.array(list(predictions), dtype=float)
    contract_reasons = Counter(
        reason for row in rows for reason in _row_label_contract_reasons(row)
    )
    evaluation_blockers: list[str] = []
    if len(pred) != len(rows):
        evaluation_blockers.append("PREDICTION_ROW_COUNT_MISMATCH")
    if pred.ndim != 1:
        evaluation_blockers.append("PREDICTION_SHAPE_NOT_ONE_DIMENSIONAL")
    if len(pred) and not bool(np.isfinite(pred).all()):
        evaluation_blockers.append("PREDICTION_NONFINITE")
    threshold = finite_float(threshold_bps)
    if threshold is None or threshold < 0.0:
        evaluation_blockers.append("THRESHOLD_MISSING_NONFINITE_OR_NEGATIVE")
    if contract_reasons:
        evaluation_blockers.append("ACTION_SPECIFIC_ROW_CONTRACT_INVALID")
    if evaluation_blockers:
        return {
            "sample_count": len(rows),
            "prediction_count": len(pred),
            "trade_count": 0,
            "hold_count": 0,
            "long_count": 0,
            "short_count": 0,
            "coverage": 0.0,
            "directional_accuracy": None,
            "false_positive_rate": None,
            "after_cost_expectancy_bps": None,
            "after_cost_expectancy_clustered_lcb_bps": None,
            "expected_move_mae_bps": None,
            "true_positive_count": 0,
            "false_positive_count": 0,
            "expectancy_scope": "explicit_action_specific_net_labels_only",
            "label_schema_version": ACTION_SPECIFIC_LABEL_SCHEMA_VERSION,
            "action_specific_cost_policy": ACTION_SPECIFIC_COST_POLICY,
            "evaluation_blocker_reasons": sorted(set(evaluation_blockers)),
            "row_contract_rejections_by_reason": dict(sorted(contract_reasons.items())),
            "edge_evidence_valid": False,
            "edge_claim_allowed": False,
        }
    y = _targets(rows)
    actions = _actions_from_predictions(pred, threshold_bps)
    pnl = np.array(
        [
            row.long_net_bps
            if action == 1
            else row.short_net_bps
            if action == -1
            else row.hold_net_bps
            for row, action in zip(rows, actions, strict=True)
        ],
        dtype=float,
    )
    trade_mask = actions != 0
    trade_count = int(trade_mask.sum())
    false_positive_count = int(((pnl <= 0.0) & trade_mask).sum())
    true_positive_count = int(((pnl > 0.0) & trade_mask).sum())
    trade_records = [
        {
            "sample_id": row.sample_id,
            "decision_time": row.decision_time,
            "symbol": row.symbol,
            "timeframe": row.timeframe,
            "action": "long" if action == 1 else "short",
            "pnl_bps": float(row.long_net_bps if action == 1 else row.short_net_bps),
            "cost_evidence_source": row.cost_evidence_source,
            "total_cost_bps": row.total_cost_bps,
        }
        for row, action in zip(rows, actions, strict=True)
        if action != 0
    ]
    by_symbol = {
        symbol: _bucket_trade_metrics(
            [record for record in trade_records if record["symbol"] == symbol]
        )
        for symbol in sorted({row.symbol for row in rows})
    }
    by_timeframe = {
        timeframe: _bucket_trade_metrics(
            [record for record in trade_records if record["timeframe"] == timeframe]
        )
        for timeframe in sorted({row.timeframe for row in rows})
    }
    source_rows = Counter(row.cost_evidence_source for row in rows)
    source_trades = Counter(str(record["cost_evidence_source"]) for record in trade_records)
    costs = [float(row.total_cost_bps) for row in rows]
    uncertainty = (
        _clustered_expectancy_lcb(
            trade_records,
            seed_material={
                "policy": CLUSTERED_BOOTSTRAP_POLICY,
                "threshold_bps": float(threshold_bps),
                "rows": [row.sample_id for row in rows],
                "predictions": [float(value) for value in pred],
            },
        )
        if include_uncertainty
        else {
            "clustered_bootstrap_policy": CLUSTERED_BOOTSTRAP_POLICY,
            "clustered_bootstrap_status": "NOT_RUN_HYPERPARAMETER_SCAN",
            "clustered_bootstrap_replicates": 0,
            "clustered_bootstrap_lcb_quantile": CLUSTERED_BOOTSTRAP_LCB_QUANTILE,
            "decision_time_cluster_count": len(
                {str(record["decision_time"]) for record in trade_records}
            ),
            "symbol_cluster_count": len({str(record["symbol"]) for record in trade_records}),
            "multi_symbol_decision_time_cluster_count": sum(
                len(
                    {
                        str(record["symbol"])
                        for record in trade_records
                        if str(record["decision_time"]) == decision_time
                    }
                )
                >= 2
                for decision_time in {str(record["decision_time"]) for record in trade_records}
            ),
            "after_cost_expectancy_clustered_lcb_bps": None,
        }
    )
    lcb = finite_float(uncertainty.get("after_cost_expectancy_clustered_lcb_bps"))
    edge_evidence_valid = bool(
        include_uncertainty
        and uncertainty.get("clustered_bootstrap_status") == "PASS"
        and trade_count > 0
    )
    result = {
        "sample_count": len(rows),
        "prediction_count": len(pred),
        "trade_count": trade_count,
        "hold_count": int((actions == 0).sum()),
        "long_count": int((actions == 1).sum()),
        "short_count": int((actions == -1).sum()),
        "coverage": (trade_count / len(rows)) if rows else 0.0,
        "directional_accuracy": (true_positive_count / trade_count) if trade_count else None,
        "false_positive_rate": (false_positive_count / trade_count) if trade_count else None,
        "after_cost_expectancy_bps": float(pnl[trade_mask].mean()) if trade_count else None,
        "expected_move_mae_bps": float(np.abs(pred - y).mean()) if len(rows) else None,
        "true_positive_count": true_positive_count,
        "false_positive_count": false_positive_count,
        "expectancy_scope": "explicit_action_specific_net_labels_directional_trades_only",
        "label_schema_version": ACTION_SPECIFIC_LABEL_SCHEMA_VERSION,
        "action_specific_cost_policy": ACTION_SPECIFIC_COST_POLICY,
        "evaluation_blocker_reasons": [],
        "row_contract_rejections_by_reason": {},
        "per_symbol": by_symbol,
        "per_timeframe": by_timeframe,
        "cost_source_distribution": {
            "rows": dict(sorted(source_rows.items())),
            "trades": dict(sorted(source_trades.items())),
            "total_cost_bps": {
                "count": len(costs),
                "min": min(costs) if costs else None,
                "max": max(costs) if costs else None,
                "mean": sum(costs) / len(costs) if costs else None,
            },
        },
        **uncertainty,
        "edge_evidence_valid": edge_evidence_valid,
        "edge_claim_allowed": bool(edge_evidence_valid and lcb is not None and lcb > 0.0),
    }
    if include_uncertainty and not edge_evidence_valid:
        result["evaluation_blocker_reasons"] = [
            str(uncertainty.get("clustered_bootstrap_status") or "CLUSTERED_BOOTSTRAP_INVALID")
        ]
    elif include_uncertainty and (lcb is None or lcb <= 0.0):
        result["evaluation_blocker_reasons"] = ["CLUSTERED_EXPECTANCY_LCB_NOT_POSITIVE"]
    return result


def train_challenger_model(
    *,
    train_rows: Sequence[EdgeRecoveryRow],
    validation_rows: Sequence[EdgeRecoveryRow],
    max_features: int = 256,
    ridge_lambdas: Sequence[float] = DEFAULT_RIDGE_LAMBDAS,
    thresholds_bps: Sequence[float] = DEFAULT_THRESHOLDS_BPS,
    min_validation_trades: int = 100,
    min_validation_supply_trades: int = DEFAULT_MIN_VALIDATION_SUPPLY_TRADES,
    min_validation_supply_coverage: float = DEFAULT_MIN_VALIDATION_SUPPLY_COVERAGE,
    model_feature_cap: int | None = DEFAULT_MODEL_FEATURE_CAP,
    target_clip_bps: float | None = DEFAULT_TARGET_CLIP_BPS,
) -> ChallengerModel:
    import numpy as np

    if not train_rows:
        raise ValueError("train_rows_required")
    if not validation_rows:
        raise ValueError("validation_rows_required")
    train_contract_reasons = sorted(
        {reason for row in train_rows for reason in _row_label_contract_reasons(row)}
    )
    validation_contract_reasons = sorted(
        {reason for row in validation_rows for reason in _row_label_contract_reasons(row)}
    )
    if train_contract_reasons:
        raise ValueError(
            "train_action_specific_row_contract_invalid:" + ",".join(train_contract_reasons)
        )
    if validation_contract_reasons:
        raise ValueError(
            "validation_action_specific_row_contract_invalid:"
            + ",".join(validation_contract_reasons)
        )
    feature_limit = (
        min(int(max_features), int(model_feature_cap)) if model_feature_cap else int(max_features)
    )
    feature_names = select_feature_names(train_rows, max_features=feature_limit)
    if not feature_names:
        raise ValueError("numeric_feature_names_required")
    x_train = _matrix(train_rows, feature_names)
    raw_y_train = _targets(train_rows)
    clip_bps = float(target_clip_bps) if target_clip_bps is not None else None
    y_train = (
        np.clip(raw_y_train, -clip_bps, clip_bps) if clip_bps and clip_bps > 0 else raw_y_train
    )
    x_val = _matrix(validation_rows, feature_names)
    means = x_train.mean(axis=0)
    stds = x_train.std(axis=0)
    stds[stds < 1e-9] = 1.0
    xs_train = (x_train - means) / stds
    xs_val = (x_val - means) / stds
    x_design = np.c_[np.ones(xs_train.shape[0]), xs_train]
    best: tuple[float, float, float, Any, dict[str, Any]] | None = None
    validation_supply_floor = min(
        len(validation_rows),
        max(
            int(min_validation_trades),
            int(min_validation_supply_trades),
            int(math.ceil(len(validation_rows) * max(0.0, float(min_validation_supply_coverage)))),
        ),
    )
    for ridge_lambda in ridge_lambdas:
        penalty = float(ridge_lambda) * np.eye(x_design.shape[1])
        penalty[0, 0] = 0.0
        try:
            coef = np.linalg.solve(x_design.T @ x_design + penalty, x_design.T @ y_train)
        except np.linalg.LinAlgError:
            coef = np.linalg.pinv(x_design.T @ x_design + penalty) @ x_design.T @ y_train
        val_pred = np.c_[np.ones(xs_val.shape[0]), xs_val] @ coef
        for threshold in thresholds_bps:
            metrics = evaluate_predictions(
                rows=validation_rows,
                predictions=val_pred,
                threshold_bps=float(threshold),
                include_uncertainty=False,
            )
            if metrics["trade_count"] < int(min_validation_trades):
                continue
            if metrics["trade_count"] < validation_supply_floor:
                continue
            expectancy = metrics["after_cost_expectancy_bps"]
            if expectancy is None:
                continue
            # Validation selects only model hyperparameters. Holdout remains untouched.
            score = float(expectancy) + 10.0 * float(metrics["directional_accuracy"] or 0.0)
            if best is None or score > best[0]:
                metrics = dict(metrics)
                metrics["selection_score"] = score
                metrics["selection_min_validation_trades"] = int(min_validation_trades)
                metrics["selection_validation_supply_floor"] = int(validation_supply_floor)
                metrics["selection_validation_supply_coverage_floor"] = float(
                    min_validation_supply_coverage
                )
                best = (score, float(ridge_lambda), float(threshold), coef, metrics)
    if best is None:
        raise ValueError("no_validation_candidate_met_minimum_trade_supply")
    score, ridge_lambda, threshold, coef, selection_metrics = best
    selected_validation_predictions = np.c_[np.ones(xs_val.shape[0]), xs_val] @ coef
    validation_metrics = evaluate_predictions(
        rows=validation_rows,
        predictions=selected_validation_predictions,
        threshold_bps=threshold,
        include_uncertainty=True,
    )
    validation_metrics.update(
        {
            "selection_score": score,
            "selection_min_validation_trades": selection_metrics["selection_min_validation_trades"],
            "selection_validation_supply_floor": selection_metrics[
                "selection_validation_supply_floor"
            ],
            "selection_validation_supply_coverage_floor": selection_metrics[
                "selection_validation_supply_coverage_floor"
            ],
            "selected_hyperparameters_re_evaluated_once_with_clustered_uncertainty": True,
        }
    )
    if validation_metrics.get("edge_evidence_valid") is not True:
        raise ValueError("validation_action_specific_edge_evidence_invalid")
    validation_lcb = finite_float(validation_metrics.get("after_cost_expectancy_clustered_lcb_bps"))
    if validation_lcb is None or validation_lcb <= 0.0:
        raise ValueError("validation_clustered_lcb_not_positive")
    feature_set_hash = stable_hash(
        {
            "selection_source": "training_rows_only",
            "feature_names": list(feature_names),
        }
    )
    hyperparameter_grid_hash = stable_hash(
        {
            "selection_source": "validation_rows_only",
            "ridge_lambdas": [float(value) for value in ridge_lambdas],
            "thresholds_bps": [float(value) for value in thresholds_bps],
            "min_validation_trades": int(min_validation_trades),
            "min_validation_supply_trades": int(min_validation_supply_trades),
            "min_validation_supply_coverage": float(min_validation_supply_coverage),
            "model_feature_cap": int(model_feature_cap) if model_feature_cap else None,
            "target_clip_bps": clip_bps,
        }
    )
    return ChallengerModel(
        feature_names=list(feature_names),
        means=[float(v) for v in means],
        stds=[float(v) for v in stds],
        weights=[float(v) for v in coef[1:]],
        bias=float(coef[0]),
        ridge_lambda=ridge_lambda,
        threshold_bps=threshold,
        validation_metrics=validation_metrics,
        target_transform="clipped_raw_future_return_bps_action_specific_net_evaluation"
        if clip_bps and clip_bps > 0
        else "raw_future_return_bps_action_specific_net_evaluation",
        target_clip_bps=clip_bps if clip_bps and clip_bps > 0 else None,
        feature_count_limit=feature_limit,
        feature_set_hash=feature_set_hash,
        hyperparameter_grid_hash=hyperparameter_grid_hash,
    )


def predict_rows(model: ChallengerModel, rows: Sequence[EdgeRecoveryRow]) -> list[float]:
    return [model.predict(row.features) for row in rows]


def _improvement_status(holdout_metrics: Mapping[str, Any]) -> dict[str, Any]:
    directional = finite_float(holdout_metrics.get("directional_accuracy"))
    mae = finite_float(holdout_metrics.get("expected_move_mae_bps"))
    false_positive = finite_float(holdout_metrics.get("false_positive_rate"))
    expectancy = finite_float(holdout_metrics.get("after_cost_expectancy_bps"))
    expectancy_lcb = finite_float(holdout_metrics.get("after_cost_expectancy_clustered_lcb_bps"))
    return {
        "directional_accuracy_improved": directional is not None
        and directional > CHAMPION_BASELINE["directional_accuracy"],
        "expected_move_mae_improved": mae is not None
        and mae < CHAMPION_BASELINE["expected_move_mae_bps"],
        "false_positive_rate_improved": false_positive is not None
        and false_positive < CHAMPION_BASELINE["false_positive_rate"],
        "after_cost_expectancy_improved": expectancy is not None
        and expectancy > CHAMPION_BASELINE["after_cost_expectancy_bps"],
        "positive_after_cost_expectancy": expectancy is not None and expectancy > 0.0,
        "action_specific_edge_evidence_valid": holdout_metrics.get("edge_evidence_valid") is True,
        "positive_clustered_after_cost_expectancy_lcb": expectancy_lcb is not None
        and expectancy_lcb > 0.0,
    }


def run_champion_challenger(
    *,
    repo_root: Path,
    scan_limit: int = 60_000,
    replay_limit: int = 30_000,
    min_train_rows: int = 1000,
    min_validation_trades: int = 100,
    min_holdout_trades: int = 100,
    max_features: int = 256,
    min_validation_supply_trades: int = DEFAULT_MIN_VALIDATION_SUPPLY_TRADES,
    min_validation_supply_coverage: float = DEFAULT_MIN_VALIDATION_SUPPLY_COVERAGE,
    archive_root: Path | None = None,
) -> dict[str, Any]:
    archive_root = archive_root or default_archive_root(repo_root)
    freeze = freeze_dataset_from_archive(
        archive_root=archive_root,
        scan_limit=scan_limit,
        replay_limit=replay_limit,
    )
    train_rows, validation_rows, holdout_rows, split_manifest = _split_rows(freeze.rows)
    status = "BLOCKED_INSUFFICIENT_TRUSTED_REPLAY_ROWS"
    model: ChallengerModel | None = None
    train_metrics = validation_metrics = holdout_metrics = None
    blocker_reasons: list[str] = []
    model_frozen_before_holdout_hash: str | None = None
    model_after_holdout_hash: str | None = None
    holdout_evaluation_count_this_run = 0
    if freeze.manifest.get("action_specific_cost_coverage_complete") is not True:
        blocker_reasons.append("ACTION_SPECIFIC_COST_COVERAGE_INCOMPLETE")
    blocker_reasons.extend(str(reason) for reason in split_manifest["split_blocker_reasons"])
    if len(train_rows) < int(min_train_rows):
        blocker_reasons.append("INSUFFICIENT_TRAIN_ROWS")
    if not validation_rows:
        blocker_reasons.append("VALIDATION_ROWS_MISSING")
    if not holdout_rows:
        blocker_reasons.append("HOLDOUT_ROWS_MISSING")
    if not blocker_reasons:
        try:
            model = train_challenger_model(
                train_rows=train_rows,
                validation_rows=validation_rows,
                max_features=max_features,
                min_validation_trades=min_validation_trades,
                min_validation_supply_trades=min_validation_supply_trades,
                min_validation_supply_coverage=min_validation_supply_coverage,
            )
        except ValueError as exc:
            blocker_reasons.append(str(exc).upper())
            status = "BLOCKED_VALIDATION_CANDIDATE_NOT_PROVEN"
            improvements = {}
        else:
            train_metrics = evaluate_predictions(
                rows=train_rows,
                predictions=predict_rows(model, train_rows),
                threshold_bps=model.threshold_bps,
                include_uncertainty=False,
            )
            validation_metrics = model.validation_metrics
            model_frozen_before_holdout_hash = stable_hash(model.to_jsonable())
            holdout_predictions = predict_rows(model, holdout_rows)
            holdout_evaluation_count_this_run += 1
            holdout_metrics = evaluate_predictions(
                rows=holdout_rows,
                predictions=holdout_predictions,
                threshold_bps=model.threshold_bps,
                include_uncertainty=True,
            )
            model_after_holdout_hash = stable_hash(model.to_jsonable())
            if model_after_holdout_hash != model_frozen_before_holdout_hash:
                blocker_reasons.append("MODEL_CHANGED_DURING_HOLDOUT_EVALUATION")
            improvements = _improvement_status(holdout_metrics)
            if holdout_metrics["trade_count"] < int(min_holdout_trades):
                blocker_reasons.append("INSUFFICIENT_HOLDOUT_TRADES")
            for name, passed in improvements.items():
                if not passed:
                    blocker_reasons.append(name.upper() + "_FAILED")
            status = (
                "PASSED_PAPER_CHALLENGER_READY"
                if not blocker_reasons
                else "BLOCKED_HOLDOUT_EDGE_NOT_PROVEN"
            )
    else:
        improvements = {}

    dataset_manifest = dict(freeze.manifest)
    dataset_manifest.update(split_manifest)
    edge_claim_allowed = bool(
        status == "PASSED_PAPER_CHALLENGER_READY"
        and holdout_metrics is not None
        and holdout_metrics.get("edge_claim_allowed") is True
    )
    result = {
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "status": status,
        "blocker_reasons": sorted(set(blocker_reasons)),
        "champion_baseline": CHAMPION_BASELINE,
        "dataset_freeze": dataset_manifest,
        "rejections_by_reason": freeze.rejections_by_reason,
        "row_counts": {
            "train": len(train_rows),
            "validation": len(validation_rows),
            "untouched_holdout": len(holdout_rows),
        },
        "point_in_time_safety": {
            "future_labels_used_as_features": False,
            "feature_available_at_after_decision_rejected": freeze.rejections_by_reason.get(
                "AVAILABLE_AT_AFTER_DECISION_TIME", 0
            ),
            "feature_cutoff_after_decision_rejected": freeze.rejections_by_reason.get(
                "FEATURE_CUTOFF_AFTER_DECISION_TIME", 0
            ),
            "open_candle_rejected": freeze.rejections_by_reason.get("OPEN_CANDLE_REJECTED", 0),
            "latest_unclosed_exclusion_unproven_rejected": freeze.rejections_by_reason.get(
                "LATEST_UNCLOSED_KLINE_EXCLUSION_UNPROVEN", 0
            ),
            "content_hash_missing_rejected": freeze.rejections_by_reason.get(
                "CONTENT_SHA256_MISSING", 0
            ),
            "content_hash_mismatch_rejected": freeze.rejections_by_reason.get(
                "CONTENT_SHA256_MISMATCH", 0
            ),
            "naive_or_invalid_clock_rejected": sum(
                count
                for reason, count in freeze.rejections_by_reason.items()
                if "MISSING_INVALID_OR_NAIVE" in reason
            ),
            "temporal_overlap": split_manifest["temporal_overlap"],
            "label_overlap": split_manifest["label_overlap"],
            "split_pit_safe": split_manifest["split_pit_safe"],
            "purge_embargo_seconds": split_manifest["purge_embargo_seconds"],
            "max_future_horizon_seconds_consumed": split_manifest[
                "max_future_horizon_seconds_consumed"
            ],
            "split_by_decision_time_group_not_row": split_manifest[
                "split_by_decision_time_group_not_row"
            ],
        },
        "model": model.to_jsonable() if model else None,
        "train_metrics": train_metrics,
        "validation_metrics": validation_metrics,
        "untouched_holdout_metrics": holdout_metrics,
        "holdout_improvement": improvements,
        "validity_contract": {
            "label_schema_version": ACTION_SPECIFIC_LABEL_SCHEMA_VERSION,
            "action_specific_cost_policy": ACTION_SPECIFIC_COST_POLICY,
            "temporal_split_policy": TEMPORAL_SPLIT_POLICY,
            "clustered_bootstrap_policy": CLUSTERED_BOOTSTRAP_POLICY,
            "strict_aware_utc_required": True,
            "content_hash_verification_required": True,
            "final_candle_and_latest_unclosed_exclusion_proof_required": True,
            "static_cost_fallback_allowed": False,
            "signed_net_label_inversion_allowed": False,
            "no_edge_claim_without_complete_evidence_and_positive_clustered_lcb": True,
        },
        "holdout_evaluation_contract": {
            "forward_chronological_holdout": True,
            "holdout_used_for_feature_or_hyperparameter_selection": False,
            "features_and_hyperparameters_frozen_before_holdout": model is not None,
            "model_frozen_before_holdout_hash": model_frozen_before_holdout_hash,
            "model_after_holdout_hash": model_after_holdout_hash,
            "model_unchanged_during_holdout": bool(
                model_frozen_before_holdout_hash
                and model_frozen_before_holdout_hash == model_after_holdout_hash
            ),
            "holdout_evaluation_count_this_run": holdout_evaluation_count_this_run,
            "purge_embargo_seconds": MIN_TEMPORAL_EMBARGO_SECONDS,
        },
        "edge_claim": {
            "allowed": edge_claim_allowed,
            "claimed_after_cost_expectancy_bps": (
                holdout_metrics.get("after_cost_expectancy_bps")
                if edge_claim_allowed and holdout_metrics is not None
                else None
            ),
            "claimed_clustered_lcb_bps": (
                holdout_metrics.get("after_cost_expectancy_clustered_lcb_bps")
                if edge_claim_allowed and holdout_metrics is not None
                else None
            ),
            "reason": (
                "complete_action_specific_evidence_and_positive_clustered_holdout_lcb"
                if edge_claim_allowed
                else "blocked_missing_invalid_or_nonpositive_action_specific_holdout_evidence"
            ),
        },
        "paper_challenger_policy": {
            "enabled": edge_claim_allowed,
            "paper_opportunity_tier": PAPER_CHALLENGER_TIER,
            "paper_fill_allowed_upstream": False,
            "routes_to_live": False,
            "places_real_order": False,
            "counts_as_a_grade_evidence": False,
            "a_grade_promotion_allowed": False,
            "live_ready_implication": False,
        },
        "safety": {
            "paper_only": True,
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
        },
    }
    result["result_hash"] = stable_hash(_stable_result_material(result))
    return result


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    tmp.replace(path)


def emit_artifacts(repo_root: Path, result: Mapping[str, Any]) -> list[Path]:
    paths = [
        repo_root / "goal_state" / GOAL_ID / "model_edge_recovery_champion_challenger_status.json",
        repo_root
        / "v2/frontend/public"
        / ARTIFACT_REL
        / "model_edge_recovery_champion_challenger_status.json",
    ]
    for path in paths:
        _write_json(path, result)
    return paths


def champion_challenger_status_from_result(
    result: Mapping[str, Any],
    *,
    source: str = "model_edge_recovery_challenger",
) -> dict[str, Any]:
    """Normalize a challenger evaluation into the runtime status contract.

    This contract is deliberately descriptive. It never promotes A-grade/live
    behavior by itself; it only exposes the currently evaluated challenger and
    the reason promotion remains allowed or blocked.
    """
    result_hash = str(result.get("result_hash") or "")
    result_status = str(result.get("status") or "UNKNOWN")
    policy = result.get("paper_challenger_policy")
    policy_map = policy if isinstance(policy, Mapping) else {}
    model_payload = result.get("model")
    model_map = model_payload if isinstance(model_payload, Mapping) else {}
    dataset_freeze = result.get("dataset_freeze")
    freeze_map = dataset_freeze if isinstance(dataset_freeze, Mapping) else {}
    holdout_metrics = result.get("untouched_holdout_metrics")
    holdout_map = holdout_metrics if isinstance(holdout_metrics, Mapping) else {}
    validation_metrics = result.get("validation_metrics")
    validation_map = validation_metrics if isinstance(validation_metrics, Mapping) else {}
    row_counts = result.get("row_counts")
    row_counts_map = row_counts if isinstance(row_counts, Mapping) else {}
    blockers = [str(item) for item in (result.get("blocker_reasons") or [])]

    paper_challenger_enabled = bool(policy_map.get("enabled"))
    best_challenger_id = (
        f"model_edge_recovery:{result_hash[:16]}"
        if paper_challenger_enabled and result_hash
        else None
    )
    promotion_allowed = bool(policy_map.get("a_grade_promotion_allowed") is True)
    if promotion_allowed:
        promotion_reason = "a_grade_promotion_allowed_by_challenger_contract"
    elif result_status == "PASSED_PAPER_CHALLENGER_READY":
        promotion_reason = (
            "paper challenger passed holdout, but A-grade/live promotion remains disabled "
            "until separate runtime paper evidence approves it"
        )
    else:
        promotion_reason = ",".join(blockers) if blockers else result_status

    replay_rows = freeze_map.get("trusted_replay_rows")
    scan_rows = freeze_map.get("snapshots_scanned")
    holdout_trades = holdout_map.get("trade_count")
    model_validation = model_map.get("validation_metrics")
    model_validation_map = model_validation if isinstance(model_validation, Mapping) else {}
    validation_trades = validation_map.get("trade_count") or model_validation_map.get("trade_count")

    return {
        "schema_version": CHAMPION_CHALLENGER_STATUS_SCHEMA_VERSION,
        "generated_utc": utc_now(),
        "evaluated_at_utc": result.get("generated_utc"),
        "source": source,
        "source_goal_id": result.get("goal_id"),
        "source_result_hash": result_hash or None,
        "redis_key": CHAMPION_CHALLENGER_STATUS_REDIS_KEY,
        "status": (
            "CHAMPION_CHALLENGER_EVALUATED_PAPER_READY"
            if result_status == "PASSED_PAPER_CHALLENGER_READY"
            else "CHAMPION_CHALLENGER_EVALUATED_BLOCKED"
        ),
        "result_status": result_status,
        "best_challenger_id": best_challenger_id,
        "paper_challenger_enabled": paper_challenger_enabled,
        "paper_opportunity_tier": policy_map.get("paper_opportunity_tier"),
        "promotion_allowed": promotion_allowed,
        "promotion_reason": promotion_reason,
        "blocker_reasons": blockers,
        "replay_windows_processed": replay_rows,
        "replay_snapshots_scanned": scan_rows,
        "backtests_processed": {
            "train_rows": row_counts_map.get("train"),
            "validation_rows": row_counts_map.get("validation"),
            "untouched_holdout_rows": row_counts_map.get("untouched_holdout"),
            "validation_trade_count": validation_trades,
            "untouched_holdout_trade_count": holdout_trades,
        },
        "holdout_metrics": holdout_map,
        "holdout_improvement": result.get("holdout_improvement") or {},
        "point_in_time_safety": result.get("point_in_time_safety") or {},
        "trainer_model_source": model_map.get("model_source") or MODEL_SOURCE,
        "model_threshold_bps": model_map.get("threshold_bps"),
        "model_feature_count": len(model_map.get("feature_names") or []),
        "safety": {
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "live_gate": LIVE_GATE_BLOCKED,
            "counts_as_a_grade_evidence": policy_map.get("counts_as_a_grade_evidence") is True,
            "a_grade_promotion_allowed": promotion_allowed,
            "live_ready_implication": False,
        },
    }


def publish_champion_challenger_status(
    *,
    client: Any,
    result: Mapping[str, Any],
    ttl_seconds: int = CHAMPION_CHALLENGER_STATUS_TTL_SECONDS,
) -> dict[str, Any]:
    status = champion_challenger_status_from_result(result, source="redis_runtime_publish")
    client.set(
        CHAMPION_CHALLENGER_STATUS_REDIS_KEY,
        json.dumps(status, sort_keys=True, default=str),
        ex=max(60, int(ttl_seconds)),
    )
    return status


def _trust_row_for_current_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    features = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
    decision_time = (
        snapshot.get("decision_time")
        or snapshot.get("decision_time_est")
        or snapshot.get("decision_cutoff_time_est")
        or snapshot.get("generated_at")
    )
    feature_cutoff = (
        snapshot.get("feature_cutoff")
        or snapshot.get("candle_close_time")
        or snapshot.get("source_event_time_est")
    )
    available_at = (
        snapshot.get("available_at")
        or snapshot.get("source_available_time")
        or snapshot.get("generated_at")
    )
    return {
        "symbol": str(snapshot.get("symbol") or "").upper(),
        "timeframe": str(snapshot.get("timeframe") or ""),
        "feature_snapshot_id": snapshot.get("feature_snapshot_id") or snapshot.get("snapshot_id"),
        "feature_vector_hash": hashlib.sha256(
            _canonical_json(features).encode("utf-8")
        ).hexdigest(),
        "generated_at": snapshot.get("generated_at")
        or snapshot.get("generated_utc")
        or decision_time,
        "feature_cutoff": feature_cutoff,
        "available_at": available_at,
        "decision_time_est": decision_time,
        "source_event_time_est": snapshot.get("source_event_time_est") or feature_cutoff,
        "source_received_time_est": snapshot.get("source_received_time_est") or available_at,
        "source_available_time": snapshot.get("source_available_time") or available_at,
        "candle_closed_confirmed": snapshot.get("candle_closed_confirmed"),
        "candle_open_time": snapshot.get("candle_open_time"),
        "candle_close_time": snapshot.get("candle_close_time") or feature_cutoff,
        "feature_freshness_state": snapshot.get("feature_freshness_state"),
        "trainer_consumable": snapshot.get("trainer_consumable") is not False,
        "row_classification": "TRAINABLE",
        "missing_feature_count": snapshot.get("missing_feature_count") or 0,
        "missing_feature_names": list(snapshot.get("missing_feature_flags") or []),
        "stale_feature_count": len(snapshot.get("stale_feature_flags") or []),
        "stale_feature_names": list(snapshot.get("stale_feature_flags") or []),
        "features": dict(features),
    }


def build_paper_challenger_signal(
    *,
    model: ChallengerModel,
    snapshot: Mapping[str, Any],
    result_hash: str,
) -> dict[str, Any] | None:
    features = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
    if not features:
        return None
    if any(not _feature_name_allowed(str(name)) for name in features):
        return None
    prediction = model.predict(features)
    if abs(prediction) < model.threshold_bps:
        return None
    side = "long" if prediction > 0.0 else "short"
    trust_row = _trust_row_for_current_snapshot(snapshot)
    trust = classify_training_sample(trust_row)
    if trust["accepted_for_training"] is not True:
        return None
    confidence = min(
        0.74, max(0.50, 0.50 + min(abs(prediction) / max(model.threshold_bps, 1.0), 1.0) * 0.20)
    )
    snapshot_id = str(snapshot.get("feature_snapshot_id") or snapshot.get("snapshot_id") or "")
    symbol = str(snapshot.get("symbol") or "").upper()
    timeframe = str(snapshot.get("timeframe") or "")
    signal_id = (
        "sig_model_edge_recovery_"
        + stable_hash(
            {
                "snapshot_id": snapshot_id,
                "side": side,
                "result_hash": result_hash,
            }
        )[:24]
    )
    return {
        "signal_id": signal_id,
        "winner_proposal_id": signal_id,
        "prediction_id": "pred_model_edge_recovery_"
        + stable_hash({"snapshot_id": snapshot_id, "result_hash": result_hash})[:24],
        "symbol": symbol,
        "timeframe": timeframe,
        "side": side,
        "action": side,
        "selected_action": side,
        "expected_move_after_cost_bps": float(prediction),
        "expected_move_bps": float(prediction),
        "confidence_calibrated": round(float(confidence), 8),
        "confidence_raw": round(float(confidence), 8),
        "paper_opportunity_tier": PAPER_CHALLENGER_TIER,
        "paper_execution_tier": PAPER_CHALLENGER_TIER,
        "paper_fill_allowed": False,
        "paper_fill_gate_status": "BLOCKED_STRICT_GATE_CHALLENGER_LOCAL_ONLY",
        "paper_fill_gate_block_reasons": [
            "MODEL_EDGE_RECOVERY_CHALLENGER_B_GRADE_LOCAL_PAPER_ONLY"
        ],
        "valid_for_paper": True,
        "market_state_id": trust.get("market_state_id"),
        "market_state_integrity_score": trust.get("market_state_integrity_score"),
        "market_state_reject_reasons": [],
        "feature_snapshot_id": snapshot_id,
        "feature_cutoff": trust_row.get("feature_cutoff"),
        "decision_time": trust_row.get("decision_time_est"),
        "available_at": trust_row.get("available_at"),
        "generated_utc": utc_now(),
        "trainer_source": MODEL_SOURCE,
        "model_source": MODEL_SOURCE,
        "model_version": result_hash,
        "checkpoint_id": None,
        "source_hashes": snapshot.get("source_hashes") or {},
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "counts_as_a_grade_evidence": False,
        "a_grade_promotion_allowed": False,
        "live_ready_implication": False,
        "future_labels_used_as_features": False,
    }


def publish_paper_challenger_signals(
    *,
    client: Any,
    result: Mapping[str, Any],
    max_signals: int = 5,
) -> dict[str, Any]:
    if result.get("status") != "PASSED_PAPER_CHALLENGER_READY":
        return {
            "status": "NOT_PUBLISHED_HOLDOUT_EDGE_NOT_PROVEN",
            "published_count": 0,
            "paper_only": True,
            "routes_to_live": False,
        }
    model_payload = result.get("model") if isinstance(result.get("model"), Mapping) else None
    if not model_payload:
        return {"status": "NOT_PUBLISHED_MODEL_MISSING", "published_count": 0}
    model = ChallengerModel(
        feature_names=list(model_payload["feature_names"]),
        means=[float(v) for v in model_payload["means"]],
        stds=[float(v) for v in model_payload["stds"]],
        weights=[float(v) for v in model_payload["weights"]],
        bias=float(model_payload["bias"]),
        ridge_lambda=float(model_payload["ridge_lambda"]),
        threshold_bps=float(model_payload["threshold_bps"]),
        validation_metrics=dict(model_payload.get("validation_metrics") or {}),
    )
    keys = list(client.scan_iter("v2:features:latest:*", count=1000))
    published: list[str] = []
    rejected = 0
    for key in keys:
        if len(published) >= int(max_signals):
            break
        try:
            raw = client.get(key)
            snapshot = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            rejected += 1
            continue
        if not isinstance(snapshot, Mapping):
            rejected += 1
            continue
        signal = build_paper_challenger_signal(
            model=model,
            snapshot=snapshot,
            result_hash=str(result.get("result_hash") or ""),
        )
        if signal is None:
            rejected += 1
            continue
        out_key = (
            "v2:signals:paper:challenger:model_edge_recovery:"
            f"{signal['symbol']}:{signal['timeframe']}"
        )
        client.set(out_key, json.dumps(signal, sort_keys=True, default=str), ex=900)
        published.append(out_key)
    return {
        "status": "PUBLISHED_PAPER_ONLY_CHALLENGER_SIGNALS"
        if published
        else "NO_CURRENT_CHALLENGER_SIGNAL_ELIGIBLE",
        "published_count": len(published),
        "rejected_count": rejected,
        "keys_written": published,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
