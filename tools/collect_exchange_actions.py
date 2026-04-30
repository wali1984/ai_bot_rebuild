#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path

from common_audit import (
    evidence_record,
    iter_files,
    read_text_safely,
    redact_text,
    relative_to,
    resolve_path,
    write_json,
    write_markdown,
)

RELEVANCE_HINTS = [
    "binance",
    "ccxt",
    "client(",
    "asyncclient",
    "exchange",
    "futures_",
    "create_order",
    "cancel",
    "leverage",
    "margin",
    "position",
    "balance",
    "klines",
    "ticker",
    "depth",
    "trades",
    "websocket",
    "stream",
    "exchangeinfo",
    "stop",
    "take_profit",
    "reduceonly",
    "closeposition",
]

RULES = {
    "order_create": [
        "futures_create_order",
        "create_order",
        "order_market",
        "order_limit",
        "buy(",
        "sell(",
        "side=",
        "quantity=",
    ],
    "order_cancel": ["cancel_order", "futures_cancel_order", "futures_cancel", "cancel_all"],
    "leverage_change": ["change_leverage", "futures_change_leverage", "leverage="],
    "margin_change": ["change_margin_type", "futures_change_margin_type", "margintype", "crossed", "isolated"],
    "stop_loss": ["stop_market", "stop_loss", "stopprice", "stopPrice"],
    "take_profit": ["take_profit", "take_profit_market", "TAKE_PROFIT", "TAKE_PROFIT_MARKET"],
    "reduce_only": ["reduceonly", "reduce_only", "closeposition"],
    "position_query": [
        "get_position",
        "positionrisk",
        "futures_position_information",
        "fetch_positions",
        "account positions",
        "position_mode",
    ],
    "balance_query": ["futures_account_balance", "account_balance", "balance", "futures_account"],
    "market_data": ["klines", "ticker", "depth", "trades", "exchangeinfo", "time", "websocket", "stream"],
    "exchange_client_init": ["client(", "binance", "ccxt.binance", "exchange =", "asyncclient"],
}

TIER_A_CLASSES = {
    "order_create",
    "order_cancel",
    "leverage_change",
    "margin_change",
    "stop_loss",
    "take_profit",
    "reduce_only",
    "position_query",
    "balance_query",
    "unknown_exchange_use",
}


def classify_line(line: str, context: str) -> tuple[str, str, str]:
    low = line.lower()
    ctx = context.lower()

    for cls in [
        "order_cancel",
        "order_create",
        "leverage_change",
        "margin_change",
        "stop_loss",
        "take_profit",
        "reduce_only",
    ]:
        hits = [k for k in RULES[cls] if k.lower() in ctx]
        if hits:
            confidence = "high" if any(k in low for k in ["futures_", "create_order", "cancel_order", "change_"]) else "medium"
            return cls, confidence, f"matched keys: {', '.join(hits[:4])}"

    for cls in ["position_query", "balance_query", "market_data", "exchange_client_init"]:
        hits = [k for k in RULES[cls] if k.lower() in ctx]
        if hits:
            confidence = "medium" if cls in {"position_query", "balance_query"} else "low"
            return cls, confidence, f"matched keys: {', '.join(hits[:4])}"

    if any(h in ctx for h in RELEVANCE_HINTS):
        return "unknown_exchange_use", "low", "exchange-related line not resolved by taxonomy"

    return "not_exchange", "low", "no exchange indicators"


def is_prod_code(path: str) -> bool:
    p = path.lower()
    return not (
        "/.backups/" in p
        or p.startswith(".backups/")
        or "/backups/" in p
        or "/tests/" in p
        or p.startswith("tests/")
        or p.endswith(".md")
        or "/docs/" in p
        or "/documentation/" in p
    )


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
    pre_unknown_count = 0
    after_unknown_count = 0
    unresolved_by_file: dict[str, int] = defaultdict(int)

    for f in iter_files(legacy):
        rel = relative_to(legacy, f)
        if f.suffix.lower() not in {".py", ".sh", ".bash", ".zsh", ".js", ".ts", ".tsx", ".jsx"}:
            continue
        try:
            lines = read_text_safely(f).splitlines()
        except Exception:
            continue

        for i, line in enumerate(lines, start=1):
            low = line.lower()
            if not any(h in low for h in RELEVANCE_HINTS):
                continue

            pre_unknown_count += 1
            s = max(1, i - 3)
            e = min(len(lines), i + 3)
            context_lines = lines[s - 1 : e]
            context = "\n".join(context_lines)

            cls, confidence, reason = classify_line(line, context)
            if cls == "not_exchange":
                continue

            if cls == "unknown_exchange_use":
                after_unknown_count += 1
                unresolved_by_file[rel] += 1

            tier = "Tier A" if cls in TIER_A_CLASSES else "Tier B"
            if tier == "Tier A":
                tier_a_files.add(rel)

            matches.append(
                {
                    "file": rel,
                    "line": i,
                    "classifications": [cls],
                    "classification": cls,
                    "confidence": confidence,
                    "reason": reason,
                    "context_start": s,
                    "context_end": e,
                    "context_lines": [(redact_text(x[:500]) or "") for x in context_lines],
                    "text": (redact_text(line.strip()[:500]) or ""),
                    "tier": tier,
                    "verification_command": f"python3 tools/show_file_range.py --file ./legacy_reference/{rel} --start {s} --end {e}",
                    "evidence": evidence_record(f"./legacy_reference/{rel}", i, line.strip()[:400], cls, reason),
                }
            )

    class_counts = Counter(m.get("classification") for m in matches)
    data = {
        "matches": matches,
        "tier_a_files": sorted(tier_a_files),
        "class_counts": dict(class_counts),
        "unknown_exchange_use_count_before": pre_unknown_count,
        "unknown_exchange_use_count_after": after_unknown_count,
    }
    write_json(out / "EXCHANGE_ACTION_MAP.json", data)

    md = [
        "# Exchange Action Map",
        "",
        f"Total matches: {len(matches)}",
        f"Tier A files: {len(tier_a_files)}",
        f"unknown_exchange_use before: {pre_unknown_count}",
        f"unknown_exchange_use after: {after_unknown_count}",
        "",
        "| file | line | class | confidence | reason |",
        "|---|---:|---|---|---|",
    ]
    for m in matches[:500]:
        md.append(
            f"| {m['file']} | {m['line']} | {m['classification']} | {m['confidence']} | {str(m['reason']).replace('|','/')} |"
        )
    write_markdown(out / "EXCHANGE_ACTION_MAP.md", "\n".join(md))

    unresolved_sorted = sorted(unresolved_by_file.items(), key=lambda x: x[1], reverse=True)
    res_md = [
        "# Exchange Unknown Resolution",
        "",
        f"- count before: {pre_unknown_count}",
        f"- count after: {after_unknown_count}",
        f"- remaining unknown_exchange_use: {after_unknown_count}",
        "",
        "## Top files with unresolved unknowns",
    ]
    for fpath, c in unresolved_sorted[:100]:
        blocker = "blocker" if is_prod_code(fpath) else "acceptable_false_positive"
        res_md.append(f"- {fpath}: {c} ({blocker})")

    res_md += ["", "## Raw evidence pointers"]
    for m in [x for x in matches if x.get("classification") == "unknown_exchange_use"][:120]:
        res_md.append(f"- {m['file']}:{m['line']} -> {m['verification_command']}")
    write_markdown(out / "EXCHANGE_UNKNOWN_RESOLUTION.md", "\n".join(res_md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
