from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from .errors import ExecutionAttributionNormalizerCompositionError


REQUIRED_ATTRIBUTION_FIELDS = (
    "signal_id",
    "prediction_id",
    "feature_snapshot_id",
    "risk_decision_id",
    "execution_intent_id",
)


class ExecutionAttributionNormalizerRuntime:
    __slots__ = ("normalize_now",)

    def __init__(self, *, normalize_now: Callable[..., dict[str, Any]]) -> None:
        self.normalize_now = normalize_now


def build_execution_attribution_normalizer_runtime(
    *,
    now_ms_clock: Callable[[], int],
    stale_signal_max_age_ms: int = 300_000,
) -> ExecutionAttributionNormalizerRuntime:
    if not callable(now_ms_clock):
        raise ExecutionAttributionNormalizerCompositionError("must_be_callable", field="now_ms_clock")
    if not isinstance(stale_signal_max_age_ms, int) or stale_signal_max_age_ms < 1:
        raise ExecutionAttributionNormalizerCompositionError("must_be_positive_int", field="stale_signal_max_age_ms")

    def _normalize_now(
        *,
        paper_execution: Mapping[str, Any] | None = None,
        legacy_execution: Mapping[str, Any] | None = None,
        seen_exchange_order_ids: Iterable[str] = (),
    ) -> dict[str, Any]:
        now_ms = _valid_now_ms(now_ms_clock())
        paper = _as_mapping(paper_execution, "paper_execution")
        legacy = _as_mapping(legacy_execution, "legacy_execution")
        seen = {str(value) for value in seen_exchange_order_ids if value}

        lineage = {
            "signal_id": _first(paper, legacy, "signal_id"),
            "prediction_id": _first(paper, legacy, "prediction_id"),
            "feature_snapshot_id": _first(paper, legacy, "feature_snapshot_id"),
            "risk_decision_id": _first(paper, legacy, "risk_decision_id"),
            "execution_intent_id": _first(paper, legacy, "execution_intent_id", "paper_intent_id"),
            "exchange_order_id": _first(paper, legacy, "exchange_order_id", "order_id"),
            "paper_ledger_entry_id": _first(paper, legacy, "paper_ledger_entry_id", "paper_event_id"),
        }

        missing_fields = [field for field in REQUIRED_ATTRIBUTION_FIELDS if not lineage.get(field)]
        exchange_order_id = lineage["exchange_order_id"]
        duplicate_exchange_order_id = bool(exchange_order_id and str(exchange_order_id) in seen)
        signal_ts_ms = _event_ts_ms(paper, legacy)
        stale_signal = signal_ts_ms is None or now_ms - signal_ts_ms > stale_signal_max_age_ms
        live_order_observed = bool(
            _first(paper, legacy, "live_order", "exchange_order_allowed", "exchange_order_sent") is True
        )
        blockers = []
        if missing_fields:
            blockers.append("missing_execution_attribution")
        if duplicate_exchange_order_id:
            blockers.append("duplicate_exchange_order_id")
        if stale_signal:
            blockers.append("stale_or_missing_signal_timestamp")
        if live_order_observed:
            blockers.append("live_exchange_order_observed_readonly")

        return {
            "classification": "P0_EXECUTION_ATTRIBUTION_BLOCKED" if blockers else "P0_EXECUTION_ATTRIBUTION_CURRENT",
            "source": "V2_EXECUTION_ATTRIBUTION_NORMALIZER",
            "generated_at_ms": now_ms,
            "lineage": lineage,
            "missing_fields": missing_fields,
            "duplicate_exchange_order_id": duplicate_exchange_order_id,
            "stale_signal": stale_signal,
            "live_order_observed_readonly": live_order_observed,
            "blockers": blockers,
            "safe_for_live": False,
            "live_gate_status": "blocked_human_only",
        }

    return ExecutionAttributionNormalizerRuntime(normalize_now=_normalize_now)


def _as_mapping(value: Mapping[str, Any] | None, field: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ExecutionAttributionNormalizerCompositionError("must_be_mapping", field=field)
    return value


def _first(primary: Mapping[str, Any], secondary: Mapping[str, Any], *keys: str) -> Any:
    for source in (primary, secondary):
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                return value
    return None


def _event_ts_ms(primary: Mapping[str, Any], secondary: Mapping[str, Any]) -> int | None:
    value = _first(primary, secondary, "signal_ts_ms", "generated_at_ms", "ts_ms", "generated_at")
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
        raise ExecutionAttributionNormalizerCompositionError("must_be_non_negative_int", field="now_ms_clock")
    return value
