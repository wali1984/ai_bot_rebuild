from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Any, Iterable, Mapping

from v2.backend.app.services.legacy_v2_observatory_common import (
    LIVE_GATE_STATUS,
    as_float,
    nested_get,
    parse_ts,
    safety_footer,
    utc_now,
)


HORIZON_SECONDS = {
    "horizon_5m": 5 * 60,
    "horizon_15m": 15 * 60,
    "horizon_30m": 30 * 60,
    "horizon_1h": 60 * 60,
}
DEFAULT_COST_BPS = 6.0


def _num(value: Any, default: float | None = None) -> float | None:
    parsed = as_float(value)
    return default if parsed is None else parsed


def _str(value: Any) -> str:
    return str(value or "").strip()


def _side(value: Any) -> str:
    text = _str(value).lower()
    if text in {"long", "buy", "open_long"}:
        return "long"
    if text in {"short", "sell", "open_short"}:
        return "short"
    return text or "unknown"


def _parse_sample_ts(sample: Mapping[str, Any]) -> dt.datetime | None:
    return parse_ts(sample.get("time") or sample.get("generated_at") or sample.get("ts"))


def _sample_price(sample: Mapping[str, Any], key: str) -> float | None:
    return _num(sample.get(key) or sample.get("price") or sample.get("last_price"))


def _bps(side: str, entry: float, price: float) -> float:
    if entry <= 0:
        return 0.0
    raw = ((price - entry) / entry) * 10_000.0
    return round(raw if side != "short" else -raw, 8)


def _cost_bps(request: Mapping[str, Any]) -> float:
    explicit = _num(request.get("cost_bps"))
    if explicit is not None:
        return explicit
    return round(
        (_num(request.get("fee_bps"), 4.0) or 0.0)
        + (_num(request.get("spread_bps"), 0.0) or 0.0)
        + (_num(request.get("slippage_bps"), 2.0) or 0.0)
        + (_num(request.get("funding_risk_bps"), 0.0) or 0.0),
        8,
    )


def _samples_for_symbol(
    price_samples: Iterable[Mapping[str, Any]],
    *,
    symbol: str,
    event_ts: dt.datetime,
    deadline: dt.datetime,
) -> list[Mapping[str, Any]]:
    wanted = symbol.upper()
    rows: list[tuple[dt.datetime, Mapping[str, Any]]] = []
    for sample in price_samples:
        sample_symbol = _str(sample.get("symbol")).upper()
        if sample_symbol and sample_symbol != wanted:
            continue
        sample_ts = _parse_sample_ts(sample)
        if sample_ts is None or sample_ts <= event_ts or sample_ts > deadline:
            continue
        rows.append((sample_ts, sample))
    return [sample for _, sample in sorted(rows, key=lambda item: item[0])]


def evaluate_observation_request(
    request: Mapping[str, Any],
    *,
    price_samples: Iterable[Mapping[str, Any]],
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    now = now or dt.datetime.now(dt.timezone.utc)
    symbol = _str(request.get("symbol")).upper()
    side = _side(request.get("side"))
    event_ts = parse_ts(request.get("event_ts"))
    entry = _num(request.get("entry_reference_price"))
    cost_bps = _cost_bps(request) or DEFAULT_COST_BPS
    expected_after_cost = _num(request.get("expected_move_after_cost_bps"))
    base = {
        "observation_id": _str(request.get("observation_id"))
        or f"shadow_{_str(request.get('intent_id') or request.get('risk_decision_id') or request.get('event_id') or 'unknown')}",
        "event_id": _str(request.get("event_id")),
        "intent_id": _str(request.get("intent_id")),
        "risk_decision_id": _str(request.get("risk_decision_id")),
        "prediction_id": _str(request.get("prediction_id")),
        "feature_snapshot_id": _str(request.get("feature_snapshot_id")),
        "symbol": symbol,
        "side": side,
        "entry_reference_price": entry,
        "event_ts": request.get("event_ts"),
        "expected_move_bps": _num(request.get("expected_move_bps")),
        "expected_move_after_cost_bps": expected_after_cost,
        "expected_move_source": _str(request.get("expected_move_source")),
        "expected_move_coverage_status": _str(request.get("expected_move_coverage_status")),
        "cost_bps": cost_bps,
        "block_reason": request.get("block_reason"),
        "fill_allowed": False,
        "fee_charged_usdt": 0.0,
        "paper_fill_recorded": False,
    }
    if event_ts is None or entry is None or entry <= 0 or not symbol or side not in {"long", "short"}:
        base.update(
            {
                "outcome_status": "MISSING_EVIDENCE_CANNOT_OBSERVE",
                "completed": False,
                "after_cost_correct": "MISSING_EVIDENCE",
                "no_trade_correct": "MISSING_EVIDENCE",
                "horizons": {
                    name: {"status": "MISSING_EVIDENCE_CANNOT_OBSERVE"}
                    for name in HORIZON_SECONDS
                },
            }
        )
        return base

    completed_horizons = []
    horizon_results: dict[str, dict[str, Any]] = {}
    for name, seconds in HORIZON_SECONDS.items():
        deadline = event_ts + dt.timedelta(seconds=seconds)
        rows = _samples_for_symbol(
            price_samples,
            symbol=symbol,
            event_ts=event_ts,
            deadline=deadline,
        )
        if now < deadline or not rows:
            horizon_results[name] = {
                "status": "PENDING_INSUFFICIENT_FUTURE_DATA",
                "deadline": deadline.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            continue
        close_price = _sample_price(rows[-1], "close")
        if close_price is None:
            horizon_results[name] = {"status": "MISSING_CLOSE_PRICE"}
            continue
        highs = [_sample_price(row, "high") for row in rows]
        lows = [_sample_price(row, "low") for row in rows]
        valid_highs = [price for price in highs if price is not None]
        valid_lows = [price for price in lows if price is not None]
        high = max(valid_highs) if valid_highs else close_price
        low = min(valid_lows) if valid_lows else close_price
        favorable_price = high if side == "long" else low
        adverse_price = low if side == "long" else high
        realized = _bps(side, entry, close_price)
        favorable = max(0.0, _bps(side, entry, favorable_price))
        adverse = min(0.0, _bps(side, entry, adverse_price))
        would_have_beaten_costs = realized > cost_bps
        horizon_result = {
            "status": "COMPLETED",
            "deadline": deadline.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sample_count": len(rows),
            "realized_return_bps": realized,
            "max_favorable_excursion_bps": round(favorable, 8),
            "max_adverse_excursion_bps": round(adverse, 8),
            "would_have_beaten_costs": would_have_beaten_costs,
            "would_have_hit_stop": adverse <= -cost_bps,
            "would_have_hit_take_profit": favorable >= max(cost_bps, expected_after_cost or cost_bps),
        }
        completed_horizons.append(horizon_result)
        horizon_results[name] = horizon_result

    any_completed = bool(completed_horizons)
    any_beats_costs = any(bool(row["would_have_beaten_costs"]) for row in completed_horizons)
    all_completed_fail_costs = any_completed and not any_beats_costs
    base.update(
        {
            "outcome_status": "COMPLETED"
            if any_completed
            else "PENDING_INSUFFICIENT_FUTURE_DATA",
            "completed": any_completed,
            "horizons": horizon_results,
            "max_favorable_excursion_bps": max(
                (row["max_favorable_excursion_bps"] for row in completed_horizons),
                default=None,
            ),
            "max_adverse_excursion_bps": min(
                (row["max_adverse_excursion_bps"] for row in completed_horizons),
                default=None,
            ),
            "would_have_beaten_costs": any_beats_costs if any_completed else "PENDING_OUTCOME",
            "after_cost_correct": any_beats_costs if any_completed else "PENDING_OUTCOME",
            "no_trade_correct": all_completed_fail_costs if any_completed else "PENDING_OUTCOME",
        }
    )
    return base


def _request_from_worker_status(worker_status: Mapping[str, Any]) -> dict[str, Any] | None:
    request = worker_status.get("shadow_observation_request")
    if isinstance(request, Mapping) and request:
        enriched = dict(request)
        for key in (
            "event_id",
            "intent_id",
            "risk_decision_id",
            "prediction_id",
            "feature_snapshot_id",
            "fee_bps",
            "spread_bps",
            "slippage_bps",
            "funding_risk_bps",
            "expected_move_source",
            "expected_move_coverage_status",
        ):
            enriched.setdefault(key, worker_status.get(key))
        return enriched
    return None


def _request_from_paper_runtime(paper_status: Mapping[str, Any]) -> dict[str, Any] | None:
    risk = nested_get(paper_status, "current_risk_decision", {})
    lineage = nested_get(paper_status, "current_signal_lineage", {})
    intent = nested_get(lineage, "execution_intent", {})
    signal = nested_get(lineage, "signal", {})
    trainer = nested_get(lineage, "trainer_prediction", {})
    market = nested_get(paper_status, "market_feed", {})
    last_event = nested_get(paper_status, "last_paper_event", {})
    if not isinstance(risk, Mapping) or not risk:
        return None
    if str(risk.get("risk_action") or "").lower() != "deny":
        return None
    side = intent.get("side") or signal.get("side") or nested_get(trainer, "raw_output.side")
    price = last_event.get("observed_price") or market.get("last_price")
    trainer_expected_move = nested_get(trainer, "raw_output.expected_move_bps")
    expected_move_bps = (
        nested_get(risk, "canary_profile_tightening.expected_move_bps")
        or nested_get(risk, "expected_move_bps")
        or trainer_expected_move
    )
    cost_bps = round(
        (_num(nested_get(risk, "canary_profile_tightening.fee_bps"), 4.0) or 0.0)
        + (_num(nested_get(risk, "canary_profile_tightening.spread_bps"), 0.0) or 0.0)
        + (_num(last_event.get("slippage_bps") or nested_get(risk, "canary_profile_tightening.slippage_bps"), 2.0) or 0.0)
        + (_num(nested_get(risk, "canary_profile_tightening.funding_risk_bps"), 0.0) or 0.0),
        8,
    )
    expected_after_cost = nested_get(risk, "expected_move_after_cost_bps")
    if expected_after_cost is None and _num(expected_move_bps) is not None:
        expected_after_cost = round((_num(expected_move_bps) or 0.0) - cost_bps, 8)
    block_reason = (
        risk.get("canary_profile_tightening_blockers")
        or risk.get("risk_reason_code")
        or last_event.get("paper_reason")
    )
    return {
        "event_id": last_event.get("tick_id"),
        "intent_id": intent.get("execution_intent_id"),
        "risk_decision_id": risk.get("risk_decision_id"),
        "prediction_id": risk.get("prediction_id") or trainer.get("prediction_id"),
        "feature_snapshot_id": risk.get("feature_snapshot_id") or trainer.get("feature_snapshot_id"),
        "symbol": risk.get("symbol") or intent.get("symbol") or signal.get("symbol"),
        "side": side,
        "entry_reference_price": price,
        "event_ts": risk.get("generated_at") or last_event.get("generated_at"),
        "expected_move_bps": expected_move_bps,
        "expected_move_after_cost_bps": expected_after_cost,
        "expected_move_source": risk.get("expected_move_source")
        or nested_get(risk, "expected_move_coverage.expected_move_source"),
        "expected_move_coverage_status": risk.get("expected_move_coverage_status")
        or nested_get(risk, "expected_move_coverage.expected_move_coverage_status"),
        "fee_bps": nested_get(risk, "canary_profile_tightening.fee_bps"),
        "spread_bps": nested_get(risk, "canary_profile_tightening.spread_bps"),
        "slippage_bps": last_event.get("slippage_bps") or 2.0,
        "funding_risk_bps": nested_get(risk, "canary_profile_tightening.funding_risk_bps") or 0.0,
        "block_reason": block_reason,
    }


def _samples_from_paper_status(paper_status: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    candles = nested_get(paper_status, "market_feed.candles", [])
    if isinstance(candles, list):
        symbol = _str(nested_get(paper_status, "feature_snapshot.symbol") or nested_get(paper_status, "last_paper_event.symbol")).upper()
        return [
            {**row, "symbol": row.get("symbol") or symbol}
            for row in candles
            if isinstance(row, Mapping)
        ]
    return []


def _reason_items(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if value in (None, ""):
        return []
    return [str(value)]


def _is_missing_expected_move_block(row: Mapping[str, Any]) -> bool:
    reasons = {item.lower() for item in _reason_items(row.get("block_reason"))}
    return (
        row.get("expected_move_after_cost_bps") is None
        or "missing_expected_move_after_costs" in reasons
        or "edge_after_costs_missing_block" in reasons
    )


def _is_native_expected_move_block(row: Mapping[str, Any]) -> bool:
    source = _str(row.get("expected_move_source")).lower()
    return source.startswith("native_") and row.get("expected_move_after_cost_bps") is not None


def build_paper_shadow_outcome_observer_status(
    *,
    worker_status: Mapping[str, Any] | None = None,
    paper_status: Mapping[str, Any] | None = None,
    requests: Iterable[Mapping[str, Any]] | None = None,
    price_samples: Iterable[Mapping[str, Any]] | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    worker_status = worker_status or {}
    paper_status = paper_status or {}
    now = now or dt.datetime.now(dt.timezone.utc)
    request_rows = [dict(row) for row in requests or []]
    worker_request = _request_from_worker_status(worker_status)
    if worker_request:
        request_rows.append(worker_request)
    runtime_request = _request_from_paper_runtime(paper_status)
    if runtime_request:
        request_rows.append(runtime_request)
    deduped_requests: dict[str, dict[str, Any]] = {}
    for row in request_rows:
        observation_id = _str(row.get("observation_id"))
        identity = (
            observation_id
            or _str(row.get("intent_id"))
            or _str(row.get("risk_decision_id"))
            or _str(row.get("event_id"))
        )
        if not identity:
            identity = f"request_{len(deduped_requests)}"
        deduped_requests[identity] = row
    request_rows = list(deduped_requests.values())[-500:]
    sample_rows = [dict(row) for row in price_samples or []]
    if not sample_rows:
        sample_rows = [dict(row) for row in _samples_from_paper_status(paper_status)]

    observations = []
    for request in request_rows:
        evaluated = evaluate_observation_request(request, price_samples=sample_rows, now=now)
        if request.get("completed") is True and evaluated.get("completed") is not True:
            preserved = dict(request)
            preserved["preserved_completed_outcome"] = True
            preserved.setdefault("outcome_status", "COMPLETED")
            observations.append(preserved)
        else:
            observations.append(evaluated)
    completed = [row for row in observations if row.get("completed") is True]
    pending = [row for row in observations if row.get("completed") is not True]
    false_blocks = [
        row for row in completed if row.get("would_have_beaten_costs") is True
    ]
    no_trade_correct = [
        row for row in completed if row.get("no_trade_correct") is True
    ]
    false_block_reason_counts: Counter[str] = Counter()
    for row in false_blocks:
        false_block_reason_counts.update(_reason_items(row.get("block_reason")))
    false_blocks_missing_expected_move = [
        row for row in false_blocks if _is_missing_expected_move_block(row)
    ]
    false_blocks_with_expected_move = [
        row for row in false_blocks if row.get("expected_move_after_cost_bps") is not None
    ]
    false_blocks_native_expected_move = [
        row for row in false_blocks if _is_native_expected_move_block(row)
    ]
    false_blocks_unknown_expected_move_source = [
        row
        for row in false_blocks_with_expected_move
        if not _str(row.get("expected_move_source"))
    ]
    if not observations:
        outcome_status = "EDGE_PENDING_INSUFFICIENT_SAMPLE"
    elif not completed:
        outcome_status = "EDGE_PENDING_INSUFFICIENT_SAMPLE"
    elif false_blocks:
        outcome_status = "BLOCKED_INTENTS_BEAT_COSTS_MODEL_REVIEW_REQUIRED"
    else:
        outcome_status = "NO_TRADE_DECISIONS_CORRECT_SO_FAR"
    recommended_next_action = (
        "EXPECTED_MOVE_MODEL_REVIEW_REQUIRED_KEEP_FILL_GATE_STRICT"
        if false_blocks
        else "CONTINUE_SHADOW_OUTCOME_OBSERVATION"
    )

    status = {
        "worker_id": "paper_shadow_outcome_observer",
        "generated_at": utc_now(),
        "outcome_status": outcome_status,
        "edge_status": "EDGE_PENDING_INSUFFICIENT_SAMPLE"
        if outcome_status == "EDGE_PENDING_INSUFFICIENT_SAMPLE"
        else "EDGE_PENDING_MODEL_REVIEW_REQUIRED"
        if false_blocks
        else "SHADOW_OUTCOME_OBSERVING",
        "observations_total": len(observations),
        "completed_observations": len(completed),
        "pending_observations": len(pending),
        "false_block_count": len(false_blocks),
        "false_block_missing_expected_move_count": len(false_blocks_missing_expected_move),
        "false_block_with_expected_move_count": len(false_blocks_with_expected_move),
        "false_block_native_expected_move_count": len(false_blocks_native_expected_move),
        "false_block_unknown_expected_move_source_count": len(false_blocks_unknown_expected_move_source),
        "false_block_reason_counts": dict(sorted(false_block_reason_counts.items())),
        "false_block_examples": [
            {
                "observation_id": row.get("observation_id"),
                "symbol": row.get("symbol"),
                "side": row.get("side"),
                "event_ts": row.get("event_ts"),
                "cost_bps": row.get("cost_bps"),
                "expected_move_bps": row.get("expected_move_bps"),
                "expected_move_after_cost_bps": row.get("expected_move_after_cost_bps"),
                "expected_move_source": row.get("expected_move_source"),
                "block_reason": row.get("block_reason"),
                "max_favorable_excursion_bps": row.get("max_favorable_excursion_bps"),
            }
            for row in false_blocks[:5]
        ],
        "false_block_classification": {
            "historical_missing_expected_move": len(false_blocks_missing_expected_move),
            "expected_move_present_model_review": len(false_blocks_with_expected_move),
            "native_expected_move_model_review": len(false_blocks_native_expected_move),
            "expected_move_source_unknown": len(false_blocks_unknown_expected_move_source),
        },
        "no_trade_correct_count": len(no_trade_correct),
        "after_cost_correct_count": len(false_blocks),
        "candidate_trade_count": len(observations),
        "allowed_paper_fill_count": 0,
        "blocked_shadow_count": len(observations),
        "observations": observations,
        "latest_observation": observations[-1] if observations else {},
        "sample_count": len(sample_rows),
        "minimum_sample_status": "INSUFFICIENT_SAMPLE"
        if len(completed) < 20
        else "PRELIMINARY_SAMPLE",
        "recommended_next_action": recommended_next_action,
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "live_gate": LIVE_GATE_STATUS,
        "live_symbols": [],
    }
    status.update(safety_footer())
    return status
