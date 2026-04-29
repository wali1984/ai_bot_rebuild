#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

from common_audit import iter_files, read_text_safely, relative_to, resolve_path, write_json, write_markdown, evidence_record, redact_text

PATS = {
    "os_getenv": re.compile(r"\bos\.getenv\s*\("),
    "os_environ": re.compile(r"\bos\.environ\b|\benviron\["),
    "dotenv": re.compile(r"dotenv|load_dotenv", re.IGNORECASE),
    "config_import": re.compile(r"from\s+config\s+import|import\s+config|\bconfig\."),
    "yaml_json_config": re.compile(r"\b(?:yaml|yml|json|toml|ini|cfg)\b", re.IGNORECASE),
}
ENV_KEY = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-root", default="./legacy_reference")
    ap.add_argument("--out-dir", default="./claude_worklog/coverage")
    args = ap.parse_args()
    legacy = resolve_path(args.legacy_root, Path.cwd())
    out = resolve_path(args.out_dir, Path.cwd())
    out.mkdir(parents=True, exist_ok=True)

    matches = []
    per_file = {}
    for f in iter_files(legacy):
        rel = relative_to(legacy, f)
        if f.suffix.lower() not in {".py", ".sh", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".md"}:
            continue
        try:
            text = read_text_safely(f)
        except Exception:
            continue
        env_keys = set()
        for i, line in enumerate(text.splitlines(), start=1):
            for name, pat in PATS.items():
                if pat.search(line):
                    matches.append({
                        "file": rel,
                        "line": i,
                        "kind": name,
                        "text": (redact_text(line.strip()[:500]) or ""),
                        "evidence": evidence_record(f"./legacy_reference/{rel}", i, line.strip()[:400], name, "config/env pattern"),
                    })
                    per_file.setdefault(rel, {"config_refs": 0, "env_refs": 0, "env_vars": set()})
                    per_file[rel]["config_refs"] += 1
                    if name in {"os_getenv", "os_environ", "dotenv"}:
                        per_file[rel]["env_refs"] += 1
            for key in ENV_KEY.findall(line):
                if len(key) > 3:
                    env_keys.add(key)
        if env_keys:
            per_file.setdefault(rel, {"config_refs": 0, "env_refs": 0, "env_vars": set()})
            per_file[rel]["env_vars"].update(env_keys)

    out_files = []
    for f, v in sorted(per_file.items()):
        out_files.append({"file": f, "config_refs": v["config_refs"], "env_refs": v["env_refs"], "env_vars": sorted(v["env_vars"])})
    data = {"matches": matches, "files": out_files}
    write_json(out / "CONFIG_ENV_MAP.json", data)

    md = ["# Config and Environment Map", "", f"Matches: {len(matches)}", "", "| file | config_refs | env_refs | env_var_count |", "|---|---:|---:|---:|"]
    for row in out_files[:500]:
        md.append(f"| {row['file']} | {row['config_refs']} | {row['env_refs']} | {len(row['env_vars'])} |")
    write_markdown(out / "CONFIG_ENV_MAP.md", "\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
