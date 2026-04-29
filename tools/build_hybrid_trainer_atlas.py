#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from common_audit import resolve_path, sha256_file, write_markdown, load_json, write_json


def run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")


def discover_candidates(legacy_root: Path):
    out = []
    for p in legacy_root.rglob("*trainer*.py"):
        if not p.is_file():
            continue
        rel = str(p.relative_to(legacy_root)).replace("\\", "/")
        lines = sum(1 for _ in p.open("r", encoding="utf-8", errors="replace"))
        likely = rel == "rl/hybrid_trainer.py" or p.name == "hybrid_trainer.py"
        reason = "matches runtime module rl.hybrid_trainer" if likely else "trainer-like filename"
        out.append({"path": rel, "line_count": lines, "size": p.stat().st_size, "sha256": sha256_file(p), "likely_primary": likely, "reason": reason})
    out.sort(key=lambda x: (not x["likely_primary"], -x["line_count"]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-root", default="./legacy_reference")
    ap.add_argument("--trainer-file", default="")
    ap.add_argument("--out-dir", default="./claude_worklog/trainer_atlas")
    args = ap.parse_args()

    legacy = resolve_path(args.legacy_root, Path.cwd())
    out = resolve_path(args.out_dir, Path.cwd())
    out.mkdir(parents=True, exist_ok=True)

    cands = discover_candidates(legacy)
    if not cands:
        write_markdown(out / "TRAINER_CANDIDATES.md", "# Trainer Candidates\n\nNo candidates found.\n")
        write_markdown(out / "HYBRID_TRAINER_COVERAGE_REPORT.md", "# Hybrid Trainer Coverage Report\n\nNO-GO: no trainer candidates found.\n")
        return 2

    lines = ["# Trainer Candidates", "", "| path | lines | size | sha256 | likely primary | reason |", "|---|---:|---:|---|---|---|"]
    for c in cands:
        lines.append(f"| {c['path']} | {c['line_count']} | {c['size']} | {c['sha256'][:16]}... | {c['likely_primary']} | {c['reason']} |")
    write_markdown(out / "TRAINER_CANDIDATES.md", "\n".join(lines))

    if args.trainer_file:
        trainer = resolve_path(args.trainer_file, Path.cwd())
    else:
        default = legacy / "rl" / "hybrid_trainer.py"
        trainer = default if default.exists() else (legacy / cands[0]["path"])

    scripts = [
        "split_hybrid_trainer.py",
        "index_hybrid_trainer_ast.py",
        "extract_trainer_imports.py",
        "extract_trainer_functions.py",
        "extract_trainer_classes.py",
        "extract_trainer_redis_usage.py",
        "extract_trainer_config_usage.py",
        "extract_trainer_signal_paths.py",
        "extract_trainer_reward_paths.py",
        "extract_trainer_confidence_paths.py",
        "extract_trainer_feature_paths.py",
        "extract_trainer_checkpoint_paths.py",
        "extract_trainer_entrypoints.py",
    ]

    run_logs = []
    py = "python3"
    tools_dir = Path(__file__).resolve().parent
    for s in scripts:
        cmd = [py, str(tools_dir / s), "--trainer-file", str(trainer), "--out-dir", str(out)]
        if s == "split_hybrid_trainer.py":
            cmd += ["--chunk-lines", "1000"]
        rc, txt = run(cmd)
        run_logs.append({"tool": s, "rc": rc, "output": txt[-2000:]})

    chunks = load_json(out / "HYBRID_TRAINER_CHUNKS.json", {})
    signal = load_json(out / "HYBRID_TRAINER_SIGNAL_PATHS.json", {})
    reward = load_json(out / "HYBRID_TRAINER_REWARD_PATHS.json", {})
    conf = load_json(out / "HYBRID_TRAINER_CONFIDENCE_PATHS.json", {})
    redis = load_json(out / "HYBRID_TRAINER_REDIS_USAGE.json", {})

    unclassified_chunks = chunks.get("unclassified_chunks", 0)
    unknown_signal = signal.get("unknown_signal_paths", 1)
    unknown_reward = reward.get("unknown_reward_paths", 1)
    unknown_conf = conf.get("unknown_confidence_paths", 1)
    unknown_redis = redis.get("unknown_redis_writes", 1)

    chunk_rows = [
        "# Hybrid Trainer Chunk Classification",
        "",
        "| chunk_id | lines | category | tier | risk_flags |",
        "|---|---|---|---|---|",
    ]
    for c in chunks.get("chunks", []):
        chunk_rows.append(
            f"| {c.get('chunk_id')} | {c.get('line_start')}-{c.get('line_end')} | {c.get('chunk_category','unknown_quarantine')} | {c.get('tier_candidate')} | {','.join(c.get('risk_flags',[])) or '-'} |"
        )
    write_markdown(out / "HYBRID_TRAINER_CHUNK_CLASSIFICATION.md", "\n".join(chunk_rows))

    redis_rows = [
        "# Hybrid Trainer Redis Write Classification",
        "",
        "| line | classification | text |",
        "|---:|---|---|",
    ]
    for m in redis.get("matches", []):
        cls = m.get("classification", "read_only")
        redis_rows.append(f"| {m.get('line')} | {cls} | {str(m.get('text','')).replace('|','/')} |")
    write_markdown(out / "HYBRID_TRAINER_REDIS_WRITE_CLASSIFICATION.md", "\n".join(redis_rows))

    reasons = []
    if unclassified_chunks > 0: reasons.append("unclassified chunks > 0")
    if unknown_signal > 0: reasons.append("unknown signal paths > 0")
    if unknown_reward > 0: reasons.append("unknown reward paths > 0")
    if unknown_conf > 0: reasons.append("unknown confidence paths > 0")
    if unknown_redis > 0: reasons.append("unknown Redis writes > 0")
    decision = "NO-GO" if reasons else "GO"

    atlas = [
        "# Hybrid Trainer Atlas",
        "",
        f"Selected trainer: {trainer}",
        f"Line count: {chunks.get('line_count', 'unknown')}",
        f"Chunks: {len(chunks.get('chunks', []))}",
        "",
        "## Tool runs",
    ]
    for r in run_logs:
        atlas.append(f"- {r['tool']}: rc={r['rc']}")
    write_markdown(out / "HYBRID_TRAINER_ATLAS.md", "\n".join(atlas))

    cov = ["# Hybrid Trainer Coverage Report", "", f"Decision: **{decision}**", "", f"- unclassified_chunks: {unclassified_chunks}", f"- unknown_signal_paths: {unknown_signal}", f"- unknown_reward_paths: {unknown_reward}", f"- unknown_confidence_paths: {unknown_conf}", f"- unknown_redis_writes: {unknown_redis}", "", "## Reasons"] + [f"- {r}" for r in reasons]
    write_markdown(out / "HYBRID_TRAINER_COVERAGE_REPORT.md", "\n".join(cov))

    tier_plan = [
        "# Hybrid Trainer Tier A Review Plan",
        "",
        "Tier A criteria include chunks/functions touching:",
        "- reward",
        "- MASS/state-space",
        "- feature freshness",
        "- confidence",
        "- prediction",
        "- signal",
        "- orchestrator",
        "- Redis write",
        "- checkpoint promotion",
        "- trainer_stale",
        "- live/paper mode",
        "- risk metadata",
        "- price data",
        "- portfolio data",
        "- position data",
        "",
        "Use tools/show_trainer_section.py for raw verification of Tier A sections.",
    ]
    write_markdown(out / "HYBRID_TRAINER_TIER_A_REVIEW_PLAN.md", "\n".join(tier_plan))

    write_json(out / "HYBRID_TRAINER_ATLAS_RUN_LOG.json", {"trainer": str(trainer), "tool_runs": run_logs, "decision": decision, "reasons": reasons})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
