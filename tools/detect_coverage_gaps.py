#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from common_audit import load_json, resolve_path, write_json, write_markdown

REQUIRED = [
    "FILE_MANIFEST.json",
    "IMPORT_GRAPH.json",
    "STARTUP_PATH_MAP.json",
    "REDIS_USAGE_MAP.json",
    "EXCHANGE_ACTION_MAP.json",
    "CONFIG_ENV_MAP.json",
    "RUNTIME_PROCESS_MAP.json",
    "SCRIPT_REGISTRY.json",
    "TIER_A_SCRIPT_CLASSIFICATION.md",
    "TIER_A_RAW_REVIEW_PLAN.json",
]


def _plan_entries(plan: dict) -> list[dict]:
    return plan.get("entries") or plan.get("items") or []


def _has_plan_coverage(entries: list[dict], file: str, line: int) -> bool:
    for e in entries:
        ef = str(e.get("file") or "")
        s = int(e.get("start_line") or 0)
        en = int(e.get("end_line") or 0)
        vc = str(e.get("verification_command") or "")
        if ef == file and s > 0 and en >= s and vc and s <= line <= en:
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coverage-dir", default="./claude_worklog/coverage")
    ap.add_argument("--out-dir", default="./claude_worklog/coverage")
    args = ap.parse_args()

    cov = resolve_path(args.coverage_dir, Path.cwd())
    out = resolve_path(args.out_dir, Path.cwd())
    out.mkdir(parents=True, exist_ok=True)

    missing = [f for f in REQUIRED if not (cov / f).exists()]

    mf = load_json(cov / "FILE_MANIFEST.json", {"files": []})
    sr = load_json(cov / "SCRIPT_REGISTRY.json", {"scripts": []})
    ex = load_json(cov / "EXCHANGE_ACTION_MAP.json", {"matches": []})
    ru = load_json(cov / "REDIS_USAGE_MAP.json", {"matches": [], "files": []})
    rp = load_json(cov / "RUNTIME_PROCESS_MAP.json", {"unmapped_bot_like_processes": [], "processes": []})
    plan = load_json(cov / "TIER_A_RAW_REVIEW_PLAN.json", {"entries": []})

    scripts = sr.get("scripts", [])
    script_by_path = {s.get("path"): s for s in scripts}

    unsafe_unknown = [
        s for s in scripts if s.get("classification_candidate") in {"unsafe_unknown", "quarantine_unknown"}
    ]
    tier_a = [s for s in scripts if s.get("tier") == "Tier A"]
    code_files = [f for f in mf.get("files", []) if f.get("category") == "code"]
    script_files = [f for f in mf.get("files", []) if f.get("category") in {"code", "shell"}]

    matches = ex.get("matches", [])
    exch_missing_evidence = [m for m in matches if not m.get("evidence")]
    exch_script_files = sorted(
        set(
            m.get("file")
            for m in matches
            if str(m.get("file", "")).endswith((".py", ".sh", ".bash", ".zsh", ".js", ".ts", ".tsx", ".jsx"))
        )
    )
    exch_unclassified = [p for p in exch_script_files if p and not script_by_path.get(p)]

    redis_writers = [m for m in ru.get("matches", []) if m.get("classification") == "redis_write"]
    redis_missing_evidence = [m for m in redis_writers if not m.get("evidence")]

    plan_entries = _plan_entries(plan)
    unresolved = [
        m
        for m in matches
        if (m.get("classification") == "exchange_unresolved_tier_a_review")
        or ("exchange_unresolved_tier_a_review" in (m.get("classifications") or []))
    ]

    unresolved_missing_plan = []
    for m in unresolved:
        file = str(m.get("file") or "")
        line = int(m.get("line") or 0)
        if not file or line <= 0 or not _has_plan_coverage(plan_entries, file, line):
            unresolved_missing_plan.append(m)

    unknown_total = 0
    blocking_unknown = int(ex.get("blocking_unknown_exchange_use_count") or 0)
    for m in matches:
        cls = m.get("classification") or ""
        clss = m.get("classifications") or []
        if cls == "unknown_exchange_use" or "unknown_exchange_use" in clss:
            unknown_total += 1
            if m.get("is_blocking_unknown", True):
                blocking_unknown += 0  # already emitted by collector metric

    summary = {
        "total_files": len(mf.get("files", [])),
        "total_code_files": len(code_files),
        "total_scripts": len(script_files),
        "classified_scripts": len(scripts),
        "unsafe_unknown_count": len(unsafe_unknown),
        "unsafe_unknown_canonical_label": "unsafe_unknown",
        "tier_a_count": len(tier_a),
        "exchange_action_files": len(set(m.get("file") for m in matches)),
        "redis_writer_files": len(set(m.get("file") for m in redis_writers)),
        "runtime_mapped_count": sum(1 for p in rp.get("processes", []) if p.get("mapped_status") == "mapped"),
        "unmapped_bot_looking_runtime_processes": len(rp.get("unmapped_bot_like_processes", [])),
        "exchange_script_files_unclassified": len(exch_unclassified),
        "unknown_exchange_use_count": unknown_total,
        "blocking_unknown_exchange_use_count": int(ex.get("blocking_unknown_exchange_use_count") or 0),
        "exchange_unresolved_tier_a_review_count": int(ex.get("exchange_unresolved_tier_a_review_count") or 0),
        "exchange_unresolved_missing_tier_a_plan_count": len(unresolved_missing_plan),
        "missing_artifacts": missing,
    }

    no_go_reasons = []
    if missing:
        no_go_reasons.append("missing required artifact")
    if len(unsafe_unknown) > 0:
        no_go_reasons.append("unsafe_unknown > 0")
    if int(ex.get("blocking_unknown_exchange_use_count") or 0) > 0:
        no_go_reasons.append("blocking_unknown_exchange_use_count > 0")
    if summary["unmapped_bot_looking_runtime_processes"] > 0:
        no_go_reasons.append("unmapped bot-looking runtime process > 0")
    if exch_missing_evidence:
        no_go_reasons.append("exchange execution file missing raw evidence")
    if redis_missing_evidence:
        no_go_reasons.append("Redis writer missing raw evidence")
    if unresolved_missing_plan:
        no_go_reasons.append("exchange_unresolved_tier_a_review missing Tier A raw review coverage")
    if exch_unclassified:
        no_go_reasons.append("exchange-action script lacks classification")

    status = "NO-GO" if no_go_reasons else "GO"
    summary["decision"] = status
    summary["reasons"] = no_go_reasons

    write_json(out / "COVERAGE_SUMMARY.json", summary)

    md = ["# Coverage Summary", "", f"Decision: **{status}**", "", "## Metrics"]
    for k, v in summary.items():
        if k in {"reasons", "missing_artifacts"}:
            continue
        md.append(f"- {k}: {v}")

    md += ["", "## Taxonomy", "- Canonical unknown-risk class: `unsafe_unknown`.", "- Legacy alias handling is normalized to `unsafe_unknown` during gap detection."]
    md += ["", "## Missing artifacts"]
    for m in missing:
        md.append(f"- {m}")

    md += ["", "## NO-GO reasons"]
    for r in no_go_reasons:
        md.append(f"- {r}")

    if status == "GO":
        md += [
            "",
            "## Gate rationale",
            "- GO for Claude Phase 1 rerun because unresolved exchange logic is evidence-backed and queued for Tier A raw review.",
        ]

    write_markdown(out / "COVERAGE_SUMMARY.md", "\n".join(md))

    ug = ["# Unknown Gaps", "", "Canonical class: unsafe_unknown", ""]
    for s in unsafe_unknown:
        ug.append(f"- unsafe_unknown: {s.get('path')} ({s.get('classification_reason')})")
    write_markdown(out / "UNKNOWN_GAPS.md", "\n".join(ug))

    go = ["# GO/NO-GO Coverage", "", f"Decision: **{status}**"]
    for r in no_go_reasons:
        go.append(f"- {r}")
    if status == "GO":
        go.append("- GO for Claude Phase 1 rerun because unresolved exchange logic is evidence-backed and queued for Tier A raw review.")
    write_markdown(out / "GO_NO_GO_COVERAGE.md", "\n".join(go))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
