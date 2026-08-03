#!/usr/bin/env python3
"""Realtime verbose monitor for the V2 native CUDA trainer.

Self-contained (no shell heredoc/pipe collision — the previous .sh piped
`tail` into an interpreter reading its program from a heredoc on stdin, but
that heredoc IS the interpreter's stdin, so the piped log never reached
sys.stdin and nothing printed).

Streams three things as they happen:
  * per-cycle learning metrics from Redis v2:trainer:hybrid_cuda:status
    (online_learning_status, train/val loss, PPO/MASA losses, steps,
    weight delta, checkpoint promotion, overfit gap) — this is where the
    trainer publishes its rich status; stdout only has a coarse guard line.
  * guard/heartbeat lines tailed from the persistent stdout log.
  * stderr lines tailed from the persistent err log.

Read-only monitor; observes runtime state only. Ctrl-C stops the monitor;
the trainer keeps running.
"""
from __future__ import annotations

import json
import os
import subprocess
import time

ROOT = "/home/wali/Desktop/AI BOT REBUILD"
LOG = f"{ROOT}/claude_worklog/agent_supervisor/logs/control_plane/ai-bot-v2-native-cuda-trainer-persistent.log"
ERR = f"{ROOT}/claude_worklog/agent_supervisor/logs/control_plane/ai-bot-v2-native-cuda-trainer-persistent.err"
STATUS_KEY = "v2:trainer:hybrid_cuda:status"
REDIS_POLL_SECONDS = 8.0

C = {
    "reset": "\033[0m", "dim": "\033[2m", "cyan": "\033[36m", "green": "\033[32m",
    "yellow": "\033[33m", "red": "\033[31m", "mag": "\033[35m", "bold": "\033[1m",
}


def _redis():
    try:
        import redis  # type: ignore

        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def _gpu() -> str:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2,
        )
        first = out.stdout.strip().splitlines()[0].split(",")
        return f"{first[0].strip()}%util/{first[1].strip()}MiB"
    except Exception:
        return "n/a"


def _f(value, fmt="{:.3f}"):
    try:
        return fmt.format(float(value))
    except (TypeError, ValueError):
        return None


def _learning_line(status: dict) -> str:
    lm = status.get("learning_metrics") if isinstance(status.get("learning_metrics"), dict) else {}
    ts = status.get("generated_utc") or status.get("generated_est") or ""
    ols = str(status.get("online_learning_status") or "?")
    ols_color = C["green"] if ols == "WEIGHTS_UPDATING" else C["yellow"]
    parts = [f"{C['cyan']}{ts}{C['reset']}", f"{ols_color}{C['bold']}⟳ {ols}{C['reset']}"]
    mode = status.get("effective_trainer_mode")
    if mode:
        parts.append(f"mode={mode}")
    lane = lm.get("learning_update_lane")
    if lane:
        parts.append(f"lane={lane}")
    lb, la = _f(lm.get("loss_before")), _f(lm.get("loss_after"))
    if lb and la:
        parts.append(f"train={lb}→{la}")
    vb = _f(lm.get("validation_supervised_loss_before"))
    va = _f(lm.get("validation_supervised_loss_after"))
    if vb and va:
        gap = _f(lm.get("train_val_generalization_gap"), "{:.2f}")
        warn = f"{C['red']}!{C['reset']}" if lm.get("overfit_gap_warning") else ""
        parts.append(f"val={vb}→{va}{f' gap={gap}{warn}' if gap else ''}")
    comp = []
    for key, short in (("ppo_policy_loss", "pol"), ("ppo_value_loss", "val"),
                       ("ppo_entropy", "ent"), ("masa_loss", "masa")):
        v = _f(lm.get(key))
        if v is not None:
            comp.append(f"{short}={v}")
    if comp:
        parts.append(" ".join(comp))
    steps = lm.get("training_steps")
    if steps is not None:
        parts.append(f"steps={steps}")
    dw = _f(lm.get("weight_delta_norm"), "{:.2f}")
    if dw:
        parts.append(f"Δw={dw}")
    promo_reason = lm.get("checkpoint_promotion_reason")
    if promo_reason:
        promoted = lm.get("checkpoint_promoted_this_cycle")
        pc = C["mag"] if promoted else C["dim"]
        parts.append(f"{pc}promo={promo_reason}(promoted={promoted}){C['reset']}")
    parts.append(f"{C['dim']}gpu={_gpu()}{C['reset']}")
    return " | ".join(parts)


def _guard_line(raw: str):
    try:
        d = json.loads(raw)
    except (TypeError, ValueError):
        return raw.rstrip("\n") if raw.strip() else None
    ts = d.get("generated_est") or d.get("generated_utc") or ""
    bits = [f"{C['dim']}{ts}{C['reset']}", f"{C['dim']}▪ heartbeat{C['reset']}"]
    if d.get("paper_guard_status"):
        bits.append(f"guard={d['paper_guard_status']}")
    if d.get("prediction_grid_rows") is not None:
        bits.append(f"grid_rows={d['prediction_grid_rows']}")
    if d.get("training_steps_total") is not None:
        bits.append(f"steps_total={d['training_steps_total']}")
    if d.get("training_steps_last_hour") is not None:
        bits.append(f"steps/hr={d['training_steps_last_hour']}")
    return " | ".join(str(b) for b in bits)


def _follow(path: str):
    """Generator yielding new lines appended to path (tail -F semantics)."""
    while not os.path.exists(path):
        yield None
        time.sleep(1.0)
    handle = open(path, "r", errors="replace")
    try:
        handle.seek(0, os.SEEK_END)
    except OSError:
        pass
    inode = os.fstat(handle.fileno()).st_ino
    buffer = ""
    while True:
        chunk = handle.read()
        if chunk:
            buffer += chunk
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                yield line
        else:
            try:
                if os.stat(path).st_ino != inode:
                    handle.close()
                    handle = open(path, "r", errors="replace")
                    inode = os.fstat(handle.fileno()).st_ino
                    buffer = ""
            except OSError:
                pass
            yield None
            time.sleep(0.5)


def main() -> int:
    print("=" * 78)
    print(f" {C['bold']}V2 NATIVE CUDA TRAINER - REALTIME VERBOSE MONITOR{C['reset']}")
    print(f" learning metrics: redis {STATUS_KEY} (per training cycle)")
    print(f" heartbeat log:    {LOG}")
    print(f" stderr log:       {ERR}")
    print(" (Ctrl-C to stop; the trainer keeps running regardless)")
    print("=" * 78, flush=True)

    client = _redis()
    if client is None:
        print(f"{C['red']}[warn] redis unavailable - learning metrics line disabled; "
              f"still tailing logs{C['reset']}", flush=True)

    log_follow = _follow(LOG)
    err_follow = _follow(ERR)
    last_status_utc = None
    last_redis_poll = 0.0

    if client is not None:
        try:
            raw = client.get(STATUS_KEY)
            if raw:
                status = json.loads(raw)
                last_status_utc = status.get("generated_utc")
                print(_learning_line(status), flush=True)
        except Exception:
            pass

    while True:
        for _ in range(200):
            line = next(log_follow)
            if line is None:
                break
            formatted = _guard_line(line)
            if formatted:
                print(formatted, flush=True)
        for _ in range(200):
            line = next(err_follow)
            if line is None:
                break
            if line.strip():
                print(f"{C['red']}[stderr]{C['reset']} {line}", flush=True)

        now = time.monotonic()
        if client is not None and now - last_redis_poll >= REDIS_POLL_SECONDS:
            last_redis_poll = now
            try:
                raw = client.get(STATUS_KEY)
                if raw:
                    status = json.loads(raw)
                    utc = status.get("generated_utc")
                    if utc and utc != last_status_utc:
                        last_status_utc = utc
                        print(_learning_line(status), flush=True)
            except Exception:
                pass

        time.sleep(0.5)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nstopped (trainer still running).")
