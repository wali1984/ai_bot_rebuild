from __future__ import annotations

from dataclasses import dataclass

from v2.backend.app.composition.paper_mode.runtime import build_paper_mode_runtime
from v2.backend.app.domain.paper_mode.flag import PaperModeFlag
from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
    RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
    RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
    RiskDecisionRecord,
)
from v2.backend.tests.unit.aggregate_evidence_rollup_harness.fixtures import (
    AggregateRollupPerSourceRecord,
    AggregateRollupPerSymbolCount,
    AggregateRollupSourcePack,
    AggregateRollupSummary,
    build_paper_mode_clock,
)


@dataclass(frozen=True, slots=True)
class AggregateRollupHarnessResult:
    paper_mode_flag: PaperModeFlag
    per_source_records: tuple[AggregateRollupPerSourceRecord, ...]
    summary: AggregateRollupSummary


def aggregate_evidence_rollup_harness(
    source_packs: tuple[AggregateRollupSourcePack, ...],
) -> AggregateRollupHarnessResult:
    paper_mode_runtime = build_paper_mode_runtime(now_ms_clock=build_paper_mode_clock())
    paper_mode_flag = paper_mode_runtime.paper_mode_now(requested_mode="paper")
    assert paper_mode_flag.live_blocked is True
    assert paper_mode_flag.mode in {"paper", "live_blocked"}

    per_source_records = tuple(
        _build_per_source_record(source_pack) for source_pack in source_packs
    )
    summary = _build_summary(
        paper_mode_flag=paper_mode_flag,
        per_source_records=per_source_records,
    )
    return AggregateRollupHarnessResult(
        paper_mode_flag=paper_mode_flag,
        per_source_records=per_source_records,
        summary=summary,
    )


def _build_per_source_record(
    source_pack: AggregateRollupSourcePack,
) -> AggregateRollupPerSourceRecord:
    reason_counts = {
        RISK_DECISION_REASON_ALLOW_PROCEED_LONG: 0,
        RISK_DECISION_REASON_ALLOW_PROCEED_SHORT: 0,
        RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD: 0,
    }
    symbol_counts: dict[str, int] = {}
    lab_pointer_presence_count = 0

    for input_row in source_pack.inputs:
        _assert_lineage_matches_input(input_row.risk_decision_record)
        reason_counts[input_row.risk_reason] += 1
        symbol_counts[input_row.symbol] = symbol_counts.get(input_row.symbol, 0) + 1
        if input_row.has_lab_pointer is True:
            lab_pointer_presence_count += 1

    return AggregateRollupPerSourceRecord(
        source_id=source_pack.source_id,
        total_inputs=len(source_pack.inputs),
        allow_proceed_long_count=reason_counts[
            RISK_DECISION_REASON_ALLOW_PROCEED_LONG
        ],
        allow_proceed_short_count=reason_counts[
            RISK_DECISION_REASON_ALLOW_PROCEED_SHORT
        ],
        deny_orchestrator_held_count=reason_counts[
            RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD
        ],
        per_symbol_counts=_symbol_counts_to_rows(symbol_counts),
        lab_pointer_presence_count=lab_pointer_presence_count,
    )


def _build_summary(
    *,
    paper_mode_flag: PaperModeFlag,
    per_source_records: tuple[AggregateRollupPerSourceRecord, ...],
) -> AggregateRollupSummary:
    symbol_totals: dict[str, int] = {}
    for record in per_source_records:
        for symbol_count in record.per_symbol_counts:
            symbol_totals[symbol_count.symbol] = (
                symbol_totals.get(symbol_count.symbol, 0) + symbol_count.count
            )

    return AggregateRollupSummary(
        paper_mode_flag=paper_mode_flag,
        per_source_records=per_source_records,
        total_inputs=sum(record.total_inputs for record in per_source_records),
        total_allow_proceed_long_count=sum(
            record.allow_proceed_long_count for record in per_source_records
        ),
        total_allow_proceed_short_count=sum(
            record.allow_proceed_short_count for record in per_source_records
        ),
        total_deny_orchestrator_held_count=sum(
            record.deny_orchestrator_held_count for record in per_source_records
        ),
        total_lab_pointer_presence_count=sum(
            record.lab_pointer_presence_count for record in per_source_records
        ),
        per_symbol_total_counts=_symbol_counts_to_rows(symbol_totals),
    )


def _symbol_counts_to_rows(
    symbol_counts: dict[str, int],
) -> tuple[AggregateRollupPerSymbolCount, ...]:
    return tuple(
        AggregateRollupPerSymbolCount(symbol=symbol, count=symbol_counts[symbol])
        for symbol in sorted(symbol_counts)
    )


def _assert_lineage_matches_input(record: RiskDecisionRecord) -> None:
    assert record.risk_decision_id.startswith("risk_decision_")
    assert record.decision_id.startswith("decision_")
    assert record.prediction_id.startswith("prediction_")
    assert record.feature_snapshot_id.startswith("feature_snapshot_")
    assert record.live_blocked is True
