#!/usr/bin/env bash
# Terminal-wealth F2-DEPLOY remediation: repoint ALL FOUR cooperating services
# (trade-management paper loop, candidate-outcome calibration publisher,
# candidate-outcome publisher, adaptive-policy shadow) to ONE immutable SHA,
# replacing the three-SHA skew (6bcada5039 / d4569be033 / 6f49487175).
#
# Order matters: calibration publisher restarts FIRST and must publish a
# candidate_outcome_calibration_v3 artifact (learned_terminal_equity_objective_
# weights_v3 with both terminal fields + learned_online=false derivations)
# into v2:adaptive_system:candidate_calibration:v2 BEFORE the consumers
# restart. Old consumers reject a v3 artifact gracefully; new consumers reject
# a v2 artifact gracefully — but only the ordered restart avoids any window
# where a consumer needs an artifact generation nobody publishes.
#
# Usage: deploy_terminal_wealth_four_service_single_sha.sh <NEW_SHA>
# Rollback: restore the .bak-* drop-ins written below, daemon-reload, restart
# the four units (old artifact remains valid for old code).
set -euo pipefail

NEW="${1:?usage: $0 <new-sha>}"
REPO="/home/wali/Desktop/AI BOT REBUILD"
DEPLOY_ROOT="/home/wali/ai_bot_local_data/deployments/ai_bot_rebuild"
SNAP="$DEPLOY_ROOT/$NEW"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REDIS_KEY="v2:adaptive_system:candidate_calibration:v2"

declare -A DROPIN=(
  [ai-bot-v2-candidate-outcome-calibration]="$HOME/.config/systemd/user/ai-bot-v2-candidate-outcome-calibration.service.d/90-immutable-release.conf"
  [ai-bot-v2-candidate-outcome-publisher]="$HOME/.config/systemd/user/ai-bot-v2-candidate-outcome-publisher.service.d/90-immutable-release.conf"
  [ai-bot-v2-adaptive-policy-shadow]="$HOME/.config/systemd/user/ai-bot-v2-adaptive-policy-shadow.service.d/90-immutable-final-pass.conf"
  [ai-bot-v2-trade-management-paper-loop]="$HOME/.config/systemd/user/ai-bot-v2-trade-management-paper-loop.service.d/90-immutable-release.conf"
)

echo "== preflight =="
git -C "$REPO" cat-file -e "$NEW^{commit}" || { echo "unknown SHA $NEW"; exit 1; }
# Credential files must exist on disk BEFORE any restart (2026-07-24 rule).
for cred in \
  "$HOME/.config/ai-bot-v2/credentials/binance-bracket-evidence/evidence-hmac.cred" \
  "$HOME/.config/ai-bot-v2/credentials/adaptive-hard-validator/seed.cred"; do
  [[ -s "$cred" ]] || { echo "credential missing on disk: $cred"; exit 1; }
done

echo "== immutable snapshot =="
if [[ ! -d "$SNAP" ]]; then
  git -C "$REPO" worktree add --detach "$SNAP" "$NEW"
fi
[[ -e "$SNAP/.venv" ]] || ln -s "$REPO/.venv" "$SNAP/.venv"
[[ -x "$SNAP/.venv/bin/python3" ]] || { echo "snapshot venv missing"; exit 1; }
git -C "$SNAP" diff --quiet --exit-code "$NEW" -- || { echo "snapshot attestation failed"; exit 1; }

echo "== repoint drop-ins (backup: .bak-$STAMP) =="
for unit in "${!DROPIN[@]}"; do
  conf="${DROPIN[$unit]}"
  [[ -f "$conf" ]] || { echo "missing drop-in $conf"; exit 1; }
  old=$(grep -oE "$DEPLOY_ROOT/[0-9a-f]{40}" "$conf" | head -1 | grep -oE '[0-9a-f]{40}$')
  [[ -n "$old" ]] || { echo "no SHA found in $conf"; exit 1; }
  if [[ "$old" == "$NEW" ]]; then echo "$unit already on $NEW"; continue; fi
  cp "$conf" "$conf.bak-$STAMP"
  sed -i "s/$old/$NEW/g" "$conf"
  echo "$unit: $old -> $NEW"
done
systemctl --user daemon-reload

echo "== restart calibration publisher first =="
systemctl --user restart ai-bot-v2-candidate-outcome-calibration.service
for i in $(seq 1 30); do
  sleep 10
  payload=$(redis-cli --no-raw GET "$REDIS_KEY" 2>/dev/null | head -c 2000000 || true)
  if redis-cli GET "$REDIS_KEY" | python3 -c '
import json, sys
d = json.load(sys.stdin)
w = d.get("learned_objective_weights") or {}
ok = (
    d.get("schema_version") == "candidate_outcome_calibration_v3"
    and w.get("schema_version") == "learned_terminal_equity_objective_weights_v3"
    and "terminal_target_probability_reward" in w
    and "expected_log_equity_growth_reward" in w
)
sys.exit(0 if ok else 1)
'; then
    echo "v3 artifact with terminal fields verified in $REDIS_KEY"
    break
  fi
  [[ $i -eq 30 ]] && { echo "v3 artifact NOT observed after 300s - HALT (consumers not restarted)"; exit 1; }
done

echo "== restart consumers =="
systemctl --user restart ai-bot-v2-candidate-outcome-publisher.service
systemctl --user restart ai-bot-v2-adaptive-policy-shadow.service
systemctl --user restart ai-bot-v2-trade-management-paper-loop.service
sleep 30

echo "== verify =="
fail=0
for unit in "${!DROPIN[@]}"; do
  state=$(systemctl --user show "$unit.service" -p ActiveState -p NRestarts --value | paste -sd' ')
  exe=$(systemctl --user show "$unit.service" -p ExecStart --value | grep -oE "$DEPLOY_ROOT/[0-9a-f]{40}" | head -1 || true)
  echo "$unit: $state ${exe:-repo-venv-PYTHONPATH-pinned}"
  [[ "$state" == active* ]] || fail=1
done
[[ $fail -eq 0 ]] || { echo "one or more units not active - inspect + rollback via .bak-$STAMP"; exit 1; }
echo "DEPLOYED all four services at $NEW"
