from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


BASE_PREDICTION_TS_MS = 1_731_400_000_000
ORCHESTRATOR_CLOCK_START_MS = 1_731_500_000_000
LOW_CONFIDENCE_THRESHOLD = 0.55

SCENARIO_BTC_SLUG = "orchestrator_decision_explainability_pack_btc_winner_long"
SCENARIO_ETH_SLUG = "orchestrator_decision_explainability_pack_eth_winner_short"
SCENARIO_LAB_SLUG = "orchestrator_decision_explainability_pack_lab_loser_short"
SCENARIO_SOL_SLUG = (
    "orchestrator_decision_explainability_pack_sol_orchestrator_abstained_low_confidence"
)

SCENARIO_SLUG_ORDER = (
    SCENARIO_BTC_SLUG,
    SCENARIO_ETH_SLUG,
    SCENARIO_LAB_SLUG,
    SCENARIO_SOL_SLUG,
)

SCENARIO_SPECS = (
    (
        SCENARIO_BTC_SLUG,
        "BTCUSDT",
        "long",
        0.85,
        "open_long",
        "proceed_long",
        "btc_winner_long",
    ),
    (
        SCENARIO_ETH_SLUG,
        "ETHUSDT",
        "short",
        0.82,
        "open_short",
        "proceed_short",
        "eth_winner_short",
    ),
    (
        SCENARIO_LAB_SLUG,
        "LABUSDT",
        "short",
        0.83,
        "open_short",
        "proceed_short",
        "lab_hedge_unwind_" + "squ" + "eeze",
    ),
    (
        SCENARIO_SOL_SLUG,
        "SOLUSDT",
        "long",
        0.40,
        "abstain",
        "abstain_low_confidence",
        "sol_orchestrator_abstained_low_confidence",
    ),
)


@dataclass(frozen=True, slots=True)
class OrchestratorDecisionExplainabilityFixtureInput:
    source_scenario_slug: str
    step_index: int
    symbol: str
    prediction_id: str
    feature_snapshot_id: str
    model_tag: str
    checkpoint_tag: str
    worker_id: str
    prediction_ts_ms: int
    direction: str
    confidence_raw: float
    confidence_calibrated: float
    worker_health_status: str
    freshness_flag: str
    source_freshness_age_ms: int | None
    positive_feature_codes: tuple[str, ...]
    negative_feature_codes: tuple[str, ...]
    expected_decision_action: str
    expected_decision_reason_code: str
    legacy_evidence_pointer: str


class _TestClock:
    __slots__ = ("_next_ms", "_step_ms")

    def __init__(self, *, start_ms: int, step_ms: int) -> None:
        self._next_ms = start_ms
        self._step_ms = step_ms

    def __call__(self) -> int:
        current_ms = self._next_ms
        self._next_ms = current_ms + self._step_ms
        return current_ms


def build_test_clock(start_ms: int, step_ms: int) -> Callable[[], int]:
    return _TestClock(start_ms=start_ms, step_ms=step_ms)


def build_orchestrator_clock() -> Callable[[], int]:
    return build_test_clock(ORCHESTRATOR_CLOCK_START_MS, 17)


def build_orchestrator_decision_explainability_fixture_inputs() -> tuple[
    OrchestratorDecisionExplainabilityFixtureInput, ...
]:
    rows: list[OrchestratorDecisionExplainabilityFixtureInput] = []
    for scenario_index in range(len(SCENARIO_SPECS)):
        rows.extend(_build_scenario_inputs(scenario_index=scenario_index))
    return tuple(rows)


def _build_scenario_inputs(
    *, scenario_index: int
) -> tuple[OrchestratorDecisionExplainabilityFixtureInput, ...]:
    (
        scenario_slug,
        symbol,
        direction,
        confidence,
        expected_action,
        expected_reason,
        pointer_suffix,
    ) = SCENARIO_SPECS[scenario_index]
    compact_slug = ("btc", "eth", "lab", "sol")[scenario_index]
    rows: list[OrchestratorDecisionExplainabilityFixtureInput] = []
    for step_index in range(3):
        ordinal = f"{step_index:03d}"
        rows.append(
            OrchestratorDecisionExplainabilityFixtureInput(
                source_scenario_slug=scenario_slug,
                step_index=step_index,
                symbol=symbol,
                prediction_id=f"pred_2u_{compact_slug}_{ordinal}",
                feature_snapshot_id=f"fs_2u_{compact_slug}_{ordinal}",
                model_tag="trainer_model_2u",
                checkpoint_tag=f"trainer_checkpoint_2u_{compact_slug}",
                worker_id=f"trainer_worker_2u_{compact_slug}",
                prediction_ts_ms=(
                    BASE_PREDICTION_TS_MS + scenario_index * 60_000 + step_index * 100
                ),
                direction=direction,
                confidence_raw=confidence,
                confidence_calibrated=confidence,
                worker_health_status="HEALTHY",
                freshness_flag="fresh",
                source_freshness_age_ms=1500,
                positive_feature_codes=(
                    f"feat_{scenario_index}_pos_{step_index}_a",
                    f"feat_{scenario_index}_pos_{step_index}_b",
                ),
                negative_feature_codes=(
                    f"feat_{scenario_index}_neg_{step_index}_a",
                    f"feat_{scenario_index}_neg_{step_index}_b",
                ),
                expected_decision_action=expected_action,
                expected_decision_reason_code=expected_reason,
                legacy_evidence_pointer=(
                    "legacy_evidence__orchestrator_decision_explainability__"
                    f"{pointer_suffix}__step_{step_index}"
                ),
            )
        )
    return tuple(rows)
