"""A+ zero-tolerance trade gate (Phase 8).

A paper candidate is A+ only when every check agrees; anything else stays
no-trade or shadow-only. This is the gate that a future operator-approved
live flip would reuse — no non-A+ row can ever become a live candidate.

Checks (all fail-closed; a missing input is a rejection, never a pass):
    1.  trainer online learning active
    2.  side bucket positive (expectancy > 0 with evidence, side gate allows)
    3.  regime aligned (adaptive regime gate + strategy/regime permission matrix)
    4.  HTF aligned (multi-timeframe alignment score for the side)
    5.  trade tape confirms the side
    6.  microstructure trust confirms
    7.  risk allows (runtime risk/pre-trade result passed in by the loop)
    8.  allocator allows (allocation payload passed in by the loop)
    9.  exit plan valid (ATR present so stop/trailing/MFE protection computable)
    10. cost evidence production-grade
    11. no quarantine bucket active
    12. no stale/missing critical feature on the prediction row
    13. no recent high-confidence loss in the same bucket

Paper-only. Places no orders. Never mutates exchange state.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from v2.backend.app.services.adaptive_regime_gate.permission_matrix import (
    strategy_allowed_in_regime,
)
from v2.backend.app.services.htf_context.service import multi_timeframe_alignment_score
from v2.backend.app.services.microstructure_trust.trust_score import (
    FINAL_A_PLUS_MIN_COMPOSITE_TRUST,
)
from v2.backend.app.services.paper_trade_management.side_performance import (
    SideGateConfig,
    evaluate_side_gate,
)
from v2.backend.app.services.trade_tape.service import order_flow_confirms_side

A_PLUS_GATE_SCHEMA_VERSION = "v2_a_plus_trade_gate_v1"
A_PLUS_GATE_STATUS_REDIS_KEY = "v2:paper:a_plus_gate:status"

REGIME_GATE_KEY_TEMPLATE = "v2:regime:gate:{symbol}:{timeframe}"
HTF_CONTEXT_KEY_TEMPLATE = "v2:context:htf:{symbol}"
CROSS_ASSET_CONTEXT_KEY = "v2:context:cross_asset"
TRADE_TAPE_KEY_TEMPLATE = "v2:market:trade_tape_features:{symbol}"
MICROSTRUCTURE_TRUST_KEY_TEMPLATE = "v2:microstructure:trust_score:{symbol}:{timeframe}"
TRAINER_METRICS_KEY = "v2:trainer:hybrid_cuda:metrics"
SIDE_PERFORMANCE_KEY = "v2:paper:side_performance"
FEEDBACK_OUTCOMES_KEY = "v2:trainer:feedback:outcomes"

CHECKS = (
    "trainer_online_learning_active",
    "side_bucket_positive",
    "regime_aligned",
    "htf_aligned",
    "trade_tape_confirms",
    "microstructure_trust_confirms",
    "risk_allows",
    "allocator_allows",
    "exit_plan_valid",
    "cost_evidence_production_grade",
    "no_quarantine_bucket",
    "no_stale_or_missing_critical_feature",
    "no_recent_high_confidence_loss_in_bucket",
)

REQUIRED_MICROSTRUCTURE_CONFIRMATION_FIELDS = (
    "feed_integrity_pass",
    "sequence_gap_free",
    "latency_within_bound",
    "trade_tape_confirmation_pass",
    "cross_venue_confirmation_pass",
    "liquidation_sweep_risk_acceptable",
    "oi_funding_long_short_confirmation_pass",
    "real_spread_depth_cost_evidence_pass",
)


@dataclass(frozen=True)
class APlusGateConfig:
    min_htf_alignment_score: float = 0.25
    min_microstructure_trust_score: float = FINAL_A_PLUS_MIN_COMPOSITE_TRUST
    # Context freshness: regime/tape/HTF payloads older than this are unusable.
    max_context_age_seconds: float = 1800.0
    # Recent high-confidence loss lookback.
    high_confidence_threshold: float = 0.70
    recent_loss_lookback_hours: float = 24.0
    # Side bucket must be positive with at least this many closed trades;
    # fewer trades on a side is still not A+ (exploration stays paper-only
    # through the ordinary non-A+ paper path if the side gate allows it).
    min_side_trades_for_a_plus: int = 3
    side_gate: SideGateConfig = SideGateConfig()


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _read_json(redis_client: Any, key: str) -> Any:
    if redis_client is None:
        return None
    try:
        raw = redis_client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _fresh(payload: Any, *, max_age_seconds: float, now: datetime) -> bool:
    if not isinstance(payload, Mapping):
        return False
    generated = _parse_utc(
        payload.get("generated_utc") or payload.get("generated_at") or payload.get("generated_est")
    )
    if generated is None:
        return False
    return (now - generated).total_seconds() <= max_age_seconds


def load_a_plus_context(
    redis_client: Any,
    *,
    symbol: str,
    timeframe: str,
) -> dict[str, Any]:
    """Read every Redis-backed input the gate needs, in one place."""
    sym = (symbol or "").upper()
    tf = (timeframe or "").strip()
    microstructure_lookup_keys = [
        MICROSTRUCTURE_TRUST_KEY_TEMPLATE.format(symbol=sym, timeframe=tf),
        MICROSTRUCTURE_TRUST_KEY_TEMPLATE.format(symbol=sym, timeframe="1m"),
        f"v2:microstructure:feed_quality:binance:{sym}",
    ]
    microstructure_trust = None
    microstructure_source_key = None
    for key in microstructure_lookup_keys:
        payload = _read_json(redis_client, key)
        if isinstance(payload, Mapping):
            microstructure_trust = payload
            microstructure_source_key = key
            break
    return {
        "regime_decision": _read_json(
            redis_client, REGIME_GATE_KEY_TEMPLATE.format(symbol=sym, timeframe=tf)
        ),
        "htf_context": _read_json(redis_client, HTF_CONTEXT_KEY_TEMPLATE.format(symbol=sym)),
        "cross_asset": _read_json(redis_client, CROSS_ASSET_CONTEXT_KEY),
        "trade_tape": _read_json(redis_client, TRADE_TAPE_KEY_TEMPLATE.format(symbol=sym)),
        "microstructure_trust": microstructure_trust,
        "microstructure_trust_lookup_keys": microstructure_lookup_keys,
        "microstructure_trust_source_key": microstructure_source_key,
        "trainer_metrics": _read_json(redis_client, TRAINER_METRICS_KEY),
        "side_performance": _read_json(redis_client, SIDE_PERFORMANCE_KEY),
        "feedback_rows": _read_json(redis_client, FEEDBACK_OUTCOMES_KEY),
    }


def _check(passed: bool | None, reason: str) -> dict[str, Any]:
    # None (missing evidence) is fail-closed but distinguishable for the matrix.
    return {
        "passed": passed is True,
        "missing_evidence": passed is None,
        "reason": reason,
    }


def _trainer_learning_check(trainer_metrics: Any) -> dict[str, Any]:
    if not isinstance(trainer_metrics, Mapping):
        return _check(None, "TRAINER_METRICS_MISSING")
    training = trainer_metrics.get("training")
    metrics = training.get("metrics") if isinstance(training, Mapping) else None
    if not isinstance(metrics, Mapping):
        return _check(None, "TRAINER_TRAINING_METRICS_MISSING")
    status = str(metrics.get("online_learning_status") or "")
    trusted = _finite(metrics.get("trusted_rows_loaded")) or 0
    last_update = metrics.get("last_successful_weight_update_at")
    active = status in {"WEIGHTS_UPDATING", "ACTIVE"} and trusted > 0 and bool(last_update)
    return _check(
        active,
        f"online_learning_status={status};trusted_rows={int(trusted)};last_update={last_update}",
    )


def _side_bucket_check(
    side_performance: Any,
    *,
    side: str,
    confidence_calibrated: float | None,
    config: APlusGateConfig,
) -> dict[str, Any]:
    if not isinstance(side_performance, Mapping):
        return _check(None, "SIDE_PERFORMANCE_MISSING")
    gate = evaluate_side_gate(
        side_performance,
        side=side,
        confidence_calibrated=confidence_calibrated,
        config=config.side_gate,
    )
    buckets = side_performance.get("sides")
    bucket = buckets.get(side.upper()) if isinstance(buckets, Mapping) else None
    if not isinstance(bucket, Mapping):
        return _check(None, f"SIDE_BUCKET_MISSING:{side.upper()}")
    trade_count = int(_finite(bucket.get("trade_count")) or 0)
    expectancy = _finite(bucket.get("expectancy_bps"))
    if not gate.get("allowed", False):
        return _check(False, f"SIDE_GATE_BLOCKED:{';'.join(gate.get('reasons') or [])}")
    # Enough evidence: expectancy must be strictly positive.
    if trade_count >= config.side_gate.min_trades_for_expectancy_block:
        if expectancy is None or expectancy <= 0:
            return _check(False, f"SIDE_EXPECTANCY_NOT_POSITIVE:{expectancy};trades={trade_count}")
        return _check(True, f"side={side.upper()};expectancy_bps={expectancy:.2f};trades={trade_count}")
    if trade_count >= config.min_side_trades_for_a_plus and expectancy is not None and expectancy > 0:
        return _check(True, f"side={side.upper()};expectancy_bps={expectancy:.2f};trades={trade_count}")
    # Sparse side: bootstrap exploration window. The side gate above already
    # enforces the per-side calibration-aware confidence floor, and every other
    # A+ check still has to agree — this is not a threshold reduction, it is
    # the only path by which a starved side (LONG) can ever build a bucket.
    if expectancy is not None and expectancy <= 0 and trade_count >= config.min_side_trades_for_a_plus:
        return _check(False, f"SIDE_EXPECTANCY_NOT_POSITIVE:{expectancy};trades={trade_count}")
    return _check(True, f"SIDE_EXPLORATION_WINDOW:side={side.upper()};trades={trade_count}")


def _regime_check(
    *,
    regime_decision: Any,
    strategy_id: str,
    side: str,
    trade_tape: Any,
    microstructure_trust: Any,
    now: datetime,
    config: APlusGateConfig,
) -> dict[str, Any]:
    if not isinstance(regime_decision, Mapping):
        return _check(None, "REGIME_DECISION_MISSING")
    if not _fresh(regime_decision, max_age_seconds=config.max_context_age_seconds, now=now):
        return _check(None, "REGIME_DECISION_STALE")
    if regime_decision.get("fail_closed") is True:
        return _check(False, "REGIME_FAIL_CLOSED_ON_MISSING_INPUTS")
    verdict = strategy_allowed_in_regime(
        strategy_id=strategy_id,
        side=side,
        regime_decision=regime_decision,
        trade_tape=trade_tape if isinstance(trade_tape, Mapping) else None,
        microstructure_trust=microstructure_trust if isinstance(microstructure_trust, Mapping) else None,
    )
    allowed = verdict.get("allowed") is True
    verdict_reasons = verdict.get("reasons") if isinstance(verdict.get("reasons"), list) else []
    return _check(
        allowed,
        f"regime={regime_decision.get('regime')};{';'.join(str(reason) for reason in verdict_reasons)}",
    )


def _htf_check(
    *,
    htf_context: Any,
    cross_asset: Any,
    side: str,
    entry_timeframe_trend: str | None,
    now: datetime,
    config: APlusGateConfig,
) -> dict[str, Any]:
    if not isinstance(htf_context, Mapping):
        return _check(None, "HTF_CONTEXT_MISSING")
    if not _fresh(htf_context, max_age_seconds=config.max_context_age_seconds, now=now):
        return _check(None, "HTF_CONTEXT_STALE")
    alignment = multi_timeframe_alignment_score(
        side=side,
        entry_timeframe_trend=entry_timeframe_trend,
        htf_context=htf_context,
        cross_asset=cross_asset if isinstance(cross_asset, Mapping) else None,
    )
    score = _finite(alignment.get("alignment_score"))
    if score is None:
        return _check(None, f"HTF_ALIGNMENT_UNAVAILABLE:{alignment.get('reason')}")
    passed = score >= config.min_htf_alignment_score
    return _check(passed, f"alignment_score={score:.3f};threshold={config.min_htf_alignment_score}")


def _tape_check(*, trade_tape: Any, side: str, now: datetime, config: APlusGateConfig) -> dict[str, Any]:
    if not isinstance(trade_tape, Mapping):
        return _check(None, "TRADE_TAPE_MISSING")
    if not _fresh(trade_tape, max_age_seconds=config.max_context_age_seconds, now=now):
        return _check(None, "TRADE_TAPE_STALE")
    confirms, reason = order_flow_confirms_side(trade_tape, side)
    if confirms is None:
        return _check(None, reason)
    return _check(confirms, reason)


def _microstructure_check(*, microstructure_trust: Any, config: APlusGateConfig) -> dict[str, Any]:
    if not isinstance(microstructure_trust, Mapping):
        return _check(None, "MICROSTRUCTURE_TRUST_MISSING")
    if (
        microstructure_trust.get("public_book_can_approve_trade_alone") is True
        or microstructure_trust.get("public_orderbook_can_produce_final_a_plus") is True
    ):
        return _check(False, "PUBLIC_ORDERBOOK_TRUST_CANNOT_APPROVE_FINAL_A_PLUS")
    score = _finite(microstructure_trust.get("composite_microstructure_trust_score"))
    if score is None:
        return _check(None, "COMPOSITE_MICROSTRUCTURE_TRUST_SCORE_MISSING")
    if score > 1.0:
        score = score / 100.0
    tier = str(microstructure_trust.get("orderbook_trust_tier") or "").upper()
    action = str(microstructure_trust.get("microstructure_action") or "").upper()
    if (
        tier == "REDUCED_SIZE"
        or action == "REDUCE_SIZE"
        or microstructure_trust.get("bootstrap_reduced_size_paper_only") is True
        or microstructure_trust.get("reduced_size_counts_as_final_a_plus") is True
    ):
        return _check(False, f"REDUCED_SIZE_BOOTSTRAP_NOT_FINAL_A_PLUS:score={score:.3f}")
    explicit_missing = microstructure_trust.get("composite_confirmation_missing_fields")
    if isinstance(explicit_missing, list) and explicit_missing:
        missing = [str(field) for field in explicit_missing]
    else:
        missing = [
            field
            for field in REQUIRED_MICROSTRUCTURE_CONFIRMATION_FIELDS
            if microstructure_trust.get(field) is not True
        ]
    if missing:
        return _check(None, f"COMPOSITE_CONFIRMATION_MISSING:{','.join(missing[:5])}")
    passed = score >= config.min_microstructure_trust_score
    return _check(
        passed,
        f"composite_trust_score={score:.3f};threshold={config.min_microstructure_trust_score}",
    )


def _risk_check(risk_result: Any) -> dict[str, Any]:
    if not isinstance(risk_result, Mapping):
        return _check(None, "RISK_RESULT_MISSING")
    allowed = risk_result.get("allowed")
    if allowed is None:
        action = str(risk_result.get("risk_action") or risk_result.get("action") or "").lower()
        if action:
            allowed = action in {"allow", "approved"}
    if allowed is None:
        return _check(None, "RISK_DECISION_UNREADABLE")
    reasons = risk_result.get("reasons") or risk_result.get("block_reasons") or []
    return _check(bool(allowed), f"risk_allowed={bool(allowed)};reasons={list(reasons)[:4]}")


def _allocator_check(allocation: Any) -> dict[str, Any]:
    if not isinstance(allocation, Mapping):
        return _check(None, "ALLOCATION_MISSING")
    blocked = allocation.get("blocked")
    approved = allocation.get("approved")
    decision = str(allocation.get("allocator_decision") or "").upper()
    size = None
    for field in (
        "approved_notional_usd",
        "recommended_notional_usd",
        # adaptive_capital_allocator AllocationResult / paper intents carry
        # the target in these names (usdt spelling included).
        "target_notional_usdt",
        "target_notional_usd",
        "allocated_notional_usd",
        "order_size_usd",
    ):
        size = _finite(allocation.get(field))
        if size is not None:
            break
    if blocked is True or approved is False or decision.startswith(("DENY", "BLOCK")):
        return _check(False, f"ALLOCATOR_BLOCKED:{allocation.get('block_reason') or decision}")
    if size is None or size <= 0:
        return _check(None, "ALLOCATOR_SIZE_MISSING_OR_ZERO")
    return _check(True, f"allocator_size_usd={size:.2f};decision={decision or 'n/a'}")


def _exit_plan_check(*, atr_bps: float | None, prediction_row: Any) -> dict[str, Any]:
    if atr_bps is None or atr_bps <= 0:
        return _check(None, "ATR_MISSING_EXIT_PLAN_NOT_COMPUTABLE")
    expected = None
    if isinstance(prediction_row, Mapping):
        expected = _finite(prediction_row.get("expected_move_after_cost_bps"))
    if expected is None:
        return _check(None, "EXPECTED_MOVE_MISSING_EXIT_THESIS_NOT_COMPUTABLE")
    return _check(True, f"atr_bps={atr_bps:.2f};expected_move_after_cost_bps={expected:.2f}")


def _cost_evidence_check(intent: Any) -> dict[str, Any]:
    if not isinstance(intent, Mapping):
        return _check(None, "INTENT_MISSING")
    status = str(intent.get("runtime_cost_capture_status") or "")
    flag = intent.get("production_grade_cost_flag")
    passed = status == "PRODUCTION_GRADE_COST_CAPTURE" or flag is True
    if not status and flag is None:
        return _check(None, "COST_EVIDENCE_MISSING")
    return _check(passed, f"runtime_cost_capture_status={status or flag}")


def _candidate_quarantine_keys(
    *,
    symbol: str,
    timeframe: str,
    side: str,
    strategy_id: str,
    regime_label: str | None,
) -> set[str]:
    """Bucket keys this candidate belongs to, mirroring the paper loop's
    _paper_performance_quarantine_group_keys formats."""
    side_l = (side or "").lower()
    strategy = (strategy_id or "").strip()
    tf = (timeframe or "").strip()
    regime = (regime_label or "").strip()
    keys: set[str] = set()
    if side_l:
        keys.add(f"side:{side_l}")
    if regime:
        keys.add(f"regime:{regime}")
    if tf:
        keys.add(f"timeframe:{tf}")
    if side_l and tf:
        keys.add(f"side_timeframe:{side_l}|{tf}")
    if strategy and regime:
        keys.add(f"strategy_regime:{strategy}|{regime}")
    if strategy and side_l and tf:
        keys.add(f"strategy_side_timeframe:{strategy}|{side_l}|{tf}")
    if symbol:
        keys.add(f"{symbol.upper()}|{tf}|{strategy}|{regime}")
    return keys


def _quarantine_check(
    bucket_quarantine_status: Any,
    *,
    symbol: str = "",
    timeframe: str = "",
    side: str = "",
    strategy_id: str = "",
    regime_label: str | None = None,
) -> dict[str, Any]:
    """Per-candidate bucket quarantine check (A+ goal Phase 13).

    Quarantine is bucket-scoped ("same bad bucket cannot re-enter"): a
    candidate fails only when one of ITS bucket keys is blocked. The prior
    global behaviour starved A+ supply permanently once any bucket was
    quarantined. When the payload carries no blocked_bucket_keys while
    quarantine is active, every candidate fails closed (old behaviour).
    """
    if bucket_quarantine_status is None:
        return _check(None, "BUCKET_QUARANTINE_STATUS_MISSING")
    if isinstance(bucket_quarantine_status, Mapping):
        status = str(bucket_quarantine_status.get("status") or "")
        quarantined = bucket_quarantine_status.get("quarantine_active")
        if quarantined is None:
            quarantined = status.upper() not in {"", "NONE", "CLEAR", "INACTIVE", "NO_QUARANTINE"}
        if not quarantined:
            return _check(True, f"bucket_quarantine_status={status or 'clear'}")
        blocked_raw = bucket_quarantine_status.get("blocked_bucket_keys")
        if not isinstance(blocked_raw, (list, tuple, set)) or not blocked_raw:
            return _check(False, f"bucket_quarantine_status={status}:blocked_keys_unavailable_fail_closed")
        blocked = {str(key) for key in blocked_raw}
        candidate_keys = _candidate_quarantine_keys(
            symbol=symbol,
            timeframe=timeframe,
            side=side,
            strategy_id=strategy_id,
            regime_label=regime_label,
        )
        hits = sorted(blocked & candidate_keys)
        if hits:
            return _check(False, f"candidate_bucket_quarantined:{','.join(hits[:3])}")
        return _check(True, "candidate_buckets_clear_of_quarantine")
    text = str(bucket_quarantine_status).upper()
    return _check(text in {"NONE", "CLEAR", "INACTIVE", "NO_QUARANTINE"}, f"bucket_quarantine_status={text}")


def _feature_integrity_check(prediction_row: Any) -> dict[str, Any]:
    if not isinstance(prediction_row, Mapping):
        return _check(None, "PREDICTION_ROW_MISSING")
    missing = int(_finite(prediction_row.get("missing_feature_count")) or 0)
    stale = int(_finite(prediction_row.get("stale_feature_count")) or 0)
    freshness = str(prediction_row.get("feature_freshness_state") or "").upper()
    if freshness and freshness != "CURRENT":
        return _check(False, f"FEATURE_FRESHNESS_{freshness}")
    if missing > 0:
        return _check(False, f"MISSING_CRITICAL_FEATURES:{missing}")
    if stale > 0:
        return _check(False, f"STALE_FEATURES:{stale}")
    return _check(True, "feature_snapshot_clean")


def _bucket_key(symbol: str, timeframe: str, side: str, strategy_id: str) -> str:
    return f"{(symbol or '').upper()}|{timeframe}|{(strategy_id or '').lower()}|{(side or '').lower()}"


def _recent_high_confidence_loss_check(
    feedback_rows: Any,
    *,
    symbol: str,
    timeframe: str,
    side: str,
    strategy_id: str,
    now: datetime,
    config: APlusGateConfig,
) -> dict[str, Any]:
    if not isinstance(feedback_rows, list):
        return _check(None, "FEEDBACK_ROWS_MISSING")
    bucket = _bucket_key(symbol, timeframe, side, strategy_id)
    cutoff = now - timedelta(hours=config.recent_loss_lookback_hours)
    for row in feedback_rows:
        if not isinstance(row, Mapping):
            continue
        row_bucket = _bucket_key(
            str(row.get("symbol") or ""),
            str(row.get("timeframe") or ""),
            str(row.get("action") or row.get("selected_action") or ""),
            str(row.get("strategy_id") or row.get("strategy_family") or ""),
        )
        if row_bucket != bucket:
            continue
        confidence = _finite(row.get("confidence_calibrated"))
        pnl = _finite(row.get("realized_net_pnl_bps"))
        if pnl is None:
            pnl = _finite(row.get("realized_pnl_bps"))
        exit_time = _parse_utc(str(row.get("exit_time") or ""))
        if (
            confidence is not None
            and confidence >= config.high_confidence_threshold
            and pnl is not None
            and pnl < 0
            and (exit_time is None or exit_time >= cutoff)
        ):
            return _check(
                False,
                f"RECENT_HIGH_CONFIDENCE_LOSS:conf={confidence:.2f};pnl_bps={pnl:.1f};exit={row.get('exit_time')}",
            )
    return _check(True, f"no_high_confidence_loss_in_bucket_last_{config.recent_loss_lookback_hours}h")


def evaluate_a_plus_candidate(
    *,
    symbol: str,
    timeframe: str,
    side: str,
    strategy_id: str,
    confidence_calibrated: float | None,
    atr_bps: float | None,
    entry_timeframe_trend: str | None = None,
    prediction_row: Mapping[str, Any] | None = None,
    intent: Mapping[str, Any] | None = None,
    risk_result: Mapping[str, Any] | None = None,
    allocation: Mapping[str, Any] | None = None,
    bucket_quarantine_status: Any = None,
    context: Mapping[str, Any] | None = None,
    redis_client: Any = None,
    config: APlusGateConfig | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate one candidate against every A+ check. Fail-closed everywhere."""
    cfg = config or APlusGateConfig()
    now_utc = now or datetime.now(timezone.utc)
    normalized_side = (side or "").strip().lower()
    ctx = dict(context) if context is not None else load_a_plus_context(
        redis_client, symbol=symbol, timeframe=timeframe
    )
    checks: dict[str, dict[str, Any]] = {
        "trainer_online_learning_active": _trainer_learning_check(ctx.get("trainer_metrics")),
        "side_bucket_positive": _side_bucket_check(
            ctx.get("side_performance"),
            side=normalized_side,
            confidence_calibrated=confidence_calibrated,
            config=cfg,
        ),
        "regime_aligned": _regime_check(
            regime_decision=ctx.get("regime_decision"),
            strategy_id=strategy_id,
            side=normalized_side,
            trade_tape=ctx.get("trade_tape"),
            microstructure_trust=ctx.get("microstructure_trust"),
            now=now_utc,
            config=cfg,
        ),
        "htf_aligned": _htf_check(
            htf_context=ctx.get("htf_context"),
            cross_asset=ctx.get("cross_asset"),
            side=normalized_side,
            entry_timeframe_trend=entry_timeframe_trend,
            now=now_utc,
            config=cfg,
        ),
        "trade_tape_confirms": _tape_check(
            trade_tape=ctx.get("trade_tape"), side=normalized_side, now=now_utc, config=cfg
        ),
        "microstructure_trust_confirms": _microstructure_check(
            microstructure_trust=ctx.get("microstructure_trust"), config=cfg
        ),
        "risk_allows": _risk_check(risk_result),
        "allocator_allows": _allocator_check(allocation),
        "exit_plan_valid": _exit_plan_check(atr_bps=atr_bps, prediction_row=prediction_row),
        "cost_evidence_production_grade": _cost_evidence_check(intent),
        "no_quarantine_bucket": _quarantine_check(
            bucket_quarantine_status,
            symbol=symbol,
            timeframe=timeframe,
            side=normalized_side,
            strategy_id=strategy_id,
            regime_label=str((ctx.get("regime_decision") or {}).get("regime") or "") or None,
        ),
        "no_stale_or_missing_critical_feature": _feature_integrity_check(prediction_row),
        "no_recent_high_confidence_loss_in_bucket": _recent_high_confidence_loss_check(
            ctx.get("feedback_rows"),
            symbol=symbol,
            timeframe=timeframe,
            side=normalized_side,
            strategy_id=strategy_id,
            now=now_utc,
            config=cfg,
        ),
    }
    failed = [name for name, result in checks.items() if not result["passed"]]
    missing = [name for name, result in checks.items() if result.get("missing_evidence")]
    a_plus = not failed
    return {
        "schema_version": A_PLUS_GATE_SCHEMA_VERSION,
        "generated_utc": now_utc.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "symbol": (symbol or "").upper(),
        "timeframe": timeframe,
        "side": normalized_side,
        "strategy_id": strategy_id,
        "bucket_key": _bucket_key(symbol, timeframe, normalized_side, strategy_id),
        "a_plus": a_plus,
        "checks": checks,
        "failed_checks": failed,
        "missing_evidence_checks": missing,
        "check_count": len(CHECKS),
        "passed_check_count": len(CHECKS) - len(failed),
        "fail_closed": True,
        "paper_tradeable": a_plus,
        "live_candidate_eligible": a_plus,
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "writes_legacy_redis": False,
    }
