#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from collections import Counter

from common_audit import (
    classify_category,
    classify_language,
    is_secret_path,
    iter_files,
    relative_to,
    resolve_path,
    sha256_file,
    verification_command,
    write_json,
    write_markdown,
)


def main() -> int:
    p = argparse.ArgumentParser(description="Collect deterministic file manifest")
    p.add_argument("--legacy-root", default="./legacy_reference")
    p.add_argument("--out-dir", default="./claude_worklog/coverage")
    args = p.parse_args()

    legacy_root = resolve_path(args.legacy_root, Path.cwd())
    out_dir = resolve_path(args.out_dir, Path.cwd())
    out_dir.mkdir(parents=True, exist_ok=True)

    records = []
    counters = Counter()

    for f in iter_files(legacy_root):
        try:
            st = f.lstat()
        except Exception:
            continue
        rel = relative_to(legacy_root, f)
        ext = f.suffix.lower()
        executable = bool(st.st_mode & 0o111)
        symlink = f.is_symlink()
        shebang = ""
        if f.is_file():
            try:
                with f.open("rb") as fh:
                    first = fh.readline(300).decode("utf-8", errors="replace").strip()
                shebang = first if first.startswith("#!") else ""
            except Exception:
                shebang = ""
        language = classify_language(f)
        category = classify_category(f, language)
        skipped_secret = is_secret_path(f)
        reason = f"language={language} mapped to category={category}"
        verify = verification_command(f"./legacy_reference/{rel}", 1, 5)
        rec = {
            "relative_path": rel,
            "absolute_path": str(f.resolve()),
            "extension": ext,
            "size_bytes": st.st_size,
            "sha256": sha256_file(f) if f.is_file() and not symlink else None,
            "executable": executable,
            "symlink": symlink,
            "shebang": shebang,
            "language": language,
            "category": category,
            "skipped_secret": skipped_secret,
            "classification_reason": reason,
            "verification_command": verify,
            "evidence": {
                "source_file": f"./legacy_reference/{rel}",
                "line": 1,
                "matched_text": shebang or "file metadata",
                "kind": "file_manifest",
                "classification_reason": reason,
                "verification_command": verify,
            },
        }
        records.append(rec)
        counters["total"] += 1
        counters[category] += 1
        if language in {"python", "shell", "javascript", "typescript", "make"}:
            counters["scripts"] += 1

    records.sort(key=lambda x: x["relative_path"])
    out_json = {"legacy_root": str(legacy_root), "totals": dict(counters), "files": records}
    write_json(out_dir / "FILE_MANIFEST.json", out_json)

    md = ["# File Manifest", "", f"Legacy root: {legacy_root}", "", "## Totals"]
    md += [
        f"- total files: {counters.get('total',0)}",
        f"- code files: {counters.get('code',0)}",
        f"- scripts: {counters.get('scripts',0)}",
        f"- configs: {counters.get('config',0)}",
        f"- docs: {counters.get('docs',0)}",
        f"- binaries: {counters.get('binary',0)}",
        f"- models/data: {counters.get('model',0)+counters.get('data',0)}",
        f"- unknowns: {counters.get('unknown',0)}",
        "",
        "## Sample entries",
        "",
        "| path | category | lang | size | exec |",
        "|---|---|---:|---:|---:|",
    ]
    for r in records[:100]:
        md.append(f"| {r['relative_path']} | {r['category']} | {r['language']} | {r['size_bytes']} | {r['executable']} |")
    write_markdown(out_dir / "FILE_MANIFEST.md", "\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
