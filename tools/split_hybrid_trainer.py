#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from common_audit import resolve_path, read_text_safely, sha256_text, write_json, verification_command

KEYWORDS = ["reward", "confidence", "signal", "orchestrator", "xadd", "publish", "checkpoint", "state_space", "MASS", "stale", "live", "paper", "risk", "position", "portfolio"]


def chunk_category(text_l: str) -> str:
    if any(k in text_l for k in ["reward", "pnl", "drawdown", "penalty", "profit", "loss"]):
        return "reward"
    if any(k in text_l for k in ["confidence", "probability", "softmax", "logits", "threshold", "score"]):
        return "confidence"
    if any(k in text_l for k in ["signal", "xadd", "publish", "action", "long", "short", "buy", "sell"]):
        return "signal_publish"
    if any(k in text_l for k in ["feature", "freshness", "stale", "ingest", "observation"]):
        return "feature_ingest"
    if any(k in text_l for k in ["mass", "state_space", "state", "tensor", "normalize"]):
        return "state_space"
    if any(k in text_l for k in ["checkpoint", "state_dict", "torch.save", "torch.load", "best_model", "promote"]):
        return "checkpoint"
    if any(k in text_l for k in ["redis", "xread", "xlen", "hset", "hget", "get(", "set("]):
        return "redis_io"
    if any(k in text_l for k in ["train", "optimizer", "backward", "epoch", "ppo", "masa"]):
        return "training_loop"
    if any(k in text_l for k in ["predict", "inference", "forward", "eval(", "action"]):
        return "inference_loop"
    if any(k in text_l for k in ["risk", "halt", "guard", "cooldown", "circuit"]):
        return "risk_metadata"
    if any(k in text_l for k in ["helper", "utility", "format", "logger", "print("]):
        return "dead_or_utility"
    return "unknown_quarantine"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trainer-file", required=True)
    ap.add_argument("--out-dir", default="./claude_worklog/trainer_atlas")
    ap.add_argument("--chunk-lines", type=int, default=1000)
    args = ap.parse_args()

    trainer = resolve_path(args.trainer_file, Path.cwd())
    out = resolve_path(args.out_dir, Path.cwd())
    out.mkdir(parents=True, exist_ok=True)

    lines = read_text_safely(trainer, max_bytes=200_000_000).splitlines()
    chunks = []
    chunk_size = max(100, args.chunk_lines)
    for idx, start in enumerate(range(1, len(lines) + 1, chunk_size), start=1):
        end = min(len(lines), start + chunk_size - 1)
        seg = lines[start - 1:end]
        txt = "\n".join(seg)
        txt_l = txt.lower()
        kws = sorted({k for k in KEYWORDS if k.lower() in txt.lower()})
        flags = []
        if any(k in kws for k in ["reward", "confidence", "signal", "orchestrator", "xadd", "publish", "checkpoint", "state_space", "MASS", "stale", "live", "paper", "risk", "position", "portfolio"]):
            flags.append("tier_a_touch")
        if any(k in kws for k in ["xadd", "publish"]):
            flags.append("redis_write_candidate")
        category = chunk_category(txt_l)
        tier = "Tier A" if flags or category != "unknown_quarantine" else "unclassified"
        chunks.append({
            "chunk_id": f"chunk_{idx:04d}",
            "line_start": start,
            "line_end": end,
            "sha256": sha256_text(txt),
            "keywords_found": kws,
            "risk_flags": flags,
            "chunk_category": category,
            "tier_candidate": tier,
            "verification_command": verification_command(str(trainer), start, end),
        })

    out_json = {
        "trainer_file": str(trainer),
        "line_count": len(lines),
        "chunk_lines": chunk_size,
        "chunks": chunks,
        "unclassified_chunks": sum(1 for c in chunks if c["tier_candidate"] == "unclassified"),
    }
    write_json(out / "HYBRID_TRAINER_CHUNKS.json", out_json)
    print(f"Wrote {len(chunks)} chunks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
