#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

from common_audit import iter_files, read_text_safely, relative_to, resolve_path, write_json, write_markdown, evidence_record, redact_text

CMD_PATTERNS = [
    ("python_module", re.compile(r"\bpython\d*\s+-m\s+([\w\.]+)")),
    ("python_script", re.compile(r"\bpython\d*\s+([^\s]+\.py)")),
    ("node", re.compile(r"\bnode\s+([^\s]+)")),
    ("npm", re.compile(r"\bnpm\s+(run\s+\S+|start|test|build)")),
    ("bash", re.compile(r"\b(?:bash|sh)\s+([^\s]+)")),
]
SCRIPT_REF = re.compile(r"([\w./-]+\.(?:py|sh|bash|zsh|js|ts))")


def file_kind(rel: str) -> str:
    r = rel.lower()
    if "docker-compose" in r or r.endswith("dockerfile"):
        return "docker"
    if r.endswith(".service") or "systemd" in r:
        return "systemd"
    if "supervisor" in r:
        return "supervisor"
    if "tmux" in r:
        return "tmux"
    if r.endswith("makefile") or r.endswith(".mk"):
        return "make"
    if r.endswith(".md") or r.endswith(".txt"):
        return "docs"
    if r.endswith(".sh") or r.endswith(".bash"):
        return "shell"
    return "other"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-root", default="./legacy_reference")
    ap.add_argument("--out-dir", default="./claude_worklog/coverage")
    args = ap.parse_args()
    legacy = resolve_path(args.legacy_root, Path.cwd())
    out = resolve_path(args.out_dir, Path.cwd())
    out.mkdir(parents=True, exist_ok=True)

    refs = []
    for f in iter_files(legacy):
        rel = relative_to(legacy, f)
        fk = file_kind(rel)
        if fk == "other":
            continue
        try:
            text = read_text_safely(f)
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            for kind, rx in CMD_PATTERNS:
                m = rx.search(line)
                if m:
                    refs.append({
                        "source_file": rel,
                        "source_kind": fk,
                        "line": i,
                        "detected_kind": kind,
                        "command_fragment": (redact_text(line.strip()[:500]) or ""),
                        "module_or_target": m.group(1),
                        "evidence": evidence_record(f"./legacy_reference/{rel}", i, line.strip()[:400], "startup_ref", f"matched {kind}"),
                    })
            for m in SCRIPT_REF.finditer(line):
                refs.append({
                    "source_file": rel,
                    "source_kind": fk,
                    "line": i,
                    "detected_kind": "script_reference",
                    "command_fragment": (redact_text(line.strip()[:500]) or ""),
                    "module_or_target": m.group(1),
                    "evidence": evidence_record(f"./legacy_reference/{rel}", i, m.group(1), "startup_ref", "script path token"),
                })

    data = {"startup_references": refs}
    write_json(out / "STARTUP_PATH_MAP.json", data)

    md = ["# Startup Path Map", "", f"Total references: {len(refs)}", "", "| source | kind | line | detected | target |", "|---|---|---:|---|---|"]
    for r in refs[:300]:
        md.append(f"| {r['source_file']} | {r['source_kind']} | {r['line']} | {r['detected_kind']} | {str(r['module_or_target']).replace('|','/')} |")
    write_markdown(out / "STARTUP_PATH_MAP.md", "\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
