#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

from common_audit import iter_files, read_text_safely, relative_to, resolve_path, write_json, write_markdown, evidence_record, redact_text

PATTERNS = {
    "order_create": ["futures_create_order", "create_order"],
    "order_cancel": ["cancel_order", "futures_cancel"],
    "leverage_change": ["change_leverage", "futures_change_leverage", "leverage"],
    "margin_change": ["change_margin_type", "futures_change_margin_type", "margin"],
    "stop_loss": ["STOP_MARKET", "stop_loss", "stop loss"],
    "take_profit": ["TAKE_PROFIT", "take profit"],
    "reduce_only": ["reduceOnly", "reduce_only"],
    "position_query": ["position_mode", "position", "positions"],
    "unknown_exchange_use": ["Binance", "ccxt", "exchange", "liquidation", "trailing"],
}


def classify(line: str) -> list[str]:
    found = []
    for cls, keys in PATTERNS.items():
        if any(k.lower() in line.lower() for k in keys):
            found.append(cls)
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-root", default="./legacy_reference")
    ap.add_argument("--out-dir", default="./claude_worklog/coverage")
    args = ap.parse_args()
    legacy = resolve_path(args.legacy_root, Path.cwd())
    out = resolve_path(args.out_dir, Path.cwd())
    out.mkdir(parents=True, exist_ok=True)

    matches = []
    tier_a_files = set()

    rx = re.compile("|".join(re.escape(k) for vals in PATTERNS.values() for k in vals), re.IGNORECASE)
    for f in iter_files(legacy):
        rel = relative_to(legacy, f)
        if f.suffix.lower() not in {".py", ".sh", ".bash", ".zsh", ".js", ".ts", ".tsx", ".jsx"}:
            continue
        try:
            text = read_text_safely(f)
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if rx.search(line):
                cl = classify(line) or ["unknown_exchange_use"]
                tier_a_files.add(rel)
                matches.append({
                    "file": rel,
                    "line": i,
                    "classifications": cl,
                    "text": (redact_text(line.strip()[:500]) or ""),
                    "tier": "Tier A",
                    "evidence": evidence_record(f"./legacy_reference/{rel}", i, line.strip()[:400], cl[0], "exchange keyword match"),
                })

    data = {"matches": matches, "tier_a_files": sorted(tier_a_files)}
    write_json(out / "EXCHANGE_ACTION_MAP.json", data)

    md = ["# Exchange Action Map", "", f"Total matches: {len(matches)}", f"Tier A files: {len(tier_a_files)}", "", "| file | line | classes |", "|---|---:|---|"]
    for m in matches[:500]:
        md.append(f"| {m['file']} | {m['line']} | {','.join(m['classifications'])} |")
    write_markdown(out / "EXCHANGE_ACTION_MAP.md", "\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
