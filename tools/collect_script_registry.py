#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Dict, Set

from common_audit import load_json, resolve_path, write_json, write_markdown


def sid(path: str) -> str:
    return "script_" + hashlib.sha1(path.encode("utf-8")).hexdigest()[:12]


def is_build_artifact(path: str) -> bool:
    p = path.lower()
    return any(
        tok in p
        for tok in [
            "/.next/",
            "/node_modules/",
            "/dist/",
            "/build/",
            "/coverage/",
            "__pycache__",
            "/.pytest_cache/",
        ]
    )


def is_archived(path: str) -> bool:
    p = path.lower()
    return any(tok in p for tok in ["/.backups/", "/backups/", "/archive/"])


def script_like(rel: str, language: str) -> bool:
    ext = Path(rel).suffix.lower()
    return language in {"python", "javascript", "typescript", "shell", "make"} or ext in {
        ".py",
        ".sh",
        ".bash",
        ".zsh",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
    }


def is_docs_path(rel: str) -> bool:
    p = rel.lower()
    return p.endswith(".md") or any(tok in p for tok in ["/docs/", "readme", "runbook", "changelog", "report"])


def is_test_path(rel: str) -> bool:
    p = rel.lower()
    return "/tests/" in f"/{p}" or p.startswith("tests/") or p.startswith("test_") or p.endswith("_test.py")


def is_config_path(rel: str) -> bool:
    p = rel.lower()
    return "config" in p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-root", default="./legacy_reference")
    ap.add_argument("--out-dir", default="./claude_worklog/coverage")
    args = ap.parse_args()

    out = resolve_path(args.out_dir, Path.cwd())

    manifest = load_json(out / "FILE_MANIFEST.json", {"files": []})
    imports = load_json(out / "IMPORT_GRAPH.json", {})
    startup = load_json(out / "STARTUP_PATH_MAP.json", {"startup_references": []})
    redis = load_json(out / "REDIS_USAGE_MAP.json", {"matches": [], "files": []})
    exch = load_json(out / "EXCHANGE_ACTION_MAP.json", {"matches": [], "tier_a_files": []})
    cfg = load_json(out / "CONFIG_ENV_MAP.json", {"matches": [], "files": []})
    runtime = load_json(out / "RUNTIME_PROCESS_MAP.json", {"processes": []})

    import_by_file = {x.get("file"): x for x in imports.get("python_files", [])}

    redis_by_file: Dict[str, Dict[str, int]] = {x["file"]: x for x in redis.get("files", [])}
    exch_by_file: Dict[str, list] = {}
    for m in exch.get("matches", []):
        exch_by_file.setdefault(m["file"], []).extend(m.get("classifications", []))
    cfg_by_file = {x["file"]: x for x in cfg.get("files", [])}

    startup_by_target: Dict[str, list] = {}
    for r in startup.get("startup_references", []):
        target = str(r.get("module_or_target", ""))
        startup_by_target.setdefault(target, []).append(r)

    runtime_refs: Dict[str, list] = {}
    for p in runtime.get("processes", []):
        cmd = p.get("command", "")
        for f in manifest.get("files", []):
            rel = f.get("relative_path")
            if rel and rel in cmd:
                runtime_refs.setdefault(rel, []).append(p)

    scripts = []
    dep_edges = []
    usage_lines = ["# Script Usage Evidence", "", "| script | class | reason |", "|---|---|---|"]
    tier_a_lines = [
        "# Tier A Script Classification",
        "",
        "| script | tier_a_reason | redis(read/write/unknown) | exchange_actions | config_refs | startup_refs | runtime_refs | trading_impact |",
        "|---|---|---|---|---:|---:|---:|---|",
    ]

    for f in manifest.get("files", []):
        rel = f["relative_path"]
        if not script_like(rel, f.get("language", "unknown")):
            continue
        py_info = import_by_file.get(rel, {})

        imports_list = [i["name"] for i in py_info.get("imports", [])] + [
            x.get("module") for x in py_info.get("from_imports", []) if x.get("module")
        ]
        imported_by: Set[str] = set()
        stem = Path(rel).stem
        for other, info in import_by_file.items():
            for imp in info.get("imports", []):
                if imp.get("name", "").split(".")[-1] == stem:
                    imported_by.add(other)
            for imp in info.get("from_imports", []):
                if str(imp.get("module", "")).split(".")[-1] == stem:
                    imported_by.add(other)

        startup_refs = []
        for target, refs in startup_by_target.items():
            if rel in target or Path(rel).name in target:
                startup_refs.extend(refs)

        rr = redis_by_file.get(rel, {"redis_read": 0, "redis_write": 0, "redis_unknown": 0})
        ex = sorted(set(exch_by_file.get(rel, [])))
        cf = cfg_by_file.get(rel, {"config_refs": 0, "env_refs": 0, "env_vars": []})

        tier = "Tier C"
        risk = "low"
        if ex or rr.get("redis_write", 0) > 0:
            tier = "Tier A"
            risk = "critical" if ex else "high"
        elif any(k in rel.lower() for k in ["trainer", "reward", "confidence", "signal", "orchestrator", "risk"]):
            tier = "Tier A"
            risk = "high"
        elif rr.get("redis_read", 0) > 0:
            tier = "Tier B"
            risk = "medium"

        if runtime_refs.get(rel):
            cls = "active_runtime"
            reason = "mapped runtime process references this script"
        elif startup_refs:
            kind = startup_refs[0].get("source_kind")
            cls = (
                "active_service"
                if kind in {"systemd", "supervisor"}
                else "active_scheduled"
                if kind in {"cron", "make"}
                else "active_wrapper"
            )
            reason = f"startup reference found in {kind}"
        elif imported_by:
            cls = "active_imported"
            reason = "imported by other discovered code"
        elif is_test_path(rel):
            cls = "active_test"
            reason = "test path"
        elif is_docs_path(rel):
            cls = "docs_only"
            reason = "documentation/report path"
        elif is_config_path(rel) and rr.get("redis_write", 0) == 0 and not ex:
            cls = "config_only"
            reason = "configuration-focused path without runtime execution evidence"
        elif is_build_artifact(rel):
            cls = "dead_with_evidence"
            reason = "build/cache artifact path"
        elif is_archived(rel):
            cls = "deprecated_with_evidence"
            reason = "archived/backups path"
        elif f.get("category") == "shell" and f.get("executable"):
            cls = "active_manual"
            reason = "executable shell script without startup evidence"
        elif tier in {"Tier A", "Tier B"}:
            cls = "active_manual"
            reason = "code path has trading/runtime relevance but no deterministic scheduler evidence"
        else:
            cls = "active_manual"
            reason = "manual/adhoc script without deterministic startup evidence"

        ev = []
        if runtime_refs.get(rel):
            ev.append({"kind": "runtime_process", "count": len(runtime_refs[rel])})
        if startup_refs:
            ev.append({"kind": "startup_refs", "count": len(startup_refs)})
        if imported_by:
            ev.append({"kind": "imported_by", "count": len(imported_by)})
        if ex:
            ev.append({"kind": "exchange_actions", "actions": ex})
        if rr.get("redis_write", 0):
            ev.append({"kind": "redis_write", "count": rr.get("redis_write", 0)})

        scripts.append(
            {
                "script_id": sid(rel),
                "path": rel,
                "language": f.get("language"),
                "executable": f.get("executable"),
                "shebang": f.get("shebang"),
                "has_main_entrypoint": bool(py_info.get("has_main_entrypoint", False)),
                "imports": imports_list,
                "imported_by": sorted(imported_by),
                "startup_references": startup_refs,
                "runtime_process_refs": runtime_refs.get(rel, []),
                "redis_refs": rr,
                "redis_writes": rr.get("redis_write", 0),
                "exchange_actions": ex,
                "config_refs": cf.get("config_refs", 0),
                "env_vars": cf.get("env_vars", []),
                "docs_refs": [r for r in startup_refs if r.get("source_kind") == "docs"],
                "risk_level": risk,
                "tier": tier,
                "classification_candidate": cls,
                "classification_reason": reason,
                "evidence": ev,
            }
        )
        usage_lines.append(f"| {rel} | {cls} | {reason} |")

        if tier == "Tier A":
            impact = (
                "yes"
                if ex
                or rr.get("redis_write", 0) > 0
                or any(
                    k in rel.lower()
                    for k in [
                        "trader",
                        "trainer",
                        "signal",
                        "risk",
                        "position",
                        "portfolio",
                        "leverage",
                        "stop",
                        "pnl",
                    ]
                )
                else "possible"
            )
            tier_reason = []
            if ex:
                tier_reason.append("exchange_action")
            if rr.get("redis_write", 0) > 0:
                tier_reason.append("redis_write")
            if any(
                k in rel.lower()
                for k in ["trainer", "signal", "risk", "orchestrator", "position", "portfolio", "reward", "confidence"]
            ):
                tier_reason.append("critical_keyword_path")
            tier_a_lines.append(
                f"| {rel} | {','.join(tier_reason) or 'tier_rule'} | {rr.get('redis_read',0)}/{rr.get('redis_write',0)}/{rr.get('redis_unknown',0)} | {','.join(ex) if ex else '-'} | {cf.get('config_refs',0)} | {len(startup_refs)} | {len(runtime_refs.get(rel, []))} | {impact} |"
            )

        for dep in imports_list:
            dep_edges.append({"from": rel, "to": dep, "kind": "import"})

    scripts.sort(key=lambda x: x["path"])
    write_json(out / "SCRIPT_REGISTRY.json", {"scripts": scripts})
    write_json(out / "SCRIPT_DEPENDENCY_GRAPH.json", {"edges": dep_edges})

    md = [
        "# Script Registry",
        "",
        f"Scripts: {len(scripts)}",
        "",
        "| path | tier | risk | class | redis_write | exch |",
        "|---|---|---|---|---:|---:|",
    ]
    for s in scripts:
        md.append(
            f"| {s['path']} | {s['tier']} | {s['risk_level']} | {s['classification_candidate']} | {s['redis_writes']} | {len(s['exchange_actions'])} |"
        )
    write_markdown(out / "SCRIPT_REGISTRY.md", "\n".join(md))
    write_markdown(out / "SCRIPT_USAGE_EVIDENCE.md", "\n".join(usage_lines))
    write_markdown(out / "TIER_A_SCRIPT_CLASSIFICATION.md", "\n".join(tier_a_lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
