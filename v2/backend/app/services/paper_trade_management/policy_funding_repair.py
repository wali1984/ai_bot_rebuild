"""Repair policy activation and funding accounting on V2 paper rows.

The repair is intentionally paper-only. It never submits, cancels, modifies, or
simulates exchange orders; it only enriches V2 paper ledger rows when the
missing fields can be derived from the row itself or from a safe accepted-fill
lineage match.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from .exits import PAPER_EXIT_POLICY_VERSION
from .outcomes import FUNDING_PNL_ACCOUNTING_FORMULA, FUNDING_PNL_ACCOUNTING_VERSION
from .position_state import ADAPTIVE_CAPITAL_POLICY_VERSION


SCHEMA_VERSION = "v2_paper_policy_activation_funding_repair_v1"
V2_PAPER_LEDGER_KEY = "v2:paper:ledger"
V2_PAPER_CLOSED_TRADES_KEY = "v2:paper:closed_trades"
V2_PAPER_OUTCOME_LABELS_KEY = "v2:paper:outcome_labels"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def safe_load_json(raw: Any) -> Any:
    if raw in (None, ""):
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def rows_from_payload(payload: Any, keys: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    if not keys:
        keys = ("closed_trades", "closed", "closes", "closed_positions", "outcome_labels", "rows")
    for key in keys:
        rows = payload.get(key)
        if isinstance(rows, list):
            return [dict(row) for row in rows if isinstance(row, dict)]
    return []


def coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def parse_time(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        parsed = float(value)
        if not math.isfinite(parsed):
            return None
        if parsed > 10_000_000_000:
            parsed = parsed / 1000.0
        return datetime.fromtimestamp(parsed, tz=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_from_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _allocation(row: dict[str, Any]) -> dict[str, Any]:
    allocation = row.get("adaptive_allocation")
    return allocation if isinstance(allocation, dict) else {}


def _model_inputs(row: dict[str, Any]) -> dict[str, Any]:
    allocation = _allocation(row)
    model_inputs = allocation.get("model_inputs")
    return model_inputs if isinstance(model_inputs, dict) else {}


def _oi_funding(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("oi_funding_context")
    return value if isinstance(value, dict) else {}


def _field_value(row: dict[str, Any], field: str) -> Any:
    allocation = _allocation(row)
    model_inputs = _model_inputs(row)
    oi_funding = _oi_funding(row)
    return first_present(
        row.get(field),
        allocation.get(field),
        model_inputs.get(field),
        oi_funding.get(field),
    )


def _lineage_ids(row: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in (
        "fill_id",
        "ledger_row_id",
        "intent_id",
        "candidate_id",
        "paper_exploration_candidate_id",
        "materialization_queue_id",
        "queue_id",
        "signal_id",
        "source_signal_id",
        "prediction_id",
        "source_prediction_id",
        "entry_signal_id",
        "entry_prediction_id",
    ):
        value = row.get(key)
        if value not in (None, ""):
            ids.add(str(value))
    for value in row.get("source_fill_ids") or []:
        if value not in (None, ""):
            ids.add(str(value))
    return ids


def _row_identity(row: dict[str, Any]) -> str:
    for key in (
        "close_id",
        "outcome_label_id",
        "trainer_feedback_id",
        "fill_id",
        "ledger_row_id",
    ):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return (
        f"{row.get('symbol')}|{row.get('timeframe')}|{row.get('side') or row.get('action')}|"
        f"{row.get('entry_price')}|{row.get('exit_price')}|"
        f"{row.get('exit_time') or row.get('exit_price_utc')}"
    )


def _row_tokens(row: dict[str, Any]) -> set[str]:
    tokens = {
        str(value)
        for value in (
            row.get("close_id"),
            row.get("outcome_label_id"),
            row.get("trainer_feedback_id"),
        )
        if value not in (None, "")
    }
    tokens.add(_row_identity(row))
    return tokens


def _deep_merge_context(primary: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    merged = dict(context)
    for key, value in primary.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_context(value, merged[key])
            continue
        if value not in (None, "") or key not in merged:
            merged[key] = value
    return merged


def _context_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        for token in _row_tokens(row):
            index.setdefault(token, row)
    return index


def _rows_with_ledger_context(
    primary_rows: list[dict[str, Any]],
    *,
    ledger_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not primary_rows:
        return [dict(row) for row in ledger_rows]
    index = _context_index(ledger_rows)
    enriched: list[dict[str, Any]] = []
    for row in primary_rows:
        context = None
        for token in _row_tokens(row):
            context = index.get(token)
            if context is not None:
                break
        enriched.append(_deep_merge_context(row, context or {}))
    return enriched


def _policy_version(row: dict[str, Any]) -> str | None:
    value = first_present(
        row.get("adaptive_capital_policy_version"),
        _allocation(row).get("adaptive_capital_policy_version"),
    )
    return str(value) if value not in (None, "") else None


def _is_policy_row(row: dict[str, Any]) -> bool:
    return _policy_version(row) == ADAPTIVE_CAPITAL_POLICY_VERSION


def _safe_paper_row(row: dict[str, Any], *, require_paper_only_true: bool) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if require_paper_only_true and row.get("paper_only") is not True:
        reasons.append("PAPER_ONLY_NOT_TRUE")
    elif row.get("paper_only") is False:
        reasons.append("PAPER_ONLY_FALSE")
    for field in (
        "places_real_order",
        "test_order",
        "test_orders",
        "exchange_order_allowed",
        "routes_to_live",
        "order_submitted",
        "test_order_submitted",
        "leverage_mutated",
        "margin_mutated",
        "leverage_mutation",
        "margin_mode_mutation",
        "leverage_changed",
        "margin_mode_changed",
        "withdrawals",
        "transfers",
        "trainer_bridge_unmasked",
        "writes_legacy_redis",
    ):
        if _truthy(row.get(field)):
            reasons.append(f"UNSAFE_{field.upper()}")
    return not reasons, reasons


PAPER_RISK_CONTROLLER_EXPLORATION_TIER = "PAPER_RISK_CONTROLLER_EXPLORATION"

_EXPLORATION_LINEAGE_REPAIR_FIELDS = (
    "tier",
    "exploration_tier",
    "paper_exploration_tier",
    "paper_opportunity_tier",
    "paper_opportunity_tier_reason",
    "policy_tier",
    "source_tier",
    "preemptive_decision_id",
    "runtime_revalidated_preemptive_decision_id",
    "risk_decision_id",
    "orchestrator_decision_id",
    "allocator_decision_id",
    "allocator_decision",
    "materialization_queue_id",
    "materialization_queue_accepted_at",
    "materialization_queue_expires_at",
    "feature_vector_hash",
    "provider_hashes",
    "confidence_executable_trade",
    "dynamic_exploration_floor",
    "dynamic_exploration_floor_formula",
    "exploration_floor_inputs",
    "floor_inputs",
    "paper_risk_controller_exploration_above_floor",
    "paper_risk_controller_exploration_eligible",
    "bootstrap_exploration",
    "bootstrap_overridden_blockers",
)


def _exploration_tier(row: dict[str, Any]) -> str | None:
    for field in (
        "tier",
        "exploration_tier",
        "paper_exploration_tier",
        "paper_opportunity_tier",
        "policy_tier",
        "source_tier",
    ):
        value = row.get(field)
        if value not in (None, "") and str(value).strip().upper() == PAPER_RISK_CONTROLLER_EXPLORATION_TIER:
            return PAPER_RISK_CONTROLLER_EXPLORATION_TIER
    return None


def _stable_value_key(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    except TypeError:
        return str(value)


def _unique_match_value(matches: list[dict[str, Any]], field: str) -> Any:
    values: list[Any] = [
        match.get(field)
        for match in matches
        if match.get(field) not in (None, "", {}, [])
    ]
    if not values:
        return None
    unique = {_stable_value_key(value): value for value in values}
    if len(unique) != 1:
        return None
    return next(iter(unique.values()))


def _repair_exploration_lineage_fields(
    repaired: dict[str, Any],
    *,
    matches: list[dict[str, Any]],
    generated_at: str,
) -> list[str]:
    tier = _exploration_tier(repaired)
    if tier is None:
        for match in matches:
            tier = _exploration_tier(match)
            if tier is not None:
                break
    if tier != PAPER_RISK_CONTROLLER_EXPLORATION_TIER:
        return []

    changed_fields: list[str] = []
    for field in _EXPLORATION_LINEAGE_REPAIR_FIELDS:
        if repaired.get(field) not in (None, "", {}, []):
            continue
        value = _unique_match_value(matches, field)
        if value in (None, "", {}, []):
            continue
        repaired[field] = value
        changed_fields.append(field)

    for field in ("tier", "exploration_tier", "paper_exploration_tier", "paper_opportunity_tier"):
        if repaired.get(field) in (None, ""):
            repaired[field] = PAPER_RISK_CONTROLLER_EXPLORATION_TIER
            changed_fields.append(field)
    for field, value in (
        ("paper_only", True),
        ("routes_to_live", False),
        ("places_real_order", False),
        ("counts_as_A_plus", False),
        ("counts_as_final_A_plus", False),
        ("counts_as_final_a_plus", False),
        ("counts_as_live_ready", False),
        ("order_submitted", False),
        ("test_order_submitted", False),
        ("leverage_mutated", False),
        ("margin_mutated", False),
    ):
        if repaired.get(field) is None:
            repaired[field] = value
            changed_fields.append(field)

    if changed_fields:
        repaired["paper_exploration_lineage_repair_status"] = (
            "REPAIRED_FROM_SAFE_ACCEPTED_FILL_CONTEXT"
        )
        repaired["paper_exploration_lineage_repaired_at"] = generated_at
        repaired["paper_exploration_lineage_repaired_fields"] = sorted(set(changed_fields))
    return changed_fields


def _event_time(row: dict[str, Any]) -> datetime | None:
    return parse_time(first_present(
        row.get("exit_time"),
        row.get("closed_utc"),
        row.get("exit_price_utc"),
        row.get("generated_utc"),
        row.get("event_time"),
    ))


def _accepted_time(row: dict[str, Any]) -> datetime | None:
    return parse_time(first_present(
        row.get("fill_price_utc"),
        row.get("entry_price_utc"),
        row.get("original_fill_utc"),
        row.get("generated_utc"),
        row.get("fill_time_est"),
        row.get("policy_activated_at"),
        _allocation(row).get("policy_activated_at"),
    ))


def _entry_time_from_row(row: dict[str, Any]) -> tuple[str | None, str | None]:
    direct = parse_time(first_present(
        row.get("opened_at"),
        row.get("opened_utc"),
        row.get("opened_est"),
        row.get("entry_time"),
        row.get("entry_time_utc"),
        row.get("entry_price_utc"),
        row.get("fill_price_utc"),
        row.get("original_fill_utc"),
        row.get("policy_activated_at"),
        _allocation(row).get("policy_activated_at"),
    ))
    if direct is not None:
        return iso_from_dt(direct), "ROW_ENTRY_TIME"
    exit_time = _event_time(row)
    hold_time_seconds = coerce_float(row.get("hold_time_seconds"))
    if exit_time is None or hold_time_seconds is None or hold_time_seconds < 0.0:
        return None, None
    return (
        iso_from_dt(exit_time - timedelta(seconds=float(hold_time_seconds))),
        "EXIT_TIME_MINUS_HOLD_TIME_SECONDS",
    )


def _build_accepted_index(accepted_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    accepted_index: dict[str, list[dict[str, Any]]] = {}
    for accepted in accepted_rows:
        safe, _reasons = _safe_paper_row(accepted, require_paper_only_true=True)
        if not safe:
            continue
        for lineage_id in _lineage_ids(accepted):
            accepted_index.setdefault(lineage_id, []).append(accepted)
    return accepted_index


def _safe_matches(
    row: dict[str, Any],
    accepted_index: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[str]]:
    row_safe, row_reasons = _safe_paper_row(row, require_paper_only_true=False)
    if not row_safe:
        return [], row_reasons
    close_time = _event_time(row)
    matched_by_id: dict[int, dict[str, Any]] = {}
    for lineage_id in _lineage_ids(row):
        for accepted in accepted_index.get(lineage_id, []):
            matched_by_id[id(accepted)] = accepted
    matches: list[dict[str, Any]] = []
    reasons: list[str] = []
    for accepted in matched_by_id.values():
        accepted_time = _accepted_time(accepted)
        if close_time is None:
            reasons.append("MISSING_CLOSE_EVENT_TIME")
            continue
        if accepted_time is None:
            reasons.append("MISSING_ACCEPTED_FILL_TIME")
            continue
        if accepted_time > close_time:
            reasons.append("ACCEPTED_FILL_AFTER_CLOSE")
            continue
        matches.append(accepted)
    return matches, sorted(set(reasons))


def _first_numeric_from_rows(rows: list[dict[str, Any]], *fields: str) -> tuple[float | None, str | None]:
    candidates: list[tuple[float, str]] = []
    for row in rows:
        for field in fields:
            parsed = coerce_float(_field_value(row, field))
            if parsed is not None:
                candidates.append((parsed, field))
                break
    if not candidates:
        return None, None
    unique = {round(value, 12) for value, _field in candidates}
    if len(unique) > 1:
        return None, "AMBIGUOUS_NUMERIC_VALUE"
    value, field = candidates[0]
    return value, field


def _funding_rate_and_bps(
    row: dict[str, Any],
    matches: list[dict[str, Any]],
) -> tuple[float | None, float | None, str | None, str | None]:
    row_rate, row_rate_source = _first_numeric_from_rows(
        [row],
        "funding_rate",
        "last_funding_rate",
        "next_funding_rate",
        "expected_funding_rate",
        "actual_funding_rate",
    )
    row_bps, row_bps_source = _first_numeric_from_rows(
        [row],
        "actual_funding_bps",
        "expected_funding_bps",
        "funding_bps",
        "funding_rate_bps",
    )
    if row_rate is not None:
        return row_rate, row_rate * 10000.0, "FUNDING_RATE", row_rate_source
    if row_bps is not None:
        return row_bps / 10000.0, row_bps, "EXPECTED_FUNDING_BPS", row_bps_source
    rate, rate_source = _first_numeric_from_rows(
        matches,
        "funding_rate",
        "last_funding_rate",
        "next_funding_rate",
        "expected_funding_rate",
        "actual_funding_rate",
    )
    bps, bps_source = _first_numeric_from_rows(
        matches,
        "actual_funding_bps",
        "expected_funding_bps",
        "funding_bps",
        "funding_rate_bps",
    )
    if rate_source == "AMBIGUOUS_NUMERIC_VALUE" or bps_source == "AMBIGUOUS_NUMERIC_VALUE":
        return None, None, None, "AMBIGUOUS_FUNDING_RATE_OR_BPS"
    if rate is not None:
        return rate, rate * 10000.0, "FUNDING_RATE", rate_source
    if bps is not None:
        return bps / 10000.0, bps, "EXPECTED_FUNDING_BPS", bps_source
    return None, None, None, None


def _notional(row: dict[str, Any]) -> float | None:
    explicit = coerce_float(first_present(
        _field_value(row, "funding_notional_usd"),
        row.get("closed_notional_usd"),
        row.get("gross_notional_usd"),
        row.get("notional"),
        row.get("notional_usdt"),
    ))
    if explicit is not None:
        return abs(explicit)
    quantity = coerce_float(first_present(
        row.get("closed_quantity"),
        row.get("quantity"),
        row.get("target_quantity"),
        _field_value(row, "quantity"),
    ))
    entry_price = coerce_float(first_present(row.get("entry_price"), _field_value(row, "entry_price")))
    if quantity is None or entry_price is None:
        return None
    return abs(quantity * entry_price)


def _side(row: dict[str, Any]) -> str | None:
    side = str(first_present(row.get("side"), row.get("action"), row.get("selected_action"), "")).lower()
    if side in {"buy", "long"}:
        return "long"
    if side in {"sell", "short"}:
        return "short"
    return None


def _policy_activated_at(
    row: dict[str, Any],
    matches: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    existing = first_present(row.get("policy_activated_at"), _allocation(row).get("policy_activated_at"))
    if existing not in (None, ""):
        parsed = parse_time(existing)
        return iso_from_dt(parsed) if parsed is not None else str(existing), "EXISTING_POLICY_ACTIVATED_AT"
    accepted_times = sorted(
        dt for dt in (_accepted_time(match) for match in matches) if dt is not None
    )
    if accepted_times:
        return iso_from_dt(accepted_times[0]), "EARLIEST_SAFE_ACCEPTED_FILL_TIME"
    return _entry_time_from_row(row)


def _repair_one_row(
    row: dict[str, Any],
    *,
    accepted_index: dict[str, list[dict[str, Any]]],
    generated_at: str,
) -> tuple[dict[str, Any], str, list[str]]:
    repaired = dict(row)
    matches, match_reject_reasons = _safe_matches(row, accepted_index)
    lineage_changed_fields = _repair_exploration_lineage_fields(
        repaired,
        matches=matches,
        generated_at=generated_at,
    )
    matched_policy = [match for match in matches if _is_policy_row(match)]
    is_policy = _is_policy_row(row)
    if not is_policy and row.get("paper_exit_policy_version") == PAPER_EXIT_POLICY_VERSION and matched_policy:
        repaired["adaptive_capital_policy_version"] = ADAPTIVE_CAPITAL_POLICY_VERSION
        repaired["adaptive_capital_policy_repaired_from_accepted_fill"] = True
        repaired["accepted_fill_policy_repair_ids"] = sorted({
            lineage_id for match in matched_policy for lineage_id in _lineage_ids(match)
            if lineage_id in _lineage_ids(row)
        })
        matches = matched_policy
        is_policy = True
    if not is_policy:
        if lineage_changed_fields:
            return repaired, "lineage_repaired", match_reject_reasons
        return repaired, "not_policy_scope", match_reject_reasons

    changed_fields: list[str] = list(lineage_changed_fields)
    missing_reasons: list[str] = []
    policy_activated_at, policy_source = _policy_activated_at(repaired, matches)
    if policy_activated_at:
        if repaired.get("policy_activated_at") in (None, ""):
            repaired["policy_activated_at"] = policy_activated_at
            repaired["policy_activated_at_source"] = f"PAPER_POLICY_FUNDING_REPAIR:{policy_source}"
            changed_fields.append("policy_activated_at")
    else:
        missing_reasons.append("MISSING_POLICY_ACTIVATED_AT_EVIDENCE")

    existing_funding_pnl = coerce_float(first_present(repaired.get("funding_pnl_usd"), repaired.get("funding_pnl")))
    existing_funding_source = first_present(repaired.get("funding_pnl_source"), repaired.get("funding_source"))
    needs_funding = existing_funding_pnl is None or existing_funding_source in (None, "")
    if not needs_funding:
        if lineage_changed_fields and set(changed_fields) == set(lineage_changed_fields):
            return repaired, "lineage_repaired", missing_reasons
        if changed_fields:
            repaired["paper_policy_funding_repair_status"] = "REPAIRED_POLICY_ACTIVATION_ONLY"
            repaired["paper_policy_funding_repaired_at"] = generated_at
            repaired["paper_policy_funding_repaired_fields"] = changed_fields
            return repaired, "repaired", missing_reasons
        return repaired, "already_accounted", missing_reasons

    rate, bps, funding_source, funding_input_source = _funding_rate_and_bps(repaired, matches)
    if funding_input_source == "AMBIGUOUS_FUNDING_RATE_OR_BPS":
        missing_reasons.append("AMBIGUOUS_FUNDING_RATE_OR_BPS")
    if rate is None or bps is None or funding_source is None:
        missing_reasons.append("MISSING_FUNDING_RATE_OR_BPS")
    notional = _notional(repaired)
    if notional is None or notional <= 0.0:
        missing_reasons.append("MISSING_FUNDING_NOTIONAL")
    hold_time = coerce_float(repaired.get("hold_time_seconds"))
    if hold_time is None:
        entry_time = parse_time(policy_activated_at)
        exit_time = _event_time(repaired)
        if entry_time is not None and exit_time is not None and exit_time >= entry_time:
            hold_time = (exit_time - entry_time).total_seconds()
    if hold_time is None or hold_time < 0.0:
        missing_reasons.append("MISSING_HOLD_TIME")
    interval_seconds = coerce_float(first_present(
        _field_value(repaired, "funding_interval_seconds"),
        *(_field_value(match, "funding_interval_seconds") for match in matches),
        28800.0,
    ))
    if interval_seconds is None or interval_seconds <= 0.0:
        missing_reasons.append("INVALID_FUNDING_INTERVAL")
    side = _side(repaired)
    if side not in {"long", "short"}:
        missing_reasons.append("MISSING_DIRECTIONAL_SIDE")
    if missing_reasons:
        if changed_fields:
            repaired["paper_policy_funding_repair_status"] = "PARTIAL_POLICY_ACTIVATION_REPAIRED_FUNDING_UNREPAIRABLE"
            repaired["paper_policy_funding_repaired_at"] = generated_at
            repaired["paper_policy_funding_repaired_fields"] = changed_fields
            repaired["paper_policy_funding_unrepairable_reasons"] = sorted(set(missing_reasons))
            return repaired, "partially_repaired", sorted(set(missing_reasons))
        return repaired, "unrepairable", sorted(set(missing_reasons))

    side_sign = -1.0 if side == "long" else 1.0
    interval_count = float(hold_time or 0.0) / float(interval_seconds or 28800.0)
    funding_pnl = float(notional or 0.0) * float(rate) * interval_count * side_sign
    old_realized = coerce_float(first_present(repaired.get("realized_pnl_usd"), repaired.get("realized_pnl_usdt"), repaired.get("realized_pnl")))
    if old_realized is not None:
        new_realized = old_realized + funding_pnl
        repaired["realized_pnl_usd"] = new_realized
        repaired["realized_pnl_usdt"] = new_realized
        repaired["realized_pnl"] = new_realized
        repaired["winner"] = new_realized > 0.0
        repaired["paper_policy_funding_repair_realized_pnl_delta_usd"] = funding_pnl
    repaired["funding_pnl_accounting_version"] = FUNDING_PNL_ACCOUNTING_VERSION
    repaired["funding_pnl_accounting_status"] = "READY_FUNDING_PNL_ACCRUED"
    repaired["funding_pnl_usd"] = funding_pnl
    repaired["funding_rate"] = rate
    repaired["funding_bps"] = bps
    if funding_input_source in {"expected_funding_bps", "funding_bps", "funding_rate_bps", "actual_funding_bps"}:
        repaired.setdefault(funding_input_source, bps)
    else:
        repaired.setdefault("expected_funding_bps", bps)
    repaired["funding_interval_seconds"] = float(interval_seconds or 28800.0)
    repaired["funding_accrual_intervals"] = interval_count
    repaired["funding_notional_usd"] = float(notional or 0.0)
    repaired["funding_pnl_formula"] = FUNDING_PNL_ACCOUNTING_FORMULA
    repaired["funding_pnl_side_sign"] = side_sign
    repaired["funding_pnl_source"] = funding_source
    repaired["paper_policy_funding_repair_status"] = "REPAIRED_POLICY_ACTIVATION_AND_FUNDING"
    repaired["paper_policy_funding_repaired_at"] = generated_at
    changed_fields.extend([
        "funding_pnl_accounting_version",
        "funding_pnl_accounting_status",
        "funding_pnl_usd",
        "funding_pnl_source",
    ])
    repaired["paper_policy_funding_repaired_fields"] = sorted(set(changed_fields))
    return repaired, "repaired", missing_reasons


def repair_policy_funding_rows(
    rows: list[dict[str, Any]],
    *,
    accepted_rows: list[dict[str, Any]],
    generated_at: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, dict[str, Any]]]:
    accepted_index = _build_accepted_index(accepted_rows)
    repaired_rows: list[dict[str, Any]] = []
    repaired_by_token: dict[str, dict[str, Any]] = {}
    status_counts: dict[str, int] = {}
    missing_reason_counts: dict[str, int] = {}
    examples: list[dict[str, Any]] = []
    policy_rows_seen = 0
    for row in rows:
        repaired, status, reasons = _repair_one_row(
            row,
            accepted_index=accepted_index,
            generated_at=generated_at,
        )
        if status != "not_policy_scope":
            policy_rows_seen += 1
        status_counts[status] = status_counts.get(status, 0) + 1
        for reason in reasons:
            missing_reason_counts[reason] = missing_reason_counts.get(reason, 0) + 1
        if status in {"repaired", "partially_repaired", "lineage_repaired"}:
            for token in _row_tokens(row):
                repaired_by_token[token] = repaired
        if status in {"repaired", "partially_repaired", "lineage_repaired", "unrepairable"} and len(examples) < 20:
            examples.append({
                "symbol": repaired.get("symbol"),
                "timeframe": repaired.get("timeframe"),
                "side": first_present(repaired.get("side"), repaired.get("action")),
                "close_id": repaired.get("close_id"),
                "outcome_label_id": repaired.get("outcome_label_id"),
                "status": status,
                "policy_activated_at": repaired.get("policy_activated_at"),
                "funding_pnl_usd": repaired.get("funding_pnl_usd"),
                "funding_pnl_source": repaired.get("funding_pnl_source"),
                "paper_exploration_lineage_repair_status": repaired.get(
                    "paper_exploration_lineage_repair_status"
                ),
                "missing_reasons": sorted(set(reasons)),
            })
        repaired_rows.append(repaired)
    return repaired_rows, {
        "rows_seen": len(rows),
        "policy_rows_seen": policy_rows_seen,
        "accepted_fill_indexed_lineage_count": len(accepted_index),
        "status_counts": {key: status_counts[key] for key in sorted(status_counts)},
        "missing_reason_counts": {
            key: missing_reason_counts[key] for key in sorted(missing_reason_counts)
        },
        "examples": examples,
    }, repaired_by_token


def _update_matching_rows(
    rows: list[dict[str, Any]],
    repaired_by_token: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    updated: list[dict[str, Any]] = []
    count = 0
    for row in rows:
        repaired = None
        for token in _row_tokens(row):
            repaired = repaired_by_token.get(token)
            if repaired is not None:
                break
        if repaired is None:
            updated.append(dict(row))
            continue
        merged = dict(row)
        for key, value in repaired.items():
            if (
                key.startswith("funding_")
                or key.startswith("paper_policy_funding_")
                or key in {
                    "adaptive_capital_policy_version",
                    "adaptive_capital_policy_repaired_from_accepted_fill",
                    "accepted_fill_policy_repair_ids",
                    "policy_activated_at",
                    "policy_activated_at_source",
                    "expected_funding_bps",
                    "realized_pnl",
                    "realized_pnl_usd",
                    "realized_pnl_usdt",
                    "winner",
                    "tier",
                    "exploration_tier",
                    "paper_exploration_tier",
                    "paper_opportunity_tier",
                    "paper_opportunity_tier_reason",
                    "policy_tier",
                    "source_tier",
                    "preemptive_decision_id",
                    "runtime_revalidated_preemptive_decision_id",
                    "risk_decision_id",
                    "orchestrator_decision_id",
                    "allocator_decision_id",
                    "allocator_decision",
                    "materialization_queue_id",
                    "materialization_queue_accepted_at",
                    "materialization_queue_expires_at",
                    "feature_vector_hash",
                    "provider_hashes",
                    "confidence_executable_trade",
                    "dynamic_exploration_floor",
                    "dynamic_exploration_floor_formula",
                    "exploration_floor_inputs",
                    "floor_inputs",
                    "paper_risk_controller_exploration_above_floor",
                    "paper_risk_controller_exploration_eligible",
                    "bootstrap_exploration",
                    "bootstrap_overridden_blockers",
                    "paper_exploration_lineage_repair_status",
                    "paper_exploration_lineage_repaired_at",
                    "paper_exploration_lineage_repaired_fields",
                    "paper_only",
                    "routes_to_live",
                    "places_real_order",
                    "counts_as_A_plus",
                    "counts_as_final_A_plus",
                    "counts_as_final_a_plus",
                    "counts_as_live_ready",
                    "order_submitted",
                    "test_order_submitted",
                    "leverage_mutated",
                    "margin_mutated",
                }
            ):
                merged[key] = value
        updated.append(merged)
        count += 1
    return updated, count


def build_policy_funding_repair_report(
    redis_client: Any,
    *,
    write: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or utc_iso()
    ledger = safe_load_json(redis_client.get(V2_PAPER_LEDGER_KEY))
    ledger = ledger if isinstance(ledger, dict) else {}
    accepted_rows = rows_from_payload(ledger, keys=("accepted", "accepted_intents"))
    ledger_closed_trades = rows_from_payload(
        ledger,
        keys=("closed_trades", "closes", "closed", "closed_positions"),
    )
    closed_trades = _rows_with_ledger_context(
        rows_from_payload(safe_load_json(redis_client.get(V2_PAPER_CLOSED_TRADES_KEY))),
        ledger_rows=ledger_closed_trades,
    )
    outcome_labels = rows_from_payload(safe_load_json(redis_client.get(V2_PAPER_OUTCOME_LABELS_KEY)))
    if not outcome_labels:
        outcome_labels = rows_from_payload(ledger, keys=("outcome_labels",))

    repaired_closed, closed_report, repaired_by_token = repair_policy_funding_rows(
        closed_trades,
        accepted_rows=accepted_rows,
        generated_at=generated_at,
    )
    updated_outcomes, outcome_updates = _update_matching_rows(outcome_labels, repaired_by_token)
    updated_ledger = dict(ledger)
    ledger_updates: dict[str, int] = {}
    for key in ("closed_trades", "closes", "closed", "closed_positions"):
        if isinstance(ledger.get(key), list):
            updated_rows, count = _update_matching_rows(
                rows_from_payload({key: ledger.get(key)}, keys=(key,)),
                repaired_by_token,
            )
            updated_ledger[key] = updated_rows
            ledger_updates[key] = count
    if isinstance(ledger.get("outcome_labels"), list):
        updated_rows, count = _update_matching_rows(
            rows_from_payload({"outcome_labels": ledger.get("outcome_labels")}, keys=("outcome_labels",)),
            repaired_by_token,
        )
        updated_ledger["outcome_labels"] = updated_rows
        ledger_updates["outcome_labels"] = count

    keys_written: list[str] = []
    if write:
        redis_client.set(V2_PAPER_CLOSED_TRADES_KEY, json.dumps(repaired_closed), ex=1800)
        keys_written.append(V2_PAPER_CLOSED_TRADES_KEY)
        if outcome_labels:
            redis_client.set(V2_PAPER_OUTCOME_LABELS_KEY, json.dumps(updated_outcomes), ex=1800)
            keys_written.append(V2_PAPER_OUTCOME_LABELS_KEY)
        if ledger:
            redis_client.set(V2_PAPER_LEDGER_KEY, json.dumps(updated_ledger), ex=600)
            keys_written.append(V2_PAPER_LEDGER_KEY)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "dry_run": not write,
        "writes_redis": bool(write),
        "writes_exchange_orders": False,
        "places_real_order": False,
        "live_gate": "blocked_human_only",
        "accepted_rows_seen": len(accepted_rows),
        "closed_trade_rows_seen": len(closed_trades),
        "outcome_label_rows_seen": len(outcome_labels),
        "closed_trade_repair": closed_report,
        "outcome_label_rows_updated": outcome_updates,
        "ledger_rows_updated": ledger_updates,
        "keys_written": keys_written,
        "repair_policy": {
            "scope": "V2 paper ledger closed trades and outcome labels only",
            "requires_paper_only_accepted_fill_match_for_unversioned_p0_rows": True,
            "uses_earliest_safe_accepted_fill_time_for_policy_activated_at": True,
            "derives_policy_activated_at_from_exit_time_minus_hold_time_when_entry_time_missing": True,
            "requires_funding_rate_or_bps_evidence_before_persisting_funding_pnl": True,
            "does_not_fabricate_missing_funding_rates": True,
            "no_live_or_exchange_mutation": True,
        },
    }
