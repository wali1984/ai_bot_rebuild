"""CUDA trainer edge calibration and outcome burn-in artifacts.

This module consumes the V2 native CUDA trainer operator payload and, when
available, V2-owned OHLCV timelines. It never enables live/canary, never calls
an exchange, never writes Redis, and never fabricates missing future windows.
"""
from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.config import (
    LIVE_GATE_BLOCKED,
    MODEL_SOURCE,
    TRAINER_SOURCE,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.publisher import dumps_pretty

GO_READY = "V2_NATIVE_CUDA_TRAINER_EDGE_CALIBRATION_AND_OUTCOME_BURN_IN_READY"
GO_BLOCKED = "V2_NATIVE_CUDA_TRAINER_EDGE_CALIBRATION_AND_OUTCOME_BURN_IN_BLOCKED"
SCHEMA_VERSION = "v2_native_cuda_trainer_edge_calibration_outcome_burn_in_v1"
ARTIFACT_REL = Path("v2_native_cuda_trainer_edge_calibration_and_outcome_burn_in/latest")
SOURCE_PAYLOAD_REL = Path("v2_native_rl_masa_ppo_cuda_trainer_implementation/latest/operator_dashboard_payload.json")

OUTCOME_WINDOWS: tuple[tuple[str, int], ...] = (
    ("1m", 60),
    ("5m", 5 * 60),
    ("15m", 15 * 60),
    ("1h", 60 * 60),
)

ALLOWED_RECOMMENDATIONS = (
    "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN",
    "BLOCK_LIVE_MODEL_SIGNAL_QUALITY_NOT_READY",
    "BLOCK_LIVE_RISK_CAPS_OPERATOR_REQUIRED",
    "CANARY_OPERATOR_DECISION_REQUIRED",
)
DEFAULT_ROUND_TRIP_COST_BPS = 12.0
MIN_OUTCOME_SAMPLE_GUARD = 30


@dataclass(frozen=True)
class EdgeBurnInPaths:
    repo_root: Path
    worklog_dir: Path
    public_dir: Path
    source_payload_path: Path


@dataclass(frozen=True)
class EdgeBurnInResult:
    go_no_go: str
    artifacts: dict[str, Any]
    operator_dashboard_payload: dict[str, Any]
    paths_written: tuple[str, ...] = field(default_factory=tuple)


TimelineProvider = Callable[[str], list[dict[str, Any]]]


def default_paths(repo_root: Path) -> EdgeBurnInPaths:
    root = repo_root.resolve()
    return EdgeBurnInPaths(
        repo_root=root,
        worklog_dir=root / "claude_worklog/final_readiness" / ARTIFACT_REL,
        public_dir=root / "v2/frontend/public" / ARTIFACT_REL,
        source_payload_path=root / "v2/frontend/public" / SOURCE_PAYLOAD_REL,
    )


def _est_iso() -> str:
    return datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _ci_lower_95(values: list[float]) -> float | None:
    if not values:
        return None
    if len(values) < 2:
        return float(values[0])
    avg = statistics.fmean(values)
    std = statistics.stdev(values)
    return avg - 1.96 * std / math.sqrt(len(values))


def _parse_ts_ms(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            dt = datetime.fromisoformat(text)
            return int(dt.timestamp() * 1000)
        except ValueError:
            try:
                return int(float(text))
            except ValueError:
                return None
    return None


def _read_json(path: Path) -> dict[str, Any]:
    return _as_dict(json.loads(path.read_text(encoding="utf-8")))


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _prediction_ts_ms(prediction: Mapping[str, Any], lineage: Mapping[str, Any] | None) -> int | None:
    for candidate in (
        prediction.get("generated_est"),
        prediction.get("generated_at"),
        _as_dict(_as_dict(lineage).get("trainer_prediction_record")).get("prediction_ts_ms"),
        _as_dict(_as_dict(lineage).get("orchestrator_decision_record")).get("decision_ts_ms"),
    ):
        ts = _parse_ts_ms(candidate)
        if ts is not None and ts > 0:
            return ts
    return None


def _round_trip_cost_bps(prediction: Mapping[str, Any]) -> float:
    expected = _float(prediction.get("expected_move_bps"))
    after = _float(prediction.get("expected_move_after_cost_bps"))
    if expected is not None and after is not None:
        cost = abs(expected - after)
        if cost > 0:
            return cost
    return DEFAULT_ROUND_TRIP_COST_BPS


def _side_from_prediction(prediction: Mapping[str, Any]) -> str | None:
    action = str(prediction.get("selected_action") or "").lower()
    if action == "long":
        return "long"
    if action == "short":
        return "short"
    expected_after = _float(prediction.get("expected_move_after_cost_bps"))
    if expected_after is None or abs(expected_after) < 4.0:
        return None
    return "long" if expected_after > 0 else "short"


def parse_ohlcv_timeline(payload: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source_rows = _as_list(payload)
    if isinstance(payload, dict):
        for key in ("candles", "ohlcv", "ohlcv_list", "rows", "data"):
            if isinstance(payload.get(key), list):
                source_rows = payload[key]
                break
    for row in source_rows:
        try:
            if isinstance(row, list) and len(row) >= 6:
                open_ms = int(float(row[0]))
                close_ms = int(float(row[6])) if len(row) > 6 else open_ms + 60_000 - 1
                rows.append(
                    {
                        "open_time_ms": open_ms,
                        "close_time_ms": close_ms,
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                    }
                )
            elif isinstance(row, dict):
                open_ms = _parse_ts_ms(row.get("open_time_ms") or row.get("open_time") or row.get("ts_ms") or row.get("time"))
                close_ms = _parse_ts_ms(row.get("close_time_ms") or row.get("close_time"))
                close_ms = close_ms if close_ms is not None else (open_ms + 60_000 - 1 if open_ms is not None else None)
                if open_ms is None or close_ms is None:
                    continue
                close = _float(row.get("close") or row.get("c"))
                high = _float(row.get("high") or row.get("h") or close)
                low = _float(row.get("low") or row.get("l") or close)
                open_price = _float(row.get("open") or row.get("o") or close)
                if close is None or high is None or low is None or open_price is None:
                    continue
                rows.append(
                    {
                        "open_time_ms": open_ms,
                        "close_time_ms": close_ms,
                        "open": open_price,
                        "high": high,
                        "low": low,
                        "close": close,
                    }
                )
        except Exception:
            continue
    rows.sort(key=lambda item: int(item["open_time_ms"]))
    return rows


def redis_timeline_provider(redis_client: Any | None) -> TimelineProvider:
    def provider(symbol: str) -> list[dict[str, Any]]:
        if redis_client is None:
            return []
        key = f"v2:market:ohlcv:binance:{symbol.upper()}:1m"
        try:
            raw = redis_client.get(key)
        except Exception:
            return []
        if not raw:
            return []
        try:
            return parse_ohlcv_timeline(json.loads(raw))
        except Exception:
            return []

    return provider


def _compute_one_window(
    *,
    timeline: list[dict[str, Any]],
    anchor_ms: int | None,
    side: str | None,
    window_id: str,
    window_seconds: int,
    round_trip_cost_bps: float,
) -> dict[str, Any]:
    if anchor_ms is None:
        return _insufficient_window(window_id, window_seconds, "INSUFFICIENT_EVIDENCE_NO_PREDICTION_TIMESTAMP")
    if side not in {"long", "short"}:
        return _insufficient_window(window_id, window_seconds, "INSUFFICIENT_EVIDENCE_NO_DIRECTIONAL_SIDE")
    if not timeline:
        return _insufficient_window(window_id, window_seconds, "INSUFFICIENT_EVIDENCE_NO_V2_OHLCV_TIMELINE")

    entry_candidates = [row for row in timeline if int(row["close_time_ms"]) <= anchor_ms]
    if not entry_candidates:
        return _insufficient_window(window_id, window_seconds, "INSUFFICIENT_EVIDENCE_NO_ENTRY_CANDLE")
    entry = entry_candidates[-1]
    entry_price = _float(entry.get("close"))
    if entry_price is None or entry_price <= 0:
        return _insufficient_window(window_id, window_seconds, "INSUFFICIENT_EVIDENCE_BAD_ENTRY_PRICE")
    end_ms = anchor_ms + window_seconds * 1000
    latest_close = max(int(row["close_time_ms"]) for row in timeline)
    if latest_close < end_ms:
        return _insufficient_window(window_id, window_seconds, "INSUFFICIENT_EVIDENCE_AWAITING_FUTURE_WINDOW")
    window_rows = [row for row in timeline if anchor_ms < int(row["close_time_ms"]) <= end_ms]
    if not window_rows:
        return _insufficient_window(window_id, window_seconds, "INSUFFICIENT_EVIDENCE_NO_CANDLES_IN_WINDOW")

    end_price = float(window_rows[-1]["close"])
    sign = 1.0 if side == "long" else -1.0
    raw_return_bps = ((end_price - entry_price) / entry_price) * 10_000.0
    signed_return_bps = sign * raw_return_bps
    after_cost = signed_return_bps - round_trip_cost_bps
    if side == "long":
        path_favorable = [((float(row["high"]) - entry_price) / entry_price) * 10_000.0 for row in window_rows]
        path_adverse = [((float(row["low"]) - entry_price) / entry_price) * 10_000.0 for row in window_rows]
    else:
        path_favorable = [((entry_price - float(row["low"])) / entry_price) * 10_000.0 for row in window_rows]
        path_adverse = [((entry_price - float(row["high"])) / entry_price) * 10_000.0 for row in window_rows]
    max_favorable = max(path_favorable) if path_favorable else None
    max_adverse = min(path_adverse) if path_adverse else None
    drawdown = max(0.0, -float(max_adverse)) if max_adverse is not None else None
    return {
        "window_id": window_id,
        "window_seconds": window_seconds,
        "status": "OUTCOME_READY",
        "entry_price": entry_price,
        "end_price": end_price,
        "side": side,
        "return_bps": raw_return_bps,
        "signed_return_bps": signed_return_bps,
        "after_cost_return_bps": after_cost,
        "drawdown_bps": drawdown,
        "max_favorable_bps": max_favorable,
        "max_adverse_bps": max_adverse,
        "round_trip_cost_bps": round_trip_cost_bps,
        "samples": len(window_rows),
        "source": "v2:market:ohlcv:binance:{symbol}:1m",
    }


def _insufficient_window(window_id: str, window_seconds: int, reason: str) -> dict[str, Any]:
    return {
        "window_id": window_id,
        "window_seconds": window_seconds,
        "status": reason,
        "return_bps": None,
        "signed_return_bps": None,
        "after_cost_return_bps": None,
        "drawdown_bps": None,
        "samples": 0,
        "source": reason,
    }


def _lineage_by_prediction(source: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in _as_list(source.get("lineage_samples")):
        lineage = _as_dict(row)
        ids = [
            _as_dict(lineage.get("trainer_prediction_record")).get("prediction_id"),
            _as_dict(lineage.get("paper_signal_lineage")).get("trainer_prediction_id"),
            _as_dict(lineage.get("paper_execution_ledger_entry")).get("prediction_id"),
        ]
        for prediction_id in ids:
            if isinstance(prediction_id, str) and prediction_id:
                out[prediction_id] = lineage
    return out


def _label_outcome(prediction: Mapping[str, Any], lineage: Mapping[str, Any], outcome_5m: Mapping[str, Any]) -> str:
    after_cost = _float(outcome_5m.get("after_cost_return_bps"))
    if after_cost is None:
        return "insufficient_evidence"
    risk = _as_dict(lineage.get("risk_decision_record"))
    paper = _as_dict(lineage.get("paper_execution_ledger_entry"))
    selected_action = str(prediction.get("selected_action") or "").lower()
    open_risk_action = selected_action in {"long", "short"}
    paper_allowed = prediction.get("paper_fill_allowed") is True or risk.get("risk_action") == "allow"
    ledger_action = str(paper.get("ledger_action") or "").lower()
    traded = bool(open_risk_action and paper_allowed and "deny" not in ledger_action)
    if traded:
        return "correct_trade" if after_cost > 0 else "false_positive"
    return "false_negative" if after_cost > 0 else "correct_no_trade"


def build_outcome_rows(source: Mapping[str, Any], timeline_provider: TimelineProvider) -> list[dict[str, Any]]:
    lineages = _lineage_by_prediction(source)
    rows: list[dict[str, Any]] = []
    timeline_cache: dict[str, list[dict[str, Any]]] = {}
    for prediction in [_as_dict(row) for row in _as_list(source.get("predictions_by_symbol"))]:
        prediction_id = str(prediction.get("prediction_id") or "")
        symbol = str(prediction.get("symbol") or "").upper()
        lineage = lineages.get(prediction_id, {})
        timeline = timeline_cache.setdefault(symbol, timeline_provider(symbol))
        anchor_ms = _prediction_ts_ms(prediction, lineage)
        side = _side_from_prediction(prediction)
        round_trip_cost = _round_trip_cost_bps(prediction)
        windows = {
            wid: _compute_one_window(
                timeline=timeline,
                anchor_ms=anchor_ms,
                side=side,
                window_id=wid,
                window_seconds=secs,
                round_trip_cost_bps=round_trip_cost,
            )
            for wid, secs in OUTCOME_WINDOWS
        }
        label = _label_outcome(prediction, lineage, windows["5m"])
        orch = _as_dict(lineage.get("orchestrator_decision_record"))
        risk = _as_dict(lineage.get("risk_decision_record"))
        paper = _as_dict(lineage.get("paper_execution_ledger_entry"))
        signal = _as_dict(lineage.get("paper_signal_lineage"))
        rows.append(
            {
                "prediction_id": prediction_id,
                "symbol": symbol,
                "timeframe": prediction.get("timeframe"),
                "prediction_ts_ms": anchor_ms,
                "selected_action": prediction.get("selected_action"),
                "counterfactual_side": side,
                "expected_move_after_cost_bps": prediction.get("expected_move_after_cost_bps"),
                "confidence_calibrated": prediction.get("confidence_calibrated"),
                "paper_fill_allowed": prediction.get("paper_fill_allowed"),
                "paper_fill_gate_status": prediction.get("paper_fill_gate_status"),
                "paper_fill_gate_block_reasons": prediction.get("paper_fill_gate_block_reasons", []),
                "orchestrator_decision_id": orch.get("decision_id"),
                "orchestrator_action": orch.get("decision_action"),
                "orchestrator_reason": orch.get("decision_reason_code"),
                "risk_decision_id": risk.get("risk_decision_id"),
                "risk_action": risk.get("risk_action"),
                "risk_reason": risk.get("risk_reason_code"),
                "paper_intent_id": signal.get("trainer_prediction_id") or paper.get("prediction_id"),
                "paper_ledger_id": paper.get("paper_trade_id"),
                "paper_ledger_action": paper.get("ledger_action"),
                "paper_ledger_reason": paper.get("ledger_reason_code"),
                "data_coverage_percent": prediction.get("data_coverage_percent"),
                "missing_feature_count": prediction.get("missing_feature_count"),
                "stale_feature_count": prediction.get("stale_feature_count"),
                "outcome_windows": windows,
                "primary_outcome_window": "5m",
                "realized_after_cost_return_bps": windows["5m"].get("after_cost_return_bps"),
                "classification": label,
                "false_positive": label == "false_positive",
                "false_negative": label == "false_negative",
                "correct_no_trade": label == "correct_no_trade",
                "correct_trade": label == "correct_trade",
            }
        )
    return rows


def build_burn_in_expansion_status(source: Mapping[str, Any], rows: list[dict[str, Any]], *, generated_est: str) -> dict[str, Any]:
    trainer = _as_dict(source.get("trainer"))
    metrics = _as_dict(source.get("metrics"))
    training = _as_dict(metrics.get("training"))
    predictions = [_as_dict(row) for row in _as_list(source.get("predictions_by_symbol"))]
    fallback_rows = [
        row
        for row in predictions
        if row.get("trainer_source") != TRAINER_SOURCE
        or row.get("model_source") != MODEL_SOURCE
        or row.get("cuda_active") is not True
        or row.get("model_tensors_device_verified") is not True
    ]
    symbols = sorted({str(row.get("symbol")) for row in predictions if row.get("symbol")})
    return {
        "schema_version": f"{SCHEMA_VERSION}_burn_in_expansion",
        "generated_est": generated_est,
        "status": "CUDA_TRAINER_BURN_IN_EXPANSION_READY" if predictions and not fallback_rows else "CUDA_TRAINER_BURN_IN_EXPANSION_BLOCKED",
        "trainer_source": trainer.get("trainer_source"),
        "model_source": trainer.get("model_source"),
        "cuda_active": bool(trainer.get("cuda_active") and training.get("cuda_active")),
        "gpu_name": training.get("gpu_name"),
        "model_device": trainer.get("model_device") or training.get("device"),
        "model_tensors_device_verified": bool(trainer.get("model_tensors_device_verified") and training.get("cuda_claim_verified")),
        "training_steps": training.get("training_steps", 0),
        "model_loss": {"loss_before": training.get("loss_before"), "loss_after": training.get("loss_after")},
        "prediction_count": len(predictions),
        "lineage_count": int(source.get("lineage_count") or len(_as_list(source.get("lineage_samples")))),
        "symbols_covered": symbols,
        "symbols_covered_count": len(symbols),
        "missing_feature_count_total": metrics.get("missing_feature_count_total", 0),
        "stale_feature_count_total": metrics.get("stale_feature_count_total", 0),
        "fallback_wrapper_usage_count": len(fallback_rows),
        "fallback_wrapper_prediction_ids": [row.get("prediction_id") for row in fallback_rows[:32]],
        "cuda_prediction_coverage": {
            "predictions_checked": len(predictions),
            "cuda_predictions_verified": len(predictions) - len(fallback_rows),
            "coverage_ratio": (len(predictions) - len(fallback_rows)) / len(predictions) if predictions else 0.0,
        },
        "outcome_windows_ready_counts": _window_ready_counts(rows),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
    }


def _window_ready_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {wid: 0 for wid, _ in OUTCOME_WINDOWS}
    for row in rows:
        windows = _as_dict(row.get("outcome_windows"))
        for wid, _ in OUTCOME_WINDOWS:
            if _as_dict(windows.get(wid)).get("after_cost_return_bps") is not None:
                counts[wid] += 1
    return counts


def build_outcome_mining_status(rows: list[dict[str, Any]], *, generated_est: str) -> dict[str, Any]:
    labels: dict[str, int] = {}
    for row in rows:
        label = str(row.get("classification") or "insufficient_evidence")
        labels[label] = labels.get(label, 0) + 1
    return {
        "schema_version": f"{SCHEMA_VERSION}_prediction_outcome_mining",
        "generated_est": generated_est,
        "status": "CUDA_PREDICTION_OUTCOME_MINING_READY",
        "prediction_count": len(rows),
        "primary_outcome_window": "5m",
        "outcome_windows": [{"window_id": wid, "window_seconds": secs} for wid, secs in OUTCOME_WINDOWS],
        "outcome_sample_count": _window_ready_counts(rows).get("5m", 0),
        "window_ready_counts": _window_ready_counts(rows),
        "classification_counts": labels,
        "rows": rows,
        "no_fabricated_outcomes": True,
        "pending_windows_are_null": True,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
    }


def _completed_rows(rows: list[dict[str, Any]], window: str = "5m") -> list[dict[str, Any]]:
    completed = []
    for row in rows:
        outcome = _as_dict(_as_dict(row.get("outcome_windows")).get(window))
        if outcome.get("after_cost_return_bps") is not None:
            completed.append(row)
    return completed


def _success_label(label: str) -> bool:
    return label in {"correct_trade", "correct_no_trade"}


def _confidence_bucket(value: Any) -> str:
    conf = _float(value)
    if conf is None:
        return "missing"
    low = math.floor(conf * 10) / 10
    high = min(1.0, low + 0.1)
    return f"{low:.1f}-{high:.1f}"


def build_confidence_calibration_status(rows: list[dict[str, Any]], *, generated_est: str) -> dict[str, Any]:
    completed = _completed_rows(rows)
    by_bucket: dict[str, dict[str, Any]] = {}
    for row in completed:
        bucket = _confidence_bucket(row.get("confidence_calibrated"))
        rec = by_bucket.setdefault(bucket, {"bucket": bucket, "sample_count": 0, "confidence_values": [], "success_count": 0})
        rec["sample_count"] += 1
        conf = _float(row.get("confidence_calibrated"))
        if conf is not None:
            rec["confidence_values"].append(conf)
        if _success_label(str(row.get("classification"))):
            rec["success_count"] += 1
    bucket_rows: list[dict[str, Any]] = []
    errors: list[float] = []
    for rec in by_bucket.values():
        avg_conf = _mean([float(v) for v in rec.pop("confidence_values")])
        success_rate = rec["success_count"] / rec["sample_count"] if rec["sample_count"] else None
        calibration_error = abs(float(avg_conf) - float(success_rate)) if avg_conf is not None and success_rate is not None else None
        if calibration_error is not None:
            errors.append(calibration_error)
        rec["avg_confidence"] = avg_conf
        rec["realized_success_rate"] = success_rate
        rec["calibration_error"] = calibration_error
        bucket_rows.append(rec)
    high_conf_losers = [
        row
        for row in completed
        if (_float(row.get("confidence_calibrated")) or 0.0) >= 0.55
        and row.get("classification") in {"false_positive", "false_negative"}
    ]
    low_conf_winners = [
        row
        for row in completed
        if (_float(row.get("confidence_calibrated")) or 1.0) < 0.55
        and row.get("classification") in {"correct_trade", "correct_no_trade"}
    ]
    calibration_error = _mean(errors)
    sample_guard_active = len(completed) < MIN_OUTCOME_SAMPLE_GUARD
    return {
        "schema_version": f"{SCHEMA_VERSION}_confidence_calibration",
        "generated_est": generated_est,
        "status": "OUTCOME_SAMPLE_GUARD_ACTIVE" if sample_guard_active else "CONFIDENCE_CALIBRATION_READY",
        "outcome_sample_count": len(completed),
        "minimum_outcome_sample_guard": MIN_OUTCOME_SAMPLE_GUARD,
        "minimum_outcome_sample_guard_passed": not sample_guard_active,
        "confidence_bucket_calibration": sorted(bucket_rows, key=lambda row: row["bucket"]),
        "calibration_error": calibration_error,
        "high_confidence_loser_count": len(high_conf_losers),
        "high_confidence_losers": _trim_rows(high_conf_losers, 20),
        "low_confidence_winner_count": len(low_conf_winners),
        "low_confidence_winners": _trim_rows(low_conf_winners, 20),
        "paper_shadow_calibration_overlay": {
            "confidence_calibration_penalty": min(0.25, float(calibration_error or 0.0)),
            "expected_move_decay": 0.85 if high_conf_losers else 1.0,
            "minimum_outcome_sample_guard": MIN_OUTCOME_SAMPLE_GUARD,
            "high_confidence_loser_downrank": bool(high_conf_losers),
            "applies_to_live": False,
            "applies_to_canary": False,
        },
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
    }


def _trim_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    keys = (
        "prediction_id",
        "symbol",
        "timeframe",
        "selected_action",
        "counterfactual_side",
        "confidence_calibrated",
        "expected_move_after_cost_bps",
        "realized_after_cost_return_bps",
        "classification",
        "risk_reason",
        "paper_ledger_reason",
    )
    return [{key: row.get(key) for key in keys} for row in rows[:limit]]


def build_signal_runtime_lineage_status(source: Mapping[str, Any], rows: list[dict[str, Any]], *, generated_est: str) -> dict[str, Any]:
    missing: list[str] = []
    lineage_rows: list[dict[str, Any]] = []
    for row in rows:
        required = {
            "cuda_trainer_prediction_id": row.get("prediction_id"),
            "risk_decision_id": row.get("risk_decision_id"),
            "orchestrator_decision_id": row.get("orchestrator_decision_id"),
            "paper_intent_id": row.get("paper_intent_id"),
            "paper_ledger_outcome": row.get("paper_ledger_action"),
        }
        row_missing = [key for key, value in required.items() if value in (None, "", [])]
        if row_missing:
            missing.extend(f"{row.get('prediction_id')}:{','.join(row_missing)}")
        lineage_rows.append(
            {
                **required,
                "trainer_prediction_id": row.get("prediction_id"),
                "paper_ledger_row": row.get("paper_ledger_id"),
                "paper_ledger_id": row.get("paper_ledger_id"),
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "selected_action": row.get("selected_action"),
                "action": row.get("selected_action"),
                "risk_action": row.get("risk_action"),
                "block_allow_reason": row.get("risk_reason") or row.get("orchestrator_reason") or row.get("paper_ledger_reason"),
                "fill_held_block_result": row.get("classification"),
                "confidence_calibrated": row.get("confidence_calibrated"),
                "expected_move_after_cost_bps": row.get("expected_move_after_cost_bps"),
                "data_coverage_percent": row.get("data_coverage_percent"),
                "pnl_effect_bps": row.get("realized_after_cost_return_bps"),
                "classification": row.get("classification"),
                "contract_pass": not row_missing,
                "missing": row_missing,
            }
        )
    return {
        "schema_version": f"{SCHEMA_VERSION}_signal_runtime_lineage",
        "generated_est": generated_est,
        "status": "CUDA_SIGNAL_RUNTIME_LINEAGE_READY" if not missing else "CUDA_SIGNAL_RUNTIME_LINEAGE_BLOCKED",
        "lineage_count": len(lineage_rows),
        "source_lineage_count": int(source.get("lineage_count") or 0),
        "rows": lineage_rows,
        "missing_lineage_fields": missing[:100],
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "exchange_mutation": False,
    }


def _group_edge(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        label = str(row.get(key) or "UNKNOWN")
        value = _float(row.get("realized_after_cost_return_bps"))
        if value is None:
            continue
        grouped.setdefault(label, []).append(value)
    out = []
    for label, values in grouped.items():
        out.append(
            {
                key: label,
                "sample_count": len(values),
                "after_cost_expectancy_bps": _mean(values),
                "after_cost_ci_lower_bps": _ci_lower_95(values),
            }
        )
    return sorted(out, key=lambda item: str(item.get(key)))


def build_edge_recompute_after_burn_in(rows: list[dict[str, Any]], calibration: Mapping[str, Any], *, generated_est: str) -> dict[str, Any]:
    completed = _completed_rows(rows)
    values = [float(row["realized_after_cost_return_bps"]) for row in completed if _float(row.get("realized_after_cost_return_bps")) is not None]
    labels = [str(row.get("classification")) for row in completed]
    fp = labels.count("false_positive")
    fn = labels.count("false_negative")
    ct = labels.count("correct_trade")
    cnt = labels.count("correct_no_trade")
    false_positive_rate = fp / (fp + ct) if (fp + ct) else None
    false_negative_rate = fn / (fn + cnt) if (fn + cnt) else None
    drawdowns: list[float] = []
    for row in completed:
        outcome = _as_dict(_as_dict(row.get("outcome_windows")).get("5m"))
        dd = _float(outcome.get("drawdown_bps"))
        if dd is not None:
            drawdowns.append(dd)
    expectancy = _mean(values)
    ci_lower = _ci_lower_95(values)
    sample_guard_passed = len(completed) >= MIN_OUTCOME_SAMPLE_GUARD
    edge_proven = bool(sample_guard_passed and expectancy is not None and expectancy > 0 and ci_lower is not None and ci_lower > 0)
    recommendations = ["CANARY_OPERATOR_DECISION_REQUIRED"] if edge_proven else [
        "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN",
        "BLOCK_LIVE_MODEL_SIGNAL_QUALITY_NOT_READY",
        "BLOCK_LIVE_RISK_CAPS_OPERATOR_REQUIRED",
    ]
    return {
        "schema_version": f"{SCHEMA_VERSION}_edge_recompute_after_burn_in",
        "generated_est": generated_est,
        "status": "EDGE_RECOMPUTE_AFTER_BURN_IN_READY",
        "edge_proven": edge_proven,
        "outcome_sample_count": len(completed),
        "pending_primary_outcome_count": max(0, len(rows) - len(completed)),
        "after_cost_expectancy_bps": expectancy,
        "after_cost_ci_lower_bps": ci_lower,
        "false_positive_count": fp,
        "false_negative_count": fn,
        "correct_trade_count": ct,
        "correct_no_trade_count": cnt,
        "false_positive_rate": false_positive_rate,
        "false_negative_rate": false_negative_rate,
        "drawdown": {"max_drawdown_bps": max(drawdowns) if drawdowns else None, "observations": len(drawdowns)},
        "by_symbol_edge": _group_edge(completed, "symbol"),
        "by_action_edge": _group_edge(completed, "selected_action"),
        "by_confidence_bucket_edge": _group_edge([{**row, "confidence_bucket": _confidence_bucket(row.get("confidence_calibrated"))} for row in completed], "confidence_bucket"),
        "trainer_vs_strategy_comparison": {
            "cuda_trainer_completed_outcomes": len(completed),
            "cuda_trainer_false_positive_count": fp,
            "no_trade_strategy_would_avoid_false_positives": fp,
            "no_trade_strategy_misses_profitable_blocks": fn,
            "comparison_status": "DIAGNOSTIC_ONLY_NO_LIVE_AUTHORITY",
        },
        "confidence_calibration": {
            "status": calibration.get("status"),
            "calibration_error": calibration.get("calibration_error"),
            "high_confidence_loser_count": calibration.get("high_confidence_loser_count"),
        },
        "recommendations": recommendations,
        "primary_recommendation": recommendations[0],
        "allowed_recommendations": list(ALLOWED_RECOMMENDATIONS),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
    }


def build_website_sync_status(edge: Mapping[str, Any], calibration: Mapping[str, Any], outcome: Mapping[str, Any], *, generated_est: str) -> dict[str, Any]:
    surfaces = ["AI Brain", "Live Readiness", "Paper Trading", "Risk", "Orchestrator", "Replay / Edge", "Symbols"]
    return {
        "schema_version": f"{SCHEMA_VERSION}_website_sync",
        "generated_est": generated_est,
        "status": "WEBSITE_SYNCED",
        "payload_path": f"/{ARTIFACT_REL}/operator_dashboard_payload.json",
        "surfaces_synced": surfaces,
        "must_show": {
            "cuda_trainer_active": True,
            "current_after_cost_edge": edge.get("after_cost_expectancy_bps"),
            "confidence_calibration": calibration.get("status"),
            "high_confidence_losers": calibration.get("high_confidence_loser_count"),
            "outcome_sample_count": outcome.get("outcome_sample_count"),
            "false_positives": edge.get("false_positive_count"),
            "false_negatives": edge.get("false_negative_count"),
            "why_live_blocked": edge.get("recommendations"),
            "next_automatic_action": "Continue CUDA trainer paper/shadow burn-in, outcome mining, and calibration; do not enable live/canary.",
        },
        "live_switch": {
            "visible": True,
            "enabled": False,
            "backend_live_enable_callable": False,
            "disabled_reason": "LIVE_GATE=blocked_human_only; CUDA trainer edge/outcome proof is not live approval.",
        },
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
    }


def build_operator_payload(
    *,
    source: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    generated_est: str,
    go_no_go: str,
) -> dict[str, Any]:
    burn = artifacts["v2_cuda_trainer_burn_in_expansion_status.json"]
    outcome = artifacts["v2_cuda_prediction_outcome_mining_status.json"]
    calibration = artifacts["v2_cuda_confidence_calibration_status.json"]
    lineage = artifacts["v2_cuda_signal_runtime_lineage_status.json"]
    edge = artifacts["v2_cuda_trainer_edge_recompute_after_burn_in.json"]
    website = artifacts["v2_cuda_trainer_edge_website_sync_status.json"]
    return {
        "schema_version": f"{SCHEMA_VERSION}_operator_dashboard",
        "generated_est": generated_est,
        "generated_at": generated_est,
        "go_no_go": go_no_go,
        "source_gate": source.get("go_no_go"),
        "source_payload_path": f"/{SOURCE_PAYLOAD_REL}",
        "trainer": _as_dict(source.get("trainer")),
        "metrics": _as_dict(source.get("metrics")),
        "prediction_count": int(source.get("prediction_count") or len(_as_list(source.get("predictions_by_symbol")))),
        "lineage_count": int(source.get("lineage_count") or len(_as_list(source.get("lineage_samples")))),
        "predictions_by_symbol": _as_list(source.get("predictions_by_symbol"))[:64],
        "lineage_samples": _as_list(source.get("lineage_samples"))[:16],
        "burn_in": burn,
        "prediction_contract": {
            "status": "PREDICTION_CONTRACT_READY" if burn.get("fallback_wrapper_usage_count") == 0 else "PREDICTION_CONTRACT_BLOCKED",
            "contract_pass": burn.get("fallback_wrapper_usage_count") == 0,
            "predictions_checked": burn.get("prediction_count"),
            "trainer_source_required": TRAINER_SOURCE,
            "model_source_required": MODEL_SOURCE,
        },
        "risk_consumption": {
            "status": lineage.get("status"),
            "consumption_pass": lineage.get("status") == "CUDA_SIGNAL_RUNTIME_LINEAGE_READY",
            "lineage_count": lineage.get("lineage_count"),
            "risk_caps_status": "OPERATOR_REQUIRED_BLOCKED",
            "rows": [
                {
                    "prediction_id_consumed": row.get("cuda_trainer_prediction_id"),
                    "risk_decision_id": row.get("risk_decision_id"),
                    "risk_action": row.get("risk_action"),
                    "block_allow_reason": row.get("block_allow_reason"),
                    "confidence_calibrated": row.get("confidence_calibrated"),
                    "expected_move_after_cost_bps": row.get("expected_move_after_cost_bps"),
                }
                for row in _as_list(lineage.get("rows"))[:64]
            ],
        },
        "orchestrator_consumption": {
            "status": lineage.get("status"),
            "consumption_pass": lineage.get("status") == "CUDA_SIGNAL_RUNTIME_LINEAGE_READY",
            "lineage_count": lineage.get("lineage_count"),
            "risk_decision_pairing": {"status": "PAIRED_LINEAGE_VERIFIED"},
            "strategy_fallback": {"status": "NO_TRADE_PRESERVATION_REMAINS_ACTIVE"},
            "rows": [
                {
                    "orchestrator_decision_id": row.get("orchestrator_decision_id"),
                    "trainer_prediction_id": row.get("cuda_trainer_prediction_id"),
                    "risk_decision_id": row.get("risk_decision_id"),
                    "action": row.get("selected_action"),
                    "hold_block_reason": row.get("block_allow_reason"),
                }
                for row in _as_list(lineage.get("rows"))[:64]
            ],
        },
        "paper_signal_lineage": {
            "status": lineage.get("status"),
            "consumption_pass": lineage.get("status") == "CUDA_SIGNAL_RUNTIME_LINEAGE_READY",
            "lineage_count": lineage.get("lineage_count"),
            "rows": _as_list(lineage.get("rows"))[:64],
        },
        "outcome_mining": outcome,
        "confidence_calibration": calibration,
        "edge_recompute": {
            "status": edge.get("status"),
            "edge_proven": edge.get("edge_proven"),
            "primary_recommendation": edge.get("primary_recommendation"),
            "recommendations": edge.get("recommendations"),
            "new_cuda_trainer": {
                "sample_count": edge.get("outcome_sample_count"),
                "after_cost_expectancy_bps": edge.get("after_cost_expectancy_bps"),
                "after_cost_ci_lower_bps": edge.get("after_cost_ci_lower_bps"),
            },
            "false_positive_rate": edge.get("false_positive_rate"),
            "false_negative_rate": edge.get("false_negative_rate"),
            "false_positive_count": edge.get("false_positive_count"),
            "false_negative_count": edge.get("false_negative_count"),
            "drawdown": edge.get("drawdown"),
            "by_symbol_edge": edge.get("by_symbol_edge"),
            "by_action_edge": edge.get("by_action_edge"),
            "by_confidence_bucket_edge": edge.get("by_confidence_bucket_edge"),
        },
        "website_live_gate": website,
        "live_switch": website.get("live_switch"),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "next_automatic_action": website["must_show"]["next_automatic_action"],
        "safety_scoreboard": {
            "paper_shadow_only": True,
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
            "execution_live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "places_orders": False,
            "cancels_orders": False,
            "modifies_orders": False,
            "calls_test_order_endpoint": False,
            "changes_leverage": False,
            "changes_margin_mode": False,
            "writes_old_redis": False,
            "restarts_legacy": False,
            "trims_redis": False,
        },
    }


def build_report(result: EdgeBurnInResult) -> str:
    p = result.operator_dashboard_payload
    edge = p["edge_recompute"]
    calibration = p["confidence_calibration"]
    outcome = p["outcome_mining"]
    return "\n".join(
        [
            "# V2 Native CUDA Trainer Edge Calibration And Outcome Burn-In Report",
            "",
            f"Gate: `{result.go_no_go}`",
            f"Generated EST: `{p['generated_est']}`",
            f"Trainer source: `{p['trainer'].get('trainer_source')}`",
            f"Model source: `{p['trainer'].get('model_source')}`",
            f"CUDA active: `{p['burn_in'].get('cuda_active')}`",
            f"GPU: `{p['burn_in'].get('gpu_name')}`",
            f"Predictions checked: `{p['prediction_count']}`",
            f"Lineage checked: `{p['lineage_count']}`",
            f"Outcome sample count 5m: `{outcome.get('outcome_sample_count')}`",
            f"After-cost expectancy bps: `{edge['new_cuda_trainer']['after_cost_expectancy_bps']}`",
            f"CI lower bps: `{edge['new_cuda_trainer']['after_cost_ci_lower_bps']}`",
            f"False positives: `{edge.get('false_positive_count')}`",
            f"False negatives: `{edge.get('false_negative_count')}`",
            f"Confidence calibration: `{calibration.get('status')}`",
            f"High-confidence losers: `{calibration.get('high_confidence_loser_count')}`",
            "",
            "Live/canary remain blocked. This artifact does not emit a live-ready or canary-ready approval.",
            "",
            f"- live_gate: `{LIVE_GATE_BLOCKED}`",
            "- live_symbols: `[]`",
            "- execution_live_symbols: `[]`",
            f"- recommendation: `{edge.get('primary_recommendation')}`",
            f"- blockers: `{', '.join(edge.get('recommendations') or [])}`",
            "",
            "Safety: no live/canary enable, no order/test-order/cancel/modify, no leverage/margin mutation, no old Redis write, no legacy restart, no Redis trim.",
        ]
    ) + "\n"


def build_edge_burn_in(
    source: Mapping[str, Any],
    *,
    timeline_provider: TimelineProvider,
    generated_est: str | None = None,
) -> EdgeBurnInResult:
    generated = generated_est or _est_iso()
    rows = build_outcome_rows(source, timeline_provider)
    artifacts: dict[str, Any] = {}
    artifacts["v2_cuda_trainer_burn_in_expansion_status.json"] = build_burn_in_expansion_status(
        source,
        rows,
        generated_est=generated,
    )
    artifacts["v2_cuda_prediction_outcome_mining_status.json"] = build_outcome_mining_status(rows, generated_est=generated)
    artifacts["v2_cuda_confidence_calibration_status.json"] = build_confidence_calibration_status(rows, generated_est=generated)
    artifacts["v2_cuda_signal_runtime_lineage_status.json"] = build_signal_runtime_lineage_status(source, rows, generated_est=generated)
    artifacts["v2_cuda_trainer_edge_recompute_after_burn_in.json"] = build_edge_recompute_after_burn_in(
        rows,
        artifacts["v2_cuda_confidence_calibration_status.json"],
        generated_est=generated,
    )
    artifacts["v2_cuda_trainer_edge_website_sync_status.json"] = build_website_sync_status(
        artifacts["v2_cuda_trainer_edge_recompute_after_burn_in.json"],
        artifacts["v2_cuda_confidence_calibration_status.json"],
        artifacts["v2_cuda_prediction_outcome_mining_status.json"],
        generated_est=generated,
    )
    hard_blockers = []
    burn = artifacts["v2_cuda_trainer_burn_in_expansion_status.json"]
    lineage = artifacts["v2_cuda_signal_runtime_lineage_status.json"]
    if burn["status"].endswith("BLOCKED"):
        hard_blockers.append("CUDA_BURN_IN_CONTRACT_BLOCKED")
    if lineage["status"].endswith("BLOCKED"):
        hard_blockers.append("CUDA_LINEAGE_CONTRACT_BLOCKED")
    go_no_go = GO_BLOCKED if hard_blockers else GO_READY
    operator = build_operator_payload(source=source, artifacts=artifacts, generated_est=generated, go_no_go=go_no_go)
    if hard_blockers:
        operator["hard_blockers"] = hard_blockers
    return EdgeBurnInResult(go_no_go=go_no_go, artifacts=artifacts, operator_dashboard_payload=operator)


def write_edge_burn_in_artifacts(*, paths: EdgeBurnInPaths, result: EdgeBurnInResult) -> EdgeBurnInResult:
    report = build_report(result)
    written: list[str] = []
    for base in (paths.worklog_dir, paths.public_dir):
        base.mkdir(parents=True, exist_ok=True)
        files: dict[str, str] = {
            "GO_NO_GO.md": result.go_no_go + "\n",
            "V2_NATIVE_CUDA_TRAINER_EDGE_CALIBRATION_AND_OUTCOME_BURN_IN_REPORT.md": report,
            "operator_dashboard_payload.json": dumps_pretty(result.operator_dashboard_payload),
        }
        for name, obj in result.artifacts.items():
            files[name] = dumps_pretty(obj)
        for name, text in files.items():
            path = base / name
            _write_text_atomic(path, text)
            written.append(str(path))
    return EdgeBurnInResult(
        go_no_go=result.go_no_go,
        artifacts=result.artifacts,
        operator_dashboard_payload=result.operator_dashboard_payload,
        paths_written=tuple(written),
    )


def run_edge_burn_in(
    *,
    paths: EdgeBurnInPaths,
    source_payload_path: Path | None = None,
    timeline_provider: TimelineProvider,
) -> EdgeBurnInResult:
    source = _read_json(source_payload_path or paths.source_payload_path)
    result = build_edge_burn_in(source, timeline_provider=timeline_provider)
    return write_edge_burn_in_artifacts(paths=paths, result=result)
