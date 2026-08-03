#!/usr/bin/env bash
# Continuous offline GPU-saturating trainer loop (paper/shadow; NEVER live).
#
# Root-cause fix companion: the online resident trainer alone overfits on a small
# per-cycle batch and self-rejects, so durable learning stalled and the RTX sat
# idle. This loop keeps the RTX saturated on the large offline batch trainer
# (v2_trainer_offline_batch_train), which:
#   - warm-starts read-only from the current LIVE checkpoint (--from-checkpoint)
#   - trains a big batch (8192) for several epochs on trusted replay
#   - writes ONLY to the NON-LIVE offline dir (--save-offline); the CLI refuses to
#     write the live checkpoint dir.
# Promotion into the live warm start stays gated by the out-of-sample H2L in
# ai-bot-v2-trainer-scheduled-pretrain (unchanged). This process never promotes,
# never places an order, never mutates live.
#
# Env knobs (all optional): V2_OFFLINE_LOOP_INTERVAL_SECONDS, V2_OFFLINE_EPOCHS,
# V2_OFFLINE_STEPS_PER_EPOCH, V2_OFFLINE_BATCH_SIZE, V2_OFFLINE_MIN_EPOCHS,
# V2_OFFLINE_EARLY_STOP, V2_OFFLINE_LIMIT, V2_OFFLINE_REBUILD_EVERY.
set -u

REPO="/home/wali/Desktop/AI BOT REBUILD"
cd "$REPO" || { echo "repo not found: $REPO" >&2; exit 1; }
PY="$REPO/.venv/bin/python"

export PYTHONPATH="$REPO"
# Model architecture MUST match the live persistent trainer or H2L input-dim /
# architecture reconciliation aborts. Keep in lockstep with the persistent unit.
export V2_TRAINER_HIDDEN_SIZE="${V2_TRAINER_HIDDEN_SIZE:-2048}"
export V2_TRAINER_RESIDUAL_BLOCKS="${V2_TRAINER_RESIDUAL_BLOCKS:-4}"
export V2_TRAINER_TEMPORAL_ENCODER="${V2_TRAINER_TEMPORAL_ENCODER:-gru}"
export V2_TRAINER_TEMPORAL_PROJ_DIM="${V2_TRAINER_TEMPORAL_PROJ_DIM:-256}"
export V2_TRAINER_CPU_THREADS="${V2_TRAINER_CPU_THREADS:-8}"
export LIVE_GATE="blocked_human_only"
export V2_LIVE="0"

INTERVAL="${V2_OFFLINE_LOOP_INTERVAL_SECONDS:-90}"
EPOCHS="${V2_OFFLINE_EPOCHS:-12}"
STEPS_PER_EPOCH="${V2_OFFLINE_STEPS_PER_EPOCH:-60}"
BATCH_SIZE="${V2_OFFLINE_BATCH_SIZE:-2048}"
MIN_EPOCHS="${V2_OFFLINE_MIN_EPOCHS:-6}"
EARLY_STOP="${V2_OFFLINE_EARLY_STOP:-4}"
LIMIT="${V2_OFFLINE_LIMIT:-49152}"
# Rebuild the CPU-heavy example cache only occasionally so we do not starve the
# real-time online trainer's per-cycle data prep. Matured labels change slowly
# (4.5h embargo), so a rebuild every ~20 iterations is ample fresh data; between
# rebuilds we reuse the cache and stay GPU-bound (cheap on CPU).
REBUILD_EVERY="${V2_OFFLINE_REBUILD_EVERY:-20}"
REPORT="$REPO/claude_worklog/trainer_atlas/continuous_offline_last_report.json"
CACHE="${V2_OFFLINE_CACHE_PATH:-$REPO/claude_worklog/trainer_atlas/offline_batch_example_cache.pkl}"
mkdir -p "$(dirname "$REPORT")"

# Warm-start from the LIVE checkpoint only when explicitly enabled.  The current
# live checkpoint's causal ledger (.local_models/v2_native_rl_masa_ppo/
# .checkpoint-causal-order.jsonl) has a mid-chain integrity break
# (checkpoint_causal_ledger_invalid), so --from-checkpoint fail-closes every
# run and the loop can never emit a checkpoint.  Default to COLD START so the
# loop trains on the now-flowing durable-archive data and starts a clean
# offline causal lineage.  Re-enable with V2_OFFLINE_FROM_CHECKPOINT=1 once the
# live checkpoint is repaired or a fresh offline checkpoint is promoted to live.
if [ "${V2_OFFLINE_FROM_CHECKPOINT:-0}" = "1" ]; then
  WARMSTART_FLAG="--from-checkpoint"
else
  WARMSTART_FLAG=""
fi

_running=1
trap '_running=0' INT TERM

iter=0
while [ "$_running" -eq 1 ]; do
  iter=$((iter + 1))
  # Rebuild only every Nth iteration, AND never force a rebuild on a restart when
  # a cache already exists (a restart must not trigger a fresh 49k-row scan that
  # starves the online trainer). If no cache exists the CLI builds one once.
  rebuild=""
  if [ "$REBUILD_EVERY" -gt 0 ] && [ $((iter % REBUILD_EVERY)) -eq 0 ]; then
    rebuild="--rebuild-cache"
  fi
  echo "[continuous-offline] iter=$iter rebuild=${rebuild:-no} $(date -Is)"
  "$PY" -m v2.backend.app.cli.v2_trainer_offline_batch_train \
    $WARMSTART_FLAG \
    --save-offline \
    --epochs "$EPOCHS" \
    --steps-per-epoch "$STEPS_PER_EPOCH" \
    --batch-size "$BATCH_SIZE" \
    --min-epochs "$MIN_EPOCHS" \
    --early-stop-patience "$EARLY_STOP" \
    --limit "$LIMIT" \
    $rebuild \
    --output "$REPORT"
  trainer_rc=$?
  if [ "$trainer_rc" -ne 0 ]; then
    echo "[continuous-offline] iter=$iter exited non-zero rc=$trainer_rc; propagating to systemd" >&2
    exit "$trainer_rc"
  fi
  # Interruptible sleep so SIGTERM stops promptly.
  for _ in $(seq 1 "$INTERVAL"); do
    [ "$_running" -eq 1 ] || break
    sleep 1
  done
done
echo "[continuous-offline] stopped after iter=$iter"
