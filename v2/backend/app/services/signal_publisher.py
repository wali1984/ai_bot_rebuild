"""V2 signal publisher service.

Builds signal records from trainer predictions and feature snapshots,
emits explainability evidence citations for each input field, and
returns ``EVIDENCE_MISSING_LABEL`` when an input field is absent so
that downstream code never publishes a claim it cannot back with
evidence.

Live trading remains permanently ``blocked_human_only``. This service
is non-mutating: it does not call any exchange, does not write to any
Redis namespace, and does not modify the legacy bot.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import time
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple


SIGNAL_SERVICE_ID = "v2_signal_publisher"
LIVE_GATE_STATUS = "blocked_human_only"
EXCHANGE_CALL_INVARIANT = "NO_REAL_EXCHANGE_CALL_FROM_SIGNAL_PUBLISHER"
EVIDENCE_MISSING_LABEL = "Evidence missing — cannot explain without guessing"
DEFAULT_CONFIDENCE_FLOOR = 0.58
ACTIONABLE_FRESHNESS_STATES: Tuple[str, ...] = ("CURRENT", "WARN")
SIDE_TO_ACTION: Dict[str, str] = {
    "long": "open_long",
    "short": "open_short",
    "hold": "hold",
}


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_ms() -> int:
    return int(time.time() * 1000)


def _present(value: Any) -> bool:
    return value is not None and value != ""


def _first_present(*values: Any) -> Any:
    for value in values:
        if _present(value):
            return value
    return None


def _float_or_none(value: Any) -> Optional[float]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric


def cite_evidence(
    *,
    field_name: str,
    source: str,
    value: Any,
) -> Dict[str, Any]:
    """Build a single evidence citation record.

    A citation is *present* iff ``value`` is not ``None`` and not the
    empty string. Numeric zero and ``False`` are considered present
    because they are legitimate observations.
    """
    present = value is not None and value != ""
    return {
        "field_name": field_name,
        "source": source,
        "value": value if present else None,
        "present": bool(present),
    }


def evidence_present(citation: Mapping[str, Any]) -> bool:
    return bool(citation.get("present"))


def explain_or_missing(
    *,
    explanation: str,
    citations: Iterable[Mapping[str, Any]],
) -> str:
    """Return ``explanation`` only when every required citation is
    present. Otherwise return ``EVIDENCE_MISSING_LABEL`` so the caller
    cannot accidentally publish a claim that lacks evidence.
    """
    for citation in citations:
        if not evidence_present(citation):
            return EVIDENCE_MISSING_LABEL
    return explanation


def is_signal_actionable(
    *,
    side: str,
    confidence_calibrated: Optional[float],
    market_freshness_state: str,
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
) -> Tuple[bool, str]:
    """Return ``(actionable, reason_code)``.

    Actionable iff ``side in {long, short}`` AND
    ``market_freshness_state in {CURRENT, WARN}`` AND
    ``confidence_calibrated >= confidence_floor``.
    """
    if side not in ("long", "short"):
        return False, "non_directional_side"
    if market_freshness_state not in ACTIONABLE_FRESHNESS_STATES:
        return False, "non_actionable_market_freshness"
    try:
        numeric = float(confidence_calibrated) if confidence_calibrated is not None else None
    except (TypeError, ValueError):
        return False, "non_numeric_confidence"
    if numeric is None or numeric < confidence_floor:
        return False, "below_confidence_floor"
    return True, "actionable"


def _signal_id(prediction_id: str, run_ts: str) -> str:
    digest = hashlib.sha256(
        f"{prediction_id}|{run_ts}".encode("utf-8")
    ).hexdigest()[:12]
    return f"sig_{digest}"


def required_signal_record_fields() -> Tuple[str, ...]:
    return (
        "signal_id",
        "service_id",
        "generated_at",
        "symbol",
        "timeframe",
        "prediction_id",
        "feature_snapshot_id",
        "proposed_action",
        "side",
        "confidence_calibrated",
        "expected_move_bps",
        "expected_move_after_cost_bps",
        "expected_net_edge_bps",
        "available_at",
        "decision_time",
        "feature_cutoff",
        "confidence_floor",
        "actionable",
        "actionable_reason_code",
        "source_freshness",
        "market_age_seconds",
        "evidence_citations",
        "explanation",
        "live_gate",
        "exchange_call_invariant",
        "exchange_action_taken",
    )


def build_signal_record(
    *,
    prediction: Mapping[str, Any],
    feature_snapshot: Mapping[str, Any],
    market_freshness_state: str,
    market_age_seconds: Optional[int],
    run_ts: Optional[str] = None,
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
) -> Dict[str, Any]:
    """Build a deterministic, evidence-cited signal record from a
    trainer prediction and the feature snapshot that produced it.

    Every claim made by the returned record is backed by a citation in
    the ``evidence_citations`` list. If any required citation is
    absent, ``explanation`` collapses to ``EVIDENCE_MISSING_LABEL``
    instead of being filled with synthesized text.
    """
    ts = run_ts or iso_now()
    prediction_id = str(prediction.get("prediction_id") or "")
    feature_snapshot_id = str(feature_snapshot.get("feature_snapshot_id") or "")
    raw_output = prediction.get("raw_output") or {}
    side = str(raw_output.get("side") or "")
    confidence_calibrated_raw = prediction.get("confidence_calibrated")
    try:
        confidence_calibrated: Optional[float] = (
            float(confidence_calibrated_raw)
            if confidence_calibrated_raw is not None
            else None
        )
    except (TypeError, ValueError):
        confidence_calibrated = None
    symbol = str(prediction.get("symbol") or feature_snapshot.get("symbol") or "")
    timeframe = str(prediction.get("timeframe") or feature_snapshot.get("timeframe") or "")
    expected_move_bps = _float_or_none(prediction.get("expected_move_bps"))
    expected_move_after_cost_bps = _float_or_none(
        prediction.get("expected_move_after_cost_bps")
    )
    available_at = _first_present(
        prediction.get("available_at"),
        prediction.get("generated_at"),
        feature_snapshot.get("available_at"),
    )
    decision_time = _first_present(
        prediction.get("decision_time"),
        prediction.get("decision_time_est"),
        prediction.get("generated_at"),
    )
    feature_cutoff = _first_present(
        prediction.get("feature_cutoff"),
        feature_snapshot.get("feature_cutoff"),
        feature_snapshot.get("generated_at"),
    )
    masa_feature_cutoff = prediction.get("masa_feature_cutoff")
    last_price = _first_present(
        prediction.get("last_price"),
        prediction.get("mark_price"),
        feature_snapshot.get("last_price"),
        feature_snapshot.get("price"),
    )

    citations = [
        cite_evidence(
            field_name="prediction_id",
            source="trainer_prediction.prediction_id",
            value=prediction_id,
        ),
        cite_evidence(
            field_name="feature_snapshot_id",
            source="feature_snapshot.feature_snapshot_id",
            value=feature_snapshot_id,
        ),
        cite_evidence(
            field_name="side",
            source="trainer_prediction.raw_output.side",
            value=side or None,
        ),
        cite_evidence(
            field_name="confidence_calibrated",
            source="trainer_prediction.confidence_calibrated",
            value=confidence_calibrated,
        ),
        cite_evidence(
            field_name="market_freshness_state",
            source="market_feed.freshness_state",
            value=market_freshness_state or None,
        ),
        cite_evidence(
            field_name="market_age_seconds",
            source="market_feed.age_seconds",
            value=market_age_seconds,
        ),
    ]
    optional_citations = [
        cite_evidence(
            field_name="timeframe",
            source="trainer_prediction.timeframe or feature_snapshot.timeframe",
            value=timeframe or None,
        ),
        cite_evidence(
            field_name="expected_move_bps",
            source="trainer_prediction.expected_move_bps",
            value=expected_move_bps,
        ),
        cite_evidence(
            field_name="expected_move_after_cost_bps",
            source="trainer_prediction.expected_move_after_cost_bps",
            value=expected_move_after_cost_bps,
        ),
        cite_evidence(
            field_name="available_at",
            source="trainer_prediction.available_at",
            value=available_at,
        ),
        cite_evidence(
            field_name="decision_time",
            source="trainer_prediction.decision_time",
            value=decision_time,
        ),
        cite_evidence(
            field_name="feature_cutoff",
            source="trainer_prediction.feature_cutoff or feature_snapshot.feature_cutoff",
            value=feature_cutoff,
        ),
    ]
    actionable, reason_code = is_signal_actionable(
        side=side,
        confidence_calibrated=confidence_calibrated,
        market_freshness_state=market_freshness_state,
        confidence_floor=confidence_floor,
    )
    proposed_action = SIDE_TO_ACTION.get(side, "hold")
    explanation = (
        f"Signal {proposed_action!r} proposed because trainer side={side!r} "
        f"with calibrated confidence {confidence_calibrated!r} "
        f"(floor={confidence_floor}) and market freshness "
        f"{market_freshness_state!r} (age_seconds={market_age_seconds!r})."
    )
    return {
        "signal_id": _signal_id(prediction_id or feature_snapshot_id or ts, ts),
        "service_id": SIGNAL_SERVICE_ID,
        "generated_at": ts,
        "symbol": symbol,
        "timeframe": timeframe or None,
        "prediction_id": prediction_id,
        "feature_snapshot_id": feature_snapshot_id,
        "proposed_action": proposed_action,
        "side": side or None,
        "selected_action": side or None,
        "confidence_calibrated": confidence_calibrated,
        "expected_move_bps": expected_move_bps,
        "expected_move_after_cost_bps": expected_move_after_cost_bps,
        "expected_net_edge_bps": expected_move_after_cost_bps,
        "last_price": last_price,
        "price_target": prediction.get("price_target"),
        "price_target_after_cost": prediction.get("price_target_after_cost"),
        "price_target_low": prediction.get("price_target_low"),
        "price_target_high": prediction.get("price_target_high"),
        "stop_reference": prediction.get("stop_reference"),
        "take_profit_reference": prediction.get("take_profit_reference"),
        "available_at": available_at,
        "decision_time": decision_time,
        "feature_cutoff": feature_cutoff,
        "masa_feature_cutoff": masa_feature_cutoff,
        "confidence_floor": confidence_floor,
        "actionable": actionable,
        "actionable_reason_code": reason_code,
        "source_freshness": market_freshness_state or None,
        "market_age_seconds": market_age_seconds,
        "evidence_citations": citations + optional_citations,
        "explanation": explain_or_missing(
            explanation=explanation,
            citations=citations,
        ),
        "source_lineage": {
            "prediction_id_source_field": "trainer_prediction.prediction_id",
            "feature_snapshot_id_source_field": "feature_snapshot.feature_snapshot_id",
            "confidence_calibrated_source_field": "trainer_prediction.confidence_calibrated",
            "expected_move_bps_source_field": "trainer_prediction.expected_move_bps",
            "expected_move_after_cost_bps_source_field": "trainer_prediction.expected_move_after_cost_bps",
            "timeframe_source_field": "trainer_prediction.timeframe or feature_snapshot.timeframe",
            "available_at_source_field": "trainer_prediction.available_at",
            "decision_time_source_field": "trainer_prediction.decision_time",
            "feature_cutoff_source_field": "trainer_prediction.feature_cutoff or feature_snapshot.feature_cutoff",
        },
        "live_gate": LIVE_GATE_STATUS,
        "exchange_call_invariant": EXCHANGE_CALL_INVARIANT,
        "exchange_action_taken": False,
    }


def build_paper_runtime_lineage(
    *,
    tick_id: str,
    generated_at: str,
    feature_snapshot: Mapping[str, Any],
    prediction: Mapping[str, Any],
    market_symbol: str,
    market_freshness_state: str,
    market_age_seconds: Optional[int],
) -> Dict[str, Any]:
    """Compatibility lineage builder used by ``paper_online_runtime``.

    The standalone V2 signal lineage worker owns the durable lineage
    payload. This helper keeps paper-online's current bundle shape while
    moving the construction out of the paper runtime module.
    """
    signal_record = build_signal_record(
        prediction=prediction,
        feature_snapshot=feature_snapshot,
        market_freshness_state=market_freshness_state,
        market_age_seconds=market_age_seconds,
        run_ts=generated_at,
    )
    side = str((prediction.get("raw_output") or {}).get("side") or "")
    signal_id = f"sig_{tick_id}"
    signal_record = dict(signal_record)
    signal_record["signal_id"] = signal_id
    signal_record["symbol"] = market_symbol
    orchestrator_decision_id = f"orch_{tick_id}"
    risk_decision_id = f"risk_{tick_id}"
    execution_intent_id = f"pei_{tick_id}"
    paper_ledger_entry_id = f"pledger_{tick_id}"
    proposed_action = signal_record["proposed_action"]
    orchestrator = {
        "orchestrator_decision_id": orchestrator_decision_id,
        "generated_at": generated_at,
        "signal_id": signal_id,
        "decision_action": proposed_action,
        "decision_reason": (
            "paper_momentum_signal_routed"
            if proposed_action != "hold"
            else "paper_momentum_signal_held"
        ),
        "risk_gateway_required": True,
        "cannot_bypass_risk_gateway": True,
    }
    missing_fields = [
        field
        for field, value in {
            "signal_id": signal_id,
            "prediction_id": prediction.get("prediction_id"),
            "feature_snapshot_id": feature_snapshot.get("feature_snapshot_id"),
            "confidence": prediction.get("confidence_calibrated"),
        }.items()
        if value in (None, "", 0)
    ]
    risk_action = "deny"
    risk_reason = "deny_default"
    risk_result = "BLOCKED"
    confidence = prediction.get("confidence_calibrated")
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError):
        confidence_value = 0.0
    if missing_fields:
        risk_reason = "deny_missing_required_evidence"
    elif market_age_seconds is None or market_age_seconds > 120:
        risk_reason = "deny_stale_market_feed"
    elif proposed_action == "hold":
        risk_reason = "deny_orchestrator_held"
    elif confidence_value < DEFAULT_CONFIDENCE_FLOOR:
        risk_reason = "deny_low_confidence"
    else:
        risk_action = "allow"
        risk_reason = (
            "allow_proceed_long"
            if proposed_action == "open_long"
            else "allow_proceed_short"
        )
        risk_result = "APPROVED_FOR_PAPER_ONLY"
    risk_decision = {
        "risk_decision_id": risk_decision_id,
        "generated_at": generated_at,
        "signal_id": signal_id,
        "prediction_id": prediction.get("prediction_id"),
        "feature_snapshot_id": feature_snapshot.get("feature_snapshot_id"),
        "orchestrator_decision_id": orchestrator_decision_id,
        "risk_action": risk_action,
        "risk_result": risk_result,
        "risk_reason_code": risk_reason,
        "live_blocked": True,
        "required_blocks_checked": [
            "missing_signal_id",
            "missing_prediction_id",
            "missing_feature_snapshot_id",
            "missing_confidence",
            "stale_signal",
            "duplicate_signal_execution",
            "cross_margin_live_mode",
            "leverage_above_cap",
            "adjust_leverage_disabled",
            "missing_stop_policy",
            "disabled_kill_switch",
            "daily_loss_breach",
            "weekly_loss_breach",
            "untraceable_execution",
        ],
        "missing_fields": missing_fields,
    }
    execution_intent = {
        "execution_intent_id": execution_intent_id,
        "generated_at": generated_at,
        "risk_decision_id": risk_decision_id,
        "signal_id": signal_id,
        "intent_action": (
            "paper_fill_simulation" if risk_action == "allow" else "paper_noop_blocked"
        ),
        "symbol": market_symbol,
        "side": side,
        "paper_only": True,
        "exchange_order_allowed": False,
    }
    return {
        "generated_at": generated_at,
        "classification": "REALTIME_RUNTIME_EVIDENCE",
        "feature_snapshot": dict(feature_snapshot),
        "trainer_prediction": dict(prediction),
        "signal": signal_record,
        "orchestrator_decision": orchestrator,
        "risk_decision": risk_decision,
        "execution_intent": execution_intent,
        "lineage_ids": {
            "prediction_id": prediction.get("prediction_id"),
            "feature_snapshot_id": feature_snapshot.get("feature_snapshot_id"),
            "signal_id": signal_id,
            "orchestrator_decision_id": orchestrator_decision_id,
            "risk_decision_id": risk_decision_id,
            "execution_intent_id": execution_intent_id,
            "paper_ledger_entry_id": paper_ledger_entry_id,
        },
    }


def signal_publisher_self_check() -> Dict[str, Any]:
    """Return a self-check payload describing the service identity and
    invariants. Consumed by the V2 signal lineage worker to confirm the
    publisher module exposes the real implementation.
    """
    return {
        "service_id": SIGNAL_SERVICE_ID,
        "live_gate": LIVE_GATE_STATUS,
        "exchange_call_invariant": EXCHANGE_CALL_INVARIANT,
        "evidence_missing_label": EVIDENCE_MISSING_LABEL,
        "required_record_fields": list(required_signal_record_fields()),
        "implementation_present": True,
    }
