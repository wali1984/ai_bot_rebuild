"""Read-only control-center status aliases.

These endpoints exist so web, iOS, and authenticated crawlers can depend on
canonical JSON contracts instead of accidentally accepting SPA HTML fallbacks.
They never place orders, submit test orders, or mutate exchange settings.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from app.api.v2._common import get_redis
from app.services.realtime.operator_snapshot import build_ui_snapshot

router = APIRouter(tags=["v2-control-center-status"])

DISPLAY_TZ = ZoneInfo("America/New_York")
PREVIEW_LIMIT = 25
TRAINER_HYBRID_CUDA_STATUS_KEY = "v2:trainer:hybrid_cuda:status"
A_GRADE_GATE_BURNDOWN_STATUS_KEY = "v2:paper:a_grade_gate_burndown_status"
PREEMPTIVE_EDGE_CONTROL_STATUS_KEY = "v2:paper:preemptive_edge_control_status"
PREEMPTIVE_CANDIDATE_DECISION_MATRIX_KEY = (
    "v2:paper:preemptive_candidate_decision_matrix"
)
PAPER_EXPLORATION_SUPPLY_STATUS_KEY = "v2:paper:exploration:supply_status"
PAPER_EXPLORATION_MATERIALIZATION_QUEUE_STATUS_KEY = (
    "v2:paper:exploration:materialization_queue_status"
)
CONTINUOUS_EDGE_GUARDIAN_EXECUTION_GATE_KEY = (
    "v2:continuous_edge_guardian:a_grade_execution_gate"
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _display_time_et() -> str:
    return datetime.now(DISPLAY_TZ).isoformat(timespec="seconds")


def _json_object(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_json(client: Any, key: str) -> dict[str, Any]:
    if client is None:
        return {}
    try:
        return _json_object(client.get(key))
    except Exception:
        return {}


def _first(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item not in (None, "")]
    if value in (None, ""):
        return []
    return [str(value)]


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _materialization_no_fill_detail(paper_queue: Mapping[str, Any]) -> dict[str, Any]:
    after_queue_reasons = _string_list(paper_queue.get("after_queue_no_fill_reasons"))
    prequeue_reasons = _string_list(paper_queue.get("prequeue_no_fill_reasons"))
    component_reasons = _dedupe_strings([*after_queue_reasons, *prequeue_reasons])
    return {
        "exact_no_fill_reason": paper_queue.get("exact_no_fill_reason"),
        "canonical_exact_no_fill_reason": paper_queue.get(
            "canonical_exact_no_fill_reason"
        ),
        "after_queue_exact_no_fill_reason": paper_queue.get(
            "after_queue_exact_no_fill_reason"
        ),
        "after_queue_no_fill_reasons": after_queue_reasons,
        "prequeue_exact_no_fill_reason": paper_queue.get(
            "prequeue_exact_no_fill_reason"
        ),
        "prequeue_no_fill_reasons": prequeue_reasons,
        "no_fill_component_reasons": component_reasons,
        "rejected_after_queue_reason_counts": paper_queue.get(
            "rejected_after_queue_reason_counts"
        )
        if isinstance(paper_queue.get("rejected_after_queue_reason_counts"), Mapping)
        else {},
        "prequeue_rejected_reason_counts": paper_queue.get(
            "prequeue_rejected_reason_counts"
        )
        if isinstance(paper_queue.get("prequeue_rejected_reason_counts"), Mapping)
        else {},
    }


def _float_or_none(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:
        return None
    return parsed


def _int_or_zero(value: Any) -> int:
    parsed = _float_or_none(value)
    return int(parsed) if parsed is not None else 0


def _distribution(values: list[float]) -> dict[str, Any] | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "p50": ordered[len(ordered) // 2],
        "p90": ordered[int((len(ordered) - 1) * 0.9)],
        "max": ordered[-1],
    }


def _preemptive_matrix_rows(matrix: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = matrix.get("rows")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _preemptive_matrix_diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reason_counts: dict[str, int] = {}
    loss_probabilities: list[float] = []
    profit_factors: list[float] = []
    after_cost_edges: list[float] = []
    for row in rows:
        for key in (
            "block_reasons",
            "preemptive_block_reasons",
            "paper_exploration_paper_fill_block_reasons",
            "reasons",
        ):
            reasons = row.get(key)
            if isinstance(reasons, list):
                for reason in reasons:
                    if reason:
                        reason_key = str(reason)
                        reason_counts[reason_key] = (
                            reason_counts.get(reason_key, 0) + 1
                        )
        for key in ("pre_trade_loss_probability", "loss_probability"):
            parsed = _float_or_none(row.get(key))
            if parsed is not None:
                loss_probabilities.append(parsed)
                break
        for key in (
            "recent_bucket_profit_factor",
            "bucket_profit_factor",
            "profit_factor",
        ):
            parsed = _float_or_none(row.get(key))
            if parsed is not None:
                profit_factors.append(parsed)
                break
        for key in (
            "expected_edge_after_cost_bps",
            "edge_after_cost_bps",
            "expected_net_edge_bps",
        ):
            parsed = _float_or_none(row.get(key))
            if parsed is not None:
                after_cost_edges.append(parsed)
                break
    return {
        "row_count": len(rows),
        "top_block_reasons": [
            {"reason": reason, "count": count}
            for reason, count in sorted(
                reason_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:20]
        ],
        "loss_probability": _distribution(loss_probabilities),
        "bucket_profit_factor": _distribution(profit_factors),
        "expected_edge_after_cost_bps": _distribution(after_cost_edges),
    }


def _finding_ids(findings: list[Mapping[str, Any]]) -> list[str]:
    return [str(finding["id"]) for finding in findings if finding.get("id")]


def _dedupe_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not value:
            continue
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _primary_a_grade_blocker(finding_ids: list[str]) -> str | None:
    for blocker in (
        "A_GRADE_SUPPLY_ZERO",
        "VALIDATION_LOSS_REGRESSED",
        "TRAIN_VAL_OVERFIT_GAP",
        "BLOCKED_NO_DURABLE_WEIGHT_UPDATE",
        "GUARDIAN_HALTED_PERFORMANCE",
        "PREEMPTIVE_LOSS_PROBABILITY_TOO_HIGH",
        "PAPER_OUTCOME_FEEDER_STARVED_BY_TRUE_GATES",
        "TRAIN_VAL_GENERALIZATION_GAP_HIGH",
        "PPO_ENTROPY_HIGH_POLICY_NOT_CONVERGED",
        "BUCKET_PROFIT_FACTOR_BELOW_A_GRADE_STANDARD",
    ):
        if blocker in finding_ids:
            return blocker
    return finding_ids[0] if finding_ids else None


def _real_trader_readiness_from_a_grade_truth(
    a_grade_blocker_truth: Mapping[str, Any],
) -> dict[str, Any]:
    status = str(a_grade_blocker_truth.get("status") or "")
    primary_blocker = (
        a_grade_blocker_truth.get("primary_blocker")
        if status == "A_GRADE_ADAPTATION_NOT_PROVEN"
        else None
    )
    if not primary_blocker and status != "NO_ACTIVE_BLOCKER_DETECTED":
        primary_blocker = status or "A_GRADE_BLOCKER_TRUTH_UNAVAILABLE"
    finding_ids = (
        a_grade_blocker_truth.get("finding_ids")
        if isinstance(a_grade_blocker_truth.get("finding_ids"), list)
        else []
    )
    blockers = _dedupe_strings([primary_blocker, *finding_ids])
    if not blockers:
        blockers = ["LIVE_GATE_BLOCKED_HUMAN_ONLY"]
    return {
        "live_gate": "blocked_human_only",
        "operator_flip_required": True,
        "live_ready": False,
        "live_submit_allowed": False,
        "exact_no_live_reason": blockers[0],
        "readiness_blockers": blockers,
        "a_grade_blocker_truth": dict(a_grade_blocker_truth),
        "order_submitted": False,
        "test_order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _current_a_grade_blocker_truth(client: Any) -> dict[str, Any]:
    """Compose current A-grade blockers from runtime Redis truth.

    This is a read-only operator surface helper. It does not lower gates, count
    exploration rows as A+, or infer live readiness from partial evidence.
    """
    trainer_status = _read_json(client, TRAINER_HYBRID_CUDA_STATUS_KEY)
    a_grade_status = _read_json(client, A_GRADE_GATE_BURNDOWN_STATUS_KEY)
    preemptive_status = _read_json(client, PREEMPTIVE_EDGE_CONTROL_STATUS_KEY)
    preemptive_matrix = _read_json(client, PREEMPTIVE_CANDIDATE_DECISION_MATRIX_KEY)
    paper_supply = _read_json(client, PAPER_EXPLORATION_SUPPLY_STATUS_KEY)
    paper_queue = _read_json(client, PAPER_EXPLORATION_MATERIALIZATION_QUEUE_STATUS_KEY)
    guardian_gate = _read_json(client, CONTINUOUS_EDGE_GUARDIAN_EXECUTION_GATE_KEY)
    available = any(
        bool(payload)
        for payload in (
            trainer_status,
            a_grade_status,
            preemptive_status,
            preemptive_matrix,
            paper_supply,
            paper_queue,
            guardian_gate,
        )
    )

    rows = _preemptive_matrix_rows(preemptive_matrix)
    preemptive = _preemptive_matrix_diagnostics(rows)
    loss_stats = preemptive.get("loss_probability") or {}
    pf_stats = preemptive.get("bucket_profit_factor") or {}
    learning_metrics = (
        trainer_status.get("learning_metrics")
        if isinstance(trainer_status.get("learning_metrics"), dict)
        else {}
    )
    ppo_entropy = _float_or_none(learning_metrics.get("ppo_entropy"))
    validation_gap = _float_or_none(
        learning_metrics.get("train_val_generalization_gap")
    )
    validation_loss = _float_or_none(
        learning_metrics.get("validation_supervised_loss")
    )
    validation_loss_before = _float_or_none(
        _first(
            learning_metrics.get("validation_supervised_loss_before"),
            trainer_status.get("validation_supervised_loss_before"),
        )
    )
    validation_loss_after = _float_or_none(
        _first(
            learning_metrics.get("validation_supervised_loss_after"),
            trainer_status.get("validation_supervised_loss_after"),
            learning_metrics.get("validation_supervised_loss"),
            trainer_status.get("validation_supervised_loss"),
        )
    )
    validation_loss_delta = _float_or_none(
        _first(
            learning_metrics.get("validation_loss_delta"),
            trainer_status.get("validation_loss_delta"),
        )
    )
    loss_after = _float_or_none(learning_metrics.get("loss_after"))
    online_learning_status = str(trainer_status.get("online_learning_status") or "")
    checkpoint_promotion_reason = str(
        _first(
            learning_metrics.get("checkpoint_promotion_reason"),
            trainer_status.get("checkpoint_promotion_reason"),
        )
        or ""
    )
    checkpoint_promotion_rejected = _first(
        learning_metrics.get("checkpoint_promotion_rejected"),
        trainer_status.get("checkpoint_promotion_rejected"),
    )
    hard_promotion_rejection = _first(
        learning_metrics.get("hard_promotion_rejection_reason"),
        trainer_status.get("hard_promotion_rejection_reason"),
    )
    a_grade_rows = _int_or_zero(
        _first(
            a_grade_status.get("A_grade_rows"),
            a_grade_status.get("a_grade_rows"),
        )
    )
    near_a_grade_rows = _int_or_zero(
        _first(
            a_grade_status.get("near_A_grade_rows"),
            a_grade_status.get("near_a_grade_rows"),
        )
    )
    paper_fill_allowed_rows = _int_or_zero(
        _first(
            a_grade_status.get("paper_fill_allowed_rows"),
            preemptive_status.get("accepted_count"),
        )
    )
    materialized_positions = _int_or_zero(
        _first(
            paper_queue.get("same_cycle_materialized_count"),
            paper_supply.get("materialized_positions_last_cycle"),
        )
    )
    guardian_status = str(
        _first(
            guardian_gate.get("status"),
            guardian_gate.get("state"),
            a_grade_status.get("guardian_status"),
            paper_queue.get("guardian_status"),
            paper_queue.get("continuous_edge_guardian_status"),
        )
        or ""
    )
    guardian_allows_entries = _first(
        guardian_gate.get("a_grade_new_entries_allowed"),
        guardian_gate.get("new_entries_allowed"),
        a_grade_status.get("guardian_new_entries_allowed"),
        paper_queue.get("guardian_new_entries_allowed"),
        paper_queue.get("continuous_edge_guardian_new_entries_allowed"),
    )
    no_fill_detail = _materialization_no_fill_detail(paper_queue)

    findings: list[dict[str, Any]] = []
    if (
        checkpoint_promotion_rejected is True
        and checkpoint_promotion_reason
        in {"VALIDATION_LOSS_REGRESSED", "TRAIN_VAL_OVERFIT_GAP"}
    ):
        findings.append(
            {
                "id": checkpoint_promotion_reason,
                "severity": "learning_checkpoint_blocker",
                "online_learning_status": online_learning_status or None,
                "checkpoint_promotion_rejected": True,
                "hard_promotion_rejection_reason": hard_promotion_rejection,
                "validation_loss_delta": validation_loss_delta,
                "validation_supervised_loss_before": validation_loss_before,
                "validation_supervised_loss_after": validation_loss_after,
                "code_defect": False,
            }
        )
    if online_learning_status == "BLOCKED_NO_DURABLE_WEIGHT_UPDATE":
        findings.append(
            {
                "id": "BLOCKED_NO_DURABLE_WEIGHT_UPDATE",
                "severity": "learning_checkpoint_blocker",
                "checkpoint_promotion_reason": checkpoint_promotion_reason or None,
                "checkpoint_promotion_rejected": checkpoint_promotion_rejected,
                "hard_promotion_rejection_reason": hard_promotion_rejection,
                "code_defect": False,
            }
        )
    if ppo_entropy is not None and ppo_entropy >= 0.8:
        findings.append(
            {
                "id": "PPO_ENTROPY_HIGH_POLICY_NOT_CONVERGED",
                "severity": "learning_blocker",
                "observed": ppo_entropy,
                "code_defect": False,
            }
        )
    if validation_gap is not None and validation_gap > 1.0:
        findings.append(
            {
                "id": "TRAIN_VAL_GENERALIZATION_GAP_HIGH",
                "severity": "learning_blocker",
                "observed": validation_gap,
                "validation_supervised_loss": validation_loss,
                "loss_after": loss_after,
                "code_defect": False,
            }
        )
    if (loss_stats.get("p50") or 0.0) >= 0.8:
        findings.append(
            {
                "id": "PREEMPTIVE_LOSS_PROBABILITY_TOO_HIGH",
                "severity": "paper_gate_blocker",
                "observed_p50": loss_stats.get("p50"),
                "observed_p90": loss_stats.get("p90"),
                "code_defect": False,
            }
        )
    if pf_stats and (pf_stats.get("p90") or 0.0) < 2.0:
        findings.append(
            {
                "id": "BUCKET_PROFIT_FACTOR_BELOW_A_GRADE_STANDARD",
                "severity": "economic_blocker",
                "observed_p50": pf_stats.get("p50"),
                "observed_p90": pf_stats.get("p90"),
                "required": 2.0,
                "code_defect": False,
            }
        )
    if a_grade_status and a_grade_rows <= 0:
        findings.append(
            {
                "id": "A_GRADE_SUPPLY_ZERO",
                "severity": "a_grade_blocker",
                "observed": a_grade_rows,
                "near_a_grade_rows": near_a_grade_rows,
                "code_defect": False,
            }
        )
    if (paper_queue or paper_supply or preemptive_status) and (
        materialized_positions <= 0 or paper_fill_allowed_rows <= 0
    ):
        findings.append(
            {
                "id": "PAPER_OUTCOME_FEEDER_STARVED_BY_TRUE_GATES",
                "severity": "learning_data_blocker",
                "materialized_positions": materialized_positions,
                "paper_fill_allowed_rows": paper_fill_allowed_rows,
                **no_fill_detail,
                "code_defect": False,
            }
        )
    if (
        guardian_status.upper() == "A_GRADE_HALTED_PERFORMANCE"
        or guardian_allows_entries is False
    ):
        findings.append(
            {
                "id": "GUARDIAN_HALTED_PERFORMANCE",
                "severity": "a_grade_blocker",
                "guardian_status": guardian_status or None,
                "guardian_new_entries_allowed": guardian_allows_entries,
                "code_defect": False,
            }
        )

    ids = _finding_ids(findings)
    return {
        "schema_version": "control_center_a_grade_blocker_truth_v1",
        "generated_utc": _utc_now(),
        "available": available,
        "status": (
            "A_GRADE_ADAPTATION_NOT_PROVEN"
            if findings
            else "NO_ACTIVE_BLOCKER_DETECTED"
            if available
            else "A_GRADE_BLOCKER_TRUTH_UNAVAILABLE"
        ),
        "primary_blocker": _primary_a_grade_blocker(ids),
        "finding_ids": ids,
        "findings": findings,
        "trainer": {
            "online_learning_status": online_learning_status or None,
            "effective_trainer_mode": trainer_status.get("effective_trainer_mode"),
            "checkpoint_promotion_reason": checkpoint_promotion_reason or None,
            "checkpoint_promotion_rejected": checkpoint_promotion_rejected,
            "hard_promotion_rejection_reason": hard_promotion_rejection,
            "ppo_entropy": ppo_entropy,
            "train_val_generalization_gap": validation_gap,
            "validation_supervised_loss": validation_loss,
            "validation_supervised_loss_before": validation_loss_before,
            "validation_supervised_loss_after": validation_loss_after,
            "validation_loss_delta": validation_loss_delta,
            "loss_after": loss_after,
        },
        "a_grade": {
            "A_grade_rows": a_grade_rows,
            "near_A_grade_rows": near_a_grade_rows,
            "status": a_grade_status.get("status"),
            "closest_gap_reason": a_grade_status.get("closest_gap_reason"),
            "guardian_status": guardian_status or None,
            "guardian_new_entries_allowed": guardian_allows_entries,
        },
        "preemptive": {
            "candidate_count": preemptive_status.get("candidate_count"),
            "accepted_count": preemptive_status.get("accepted_count"),
            **preemptive,
        },
        "paper_learning_feeder": {
            "fresh_strategy_supply_rows": paper_supply.get("fresh_strategy_supply_rows"),
            "fresh_exploration_candidates": paper_supply.get(
                "fresh_exploration_candidates"
            ),
            "materialized_positions_last_cycle": paper_supply.get(
                "materialized_positions_last_cycle"
            ),
            "queued_count": paper_queue.get("queued_count"),
            "active_count": paper_queue.get("active_count"),
            "same_cycle_materialized_count": paper_queue.get(
                "same_cycle_materialized_count"
            ),
            "rejected_after_queue_count": paper_queue.get("rejected_after_queue_count"),
            **no_fill_detail,
        },
        "forbidden_shortcuts_refused": [
            "lowering A-grade, holdout, profit-factor, or live gates",
            "counting exploration/probation rows as A+ or live-ready",
            "fabricating paper closes, test orders, or live orders",
            "disabling guardian/risk gates to create cosmetic evidence",
        ],
        "live_gate": "blocked_human_only",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "order_submitted": False,
        "test_order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }


def _a_plus_blocker_summary(
    payload: Mapping[str, Any],
    rows: list[Any],
    *,
    a_plus_count: int,
) -> tuple[str | None, list[str]]:
    """Return exact A+ blockers without synthesizing a live-ready-sounding label."""
    if a_plus_count > 0:
        return None, []

    reason_counts: dict[str, int] = {}
    matrix = payload.get("rejected_reason_matrix")
    if isinstance(matrix, Mapping):
        for reason, count in matrix.items():
            if not reason:
                continue
            try:
                parsed_count = int(count)
            except (TypeError, ValueError):
                parsed_count = 1
            reason_counts[str(reason)] = max(parsed_count, 1)

    for row in rows:
        if not isinstance(row, Mapping):
            continue
        failed_checks = row.get("failed_checks")
        if isinstance(failed_checks, list):
            for reason in failed_checks:
                if reason:
                    key = str(reason)
                    reason_counts[key] = reason_counts.get(key, 0) + 1

    top_blockers = [
        reason
        for reason, _count in sorted(
            reason_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ][:8]
    if top_blockers:
        return top_blockers[0], top_blockers

    evaluated = payload.get("evaluated_candidates")
    try:
        evaluated_count = int(evaluated)
    except (TypeError, ValueError):
        evaluated_count = len(rows)
    if evaluated_count <= 0 and not rows:
        return "NO_EVALUATED_CANDIDATES_IN_A_PLUS_GATE_STATUS", []
    return "A_PLUS_GATE_REJECTION_REASON_MISSING_FROM_RUNTIME_PAYLOAD", []


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _payload_timestamp(payload: Mapping[str, Any]) -> str | None:
    value = _first(
        payload.get("generated_at_utc"),
        payload.get("generated_utc"),
        payload.get("generated_at"),
        payload.get("available_at"),
        payload.get("updated_at"),
    )
    return str(value) if value is not None else None


def _age_seconds(payload: Mapping[str, Any], fallback: Any = None) -> float | None:
    if isinstance(fallback, (int, float)):
        return max(0.0, float(fallback))
    parsed = _parse_utc(_payload_timestamp(payload))
    if parsed is None:
        return None
    return max(0.0, (datetime.now(UTC) - parsed).total_seconds())


def _freshness(age_seconds: float | None, *, has_payload: bool) -> str:
    if not has_payload:
        return "missing"
    if age_seconds is None:
        return "unknown"
    if age_seconds <= 300:
        return "fresh"
    if age_seconds <= 1800:
        return "degraded"
    return "stale"


def _data_quality(*, has_payload: bool, freshness_status: str, source_quality: Any = None) -> str:
    if not has_payload:
        return "missing"
    quality = str(source_quality or "").lower()
    if quality in {"fresh", "valid"} and freshness_status == "fresh":
        return "fresh"
    if freshness_status in {"stale", "degraded"}:
        return freshness_status
    if freshness_status == "fresh":
        return "fresh"
    if quality:
        return quality
    return "partial"


def _contract(
    *,
    schema_version: str,
    canonical_owner: str,
    source: str,
    data: dict[str, Any],
    source_quality: Any = None,
    staleness_seconds: float | None = None,
) -> dict[str, Any]:
    has_payload = bool(data)
    age = _age_seconds(data, staleness_seconds)
    freshness_status = _freshness(age, has_payload=has_payload)
    return {
        "schema_version": schema_version,
        "generated_at_utc": _utc_now(),
        "generated_at_et": _display_time_et(),
        "source": source,
        "staleness_seconds": age,
        "freshness_status": freshness_status,
        "canonical_owner": canonical_owner,
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "routes_to_live": False,
        "data_quality_status": _data_quality(
            has_payload=has_payload,
            freshness_status=freshness_status,
            source_quality=source_quality,
        ),
        "data": data,
    }


@router.get("/providers/status")
async def get_provider_status() -> dict[str, Any]:
    client = get_redis()
    snapshot = build_ui_snapshot(client, "providers", use_materialized=False)
    payload = snapshot.get("payload") if isinstance(snapshot.get("payload"), dict) else {}
    data = dict(payload)
    data["provider_count"] = len(data.get("providers") or [])
    data["consumer_surface"] = "web_ios_control_center"
    data["source_snapshot_schema_version"] = snapshot.get("schema_version")
    return _contract(
        schema_version="control_center_provider_status_v1",
        canonical_owner="/api/v2/providers/status",
        source=str(snapshot.get("source") or "compact_live_fallback"),
        data=data,
        source_quality=snapshot.get("data_quality"),
        staleness_seconds=snapshot.get("staleness_seconds"),
    )


@router.get("/control-center/status")
async def get_control_center_status() -> dict[str, Any]:
    client = get_redis()
    provider_status = await get_provider_status()
    live_canary_status = await get_live_canary_status()
    a_plus_inventory = await get_a_plus_inventory()
    a_grade_blocker_truth = _current_a_grade_blocker_truth(client)
    readiness = _real_trader_readiness_from_a_grade_truth(a_grade_blocker_truth)
    data = {
        "status": (
            "A_GRADE_BLOCKED_LIVE_BLOCKED"
            if readiness["exact_no_live_reason"] != "LIVE_GATE_BLOCKED_HUMAN_ONLY"
            else "LIVE_BLOCKED_HUMAN_ONLY"
        ),
        "real_trader_readiness": readiness,
        "a_grade_blocker_truth": a_grade_blocker_truth,
        "exact_no_live_reason": readiness["exact_no_live_reason"],
        "readiness_blockers": readiness["readiness_blockers"],
        "top_blockers": readiness["readiness_blockers"][:8],
        "providers_status": provider_status.get("data") if isinstance(provider_status, dict) else {},
        "live_canary_status": live_canary_status.get("data") if isinstance(live_canary_status, dict) else {},
        "a_plus_inventory": a_plus_inventory.get("data") if isinstance(a_plus_inventory, dict) else {},
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
    }
    return _contract(
        schema_version="control_center_status_v1",
        canonical_owner="/api/v2/control-center/status",
        source="control_center_status.aggregate",
        data=data,
    )


@router.get("/control-center")
async def get_control_center_status_alias() -> dict[str, Any]:
    response = dict(await get_control_center_status())
    response["canonical_owner"] = "/api/v2/control-center"
    response["data"] = dict(response.get("data") or {})
    response["data"]["alias_of"] = "/api/v2/control-center/status"
    return response


@router.get("/live-canary/status")
async def get_live_canary_status() -> dict[str, Any]:
    client = get_redis()
    payload = _read_json(client, "v2:live_canary:status")
    a_grade_blocker_truth = _current_a_grade_blocker_truth(client)
    truth_finding_ids = a_grade_blocker_truth.get("finding_ids")
    if not isinstance(truth_finding_ids, list):
        truth_finding_ids = []
    legacy_why_none = _first(
        payload.get("why_none"), payload.get("live_blocker"), payload.get("go_no_go")
    )
    current_a_grade_blocker = (
        a_grade_blocker_truth.get("primary_blocker")
        if a_grade_blocker_truth.get("status") == "A_GRADE_ADAPTATION_NOT_PROVEN"
        else None
    )
    why_none = current_a_grade_blocker or legacy_why_none
    data = {
        "generated_utc": payload.get("generated_utc"),
        "status_payload": payload,
        "selected_a_plus_candidate": _first(
            payload.get("selected_a_plus_candidate"),
            payload.get("active_candidate"),
        ),
        "why_none": why_none,
        "legacy_why_none": legacy_why_none,
        "why_none_detail": truth_finding_ids if current_a_grade_blocker else [],
        "a_grade_blocker_truth": a_grade_blocker_truth,
        "a_plus_candidates": (
            0 if current_a_grade_blocker else payload.get("a_plus_candidates", 0)
        ),
        "live_ready_candidates": (
            0
            if current_a_grade_blocker
            else payload.get("live_ready_candidates", 0)
        ),
        "dry_run": payload.get("dry_run", True),
        "operator_approval_required": True,
        "live_gate": "blocked_human_only",
        "order_submitted": False,
        "test_order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
        "order_builder_dry_run": {
            "available": bool(payload),
            "post_only_maker_first": payload.get("post_only_maker_first"),
            "taker_fallback_reason": payload.get("taker_fallback_reason"),
            "reduce_close_path": payload.get("reduce_close_path"),
        },
        "no_mutation_flags": {
            "real_order_attempted": bool(payload.get("real_order_attempted")),
            "real_order_submitted": bool(payload.get("real_order_submitted")),
            "test_order_submitted": bool(payload.get("test_order_submitted")),
            "leverage_changed": bool(payload.get("leverage_changed")),
            "margin_mode_changed": bool(payload.get("margin_mode_changed")),
            "places_real_order": False,
            "routes_to_live": False,
        },
    }
    return _contract(
        schema_version="control_center_live_canary_status_v1",
        canonical_owner="/api/v2/live-canary/status",
        source="redis:v2:live_canary:status",
        data=data,
    )


@router.get("/a-plus/inventory")
async def get_a_plus_inventory() -> dict[str, Any]:
    client = get_redis()
    payload = _read_json(client, "v2:paper:a_plus_gate:status")
    source_key_present = bool(payload)
    supply_status = _read_json(client, "v2:paper:a_plus_supply_status")
    supply_status_age_seconds = _age_seconds(supply_status) if supply_status else None
    supply_status_fresh = (
        bool(supply_status)
        and supply_status_age_seconds is not None
        and supply_status_age_seconds <= 900
    )
    rows = (
        payload.get("candidate_matrix")
        if isinstance(payload.get("candidate_matrix"), list)
        else []
    )
    a_plus_rows = [
        row for row in rows if isinstance(row, dict) and row.get("a_plus") is True
    ]
    # Strict fail-closed counting: an a_plus:true row with non-empty
    # failed_checks or an adaptive-gate override is NOT a strict A+ candidate.
    strict_a_plus_rows = [
        row
        for row in a_plus_rows
        if not row.get("failed_checks")
        and not row.get("adaptive_gate_override_applied")
    ]
    adaptive_override_rows = [
        row
        for row in a_plus_rows
        if row.get("failed_checks") or row.get("adaptive_gate_override_applied")
    ]
    live_ready_rows = [
        row
        for row in rows
        if isinstance(row, dict)
        and (row.get("live_ready") or row.get("live_candidate_eligible"))
    ]
    exact_no_a_plus_reason, top_a_plus_blockers = _a_plus_blocker_summary(
        payload,
        rows,
        a_plus_count=len(strict_a_plus_rows),
    )
    legacy_exact_no_a_plus_reason = exact_no_a_plus_reason
    legacy_top_a_plus_blockers = list(top_a_plus_blockers)
    a_grade_blocker_truth = _current_a_grade_blocker_truth(client)
    truth_finding_ids = a_grade_blocker_truth.get("finding_ids")
    if not isinstance(truth_finding_ids, list):
        truth_finding_ids = []
    current_a_grade_blocker = (
        a_grade_blocker_truth.get("primary_blocker")
        if len(strict_a_plus_rows) <= 0
        and a_grade_blocker_truth.get("status") == "A_GRADE_ADAPTATION_NOT_PROVEN"
        else None
    )
    if current_a_grade_blocker:
        exact_no_a_plus_reason = str(current_a_grade_blocker)
        top_a_plus_blockers = _dedupe_strings(
            [current_a_grade_blocker, *truth_finding_ids, *legacy_top_a_plus_blockers]
        )[:12]
    staleness_seconds = _age_seconds(payload) if source_key_present else None
    if not source_key_present:
        # Source-key honesty: the gate status key is missing/expired, which
        # means the paper loop publisher is stale — not "zero candidates".
        heartbeat = _read_json(client, "v2:paper:heartbeat")
        heartbeat_ts = _parse_utc(
            _first(
                heartbeat.get("heartbeat_generated_at"),
                heartbeat.get("finished_at"),
                _payload_timestamp(heartbeat),
            )
        )
        if heartbeat_ts is not None:
            staleness_seconds = max(
                0.0, (datetime.now(UTC) - heartbeat_ts).total_seconds()
            )
        exact_no_a_plus_reason = (
            "A_PLUS_GATE_STATUS_KEY_MISSING_OR_EXPIRED_PAPER_LOOP_STALE"
        )
        top_a_plus_blockers = _dedupe_strings(
            [exact_no_a_plus_reason, *top_a_plus_blockers]
        )[:12]
    if supply_status_fresh:
        counting_source = "redis:v2:paper:a_plus_supply_status"
        evaluated_candidates = _first(
            supply_status.get("evaluated_candidates"),
            payload.get("evaluated_candidates"),
            len(rows),
        )
        a_plus_candidates = _first(
            supply_status.get("strict_a_plus_candidates"),
            len(strict_a_plus_rows),
        )
        adaptive_override_candidates = _first(
            supply_status.get("adaptive_override_candidates"),
            len(adaptive_override_rows),
        )
        live_ready_count = _first(
            supply_status.get("live_ready_rows"),
            len(live_ready_rows),
        )
    else:
        counting_source = "redis:v2:paper:a_plus_gate:status"
        evaluated_candidates = payload.get("evaluated_candidates", len(rows))
        a_plus_candidates = len(strict_a_plus_rows)
        adaptive_override_candidates = len(adaptive_override_rows)
        live_ready_count = len(live_ready_rows)
    data = {
        "schema_version": payload.get("schema_version"),
        "generated_utc": payload.get("generated_utc"),
        "paper_session_id": payload.get("paper_session_id"),
        "source_key_present": source_key_present,
        "staleness_seconds": staleness_seconds,
        "counting_source": counting_source,
        "evaluated_candidates": evaluated_candidates,
        "a_plus_candidates": a_plus_candidates,
        "adaptive_override_candidates": adaptive_override_candidates,
        "a_plus_counting_policy": "STRICT_FAIL_CLOSED_OVERRIDES_EXCLUDED",
        "publisher_reported_a_plus_candidates": payload.get("a_plus_candidates"),
        "live_ready_rows": live_ready_count,
        "a_plus_supply_status": supply_status or None,
        "a_plus_supply_status_fresh": supply_status_fresh,
        "a_plus_supply_status_age_seconds": supply_status_age_seconds,
        "exact_no_a_plus_reason": exact_no_a_plus_reason,
        "top_a_plus_blockers": top_a_plus_blockers,
        "legacy_exact_no_a_plus_reason": legacy_exact_no_a_plus_reason,
        "legacy_top_a_plus_blockers": legacy_top_a_plus_blockers,
        "a_grade_blocker_truth": a_grade_blocker_truth,
        "counts_as_final_a_plus": False,
        "b_grade_counts_as_final_a_plus": False,
        "probation_counts_as_final_a_plus": False,
        "rejected_reason_matrix": payload.get("rejected_reason_matrix"),
        "candidate_matrix_preview": rows[:PREVIEW_LIMIT],
        "a_plus_preview": a_plus_rows[:PREVIEW_LIMIT],
        "payload_compacted": len(rows) > PREVIEW_LIMIT,
        "full_candidate_count": len(rows),
    }
    return _contract(
        schema_version="control_center_a_plus_inventory_v1",
        canonical_owner="/api/v2/a-plus/inventory",
        source=counting_source,
        data=data,
    )
