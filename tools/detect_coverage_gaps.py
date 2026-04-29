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
]


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
    rp = load_json(cov / "RUNTIME_PROCESS_MAP.json", {"unmapped_bot_like_processes": []})

    scripts = sr.get("scripts", [])
    script_by_path = {s.get("path"): s for s in scripts}
    unsafe_unknown = [s for s in scripts if s.get("classification_candidate") == "unsafe_unknown"]
    tier_a = [s for s in scripts if s.get("tier") == "Tier A"]
    code_files = [f for f in mf.get("files", []) if f.get("category") == "code"]
    script_files = [f for f in mf.get("files", []) if f.get("category") in {"code", "shell"}]

    exch_missing_evidence = [m for m in ex.get("matches", []) if not m.get("evidence")]
    exch_script_files = sorted(set(m.get("file") for m in ex.get("matches", []) if str(m.get("file", "")).endswith((".py", ".sh", ".bash", ".zsh", ".js", ".ts", ".tsx", ".jsx"))))
    exch_unclassified = [p for p in exch_script_files if not script_by_path.get(p)]
    redis_writers = [m for m in ru.get("matches", []) if m.get("classification") == "redis_write"]
    redis_missing_evidence = [m for m in redis_writers if not m.get("evidence")]

    summary = {
        "total_files": len(mf.get("files", [])),
        "total_code_files": len(code_files),
        "total_scripts": len(script_files),
        "classified_scripts": len(scripts),
        "unsafe_unknown_count": len(unsafe_unknown),
        "tier_a_count": len(tier_a),
        "exchange_action_files": len(set(m.get("file") for m in ex.get("matches", []))),
        "redis_writer_files": len(set(m.get("file") for m in redis_writers)),
        "runtime_mapped_count": sum(1 for p in load_json(cov / "RUNTIME_PROCESS_MAP.json", {"processes": []}).get("processes", []) if p.get("mapped_status") == "mapped"),
        "unmapped_bot_looking_runtime_processes": len(rp.get("unmapped_bot_like_processes", [])),
        "exchange_script_files_unclassified": len(exch_unclassified),
        "missing_artifacts": missing,
    }

    no_go_reasons = []
    if missing:
        no_go_reasons.append("missing required artifact")
    if len(unsafe_unknown) > 0:
        no_go_reasons.append("unsafe_unknown > 0")
    if summary["unmapped_bot_looking_runtime_processes"] > 0:
        no_go_reasons.append("unmapped bot-looking runtime process > 0")
    if exch_missing_evidence:
        no_go_reasons.append("exchange action file missing evidence")
    if exch_unclassified:
        no_go_reasons.append("exchange-action script lacks classification")
    if redis_missing_evidence:
        no_go_reasons.append("Redis writer missing evidence")

    status = "NO-GO" if no_go_reasons else "GO"
    summary["decision"] = status
    summary["reasons"] = no_go_reasons

    write_json(out / "COVERAGE_SUMMARY.json", summary)

    md = ["# Coverage Summary", "", f"Decision: **{status}**", "", "## Metrics"]
    for k, v in summary.items():
        if k in {"reasons", "missing_artifacts"}:
            continue
        md.append(f"- {k}: {v}")
    md.append("")
    md.append("## Missing artifacts")
    for m in missing:
        md.append(f"- {m}")
    md.append("")
    md.append("## NO-GO reasons")
    for r in no_go_reasons:
        md.append(f"- {r}")
    if exch_unclassified:
        md.append("")
        md.append("## Exchange script files missing classification")
        for p in exch_unclassified[:500]:
            md.append(f"- {p}")

    write_markdown(out / "COVERAGE_SUMMARY.md", "\n".join(md))
    write_markdown(out / "UNKNOWN_GAPS.md", "\n".join(["# Unknown Gaps", ""] + [f"- unsafe_unknown: {s.get('path')} ({s.get('classification_reason')})" for s in unsafe_unknown]))
    write_markdown(out / "GO_NO_GO_COVERAGE.md", "\n".join(["# GO/NO-GO Coverage", "", f"Decision: **{status}**"] + [f"- {r}" for r in no_go_reasons]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
