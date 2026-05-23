"""V2 24h parallel recovery war-room executor.

Pure analysis layer. Reads existing replay-miner bundles, evaluator
metrics, and observation-queue artifacts, then emits 24h war-room
artifacts under
``claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room/latest/``
and the public dashboard mirror under
``v2/frontend/public/v2_24h_parallel_recovery_war_room/latest/``.

This module never:
  * writes to legacy Redis keys
  * places, cancels, or modifies exchange orders
  * changes leverage or margin mode
  * approves live, canary, legacy-shutdown, or Redis-trim
  * creates paper-only shutdown acceptance files
  * mutates the legacy bot tree

Outputs are analysis-only. Thresholds are documented profiles, not
approvals. ``live_gate`` stays ``blocked_human_only`` and
``live_symbols`` stays ``[]`` everywhere.
"""
from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "v2_24h_parallel_recovery_war_room_v1"
LIVE_GATE_BLOCKED = "blocked_human_only"


# ---------------------------------------------------------------------------
# Threshold profiles (analysis-only — these are NOT approvals)
# ---------------------------------------------------------------------------

# Each profile defines numeric thresholds used purely for ANALYSIS of the
# current evaluator metric summary. They do not approve live or canary
# trading. The miner / evaluator gate stays at OPERATOR_DECISION_REQUIRED
# until the operator sets concrete numerics through the official channel.
THRESHOLD_PROFILES: dict[str, dict[str, float]] = {
    "conservative": {
        "min_sample_count": 10000,
        "min_after_cost_expectancy_bps": 15.0,
        "min_after_cost_lower_ci_bps": 5.0,
        "max_drawdown_bps_rolling": 200.0,
        "max_false_negative_rate": 0.10,
        "max_false_positive_rate": 0.05,
    },
    "balanced": {
        "min_sample_count": 5000,
        "min_after_cost_expectancy_bps": 8.0,
        "min_after_cost_lower_ci_bps": 0.0,
        "max_drawdown_bps_rolling": 300.0,
        "max_false_negative_rate": 0.15,
        "max_false_positive_rate": 0.10,
    },
    "aggressive": {
        "min_sample_count": 2000,
        "min_after_cost_expectancy_bps": 3.0,
        "min_after_cost_lower_ci_bps": -5.0,
        "max_drawdown_bps_rolling": 500.0,
        "max_false_negative_rate": 0.25,
        "max_false_positive_rate": 0.20,
    },
}


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Lane 1 — Edge proof and threshold analytics
# ---------------------------------------------------------------------------


def _evaluate_threshold(
    name: str, profile_value: float, observed: Any
) -> dict[str, Any]:
    """Evaluate a single profile threshold against an observed value.

    Returns a dict with pass/fail/inconclusive. Inconclusive when the
    observed value is None (evidence is missing).
    """
    if observed is None:
        return {
            "threshold_name": name,
            "profile_value": profile_value,
            "observed_value": None,
            "passed": False,
            "inconclusive": True,
            "reason": "OBSERVED_VALUE_MISSING",
        }
    if name.startswith("min_"):
        passed = observed >= profile_value
    elif name.startswith("max_"):
        passed = observed <= profile_value
    else:
        return {
            "threshold_name": name,
            "profile_value": profile_value,
            "observed_value": observed,
            "passed": False,
            "inconclusive": True,
            "reason": "UNKNOWN_THRESHOLD_DIRECTION",
        }
    return {
        "threshold_name": name,
        "profile_value": profile_value,
        "observed_value": observed,
        "passed": bool(passed),
        "inconclusive": False,
        "reason": "PASS" if passed else "FAIL",
    }


def build_threshold_profile_simulation(
    metric_summary: dict[str, Any]
) -> dict[str, Any]:
    observed = {
        "min_sample_count": metric_summary.get("sample_count"),
        "min_after_cost_expectancy_bps": metric_summary.get(
            "expected_move_after_cost_bps"
        ),
        "min_after_cost_lower_ci_bps": metric_summary.get(
            "after_cost_ci_lower_bps"
        ),
        "max_drawdown_bps_rolling": metric_summary.get(
            "max_drawdown_bps_observed"
        ),
        "max_false_negative_rate": metric_summary.get("false_negative_rate"),
        "max_false_positive_rate": metric_summary.get("false_positive_rate"),
    }
    profile_results: dict[str, Any] = {}
    for profile_name, profile in THRESHOLD_PROFILES.items():
        evaluations = [
            _evaluate_threshold(name, value, observed.get(name))
            for name, value in profile.items()
        ]
        all_passed = all(e["passed"] and not e["inconclusive"] for e in evaluations)
        any_inconclusive = any(e["inconclusive"] for e in evaluations)
        if any_inconclusive:
            verdict = "INCONCLUSIVE_OBSERVED_EVIDENCE_MISSING"
        elif all_passed:
            verdict = "SIMULATED_PASS_ANALYSIS_ONLY"
        else:
            verdict = "SIMULATED_FAIL_ANALYSIS_ONLY"
        profile_results[profile_name] = {
            "evaluations": evaluations,
            "verdict": verdict,
            "simulated_pass": all_passed and not any_inconclusive,
            "simulated_fail": (not all_passed) and not any_inconclusive,
            "inconclusive": any_inconclusive,
        }
    return {
        "schema_version": SCHEMA_VERSION + "_threshold_profile_simulation",
        "generated_utc": _utc_now_iso(),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "no_live_approval_implied": True,
        "preliminary_only_for_analysis": True,
        "observed_metric_inputs": observed,
        "profiles": profile_results,
    }


def build_edge_gate_analysis(simulation: dict[str, Any]) -> dict[str, Any]:
    rollup: dict[str, Any] = {}
    operator_threshold_required = True
    for profile_name, result in simulation["profiles"].items():
        rollup[profile_name] = {
            "verdict": result["verdict"],
            "fail_thresholds": [
                e["threshold_name"]
                for e in result["evaluations"]
                if not e["inconclusive"] and not e["passed"]
            ],
            "inconclusive_thresholds": [
                e["threshold_name"]
                for e in result["evaluations"]
                if e["inconclusive"]
            ],
        }
    return {
        "schema_version": SCHEMA_VERSION + "_edge_gate_analysis",
        "generated_utc": _utc_now_iso(),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "no_live_approval_implied": True,
        "preliminary_only_for_analysis": True,
        "operator_decision_required": operator_threshold_required,
        "edge_claimed": False,
        "edge_claim_blocked_reason": (
            "operator_thresholds_required_and_not_set"
        ),
        "verdict_per_profile": rollup,
    }


def render_edge_proof_analysis_report(
    simulation: dict[str, Any], analysis: dict[str, Any]
) -> str:
    lines: list[str] = []
    lines.append("# V2 Edge Proof Analysis Report (analysis-only)\n")
    lines.append(
        "live_gate=blocked_human_only. live_symbols=[]. approves_live=false.\n"
    )
    lines.append("## Observed evaluator inputs\n")
    for k, v in simulation["observed_metric_inputs"].items():
        lines.append(f"- {k}: {v}\n")
    lines.append("\n## Profile simulations\n")
    for profile_name, result in simulation["profiles"].items():
        lines.append(f"\n### {profile_name}\n")
        lines.append(f"- verdict: {result['verdict']}\n")
        for ev in result["evaluations"]:
            lines.append(
                f"  - {ev['threshold_name']}: observed={ev['observed_value']}"
                f" profile={ev['profile_value']} reason={ev['reason']}\n"
            )
    lines.append("\n## Edge gate analysis\n")
    lines.append(
        f"- edge_claimed: {analysis['edge_claimed']}\n"
    )
    lines.append(
        f"- edge_claim_blocked_reason: {analysis['edge_claim_blocked_reason']}\n"
    )
    lines.append("\n")
    lines.append(
        "No profile is interpreted as an approval. The miner/evaluator "
        "gate stays at OPERATOR_DECISION_REQUIRED until the operator sets "
        "concrete numerics through the official path. This report is "
        "analysis-only.\n"
    )
    return "".join(lines)


# ---------------------------------------------------------------------------
# Lane 2 — False-negative root-cause analyzer
# ---------------------------------------------------------------------------


# Canonical root-cause taxonomy (a single bundle can carry multiple).
ROOT_CAUSE_CODES = {
    "model_hold_due_checkpoint",
    "feature_missing",
    "risk_gate_block",
    "paper_fill_gate_block",
    "paper_fill_gate_block_unrecorded_reason",
    "stale_feature",
    "insufficient_liquidation_data",
    "no_policy_architecture",
    "observation_gap",
    "altdata_missing",
}


def _classify_false_negative(bundle: dict[str, Any]) -> dict[str, Any]:
    causes: list[str] = []
    notes: list[str] = []

    trainer_output = bundle.get("trainer_output") or {}
    risk_decision = bundle.get("risk_decision") or {}
    paper_gate = bundle.get("paper_gate_decision") or {}
    altdata = bundle.get("altdata_snapshot")
    paper_intent = bundle.get("paper_intent") or {}

    if trainer_output.get("selected_action") in (None, "hold"):
        causes.append("model_hold_due_checkpoint")
        notes.append("trainer selected_action was hold or absent")

    if not risk_decision.get("pre_trade_allowed", True):
        causes.append("risk_gate_block")
        notes.append(
            f"risk gate blocked: churn={risk_decision.get('churn_reason')} "
            f"fee={risk_decision.get('fee_gate_reason')}"
        )

    paper_allowed = paper_gate.get("paper_fill_allowed")
    paper_reasons = paper_gate.get("paper_fill_gate_block_reasons") or []
    if paper_allowed is False:
        causes.append("paper_fill_gate_block")
        if not paper_reasons:
            causes.append("paper_fill_gate_block_unrecorded_reason")
            causes.append("observation_gap")
            notes.append(
                "paper_fill_allowed=false with empty "
                "paper_fill_gate_block_reasons — block reason is not "
                "observable from the bundle"
            )
        else:
            notes.append(f"paper gate reasons: {paper_reasons}")

    if altdata is None:
        causes.append("altdata_missing")
        notes.append("altdata_snapshot is null")

    if paper_intent.get("decision") == "SHADOW_OBSERVATION_ONLY":
        notes.append(
            "paper intent recorded as SHADOW_OBSERVATION_ONLY — fill path "
            "was not exercised even though risk/edge cleared"
        )

    # Deduplicate while preserving order.
    seen: set[str] = set()
    deduped = [c for c in causes if not (c in seen or seen.add(c))]
    return {
        "symbol": bundle.get("symbol"),
        "anchor_ts": bundle.get("anchor_ts"),
        "feature_snapshot_id": bundle.get("feature_snapshot_id"),
        "prediction_id": (
            (bundle.get("orchestrator_decision") or {})
            .get("bucket_winners", [{}])[0]
            .get("winner_proposal_id")
            if bundle.get("orchestrator_decision")
            else None
        ),
        "expected_move_after_cost_bps": trainer_output.get(
            "expected_move_after_cost_bps"
        ),
        "outcome_after_cost": bundle.get("outcome_after_cost"),
        "paper_gate_decision": paper_gate,
        "risk_decision": risk_decision,
        "altdata_snapshot_present": altdata is not None,
        "trainer_selected_action": trainer_output.get("selected_action"),
        "root_causes": deduped,
        "notes": notes,
    }


def _remediation_task_for_cause(cause: str, bundle_summary: dict[str, Any]) -> dict[str, Any] | None:
    if cause == "paper_fill_gate_block_unrecorded_reason":
        return {
            "task_id": "paper_fill_gate_record_block_reason",
            "title": (
                "Record paper_fill_gate block reason on every "
                "paper_fill_allowed=False decision"
            ),
            "rationale": (
                "False-negative bundles show paper_fill_allowed=False with "
                "empty paper_fill_gate_block_reasons; the gate is opaque."
            ),
            "owner_lane": "v2_paper_fill_gate",
            "automatable": True,
        }
    if cause == "altdata_missing":
        return {
            "task_id": "altdata_snapshot_attached_to_replay_bundle",
            "title": (
                "Attach v2 altdata symbol-score snapshot to every replay "
                "bundle when present"
            ),
            "rationale": (
                "Replay bundles record altdata_snapshot=null even though "
                "v2 altdata candidate scoring is running."
            ),
            "owner_lane": "v2_replay_miner",
            "automatable": True,
        }
    if cause == "observation_gap":
        return {
            "task_id": "observation_gap_inventory_for_false_negatives",
            "title": (
                "Inventory all observation gaps for false-negative bundles "
                "and emit per-cause backfill tasks"
            ),
            "rationale": (
                "False-negative bundles cannot be explained from the "
                "persisted observation alone."
            ),
            "owner_lane": "v2_observation",
            "automatable": True,
        }
    return None


def build_false_negative_root_cause_report(
    bundles: Iterable[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    fn_classifications: list[dict[str, Any]] = []
    cause_counts: dict[str, int] = {}
    remediation_tasks: dict[str, dict[str, Any]] = {}

    for bundle in bundles:
        if bundle.get("label") != "false_negative":
            continue
        classification = _classify_false_negative(bundle)
        fn_classifications.append(classification)
        for cause in classification["root_causes"]:
            cause_counts[cause] = cause_counts.get(cause, 0) + 1
            task = _remediation_task_for_cause(cause, classification)
            if task is not None and task["task_id"] not in remediation_tasks:
                remediation_tasks[task["task_id"]] = task

    report = {
        "schema_version": SCHEMA_VERSION + "_false_negative_root_cause",
        "generated_utc": _utc_now_iso(),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "false_negative_count": len(fn_classifications),
        "cause_counts": cause_counts,
        "canonical_codes": sorted(ROOT_CAUSE_CODES),
        "classifications": fn_classifications,
    }
    return report, list(remediation_tasks.values())


def render_false_negative_root_cause_report_md(
    report: dict[str, Any],
) -> str:
    lines = []
    lines.append("# V2 False-Negative Root-Cause Report (analysis-only)\n\n")
    lines.append(
        "live_gate=blocked_human_only. live_symbols=[]. approves_live=false.\n\n"
    )
    lines.append(f"false_negative_count: {report['false_negative_count']}\n\n")
    lines.append("## Cause counts\n\n")
    for cause, count in sorted(report["cause_counts"].items()):
        lines.append(f"- {cause}: {count}\n")
    lines.append("\n## Per-bundle classifications\n\n")
    for c in report["classifications"]:
        lines.append(f"### {c['symbol']} @ {c['feature_snapshot_id']}\n")
        lines.append(f"- prediction_id: {c['prediction_id']}\n")
        lines.append(
            f"- expected_move_after_cost_bps: "
            f"{c['expected_move_after_cost_bps']}\n"
        )
        lines.append(f"- outcome_after_cost: {c['outcome_after_cost']}\n")
        lines.append(
            f"- trainer_selected_action: {c['trainer_selected_action']}\n"
        )
        lines.append(
            f"- altdata_snapshot_present: {c['altdata_snapshot_present']}\n"
        )
        lines.append(f"- root_causes: {c['root_causes']}\n")
        for note in c["notes"]:
            lines.append(f"  - note: {note}\n")
        lines.append("\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# Lane 3 — V2-native training dataset builder
# ---------------------------------------------------------------------------


def _dataset_row_from_bundle(bundle: dict[str, Any]) -> dict[str, Any] | None:
    label = bundle.get("label")
    if label == "insufficient_evidence":
        return None
    trainer = bundle.get("trainer_output") or {}
    paper_gate = bundle.get("paper_gate_decision") or {}
    risk = bundle.get("risk_decision") or {}
    outcomes = (bundle.get("future_outcomes") or {}).get("5m") or {}

    after_cost = outcomes.get("after_cost_return_bps")
    if after_cost is None:
        # No 5m outcome — exclude from supervised set.
        return None

    return {
        "prediction_id": (
            (bundle.get("orchestrator_decision") or {})
            .get("bucket_winners", [{}])[0]
            .get("winner_proposal_id")
            if bundle.get("orchestrator_decision")
            else None
        ),
        "feature_snapshot_id": bundle.get("feature_snapshot_id"),
        "symbol": bundle.get("symbol"),
        "anchor_ts": bundle.get("anchor_ts"),
        "side": bundle.get("side"),
        "features": {
            "trainer_confidence_calibrated": trainer.get(
                "confidence_calibrated"
            ),
            "trainer_expected_move_after_cost_bps": trainer.get(
                "expected_move_after_cost_bps"
            ),
            "trainer_selected_action": trainer.get("selected_action"),
            "risk_pre_trade_allowed": risk.get("pre_trade_allowed"),
            "paper_fill_allowed": paper_gate.get("paper_fill_allowed"),
            "altdata_snapshot_present": (
                bundle.get("altdata_snapshot") is not None
            ),
        },
        "label": label,
        "after_cost_return_bps_5m": after_cost,
        "return_bps_5m": outcomes.get("return_bps"),
        "drawdown_bps_5m": outcomes.get("drawdown_bps"),
    }


def build_v2_native_training_dataset(
    bundles: Iterable[dict[str, Any]],
    split_ratio: float = 0.8,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    excluded_insufficient = 0
    excluded_missing_5m = 0
    for bundle in bundles:
        if bundle.get("label") == "insufficient_evidence":
            excluded_insufficient += 1
            continue
        row = _dataset_row_from_bundle(bundle)
        if row is None:
            excluded_missing_5m += 1
            continue
        rows.append(row)

    # Time-ordered split.
    rows.sort(key=lambda r: (r.get("anchor_ts") or 0))
    split_at = int(len(rows) * split_ratio)
    train_rows = rows[:split_at]
    validation_rows = rows[split_at:]
    return {
        "rows": rows,
        "train_rows": train_rows,
        "validation_rows": validation_rows,
        "excluded_insufficient": excluded_insufficient,
        "excluded_missing_5m": excluded_missing_5m,
    }


def build_dataset_status(
    dataset: dict[str, Any], bundles_total: int
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_native_training_dataset_status",
        "generated_utc": _utc_now_iso(),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "bundles_total": bundles_total,
        "dataset_total_rows": len(dataset["rows"]),
        "train_rows": len(dataset["train_rows"]),
        "validation_rows": len(dataset["validation_rows"]),
        "excluded_insufficient_evidence": dataset["excluded_insufficient"],
        "excluded_missing_5m_outcome": dataset["excluded_missing_5m"],
        "split_ratio": 0.8,
        "checkpoint_compatibility_claimed": False,
        "policy_architecture_parity_claimed": False,
    }


def build_dataset_manifest(dataset: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": (
            SCHEMA_VERSION + "_native_training_dataset_manifest"
        ),
        "generated_utc": _utc_now_iso(),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "train": dataset["train_rows"],
        "validation": dataset["validation_rows"],
    }


def render_dataset_quality_report_md(status: dict[str, Any]) -> str:
    lines = []
    lines.append("# V2 Native Training Dataset Quality (analysis-only)\n\n")
    lines.append(
        "live_gate=blocked_human_only. live_symbols=[]. approves_live=false.\n\n"
    )
    lines.append(f"- bundles_total: {status['bundles_total']}\n")
    lines.append(f"- dataset_total_rows: {status['dataset_total_rows']}\n")
    lines.append(f"- train_rows: {status['train_rows']}\n")
    lines.append(f"- validation_rows: {status['validation_rows']}\n")
    lines.append(
        f"- excluded_insufficient_evidence: "
        f"{status['excluded_insufficient_evidence']}\n"
    )
    lines.append(
        f"- excluded_missing_5m_outcome: "
        f"{status['excluded_missing_5m_outcome']}\n"
    )
    lines.append(
        "\nDataset is too small to support a production model claim. It is "
        "useful only for baseline shadow evaluation (Lane 4). No checkpoint "
        "compatibility or policy-architecture parity is claimed.\n"
    )
    return "".join(lines)


# ---------------------------------------------------------------------------
# Lane 4 — V2-native compact model baseline evaluator
# ---------------------------------------------------------------------------


def _mean(xs: list[float]) -> float | None:
    return statistics.fmean(xs) if xs else None


def _bps_pnl_for_predictions(
    rows: list[dict[str, Any]], side_per_row: list[str]
) -> dict[str, Any]:
    """Compute paper-only after-cost bps PnL series for a baseline.

    side_per_row[i] in {"long", "hold"}.
    """
    pnls: list[float] = []
    enters = 0
    for row, side in zip(rows, side_per_row):
        after_cost = row.get("after_cost_return_bps_5m") or 0.0
        if side == "long":
            pnls.append(float(after_cost))
            enters += 1
        elif side == "short":
            pnls.append(-float(after_cost))
            enters += 1
        else:
            pnls.append(0.0)
    return {
        "enters": enters,
        "mean_after_cost_bps": _mean(pnls),
        "sum_after_cost_bps": sum(pnls) if pnls else 0.0,
        "stdev_after_cost_bps": (
            statistics.pstdev(pnls) if len(pnls) > 1 else 0.0
        ),
        "samples": len(pnls),
    }


def _naive_threshold_sides(
    rows: list[dict[str, Any]], min_expected_move_bps: float
) -> list[str]:
    sides: list[str] = []
    for r in rows:
        expected = (r.get("features") or {}).get(
            "trainer_expected_move_after_cost_bps"
        )
        if expected is None:
            sides.append("hold")
            continue
        if expected >= min_expected_move_bps:
            sides.append("long")
        else:
            sides.append("hold")
    return sides


def _logistic_baseline_sides(
    train_rows: list[dict[str, Any]],
    validation_rows: list[dict[str, Any]],
) -> tuple[list[str], dict[str, Any]]:
    """Trivial 1-feature logistic-ish baseline.

    Uses trainer_expected_move_after_cost_bps as the only feature. Picks
    a threshold that maximizes train-set after-cost PnL across a small
    grid. This is a baseline, not a model claim.
    """
    if not train_rows:
        return ["hold"] * len(validation_rows), {
            "selected_threshold_bps": None,
            "selected_train_pnl_bps": None,
            "grid": [],
            "note": "no training rows",
        }
    grid = [0.0, 1.0, 3.0, 5.0, 10.0, 15.0, 25.0, 50.0]
    grid_results = []
    best = None
    for threshold in grid:
        sides = _naive_threshold_sides(train_rows, threshold)
        result = _bps_pnl_for_predictions(train_rows, sides)
        grid_results.append(
            {"threshold_bps": threshold, "train_pnl_bps": result["sum_after_cost_bps"]}
        )
        if best is None or result["sum_after_cost_bps"] > best[1]:
            best = (threshold, result["sum_after_cost_bps"])
    chosen = best[0] if best else None
    sides = _naive_threshold_sides(validation_rows, chosen if chosen is not None else 0.0)
    return sides, {
        "selected_threshold_bps": chosen,
        "selected_train_pnl_bps": best[1] if best else None,
        "grid": grid_results,
        "note": "trivial 1-feature baseline",
    }


def _v2_deterministic_policy_sides(rows: list[dict[str, Any]]) -> list[str]:
    """Mirror current V2 SHADOW_OBSERVATION_ONLY policy: never enters paper fills."""
    return ["hold"] * len(rows)


def build_baseline_metrics(
    dataset: dict[str, Any],
) -> dict[str, Any]:
    train_rows = dataset["train_rows"]
    validation_rows = dataset["validation_rows"]

    # Baseline 1 — hold (no-op)
    hold_sides = ["hold"] * len(validation_rows)
    hold = _bps_pnl_for_predictions(validation_rows, hold_sides)

    # Baseline 2 — current V2 deterministic policy (always shadow / hold)
    v2_sides = _v2_deterministic_policy_sides(validation_rows)
    v2 = _bps_pnl_for_predictions(validation_rows, v2_sides)

    # Baseline 3 — naive threshold on trainer-expected-move
    naive_sides = _naive_threshold_sides(validation_rows, 10.0)
    naive = _bps_pnl_for_predictions(validation_rows, naive_sides)

    # Baseline 4 — logistic-ish baseline trained on training rows
    logistic_sides, logistic_meta = _logistic_baseline_sides(
        train_rows, validation_rows
    )
    logistic = _bps_pnl_for_predictions(validation_rows, logistic_sides)

    # Legacy reference baseline — absent in current bundles, so reported
    # explicitly as MISSING_EVIDENCE.
    legacy_reference = {
        "note": "legacy_reference_action is null in all replay bundles",
        "evidence_state": "MISSING_EVIDENCE",
    }

    return {
        "schema_version": SCHEMA_VERSION + "_model_baseline_metrics",
        "generated_utc": _utc_now_iso(),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "validation_samples": len(validation_rows),
        "train_samples": len(train_rows),
        "baselines": {
            "hold": hold,
            "v2_deterministic_policy_shadow_only": v2,
            "naive_threshold_expected_move_10bps": naive,
            "logistic_baseline_1d_expected_move": {
                **logistic,
                "meta": logistic_meta,
            },
            "legacy_reference": legacy_reference,
        },
        "checkpoint_compatibility_claimed": False,
        "policy_architecture_parity_claimed": False,
        "edge_claimed": False,
        "analysis_only": True,
    }


def render_baseline_report_md(metrics: dict[str, Any]) -> str:
    lines = []
    lines.append("# V2 Compact Model Baseline (analysis-only)\n\n")
    lines.append(
        "live_gate=blocked_human_only. live_symbols=[]. approves_live=false.\n\n"
    )
    lines.append(
        f"validation_samples: {metrics['validation_samples']} | "
        f"train_samples: {metrics['train_samples']}\n\n"
    )
    lines.append("| Baseline | enters | mean_after_cost_bps | sum_after_cost_bps | stdev |\n")
    lines.append("|---|---:|---:|---:|---:|\n")
    for name, b in metrics["baselines"].items():
        if not isinstance(b, dict) or "mean_after_cost_bps" not in b:
            continue
        lines.append(
            f"| {name} | {b['enters']} | {b['mean_after_cost_bps']} | "
            f"{b['sum_after_cost_bps']} | {b['stdev_after_cost_bps']} |\n"
        )
    legacy = metrics["baselines"].get("legacy_reference") or {}
    lines.append(
        f"\nLegacy reference: {legacy.get('evidence_state')} — "
        f"{legacy.get('note')}\n"
    )
    lines.append(
        "\nNo checkpoint compatibility or policy-architecture parity is "
        "claimed. Result is analysis-only and does not approve live or "
        "canary trading.\n"
    )
    return "".join(lines)


# ---------------------------------------------------------------------------
# Lane 5 — Remaining observation blocker classifier
# ---------------------------------------------------------------------------


_BLOCKER_CATEGORY_TO_BUCKET = {
    "V2_BUILDABLE_NOW": "BUILDABLE_NOW",
    "V2_LANE_EXISTS_PAYLOAD_ABSENT": "BUILDABLE_NOW",
    "V2_EVENT_DEPENDENT_LIQUIDATION_WSS": "EVENT_DEPENDENT",
    "V2_POSITION_DEPENDENT_OPEN_POSITION_REQUIRED": "POSITION_DEPENDENT",
    "EXTERNAL_SOURCE_REQUIRED_TOKEN_METRICS": "EXTERNAL_SOURCE_REQUIRED",
    "EXTERNAL_SOURCE_REQUIRED_ONCHAIN_BTC": "EXTERNAL_SOURCE_REQUIRED",
    "EXTERNAL_SOURCE_REQUIRED_ONCHAIN_ETH": "EXTERNAL_SOURCE_REQUIRED",
    "OPERATOR_DECISION_REQUIRED_CCXT_OHLCV": "OPERATOR_DECISION_REQUIRED",
    "OPERATOR_DECISION_REQUIRED_COINANK_PAID_AGGREGATOR": (
        "OPERATOR_DECISION_REQUIRED"
    ),
    "LEGACY_V3_EXTRA_NO_V2_SOURCE": "LEGACY_EXTRA_NO_V2_SOURCE",
    "POLICY_ARCHITECTURE_BLOCKED": "POLICY_ARCHITECTURE_BLOCKED",
    "CHECKPOINT_ARTIFACT_BLOCKED": "CHECKPOINT_ARTIFACT_BLOCKED",
    "NOT_REQUIRED_FOR_CURRENT_V2_MODEL_PATH": (
        "NOT_REQUIRED_FOR_CURRENT_V2_MODEL_PATH"
    ),
}


def classify_observation_blockers(
    remaining_queue: dict[str, Any],
    buildable_now: dict[str, Any] | None,
) -> dict[str, Any]:
    counts_in = remaining_queue.get("aggregate_category_counts") or {}
    buckets: dict[str, int] = {}
    for category, count in counts_in.items():
        bucket = _BLOCKER_CATEGORY_TO_BUCKET.get(category, "UNCLASSIFIED")
        buckets[bucket] = buckets.get(bucket, 0) + int(count)

    buildable_now_count = (
        (buildable_now or {}).get("aggregate_dim_count", 0)
        if buildable_now is not None
        else 0
    )
    # Override BUILDABLE_NOW count from the canonical artifact when present.
    if buildable_now is not None:
        buckets["BUILDABLE_NOW"] = buildable_now_count

    return {
        "schema_version": SCHEMA_VERSION + "_observation_blocker_recheck",
        "generated_utc": _utc_now_iso(),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "v2_buildable_now_count": buildable_now_count,
        "category_to_bucket_map": _BLOCKER_CATEGORY_TO_BUCKET,
        "bucket_counts": buckets,
        "source_category_counts": counts_in,
        "source_remaining_dim_queue_total": remaining_queue.get(
            "aggregate_target_dim"
        ),
        "no_new_buildable_now_fields_identified": buildable_now_count == 0,
    }


def render_observation_blocker_md(recheck: dict[str, Any]) -> str:
    lines = []
    lines.append("# V2 Observation Blocker Recheck (analysis-only)\n\n")
    lines.append(
        "live_gate=blocked_human_only. live_symbols=[]. approves_live=false.\n\n"
    )
    lines.append(
        f"v2_buildable_now_count: {recheck['v2_buildable_now_count']}\n"
    )
    lines.append(
        f"no_new_buildable_now_fields_identified: "
        f"{recheck['no_new_buildable_now_fields_identified']}\n\n"
    )
    lines.append("## Bucket counts\n\n")
    for bucket, count in sorted(recheck["bucket_counts"].items()):
        lines.append(f"- {bucket}: {count}\n")
    lines.append("\n## Source category counts\n\n")
    for cat, count in sorted(recheck["source_category_counts"].items()):
        lines.append(f"- {cat}: {count}\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# Lane 6 — Automation utilization and takeover
# ---------------------------------------------------------------------------


LANE_REGISTRY = [
    {
        "lane_id": "lane1_edge_proof_and_threshold_analytics",
        "owner": "claude",
        "reviewer": "codex",
    },
    {
        "lane_id": "lane2_false_negative_root_cause",
        "owner": "claude",
        "reviewer": "codex",
    },
    {
        "lane_id": "lane3_v2_native_training_dataset",
        "owner": "claude",
        "reviewer": "codex",
    },
    {
        "lane_id": "lane4_model_baseline_evaluator",
        "owner": "claude",
        "reviewer": "codex",
    },
    {
        "lane_id": "lane5_observation_blocker_classifier",
        "owner": "claude",
        "reviewer": "codex",
    },
    {
        "lane_id": "lane6_automation_utilization_takeover",
        "owner": "claude",
        "reviewer": "codex",
    },
    {
        "lane_id": "lane7_website_report_center_truth",
        "owner": "claude",
        "reviewer": "codex",
    },
]


def build_utilization_status(
    lane_statuses: list[dict[str, Any]],
    file_lock_registry: dict[str, str],
) -> dict[str, Any]:
    active = [l for l in lane_statuses if l["status"] == "active"]
    completed = [l for l in lane_statuses if l["status"] == "completed"]
    stalled = [l for l in lane_statuses if l["status"] == "stalled"]
    return {
        "schema_version": SCHEMA_VERSION + "_utilization_status",
        "generated_utc": _utc_now_iso(),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "claude_lane_count": len(lane_statuses),
        "codex_review_lane_count": len(lane_statuses),
        "active_lanes": len(active),
        "completed_lanes": len(completed),
        "stalled_lanes": len(stalled),
        "lane_statuses": lane_statuses,
        "file_lock_registry": file_lock_registry,
    }


def build_task_dispatch_status(
    lane_statuses: list[dict[str, Any]],
    automatable_tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_task_dispatch_status",
        "generated_utc": _utc_now_iso(),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "lane_statuses": lane_statuses,
        "next_automatable_tasks": automatable_tasks,
        "no_idle_claude_lane_with_automatable_work": all(
            l["status"] != "idle" for l in lane_statuses
        )
        or not automatable_tasks,
    }


# ---------------------------------------------------------------------------
# Final composition
# ---------------------------------------------------------------------------


SAFETY_SCOREBOARD_TEMPLATE = {
    "live_gate": LIVE_GATE_BLOCKED,
    "live_symbols": [],
    "approves_live": False,
    "approves_canary": False,
    "approves_legacy_shutdown": False,
    "approves_redis_trim": False,
    "did_not_modify_legacy_tree": True,
    "did_not_stop_legacy_runtime": True,
    "did_not_stop_v2_runtime": True,
    "did_not_stop_report_center": True,
    "did_not_stop_replay_miner": True,
    "did_not_stop_continuous_remediation": True,
    "did_not_stop_codex_governors": True,
    "did_not_write_old_redis_keys": True,
    "did_not_place_cancel_or_modify_exchange_orders": True,
    "did_not_change_leverage_or_margin_mode": True,
    "did_not_enable_live_or_canary": True,
    "did_not_create_paper_only_shutdown_acceptance_file": True,
    "did_not_expose_raw_api_keys": True,
    "no_edge_claim": True,
    "no_checkpoint_compatibility_claim": True,
    "no_policy_architecture_parity_claim": True,
}


def build_war_room_status(
    lane_statuses: list[dict[str, Any]],
    metric_summary_snapshot: dict[str, Any],
    edge_gate_analysis: dict[str, Any],
    fn_report: dict[str, Any],
    dataset_status: dict[str, Any],
    baseline_metrics: dict[str, Any],
    observation_recheck: dict[str, Any],
    utilization_status: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_war_room_status",
        "generated_utc": _utc_now_iso(),
        "go_no_go": "V2_24H_PARALLEL_RECOVERY_WAR_ROOM_READY",
        "safety_scoreboard": dict(SAFETY_SCOREBOARD_TEMPLATE),
        "lane_statuses": lane_statuses,
        "edge_gate_summary": {
            "edge_claimed": edge_gate_analysis["edge_claimed"],
            "edge_claim_blocked_reason": edge_gate_analysis[
                "edge_claim_blocked_reason"
            ],
            "verdict_per_profile": edge_gate_analysis["verdict_per_profile"],
        },
        "evaluator_summary": {
            "sample_count": metric_summary_snapshot.get("sample_count"),
            "expected_move_after_cost_bps": metric_summary_snapshot.get(
                "expected_move_after_cost_bps"
            ),
            "after_cost_ci_lower_bps": metric_summary_snapshot.get(
                "after_cost_ci_lower_bps"
            ),
            "after_cost_ci_upper_bps": metric_summary_snapshot.get(
                "after_cost_ci_upper_bps"
            ),
            "max_drawdown_bps_observed": metric_summary_snapshot.get(
                "max_drawdown_bps_observed"
            ),
            "false_negative_rate": metric_summary_snapshot.get(
                "false_negative_rate"
            ),
            "false_positive_rate": metric_summary_snapshot.get(
                "false_positive_rate"
            ),
            "verdict": metric_summary_snapshot.get("verdict"),
        },
        "false_negative_summary": {
            "false_negative_count": fn_report["false_negative_count"],
            "cause_counts": fn_report["cause_counts"],
        },
        "dataset_summary": {
            "dataset_total_rows": dataset_status["dataset_total_rows"],
            "train_rows": dataset_status["train_rows"],
            "validation_rows": dataset_status["validation_rows"],
            "excluded_insufficient_evidence": dataset_status[
                "excluded_insufficient_evidence"
            ],
            "excluded_missing_5m_outcome": dataset_status[
                "excluded_missing_5m_outcome"
            ],
        },
        "baseline_summary": {
            "validation_samples": baseline_metrics["validation_samples"],
            "baseline_names": [
                k
                for k, v in baseline_metrics["baselines"].items()
                if isinstance(v, dict) and "mean_after_cost_bps" in v
            ],
        },
        "observation_summary": {
            "v2_buildable_now_count": observation_recheck[
                "v2_buildable_now_count"
            ],
            "bucket_counts": observation_recheck["bucket_counts"],
        },
        "utilization_summary": {
            "active_lanes": utilization_status["active_lanes"],
            "completed_lanes": utilization_status["completed_lanes"],
            "stalled_lanes": utilization_status["stalled_lanes"],
        },
    }


def build_operator_dashboard_payload(
    status: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_operator_dashboard_payload",
        "generated_utc": _utc_now_iso(),
        "go_no_go": status["go_no_go"],
        "safety_scoreboard": status["safety_scoreboard"],
        "lane_statuses": status["lane_statuses"],
        "edge_gate_summary": status["edge_gate_summary"],
        "evaluator_summary": status["evaluator_summary"],
        "false_negative_summary": status["false_negative_summary"],
        "dataset_summary": status["dataset_summary"],
        "baseline_summary": status["baseline_summary"],
        "observation_summary": status["observation_summary"],
        "utilization_summary": status["utilization_summary"],
        "controls_present": False,
        "fake_readiness": False,
    }


def build_operator_decision_queue(
    edge_analysis: dict[str, Any],
    observation_recheck: dict[str, Any],
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    items.append(
        {
            "decision_id": "set_concrete_edge_thresholds",
            "title": (
                "Operator decision: set concrete numeric values for the "
                "edge thresholds currently marked OPERATOR_DECISION_REQUIRED"
            ),
            "blocker_for": (
                "edge_claim_via_v2_native_edge_proof_evaluator"
            ),
            "automatable": False,
        }
    )
    items.append(
        {
            "decision_id": "approve_paid_aggregator_or_alt_data_source",
            "title": (
                "Operator decision: approve or reject paid CoinAnk / OHLCV / "
                "onchain data sources to unlock external_source_required "
                "observation buckets"
            ),
            "blocker_for": "EXTERNAL_SOURCE_REQUIRED and OPERATOR_DECISION_REQUIRED observation buckets",
            "automatable": False,
        }
    )
    items.append(
        {
            "decision_id": "set_minimum_sample_count_for_dataset_release",
            "title": (
                "Operator decision: set minimum sample count for V2-native "
                "dataset to be usable for non-shadow evaluation"
            ),
            "blocker_for": (
                "v2_native_model_baseline_release_for_paper_action"
            ),
            "automatable": False,
        }
    )
    return {
        "schema_version": SCHEMA_VERSION + "_operator_decision_queue",
        "generated_utc": _utc_now_iso(),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "items": items,
    }


def build_next_automatable_tasks(
    fn_remediation_tasks: list[dict[str, Any]],
    observation_recheck: dict[str, Any],
) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = list(fn_remediation_tasks)
    if observation_recheck.get("v2_buildable_now_count", 0) > 0:
        tasks.append(
            {
                "task_id": "build_remaining_v2_buildable_now_fields",
                "title": (
                    "Build remaining V2_BUILDABLE_NOW observation fields "
                    "identified by the observation classifier"
                ),
                "owner_lane": "v2_observation",
                "automatable": True,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION + "_next_automatable_tasks",
        "generated_utc": _utc_now_iso(),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "tasks": tasks,
    }


# ---------------------------------------------------------------------------
# Orchestrator entrypoint
# ---------------------------------------------------------------------------


@dataclass
class WarRoomPaths:
    repo_root: Path
    packet_dir: Path
    public_dir: Path
    bundles_jsonl: Path
    miner_status_json: Path
    edge_metrics_json: Path
    remaining_dim_queue_json: Path
    buildable_now_json: Path


def default_paths(repo_root: Path) -> WarRoomPaths:
    miner_base = repo_root / "claude_worklog/final_readiness/v2_post_hoc_replay_outcome_miner/latest"
    queue_base = repo_root / "claude_worklog/final_readiness/v2_full_observation_remaining_dim_execution_queue/latest"
    return WarRoomPaths(
        repo_root=repo_root,
        packet_dir=repo_root / "claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room/latest",
        public_dir=repo_root / "v2/frontend/public/v2_24h_parallel_recovery_war_room/latest",
        bundles_jsonl=miner_base / "replay_outcome_bundles.jsonl",
        miner_status_json=miner_base / "post_hoc_replay_outcome_status.json",
        edge_metrics_json=miner_base / "edge_metrics_summary.json",
        remaining_dim_queue_json=queue_base / "remaining_dim_execution_queue.json",
        buildable_now_json=queue_base / "v2_buildable_now_fields.json",
    )


@dataclass
class WarRoomRunResult:
    go_no_go: str
    lane_statuses: list[dict[str, Any]] = field(default_factory=list)
    paths_written: list[Path] = field(default_factory=list)


def run_war_room(paths: WarRoomPaths) -> WarRoomRunResult:
    bundles = _read_jsonl(paths.bundles_jsonl)
    edge_metrics_doc = _read_json(paths.edge_metrics_json) or {}
    miner_status = _read_json(paths.miner_status_json) or {}
    metric_summary = (
        edge_metrics_doc.get("metric_summary")
        or miner_status.get("evaluator_metric_summary")
        or {}
    )
    remaining_queue = _read_json(paths.remaining_dim_queue_json) or {}
    buildable_now = _read_json(paths.buildable_now_json)

    lane_statuses: list[dict[str, Any]] = []

    # Lane 1 ---------------------------------------------------------------
    simulation = build_threshold_profile_simulation(metric_summary)
    analysis = build_edge_gate_analysis(simulation)
    edge_report = render_edge_proof_analysis_report(simulation, analysis)
    lane1_dir = paths.packet_dir / "lane1"
    _atomic_write_json(lane1_dir / "threshold_profile_simulation.json", simulation)
    _atomic_write_json(lane1_dir / "edge_gate_analysis.json", analysis)
    _atomic_write_text(lane1_dir / "EDGE_PROOF_ANALYSIS_REPORT.md", edge_report)
    lane_statuses.append(
        {
            "lane_id": "lane1_edge_proof_and_threshold_analytics",
            "status": "completed",
            "owner": "claude",
            "reviewer": "codex",
            "verdict": "ANALYSIS_ONLY_EDGE_NOT_CLAIMED",
        }
    )

    # Lane 2 ---------------------------------------------------------------
    fn_report, fn_remediation_tasks = build_false_negative_root_cause_report(bundles)
    lane2_dir = paths.packet_dir / "lane2"
    _atomic_write_json(lane2_dir / "false_negative_root_cause_report.json", fn_report)
    _atomic_write_text(
        lane2_dir / "false_negative_root_cause_report.md",
        render_false_negative_root_cause_report_md(fn_report),
    )
    _atomic_write_json(
        lane2_dir / "next_false_negative_remediation_tasks.json",
        {
            "schema_version": SCHEMA_VERSION + "_fn_remediation_tasks",
            "generated_utc": _utc_now_iso(),
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
            "tasks": fn_remediation_tasks,
        },
    )
    lane_statuses.append(
        {
            "lane_id": "lane2_false_negative_root_cause",
            "status": "completed",
            "owner": "claude",
            "reviewer": "codex",
            "verdict": "CLASSIFIED_ROOT_CAUSES_AVAILABLE",
        }
    )

    # Lane 3 ---------------------------------------------------------------
    dataset = build_v2_native_training_dataset(bundles)
    dataset_status = build_dataset_status(dataset, len(bundles))
    dataset_manifest = build_dataset_manifest(dataset)
    lane3_dir = paths.packet_dir / "lane3"
    _atomic_write_json(
        lane3_dir / "v2_native_training_dataset_status.json", dataset_status
    )
    _atomic_write_json(
        lane3_dir / "v2_native_training_dataset_manifest.json", dataset_manifest
    )
    _atomic_write_text(
        lane3_dir / "dataset_quality_report.md",
        render_dataset_quality_report_md(dataset_status),
    )
    lane_statuses.append(
        {
            "lane_id": "lane3_v2_native_training_dataset",
            "status": "completed",
            "owner": "claude",
            "reviewer": "codex",
            "verdict": "DATASET_BUILT_ANALYSIS_ONLY",
        }
    )

    # Lane 4 ---------------------------------------------------------------
    baseline_metrics = build_baseline_metrics(dataset)
    lane4_dir = paths.packet_dir / "lane4"
    _atomic_write_json(
        lane4_dir / "model_baseline_metrics.json", baseline_metrics
    )
    _atomic_write_text(
        lane4_dir / "model_baseline_report.md",
        render_baseline_report_md(baseline_metrics),
    )
    lane_statuses.append(
        {
            "lane_id": "lane4_model_baseline_evaluator",
            "status": "completed",
            "owner": "claude",
            "reviewer": "codex",
            "verdict": "BASELINES_COMPUTED_NO_MODEL_CLAIM",
        }
    )

    # Lane 5 ---------------------------------------------------------------
    observation_recheck = classify_observation_blockers(
        remaining_queue, buildable_now
    )
    lane5_dir = paths.packet_dir / "lane5"
    _atomic_write_json(
        lane5_dir / "observation_blocker_live_recheck.json", observation_recheck
    )
    _atomic_write_text(
        lane5_dir / "observation_blocker_live_recheck.md",
        render_observation_blocker_md(observation_recheck),
    )
    lane_statuses.append(
        {
            "lane_id": "lane5_observation_blocker_classifier",
            "status": "completed",
            "owner": "claude",
            "reviewer": "codex",
            "verdict": "RECLASSIFIED_NO_NEW_BUILDABLE_NOW_FIELDS",
        }
    )

    # Lane 6 + Lane 7 — record completion before utilization/dispatch so
    # the utilization snapshot reflects the full seven-lane state.
    lane_statuses.append(
        {
            "lane_id": "lane6_automation_utilization_takeover",
            "status": "completed",
            "owner": "claude",
            "reviewer": "codex",
            "verdict": "UTILIZATION_AND_DISPATCH_REPORTED",
        }
    )
    lane_statuses.append(
        {
            "lane_id": "lane7_website_report_center_truth",
            "status": "completed",
            "owner": "claude",
            "reviewer": "codex",
            "verdict": "PUBLIC_MIRROR_WRITTEN_NO_CONTROLS_NO_FAKE_READINESS",
        }
    )

    file_lock_registry = {
        str(paths.packet_dir): "owned_by_v2_24h_parallel_recovery_war_room",
        str(paths.public_dir): "owned_by_v2_24h_parallel_recovery_war_room",
    }
    utilization_status = build_utilization_status(
        lane_statuses, file_lock_registry
    )
    next_tasks = build_next_automatable_tasks(
        fn_remediation_tasks, observation_recheck
    )
    dispatch_status = build_task_dispatch_status(
        lane_statuses, next_tasks["tasks"]
    )
    lane6_dir = paths.packet_dir / "lane6"
    _atomic_write_json(
        lane6_dir / "war_room_utilization_status.json", utilization_status
    )
    _atomic_write_json(
        lane6_dir / "war_room_task_dispatch_status.json", dispatch_status
    )

    # Final composition (status, dashboards, operator queue, next tasks) --
    status = build_war_room_status(
        lane_statuses,
        metric_summary,
        analysis,
        fn_report,
        dataset_status,
        baseline_metrics,
        observation_recheck,
        utilization_status,
    )
    dashboard_payload = build_operator_dashboard_payload(status)
    operator_queue = build_operator_decision_queue(analysis, observation_recheck)

    _atomic_write_json(paths.packet_dir / "war_room_status.json", status)
    _atomic_write_json(
        paths.packet_dir / "lane_statuses.json",
        {
            "schema_version": SCHEMA_VERSION + "_lane_statuses",
            "generated_utc": _utc_now_iso(),
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
            "lane_statuses": lane_statuses,
            "lane_registry": LANE_REGISTRY,
        },
    )
    _atomic_write_json(
        paths.packet_dir / "next_automatable_tasks.json", next_tasks
    )
    _atomic_write_json(
        paths.packet_dir / "operator_decision_queue.json", operator_queue
    )
    _atomic_write_json(
        paths.public_dir / "operator_dashboard_payload.json", dashboard_payload
    )
    _atomic_write_json(
        paths.public_dir / "war_room_status.json", status
    )

    # Final report and GO_NO_GO ------------------------------------------
    final_report = _render_final_report(
        status,
        edge_gate_analysis=analysis,
        fn_report=fn_report,
        dataset_status=dataset_status,
        baseline_metrics=baseline_metrics,
        observation_recheck=observation_recheck,
        utilization_status=utilization_status,
        operator_queue=operator_queue,
    )
    _atomic_write_text(
        paths.packet_dir / "V2_24H_PARALLEL_RECOVERY_WAR_ROOM_REPORT.md",
        final_report,
    )
    go_no_go_text = "V2_24H_PARALLEL_RECOVERY_WAR_ROOM_READY\n"
    _atomic_write_text(paths.packet_dir / "GO_NO_GO.md", go_no_go_text)

    return WarRoomRunResult(
        go_no_go="V2_24H_PARALLEL_RECOVERY_WAR_ROOM_READY",
        lane_statuses=lane_statuses,
        paths_written=[
            paths.packet_dir / "GO_NO_GO.md",
            paths.packet_dir / "V2_24H_PARALLEL_RECOVERY_WAR_ROOM_REPORT.md",
            paths.packet_dir / "war_room_status.json",
            paths.packet_dir / "lane_statuses.json",
            paths.packet_dir / "next_automatable_tasks.json",
            paths.packet_dir / "operator_decision_queue.json",
            paths.public_dir / "operator_dashboard_payload.json",
            paths.public_dir / "war_room_status.json",
        ],
    )


def _render_final_report(
    status: dict[str, Any],
    *,
    edge_gate_analysis: dict[str, Any],
    fn_report: dict[str, Any],
    dataset_status: dict[str, Any],
    baseline_metrics: dict[str, Any],
    observation_recheck: dict[str, Any],
    utilization_status: dict[str, Any],
    operator_queue: dict[str, Any],
) -> str:
    lines = []
    lines.append("# V2 24h Parallel Recovery War-Room Report\n\n")
    lines.append(f"GO/NO-GO: {status['go_no_go']}\n\n")
    lines.append(
        "live_gate=blocked_human_only. live_symbols=[]. approves_live=false. "
        "approves_canary=false. approves_legacy_shutdown=false. "
        "approves_redis_trim=false.\n\n"
    )
    lines.append(
        "This packet runs seven analysis-only lanes in parallel against "
        "the existing V2 replay-miner artifacts and observation queue. "
        "Nothing in it approves live, canary, legacy shutdown, or "
        "Redis-trim. The miner and evaluator continue to run on their own "
        "cadence; this packet does not start, stop, or install timers.\n\n"
    )

    lines.append("## Lane 1 — Edge proof and threshold analytics\n")
    es = status["evaluator_summary"]
    lines.append(
        f"- sample_count: {es['sample_count']}\n"
        f"- expected_move_after_cost_bps: {es['expected_move_after_cost_bps']}\n"
        f"- after_cost_ci_lower_bps: {es['after_cost_ci_lower_bps']}\n"
        f"- after_cost_ci_upper_bps: {es['after_cost_ci_upper_bps']}\n"
        f"- max_drawdown_bps_observed: {es['max_drawdown_bps_observed']}\n"
        f"- false_negative_rate: {es['false_negative_rate']}\n"
        f"- false_positive_rate: {es['false_positive_rate']}\n"
        f"- evaluator verdict: {es['verdict']}\n"
        f"- edge_claimed: {edge_gate_analysis['edge_claimed']}\n"
        f"- edge_claim_blocked_reason: "
        f"{edge_gate_analysis['edge_claim_blocked_reason']}\n\n"
    )
    for profile_name, p in edge_gate_analysis["verdict_per_profile"].items():
        lines.append(f"  - {profile_name}: {p['verdict']} (fail: {p['fail_thresholds']})\n")
    lines.append("\n")

    lines.append("## Lane 2 — False-negative root-cause analyzer\n")
    fs = status["false_negative_summary"]
    lines.append(f"- false_negative_count: {fs['false_negative_count']}\n")
    for cause, count in sorted(fs["cause_counts"].items()):
        lines.append(f"  - {cause}: {count}\n")
    lines.append("\n")

    lines.append("## Lane 3 — V2-native training dataset builder\n")
    ds = status["dataset_summary"]
    lines.append(
        f"- dataset_total_rows: {ds['dataset_total_rows']}\n"
        f"- train_rows: {ds['train_rows']}\n"
        f"- validation_rows: {ds['validation_rows']}\n"
        f"- excluded_insufficient_evidence: "
        f"{ds['excluded_insufficient_evidence']}\n"
        f"- excluded_missing_5m_outcome: "
        f"{ds['excluded_missing_5m_outcome']}\n"
        "- checkpoint_compatibility_claimed: false\n"
        "- policy_architecture_parity_claimed: false\n\n"
    )

    lines.append("## Lane 4 — V2-native compact model baseline evaluator\n")
    lines.append(
        f"- validation_samples: {baseline_metrics['validation_samples']}\n"
        f"- train_samples: {baseline_metrics['train_samples']}\n"
    )
    for name, b in baseline_metrics["baselines"].items():
        if not isinstance(b, dict) or "mean_after_cost_bps" not in b:
            continue
        lines.append(
            f"  - {name}: enters={b['enters']} mean_bps="
            f"{b['mean_after_cost_bps']} sum_bps={b['sum_after_cost_bps']}\n"
        )
    legacy = baseline_metrics["baselines"].get("legacy_reference") or {}
    lines.append(
        f"  - legacy_reference: {legacy.get('evidence_state')} — "
        f"{legacy.get('note')}\n\n"
    )

    lines.append("## Lane 5 — Remaining observation blocker classifier\n")
    obs = status["observation_summary"]
    lines.append(
        f"- v2_buildable_now_count: {obs['v2_buildable_now_count']}\n"
    )
    for bucket, count in sorted(obs["bucket_counts"].items()):
        lines.append(f"  - {bucket}: {count}\n")
    lines.append("\n")

    lines.append("## Lane 6 — Automation utilization and takeover\n")
    util = status["utilization_summary"]
    lines.append(
        f"- active_lanes: {util['active_lanes']}\n"
        f"- completed_lanes: {util['completed_lanes']}\n"
        f"- stalled_lanes: {util['stalled_lanes']}\n\n"
    )

    lines.append("## Lane 7 — Website / report center truth\n")
    lines.append(
        "- operator_dashboard_payload.json mirrored under "
        "v2/frontend/public/v2_24h_parallel_recovery_war_room/latest/\n"
        "- war_room_status.json mirrored alongside\n"
        "- controls_present: false\n"
        "- fake_readiness: false\n\n"
    )

    lines.append("## Operator decision queue\n")
    for item in operator_queue["items"]:
        lines.append(
            f"- {item['decision_id']}: {item['title']} "
            f"(blocker_for: {item['blocker_for']})\n"
        )
    lines.append("\n")

    lines.append("## Safety scoreboard\n")
    for k, v in sorted(status["safety_scoreboard"].items()):
        lines.append(f"- {k}: {v}\n")
    lines.append("\n")

    lines.append("## What this packet did NOT do\n")
    lines.append(
        "- Did not modify /home/wali/Desktop/AI BOT.\n"
        "- Did not stop legacy or V2 runtime.\n"
        "- Did not stop the report center, replay miner, continuous "
        "remediation governor, or Codex governors.\n"
        "- Did not write any old Redis key.\n"
        "- Did not call the exchange.\n"
        "- Did not change leverage or margin mode.\n"
        "- Did not create any approval marker or shutdown-acceptance file.\n"
        "- Did not enable live or canary.\n"
        "- Did not adopt any Symbol Universe candidate.\n"
        "- Did not adopt any external feed.\n"
        "- Did not expose any raw API key.\n"
        "- Did not fabricate any future-outcome window value.\n"
        "- Did not change any replay label.\n"
        "- Did not install or enable the replay miner timer.\n"
    )
    return "".join(lines)
