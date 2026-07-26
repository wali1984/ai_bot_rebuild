"""Bounded natural-acceptance observer for a governed paper checkpoint.

This worker is evidence-only.  It reads canonical serving, paper admission,
fill, position, accounting, and close records; it never writes a prediction,
decision, order, fill, position, or economic outcome.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

STATUS_KEY = "v2:operations:generation_acceptance"
RESTART_PENDING_KEY = "v2:operations:restart_reconstruction_pending"
COHORT_KEY = "v2:paper:economic_evaluation_cohort"
PREDICTION_STATUS_KEY = "v2:prediction_serving:status"
MATRIX_KEY = "v2:paper:preemptive_decision_matrix"
PAPER_STATUS_KEY = "v2:paper:trade_management:status"
ACCEPTED_FILLS_KEY = "v2:paper:accepted_fills"
OPEN_POSITIONS_KEY = "v2:paper:open_positions"
CLOSED_TRADES_KEY = "v2:paper:closed_trades"
ACCOUNT_STATUS_KEY = "v2:paper:account_margin_status"
PAPER_SIGNALS_KEY = "v2:signals:paper"
ADAPTIVE_TUNING_KEY = "v2:orchestrator:adaptive_gate_tuning_state"

DEFAULT_MINIMUM_CYCLES = 50
# Binance USD-M is continuous rather than session-gapped.  The governed
# candidate matrix currently spans 5m, 15m, and 1h, so one fully elapsed 1h
# opportunity window is the smallest explicit window that covers every active
# decision timeframe without inventing an exchange session boundary.
DEFAULT_MINIMUM_OBSERVATION_SECONDS = 60 * 60
DEFAULT_STATUS_TTL_SECONDS = 900
SCHEMA_VERSION = "generation_natural_acceptance_observer_v1"
MARKET_SESSION_DEFINITION = (
    "ONE_FULL_MAXIMUM_ELIGIBLE_TIMEFRAME_WINDOW_1H_CONTINUOUS_CRYPTO_MARKET"
)
RESTART_CAPTURE_SCHEMA_VERSION = "generation_restart_reconstruction_capture_v1"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _json_value(client: Any, key: str, default: Any) -> Any:
    try:
        raw = client.get(key)
    except Exception:  # noqa: BLE001
        return default
    if not raw:
        return default
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="strict")
    try:
        return json.loads(raw)
    except (TypeError, ValueError, UnicodeDecodeError):
        return default


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value if isinstance(row, Mapping)]


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _matches_generation(
    row: Mapping[str, Any], *, generation: int, cohort_id: str
) -> bool:
    row_generation = row.get("checkpoint_generation")
    if row_generation in (None, ""):
        row_generation = row.get("active_model_registry_generation")
    try:
        generation_matches = int(row_generation) == generation
    except (TypeError, ValueError):
        generation_matches = False
    row_cohort = str(row.get("paper_strategy_cohort_id") or "")
    return generation_matches and row_cohort == cohort_id


def _is_natural(row: Mapping[str, Any]) -> bool:
    exclusion_flags = (
        "engineering_canary",
        "paper_recovery_only",
        "engineering_replay",
        "excluded_from_economic_metrics",
        "synthetic_outcome",
        "test_order",
    )
    return row.get("paper_only") is not False and not any(
        row.get(field) is True for field in exclusion_flags
    )


def _identity(row: Mapping[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = row.get(field)
        if value not in (None, ""):
            return str(value)
    return ""


def _duplicate_count(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> int:
    identities = [_identity(row, fields) for row in rows]
    counts = Counter(identity for identity in identities if identity)
    return sum(count - 1 for count in counts.values() if count > 1)


def _reservation_leak_count(
    *, account: Mapping[str, Any], open_positions: list[dict[str, Any]]
) -> int:
    reserved = _finite(
        account.get("newly_reserved_margin_usd", account.get("newly_reserved_margin"))
    )
    used = _finite(account.get("used_margin_usd", account.get("used_margin")))
    if open_positions:
        return 0
    return int((reserved or 0.0) > 1e-9 or (used or 0.0) > 1e-9)


def _adaptive_loss_probability_threshold(client: Any) -> float | None:
    try:
        prefix = client.getrange(ADAPTIVE_TUNING_KEY, 0, 65_535)
    except Exception:  # noqa: BLE001
        return None
    if isinstance(prefix, bytes):
        prefix = prefix.decode("utf-8", errors="strict")
    if not isinstance(prefix, str):
        return None
    match = re.search(
        r'"adaptive_loss_probability_threshold"\s*:\s*'
        r"(-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)",
        prefix,
    )
    return _finite(match.group(1)) if match else None


def _evidence_age_seconds(
    row: Mapping[str, Any], signal: Mapping[str, Any]
) -> float | None:
    candidate_available = _parse_time(
        row.get("candidate_available_at")
        or signal.get("available_at")
        or signal.get("source_available_time")
        or _mapping(
            _mapping(signal.get("microstructure_trust_evidence")).get(
                "source_payload"
            )
        ).get("record_available_at")
    )
    decision_time = _parse_time(row.get("preemptive_decision_time"))
    evidence_age = None
    if candidate_available is not None and decision_time is not None:
        evidence_age = max(0.0, (decision_time - candidate_available).total_seconds())
    return evidence_age


def _candidate_attribution(
    client: Any,
    row: Mapping[str, Any],
    *,
    signal_by_prediction: Mapping[str, Mapping[str, Any]],
    required_max_loss: float | None,
) -> dict[str, Any]:
    prediction_id = str(row.get("prediction_id") or "")
    signal = signal_by_prediction.get(prediction_id, {})
    row_required_max_loss = _finite(
        row.get("adaptive_loss_probability_threshold_used")
    )
    if row_required_max_loss is not None:
        required_max_loss = row_required_max_loss
    required_profit = None if required_max_loss is None else 1.0 - required_max_loss
    evidence_age = _evidence_age_seconds(row, signal)
    model_loss = _finite(row.get("pre_trade_loss_probability"))
    return {
        "prediction_id": prediction_id or None,
        "intent_id": row.get("intent_id"),
        "symbol": row.get("symbol"),
        "timeframe": row.get("timeframe"),
        "side": row.get("side"),
        "blocker": row.get("preemptive_action"),
        "block_reasons": list(row.get("preemptive_block_reasons") or []),
        "model_loss_probability": model_loss,
        "model_profit_probability": None if model_loss is None else 1.0 - model_loss,
        "required_max_loss_probability": required_max_loss,
        "required_min_profit_probability": required_profit,
        "microstructure_action": row.get("microstructure_action")
        or signal.get(
            "ordinary_paper_effective_microstructure_action"
        )
        or signal.get("microstructure_action")
        or _mapping(
            _mapping(signal.get("microstructure_trust_evidence")).get(
                "source_payload"
            )
        ).get("microstructure_action"),
        "microstructure_trust_score": row.get("microstructure_trust_score"),
        "microstructure_trust_state": row.get("microstructure_trust_state"),
        "evidence_age_seconds": evidence_age,
        "expected_edge_after_cost_bps": _finite(
            row.get("expected_edge_after_cost_bps")
        ),
        "exit_feasibility_score": _finite(row.get("exit_feasibility_score")),
        "confidence_overstatement_risk": _finite(
            row.get("confidence_overstatement_risk")
        ),
        "advanced_indicator_block_reasons": list(
            row.get("advanced_indicator_block_reasons") or []
        ),
        "advanced_indicator_block": row.get("advanced_indicator_block"),
        "advanced_indicator_shadow": row.get("advanced_indicator_shadow"),
        "matched_quarantined_bucket_keys": list(
            row.get("matched_quarantined_bucket_keys") or []
        ),
        "atr_stop_cluster_active": row.get("atr_stop_cluster_active"),
        "cohort_breaker_state": row.get("paper_cohort_breaker_state"),
        "cohort_breaker_new_entries_allowed": row.get(
            "paper_cohort_breaker_new_entries_allowed"
        ),
        "cohort_preemptive_controls_scoped": row.get(
            "paper_cohort_preemptive_controls_scoped"
        ),
        "guardian_state": row.get("continuous_edge_guardian_status"),
        "guardian_new_entries_allowed": row.get("guardian_new_entries_allowed"),
    }


def capture_cycle(client: Any, *, observed_at: datetime | None = None) -> dict[str, Any]:
    observed_at = observed_at or _utc_now()
    cohort = _mapping(_json_value(client, COHORT_KEY, {}))
    generation = int(cohort.get("checkpoint_generation") or 0)
    cohort_id = str(cohort.get("cohort_id") or "")
    checkpoint_id = str(cohort.get("checkpoint_id") or "")
    if generation <= 0 or not cohort_id or not checkpoint_id:
        raise RuntimeError("ACTIVE_ECONOMIC_COHORT_MISSING_OR_INVALID")

    prediction = _mapping(_json_value(client, PREDICTION_STATUS_KEY, {}))
    matrix = _mapping(_json_value(client, MATRIX_KEY, {}))
    paper = _mapping(_json_value(client, PAPER_STATUS_KEY, {}))
    account = _mapping(_json_value(client, ACCOUNT_STATUS_KEY, {}))
    fills = _rows(_json_value(client, ACCEPTED_FILLS_KEY, []))
    open_positions = _rows(_json_value(client, OPEN_POSITIONS_KEY, []))
    closes = _rows(_json_value(client, CLOSED_TRADES_KEY, []))
    matrix_rows = _rows(matrix.get("rows"))

    cycle_time = str(matrix.get("generated_utc") or "")
    if _parse_time(cycle_time) is None:
        raise RuntimeError("COMPLETED_PAPER_MATRIX_TIME_MISSING_OR_INVALID")

    generation_rows = [
        row
        for row in matrix_rows
        if _matches_generation(row, generation=generation, cohort_id=cohort_id)
    ]
    admitted = [row for row in generation_rows if row.get("preemptive_allowed") is True]
    generation_fills = [
        row
        for row in fills
        if _matches_generation(row, generation=generation, cohort_id=cohort_id)
        and _is_natural(row)
    ]
    generation_open = [
        row
        for row in open_positions
        if _matches_generation(row, generation=generation, cohort_id=cohort_id)
        and _is_natural(row)
    ]
    generation_closes = [
        row
        for row in closes
        if _matches_generation(row, generation=generation, cohort_id=cohort_id)
        and _is_natural(row)
    ]
    signal_by_prediction: dict[str, dict[str, Any]] = {}
    for row in generation_rows:
        prediction_id = str(row.get("prediction_id") or "")
        symbol = str(row.get("symbol") or "").upper()
        timeframe = str(row.get("timeframe") or "")
        if not prediction_id or not symbol or not timeframe:
            continue
        signal = _mapping(
            _json_value(client, f"{PAPER_SIGNALS_KEY}:{symbol}:{timeframe}", {})
        )
        signal_prediction_id = str(
            signal.get("prediction_id") or signal.get("source_prediction_id") or ""
        )
        if signal_prediction_id == prediction_id:
            signal_by_prediction[prediction_id] = signal
    required_max_loss = _adaptive_loss_probability_threshold(client)

    reason_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    for row in generation_rows:
        action_counts[str(row.get("preemptive_action") or "UNSPECIFIED")] += 1
        for reason in row.get("preemptive_block_reasons") or []:
            reason_counts[str(reason)] += 1

    prediction_generation = int(prediction.get("registry_generation") or 0)
    generation_predictions = (
        int(prediction.get("records_published") or 0)
        if prediction_generation == generation
        else 0
    )
    generation_directional = (
        int(prediction.get("directional_records") or 0)
        if prediction_generation == generation
        else 0
    )
    attributions = [
        _candidate_attribution(
            client,
            row,
            signal_by_prediction=signal_by_prediction,
            required_max_loss=required_max_loss,
        )
        for row in generation_rows
        if row.get("preemptive_allowed") is not True
    ]

    return {
        "schema_version": "generation_natural_acceptance_cycle_v1",
        "observed_utc": _iso(observed_at),
        "cycle_generated_utc": cycle_time,
        "checkpoint_generation": generation,
        "checkpoint_id": checkpoint_id,
        "cohort_id": cohort_id,
        "generation_predictions": generation_predictions,
        "generation_directional_predictions": generation_directional,
        "candidates_evaluated": len(generation_rows),
        "all_generation_candidates_evaluated": int(matrix.get("candidate_count") or 0),
        "candidates_admitted": len(admitted),
        "admission_rate": (
            len(admitted) / len(generation_rows) if generation_rows else 0.0
        ),
        "rejections_by_primary_action": dict(sorted(action_counts.items())),
        "rejections_by_reason": dict(sorted(reason_counts.items())),
        "paper_intents_created": sum(
            1 for row in generation_rows if row.get("intent_id") not in (None, "")
        ),
        "paper_fills_created": len(generation_fills),
        "generation_open_positions": len(generation_open),
        "generation_natural_closes": len(generation_closes),
        "reservation_leak_count": _reservation_leak_count(
            account=account, open_positions=open_positions
        ),
        "duplicate_fill_count": _duplicate_count(
            generation_fills, ("fill_id", "paper_fill_id", "row_id")
        ),
        "duplicate_close_count": _duplicate_count(
            generation_closes, ("close_id", "closed_trade_id", "row_id")
        ),
        "paper_cycle_state": paper.get("cycle_state"),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "candidate_attribution": attributions,
    }


def _load_archive(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(row, Mapping) and row.get("cycle_generated_utc"):
            rows.append(dict(row))
    by_cycle = {str(row["cycle_generated_utc"]): row for row in rows}
    return [by_cycle[key] for key in sorted(by_cycle)]


def _append_cycle(path: Path, cycle: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(cycle, sort_keys=True, separators=(",", ":")))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _restart_position_id(row: Mapping[str, Any]) -> str:
    return _identity(
        row,
        (
            "position_id",
            "paper_position_id",
            "fill_id",
            "paper_fill_id",
            "intent_id",
        ),
    )


def _captured_restart_position_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    identities: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except (TypeError, ValueError):
            continue
        if not isinstance(row, Mapping):
            continue
        for position in row.get("open_positions") or []:
            if isinstance(position, Mapping):
                identity = _restart_position_id(position)
                if identity:
                    identities.add(identity)
    return identities


def capture_restart_pending_if_needed(
    client: Any,
    *,
    archive_path: Path,
    status_ttl_seconds: int = DEFAULT_STATUS_TTL_SECONDS,
) -> dict[str, Any] | None:
    """Durably snapshot the first sight of each natural governed open position."""
    cohort = _mapping(_json_value(client, COHORT_KEY, {}))
    generation = int(cohort.get("checkpoint_generation") or 0)
    cohort_id = str(cohort.get("cohort_id") or "")
    checkpoint_id = str(cohort.get("checkpoint_id") or "")
    if generation <= 0 or not cohort_id or not checkpoint_id:
        return None
    open_positions = [
        row
        for row in _rows(_json_value(client, OPEN_POSITIONS_KEY, []))
        if _matches_generation(row, generation=generation, cohort_id=cohort_id)
        and _is_natural(row)
    ]
    if not open_positions:
        return None
    captured = _captured_restart_position_ids(archive_path)
    new_positions = [
        row
        for row in open_positions
        if _restart_position_id(row) and _restart_position_id(row) not in captured
    ]
    if not new_positions:
        return None
    fills = [
        row
        for row in _rows(_json_value(client, ACCEPTED_FILLS_KEY, []))
        if _matches_generation(row, generation=generation, cohort_id=cohort_id)
        and _is_natural(row)
    ]
    event = {
        "schema_version": RESTART_CAPTURE_SCHEMA_VERSION,
        "captured_utc": _iso(_utc_now()),
        "status": "PENDING_CANONICAL_SERVING_AND_PAPER_LOOP_RESTART",
        "checkpoint_generation": generation,
        "checkpoint_id": checkpoint_id,
        "cohort_id": cohort_id,
        "position_ids": [_restart_position_id(row) for row in new_positions],
        "open_positions": new_positions,
        "generation_fills": fills,
        "accounting_snapshot": _mapping(
            _json_value(client, ACCOUNT_STATUS_KEY, {})
        ),
        "restart_reconstruction_match": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    _append_cycle(archive_path, event)
    client.set(
        RESTART_PENDING_KEY,
        json.dumps(event, sort_keys=True, separators=(",", ":")),
        ex=status_ttl_seconds,
    )
    return event


def build_status(
    cycles: list[dict[str, Any]],
    *,
    minimum_cycles: int,
    minimum_observation_seconds: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or _utc_now()
    if not cycles:
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_utc": _iso(now),
            "classification": "OBSERVING_NO_COMPLETED_CYCLE",
            "completed_cycles": 0,
            "minimum_completed_cycles": minimum_cycles,
            "minimum_observation_seconds": minimum_observation_seconds,
            "market_session_definition": MARKET_SESSION_DEFINITION,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }

    first = _parse_time(cycles[0].get("observed_utc")) or now
    elapsed = max(0.0, (now - first).total_seconds())
    admitted_total = sum(int(row.get("candidates_admitted") or 0) for row in cycles)
    evaluated_total = sum(int(row.get("candidates_evaluated") or 0) for row in cycles)
    prediction_total = sum(int(row.get("generation_predictions") or 0) for row in cycles)
    directional_total = sum(
        int(row.get("generation_directional_predictions") or 0) for row in cycles
    )
    reason_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    symbols: Counter[str] = Counter()
    timeframes: Counter[str] = Counter()
    blocker_rows: dict[str, list[dict[str, Any]]] = {}
    for cycle in cycles:
        reason_counts.update(cycle.get("rejections_by_reason") or {})
        action_counts.update(cycle.get("rejections_by_primary_action") or {})
        for row in cycle.get("candidate_attribution") or []:
            blocker = str(row.get("blocker") or "UNSPECIFIED")
            blocker_rows.setdefault(blocker, []).append(row)
            if row.get("symbol"):
                symbols[str(row["symbol"])] += 1
            if row.get("timeframe"):
                timeframes[str(row["timeframe"])] += 1

    blocker_attribution: dict[str, dict[str, Any]] = {}
    for blocker, rows in sorted(blocker_rows.items()):
        model_loss = [
            value
            for value in (_finite(row.get("model_loss_probability")) for row in rows)
            if value is not None
        ]
        required_loss = [
            value
            for value in (
                _finite(row.get("required_max_loss_probability")) for row in rows
            )
            if value is not None
        ]
        evidence_ages = [
            value
            for value in (_finite(row.get("evidence_age_seconds")) for row in rows)
            if value is not None
        ]
        blocker_attribution[blocker] = {
            "count": len(rows),
            "percentage_of_evaluated": (
                100.0 * len(rows) / evaluated_total if evaluated_total else 0.0
            ),
            "symbols": dict(
                sorted(
                    Counter(
                        str(row["symbol"])
                        for row in rows
                        if row.get("symbol") not in (None, "")
                    ).items()
                )
            ),
            "timeframes": dict(
                sorted(
                    Counter(
                        str(row["timeframe"])
                        for row in rows
                        if row.get("timeframe") not in (None, "")
                    ).items()
                )
            ),
            "model_loss_probability": {
                "minimum": min(model_loss) if model_loss else None,
                "median": median(model_loss) if model_loss else None,
                "maximum": max(model_loss) if model_loss else None,
            },
            "required_max_loss_probability": {
                "minimum": min(required_loss) if required_loss else None,
                "median": median(required_loss) if required_loss else None,
                "maximum": max(required_loss) if required_loss else None,
            },
            "microstructure_actions": dict(
                sorted(
                    Counter(
                        str(row.get("microstructure_action") or "MISSING")
                        for row in rows
                    ).items()
                )
            ),
            "evidence_age_seconds": {
                "minimum": min(evidence_ages) if evidence_ages else None,
                "median": median(evidence_ages) if evidence_ages else None,
                "maximum": max(evidence_ages) if evidence_ages else None,
            },
            "guardian_states": dict(
                sorted(
                    Counter(
                        str(row.get("guardian_state") or "MISSING") for row in rows
                    ).items()
                )
            ),
        }

    window_complete = (
        len(cycles) >= minimum_cycles and elapsed >= minimum_observation_seconds
    )
    if admitted_total > 0:
        classification = "NATURAL_ADMISSION_OBSERVED"
    elif window_complete:
        classification = "GENERATION_3_ADMISSION_STARVATION"
    else:
        classification = "OBSERVING_BOUNDED_NATURAL_OPPORTUNITY_WINDOW"

    latest = cycles[-1]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": _iso(now),
        "classification": classification,
        "checkpoint_generation": latest.get("checkpoint_generation"),
        "checkpoint_id": latest.get("checkpoint_id"),
        "cohort_id": latest.get("cohort_id"),
        "started_utc": _iso(first),
        "completed_cycles": len(cycles),
        "minimum_completed_cycles": minimum_cycles,
        "observation_elapsed_seconds": elapsed,
        "minimum_observation_seconds": minimum_observation_seconds,
        "market_session_definition": MARKET_SESSION_DEFINITION,
        "cycle_requirement_satisfied": len(cycles) >= minimum_cycles,
        "market_session_requirement_satisfied": elapsed
        >= minimum_observation_seconds,
        "bounded_window_complete": window_complete,
        "generation_predictions": prediction_total,
        "generation_directional_predictions": directional_total,
        "candidates_evaluated": evaluated_total,
        "candidates_admitted": admitted_total,
        "admission_rate": admitted_total / evaluated_total if evaluated_total else 0.0,
        "rejections_by_primary_action": dict(sorted(action_counts.items())),
        "rejections_by_reason": dict(sorted(reason_counts.items())),
        "blocker_attribution": blocker_attribution,
        "symbols": dict(sorted(symbols.items())),
        "timeframes": dict(sorted(timeframes.items())),
        "paper_intents_created": sum(
            int(row.get("paper_intents_created") or 0) for row in cycles
        ),
        "paper_fills_created": int(latest.get("paper_fills_created") or 0),
        "generation_open_positions": int(
            latest.get("generation_open_positions") or 0
        ),
        "generation_natural_closes": int(
            latest.get("generation_natural_closes") or 0
        ),
        "reservation_leak_count": int(latest.get("reservation_leak_count") or 0),
        "duplicate_fill_count": int(latest.get("duplicate_fill_count") or 0),
        "duplicate_close_count": int(latest.get("duplicate_close_count") or 0),
        "latest_cycle": latest,
        "engineering_recovery_complete": True,
        "runtime_acceptance_pending": True,
        "economic_acceptance_pending": True,
        "live_no_go": True,
        "live_gate": "blocked_human_only",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }


def _write_status(path: Path, status: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def observe_once(
    client: Any,
    *,
    archive_path: Path,
    status_path: Path,
    minimum_cycles: int,
    minimum_observation_seconds: int,
    status_ttl_seconds: int = DEFAULT_STATUS_TTL_SECONDS,
    restart_capture_path: Path | None = None,
) -> dict[str, Any]:
    if restart_capture_path is not None:
        capture_restart_pending_if_needed(
            client,
            archive_path=restart_capture_path,
            status_ttl_seconds=status_ttl_seconds,
        )
    cycles = _load_archive(archive_path)
    known = {str(row.get("cycle_generated_utc")) for row in cycles}
    current_matrix = _mapping(_json_value(client, MATRIX_KEY, {}))
    current_cycle_time = str(current_matrix.get("generated_utc") or "")
    if current_cycle_time in known:
        status = build_status(
            cycles,
            minimum_cycles=minimum_cycles,
            minimum_observation_seconds=minimum_observation_seconds,
        )
        _write_status(status_path, status)
        client.set(
            STATUS_KEY,
            json.dumps(status, sort_keys=True, separators=(",", ":")),
            ex=status_ttl_seconds,
        )
        return status

    cycle = capture_cycle(client)
    if any(
        int(row.get("checkpoint_generation") or 0)
        != int(cycle["checkpoint_generation"])
        or str(row.get("cohort_id") or "") != str(cycle["cohort_id"])
        for row in cycles
    ):
        raise RuntimeError("OBSERVATION_GENERATION_OR_COHORT_CHANGED")
    if str(cycle["cycle_generated_utc"]) not in known:
        _append_cycle(archive_path, cycle)
        cycles.append(cycle)
    status = build_status(
        cycles,
        minimum_cycles=minimum_cycles,
        minimum_observation_seconds=minimum_observation_seconds,
    )
    _write_status(status_path, status)
    client.set(
        STATUS_KEY,
        json.dumps(status, sort_keys=True, separators=(",", ":")),
        ex=status_ttl_seconds,
    )
    return status


def _connect_redis() -> Any:
    import redis

    client = redis.Redis(
        host=os.getenv("REDIS_HOST", "127.0.0.1"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=int(os.getenv("REDIS_DB", "0")),
        decode_responses=True,
        socket_timeout=5,
    )
    client.ping()
    return client


def _log_projection(status: Mapping[str, Any]) -> dict[str, Any]:
    """Keep resident stdout bounded; full evidence remains in JSON/Redis."""
    fields = (
        "generated_utc",
        "classification",
        "checkpoint_generation",
        "cohort_id",
        "completed_cycles",
        "observation_elapsed_seconds",
        "candidates_evaluated",
        "candidates_admitted",
        "paper_fills_created",
        "generation_open_positions",
        "generation_natural_closes",
        "live_no_go",
        "places_real_order",
        "exchange_action_taken",
    )
    return {field: status.get(field) for field in fields if field in status}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=10.0)
    parser.add_argument("--minimum-cycles", type=int, default=DEFAULT_MINIMUM_CYCLES)
    parser.add_argument(
        "--minimum-observation-seconds",
        type=int,
        default=DEFAULT_MINIMUM_OBSERVATION_SECONDS,
    )
    parser.add_argument(
        "--restart-capture-path",
        type=Path,
        default=Path(
            ".local_data/permanent_system_recovery/"
            "restart_reconstruction_captures_v1.jsonl"
        ),
    )
    parser.add_argument(
        "--archive-path",
        type=Path,
        default=Path(
            ".local_data/permanent_system_recovery/"
            "generation_acceptance_cycles_v1.jsonl"
        ),
    )
    parser.add_argument(
        "--status-path",
        type=Path,
        default=Path(
            "goal_state/PERMANENT_SYSTEM_RECOVERY/"
            "generation_acceptance_status.json"
        ),
    )
    args = parser.parse_args()
    if args.minimum_cycles <= 0 or args.minimum_observation_seconds <= 0:
        raise SystemExit("minimum cycles and observation seconds must be positive")
    client = _connect_redis()
    while True:
        status = observe_once(
            client,
            archive_path=args.archive_path,
            status_path=args.status_path,
            minimum_cycles=args.minimum_cycles,
            minimum_observation_seconds=args.minimum_observation_seconds,
            restart_capture_path=args.restart_capture_path,
        )
        print(json.dumps(_log_projection(status), sort_keys=True), flush=True)
        if not args.loop:
            return 0
        time.sleep(max(1.0, args.interval_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
