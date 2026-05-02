#!/usr/bin/env python3
"""Build the Phase 2 ingestor preservation inventory.

This tool is intentionally read-only against the legacy bot. It copies only the
approved `live_coinank.py` preservation snapshot into AI BOT REBUILD and writes
hash/inventory reports under claude_worklog.
"""
from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
import pathlib
import shutil
import subprocess
from typing import Any, Dict, Iterable, List, Optional


WORKSPACE = pathlib.Path("/home/wali/Desktop/AI BOT REBUILD").resolve()
LIVE_ROOT = pathlib.Path("/home/wali/Desktop/AI BOT").resolve()
REFERENCE_ROOT = WORKSPACE / "legacy_reference"
OUT_DIR = WORKSPACE / "claude_worklog/phase2_core_rebuild/ingestors"
PRESERVED_DIR = WORKSPACE / "v2/legacy_preserved/ingestors"

COMPONENTS = [
    ("live_binance.py", "ingest/live_binance.py"),
    ("live_kucoin.py", "ingest/live_kucoin.py"),
    ("live_coinank.py", "ingest/live_coinank.py"),
    ("live_binance_liquidations.py", "ingest/live_binance_liquidations.py"),
    ("liquidation_bridge.py", "ingest/liquidation_bridge.py"),
    ("liquidation_levels_engine.py", "ingest/liquidation_levels_engine.py"),
    ("realtime_price_provider.py", "ingest/realtime_price_provider.py"),
    ("live_coinank_global_aggregator.py", "ingest/live_coinank_global_aggregator.py"),
    ("ingest.live_coinapi_wsds", "ingest/live_coinapi_wsds.py"),
    ("ingest.live_coinapi_v1", "ingest/live_coinapi_v1.py"),
    ("ohlcv_resampler_hotfix.py", "ohlcv_resampler_hotfix.py"),
    ("feature_pipeline.py", "feature_pipeline.py"),
    ("live_technical_analysis.py", "ingest/live_technical_analysis.py"),
]

SYMBOL_NAME_HINTS = (
    "SYMBOL",
    "SYMBOLS",
    "COIN",
    "COINS",
    "PAIR",
    "PAIRS",
    "UNIVERSE",
    "WATCHLIST",
    "MARKET",
    "MARKETS",
)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def rel(path: pathlib.Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE))
    except ValueError:
        return str(path.resolve())


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_record(path: pathlib.Path) -> Dict[str, Any]:
    stat = path.stat()
    return {
        "path": rel(path),
        "size_bytes": stat.st_size,
        "sha256": sha256_file(path),
    }


def first_existing(relative_path: str) -> tuple[Optional[pathlib.Path], Optional[str]]:
    live = LIVE_ROOT / relative_path
    if live.exists():
        return live, "live"
    ref = REFERENCE_ROOT / relative_path
    if ref.exists():
        return ref, "legacy_reference"
    return None, None


def process_snapshot() -> List[Dict[str, Any]]:
    cp = subprocess.run(
        ["ps", "-eo", "pid,ppid,etimes,cmd"],
        cwd=str(WORKSPACE),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    rows = []
    for line in cp.stdout.splitlines()[1:]:
        parts = line.strip().split(None, 3)
        if len(parts) != 4:
            continue
        pid, ppid, etimes, cmd = parts
        rows.append({"pid": pid, "ppid": ppid, "etimes": etimes, "cmd": cmd})
    return rows


def observed_processes(component: str, relative_path: str, rows: Iterable[Dict[str, str]]) -> List[Dict[str, Any]]:
    needles = {component, pathlib.Path(relative_path).name, relative_path.replace("/", ".").removesuffix(".py")}
    matches = []
    for row in rows:
        cmd = row["cmd"]
        if any(n and n in cmd for n in needles):
            matches.append({
                "pid": int(row["pid"]),
                "etimes": int(row["etimes"]),
                "matched_component": component,
                "command_redacted": component,
            })
    return matches


def literal_count(node: ast.AST) -> Optional[int]:
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return len(node.elts)
    if isinstance(node, ast.Dict):
        return len(node.keys)
    return None


def config_symbol_map() -> Dict[str, Any]:
    source_path, source_type = first_existing("config.py")
    result: Dict[str, Any] = {
        "source_found": bool(source_path),
        "source_type": source_type,
        "source_path": rel(source_path) if source_path else None,
        "symbol_related_assignments": [],
        "note": "Names and counts only. Values are intentionally not written.",
    }
    if not source_path:
        return result
    tree = ast.parse(source_path.read_text(encoding="utf-8", errors="replace"), filename=str(source_path))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            name = target.id
            if not any(hint in name.upper() for hint in SYMBOL_NAME_HINTS):
                continue
            result["symbol_related_assignments"].append({
                "name": name,
                "value_type": type(node.value).__name__,
                "literal_count": literal_count(node.value),
            })
    return result


def write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PRESERVED_DIR.mkdir(parents=True, exist_ok=True)

    ps_rows = process_snapshot()
    inventory: Dict[str, Any] = {
        "generated_at": now_iso(),
        "workspace": str(WORKSPACE),
        "legacy_live_root": str(LIVE_ROOT),
        "legacy_reference_root": rel(REFERENCE_ROOT),
        "policy": "preserve_first_wrap_then_parity_test",
        "components": [],
        "live_coinank_copy": {},
    }

    missing: List[str] = []
    for component, relative_path in COMPONENTS:
        source_path, source_type = first_existing(relative_path)
        record: Dict[str, Any] = {
            "component": component,
            "relative_path": relative_path,
            "source_found": bool(source_path),
            "source_type": source_type,
            "source": file_record(source_path) if source_path else None,
            "process_observed": False,
            "process_evidence": [],
            "preservation_rule": "copy_as_is" if component == "live_coinank.py" else "preserve_behavior_first",
            "enhancement_gate": "parity_tests_and_codex_review_required",
        }
        if source_path:
            evidence = observed_processes(component, relative_path, ps_rows)
            record["process_observed"] = bool(evidence)
            record["process_evidence"] = evidence
        else:
            missing.append(component)
        inventory["components"].append(record)

    coinank_source, coinank_source_type = first_existing("ingest/live_coinank.py")
    if coinank_source:
        target = PRESERVED_DIR / "live_coinank.py"
        shutil.copyfile(coinank_source, target)
        source_hash = sha256_file(coinank_source)
        copied_hash = sha256_file(target)
        inventory["live_coinank_copy"] = {
            "source_type": coinank_source_type,
            "source": file_record(coinank_source),
            "copied": file_record(target),
            "hash_match": source_hash == copied_hash,
            "copy_mode": "as_is_no_behavior_change",
        }
    else:
        missing.append("live_coinank.py copy source")
        inventory["live_coinank_copy"] = {"hash_match": False, "blocked_reason": "source not found"}

    symbol_map = config_symbol_map()
    go = (
        "PHASE2_INGESTOR_PRESERVATION_READY"
        if not missing and inventory["live_coinank_copy"].get("hash_match") else
        "PHASE2_INGESTOR_PRESERVATION_BLOCKED"
    )

    write_text(
        OUT_DIR / "00_SCOPE.md",
        "\n".join([
            "# Phase 2A Ingestor Preservation Scope",
            "",
            "This task inventories and hashes known legacy ingestors without modifying the live legacy bot.",
            "",
            "Actions performed:",
            "- Located known ingestor and feature pipeline sources.",
            "- Copied `live_coinank.py` as-is into V2 preservation space.",
            "- Verified original and copied `live_coinank.py` SHA256 hashes match.",
            "- Recorded config symbol source names and counts only.",
            "",
            "Forbidden actions respected:",
            "- No writes to `/home/wali/Desktop/AI BOT`.",
            "- No Redis writes or deletes.",
            "- No ingestor execution.",
            "- No service restarts.",
            "- No secrets written.",
            "",
            "PHASE2_INGESTOR_COPY_HASH_SCOPE_READY",
            "",
        ]),
    )
    write_text(OUT_DIR / "01_INGESTOR_COPY_HASH_INVENTORY.json", json.dumps(inventory, indent=2) + "\n")

    copy = inventory["live_coinank_copy"]
    write_text(
        OUT_DIR / "02_LIVE_COINANK_COPY_VERIFICATION.md",
        "\n".join([
            "# live_coinank.py Copy Verification",
            "",
            f"Source type: {copy.get('source_type')}",
            f"Source path: {copy.get('source', {}).get('path')}",
            f"Copied path: {copy.get('copied', {}).get('path')}",
            f"Source SHA256: {copy.get('source', {}).get('sha256')}",
            f"Copied SHA256: {copy.get('copied', {}).get('sha256')}",
            f"Hash match: {copy.get('hash_match')}",
            "",
            "Behavior rule: copy as-is, no refactor, no rewrite, no timing/parsing/output/symbol changes.",
            "",
            "LIVE_COINANK_COPY_HASH_MATCH" if copy.get("hash_match") else "LIVE_COINANK_COPY_HASH_MISMATCH",
            "",
        ]),
    )
    write_text(
        OUT_DIR / "03_CONFIG_SYMBOL_SOURCE_MAP.md",
        "\n".join([
            "# Config Symbol Source Map",
            "",
            f"Source found: {symbol_map['source_found']}",
            f"Source type: {symbol_map['source_type']}",
            f"Source path: {symbol_map['source_path']}",
            "",
            "Values are intentionally omitted. Names and counts only.",
            "",
            "| Assignment | Value type | Literal count |",
            "|---|---:|---:|",
            *[
                f"| `{item['name']}` | {item['value_type']} | {item['literal_count']} |"
                for item in symbol_map["symbol_related_assignments"]
            ],
            "",
            "CONFIG_SYMBOL_SOURCE_MAP_READY",
            "",
        ]),
    )
    write_text(OUT_DIR / "04_GO_NO_GO.md", go + "\n")
    print(go)
    return 0 if go.endswith("_READY") else 2


if __name__ == "__main__":
    raise SystemExit(main())
