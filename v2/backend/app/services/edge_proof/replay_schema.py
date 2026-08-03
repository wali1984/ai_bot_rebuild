"""V2 Native Edge-Proof — replay bundle and label schema.

A replay bundle freezes everything the evaluator needs to score a
single V2 prediction against the future market outcome: feature
snapshot, market context, alt-data, risk / paper-gate / orchestrator
decisions, paper intent, the optional legacy-reference action from
the V2-vs-legacy comparator, and the future outcome windows.

This module is read-only with respect to filesystem, Redis, and the
exchange. It defines pure dataclasses + enums + canonical schema
emitters. No I/O happens here.
"""
from __future__ import annotations

import enum
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


REPLAY_BUNDLE_SCHEMA_VERSION = "v2_native_edge_proof_replay_bundle_v1"


class ReplayLabel(str, enum.Enum):
    """The objective label assigned to one replay bundle.

    These labels are derived from the realized after-cost outcome and
    the V2 paper gate's decision; they are NOT a live trading authority.
    """

    CORRECT_TRADE = "correct_trade"
    CORRECT_NO_TRADE = "correct_no_trade"
    FALSE_POSITIVE = "false_positive"
    FALSE_NEGATIVE = "false_negative"
    FALSE_BLOCK = "false_block"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


# Outcome windows we measure on every bundle. Numeric values are in
# seconds. Add new entries here and the evaluator will pick them up.
OUTCOME_WINDOWS_SECONDS: tuple[tuple[str, int], ...] = (
    ("1m", 60),
    ("5m", 5 * 60),
    ("15m", 15 * 60),
    ("1h", 60 * 60),
)


@dataclass(frozen=True)
class OutcomeWindow:
    """Realized outcome over a single window after the prediction.

    ``return_bps`` is the simple log/percent return in basis points
    over the window, after subtracting the bundle's fee and slippage
    estimates. ``stop_hit`` is True if a hard stop / liquidation level
    was crossed inside the window. ``samples`` records how many ticks
    backed the measurement.
    """

    window_id: str
    window_seconds: int
    return_bps: float | None
    after_cost_return_bps: float | None
    drawdown_bps: float | None
    stop_hit: bool
    samples: int


@dataclass(frozen=True)
class ReplayBundle:
    """One frozen training/evaluation sample."""

    feature_snapshot_id: str
    prediction_id: str
    symbol: str
    timeframe: str
    generated_at: str
    features_hash: str | None
    market_snapshot: Mapping[str, Any]
    altdata_snapshot: Mapping[str, Any] | None
    risk_decision: Mapping[str, Any] | None
    trainer_output: Mapping[str, Any] | None
    paper_gate_decision: Mapping[str, Any] | None
    orchestrator_decision: Mapping[str, Any] | None
    paper_intent: Mapping[str, Any] | None
    legacy_reference_action: Mapping[str, Any] | None
    future_outcomes: dict[str, OutcomeWindow]
    outcome_after_cost: float | None
    label: ReplayLabel

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["label"] = self.label.value
        d["future_outcomes"] = {k: asdict(v) for k, v in self.future_outcomes.items()}
        return d


# ---------------------------------------------------------------------------
# Default thresholds. These are PRELIMINARY thresholds for analysis only;
# they are NOT a live trading authority. Operator decision is required
# before any of them can be considered a gate.
# ---------------------------------------------------------------------------

DEFAULT_THRESHOLDS: Mapping[str, Any] = {
    "min_sample_count": "OPERATOR_DECISION_REQUIRED",
    "min_after_cost_expectancy_bps": "OPERATOR_DECISION_REQUIRED",
    "min_after_cost_lower_ci_bps": "OPERATOR_DECISION_REQUIRED",
    "max_drawdown_bps_rolling": "OPERATOR_DECISION_REQUIRED",
    "min_downside_pre_cascade_recall": "OPERATOR_DECISION_REQUIRED",
    "max_false_positive_rate": "OPERATOR_DECISION_REQUIRED",
    "max_false_negative_rate": "OPERATOR_DECISION_REQUIRED",
    "min_v2_vs_legacy_action_match_rate": "OPERATOR_DECISION_REQUIRED_INFORMATIONAL_ONLY",
    "preliminary_only_for_analysis": True,
    "no_live_approval_implied": True,
}


CANONICAL_INPUT_KEYS: tuple[str, ...] = (
    "v2:prediction:{symbol}:{timeframe}",
    "v2:features:latest:{symbol}:{timeframe}",
    "v2:market:prices:{symbol}",
    "v2:market:liquidations:heartbeat",
    "v2:market:liquidations:latest:{symbol}",
    "v2:market:liquidations:aggregate:{symbol}",
    "v2:altdata:symbol_score:{symbol}",
    "v2:risk:decisions",
    "v2:paper:intents",
    "v2:paper:intents_held_by_paper_fill_gate",
    "v2:paper:ledger",
    "v2:paper:position_history:{symbol}",
    "v2:paper:position_price_track:{symbol}",
    "v2:orchestrator:decisions",
    "v2_vs_legacy_comparator: read-only public payload mirror",
    "legacy log observer: read-only summary mirror only (never raw Redis)",
)


def emit_canonical_schema() -> dict[str, Any]:
    """Return the canonical replay-bundle schema as a JSON-safe dict.

    The schema is intentionally explicit about the safety invariants
    that the bundle must preserve.
    """
    return {
        "schema_version": REPLAY_BUNDLE_SCHEMA_VERSION,
        "bundle_fields": [
            "feature_snapshot_id",
            "prediction_id",
            "symbol",
            "timeframe",
            "generated_at",
            "features_hash",
            "market_snapshot",
            "altdata_snapshot",
            "risk_decision",
            "trainer_output",
            "paper_gate_decision",
            "orchestrator_decision",
            "paper_intent",
            "legacy_reference_action",
            "future_outcomes",
            "outcome_after_cost",
            "label",
        ],
        "future_outcomes_windows": [
            {"window_id": wid, "window_seconds": secs}
            for wid, secs in OUTCOME_WINDOWS_SECONDS
        ],
        "labels": [label.value for label in ReplayLabel],
        "canonical_input_keys": list(CANONICAL_INPUT_KEYS),
        "default_thresholds": dict(DEFAULT_THRESHOLDS),
        "required_thresholds_for_provisional_paper_pass": [
            "min_sample_count",
            "min_after_cost_expectancy_bps",
            "min_after_cost_lower_ci_bps",
            "max_drawdown_bps_rolling",
            "min_downside_pre_cascade_recall",
            "max_false_positive_rate",
            "max_false_negative_rate",
        ],
        "default_cost_model": {
            "fee_drag_bps": 5.0,
            "slippage_estimate_bps": 2.0,
            "cost_model_source": (
                "DEFAULT_PAPER_COST_MODEL_PENDING_OPERATOR_OVERRIDE_"
                "OPERATOR_DECISION_REQUIRED"
            ),
            "operator_override_required": True,
            "operator_decision_required": True,
        },
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "did_not_read_old_redis_current_truth": True,
        "did_not_modify_legacy_bot": True,
        "did_not_call_exchange": True,
        "did_not_expose_raw_api_keys": True,
    }


def replay_bundle_to_json(bundle: ReplayBundle) -> str:
    """Serialize one replay bundle as a JSON string."""
    return json.dumps(bundle.to_dict(), indent=2, sort_keys=True, default=str)
