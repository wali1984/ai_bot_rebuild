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
BATCH_SIZE="${V2_OFFLINE_BATCH_SIZE:-8192}"
MIN_EPOCHS="${V2_OFFLINE_MIN_EPOCHS:-6}"
EARLY_STOP="${V2_OFFLINE_EARLY_STOP:-4}"
LIMIT="${V2_OFFLINE_LIMIT:-65536}"
REBUILD_EVERY="${V2_OFFLINE_REBUILD_EVERY:-5}"
REPORT="$REPO/claude_worklog/trainer_atlas/continuous_offline_last_report.json"
mkdir -p "$(dirname "$REPORT")"

_running=1
trap '_running=0' INT TERM

iter=0
while [ "$_running" -eq 1 ]; do
  iter=$((iter + 1))
  # Rebuild the example cache every Nth iteration to ingest newly-matured replay
  # labels; warm-start / reuse cache otherwise for a tight GPU-busy cadence.
  rebuild=""
  if [ "$REBUILD_EVERY" -gt 0 ] && [ $((iter % REBUILD_EVERY)) -eq 1 ]; then
    rebuild="--rebuild-cache"
  fi
  echo "[continuous-offline] iter=$iter rebuild=${rebuild:-no} $(date -Is)"
  "$PY" -m v2.backend.app.cli.v2_trainer_offline_batch_train \
    --from-checkpoint \
    --save-offline \
    --epochs "$EPOCHS" \
    --steps-per-epoch "$STEPS_PER_EPOCH" \
    --batch-size "$BATCH_SIZE" \
    --min-epochs "$MIN_EPOCHS" \
    --early-stop-patience "$EARLY_STOP" \
    --limit "$LIMIT" \
    $rebuild \
    --output "$REPORT" || echo "[continuous-offline] iter=$iter exited non-zero (continuing)"
  # Interruptible sleep so SIGTERM stops promptly.
  for _ in $(seq 1 "$INTERVAL"); do
    [ "$_running" -eq 1 ] || break
    sleep 1
  done
done
echo "[continuous-offline] stopped after iter=$iter"
