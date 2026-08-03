from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from v2.backend.app.cli import verify_pipeline_trust as trust
from v2.backend.app.services.market_state_integrity import (
    TrustGateResult,
    build_market_state_envelope_from_snapshot,
    persist_decision_replay,
)

_NON_BLOCKING_RECORDED_FINDING_IDS = {
    "mtf_alignment.missing_timeframe",
    "mtf_snapshot.missing",
    "parity.known_differences",
}


def _is_consumable_feature_record(feature: dict[str, Any]) -> bool:
    key = str(trust.first_value(feature, ("_key", "redis_key", "key")) or "").lower()
    if key.startswith("v2:features:latest:"):
        return True
    if trust.truthy(
        trust.first_value(
            feature,
            ("trainer_consumable", "model_consumable", "used_for_training", "accepted_for_training"),
        )
    ):
        return True
    return bool(
        trust.first_value(feature, ("feature_snapshot_id",))
        and trust.first_timestamp(feature, ("feature_cutoff", "decision_cutoff", "generated_at", "generated_utc"))
        and isinstance(feature.get("features"), dict)
    )


def _is_recorded_decision_record(decision: dict[str, Any]) -> bool:
    if trust.is_model_prediction_record(decision):
        return True
    source = str(trust.first_value(decision, ("_source", "_key", "redis_key", "key")) or "").lower()
    if "replay_snapshot" in source or "replay:snapshot" in source:
        return False
    if trust.requires_snapshot_evidence(decision) and any(
        trust.first_value(decision, (field,)) is not None
        for field in (
            "selected_action",
            "action_probabilities",
            "masa_generated_at",
            "masa_feature_cutoff",
            "masa_forecast_horizon",
            "ppo_observation_time",
            "ppo_feature_cutoff",
        )
    ):
        return True
    if not trust.first_value(decision, ("prediction_id", "decision_id")):
        return False
    return any(
        trust.first_value(decision, (field,)) is not None
        for field in (
            "decision_time",
            "decision_cutoff",
            "masa_generated_at",
            "masa_generated_utc",
            "ppo_observation_time",
            "feature_cutoff",
            "replay_snapshot_id",
            "replay_snapshot_key",
            "mtf_snapshot_id",
        )
    )


def _is_recorded_training_sample(sample: dict[str, Any]) -> bool:
    if trust.first_value(sample, ("row_classification", "sample_classification", "classification")) is not None:
        return True
    if trust.truthy(
        trust.first_value(sample, ("used_for_training", "accepted_for_training", "included_in_training", "accepted"))
    ):
        return True
    return bool(
        isinstance(sample.get("features"), dict)
        and trust.first_timestamp(sample, ("feature_cutoff", "decision_cutoff", "observation_time", "generated_at"))
        is not None
    )


def _compute_metrics(records: list[trust.SourceRecord]) -> dict[str, Any]:
    features = [feature for feature in trust.extract_features(records) if _is_consumable_feature_record(feature)]
    decisions = [decision for decision in trust.extract_decisions(records) if _is_recorded_decision_record(decision)]
    training_samples = [sample for sample in trust.extract_training_samples(records) if _is_recorded_training_sample(sample)]
    execution_records = trust.extract_execution_records(records)

    invalid_feature_states = 0
    future_feature_leak_count = 0
    for feature in features:
        vector = trust.extract_feature_vector(feature)
        invalid_count = trust.count_invalid_values(vector)
        decision_time = trust.first_timestamp(
            feature,
            ("decision_time", "decision_cutoff", "feature_cutoff", "generated_at", "generated_utc", "timestamp"),
        )
        source_times = trust.source_candle_timestamps(feature)
        future_count = 0
        if decision_time is not None:
            future_count = sum(
                1
                for source_time in source_times
                if trust.normalize_ms(source_time) > trust.normalize_ms(decision_time)
            )
        available_at = trust.first_timestamp(feature, ("available_at", "source_available_time", "source_received_time_est"))
        feature_cutoff = trust.first_timestamp(feature, ("feature_cutoff", "decision_cutoff", "decision_cutoff_time_est"))
        if invalid_count or future_count or available_at is None or feature_cutoff is None or trust.explicit_forward_fill_flag(feature):
            invalid_feature_states += 1
        future_feature_leak_count += future_count

    invalid_decision_states = 0
    masa_ppo_cutoff_mismatch_count = 0
    trades_blocked_by_data_quality = 0
    for decision in decisions:
        decision_time = trust.first_timestamp(decision, ("decision_time", "decision_cutoff", "generated_at", "generated_est", "timestamp"))
        masa_feature_cutoff = trust.first_timestamp(decision, ("masa_feature_cutoff", "masa_cutoff", "masa_input_cutoff"))
        ppo_feature_cutoff = trust.first_timestamp(decision, ("ppo_feature_cutoff", "feature_cutoff", "decision_cutoff"))
        required_missing = any(
            trust.first_value(decision, keys) is None
            for keys in (
                ("masa_generated_at", "masa_generated_utc"),
                ("masa_feature_cutoff", "masa_cutoff", "masa_input_cutoff"),
                ("masa_forecast_horizon", "forecast_horizon"),
                ("ppo_observation_time", "observation_time"),
                ("ppo_feature_cutoff", "feature_cutoff", "decision_cutoff"),
            )
        )
        masa_future = (
            decision_time is not None
            and masa_feature_cutoff is not None
            and trust.normalize_ms(masa_feature_cutoff) > trust.normalize_ms(decision_time)
        )
        ppo_future = (
            decision_time is not None
            and ppo_feature_cutoff is not None
            and trust.normalize_ms(ppo_feature_cutoff) > trust.normalize_ms(decision_time)
        )
        cutoff_mismatch = (
            masa_feature_cutoff is not None
            and ppo_feature_cutoff is not None
            and trust.normalize_ms(masa_feature_cutoff) != trust.normalize_ms(ppo_feature_cutoff)
        )
        if cutoff_mismatch:
            masa_ppo_cutoff_mismatch_count += 1
        replay_snapshot = trust.first_value(
            decision,
            ("replay_snapshot", "replay_snapshot_id", "market_state_replay_snapshot_id", "replay_snapshot_key"),
        )
        replay_write = trust.bool_or_none(trust.first_value(decision, ("replay_snapshot_write_success",)))
        if required_missing or masa_future or ppo_future or cutoff_mismatch or (replay_snapshot is None and replay_write is not True):
            invalid_decision_states += 1
        decision_id = str(
            trust.first_value(
                decision,
                ("decision_id", "prediction_id", "replay_snapshot_id", "market_state_replay_snapshot_id"),
            )
            or f"recorded_{invalid_decision_states}_{masa_ppo_cutoff_mismatch_count}"
        )
        try:
            envelope = build_market_state_envelope_from_snapshot(decision)
        except Exception:
            envelope = None
        persist_decision_replay(
            decision_id=decision_id,
            market_state_envelope=envelope,
            masa_output=decision,
            block_reason=(
                "recorded_state_verification_invalid"
                if required_missing or masa_future or ppo_future or cutoff_mismatch
                else None
            ),
            trust_gate_result=TrustGateResult(
                accepted=not (
                    required_missing
                    or masa_future
                    or ppo_future
                    or cutoff_mismatch
                    or (replay_snapshot is None and replay_write is not True)
                ),
                severity="reject"
                if (
                    required_missing
                    or masa_future
                    or ppo_future
                    or cutoff_mismatch
                    or (replay_snapshot is None and replay_write is not True)
                )
                else "accept",
                reject_reasons=tuple(
                    reason
                    for reason, failed in (
                        ("required_contract_fields_missing", required_missing),
                        ("masa_future_cutoff", masa_future),
                        ("ppo_future_cutoff", ppo_future),
                        ("masa_ppo_cutoff_mismatch", cutoff_mismatch),
                        ("replay_snapshot_missing", replay_snapshot is None and replay_write is not True),
                    )
                    if failed
                ),
                warnings=(),
                data_quality_score=1.0,
                future_leak_detected=bool(masa_future or ppo_future),
                cutoff_mismatch_detected=bool(cutoff_mismatch),
                replay_required=True,
                metrics={"source": "run_recorded_state_verification"},
            ),
            extra={"recorded_state_verification": True},
        )
        block_reason = str(
            trust.first_value(
                decision,
                ("strategy_router_block_reason", "paper_fill_block_reason", "risk_reason_code", "block_reason"),
            )
            or ""
        ).lower()
        if "data_quality" in block_reason or "market_state" in block_reason:
            trades_blocked_by_data_quality += 1

    invalid_training_states = 0
    training_samples_rejected_count = 0
    for sample in training_samples:
        classification = str(trust.first_value(sample, ("row_classification", "sample_classification", "classification")) or "").upper()
        dirty_flags = trust.collect_dirty_training_flags(sample, classification)
        accepted = trust.truthy(
            trust.first_value(sample, ("used_for_training", "accepted", "trainer_consumable", "included_in_training"))
        )
        feature_cutoff = trust.first_timestamp(sample, ("feature_cutoff", "decision_cutoff", "observation_time", "generated_at"))
        label_start = trust.first_timestamp(sample, ("label_start_time", "label_start", "horizon_start"))
        label_end = trust.first_timestamp(sample, ("label_end_time", "label_end", "horizon_end"))
        horizon_seconds = trust.numeric_value(
            trust.first_value(sample, ("prediction_horizon_seconds", "forecast_horizon_seconds", "horizon_seconds"))
        )
        future_label = (
            label_start is not None
            and label_end is not None
            and horizon_seconds is not None
            and ((trust.normalize_ms(label_end) - trust.normalize_ms(label_start)) / 1000.0) > horizon_seconds + 1
        )
        if dirty_flags or future_label or feature_cutoff is None:
            invalid_training_states += 1
        if accepted is not True or dirty_flags or future_label:
            training_samples_rejected_count += 1

    invalid_execution_states = 0
    position_transition_reject_count = 0
    for record in execution_records:
        position_before = trust.first_value(record, ("position_before", "before_position", "previous_position", "local_position_before"))
        requested_action = str(trust.first_value(record, ("requested_action", "action", "risk_action", "order_action")) or "").lower()
        position_after = trust.first_value(record, ("position_after", "after_position", "new_position", "local_position_after"))
        invalid_flag = trust.truthy(trust.first_value(record, ("invalid_transition", "transition_invalid")))
        invalid_transition = invalid_flag or trust.transition_is_invalid(position_before, requested_action, position_after)
        if invalid_transition:
            position_transition_reject_count += 1
            invalid_execution_states += 1
        block_reason = str(
            trust.first_value(
                record,
                ("strategy_router_block_reason", "paper_fill_block_reason", "risk_reason_code", "block_reason"),
            )
            or ""
        ).lower()
        if "data_quality" in block_reason or "market_state" in block_reason:
            trades_blocked_by_data_quality += 1

    invalid_state_count = (
        invalid_feature_states
        + invalid_decision_states
        + invalid_training_states
        + invalid_execution_states
    )
    total_states = max(
        1,
        len(features) + len(decisions) + len(training_samples) + len(execution_records),
    )
    return {
        "invalid_state_count": invalid_state_count,
        "invalid_state_rate": round(invalid_state_count / total_states, 6),
        "future_feature_leak_count": future_feature_leak_count,
        "masa_ppo_cutoff_mismatch_count": masa_ppo_cutoff_mismatch_count,
        "training_samples_rejected_count": training_samples_rejected_count,
        "trades_blocked_by_data_quality": trades_blocked_by_data_quality,
        "position_transition_reject_count": position_transition_reject_count,
        "records_loaded": len(records),
        "features_loaded": len(features),
        "decisions_loaded": len(decisions),
        "training_samples_loaded": len(training_samples),
        "execution_records_loaded": len(execution_records),
    }


def _render_text_report(*, report: trust.TrustReport, metrics: dict[str, Any], input_paths: list[str]) -> str:
    summary = report.to_jsonable()["summary"]
    lines = [
        "# Recorded State Verification Report",
        "",
        f"Inputs: {', '.join(input_paths)}",
        f"Total findings: {summary['total_findings']}",
        f"Critical failures: {summary['critical_failures']}",
        f"Failures: {summary['failures']}",
        "",
        "## Metrics",
        "",
        f"- invalid_state_count: {metrics['invalid_state_count']}",
        f"- invalid_state_rate: {metrics['invalid_state_rate']}",
        f"- future_feature_leak_count: {metrics['future_feature_leak_count']}",
        f"- masa_ppo_cutoff_mismatch_count: {metrics['masa_ppo_cutoff_mismatch_count']}",
        f"- training_samples_rejected_count: {metrics['training_samples_rejected_count']}",
        f"- trades_blocked_by_data_quality: {metrics['trades_blocked_by_data_quality']}",
        f"- position_transition_reject_count: {metrics['position_transition_reject_count']}",
        "",
        "## Failing checks",
        "",
    ]
    for finding in report.findings:
        if finding.status == "FAIL":
            lines.append(f"- {finding.check_id}: {finding.title}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_recorded_state_verification",
        description="Run recorded-state trust verification against exported real bot state or replay snapshots.",
    )
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        help="JSON/JSONL file or directory containing recorded bot state exports.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for JSON and text verification reports.",
    )
    parser.add_argument("--max-files", type=int, default=500)
    parser.add_argument("--max-examples", type=int, default=5)
    args = parser.parse_args(argv)

    trust_args = argparse.Namespace(
        input=list(args.input),
        output_dir=str(args.output_dir),
        redis_url="",
        redis_pattern=[],
        max_files=int(args.max_files),
        max_redis_keys=0,
        max_examples=int(args.max_examples),
        source_disagreement_bps=50.0,
        strict_unknown=True,
    )

    records = trust.load_records(trust_args)
    report = trust.verify_records(records, trust_args)
    report_payload = report.to_jsonable()
    summary = dict(report_payload["summary"])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    trust.write_reports(report, args.output_dir)
    metrics = _compute_metrics(records)
    payload = {
        "input_paths": list(args.input),
        "output_dir": str(args.output_dir),
        "summary": summary,
        "metrics": metrics,
        "findings": list(report_payload["findings"]),
        "section_summaries": dict(report.summaries),
    }
    (args.output_dir / "recorded_state_verification_report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (args.output_dir / "recorded_state_verification_report.txt").write_text(
        _render_text_report(report=report, metrics=metrics, input_paths=list(args.input)),
        encoding="utf-8",
    )
    effective_critical_failures = sum(
        1
        for finding in report.findings
        if finding.status == "FAIL"
        and finding.severity == "Critical"
        and finding.check_id not in _NON_BLOCKING_RECORDED_FINDING_IDS
    )
    exit_code = 1 if effective_critical_failures > 0 else 0
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "total_findings": summary["total_findings"],
                "critical_failures": effective_critical_failures,
                "invalid_state_count": metrics["invalid_state_count"],
                "invalid_state_rate": metrics["invalid_state_rate"],
                "future_feature_leak_count": metrics["future_feature_leak_count"],
                "masa_ppo_cutoff_mismatch_count": metrics["masa_ppo_cutoff_mismatch_count"],
                "training_samples_rejected_count": metrics["training_samples_rejected_count"],
                "trades_blocked_by_data_quality": metrics["trades_blocked_by_data_quality"],
                "position_transition_reject_count": metrics["position_transition_reject_count"],
            },
            sort_keys=True,
        )
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
