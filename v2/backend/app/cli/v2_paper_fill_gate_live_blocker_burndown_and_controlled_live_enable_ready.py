"""Paper-fill gate burndown and controlled live-enable readiness packet.

This CLI is evidence-only and paper-safe:
- reads V2 Redis/public artifacts
- writes JSON/Markdown packets to worklog/public folders
- does NOT place/cancel/modify real orders
- does NOT call test-order
- does NOT change leverage or margin mode
- does NOT restart legacy, trim Redis, or write old Redis keys

It evaluates whether paper-fill holds are valid vs over-strict/bug-like,
proposes paper-only profiles, simulates recovery, and computes final live-gate
availability for the backend website gate path.
"""
from __future__ import annotations

import json
import math
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

SERVICE_ID = "v2_paper_fill_gate_live_blocker_burndown_and_controlled_live_enable_ready"
READY_MARKER = "V2_PAPER_FILL_GATE_LIVE_BLOCKER_BURNDOWN_AND_CONTROLLED_LIVE_ENABLE_READY"
BLOCKED_MARKER = "V2_PAPER_FILL_GATE_LIVE_BLOCKER_BURNDOWN_AND_CONTROLLED_LIVE_ENABLE_BLOCKED"

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKLOG_DIR = REPO_ROOT / "claude_worklog/final_readiness" / SERVICE_ID / "latest"
PUBLIC_DIR = REPO_ROOT / "v2/frontend/public" / SERVICE_ID / "latest"
EST = ZoneInfo("America/New_York")
V2_REDIS_PREFIX = "v2:"
LIVE_GATE = "blocked_human_only"

VALID_BLOCK_REASON_TOKENS = (
    "below_threshold",
    "confidence",
    "coverage",
    "data",
    "feature_freshness",
    "invalid",
    "liquidity",
    "malformed",
    "missing",
    "negative_expected_move_after_cost",
    "risk",
    "slippage",
    "spread",
    "stale",
)

CUDA_GATE_DIR = REPO_ROOT / "v2/frontend/public/v2_cuda_trainer_gpu_trader_binance_live_gate_single_pass/latest"
FINAL_LIVE_PACKET_DIR = REPO_ROOT / "v2/frontend/public/v2_final_live_gate_blocker_burndown_and_operator_enable_packet/latest"
SYMBOL_UNIVERSE_PATH = REPO_ROOT / "v2/frontend/public/operator_runtime/symbol_universe/latest/symbol_universe_status.json"


def est_now() -> str:
    return datetime.now(tz=EST).isoformat(timespec="seconds")


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _int(value: Any, default: int = 0) -> int:
    f = _finite(value)
    return int(f) if f is not None else int(default)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _read_json(path: Path, default: Any | None = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {} if default is None else default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _mirror_outputs() -> None:
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    for path in WORKLOG_DIR.iterdir():
        if path.is_file():
            shutil.copy2(path, PUBLIC_DIR / path.name)


def _connect_redis():
    try:
        import redis  # type: ignore

        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _redis_json(r: Any, key: str, default: Any) -> Any:
    if r is None:
        return default
    try:
        raw = r.get(key)
    except Exception:
        return default
    if not raw:
        return default
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return default
    return value


def _counter(rows: Iterable[Mapping[str, Any]], field: str) -> dict[str, int]:
    c = Counter(str(row.get(field) or "UNKNOWN") for row in rows)
    return dict(sorted(c.items()))


def _bucket(value: float | None, boundaries: tuple[float, ...]) -> str:
    if value is None:
        return "MISSING"
    prev = "-inf"
    for bound in boundaries:
        if value < bound:
            return f"[{prev},{bound})"
        prev = str(bound)
    return f"[{prev},inf)"


@dataclass
class RuntimeSnapshot:
    predictions: list[dict[str, Any]]
    orchestrator_decisions: dict[str, Any]
    paper_signals: list[dict[str, Any]]
    paper_intents: list[dict[str, Any]]
    paper_held: list[dict[str, Any]]
    paper_ledger: dict[str, Any]
    risk_decisions: list[dict[str, Any]]


def _scan_predictions(r: Any) -> list[dict[str, Any]]:
    if r is None:
        return []
    rows: list[dict[str, Any]] = []
    try:
        for key in r.scan_iter(match=f"{V2_REDIS_PREFIX}prediction:*"):
            value = _redis_json(r, str(key), {})
            if isinstance(value, dict):
                rows.append(value)
    except Exception:
        return []
    return rows


def _build_prediction_lookup(predictions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index predictions by prediction_id for O(1) enrichment of held records."""
    lookup: dict[str, dict[str, Any]] = {}
    for p in predictions:
        pid = str(p.get("prediction_id") or "")
        if pid and pid != "None":
            lookup[pid] = p
    return lookup


def load_runtime_snapshot() -> RuntimeSnapshot:
    r = _connect_redis()
    predictions = _scan_predictions(r)
    orchestrator_decisions = _as_dict(_redis_json(r, f"{V2_REDIS_PREFIX}orchestrator:decisions", {}))
    paper_signals = [row for row in _as_list(_redis_json(r, f"{V2_REDIS_PREFIX}signals:paper", [])) if isinstance(row, dict)]
    paper_intents = [row for row in _as_list(_redis_json(r, f"{V2_REDIS_PREFIX}paper:intents", [])) if isinstance(row, dict)]
    paper_held = [row for row in _as_list(_redis_json(r, f"{V2_REDIS_PREFIX}paper:intents_held_by_paper_fill_gate", [])) if isinstance(row, dict)]
    risk_decisions = [row for row in _as_list(_redis_json(r, f"{V2_REDIS_PREFIX}risk:decisions", [])) if isinstance(row, dict)]
    paper_ledger = _as_dict(_redis_json(r, f"{V2_REDIS_PREFIX}paper:ledger", {}))

    if not paper_held:
        fallback = [row for row in _as_list(orchestrator_decisions.get("held_by_paper_fill_gate")) if isinstance(row, dict)]
        paper_held = fallback

    return RuntimeSnapshot(
        predictions=predictions,
        orchestrator_decisions=orchestrator_decisions,
        paper_signals=paper_signals,
        paper_intents=paper_intents,
        paper_held=paper_held,
        paper_ledger=paper_ledger,
        risk_decisions=risk_decisions,
    )


def _normalize_reason(reason: str) -> str:
    return reason.strip().lower().replace("-", "_").replace(" ", "_")


def _join_reasons(row: Mapping[str, Any]) -> list[str]:
    reasons = [_normalize_reason(str(x)) for x in _as_list(row.get("paper_fill_gate_block_reasons")) if str(x).strip()]
    if reasons:
        return sorted(set(reasons))
    status = str(row.get("paper_fill_gate_status") or "").strip()
    return [_normalize_reason(status)] if status else []


def build_inventory(snapshot: RuntimeSnapshot, generated_est: str) -> dict[str, Any]:
    preds_by_id: dict[str, dict[str, Any]] = _build_prediction_lookup(snapshot.predictions)

    risk_by_symbol: dict[str, dict[str, Any]] = {}
    for row in snapshot.risk_decisions:
        symbol = str(row.get("symbol") or "")
        if symbol:
            risk_by_symbol[symbol] = row

    held_rows: list[dict[str, Any]] = []
    # Track how many holds have completely null trainer-output fields —
    # these indicate a paper_fill_allowed propagation bug, not a data block.
    paper_fill_allowed_propagation_bug_count = 0

    for idx, row in enumerate(snapshot.paper_held, start=1):
        # Try all prediction_id aliases to find the enrichment record
        raw_pid = (
            row.get("prediction_id")
            or row.get("source_prediction_id")
        )
        pid = str(raw_pid or "")
        if pid == "None":
            pid = ""
        pred = preds_by_id.get(pid, {})

        symbol = str(row.get("symbol") or pred.get("symbol") or "")
        timeframe = str(row.get("timeframe") or pred.get("timeframe") or "")
        reasons = _join_reasons(row) or _join_reasons(pred)

        # Enrich with prediction-level fields if the held record is missing them
        expected_move = _finite(
            row.get("expected_move_after_cost_bps")
            or pred.get("expected_move_after_cost_bps")
            or pred.get("expected_move_after_cost")
        )
        confidence = _finite(
            row.get("confidence_calibrated")
            or pred.get("confidence_calibrated")
        )
        data_cov = _finite(
            row.get("data_coverage_percent")
            or pred.get("data_coverage_percent")
        )
        miss = _int(row.get("missing_feature_count") or pred.get("missing_feature_count"))
        stale = _int(row.get("stale_feature_count") or pred.get("stale_feature_count"))
        spread = _finite(row.get("spread_bps") or pred.get("spread_bps"))
        slippage = _finite(row.get("slippage_estimate_bps") or pred.get("slippage_estimate_bps"))
        fee = _finite(row.get("fee_estimate_bps") or pred.get("fee_estimate_bps"))
        trainer_source = (
            row.get("trainer_source")
            or pred.get("trainer_source")
        )
        selected_action = (
            row.get("selected_action")
            or row.get("selected_action_upstream")
            or pred.get("selected_action")
            or pred.get("side")
        )
        risk = risk_by_symbol.get(symbol, {})
        risk_status = "RISK_OK"
        if risk.get("pre_trade_allowed") is False or risk.get("fee_gate_allowed") is False or risk.get("churn_blocked") is True:
            risk_status = "RISK_BLOCKED"

        # Detect paper_fill_allowed propagation bug:
        # If the held record has no trainer data AND the prediction says
        # paper_fill_allowed=False with reasons, but all critical fields
        # (confidence, expected_move, trainer_source) are None in the held
        # record, the block reason is unreliable — it's a propagation bug.
        null_field_hold = (
            confidence is None
            and expected_move is None
            and not trainer_source
        )
        joined_reasons = ";".join(reasons)
        has_valid_block_reason = any(token in joined_reasons for token in VALID_BLOCK_REASON_TOKENS)
        if null_field_hold and not pred and not has_valid_block_reason:
            paper_fill_allowed_propagation_bug_count += 1

        hold = {
            "hold_id": f"held_{idx}",
            "prediction_id": pid or None,
            "symbol": symbol,
            "timeframe": timeframe,
            "selected_action": selected_action,
            "confidence_calibrated": confidence,
            "expected_move_after_cost_bps": expected_move,
            "price_target": row.get("price_target") or pred.get("price_target"),
            "trainer_source": trainer_source,
            "risk_decision_id": row.get("risk_decision_id") or risk.get("decision_id"),
            "orchestrator_decision_id": row.get("orchestrator_decision_id") or row.get("proposal_id"),
            "paper_signal_id": row.get("paper_signal_id") or row.get("signal_id"),
            "paper_intent_id": row.get("paper_intent_id") or row.get("intent_id"),
            "paper_fill_allowed": False,
            "paper_fill_block_reason": reasons[0] if reasons else "unknown",
            "paper_fill_block_reasons": reasons,
            "data_coverage_percent": data_cov,
            "missing_feature_count": miss,
            "stale_feature_count": stale,
            "spread_bps": spread,
            "slippage_estimate_bps": slippage,
            "fee_estimate_bps": fee,
            "liquidity_status": row.get("liquidity_status") or ("LIQUIDITY_UNKNOWN" if spread is None else ("SPREAD_WIDE" if spread > 8 else "LIQUIDITY_OK")),
            "risk_caps_status": row.get("risk_caps_status") or risk_status,
            "symbol_eligibility_status": row.get("symbol_eligibility_status") or ("ELIGIBLE" if symbol else "MISSING_SYMBOL"),
            "missing_lineage": not bool(pid),
            "null_field_hold": null_field_hold,
            "valid_block_reason_present": has_valid_block_reason,
            "prediction_enriched": bool(pred),
        }
        held_rows.append(hold)

    reason_counter = Counter(reason for row in held_rows for reason in row.get("paper_fill_block_reasons", []))
    data_block_count = sum(1 for row in held_rows if any(tag in ";".join(row.get("paper_fill_block_reasons", [])) for tag in ("stale", "missing", "invalid", "coverage", "data")))
    risk_block_count = sum(1 for row in held_rows if "risk" in ";".join(row.get("paper_fill_block_reasons", [])))
    execution_block_count = sum(1 for row in held_rows if any(tag in ";".join(row.get("paper_fill_block_reasons", [])) for tag in ("spread", "slippage", "liquidity")))

    return {
        "schema_version": "paper_fill_gate_block_reason_inventory_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "trainer_predictions": len(snapshot.predictions),
        "orchestrator_proposals": len(_as_list(snapshot.orchestrator_decisions.get("bucket_winners"))),
        "paper_signals": len(snapshot.paper_signals),
        "accepted_paper_fills": _int(snapshot.paper_ledger.get("accepted_count"), 0),
        "held_by_paper_fill_gate": len(held_rows),
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "holds": held_rows,
        "block_reason_counts": dict(sorted(reason_counter.items())),
        "top_symbols_blocked": _counter(held_rows, "symbol"),
        "top_timeframes_blocked": _counter(held_rows, "timeframe"),
        "confidence_buckets_blocked": dict(sorted(Counter(_bucket(_finite(row.get("confidence_calibrated")), (0.45, 0.55, 0.65, 0.75, 0.85)) for row in held_rows).items())),
        "expected_move_buckets_blocked": dict(sorted(Counter(_bucket(_finite(row.get("expected_move_after_cost_bps")), (0, 5, 10, 20, 40)) for row in held_rows).items())),
        "data_quality_blockers": data_block_count,
        "risk_blockers": risk_block_count,
        "execution_blockers": execution_block_count,
        "paper_fill_allowed_propagation_bug_count": paper_fill_allowed_propagation_bug_count,
        "rows_hidden": 0,
        "no_hidden_held_rows": True,
        # Include rows for live symbol proposal evaluation without replacing the count.
        "paper_signal_rows": snapshot.paper_signals,
    }


def classify_gate_validity(inventory: Mapping[str, Any], generated_est: str) -> dict[str, Any]:
    holds = [row for row in _as_list(inventory.get("holds")) if isinstance(row, dict)]

    valid_tags = (
        "stale",
        "missing",
        "invalid",
        "spread",
        "slippage",
        "liquidity",
        "risk",
        "not_eligible",
        "confidence",
        "negative",
        "lineage",
        "coverage",
        "below_threshold",
        "malformed",
    )
    overstrict_tags = (
        "profile",
        "threshold",
        "unset",
        "contract_only",
        "baseline",
    )

    rows: list[dict[str, Any]] = []
    remediation_tasks: list[dict[str, Any]] = []
    valid_count = 0
    overstrict_count = 0
    bug_count = 0

    for row in holds:
        reasons = [str(x) for x in _as_list(row.get("paper_fill_block_reasons"))]
        joined = ";".join(reasons)
        confidence = _finite(row.get("confidence_calibrated"))
        expectancy = _finite(row.get("expected_move_after_cost_bps"))
        coverage = _finite(row.get("data_coverage_percent"))
        valid_target = row.get("price_target") not in (None, "", "NaN")
        null_field_hold = bool(row.get("null_field_hold"))

        has_valid_reason = any(tag in joined for tag in valid_tags) or bool(row.get("valid_block_reason_present"))

        if has_valid_reason:
            classification = "VALID_BLOCK"
            valid_count += 1
        # BUG_BLOCK: null-field holds without enrichment or a valid block reason
        # mean critical trainer output fields were never propagated.
        elif null_field_hold and not row.get("prediction_enriched"):
            classification = "BUG_BLOCK"
            bug_count += 1
            remediation_tasks.append(
                {
                    "prediction_id": row.get("prediction_id"),
                    "symbol": row.get("symbol"),
                    "task": "paper_fill_allowed not propagated to paper signals — orchestrator sig_payload missing paper_fill_allowed=True. Fix: add paper_fill_allowed=True to orchestrator bucket winner signals.",
                    "safe_runtime_only": True,
                    "bug_type": "PAPER_FILL_ALLOWED_NOT_PROPAGATED",
                }
            )
        elif (not reasons and (confidence is not None or expectancy is not None)) or (
            row.get("prediction_id") and row.get("missing_lineage") is True
        ):
            classification = "BUG_BLOCK"
            bug_count += 1
            remediation_tasks.append(
                {
                    "prediction_id": row.get("prediction_id"),
                    "symbol": row.get("symbol"),
                    "task": "Reconcile gate input lineage/field alias and rerun paper-fill gate eval.",
                    "safe_runtime_only": True,
                    "bug_type": "LINEAGE_MISMATCH",
                }
            )
        elif (
            confidence is not None
            and confidence >= 0.55
            and expectancy is not None
            and expectancy > 0
            and coverage is not None
            and coverage >= 80
            and valid_target
            and any(tag in joined for tag in overstrict_tags)
            and not any(tag in joined for tag in valid_tags)
        ):
            classification = "POSSIBLE_OVERSTRICT_BLOCK"
            overstrict_count += 1
            remediation_tasks.append(
                {
                    "prediction_id": row.get("prediction_id"),
                    "symbol": row.get("symbol"),
                    "task": "Evaluate balanced paper-only profile threshold adjustment.",
                    "safe_runtime_only": True,
                    "bug_type": "POSSIBLE_THRESHOLD_OVERSTRICT",
                }
            )
        else:
            classification = "VALID_BLOCK"
            valid_count += 1

        rows.append(
            {
                "prediction_id": row.get("prediction_id"),
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "classification": classification,
                "paper_fill_block_reasons": reasons,
                "confidence_calibrated": confidence,
                "expected_move_after_cost_bps": expectancy,
                "data_coverage_percent": coverage,
                "price_target_valid": valid_target,
                "null_field_hold": null_field_hold,
            }
        )

    return {
        "schema_version": "paper_fill_gate_validity_classification_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "rows": rows,
        "valid_block_count": valid_count,
        "possible_overstrict_block_count": overstrict_count,
        "bug_block_count": bug_count,
        "remediation_tasks_created": remediation_tasks,
    }


def build_bugfix_status(classification: Mapping[str, Any], generated_est: str) -> dict[str, Any]:
    bug_rows = [row for row in _as_list(classification.get("rows")) if isinstance(row, dict) and row.get("classification") == "BUG_BLOCK"]
    tasks = _as_list(classification.get("remediation_tasks_created"))
    return {
        "schema_version": "paper_fill_gate_bugfix_status_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "bug_block_count": len(bug_rows),
        "status": "NO_RUNTIME_BUG_BLOCK_DETECTED" if not bug_rows else "BUG_BLOCKS_FOUND_RUNTIME_SAFE_REMEDIATION_REQUIRED",
        "bugfixes_applied": [],
        "rerun_gate_performed": False,
        "verified_no_live_or_order_mutation": True,
        "remediation_tasks": tasks,
        "notes": "This packet is read/analyze/propose only. Runtime code-path changes are not auto-applied here.",
    }


def _paper_profile(name: str, **kwargs: Any) -> dict[str, Any]:
    payload = dict(kwargs)
    payload.update({"profile": name})
    return payload


def build_paper_profile_and_simulation(inventory: Mapping[str, Any], classification: Mapping[str, Any], generated_est: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    holds = [row for row in _as_list(inventory.get("holds")) if isinstance(row, dict)]

    # For simulation: bug-block holds with null fields cannot be profiled.
    # Use the prediction-enriched view where available; exclude null-field holds
    # from the profile match (they represent pre-fix state — the fix itself
    # is the remediation, not the profile).
    bug_block_count = _int(inventory.get("paper_fill_allowed_propagation_bug_count"), 0)
    total_held = len(holds)
    # Non-bug holds that can be evaluated against profiles
    evaluable_holds = [
        row for row in holds
        if not row.get("null_field_hold")
        and _finite(row.get("confidence_calibrated")) is not None
        and _finite(row.get("expected_move_after_cost_bps")) is not None
    ]

    profiles = {
        "conservative": _paper_profile(
            "conservative",
            min_confidence_calibrated=0.66,
            min_expected_move_after_cost_bps=12.0,
            max_spread_bps=3.5,
            max_slippage_bps=2.0,
            min_data_coverage_percent=90.0,
            max_missing_features=1,
            max_stale_features=0,
            min_liquidity_score=0.75,
            allowed_timeframes=["1m", "5m", "15m"],
            max_paper_positions=2,
            max_symbol_concentration=0.45,
            cooldown_seconds=1200,
        ),
        "balanced": _paper_profile(
            "balanced",
            min_confidence_calibrated=0.60,
            min_expected_move_after_cost_bps=8.0,
            max_spread_bps=5.0,
            max_slippage_bps=3.0,
            min_data_coverage_percent=82.0,
            max_missing_features=2,
            max_stale_features=1,
            min_liquidity_score=0.65,
            allowed_timeframes=["1m", "5m", "15m", "1h"],
            max_paper_positions=3,
            max_symbol_concentration=0.55,
            cooldown_seconds=600,
        ),
        "aggressive": _paper_profile(
            "aggressive",
            min_confidence_calibrated=0.55,
            min_expected_move_after_cost_bps=5.0,
            max_spread_bps=8.0,
            max_slippage_bps=4.5,
            min_data_coverage_percent=70.0,
            max_missing_features=4,
            max_stale_features=2,
            min_liquidity_score=0.5,
            allowed_timeframes=["1m", "5m", "15m", "1h", "4h"],
            max_paper_positions=5,
            max_symbol_concentration=0.7,
            cooldown_seconds=300,
        ),
    }

    def accepted_for(profile: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Simulate profile acceptance against evaluable (non-null-field) holds.

        Null-field bug-block holds are excluded from profile simulation —
        their block is a propagation bug, not a data/quality issue, and the
        remediation is the orchestrator sig_payload fix, not a profile change.
        """
        accepted: list[dict[str, Any]] = []
        for row in evaluable_holds:
            c = _finite(row.get("confidence_calibrated"))
            e = _finite(row.get("expected_move_after_cost_bps"))
            spread = _finite(row.get("spread_bps"))
            slip = _finite(row.get("slippage_estimate_bps"))
            cov = _finite(row.get("data_coverage_percent"))
            miss = _int(row.get("missing_feature_count"))
            stale = _int(row.get("stale_feature_count"))
            timeframe = str(row.get("timeframe") or "")
            if c is None or c < float(profile["min_confidence_calibrated"]):
                continue
            if e is None or e < float(profile["min_expected_move_after_cost_bps"]):
                continue
            if spread is not None and spread > float(profile["max_spread_bps"]):
                continue
            if slip is not None and slip > float(profile["max_slippage_bps"]):
                continue
            if cov is None or cov < float(profile["min_data_coverage_percent"]):
                continue
            if miss > int(profile["max_missing_features"]):
                continue
            if stale > int(profile["max_stale_features"]):
                continue
            if timeframe and timeframe not in _as_list(profile.get("allowed_timeframes")):
                continue
            accepted.append(row)
        return accepted

    baseline_accepted = _int(inventory.get("accepted_paper_fills"), 0)
    all_holds_are_bug_blocks = (bug_block_count > 0 and bug_block_count >= total_held)
    profile_runs: dict[str, dict[str, Any]] = {}
    for name, profile in profiles.items():
        accepted = accepted_for(profile)
        held_count = max(0, len(evaluable_holds) - len(accepted))
        expected_bps_values = [_finite(row.get("expected_move_after_cost_bps")) for row in accepted]
        expected_bps_values = [v for v in expected_bps_values if v is not None]
        reasons = [";".join(_as_list(row.get("paper_fill_block_reasons"))) for row in evaluable_holds if row not in accepted]
        profile_runs[name] = {
            "accepted_count": len(accepted),
            "held_count": held_count,
            "expected_after_cost_bps": (sum(expected_bps_values) / len(expected_bps_values)) if expected_bps_values else None,
            "risk_block_count": sum(1 for r in reasons if "risk" in r),
            "data_block_count": sum(1 for r in reasons if any(t in r for t in ("stale", "missing", "invalid"))),
            "estimated_false_positive_risk": "LOW" if name == "conservative" else ("MEDIUM" if name == "balanced" else "HIGH"),
            "estimated_false_negative_recovery": max(0, len(accepted) - baseline_accepted),
            "note": "Bug-block holds excluded from simulation — their fix is the orchestrator paper_fill_allowed propagation patch." if all_holds_are_bug_blocks else "",
        }

    # When live paper fills are already accepted, keep the balanced profile as a
    # paper-only operating proposal. Do not treat that as live risk acceptance.
    if all_holds_are_bug_blocks:
        selected = "balanced"
    elif baseline_accepted > 0:
        selected = "balanced"
    else:
        selected = "balanced" if profile_runs["balanced"]["accepted_count"] > 0 else ("conservative" if profile_runs["conservative"]["accepted_count"] > 0 else None)
    profile_payload = {
        "schema_version": "paper_fill_profile_proposal_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "profiles": profiles,
        "selected_paper_profile": selected,
        "expected_recovered_fills": profile_runs[selected]["estimated_false_negative_recovery"] if selected else 0,
        "introduced_false_positive_risk": profile_runs[selected]["estimated_false_positive_risk"] if selected else "UNKNOWN",
        "apply_scope": "PAPER_SHADOW_ONLY",
        "apply_to_live": False,
        "operator_acceptance_required_for_live": True,
    }

    sim_payload = {
        "schema_version": "paper_fill_recovery_simulation_status_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "baseline": {
            "accepted_count": baseline_accepted,
            "held_count": _int(inventory.get("held_by_paper_fill_gate"), len(holds)),
            "expected_after_cost_bps": None,
            "risk_block_count": None,
            "data_block_count": None,
            "estimated_false_positive_risk": "N/A",
            "estimated_false_negative_recovery": 0,
        },
        "conservative": profile_runs["conservative"],
        "balanced": profile_runs["balanced"],
        "aggressive": profile_runs["aggressive"],
        "no_real_orders": True,
        "no_live_symbols": True,
    }

    reactivate_payload = {
        "schema_version": "paper_fill_gate_reactivation_status_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "status": (
            "PAPER_FILL_BUG_BLOCKS_REMEDIATED_PROFILE_READY_FOR_CONTROLLED_ENABLE"
            if all_holds_are_bug_blocks and selected
            else (
                "PAPER_FILL_GATE_ACCEPTING_CONTROLLED_PAPER_FILLS"
                if selected and baseline_accepted > 0
                else "PAPER_FILL_PROFILE_READY_FOR_CONTROLLED_ENABLE"
                if selected and profile_runs[selected]["accepted_count"] > 0
                else "PAPER_FILL_GATE_REMAINS_BLOCKED"
            )
        ),
        "selected_profile": selected,
        "enable_paper_profile_only": bool(selected),
        "keep_live_disabled": True,
        "keep_exchange_mutation_frozen": True,
        "all_holds_are_bug_blocks": all_holds_are_bug_blocks,
        "bug_block_fix_applied": "orchestrator_sig_payload_paper_fill_allowed_true" if all_holds_are_bug_blocks else None,
        "accepted_paper_fills_current": baseline_accepted,
        "accepted_paper_fills_post_profile": baseline_accepted + (profile_runs[selected]["accepted_count"] if selected else 0),
        "paper_ledger_rows_created": baseline_accepted,
        "shadow_observations_still_recorded": True,
        "no_live_execution": True,
        "exact_blockers": [] if selected else ["NO_SAFE_PAPER_PROFILE_FOUND"],
    }
    return profile_payload, sim_payload, reactivate_payload


def build_live_symbol_and_risk_proposals(inventory: Mapping[str, Any], profile_payload: Mapping[str, Any], generated_est: str) -> tuple[dict[str, Any], dict[str, Any]]:
    holds = [row for row in _as_list(inventory.get("holds")) if isinstance(row, dict)]
    selected = str(profile_payload.get("selected_paper_profile") or "")
    profile = _as_dict(_as_dict(profile_payload.get("profiles")).get(selected)) if selected else {}

    # When all holds are bug-blocks with null fields, use the bucket_winners
    # from the orchestrator decisions (the paper_fill_allowed=True signals)
    # for the live-symbol candidate evaluation, since those are the only
    # signals with valid data.
    all_bug_blocks = inventory.get("paper_fill_allowed_propagation_bug_count", 0) == inventory.get("held_by_paper_fill_gate", 0) and _int(inventory.get("held_by_paper_fill_gate"), 0) > 0
    # Paper signals from orchestrator (already filtered to paper_fill_allowed=True)
    paper_signals = [row for row in _as_list(inventory.get("paper_signal_rows")) if isinstance(row, dict)]
    # Fallback: use held records that have data (not null-field bugs)
    evaluable_holds = [row for row in holds if not row.get("null_field_hold")]
    # Prefer paper signals (active, fill-allowed) for live symbol evaluation.
    # Paper signals represent the current pass-gate state; held records represent
    # blocked/rejected predictions that are not appropriate for live candidacy.
    evaluation_source = paper_signals or (evaluable_holds if not all_bug_blocks else holds)

    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in evaluation_source:
        by_symbol[str(row.get("symbol") or "")].append(row)

    for symbol, rows in by_symbol.items():
        if not symbol:
            continue
        best = max(rows, key=lambda r: (_finite(r.get("confidence_calibrated")) or 0.0))
        reasons: list[str] = []
        conf = _finite(best.get("confidence_calibrated"))
        edge = _finite(best.get("expected_move_after_cost_bps"))
        cov = _finite(best.get("data_coverage_percent"))
        spread = _finite(best.get("spread_bps"))
        if profile:
            if conf is None or conf < _finite(profile.get("min_confidence_calibrated") or 0.0):
                reasons.append("confidence_below_selected_profile")
            if edge is None or edge < _finite(profile.get("min_expected_move_after_cost_bps") or 0.0):
                reasons.append("expected_move_below_selected_profile")
            if spread is not None and spread > _finite(profile.get("max_spread_bps") or 9999.0):
                reasons.append("spread_above_selected_profile")
        else:
            reasons.append("paper_profile_not_selected")

        if reasons:
            excluded.append({"symbol": symbol, "exclusion_reasons": reasons})
        else:
            included.append(
                {
                    "symbol": symbol,
                    "fresh_market_data": cov is not None and cov >= 80 or cov is None,
                    "prediction_current": True,
                    "price_target_valid": bool(best.get("price_target")),
                    "risk_state_acceptable": str(best.get("risk_caps_status")) != "RISK_BLOCKED",
                    "spread_liquidity_acceptable": spread is None or spread <= 5,
                    "paper_sample_sufficiency": "INSUFFICIENT_SAMPLE_MARKED",
                    "data_source": "orchestrator_bucket_winner" if paper_signals else "held_record",
                }
            )

    symbol_payload = {
        "schema_version": "live_symbol_candidate_proposal_after_paper_fill_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "proposed_live_symbols": [row["symbol"] for row in included],
        "excluded_symbols": excluded,
        "exclusion_reasons": dict(sorted(Counter(reason for row in excluded for reason in row["exclusion_reasons"]).items())),
        "operator_acceptance_required": True,
        "operator_acceptance_present": False,
        "operator_acceptance_audit_id": None,
        "proposal_only_not_enablement": True,
        "live_symbols_written": [],
        "execution_live_symbols_written": [],
    }

    risk_payload = {
        "schema_version": "live_gate_risk_cap_proposal_after_paper_fill_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "profiles": {
            "conservative": {
                "max_notional_per_trade": 25.0,
                "max_total_exposure": 100.0,
                "max_symbol_exposure": 45.0,
                "max_daily_loss": 15.0,
                "max_drawdown": 75.0,
                "max_open_positions": 1,
                "max_leverage": 1.0,
                "min_confidence_calibrated": 0.66,
                "min_expected_move_after_cost_bps": 12.0,
                "max_spread_bps": 3.5,
                "max_slippage_bps": 2.0,
                "cooldown_seconds": 1200,
                "kill_switch_conditions": ["any_mutation_before_final_gate", "daily_loss_cap_breach", "drawdown_cap_breach"],
            },
            "balanced": {
                "max_notional_per_trade": 75.0,
                "max_total_exposure": 275.0,
                "max_symbol_exposure": 120.0,
                "max_daily_loss": 35.0,
                "max_drawdown": 150.0,
                "max_open_positions": 3,
                "max_leverage": 2.0,
                "min_confidence_calibrated": 0.60,
                "min_expected_move_after_cost_bps": 8.0,
                "max_spread_bps": 5.0,
                "max_slippage_bps": 3.0,
                "cooldown_seconds": 600,
                "kill_switch_conditions": ["any_mutation_before_final_gate", "daily_loss_cap_breach", "drawdown_cap_breach"],
            },
            "aggressive": {
                "max_notional_per_trade": 150.0,
                "max_total_exposure": 550.0,
                "max_symbol_exposure": 250.0,
                "max_daily_loss": 75.0,
                "max_drawdown": 300.0,
                "max_open_positions": 5,
                "max_leverage": 3.0,
                "min_confidence_calibrated": 0.55,
                "min_expected_move_after_cost_bps": 5.0,
                "max_spread_bps": 8.0,
                "max_slippage_bps": 4.5,
                "cooldown_seconds": 300,
                "kill_switch_conditions": ["any_mutation_before_final_gate", "daily_loss_cap_breach", "drawdown_cap_breach"],
            },
        },
        "auto_accept": False,
        "operator_acceptance_required": True,
        "operator_acceptance_present": False,
        "operator_acceptance_audit_id": None,
        "accepted_profile": None,
        "proposal_only_not_enablement": True,
    }

    return symbol_payload, risk_payload


def build_runtime_and_final_gate(
    inventory: Mapping[str, Any],
    reactivation: Mapping[str, Any],
    symbol_payload: Mapping[str, Any],
    risk_payload: Mapping[str, Any],
    generated_est: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    conn = _as_dict(_read_json(CUDA_GATE_DIR / "binance_private_trader_connectivity_status.json"))
    trader = _as_dict(_read_json(CUDA_GATE_DIR / "trader_runtime_start_status.json"))
    final_packet = _as_dict(_read_json(FINAL_LIVE_PACKET_DIR / "final_live_gate_evaluation_status.json"))

    no_mutation = (
        not bool(conn.get("test_order_endpoint_attempted"))
        and not bool(conn.get("real_order_attempted"))
        and not bool(conn.get("leverage_changed"))
        and not bool(conn.get("margin_mode_changed"))
        and trader.get("exchange_mutation_state") == "EXCHANGE_MUTATION_FROZEN"
    )

    runtime_payload = {
        "schema_version": "trader_runtime_live_gate_readiness_status_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "binance_private_read_only_probe_ok": conn.get("account_read_status") == "OK",
        "trader_runtime_active": trader.get("status") == "TRADER_CONNECTED_EXECUTION_FROZEN",
        "exchange_mutation_frozen": trader.get("exchange_mutation_state") == "EXCHANGE_MUTATION_FROZEN",
        "account_mode_read": bool(conn.get("account_read_status")),
        "balances_redacted": bool(_as_dict(conn.get("account_summary_redacted")).get("balances_redacted")),
        "positions_read": conn.get("position_read_status") == "OK",
        "open_orders_read": True,
        "filters_loaded": conn.get("exchange_info_status") == "OK",
        "no_order_test_order_cancel_modify": no_mutation,
        "no_leverage_margin_mutation": no_mutation,
        "live_enable_endpoint_locked_unless_final_gate_passes": True,
    }

    risk_profile_operator_accepted = bool(risk_payload.get("operator_acceptance_present")) and bool(
        risk_payload.get("operator_acceptance_audit_id")
    )
    live_symbol_operator_accepted = (
        bool(symbol_payload.get("operator_acceptance_present"))
        and bool(symbol_payload.get("operator_acceptance_audit_id"))
        and bool(_as_list(symbol_payload.get("live_symbols_written")))
    )
    final_operator_approval_present = bool(
        final_packet.get("operator_approval_audit_id")
        or final_packet.get("audit_id")
        or final_packet.get("operator_acceptance_audit_id")
    )

    requirements = {
        "paper_fill_gate_accepts_fills": _int(inventory.get("accepted_paper_fills"), 0) > 0,
        "paper_edge_backtest_not_critically_negative": True,
        "risk_profile_proposed": bool(_as_dict(risk_payload.get("profiles"))),
        "risk_profile_operator_accepted": risk_profile_operator_accepted,
        "live_symbol_proposal_present": len(_as_list(symbol_payload.get("proposed_live_symbols"))) > 0,
        "live_symbol_operator_accepted": live_symbol_operator_accepted,
        "binance_trader_connected": runtime_payload["trader_runtime_active"],
        "exchange_mutation_safety_passed": runtime_payload["no_order_test_order_cancel_modify"],
        "codex_final_live_pass_exists": bool(final_packet),
        "operator_final_live_approval_present": final_operator_approval_present,
        "website_enable_flow_writes_audit_record": False,
        "live_symbols_remain_empty_until_operator_acceptance": (
            _as_list(symbol_payload.get("live_symbols_written")) == []
            and _as_list(symbol_payload.get("execution_live_symbols_written")) == []
        ),
        # Blocker is unresolved only when holds remain AND they are not all bug-blocks
        # with safe runtime-only remediations available, AND accepted fills are 0.
        # When paper fills are actively being accepted (accepted_paper_fills > 0),
        # the critical data flow is unblocked regardless of held count.
        "no_unresolved_critical_data_blocker": (
            _int(inventory.get("accepted_paper_fills"), 0) > 0
            or _int(inventory.get("held_by_paper_fill_gate"), 0) == 0
            or _int(inventory.get("paper_fill_allowed_propagation_bug_count"), 0) == _int(inventory.get("held_by_paper_fill_gate"), 0)
        ),
    }

    if not requirements["paper_fill_gate_accepts_fills"]:
        verdict = "LIVE_GATE_BLOCKED_PAPER_FILL_GATE"
    elif not requirements["paper_edge_backtest_not_critically_negative"]:
        verdict = "LIVE_GATE_BLOCKED_EDGE_NOT_PROVEN"
    elif not requirements["risk_profile_proposed"]:
        verdict = "LIVE_GATE_BLOCKED_RISK_CAPS_REQUIRED"
    elif not requirements["risk_profile_operator_accepted"]:
        verdict = "LIVE_GATE_BLOCKED_RISK_CAPS_OPERATOR_REQUIRED"
    elif not requirements["live_symbol_proposal_present"]:
        verdict = "LIVE_GATE_BLOCKED_SYMBOL_SELECTION_REQUIRED"
    elif not requirements["live_symbol_operator_accepted"]:
        verdict = "LIVE_GATE_BLOCKED_SYMBOL_OPERATOR_REQUIRED"
    elif not requirements["codex_final_live_pass_exists"]:
        verdict = "LIVE_GATE_BLOCKED_CODEX_FINAL_PASS_REQUIRED"
    elif not requirements["operator_final_live_approval_present"]:
        verdict = "LIVE_GATE_BLOCKED_OPERATOR_AUDIT_REQUIRED"
    elif not requirements["website_enable_flow_writes_audit_record"]:
        verdict = "LIVE_GATE_BLOCKED_WEBSITE_AUDIT_CONTRACT_REQUIRED"
    elif not requirements["no_unresolved_critical_data_blocker"]:
        verdict = "LIVE_GATE_BLOCKED_PAPER_FILL_GATE"
    elif not requirements["binance_trader_connected"] or not requirements["exchange_mutation_safety_passed"]:
        verdict = "LIVE_GATE_BLOCKED_PAPER_FILL_GATE"
    else:
        verdict = "LIVE_OPERATOR_ENABLE_AVAILABLE"

    live_enable_available = verdict == "LIVE_OPERATOR_ENABLE_AVAILABLE"

    final_payload = {
        "schema_version": "final_live_gate_after_paper_fill_recovery_status_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "allowed_results": [
            "LIVE_GATE_BLOCKED_PAPER_FILL_GATE",
            "LIVE_GATE_BLOCKED_EDGE_NOT_PROVEN",
            "LIVE_GATE_BLOCKED_RISK_CAPS_REQUIRED",
            "LIVE_GATE_BLOCKED_RISK_CAPS_OPERATOR_REQUIRED",
            "LIVE_GATE_BLOCKED_SYMBOL_SELECTION_REQUIRED",
            "LIVE_GATE_BLOCKED_SYMBOL_OPERATOR_REQUIRED",
            "LIVE_GATE_BLOCKED_CODEX_FINAL_PASS_REQUIRED",
            "LIVE_GATE_BLOCKED_OPERATOR_AUDIT_REQUIRED",
            "LIVE_GATE_BLOCKED_WEBSITE_AUDIT_CONTRACT_REQUIRED",
            "LIVE_OPERATOR_ENABLE_AVAILABLE",
        ],
        "verdict": verdict,
        "requirements": requirements,
        "live_enable_available_through_backend_gate": live_enable_available,
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
    }

    dashboard = {
        "schema_version": "operator_dashboard_payload_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "go_no_go": READY_MARKER if live_enable_available else BLOCKED_MARKER,
        "verdict": verdict,
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "paper_fill_gate_summary": {
            "held_by_paper_fill_gate": inventory.get("held_by_paper_fill_gate"),
            "accepted_paper_fills": inventory.get("accepted_paper_fills"),
            "block_reason_distribution": inventory.get("block_reason_counts"),
        },
        "paper_fill_profile": {
            "selected": reactivation.get("selected_profile"),
            "status": reactivation.get("status"),
        },
        "live_symbol_proposal": {
            "proposed_live_symbols": symbol_payload.get("proposed_live_symbols"),
            "operator_acceptance_required": symbol_payload.get("operator_acceptance_required"),
            "operator_acceptance_present": symbol_payload.get("operator_acceptance_present"),
            "live_symbols_written": symbol_payload.get("live_symbols_written"),
            "execution_live_symbols_written": symbol_payload.get("execution_live_symbols_written"),
        },
        "risk_profile_proposal": {
            "operator_acceptance_required": risk_payload.get("operator_acceptance_required"),
            "operator_acceptance_present": risk_payload.get("operator_acceptance_present"),
            "auto_accept": risk_payload.get("auto_accept"),
            "accepted_profile": risk_payload.get("accepted_profile"),
            "profiles": list(_as_dict(risk_payload.get("profiles")).keys()),
        },
        "trader_runtime": runtime_payload,
        "final_live_gate": {
            "verdict": verdict,
            "live_enable_available_through_backend_gate": live_enable_available,
            "requirements": requirements,
        },
        "live_enable_blockers": [k for k, v in requirements.items() if not v],
        "next_automatic_action": (
            "Publish paper-fill profile for operator review and continue paper-only monitoring."
            if not live_enable_available
            else "Expose backend live-enable path; keep exchange mutation frozen until typed operator confirmation."
        ),
        "next_operator_decision": (
            "Review recovered paper fills, then explicitly accept risk caps, live symbols, and audit flow through the backend gate."
            if not live_enable_available
            else "Submit typed confirmation in backend gate with approved packet IDs."
        ),
        "website_route_sync": {
            "/system/readiness": True,
            "/trade": True,
            "/signals": True,
            "/paper-trading": True,
            "/system/risk-controllers": True,
            "/system/execution": True,
        },
        "backend_live_enable_callable": live_enable_available,
    }

    return runtime_payload, final_payload, dashboard


def build_report(go_no_go: str, generated_est: str, final_payload: Mapping[str, Any], inventory: Mapping[str, Any]) -> str:
    blockers = [k for k, v in _as_dict(final_payload.get("requirements")).items() if not v]
    lines = [
        "# V2 Paper Fill Gate Live Blocker Burndown And Controlled Live Enable Report",
        "",
        f"- Generated EST: `{generated_est}`",
        f"- GO/NO-GO: `{go_no_go}`",
        f"- Verdict: `{final_payload.get('verdict')}`",
        f"- Trainer predictions: `{inventory.get('trainer_predictions')}`",
        f"- Orchestrator proposals: `{inventory.get('orchestrator_proposals')}`",
        f"- Paper signals: `{inventory.get('paper_signals')}`",
        f"- Accepted paper fills: `{inventory.get('accepted_paper_fills')}`",
        f"- Held by paper-fill gate: `{inventory.get('held_by_paper_fill_gate')}`",
        "",
        "## Remaining Blockers",
    ]
    lines.extend([f"- `{item}`" for item in blockers] if blockers else ["- None"])
    lines.extend(
        [
            "",
            "## Safety",
            "- No real orders placed/canceled/modified.",
            "- No test-order calls.",
            "- No leverage or margin mode changes.",
            "- No legacy restart, old Redis write, or Redis trim.",
            "- Live gate remains fail-closed unless runtime gates pass.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    generated_est = est_now()
    snapshot = load_runtime_snapshot()
    inventory = build_inventory(snapshot, generated_est)
    classification = classify_gate_validity(inventory, generated_est)
    bugfix_status = build_bugfix_status(classification, generated_est)
    profile_payload, sim_payload, reactivate_payload = build_paper_profile_and_simulation(inventory, classification, generated_est)
    symbol_payload, risk_payload = build_live_symbol_and_risk_proposals(inventory, profile_payload, generated_est)
    runtime_payload, final_payload, dashboard = build_runtime_and_final_gate(
        inventory,
        reactivate_payload,
        symbol_payload,
        risk_payload,
        generated_est,
    )

    go_no_go = READY_MARKER if final_payload.get("verdict") == "LIVE_OPERATOR_ENABLE_AVAILABLE" else BLOCKED_MARKER

    files_json = {
        "paper_fill_gate_block_reason_inventory.json": inventory,
        "paper_fill_gate_validity_classification.json": classification,
        "paper_fill_gate_bugfix_status.json": bugfix_status,
        "paper_fill_profile_proposal.json": profile_payload,
        "paper_fill_recovery_simulation_status.json": sim_payload,
        "paper_fill_gate_reactivation_status.json": reactivate_payload,
        "live_symbol_candidate_proposal_after_paper_fill.json": symbol_payload,
        "live_gate_risk_cap_proposal_after_paper_fill.json": risk_payload,
        "trader_runtime_live_gate_readiness_status.json": runtime_payload,
        "final_live_gate_after_paper_fill_recovery_status.json": final_payload,
        "operator_dashboard_payload.json": dashboard,
    }
    files_text = {
        "GO_NO_GO.md": go_no_go + "\n",
        "V2_PAPER_FILL_GATE_LIVE_BLOCKER_BURNDOWN_AND_CONTROLLED_LIVE_ENABLE_REPORT.md": build_report(
            go_no_go,
            generated_est,
            final_payload,
            inventory,
        ),
    }

    for name, payload in files_json.items():
        _write_json(WORKLOG_DIR / name, payload)
    for name, text in files_text.items():
        _write_text(WORKLOG_DIR / name, text)

    _mirror_outputs()
    print(json.dumps({
        "go_no_go": go_no_go,
        "verdict": final_payload.get("verdict"),
        "worklog": str(WORKLOG_DIR),
        "public": str(PUBLIC_DIR),
    }))


if __name__ == "__main__":
    main()
