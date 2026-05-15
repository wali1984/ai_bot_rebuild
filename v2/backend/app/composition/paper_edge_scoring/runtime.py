"""Pure cost-aware admission gate for V2 paper fills."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


EDGE_AFTER_COSTS_PASS = "EDGE_AFTER_COSTS_PASS"
EDGE_AFTER_COSTS_MISSING_BLOCK = "EDGE_AFTER_COSTS_MISSING_BLOCK"
EDGE_AFTER_COSTS_NEGATIVE_BLOCK = "EDGE_AFTER_COSTS_NEGATIVE_BLOCK"
TRAINER_SOURCE_MISSING_BLOCK = "TRAINER_SOURCE_MISSING_BLOCK"
FEATURE_FRESHNESS_MISSING_BLOCK = "FEATURE_FRESHNESS_MISSING_BLOCK"
FEATURE_STALE_BLOCK = "FEATURE_STALE_BLOCK"
CONFIDENCE_TOO_LOW_BLOCK = "CONFIDENCE_TOO_LOW_BLOCK"
COOLDOWN_BLOCK = "COOLDOWN_BLOCK"
FLIP_CHURN_BLOCK = "FLIP_CHURN_BLOCK"
SYMBOL_NOT_PAPER_ELIGIBLE_BLOCK = "SYMBOL_NOT_PAPER_ELIGIBLE_BLOCK"
RISK_GATE_BLOCK = "RISK_GATE_BLOCK"
LIVE_GATE_BLOCK = "LIVE_GATE_BLOCK"
LIVE_SYMBOLS_BLOCK = "LIVE_SYMBOLS_BLOCK"
REDUCE_ONLY_PROTECTION_BLOCK = "REDUCE_ONLY_PROTECTION_BLOCK"
INTELLIGENT_CLOSE_GUARD_BLOCK = "INTELLIGENT_CLOSE_GUARD_BLOCK"
MICROSTRUCTURE_TOXICITY_BLOCK = "MICROSTRUCTURE_TOXICITY_BLOCK"


@dataclass(frozen=True)
class PaperEdgeScoringConfig:
    min_expected_move_after_cost_bps: float = 8.0
    min_confidence_calibrated: float = 0.70
    accepted_trainer_sources: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "LEGACY_HYBRID_TRAINER_LOG_READONLY",
                "LEGACY_HYBRID_TRAINER_REDIS_READONLY",
                "LEGACY_HYBRID_TRAINER",
                "V2_PAPER_TRAINER_WRAPPER",
                "V2_TRAINER_BRIDGE",
                "V2_NATIVE_TRAINER",
            }
        )
    )


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string(value: Any) -> str:
    return str(value or "").strip()


def _symbols(value: Any) -> list[str]:
    if isinstance(value, str):
        raw = [value]
    elif isinstance(value, list):
        raw = value
    else:
        raw = []
    return sorted({_string(item).upper() for item in raw if _string(item)})


def _bool_with_default(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "y"}:
            return True
        if text in {"false", "0", "no", "n"}:
            return False
    return bool(value)


def _first(record: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def score_paper_edge(
    record: Mapping[str, Any],
    *,
    paper_symbols: list[str],
    live_symbols: list[str] | None = None,
    live_gate: str = "blocked_human_only",
    config: PaperEdgeScoringConfig | None = None,
) -> dict[str, Any]:
    cfg = config or PaperEdgeScoringConfig()
    symbol = _string(record.get("symbol")).upper()
    accepted_sources = {item.upper() for item in cfg.accepted_trainer_sources}
    trainer_source = _string(record.get("trainer_source"))
    feature_freshness_state = _string(
        _first(record, "feature_freshness_state", "feature_snapshot_freshness_state")
    ).upper()
    confidence = _number(
        _first(record, "confidence_calibrated", "input_prediction_confidence_calibrated")
    )
    expected_after_cost = _number(
        _first(record, "expected_move_after_cost_bps", "expected_move_after_costs_bps")
    )
    expected_move = _number(_first(record, "expected_move_bps", "predicted_move_bps"))
    fee_bps = _number(_first(record, "fee_bps", "estimated_fee_bps")) or 0.0
    spread_bps = _number(_first(record, "spread_bps", "estimated_spread_bps")) or 0.0
    slippage_bps = _number(_first(record, "slippage_bps", "estimated_slippage_bps")) or 0.0
    funding_risk_bps = _number(
        _first(record, "funding_risk_bps", "funding_bps", "estimated_funding_bps")
    ) or 0.0
    computed_after_cost = (
        None
        if expected_move is None
        else round(expected_move - fee_bps - spread_bps - slippage_bps - funding_risk_bps, 8)
    )

    blockers: list[str] = []
    if live_gate != "blocked_human_only":
        blockers.append(LIVE_GATE_BLOCK)
    if _symbols(live_symbols or []):
        blockers.append(LIVE_SYMBOLS_BLOCK)
    if symbol not in set(_symbols(paper_symbols)):
        blockers.append(SYMBOL_NOT_PAPER_ELIGIBLE_BLOCK)
    if not trainer_source or trainer_source.upper() not in accepted_sources:
        blockers.append(TRAINER_SOURCE_MISSING_BLOCK)
    if not feature_freshness_state:
        blockers.append(FEATURE_FRESHNESS_MISSING_BLOCK)
    elif feature_freshness_state != "CURRENT":
        blockers.append(FEATURE_STALE_BLOCK)
    if expected_after_cost is None:
        blockers.append(EDGE_AFTER_COSTS_MISSING_BLOCK)
    elif expected_after_cost < cfg.min_expected_move_after_cost_bps:
        blockers.append(EDGE_AFTER_COSTS_NEGATIVE_BLOCK)
    if confidence is None or confidence < cfg.min_confidence_calibrated:
        blockers.append(CONFIDENCE_TOO_LOW_BLOCK)
    if not _bool_with_default(record.get("cooldown_clear")):
        blockers.append(COOLDOWN_BLOCK)
    if not _bool_with_default(
        _first(record, "flip_churn_clear", "churn_clear", "flip_clear"),
    ):
        blockers.append(FLIP_CHURN_BLOCK)
    reduce_only_clear = _bool_with_default(
        _first(record, "reduce_only_clear", "reduce_only_protection_clear")
    )
    intelligent_close_clear = _bool_with_default(
        _first(record, "intelligent_close_guard_clear", "close_guard_clear")
    )
    microstructure_clear = _bool_with_default(
        _first(record, "microstructure_toxicity_clear", "toxicity_clear")
    )
    if not reduce_only_clear:
        blockers.append(REDUCE_ONLY_PROTECTION_BLOCK)
    if not intelligent_close_clear:
        blockers.append(INTELLIGENT_CLOSE_GUARD_BLOCK)
    if not microstructure_clear:
        blockers.append(MICROSTRUCTURE_TOXICITY_BLOCK)
    if _string(record.get("risk_action")).lower() != "allow":
        blockers.append(RISK_GATE_BLOCK)

    allowed = not blockers
    classification = EDGE_AFTER_COSTS_PASS if allowed else blockers[0]
    edge_score = expected_after_cost if allowed and expected_after_cost is not None else None
    return {
        "fill_allowed": allowed,
        "classification": classification,
        "blockers": blockers,
        "trainer_source": trainer_source,
        "feature_freshness_state": feature_freshness_state or "",
        "confidence_calibrated": confidence,
        "expected_move_bps": expected_move,
        "expected_move_after_cost_bps": expected_after_cost,
        "computed_expected_move_after_cost_bps": computed_after_cost,
        "fee_bps": fee_bps,
        "spread_bps": spread_bps,
        "slippage_bps": slippage_bps,
        "funding_risk_bps": funding_risk_bps,
        "edge_score": edge_score,
        "paper_symbol_allowed": symbol in set(_symbols(paper_symbols)),
        "live_gate": live_gate,
        "live_symbols": _symbols(live_symbols or []),
        "reduce_only_clear": reduce_only_clear,
        "intelligent_close_guard_clear": intelligent_close_clear,
        "microstructure_toxicity_clear": microstructure_clear,
        "min_expected_move_after_cost_bps": cfg.min_expected_move_after_cost_bps,
        "min_confidence_calibrated": cfg.min_confidence_calibrated,
    }
