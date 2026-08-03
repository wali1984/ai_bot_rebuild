#!/usr/bin/env bash
# guardian_stop_hook.sh — deterministic Stop hook for the Capital Guardian loop.
# Fires when Claude finishes a session. Writes STOP_CHECKPOINT.json.
# Paper-only / no-exchange-action system. No mutations to old Redis keys.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GOAL_DIR="$REPO_ROOT/goal_state/V2_CLAUDE_CONTINUOUS_ADVERSARIAL_VALIDATION_AND_CAPITAL_PRODUCTIVITY_GUARDIAN"
CHECKPOINT="$GOAL_DIR/STOP_CHECKPOINT.json"
LOG="$GOAL_DIR/stop_hook.log"
NOW_UTC=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Drain stdin (Claude Code sends Stop event JSON here)
STOP_EVENT=$(cat 2>/dev/null || true)
SESSION_ID=$(echo "$STOP_EVENT" | \
    python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('session_id','unknown'))" \
    2>/dev/null || echo "unknown")

# Read guardian state (graceful on missing)
read_json_field() {
    local file="$1" field="$2" default="$3"
    python3 -c \
        "import json; d=json.load(open('$file')); print(d.get('$field','$default'))" \
        2>/dev/null || echo "$default"
}

OPEN_FINDINGS=0; CRITICAL=0; HIGH=0; MEDIUM=0
GATES_PASSED=0; STATE="ACTIVE"; COMPLETION="false"; LAST_HB="unknown"

if [[ -f "$GOAL_DIR/GOAL_STATE.json" ]]; then
    OPEN_FINDINGS=$(read_json_field "$GOAL_DIR/GOAL_STATE.json" "open_finding_count"    0)
    CRITICAL=$(read_json_field      "$GOAL_DIR/GOAL_STATE.json" "critical_finding_count" 0)
    HIGH=$(read_json_field           "$GOAL_DIR/GOAL_STATE.json" "high_finding_count"     0)
    MEDIUM=$(read_json_field         "$GOAL_DIR/GOAL_STATE.json" "medium_finding_count"   0)
    GATES_PASSED=$(read_json_field   "$GOAL_DIR/GOAL_STATE.json" "completion_gates_passed" 0)
    STATE=$(read_json_field          "$GOAL_DIR/GOAL_STATE.json" "state"                  "ACTIVE")
    COMPLETION=$(read_json_field     "$GOAL_DIR/GOAL_STATE.json" "completion_allowed"     "false")
fi
if [[ -f "$GOAL_DIR/HEARTBEAT.json" ]]; then
    LAST_HB=$(read_json_field "$GOAL_DIR/HEARTBEAT.json" "last_heartbeat_utc" "unknown")
fi

FINDINGS_COUNT=$(grep -c '"finding_id"' "$GOAL_DIR/FINDINGS.jsonl" 2>/dev/null || echo 0)

# Write checkpoint via Python (reliable JSON encoding)
python3 - << PYEOF
import json, sys

chk = {
    "checkpoint_version": "1",
    "written_utc": "${NOW_UTC}",
    "session_id": "${SESSION_ID}",
    "goal_id": "V2_CLAUDE_CONTINUOUS_ADVERSARIAL_VALIDATION_AND_CAPITAL_PRODUCTIVITY_GUARDIAN",
    "state": "${STATE}",
    "completion_allowed": "${COMPLETION}" == "true",
    "completion_gates_passed": int("${GATES_PASSED}"),
    "completion_gates_total": 16,
    "open_finding_count": int("${OPEN_FINDINGS}"),
    "critical_finding_count": int("${CRITICAL}"),
    "high_finding_count": int("${HIGH}"),
    "medium_finding_count": int("${MEDIUM}"),
    "last_heartbeat_utc": "${LAST_HB}",
    "findings_on_disk": int("${FINDINGS_COUNT}"),
    "key_files": {
        "findings":             "${GOAL_DIR}/FINDINGS.jsonl",
        "heartbeat":            "${GOAL_DIR}/HEARTBEAT.json",
        "goal_state":           "${GOAL_DIR}/GOAL_STATE.json",
        "status":               "${GOAL_DIR}/STATUS.md",
        "runtime_observations": "${GOAL_DIR}/RUNTIME_OBSERVATIONS.jsonl",
        "resume_prompt":        "${GOAL_DIR}/RESUME_PROMPT.txt"
    },
    "resume_instruction": "Read STOP_CHECKPOINT.json + HEARTBEAT.json + GOAL_STATE.json + STATUS.md. Then run the full guardian cycle described in RESUME_PROMPT.txt starting at Step 1."
}
with open("${CHECKPOINT}", "w") as f:
    json.dump(chk, f, indent=2)
PYEOF

echo "[$NOW_UTC] guardian_stop_hook: checkpoint written" \
     "session=$SESSION_ID findings=$OPEN_FINDINGS critical=$CRITICAL gates=$GATES_PASSED/18" \
     >> "$LOG"

exit 0
