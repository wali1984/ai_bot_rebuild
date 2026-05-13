from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from .errors import CurrentSignalLineageAdapterCompositionError


REQUIRED_LINEAGE_IDS = (
    "prediction_id",
    "feature_snapshot_id",
    "signal_id",
    "risk_decision_id",
    "execution_intent_id",
)


class CurrentSignalLineageAdapterRuntime:
    __slots__ = ("build_now",)

    def __init__(self, *, build_now: Callable[..., dict[str, Any]]) -> None:
        self.build_now = build_now


def build_current_signal_lineage_adapter_runtime(
    *,
    now_ms_clock: Callable[[], int],
    max_runtime_age_seconds: int = 300,
) -> CurrentSignalLineageAdapterRuntime:
    if not callable(now_ms_clock):
        raise CurrentSignalLineageAdapterCompositionError("must_be_callable", field="now_ms_clock")
    if not isinstance(max_runtime_age_seconds, int) or max_runtime_age_seconds < 1:
        raise CurrentSignalLineageAdapterCompositionError("must_be_positive_int", field="max_runtime_age_seconds")

    def _build_now(
        *,
        paper_runtime_payload: Mapping[str, Any],
        legacy_bridge_payload: Mapping[str, Any] | None = None,
        coinank_payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        now_ms = _valid_now_ms(now_ms_clock())
        paper = _as_mapping(paper_runtime_payload, "paper_runtime_payload")
        legacy = _as_mapping(legacy_bridge_payload, "legacy_bridge_payload")
        coinank = _as_mapping(coinank_payload, "coinank_payload")
        lineage = _as_mapping(paper.get("current_signal_lineage"), "paper_runtime_payload.current_signal_lineage")
        lineage_ids = _as_mapping(lineage.get("lineage_ids"), "paper_runtime_payload.current_signal_lineage.lineage_ids")
        risk_decision = _as_mapping(paper.get("current_risk_decision"), "paper_runtime_payload.current_risk_decision")
        trainer_prediction = _as_mapping(paper.get("trainer_prediction"), "paper_runtime_payload.trainer_prediction")
        signal = _as_mapping(lineage.get("signal"), "paper_runtime_payload.current_signal_lineage.signal")
        execution_intent = _as_mapping(lineage.get("execution_intent"), "paper_runtime_payload.current_signal_lineage.execution_intent")

        ids = {
            "prediction_id": _first(lineage_ids, trainer_prediction, "prediction_id"),
            "feature_snapshot_id": _first(lineage_ids, trainer_prediction, "feature_snapshot_id"),
            "signal_id": _first(lineage_ids, signal, "signal_id"),
            "risk_decision_id": _first(lineage_ids, risk_decision, "risk_decision_id"),
            "execution_intent_id": _first(lineage_ids, execution_intent, "execution_intent_id"),
        }
        missing_ids = [field for field in REQUIRED_LINEAGE_IDS if not ids.get(field)]
        runtime_age_seconds = _age_seconds(now_ms, paper.get("generated_at"))
        stale = runtime_age_seconds is None or runtime_age_seconds > max_runtime_age_seconds
        blockers = []
        if missing_ids:
            blockers.append("current_lineage_ids_missing")
        if stale:
            blockers.append("paper_runtime_stale_or_missing_generated_at")

        return {
            "classification": "CURRENT_V2_PAPER_LINEAGE" if not blockers else "CURRENT_V2_PAPER_LINEAGE_BLOCKED",
            "source": "V2_CURRENT_SIGNAL_LINEAGE_ADAPTER",
            "generated_at_ms": now_ms,
            "runtime_age_seconds": runtime_age_seconds,
            "lineage_ids": ids,
            "missing_ids": missing_ids,
            "trainer_state": trainer_prediction.get("trainer_state") or "MISSING_EVIDENCE",
            "signal_action": signal.get("proposed_action") or "MISSING_EVIDENCE",
            "risk_result": risk_decision.get("risk_result") or "MISSING_EVIDENCE",
            "paper_only": execution_intent.get("paper_only") is True,
            "legacy_bridge_status": legacy.get("status") or legacy.get("classification") or "MISSING_EVIDENCE",
            "coinank_availability": coinank.get("availability") or {},
            "blockers": blockers,
            "safe_for_live": False,
            "live_gate_status": paper.get("live_gate_status") or "blocked_human_only",
        }

    return CurrentSignalLineageAdapterRuntime(build_now=_build_now)


def _as_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise CurrentSignalLineageAdapterCompositionError("must_be_mapping", field=field)
    return value


def _first(primary: Mapping[str, Any], secondary: Mapping[str, Any], *keys: str) -> Any:
    for source in (primary, secondary):
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                return value
    return None


def _age_seconds(now_ms: int, generated_at: Any) -> int | None:
    generated_ms = _generated_at_ms(generated_at)
    if generated_ms is None:
        return None
    return max(0, int((now_ms - generated_ms) / 1000))


def _generated_at_ms(value: Any) -> int | None:
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
        raise CurrentSignalLineageAdapterCompositionError("must_be_non_negative_int", field="now_ms_clock")
    return value
