from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any

from .snapshot import snapshot_from_prediction

EST = timezone(timedelta(hours=-4))


def _est_now() -> str:
    return datetime.now(EST).isoformat(timespec="seconds")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _json(raw: Any) -> Any | None:
    if not raw:
        return None
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return None


def _scan_predictions(redis_client: Any, limit: int = 500) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if redis_client is None:
        return rows
    try:
        for key in redis_client.scan_iter(match="v2:prediction:*", count=500):
            payload = _json(redis_client.get(str(key)))
            if isinstance(payload, dict):
                payload = dict(payload)
                payload["_redis_key"] = str(key)
                rows.append(payload)
            if len(rows) >= limit:
                break
    except Exception:
        return rows
    return rows


def _scan_risk_decisions(redis_client: Any) -> dict[str, dict[str, Any]]:
    if redis_client is None:
        return {}
    payload = _json(redis_client.get("v2:risk:decisions"))
    if not isinstance(payload, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        prediction_id = str(row.get("prediction_id") or "")
        if prediction_id:
            out[prediction_id] = row
    return out


def _scan_paper_candidates(redis_client: Any) -> dict[str, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if redis_client is None:
        return {}
    ledger = _json(redis_client.get("v2:paper:ledger"))
    if isinstance(ledger, dict):
        for key in (
            "accepted",
            "current_cycle_accepted",
            "blocked",
            "shadow_observations",
            "held_by_paper_fill_gate",
        ):
            rows.extend([row for row in ledger.get(key) or [] if isinstance(row, dict)])
    held = _json(redis_client.get("v2:paper:intents_held_by_paper_fill_gate"))
    if isinstance(held, list):
        rows.extend([row for row in held if isinstance(row, dict)])
    ranked: dict[str, dict[str, Any]] = {}
    for row in rows:
        prediction_id = str(row.get("prediction_id") or row.get("source_prediction_id") or "")
        if not prediction_id:
            continue
        current = ranked.get(prediction_id)
        if current is None:
            ranked[prediction_id] = row
            continue
        current_score = 1 if current.get("decision") == "ACCEPTED_PAPER_FILL" else 0
        new_score = 1 if row.get("decision") == "ACCEPTED_PAPER_FILL" else 0
        if new_score >= current_score:
            ranked[prediction_id] = row
    return ranked


def build_debugger_payload(redis_client: Any = None, integrity_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    integrity_by_prediction = {
        str(row.get("source_lineage", {}).get("prediction_id") or ""): row
        for row in (integrity_rows or [])
        if isinstance(row, dict)
    }
    predictions = _scan_predictions(redis_client)
    predictions_by_id = {
        str(prediction.get("prediction_id") or ""): prediction
        for prediction in predictions
        if isinstance(prediction, dict) and prediction.get("prediction_id")
    }
    paper_candidates_by_prediction = _scan_paper_candidates(redis_client)
    risk_by_prediction = _scan_risk_decisions(redis_client)
    snapshots = []
    for prediction_id in sorted(
        set(predictions_by_id.keys())
        | set(paper_candidates_by_prediction.keys())
        | set(risk_by_prediction.keys())
    ):
        prediction = predictions_by_id.get(prediction_id) or {
            "prediction_id": prediction_id,
            "symbol": (paper_candidates_by_prediction.get(prediction_id) or {}).get("symbol"),
            "timeframe": (paper_candidates_by_prediction.get(prediction_id) or {}).get("timeframe"),
        }
        integrity = integrity_by_prediction.get(prediction_id) or {}
        snapshots.append(
            snapshot_from_prediction(
                prediction,
                integrity,
                paper_candidate=paper_candidates_by_prediction.get(prediction_id),
                risk_decision=risk_by_prediction.get(prediction_id),
            )
        )
    return {
        "schema_version": "v2_replay_debugger_payload_v1",
        "generated_est": _est_now(),
        "generated_utc": _utc_now(),
        "snapshots_available": len(snapshots),
        "snapshots": snapshots[:100],
        "query_modes": [
            "--decision-id <id>",
            "--prediction-id <id>",
            "--symbol BTCUSDT --latest",
        ],
        "source_redis_pattern": "v2:prediction:*",
        "writes_exchange_orders": False,
        "writes_old_redis": False,
    }


def query_snapshots(
    payload: dict[str, Any],
    *,
    decision_id: str | None = None,
    prediction_id: str | None = None,
    symbol: str | None = None,
    latest: bool = False,
) -> list[dict[str, Any]]:
    rows = [row for row in payload.get("snapshots") or [] if isinstance(row, dict)]
    if decision_id:
        rows = [row for row in rows if str(row.get("decision_id")) == decision_id]
    if prediction_id:
        rows = [row for row in rows if str(row.get("prediction_id")) == prediction_id]
    if symbol:
        rows = [row for row in rows if str(row.get("symbol") or "").upper() == symbol.upper()]
    if latest and rows:
        return rows[:1]
    return rows
