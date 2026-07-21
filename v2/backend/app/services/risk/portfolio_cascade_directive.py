"""Versioned evidence envelopes for paper-only portfolio cascade directives."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

GUARD_SCHEMA_VERSION = "portfolio_cascade_guard_v3"
DIRECTIVE_SCHEMA_VERSION = "portfolio_cascade_directive_v3"
_HASH_FIELDS = frozenset({"directive_id", "directive_evidence_sha256"})
_HEX = frozenset("0123456789abcdef")


def parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def canonical_sha256(value: Any) -> str | None:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def _sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and set(value).issubset(_HEX)
    )


def _paper_safety_valid(value: Mapping[str, Any]) -> bool:
    return (
        value.get("paper_only") is True
        and value.get("routes_to_live") is False
        and value.get("places_real_order") is False
        and value.get("leverage_mutated") is False
        and value.get("margin_mutated") is False
    )


def seal_directive(material: Mapping[str, Any]) -> dict[str, Any]:
    """Return a content-bound directive; caller material is not mutated."""

    directive = {
        key: value
        for key, value in dict(material).items()
        if key not in _HASH_FIELDS
    }
    digest = canonical_sha256(directive)
    if digest is None:
        raise ValueError("PORTFOLIO_CASCADE_DIRECTIVE_HASH_FAILED")
    return {
        **directive,
        "directive_id": f"paper-cascade:{digest}",
        "directive_evidence_sha256": digest,
    }


def seal_guard_payload(material: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in dict(material).items()
        if key != "guard_evidence_sha256"
    }
    digest = canonical_sha256(payload)
    if digest is None:
        raise ValueError("PORTFOLIO_CASCADE_GUARD_HASH_FAILED")
    return {**payload, "guard_evidence_sha256": digest}


def verify_directive(
    directive: Any,
    *,
    expected_paper_session_id: str,
    guard_generated_utc: str,
    guard_expires_utc: str,
) -> list[str]:
    if not isinstance(directive, Mapping):
        return ["DIRECTIVE_NOT_A_MAPPING"]
    reasons: list[str] = []
    material = {
        key: value
        for key, value in dict(directive).items()
        if key not in _HASH_FIELDS
    }
    digest = canonical_sha256(material)
    if digest is None or directive.get("directive_evidence_sha256") != digest:
        reasons.append("DIRECTIVE_EVIDENCE_HASH_INVALID")
    if directive.get("directive_id") != f"paper-cascade:{digest}":
        reasons.append("DIRECTIVE_ID_INVALID")
    if directive.get("schema_version") != DIRECTIVE_SCHEMA_VERSION:
        reasons.append("DIRECTIVE_SCHEMA_VERSION_INVALID")
    if not _paper_safety_valid(directive):
        reasons.append("DIRECTIVE_PAPER_ROUTE_SAFETY_INVALID")
    if directive.get("paper_session_id") != expected_paper_session_id:
        reasons.append("DIRECTIVE_PAPER_SESSION_ID_MISMATCH")
    for field in ("position_id", "position_generation_id", "symbol", "reason"):
        if not isinstance(directive.get(field), str) or not str(directive.get(field)).strip():
            reasons.append(f"DIRECTIVE_{field.upper()}_MISSING_OR_INVALID")
    action = directive.get("action")
    if action not in {"CLOSE", "RIDE_TIGHTEN"}:
        reasons.append("DIRECTIVE_ACTION_INVALID")
    close_reasons = {
        "ADAPTIVE_PORTFOLIO_STRESS_DE_RISK",
        "CASCADE_CONFIRMED_SIGNED_ADVERSE_MOVE",
    }
    if action == "CLOSE" and directive.get("reason") not in close_reasons:
        reasons.append("DIRECTIVE_CLOSE_REASON_INVALID")
    if (
        action == "RIDE_TIGHTEN"
        and directive.get("reason")
        != "CASCADE_CONFIRMED_POSITION_WINNING_TELEMETRY_ONLY"
    ):
        reasons.append("DIRECTIVE_RIDE_REASON_INVALID")
    if directive.get("generated_utc") != guard_generated_utc:
        reasons.append("DIRECTIVE_GENERATED_UTC_NOT_BOUND_TO_GUARD")
    if directive.get("expires_utc") != guard_expires_utc:
        reasons.append("DIRECTIVE_EXPIRES_UTC_NOT_BOUND_TO_GUARD")
    if directive.get("portfolio_level_computed") is not True:
        reasons.append("DIRECTIVE_PORTFOLIO_LEVEL_NOT_COMPUTED")
    if type(directive.get("worst_case_liquidation_breached")) is not bool:
        reasons.append("DIRECTIVE_PORTFOLIO_BREACH_FLAG_INVALID")
    for field in (
        "source_ledger_sha256",
        "portfolio_snapshot_sha256",
        "position_evidence_sha256",
    ):
        if not _sha256_hex(directive.get(field)):
            reasons.append(f"DIRECTIVE_{field.upper()}_INVALID")
    pnl_bps = finite_number(directive.get("unrealized_pnl_bps_at_generation"))
    if pnl_bps is None:
        reasons.append("DIRECTIVE_GENERATION_PNL_BPS_MISSING_OR_NONFINITE")
    elif (
        action == "CLOSE"
        and directive.get("reason") == "CASCADE_CONFIRMED_SIGNED_ADVERSE_MOVE"
        and pnl_bps >= 0.0
    ):
        reasons.append("DIRECTIVE_CASCADE_CLOSE_GENERATION_PNL_NOT_NEGATIVE")
    elif action == "RIDE_TIGHTEN" and pnl_bps < 0.0:
        reasons.append("DIRECTIVE_RIDE_GENERATION_PNL_NEGATIVE")
    if (
        directive.get("reason") == "ADAPTIVE_PORTFOLIO_STRESS_DE_RISK"
        and directive.get("adaptive_stress_authority_complete") is not True
    ):
        reasons.append("DIRECTIVE_ADAPTIVE_STRESS_AUTHORITY_NOT_TRUE")
    for field in (
        "position_quantity_at_generation",
        "entry_price_at_generation",
        "effective_leverage_at_generation",
    ):
        number = finite_number(directive.get(field))
        if number is None or number <= 0.0:
            reasons.append(f"DIRECTIVE_{field.upper()}_MISSING_OR_INVALID")
    if directive.get("position_side_at_generation") not in {"long", "short"}:
        reasons.append("DIRECTIVE_POSITION_SIDE_AT_GENERATION_INVALID")

    generated_at = parse_utc(directive.get("generated_utc"))
    expires_at = parse_utc(directive.get("expires_utc"))
    ledger_at = parse_utc(directive.get("source_ledger_generated_utc"))
    freshness_budget = finite_number(
        directive.get("adaptive_guard_freshness_budget_seconds")
    )
    guard_lifetime = finite_number(
        directive.get("adaptive_guard_lifetime_seconds")
    )
    if freshness_budget is None or freshness_budget <= 0.0:
        reasons.append("DIRECTIVE_ADAPTIVE_FRESHNESS_BUDGET_INVALID")
    if guard_lifetime is None or guard_lifetime <= 0.0:
        reasons.append("DIRECTIVE_ADAPTIVE_LIFETIME_INVALID")
    if not isinstance(
        directive.get("adaptive_guard_cadence_policy_version"), str
    ) or not str(directive.get("adaptive_guard_cadence_policy_version") or "").strip():
        reasons.append("DIRECTIVE_ADAPTIVE_CADENCE_POLICY_VERSION_INVALID")
    if generated_at is None or expires_at is None or ledger_at is None:
        reasons.append("DIRECTIVE_PRIMARY_CLOCK_INVALID")
    elif not ledger_at <= generated_at < expires_at:
        reasons.append("DIRECTIVE_PRIMARY_CLOCK_ORDER_INVALID")
    else:
        if (
            freshness_budget is None
            or (generated_at - ledger_at).total_seconds() > freshness_budget
        ):
            reasons.append("DIRECTIVE_SOURCE_LEDGER_STALE_AT_ADAPTIVE_CADENCE")
        if (
            guard_lifetime is None
            or not math.isclose(
                (expires_at - generated_at).total_seconds(),
                guard_lifetime,
                rel_tol=1e-9,
                abs_tol=1e-7,
            )
        ):
            reasons.append("DIRECTIVE_LIFETIME_NOT_EQUAL_ADAPTIVE_POLICY")

    if directive.get("reason") == "ADAPTIVE_PORTFOLIO_STRESS_DE_RISK":
        for field in (
            "adaptive_stress_evidence_sha256",
            "adaptive_stress_source_observations_sha256",
        ):
            if not _sha256_hex(directive.get(field)):
                reasons.append(f"DIRECTIVE_{field.upper()}_INVALID")
        for field in (
            "adaptive_stress_policy_version",
            "worst_case_scenario",
        ):
            if not isinstance(directive.get(field), str) or not str(
                directive.get(field) or ""
            ).strip():
                reasons.append(f"DIRECTIVE_{field.upper()}_INVALID")
        if directive.get("margin_mode_at_generation") != "cross":
            reasons.append("DIRECTIVE_MARGIN_MODE_AT_GENERATION_NOT_CROSS")
        relief = finite_number(
            directive.get("marginal_stress_buffer_relief_if_closed_usd")
        )
        deficit = finite_number(
            directive.get("stress_buffer_deficit_usd_at_generation")
        )
        reserve = finite_number(
            directive.get("adaptive_recovery_reserve_usd_at_generation")
        )
        buffer = finite_number(
            directive.get("worst_case_liquidation_buffer_usd_at_generation")
        )
        cumulative = finite_number(directive.get("cumulative_ranked_relief_usd"))
        rank = directive.get("stress_close_rank")
        if relief is None or relief <= 0.0:
            reasons.append("DIRECTIVE_MARGINAL_STRESS_RELIEF_NOT_POSITIVE")
        if deficit is None or deficit <= 0.0:
            reasons.append("DIRECTIVE_STRESS_BUFFER_DEFICIT_NOT_POSITIVE")
        if reserve is None or reserve < 0.0 or buffer is None:
            reasons.append("DIRECTIVE_STRESS_RESERVE_OR_BUFFER_INVALID")
        elif deficit is not None and not math.isclose(
            deficit, reserve - buffer, rel_tol=1e-9, abs_tol=1e-7
        ):
            reasons.append("DIRECTIVE_STRESS_DEFICIT_RECONCILIATION_FAILED")
        if cumulative is None or relief is None or cumulative < relief:
            reasons.append("DIRECTIVE_CUMULATIVE_STRESS_RELIEF_INVALID")
        if type(rank) is not int or rank <= 0:
            reasons.append("DIRECTIVE_STRESS_CLOSE_RANK_INVALID")
        if finite_number(directive.get("stress_symbol_move_at_generation")) is None:
            reasons.append("DIRECTIVE_STRESS_SYMBOL_MOVE_INVALID")

    reason = directive.get("reason")
    cascade_required = reason in {
        "CASCADE_CONFIRMED_SIGNED_ADVERSE_MOVE",
        "CASCADE_CONFIRMED_POSITION_WINNING_TELEMETRY_ONLY",
    }
    if cascade_required:
        if not _sha256_hex(directive.get("cascade_evidence_sha256")):
            reasons.append("DIRECTIVE_CASCADE_EVIDENCE_HASH_INVALID")
        if directive.get("cascade_schema_version") != "cascade_context_v1":
            reasons.append("DIRECTIVE_CASCADE_SCHEMA_VERSION_INVALID")
        if directive.get("cascade_status") not in {
            "EVENT_CONFIRMED",
            "LEVEL_PROXIMITY_CONFIRMED",
            "PROXY_CONFIRMED",
        }:
            reasons.append("DIRECTIVE_CASCADE_STATUS_NOT_CONFIRMED")
        score = finite_number(directive.get("cascade_score"))
        if score is None or not 0.0 <= score <= 1.0:
            reasons.append("DIRECTIVE_CASCADE_SCORE_INVALID")
        cascade_clocks = [
            parse_utc(directive.get(field))
            for field in (
                "cascade_event_time",
                "cascade_available_at",
                "cascade_decision_time",
                "cascade_generated_at",
            )
        ]
        if any(value is None for value in cascade_clocks):
            reasons.append("DIRECTIVE_CASCADE_CLOCK_INVALID")
        else:
            event_at, available_at, decision_at, cascade_generated_at = cascade_clocks
            assert all(
                value is not None
                for value in (event_at, available_at, decision_at, cascade_generated_at)
            )
            if not event_at <= available_at <= decision_at <= cascade_generated_at <= generated_at:
                reasons.append("DIRECTIVE_CASCADE_CLOCK_ORDER_INVALID")
        if directive.get("cascade_direction_authority_complete") is not True:
            reasons.append("DIRECTIVE_CASCADE_DIRECTION_AUTHORITY_NOT_TRUE")
        direction = directive.get("cascade_adverse_price_move_direction")
        side = directive.get("position_side_at_generation")
        if (side == "long" and direction != "DOWN") or (
            side == "short" and direction != "UP"
        ):
            reasons.append("DIRECTIVE_CASCADE_DIRECTION_NOT_ADVERSE_TO_POSITION")
        if not _sha256_hex(directive.get("cascade_direction_evidence_sha256")):
            reasons.append("DIRECTIVE_CASCADE_DIRECTION_EVIDENCE_HASH_INVALID")
    return list(dict.fromkeys(reasons))


def verify_guard_payload(
    payload: Any,
    *,
    expected_paper_session_id: str,
    observed_utc: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Verify the whole envelope before lifecycle considers any directive."""

    if not isinstance(payload, Mapping):
        return [], ["GUARD_PAYLOAD_NOT_A_MAPPING"]
    reasons: list[str] = []
    material = {
        key: value
        for key, value in dict(payload).items()
        if key != "guard_evidence_sha256"
    }
    digest = canonical_sha256(material)
    if digest is None or payload.get("guard_evidence_sha256") != digest:
        reasons.append("GUARD_EVIDENCE_HASH_INVALID")
    if payload.get("schema_version") != GUARD_SCHEMA_VERSION:
        reasons.append("GUARD_SCHEMA_VERSION_INVALID")
    if payload.get("directive_authority") is not True:
        reasons.append("GUARD_DIRECTIVE_AUTHORITY_NOT_TRUE")
    if payload.get("status") not in {"PASS", "AUTHORITATIVE_EMPTY"}:
        reasons.append("GUARD_STATUS_NOT_AUTHORITATIVE")
    if payload.get("paper_session_id") != expected_paper_session_id:
        reasons.append("GUARD_PAPER_SESSION_ID_MISMATCH")
    if not _paper_safety_valid(payload):
        reasons.append("GUARD_PAPER_ROUTE_SAFETY_INVALID")
    for field in ("source_ledger_sha256", "portfolio_snapshot_sha256"):
        if not _sha256_hex(payload.get(field)):
            reasons.append(f"GUARD_{field.upper()}_INVALID")

    generated_at = parse_utc(payload.get("generated_utc"))
    expires_at = parse_utc(payload.get("expires_utc"))
    observed_at = parse_utc(observed_utc)
    ledger_at = parse_utc(payload.get("source_ledger_generated_utc"))
    freshness_budget = finite_number(
        payload.get("adaptive_guard_freshness_budget_seconds")
    )
    guard_lifetime = finite_number(payload.get("adaptive_guard_lifetime_seconds"))
    if freshness_budget is None or freshness_budget <= 0.0:
        reasons.append("GUARD_ADAPTIVE_FRESHNESS_BUDGET_INVALID")
    if guard_lifetime is None or guard_lifetime <= 0.0:
        reasons.append("GUARD_ADAPTIVE_LIFETIME_INVALID")
    for field in (
        "adaptive_stress_policy_version",
        "adaptive_guard_cadence_policy_version",
    ):
        if not isinstance(payload.get(field), str) or not str(
            payload.get(field) or ""
        ).strip():
            reasons.append(f"GUARD_{field.upper()}_INVALID")
    if payload.get("adaptive_stress_authority_complete") is not True:
        reasons.append("GUARD_ADAPTIVE_STRESS_AUTHORITY_NOT_TRUE")
    if payload.get("adaptive_stress_producer") != "adaptive_portfolio_stress_controller":
        reasons.append("GUARD_ADAPTIVE_STRESS_PRODUCER_INVALID")
    if payload.get("adaptive_stress_auth_boundary") != "PAPER_ADAPTIVE_STRESS_PIT_V1":
        reasons.append("GUARD_ADAPTIVE_STRESS_AUTH_BOUNDARY_INVALID")
    for field in (
        "adaptive_stress_evidence_sha256",
        "adaptive_stress_source_observations_sha256",
    ):
        if not _sha256_hex(payload.get(field)):
            reasons.append(f"GUARD_{field.upper()}_INVALID")
    if any(value is None for value in (generated_at, expires_at, observed_at, ledger_at)):
        reasons.append("GUARD_PRIMARY_CLOCK_INVALID")
    else:
        assert all(
            value is not None
            for value in (generated_at, expires_at, observed_at, ledger_at)
        )
        if not ledger_at <= generated_at <= observed_at <= expires_at:
            reasons.append("GUARD_PRIMARY_CLOCK_ORDER_OR_EXPIRY_INVALID")
        else:
            if (
                freshness_budget is None
                or (generated_at - ledger_at).total_seconds() > freshness_budget
            ):
                reasons.append("GUARD_SOURCE_LEDGER_STALE_AT_ADAPTIVE_CADENCE")
            if (
                freshness_budget is None
                or (observed_at - generated_at).total_seconds() > freshness_budget
            ):
                reasons.append("GUARD_STALE_AT_ADAPTIVE_CONSUMER_CADENCE")
            if (
                guard_lifetime is None
                or not math.isclose(
                    (expires_at - generated_at).total_seconds(),
                    guard_lifetime,
                    rel_tol=1e-9,
                    abs_tol=1e-7,
                )
            ):
                reasons.append("GUARD_LIFETIME_NOT_EQUAL_ADAPTIVE_POLICY")

    if payload.get("portfolio_level_computed") is not True:
        reasons.append("GUARD_PORTFOLIO_LEVEL_NOT_COMPUTED")
    if type(payload.get("worst_case_liquidation_breached")) is not bool:
        reasons.append("GUARD_PORTFOLIO_BREACH_FLAG_INVALID")
    open_position_count = payload.get("open_position_count")
    if type(open_position_count) is not int or open_position_count < 0:
        reasons.append("GUARD_OPEN_POSITION_COUNT_INVALID")

    raw_directives = payload.get("directives")
    if not isinstance(raw_directives, list):
        reasons.append("GUARD_DIRECTIVES_KEY_MISSING_OR_NOT_A_LIST")
        raw_directives = []
    verified: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_positions: set[tuple[str, str]] = set()
    for directive in raw_directives:
        directive_reasons = verify_directive(
            directive,
            expected_paper_session_id=expected_paper_session_id,
            guard_generated_utc=str(payload.get("generated_utc") or ""),
            guard_expires_utc=str(payload.get("expires_utc") or ""),
        )
        if directive_reasons:
            reasons.extend(directive_reasons)
            continue
        assert isinstance(directive, Mapping)
        for directive_field, guard_field in (
            ("source_ledger_generated_utc", "source_ledger_generated_utc"),
            ("source_ledger_sha256", "source_ledger_sha256"),
            ("portfolio_snapshot_sha256", "portfolio_snapshot_sha256"),
            ("worst_case_liquidation_breached", "worst_case_liquidation_breached"),
            ("adaptive_stress_evidence_sha256", "adaptive_stress_evidence_sha256"),
            (
                "adaptive_stress_source_observations_sha256",
                "adaptive_stress_source_observations_sha256",
            ),
            ("adaptive_stress_policy_version", "adaptive_stress_policy_version"),
            (
                "adaptive_guard_cadence_policy_version",
                "adaptive_guard_cadence_policy_version",
            ),
            (
                "adaptive_guard_freshness_budget_seconds",
                "adaptive_guard_freshness_budget_seconds",
            ),
            ("adaptive_guard_lifetime_seconds", "adaptive_guard_lifetime_seconds"),
        ):
            if directive.get(directive_field) != payload.get(guard_field):
                reasons.append(
                    f"DIRECTIVE_{directive_field.upper()}_NOT_BOUND_TO_GUARD"
                )
        if reasons:
            continue
        directive_id = str(directive["directive_id"])
        identity = (
            str(directive["position_id"]),
            str(directive["position_generation_id"]),
        )
        if directive_id in seen_ids:
            reasons.append("GUARD_DIRECTIVE_ID_REUSED")
            continue
        if identity in seen_positions:
            reasons.append("GUARD_POSITION_GENERATION_DIRECTIVE_REUSED")
            continue
        seen_ids.add(directive_id)
        seen_positions.add(identity)
        verified.append(dict(directive))
    if payload.get("status") == "AUTHORITATIVE_EMPTY" and (
        open_position_count != 0 or raw_directives
    ):
        reasons.append("AUTHORITATIVE_EMPTY_GUARD_CONTAINS_POSITIONS_OR_DIRECTIVES")
    if isinstance(raw_directives, list) and len(raw_directives) > int(
        open_position_count or 0
    ):
        reasons.append("GUARD_DIRECTIVE_COUNT_EXCEEDS_OPEN_POSITION_COUNT")
    if reasons:
        return [], list(dict.fromkeys(reasons))
    return verified, []
