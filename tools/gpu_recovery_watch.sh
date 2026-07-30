#!/usr/bin/env bash
# GPU recovery watcher (CG-F055). Runs from a user timer every 2 minutes.
# When the NVIDIA driver becomes loadable again (operator installs
# linux-modules-nvidia-580-open-$(uname -r) and modprobes, or reboots),
# restart the research trainer so torch re-probes CUDA, then retire the timer.
# Paper/research only; never touches live; no-op while the driver is absent.
set -euo pipefail

nvidia-smi >/dev/null 2>&1 || exit 0   # driver still down - nothing to do

STATUS=/home/wali/ai_bot_local_data/v2_native_trainer/local_profiled_research_v1/status.json
BLOCKER=$(python3 -c "
import json
try:
    d = json.load(open('$STATUS'))
    print(d.get('cuda_runtime', {}).get('cuda_runtime_blocker') or '')
except Exception:
    print('')" 2>/dev/null)

if [[ "$BLOCKER" == "CUDA_UNAVAILABLE" ]]; then
  echo "GPU back; restarting research trainer to re-probe CUDA"
  systemctl --user restart ai-bot-v2-native-cuda-trainer-persistent.service
  sleep 45
fi

# Verify and self-retire once the trainer sees the GPU (or was never blocked).
NEWBLOCKER=$(python3 -c "
import json
try:
    d = json.load(open('$STATUS'))
    print(d.get('cuda_runtime', {}).get('cuda_runtime_blocker') or '')
except Exception:
    print('unknown')" 2>/dev/null)
if [[ "$NEWBLOCKER" != "CUDA_UNAVAILABLE" ]]; then
  echo "trainer CUDA blocker cleared ('$NEWBLOCKER'); retiring watcher timer"
  systemctl --user disable --now ai-bot-v2-gpu-recovery-watch.timer || true
fi
