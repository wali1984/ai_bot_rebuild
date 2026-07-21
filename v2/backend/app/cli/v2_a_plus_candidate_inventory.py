"""Current-session A+ live-canary candidate inventory.

This command reads runtime Redis payloads, writes inventory artifacts, and
publishes paper-only exploration materialization queue records. It does not
submit orders or mutate exchange state. Canonical risk/orchestrator decision
records and indexes are producer-owned inputs: inventory only observes them.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from v2.backend.app.domain.trainer_prediction_output import (
    PREDICTION_DIRECTION_FLAT,
    PREDICTION_DIRECTION_LONG,
    PREDICTION_DIRECTION_SHORT,
    PREDICTION_FRESHNESS_FRESH,
    PREDICTION_FRESHNESS_MISSING,
    PREDICTION_FRESHNESS_STALE,
    TrainerPredictionRecord,
)
from v2.backend.app.services.allocator import build_allocator_simulation
from v2.backend.app.services.orchestrator_decision import assemble_orchestrator_decision_record
from v2.backend.app.services.paper_exploration import (
    PAPER_RISK_CONTROLLER_EXPLORATION_TIER,
    build_paper_exploration_exit_plan,
    build_paper_exploration_safety_truth,
    build_paper_exploration_row_resolution,
    evaluate_paper_risk_controller_exploration,
    exploration_paper_fill_gate,
    exploration_sizing_controls,
)
from v2.backend.app.services.paper_trade_management.entry_gate import (
    DEFAULT_PAPER_ENTRY_ALLOWED_TIMEFRAMES,
    DEFAULT_PAPER_ENTRY_OPERATOR_SYMBOL_EXCLUSION_LIST,
    expected_move_after_cost_favorable_for_side,
)
from v2.backend.app.services.preemptive_edge_control import evaluate_candidate
from v2.backend.app.services.risk_gateway import assemble_risk_decision_record


SCHEMA_VERSION = "v2_a_plus_candidate_inventory_v1"
TARGET_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
PREEMPTIVE_MATRIX_KEY = "v2:paper:preemptive_candidate_decision_matrix"
PREEMPTIVE_STATUS_KEY = "v2:paper:preemptive_edge_control_status"
CONTINUOUS_GUARDIAN_GATE_KEY = "v2:continuous_edge_guardian:a_grade_execution_gate"
LIVE_GATE_KEY = "v2:live_gate:state"
EXPLORATION_MATERIALIZATION_QUEUE_KEY = "v2:paper:exploration:materialization_queue"
EXPLORATION_MATERIALIZATION_QUEUE_STATUS_KEY = (
    "v2:paper:exploration:materialization_queue_status"
)
PAPER_EXPLORATION_MATERIALIZATION_COUNTERFACTUAL_KEY = (
    "v2:trainer:paper_exploration_materialization_counterfactual_feedback"
)
PAPER_PERFORMANCE_CIRCUIT_BREAKER_STATUS_KEY = (
    "v2:paper:performance_circuit_breaker_status"
)
PAPER_TRAINING_EVIDENCE_TTL_SECONDS = 30 * 24 * 60 * 60
ALLOCATOR_MARKET_STATE_INTEGRITY_MIN_SCORE = 70.0
DEFAULT_ORCHESTRATOR_LOW_CONFIDENCE_THRESHOLD = 0.55
PAPER_SIGNAL_STALE_SECONDS = 900
PAPER_SIGNAL_ADAPTIVE_STALE_OPERATOR_MIN_SECONDS = 120
PAPER_SIGNAL_ADAPTIVE_STALE_CANDLE_MULTIPLIER = 1
PAPER_EXPLORATION_MATERIALIZATION_ALLOWED_ENTRY_TIMEFRAMES = (
    DEFAULT_PAPER_ENTRY_ALLOWED_TIMEFRAMES
)
PAPER_EXPLORATION_MATERIALIZATION_SYMBOL_EXCLUSION_LIST = (
    DEFAULT_PAPER_ENTRY_OPERATOR_SYMBOL_EXCLUSION_LIST
)
PAPER_NEGATIVE_BUCKET_QUARANTINE_MIN_COUNT = int(
    os.getenv("PAPER_NEGATIVE_BUCKET_QUARANTINE_MIN_COUNT", "2")
)

ALLOWED_BLOCKER_CLASSES = (
    "DATA_FRESHNESS_BLOCKER",
    "FEATURE_COVERAGE_BLOCKER",
    "MICROSTRUCTURE_TRUST_BLOCKER",
    "PROVIDER_MISSING_BLOCKER",
    "TRAINER_CONFIDENCE_BLOCKER",
    "EXPECTED_NET_EDGE_BLOCKER",
    "PREEMPTIVE_LOSS_PROBABILITY_BLOCKER",
    "RISK_GATEWAY_BLOCKER",
    "ORCHESTRATOR_BLOCKER",
    "ALLOCATOR_BLOCKER",
    "POSITION_LIMIT_BLOCKER",
    "LIVE_DRY_RUN_PACKET_BLOCKER",
    "SIGNED_READ_OPERATOR_BLOCKER",
)

ALLOW_RISK_VALUES = {"PASS", "ALLOW", "ALLOWED", "APPROVE", "APPROVED"}
ALLOW_ORCHESTRATOR_VALUES = {
    "PASS",
    "ALLOW",
    "ALLOWED",
    "APPROVE",
    "APPROVED",
    "OPEN_LONG",
    "OPEN_SHORT",
}
ALLOW_ALLOCATOR_VALUES = {"PASS", "ALLOW", "ALLOWED", "APPROVE", "APPROVED", "ALLOW_WITH_SIZE"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _format_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00",
        "Z",
    )


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "pass", "allow", "allowed"}


def _explicit_false(value: Any) -> bool:
    if isinstance(value, bool):
        return value is False
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value == 0
    return str(value).strip().lower() in {"0", "false", "no", "n", "off"}


_CONTRADICTED_MICROSTRUCTURE_TRUST_REASONS = {
    "MICROSTRUCTURE_TRUST_MISSING",
    "MICROSTRUCTURE_TRUST_LOW",
    "MICROSTRUCTURE_TRUST_FAIL_CLOSED",
    "HIGH_CONFIDENCE_WITHOUT_MICROSTRUCTURE_TRUST_EVIDENCE",
    "FVG_CONFLUENCE_WITHOUT_SUFFICIENT_MICROSTRUCTURE_TRUST",
}


def _normalized_score(value: Any) -> float | None:
    score = _float(value)
    if score is None:
        return None
    return score / 100.0 if score > 1.0 else score


def _drop_contradicted_microstructure_trust_reasons(
    reasons: list[str],
    *,
    microstructure_trust_score: Any,
    composite_microstructure_trust_score: Any,
    microstructure_trust_state: Any,
    microstructure_trust_status: Any = None,
) -> list[str]:
    state = str(microstructure_trust_state or "").strip().upper()
    status = str(microstructure_trust_status or "").strip().upper()
    if state in {"UNSAFE", "FAIL_CLOSED"} or any(
        token in status for token in ("REJECTED", "AFTER_DECISION", "STALE")
    ):
        return reasons
    trust_score = _first_present(
        _normalized_score(composite_microstructure_trust_score),
        _normalized_score(microstructure_trust_score),
    )
    if trust_score is None or trust_score < 0.65:
        return reasons
    return [
        reason
        for reason in reasons
        if str(reason).upper() not in _CONTRADICTED_MICROSTRUCTURE_TRUST_REASONS
    ]


def _inventory_final_state(
    *,
    a_plus_candidate_count: int,
    live_ready_candidate_count: int,
    hard_fail: bool,
    primary_blocker: Any,
) -> str:
    if live_ready_candidate_count > 0:
        return "A_PLUS_CANDIDATE_PRESENT_LIVE_BLOCKED_HUMAN_ONLY"
    if a_plus_candidate_count > 0:
        return "A_PLUS_PAPER_CANDIDATE_PRESENT_LIVE_BLOCKED_HUMAN_ONLY"
    if hard_fail:
        return "A_PLUS_INVENTORY_HARD_FAIL_LIVE_BLOCKED"
    if primary_blocker:
        return "A_PLUS_BLOCKERS_ACTIVE_LIVE_BLOCKED"
    return "NO_CURRENT_A_PLUS_CANDIDATE_LIVE_BLOCKED"


def _canonical_materialization_no_fill_reason(reason: Any) -> str | None:
    mapping = {
        "ALL_CURRENT_ROWS_MARKET_INTEGRITY_BLOCKED": "ALL_ROWS_MARKET_INTEGRITY_BLOCKED",
        "ALL_CURRENT_ROWS_PAPER_PERFORMANCE_CIRCUIT_BREAKER_BLOCKED": "ALL_ROWS_TRUE_PERFORMANCE_CIRCUIT_BLOCKED",
        "ALL_CURRENT_ROWS_TRUE_BUCKET_QUARANTINE": "ALL_ROWS_TRUE_BUCKET_QUARANTINE",
        "ALL_CURRENT_ROWS_TRUE_RISK_BLOCKED": "ALL_ROWS_TRUE_RISK_BLOCKED",
        "ALL_CURRENT_ROWS_TRUE_ORCHESTRATOR_BLOCKED": "ALL_ROWS_TRUE_ORCHESTRATOR_BLOCKED",
        "ALL_CURRENT_ROWS_TRUE_ALLOCATOR_BLOCKED": "ALL_ROWS_TRUE_ALLOCATOR_BLOCKED",
        "ALL_CURRENT_ROWS_EXPLORATION_POLICY_REVALIDATION_BLOCKED": "ALL_ROWS_TRUE_TRUST_UNSAFE",
        "ALL_CURRENT_ROWS_TRUE_ENTRY_GATE_BLOCKED": "ALL_ROWS_TRUE_TRUST_UNSAFE",
        "TRUE_ENTRY_GATE_BLOCKED_PREQUEUE": "ALL_ROWS_TRUE_TRUST_UNSAFE",
        "TRUE_MARKET_INTEGRITY_BLOCKED_PREQUEUE": "ALL_ROWS_MARKET_INTEGRITY_BLOCKED",
    }
    if reason in (None, ""):
        return None
    return mapping.get(str(reason), str(reason))


def _prequeue_materialization_no_fill_reason(
    reason_counts: Mapping[str, int],
) -> str | None:
    reasons = [str(reason) for reason, count in reason_counts.items() if int(count or 0) > 0]
    if not reasons:
        return None
    if all(reason.startswith("MATERIALIZATION_PREQUEUE_ACTIVE_BUCKET_QUARANTINE:") for reason in reasons):
        return "ALL_CURRENT_ROWS_TRUE_BUCKET_QUARANTINE"
    if all(reason.startswith("MATERIALIZATION_PREQUEUE_ENTRY_GATE:") for reason in reasons):
        return "ALL_CURRENT_ROWS_TRUE_ENTRY_GATE_BLOCKED"
    if all(reason.startswith("MATERIALIZATION_PREQUEUE_SOURCE_") for reason in reasons):
        return "ALL_CURRENT_ROWS_MARKET_INTEGRITY_BLOCKED"
    if all(reason.startswith("MATERIALIZATION_PREQUEUE_RISK:") for reason in reasons):
        return "ALL_CURRENT_ROWS_TRUE_RISK_BLOCKED"
    if all(reason.startswith("MATERIALIZATION_PREQUEUE_ORCHESTRATOR:") for reason in reasons):
        return "ALL_CURRENT_ROWS_TRUE_ORCHESTRATOR_BLOCKED"
    if all(reason.startswith("MATERIALIZATION_PREQUEUE_ALLOCATOR:") for reason in reasons):
        return "ALL_CURRENT_ROWS_TRUE_ALLOCATOR_BLOCKED"
    return "ALL_CURRENT_ROWS_PREQUEUE_BLOCKED_WITH_EXACT_REASONS"


def _read_json(client: Any, key: str) -> Any:
    if client is None:
        return None
    try:
        raw = client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError):
        return None


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    tmp.replace(path)


def _safe_redis_set(client: Any, key: str, payload: Any, *, ex: int) -> bool:
    if client is None:
        return False
    try:
        client.set(key, json.dumps(payload, sort_keys=True, default=str), ex=ex)
        return True
    except Exception:
        return False


def _record_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _decision_record_key(kind: str, decision_id: Any) -> str:
    return f"v2:decision:{kind}:{decision_id}"


def _decision_record_matches_row(
    record: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    id_field: str,
    decision_id: Any,
) -> bool:
    if str(record.get(id_field) or record.get("decision_id") or "") != str(decision_id):
        return False
    symbol = str(row.get("symbol") or "").upper()
    if symbol and str(record.get("symbol") or "").upper() != symbol:
        return False
    timeframe = str(row.get("timeframe") or "")
    if timeframe and str(record.get("timeframe") or "") != timeframe:
        return False
    for field in ("signal_id", "prediction_id"):
        row_value = row.get(field)
        if row_value not in (None, "") and str(record.get(field) or "") != str(row_value):
            return False
    candidate_ids = {
        str(value)
        for value in (row.get("candidate_id"), row.get("prediction_id"))
        if value not in (None, "")
    }
    if candidate_ids and str(record.get("candidate_id") or "") not in candidate_ids:
        return False
    row_feature_hash = _first_present(
        row.get("feature_vector_hash"), row.get("input_feature_hash")
    )
    record_feature_hash = _first_present(
        record.get("feature_vector_hash"), record.get("input_feature_hash")
    )
    if (row_feature_hash not in (None, "") or record_feature_hash not in (None, "")) and str(
        row_feature_hash or ""
    ) != str(record_feature_hash or ""):
        return False
    return True


def _strict_aware_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _canonical_decision_record_rejection_reason(
    record: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    kind: str,
    id_field: str,
    decision_id: Any,
    expected_schema: str,
    expected_producer: str,
    observed_at: datetime,
) -> str | None:
    if not record:
        return f"{kind.upper()}_CANONICAL_DECISION_RECORD_MISSING"
    if str(record.get("schema_version") or "") != expected_schema:
        return f"{kind.upper()}_CANONICAL_DECISION_SCHEMA_MISMATCH"
    if str(record.get("producer") or "") != expected_producer:
        return f"{kind.upper()}_CANONICAL_DECISION_PRODUCER_MISMATCH"
    if not _decision_record_matches_row(
        record,
        row,
        id_field=id_field,
        decision_id=decision_id,
    ):
        return f"{kind.upper()}_CANONICAL_DECISION_IDENTITY_MISMATCH"
    if (
        record.get("paper_only") is not True
        or record.get("routes_to_live") is not False
        or record.get("places_real_order") is not False
    ):
        return f"{kind.upper()}_CANONICAL_DECISION_SAFETY_CONTRACT_MISMATCH"
    side = str(row.get("side") or "").strip().lower()
    if kind == "risk":
        action = str(
            _first_present(record.get("risk_action"), record.get("decision")) or ""
        ).strip().lower()
        if action not in {"allow", "pass", "approve"}:
            return "RISK_CANONICAL_DECISION_NOT_ALLOWING"
    else:
        action = str(
            _first_present(record.get("orchestrator_action"), record.get("decision"))
            or ""
        ).strip().lower()
        allowed_actions = {
            "allow",
            "pass",
            "approve",
            "open_long",
            "open_short",
            "proceed_long",
            "proceed_short",
        }
        if action not in allowed_actions:
            return "ORCHESTRATOR_CANONICAL_DECISION_NOT_ALLOWING"
        if action in {"open_long", "proceed_long"} and side != "long":
            return "ORCHESTRATOR_CANONICAL_DECISION_DIRECTION_MISMATCH"
        if action in {"open_short", "proceed_short"} and side != "short":
            return "ORCHESTRATOR_CANONICAL_DECISION_DIRECTION_MISMATCH"
    generated_at = _strict_aware_utc(record.get("generated_utc"))
    expires_at = _strict_aware_utc(record.get("expires_at"))
    if (
        generated_at is None
        or expires_at is None
        or generated_at > observed_at
        or expires_at <= generated_at
    ):
        return f"{kind.upper()}_CANONICAL_DECISION_CLOCK_INVALID"
    if expires_at <= observed_at:
        return f"{kind.upper()}_CANONICAL_DECISION_RECORD_EXPIRED"
    return None


def _mark_materialization_request_only(
    row: dict[str, Any],
    *,
    reasons: Iterable[str],
) -> None:
    exact_reasons = list(dict.fromkeys(str(reason) for reason in reasons if reason))
    row["canonical_decision_records_resolved"] = False
    row["canonical_decision_request_only"] = True
    row["non_executable_request_telemetry"] = True
    row["paper_exploration_paper_fill_allowed"] = False
    row["paper_exploration_materialization_queue_ready"] = False
    row["paper_exploration_current_blocker"] = "CANONICAL_DECISION_PRODUCERS_PENDING"
    row["canonical_decision_request_reasons"] = exact_reasons
    row["paper_fill_allowed"] = False
    row["valid_for_paper"] = False
    row["routes_to_live"] = False
    row["places_real_order"] = False
    signal = row.get("paper_signal")
    if isinstance(signal, dict):
        signal["paper_fill_allowed"] = False
        signal["valid_for_paper"] = False
        signal["canonical_decision_records_resolved"] = False
        signal["canonical_decision_request_only"] = True
        signal["non_executable_request_telemetry"] = True
        signal["canonical_decision_request_reasons"] = exact_reasons
        signal["routes_to_live"] = False
        signal["places_real_order"] = False


def _observe_materialization_decision_records(
    client: Any,
    rows: list[dict[str, Any]],
    *,
    generated_utc: str,
) -> dict[str, Any]:
    """Resolve canonical decisions without ever owning or writing their namespace."""

    observed_at = _parse_utc(generated_utc) or datetime.now(timezone.utc)
    status: dict[str, Any] = {
        "implemented": True,
        "schema_version": "paper_exploration_canonical_decision_observer_v2",
        "consumer_role": "READ_ONLY_CANONICAL_DECISION_OBSERVER",
        "write_mode": "READ_ONLY_NEVER_MATERIALIZE_CANONICAL_RECORDS_OR_INDEXES",
        "canonical_risk_producer": "v2_risk_gateway_live_loop",
        "canonical_orchestrator_producer": "v2_orchestrator_arbitration_loop",
        "risk_records_written": 0,
        "risk_records_resolved": 0,
        "risk_records_missing": 0,
        "risk_records_mismatch": 0,
        "orchestrator_records_written": 0,
        "orchestrator_records_resolved": 0,
        "orchestrator_records_missing": 0,
        "orchestrator_records_mismatch": 0,
        "candidate_indexes_written": 0,
        "signal_indexes_written": 0,
        "canonical_records_written": 0,
        "canonical_indexes_written": 0,
        "canonical_index_claimed": False,
        "request_telemetry_count": 0,
        "row_count": len(rows),
        "row_status": [],
    }
    for row in rows:
        candidate_id = _first_present(row.get("candidate_id"), row.get("prediction_id"))
        signal_id = row.get("signal_id")
        row_status: dict[str, Any] = {
            "candidate_id": candidate_id,
            "signal_id": signal_id,
            "risk_decision_id": _first_present(
                row.get("risk_decision_id"),
                row.get("paper_exploration_risk_decision_id"),
            ),
            "orchestrator_decision_id": _first_present(
                row.get("orchestrator_decision_id"),
                row.get("paper_exploration_orchestrator_decision_id"),
            ),
            "risk_decision_record_resolved": False,
            "orchestrator_decision_record_resolved": False,
            "decision_record_missing_reasons": [],
        }

        risk_record: dict[str, Any] = {}
        orchestrator_record: dict[str, Any] = {}
        risk_decision_id = row_status["risk_decision_id"]
        if not risk_decision_id:
            status["risk_records_missing"] += 1
            row_status["decision_record_missing_reasons"].append("RISK_DECISION_ID_MISSING")
        else:
            risk_key = _decision_record_key("risk", risk_decision_id)
            risk_record = _as_dict(_read_json(client, risk_key))
            rejection_reason = _canonical_decision_record_rejection_reason(
                risk_record,
                row,
                kind="risk",
                id_field="risk_decision_id",
                decision_id=risk_decision_id,
                expected_schema="v2_per_id_risk_decision_record_v1",
                expected_producer="v2_risk_gateway_live_loop",
                observed_at=observed_at,
            )
            if rejection_reason is None:
                status["risk_records_resolved"] += 1
                row_status["risk_decision_record_resolved"] = True
            else:
                if rejection_reason.endswith("_MISSING"):
                    status["risk_records_missing"] += 1
                else:
                    status["risk_records_mismatch"] += 1
                row_status["decision_record_missing_reasons"].append(rejection_reason)
            if row_status["risk_decision_record_resolved"]:
                row_status["risk_decision_record_key"] = risk_key
                row_status["risk_decision_record_hash"] = _record_hash(risk_record)
                row["risk_decision_record_key"] = risk_key
                row["risk_decision_record_hash"] = row_status["risk_decision_record_hash"]
                row["risk_decision_record_resolved"] = True
                row["risk_decision_source"] = "CANONICAL_PER_ID_DECISION_RECORD"
                row["risk_decision"] = _first_present(
                    risk_record.get("risk_action"),
                    risk_record.get("decision"),
                )

        orchestrator_decision_id = row_status["orchestrator_decision_id"]
        if not orchestrator_decision_id:
            status["orchestrator_records_missing"] += 1
            row_status["decision_record_missing_reasons"].append(
                "ORCHESTRATOR_DECISION_ID_MISSING"
            )
        else:
            orchestrator_key = _decision_record_key("orchestrator", orchestrator_decision_id)
            orchestrator_record = _as_dict(_read_json(client, orchestrator_key))
            rejection_reason = _canonical_decision_record_rejection_reason(
                orchestrator_record,
                row,
                kind="orchestrator",
                id_field="orchestrator_decision_id",
                decision_id=orchestrator_decision_id,
                expected_schema="v2_per_id_orchestrator_decision_record_v1",
                expected_producer="v2_orchestrator_arbitration_loop",
                observed_at=observed_at,
            )
            if rejection_reason is None:
                status["orchestrator_records_resolved"] += 1
                row_status["orchestrator_decision_record_resolved"] = True
            else:
                if rejection_reason.endswith("_MISSING"):
                    status["orchestrator_records_missing"] += 1
                else:
                    status["orchestrator_records_mismatch"] += 1
                row_status["decision_record_missing_reasons"].append(rejection_reason)
            if row_status["orchestrator_decision_record_resolved"]:
                row_status["orchestrator_decision_record_key"] = orchestrator_key
                row_status["orchestrator_decision_record_hash"] = _record_hash(
                    orchestrator_record
                )
                row["orchestrator_decision_record_key"] = orchestrator_key
                row["orchestrator_decision_record_hash"] = row_status[
                    "orchestrator_decision_record_hash"
                ]
                row["orchestrator_decision_record_resolved"] = True
                row["orchestrator_decision_source"] = "CANONICAL_PER_ID_DECISION_RECORD"
                row["orchestrator_decision"] = _first_present(
                    orchestrator_record.get("orchestrator_action"),
                    orchestrator_record.get("decision"),
                )

        row_resolved = bool(
            row_status["risk_decision_record_resolved"]
            and row_status["orchestrator_decision_record_resolved"]
        )
        if row_resolved and str(risk_record.get("orchestrator_decision_id") or "") != str(
            orchestrator_decision_id
        ):
            row_resolved = False
            status["risk_records_mismatch"] += 1
            row_status["decision_record_missing_reasons"].append(
                "RISK_TO_ORCHESTRATOR_CANONICAL_DECISION_ID_MISMATCH"
            )
        row["canonical_decision_records_resolved"] = row_resolved
        row_status["canonical_decision_records_resolved"] = row_resolved
        row["canonical_decision_request_only"] = not row_resolved
        row["non_executable_request_telemetry"] = not row_resolved
        if row_resolved:
            row["canonical_decision_request_reasons"] = []
            signal = row.get("paper_signal")
            if isinstance(signal, dict):
                for field in (
                    "risk_decision_record_key",
                    "risk_decision_record_hash",
                    "orchestrator_decision_record_key",
                    "orchestrator_decision_record_hash",
                ):
                    signal[field] = row.get(field)
                signal["canonical_decision_records_resolved"] = True
                signal["canonical_decision_request_only"] = False
                signal["non_executable_request_telemetry"] = False
        else:
            status["request_telemetry_count"] += 1
            _mark_materialization_request_only(
                row,
                reasons=row_status["decision_record_missing_reasons"],
            )
        row["decision_record_missing_reasons"] = row_status[
            "decision_record_missing_reasons"
        ]
        status["row_status"].append(row_status)

    status["missing_record_count"] = (
        status["risk_records_missing"]
        + status["orchestrator_records_missing"]
        + status["risk_records_mismatch"]
        + status["orchestrator_records_mismatch"]
    )
    status["canonical_namespace_conflict_count"] = (
        status["risk_records_mismatch"] + status["orchestrator_records_mismatch"]
    )
    status["canonical_namespace_cleanup_required"] = bool(
        status["canonical_namespace_conflict_count"]
    )
    status["canonical_namespace_cleanup_policy"] = (
        "OPERATOR_REVIEW_REQUIRED_INVENTORY_NEVER_OVERWRITES_OR_DELETES"
    )
    return status


def _counterfactual_feedback_identity(row: Mapping[str, Any]) -> str:
    for field in (
        "trainer_feedback_id",
        "paper_exploration_candidate_id",
        "prediction_id",
        "signal_id",
    ):
        value = row.get(field)
        if value not in (None, ""):
            return str(value)
    return "|".join(
        str(row.get(field) or "")
        for field in ("feedback_type", "symbol", "timeframe", "side")
    )


def _merge_counterfactual_feedback_rows(
    existing_payload: Any,
    new_rows: list[Mapping[str, Any]],
    *,
    limit: int = 1_000,
) -> list[dict[str, Any]]:
    if isinstance(existing_payload, Mapping):
        existing_rows = existing_payload.get("rows")
    else:
        existing_rows = existing_payload
    merged_by_id: dict[str, dict[str, Any]] = {}
    if isinstance(existing_rows, list):
        for row in existing_rows:
            if not isinstance(row, Mapping):
                continue
            merged = dict(row)
            merged_by_id[_counterfactual_feedback_identity(merged)] = merged
    for row in new_rows:
        if not isinstance(row, Mapping):
            continue
        merged = dict(row)
        merged_by_id[_counterfactual_feedback_identity(merged)] = merged
    return list(merged_by_id.values())[-limit:]


def _redis_client(redis_url: str | None = None) -> Any:
    try:
        import redis  # type: ignore
    except Exception:
        return None
    url = redis_url or os.environ.get("V2_REDIS_URL") or os.environ.get("REDIS_URL") or "redis://127.0.0.1:6379/0"
    try:
        client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2.0, socket_timeout=5.0)
        client.ping()
        return client
    except Exception:
        return None


def _scan_prediction_keys(client: Any, *, timeframes: tuple[str, ...], max_keys: int) -> list[str]:
    if client is None or max_keys <= 0:
        return []
    keys: list[str] = []
    seen: set[str] = set()
    for timeframe in timeframes:
        pattern = f"v2:prediction:*:{timeframe}"
        try:
            iterator = client.scan_iter(match=pattern, count=500)
        except TypeError:
            iterator = client.scan_iter(pattern)
        except Exception:
            continue
        try:
            for key in iterator:
                text = key.decode("utf-8", errors="replace") if isinstance(key, bytes) else str(key)
                if text in seen:
                    continue
                seen.add(text)
                keys.append(text)
                if len(keys) >= max_keys:
                    return keys
        except Exception:
            continue
    return keys


def _candidate_hash_basis(row: Mapping[str, Any], prediction: Mapping[str, Any] | None) -> str:
    basis = {
        "symbol": _first_present(row.get("symbol"), prediction and prediction.get("symbol")),
        "timeframe": _first_present(row.get("timeframe"), prediction and prediction.get("timeframe")),
        "prediction_id": _first_present(row.get("prediction_id"), prediction and prediction.get("prediction_id")),
        "signal_id": _first_present(row.get("signal_id"), prediction and prediction.get("signal_id")),
        "decision_time": _first_present(
            row.get("preemptive_decision_time"),
            row.get("decision_time"),
            prediction and prediction.get("decision_time"),
            prediction and prediction.get("generated_at"),
        ),
    }
    digest = hashlib.sha256(json.dumps(basis, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:24]
    return f"cand_{digest}"


def _feature_values(prediction: Mapping[str, Any] | None) -> tuple[dict[str, Any], list[str], list[str]]:
    prediction = prediction if isinstance(prediction, Mapping) else {}
    entry_snapshot = _as_dict(prediction.get("entry_feature_snapshot"))
    features = _as_dict(_first_present(entry_snapshot.get("features"), prediction.get("features")))
    feature_names = [str(item) for item in _as_list(prediction.get("feature_names"))]
    source_labels = [str(item) for item in _as_list(prediction.get("source_labels"))]
    return features, feature_names, source_labels


def _has_named_feature(
    *,
    features: Mapping[str, Any],
    feature_names: list[str],
    source_labels: list[str],
    needles: tuple[str, ...],
) -> bool:
    names = set(str(name).lower() for name in features)
    names.update(str(name).lower() for name in feature_names)
    labels = " ".join(source_labels).lower()
    for needle in needles:
        lower = needle.lower()
        if lower in labels:
            return True
        if any(lower in name for name in names):
            return True
    return False


def _provider_presence(prediction: Mapping[str, Any] | None) -> dict[str, Any]:
    features, feature_names, source_labels = _feature_values(prediction)
    prediction = prediction if isinstance(prediction, Mapping) else {}

    def _explicit_bool(name: str) -> bool | None:
        value = prediction.get(name)
        if isinstance(value, bool):
            return value
        return None

    coinank = _has_named_feature(
        features=features,
        feature_names=feature_names,
        source_labels=source_labels,
        needles=("coinank", "liquidation", "long_short", "open_interest"),
    )
    coinglass = _has_named_feature(
        features=features,
        feature_names=feature_names,
        source_labels=source_labels,
        needles=("coinglass", "funding", "open_interest", "long_short", "liquidation"),
    )
    moralis = _has_named_feature(
        features=features,
        feature_names=feature_names,
        source_labels=source_labels,
        needles=("moralis", "wallet", "smart_money", "onchain", "token_transfer"),
    )
    ta = _has_named_feature(
        features=features,
        feature_names=feature_names,
        source_labels=source_labels,
        needles=("ta_", "rsi", "macd", "ema", "atr", "bollinger"),
    )
    micro = _has_named_feature(
        features=features,
        feature_names=feature_names,
        source_labels=source_labels,
        needles=("orderbook", "depth", "spread", "microstructure", "tape", "bid_ask"),
    )
    advanced = _has_named_feature(
        features=features,
        feature_names=feature_names,
        source_labels=source_labels,
        needles=("fvg", "liquidity_zone", "vwap", "structure", "sweep", "order_block"),
    )
    fvg_liquidity = _has_named_feature(
        features=features,
        feature_names=feature_names,
        source_labels=source_labels,
        needles=("fvg", "liquidity_zone", "nearest_liquidity", "liquidity_sweep"),
    )
    explicit_provider_flags = {
        "coinank": _explicit_bool("CoinAnk_features_present"),
        "coinglass": _explicit_bool("CoinGlass_features_present"),
        "moralis": _explicit_bool("Moralis_features_present"),
        "ta": _explicit_bool("TA_features_present"),
        "micro": _explicit_bool("microstructure_features_present"),
        "advanced": _explicit_bool("advanced_indicator_features_present"),
        "fvg_liquidity": _explicit_bool("FVG_liquidity_zone_features_present"),
    }
    microstructure_evidence_present = any(
        _float(prediction.get(field)) is not None
        for field in (
            "microstructure_trust_score",
            "composite_microstructure_trust_score",
            "trade_tape_confirmation_score",
            "orderbook_depth_usd",
            "liquidity_exit_depth",
            "expected_exit_depth_usd",
        )
    )
    coinank = explicit_provider_flags["coinank"] if explicit_provider_flags["coinank"] is not None else coinank
    coinglass = (
        explicit_provider_flags["coinglass"]
        if explicit_provider_flags["coinglass"] is not None
        else coinglass
    )
    moralis = explicit_provider_flags["moralis"] if explicit_provider_flags["moralis"] is not None else moralis
    ta = explicit_provider_flags["ta"] if explicit_provider_flags["ta"] is not None else ta
    micro = (
        bool(explicit_provider_flags["micro"] or microstructure_evidence_present)
        if explicit_provider_flags["micro"] is not None
        else bool(micro or microstructure_evidence_present)
    )
    advanced = (
        explicit_provider_flags["advanced"]
        if explicit_provider_flags["advanced"] is not None
        else advanced
    )
    fvg_liquidity = (
        explicit_provider_flags["fvg_liquidity"]
        if explicit_provider_flags["fvg_liquidity"] is not None
        else fvg_liquidity
    )
    entry_snapshot = _as_dict(prediction.get("entry_feature_snapshot"))
    missing_names = [
        str(item)
        for item in _as_list(
            _first_present(
                entry_snapshot.get("missing_feature_flags"),
                entry_snapshot.get("missing_feature_names"),
                prediction and prediction.get("tensor_unreconstructed_feature_names"),
                prediction and prediction.get("missing_feature_names"),
            )
        )
    ]
    return {
        "CoinAnk_features_present": coinank,
        "CoinGlass_features_present": coinglass,
        "Moralis_features_present": moralis,
        "TA_features_present": ta,
        "microstructure_features_present": micro,
        "advanced_indicator_features_present": advanced,
        "FVG_liquidity_zone_features_present": fvg_liquidity,
        "provider_missing_masks": {
            "required_missing": [
                name
                for name, present in (
                    ("CoinAnk", coinank),
                    ("CoinGlass", coinglass),
                    ("TA", ta),
                    ("microstructure", micro),
                    ("advanced_indicator", advanced),
                )
                if not present
            ],
            "optional_missing": [] if moralis else ["Moralis"],
            "raw_missing_feature_names": missing_names,
        },
    }


def _lineage_value(row: Mapping[str, Any], prediction: Mapping[str, Any] | None, field: str) -> Any:
    prediction = prediction if isinstance(prediction, Mapping) else {}
    entry_snapshot = _as_dict(prediction.get("entry_feature_snapshot"))
    source_hashes = _as_dict(prediction.get("source_hashes"))
    return _first_present(
        row.get(field),
        prediction.get(field),
        source_hashes.get(field),
        entry_snapshot.get(field),
    )


def _candidate_field(
    row: Mapping[str, Any],
    prediction: Mapping[str, Any] | None,
    *fields: str,
) -> tuple[str | None, Any]:
    prediction = prediction if isinstance(prediction, Mapping) else {}
    entry_snapshot = _as_dict(prediction.get("entry_feature_snapshot"))
    features = _as_dict(_first_present(entry_snapshot.get("features"), prediction.get("features")))
    for field in fields:
        value = _first_present(row.get(field), prediction.get(field), entry_snapshot.get(field), features.get(field))
        if value is not None:
            return field, value
    return None, None


def _candidate_value(row: Mapping[str, Any], prediction: Mapping[str, Any] | None, *fields: str) -> Any:
    return _candidate_field(row, prediction, *fields)[1]


def _risk_status(row: Mapping[str, Any]) -> str:
    value = _first_present(
        row.get("risk_decision"),
        row.get("risk_result"),
        row.get("risk_action"),
        _as_dict(row.get("risk")).get("decision"),
    )
    if value is None:
        return "MISSING"
    text = str(value).strip().upper()
    if text in ALLOW_RISK_VALUES or text == "PASS":
        return "PASS"
    if text in {"DENY", "DENIED", "BLOCK", "BLOCKED", "FAIL", "FAILED"}:
        return "BLOCKED"
    return text


def _orchestrator_status(row: Mapping[str, Any]) -> str:
    value = _first_present(
        row.get("orchestrator_decision"),
        row.get("orchestrator_result"),
        row.get("orchestrator_action"),
        row.get("decision_action"),
        row.get("orchestrator_decision_action"),
        _as_dict(row.get("orchestrator")).get("decision"),
        _as_dict(row.get("orchestrator")).get("decision_action"),
        _as_dict(row.get("orchestrator_decision_record")).get("decision_action"),
    )
    if value is None:
        return "MISSING"
    text = str(value).strip().upper()
    if text in ALLOW_ORCHESTRATOR_VALUES:
        return "PASS"
    if text in {"HOLD", "HELD", "DENY", "BLOCK", "BLOCKED", "FAIL", "FAILED"}:
        return "BLOCKED"
    return text


def _allocator_status(row: Mapping[str, Any]) -> str:
    allocation = _as_dict(row.get("allocation"))
    value = _first_present(row.get("allocator_decision"), row.get("allocation_decision"), allocation.get("allocator_decision"), allocation.get("decision"))
    if value is None:
        return "MISSING"
    text = str(value).strip().upper()
    if text in ALLOW_ALLOCATOR_VALUES:
        return "PASS"
    if text.startswith("BLOCK"):
        return text
    return text


def _side(row: Mapping[str, Any], prediction: Mapping[str, Any] | None) -> str | None:
    value = _first_present(row.get("side"), row.get("action"), prediction and prediction.get("selected_action"), prediction and prediction.get("ppo_action"))
    text = str(value or "").strip().lower()
    if text in {"long", "buy", "open_long"}:
        return "long"
    if text in {"short", "sell", "open_short"}:
        return "short"
    return None


def _is_probation(row: Mapping[str, Any]) -> bool:
    action = str(row.get("preemptive_action") or "").upper()
    return (
        action == "ALLOW_PROBATION_PAPER"
        or row.get("allow_positive_edge_probation_paper") is True
        or row.get("counts_as_probation") is True
        or "PROBATION" in str(row.get("source_tier") or "").upper()
    )


def _is_reconstructed(row: Mapping[str, Any]) -> bool:
    text = " ".join(
        str(_first_present(row.get("source_tier"), row.get("candidate_id"), row.get("paper_session_id"), ""))
        .upper()
        .split()
    )
    return (
        row.get("counts_as_reconstructed") is True
        or row.get("reconstructed") is True
        or row.get("preemptive_decision_backfilled") is True
        or "RECONSTRUCT" in text
        or "LEGACY" in text
    )


def _no_side_reason(
    row: Mapping[str, Any],
    prediction: Mapping[str, Any] | None,
    *,
    expected_long_net: float | None,
    expected_short_net: float | None,
    feature_vector_hash: Any,
) -> str | None:
    if _side(row, prediction) is not None:
        return None
    raw_action = _first_present(
        row.get("side"),
        row.get("action"),
        row.get("selected_action"),
        prediction and prediction.get("selected_action"),
        prediction and prediction.get("ppo_action"),
        prediction and prediction.get("side"),
    )
    text = str(raw_action or "").strip().lower()
    if not feature_vector_hash:
        return "FEATURE_SNAPSHOT_MISSING"
    if expected_long_net is not None and expected_short_net is not None and expected_long_net <= 0.0 and expected_short_net <= 0.0:
        return "BOTH_LONG_AND_SHORT_NET_PNL_NON_POSITIVE"
    if text in {"hold", "no_trade", "none", "flat", "0"}:
        return "MODEL_HOLD_OR_NO_TRADE_ACTION"
    if raw_action in (None, ""):
        return "SIDE_NOT_EMITTED_BY_PUBLISHER"
    return f"UNSUPPORTED_ACTION_{str(raw_action).upper()}"


_NO_TRADE_STRATEGY_TOKENS = {
    "hold",
    "no_trade",
    "no_trade_mode",
    "no_trade_expert",
    "risk_off_no_trade",
}

_LIFECYCLE_STRATEGY_TOKENS = {
    "close",
    "close_only",
    "close_or_reduce_only",
    "reduce",
    "reduce_only",
    "reduce_size",
    "reduce_size_mode",
    "reduce_only_recovery",
}


def _split_strategy_tokens(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        tokens: list[str] = []
        for item in value:
            tokens.extend(_split_strategy_tokens(item))
        return tokens
    text = str(value).strip().lower()
    if not text:
        return []
    return [
        token
        for token in re.split(r"[^a-z0-9_]+", text)
        if token
    ] or [text]


def _materialization_no_trade_entry_evidence_reasons(
    row: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    fields = (
        "strategy_id",
        "strategy_family",
        "strategy_subtype",
        "strategy_mode",
        "strategy_canonical_mode",
        "strategy_selected_mode",
        "strategy_router_selected_mode",
        "entry_reason",
    )
    for field in fields:
        for token in _split_strategy_tokens(row.get(field)):
            if token in _NO_TRADE_STRATEGY_TOKENS:
                reasons.append(f"{field}=NO_TRADE")
            elif token in _LIFECYCLE_STRATEGY_TOKENS:
                reasons.append(f"{field}=LIFECYCLE_ACTION")
    for token in _split_strategy_tokens(
        _first_present(
            row.get("strategy_regime_labels"),
            row.get("market_regime"),
            row.get("market_regime_at_entry"),
        )
    ):
        if token in _NO_TRADE_STRATEGY_TOKENS or token == "no_trade":
            reasons.append("strategy_regime_labels_include_NO_TRADE")
    return sorted(set(reasons))


def _selected_side_economics_consistency(row: Mapping[str, Any]) -> dict[str, Any]:
    side = str(row.get("side") or row.get("selected_action") or "").strip().lower()
    expected_move = _float(row.get("expected_move_after_cost_bps"))
    if side not in {"long", "short"}:
        return {
            "status": "UNKNOWN_SIDE",
            "side": side or None,
            "expected_move_after_cost_bps": expected_move,
            "selected_side_expected_net_pnl_usd": None,
            "selected_side_expected_net_edge_bps": None,
            "contradiction_reasons": ["SELECTED_SIDE_MISSING"],
        }

    selected_net = _float(
        _first_present(
            row.get(f"{side}_expected_net_pnl_usd"),
            row.get(f"expected_{side}_net_pnl_usd"),
            row.get("expected_net_pnl_usd"),
        )
    )
    selected_edge = _float(
        _first_present(
            row.get(f"{side}_expected_net_edge_bps"),
            row.get(f"expected_{side}_net_edge_bps"),
        )
    )
    signed_move_favorable = expected_move_after_cost_favorable_for_side(
        side=side,
        expected_move_after_cost_bps=expected_move,
    )
    contradiction_reasons: list[str] = []
    if (
        expected_move is not None
        and not signed_move_favorable
        and selected_net is not None
        and selected_net > 0.0
    ):
        contradiction_reasons.append(
            "SELECTED_SIDE_NET_USD_POSITIVE_WHILE_SIGNED_MOVE_UNFAVORABLE"
        )
    if selected_edge is not None and selected_net is not None:
        if selected_edge <= 0.0 < selected_net:
            contradiction_reasons.append(
                "SELECTED_SIDE_NET_USD_POSITIVE_WHILE_EDGE_BPS_NON_POSITIVE"
            )
        elif selected_edge > 0.0 and selected_net <= 0.0:
            contradiction_reasons.append(
                "SELECTED_SIDE_NET_USD_NON_POSITIVE_WHILE_EDGE_BPS_POSITIVE"
            )

    return {
        "status": "CONFLICT" if contradiction_reasons else "CONSISTENT",
        "side": side,
        "expected_move_after_cost_bps": expected_move,
        "expected_move_after_cost_favorable_for_side": signed_move_favorable,
        "selected_side_expected_net_pnl_usd": selected_net,
        "selected_side_expected_net_edge_bps": selected_edge,
        "contradiction_reasons": contradiction_reasons,
    }


def _materialization_source_freshness(
    row: Mapping[str, Any],
    *,
    accepted_at: Any,
) -> dict[str, Any]:
    accepted_dt = _parse_utc(accepted_at)
    adaptive_seconds = _adaptive_stale_seconds(row)
    source_candidates: list[tuple[str, datetime]] = []
    for field, value in (
        ("available_at", _first_present(row.get("source_available_at"), row.get("available_at"), row.get("entry_feature_available_at"))),
        ("decision_time", _first_present(row.get("source_decision_time"), row.get("decision_time"), row.get("entry_feature_decision_time"))),
        ("generated_utc", _first_present(row.get("source_generated_utc"), row.get("generated_utc"), row.get("generated_at"))),
        ("feature_cutoff", row.get("feature_cutoff")),
    ):
        parsed = _parse_utc(value)
        if parsed is not None:
            source_candidates.append((field, parsed))

    if accepted_dt is None:
        return {
            "source_freshness_basis": None,
            "source_freshness_time": None,
            "source_expires_at": None,
            "source_age_seconds_at_acceptance": None,
            "source_stale_seconds": adaptive_seconds,
            "source_stale_at_acceptance": True,
            "source_future_at_acceptance": False,
            "source_freshness_reasons": ["MATERIALIZATION_PREQUEUE_ACCEPTED_AT_INVALID"],
        }

    if not source_candidates:
        return {
            "source_freshness_basis": None,
            "source_freshness_time": None,
            "source_expires_at": None,
            "source_age_seconds_at_acceptance": None,
            "source_stale_seconds": adaptive_seconds,
            "source_stale_at_acceptance": True,
            "source_future_at_acceptance": False,
            "source_freshness_reasons": ["MATERIALIZATION_PREQUEUE_SOURCE_TIME_MISSING"],
        }

    basis_field, basis_dt = max(source_candidates, key=lambda item: item[1])
    source_expires_at = basis_dt + timedelta(seconds=adaptive_seconds)
    age_seconds = int(round((accepted_dt - basis_dt).total_seconds()))
    source_future = basis_dt > accepted_dt
    source_stale = source_expires_at < accepted_dt
    reasons: list[str] = []
    if source_future:
        reasons.append(
            f"MATERIALIZATION_PREQUEUE_SOURCE_TIME_AFTER_ACCEPTED_AT:{basis_field}"
        )
    if source_stale:
        reasons.append(
            "MATERIALIZATION_PREQUEUE_SOURCE_STALE:"
            f"{max(0, age_seconds)}>{adaptive_seconds}:{basis_field}"
        )
    return {
        "source_freshness_basis": basis_field,
        "source_freshness_time": _format_utc(basis_dt),
        "source_expires_at": _format_utc(source_expires_at),
        "source_age_seconds_at_acceptance": age_seconds,
        "source_stale_seconds": adaptive_seconds,
        "source_stale_at_acceptance": source_stale,
        "source_future_at_acceptance": source_future,
        "source_freshness_reasons": reasons,
    }


def _materialization_prequeue_block_reasons(
    row: Mapping[str, Any],
    *,
    accepted_at: Any | None = None,
) -> list[str]:
    reasons: list[str] = []
    if accepted_at not in (None, ""):
        source_freshness = _materialization_source_freshness(
            row,
            accepted_at=accepted_at,
        )
        reasons.extend(
            str(reason)
            for reason in source_freshness.get("source_freshness_reasons") or []
            if reason
            and not str(reason).startswith(
                "MATERIALIZATION_PREQUEUE_SOURCE_TIME_AFTER_ACCEPTED_AT:"
            )
        )
    no_trade_entry_reasons = _materialization_no_trade_entry_evidence_reasons(row)
    if no_trade_entry_reasons:
        reasons.append(
            "MATERIALIZATION_PREQUEUE_LIFECYCLE_OR_NO_TRADE_STRATEGY_NOT_ENTRY_EVIDENCE"
        )
        reasons.extend(
            f"MATERIALIZATION_PREQUEUE_NO_TRADE_ENTRY_EVIDENCE:{reason}"
            for reason in no_trade_entry_reasons
        )
    symbol = str(row.get("symbol") or "").strip().upper()
    timeframe = str(row.get("timeframe") or "").strip().lower()
    if symbol in PAPER_EXPLORATION_MATERIALIZATION_SYMBOL_EXCLUSION_LIST:
        reasons.append(
            "MATERIALIZATION_PREQUEUE_ENTRY_GATE:"
            f"SYMBOL_EXPLICITLY_EXCLUDED_BY_OPERATOR:{symbol}"
        )
    if (
        timeframe
        and timeframe not in PAPER_EXPLORATION_MATERIALIZATION_ALLOWED_ENTRY_TIMEFRAMES
    ):
        reasons.append(
            "MATERIALIZATION_PREQUEUE_ENTRY_GATE:"
            f"TIMEFRAME_BLOCKED:{timeframe}"
        )
    side = str(row.get("side") or row.get("selected_action") or "").strip().lower()
    expected_move = _float(row.get("expected_move_after_cost_bps"))
    if not expected_move_after_cost_favorable_for_side(
        side=side,
        expected_move_after_cost_bps=expected_move,
    ):
        reasons.append(
            "MATERIALIZATION_PREQUEUE_EXPECTED_MOVE_NOT_FAVORABLE_FOR_SIDE:"
            f"{side or 'missing'}:{expected_move}"
        )
    side_economics_consistency = _selected_side_economics_consistency(row)
    for reason in side_economics_consistency.get("contradiction_reasons") or []:
        reasons.append(
            "MATERIALIZATION_PREQUEUE_SELECTED_SIDE_ECONOMICS_CONFLICT:"
            f"{side or 'missing'}:{reason}"
        )
    if row.get("current_price_can_size_trade") is False:
        reasons.append("MATERIALIZATION_PREQUEUE_CURRENT_PRICE_NOT_TRADE_SIZE_SAFE")
    quarantine = _as_dict(row.get("paper_exploration_quarantine"))
    if quarantine.get("should_block_this_row") is True:
        reasons.append("MATERIALIZATION_PREQUEUE_ACTIVE_BUCKET_QUARANTINE")
    return sorted(set(reasons))


def _inventory_confidence_bucket(value: Any) -> str:
    confidence = _float(value)
    if confidence is None:
        return "MISSING"
    bounded = max(0.0, min(1.0, confidence))
    low_index = min(9, max(0, int(bounded * 10.0)))
    low = low_index / 10.0
    high = 1.0 if low_index == 9 else (low_index + 1) / 10.0
    return f"{low:.1f}-{high:.1f}"


def _inventory_regime_from_labels(value: Any) -> str | None:
    if isinstance(value, str):
        labels = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, (list, tuple, set)):
        labels = [str(item).strip() for item in value if str(item).strip()]
    else:
        labels = []
    normalized = [label.upper() for label in labels if label]
    if not normalized:
        return None
    non_no_trade = [label for label in normalized if label != "NO_TRADE"]
    return ",".join(non_no_trade or normalized)


def _inventory_regime_value(row: Mapping[str, Any]) -> str:
    raw_regime = _first_present(
        row.get("market_regime_at_entry"),
        row.get("market_regime"),
        row.get("market_regime_at_exit"),
    )
    if raw_regime not in (None, ""):
        if isinstance(raw_regime, (list, tuple, set)):
            derived = _inventory_regime_from_labels(raw_regime)
            if derived:
                return derived
        return str(raw_regime)
    return _inventory_regime_from_labels(row.get("strategy_regime_labels")) or "UNKNOWN"


def _inventory_known_bucket_value(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and text.upper() != "UNKNOWN"


def _inventory_candidate_quarantine_keys(row: Mapping[str, Any]) -> set[str]:
    symbol = str(row.get("symbol") or "UNKNOWN")
    timeframe = str(row.get("timeframe") or "UNKNOWN")
    side = str(_first_present(row.get("side"), row.get("selected_action"), row.get("action")) or "UNKNOWN").lower()
    strategy = str(
        _first_present(
            row.get("strategy_mode"),
            row.get("strategy_canonical_mode"),
            row.get("strategy_id"),
            row.get("strategy_family"),
            row.get("strategy_subtype"),
            row.get("strategy_selected_mode"),
            row.get("strategy_router_selected_mode"),
        )
        or "UNKNOWN"
    )
    regime = _inventory_regime_value(row)
    confidence_bucket = _inventory_confidence_bucket(
        _first_present(
            row.get("confidence_calibrated"),
            row.get("selected_action_probability"),
            row.get("confidence_raw"),
        )
    )
    keys: set[str] = {"|".join((symbol, timeframe, strategy, regime))}
    if _inventory_known_bucket_value(side):
        keys.add(f"side:{side}")
    if _inventory_known_bucket_value(regime):
        keys.add(f"regime:{regime}")
    if _inventory_known_bucket_value(timeframe):
        keys.add(f"timeframe:{timeframe}")
    if _inventory_known_bucket_value(side) and _inventory_known_bucket_value(timeframe):
        keys.add(f"side_timeframe:{side}|{timeframe}")
    if _inventory_known_bucket_value(strategy) and _inventory_known_bucket_value(regime):
        keys.add(f"strategy_regime:{strategy}|{regime}")
    if (
        _inventory_known_bucket_value(strategy)
        and _inventory_known_bucket_value(side)
        and _inventory_known_bucket_value(timeframe)
    ):
        keys.add(f"strategy_side_timeframe:{strategy}|{side}|{timeframe}")
    if _inventory_known_bucket_value(confidence_bucket) and _inventory_known_bucket_value(regime):
        keys.add(f"confidence_regime:{confidence_bucket}|{regime}")
    return keys


def _inventory_specific_quarantine_key(key: str) -> bool:
    normalized = str(key or "")
    return not normalized.startswith(("side:", "timeframe:", "regime:"))


_INVENTORY_REGIME_BUCKET_TYPES = {
    "regime",
    "confidence_regime",
    "strategy_regime",
}


def _inventory_quarantine_bucket_metadata(
    status: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    nested_status = _as_dict(status.get("bucket_quarantine_status"))
    rows = status.get("quarantined_buckets")
    if not isinstance(rows, list):
        rows = nested_status.get("quarantined_buckets")
    if not isinstance(rows, list):
        return {}
    return {
        str(bucket.get("bucket_key")): bucket
        for bucket in rows
        if isinstance(bucket, Mapping) and bucket.get("bucket_key") not in (None, "")
    }


def _inventory_quarantine_min_count(status: Mapping[str, Any]) -> int:
    nested_status = _as_dict(status.get("bucket_quarantine_status"))
    configured = _float(
        _first_present(
            status.get("negative_bucket_min_count"),
            nested_status.get("negative_bucket_min_count"),
            PAPER_NEGATIVE_BUCKET_QUARANTINE_MIN_COUNT,
        )
    )
    if configured is None:
        return PAPER_NEGATIVE_BUCKET_QUARANTINE_MIN_COUNT
    return max(1, int(configured))


def _inventory_bucket_proof_rows(
    keys: Iterable[str],
    status: Mapping[str, Any],
    *,
    classification: str,
) -> list[dict[str, Any]]:
    metadata = _inventory_quarantine_bucket_metadata(status)
    min_count = _inventory_quarantine_min_count(status)
    proof_rows: list[dict[str, Any]] = []
    for key in keys:
        bucket = metadata.get(str(key or ""))
        if bucket is None:
            proof_rows.append(
                {
                    "bucket_key": key,
                    "proof_status": "MISSING_BUCKET_METADATA_FAIL_CLOSED",
                    "classification": classification,
                    "negative_bucket_min_count": min_count,
                }
            )
            continue
        proof_rows.append(
            {
                "bucket_key": bucket.get("bucket_key"),
                "bucket_type": bucket.get("bucket_type"),
                "state": bucket.get("state"),
                "candidate_blocking": bucket.get("candidate_blocking"),
                "block_reasons": list(bucket.get("block_reasons") or []),
                "closed_outcome_count": bucket.get("closed_outcome_count"),
                "profit_factor": bucket.get("profit_factor"),
                "notional_weighted_expectancy_bps": bucket.get(
                    "notional_weighted_expectancy_bps"
                ),
                "high_confidence_loss_rate": bucket.get("high_confidence_loss_rate"),
                "high_confidence_loss_count": bucket.get("high_confidence_loss_count"),
                "high_confidence_outcome_count": bucket.get(
                    "high_confidence_outcome_count"
                ),
                "ATR_stop_loss_count": bucket.get("ATR_stop_loss_count"),
                "negative_bucket_min_count": _first_present(
                    bucket.get("negative_bucket_min_count"),
                    min_count,
                ),
                "proof_status": "BUCKET_METADATA_PRESENT",
                "classification": classification,
            }
        )
    return proof_rows


def _inventory_hard_quarantine_key_for_paper_exploration(
    key: str,
    status: Mapping[str, Any],
) -> bool:
    if not _inventory_specific_quarantine_key(key):
        return False
    bucket = _inventory_quarantine_bucket_metadata(status).get(str(key or ""))
    if bucket is None:
        return True
    bucket_type = str(bucket.get("bucket_type") or "")
    if bucket_type not in _INVENTORY_REGIME_BUCKET_TYPES:
        return True
    closed_count = int(_float(bucket.get("closed_outcome_count")) or 0)
    min_count = _inventory_quarantine_min_count(status)
    reasons = [str(reason) for reason in (bucket.get("block_reasons") or [])]
    profit_factor = _float(bucket.get("profit_factor"))
    expectancy_bps = _float(bucket.get("notional_weighted_expectancy_bps"))
    severe = any(
        "ATR_STOP" in reason
        or "CATASTROPHIC" in reason
        or "HIGH_CONFIDENCE_LOSS_RATE" in reason
        for reason in reasons
    )
    negative_evidence = any(reason.startswith("NEGATIVE_") for reason in reasons) and (
        (profit_factor is not None and profit_factor < 1.0)
        or (expectancy_bps is not None and expectancy_bps <= 0.0)
    )
    mature = closed_count >= min_count
    return mature or severe or negative_evidence


def _inventory_specific_loss_cluster_key(key: str) -> bool:
    normalized = str(key or "")
    return not normalized.startswith(
        ("loss_cluster_side:", "loss_cluster_timeframe:")
    )


def _inventory_high_confidence_loss_cluster_matches(
    row: Mapping[str, Any],
    performance_status: Mapping[str, Any],
) -> list[str]:
    cluster = _as_dict(performance_status.get("recovery_high_confidence_loss_cluster_status"))
    if cluster.get("cluster_detected") is not True:
        return []
    symbol = str(row.get("symbol") or "").strip().upper()
    side = str(_first_present(row.get("side"), row.get("selected_action"), row.get("action")) or "").strip().lower()
    timeframe = str(row.get("timeframe") or "").strip()
    strategy = str(
        _first_present(
            row.get("strategy_selected_mode"),
            row.get("strategy_mode"),
            row.get("strategy_id"),
            row.get("strategy_family"),
        )
        or ""
    ).strip()
    affected_symbols = {
        str(value or "").upper()
        for value in (cluster.get("affected_symbols") or [])
        if value not in (None, "")
    }
    quarantined_sides = {
        str(value or "").lower()
        for value in (cluster.get("quarantined_sides") or [])
        if value not in (None, "")
    }
    quarantined_timeframes = {
        str(value or "")
        for value in (cluster.get("quarantined_timeframes") or [])
        if value not in (None, "")
    }
    quarantined_strategy_modes = {
        str(value or "")
        for value in (cluster.get("quarantined_strategy_modes") or [])
        if value not in (None, "")
    }
    matches: list[str] = []
    if symbol and symbol in affected_symbols:
        matches.append(f"loss_cluster_symbol:{symbol}")
    if side and side in quarantined_sides:
        matches.append(f"loss_cluster_side:{side}")
    if timeframe and timeframe in quarantined_timeframes:
        matches.append(f"loss_cluster_timeframe:{timeframe}")
    if strategy and strategy in quarantined_strategy_modes:
        matches.append(f"loss_cluster_strategy:{strategy}")
    return sorted(set(matches))


def _materialization_prequeue_performance_block_reasons(
    row: Mapping[str, Any],
    performance_status: Mapping[str, Any] | None,
) -> tuple[list[str], dict[str, Any]]:
    status = _as_dict(performance_status)
    if not status:
        return [], {}
    candidate_keys = _inventory_candidate_quarantine_keys(row)
    blocked_keys = {
        str(key)
        for key in (status.get("blocked_bucket_keys") or [])
        if key not in (None, "")
    }
    matched_bucket_keys = sorted(candidate_keys & blocked_keys)
    matched_loss_cluster_keys = _inventory_high_confidence_loss_cluster_matches(
        row,
        status,
    )
    hard_bucket_keys = [
        key
        for key in matched_bucket_keys
        if _inventory_hard_quarantine_key_for_paper_exploration(key, status)
    ]
    hard_loss_cluster_keys = [
        key
        for key in matched_loss_cluster_keys
        if _inventory_specific_loss_cluster_key(key)
    ]
    advisory_bucket_keys = [
        key for key in matched_bucket_keys if key not in hard_bucket_keys
    ]
    advisory_loss_cluster_keys = [
        key for key in matched_loss_cluster_keys if key not in hard_loss_cluster_keys
    ]
    reasons = [
        f"MATERIALIZATION_PREQUEUE_ACTIVE_BUCKET_QUARANTINE:{key}"
        for key in hard_bucket_keys
    ] + [
        f"MATERIALIZATION_PREQUEUE_HIGH_CONFIDENCE_LOSS_CLUSTER:{key}"
        for key in hard_loss_cluster_keys
    ]
    evidence = {
        "paper_performance_circuit_breaker_state": status.get("state") or status.get("status"),
        "paper_performance_circuit_breaker_observed_reasons": list(
            status.get("block_reasons") or []
        ),
        "paper_performance_circuit_breaker_candidate_bucket_keys": sorted(
            candidate_keys
        ),
        "paper_performance_circuit_breaker_matched_blocked_bucket_keys": hard_bucket_keys,
        "paper_performance_circuit_breaker_matched_loss_cluster_keys": hard_loss_cluster_keys,
        "paper_performance_circuit_breaker_advisory_bucket_keys": advisory_bucket_keys,
        "paper_performance_circuit_breaker_advisory_loss_cluster_keys": advisory_loss_cluster_keys,
        "paper_performance_circuit_breaker_matched_blocked_bucket_proof": (
            _inventory_bucket_proof_rows(
                hard_bucket_keys,
                status,
                classification="HARD_BLOCK_FOR_PAPER_EXPLORATION",
            )
        ),
        "paper_performance_circuit_breaker_advisory_bucket_proof": (
            _inventory_bucket_proof_rows(
                advisory_bucket_keys,
                status,
                classification="ADVISORY_SIZE_CAP_FOR_PAPER_EXPLORATION",
            )
        ),
        "paper_performance_circuit_global_halt_only": (
            status.get("new_entries_allowed") is not True
            and not hard_bucket_keys
            and not hard_loss_cluster_keys
        ),
        "paper_risk_controller_exploration_global_halt_bucket_clean_allowed": (
            status.get("new_entries_allowed") is not True
            and not hard_bucket_keys
            and not hard_loss_cluster_keys
        ),
        "paper_risk_controller_exploration_circuit_breaker_size_cap_required": (
            status.get("new_entries_allowed") is not True
        ),
    }
    return sorted(set(reasons)), evidence


def _with_selected_side_diagnostic_usd(
    row: Mapping[str, Any],
    prediction: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Expose selected-side USD economics before allocator simulation.

    Some publisher rows provide only a signed move/edge and a directional side.
    The inventory later derives long/short USD diagnostics, but allocator
    simulation runs first. This bridge keeps USD primary by converting the
    selected signed edge into diagnostic USD at the candidate notional when
    available, otherwise at a unit USD notional until allocator sizing exists.
    """
    enriched = dict(row)
    side = _side(enriched, prediction)
    if side not in {"long", "short"}:
        return enriched
    selected_net_field = f"{side}_expected_net_pnl_usd"
    alternate_selected_net_field = f"expected_{side}_net_pnl_usd"
    if _float(_candidate_value(enriched, prediction, selected_net_field, alternate_selected_net_field)) is not None:
        return enriched
    expected_move = _float(
        _candidate_value(
            enriched,
            prediction,
            "expected_move_bps",
            "native_expected_move_bps",
            "expected_gross_move_bps",
        )
    )
    if expected_move is None:
        expected_move = _float(
            _candidate_value(
                enriched,
                prediction,
                "expected_move_after_cost_bps",
                "expected_edge_after_cost_bps",
                "pre_trade_expected_edge_after_cost_bps",
                "edge_after_cost_bps",
            )
        )
    if expected_move is None:
        return enriched
    cost_bps = sum(
        component or 0.0
        for component in (
            _float(_candidate_value(enriched, prediction, "actual_observed_spread_entry_bps", "spread_bps")),
            _float(_candidate_value(enriched, prediction, "expected_slippage_bps", "slippage_bps")),
            _float(_candidate_value(enriched, prediction, "fee_bps", "taker_fee_bps", "expected_fee_bps")),
            _float(_candidate_value(enriched, prediction, "expected_funding_bps", "funding_bps")),
        )
    )
    edge_bps = expected_move - cost_bps if side == "long" else -expected_move - cost_bps
    notional = _float(
        _first_present(
            enriched.get("target_notional_usd"),
            enriched.get("gross_notional_usd"),
            prediction.get("notional_usd") if isinstance(prediction, Mapping) else None,
        )
    )
    if notional is None or notional <= 0.0:
        notional = 1.0
    net_usd = round(notional * edge_bps / 10000.0, 8)
    enriched[selected_net_field] = net_usd
    enriched[alternate_selected_net_field] = net_usd
    enriched[f"expected_{side}_net_edge_bps"] = edge_bps
    enriched[f"{side}_expected_net_edge_bps"] = edge_bps
    return enriched


def _preemptive_cost_edge_bps_for_side(
    *,
    side: str,
    signed_move_bps: float | None,
) -> float | None:
    """Translate signed paper-entry moves into side-agnostic preemptive edge."""

    if signed_move_bps is None:
        return None
    if side == "short":
        return abs(signed_move_bps) if signed_move_bps < 0.0 else -abs(signed_move_bps)
    return signed_move_bps


def _reason_tokens(upper: str) -> set[str]:
    normalized = upper.replace("-", "_").replace(":", "_").replace("/", "_")
    return {part for part in normalized.split("_") if part}


def _has_token(tokens: set[str], *needles: str) -> bool:
    return any(needle in tokens for needle in needles)


def _has_phrase(upper: str, *needles: str) -> bool:
    return any(needle in upper for needle in needles)


def _blocker_class(reason: str) -> str:
    upper = reason.upper()
    tokens = _reason_tokens(upper)
    if _has_phrase(upper, "STALE", "FRESHNESS", "AVAILABLE_AT_AFTER_DECISION", "CUTOFF_AFTER_DECISION"):
        return "DATA_FRESHNESS_BLOCKER"
    if _has_token(tokens, "FEATURE", "HASH", "TA", "LINEAGE", "ADVANCED", "INDICATOR", "CONTEXT"):
        return "FEATURE_COVERAGE_BLOCKER"
    if _has_token(tokens, "MICROSTRUCTURE", "ORDERBOOK", "TAPE", "PUBLIC", "TRUST") or _has_phrase(upper, "PUBLIC_BOOK"):
        return "MICROSTRUCTURE_TRUST_BLOCKER"
    if _has_token(tokens, "PROVIDER", "COINANK", "COINGLASS", "MORALIS"):
        return "PROVIDER_MISSING_BLOCKER"
    if _has_token(tokens, "LOSS", "LOSSPROBABILITY", "PROBABILITY", "RATE") or _has_phrase(
        upper,
        "LOSS_PROBABILITY",
        "LOSS_RATE",
        "HIGH_CONFIDENCE_LOSS",
    ):
        return "PREEMPTIVE_LOSS_PROBABILITY_BLOCKER"
    if _has_token(tokens, "RISK", "GUARDIAN", "LIQUIDATION", "STOP", "ATR", "MFE", "EXIT", "HEDGE", "BUFFER") or _has_phrase(
        upper,
        "MAX_LOSS",
        "EXIT_FEASIBILITY",
        "EXIT_DEPTH",
    ):
        return "RISK_GATEWAY_BLOCKER"
    if "ORCHESTRATOR" in tokens:
        return "ORCHESTRATOR_BLOCKER"
    if _has_token(tokens, "POSITION", "EXPOSURE", "NOTIONAL", "STEP", "TICK"):
        return "POSITION_LIMIT_BLOCKER"
    if _has_token(tokens, "EXPECTED", "EDGE", "PNL", "BPS", "COST", "FUNDING", "SLIPPAGE", "SPREAD") or _has_phrase(upper, "BPS_ONLY"):
        return "EXPECTED_NET_EDGE_BLOCKER"
    if _has_token(tokens, "CONFIDENCE", "TRAINER", "SIDE", "BUCKET", "REGIME", "STRATEGY", "RAW", "CALIBRATED", "BREAKOUT", "TREND", "FVG", "EXPECTANCY") or _has_phrase(
        upper,
        "NO_TRADE_MODE",
        "SIDE_MISSING",
    ):
        return "TRAINER_CONFIDENCE_BLOCKER"
    if "ALLOCATOR" in upper:
        return "ALLOCATOR_BLOCKER"
    if _has_phrase(upper, "LIVE_DRY_RUN", "PACKET", "SYMBOL_FILTER"):
        return "LIVE_DRY_RUN_PACKET_BLOCKER"
    if "SIGNED" in upper:
        return "SIGNED_READ_OPERATOR_BLOCKER"
    return "TRAINER_CONFIDENCE_BLOCKER"


def _action_probability_map(
    row: Mapping[str, Any],
    prediction: Mapping[str, Any],
) -> dict[str, float] | None:
    raw = _first_present(
        row.get("action_probabilities"),
        prediction.get("action_probabilities"),
        row.get("action_probability_by_label"),
        prediction.get("action_probability_by_label"),
        prediction.get("policy_action_probabilities"),
    )
    if isinstance(raw, Mapping):
        out = {
            str(key).strip().lower(): numeric
            for key, value in raw.items()
            if (numeric := _float(value)) is not None
        }
        return out or None
    if isinstance(raw, list):
        labels = prediction.get("action_labels")
        if not isinstance(labels, list) or len(labels) != len(raw):
            labels = ["hold", "long", "short", "close", "hedge_reserved_fail_closed"][: len(raw)]
        out = {
            str(label).strip().lower(): numeric
            for label, value in zip(labels, raw)
            if (numeric := _float(value)) is not None
        }
        return out or None
    return None


def _confidence_truth_fields(
    *,
    row: Mapping[str, Any],
    prediction: Mapping[str, Any],
    action: Any,
    side: str | None,
    confidence_raw: float | None,
    confidence_calibrated: float | None,
    expected_long_net: float | None,
    expected_short_net: float | None,
    loss_probability: float | None,
    block_reasons: list[str],
) -> dict[str, Any]:
    normalized_action = str(action or "hold").strip().lower()
    probabilities = _action_probability_map(row, prediction) or {}
    selected_action_probability = _float(
        _first_present(
            row.get("selected_action_probability"),
            prediction.get("selected_action_probability"),
            row.get("opening_policy_argmax_probability"),
            prediction.get("opening_policy_argmax_probability"),
            probabilities.get(normalized_action),
        )
    )
    confidence_selected_action = _float(
        _first_present(selected_action_probability, confidence_calibrated, confidence_raw)
    )
    confidence_directional_long = _float(
        _first_present(
            row.get("confidence_directional_long"),
            prediction.get("confidence_directional_long"),
            probabilities.get("long"),
            confidence_selected_action if normalized_action == "long" else None,
        )
    )
    confidence_directional_short = _float(
        _first_present(
            row.get("confidence_directional_short"),
            prediction.get("confidence_directional_short"),
            probabilities.get("short"),
            confidence_selected_action if normalized_action == "short" else None,
        )
    )
    confidence_hold = _float(
        _first_present(
            row.get("confidence_hold"),
            prediction.get("confidence_hold"),
            probabilities.get("hold"),
            confidence_selected_action if normalized_action in {"hold", "no_trade", "flat"} else None,
        )
    )
    confidence_post_cost_long = (
        confidence_directional_long
        if confidence_directional_long is not None
        and expected_long_net is not None
        and expected_long_net > 0.0
        else 0.0
    )
    confidence_post_cost_short = (
        confidence_directional_short
        if confidence_directional_short is not None
        and expected_short_net is not None
        and expected_short_net > 0.0
        else 0.0
    )
    reasons_upper = " ".join(str(reason).upper() for reason in block_reasons)
    missing_matured_labels = (
        "BUCKET_EVIDENCE_INSUFFICIENT" in reasons_upper
        or "GUARDIAN_HALTED" in reasons_upper
        or "MISSING_MATURED" in reasons_upper
    )
    confidence_blockers: list[str] = []
    if normalized_action in {"hold", "no_trade", "none", "flat", "0"} or side is None:
        confidence_executable_trade: float | None = 0.0
        confidence_display_label = "Hold confidence"
        confidence_type = "hold_not_trade"
        confidence_blockers.append("selected_action_hold_not_executable_trade")
    elif side == "long":
        confidence_executable_trade = confidence_post_cost_long
        confidence_display_label = (
            "Post-cost executable confidence"
            if confidence_post_cost_long > 0.0
            else "Blocked by cost"
        )
        confidence_type = "directional_long_post_cost"
    elif side == "short":
        confidence_executable_trade = confidence_post_cost_short
        confidence_display_label = (
            "Post-cost executable confidence"
            if confidence_post_cost_short > 0.0
            else "Blocked by cost"
        )
        confidence_type = "directional_short_post_cost"
    else:
        confidence_executable_trade = 0.0
        confidence_display_label = "Unproven confidence"
        confidence_type = "not_side_specific"
        confidence_blockers.append("selected_action_not_side_specific")
    if loss_probability is not None and loss_probability >= 0.65:
        confidence_blockers.append("pre_trade_loss_probability_high")
        if confidence_executable_trade is not None:
            confidence_executable_trade = min(
                confidence_executable_trade,
                max(0.0, 1.0 - loss_probability),
            )
        confidence_display_label = "Blocked by loss probability"
    if missing_matured_labels:
        confidence_blockers.append("missing_matured_labels")
        if confidence_display_label == "Post-cost executable confidence":
            confidence_display_label = "Unproven confidence"
    confidence_a_plus_eligible = (
        confidence_executable_trade is not None
        and confidence_executable_trade > 0.0
        and not confidence_blockers
        and not missing_matured_labels
    )
    return {
        "selected_action_probability": selected_action_probability,
        "action_probabilities": probabilities or None,
        "confidence_directional_long": confidence_directional_long,
        "confidence_directional_short": confidence_directional_short,
        "confidence_hold": confidence_hold,
        "confidence_selected_action": confidence_selected_action,
        "confidence_post_cost_long": confidence_post_cost_long,
        "confidence_post_cost_short": confidence_post_cost_short,
        "confidence_executable_trade": confidence_executable_trade,
        "confidence_display_label": confidence_display_label,
        "confidence_type": confidence_type,
        "confidence_a_plus_eligible": confidence_a_plus_eligible,
        "confidence_tradeability_block_reasons": list(dict.fromkeys(confidence_blockers)),
    }


def _paper_exploration_projection_hash(row: Mapping[str, Any], stage: str) -> str:
    payload = {
        "stage": stage,
        "candidate_id": row.get("candidate_id"),
        "prediction_id": row.get("prediction_id"),
        "signal_id": row.get("signal_id"),
        "symbol": row.get("symbol"),
        "timeframe": row.get("timeframe"),
        "side": row.get("side"),
        "feature_vector_hash": row.get("feature_vector_hash"),
        "decision_time": row.get("decision_time"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:24]


def _project_paper_exploration_decision_coverage(
    row: Mapping[str, Any],
    *,
    above_floor: bool,
    resolution: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a paper-only view with deterministic risk/orchestrator decisions.

    This is inventory evidence only. It never writes Redis and never changes
    exchange-routing behavior.
    """

    projected = dict(row)
    current_blocker = str(resolution.get("current_blocker") or "EXPLORATION_ROW_BLOCKED")
    blockers = [
        str(reason)
        for reason in _as_list(resolution.get("row_blockers"))
        if str(reason).strip()
    ] or [current_blocker]
    record: dict[str, Any] = {
        "projection_source": "paper_exploration_inventory_dry_run",
        "projection_live_blocked": True,
        "missing_decision_reason": None,
        "risk_input_written": False,
        "risk_input_hash": None,
        "risk_decision_id": _first_present(row.get("risk_decision_id"), row.get("paper_exploration_risk_decision_id")),
        "risk_decision": _first_present(row.get("risk_decision"), row.get("risk_action")),
        "risk_block_reasons": _as_list(_first_present(row.get("risk_block_reasons"), row.get("risk_controller_block_reasons"))),
        "orchestrator_input_written": False,
        "orchestrator_input_hash": None,
        "orchestrator_decision_id": _first_present(row.get("orchestrator_decision_id"), row.get("paper_exploration_orchestrator_decision_id")),
        "orchestrator_decision": _first_present(row.get("orchestrator_decision"), row.get("orchestrator_action")),
        "orchestrator_block_reasons": _as_list(row.get("orchestrator_block_reasons")),
    }
    if not above_floor:
        return {"row": projected, **record}

    timestamp = _as_dict(resolution.get("timestamp_integrity"))
    if timestamp.get("real_lookahead_block") is True:
        record["missing_decision_reason"] = "REAL_LOOKAHEAD_BLOCK_BEFORE_RISK"
        return {"row": projected, **record}

    risk_text = str(record["risk_decision"] or "").strip().upper()
    risk_missing = risk_text in {"", "MISSING"}
    risk_input_hash = _paper_exploration_projection_hash(projected, "risk")
    record["risk_input_written"] = True
    record["risk_input_hash"] = risk_input_hash
    if risk_missing:
        risk_decision_id = str(record["risk_decision_id"] or f"paperexp_risk_{risk_input_hash}")
        projected["risk_decision"] = "BLOCKED"
        projected["risk_action"] = "blocked"
        projected["risk_decision_id"] = risk_decision_id
        projected["risk_block_reasons"] = blockers
        projected["risk_decision_record"] = {
            "risk_decision_id": risk_decision_id,
            "risk_action": "blocked",
            "risk_reason_code": current_blocker,
            "risk_block_reasons": blockers,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "projection_source": "paper_exploration_inventory_dry_run",
        }
        record["risk_decision_id"] = risk_decision_id
        record["risk_decision"] = "BLOCKED"
        record["risk_block_reasons"] = blockers

    orch_text = str(record["orchestrator_decision"] or "").strip().upper()
    orch_missing = orch_text in {"", "MISSING"}
    orch_input_hash = _paper_exploration_projection_hash(projected, "orchestrator")
    record["orchestrator_input_written"] = True
    record["orchestrator_input_hash"] = orch_input_hash
    if orch_missing:
        orchestrator_decision_id = str(
            record["orchestrator_decision_id"] or f"paperexp_orch_{orch_input_hash}"
        )
        projected["orchestrator_decision"] = "BLOCKED"
        projected["orchestrator_action"] = "blocked"
        projected["orchestrator_decision_id"] = orchestrator_decision_id
        projected["orchestrator_block_reasons"] = blockers
        projected["orchestrator_decision_record"] = {
            "decision_id": orchestrator_decision_id,
            "decision_action": "blocked",
            "decision_reason_code": current_blocker,
            "orchestrator_block_reasons": blockers,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "projection_source": "paper_exploration_inventory_dry_run",
        }
        record["orchestrator_decision_id"] = orchestrator_decision_id
        record["orchestrator_decision"] = "BLOCKED"
        record["orchestrator_block_reasons"] = blockers

    return {"row": projected, **record}


def _normalize_candidate(
    row: Mapping[str, Any],
    *,
    prediction: Mapping[str, Any] | None,
    generated_utc: str,
) -> dict[str, Any]:
    prediction = prediction if isinstance(prediction, Mapping) else {}
    original_row = _with_selected_side_diagnostic_usd(row, prediction)
    preemptive_context = str(
        _first_present(
            original_row.get("preemptive_action"),
            original_row.get("preemptive_decision"),
            original_row.get("paper_opportunity_tier"),
            original_row.get("paper_exploration_tier"),
        )
        or ""
    ).upper()
    recalculate_incomplete_existing_allocation = (
        original_row.get("paper_risk_controller_exploration") is True
        or "PAPER_RISK_CONTROLLER_EXPLORATION" in preemptive_context
        or "GUARDIAN_HALTED" in preemptive_context
    )
    allocator_packet = build_allocator_simulation(
        original_row,
        prediction=prediction,
        generated_utc=generated_utc,
        recalculate_incomplete_existing_allocation=recalculate_incomplete_existing_allocation,
    )
    original_max_loss = _float(
        _first_present(
            original_row.get("expected_max_loss_usd"),
            original_row.get("max_loss_usd"),
            original_row.get("pre_trade_max_loss_usd"),
        )
    )
    allocator_max_loss = _float(allocator_packet.get("expected_max_loss_usd"))
    conservative_max_loss = max(
        value for value in (original_max_loss, allocator_max_loss) if value is not None
    ) if any(value is not None for value in (original_max_loss, allocator_max_loss)) else None
    row = {
        **original_row,
        "allocation": allocator_packet,
        "allocator_simulation": allocator_packet,
        "allocator_decision_id": allocator_packet.get("allocator_decision_id"),
        "allocator_decision": allocator_packet.get("allocator_decision"),
        "allocator_block_reasons": allocator_packet.get("allocator_block_reasons") or allocator_packet.get("block_reasons") or [],
        "recommended_leverage": allocator_packet.get("recommended_leverage"),
        "recommended_leverage_source": allocator_packet.get("recommended_leverage_source"),
        "recommended_margin_mode": allocator_packet.get("recommended_margin_mode"),
        "recommended_margin_mode_source": allocator_packet.get("recommended_margin_mode_source"),
        "gross_notional_usd": allocator_packet.get("gross_notional_usd"),
        "target_notional_usd": allocator_packet.get("target_notional_usd"),
        "target_notional_usdt": allocator_packet.get("target_notional_usdt"),
        "recommended_notional_usd": _first_present(
            allocator_packet.get("recommended_notional_usd"),
            allocator_packet.get("target_notional_usd"),
            allocator_packet.get("gross_notional_usd"),
        ),
        "allocated_margin_usd": allocator_packet.get("allocated_margin_usd"),
        "risk_budget_usd": allocator_packet.get("risk_budget_usd"),
        "max_loss_usd": conservative_max_loss if conservative_max_loss is not None else allocator_packet.get("max_loss_usd"),
        "expected_max_loss_usd": conservative_max_loss if conservative_max_loss is not None else allocator_packet.get("expected_max_loss_usd"),
        "expected_net_pnl_usd": allocator_packet.get("expected_net_pnl_usd"),
        "expected_fee_usd": allocator_packet.get("expected_fee_usd"),
        "expected_fees_usd": allocator_packet.get("expected_fees_usd"),
        "expected_slippage_usd": allocator_packet.get("expected_slippage_usd"),
        "expected_funding_usd": allocator_packet.get("expected_funding_usd"),
        "liquidation_buffer_usd": allocator_packet.get("liquidation_buffer_usd"),
        "expected_liquidation_buffer_usd": allocator_packet.get("expected_liquidation_buffer_usd"),
        "liquidation_buffer_pct": allocator_packet.get("liquidation_buffer_pct"),
        "maintenance_margin_usd": allocator_packet.get("maintenance_margin_usd"),
        "estimated_liquidation_price": allocator_packet.get("estimated_liquidation_price"),
        "distance_to_liquidation_usd": allocator_packet.get("distance_to_liquidation_usd"),
        "hedge_required": allocator_packet.get("hedge_required"),
        "hedge_plan": allocator_packet.get("hedge_plan"),
        "signed_read_status": allocator_packet.get("signed_read_status"),
        "available_margin_usd": allocator_packet.get("available_margin_usd"),
    }
    provider = _provider_presence(prediction)
    risk_decision = _risk_status(row)
    orchestrator_decision = _orchestrator_status(row)
    allocator_decision = _allocator_status(row)
    price_field, price_value = _candidate_field(
        row,
        prediction,
        "selected_execution_price",
        "entry_price",
        "current_price",
        "mark_price",
        "last_trade_price",
        "last_price",
        "price",
        "price_reference",
        "close",
        "close_price",
    )
    current_price = _float(price_value)
    if current_price is not None and current_price <= 0.0:
        current_price = None
    mark_price = _float(_candidate_value(row, prediction, "mark_price"))
    index_price = _float(_candidate_value(row, prediction, "index_price"))
    last_trade_price = _float(_candidate_value(row, prediction, "last_trade_price", "last_price", "price", "close", "close_price"))
    best_bid = _float(_candidate_value(row, prediction, "best_bid", "bid", "bid_price"))
    best_ask = _float(_candidate_value(row, prediction, "best_ask", "ask", "ask_price"))
    price_source = _first_present(
        row.get("price_source"),
        row.get("current_price_source"),
        prediction.get("price_source"),
        prediction.get("market_data_source"),
        "candidate_payload" if current_price is not None else None,
    )
    price_missing_reason = _first_present(
        row.get("price_missing_reason"),
        row.get("current_price_missing_reason"),
        prediction.get("price_missing_reason"),
        prediction.get("current_price_missing_reason"),
    )
    current_price_can_size_trade = row.get("can_size_trade")
    if current_price_can_size_trade is None:
        current_price_can_size_trade = row.get("current_price_can_size_trade")
    if current_price_can_size_trade is None and current_price is not None:
        current_price_can_size_trade = True
    price_available_at = _first_present(
        row.get("price_available_at"),
        row.get("current_price_available_at"),
        row.get("market_price_available_at"),
        prediction.get("price_available_at"),
        prediction.get("market_data_available_at"),
        row.get("available_at"),
        prediction.get("available_at"),
    )
    expected_net = _float(
        _first_present(
            row.get("expected_net_pnl_usd"),
            row.get("pre_trade_expected_net_pnl_usd"),
            prediction.get("expected_net_pnl_usd"),
        )
    )
    expected_fees = _float(
        _first_present(
            row.get("expected_fees_usd"),
            row.get("expected_fee_usd"),
            row.get("pre_trade_expected_fees_usd"),
            prediction.get("expected_fees_usd"),
        )
    )
    expected_slippage = _float(
        _first_present(row.get("expected_slippage_usd"), row.get("pre_trade_slippage_risk_usd"), prediction.get("expected_slippage_usd"))
    )
    expected_funding = _float(_first_present(row.get("expected_funding_usd"), row.get("pre_trade_funding_risk_usd"), prediction.get("expected_funding_usd")))
    expected_max_loss = _float(
        _first_present(row.get("expected_max_loss_usd"), row.get("pre_trade_max_loss_usd"), row.get("max_loss_usd"), row.get("max_loss_if_stop_hit"))
    )
    latency_reserve = _float(_candidate_value(row, prediction, "latency_reserve_usd", "pre_trade_latency_reserve_usd"))
    liquidation_risk_reserve = _float(
        _candidate_value(row, prediction, "liquidation_risk_reserve_usd", "pre_trade_liquidation_risk_usd")
    )
    exit_failure_reserve = _float(_candidate_value(row, prediction, "exit_failure_reserve_usd", "pre_trade_exit_failure_reserve_usd"))
    expected_cost = sum(
        component or 0.0
        for component in (
            expected_fees,
            expected_slippage,
            expected_funding,
            latency_reserve,
            liquidation_risk_reserve,
            exit_failure_reserve,
        )
    )
    explicit_expected_cost = _float(_candidate_value(row, prediction, "expected_cost_usd", "pre_trade_expected_cost_usd"))
    if explicit_expected_cost is not None:
        expected_cost = max(expected_cost, explicit_expected_cost)
    expected_gross = _float(
        _first_present(
            row.get("expected_gross_pnl_usd"),
            row.get("pre_trade_expected_gross_pnl_usd"),
            prediction.get("expected_gross_pnl_usd"),
            prediction.get("pre_trade_expected_gross_pnl_usd"),
            allocator_packet.get("expected_gross_pnl_usd"),
        )
    )
    if expected_gross is None and expected_net is not None:
        expected_gross = expected_net + expected_cost
    expected_move_after_cost_bps = _float(
        _candidate_value(
            row,
            prediction,
            "expected_move_after_cost_bps",
            "expected_edge_after_cost_bps",
            "pre_trade_expected_edge_after_cost_bps",
            "edge_after_cost_bps",
        )
    )
    expected_move = _float(
        _candidate_value(
            row,
            prediction,
            "expected_move_bps",
            "native_expected_move_bps",
            "expected_gross_move_bps",
        )
    )
    if expected_move is None:
        expected_move = expected_move_after_cost_bps
    notional_for_move = _float(_first_present(row.get("target_notional_usd"), row.get("gross_notional_usd"), prediction.get("notional_usd")))
    if expected_move is None and expected_gross is not None and notional_for_move not in (None, 0.0):
        expected_move = expected_gross / abs(notional_for_move) * 10000.0
    confidence_raw = _float(_first_present(row.get("confidence_raw"), prediction.get("confidence_raw"), row.get("confidence"), prediction.get("confidence")))
    confidence_calibrated = _float(
        _first_present(
            row.get("confidence_calibrated"),
            row.get("calibrated_confidence"),
            prediction.get("confidence_calibrated"),
            prediction.get("calibrated_confidence"),
        )
    )
    liquidation_buffer_usd = _float(
        _first_present(row.get("expected_liquidation_buffer_usd"), row.get("liquidation_buffer_usd"), prediction.get("liquidation_buffer_usd"))
    )
    if liquidation_buffer_usd is None:
        notional = _float(_first_present(row.get("target_notional_usd"), row.get("gross_notional_usd"), prediction.get("notional_usd")))
        buffer_bps = _float(_first_present(row.get("liquidation_buffer_bps"), row.get("liquidation_buffer")))
        if notional is not None and buffer_bps is not None:
            liquidation_buffer_usd = round(abs(notional) * buffer_bps / 10000.0, 8)
    feature_vector_hash = _lineage_value(row, prediction, "feature_vector_hash")
    feature_cutoff = _first_present(
        _lineage_value(row, prediction, "feature_cutoff"),
        prediction.get("ppo_feature_cutoff"),
        prediction.get("masa_feature_cutoff"),
    )
    feature_snapshot_id = _first_present(
        _lineage_value(row, prediction, "feature_snapshot_id"),
        prediction.get("entry_feature_snapshot_id"),
        _as_dict(prediction.get("entry_feature_snapshot")).get("feature_snapshot_id"),
    )
    # Feature availability is lineage, not a market-price clock. A fresh mark
    # may arrive before an older feature snapshot has been durably published;
    # borrowing that price clock would make the snapshot appear PIT-eligible.
    available_at = _first_present(
        _lineage_value(row, prediction, "feature_available_at"),
        _lineage_value(row, prediction, "entry_feature_available_at"),
        _lineage_value(row, prediction, "source_available_at"),
        _lineage_value(row, prediction, "available_at"),
    )
    decision_time = _first_present(
        row.get("decision_time"),
        row.get("preemptive_decision_time"),
        row.get("source_decision_time"),
        prediction.get("decision_time"),
        prediction.get("source_decision_time"),
    )
    prediction_age_seconds = _candidate_age_seconds(row, prediction)
    stale_prediction = (
        prediction_age_seconds is None
        or prediction_age_seconds > SESSION_MAX_PREDICTION_AGE_SECONDS
    )
    preemptive_action = str(row.get("preemptive_action") or "")
    preemptive_decision = str(row.get("preemptive_decision") or "")
    action = _first_present(row.get("action"), row.get("selected_action"), prediction.get("selected_action"), prediction.get("ppo_action"))
    side = _side(row, prediction)
    explicit_expected_long_net = _float(_candidate_value(row, prediction, "expected_long_net_pnl_usd", "long_expected_net_pnl_usd"))
    explicit_expected_short_net = _float(_candidate_value(row, prediction, "expected_short_net_pnl_usd", "short_expected_net_pnl_usd"))
    expected_long_net = explicit_expected_long_net
    expected_short_net = explicit_expected_short_net
    expected_long_net_edge_bps = _float(_candidate_value(row, prediction, "expected_long_net_edge_bps", "long_expected_net_edge_bps"))
    expected_short_net_edge_bps = _float(_candidate_value(row, prediction, "expected_short_net_edge_bps", "short_expected_net_edge_bps"))
    if expected_long_net_edge_bps is None and expected_move is not None:
        expected_long_net_edge_bps = expected_move - (
            _float(_candidate_value(row, prediction, "actual_observed_spread_entry_bps", "spread_bps")) or 0.0
        ) - (_float(_candidate_value(row, prediction, "expected_slippage_bps", "slippage_bps")) or 0.0) - (
            _float(_candidate_value(row, prediction, "fee_bps", "taker_fee_bps", "expected_fee_bps")) or 0.0
        ) - (_float(_candidate_value(row, prediction, "expected_funding_bps", "funding_bps")) or 0.0)
    if expected_short_net_edge_bps is None and expected_move is not None:
        expected_short_net_edge_bps = -expected_move - (
            _float(_candidate_value(row, prediction, "actual_observed_spread_entry_bps", "spread_bps")) or 0.0
        ) - (_float(_candidate_value(row, prediction, "expected_slippage_bps", "slippage_bps")) or 0.0) - (
            _float(_candidate_value(row, prediction, "fee_bps", "taker_fee_bps", "expected_fee_bps")) or 0.0
        ) - (_float(_candidate_value(row, prediction, "expected_funding_bps", "funding_bps")) or 0.0)
    per_side_notional = notional_for_move
    per_side_notional_basis = "candidate_notional_usd"
    if per_side_notional is None or per_side_notional <= 0.0:
        per_side_notional = 1.0
        per_side_notional_basis = "diagnostic_unit_notional_usd_no_allocator_size"
    if expected_long_net is None and expected_long_net_edge_bps is not None:
        expected_long_net = round(per_side_notional * expected_long_net_edge_bps / 10000.0, 8)
    if expected_short_net is None and expected_short_net_edge_bps is not None:
        expected_short_net = round(per_side_notional * expected_short_net_edge_bps / 10000.0, 8)
    explicit_long_cost = _float(_candidate_value(row, prediction, "long_expected_cost_usd", "expected_long_cost_usd"))
    explicit_short_cost = _float(_candidate_value(row, prediction, "short_expected_cost_usd", "expected_short_cost_usd"))
    long_expected_cost = explicit_long_cost
    short_expected_cost = explicit_short_cost
    if long_expected_cost is None:
        long_expected_cost = expected_cost
    if short_expected_cost is None:
        short_expected_cost = expected_cost
    explicit_long_gross = _float(_candidate_value(row, prediction, "long_expected_gross_pnl_usd", "expected_long_gross_pnl_usd"))
    explicit_short_gross = _float(_candidate_value(row, prediction, "short_expected_gross_pnl_usd", "expected_short_gross_pnl_usd"))
    long_expected_gross = (
        explicit_long_gross
        if explicit_long_gross is not None
        else
        round(expected_long_net + long_expected_cost, 8)
        if expected_long_net is not None
        else None
    )
    short_expected_gross = (
        explicit_short_gross
        if explicit_short_gross is not None
        else
        round(expected_short_net + short_expected_cost, 8)
        if expected_short_net is not None
        else None
    )
    long_expected_max_loss = expected_max_loss
    short_expected_max_loss = expected_max_loss
    long_loss_probability = _float(_candidate_value(row, prediction, "long_loss_probability"))
    short_loss_probability = _float(_candidate_value(row, prediction, "short_loss_probability"))
    raw_market_state_integrity_score = _float(
        _candidate_value(row, prediction, "market_state_integrity_score")
    )
    allocator_market_state_integrity_score = _float(
        allocator_packet.get("market_state_integrity_score")
    )
    microstructure_trust_score = _float(
        _candidate_value(row, prediction, "microstructure_trust_score")
    )
    if microstructure_trust_score is None and raw_market_state_integrity_score is not None:
        microstructure_trust_score = (
            raw_market_state_integrity_score / 100.0
            if raw_market_state_integrity_score > 1.0
            else raw_market_state_integrity_score
        )
    composite_microstructure_trust_score = _float(
        _candidate_value(row, prediction, "composite_microstructure_trust_score")
    )
    if composite_microstructure_trust_score is None:
        composite_microstructure_trust_score = microstructure_trust_score
    if raw_market_state_integrity_score is not None:
        market_state_integrity_score = (
            raw_market_state_integrity_score * 100.0
            if raw_market_state_integrity_score <= 1.0
            else raw_market_state_integrity_score
        )
    elif composite_microstructure_trust_score is not None:
        market_state_integrity_score = (
            composite_microstructure_trust_score * 100.0
            if composite_microstructure_trust_score <= 1.0
            else composite_microstructure_trust_score
        )
    else:
        market_state_integrity_score = allocator_market_state_integrity_score
    market_state_integrity_source = _first_present(
        _candidate_value(row, prediction, "market_state_integrity_source"),
        allocator_packet.get("market_state_integrity_source"),
    )
    trade_tape_confirmation_score = _float(
        _candidate_value(row, prediction, "trade_tape_confirmation_score", "tape_confirmation_score")
    )
    expected_exit_depth_usd = _float(
        _candidate_value(row, prediction, "expected_exit_depth_usd", "liquidity_exit_depth", "orderbook_depth_usd", "top_of_book_depth_usd")
    )
    exit_feasible_raw = _candidate_value(row, prediction, "exit_feasible")
    exit_feasible = None if exit_feasible_raw is None else _bool(exit_feasible_raw)
    exit_feasibility_score = _float(_candidate_value(row, prediction, "exit_feasibility_score"))
    best_side = None
    best_side_expected_net = None
    if expected_long_net is not None or expected_short_net is not None:
        long_value = expected_long_net if expected_long_net is not None else float("-inf")
        short_value = expected_short_net if expected_short_net is not None else float("-inf")
        best_side = "long" if long_value >= short_value else "short"
        best_side_expected_net = long_value if best_side == "long" else short_value
    no_side_reason = _no_side_reason(
        row,
        prediction,
        expected_long_net=expected_long_net,
        expected_short_net=expected_short_net,
        feature_vector_hash=feature_vector_hash,
    )
    best_side_rejected_reason = None
    if side is None:
        best_side_rejected_reason = _candidate_value(row, prediction, "why_best_side_rejected", "best_side_rejected_reason")
        if best_side_rejected_reason is None and expected_long_net is not None and expected_short_net is not None:
            if expected_long_net <= 0.0 and expected_short_net <= 0.0:
                best_side_rejected_reason = (
                    "both_long_and_short_diagnostic_net_pnl_usd_non_positive"
                    f"_long_{expected_long_net:.8f}_short_{expected_short_net:.8f}"
                )
            elif best_side:
                best_value = expected_long_net if best_side == "long" else expected_short_net
                best_side_rejected_reason = f"selected_hold_best_side_{best_side}_diagnostic_net_pnl_usd_{best_value:.8f}"
        if best_side_rejected_reason is None:
            best_side_rejected_reason = no_side_reason
    elif side == "long":
        promote_selected_side_net = explicit_expected_long_net is not None or expected_net is None or expected_net <= 0.0
        promote_selected_side_details = expected_net is None or expected_net <= 0.0
        if promote_selected_side_net and expected_long_net is not None:
            expected_net = expected_long_net
        if (explicit_long_cost is not None or promote_selected_side_details) and long_expected_cost is not None:
            expected_cost = long_expected_cost
        if (explicit_long_gross is not None or promote_selected_side_details) and long_expected_gross is not None:
            expected_gross = long_expected_gross
    elif side == "short":
        promote_selected_side_net = explicit_expected_short_net is not None or expected_net is None or expected_net <= 0.0
        promote_selected_side_details = expected_net is None or expected_net <= 0.0
        if promote_selected_side_net and expected_short_net is not None:
            expected_net = expected_short_net
        if (explicit_short_cost is not None or promote_selected_side_details) and short_expected_cost is not None:
            expected_cost = short_expected_cost
        if (explicit_short_gross is not None or promote_selected_side_details) and short_expected_gross is not None:
            expected_gross = short_expected_gross
    raw_reasons = [
        str(reason)
        for reason in _as_list(
            _first_present(row.get("block_reasons"), row.get("preemptive_block_reasons"), row.get("preemptive_decision_reasons"))
        )
    ]
    raw_reasons.extend(str(reason) for reason in _as_list(row.get("allocator_block_reasons")))
    block_reasons = list(dict.fromkeys(reason for reason in raw_reasons if reason and reason.upper() != "UNKNOWN"))

    if not row.get("preemptive_decision_id"):
        block_reasons.append("LINEAGE_PREEMPTIVE_DECISION_ID_MISSING")
    if not feature_vector_hash:
        block_reasons.append("LINEAGE_FEATURE_VECTOR_HASH_MISSING")
    if stale_prediction:
        block_reasons.append("STALE_PREDICTION_NOT_CURRENT_SESSION")
    if expected_net is None:
        if _float(row.get("expected_edge_after_cost_bps")) is not None:
            block_reasons.append("ECONOMICS_BPS_ONLY")
        block_reasons.append("ECONOMICS_EXPECTED_NET_PNL_USD_MISSING")
    elif expected_net <= 0:
        block_reasons.append("EXPECTED_NET_EDGE_NON_POSITIVE")
    if expected_gross is None:
        block_reasons.append("ECONOMICS_EXPECTED_GROSS_PNL_USD_MISSING")
    if current_price is None:
        block_reasons.append("CURRENT_PRICE_MISSING")
    elif current_price_can_size_trade is False:
        block_reasons.append("CURRENT_PRICE_FALLBACK_NOT_EXECUTION_GRADE")
    loss_probability = _float(row.get("pre_trade_loss_probability"))
    if long_loss_probability is None:
        long_loss_probability = loss_probability
    if short_loss_probability is None:
        short_loss_probability = loss_probability
    if loss_probability is None:
        block_reasons.append("PRE_TRADE_LOSS_PROBABILITY_MISSING")
    elif loss_probability >= 0.80:
        block_reasons.append("PRE_TRADE_LOSS_PROBABILITY_ABOVE_ALLOWED_BOUND")
    if expected_max_loss is None:
        block_reasons.append("RISK_MAX_LOSS_USD_MISSING")
    if liquidation_buffer_usd is None:
        block_reasons.append("RISK_LIQUIDATION_BUFFER_USD_MISSING")
    side = _side(row, prediction)
    if side is None:
        block_reasons.append("TRAINER_SIDE_MISSING_OR_HOLD")
    if risk_decision != "PASS":
        block_reasons.append("RISK_GATEWAY_NOT_PASS")
    if orchestrator_decision != "PASS":
        block_reasons.append("ORCHESTRATOR_NOT_PASS")
    if allocator_decision != "PASS":
        block_reasons.append("ALLOCATOR_NOT_PASS")
    if str(row.get("microstructure_trust_state") or "").upper() in {"UNSAFE", "FAIL_CLOSED"}:
        block_reasons.append("MICROSTRUCTURE_TRUST_FAIL_CLOSED")
    if not provider["TA_features_present"]:
        block_reasons.append("FEATURE_COVERAGE_TA_MISSING")
    if not provider["microstructure_features_present"]:
        block_reasons.append("FEATURE_COVERAGE_MICROSTRUCTURE_MISSING")
    if not provider["advanced_indicator_features_present"]:
        block_reasons.append("FEATURE_COVERAGE_ADVANCED_INDICATOR_MISSING")
    if not provider["CoinAnk_features_present"]:
        block_reasons.append("PROVIDER_COINANK_REQUIRED_FEATURES_MISSING")
    if any(
        _explicit_false(row.get(field))
        for field in ("counts_as_final_A_plus", "counts_as_final_a_plus")
    ):
        block_reasons.append("COUNTS_AS_FINAL_A_PLUS_FALSE")
    if _is_probation(row):
        block_reasons.append("PROBATION_ROW_NOT_FINAL_A_PLUS")
    if _is_reconstructed(row):
        block_reasons.append("EVIDENCE_RECONSTRUCTED_OR_LEGACY_ROW_NOT_A_PLUS")
    if preemptive_action != "ALLOW_A_PLUS_CANDIDATE" or preemptive_decision != "ALLOW":
        block_reasons.append("PREEMPTIVE_ACTION_NOT_A_PLUS_ALLOW")
    block_reasons = _drop_contradicted_microstructure_trust_reasons(
        block_reasons,
        microstructure_trust_score=microstructure_trust_score,
        composite_microstructure_trust_score=composite_microstructure_trust_score,
        microstructure_trust_state=row.get("microstructure_trust_state"),
        microstructure_trust_status=row.get("microstructure_trust_status"),
    )

    unique_reasons = list(dict.fromkeys(block_reasons))
    reason_classes = sorted({_blocker_class(reason) for reason in unique_reasons})
    a_plus = not unique_reasons and preemptive_action == "ALLOW_A_PLUS_CANDIDATE" and preemptive_decision == "ALLOW"
    live_ready = a_plus and row.get("live_dry_run_packet_complete") is True
    if a_plus and not live_ready:
        unique_reasons.append("LIVE_DRY_RUN_PACKET_INCOMPLETE")
        reason_classes = sorted({_blocker_class(reason) for reason in unique_reasons})
        a_plus = False
    confidence_truth = _confidence_truth_fields(
        row=row,
        prediction=prediction,
        action=action,
        side=side,
        confidence_raw=confidence_raw,
        confidence_calibrated=confidence_calibrated,
        expected_long_net=expected_long_net,
        expected_short_net=expected_short_net,
        loss_probability=loss_probability,
        block_reasons=unique_reasons,
    )

    normalized = {
        "candidate_id": _first_present(row.get("candidate_id"), prediction.get("candidate_id"), prediction.get("decision_id"), _candidate_hash_basis(row, prediction)),
        "symbol": _first_present(row.get("symbol"), prediction.get("symbol")),
        "timeframe": _first_present(row.get("timeframe"), prediction.get("timeframe")),
        "side": side,
        "no_side_reason": no_side_reason,
        "action": action,
        "best_side": best_side,
        "best_side_rejected_reason": best_side_rejected_reason,
        "strategy_id": _first_present(row.get("strategy_id"), prediction.get("strategy_id"), _as_dict(prediction.get("strategy_router")).get("selected_mode")),
        "strategy_family": _first_present(row.get("strategy_family"), prediction.get("strategy_family")),
        "strategy_selected_mode": _first_present(row.get("strategy_selected_mode"), prediction.get("strategy_selected_mode")),
        "strategy_router_selected_mode": _first_present(
            row.get("strategy_router_selected_mode"),
            prediction.get("strategy_router_selected_mode"),
            _as_dict(prediction.get("strategy_router")).get("selected_mode"),
        ),
        "strategy_regime_labels": _as_list(
            _first_present(
                row.get("strategy_regime_labels"),
                prediction.get("strategy_regime_labels"),
            )
        ),
        "market_regime": _first_present(row.get("market_regime"), prediction.get("market_regime")),
        "market_regime_at_entry": _first_present(
            row.get("market_regime_at_entry"),
            prediction.get("market_regime_at_entry"),
        ),
        "entry_reason": _first_present(row.get("entry_reason"), prediction.get("entry_reason")),
        "strategy_supply_hypothesis": bool(_first_present(row.get("strategy_supply_hypothesis"), prediction.get("strategy_supply_hypothesis"), False)),
        "strategy_supply_hypothesis_id": _first_present(
            row.get("strategy_supply_hypothesis_id"),
            prediction.get("strategy_supply_hypothesis_id"),
            row.get("hypothesis_id"),
            prediction.get("hypothesis_id"),
            row.get("strategy_id"),
            prediction.get("strategy_id"),
        ),
        "strategy_supply_stage_rejected_reason": _first_present(
            row.get("strategy_supply_stage_rejected_reason"),
            prediction.get("strategy_supply_stage_rejected_reason"),
        ),
        "strategy_supply_gate_clean": _first_present(
            row.get("strategy_supply_gate_clean"),
            prediction.get("strategy_supply_gate_clean"),
        ),
        "strategy_supply_positive_net_usd": _first_present(
            row.get("strategy_supply_positive_net_usd"),
            prediction.get("strategy_supply_positive_net_usd"),
        ),
        "source_tier": _first_present(row.get("source_tier"), prediction.get("source_tier")),
        "source_runtime_key": _first_present(row.get("source_runtime_key"), prediction.get("redis_key")),
        "entry_feature_candle_closed_confirmed": _first_present(
            row.get("entry_feature_candle_closed_confirmed"),
            prediction.get("entry_feature_candle_closed_confirmed"),
        ),
        "candle_closed_confirmed": _first_present(
            row.get("candle_closed_confirmed"),
            prediction.get("candle_closed_confirmed"),
        ),
        "last_closed_candle_open_ts_ms": _first_present(
            row.get("last_closed_candle_open_ts_ms"),
            prediction.get("last_closed_candle_open_ts_ms"),
        ),
        "last_closed_candle_close_ts_ms": _first_present(
            row.get("last_closed_candle_close_ts_ms"),
            prediction.get("last_closed_candle_close_ts_ms"),
        ),
        "ta_source_key": _first_present(
            row.get("ta_source_key"),
            prediction.get("ta_source_key"),
        ),
        "prediction_id": _first_present(row.get("prediction_id"), prediction.get("prediction_id")),
        "signal_id": _first_present(row.get("signal_id"), prediction.get("signal_id")),
        "preemptive_decision_id": row.get("preemptive_decision_id"),
        "trainer_prediction_id": prediction.get("prediction_id") or row.get("prediction_id"),
        "feature_snapshot_id": feature_snapshot_id,
        "feature_vector_hash": feature_vector_hash,
        "provider_feature_hashes": _as_dict(
            _first_present(
                row.get("provider_feature_hashes"),
                prediction.get("provider_feature_hashes"),
                row.get("source_hashes"),
                prediction.get("source_hashes"),
            )
        ),
        "source_hashes": _as_dict(
            _first_present(
                row.get("source_hashes"),
                prediction.get("source_hashes"),
                row.get("provider_feature_hashes"),
                prediction.get("provider_feature_hashes"),
            )
        ),
        "feature_cutoff": feature_cutoff,
        "feature_available_at": available_at,
        "available_at": available_at,
        "decision_time": decision_time,
        "source_available_at": _first_present(
            row.get("source_available_at"),
            prediction.get("source_available_at"),
            available_at,
        ),
        "source_decision_time": _first_present(
            row.get("source_decision_time"),
            row.get("decision_time"),
            row.get("preemptive_decision_time"),
            prediction.get("source_decision_time"),
            prediction.get("decision_time"),
            decision_time,
        ),
        "source_generated_utc": _first_present(row.get("source_generated_utc"), row.get("generated_utc"), row.get("generated_at"), prediction.get("source_generated_utc"), prediction.get("generated_utc"), prediction.get("generated_at")),
        "inventory_generated_utc": generated_utc,
        "prediction_age_seconds": prediction_age_seconds,
        "stale_prediction": stale_prediction,
        "confidence": _float(_first_present(row.get("confidence"), row.get("calibrated_confidence"), prediction.get("confidence_calibrated"), prediction.get("confidence_raw"))),
        "confidence_raw": confidence_raw,
        "confidence_calibrated": confidence_calibrated,
        **confidence_truth,
        "current_price": current_price,
        "price_missing_reason": None if current_price is not None else str(price_missing_reason or "NO_EXCHANGE_MARKET"),
        "current_price_can_size_trade": bool(current_price_can_size_trade) if current_price_can_size_trade is not None else None,
        "mark_price": mark_price,
        "index_price": index_price,
        "last_trade_price": last_trade_price,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "selected_execution_price_basis": price_field,
        "price_available_at": price_available_at,
        "price_source": price_source,
        "expected_move": expected_move,
        "expected_move_bps": expected_move,
        "expected_move_after_cost_bps": expected_move_after_cost_bps,
        "expected_gross_pnl_usd": expected_gross,
        "expected_cost_usd": round(expected_cost, 8),
        "fees_usd": expected_fees or 0.0,
        "slippage_usd": expected_slippage or 0.0,
        "funding_usd": expected_funding or 0.0,
        "latency_reserve_usd": latency_reserve or 0.0,
        "liquidation_risk_reserve_usd": liquidation_risk_reserve or 0.0,
        "exit_failure_reserve_usd": exit_failure_reserve or 0.0,
        "expected_net_pnl_usd": expected_net,
        "expected_fees_usd": expected_fees,
        "expected_slippage_usd": expected_slippage,
        "expected_funding_usd": expected_funding,
        "expected_max_loss_usd": expected_max_loss,
        "long_expected_gross_pnl_usd": long_expected_gross,
        "long_expected_cost_usd": round(long_expected_cost, 8),
        "long_expected_net_pnl_usd": expected_long_net,
        "long_expected_max_loss_usd": long_expected_max_loss,
        "long_loss_probability": long_loss_probability,
        "short_expected_gross_pnl_usd": short_expected_gross,
        "short_expected_cost_usd": round(short_expected_cost, 8),
        "short_expected_net_pnl_usd": expected_short_net,
        "short_expected_max_loss_usd": short_expected_max_loss,
        "short_loss_probability": short_loss_probability,
        "best_side_expected_net_pnl_usd": best_side_expected_net if best_side_expected_net != float("-inf") else None,
        "selected_action": action,
        "hold_no_trade_reason": no_side_reason if side is None else None,
        "expected_long_net_pnl_usd": expected_long_net,
        "expected_short_net_pnl_usd": expected_short_net,
        "expected_long_net_edge_bps": expected_long_net_edge_bps,
        "expected_short_net_edge_bps": expected_short_net_edge_bps,
        "per_side_usd_notional": per_side_notional,
        "per_side_usd_notional_basis": per_side_notional_basis,
        "expected_liquidation_buffer_usd": liquidation_buffer_usd,
        "pre_trade_loss_probability": loss_probability,
        "loss_probability_reason": _first_present(
            row.get("loss_probability_reason"),
            prediction.get("loss_probability_reason"),
        ),
        "loss_probability_reasons": _as_list(
            _first_present(
                row.get("loss_probability_reasons"),
                prediction.get("loss_probability_reasons"),
            )
        ),
        "loss_probability_calibration": _as_dict(
            _first_present(
                row.get("loss_probability_calibration"),
                prediction.get("loss_probability_calibration"),
            )
        ),
        "microstructure_trust_score": microstructure_trust_score,
        "composite_microstructure_trust_score": composite_microstructure_trust_score,
        "market_state_integrity_score": None
        if market_state_integrity_score is None
        else round(market_state_integrity_score, 8),
        "market_state_integrity_minimum_score": ALLOCATOR_MARKET_STATE_INTEGRITY_MIN_SCORE,
        "market_state_integrity_source": market_state_integrity_source,
        "market_state_integrity_evidence_present": allocator_packet.get(
            "market_state_integrity_evidence_present"
        ),
        "trade_tape_confirmation_score": trade_tape_confirmation_score,
        "expected_exit_depth_usd": expected_exit_depth_usd,
        "liquidity_exit_depth": expected_exit_depth_usd,
        "orderbook_depth_usd": expected_exit_depth_usd,
        "exit_feasible": exit_feasible,
        "exit_feasibility_score": exit_feasibility_score,
        "preemptive_action": preemptive_action or None,
        "orchestrator_decision_id": row.get("orchestrator_decision_id"),
        "orchestrator_action": row.get("orchestrator_action"),
        "orchestrator_reason_code": row.get("orchestrator_reason_code"),
        "orchestrator_live_blocked": row.get("orchestrator_live_blocked"),
        "orchestrator_decision_record": row.get("orchestrator_decision_record"),
        "risk_decision": risk_decision,
        "risk_decision_id": row.get("risk_decision_id"),
        "risk_action": row.get("risk_action"),
        "risk_reason_code": row.get("risk_reason_code"),
        "risk_live_blocked": row.get("risk_live_blocked"),
        "risk_decision_record": row.get("risk_decision_record"),
        "risk_orchestrator_projection_source": row.get("risk_orchestrator_projection_source"),
        "risk_orchestrator_projection_live_blocked": row.get("risk_orchestrator_projection_live_blocked"),
        "risk_orchestrator_projection_error": row.get("risk_orchestrator_projection_error"),
        "orchestrator_decision": orchestrator_decision,
        "allocator_decision": allocator_decision,
        "allocator_decision_id": row.get("allocator_decision_id"),
        "allocator_block_reasons": _as_list(row.get("allocator_block_reasons")),
        "allocator_simulation_status": row.get("allocator_simulation_status") or allocator_packet.get("allocator_simulation_status"),
        "allocator_packet": allocator_packet,
        "recommended_leverage": row.get("recommended_leverage"),
        "recommended_leverage_source": row.get("recommended_leverage_source"),
        "recommended_margin_mode": row.get("recommended_margin_mode"),
        "recommended_margin_mode_source": row.get("recommended_margin_mode_source"),
        "gross_notional_usd": row.get("gross_notional_usd"),
        "target_notional_usd": row.get("target_notional_usd"),
        "target_notional_usdt": row.get("target_notional_usdt"),
        "recommended_notional_usd": row.get("recommended_notional_usd"),
        "allocated_margin_usd": row.get("allocated_margin_usd"),
        "risk_budget_usd": row.get("risk_budget_usd"),
        "max_loss_usd": row.get("max_loss_usd"),
        "liquidation_buffer_usd": row.get("liquidation_buffer_usd"),
        "liquidation_buffer_pct": row.get("liquidation_buffer_pct"),
        "maintenance_margin_usd": row.get("maintenance_margin_usd"),
        "estimated_liquidation_price": row.get("estimated_liquidation_price"),
        "distance_to_liquidation_usd": row.get("distance_to_liquidation_usd"),
        "hedge_required": row.get("hedge_required"),
        "hedge_plan": row.get("hedge_plan"),
        "signed_read_status": row.get("signed_read_status"),
        "available_margin_usd": row.get("available_margin_usd"),
        **provider,
        "block_reasons": unique_reasons,
        "blocker_classes": reason_classes,
        "A_plus_candidate": a_plus,
        "live_ready_candidate": live_ready,
        "counts_as_probation": _is_probation(row),
        "counts_as_reconstructed": _is_reconstructed(row),
        "counts_as_A_plus": a_plus,
        "counts_as_live_ready": live_ready,
        "counts_as_final_a_plus": a_plus,
        "generated_utc": generated_utc,
    }
    initial_exploration_policy = evaluate_paper_risk_controller_exploration(normalized)
    initial_resolution = build_paper_exploration_row_resolution(normalized)
    exploration_projection = _project_paper_exploration_decision_coverage(
        normalized,
        above_floor=bool(initial_exploration_policy.get("above_dynamic_floor")),
        resolution=initial_resolution,
    )
    exploration_view = _as_dict(exploration_projection.get("row")) or normalized
    exploration_policy = evaluate_paper_risk_controller_exploration(exploration_view)
    exploration_resolution = build_paper_exploration_row_resolution(exploration_view)
    exploration_fill_gate = exploration_paper_fill_gate(exploration_view)
    exploration_sizing = exploration_sizing_controls(exploration_view)
    selected_side_economics_consistency = _selected_side_economics_consistency(
        exploration_view
    )
    exploration_eligible = bool(exploration_policy.get("eligible"))
    exploration_above_floor = bool(exploration_policy.get("above_dynamic_floor"))
    projected_risk_decision = exploration_fill_gate.get("risk_controller_decision")
    projected_orchestrator_decision = exploration_fill_gate.get("orchestrator_decision")
    exploration_fill_allowed = bool(
        exploration_above_floor and exploration_fill_gate.get("paper_fill_allowed")
    )
    prequeue_block_reasons: list[str] = []
    if exploration_fill_allowed:
        prequeue_source = {**normalized, **exploration_view}
        prequeue_block_reasons = _materialization_prequeue_block_reasons(
            prequeue_source,
            accepted_at=generated_utc,
        )
        if prequeue_block_reasons:
            exploration_fill_allowed = False
    exploration_current_blocker = (
        "PAPER_FILL_ALLOWED"
        if exploration_fill_allowed
        else "MATERIALIZATION_PREQUEUE_BLOCKED"
        if prequeue_block_reasons
        else exploration_resolution.get("current_blocker")
    )
    normalized.update(
        {
            "paper_exploration_tier": (
                PAPER_RISK_CONTROLLER_EXPLORATION_TIER
                if exploration_above_floor
                else None
            ),
            "exploration_tier": (
                PAPER_RISK_CONTROLLER_EXPLORATION_TIER
                if exploration_above_floor
                else None
            ),
            "paper_risk_controller_exploration_eligible": exploration_eligible,
            "paper_risk_controller_exploration_above_floor": exploration_above_floor,
            "dynamic_exploration_floor": exploration_policy.get(
                "dynamic_exploration_floor"
            ),
            "dynamic_exploration_floor_formula": exploration_policy.get(
                "dynamic_exploration_floor_formula"
            ),
            "exploration_floor_inputs": exploration_policy.get("floor_inputs"),
            "exploration_floor_range": exploration_policy.get("floor_range"),
            "exploration_floor_reason_counts": exploration_policy.get(
                "reason_counts"
            ),
            "paper_risk_controller_exploration_reasons": exploration_policy.get(
                "eligibility_reasons"
            ),
            "paper_risk_controller_exploration_block_reasons": exploration_policy.get(
                "eligibility_block_reasons"
            ),
            "paper_exploration_risk_controller_input_written": bool(
                exploration_projection.get("risk_input_written")
            ),
            "paper_exploration_risk_controller_input_hash": exploration_projection.get(
                "risk_input_hash"
            ),
            "paper_exploration_risk_decision_id": exploration_projection.get(
                "risk_decision_id"
            ),
            "paper_exploration_orchestrator_input_written": bool(
                exploration_projection.get("orchestrator_input_written")
            ),
            "paper_exploration_orchestrator_input_hash": exploration_projection.get(
                "orchestrator_input_hash"
            ),
            "paper_exploration_orchestrator_decision_id": exploration_projection.get(
                "orchestrator_decision_id"
            ),
            "paper_exploration_allocator_input_written": bool(
                exploration_above_floor and exploration_policy.get("allocator_seen")
            ),
            "paper_exploration_risk_controller_decision": exploration_fill_gate.get(
                "risk_controller_decision"
            ),
            "paper_exploration_risk_controller_block_reasons": exploration_projection.get(
                "risk_block_reasons"
            ),
            "paper_exploration_orchestrator_decision": exploration_fill_gate.get(
                "orchestrator_decision"
            ),
            "paper_exploration_orchestrator_block_reasons": exploration_projection.get(
                "orchestrator_block_reasons"
            ),
            "paper_exploration_allocator_decision": exploration_fill_gate.get(
                "allocator_decision"
            ),
            "paper_exploration_paper_fill_allowed": bool(
                exploration_fill_allowed
            ),
            "paper_exploration_paper_fill_block_reasons": (
                exploration_fill_gate.get("paper_fill_block_reasons")
                or prequeue_block_reasons
            ),
            "paper_exploration_prequeue_block_reasons": prequeue_block_reasons,
            "paper_exploration_materialization_prequeue_block_reasons": (
                prequeue_block_reasons
            ),
            "paper_exploration_materialization_queue_ready": bool(
                exploration_fill_allowed
            ),
            "paper_exploration_sizing": exploration_sizing,
            "paper_exploration_selected_side_economics_consistency": (
                selected_side_economics_consistency
            ),
            "paper_exploration_timestamp_integrity": exploration_policy.get(
                "timestamp_integrity"
            ),
            "paper_exploration_timestamp_integrity_status": exploration_policy.get(
                "timestamp_integrity_status"
            ),
            "paper_exploration_earliest_eligible_decision_time": exploration_policy.get(
                "earliest_eligible_decision_time"
            ),
            "paper_exploration_requeue_for_next_cycle": bool(
                exploration_policy.get("requeue_for_next_cycle")
            ),
            "paper_exploration_real_lookahead_block": bool(
                exploration_policy.get("real_lookahead_block")
            ),
            "paper_exploration_market_integrity": exploration_resolution.get(
                "market_integrity"
            ),
            "paper_exploration_quarantine": exploration_resolution.get("quarantine"),
            "paper_exploration_risk_block_resolution": exploration_resolution.get(
                "risk_block_resolution"
            ),
            "paper_exploration_missing_decision_reason": exploration_projection.get(
                "missing_decision_reason"
            ),
            "paper_exploration_current_blocker": exploration_current_blocker,
            "paper_exploration_unknown_resolution": False
            if exploration_fill_allowed
            else bool(exploration_resolution.get("unknown")),
            "paper_exploration_decision_projection_source": exploration_projection.get(
                "projection_source"
            ),
            "paper_exploration_decision_projection_live_blocked": bool(
                exploration_projection.get("projection_live_blocked")
            ),
            "paper_exploration_counts_as_A_plus": False,
            "paper_exploration_counts_as_live_ready": False,
            "paper_exploration_routes_to_live": False,
            "paper_exploration_places_real_order": False,
        }
    )
    if exploration_above_floor:
        if normalized.get("risk_decision") in (None, "", "MISSING") and projected_risk_decision not in (
            None,
            "",
            "MISSING",
        ):
            normalized["risk_decision"] = projected_risk_decision
        if normalized.get("orchestrator_decision") in (
            None,
            "",
            "MISSING",
        ) and projected_orchestrator_decision not in (None, "", "MISSING"):
            normalized["orchestrator_decision"] = projected_orchestrator_decision
        normalized["risk_decision_id"] = _first_present(
            normalized.get("risk_decision_id"),
            exploration_projection.get("risk_decision_id"),
        )
        normalized["orchestrator_decision_id"] = _first_present(
            normalized.get("orchestrator_decision_id"),
            exploration_projection.get("orchestrator_decision_id"),
        )
    return normalized


SESSION_MAX_PREDICTION_AGE_SECONDS = 6 * 3600


def _prediction_age_seconds(prediction: Mapping[str, Any]) -> float | None:
    stamp = _first_present(
        prediction.get("generated_at"),
        prediction.get("decision_time"),
        prediction.get("generated_utc"),
        prediction.get("created_at"),
        prediction.get("available_at"),
    )
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - parsed).total_seconds()


def _candidate_age_seconds(row: Mapping[str, Any], prediction: Mapping[str, Any]) -> float | None:
    stamp = _first_present(
        prediction.get("generated_at"),
        prediction.get("decision_time"),
        prediction.get("generated_utc"),
        prediction.get("created_at"),
        prediction.get("available_at"),
        row.get("generated_at"),
        row.get("decision_time"),
        row.get("generated_utc"),
        row.get("available_at"),
    )
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - parsed).total_seconds()


def _parse_utc(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _timeframe_seconds(timeframe: Any) -> int | None:
    text = str(timeframe or "").strip().lower()
    if not text:
        return None
    unit = text[-1]
    try:
        amount = int(text[:-1])
    except ValueError:
        return None
    unit_seconds = {"m": 60, "h": 3600, "d": 86400}.get(unit)
    if unit_seconds is None:
        return None
    return amount * unit_seconds


def _adaptive_stale_seconds(row: Mapping[str, Any]) -> int:
    timeframe_seconds = _timeframe_seconds(
        _first_present(row.get("timeframe"), row.get("thesis_timeframe"))
    )
    if timeframe_seconds is None:
        return PAPER_SIGNAL_STALE_SECONDS
    adaptive = min(
        PAPER_SIGNAL_STALE_SECONDS,
        timeframe_seconds * PAPER_SIGNAL_ADAPTIVE_STALE_CANDLE_MULTIPLIER,
    )
    adaptive = max(PAPER_SIGNAL_ADAPTIVE_STALE_OPERATOR_MIN_SECONDS, int(adaptive))
    return min(PAPER_SIGNAL_STALE_SECONDS, adaptive)


def _queue_row_identity(row: Mapping[str, Any]) -> str:
    return str(
        _first_present(
            row.get("candidate_id"),
            row.get("prediction_id"),
            row.get("signal_id"),
            row.get("row_uid"),
            f"{row.get('symbol')}:{row.get('timeframe')}:{row.get('side')}",
        )
    )


def _timestamp_not_after(value: Any, decision_time: Any) -> bool:
    parsed = _parse_utc(value)
    decision = _parse_utc(decision_time)
    if parsed is None or decision is None:
        return False
    return parsed <= decision


def _entry_feature_generated_at_payload(
    row: Mapping[str, Any],
    *,
    entry_feature_available_at: Any,
    entry_feature_decision_time: Any,
    source_generated_utc: Any,
) -> tuple[Any, str | None, list[str]]:
    rejected: list[str] = []
    candidates: list[tuple[Any, str]] = [
        (row.get("entry_feature_generated_at"), "entry_feature_generated_at"),
        (row.get("feature_generated_at"), "feature_generated_at"),
        (row.get("generated_at"), "generated_at"),
        (source_generated_utc, "source_generated_utc"),
        (entry_feature_available_at, "entry_feature_available_at_fallback"),
    ]
    for value, source in candidates:
        if value in (None, ""):
            continue
        if _timestamp_not_after(value, entry_feature_decision_time):
            return value, source, rejected
        rejected.append(f"{source}_after_entry_feature_decision_time")
    return None, None, rejected


def _expected_funding_bps_payload(row: Mapping[str, Any]) -> tuple[float | None, str | None]:
    explicit = _float(
        _first_present(
            row.get("expected_funding_bps"),
            row.get("funding_bps"),
            row.get("funding_rate_bps"),
            row.get("actual_funding_bps"),
        )
    )
    if explicit is not None:
        return explicit, "strategy_supply_explicit_funding_bps"
    funding_rate = _float(row.get("funding_rate"))
    if funding_rate is not None:
        return funding_rate * 10_000.0, "strategy_supply_funding_rate_to_bps"
    expected_funding_usd = _float(
        _first_present(row.get("expected_funding_usd"), row.get("funding_usd"))
    )
    notional = _float(
        _first_present(
            row.get("recommended_notional_usd"),
            row.get("target_notional_usd"),
            row.get("target_notional_usdt"),
            row.get("gross_notional_usd"),
        )
    )
    if expected_funding_usd is not None and notional is not None and abs(notional) > 0.0:
        return expected_funding_usd / abs(notional) * 10_000.0, "strategy_supply_expected_funding_usd_to_bps"
    return None, None


def _loss_probability_reason_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    explicit_reason = str(row.get("loss_probability_reason") or "").strip()
    if explicit_reason:
        reasons.append(explicit_reason)
    for reason in _as_list(row.get("loss_probability_reasons")):
        text = str(reason or "").strip()
        if text:
            reasons.append(text)

    calibration = _as_dict(row.get("loss_probability_calibration"))
    if calibration:
        reasons.append("STRATEGY_SUPPLY_CALIBRATED_LOSS_PROBABILITY")
        penalties = _as_dict(calibration.get("penalties"))
        for penalty in sorted(str(key) for key in penalties if str(key)):
            reasons.append(f"CALIBRATION_PENALTY:{penalty}")

    stage_reason = str(
        _first_present(row.get("reason_if_rejected"), row.get("why_rejected")) or ""
    ).strip()
    if stage_reason:
        reasons.append(f"STRATEGY_SUPPLY_STAGE_REJECTED:{stage_reason}")

    if not reasons and _float(row.get("loss_probability")) is not None:
        reasons.append("STRATEGY_SUPPLY_LOSS_PROBABILITY")

    unique_reasons = list(dict.fromkeys(reasons))
    return {
        "loss_probability_reason": unique_reasons[0] if unique_reasons else None,
        "loss_probability_reasons": unique_reasons,
        "loss_probability_calibration": calibration,
    }


def _queue_signal_payload(
    row: Mapping[str, Any],
    *,
    accepted_at: str | None = None,
) -> dict[str, Any]:
    signal = dict(row)
    exit_plan = build_paper_exploration_exit_plan(row, generated_utc=accepted_at)
    identity = _first_present(
        row.get("feature_vector_hash"),
        row.get("feature_snapshot_id"),
        row.get("candidate_id"),
        row.get("prediction_id"),
        row.get("signal_id"),
        row.get("symbol"),
    )
    source_generated_utc = _first_present(
        row.get("source_generated_utc"),
        row.get("generated_utc"),
        row.get("generated_at"),
    )
    market_state_id = _first_present(
        row.get("market_state_id"),
        row.get("entry_market_state_id"),
        f"strategy_supply_market_state:{identity}" if identity else None,
    )
    entry_feature_cutoff = _first_present(
        row.get("entry_feature_cutoff"),
        row.get("feature_cutoff"),
        source_generated_utc,
    )
    entry_feature_available_at = _first_present(
        row.get("entry_feature_available_at"),
        row.get("available_at"),
    )
    entry_feature_decision_time = _first_present(
        row.get("entry_feature_decision_time"),
        row.get("decision_time"),
    )
    (
        entry_feature_generated_at,
        entry_feature_generated_at_source,
        entry_feature_generated_at_rejections,
    ) = _entry_feature_generated_at_payload(
        row,
        entry_feature_available_at=entry_feature_available_at,
        entry_feature_decision_time=entry_feature_decision_time,
        source_generated_utc=source_generated_utc,
    )
    entry_feature_candle_closed_confirmed = _first_present(
        row.get("entry_feature_candle_closed_confirmed"),
        row.get("candle_closed_confirmed"),
    )
    expected_funding_bps, expected_funding_bps_source = _expected_funding_bps_payload(row)
    signal.update(
        {
            "generated_utc": _first_present(accepted_at, source_generated_utc),
            "source_generated_utc": source_generated_utc,
            "source_available_at": _first_present(row.get("source_available_at"), row.get("available_at")),
            "source_decision_time": _first_present(row.get("source_decision_time"), row.get("decision_time")),
            "source_prediction_status": "CURRENT_RUNTIME_PAPER_SIGNAL",
            "paper_fill_allowed": True,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "test_order": False,
            "live_order": False,
            "order_submitted": False,
            "test_order_submitted": False,
            "leverage_mutated": False,
            "margin_mutated": False,
            "counts_as_A_plus": False,
            "counts_as_final_a_plus": False,
            "counts_as_live_ready": False,
            "paper_opportunity_tier": PAPER_RISK_CONTROLLER_EXPLORATION_TIER,
            "exploration_tier": PAPER_RISK_CONTROLLER_EXPLORATION_TIER,
            "paper_exploration_tier": PAPER_RISK_CONTROLLER_EXPLORATION_TIER,
            "paper_risk_controller_exploration": True,
            "paper_fill_allowed_source": "PAPER_EXPLORATION_MATERIALIZATION_QUEUE",
            "materialization_queue_source": "v2_a_plus_candidate_inventory",
            "exit_plan": exit_plan,
            "market_state_id": market_state_id,
            "entry_market_state_id": market_state_id,
            "valid_for_paper": _first_present(row.get("valid_for_paper"), True),
            "market_state_integrity_score": row.get("market_state_integrity_score"),
            "market_state_reject_reasons": list(row.get("market_state_reject_reasons") or []),
            "entry_feature_snapshot_id": _first_present(
                row.get("entry_feature_snapshot_id"),
                row.get("feature_snapshot_id"),
            ),
            "entry_feature_available_at": entry_feature_available_at,
            "entry_feature_generated_at": entry_feature_generated_at,
            "entry_feature_generated_at_source": entry_feature_generated_at_source,
            "entry_feature_generated_at_rejections": entry_feature_generated_at_rejections,
            "entry_feature_cutoff": entry_feature_cutoff,
            "entry_feature_decision_time": entry_feature_decision_time,
            "entry_feature_source": _first_present(
                row.get("entry_feature_source"),
                "strategy_supply_inventory_row",
            ),
            "loss_probability_reason": row.get("loss_probability_reason"),
            "loss_probability_reasons": row.get("loss_probability_reasons"),
            "loss_probability_calibration": row.get("loss_probability_calibration"),
        }
    )
    if entry_feature_candle_closed_confirmed is not None:
        signal["entry_feature_candle_closed_confirmed"] = (
            entry_feature_candle_closed_confirmed
        )
    if expected_funding_bps is not None:
        signal["expected_funding_bps"] = expected_funding_bps
        signal["funding_bps"] = expected_funding_bps
        signal["expected_funding_bps_source"] = expected_funding_bps_source
        signal["expected_funding_bps_fallback"] = False
        signal["expected_funding_bps_unavailable_reason"] = None
    if signal.get("selected_action") in (None, ""):
        signal["selected_action"] = _first_present(row.get("side"), row.get("action"))
    if signal.get("action") in (None, ""):
        signal["action"] = _first_present(row.get("selected_action"), row.get("side"))
    return signal


def _build_materialization_queue_row(
    row: Mapping[str, Any],
    *,
    accepted_at: str,
    inventory_generated_utc: str | None = None,
) -> dict[str, Any]:
    adaptive_seconds = _adaptive_stale_seconds(row)
    accepted_dt = _parse_utc(accepted_at) or datetime.now(timezone.utc)
    source_freshness = _materialization_source_freshness(row, accepted_at=accepted_at)
    source_freshness_reasons = [
        str(reason)
        for reason in source_freshness.get("source_freshness_reasons") or []
        if reason
    ]
    source_pending_reasons = [
        reason
        for reason in source_freshness_reasons
        if reason.startswith("MATERIALIZATION_PREQUEUE_SOURCE_TIME_AFTER_ACCEPTED_AT:")
    ]
    source_hard_reasons = [
        reason for reason in source_freshness_reasons if reason not in source_pending_reasons
    ]
    source_expires_at = _parse_utc(source_freshness.get("source_expires_at"))
    expires_at = source_expires_at or (accepted_dt + timedelta(seconds=adaptive_seconds))
    signal = _queue_signal_payload(row, accepted_at=accepted_at)
    safety_truth = build_paper_exploration_safety_truth(signal)
    return {
        "queue_id": f"paper_exploration_materialize_{_queue_row_identity(row)}",
        "candidate_id": _first_present(row.get("candidate_id"), row.get("prediction_id")),
        "prediction_id": row.get("prediction_id"),
        "signal_id": row.get("signal_id"),
        "symbol": row.get("symbol"),
        "timeframe": row.get("timeframe"),
        "side": row.get("side"),
        "strategy_supply_hypothesis": row.get("strategy_supply_hypothesis") is True,
        "strategy_supply_hypothesis_id": _first_present(
            row.get("strategy_supply_hypothesis_id"),
            row.get("hypothesis_id"),
        ),
        "tier": PAPER_RISK_CONTROLLER_EXPLORATION_TIER,
        "accepted_at": accepted_at,
        "accepted_at_semantics": "QUEUE_PUBLISH_TIME_SOURCE_EXPIRY_UNCHANGED",
        "queue_published_at": accepted_at,
        "inventory_generated_utc": inventory_generated_utc,
        "available_at": row.get("available_at"),
        "decision_time": row.get("decision_time"),
        "queue_freshness_basis": (
            "source_time"
            if source_freshness.get("source_freshness_time")
            else "accepted_at_fallback_no_source_time"
        ),
        "source_available_at": _first_present(row.get("source_available_at"), row.get("available_at")),
        "source_decision_time": _first_present(row.get("source_decision_time"), row.get("decision_time")),
        "source_generated_utc": _first_present(
            row.get("source_generated_utc"),
            row.get("generated_utc"),
            row.get("generated_at"),
        ),
        **source_freshness,
        "source_freshness_pending": bool(source_pending_reasons),
        "source_freshness_pending_reasons": source_pending_reasons,
        "source_freshness_hard_reasons": source_hard_reasons,
        "earliest_eligible_decision_time": (
            source_freshness.get("source_freshness_time")
            if source_pending_reasons
            else None
        ),
        "expires_at": _format_utc(expires_at),
        "adaptive_stale_seconds": adaptive_seconds,
        "risk_decision_id": row.get("risk_decision_id")
        or row.get("paper_exploration_risk_decision_id"),
        "risk_decision_record_key": row.get("risk_decision_record_key"),
        "risk_decision_record_hash": row.get("risk_decision_record_hash"),
        "risk_decision_record_resolved": row.get("risk_decision_record_resolved")
        is True,
        "orchestrator_decision_id": row.get("orchestrator_decision_id")
        or row.get("paper_exploration_orchestrator_decision_id"),
        "orchestrator_decision_record_key": row.get(
            "orchestrator_decision_record_key"
        ),
        "orchestrator_decision_record_hash": row.get(
            "orchestrator_decision_record_hash"
        ),
        "orchestrator_decision_record_resolved": row.get(
            "orchestrator_decision_record_resolved"
        )
        is True,
        "canonical_decision_records_resolved": row.get(
            "canonical_decision_records_resolved"
        )
        is True,
        "canonical_decision_request_only": row.get(
            "canonical_decision_request_only"
        )
        is True,
        "non_executable_request_telemetry": row.get(
            "non_executable_request_telemetry"
        )
        is True,
        "canonical_decision_request_reasons": row.get(
            "canonical_decision_request_reasons"
        )
        or [],
        "allocator_decision_id": row.get("allocator_decision_id"),
        "preemptive_decision_id": row.get("preemptive_decision_id"),
        "pre_trade_loss_probability": row.get("pre_trade_loss_probability"),
        "loss_probability_reason": row.get("loss_probability_reason"),
        "loss_probability_reasons": row.get("loss_probability_reasons"),
        "loss_probability_calibration": row.get("loss_probability_calibration"),
        "confidence_executable_trade": row.get("confidence_executable_trade"),
        "dynamic_exploration_floor": row.get("dynamic_exploration_floor"),
        "dynamic_exploration_floor_formula": row.get(
            "dynamic_exploration_floor_formula"
        ),
        "exploration_floor_inputs": row.get("exploration_floor_inputs"),
        "exploration_floor_range": row.get("exploration_floor_range"),
        "paper_risk_controller_exploration_eligible": row.get(
            "paper_risk_controller_exploration_eligible"
        ),
        "paper_risk_controller_exploration_above_floor": row.get(
            "paper_risk_controller_exploration_above_floor"
        ),
        "paper_risk_controller_exploration_reasons": row.get(
            "paper_risk_controller_exploration_reasons"
        ),
        "paper_risk_controller_exploration_block_reasons": row.get(
            "paper_risk_controller_exploration_block_reasons"
        ),
        "expected_net_pnl_usd": row.get("expected_net_pnl_usd"),
        "expected_max_loss_usd": row.get("expected_max_loss_usd"),
        "current_price": row.get("current_price"),
        "recommended_notional_usd": _first_present(
            row.get("recommended_notional_usd"),
            row.get("target_notional_usd"),
            row.get("target_notional_usdt"),
        ),
        "gross_notional_usd": row.get("gross_notional_usd"),
        "target_notional_usd": row.get("target_notional_usd"),
        "target_notional_usdt": row.get("target_notional_usdt"),
        "allocated_margin_usd": row.get("allocated_margin_usd"),
        "risk_budget_usd": row.get("risk_budget_usd"),
        "recommended_leverage": row.get("recommended_leverage"),
        "recommended_margin_mode": row.get("recommended_margin_mode"),
        "liquidation_buffer_usd": _first_present(
            row.get("liquidation_buffer_usd"),
            row.get("expected_liquidation_buffer_usd"),
        ),
        "exit_plan": signal.get("exit_plan"),
        "hedge_plan": _first_present(row.get("hedge_plan"), row.get("hedge_plan_if_any")),
        "provider_hashes": _first_present(
            row.get("provider_hashes"),
            row.get("provider_feature_hashes"),
            row.get("source_hashes"),
        ),
        "feature_vector_hash": row.get("feature_vector_hash"),
        "raw_safety_fields": safety_truth["raw_fields"],
        "invariant_checks": safety_truth["invariant_checks"],
        "raw_paper_only": safety_truth["raw_paper_only"],
        "raw_routes_to_live": safety_truth["raw_routes_to_live"],
        "raw_places_real_order": safety_truth["raw_places_real_order"],
        "raw_counts_as_A_plus": safety_truth["raw_counts_as_A_plus"],
        "raw_counts_as_live_ready": safety_truth["raw_counts_as_live_ready"],
        "routes_to_live_false": safety_truth["routes_to_live_false"],
        "places_real_order_false": safety_truth["places_real_order_false"],
        "counts_as_A_plus_false": safety_truth["counts_as_A_plus_false"],
        "counts_as_live_ready_false": safety_truth["counts_as_live_ready_false"],
        "safety_hard_fail": safety_truth["hard_fail"],
        "safety_hard_fail_reasons": safety_truth["hard_fail_reasons"],
        "source_freshness_hard_fail": bool(source_hard_reasons),
        "paper_signal": signal,
    }


def _build_materialization_prequeue_counterfactual_row(
    row: Mapping[str, Any],
    *,
    generated_utc: str,
) -> dict[str, Any]:
    signal = _queue_signal_payload(row, accepted_at=generated_utc)
    safety_truth = build_paper_exploration_safety_truth(signal)
    exact_reasons = [
        str(reason)
        for reason in row.get("paper_exploration_materialization_prequeue_block_reasons")
        or row.get("paper_exploration_prequeue_block_reasons")
        or ["MATERIALIZATION_PREQUEUE_BLOCKED"]
        if reason
    ]
    if not exact_reasons:
        exact_reasons = ["MATERIALIZATION_PREQUEUE_BLOCKED"]
    identity = _queue_row_identity(row)
    risk_decision_id = _first_present(
        row.get("risk_decision_id"),
        row.get("paper_exploration_risk_decision_id"),
        signal.get("risk_decision_id"),
    )
    orchestrator_decision_id = _first_present(
        row.get("orchestrator_decision_id"),
        row.get("paper_exploration_orchestrator_decision_id"),
        signal.get("orchestrator_decision_id"),
    )
    allocator_decision_id = _first_present(
        row.get("allocator_decision_id"),
        signal.get("allocator_decision_id"),
    )
    return {
        "schema_version": "paper_exploration_materialization_counterfactual_v1",
        "trainer_feedback_id": f"cf_materialization_prequeue_{identity}",
        "paper_exploration_candidate_id": _first_present(
            row.get("candidate_id"),
            row.get("prediction_id"),
            row.get("signal_id"),
        ),
        "prediction_id": row.get("prediction_id"),
        "signal_id": row.get("signal_id"),
        "symbol": row.get("symbol"),
        "timeframe": row.get("timeframe"),
        "side": _first_present(row.get("side"), row.get("selected_action")),
        "exploration_tier": PAPER_RISK_CONTROLLER_EXPLORATION_TIER,
        "feedback_type": (
            "PAPER_EXPLORATION_MATERIALIZATION_COUNTERFACTUAL_PREQUEUE_NO_FILL"
        ),
        "counterfactual_feedback_source": "v2_a_plus_candidate_inventory_prequeue",
        "block_reason_if_rejected": "MATERIALIZATION_PREQUEUE_BLOCKED",
        "block_reasons_if_rejected": exact_reasons,
        "rejection_reason": "MATERIALIZATION_PREQUEUE_BLOCKED",
        "exact_reasons": exact_reasons,
        "paper_performance_circuit_breaker_candidate_bucket_keys": row.get(
            "paper_performance_circuit_breaker_candidate_bucket_keys"
        )
        or [],
        "paper_performance_circuit_breaker_matched_blocked_bucket_keys": row.get(
            "paper_performance_circuit_breaker_matched_blocked_bucket_keys"
        )
        or [],
        "paper_performance_circuit_breaker_matched_blocked_bucket_proof": row.get(
            "paper_performance_circuit_breaker_matched_blocked_bucket_proof"
        )
        or [],
        "paper_performance_circuit_breaker_matched_loss_cluster_keys": row.get(
            "paper_performance_circuit_breaker_matched_loss_cluster_keys"
        )
        or [],
        "paper_performance_circuit_breaker_advisory_bucket_keys": row.get(
            "paper_performance_circuit_breaker_advisory_bucket_keys"
        )
        or [],
        "paper_performance_circuit_breaker_advisory_bucket_proof": row.get(
            "paper_performance_circuit_breaker_advisory_bucket_proof"
        )
        or [],
        "paper_performance_circuit_breaker_advisory_loss_cluster_keys": row.get(
            "paper_performance_circuit_breaker_advisory_loss_cluster_keys"
        )
        or [],
        "risk_decision": _first_present(
            row.get("risk_decision"),
            signal.get("risk_decision"),
            "PASS" if risk_decision_id else None,
        ),
        "risk_decision_id": risk_decision_id,
        "orchestrator_decision": _first_present(
            row.get("orchestrator_decision"),
            signal.get("orchestrator_decision"),
            "PASS" if orchestrator_decision_id else None,
        ),
        "orchestrator_decision_id": orchestrator_decision_id,
        "allocator_decision": _first_present(
            row.get("allocator_decision"),
            signal.get("allocator_decision"),
            "PASS" if allocator_decision_id else None,
        ),
        "allocator_decision_id": allocator_decision_id,
        "preemptive_decision_id": _first_present(
            row.get("preemptive_decision_id"),
            signal.get("preemptive_decision_id"),
        ),
        "confidence_executable_trade": row.get("confidence_executable_trade"),
        "dynamic_exploration_floor": row.get("dynamic_exploration_floor"),
        "dynamic_exploration_floor_formula": row.get(
            "dynamic_exploration_floor_formula"
        ),
        "exploration_floor_inputs": row.get("exploration_floor_inputs"),
        "expected_net_pnl_usd": row.get("expected_net_pnl_usd"),
        "expected_max_loss_usd": row.get("expected_max_loss_usd"),
        "current_price": row.get("current_price"),
        "recommended_notional_usd": _first_present(
            row.get("recommended_notional_usd"),
            row.get("target_notional_usd"),
            row.get("target_notional_usdt"),
        ),
        "recommended_leverage": row.get("recommended_leverage"),
        "recommended_margin_mode": row.get("recommended_margin_mode"),
        "liquidation_buffer_usd": _first_present(
            row.get("liquidation_buffer_usd"),
            row.get("expected_liquidation_buffer_usd"),
        ),
        "provider_hashes": _first_present(
            row.get("provider_hashes"),
            row.get("provider_feature_hashes"),
            row.get("source_hashes"),
        ),
        "feature_vector_hash": row.get("feature_vector_hash"),
        "raw_safety_fields": safety_truth["raw_fields"],
        "invariant_checks": safety_truth["invariant_checks"],
        "future_label_pending": True,
        "trainer_consumable": False,
        "trainer_consumable_block_reason": "FUTURE_LABEL_PENDING_NO_PAPER_FILL_OPENED",
        "dirty_flag": False,
        "dirty_reasons": [],
        "paper_materialized": False,
        "paper_fill_allowed": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_A_plus": False,
        "counts_as_live_ready": False,
        "order_submitted": False,
        "test_order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
        "generated_utc": generated_utc,
    }


def _publish_materialization_queue(
    client: Any,
    rows: list[Mapping[str, Any]],
    *,
    generated_utc: str,
    queue_published_at: str | None = None,
) -> dict[str, Any]:
    queue_generated_utc = queue_published_at or _utc_now()
    proposed_current_rows = [
        row
        for row in rows
        if row.get("paper_exploration_paper_fill_allowed") is True
    ]
    accepted_dry_run_row_count = len(proposed_current_rows)
    current_queue_identities = {
        f"paper_exploration_materialize_{_queue_row_identity(row)}"
        for row in proposed_current_rows
    }
    previous_queue_payload = _read_json(
        client,
        EXPLORATION_MATERIALIZATION_QUEUE_KEY,
    )
    proposed_previous_rows: list[dict[str, Any]] = []
    preserved_previous_request_rows: list[dict[str, Any]] = []
    if isinstance(previous_queue_payload, Mapping):
        for previous_row in previous_queue_payload.get("rows") or []:
            if not isinstance(previous_row, Mapping):
                continue
            previous_identity = str(
                _first_present(
                    previous_row.get("queue_id"),
                    previous_row.get("candidate_id"),
                    previous_row.get("prediction_id"),
                    previous_row.get("signal_id"),
                )
                or ""
            )
            if not previous_identity or previous_identity in current_queue_identities:
                continue
            proposed_previous_rows.append(dict(previous_row))
            current_queue_identities.add(previous_identity)
        for previous_request_row in previous_queue_payload.get("request_rows") or []:
            if not isinstance(previous_request_row, Mapping):
                continue
            previous_identity = str(
                _first_present(
                    previous_request_row.get("queue_id"),
                    previous_request_row.get("candidate_id"),
                    previous_request_row.get("prediction_id"),
                    previous_request_row.get("signal_id"),
                )
                or ""
            )
            if not previous_identity or previous_identity in current_queue_identities:
                continue
            request_row = copy.deepcopy(previous_request_row)
            request_row["previous_materialization_queue_generated_utc"] = (
                previous_queue_payload.get("generated_utc")
            )
            _mark_materialization_request_only(
                request_row,
                reasons=[
                    *(request_row.get("canonical_decision_request_reasons") or []),
                    "CURRENT_INVENTORY_REVALIDATION_REQUIRED",
                ],
            )
            preserved_previous_request_rows.append(request_row)
            current_queue_identities.add(previous_identity)

    observation_rows = [
        *[row for row in proposed_current_rows if isinstance(row, dict)],
        *proposed_previous_rows,
    ]
    per_id_decision_store_status = _observe_materialization_decision_records(
        client,
        observation_rows,
        generated_utc=queue_generated_utc,
    )
    accepted_rows = [
        row
        for row in proposed_current_rows
        if row.get("canonical_decision_records_resolved") is True
    ]
    queue_rows = [
        _build_materialization_queue_row(
            row,
            accepted_at=queue_generated_utc,
            inventory_generated_utc=generated_utc,
        )
        for row in accepted_rows
    ]
    request_rows: list[dict[str, Any]] = []
    for row in proposed_current_rows:
        if row.get("canonical_decision_records_resolved") is True:
            continue
        request_row = _build_materialization_queue_row(
            row,
            accepted_at=queue_generated_utc,
            inventory_generated_utc=generated_utc,
        )
        _mark_materialization_request_only(
            request_row,
            reasons=row.get("canonical_decision_request_reasons") or [],
        )
        request_rows.append(request_row)
    request_rows.extend(preserved_previous_request_rows)
    now = _parse_utc(queue_generated_utc) or datetime.now(timezone.utc)
    preserved_previous_queue_rows: list[dict[str, Any]] = []
    for previous_row in proposed_previous_rows:
        if previous_row.get("canonical_decision_records_resolved") is True:
            preserved_previous_queue_rows.append(
                {
                    **previous_row,
                    "materialization_queue_preserved_from_previous_queue": True,
                    "previous_materialization_queue_generated_utc": (
                        previous_queue_payload.get("generated_utc")
                        if isinstance(previous_queue_payload, Mapping)
                        else None
                    ),
                }
            )
        else:
            request_row = copy.deepcopy(previous_row)
            request_row["materialization_queue_preserved_from_previous_queue"] = False
            request_row["previous_materialization_queue_generated_utc"] = (
                previous_queue_payload.get("generated_utc")
                if isinstance(previous_queue_payload, Mapping)
                else None
            )
            _mark_materialization_request_only(
                request_row,
                reasons=previous_row.get("canonical_decision_request_reasons") or [],
            )
            request_rows.append(request_row)
    if preserved_previous_queue_rows:
        queue_rows = [*queue_rows, *preserved_previous_queue_rows]
    pending_source_rows = [
        {
            **row,
            "materialization_queue_result": "PENDING_SOURCE_TIME_NEXT_CYCLE",
            "materialization_no_fill_reason": "PENDING_SOURCE_TIME_NEXT_CYCLE",
        }
        for row in queue_rows
        if row.get("source_freshness_pending") is True
        and (_parse_utc(row.get("source_freshness_time")) or now) > now
        and row.get("safety_hard_fail") is not True
        and row.get("source_freshness_hard_fail") is not True
    ]
    pending_source_queue_ids = {
        str(row.get("queue_id")) for row in pending_source_rows if row.get("queue_id")
    }
    active_rows = [
        row
        for row in queue_rows
        if (_parse_utc(row.get("expires_at")) or now) >= now
        and row.get("safety_hard_fail") is not True
        and row.get("source_freshness_hard_fail") is not True
        and str(row.get("queue_id")) not in pending_source_queue_ids
    ]
    expired_rows = [
        row
        for row in queue_rows
        if (_parse_utc(row.get("expires_at")) or now) < now
        or row.get("source_stale_at_acceptance") is True
    ]
    source_rejected_rows = [
        row
        for row in queue_rows
        if row.get("source_freshness_hard_fail") is True
        and row not in expired_rows
    ]
    unsafe_rows = [row for row in queue_rows if row.get("safety_hard_fail") is True]
    expired_counterfactual_rows = [
        _build_materialization_prequeue_counterfactual_row(
            {
                **row,
                "paper_exploration_materialization_prequeue_block_reasons": (
                    row.get("source_freshness_reasons")
                    or ["MATERIALIZATION_PREQUEUE_SOURCE_EXPIRED_BEFORE_QUEUE"]
                ),
            },
            generated_utc=queue_generated_utc,
        )
        for row in expired_rows
    ] + [
        _build_materialization_prequeue_counterfactual_row(
            {
                **row,
                "paper_exploration_materialization_prequeue_block_reasons": (
                    row.get("source_freshness_reasons")
                    or ["MATERIALIZATION_PREQUEUE_SOURCE_REJECTED_BEFORE_QUEUE"]
                ),
            },
            generated_utc=queue_generated_utc,
        )
        for row in source_rejected_rows
    ]
    prequeue_rejected_rows = [
        row
        for row in rows
        if row.get("paper_exploration_paper_fill_allowed") is not True
        and row.get("paper_exploration_materialization_prequeue_block_reasons")
    ]
    prequeue_counterfactual_rows = [
        _build_materialization_prequeue_counterfactual_row(
            row,
            generated_utc=queue_generated_utc,
        )
        for row in prequeue_rejected_rows
    ] + expired_counterfactual_rows
    prequeue_reason_counts = Counter(
        str(reason)
        for row in prequeue_rejected_rows
        for reason in row.get("paper_exploration_materialization_prequeue_block_reasons")
        or []
        if reason
    )
    queued_count = len(active_rows) + len(pending_source_rows)
    prequeue_exact_no_fill_reason = _prequeue_materialization_no_fill_reason(
        prequeue_reason_counts,
    )
    if queued_count == 0 and request_rows:
        exact_no_fill_reason = "CANONICAL_DECISION_PRODUCERS_PENDING"
    elif queued_count == 0 and prequeue_rejected_rows:
        exact_no_fill_reason = (
            prequeue_exact_no_fill_reason
            or "ALL_CURRENT_ROWS_PREQUEUE_BLOCKED_WITH_EXACT_REASONS"
        )
    elif pending_source_rows and queued_count == len(pending_source_rows):
        exact_no_fill_reason = "PAPER_EXPLORATION_PENDING_SOURCE_TIME_NEXT_CYCLE"
    elif active_rows or pending_source_rows:
        exact_no_fill_reason = "PAPER_EXPLORATION_ACTIVE_REVALIDATION_IN_PROGRESS"
    elif expired_rows or source_rejected_rows:
        exact_no_fill_reason = "ALL_QUEUE_ROWS_EXPIRED_BEFORE_PAPER_LOOP"
    else:
        exact_no_fill_reason = "NO_CURRENT_EXPLORATION_CANDIDATES"
    queue_payload = {
        "schema_version": "paper_exploration_materialization_queue_v1",
        "generated_utc": queue_generated_utc,
        "queue_published_at": queue_generated_utc,
        "inventory_generated_utc": generated_utc,
        "accepted_at_semantics": "QUEUE_PUBLISH_TIME_SOURCE_EXPIRY_UNCHANGED",
        "queue_key": EXPLORATION_MATERIALIZATION_QUEUE_KEY,
        "rows": [*active_rows, *pending_source_rows],
        "request_rows": request_rows,
        "request_rows_executable": False,
        "pending_source_rows": pending_source_rows,
        "expired_rows": expired_rows,
        "unsafe_rows": unsafe_rows,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "canonical_namespace_owner": False,
        "canonical_decision_consumer_role": "READ_ONLY_CANONICAL_DECISION_OBSERVER",
    }
    wrote_queue = _safe_redis_set(
        client,
        EXPLORATION_MATERIALIZATION_QUEUE_KEY,
        queue_payload,
        ex=2 * 60 * 60,
    )
    status = {
        "schema_version": "paper_exploration_materialization_queue_status_v1",
        "generated_utc": queue_generated_utc,
        "queue_published_at": queue_generated_utc,
        "inventory_generated_utc": generated_utc,
        "accepted_at_semantics": "QUEUE_PUBLISH_TIME_SOURCE_EXPIRY_UNCHANGED",
        "queue_key": EXPLORATION_MATERIALIZATION_QUEUE_KEY,
        "queue_status_key": EXPLORATION_MATERIALIZATION_QUEUE_STATUS_KEY,
        "accepted_dry_run_rows": accepted_dry_run_row_count,
        "canonical_executable_row_count": len(accepted_rows),
        "canonical_decision_request_count": len(request_rows),
        "canonical_decision_request_rows": [
            {
                "candidate_id": row.get("candidate_id"),
                "signal_id": row.get("signal_id"),
                "prediction_id": row.get("prediction_id"),
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "side": row.get("side"),
                "canonical_decision_request_reasons": row.get(
                    "canonical_decision_request_reasons"
                )
                or [],
                "canonical_decision_request_only": True,
                "non_executable_request_telemetry": True,
                "paper_fill_allowed": False,
                "valid_for_paper": False,
                "routes_to_live": False,
                "places_real_order": False,
            }
            for row in request_rows[:25]
        ],
        "queued_count": queued_count,
        "active_count": len(active_rows),
        "pending_source_time_count": len(pending_source_rows),
        "expired_count": len(expired_rows),
        "expired_counterfactual_count": len(expired_counterfactual_rows),
        "source_rejected_count": len(source_rejected_rows),
        "unsafe_count": len(unsafe_rows),
        "prequeue_rejected_count": len(prequeue_rejected_rows),
        "prequeue_counterfactual_count": len(prequeue_counterfactual_rows),
        "preserved_previous_queue_count": len(preserved_previous_queue_rows),
        "preserved_previous_request_count": len(preserved_previous_request_rows),
        "prequeue_counterfactual_key": (
            PAPER_EXPLORATION_MATERIALIZATION_COUNTERFACTUAL_KEY
        ),
        "prequeue_rejected_reason_counts": dict(
            prequeue_reason_counts.most_common()
        ),
        "prequeue_exact_no_fill_reason": prequeue_exact_no_fill_reason,
        "exact_no_fill_reason": exact_no_fill_reason,
        "canonical_exact_no_fill_reason": (
            _canonical_materialization_no_fill_reason(exact_no_fill_reason)
        ),
        "prequeue_rejected_rows": [
            {
                "candidate_id": _first_present(
                    row.get("candidate_id"),
                    row.get("prediction_id"),
                    row.get("signal_id"),
                ),
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "side": row.get("side"),
                "block_reasons": (
                    row.get("paper_exploration_materialization_prequeue_block_reasons")
                    or []
                ),
                "paper_performance_circuit_breaker_candidate_bucket_keys": row.get(
                    "paper_performance_circuit_breaker_candidate_bucket_keys"
                )
                or [],
                "paper_performance_circuit_breaker_matched_blocked_bucket_keys": (
                    row.get(
                        "paper_performance_circuit_breaker_matched_blocked_bucket_keys"
                    )
                    or []
                ),
                "paper_performance_circuit_breaker_matched_blocked_bucket_proof": (
                    row.get(
                        "paper_performance_circuit_breaker_matched_blocked_bucket_proof"
                    )
                    or []
                ),
                "paper_performance_circuit_breaker_matched_loss_cluster_keys": (
                    row.get(
                        "paper_performance_circuit_breaker_matched_loss_cluster_keys"
                    )
                    or []
                ),
                "paper_performance_circuit_breaker_advisory_bucket_keys": row.get(
                    "paper_performance_circuit_breaker_advisory_bucket_keys"
                )
                or [],
                "paper_performance_circuit_breaker_advisory_bucket_proof": row.get(
                    "paper_performance_circuit_breaker_advisory_bucket_proof"
                )
                or [],
                "paper_performance_circuit_breaker_advisory_loss_cluster_keys": (
                    row.get(
                        "paper_performance_circuit_breaker_advisory_loss_cluster_keys"
                    )
                    or []
                ),
            }
            for row in prequeue_rejected_rows[:25]
        ],
        "per_id_decision_store": {
            key: value
            for key, value in per_id_decision_store_status.items()
            if key != "row_status"
        },
        "canonical_decision_observer": {
            key: value
            for key, value in per_id_decision_store_status.items()
            if key != "row_status"
        },
        "per_id_decision_store_rows": per_id_decision_store_status["row_status"][:25],
        "active_rows": [
            {
                "candidate_id": _first_present(
                    row.get("candidate_id"),
                    row.get("prediction_id"),
                    row.get("signal_id"),
                ),
                "queue_id": row.get("queue_id"),
                "materialization_queue_preserved_from_previous_queue": row.get(
                    "materialization_queue_preserved_from_previous_queue"
                )
                is True,
                "previous_materialization_queue_generated_utc": row.get(
                    "previous_materialization_queue_generated_utc"
                ),
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "side": row.get("side"),
                "tier": row.get("tier"),
                "accepted_at": row.get("accepted_at"),
                "accepted_at_semantics": row.get("accepted_at_semantics"),
                "queue_published_at": row.get("queue_published_at"),
                "inventory_generated_utc": row.get("inventory_generated_utc"),
                "available_at": row.get("available_at"),
                "decision_time": row.get("decision_time"),
                "expires_at": row.get("expires_at"),
                "adaptive_stale_seconds": row.get("adaptive_stale_seconds"),
                "confidence_executable_trade": row.get(
                    "confidence_executable_trade"
                ),
                "dynamic_exploration_floor": row.get("dynamic_exploration_floor"),
                "paper_risk_controller_exploration_above_floor": row.get(
                    "paper_risk_controller_exploration_above_floor"
                ),
                "paper_risk_controller_exploration_eligible": row.get(
                    "paper_risk_controller_exploration_eligible"
                ),
                "risk_decision_id": row.get("risk_decision_id"),
                "risk_decision_record_key": row.get("risk_decision_record_key"),
                "risk_decision_record_hash": row.get("risk_decision_record_hash"),
                "risk_decision_record_resolved": row.get(
                    "risk_decision_record_resolved"
                )
                is True,
                "orchestrator_decision_id": row.get("orchestrator_decision_id"),
                "orchestrator_decision_record_key": row.get(
                    "orchestrator_decision_record_key"
                ),
                "orchestrator_decision_record_hash": row.get(
                    "orchestrator_decision_record_hash"
                ),
                "orchestrator_decision_record_resolved": row.get(
                    "orchestrator_decision_record_resolved"
                )
                is True,
                "decision_record_missing_reasons": row.get(
                    "decision_record_missing_reasons"
                )
                or [],
                "allocator_decision_id": row.get("allocator_decision_id"),
                "preemptive_decision_id": row.get("preemptive_decision_id"),
                "expected_net_pnl_usd": row.get("expected_net_pnl_usd"),
                "expected_max_loss_usd": row.get("expected_max_loss_usd"),
                "current_price": row.get("current_price"),
                "recommended_notional_usd": row.get("recommended_notional_usd"),
                "gross_notional_usd": row.get("gross_notional_usd"),
                "target_notional_usd": row.get("target_notional_usd"),
                "target_notional_usdt": row.get("target_notional_usdt"),
                "allocated_margin_usd": row.get("allocated_margin_usd"),
                "risk_budget_usd": row.get("risk_budget_usd"),
                "paper_signal": {
                    key: row.get("paper_signal", {}).get(key)
                    for key in (
                        "recommended_notional_usd",
                        "gross_notional_usd",
                        "target_notional_usd",
                        "target_notional_usdt",
                        "allocated_margin_usd",
                        "risk_budget_usd",
                    )
                    if isinstance(row.get("paper_signal"), Mapping)
                    and key in row.get("paper_signal", {})
                },
                "recommended_leverage": row.get("recommended_leverage"),
                "recommended_margin_mode": row.get("recommended_margin_mode"),
                "liquidation_buffer_usd": row.get("liquidation_buffer_usd"),
                "feature_vector_hash": row.get("feature_vector_hash"),
                "provider_hashes_present": bool(row.get("provider_hashes")),
                "raw_safety_fields": row.get("raw_safety_fields"),
                "invariant_checks": row.get("invariant_checks"),
            }
            for row in active_rows[:25]
        ],
        "pending_source_rows": [
            {
                "candidate_id": _first_present(
                    row.get("candidate_id"),
                    row.get("prediction_id"),
                    row.get("signal_id"),
                ),
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "side": row.get("side"),
                "earliest_eligible_decision_time": row.get(
                    "earliest_eligible_decision_time"
                ),
                "source_freshness_pending_reasons": row.get(
                    "source_freshness_pending_reasons"
                )
                or [],
            }
            for row in pending_source_rows[:25]
        ],
        "queue_written": wrote_queue,
        "dry_run_accepted_row_exists_without_queue_record": bool(
            accepted_dry_run_row_count and not queue_rows
        ),
        "hard_fail": bool(unsafe_rows),
        "hard_fail_reasons": sorted(
            {
                reason
                for row in unsafe_rows
                for reason in row.get("safety_hard_fail_reasons") or []
            }
        ),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "canonical_namespace_owner": False,
        "canonical_decision_consumer_role": "READ_ONLY_CANONICAL_DECISION_OBSERVER",
        "live_gate": "blocked_human_only",
    }
    if prequeue_counterfactual_rows:
        merged_counterfactual_rows = _merge_counterfactual_feedback_rows(
            _read_json(client, PAPER_EXPLORATION_MATERIALIZATION_COUNTERFACTUAL_KEY),
            prequeue_counterfactual_rows,
        )
        _safe_redis_set(
            client,
            PAPER_EXPLORATION_MATERIALIZATION_COUNTERFACTUAL_KEY,
            merged_counterfactual_rows,
            ex=PAPER_TRAINING_EVIDENCE_TTL_SECONDS,
        )
    _safe_redis_set(
        client,
        EXPLORATION_MATERIALIZATION_QUEUE_STATUS_KEY,
        status,
        ex=2 * 60 * 60,
    )
    return status


def _iso_to_epoch_ms(value: Any, *, fallback_utc: str) -> int:
    stamp = _first_present(value, fallback_utc, _utc_now())
    try:
        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def _freshness_flag_for_projection(
    prediction: Mapping[str, Any],
    *,
    generated_utc: str,
) -> tuple[str, int | None]:
    feature_cutoff = _first_present(prediction.get("feature_cutoff"), prediction.get("generated_at"))
    decision_time = _first_present(prediction.get("decision_time"), prediction.get("generated_at"), generated_utc)
    if not feature_cutoff or not decision_time:
        return PREDICTION_FRESHNESS_MISSING, None
    try:
        cutoff_dt = datetime.fromisoformat(str(feature_cutoff).replace("Z", "+00:00"))
        decision_dt = datetime.fromisoformat(str(decision_time).replace("Z", "+00:00"))
    except ValueError:
        return PREDICTION_FRESHNESS_MISSING, None
    if cutoff_dt.tzinfo is None:
        cutoff_dt = cutoff_dt.replace(tzinfo=timezone.utc)
    if decision_dt.tzinfo is None:
        decision_dt = decision_dt.replace(tzinfo=timezone.utc)
    cutoff_dt = cutoff_dt.astimezone(timezone.utc)
    decision_dt = decision_dt.astimezone(timezone.utc)
    age_ms = max(0, int((decision_dt - cutoff_dt).total_seconds() * 1000))
    if cutoff_dt > decision_dt:
        return PREDICTION_FRESHNESS_STALE, age_ms
    if age_ms > SESSION_MAX_PREDICTION_AGE_SECONDS * 1000:
        return PREDICTION_FRESHNESS_STALE, age_ms
    return PREDICTION_FRESHNESS_FRESH, age_ms


def _strategy_supply_decision_projection(
    prediction: Mapping[str, Any],
    *,
    generated_utc: str,
) -> dict[str, Any]:
    side = str(_first_present(prediction.get("selected_action"), prediction.get("side")) or "").lower()
    if side == "long":
        direction = PREDICTION_DIRECTION_LONG
    elif side == "short":
        direction = PREDICTION_DIRECTION_SHORT
    else:
        direction = PREDICTION_DIRECTION_FLAT
    prediction_id = str(_first_present(prediction.get("prediction_id"), prediction.get("signal_id"), "strategy_supply_prediction"))
    feature_hash = str(_first_present(prediction.get("feature_vector_hash"), prediction_id))
    feature_snapshot_id = str(
        _first_present(
            prediction.get("feature_snapshot_id"),
            prediction.get("entry_feature_snapshot_id"),
            "snap_" + hashlib.sha256(feature_hash.encode("utf-8")).hexdigest()[:32],
        )
    )
    confidence_calibrated = _float(prediction.get("confidence_calibrated"))
    if confidence_calibrated is None:
        confidence_calibrated = 0.0
    confidence_calibrated = min(1.0, max(0.0, confidence_calibrated))
    confidence_raw = _float(prediction.get("confidence_raw"))
    if confidence_raw is None:
        confidence_raw = confidence_calibrated
    confidence_raw = min(1.0, max(0.0, confidence_raw))
    freshness_flag, freshness_age_ms = _freshness_flag_for_projection(
        prediction,
        generated_utc=generated_utc,
    )
    feature_codes = tuple(
        str(item)[:64]
        for item in _as_list(prediction.get("source_labels"))
        if str(item or "").strip()
    )[:8]
    if not feature_codes:
        feature_codes = ("strategy_supply",)
    record = TrainerPredictionRecord(
        prediction_id=prediction_id,
        feature_snapshot_id=feature_snapshot_id,
        symbol=str(prediction.get("symbol") or "").upper(),
        model_version="strategy_supply_dry_run_v1",
        checkpoint_id="strategy_supply_hypothesis_engine",
        prediction_ts_ms=_iso_to_epoch_ms(
            _first_present(prediction.get("decision_time"), prediction.get("generated_at")),
            fallback_utc=generated_utc,
        ),
        direction=direction,
        confidence_raw=float(confidence_raw),
        confidence_calibrated=float(confidence_calibrated),
        worker_id="strategy_supply",
        worker_health_status=str(prediction.get("worker_health_status") or "HEALTHY").upper(),
        freshness_flag=freshness_flag,
        source_freshness_age_ms=freshness_age_ms,
        top_positive_feature_codes=feature_codes,
        top_negative_feature_codes=(),
    )
    now_ms = _iso_to_epoch_ms(
        _first_present(prediction.get("decision_time"), prediction.get("generated_at")),
        fallback_utc=generated_utc,
    )
    orchestrator_record = assemble_orchestrator_decision_record(
        prediction=record,
        low_confidence_threshold=DEFAULT_ORCHESTRATOR_LOW_CONFIDENCE_THRESHOLD,
        now_ms_clock=lambda: now_ms,
    )
    risk_record = assemble_risk_decision_record(
        decision=orchestrator_record,
        now_ms_clock=lambda: now_ms,
    )
    return {
        "feature_snapshot_id": feature_snapshot_id,
        "orchestrator_decision_id": orchestrator_record.decision_id,
        "orchestrator_decision": orchestrator_record.decision_action,
        "orchestrator_action": orchestrator_record.decision_action,
        "orchestrator_decision_action": orchestrator_record.decision_action,
        "orchestrator_reason_code": orchestrator_record.decision_reason_code,
        "orchestrator_decision_reason_code": orchestrator_record.decision_reason_code,
        "orchestrator_live_blocked": orchestrator_record.live_blocked,
        "orchestrator_decision_record": asdict(orchestrator_record),
        "risk_decision_id": risk_record.risk_decision_id,
        "risk_decision": risk_record.risk_action,
        "risk_action": risk_record.risk_action,
        "risk_reason_code": risk_record.risk_reason_code,
        "risk_live_blocked": risk_record.live_blocked,
        "risk_decision_record": asdict(risk_record),
        "risk_orchestrator_projection_source": "strategy_supply_inventory_dry_run",
        "risk_orchestrator_projection_live_blocked": True,
    }


def _prediction_candidate(
    prediction: Mapping[str, Any],
    guardian: Mapping[str, Any] | None,
    altdata_confluence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    candidate = {
        **_as_dict(prediction),
        "action": _first_present(prediction.get("selected_action"), prediction.get("ppo_action")),
        "side": _first_present(prediction.get("selected_action"), prediction.get("ppo_action")),
        "gross_notional_usd": _first_present(prediction.get("gross_notional_usd"), prediction.get("notional_usd"), 0.0),
        "expected_move_after_cost_bps": prediction.get("expected_move_after_cost_bps"),
        "advanced_indicator_context": _as_dict(prediction.get("advanced_indicator_context")),
    }
    decision = evaluate_candidate(
        candidate,
        continuous_edge_guardian_gate=guardian or {},
        altdata_confluence=dict(altdata_confluence) if altdata_confluence else None,
    )
    # Predictions older than the session window are historical residue, not
    # current-session candidates; they must never inflate A+/candidate counts.
    age_seconds = _prediction_age_seconds(prediction)
    if age_seconds is None or age_seconds > SESSION_MAX_PREDICTION_AGE_SECONDS:
        decision["stale_prediction"] = True
        decision["prediction_age_seconds"] = age_seconds
        reasons = list(decision.get("preemptive_decision_reasons") or [])
        if "STALE_PREDICTION_NOT_CURRENT_SESSION" not in reasons:
            reasons.append("STALE_PREDICTION_NOT_CURRENT_SESSION")
        decision["preemptive_decision_reasons"] = reasons
        if decision.get("preemptive_decision") not in ("NO_TRADE",):
            decision["preemptive_decision"] = "NO_TRADE"
    else:
        decision["stale_prediction"] = False
        decision["prediction_age_seconds"] = age_seconds
    return decision


def _matrix_row_prediction_context(
    client: Any,
    row: Mapping[str, Any],
    predictions_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Return matching prediction context for a matrix row, never symbol-only drift.

    A preemptive matrix row can lag the latest ``v2:prediction:{symbol}:{tf}``
    payload. Merging that stale row with a newer same-symbol/timeframe prediction
    creates mixed lineage: old decision_time plus new feature_cutoff/snapshot.
    Require the prediction_id to match before borrowing the prediction payload.
    """

    row_prediction_id = str(row.get("prediction_id") or "").strip()
    prediction = predictions_by_id.get(row_prediction_id) if row_prediction_id else None
    if prediction is not None:
        return dict(prediction)
    symbol = str(row.get("symbol") or "").upper()
    timeframe = str(row.get("timeframe") or "")
    if not symbol or not timeframe:
        return {}
    key = f"v2:prediction:{symbol}:{timeframe}"
    latest = _as_dict(_read_json(client, key))
    latest_prediction_id = str(latest.get("prediction_id") or "").strip()
    if (
        not latest
        or not row_prediction_id
        or not latest_prediction_id
        or latest_prediction_id != row_prediction_id
    ):
        return {}
    latest["redis_key"] = key
    return latest


def build_inventory(
    *,
    client: Any,
    output_dir: Path | None = None,
    session: str = "current",
    timeframes: tuple[str, ...] = TARGET_TIMEFRAMES,
    max_prediction_keys: int = 2500,
) -> dict[str, Any]:
    generated = _utc_now()
    matrix = _as_dict(_read_json(client, PREEMPTIVE_MATRIX_KEY))
    status_payload = _as_dict(_read_json(client, PREEMPTIVE_STATUS_KEY))
    guardian_payload = _as_dict(_read_json(client, CONTINUOUS_GUARDIAN_GATE_KEY))
    live_gate_payload = _as_dict(_read_json(client, LIVE_GATE_KEY))
    performance_circuit_status = _as_dict(
        _read_json(client, PAPER_PERFORMANCE_CIRCUIT_BREAKER_STATUS_KEY)
    )
    guardian = (
        guardian_payload
        if guardian_payload
        else {
            "status": _first_present(status_payload.get("status"), live_gate_payload.get("guardian_state"), "A_GRADE_HALTED_PERFORMANCE"),
            "a_grade_new_entries_allowed": False,
            "new_entries_allowed": False,
        }
    )
    matrix_rows = [_as_dict(row) for row in _as_list(matrix.get("rows"))]
    rows_by_prediction_id: dict[str, dict[str, Any]] = {
        str(row["prediction_id"]): dict(row)
        for row in matrix_rows
        if row.get("prediction_id")
    }
    prediction_keys = _scan_prediction_keys(client, timeframes=timeframes, max_keys=max_prediction_keys)
    predictions: dict[tuple[str, str], dict[str, Any]] = {}
    predictions_by_id: dict[str, dict[str, Any]] = {}
    for key in prediction_keys:
        payload = _as_dict(_read_json(client, key))
        if not payload:
            continue
        symbol = str(payload.get("symbol") or "").upper()
        timeframe = str(payload.get("timeframe") or "").strip()
        if timeframe not in timeframes or not symbol:
            continue
        payload["redis_key"] = key
        predictions[(symbol, timeframe)] = payload
        if payload.get("prediction_id"):
            predictions_by_id[str(payload["prediction_id"])] = payload

    # Allocator simulation runs inside _normalize_candidate via
    # build_allocator_simulation. It resolves price from row/prediction fields
    # only, so inject the live V2 market price (read-only public data already
    # in Redis) per symbol before normalization — a candidate without any
    # market price is still honestly rejected.
    price_cache: dict[str, dict[str, Any]] = {}

    def _resolved_price(symbol: str) -> dict[str, Any]:
        if symbol in price_cache:
            return price_cache[symbol]
        payload = _read_json(client, f"v2:market:current_price:{symbol}")
        if not (isinstance(payload, Mapping) and _float(payload.get("price"))):
            try:
                from v2.backend.app.services.market_data.current_price_resolver import (
                    resolve_current_price,
                )

                payload = resolve_current_price(client, symbol)
            except Exception:
                payload = {}
        price_cache[symbol] = dict(payload) if isinstance(payload, Mapping) else {}
        return price_cache[symbol]

    def _with_price(row: dict[str, Any]) -> dict[str, Any]:
        if _float(_first_present(row.get("current_price"), row.get("entry_price"), row.get("price"))):
            return row
        symbol = str(row.get("symbol") or "").upper()
        resolved = _resolved_price(symbol) if symbol else {}
        row = dict(row)
        price = _float(resolved.get("price"))
        if price is not None and price > 0:
            row["current_price"] = price
            row["current_price_source"] = str(resolved.get("source") or "current_price_resolver")
            row["price_source"] = str(resolved.get("source") or "current_price_resolver")
            row["price_available_at"] = resolved.get("available_at")
            row["current_price_staleness_seconds"] = resolved.get("staleness_seconds")
            row["current_price_fallback_used"] = resolved.get("fallback_used")
            row["can_size_trade"] = resolved.get("can_size_trade")
            row["current_price_can_size_trade"] = resolved.get("can_size_trade")
            row["best_bid"] = resolved.get("bid")
            row["best_ask"] = resolved.get("ask")
            if str(resolved.get("source") or "").startswith("mark_price"):
                row["mark_price"] = price
            if str(resolved.get("source") or "").startswith("index_price"):
                row["index_price"] = price
            if "trade" in str(resolved.get("source") or "") or "kline" in str(resolved.get("source") or ""):
                row["last_trade_price"] = price
        else:
            row["current_price_missing_reason"] = str(
                resolved.get("reason_if_missing") or "NO_EXCHANGE_MARKET"
            )
            row["can_size_trade"] = False
        return row

    normalized: list[dict[str, Any]] = []
    seen_prediction_ids: set[str] = set()
    for row in matrix_rows:
        prediction = _matrix_row_prediction_context(client, row, predictions_by_id)
        item = _normalize_candidate(_with_price(dict(row)), prediction=prediction, generated_utc=generated)
        normalized.append(item)
        if item.get("prediction_id"):
            seen_prediction_ids.add(str(item["prediction_id"]))

    _confluence_cache: dict[tuple[str, str], dict[str, Any]] = {}

    def _confluence_for(symbol: str, timeframe: str) -> dict[str, Any]:
        cache_key = (symbol, timeframe)
        if cache_key not in _confluence_cache:
            _confluence_cache[cache_key] = _as_dict(
                _read_json(client, f"v2:altdata:confluence:{symbol}:{timeframe}")
            )
        return _confluence_cache[cache_key]

    for prediction in predictions.values():
        prediction_id = str(prediction.get("prediction_id") or "")
        if prediction_id in seen_prediction_ids:
            continue
        decision = rows_by_prediction_id.get(prediction_id) or _prediction_candidate(
            prediction,
            guardian,
            altdata_confluence=_confluence_for(
                str(prediction.get("symbol") or "").upper(),
                str(prediction.get("timeframe") or "1m"),
            ),
        )
        decision["source_runtime_key"] = prediction.get("redis_key")
        normalized.append(
            _normalize_candidate(_with_price(dict(decision)), prediction=prediction, generated_utc=generated)
        )

    # Strategy-supply hypotheses: positive-USD rule-based candidates that must
    # still pass every gate (preemptive/risk/orchestrator/allocator). They can
    # never shortcut to A+; missing bucket evidence keeps them honest.
    hypothesis_keys: list[str] = []
    try:
        for key in client.scan_iter(match="v2:strategy_supply:hypotheses:*", count=500):
            hypothesis_keys.append(key.decode() if isinstance(key, bytes) else str(key))
            if len(hypothesis_keys) >= 1_000:
                break
    except Exception:
        hypothesis_keys = []
    for key in sorted(hypothesis_keys):
        payload = _as_dict(_read_json(client, key))
        for hyp in _as_list(payload.get("rows")):
            if not isinstance(hyp, Mapping) or not hyp.get("side"):
                continue
            entry_zone = _as_dict(hyp.get("entry_zone"))
            notional = _float(hyp.get("reference_notional_usd")) or 200.0
            net_usd = _float(hyp.get("expected_net_pnl_usd"))
            supply_stage_rejected_reason = str(hyp.get("why_rejected") or "").strip() or None
            if supply_stage_rejected_reason and (net_usd is None or net_usd <= 0.0):
                continue
            target_move_bps = _float(hyp.get("debug_target_move_bps"))
            stop_move_bps = _float(hyp.get("debug_stop_move_bps"))
            hypothesis_side = str(hyp.get("side") or "").strip().lower()
            cost_bps = (
                _float(hyp.get("debug_cost_bps"))
                or _float(hyp.get("debug_round_trip_cost_bps"))
                or 10.0
            )
            selected_side_net_edge_bps = _float(
                _first_present(
                    hyp.get("selected_side_expected_net_edge_bps"),
                    hyp.get(f"expected_{hypothesis_side}_net_edge_bps"),
                    hyp.get(f"{hypothesis_side}_expected_net_edge_bps"),
                )
            )
            if selected_side_net_edge_bps is None and target_move_bps is not None:
                selected_side_net_edge_bps = target_move_bps - cost_bps
            signed_expected_move_bps = _float(hyp.get("expected_move_bps"))
            if signed_expected_move_bps is None and target_move_bps is not None:
                signed_expected_move_bps = (
                    -target_move_bps if hypothesis_side == "short" else target_move_bps
                )
            signed_expected_move_after_cost_bps = _float(
                hyp.get("expected_move_after_cost_bps")
            )
            if signed_expected_move_after_cost_bps is None and selected_side_net_edge_bps is not None:
                signed_expected_move_after_cost_bps = (
                    -selected_side_net_edge_bps
                    if hypothesis_side == "short"
                    else selected_side_net_edge_bps
                )
            preemptive_expected_move_bps = _preemptive_cost_edge_bps_for_side(
                side=hypothesis_side,
                signed_move_bps=signed_expected_move_bps,
            )
            preemptive_expected_move_after_cost_bps = (
                _preemptive_cost_edge_bps_for_side(
                    side=hypothesis_side,
                    signed_move_bps=signed_expected_move_after_cost_bps,
                )
            )
            explicit_long_net = _float(
                _first_present(
                    hyp.get("long_expected_net_pnl_usd"),
                    hyp.get("expected_long_net_pnl_usd"),
                )
            )
            explicit_short_net = _float(
                _first_present(
                    hyp.get("short_expected_net_pnl_usd"),
                    hyp.get("expected_short_net_pnl_usd"),
                )
            )
            if explicit_long_net is None and hypothesis_side == "long":
                explicit_long_net = net_usd
            if explicit_short_net is None and hypothesis_side == "short":
                explicit_short_net = net_usd
            explicit_long_net_edge_bps = _float(
                _first_present(
                    hyp.get("expected_long_net_edge_bps"),
                    hyp.get("long_expected_net_edge_bps"),
                )
            )
            explicit_short_net_edge_bps = _float(
                _first_present(
                    hyp.get("expected_short_net_edge_bps"),
                    hyp.get("short_expected_net_edge_bps"),
                )
            )
            if explicit_long_net_edge_bps is None and hypothesis_side == "long":
                explicit_long_net_edge_bps = selected_side_net_edge_bps
            if explicit_short_net_edge_bps is None and hypothesis_side == "short":
                explicit_short_net_edge_bps = selected_side_net_edge_bps
            provider_labels = [str(item) for item in _as_list(hyp.get("provider_features_used"))]
            if hyp.get("ta_context"):
                provider_labels.append("ta_atr")
            if hyp.get("microstructure_context") or hyp.get("orderbook_context"):
                provider_labels.append("microstructure_orderbook_depth")
            if hyp.get("fvg_context") or hyp.get("liquidity_context"):
                provider_labels.append("fvg_liquidity_zone_structure")
            if hyp.get("coinglass_context"):
                provider_labels.append("coinglass_derivatives")
            if hyp.get("moralis_context"):
                provider_labels.append("moralis_onchain")
            advanced_context = _as_dict(hyp.get("advanced_indicator_context"))
            hypothesis_composite_trust = _float(
                _first_present(
                    hyp.get("composite_microstructure_trust_score"),
                    hyp.get("microstructure_trust_score"),
                )
            )
            hypothesis_market_state_integrity = _float(hyp.get("market_state_integrity_score"))
            if hypothesis_market_state_integrity is None and hypothesis_composite_trust is not None:
                hypothesis_market_state_integrity = (
                    hypothesis_composite_trust * 100.0
                    if hypothesis_composite_trust <= 1.0
                    else hypothesis_composite_trust
                )
            loss_probability_reason_payload = _loss_probability_reason_payload(hyp)
            pseudo_prediction = {
                "prediction_id": str(hyp.get("hypothesis_id") or hyp.get("strategy_id") or ""),
                "signal_id": str(hyp.get("hypothesis_id") or hyp.get("strategy_id") or ""),
                "hypothesis_id": hyp.get("hypothesis_id"),
                "strategy_supply_hypothesis_id": hyp.get("hypothesis_id") or hyp.get("strategy_id"),
                "symbol": hyp.get("symbol"),
                "timeframe": hyp.get("timeframe"),
                "generated_at": hyp.get("generated_utc"),
                "decision_time": hyp.get("generated_utc"),
                "available_at": _first_present(
                    entry_zone.get("available_at"),
                    hyp.get("available_at"),
                    hyp.get("generated_utc"),
                ),
                "selected_action": hyp.get("side"),
                "confidence_raw": max(0.0, 1.0 - (_float(hyp.get("loss_probability")) or 1.0)),
                "confidence_calibrated": max(0.0, 1.0 - (_float(hyp.get("loss_probability")) or 1.0)),
                "expected_move_bps": signed_expected_move_bps,
                "expected_move_after_cost_bps": signed_expected_move_after_cost_bps,
                "stop_distance_bps": stop_move_bps,
                "atr_bps": _float(hyp.get("debug_atr_bps")),
                "entry_atr_bps": _float(hyp.get("debug_atr_bps")),
                "observed_spread_bps": _float(hyp.get("debug_spread_bps")) or 0.6,
                "expected_slippage_bps": _float(hyp.get("debug_slippage_bps")) or 5.4,
                "fee_bps": _float(hyp.get("debug_fee_bps")) or 4.0,
                "funding_bps": _float(hyp.get("debug_funding_bps")) or 0.0,
                "gross_notional_usd": notional,
                "target_notional_usd": notional,
                "notional_usd": notional,
                "expected_net_pnl_usd": net_usd,
                "expected_gross_pnl_usd": _float(hyp.get("expected_gross_pnl_usd")),
                "expected_cost_usd": _float(hyp.get("expected_cost_usd")),
                "expected_fees_usd": _float(hyp.get("fees_usd")),
                "expected_slippage_usd": _float(hyp.get("slippage_usd")),
                "expected_funding_usd": _float(hyp.get("funding_usd")),
                "fees_usd": _float(hyp.get("fees_usd")),
                "slippage_usd": _float(hyp.get("slippage_usd")),
                "funding_usd": _float(hyp.get("funding_usd")),
                "latency_reserve_usd": _float(hyp.get("latency_reserve_usd")),
                "liquidation_risk_reserve_usd": _float(hyp.get("liquidation_risk_reserve_usd")),
                "exit_failure_reserve_usd": _float(hyp.get("exit_failure_reserve_usd")),
                "expected_max_loss_usd": _float(hyp.get("expected_max_loss_usd")),
                "expected_liquidation_buffer_usd": _float(hyp.get("expected_liquidation_buffer_usd")),
                "liquidation_buffer_usd": _float(hyp.get("liquidation_buffer_usd")),
                "liquidation_buffer_bps": _float(hyp.get("liquidation_buffer_bps")),
                "liquidation_buffer_source": hyp.get("liquidation_buffer_source"),
                "liquidation_buffer_signed_read_verified": hyp.get("liquidation_buffer_signed_read_verified"),
                "live_liquidation_buffer_requires_signed_read": hyp.get("live_liquidation_buffer_requires_signed_read"),
                "pre_trade_loss_probability": _float(hyp.get("loss_probability")),
                "loss_probability_reason": loss_probability_reason_payload.get(
                    "loss_probability_reason"
                ),
                "loss_probability_reasons": loss_probability_reason_payload.get(
                    "loss_probability_reasons"
                ),
                "loss_probability_calibration": loss_probability_reason_payload.get(
                    "loss_probability_calibration"
                ),
                "long_expected_net_pnl_usd": explicit_long_net,
                "short_expected_net_pnl_usd": explicit_short_net,
                "expected_long_net_edge_bps": explicit_long_net_edge_bps,
                "expected_short_net_edge_bps": explicit_short_net_edge_bps,
                "long_expected_max_loss_usd": _float(hyp.get("expected_max_loss_usd")) if hypothesis_side == "long" else None,
                "short_expected_max_loss_usd": _float(hyp.get("expected_max_loss_usd")) if hypothesis_side == "short" else None,
                "long_loss_probability": _float(hyp.get("loss_probability")) if hypothesis_side == "long" else None,
                "short_loss_probability": _float(hyp.get("loss_probability")) if hypothesis_side == "short" else None,
                "current_price": _float(entry_zone.get("price")),
                "entry_price": _float(entry_zone.get("price")),
                "price_source": _first_present(entry_zone.get("source"), hyp.get("price_source"), "strategy_supply_entry_zone"),
                "price_available_at": _first_present(entry_zone.get("available_at"), hyp.get("generated_utc")),
                "current_price_can_size_trade": True,
                "can_size_trade": True,
                "liquidity_exit_depth": _float(hyp.get("expected_exit_depth_usd")),
                "orderbook_depth_usd": _float(hyp.get("expected_exit_depth_usd")),
                "exit_feasible": hyp.get("exit_feasible"),
                "exit_feasibility_score": _float(hyp.get("exit_feasibility_score")),
                "microstructure_trust_score": _float(hyp.get("microstructure_trust_score")),
                "composite_microstructure_trust_score": hypothesis_composite_trust,
                "market_state_integrity_score": hypothesis_market_state_integrity,
                "market_state_integrity_minimum_score": _float(
                    hyp.get("market_state_integrity_minimum_score")
                )
                or ALLOCATOR_MARKET_STATE_INTEGRITY_MIN_SCORE,
                "market_state_integrity_source": hyp.get("market_state_integrity_source"),
                "trade_tape_confirmation_score": _float(hyp.get("trade_tape_confirmation_score")),
                "advanced_indicator_context": advanced_context,
                "features": {
                    name: 1.0
                    for name in provider_labels
                    if name
                },
                "source_labels": provider_labels,
                "provider_feature_hashes": _as_dict(hyp.get("provider_feature_hashes")),
                "source_hashes": _as_dict(hyp.get("provider_feature_hashes")),
                "TA_features_present": bool(hyp.get("ta_context")),
                "microstructure_features_present": bool(hyp.get("microstructure_context") or hyp.get("orderbook_context")),
                "advanced_indicator_features_present": bool(hyp.get("advanced_indicator_context") or hyp.get("fvg_context") or hyp.get("liquidity_context")),
                "FVG_liquidity_zone_features_present": bool(hyp.get("fvg_context") or hyp.get("liquidity_context")),
                "CoinGlass_features_present": bool(hyp.get("coinglass_context")),
                "Moralis_features_present": bool(hyp.get("moralis_context")),
                "CoinAnk_features_present": bool(hyp.get("coinank_context")),
                "coinank_context_missing_reason": hyp.get("coinank_context_missing_reason"),
                "liquidation_context_source": hyp.get("liquidation_context_source"),
                "strategy_selected_mode": str(hyp.get("strategy_family") or "strategy_supply"),
                "market_regime": hyp.get("market_regime"),
                "market_regime_at_entry": hyp.get("market_regime_at_entry"),
                "strategy_market_regime": hyp.get("strategy_market_regime"),
                "source_tier": "STRATEGY_SUPPLY_HYPOTHESIS",
                "strategy_supply_stage_rejected_reason": supply_stage_rejected_reason,
                "strategy_supply_gate_clean": supply_stage_rejected_reason is None,
                "strategy_supply_positive_net_usd": net_usd is not None and net_usd > 0.0,
                "redis_key": key,
                # Closed-candle confirmation is stamped at the TA/generator
                # boundary from raw close-boundary proof; carry it through so
                # the paper-loop market-evidence gate sees the truthful value
                # (never synthesized here).
                "entry_feature_candle_closed_confirmed": hyp.get(
                    "entry_feature_candle_closed_confirmed"
                ),
                "candle_closed_confirmed": hyp.get("candle_closed_confirmed"),
                "last_closed_candle_open_ts_ms": hyp.get(
                    "last_closed_candle_open_ts_ms"
                ),
                "last_closed_candle_close_ts_ms": hyp.get(
                    "last_closed_candle_close_ts_ms"
                ),
                "ta_source_key": hyp.get("ta_source_key"),
                # Lineage: the hypothesis was built from live Redis context at
                # generated_utc; its hash binds this exact row content.
                "feature_cutoff": hyp.get("generated_utc"),
                "feature_snapshot_id": "snap_"
                + hashlib.sha256(
                    json.dumps(dict(hyp), sort_keys=True, default=str).encode("utf-8")
                ).hexdigest()[:32],
                "feature_vector_hash": "strategy_supply_"
                + hashlib.sha256(
                    json.dumps(dict(hyp), sort_keys=True, default=str).encode("utf-8")
                ).hexdigest()[:32],
            }
            preemptive_prediction = dict(pseudo_prediction)
            preemptive_prediction["expected_move_bps"] = preemptive_expected_move_bps
            preemptive_prediction["expected_move_after_cost_bps"] = (
                preemptive_expected_move_after_cost_bps
            )
            decision = _prediction_candidate(
                preemptive_prediction,
                guardian,
                altdata_confluence=_confluence_for(
                    str(hyp.get("symbol") or "").upper(),
                    str(hyp.get("timeframe") or "1m"),
                ),
            )
            decision["source_runtime_key"] = key
            decision["strategy_supply_hypothesis"] = True
            decision["strategy_family"] = hyp.get("strategy_family")
            if supply_stage_rejected_reason:
                reasons = list(decision.get("preemptive_decision_reasons") or [])
                reasons.append(f"STRATEGY_SUPPLY_STAGE_REJECTED:{supply_stage_rejected_reason}")
                decision["preemptive_decision_reasons"] = list(
                    dict.fromkeys(str(reason) for reason in reasons if reason)
                )
            # evaluate_candidate returns a gate decision, not a full candidate
            # economic packet. Preserve the rule-engine USD evidence before
            # allocator normalization so rejects stay explainable without
            # promoting the row to A+.
            decision.update(
                {
                    field: value
                    for field, value in pseudo_prediction.items()
                    if field
                    in {
                        "gross_notional_usd",
                        "target_notional_usd",
                        "notional_usd",
                        "expected_net_pnl_usd",
                        "expected_gross_pnl_usd",
                        "expected_cost_usd",
                        "expected_fees_usd",
                        "expected_slippage_usd",
                        "expected_funding_usd",
                        "fees_usd",
                        "slippage_usd",
                        "funding_usd",
                        "latency_reserve_usd",
                        "liquidation_risk_reserve_usd",
                        "exit_failure_reserve_usd",
                        "expected_max_loss_usd",
                        "expected_liquidation_buffer_usd",
                        "liquidation_buffer_usd",
                        "liquidation_buffer_bps",
                        "liquidation_buffer_source",
                        "liquidation_buffer_signed_read_verified",
                        "live_liquidation_buffer_requires_signed_read",
                        "pre_trade_loss_probability",
                        "loss_probability_reason",
                        "loss_probability_reasons",
                        "loss_probability_calibration",
                        "long_expected_net_pnl_usd",
                        "short_expected_net_pnl_usd",
                        "expected_long_net_edge_bps",
                        "expected_short_net_edge_bps",
                        "long_expected_max_loss_usd",
                        "short_expected_max_loss_usd",
                        "long_loss_probability",
                        "short_loss_probability",
                        "expected_move_bps",
                        "expected_move_after_cost_bps",
                        "stop_distance_bps",
                        "observed_spread_bps",
                        "expected_slippage_bps",
                        "fee_bps",
                        "funding_bps",
                        "current_price",
                        "entry_price",
                        "price_source",
                        "price_available_at",
                        "current_price_can_size_trade",
                        "can_size_trade",
                        "liquidity_exit_depth",
                        "orderbook_depth_usd",
                        "exit_feasible",
                        "exit_feasibility_score",
                        "microstructure_trust_score",
                        "composite_microstructure_trust_score",
                        "market_state_integrity_score",
                        "market_state_integrity_minimum_score",
                        "market_state_integrity_source",
                        "entry_feature_candle_closed_confirmed",
                        "candle_closed_confirmed",
                        "last_closed_candle_open_ts_ms",
                        "last_closed_candle_close_ts_ms",
                        "ta_source_key",
                        "trade_tape_confirmation_score",
                        "advanced_indicator_context",
                        "features",
                        "source_labels",
                        "provider_feature_hashes",
                        "source_hashes",
                        "TA_features_present",
                        "microstructure_features_present",
                        "advanced_indicator_features_present",
                        "FVG_liquidity_zone_features_present",
                        "CoinGlass_features_present",
                        "Moralis_features_present",
                        "CoinAnk_features_present",
                        "coinank_context_missing_reason",
                        "liquidation_context_source",
                        "strategy_selected_mode",
                        "market_regime",
                        "market_regime_at_entry",
                        "strategy_market_regime",
                        "source_tier",
                        "strategy_supply_stage_rejected_reason",
                        "strategy_supply_gate_clean",
                        "strategy_supply_positive_net_usd",
                        "feature_snapshot_id",
                        "feature_cutoff",
                        "feature_vector_hash",
                    }
                    and value is not None
                }
            )
            try:
                decision.update(
                    _strategy_supply_decision_projection(
                        pseudo_prediction,
                        generated_utc=generated,
                    )
                )
            except Exception as exc:
                reasons = list(decision.get("preemptive_decision_reasons") or [])
                reasons.append(f"RISK_ORCHESTRATOR_DRY_RUN_PROJECTION_FAILED:{type(exc).__name__}")
                decision["preemptive_decision_reasons"] = reasons
                decision["risk_orchestrator_projection_source"] = "strategy_supply_inventory_dry_run"
                decision["risk_orchestrator_projection_error"] = type(exc).__name__
            normalized.append(
                _normalize_candidate(
                    _with_price(dict(decision)),
                    prediction=pseudo_prediction,
                    generated_utc=generated,
                )
            )

    stale_filtered_count = 0
    if session == "current":
        before_filter_count = len(normalized)
        normalized = [row for row in normalized if not row.get("stale_prediction")]
        stale_filtered_count = before_filter_count - len(normalized)

    exploration_prequeue_performance_block_counts: Counter[str] = Counter()
    exploration_prequeue_performance_advisory_rows = 0
    for row in normalized:
        block_reasons, performance_evidence = (
            _materialization_prequeue_performance_block_reasons(
                row,
                performance_circuit_status,
            )
        )
        if performance_evidence:
            row.update(performance_evidence)
        if (
            not block_reasons
            and row.get("paper_risk_controller_exploration_above_floor") is True
            and performance_evidence.get(
                "paper_risk_controller_exploration_global_halt_bucket_clean_allowed"
            )
            is True
        ):
            exploration_prequeue_performance_advisory_rows += 1
        if not block_reasons or row.get("paper_exploration_paper_fill_allowed") is not True:
            continue
        combined_prequeue = sorted(
            set(
                str(reason)
                for reason in (
                    list(row.get("paper_exploration_prequeue_block_reasons") or [])
                    + block_reasons
                )
                if reason
            )
        )
        row["paper_exploration_prequeue_block_reasons"] = combined_prequeue
        row["paper_exploration_materialization_prequeue_block_reasons"] = (
            combined_prequeue
        )
        row["paper_exploration_performance_prequeue_block_reasons"] = (
            block_reasons
        )
        row["paper_exploration_paper_fill_block_reasons"] = sorted(
            set(
                str(reason)
                for reason in (
                    list(row.get("paper_exploration_paper_fill_block_reasons") or [])
                    + block_reasons
                )
                if reason
            )
        )
        row["paper_exploration_paper_fill_allowed"] = False
        row["paper_exploration_materialization_queue_ready"] = False
        row["paper_exploration_current_blocker"] = (
            "MATERIALIZATION_PREQUEUE_BLOCKED"
        )
        for reason in block_reasons:
            exploration_prequeue_performance_block_counts[reason] += 1

    normalized.sort(key=lambda item: (str(item.get("timeframe")), str(item.get("symbol")), str(item.get("prediction_id"))))
    reason_counts: Counter[str] = Counter()
    class_counts: Counter[str] = Counter()
    timeframe_counts: Counter[str] = Counter()
    symbol_counts: Counter[str] = Counter()
    for item in normalized:
        timeframe_counts[str(item.get("timeframe") or "missing")] += 1
        symbol_counts[str(item.get("symbol") or "missing")] += 1
        if item.get("A_plus_candidate"):
            continue
        reason_counts.update(str(reason) for reason in item.get("block_reasons") or [])
        class_counts.update(str(name) for name in item.get("blocker_classes") or [])

    a_plus_rows = [row for row in normalized if row.get("A_plus_candidate")]
    live_ready_rows = [row for row in normalized if row.get("live_ready_candidate")]
    allocator_decision_status_counts = Counter(str(row.get("allocator_decision") or "MISSING") for row in normalized)
    risk_decision_status_counts = Counter(str(row.get("risk_decision") or "MISSING") for row in normalized)
    orchestrator_decision_status_counts = Counter(str(row.get("orchestrator_decision") or "MISSING") for row in normalized)
    preemptive_decision_status_counts = Counter(str(row.get("preemptive_action") or "MISSING") for row in normalized)
    exploration_rows = [
        row
        for row in normalized
        if row.get("paper_risk_controller_exploration_eligible") is True
    ]
    exploration_above_floor_rows = [
        row
        for row in normalized
        if row.get("paper_risk_controller_exploration_above_floor") is True
    ]
    exploration_floor_rejection_counts = Counter(
        str(reason)
        for row in normalized
        for reason in row.get("paper_risk_controller_exploration_block_reasons") or []
    )
    exploration_risk_controller_seen_rows = sum(
        1
        for row in exploration_above_floor_rows
        if row.get("paper_exploration_risk_controller_input_written") is True
    )
    exploration_orchestrator_seen_rows = sum(
        1
        for row in exploration_above_floor_rows
        if row.get("paper_exploration_orchestrator_input_written") is True
    )
    exploration_allocator_seen_rows = sum(
        1
        for row in exploration_above_floor_rows
        if row.get("paper_exploration_allocator_input_written") is True
    )
    materialization_queue_status = _publish_materialization_queue(
        client,
        exploration_above_floor_rows,
        generated_utc=generated,
    )
    exploration_paper_accepted_rows = int(
        materialization_queue_status.get("canonical_executable_row_count") or 0
    )
    exploration_unknown_rows = sum(
        1
        for row in exploration_above_floor_rows
        if row.get("paper_exploration_unknown_resolution") is True
    )
    allocator_decision_missing_count = allocator_decision_status_counts.get("MISSING", 0)
    allocator_decision_pass_count = allocator_decision_status_counts.get("PASS", 0)
    allocator_decision_reject_count = sum(
        count
        for decision, count in allocator_decision_status_counts.items()
        if decision not in {"MISSING", "PASS"}
    )
    near_rows = sorted(
        [row for row in normalized if not row.get("A_plus_candidate")],
        key=lambda row: (
            len(row.get("blocker_classes") or []),
            -float(row.get("expected_net_pnl_usd") or 0.0),
            float(row.get("pre_trade_loss_probability") or 1.0),
        ),
    )[:50]
    hard_failures = {
        "missing_candidate_id_count": sum(1 for row in normalized if not row.get("candidate_id")),
        "missing_symbol_count": sum(1 for row in normalized if not row.get("symbol")),
        "missing_timeframe_count": sum(1 for row in normalized if not row.get("timeframe")),
        "missing_side_and_no_side_reason_count": sum(1 for row in normalized if not row.get("side") and not row.get("no_side_reason")),
        "missing_current_price_and_price_missing_reason_count": sum(
            1 for row in normalized if row.get("current_price") is None and not row.get("price_missing_reason")
        ),
        "missing_expected_move_count": sum(1 for row in normalized if row.get("expected_move") is None),
        "missing_expected_gross_pnl_usd_count": sum(1 for row in normalized if row.get("expected_gross_pnl_usd") is None),
        "missing_expected_cost_usd_count": sum(1 for row in normalized if row.get("expected_cost_usd") is None),
        "unknown_rejection_reason_count": sum(1 for reason in reason_counts if reason.upper() == "UNKNOWN"),
        "missing_preemptive_decision_id_count": sum(1 for row in normalized if not row.get("preemptive_decision_id")),
        "missing_allocator_decision_id_count": sum(1 for row in normalized if not row.get("allocator_decision_id")),
        "missing_feature_vector_hash_count": sum(1 for row in normalized if not row.get("feature_vector_hash")),
        "missing_feature_cutoff_count": sum(1 for row in normalized if not row.get("feature_cutoff")),
        "missing_decision_time_count": sum(1 for row in normalized if not row.get("decision_time")),
        "missing_expected_net_pnl_usd_count": sum(1 for row in normalized if row.get("expected_net_pnl_usd") is None),
        "allocator_decision_missing_count": allocator_decision_missing_count,
        "expected_liquidation_buffer_usd_missing_count": sum(1 for row in normalized if row.get("expected_liquidation_buffer_usd") is None),
        "expected_max_loss_usd_missing_count": sum(1 for row in normalized if row.get("expected_max_loss_usd") is None),
        "bps_only_economics_count": sum(1 for row in normalized if "ECONOMICS_BPS_ONLY" in set(row.get("block_reasons") or [])),
        "probation_final_a_plus_count": sum(1 for row in normalized if row.get("counts_as_probation") and row.get("counts_as_A_plus")),
        "reconstructed_final_a_plus_count": sum(1 for row in normalized if row.get("counts_as_reconstructed") and row.get("counts_as_A_plus")),
    }
    hard_fail = any(int(value or 0) > 0 for value in hard_failures.values())
    guardian_failure_reasons = [
        dict(reason)
        for reason in _as_list(guardian.get("failure_reasons"))
        if isinstance(reason, Mapping)
    ]
    guardian_top_reason = _first_present(
        *[
            reason.get("reason")
            for reason in guardian_failure_reasons
            if isinstance(reason, Mapping)
        ],
        None,
    )
    rejection_matrix = {
        "schema_version": "v2_a_plus_candidate_rejection_matrix_v1",
        "generated_utc": generated,
        "session": session,
        "total_candidate_count": len(normalized),
        "a_plus_candidate_count": len(a_plus_rows),
        "live_ready_candidate_count": len(live_ready_rows),
        "blocker_class_counts": dict(class_counts.most_common()),
        "rejection_reason_counts": dict(reason_counts.most_common()),
        "top_blocker_class": class_counts.most_common(1)[0][0] if class_counts else None,
        "allowed_blocker_classes": list(ALLOWED_BLOCKER_CLASSES),
        "unknown_rejection_reason_count": hard_failures["unknown_rejection_reason_count"],
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated,
        "session": session,
        "timeframes": list(timeframes),
        "matrix_generated_utc": matrix.get("generated_utc"),
        "matrix_candidate_count": matrix.get("candidate_count"),
        "matrix_materialized_row_count": len(matrix_rows),
        "prediction_key_count": len(prediction_keys),
        "stale_current_session_rows_filtered_count": stale_filtered_count,
        "total_candidate_count": len(normalized),
        "a_plus_candidate_count": len(a_plus_rows),
        "live_ready_candidate_count": len(live_ready_rows),
        "counts_by_timeframe": dict(timeframe_counts),
        "top_symbols": [symbol for symbol, _ in symbol_counts.most_common(20)],
        "allocator_decision_missing_count": allocator_decision_missing_count,
        "allocator_decision_pass_count": allocator_decision_pass_count,
        "allocator_decision_reject_count": allocator_decision_reject_count,
        "allocator_decision_status_counts": dict(allocator_decision_status_counts),
        "risk_decision_status_counts": dict(risk_decision_status_counts),
        "orchestrator_decision_status_counts": dict(orchestrator_decision_status_counts),
        "preemptive_decision_status_counts": dict(preemptive_decision_status_counts),
        "paper_risk_controller_exploration_tier": PAPER_RISK_CONTROLLER_EXPLORATION_TIER,
        "paper_risk_controller_exploration_eligible_count": len(exploration_rows),
        "paper_risk_controller_exploration_above_floor_count": len(exploration_above_floor_rows),
        "paper_risk_controller_exploration_rejection_counts": dict(
            exploration_floor_rejection_counts.most_common()
        ),
        "paper_risk_controller_exploration_risk_controller_seen_rows": (
            exploration_risk_controller_seen_rows
        ),
        "paper_risk_controller_exploration_orchestrator_seen_rows": (
            exploration_orchestrator_seen_rows
        ),
        "paper_risk_controller_exploration_allocator_seen_rows": (
            exploration_allocator_seen_rows
        ),
        "paper_risk_controller_exploration_paper_accepted_rows": (
            exploration_paper_accepted_rows
        ),
        "paper_risk_controller_exploration_prequeue_performance_block_counts": dict(
            exploration_prequeue_performance_block_counts.most_common()
        ),
        "paper_risk_controller_exploration_prequeue_performance_advisory_rows": (
            exploration_prequeue_performance_advisory_rows
        ),
        "paper_performance_circuit_breaker_state_seen_by_inventory": (
            performance_circuit_status.get("state")
            or performance_circuit_status.get("status")
        ),
        "continuous_edge_guardian_gate_status": {
            "status": guardian.get("status"),
            "a_grade_new_entries_allowed": guardian.get("a_grade_new_entries_allowed"),
            "new_entries_allowed": guardian.get("new_entries_allowed"),
            "block_all_new_a_grade_entries": guardian.get("block_all_new_a_grade_entries"),
            "generated_utc": guardian.get("generated_utc"),
            "failure_reasons": guardian_failure_reasons,
        },
        "continuous_edge_guardian_top_reason": guardian_top_reason,
        "paper_exploration_materialization_queue_status": (
            materialization_queue_status
        ),
        "paper_exploration_materialization_queue_rows": (
            materialization_queue_status.get("queued_count")
        ),
        "paper_exploration_materialization_queue_expired_rows": (
            materialization_queue_status.get("expired_count")
        ),
        "paper_risk_controller_exploration_unknown_rows": exploration_unknown_rows,
        "expected_liquidation_buffer_usd_missing_count": hard_failures["expected_liquidation_buffer_usd_missing_count"],
        "expected_max_loss_usd_missing_count": hard_failures["expected_max_loss_usd_missing_count"],
        "expected_net_pnl_usd_missing_count": hard_failures["missing_expected_net_pnl_usd_count"],
        "preemptive_status": status_payload,
        "live_gate": _first_present(live_gate_payload.get("live_gate"), "blocked_human_only"),
        "hard_failures": hard_failures,
        "hard_fail": hard_fail,
        "primary_blocker": rejection_matrix["top_blocker_class"],
        "final_state": _inventory_final_state(
            a_plus_candidate_count=len(a_plus_rows),
            live_ready_candidate_count=len(live_ready_rows),
            hard_fail=hard_fail,
            primary_blocker=rejection_matrix["top_blocker_class"],
        ),
        "exact_no_A_plus_reason": (
            None
            if a_plus_rows
            else rejection_matrix["top_blocker_class"] or "NO_CURRENT_CANDIDATE_ROWS"
        ),
        "order_submitted": False,
        "test_order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_jsonl(output_dir / "candidate_inventory.jsonl", normalized)
        _write_json(output_dir / "candidate_inventory_summary.json", summary)
        _write_json(output_dir / "candidate_rejection_matrix.json", rejection_matrix)
        _write_jsonl(output_dir / "a_plus_candidate_rows.jsonl", a_plus_rows)
        _write_jsonl(output_dir / "near_a_plus_candidate_rows.jsonl", near_rows)
        _write_json(
            output_dir / "paper_exploration_materialization_queue_status.json",
            materialization_queue_status,
        )
    return {
        "rows": normalized,
        "summary": summary,
        "rejection_matrix": rejection_matrix,
        "a_plus_rows": a_plus_rows,
        "near_rows": near_rows,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--session", default="current", choices=("current",))
    parser.add_argument("--all-symbols", action="store_true")
    parser.add_argument("--all-timeframes", action="store_true")
    parser.add_argument("--redis-url", default=None)
    parser.add_argument("--max-prediction-keys", type=int, default=2500)
    parser.add_argument("--fail-on-hard-fail", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Compatibility flag; this read-only inventory command already runs once.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    client = _redis_client(args.redis_url)
    result = build_inventory(
        client=client,
        output_dir=Path(args.output_dir),
        session=args.session,
        timeframes=TARGET_TIMEFRAMES,
        max_prediction_keys=args.max_prediction_keys,
    )
    payload = {
        "summary": result["summary"],
        "rejection_matrix": result["rejection_matrix"],
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps({
            "total_candidate_count": result["summary"]["total_candidate_count"],
            "a_plus_candidate_count": result["summary"]["a_plus_candidate_count"],
            "live_ready_candidate_count": result["summary"]["live_ready_candidate_count"],
            "primary_blocker": result["summary"]["primary_blocker"],
            "hard_fail": result["summary"]["hard_fail"],
        }, sort_keys=True))
    if args.fail_on_hard_fail and result["summary"]["hard_fail"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
