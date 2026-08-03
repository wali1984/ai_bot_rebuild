"""V2-owned non-live startup worker (paper-only).

Coordinates the V2 paper-only stack and verifies each component
is present and paper-only:

- native ingestors classification
- native feature pipeline trainer snapshot
- native RL core trainer output (P0.2F)
- orchestrator arbitration
- trade management paper engine
- risk gateway (read-only check that legacy gateway is bound)
- paper execution stub
- shadow outcome observer present

Emits a public payload at
v2/frontend/public/operator_runtime/v2_owned_non_live_startup/latest/
v2_owned_non_live_startup_status.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from v2.backend.app.services.market_state_integrity.trust import TrustGateRejectedError
from v2.backend.app.services.native_ingestors import (
    classify_all_ingestors,
    ingestors_invariants_snapshot,
)
from v2.backend.app.services.rl_core.trainer_output import (
    emit_trainer_output,
    trainer_output_invariants_snapshot,
    validate_for_paper_fill_gate,
)
from v2.backend.app.services.trade_management_paper.service import (
    TradeManagementPaperService,
)

DEFAULT_PAYLOAD_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_owned_non_live_startup/latest/v2_owned_non_live_startup_status.json"
)
DEFAULT_NATIVE_SNAPSHOT_PATH = Path(
    "v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json"
)
DEFAULT_ORCHESTRATOR_STATUS_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_orchestrator_arbitration/latest/v2_orchestrator_arbitration_status.json"
)
DEFAULT_TRADE_MGMT_STATUS_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_trade_management_paper/latest/v2_trade_management_paper_status.json"
)
DEFAULT_RL_CORE_STATUS_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_rl_core/latest/v2_rl_core_status.json"
)
DEFAULT_INGESTORS_STATUS_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_native_ingestors/latest/v2_native_ingestors_status.json"
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(p: Path) -> dict | None:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (ValueError, OSError):
        return None


def build_payload() -> dict:
    components: list[dict] = []
    ingestors_invariants = ingestors_invariants_snapshot()

    # native ingestors
    ing_records = classify_all_ingestors()
    ing_status = _read_json(DEFAULT_INGESTORS_STATUS_PATH)
    components.append({
        "component": "native_ingestors",
        "status": "PRESENT" if ing_records else "MISSING",
        "public_payload_present": ing_status is not None,
        "live_gate_field": ingestors_invariants.get("live_gate"),
        "approves_live_field": ingestors_invariants.get("approves_live"),
        "count_or_size": len(ing_records),
    })

    # native feature pipeline snapshot
    snap = _read_json(DEFAULT_NATIVE_SNAPSHOT_PATH)
    components.append({
        "component": "native_feature_pipeline_snapshot",
        "status": "PRESENT" if snap else "MISSING",
        "feature_snapshot_id": (snap or {}).get("feature_snapshot_id"),
        "trainer_consumable": (snap or {}).get("trainer_consumable"),
        "live_gate_field": (snap or {}).get("live_gate"),
        "approves_live_field": (snap or {}).get("approves_live"),
    })

    # native RL core trainer output (PRESENT means the trainer output ran
    # and emitted a record; the paper fill gate decision is reported
    # separately and can be BLOCKED while the component is healthy)
    if snap is not None:
        try:
            rec = emit_trainer_output(snap)
            gate = validate_for_paper_fill_gate(rec)
            rl_core_summary = {
                "trainer_source": rec.trainer_source,
                "feature_snapshot_id": rec.feature_snapshot_id,
                "checkpoint_blocker": rec.checkpoint_blocker,
                "expected_move_bps": rec.expected_move_bps,
                "expected_move_after_cost_bps": rec.expected_move_after_cost_bps,
                "confidence_calibrated": rec.confidence_calibrated,
                "feature_freshness_state": rec.feature_freshness_state,
                "paper_fill_gate_status": gate["paper_fill_gate_status"],
                "paper_fill_allowed": gate["paper_fill_allowed"],
                "paper_fill_gate_block_reasons": list(gate["paper_fill_gate_block_reasons"]),
            }
            components.append({
                "component": "native_rl_core_trainer_output",
                "status": "PRESENT",
                "summary": rl_core_summary,
            })
        except TrustGateRejectedError as exc:
            components.append({
                "component": "native_rl_core_trainer_output",
                "status": "BLOCKED_TRUST_GATE",
                "summary": {
                    "paper_fill_gate_status": "BLOCKED_BY_TRUST_GATE",
                    "paper_fill_allowed": False,
                    "paper_fill_gate_block_reasons": list(exc.trust_gate_result.reject_reasons),
                    "trust_gate_decision_id": exc.decision_id,
                },
            })
    else:
        components.append({
            "component": "native_rl_core_trainer_output",
            "status": "MISSING_DUE_TO_SNAPSHOT_ABSENT",
            "summary": {},
        })

    # orchestrator arbitration
    orch = _read_json(DEFAULT_ORCHESTRATOR_STATUS_PATH)
    components.append({
        "component": "orchestrator_arbitration",
        "status": "PRESENT" if orch else "MISSING",
        "live_gate_field": (orch or {}).get("live_gate"),
        "approves_live_field": (orch or {}).get("approves_live"),
        "cannot_bypass_risk_gateway": (orch or {}).get("cannot_bypass_risk_gateway"),
        "considered_count": (orch or {}).get("arbitration_considered_count"),
    })

    # trade management paper
    tm = _read_json(DEFAULT_TRADE_MGMT_STATUS_PATH)
    components.append({
        "component": "trade_management_paper",
        "status": "PRESENT" if tm else "MISSING",
        "live_gate_field": (tm or {}).get("live_gate"),
        "approves_live_field": (tm or {}).get("approves_live"),
    })

    # risk gateway (binding check via orchestrator field)
    components.append({
        "component": "risk_gateway",
        "status": "BINDING_PER_ORCHESTRATOR_PAYLOAD"
        if (orch or {}).get("cannot_bypass_risk_gateway") is True
        else "STATUS_UNKNOWN",
        "binding_classification": "risk_gateway_is_binding_gate_orchestrator_only_proposes",
    })

    # paper execution + shadow outcome observer (verified by file presence
    # of the existing public payloads)
    paper_exec = Path("v2/frontend/public/operator_runtime/v2_paper_execution_worker/latest").exists()
    shadow = Path("v2/frontend/public/operator_runtime/paper_shadow_outcome_observer/latest").exists()
    components.append({
        "component": "paper_execution",
        "status": "PRESENT" if paper_exec else "MISSING",
    })
    components.append({
        "component": "shadow_outcome_observer",
        "status": "PRESENT" if shadow else "MISSING",
    })

    # rl core public payload check (P0.2A/B/C ground truth)
    rl_core_status = _read_json(DEFAULT_RL_CORE_STATUS_PATH)
    components.append({
        "component": "rl_core_status_public_payload",
        "status": "PRESENT" if rl_core_status else "MISSING",
        "live_gate_field": (rl_core_status or {}).get("live_gate"),
        "approves_live_field": (rl_core_status or {}).get("approves_live"),
        "p0_2b_policy_forward_included": "p0_2b_policy_forward" in (rl_core_status or {}),
        "p0_2a_rollout_included": "p0_2a_rollout" in (rl_core_status or {}),
    })

    all_present_or_binding = all(
        c["status"]
        in (
            "PRESENT",
            "BINDING_PER_ORCHESTRATOR_PAYLOAD",
        )
        for c in components
    )
    any_live_field_unsafe = any(
        c.get("live_gate_field") not in (None, "blocked_human_only")
        or (c.get("approves_live_field") not in (None, False))
        for c in components
    )

    payload = {
        "worker_id": "v2_owned_non_live_startup",
        "schema_version": "v2_owned_non_live_startup_v1",
        "scope": "PAPER_ONLY_NATIVE_STACK_VERIFICATION",
        "components": components,
        "all_components_present_or_binding": all_present_or_binding,
        "any_unsafe_live_field": any_live_field_unsafe,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "go_no_go": (
            "V2_OWNED_NON_LIVE_STARTUP_READY"
            if all_present_or_binding and not any_live_field_unsafe
            else "V2_OWNED_NON_LIVE_STARTUP_BLOCKED"
        ),
        "missing_components": [c["component"] for c in components if c["status"] not in ("PRESENT", "BINDING_PER_ORCHESTRATOR_PAYLOAD")],
        "trainer_output_invariants": trainer_output_invariants_snapshot(),
        "ingestors_invariants": ingestors_invariants,
        "generated_utc": _utc_iso(),
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_owned_non_live_startup")
    parser.add_argument("--write-evidence", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--require-paper-only",
        action="store_true",
        help="Exit non-zero if any unsafe live field is detected.",
    )
    args = parser.parse_args(argv)
    payload = build_payload()
    if args.require_paper_only and payload.get("any_unsafe_live_field"):
        print(f"SAFETY_INVARIANT_VIOLATION: unsafe_live_field detected: "
              f"{payload}", file=sys.stderr)
        return 2
    out_text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.dry_run and args.write_evidence:
        print("ERROR: --dry-run and --write-evidence are mutually exclusive", file=sys.stderr)
        return 2
    if args.write_evidence:
        dest = args.out or DEFAULT_PAYLOAD_PATH
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(out_text)
        print(f"v2_owned_non_live_startup_status_written path={dest} go_no_go={payload['go_no_go']}")
        return 0
    print(out_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
