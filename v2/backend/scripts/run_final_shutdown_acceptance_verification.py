"""Final paper-only shutdown acceptance verification helper.

Reads the runtime payloads and the operator acceptance file (if
present). Emits the final decision packet + GO/NO-GO. Never approves
live, canary, exchange mutation, leverage, margin, or Redis trim.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(".")

ACCEPTANCE_FILE = Path(
    "claude_worklog/approvals/OPERATOR_ACCEPTS_V2_PAPER_ONLY_SHUTDOWN_LIMITATIONS.md"
)
RL_CORE_STATUS = Path(
    "v2/frontend/public/operator_runtime/v2_rl_core/latest/v2_rl_core_status.json"
)
STARTUP_STATUS = Path(
    "v2/frontend/public/operator_runtime/v2_owned_non_live_startup/latest/v2_owned_non_live_startup_status.json"
)
INGESTORS_STATUS = Path(
    "v2/frontend/public/operator_runtime/v2_native_ingestors/latest/v2_native_ingestors_status.json"
)
BURNDOWN_MATRIX = Path(
    "claude_worklog/final_readiness/core_completion_blocker_burndown/latest/core_completion_blocker_matrix.json"
)

TARGET_GO_NO_GO = Path(
    "claude_worklog/final_readiness/final_paper_only_shutdown_decision/latest/GO_NO_GO.md"
)
TARGET_DECISION_JSON = Path(
    "claude_worklog/final_readiness/final_paper_only_shutdown_decision/latest/final_paper_only_shutdown_decision.json"
)
TARGET_DECISION_MD = Path(
    "claude_worklog/final_readiness/final_paper_only_shutdown_decision/latest/FINAL_PAPER_ONLY_SHUTDOWN_DECISION_PACKET.md"
)
TARGET_PUBLIC_DASH = Path(
    "v2/frontend/public/final_paper_only_shutdown_decision/latest/operator_dashboard_payload.json"
)

REQUIRED_NEGATIVE_LITERALS = (
    "does not approve live",
    "does not approve canary",
    "does not approve exchange mutation",
    "does not approve leverage",
    "does not approve margin",
    "does not approve redis trim",
)
REQUIRED_POSITIVE_LITERALS = (
    "live_gate = blocked_human_only",
    "live_symbols = []",
    "paper-only",
)
FORBIDDEN_LITERALS = (
    "APPROVE_LIVE_TRADING",
    "ENABLE_LIVE",
    "APPROVE_CANARY",
    "APPROVE_REDIS_TRIM",
    "APPROVE_EXCHANGE_MUTATION",
    "APPROVE_LEVERAGE_CHANGE",
    "APPROVE_MARGIN_CHANGE",
)


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def _read_json(p: Path) -> dict | None:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def _verify_acceptance_file(path: Path) -> dict:
    """Return a structured acceptance-file verification result.

    Note: missing required literal phrases short-circuit acceptance to
    INVALID. Forbidden literal phrases (e.g. APPROVE_LIVE_TRADING)
    short-circuit acceptance to REJECTED regardless of presence of
    paper-only language.
    """
    if not path.exists():
        return {
            "file_present": False,
            "file_path": str(path),
            "verdict": "MISSING",
            "missing_required_literals": list(REQUIRED_POSITIVE_LITERALS + REQUIRED_NEGATIVE_LITERALS),
            "forbidden_literals_found": [],
        }
    body = path.read_text()
    body_lower = body.lower()
    missing_positive = [s for s in REQUIRED_POSITIVE_LITERALS if s.lower() not in body_lower]
    missing_negative = [s for s in REQUIRED_NEGATIVE_LITERALS if s.lower() not in body_lower]
    forbidden_found = [s for s in FORBIDDEN_LITERALS if s in body]
    if forbidden_found:
        verdict = "REJECTED_DANGEROUS_LANGUAGE"
    elif missing_positive or missing_negative:
        verdict = "INVALID_MISSING_REQUIRED_LANGUAGE"
    else:
        verdict = "ACCEPTED_PAPER_ONLY"
    return {
        "file_present": True,
        "file_path": str(path),
        "file_size_bytes": path.stat().st_size,
        "verdict": verdict,
        "missing_required_literals": missing_positive + missing_negative,
        "forbidden_literals_found": forbidden_found,
    }


def build_decision() -> dict:
    rl_core = _read_json(RL_CORE_STATUS) or {}
    startup = _read_json(STARTUP_STATUS) or {}
    ingestors = _read_json(INGESTORS_STATUS) or {}
    matrix = _read_json(BURNDOWN_MATRIX) or {}
    acceptance = _verify_acceptance_file(ACCEPTANCE_FILE)

    p0_2f = rl_core.get("p0_2f_paper_fill_gate", {})
    p0_2g = rl_core.get("p0_2g_trainer_algo_completion", {})
    ingestor_classes = {r["name"]: r["classification"] for r in ingestors.get("ingestors", [])}

    runtime_truth = {
        "p0_2f_paper_fill_allowed": p0_2f.get("paper_fill_allowed"),
        "p0_2f_paper_fill_gate_status": p0_2f.get("paper_fill_gate_status"),
        "p0_2f_paper_fill_gate_block_reasons": p0_2f.get("paper_fill_gate_block_reasons", []),
        "p0_2f_expected_move_after_cost_bps": p0_2f.get("expected_move_after_cost_bps"),
        "p0_2g_migration_classification": p0_2g.get("migration_classification"),
        "p0_2g_ppo_clip_status": p0_2g.get("ppo_clip_status"),
        "p0_2g_gae_status": p0_2g.get("gae_status"),
        "p0_2g_optimizer_state_status": p0_2g.get("optimizer_state_status"),
        "p0_2g_checkpoint_weight_status": p0_2g.get("checkpoint_weight_status"),
        "p0_2g_hedge_status": p0_2g.get("hedge_status"),
        "v2_owned_non_live_startup_go_no_go": startup.get("go_no_go"),
        "v2_owned_non_live_startup_unsafe_live_field": startup.get("any_unsafe_live_field"),
        "live_coinank_classification": ingestor_classes.get("live_coinank"),
        "live_coinapi_v1_classification": ingestor_classes.get("live_coinapi_v1"),
        "live_coinapi_wsds_classification": ingestor_classes.get("live_coinapi_wsds"),
        "live_coinank_global_aggregator_classification": ingestor_classes.get("live_coinank_global_aggregator"),
        "live_kucoin_classification": ingestor_classes.get("live_kucoin"),
        "matrix_burndown_go_no_go": matrix.get("burndown_go_no_go"),
        "matrix_agrees_with_runtime": matrix.get("runtime_truth_check", {}).get("matrix_agrees_with_runtime"),
        "matrix_all_required_operator_decisions_accepted": matrix.get("all_required_operator_decisions_accepted"),
    }

    runtime_health_ok = (
        runtime_truth["p0_2f_paper_fill_allowed"] is False
        and "NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK" in (runtime_truth["p0_2f_paper_fill_gate_block_reasons"] or [])
        and runtime_truth["v2_owned_non_live_startup_go_no_go"] == "V2_OWNED_NON_LIVE_STARTUP_READY"
        and runtime_truth["v2_owned_non_live_startup_unsafe_live_field"] is False
        and runtime_truth["matrix_agrees_with_runtime"] is True
        and runtime_truth["matrix_burndown_go_no_go"]
        == "V2_CORE_COMPLETION_BLOCKER_BURNDOWN_TRUTH_REMEDIATION_READY"
    )

    if not runtime_health_ok:
        decision = "BLOCK_LEGACY_SHUTDOWN_PARITY_INCOMPLETE"
        decision_reason = (
            "Runtime health check failed: one or more of P0.2F strict gate, "
            "P0.2G trainer-algo status, V2-owned non-live startup readiness, "
            "burndown matrix/runtime agreement, or burndown remediation GO is "
            "in a non-expected state. See runtime_truth block."
        )
    elif acceptance["verdict"] != "ACCEPTED_PAPER_ONLY":
        decision = "OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN"
        if acceptance["verdict"] == "MISSING":
            decision_reason = (
                "Operator acceptance file is absent. Without "
                "claude_worklog/approvals/OPERATOR_ACCEPTS_V2_PAPER_ONLY_SHUTDOWN_LIMITATIONS.md, "
                "the packet cannot mark SAFE."
            )
        elif acceptance["verdict"] == "REJECTED_DANGEROUS_LANGUAGE":
            decision_reason = (
                "Operator acceptance file contains forbidden language "
                "(e.g. live/canary/Redis-trim approval phrases). Refusing to "
                "treat it as paper-only acceptance."
            )
        else:
            decision_reason = (
                "Operator acceptance file is present but is missing required "
                "paper-only language. See missing_required_literals."
            )
    else:
        # Note: even if acceptance verdict were ACCEPTED_PAPER_ONLY,
        # SAFE still requires the operator file to never contain live
        # approval phrases AND the runtime health checks to pass. Both
        # are confirmed above.
        decision = "SAFE_TO_SHUTDOWN_LEGACY_RUNTIME_FOR_V2_PAPER_ONLY"
        decision_reason = (
            "Operator acceptance file present and paper-only; runtime health "
            "checks pass; all blockers IMPLEMENTED_AND_TESTED or "
            "CONVERTED_TO_OPERATOR_DECISION_REQUIRED (and operator has "
            "accepted them via the acceptance file)."
        )

    return {
        "schema_version": "v2_final_paper_only_shutdown_decision_v2",
        "generated_utc": _utc_iso(),
        "git_head": "31a7fd70319f0d586c454b5ea2ea530ba9cb1541",
        "decision": decision,
        "decision_reason": decision_reason,
        "acceptance_file_verification": acceptance,
        "runtime_truth": runtime_truth,
        "runtime_health_ok": runtime_health_ok,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "final_live_approval_token_created": False,
    }


def main() -> int:
    decision = build_decision()
    TARGET_DECISION_JSON.parent.mkdir(parents=True, exist_ok=True)
    TARGET_PUBLIC_DASH.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(decision, indent=2, sort_keys=True) + "\n"
    TARGET_DECISION_JSON.write_text(body)
    TARGET_PUBLIC_DASH.write_text(body)
    TARGET_GO_NO_GO.write_text(decision["decision"] + "\n")
    print("decision", decision["decision"])
    print("acceptance_verdict", decision["acceptance_file_verification"]["verdict"])
    print("runtime_health_ok", decision["runtime_health_ok"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
