from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_ACTION_ALLOW,
    RISK_DECISION_ACTION_DENY,
    RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
    RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
    RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
    RiskDecisionRecord,
)


BASE_TS_MS = 1_700_000_000_000
PAPER_MODE_CLOCK_START_MS = BASE_TS_MS + 2_000_000

SOURCE_IDS = ("paper_mode", "shadow_mode", "historical_pnl")
SCENARIO_SPECS = (
    (
        "pack_btc_winner_long",
        "BTCUSDT",
        RISK_DECISION_ACTION_ALLOW,
        RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
        False,
    ),
    (
        "pack_eth_winner_short",
        "ETHUSDT",
        RISK_DECISION_ACTION_ALLOW,
        RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
        False,
    ),
    (
        "pack_lab_loser_short",
        "LABUSDT",
        RISK_DECISION_ACTION_ALLOW,
        RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
        True,
    ),
    (
        "pack_sol_orchestrator_held",
        "SOLUSDT",
        RISK_DECISION_ACTION_DENY,
        RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
        False,
    ),
)

_REASON_TO_INPUT_DECISION = {
    RISK_DECISION_REASON_ALLOW_PROCEED_LONG: ("open_long", "proceed_long"),
    RISK_DECISION_REASON_ALLOW_PROCEED_SHORT: ("open_short", "proceed_short"),
    RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD: ("hold", "hold_flat_direction"),
}


@dataclass(frozen=True, slots=True)
class AggregateRollupSourceInput:
    source_id: str
    scenario_slug: str
    symbol: str
    risk_action: str
    risk_reason: str
    legacy_evidence_pointer: str
    has_lab_pointer: bool
    risk_decision_record: RiskDecisionRecord


@dataclass(frozen=True, slots=True)
class AggregateRollupSourcePack:
    source_id: str
    inputs: tuple[AggregateRollupSourceInput, ...]


@dataclass(frozen=True, slots=True)
class AggregateRollupPerSymbolCount:
    symbol: str
    count: int


@dataclass(frozen=True, slots=True)
class AggregateRollupPerSourceRecord:
    source_id: str
    total_inputs: int
    allow_proceed_long_count: int
    allow_proceed_short_count: int
    deny_orchestrator_held_count: int
    per_symbol_counts: tuple[AggregateRollupPerSymbolCount, ...]
    lab_pointer_presence_count: int


@dataclass(frozen=True, slots=True)
class AggregateRollupSummary:
    paper_mode_flag: object
    per_source_records: tuple[AggregateRollupPerSourceRecord, ...]
    total_inputs: int
    total_allow_proceed_long_count: int
    total_allow_proceed_short_count: int
    total_deny_orchestrator_held_count: int
    total_lab_pointer_presence_count: int
    per_symbol_total_counts: tuple[AggregateRollupPerSymbolCount, ...]


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


def build_paper_mode_clock() -> Callable[[], int]:
    return build_test_clock(PAPER_MODE_CLOCK_START_MS, 19)


def build_paper_mode_source_pack() -> AggregateRollupSourcePack:
    return _build_source_pack(source_id="paper_mode", source_index=0)


def build_shadow_mode_source_pack() -> AggregateRollupSourcePack:
    return _build_source_pack(source_id="shadow_mode", source_index=1)


def build_historical_pnl_source_pack() -> AggregateRollupSourcePack:
    return _build_source_pack(source_id="historical_pnl", source_index=2)


def build_aggregate_rollup_source_packs() -> tuple[AggregateRollupSourcePack, ...]:
    return (
        build_paper_mode_source_pack(),
        build_shadow_mode_source_pack(),
        build_historical_pnl_source_pack(),
    )


def _build_source_pack(
    *,
    source_id: str,
    source_index: int,
) -> AggregateRollupSourcePack:
    inputs: list[AggregateRollupSourceInput] = []
    for scenario_index, scenario_spec in enumerate(SCENARIO_SPECS):
        scenario_suffix, symbol, risk_action, risk_reason, has_lab_pointer = scenario_spec
        inputs.extend(
            _build_input(
                source_id=source_id,
                source_index=source_index,
                scenario_suffix=scenario_suffix,
                scenario_index=scenario_index,
                symbol=symbol,
                risk_action=risk_action,
                risk_reason=risk_reason,
                has_lab_pointer=has_lab_pointer,
                ordinal=ordinal,
            )
            for ordinal in range(1, 4)
        )
    return AggregateRollupSourcePack(source_id=source_id, inputs=tuple(inputs))


def _build_input(
    *,
    source_id: str,
    source_index: int,
    scenario_suffix: str,
    scenario_index: int,
    symbol: str,
    risk_action: str,
    risk_reason: str,
    has_lab_pointer: bool,
    ordinal: int,
) -> AggregateRollupSourceInput:
    ordinal_id = f"{ordinal:03d}"
    scenario_slug = f"aggregate_rollup_{source_id}_{scenario_suffix}"
    input_action, input_reason_code = _REASON_TO_INPUT_DECISION[risk_reason]
    pointer_slug = (
        f"{source_id}__lab_hedge_unwind_squeeze"
        if has_lab_pointer
        else f"{source_id}__{scenario_suffix}"
    )
    return AggregateRollupSourceInput(
        source_id=source_id,
        scenario_slug=scenario_slug,
        symbol=symbol,
        risk_action=risk_action,
        risk_reason=risk_reason,
        legacy_evidence_pointer=f"legacy_evidence__{pointer_slug}__step_{ordinal}",
        has_lab_pointer=has_lab_pointer,
        risk_decision_record=RiskDecisionRecord(
            risk_decision_id=(
                f"risk_decision_{source_id}_{scenario_suffix}_{ordinal_id}"
            ),
            decision_id=f"decision_{source_id}_{scenario_suffix}_{ordinal_id}",
            prediction_id=f"prediction_{source_id}_{scenario_suffix}_{ordinal_id}",
            feature_snapshot_id=(
                f"feature_snapshot_{source_id}_{scenario_suffix}_{ordinal_id}"
            ),
            symbol=symbol,
            risk_decision_ts_ms=(
                BASE_TS_MS + source_index * 600_000 + scenario_index * 60_000 + ordinal * 100
            ),
            risk_action=risk_action,
            risk_reason_code=risk_reason,
            input_decision_action=input_action,
            input_decision_reason_code=input_reason_code,
            live_blocked=True,
        ),
    )
