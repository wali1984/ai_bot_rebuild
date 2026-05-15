from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from .errors import CanaryProfileTighteningCompositionError


DEFAULT_SYMBOL_WHITELIST = ("BTCUSDT",)
RISK_ADD_ACTIONS = frozenset({"OPEN", "OPEN_LONG", "OPEN_SHORT", "INCREASE", "FLIP", "HEDGE", "DCA"})
REDUCE_ONLY_ACTIONS = frozenset({"CLOSE", "REDUCE", "REDUCE_ONLY", "PARTIAL_CLOSE_LONG", "PARTIAL_CLOSE_SHORT"})


class CanaryProfileTighteningRuntime:
    __slots__ = ("evaluate_now",)

    def __init__(self, *, evaluate_now: Callable[..., dict[str, Any]]) -> None:
        self.evaluate_now = evaluate_now


def build_canary_profile_tightening_runtime(
    *,
    now_ms_clock: Callable[[], int],
    min_confidence: float = 0.75,
    max_fills_per_hour: int = 12,
    cooldown_seconds: int = 300,
    loss_cooldown_seconds: int = 600,
    max_signal_age_seconds: int = 10,
    max_feature_age_seconds: int = 60,
    symbol_whitelist: Iterable[str] = DEFAULT_SYMBOL_WHITELIST,
) -> CanaryProfileTighteningRuntime:
    if not callable(now_ms_clock):
        raise CanaryProfileTighteningCompositionError("must_be_callable", field="now_ms_clock")
    if not 0 < min_confidence <= 1:
        raise CanaryProfileTighteningCompositionError("must_be_probability", field="min_confidence")
    for field, value in {
        "max_fills_per_hour": max_fills_per_hour,
        "cooldown_seconds": cooldown_seconds,
        "loss_cooldown_seconds": loss_cooldown_seconds,
        "max_signal_age_seconds": max_signal_age_seconds,
        "max_feature_age_seconds": max_feature_age_seconds,
    }.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise CanaryProfileTighteningCompositionError("must_be_positive_int", field=field)

    whitelist = tuple(str(symbol).upper() for symbol in symbol_whitelist if str(symbol).strip())
    if not whitelist:
        raise CanaryProfileTighteningCompositionError("must_not_be_empty", field="symbol_whitelist")

    def _evaluate_now(
        *,
        intent_payload: Mapping[str, Any],
        recent_events: Iterable[Mapping[str, Any]] = (),
        approval_token_present: bool = False,
    ) -> dict[str, Any]:
        now_ms = _valid_now_ms(now_ms_clock())
        intent = _as_mapping(intent_payload, "intent_payload")
        events = [_as_mapping(event, "recent_events") for event in recent_events]
        symbol = str(intent.get("symbol") or "").upper()
        action = _intent_action(intent)
        confidence = _numeric(intent.get("confidence"))
        signal_age = _age_seconds(now_ms, _first(intent, "signal_generated_at_ms", "signal_generated_at", "generated_at"))
        feature_age = _age_seconds(now_ms, _first(intent, "feature_snapshot_generated_at_ms", "feature_generated_at", "feature_snapshot_generated_at"))
        expected_move_bps = _numeric(intent.get("expected_move_bps") or intent.get("expected_move_after_costs_bps"))
        fee_bps = _numeric(intent.get("fee_bps")) or _fee_bps_from_rate(intent.get("fee_rate"))
        slippage_bps = _numeric(intent.get("slippage_bps")) or 0.0
        funding_bps = _numeric(intent.get("funding_bps")) or 0.0
        cost_bps = round(fee_bps + slippage_bps + funding_bps, 8)
        recent = _recent_fill_stats(
            now_ms=now_ms,
            events=events,
            symbol=symbol,
            action=action,
            cooldown_seconds=cooldown_seconds,
            loss_cooldown_seconds=loss_cooldown_seconds,
        )

        blockers: list[str] = []
        if symbol not in whitelist:
            blockers.append("symbol_not_whitelisted")
        if confidence is None:
            blockers.append("missing_confidence")
        elif confidence < min_confidence:
            blockers.append("confidence_below_canary_threshold")
        if recent["fills_last_hour"] >= max_fills_per_hour:
            blockers.append("fill_frequency_exceeds_canary_limit")
        if recent["same_symbol_same_direction_in_cooldown"]:
            blockers.append("same_symbol_same_direction_cooldown")
        if recent["flip_churn_in_cooldown"] and action not in REDUCE_ONLY_ACTIONS:
            blockers.append("flip_churn_cooldown")
        if recent["loss_in_cooldown"]:
            blockers.append("loss_cooldown_active")
        if signal_age is None:
            blockers.append("missing_signal_timestamp")
        elif signal_age > max_signal_age_seconds:
            blockers.append("stale_signal")
        if feature_age is None:
            blockers.append("missing_feature_freshness")
        elif feature_age > max_feature_age_seconds:
            blockers.append("stale_feature_snapshot")
        if expected_move_bps is None:
            blockers.append("missing_expected_move_after_costs")
        elif expected_move_bps <= cost_bps:
            blockers.append("expected_edge_below_costs")

        live_blockers = []
        if not approval_token_present:
            live_blockers.append("approval_token_absent_live_block")

        return {
            "classification": "TIGHTENED_PROFILE_BLOCKED" if blockers else "TIGHTENED_PROFILE_PAPER_SIMULATION_ELIGIBLE",
            "source": "V2_CANARY_PROFILE_TIGHTENING",
            "generated_at_ms": now_ms,
            "symbol": symbol,
            "action": action,
            "confidence": confidence,
            "min_confidence": min_confidence,
            "signal_age_seconds": signal_age,
            "feature_age_seconds": feature_age,
            "expected_move_bps": expected_move_bps,
            "estimated_cost_bps": cost_bps,
            "blockers": blockers,
            "recent_fill_stats": recent,
            "paper_simulation_allowed": not blockers,
            "live_gate_status": "blocked_human_only",
            "live_blockers": live_blockers,
            "safe_for_live": False,
            "automation_can_enable_live": False,
        }

    return CanaryProfileTighteningRuntime(evaluate_now=_evaluate_now)


def _as_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CanaryProfileTighteningCompositionError("must_be_mapping", field=field)
    return value


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _fee_bps_from_rate(value: Any) -> float:
    rate = _numeric(value)
    return round(rate * 10_000, 8) if rate is not None else 0.0


def _intent_action(intent: Mapping[str, Any]) -> str:
    text = str(intent.get("action") or intent.get("side") or intent.get("risk_reason_code") or "").upper()
    if "SHORT" in text:
        return "OPEN_SHORT" if "OPEN" in text or "ALLOW" in text else "SHORT"
    if "LONG" in text:
        return "OPEN_LONG" if "OPEN" in text or "ALLOW" in text else "LONG"
    return text or "MISSING_ACTION"


def _event_action(event: Mapping[str, Any]) -> str:
    return _intent_action(event)


def _is_fill(event: Mapping[str, Any]) -> bool:
    return event.get("paper_result") == "FILLED_PAPER_ONLY" or event.get("ledger_action") == "PAPER_FILL_SIMULATED"


def _is_position_close(event: Mapping[str, Any]) -> bool:
    return event.get("paper_result") == "POSITION_CLOSED_PAPER_ONLY" or event.get("ledger_action") == "PAPER_POSITION_CLOSED"


def _event_pnl_delta(event: Mapping[str, Any]) -> float:
    for key in ("paper_pnl_delta", "realized_delta_usdt", "realized_delta", "gross_pnl_usdt"):
        value = _numeric(event.get(key))
        if value is not None:
            return value
    return 0.0


def _recent_fill_stats(
    *,
    now_ms: int,
    events: list[Mapping[str, Any]],
    symbol: str,
    action: str,
    cooldown_seconds: int,
    loss_cooldown_seconds: int,
) -> dict[str, Any]:
    last_hour_cutoff = now_ms - 3_600_000
    cooldown_cutoff = now_ms - cooldown_seconds * 1000
    loss_cutoff = now_ms - loss_cooldown_seconds * 1000
    fills: list[Mapping[str, Any]] = []
    fills_last_hour = 0
    same_direction = False
    flip_churn = False
    loss_in_cooldown = False
    for event in events:
        is_fill = _is_fill(event)
        is_position_close = _is_position_close(event)
        if not is_fill and not is_position_close:
            continue
        event_ms = _event_ts_ms(event)
        if event_ms is None:
            continue
        if is_fill:
            fills.append(event)
            if event_ms >= last_hour_cutoff:
                fills_last_hour += 1
        event_symbol = str(event.get("symbol") or "").upper()
        event_action = _event_action(event)
        if is_fill and event_symbol == symbol and event_ms >= cooldown_cutoff:
            if event_action == action:
                same_direction = True
            elif {event_action, action} <= {"OPEN_LONG", "OPEN_SHORT", "LONG", "SHORT"}:
                flip_churn = True
        if event_symbol == symbol and event_ms >= loss_cutoff and _event_pnl_delta(event) < 0:
            loss_in_cooldown = True
    return {
        "fills_last_hour": fills_last_hour,
        "total_recent_fills": len(fills),
        "same_symbol_same_direction_in_cooldown": same_direction,
        "flip_churn_in_cooldown": flip_churn,
        "loss_in_cooldown": loss_in_cooldown,
    }


def _age_seconds(now_ms: int, value: Any) -> int | None:
    event_ms = _event_ts_ms({"generated_at": value})
    if event_ms is None:
        return None
    return max(0, int((now_ms - event_ms) / 1000))


def _event_ts_ms(event: Mapping[str, Any]) -> int | None:
    value = _first(event, "generated_at_ms", "ts_ms", "generated_at")
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)
    return None


def _valid_now_ms(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CanaryProfileTighteningCompositionError("must_be_non_negative_int", field="now_ms_clock")
    return value
