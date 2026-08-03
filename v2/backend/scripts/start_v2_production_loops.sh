#!/usr/bin/env bash
# Start the five V2 production-equivalent loops in background.
# Paper-only. No exchange mutation. V2 namespace only.
set -e
cd "$(dirname "$0")/../../.."
export PYTHONPATH="$(pwd)"
mkdir -p v2/runtime/v2_production_replacement_runtime
PY=./.venv/bin/python
LOG=v2/runtime/v2_production_replacement_runtime

start_loop() {
  local name="$1"; shift
  local cmd=( "$@" )
  if pgrep -f "v2.backend.app.cli.${name}" >/dev/null 2>&1; then
    echo "${name} already running"
  else
    nohup "$PY" -m "v2.backend.app.cli.${name}" --loop --interval-seconds 60 \
      >> "$LOG/${name}.log" 2>&1 &
    echo "${name}_pid=$!"
  fi
}

start_loop v2_native_ingestors_live_loop
start_loop v2_feature_pipeline_native_loop
start_loop v2_rl_core_inference_loop
start_loop v2_orchestrator_arbitration_loop
start_loop v2_trade_management_paper_loop
