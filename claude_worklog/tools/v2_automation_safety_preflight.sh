#!/usr/bin/env bash
# Shared preflight for persistent V2 automation services.
set -euo pipefail

SERVICE_NAME="${1:-unknown-service}"
ROOT="/home/wali/Desktop/AI BOT REBUILD"
FINAL_APPROVAL="$ROOT/claude_worklog/approvals/APPROVED_FINAL_LIVE_TINY_CANARY_ONLY.md"
REDIS_TRIM_APPROVAL="$ROOT/claude_worklog/approvals/APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID_1777222885206_0_ONLY.md"
STATE_JSON="$ROOT/claude_worklog/final_readiness/v2_worker_porting_orchestrator/latest/worker_porting_state.json"

fail() {
  printf 'V2_AUTOMATION_PREFLIGHT_BLOCKED service=%s reason=%s\n' "$SERVICE_NAME" "$1" >&2
  exit 2
}

[ -d "$ROOT" ] || fail "workspace_missing"
cd "$ROOT"

[ -x "$ROOT/.venv/bin/python3" ] || fail "venv_python_missing"
[ ! -f "$FINAL_APPROVAL" ] || fail "final_live_approval_present"
[ ! -f "$REDIS_TRIM_APPROVAL" ] || fail "redis_trim_approval_present"

if [ -f "$STATE_JSON" ]; then
  "$ROOT/.venv/bin/python3" - "$STATE_JSON" <<'PY' || exit 2
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text())
gate = data.get("live_gate") or data.get("current_gate_state")
approval = data.get("final_approval_token")
if gate and gate != "blocked_human_only":
    print(f"V2_AUTOMATION_PREFLIGHT_BLOCKED live_gate={gate}", file=sys.stderr)
    raise SystemExit(2)
if approval and approval != "absent":
    print(f"V2_AUTOMATION_PREFLIGHT_BLOCKED final_approval_token={approval}", file=sys.stderr)
    raise SystemExit(2)
PY
fi

if ! git fsck --no-dangling --connectivity-only >/dev/null 2>&1; then
  fail "git_fsck_failed"
fi

case "$SERVICE_NAME" in
  *legacy*|*trader*|*live-exec*|*live_exec*)
    fail "service_name_not_allowed"
    ;;
esac

printf 'V2_AUTOMATION_PREFLIGHT_OK service=%s live_gate=blocked_human_only\n' "$SERVICE_NAME"
