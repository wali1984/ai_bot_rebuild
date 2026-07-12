#!/usr/bin/env bash
# Verbose live tail of the V2 native CUDA trainer (stdout status + stderr).
# Pretty-prints the per-cycle JSON status so the operator can watch training in
# real time: cycle cadence, online_learning_status, promotion reason, PPO/MASA
# losses, validation trajectory, GPU util. Launched detached in gnome-terminal.
set -u
ROOT="/home/wali/Desktop/AI BOT REBUILD"
LOG="$ROOT/claude_worklog/agent_supervisor/logs/control_plane/ai-bot-v2-native-cuda-trainer-persistent.log"
ERR="$ROOT/claude_worklog/agent_supervisor/logs/control_plane/ai-bot-v2-native-cuda-trainer-persistent.err"
PY="$ROOT/.venv/bin/python"

echo "======================================================================"
echo " V2 NATIVE CUDA TRAINER — LIVE VERBOSE TAIL"
echo " log: $LOG"
echo " err: $ERR"
echo " (Ctrl-C to stop; the trainer keeps running regardless)"
echo "======================================================================"

# Pretty-printer for the JSON status lines; passes non-JSON through untouched.
pretty() {
  "$PY" - <<'PYEOF'
import sys, json, datetime
def gpu():
    try:
        import subprocess
        o = subprocess.run(["nvidia-smi","--query-gpu=utilization.gpu,memory.used","--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=2)
        return o.stdout.strip().splitlines()[0].replace(", ", "%util / ")+"MiB"
    except Exception:
        return "n/a"
for line in sys.stdin:
    line = line.rstrip("\n")
    if not line.strip():
        continue
    try:
        d = json.loads(line)
    except Exception:
        print(line, flush=True); continue
    lm = d.get("learning_metrics", {}) if isinstance(d.get("learning_metrics"), dict) else {}
    ts = d.get("generated_est") or d.get("generated_utc") or datetime.datetime.now().isoformat()
    parts = [f"\033[36m{ts}\033[0m"]
    ols = d.get("online_learning_status")
    if ols:
        color = "32" if ols == "WEIGHTS_UPDATING" else "33"
        parts.append(f"\033[{color}m{ols}\033[0m")
    if d.get("effective_trainer_mode"):
        parts.append(f"mode={d['effective_trainer_mode']}")
    if d.get("checkpoint_promotion_reason"):
        parts.append(f"promo={d['checkpoint_promotion_reason']}")
    if d.get("checkpoint_promoted_this_cycle") is not None:
        parts.append(f"promoted={d['checkpoint_promoted_this_cycle']}")
    vb, va = lm.get("validation_supervised_loss_before"), lm.get("validation_supervised_loss_after")
    if vb is not None and va is not None:
        parts.append(f"val={vb:.2f}->{va:.2f}")
    lb, la = lm.get("loss_before"), lm.get("loss_after")
    if lb is not None and la is not None:
        parts.append(f"train={lb:.2f}->{la:.2f}")
    for k in ("ppo_policy_loss","ppo_value_loss","ppo_entropy","masa_loss"):
        if lm.get(k) is not None:
            parts.append(f"{k.replace('ppo_','').replace('_loss','')}={lm[k]:.3f}")
    if d.get("training_steps_total") is not None:
        parts.append(f"steps={d['training_steps_total']}")
    if d.get("training_steps_last_hour") is not None:
        parts.append(f"steps/hr={d['training_steps_last_hour']}")
    parts.append(f"gpu={gpu()}")
    print(" | ".join(str(p) for p in parts), flush=True)
PYEOF
}

# tail both streams; label stderr lines, pretty-print stdout status lines.
stdbuf -oL tail -n 30 -F "$LOG" 2>/dev/null | pretty &
TAIL_LOG_PID=$!
stdbuf -oL tail -n 5 -F "$ERR" 2>/dev/null | stdbuf -oL sed -u 's/^/\x1b[31m[stderr]\x1b[0m /' &
TAIL_ERR_PID=$!
trap 'kill $TAIL_LOG_PID $TAIL_ERR_PID 2>/dev/null' EXIT
wait
