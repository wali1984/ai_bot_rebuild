#!/usr/bin/env bash
set -euo pipefail

DRY_RUN=1
CONFIRM=0

for arg in "$@"; do
  case "$arg" in
    --dry-run)
      DRY_RUN=1
      ;;
    --confirm-v2-paper-only)
      CONFIRM=1
      DRY_RUN=0
      ;;
    --legacy|--trader|--redis|--all)
      echo "V2_LOCAL_PAPER_STOP_BLOCKED reason=target_not_allowed target=$arg" >&2
      exit 2
      ;;
  esac
done

patterns=(
  "v2.backend.app.cli.paper_online_runtime --loop"
  "v2.backend.app.cli.paper_shadow_observation --write"
  "v2.backend.app.cli.v2_feature_snapshot_builder --loop"
)

for pattern in "${patterns[@]}"; do
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "V2_LOCAL_PAPER_STOP_DRY_RUN pattern=$pattern"
    continue
  fi
  if [ "$CONFIRM" -ne 1 ]; then
    echo "V2_LOCAL_PAPER_STOP_BLOCKED reason=confirmation_required" >&2
    exit 2
  fi
  pkill -f "$pattern" >/dev/null 2>&1 || true
  echo "V2_LOCAL_PAPER_STOPPED pattern=$pattern"
done

echo "V2_LOCAL_PAPER_STOP_OK legacy_untouched=true redis_untouched=true"
