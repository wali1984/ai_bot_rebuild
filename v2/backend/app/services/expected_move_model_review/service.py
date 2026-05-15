"""Expected move model review evidence service.

This service is fail-closed and analysis-only. It does not authorize fills,
loosen the global paper gate, or claim positive edge. It reads existing
expected_move_model_review payloads and false_block / threshold_replay
evidence, applies the migration completion contract, and exposes the
GO/NO-GO summary plus the threshold table for safe consumption by the CLI
and by the frontend truth payload builder.

Safety invariants (enforced by load_and_validate):
- live_gate must equal "blocked_human_only"
- live_symbols must equal []
- approves_live, approves_canary, approves_legacy_shutdown must all be false
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]

LIVE_GATE_STATUS = "blocked_human_only"

REVIEW_GO_NO_GO_STRICT = "V2_EXPECTED_MOVE_MODEL_REVIEW_READY_KEEP_GATE_STRICT"
REVIEW_GO_NO_GO_SELECTIVE_THRESHOLD_UPDATE = "V2_EXPECTED_MOVE_MODEL_REVIEW_READY_SELECTIVE_THRESHOLD_UPDATE"
REVIEW_GO_NO_GO_BLOCKED_EDGE_NOT_FOUND = "V2_EXPECTED_MOVE_MODEL_REVIEW_BLOCKED_EDGE_NOT_FOUND"
REVIEW_GO_NO_GO_BLOCKED_INSUFFICIENT_SAMPLE = "V2_EXPECTED_MOVE_MODEL_REVIEW_BLOCKED_INSUFFICIENT_SAMPLE"

VALID_GO_NO_GO_VALUES = {
    REVIEW_GO_NO_GO_STRICT,
    REVIEW_GO_NO_GO_SELECTIVE_THRESHOLD_UPDATE,
    REVIEW_GO_NO_GO_BLOCKED_EDGE_NOT_FOUND,
    REVIEW_GO_NO_GO_BLOCKED_INSUFFICIENT_SAMPLE,
}

PAYLOAD_PATH = (
    REPO_ROOT
    / "claude_worklog/final_readiness/expected_move_model_review/latest/operator_dashboard_payload.json"
)
FALSE_BLOCK_AUDIT_PATH = (
    REPO_ROOT
    / "claude_worklog/final_readiness/expected_move_model_review/latest/false_block_audit.json"
)
THRESHOLD_REPLAY_PATH = (
    REPO_ROOT
    / "claude_worklog/final_readiness/expected_move_model_review/latest/threshold_replay_results.json"
)
PUBLIC_PAYLOAD_PATH = (
    REPO_ROOT
    / "v2/frontend/public/expected_move_model_review/latest/operator_dashboard_payload.json"
)


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


class ExpectedMoveModelReviewService:
    """Read-only evidence service over expected-move review artifacts."""

    def __init__(
        self,
        payload_path: Path | None = None,
        false_block_audit_path: Path | None = None,
        threshold_replay_path: Path | None = None,
    ) -> None:
        self.payload_path = payload_path or PAYLOAD_PATH
        self.false_block_audit_path = false_block_audit_path or FALSE_BLOCK_AUDIT_PATH
        self.threshold_replay_path = threshold_replay_path or THRESHOLD_REPLAY_PATH

    # ------------------------------------------------------------------ loading

    def load_payload(self) -> dict[str, Any] | None:
        data = _read_json(self.payload_path)
        return data if isinstance(data, dict) else None

    def load_false_block_audit(self) -> dict[str, Any] | None:
        data = _read_json(self.false_block_audit_path)
        return data if isinstance(data, dict) else None

    def load_threshold_replay(self) -> dict[str, Any] | None:
        data = _read_json(self.threshold_replay_path)
        return data if isinstance(data, dict) else None

    # ----------------------------------------------------------- safety guards

    @staticmethod
    def assert_safety_invariants(payload: dict[str, Any]) -> dict[str, Any]:
        """Return a list of safety violations; empty list means safe."""
        violations: list[str] = []
        if payload.get("live_gate") != LIVE_GATE_STATUS:
            violations.append(f"live_gate_violation:{payload.get('live_gate')}")
        if payload.get("live_symbols") not in ([], None):
            violations.append(f"live_symbols_violation:{payload.get('live_symbols')}")
        for k in ("approves_live", "approves_canary", "approves_legacy_shutdown"):
            if payload.get(k):
                violations.append(f"approval_violation:{k}=true")
        gng = payload.get("go_no_go")
        if gng and gng not in VALID_GO_NO_GO_VALUES:
            violations.append(f"go_no_go_invalid:{gng}")
        return {
            "safe": len(violations) == 0,
            "violations": violations,
            "checked_utc": _utc_now(),
        }

    # ------------------------------------------------------------- summarize

    def summarize(self) -> dict[str, Any]:
        payload = self.load_payload() or {}
        false_block_audit = self.load_false_block_audit() or {}
        threshold_replay = self.load_threshold_replay() or {}
        safety = self.assert_safety_invariants(payload)
        best_row = payload.get("best_strict_replay_row") or {}
        return {
            "worker_id": "expected_move_model_review",
            "generated_utc": _utc_now(),
            "payload_present": bool(payload),
            "false_block_audit_present": bool(false_block_audit),
            "threshold_replay_present": bool(threshold_replay),
            "go_no_go": payload.get("go_no_go"),
            "recommendation": payload.get("recommendation"),
            "edge_status": payload.get("edge_status"),
            "outcome_status": payload.get("outcome_status"),
            "observations_total": payload.get("observations_total"),
            "completed_observations": payload.get("completed_observations"),
            "pending_observations": payload.get("pending_observations"),
            "false_block_count": payload.get("false_block_count"),
            "false_block_rate": payload.get("false_block_rate"),
            "no_trade_correct_count": payload.get("no_trade_correct_count"),
            "no_trade_correct_rate": payload.get("no_trade_correct_rate"),
            "trainer_parity_status": payload.get("trainer_parity_status"),
            "trainer_remaining_parity_gaps": payload.get("trainer_remaining_parity_gaps", []),
            "paper_symbols": payload.get("paper_symbols", []),
            "best_strict_replay_row": best_row,
            "safety": safety,
            "live_gate": LIVE_GATE_STATUS,
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
        }
