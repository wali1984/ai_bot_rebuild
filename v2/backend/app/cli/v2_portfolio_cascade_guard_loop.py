"""Strict paper-only portfolio cascade guard.

The worker consumes one coherent ``v2:paper:ledger`` JSON value per cycle.
It never combines independently timed position/account keys and never emits a
directive from partial, stale, defaulted, or symbol-only evidence.

No live routing, orders, leverage changes, or margin changes are reachable.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from v2.backend.app.services.risk.cross_margin_liquidation import (
    build_portfolio_liquidation_snapshot,
)
from v2.backend.app.services.risk.portfolio_cascade_directive import (
    DIRECTIVE_SCHEMA_VERSION,
    GUARD_SCHEMA_VERSION,
    canonical_sha256,
    finite_number,
    parse_utc,
    seal_directive,
    seal_guard_payload,
)

GUARD_KEY = "v2:paper:portfolio_cascade_guard"
LEDGER_KEY = "v2:paper:ledger"
CASCADE_PREFIX = "v2:microstructure:cascade_context:"
CASCADE_TIMEFRAMES = ("1m", "5m")
CASCADE_CONFIRMED_STATUSES = {
    "EVENT_CONFIRMED",
    "LEVEL_PROXIMITY_CONFIRMED",
    "PROXY_CONFIRMED",
}
CASCADE_NON_TRIGGERING_STATUSES = {
    "INSUFFICIENT_BUT_SHADOW_ONLY",
    "ABSENT_NO_TRADE",
    "STALE_NO_TRADE",
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _redis_client():
    from redis import Redis  # noqa: PLC0415

    return Redis(host="127.0.0.1", port=6379, decode_responses=True)


def _read_json_once(r: Any, key: str) -> tuple[str, Any]:
    """Read exactly once and preserve missing vs malformed vs explicit empty."""

    try:
        raw = r.get(key)
    except Exception:
        return "READ_FAILED", None
    if raw is None:
        return "MISSING", None
    if raw == "":
        return "EMPTY_BYTES", None
    try:
        return "PRESENT", json.loads(raw)
    except (TypeError, ValueError):
        return "INVALID_JSON", None


def _paper_safety_valid(value: Mapping[str, Any], *, mutation_flags: bool) -> bool:
    valid = (
        value.get("paper_only") is True
        and value.get("routes_to_live") is False
        and value.get("places_real_order") is False
    )
    if mutation_flags:
        valid = (
            valid
            and value.get("leverage_mutated") is False
            and value.get("margin_mutated") is False
        )
    return valid


def _strict_ledger_snapshot(r: Any, *, observed_utc: str) -> dict[str, Any]:
    state, payload = _read_json_once(r, LEDGER_KEY)
    reasons: list[str] = []
    if state != "PRESENT":
        reasons.append(f"PAPER_LEDGER_{state}")
    if not isinstance(payload, Mapping):
        reasons.append("PAPER_LEDGER_NOT_A_MAPPING")
        payload = {}
    if payload.get("schema_version") != "paper_ledger_v2":
        reasons.append("PAPER_LEDGER_SCHEMA_VERSION_INVALID")
    if not _paper_safety_valid(payload, mutation_flags=True):
        reasons.append("PAPER_LEDGER_ROUTE_SAFETY_INVALID")
    paper_session_id = payload.get("paper_session_id")
    if not isinstance(paper_session_id, str) or not paper_session_id.strip():
        reasons.append("PAPER_LEDGER_SESSION_ID_MISSING_OR_INVALID")
        paper_session_id = None

    observed_at = parse_utc(observed_utc)
    ledger_generated_at = parse_utc(payload.get("generated_utc"))
    if observed_at is None or ledger_generated_at is None:
        reasons.append("PAPER_LEDGER_CLOCK_INVALID")
    elif ledger_generated_at > observed_at:
        reasons.append("PAPER_LEDGER_GENERATED_IN_FUTURE")

    if "open_positions" not in payload:
        reasons.append("PAPER_LEDGER_OPEN_POSITIONS_KEY_MISSING")
        positions: list[dict[str, Any]] = []
    elif not isinstance(payload.get("open_positions"), list):
        reasons.append("PAPER_LEDGER_OPEN_POSITIONS_NOT_A_LIST")
        positions = []
    else:
        positions = list(payload["open_positions"])
    declared_count = payload.get("open_position_count")
    if type(declared_count) is not int or declared_count != len(positions):
        reasons.append("PAPER_LEDGER_OPEN_POSITION_COUNT_MISMATCH")

    margin = payload.get("paper_account_margin_status")
    if not isinstance(margin, Mapping):
        reasons.append("PAPER_ACCOUNT_MARGIN_STATUS_MISSING_OR_INVALID")
        margin = {}
    if margin.get("schema_version") != "paper_account_margin_v1":
        reasons.append("PAPER_ACCOUNT_MARGIN_SCHEMA_VERSION_INVALID")
    if margin.get("status") != "PASS":
        reasons.append("PAPER_ACCOUNT_MARGIN_STATUS_NOT_PASS")
    if margin.get("accounting_complete") is not True:
        reasons.append("PAPER_ACCOUNT_MARGIN_ACCOUNTING_NOT_COMPLETE")
    if margin.get("admission_inputs_valid") is not True:
        reasons.append("PAPER_ACCOUNT_MARGIN_INPUTS_NOT_VALID")
    if margin.get("account_balance_components_complete") is not True:
        reasons.append("PAPER_ACCOUNT_MARGIN_BALANCE_COMPONENTS_INCOMPLETE")
    if margin.get("wallet_balance_source") != (
        "SAME_LEDGER_STARTING_EQUITY_PLUS_REALIZED_NET_PNL"
    ):
        reasons.append("PAPER_ACCOUNT_MARGIN_WALLET_SOURCE_INVALID")
    if margin.get("equity_source") != (
        "SAME_LEDGER_WALLET_BALANCE_PLUS_CURRENT_UNREALIZED_PNL"
    ):
        reasons.append("PAPER_ACCOUNT_MARGIN_EQUITY_SOURCE_INVALID")
    if not _paper_safety_valid(margin, mutation_flags=True):
        reasons.append("PAPER_ACCOUNT_MARGIN_ROUTE_SAFETY_INVALID")
    if margin.get("paper_session_id") != paper_session_id:
        reasons.append("PAPER_ACCOUNT_MARGIN_SESSION_ID_MISMATCH")
    if margin.get("generated_utc") != payload.get("generated_utc"):
        reasons.append("PAPER_ACCOUNT_MARGIN_GENERATION_NOT_LEDGER_BOUND")
    if "position_margin_rows" not in margin:
        reasons.append("PAPER_ACCOUNT_MARGIN_POSITION_ROWS_KEY_MISSING")
        margin_rows: list[dict[str, Any]] = []
    elif not isinstance(margin.get("position_margin_rows"), list):
        reasons.append("PAPER_ACCOUNT_MARGIN_POSITION_ROWS_NOT_A_LIST")
        margin_rows = []
    else:
        margin_rows = list(margin["position_margin_rows"])
    for count_field in ("open_position_count", "accounted_open_position_count"):
        count = margin.get(count_field)
        if type(count) is not int or count != len(positions):
            reasons.append(f"PAPER_ACCOUNT_MARGIN_{count_field.upper()}_MISMATCH")
    if len(margin_rows) != len(positions):
        reasons.append("PAPER_ACCOUNT_MARGIN_ROW_COUNT_MISMATCH")
    if margin.get("open_position_canonical_identities_unique") is not True:
        reasons.append("PAPER_ACCOUNT_MARGIN_IDENTITIES_NOT_UNIQUE")

    ledger_hash = canonical_sha256(dict(payload)) if payload else None
    if ledger_hash is None:
        reasons.append("PAPER_LEDGER_HASH_FAILED")
    return {
        "valid": not reasons,
        "read_state": state,
        "reasons": list(dict.fromkeys(reasons)),
        "payload": dict(payload),
        "paper_session_id": paper_session_id,
        "generated_utc": payload.get("generated_utc"),
        "positions": positions,
        "position_margin_rows": margin_rows,
        "account": dict(margin),
        "adaptive_portfolio_stress": payload.get("adaptive_portfolio_stress"),
        "source_ledger_sha256": ledger_hash,
        "explicit_empty_open_positions": (
            "open_positions" in payload
            and isinstance(payload.get("open_positions"), list)
            and len(payload["open_positions"]) == 0
        ),
    }


def _get_json(r: Any, key: str) -> tuple[str, Any]:
    return _read_json_once(r, key)


def _validate_cascade_context(
    payload: Any,
    *,
    state: str,
    symbol: str,
    timeframe: str,
    observed_utc: str,
) -> dict[str, Any]:
    reasons: list[str] = []
    if state != "PRESENT":
        reasons.append(f"CASCADE_CONTEXT_{state}")
    if not isinstance(payload, Mapping):
        reasons.append("CASCADE_CONTEXT_NOT_A_MAPPING")
        payload = {}
    if payload.get("schema_version") != "cascade_context_v1":
        reasons.append("CASCADE_CONTEXT_SCHEMA_VERSION_INVALID")
    if str(payload.get("symbol") or "").upper() != symbol:
        reasons.append("CASCADE_CONTEXT_SYMBOL_MISMATCH")
    if str(payload.get("timeframe") or "").lower() != timeframe:
        reasons.append("CASCADE_CONTEXT_TIMEFRAME_MISMATCH")
    if not _paper_safety_valid(payload, mutation_flags=False):
        reasons.append("CASCADE_CONTEXT_ROUTE_SAFETY_INVALID")
    if payload.get("fabricated_liquidation_event") is not False:
        reasons.append("CASCADE_CONTEXT_FABRICATED_EVENT_FLAG_INVALID")
    if payload.get("threshold_lowered") is not False:
        reasons.append("CASCADE_CONTEXT_THRESHOLD_LOWERED_FLAG_INVALID")
    status = payload.get("cascade_context_status")
    if status not in CASCADE_CONFIRMED_STATUSES | CASCADE_NON_TRIGGERING_STATUSES:
        reasons.append("CASCADE_CONTEXT_STATUS_INVALID")
    score = finite_number(payload.get("cascade_risk_score"))
    if score is None or not 0.0 <= score <= 1.0:
        reasons.append("CASCADE_CONTEXT_SCORE_INVALID")

    event_at = parse_utc(payload.get("event_time"))
    available_at = parse_utc(payload.get("available_at"))
    decision_at = parse_utc(payload.get("decision_time"))
    generated_at = parse_utc(payload.get("generated_at"))
    observed_at = parse_utc(observed_utc)
    freshness_budget = finite_number(payload.get("freshness_budget_seconds"))
    cadence_policy_version = payload.get("cadence_policy_version")
    if freshness_budget is None or freshness_budget <= 0.0:
        reasons.append("CASCADE_CONTEXT_ADAPTIVE_FRESHNESS_BUDGET_INVALID")
    if not isinstance(cadence_policy_version, str) or not cadence_policy_version.strip():
        reasons.append("CASCADE_CONTEXT_CADENCE_POLICY_VERSION_INVALID")
    if any(value is None for value in (available_at, decision_at, generated_at, observed_at)):
        reasons.append("CASCADE_CONTEXT_CLOCK_INVALID")
    else:
        assert all(
            value is not None
            for value in (available_at, decision_at, generated_at, observed_at)
        )
        if not available_at <= decision_at <= generated_at <= observed_at:
            reasons.append("CASCADE_CONTEXT_CLOCK_ORDER_INVALID")
        elif (
            freshness_budget is None
            or (observed_at - generated_at).total_seconds() > freshness_budget
        ):
            reasons.append("CASCADE_CONTEXT_STALE_AT_ADAPTIVE_CADENCE")
    adverse_direction = payload.get("adverse_price_move_direction")
    direction_hash = payload.get("direction_evidence_sha256")
    direction_authoritative = (
        payload.get("direction_authority_complete") is True
        and payload.get("cascade_authority_scope") == "PAPER_FORCE_CLOSE"
        and adverse_direction in {"UP", "DOWN"}
        and isinstance(payload.get("direction_policy_version"), str)
        and bool(payload.get("direction_policy_version").strip())
        and isinstance(direction_hash, str)
        and len(direction_hash) == 64
        and all(character in "0123456789abcdef" for character in direction_hash)
    )
    if status in CASCADE_CONFIRMED_STATUSES and not direction_authoritative:
        reasons.append("CASCADE_CONTEXT_SIGNED_DIRECTION_AUTHORITY_INVALID")
    if status in CASCADE_CONFIRMED_STATUSES:
        if event_at is None:
            reasons.append("CONFIRMED_CASCADE_EVENT_TIME_MISSING_OR_INVALID")
        elif available_at is not None and event_at > available_at:
            reasons.append("CONFIRMED_CASCADE_EVENT_TIME_AFTER_AVAILABLE_AT")
        source_count = payload.get("source_available_count")
        if type(source_count) is not int or source_count <= 0:
            reasons.append("CONFIRMED_CASCADE_HAS_NO_AVAILABLE_SOURCE")

    evidence_hash = canonical_sha256(dict(payload)) if payload else None
    if evidence_hash is None:
        reasons.append("CASCADE_CONTEXT_HASH_FAILED")
    valid = not reasons
    return {
        "schema_version": payload.get("schema_version"),
        "status": status,
        "score": score,
        "symbol": symbol,
        "timeframe": timeframe,
        "event_time": payload.get("event_time"),
        "available_at": payload.get("available_at"),
        "decision_time": payload.get("decision_time"),
        "generated_at": payload.get("generated_at"),
        "freshness_budget_seconds": freshness_budget,
        "cadence_policy_version": cadence_policy_version,
        "adverse_price_move_direction": adverse_direction,
        "direction_policy_version": payload.get("direction_policy_version"),
        "direction_evidence_sha256": direction_hash,
        "direction_authority_complete": direction_authoritative,
        "cascade_evidence_sha256": evidence_hash,
        "valid": valid,
        "trigger_active": valid and status in CASCADE_CONFIRMED_STATUSES,
        "non_triggering_status": valid and status in CASCADE_NON_TRIGGERING_STATUSES,
        "block_reasons": list(dict.fromkeys(reasons)),
    }


def _cascade_state(r: Any, symbol: str, *, observed_utc: str) -> dict[str, Any]:
    contexts: list[dict[str, Any]] = []
    for timeframe in CASCADE_TIMEFRAMES:
        state, payload = _get_json(r, f"{CASCADE_PREFIX}{symbol}:{timeframe}")
        contexts.append(
            _validate_cascade_context(
                payload,
                state=state,
                symbol=symbol,
                timeframe=timeframe,
                observed_utc=observed_utc,
            )
        )
    confirmed = [row for row in contexts if row["trigger_active"] is True]
    valid = [row for row in contexts if row["valid"] is True]
    selectable = confirmed or valid
    selected = (
        max(selectable, key=lambda row: float(row["score"]))
        if selectable
        else None
    )
    if selected is None:
        return {
            "valid": False,
            "trigger_active": False,
            "status": None,
            "score": None,
            "timeframe": None,
            "contexts": contexts,
            "block_reasons": list(
                dict.fromkeys(
                    reason
                    for row in contexts
                    for reason in row.get("block_reasons") or []
                )
            ),
        }
    return {**selected, "contexts": contexts}


def decide_directives(
    positions: list[dict[str, Any]],
    cascade_by_symbol: dict[str, dict[str, Any]],
    portfolio_snapshot: dict[str, Any],
    *,
    paper_session_id: str,
    source_ledger_generated_utc: str,
    source_ledger_sha256: str,
    generated_utc: str,
    expires_utc: str,
) -> list[dict[str, Any]]:
    """Build minimal, generation-bound de-risking directives.

    A present-time loser is not automatically the position that improves the
    portfolio's stressed liquidation buffer.  Selection is therefore driven
    only by the signed contribution in the authenticated worst scenario.  The
    smallest descending-relief prefix that restores the adaptive reserve is
    emitted.  Cascade contexts remain telemetry until their producer supplies
    a signed adverse-direction authority contract.
    """

    if (
        portfolio_snapshot.get("authority_complete") is not True
        or portfolio_snapshot.get("portfolio_level_computed") is not True
        or portfolio_snapshot.get("adaptive_stress_authority_complete") is not True
        or type(portfolio_snapshot.get("worst_case_liquidation_breached")) is not bool
    ):
        return []
    del cascade_by_symbol
    snapshot_hash = portfolio_snapshot.get("portfolio_snapshot_sha256")
    if not isinstance(snapshot_hash, str) or len(snapshot_hash) != 64:
        return []
    stress_hash = portfolio_snapshot.get("adaptive_stress_evidence_sha256")
    policy_version = portfolio_snapshot.get("adaptive_stress_policy_version")
    cadence_version = portfolio_snapshot.get("adaptive_stress_cadence_policy_version")
    source_observations_hash = portfolio_snapshot.get(
        "adaptive_stress_source_observations_sha256"
    )
    freshness_budget = finite_number(
        portfolio_snapshot.get("adaptive_stress_freshness_budget_seconds")
    )
    guard_lifetime = finite_number(
        portfolio_snapshot.get("adaptive_guard_lifetime_seconds")
    )
    recovery_reserve = finite_number(
        portfolio_snapshot.get("adaptive_recovery_reserve_usd")
    )
    worst_buffer = finite_number(
        portfolio_snapshot.get("worst_case_liquidation_buffer_usd")
    )
    worst_scenario = portfolio_snapshot.get("worst_case_scenario")
    scenarios = portfolio_snapshot.get("correlated_shock_scenarios")
    if (
        not isinstance(stress_hash, str)
        or len(stress_hash) != 64
        or not isinstance(source_observations_hash, str)
        or len(source_observations_hash) != 64
        or not isinstance(policy_version, str)
        or not policy_version.strip()
        or not isinstance(cadence_version, str)
        or not cadence_version.strip()
        or freshness_budget is None
        or freshness_budget <= 0.0
        or guard_lifetime is None
        or guard_lifetime <= 0.0
        or recovery_reserve is None
        or recovery_reserve < 0.0
        or worst_buffer is None
        or not isinstance(worst_scenario, str)
        or not isinstance(scenarios, Mapping)
        or not isinstance(scenarios.get(worst_scenario), Mapping)
    ):
        return []
    scenario = scenarios[worst_scenario]
    contributions = scenario.get("position_contributions")
    if not isinstance(contributions, Mapping):
        return []
    deficit = recovery_reserve - worst_buffer
    if deficit <= 0.0:
        return []
    worst_breached = portfolio_snapshot["worst_case_liquidation_breached"] is True
    positions_by_id = {
        str(row.get("position_id")): row
        for row in positions
        if isinstance(row, Mapping)
    }
    ranked: list[tuple[float, str, Mapping[str, Any], Mapping[str, Any]]] = []
    for position_id, raw_contribution in contributions.items():
        row = positions_by_id.get(str(position_id))
        if row is None or not isinstance(raw_contribution, Mapping):
            continue
        relief = finite_number(
            raw_contribution.get("marginal_stress_buffer_relief_if_closed_usd")
        )
        if (
            relief is None
            or relief <= 0.0
            or row.get("margin_mode") != "cross"
            or raw_contribution.get("position_generation_id")
            != row.get("position_generation_id")
            or str(raw_contribution.get("symbol") or "").upper()
            != str(row.get("symbol") or "").upper()
        ):
            continue
        ranked.append((relief, str(position_id), row, raw_contribution))
    ranked.sort(key=lambda item: (-item[0], item[1]))

    directives: list[dict[str, Any]] = []
    cumulative_relief = 0.0
    for rank, (relief, _position_id, row, contribution) in enumerate(ranked, start=1):
        pnl_bps = finite_number(row.get("unrealized_pnl_bps"))
        if pnl_bps is None:
            continue
        symbol = str(row.get("symbol") or "").upper()
        cumulative_relief += relief
        directives.append(
            seal_directive(
                {
                    "schema_version": DIRECTIVE_SCHEMA_VERSION,
                    "paper_session_id": paper_session_id,
                    "position_id": row["position_id"],
                    "position_generation_id": row["position_generation_id"],
                    "symbol": symbol,
                    "action": "CLOSE",
                    "reason": "ADAPTIVE_PORTFOLIO_STRESS_DE_RISK",
                    "generated_utc": generated_utc,
                    "expires_utc": expires_utc,
                    "source_ledger_generated_utc": source_ledger_generated_utc,
                    "source_ledger_sha256": source_ledger_sha256,
                    "portfolio_snapshot_sha256": snapshot_hash,
                    "position_evidence_sha256": row["position_evidence_sha256"],
                    "portfolio_level_computed": True,
                    "worst_case_liquidation_breached": worst_breached,
                    "worst_case_scenario": worst_scenario,
                    "worst_case_liquidation_buffer_usd_at_generation": round(
                        worst_buffer, 8
                    ),
                    "adaptive_recovery_reserve_usd_at_generation": round(
                        recovery_reserve, 8
                    ),
                    "stress_buffer_deficit_usd_at_generation": round(deficit, 8),
                    "marginal_stress_buffer_relief_if_closed_usd": round(
                        relief, 8
                    ),
                    "cumulative_ranked_relief_usd": round(cumulative_relief, 8),
                    "stress_close_rank": rank,
                    "stress_symbol_move_at_generation": contribution.get(
                        "symbol_move"
                    ),
                    "stress_shock_pnl_delta_usd_at_generation": contribution.get(
                        "shock_pnl_delta_usd"
                    ),
                    "stress_shocked_maintenance_margin_usd_at_generation": (
                        contribution.get("shocked_maintenance_margin_usd")
                    ),
                    "adaptive_stress_evidence_sha256": stress_hash,
                    "adaptive_stress_authority_complete": True,
                    "adaptive_stress_source_observations_sha256": (
                        source_observations_hash
                    ),
                    "adaptive_stress_policy_version": policy_version,
                    "adaptive_guard_cadence_policy_version": cadence_version,
                    "adaptive_guard_freshness_budget_seconds": freshness_budget,
                    "adaptive_guard_lifetime_seconds": guard_lifetime,
                    "unrealized_pnl_bps_at_generation": round(pnl_bps, 8),
                    "position_quantity_at_generation": row["position_quantity"],
                    "position_side_at_generation": row["side"],
                    "entry_price_at_generation": row["entry_price"],
                    "effective_leverage_at_generation": row["effective_leverage"],
                    "margin_mode_at_generation": "cross",
                    "ride_tighten_implemented": False,
                    "paper_only": True,
                    "routes_to_live": False,
                    "places_real_order": False,
                    "leverage_mutated": False,
                    "margin_mutated": False,
                }
            )
        )
        if cumulative_relief >= deficit:
            break
    return directives


def _blocked_payload(
    *,
    generated_utc: str,
    expires_utc: str,
    ledger: Mapping[str, Any],
    reasons: list[str],
    portfolio_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = portfolio_snapshot or {}
    return seal_guard_payload(
        {
            "schema_version": GUARD_SCHEMA_VERSION,
            "status": "BLOCKED",
            "directive_authority": False,
            "block_reasons": list(dict.fromkeys(reasons)),
            "paper_session_id": ledger.get("paper_session_id"),
            "source_ledger_generated_utc": ledger.get("generated_utc"),
            "source_ledger_sha256": ledger.get("source_ledger_sha256"),
            "portfolio_snapshot_sha256": snapshot.get("portfolio_snapshot_sha256"),
            "generated_utc": generated_utc,
            "expires_utc": expires_utc,
            "open_position_count": None,
            "directives": [],
            "cascade_by_symbol": {},
            "portfolio_level_computed": False,
            "worst_case_liquidation_breached": None,
            "worst_case_liquidation_buffer_usd": None,
            "adaptive_stress_authority_complete": False,
            "adaptive_stress_evidence_sha256": snapshot.get(
                "adaptive_stress_evidence_sha256"
            ),
            "adaptive_stress_source_observations_sha256": snapshot.get(
                "adaptive_stress_source_observations_sha256"
            ),
            "adaptive_stress_policy_version": snapshot.get(
                "adaptive_stress_policy_version"
            ),
            "adaptive_guard_cadence_policy_version": snapshot.get(
                "adaptive_stress_cadence_policy_version"
            ),
            "adaptive_guard_freshness_budget_seconds": snapshot.get(
                "adaptive_stress_freshness_budget_seconds"
            ),
            "adaptive_guard_lifetime_seconds": snapshot.get(
                "adaptive_guard_lifetime_seconds"
            ),
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "leverage_mutated": False,
            "margin_mutated": False,
        }
    )


def _adaptive_guard_authority_reasons(
    *,
    ledger: Mapping[str, Any],
    portfolio_snapshot: Mapping[str, Any],
    observed_utc: str,
) -> list[str]:
    """Validate the adaptive cadence and pair-safety boundary for force closes."""

    reasons: list[str] = []
    if portfolio_snapshot.get("adaptive_stress_authority_complete") is not True:
        reasons.extend(
            portfolio_snapshot.get("adaptive_stress_block_reasons")
            or ["ADAPTIVE_STRESS_AUTHORITY_INCOMPLETE"]
        )
    freshness_budget = finite_number(
        portfolio_snapshot.get("adaptive_stress_freshness_budget_seconds")
    )
    guard_lifetime = finite_number(
        portfolio_snapshot.get("adaptive_guard_lifetime_seconds")
    )
    if freshness_budget is None or freshness_budget <= 0.0:
        reasons.append("ADAPTIVE_GUARD_FRESHNESS_BUDGET_INVALID")
    if guard_lifetime is None or guard_lifetime <= 0.0:
        reasons.append("ADAPTIVE_GUARD_LIFETIME_INVALID")
    ledger_at = parse_utc(ledger.get("generated_utc"))
    observed_at = parse_utc(observed_utc)
    stress_generated = parse_utc(portfolio_snapshot.get("adaptive_stress_generated_at"))
    stress_available = parse_utc(portfolio_snapshot.get("adaptive_stress_available_at"))
    stress_decision = parse_utc(portfolio_snapshot.get("adaptive_stress_decision_time"))
    if None in (
        ledger_at,
        observed_at,
        stress_generated,
        stress_available,
        stress_decision,
    ):
        reasons.append("ADAPTIVE_GUARD_PRIMARY_CLOCKS_INVALID")
    else:
        assert all(
            value is not None
            for value in (
                ledger_at,
                observed_at,
                stress_generated,
                stress_available,
                stress_decision,
            )
        )
        if not stress_generated <= stress_available <= stress_decision <= ledger_at <= observed_at:
            reasons.append("ADAPTIVE_GUARD_PRIMARY_CLOCK_ORDER_INVALID")
        elif (
            freshness_budget is None
            or (observed_at - ledger_at).total_seconds() > freshness_budget
            or (observed_at - stress_decision).total_seconds() > freshness_budget
        ):
            reasons.append("ADAPTIVE_GUARD_INPUT_STALE_AT_POLICY_CADENCE")

    # Until pair directives have an all-or-nothing lifecycle commit, a guard
    # close cannot safely mutate either leg of an active hedge relationship.
    for position in ledger.get("positions") or []:
        if not isinstance(position, Mapping):
            continue
        hedge_state = str(position.get("hedge_state") or "").upper()
        has_pair_link = any(
            position.get(field) not in (None, "")
            for field in (
                "hedge_pair_id",
                "hedge_position_id",
                "hedge_parent_position_id",
                "parent_position_id",
            )
        )
        if has_pair_link or hedge_state not in {"", "UNHEDGED", "INACTIVE", "CLOSED"}:
            reasons.append("ACTIVE_HEDGE_PAIR_REQUIRES_ATOMIC_CLOSE_IMPLEMENTATION")
            break
    return list(dict.fromkeys(reasons))


def run_once(r: Any) -> dict[str, Any]:
    observed_utc = _utc_now()
    generated_at = parse_utc(observed_utc)
    assert generated_at is not None
    expires_utc = observed_utc
    redis_ttl_seconds: int | None = None
    ledger = _strict_ledger_snapshot(r, observed_utc=observed_utc)
    if ledger["valid"] is not True:
        payload = _blocked_payload(
            generated_utc=observed_utc,
            expires_utc=expires_utc,
            ledger=ledger,
            reasons=ledger["reasons"],
        )
    else:
        try:
            snapshot = build_portfolio_liquidation_snapshot(
                account=ledger["account"],
                positions=ledger["positions"],
                position_margin_rows=ledger["position_margin_rows"],
                generated_utc=observed_utc,
                adaptive_stress_envelope=ledger["adaptive_portfolio_stress"],
            )
        except Exception as exc:  # defensive service boundary; no directive survives
            snapshot = {
                "authority_complete": False,
                "portfolio_level_computed": False,
                "block_reasons": [
                    f"PORTFOLIO_SNAPSHOT_EXCEPTION:{type(exc).__name__}"
                ],
            }
        authority_reasons = (
            _adaptive_guard_authority_reasons(
                ledger=ledger,
                portfolio_snapshot=snapshot,
                observed_utc=observed_utc,
            )
            if snapshot.get("authority_complete") is True
            else list(snapshot.get("block_reasons") or ["PORTFOLIO_SNAPSHOT_BLOCKED"])
        )
        if snapshot.get("authority_complete") is not True or authority_reasons:
            payload = _blocked_payload(
                generated_utc=observed_utc,
                expires_utc=expires_utc,
                ledger=ledger,
                reasons=authority_reasons,
                portfolio_snapshot=snapshot,
            )
        else:
            guard_lifetime = finite_number(snapshot["adaptive_guard_lifetime_seconds"])
            assert guard_lifetime is not None and guard_lifetime > 0.0
            expires_utc = _iso(generated_at + timedelta(seconds=guard_lifetime))
            redis_ttl_seconds = max(1, math.ceil(guard_lifetime))
            cascade_by_symbol = {
                str(row["symbol"]): _cascade_state(
                    r,
                    str(row["symbol"]),
                    observed_utc=observed_utc,
                )
                for row in snapshot["positions"]
            }
            directives = decide_directives(
                snapshot["positions"],
                cascade_by_symbol,
                snapshot,
                paper_session_id=str(ledger["paper_session_id"]),
                source_ledger_generated_utc=str(ledger["generated_utc"]),
                source_ledger_sha256=str(ledger["source_ledger_sha256"]),
                generated_utc=observed_utc,
                expires_utc=expires_utc,
            )
            recovery_reserve = finite_number(snapshot["adaptive_recovery_reserve_usd"])
            worst_buffer = finite_number(snapshot["worst_case_liquidation_buffer_usd"])
            stress_deficit = (
                max(0.0, recovery_reserve - worst_buffer)
                if recovery_reserve is not None and worst_buffer is not None
                else None
            )
            if stress_deficit is not None and stress_deficit > 0.0 and not directives:
                payload = _blocked_payload(
                    generated_utc=observed_utc,
                    expires_utc=expires_utc,
                    ledger=ledger,
                    reasons=["ADAPTIVE_STRESS_NO_POSITIVE_MARGINAL_CLOSE_RELIEF"],
                    portfolio_snapshot=snapshot,
                )
            else:
                payload = seal_guard_payload(
                {
                    "schema_version": GUARD_SCHEMA_VERSION,
                    "status": (
                        "AUTHORITATIVE_EMPTY"
                        if not snapshot["positions"]
                        else "PASS"
                    ),
                    "directive_authority": True,
                    "block_reasons": [],
                    "paper_session_id": ledger["paper_session_id"],
                    "source_ledger_generated_utc": ledger["generated_utc"],
                    "source_ledger_sha256": ledger["source_ledger_sha256"],
                    "portfolio_snapshot_sha256": snapshot[
                        "portfolio_snapshot_sha256"
                    ],
                    "generated_utc": observed_utc,
                    "expires_utc": expires_utc,
                    "open_position_count": snapshot["open_position_count"],
                    "directives": directives,
                    "cascade_by_symbol": cascade_by_symbol,
                    "portfolio_level_computed": True,
                    "worst_case_liquidation_breached": snapshot[
                        "worst_case_liquidation_breached"
                    ],
                    "worst_case_liquidation_buffer_usd": snapshot[
                        "worst_case_liquidation_buffer_usd"
                    ],
                    "adaptive_recovery_reserve_usd": snapshot[
                        "adaptive_recovery_reserve_usd"
                    ],
                    "adaptive_stress_authority_complete": True,
                    "adaptive_stress_evidence_sha256": snapshot[
                        "adaptive_stress_evidence_sha256"
                    ],
                    "adaptive_stress_source_observations_sha256": snapshot[
                        "adaptive_stress_source_observations_sha256"
                    ],
                    "adaptive_stress_policy_version": snapshot[
                        "adaptive_stress_policy_version"
                    ],
                    "adaptive_stress_producer": snapshot[
                        "adaptive_stress_producer"
                    ],
                    "adaptive_stress_auth_boundary": snapshot[
                        "adaptive_stress_auth_boundary"
                    ],
                    "adaptive_guard_cadence_policy_version": snapshot[
                        "adaptive_stress_cadence_policy_version"
                    ],
                    "adaptive_guard_freshness_budget_seconds": snapshot[
                        "adaptive_stress_freshness_budget_seconds"
                    ],
                    "adaptive_guard_lifetime_seconds": guard_lifetime,
                    "paper_only": True,
                    "routes_to_live": False,
                    "places_real_order": False,
                    "leverage_mutated": False,
                    "margin_mutated": False,
                }
                )
    write_success = False
    try:
        write_success = bool(
            r.set(
                GUARD_KEY,
                json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False),
                ex=redis_ttl_seconds,
            )
        )
    except Exception:
        write_success = False
    return {**payload, "redis_write_success": write_success}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=20)
    args = parser.parse_args(argv)
    r = _redis_client()
    while True:
        payload = run_once(r)
        if args.once:
            print(json.dumps(payload, indent=1, default=str)[:3000])
            return 0
        time.sleep(max(5, int(args.interval_seconds)))


if __name__ == "__main__":
    raise SystemExit(main())
