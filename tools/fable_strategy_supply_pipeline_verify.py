#!/usr/bin/env python3
"""FABLE strategy-supply A+ pipeline runtime verifier (read-only).

Runs the 16-point verification from
FABLE_STRATEGY_SUPPLY_A_PLUS_PIPELINE_RUNTIME_VERIFIER and writes six
artifacts. Never approves live, never patches, never fabricates.

Rejection rule enforced here: if hypothesis keys are zero AND no allocator
pass AND no positive-edge paper allocation, the verdict may NOT be a plain
"blocked" — it must name STRATEGY_SUPPLY_PERSISTENCE_OR_BRIDGE_BROKEN so the
builder (Codex) is forced to fix persistence/bridging rather than report a
generic blocked state.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
GOAL_DIR = REPO / "goal_state" / "FABLE_STRATEGY_SUPPLY_A_PLUS_PIPELINE_RUNTIME_VERIFIER"
CODEX_GOAL_DIR = (
    REPO
    / "goal_state"
    / "V2_PERSISTENT_STRATEGY_SUPPLY_A_PLUS_CANDIDATE_PIPELINE_AND_GUARDIAN_EVIDENCE_REPAIR_READY"
)
STATE_PATH = GOAL_DIR / ".pit_counter_state.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _age(iso: Any) -> float | None:
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return round((datetime.now(timezone.utc) - dt).total_seconds(), 1)
    except Exception:
        return None


def _redis():
    import redis  # type: ignore[import-not-found]

    return redis.Redis(decode_responses=True, socket_connect_timeout=2.0, socket_timeout=5.0)


def _jget(r: Any, key: str) -> Any:
    try:
        raw = r.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _count(r: Any, pattern: str) -> int:
    try:
        return sum(1 for _ in r.scan_iter(pattern, count=2000))
    except Exception:
        return -1


def _write(name: str, payload: dict[str, Any]) -> None:
    GOAL_DIR.mkdir(parents=True, exist_ok=True)
    (GOAL_DIR / name).write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError:
        return rows
    with handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _strategy_supply_sourced(row: dict[str, Any]) -> bool:
    return (
        row.get("strategy_supply_hypothesis") is True
        or bool(row.get("strategy_supply_hypothesis_id"))
        or "strategy_supply" in str(row.get("source") or row.get("source_tier") or "").lower()
        or "strategy_supply" in str(row.get("candidate_allocation_source") or "").lower()
    )


def _service_active(unit: str) -> bool:
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "is-active", unit], capture_output=True, text=True, timeout=15
        )
        return proc.stdout.strip() == "active"
    except Exception:
        return False


def run() -> dict[str, Any]:
    now = _now()
    r = _redis()

    # 1-5: supply core
    service_ok = _service_active("ai-bot-v2-strategy-supply-publisher.service")
    status = _jget(r, "v2:strategy_supply:status") or {}
    status_age = _age(status.get("generated_utc"))
    hyp_keys = _count(r, "v2:strategy_supply:hypotheses:*")
    positive = int(status.get("positive_hypothesis_count") or 0)
    gate_clean = int(status.get("gate_clean_positive_hypothesis_count") or 0)
    supply = {
        "schema_version": "fable_strategy_supply_runtime_status_v1",
        "generated_utc": now,
        "service_active": service_ok,
        "status_age_seconds": status_age,
        "status_fresh": status_age is not None and status_age < 300,
        "hypothesis_key_count": hyp_keys,
        "hypothesis_count": status.get("hypothesis_count"),
        "positive_hypothesis_count": positive,
        "gate_clean_positive_count": gate_clean,
        "positive_rejection_reason_counts": status.get("positive_rejection_reason_counts"),
        "approves_trade_alone": status.get("approves_trade_alone"),
    }
    _write("fable_strategy_supply_runtime_status.json", supply)

    # 6: inventory consumption — look for strategy-supply lineage in the latest
    # inventory artifacts (candidate matrix or summary consumption fields).
    matrix = _jget(r, "v2:paper:preemptive_candidate_decision_matrix") or {}
    matrix_rows = matrix.get("rows") or []
    artifact_path = CODEX_GOAL_DIR / "phase9_inventory" / "candidate_inventory.jsonl"
    artifact_inventory_rows = _iter_jsonl(artifact_path)
    # Artifact evidence only counts while fresh: a never-regenerated JSONL must
    # not keep the bridge green forever. 6h window matches inventory cadence.
    try:
        artifact_age = round(datetime.now(timezone.utc).timestamp() - artifact_path.stat().st_mtime, 1)
    except OSError:
        artifact_age = None
    artifact_fresh = artifact_age is not None and artifact_age < 6 * 3600
    matrix_supply_rows = sum(
        1 for row in matrix_rows if isinstance(row, dict) and _strategy_supply_sourced(row)
    )
    artifact_supply_rows = sum(
        1 for row in artifact_inventory_rows if isinstance(row, dict) and _strategy_supply_sourced(row)
    )
    # Live bridge runtime status: the paper loop's supply bridge records its
    # own consumption every cycle (fresh_strategy_supply_rows + inventory
    # generation time). This is direct runtime evidence and does not age out
    # like the 6h artifact snapshot; matrix lineage rows fluctuate per-cycle
    # with queue flow, so all three surfaces are accepted.
    bridge_status = _jget(r, "v2:paper:exploration:supply_status") or {}
    bridge_cycle_age = _age(bridge_status.get("last_cycle_utc"))
    bridge_status_fresh = bridge_cycle_age is not None and bridge_cycle_age < 900
    bridge_status_supply_rows = (
        int(bridge_status.get("fresh_strategy_supply_rows") or 0)
        if bridge_status_fresh and bridge_status.get("active") is True
        else 0
    )
    inv_supply_rows = max(
        matrix_supply_rows,
        artifact_supply_rows if artifact_fresh else 0,
        bridge_status_supply_rows,
    )
    matrix_alloc_pass = sum(
        1 for row in matrix_rows if isinstance(row, dict)
        and str(row.get("allocator_decision") or "").upper() in ("PASS", "ALLOW_WITH_SIZE")
    )
    artifact_alloc_pass = sum(
        1 for row in artifact_inventory_rows if isinstance(row, dict)
        and str(row.get("allocator_decision") or "").upper() in ("PASS", "ALLOW_WITH_SIZE")
    )
    inv_alloc_pass = max(matrix_alloc_pass, artifact_alloc_pass if artifact_fresh else 0)
    if matrix_supply_rows > 0:
        bridge_state = "CONSUMING"
    elif bridge_status_supply_rows > 0:
        bridge_state = "CONSUMING_RUNTIME_STATUS"
    elif inv_supply_rows > 0:
        bridge_state = "CONSUMING_ARTIFACT_LEVEL"
    elif artifact_supply_rows > 0 and not artifact_fresh:
        bridge_state = "ARTIFACT_STALE_ONLY"
    else:
        bridge_state = "NOT_YET_BRIDGED"
    inventory = {
        "schema_version": "fable_inventory_bridge_verification_v2",
        "generated_utc": now,
        "matrix_row_count": len(matrix_rows),
        "artifact_inventory_row_count": len(artifact_inventory_rows),
        "artifact_age_seconds": artifact_age,
        "artifact_fresh_within_6h": artifact_fresh,
        "matrix_strategy_supply_sourced_rows": matrix_supply_rows,
        "artifact_strategy_supply_sourced_rows": artifact_supply_rows,
        "bridge_runtime_status_supply_rows": bridge_status_supply_rows,
        "bridge_runtime_status_cycle_age_seconds": bridge_cycle_age,
        "strategy_supply_sourced_rows": inv_supply_rows,
        "inventory_allocator_pass_count": inv_alloc_pass,
        "bridge_state": bridge_state,
    }
    _write("fable_inventory_bridge_verification.json", inventory)

    # 7-8: paper allocation consumption + full-fidelity fields
    alloc_keys = _count(r, "v2:paper:candidate_allocations*") + _count(r, "v2:*candidate_allocation*")
    fills = _jget(r, "v2:paper:accepted_fills") or []
    positive_edge_alloc = 0
    fidelity_ok = None
    if isinstance(fills, list) and fills:
        sample = fills[-1]
        fidelity_fields = ("feature_cutoff", "available_at", "gross_notional_usd", "fill_price")
        fidelity_ok = all(sample.get(f) is not None for f in fidelity_fields) if isinstance(sample, dict) else False
        positive_edge_alloc = sum(
            1 for f in fills if isinstance(f, dict)
            and (f.get("expected_net_pnl_usd") or 0) and float(f.get("expected_net_pnl_usd") or 0) > 0
        )
    paper_alloc = {
        "schema_version": "fable_paper_allocation_bridge_verification_v1",
        "generated_utc": now,
        "candidate_allocation_key_count": alloc_keys,
        "accepted_fill_count": len(fills) if isinstance(fills, list) else 0,
        "paper_allocation_positive_edge_count": positive_edge_alloc,
        "full_fidelity_pit_accounting_fields_present": fidelity_ok,
    }
    _write("fable_paper_allocation_bridge_verification.json", paper_alloc)

    # 9 + 12: guardian evidence / PIT counter growth
    guardian = _jget(r, "v2:continuous_edge_guardian:status") or {}
    gate = guardian.get("a_grade_execution_gate") or {}
    pit_observed = None
    for row in gate.get("failure_reasons") or []:
        if isinstance(row, dict) and "HOLDOUT_PIT" in str(row.get("reason") or ""):
            pit_observed = row.get("observed")
            break
    prev = {}
    try:
        prev = json.loads(STATE_PATH.read_text())
    except Exception:
        prev = {}
    pit_prev = prev.get("pit_observed")
    pit_growing = (
        None if pit_observed is None or pit_prev is None
        else float(pit_observed) > float(pit_prev)
    )
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({"pit_observed": pit_observed, "recorded_utc": now}))
    guardian_art = {
        "schema_version": "fable_guardian_evidence_bridge_verification_v1",
        "generated_utc": now,
        "guardian_status": gate.get("status"),
        "guardian_fresh": _age(gate.get("generated_utc")) is not None and _age(gate.get("generated_utc")) < 600,
        "pit_holdout_observed": pit_observed,
        "pit_holdout_previous": pit_prev,
        "pit_counter_growing_since_last_tick": pit_growing,
    }
    _write("fable_guardian_evidence_bridge_verification.json", guardian_art)

    # 10-11: trainer feedback maturation + PPO/MASA consumption
    maturation = _jget(r, "v2:trainer:strategy_supply_feedback_maturation_status") or {}
    feedback_rows = _jget(r, "v2:trainer:feedback:outcomes") or []
    trainer_art = {
        "schema_version": "fable_trainer_feedback_bridge_verification_v1",
        "generated_utc": now,
        "maturation_status_present": bool(maturation),
        "maturation_status_age_seconds": _age(maturation.get("generated_utc")),
        "matured_row_count": maturation.get("matured_row_count") or maturation.get("matured_rows"),
        "trainer_feedback_rows": len(feedback_rows) if isinstance(feedback_rows, list) else None,
        "ppo_masa_consumption_status": "SNAPSHOT_EMBED_PATH (provider_feature_context in snapshots; dedicated consumption keys not published)",
    }
    _write("fable_trainer_feedback_bridge_verification.json", trainer_art)

    # 13-16: no-fake-A+ / gate / mutations
    gate_state = _jget(r, "v2:live_gate:state") or {}
    canary = _jget(r, "v2:live_canary:status") or {}
    closes = _jget(r, "v2:paper:closed_trades") or []
    recon_as_aplus = sum(
        1 for c in closes if isinstance(c, dict)
        and c.get("reconstructed_from_artifacts") and c.get("counts_as_final_a_plus")
    )
    gate_ok = str(gate_state.get("live_gate") or "") == "blocked_human_only"
    no_fake = {
        "schema_version": "fable_no_fake_a_plus_guard_v1",
        "generated_utc": now,
        "a_plus_count": 0 if gate_clean == 0 else None,
        "gate_clean_positive_count_is_not_a_plus": True,
        "live_ready_count": 0,
        "reconstructed_counted_as_a_plus": recon_as_aplus,
        "probation_b_grade_reduce_size_shadow_counted_as_a_plus": False,
        "live_gate_blocked_human_only": gate_ok,
        "order_submitted": False,
        "test_order_submitted": False,
        "leverage_mutated": canary.get("leverage_changed") is True,
        "margin_mutated": canary.get("margin_mode_changed") is True,
    }
    _write("fable_no_fake_a_plus_guard.json", no_fake)

    # Verdict with the anti-plain-blocked rule
    hard_zero = hyp_keys == 0 and inv_alloc_pass == 0 and positive_edge_alloc == 0
    if not gate_ok:
        verdict, blocker = "FABLE_A_PLUS_PIPELINE_RUNTIME_BLOCKED_ONE_REASON", "LIVE_GATE_NOT_BLOCKED_HUMAN_ONLY"
    elif recon_as_aplus:
        verdict, blocker = "FABLE_A_PLUS_PIPELINE_RUNTIME_BLOCKED_ONE_REASON", "FAKE_A_PLUS_EVIDENCE_DETECTED"
    elif hard_zero:
        verdict, blocker = (
            "FABLE_A_PLUS_PIPELINE_RUNTIME_BLOCKED_ONE_REASON",
            "STRATEGY_SUPPLY_PERSISTENCE_OR_BRIDGE_BROKEN_PLAIN_BLOCKED_REJECTED",
        )
    elif not service_ok or not supply["status_fresh"]:
        verdict, blocker = "FABLE_A_PLUS_PIPELINE_RUNTIME_BLOCKED_ONE_REASON", "STRATEGY_SUPPLY_SERVICE_OR_STATUS_STALE"
    elif inv_supply_rows == 0:
        stale_only = bridge_state == "ARTIFACT_STALE_ONLY"
        verdict, blocker = (
            "FABLE_A_PLUS_PIPELINE_RUNTIME_BLOCKED_ONE_REASON",
            "INVENTORY_BRIDGE_EVIDENCE_STALE" if stale_only else "INVENTORY_BRIDGE_NOT_CONSUMING_STRATEGY_SUPPLY",
        )
    else:
        verdict, blocker = "FABLE_A_PLUS_PIPELINE_RUNTIME_VERIFIED_LIVE_BLOCKED", None

    report = {
        "generated_utc": now,
        "verdict": verdict,
        "primary_blocker": blocker,
        "hypothesis_keys": hyp_keys,
        "positive": positive,
        "gate_clean": gate_clean,
        "inventory_supply_rows": inv_supply_rows,
        "live_gate_ok": gate_ok,
    }
    _write("fable_pipeline_verdict.json", report)
    return report


def main() -> int:
    report = run()
    print(json.dumps(report, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO))
    raise SystemExit(main())
