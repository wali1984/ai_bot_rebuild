# Codex Review: codex_review_autoseed_decision_match_runtime_replay_comparator

GO/NO-GO: `V2_AUTONOMOUS_DECISION_MATCH_RUNTIME_REPLAY_COMPARATOR_CODEX_FAIL`

## Command

```text
/home/wali/.local/bin/codex exec review ...
```

## Blockers

- 1. Appends the current ``v2:market:prices:{symbol}`` snapshot to a
- 1. **`decision_comparator/service.py`** — add two optional kwargs `replay_status` and `legacy_reference_metadata`, produce two new sub-blocks on each comparison (`replay_evidence_match`, `legacy_reference_metadata_match`) with exact evidence pointers (file paths + dotted keys), tag legacy-reference data with `data_role: "reference_only"` and a "not current truth" note, and aggregate a top-level `mismatches[]` array with `{kind, observed, expected, evidence_pointer, severity, note}`. Add disagree
- blockers = as_list(nested_get(canary, "blockers")) + as_list(paper_exec_status.get("paper_filter_blockers"))

## Raw Output (tail)

```text
    canary = nested_get(paper_status, "current_risk_decision.canary_profile_tightening", {})
    expected_move = nested_get(canary, "expected_move_bps") or paper_exec_status.get(
        "paper_filter_expected_move_bps"
    )
    cost = nested_get(canary, "estimated_cost_bps") or paper_exec_status.get(
        "paper_filter_estimated_cost_bps"
    )
    expected_after_cost = None
    if as_float(expected_move) is not None and as_float(cost) is not None:
        expected_after_cost = float(expected_move) - float(cost)
    comparison_id_source = "|".join(
        [
            str(legacy_status.get("latest_prediction_id") or ""),
            str(v2_prediction_id or ""),
            str(utc_now()),
        ]
    )
    comparison = {
        "comparison_id": "cmp_" + hashlib.sha256(comparison_id_source.encode()).hexdigest()[:16],
        "legacy_prediction_id": legacy_status.get("latest_prediction_id"),
        "legacy_signal_id": legacy_status.get("latest_signal_id"),
        "v2_feature_snapshot_id": nested_get(paper_status, "feature_snapshot.feature_snapshot_id")
        or trainer_status.get("feature_snapshot_id"),
        "v2_prediction_id": v2_prediction_id,
        "symbol": legacy_status.get("latest_symbol")
        or nested_get(paper_status, "trainer_prediction.symbol")
        or paper_exec_status.get("symbol"),
        "side": nested_get(paper_status, "trainer_prediction.raw_output.side")
        or nested_get(paper_status, "current_signal_lineage.signal.side"),
        "timeframe": legacy_status.get("latest_timeframe")
        or nested_get(paper_status, "trainer_prediction.timeframe"),
        "legacy_confidence": legacy_status.get("latest_confidence"),
        "v2_confidence": nested_get(paper_status, "trainer_prediction.confidence_calibrated")
        or trainer_status.get("confidence_calibrated"),
        "v2_confidence_bucket": confidence_bucket(
            nested_get(paper_status, "trainer_prediction.confidence_calibrated")
            or trainer_status.get("confidence_calibrated")
        ),
        "legacy_reason": legacy_status.get("latest_signal_reason"),
        "v2_reason": nested_get(paper_status, "current_risk_decision.risk_reason_code")
        or risk_status.get("risk_reason_code"),
        "v2_block_reason": nested_get(paper_status, "current_risk_decision.canary_profile_tightening.blockers")
        or paper_exec_status.get("paper_filter_blockers")
        or risk_status.get("risk_reason_code"),
        "symbol_scope": {
            "paper_symbols": as_list(symbol_status.get("paper_symbols")),
            "live_symbols": as_list(symbol_status.get("live_symbols")),
        },
        "feature_freshness_state": nested_get(paper_status, "feature_snapshot.freshness_state")
        or nested_get(paper_status, "trainer_prediction.freshness_state"),
        "expected_move_after_cost_bps": expected_after_cost,
        "cost_breakdown_bps": _cost_breakdown(paper_status, paper_exec_status),
        "risk_decision": nested_get(paper_status, "current_risk_decision.risk_action")
        or risk_status.get("risk_action"),
        "comparator_result": _comparison_result(legacy_allow, v2_allow, legacy_present, v2_present),
        "disagreement_reasons": _disagreement_reasons(
            paper_status=paper_status,
            trainer_status=trainer_status,
            symbol_status=symbol_status,
            risk_status=risk_status,
            paper_exec_status=paper_exec_status,
        ),
    }
    status = {
        "worker_id": "legacy_v2_decision_comparator",
        "generated_at": utc_now(),
        "comparison_count": 1,
        "comparisons": [comparison],
        "latest_comparison": comparison,
        "legacy_v2_agreement_status": comparison["comparator_result"],
        "read_only_status": "READ_ONLY_REFERENCE_ONLY",
        "live_gate": LIVE_GATE_STATUS,
        "live_symbols": [],
    }
    status.update(safety_footer())
    return status
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from v2.backend.app.services.decision_comparator import build_legacy_v2_decision_comparator_status
from v2.backend.app.services.legacy_v2_observatory_common import first_json, load_json, repo_root, write_json


WORKER_ID = "legacy_v2_decision_comparator"
REPO_ROOT = repo_root()
V2_PUBLIC = REPO_ROOT / "v2" / "frontend" / "public"
OBS_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "legacy_v2_realtime_decision_observatory"
    / "latest"
)
PUBLIC_RUNTIME_DIR = V2_PUBLIC / "operator_runtime" / WORKER_ID / "latest"
PUBLIC_STATUS_FILE = PUBLIC_RUNTIME_DIR / f"{WORKER_ID}_status.json"
WORKLOG_STATUS_FILE = OBS_DIR / f"{WORKER_ID}_status.json"
LEGACY_STATUS_CANDIDATES = [
    OBS_DIR / "legacy_runtime_observer_status.json",
    V2_PUBLIC / "operator_runtime" / "legacy_runtime_readonly_observer" / "latest" / "legacy_runtime_readonly_observer_status.json",
]
PAPER_STATUS_CANDIDATES = [
    V2_PUBLIC / "operator_runtime" / "paper_online" / "latest" / "paper_runtime_status.json",
]
TRAINER_STATUS_CANDIDATES = [
    V2_PUBLIC / "operator_runtime" / "v2_trainer_bridge" / "latest" / "v2_trainer_bridge_status.json",
]
SYMBOL_STATUS_CANDIDATES = [
    V2_PUBLIC / "operator_runtime" / "symbol_universe" / "latest" / "symbol_universe_status.json",
    V2_PUBLIC / "operator_runtime" / "v2_symbol_universe" / "latest" / "symbol_universe_status.json",
]
RISK_STATUS_CANDIDATES = [
    V2_PUBLIC / "operator_runtime" / "v2_risk_gateway_runtime_worker" / "latest" / "v2_risk_gateway_runtime_worker_status.json",
]
PAPER_EXEC_STATUS_CANDIDATES = [
    V2_PUBLIC / "operator_runtime" / "v2_paper_execution_worker" / "latest" / "v2_paper_execution_worker_status.json",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--legacy-status-file", type=Path)
    parser.add_argument("--paper-status-file", type=Path)
    parser.add_argument("--trainer-status-file", type=Path)
    parser.add_argument("--symbol-status-file", type=Path)
    parser.add_argument("--risk-status-file", type=Path)
    parser.add_argument("--paper-exec-status-file", type=Path)
    return parser.parse_args(argv)


def _load(path: Path | None, candidates: list[Path]) -> dict[str, Any]:
    if path is not None:
        payload = load_json(path)
        return payload if isinstance(payload, dict) else {}
    payload, _ = first_json(candidates)
    return payload if isinstance(payload, dict) else {}


def run_once(args: argparse.Namespace | None = None) -> dict[str, Any]:
    args = args or parse_args(["--once"])
    status = build_legacy_v2_decision_comparator_status(
        legacy_status=_load(args.legacy_status_file, LEGACY_STATUS_CANDIDATES),
        paper_status=_load(args.paper_status_file, PAPER_STATUS_CANDIDATES),
        trainer_status=_load(args.trainer_status_file, TRAINER_STATUS_CANDIDATES),
        symbol_status=_load(args.symbol_status_file, SYMBOL_STATUS_CANDIDATES),
        risk_status=_load(args.risk_status_file, RISK_STATUS_CANDIDATES),
        paper_exec_status=_load(args.paper_exec_status_file, PAPER_EXEC_STATUS_CANDIDATES),
    )
    if args.write:
        write_json(PUBLIC_STATUS_FILE, status)
        write_json(WORKLOG_STATUS_FILE, status)
    return status


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    status = run_once(args)
    json.dump(status, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

exec
/bin/bash -lc "find claude_worklog/final_readiness -path '*decision_match_runtime_replay_comparator*' -print; find . -path './v2/frontend/node_modules' -prune -o -type f -name '*decision*comparator*' -print | sed -n '1,120p'" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
claude_worklog/final_readiness/v2_closed_loop_execution/latest/locks/v2_decision_match_runtime_replay_comparator.lock
claude_worklog/final_readiness/v2_closed_loop_execution/latest/codex_review_outputs/codex_review_autoseed_decision_match_runtime_replay_comparator
claude_worklog/final_readiness/v2_closed_loop_execution/latest/heartbeats/codex_review_autoseed_decision_match_runtime_replay_comparator.json
claude_worklog/final_readiness/v2_closed_loop_execution/latest/heartbeats/claude_autoseed_decision_match_runtime_replay_comparator.json
claude_worklog/final_readiness/v2_closed_loop_execution/latest/logs/codex_review_autoseed_decision_match_runtime_replay_comparator_codex.log
claude_worklog/final_readiness/v2_closed_loop_execution/latest/logs/claude_autoseed_decision_match_runtime_replay_comparator.log
./claude_worklog/agent_supervisor/tasks/codex_review_autoseed_decision_match_runtime_replay_comparator.json
./claude_worklog/agent_supervisor/tasks/claude_autoseed_decision_match_runtime_replay_comparator.json
./claude_worklog/agent_supervisor/state/tasks/codex_review_autoseed_decision_match_runtime_replay_comparator.json
./claude_worklog/agent_supervisor/state/tasks/claude_autoseed_decision_match_runtime_replay_comparator.json
./claude_worklog/final_readiness/v2_closed_loop_execution/latest/locks/v2_decision_match_runtime_replay_comparator.lock
./claude_worklog/final_readiness/v2_closed_loop_execution/latest/heartbeats/codex_review_autoseed_decision_match_runtime_replay_comparator.json
./claude_worklog/final_readiness/v2_closed_loop_execution/latest/heartbeats/claude_autoseed_decision_match_runtime_replay_comparator.json
./claude_worklog/final_readiness/v2_closed_loop_execution/latest/logs/codex_review_autoseed_decision_match_runtime_replay_comparator_codex.log
./claude_worklog/final_readiness/v2_closed_loop_execution/latest/logs/claude_autoseed_decision_match_runtime_replay_comparator.log
./claude_worklog/final_readiness/legacy_v2_realtime_decision_observatory/latest/legacy_v2_decision_comparator_status.json
./v2/backend/app/cli/legacy_v2_decision_comparator.py
./v2/backend/app/cli/__pycache__/legacy_v2_decision_comparator.cpython-312.pyc
./v2/backend/tests/integration/cli/test_legacy_v2_decision_comparator.py
./v2/backend/tests/integration/cli/__pycache__/test_legacy_v2_decision_comparator.cpython-312-pytest-8.3.3.pyc
./v2/frontend/public/operator_runtime/legacy_v2_decision_comparator/latest/legacy_v2_decision_comparator_status.json
./v2/frontend/dist/operator_runtime/legacy_v2_decision_comparator/latest/legacy_v2_decision_comparator_status.json

codex
V2_AUTONOMOUS_DECISION_MATCH_RUNTIME_REPLAY_COMPARATOR_CODEX_FAIL
V2_AUTONOMOUS_DECISION_MATCH_RUNTIME_REPLAY_COMPARATOR_CODEX_FAIL
```
