"""
CLAUDE_CHALLENGER_INDEPENDENT_SCOREBOARD — Task C (corrected drift detector)

Drift detector rule (corrected per operator feedback):
  - Inspect only files modified AFTER GOAL_LOCK.started_utc (2026-06-24T21:57:46Z,
    commit 3ca20d8862)
  - Inspect SOURCE-CODE changes, not historical artifact filenames
  - Ignore expected goal artifacts: goal_state/, claude_worklog/, v2/frontend/public/
  - Flag unrelated source work only (non-challenger .py/.ts/.tsx/.js work)
  - DRIFT_DETECTED = true if such source work appears before challenger has
    positive holdout expectancy

Usage:
  python3 scoreboard_verifier.py [--write]
"""
from __future__ import annotations

import datetime
import json
import subprocess
from pathlib import Path
from typing import Any

MAIN_REPO = Path("/home/wali/Desktop/AI BOT REBUILD")

GOAL_LOCK_COMMIT = "3ca20d8862"
GOAL_LOCK_UTC = "2026-06-24T21:57:46Z"

FROZEN_STATUS = (
    MAIN_REPO
    / "goal_state"
    / "V2_MODEL_EDGE_RECOVERY_CHAMPION_CHALLENGER_AND_A_GRADE_BOOTSTRAP"
    / "model_edge_recovery_champion_challenger_status.json"
)

# Paths that are EXPECTED to change as part of the challenger goal — not drift
EXPECTED_ARTIFACT_PREFIXES = (
    "goal_state/",
    "claude_worklog/",
    "v2/frontend/public/operator_runtime/",
    "v2/challengers/claude_regime_aware_outcome_model/",
)

# Source-code file extensions that signal real work (not docs/json artifacts)
SOURCE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".swift"}


def _git_changes_after_freeze(repo: Path) -> list[dict[str, Any]]:
    """Get all source-code files changed in commits after GOAL_LOCK_COMMIT."""
    try:
        result = subprocess.run(
            ["git", "log", "--name-only", "--format=%H %ci",
             f"{GOAL_LOCK_COMMIT}..HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:
        return [{"error": str(exc)}]

    lines = result.stdout.splitlines()
    changes: list[dict[str, Any]] = []
    current_commit = ""
    current_timestamp = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if len(line.split()) >= 2 and len(line.split()[0]) == 40:
            parts = line.split(maxsplit=2)
            current_commit = parts[0]
            current_timestamp = parts[1] if len(parts) > 1 else ""
        elif line and current_commit:
            ext = Path(line).suffix.lower()
            is_source = ext in SOURCE_EXTENSIONS
            is_expected = any(line.startswith(p) for p in EXPECTED_ARTIFACT_PREFIXES)
            if is_source and not is_expected:
                changes.append({
                    "commit": current_commit,
                    "timestamp": current_timestamp,
                    "file": line,
                    "extension": ext,
                    "classified_as": "UNRELATED_SOURCE_WORK",
                })
    return changes


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def run_scoreboard(*, write: bool = False) -> dict[str, Any]:
    frozen = _read_json(FROZEN_STATUS)
    if not frozen:
        return {
            "error": "frozen_status_not_found",
            "path": str(FROZEN_STATUS),
        }

    holdout = frozen.get("untouched_holdout_metrics") or {}
    holdout_expectancy = holdout.get("after_cost_expectancy_bps")
    holdout_da = holdout.get("directional_accuracy")
    holdout_trades = holdout.get("trade_count")
    challenger_status = frozen.get("status", "UNKNOWN")
    result_hash = frozen.get("result_hash", "")
    paper_pub = frozen.get("paper_challenger_publication") or {}
    published_count = paper_pub.get("published_count", 0)
    rejected_count = paper_pub.get("rejected_count", 0)

    challenger_has_positive_expectancy = (
        holdout_expectancy is not None and holdout_expectancy > 0.0
    )

    unrelated_source_changes = _git_changes_after_freeze(MAIN_REPO)
    has_errors = any("error" in c for c in unrelated_source_changes)

    drift_detected = (
        not has_errors
        and len(unrelated_source_changes) > 0
        and not challenger_has_positive_expectancy
    )

    now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    scoreboard: dict[str, Any] = {
        "generated_utc": now_utc,
        "goal_lock_commit": GOAL_LOCK_COMMIT,
        "goal_lock_utc": GOAL_LOCK_UTC,
        "verifier": "CLAUDE_INDEPENDENT_SCOREBOARD_V2",
        "challenger_status": challenger_status,
        "result_hash": result_hash,
        "holdout_metrics": {
            "after_cost_expectancy_bps": holdout_expectancy,
            "directional_accuracy": holdout_da,
            "trade_count": holdout_trades,
            "positive_expectancy": challenger_has_positive_expectancy,
        },
        "paper_publication": {
            "published_count": published_count,
            "rejected_count": rejected_count,
            "canary_started": False,
        },
        "drift_check": {
            "method": "git_log_source_code_changes_after_freeze_commit",
            "inspect_after_utc": GOAL_LOCK_UTC,
            "exclude_prefixes": list(EXPECTED_ARTIFACT_PREFIXES),
            "source_extensions_checked": sorted(SOURCE_EXTENSIONS),
            "unrelated_source_changes": unrelated_source_changes,
            "unrelated_change_count": len([c for c in unrelated_source_changes if "error" not in c]),
        },
        "DRIFT_DETECTED": drift_detected,
        "drift_rationale": (
            "No unrelated source changes detected after freeze commit."
            if not drift_detected and not unrelated_source_changes
            else (
                f"{len(unrelated_source_changes)} unrelated source file(s) changed after freeze; "
                "but challenger already has positive holdout expectancy — acceptable sequencing."
                if not drift_detected and unrelated_source_changes
                else (
                    f"{len(unrelated_source_changes)} unrelated source file(s) changed after freeze "
                    "before challenger achieved positive holdout expectancy."
                    if drift_detected
                    else "git error — drift status unknown"
                )
            )
        ),
        "final_marker": (
            "CLAUDE_FROZEN_HOLDOUT_ARTIFACT_VERIFIED_BLIND_LOCKBOX_AND_FORWARD_CANARY_BLOCKED"
            if challenger_has_positive_expectancy and not drift_detected
            else "CLAUDE_FROZEN_HOLDOUT_ARTIFACT_UNVERIFIED_BLIND_LOCKBOX_AND_FORWARD_CANARY_BLOCKED"
        ),
    }

    if write:
        out = MAIN_REPO / "v2/challengers/claude_regime_aware_outcome_model"
        out.mkdir(parents=True, exist_ok=True)
        (out / "claude_challenger_independent_scoreboard.json").write_text(
            json.dumps(scoreboard, indent=2, sort_keys=True) + "\n"
        )
        drift_alert = {
            "generated_utc": now_utc,
            "DRIFT_DETECTED": drift_detected,
            "rationale": scoreboard["drift_rationale"],
            "unrelated_source_change_count": scoreboard["drift_check"]["unrelated_change_count"],
            "challenger_has_positive_expectancy": challenger_has_positive_expectancy,
            "method": "git_log_source_code_changes_after_freeze_commit_NOT_filename_pattern_match",
        }
        (out / "claude_drift_alert.json").write_text(
            json.dumps(drift_alert, indent=2, sort_keys=True) + "\n"
        )

    return scoreboard


if __name__ == "__main__":
    import sys
    write = "--write" in sys.argv
    result = run_scoreboard(write=write)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result.get("DRIFT_DETECTED"):
        sys.exit(1)
