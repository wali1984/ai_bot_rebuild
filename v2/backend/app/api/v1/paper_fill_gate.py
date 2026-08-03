"""`/paper-fill-gate/` — read-only paper fill gate diagnostic surface.

Serves the burndown CLI output artifacts for the website dashboard.
Routes:
  GET /paper-fill-gate/status          — operator dashboard summary
  GET /paper-fill-gate/inventory       — phase 1 block-reason inventory
  GET /paper-fill-gate/classification  — phase 2 validity classification
  GET /paper-fill-gate/bugfix-status   — phase 3 bug fix status
  GET /paper-fill-gate/profile         — phase 4 paper-fill profile proposal
  GET /paper-fill-gate/simulation      — phase 5 recovery simulation
  GET /paper-fill-gate/reactivation    — phase 6 reactivation status
  GET /paper-fill-gate/live-symbols    — phase 7 live-symbol candidate proposal
  GET /paper-fill-gate/risk-caps       — phase 8 risk cap proposal
  GET /paper-fill-gate/runtime         — phase 9 trader runtime readiness
  GET /paper-fill-gate/final-gate      — phase 10 final live gate evaluation
  POST /paper-fill-gate/run-burndown   — trigger one burndown CLI pass (read-only)

Hard constraints (same as live-gate):
- No real orders, no test-order, no leverage/margin mutation.
- No legacy Redis write, no Redis trim.
- Live gate stays blocked unless runtime gates independently pass.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/paper-fill-gate", tags=["paper-fill-gate"])

ROUTE_METADATA: dict[str, Any] = {
    "group": "paper_fill_gate",
    "prefix": "/paper-fill-gate",
    "endpoints": (
        "/status", "/inventory", "/classification", "/bugfix-status",
        "/profile", "/simulation", "/reactivation", "/live-symbols",
        "/risk-caps", "/runtime", "/final-gate", "/run-burndown",
    ),
    "rbac": "read",
    "default_deny_execution": True,
    "live_gate": "blocked_human_only",
    "places_real_order": False,
}

_REPO_ROOT_ENV = "V2_REPO_ROOT"
_ARTIFACT_REL = Path(
    "v2/frontend/public"
    "/v2_paper_fill_gate_live_blocker_burndown_and_controlled_live_enable_ready"
    "/latest"
)

_ARTIFACT_FILES = {
    "status": "operator_dashboard_payload.json",
    "inventory": "paper_fill_gate_block_reason_inventory.json",
    "classification": "paper_fill_gate_validity_classification.json",
    "bugfix-status": "paper_fill_gate_bugfix_status.json",
    "profile": "paper_fill_profile_proposal.json",
    "simulation": "paper_fill_recovery_simulation_status.json",
    "reactivation": "paper_fill_gate_reactivation_status.json",
    "live-symbols": "live_symbol_candidate_proposal_after_paper_fill.json",
    "risk-caps": "live_gate_risk_cap_proposal_after_paper_fill.json",
    "runtime": "trader_runtime_live_gate_readiness_status.json",
    "final-gate": "final_live_gate_after_paper_fill_recovery_status.json",
}


def _repo_root() -> Path:
    return Path(os.environ.get(_REPO_ROOT_ENV, "/home/wali/Desktop/AI BOT REBUILD")).resolve()


def _read_artifact(name: str) -> dict[str, Any]:
    filename = _ARTIFACT_FILES.get(name)
    if not filename:
        raise HTTPException(status_code=404, detail=f"Unknown artifact: {name}")
    path = _repo_root() / _ARTIFACT_REL / filename
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {
            "status": "ARTIFACT_NOT_YET_GENERATED",
            "artifact": filename,
            "hint": "POST /paper-fill-gate/run-burndown to generate",
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "execution_live_symbols": [],
            "places_real_order": False,
        }
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        raise HTTPException(status_code=500, detail=f"Artifact parse error: {filename}")


@router.options("/", include_in_schema=False)
async def _route_metadata() -> dict[str, Any]:
    return ROUTE_METADATA


@router.get("/status")
async def get_paper_fill_gate_status() -> dict[str, Any]:
    """Operator dashboard summary — all 12-phase aggregate output."""
    payload = _read_artifact("status")
    # Always enforce fail-closed fields
    payload.setdefault("live_gate", "blocked_human_only")
    payload.setdefault("live_symbols", [])
    payload.setdefault("execution_live_symbols", [])
    payload.setdefault("places_real_order", False)
    return payload


@router.get("/inventory")
async def get_block_reason_inventory() -> dict[str, Any]:
    """Phase 1 — block reason inventory for all held decisions."""
    return _read_artifact("inventory")


@router.get("/classification")
async def get_gate_validity_classification() -> dict[str, Any]:
    """Phase 2 — valid/overstrict/bug classification per held decision."""
    return _read_artifact("classification")


@router.get("/bugfix-status")
async def get_bugfix_status() -> dict[str, Any]:
    """Phase 3 — bug fix status and remediation tasks."""
    return _read_artifact("bugfix-status")


@router.get("/profile")
async def get_paper_fill_profile() -> dict[str, Any]:
    """Phase 4 — paper-fill profile proposals (conservative/balanced/aggressive)."""
    return _read_artifact("profile")


@router.get("/simulation")
async def get_recovery_simulation() -> dict[str, Any]:
    """Phase 5 — paper-fill recovery simulation across profile variants."""
    return _read_artifact("simulation")


@router.get("/reactivation")
async def get_reactivation_status() -> dict[str, Any]:
    """Phase 6 — controlled paper-fill reactivation status."""
    return _read_artifact("reactivation")


@router.get("/live-symbols")
async def get_live_symbol_candidates() -> dict[str, Any]:
    """Phase 7 — live-symbol candidate proposal (operator acceptance required)."""
    payload = _read_artifact("live-symbols")
    payload.setdefault("operator_acceptance_required", True)
    payload.setdefault("live_symbols_written", [])
    payload.setdefault("execution_live_symbols_written", [])
    return payload


@router.get("/risk-caps")
async def get_risk_cap_proposal() -> dict[str, Any]:
    """Phase 8 — risk cap profile proposals (operator acceptance required)."""
    payload = _read_artifact("risk-caps")
    payload.setdefault("auto_accept", False)
    payload.setdefault("operator_acceptance_required", True)
    return payload


@router.get("/runtime")
async def get_trader_runtime_readiness() -> dict[str, Any]:
    """Phase 9 — trader runtime live gate readiness status."""
    return _read_artifact("runtime")


@router.get("/final-gate")
async def get_final_live_gate() -> dict[str, Any]:
    """Phase 10 — final live gate evaluation after paper fill recovery."""
    payload = _read_artifact("final-gate")
    payload.setdefault("live_gate", "blocked_human_only")
    payload.setdefault("live_symbols", [])
    payload.setdefault("execution_live_symbols", [])
    return payload


@router.post("/run-burndown")
async def run_burndown() -> dict[str, Any]:
    """Trigger one read-only burndown CLI pass.

    Reads Redis state, builds all 12 phase outputs, writes to public dir.
    Does NOT place orders, does NOT mutate exchange, does NOT change live gate.
    """
    repo_root = _repo_root()
    cli_module = (
        "v2.backend.app.cli"
        ".v2_paper_fill_gate_live_blocker_burndown_and_controlled_live_enable_ready"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-m", cli_module],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(repo_root),
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=503, detail="BURNDOWN_CLI_TIMEOUT_60S")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"BURNDOWN_CLI_LAUNCH_ERROR:{exc}")

    stdout = result.stdout.strip() if result.stdout else ""
    stderr = result.stderr.strip() if result.stderr else ""

    summary: dict[str, Any] = {
        "exit_code": result.returncode,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "execution_live_symbols": [],
        "places_real_order": False,
        "no_exchange_mutation": True,
        "no_legacy_redis_write": True,
        "no_redis_trim": True,
    }
    if stdout:
        try:
            parsed = json.loads(stdout)
            summary.update(parsed)
        except (ValueError, TypeError):
            summary["cli_stdout_raw"] = stdout[:512]
    if stderr:
        summary["cli_stderr"] = stderr[:512]
    if result.returncode != 0:
        summary["status"] = "BURNDOWN_CLI_NONZERO_EXIT"
    else:
        summary["status"] = "BURNDOWN_COMPLETE"
    # Always enforce gate invariants
    summary["live_gate"] = "blocked_human_only"
    summary["live_symbols"] = []
    summary["execution_live_symbols"] = []
    summary["places_real_order"] = False
    return summary
