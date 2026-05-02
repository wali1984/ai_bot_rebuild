#!/usr/bin/env python3
"""Build a read-only inventory of legacy-compatible ingestor files."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, Iterable, List

WORKSPACE_ROOT = Path.home() / "Desktop" / "AI BOT REBUILD"
LEGACY_REFERENCE = WORKSPACE_ROOT / "legacy_reference"
LIVE_LEGACY_ROOT = Path("/home/wali/Desktop/AI BOT")
OUT_JSON = WORKSPACE_ROOT / "claude_worklog/legacy_preservation/01_LEGACY_INGESTOR_INVENTORY.json"
OUT_MD = WORKSPACE_ROOT / "claude_worklog/legacy_preservation/02_LEGACY_INGESTOR_INVENTORY.md"

KEYWORDS = {
    "ingest": "ingestor",
    "binance": "binance_futures",
    "coinank": "coinank",
    "coinapi": "coinapi",
    "kucoin": "kucoin",
    "liquidation": "liquidation",
    "ohlcv": "ohlcv",
    "realtime_price": "realtime_price",
    "technical_analysis": "technical_analysis",
}

TEXT_SUFFIXES = {
    ".py",
    ".sh",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".txt",
}

SKIP_NAMES = {".env", "config.py"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def likely_ingestor(path: Path) -> bool:
    probe = str(path).lower()
    return any(keyword in probe for keyword in KEYWORDS)


def category_for(path: Path) -> str:
    probe = str(path).lower()
    matches = [category for keyword, category in KEYWORDS.items() if keyword in probe]
    return ",".join(dict.fromkeys(matches)) if matches else "unknown"


def iter_candidate_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    paths: List[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name in SKIP_NAMES:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if likely_ingestor(path):
            paths.append(path)
    return paths


def inventory_root(root: Path, source_type: str, hash_contents: bool) -> List[Dict[str, object]]:
    items: List[Dict[str, object]] = []
    for path in sorted(iter_candidate_files(root)):
        try:
            rel = str(path.relative_to(WORKSPACE_ROOT)) if path.is_relative_to(WORKSPACE_ROOT) else str(path)
        except Exception:
            rel = str(path)
        try:
            stat = path.stat()
        except OSError:
            continue
        entry: Dict[str, object] = {
            "path": rel,
            "size_bytes": stat.st_size,
            "sha256": sha256_file(path) if hash_contents else None,
            "category": category_for(path),
            "source_type": source_type,
        }
        items.append(entry)
    return items


def main() -> int:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)

    legacy_reference_items = inventory_root(LEGACY_REFERENCE, "legacy_reference_snapshot", True)
    live_path_items = inventory_root(LIVE_LEGACY_ROOT, "live_legacy_path_reference", False)

    payload = {
        "generated_by": "claude_worklog/tools/build_legacy_ingestor_inventory.py",
        "legacy_reference_root": str(LEGACY_REFERENCE),
        "live_legacy_root": str(LIVE_LEGACY_ROOT),
        "rules": {
            "read_only": True,
            "no_runtime_calls": True,
            "secret_values_included": False,
            "live_files_hashed": False,
        },
        "counts": {
            "legacy_reference_candidates": len(legacy_reference_items),
            "live_path_candidates": len(live_path_items),
        },
        "items": legacy_reference_items + live_path_items,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Legacy Ingestor Inventory",
        "",
        "This inventory is read-only and contains paths, sizes, categories, and hashes for legacy_reference snapshots.",
        "Live legacy source candidates are listed by path and size only; their contents are not copied here.",
        "",
        "## Counts",
        f"- legacy_reference candidates: {len(legacy_reference_items)}",
        f"- live legacy path candidates: {len(live_path_items)}",
        "",
        "## Candidates",
        "",
        "| source_type | category | size_bytes | sha256 | path |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for item in payload["items"]:
        sha = item["sha256"] or "not_hashed_live_path_reference"
        lines.append(
            f"| {item['source_type']} | {item['category']} | {item['size_bytes']} | {sha} | `{item['path']}` |"
        )
    if not payload["items"]:
        lines.append("| none | none | 0 | none | none |")
    lines.extend(["", "LEGACY_INGESTOR_INVENTORY_READY"])
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("LEGACY_INGESTOR_INVENTORY_READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
