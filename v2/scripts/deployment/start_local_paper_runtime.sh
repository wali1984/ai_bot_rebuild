#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PYTHON="$ROOT/.venv/bin/python3"
LOG_DIR="$ROOT/v2/runtime"
DRY_RUN=0
PAPER_ONLY=0

for arg in "$@"; do
  case "$arg" in
    --paper-only)
      PAPER_ONLY=1
      ;;
    --dry-run)
      DRY_RUN=1
      ;;
    --real|--live|--live-mode|--mode=real|--mode=live)
      echo "V2_LOCAL_PAPER_START_BLOCKED reason=non_paper_mode_forbidden" >&2
      exit 2
      ;;
  esac
done

if [ "$PAPER_ONLY" -ne 1 ]; then
  echo "V2_LOCAL_PAPER_START_BLOCKED reason=paper_only_flag_required" >&2
  exit 2
fi

cd "$ROOT"
"$PYTHON" -m v2.scripts.deployment.preflight_check --paper-only --json >/tmp/v2_local_paper_preflight.json

mkdir -p "$LOG_DIR"

start_if_missing() {
  local name="$1"
  local pattern="$2"
  shift 2
  if pgrep -f "$pattern" >/dev/null 2>&1; then
    echo "V2_LOCAL_PAPER_ALREADY_RUNNING name=$name"
    return 0
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "V2_LOCAL_PAPER_DRY_RUN_START name=$name cmd=$*"
    return 0
  fi
  nohup "$@" >>"$LOG_DIR/${name}.log" 2>&1 &
  echo "V2_LOCAL_PAPER_STARTED name=$name pid=$!"
}

start_if_missing \
  "paper_online_runtime" \
  "v2.backend.app.cli.paper_online_runtime --loop" \
  "$PYTHON" -m v2.backend.app.cli.paper_online_runtime --loop --interval 30

start_if_missing \
  "paper_shadow_observation" \
  "v2.backend.app.cli.paper_shadow_observation --write" \
  "$PYTHON" -m v2.backend.app.cli.paper_shadow_observation --write

start_if_missing \
  "feature_snapshot_builder" \
  "v2.backend.app.cli.v2_feature_snapshot_builder --loop" \
  "$PYTHON" -m v2.backend.app.cli.v2_feature_snapshot_builder --loop --read-from-paper-runtime --interval 60

echo "V2_LOCAL_PAPER_RUNTIME_START_OK live_gate=blocked_human_only mode=paper"
