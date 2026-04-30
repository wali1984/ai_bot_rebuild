#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from common_audit import load_json, resolve_path, write_json, write_markdown


def _merge_lines(lines: list[int], max_gap: int = 15, max_span: int = 250) -> list[tuple[int, int]]:
    if not lines:
        return []
    vals = sorted(set(int(x) for x in lines if int(x) > 0))
    out: list[tuple[int, int]] = []
    s = vals[0]
    e = vals[0]
    for n in vals[1:]:
        if (n - e) <= max_gap and (n - s) <= max_span:
            e = n
        else:
            out.append((s, e))
            s = e = n
    out.append((s, e))
    return out


def _review_id(idx: int) -> str:
    return f"tier_a_{idx:05d}"


def _expected_question(category: str) -> str:
    return {
        "exchange_execution": "Does this range place/cancel/submit executable orders?",
        "leverage_margin": "Does this range mutate leverage or margin mode?",
        "stops_take_profit": "Are stop/take-profit actions explicit and safely constrained?",
        "redis_write": "Does this range write trading/position/execution state to Redis?",
        "trainer_reward": "How does this range shape reward and penalties?",
        "trainer_confidence": "How is confidence produced and gated in this range?",
        "trainer_signal": "Does this range publish/shape tradable signals?",
        "trainer_feature_state_mass": "How are features/state/MASS formed and validated here?",
        "trainer_checkpoint": "Does this range save/load/promote checkpoints?",
        "orchestrator_risk": "Does this range enforce/override allow-block risk decisions?",
        "trader_execution": "How is signal-to-order execution handled here?",
    }.get(category, "What safety-critical behavior does this range implement?")


def main() -> int:
    root = Path.cwd()
    coverage = resolve_path("./claude_worklog/coverage", root)
    atlas = resolve_path("./claude_worklog/trainer_atlas", root)
    legacy = resolve_path("./legacy_reference", root)

    script_registry = load_json(coverage / "SCRIPT_REGISTRY.json", {"scripts": []})
    exchange_map = load_json(coverage / "EXCHANGE_ACTION_MAP.json", {"matches": []})
    redis_map = load_json(coverage / "REDIS_USAGE_MAP.json", {"matches": []})
    chunks = load_json(atlas / "HYBRID_TRAINER_CHUNKS.json", {"chunks": []})
    reward_paths = load_json(atlas / "HYBRID_TRAINER_REWARD_PATHS.json", {"matches": []})
    confidence_paths = load_json(atlas / "HYBRID_TRAINER_CONFIDENCE_PATHS.json", {"matches": []})
    signal_paths = load_json(atlas / "HYBRID_TRAINER_SIGNAL_PATHS.json", {"matches": []})
    feature_paths = load_json(atlas / "HYBRID_TRAINER_FEATURE_PATHS.json", {"matches": []})
    checkpoint_paths = load_json(atlas / "HYBRID_TRAINER_CHECKPOINT_PATHS.json", {"matches": []})
    trainer_redis_usage = load_json(atlas / "HYBRID_TRAINER_REDIS_USAGE.json", {"matches": []})

    trainer_file = str((legacy / "rl/hybrid_trainer.py").resolve())
    trainer_rel = "rl/hybrid_trainer.py"

    active_tier_a_files = {
        str(s.get("path"))
        for s in script_registry.get("scripts", [])
        if str(s.get("tier")) == "Tier A" and str(s.get("classification_candidate")) != "legacy_dead"
    }

    entries: list[dict[str, Any]] = []

    def add_entry(file: str, start: int, end: int, reason: str, category: str, priority: str, source_artifact: str) -> None:
        if start <= 0 or end < start:
            return
        if file in {trainer_rel, trainer_file}:
            cmd = f"python3 tools/show_trainer_section.py --trainer-file ./legacy_reference/{trainer_rel} --start {start} --end {end}"
        else:
            cmd = f"python3 tools/show_file_range.py --file ./legacy_reference/{file} --start {start} --end {end}"
        entries.append(
            {
                "review_id": _review_id(len(entries) + 1),
                "file": file,
                "start_line": int(start),
                "end_line": int(end),
                "reason": reason,
                "category": category,
                "priority": priority,
                "evidence_source_artifact": source_artifact,
                "verification_command": cmd,
                "expected_review_question": _expected_question(category),
            }
        )

    # Exchange-action derived P0/P1 entries.
    exchange_lines: dict[tuple[str, str], list[int]] = defaultdict(list)
    for m in exchange_map.get("matches", []):
        file = str(m.get("file") or "")
        cls = str(m.get("classification") or (m.get("classifications") or ["unknown_exchange_use"])[0])
        line = int(m.get("line") or 0)
        if not file or line <= 0:
            continue
        if active_tier_a_files and file not in active_tier_a_files and file != trainer_rel:
            continue
        exchange_lines[(file, cls)].append(line)

    category_map = {
        "order_create": ("exchange_execution", "P0"),
        "order_cancel": ("exchange_execution", "P0"),
        "leverage_change": ("leverage_margin", "P0"),
        "margin_change": ("leverage_margin", "P0"),
        "stop_loss": ("stops_take_profit", "P0"),
        "take_profit": ("stops_take_profit", "P0"),
        "reduce_only": ("stops_take_profit", "P0"),
        "position_query": ("exchange_execution", "P1"),
        "balance_query": ("exchange_execution", "P1"),
        "unknown_exchange_use": ("exchange_execution", "P0"),
        "exchange_client_init": ("exchange_execution", "P1"),
        "market_data": ("exchange_execution", "P2"),
    }

    for (file, cls), lines in sorted(exchange_lines.items()):
        category, priority = category_map.get(cls, ("exchange_execution", "P2"))
        for s, e in _merge_lines(lines):
            add_entry(
                file=file,
                start=max(1, s - 3),
                end=e + 3,
                reason=f"{cls} coverage cluster",
                category=category,
                priority=priority,
                source_artifact="claude_worklog/coverage/EXCHANGE_ACTION_MAP.json",
            )

    # Redis writer ranges.
    redis_lines: dict[str, list[int]] = defaultdict(list)
    for m in redis_map.get("matches", []):
        if str(m.get("classification")) != "redis_write":
            continue
        file = str(m.get("file") or "")
        line = int(m.get("line") or 0)
        if file and line > 0:
            if active_tier_a_files and file not in active_tier_a_files and file != trainer_rel:
                continue
            redis_lines[file].append(line)
    for file, lines in sorted(redis_lines.items()):
        for s, e in _merge_lines(lines):
            add_entry(
                file=file,
                start=max(1, s - 2),
                end=e + 2,
                reason="redis write cluster",
                category="redis_write",
                priority="P0",
                source_artifact="claude_worklog/coverage/REDIS_USAGE_MAP.json",
            )

    # Trainer extractors.
    trainer_paths = [
        (reward_paths, "trainer_reward", "P0", "claude_worklog/trainer_atlas/HYBRID_TRAINER_REWARD_PATHS.json"),
        (confidence_paths, "trainer_confidence", "P0", "claude_worklog/trainer_atlas/HYBRID_TRAINER_CONFIDENCE_PATHS.json"),
        (signal_paths, "trainer_signal", "P0", "claude_worklog/trainer_atlas/HYBRID_TRAINER_SIGNAL_PATHS.json"),
        (feature_paths, "trainer_feature_state_mass", "P0", "claude_worklog/trainer_atlas/HYBRID_TRAINER_FEATURE_PATHS.json"),
        (checkpoint_paths, "trainer_checkpoint", "P0", "claude_worklog/trainer_atlas/HYBRID_TRAINER_CHECKPOINT_PATHS.json"),
    ]
    for data, category, priority, src in trainer_paths:
        lines = [int(m.get("line") or 0) for m in data.get("matches", []) if int(m.get("line") or 0) > 0]
        for s, e in _merge_lines(lines):
            add_entry(
                file=trainer_rel,
                start=max(1, s - 3),
                end=e + 3,
                reason=f"{category} extracted line cluster",
                category=category,
                priority=priority,
                source_artifact=src,
            )

    # Trainer redis ranges.
    t_redis_lines = [int(m.get("line") or 0) for m in trainer_redis_usage.get("matches", []) if int(m.get("line") or 0) > 0 and str(m.get("classification")) != "read_only"]
    for s, e in _merge_lines(t_redis_lines):
        add_entry(
                file=trainer_rel,
            start=max(1, s - 2),
            end=e + 2,
            reason="trainer redis non-read-only cluster",
            category="redis_write",
            priority="P0",
            source_artifact="claude_worklog/trainer_atlas/HYBRID_TRAINER_REDIS_USAGE.json",
        )

    # Orchestrator/trader/risk explicit searches for handoff and gating.
    explicit_targets = [
        ("rl/orchestrator_worker.py", ["signals:trading", "xadd", "publish", "route"], "orchestrator_risk", "P0"),
        ("risk/assertions.py", ["assert_risk", "block", "allow", "risk"], "orchestrator_risk", "P0"),
        ("risk/halt_manager.py", ["halt", "block", "allow"], "orchestrator_risk", "P0"),
        ("trading/trader.py", ["_execute_", "create_order", "cancel_order"], "trader_execution", "P0"),
    ]
    for rel, keys, category, priority in explicit_targets:
        p = legacy / rel
        if not p.exists():
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        hit_lines: list[int] = []
        for i, line in enumerate(lines, start=1):
            ll = line.lower()
            if any(k.lower() in ll for k in keys):
                hit_lines.append(i)
        for s, e in _merge_lines(hit_lines):
            add_entry(
                file=rel,
                start=max(1, s - 3),
                end=e + 3,
                reason=f"explicit target keys: {', '.join(keys[:3])}",
                category=category,
                priority=priority,
                source_artifact="explicit_keyword_scan",
            )

    # Keep ordering stable.
    entries = sorted(entries, key=lambda x: (x["priority"], x["file"], int(x["start_line"]), int(x["end_line"])))
    for i, e in enumerate(entries, start=1):
        e["review_id"] = _review_id(i)

    counts = Counter(e["priority"] for e in entries)
    out_json = {
        "total_entries": len(entries),
        "priority_counts": dict(counts),
        "entries": entries,
    }

    write_json(coverage / "TIER_A_RAW_REVIEW_PLAN.json", out_json)

    md = [
        "# Tier A Raw Review Plan",
        "",
        f"Total entries: {len(entries)}",
        f"Priority counts: P0={counts.get('P0', 0)} P1={counts.get('P1', 0)} P2={counts.get('P2', 0)}",
        "",
        "| review_id | category | priority | file | range | reason |",
        "|---|---|---|---|---|---|",
    ]
    for e in entries:
        md.append(
            f"| {e['review_id']} | {e['category']} | {e['priority']} | {e['file']} | {e['start_line']}-{e['end_line']} | {str(e['reason']).replace('|','/')} |"
        )
    md.append("")
    md.append("## Commands")
    for e in entries:
        md.append(f"- {e['review_id']}: {e['verification_command']}")
    write_markdown(coverage / "TIER_A_RAW_REVIEW_PLAN.md", "\n".join(md))

    phase_md = [
        "# Claude Phase 1 Tier A Raw Review Plan",
        "",
        f"Generated from deterministic artifacts. Entries: {len(entries)}",
        f"P0={counts.get('P0', 0)} P1={counts.get('P1', 0)} P2={counts.get('P2', 0)}",
        "",
    ]
    phase_md += md[5:]
    write_markdown(resolve_path("./claude_worklog/CLAUDE_PHASE1_TIER_A_RAW_REVIEW_PLAN.md", root), "\n".join(phase_md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
