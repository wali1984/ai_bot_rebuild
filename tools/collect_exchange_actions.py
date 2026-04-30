#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
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

CODE_SUFFIXES = {".py", ".sh", ".bash", ".zsh", ".js", ".ts", ".tsx", ".jsx"}

GENERIC_TERMS = {
    "exchange",
    "client",
    "order",
    "account",
    "balance",
    "margin",
    "position",
    "futures",
    "binance",
}

CONCRETE_PATTERNS = {
    "order_create": [
        "futures_create_order",
        "create_order(",
        "create_test_order",
        "order_market",
        "order_limit",
        "new_order",
    ],
    "order_cancel": [
        "cancel_order",
        "futures_cancel_order",
        "cancel_all_orders",
        "cancel_open_orders",
    ],
    "leverage_change": ["change_leverage", "futures_change_leverage", "set_leverage"],
    "margin_change": [
        "change_margin_type",
        "futures_change_margin_type",
        "set_margin",
        "margin_type",
    ],
    "stop_loss": ["stop_loss", "stop_market", "stopprice", "closeposition=true"],
    "take_profit": ["take_profit", "take_profit_market", "tp_price"],
    "reduce_only": ["reduceonly", "reduce_only", "closeposition"],
    "position_query": [
        "futures_position_information",
        "positionrisk",
        "get_position",
        "fetch_positions",
        "position_mode",
    ],
    "balance_query": ["futures_account_balance", "account_balance", "wallet_balance"],
    "account_query": ["futures_account", "get_account", "account_info", "account_status"],
    "market_data": [
        "futures_klines",
        "get_klines",
        "ticker_price",
        "book_ticker",
        "depth",
        "agg_trades",
        "exchangeinfo",
    ],
    "websocket_market_data": ["websocket", "ws_", "socket", "stream", "listen_key"],
    "exchange_client_init": [
        "client(",
        "asyncclient.create",
        "binance.client",
        "ccxt.binance",
        "umfutures(",
    ],
    "exchange_error_handling": [
        "binanceapiexception",
        "apierror",
        "retry",
        "backoff",
        "rate limit",
        "except",
    ],
    "exchange_config": ["base_url", "testnet", "api_key", "api_secret", "recvwindow"],
    "exchange_symbol_metadata": ["exchangeinfo", "filters", "ticksize", "stepsize", "lot_size"],
    "exchange_time_sync": ["server_time", "servertime", "timestamp", "time_offset", "sync_time"],
}

ACTION_CLASSES = {
    "order_create",
    "order_cancel",
    "leverage_change",
    "margin_change",
    "stop_loss",
    "take_profit",
    "reduce_only",
}

TIER_A_CLASSES = ACTION_CLASSES | {
    "position_query",
    "balance_query",
    "account_query",
    "unknown_exchange_use",
}


def tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z_][a-z0-9_]*", (s or "").lower()))


def classify_production_relevance(path: str) -> str:
    p = (path or "").lower()
    if p.endswith(".md") or any(x in p for x in ["/docs/", "readme", "report", "audit", "runbook", "changelog"]):
        return "docs"
    if any(x in p for x in ["/tests/", "/test/"]) or p.startswith("test_") or p.endswith("_test.py"):
        return "tests"
    if any(x in p for x in ["/coverage/", "claude_worklog/"]) or p.endswith(".json"):
        return "generated"
    if "config" in p:
        return "unknown" if p.endswith(".py") else "docs"
    if any(x in p for x in ["/rl/", "/trading/", "/ingest/", "/services/", "/api/", "/core/"]):
        return "production"
    if p.endswith(tuple(CODE_SUFFIXES)):
        return "production"
    return "unknown"


def is_comment_only(line: str) -> bool:
    s = (line or "").strip()
    if not s:
        return False
    return s.startswith("#") or s.startswith("//") or s.startswith("/*") or s.startswith("*")


def has_any(patterns: list[str], text: str) -> bool:
    lt = text.lower()
    return any(p.lower() in lt for p in patterns)


def generic_only(line: str) -> bool:
    t = tokens(line)
    if not t:
        return False
    # discard syntax tokens
    t = {x for x in t if x not in {"if", "for", "in", "and", "or", "not", "def", "class", "return"}}
    return bool(t) and all(x in GENERIC_TERMS for x in t)


def classify_line(path: str, line: str, context: str) -> tuple[str, str, str, bool]:
    rel = classify_production_relevance(path)
    lc = line.lower()
    cc = context.lower()
    comment = is_comment_only(line)

    # docs/tests/comments pre-classification unless concrete behavior exists
    has_concrete = any(has_any(v, cc) for v in CONCRETE_PATTERNS.values())
    has_exchange_hint = bool(tokens(cc) & GENERIC_TERMS) or "binance" in cc or "ccxt" in cc

    if comment and not has_concrete:
        return "comment_exchange_context", "high", "comment-only exchange context", False
    if rel == "docs" and not has_concrete:
        return "docs_exchange_context", "high", "docs/report exchange context", False
    if rel == "tests" and not has_concrete:
        return "test_exchange_context", "high", "test/example exchange context", False

    # concrete classes
    for cls in [
        "order_create",
        "order_cancel",
        "leverage_change",
        "margin_change",
        "stop_loss",
        "take_profit",
        "reduce_only",
        "position_query",
        "balance_query",
        "account_query",
        "exchange_symbol_metadata",
        "exchange_time_sync",
        "exchange_client_init",
        "exchange_error_handling",
        "exchange_config",
        "market_data",
        "websocket_market_data",
    ]:
        if has_any(CONCRETE_PATTERNS.get(cls, []), cc):
            conf = "high"
            reason = f"matched concrete pattern for {cls}"
            if cls in {"exchange_error_handling", "exchange_config", "websocket_market_data", "market_data"}:
                conf = "medium"
            return cls, conf, reason, False

    if generic_only(line):
        return "exchange_context_only", "high", "generic exchange term without concrete API operation", False

    if has_exchange_hint and rel == "production" and not comment:
        return "unknown_exchange_use", "low", "production exchange-related code with unresolved concrete class", True

    if has_exchange_hint:
        return "exchange_context_only", "medium", "exchange hint without concrete action", False

    return "not_exchange", "low", "no exchange indicators", False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-root", default="./legacy_reference")
    ap.add_argument("--out-dir", default="./claude_worklog/coverage")
    args = ap.parse_args()

    legacy = resolve_path(args.legacy_root, Path.cwd())
    out = resolve_path(args.out_dir, Path.cwd())
    out.mkdir(parents=True, exist_ok=True)

    matches = []
    tier_a_files: set[str] = set()
    pre_unknown_count = 0
    after_unknown_count = 0
    unresolved_by_file: dict[str, int] = defaultdict(int)

    for f in iter_files(legacy):
        if f.suffix.lower() not in CODE_SUFFIXES:
            continue

        rel = relative_to(legacy, f)
        try:
            lines = read_text_safely(f).splitlines()
        except Exception:
            continue

        for i, line in enumerate(lines, start=1):
            tl = tokens(line)
            if not (tl & GENERIC_TERMS) and "binance" not in line.lower() and "ccxt" not in line.lower():
                continue

            pre_unknown_count += 1
            s = max(1, i - 5)
            e = min(len(lines), i + 5)
            context_lines = lines[s - 1 : e]
            context = "\n".join(context_lines)

            cls, confidence, reason, blocking_unknown = classify_line(rel, line, context)
            if cls == "not_exchange":
                continue

            if cls == "unknown_exchange_use":
                after_unknown_count += 1
                unresolved_by_file[rel] += 1

            tier = "Tier A" if cls in TIER_A_CLASSES else "Tier B"
            if tier == "Tier A":
                tier_a_files.add(rel)

            prod_rel = classify_production_relevance(rel)
            vc = f"python3 tools/show_file_range.py --file ./legacy_reference/{rel} --start {s} --end {e}"
            red_line = (redact_text(line.strip()[:500]) or "")

            matches.append(
                {
                    "file": rel,
                    "line": i,
                    "matched_text": red_line,
                    "text": red_line,
                    "context_start": s,
                    "context_end": e,
                    "context_lines": [(redact_text(x[:500]) or "") for x in context_lines],
                    "classifications": [cls],
                    "classification": cls,
                    "confidence": confidence,
                    "production_relevance": prod_rel,
                    "is_blocking_unknown": bool(blocking_unknown),
                    "reason": reason,
                    "verification_command": vc,
                    "tier": tier,
                    "evidence": evidence_record(
                        f"./legacy_reference/{rel}",
                        i,
                        line.strip()[:400],
                        cls,
                        reason,
                    ),
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
        "| file | line | class | confidence | production_relevance | blocking_unknown | reason |",
        "|---|---:|---|---|---|---:|---|",
    ]
    for m in matches[:500]:
        md.append(
            f"| {m['file']} | {m['line']} | {m['classification']} | {m['confidence']} | {m['production_relevance']} | {str(m['is_blocking_unknown'])} | {str(m['reason']).replace('|', '/')} |"
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
        blocker = "blocker" if classify_production_relevance(fpath) == "production" else "non_blocking_context"
        res_md.append(f"- {fpath}: {c} ({blocker})")

    res_md += ["", "## Raw evidence pointers"]
    for m in [x for x in matches if x.get("classification") == "unknown_exchange_use"][:120]:
        res_md.append(f"- {m['file']}:{m['line']} -> {m['verification_command']}")
    write_markdown(out / "EXCHANGE_UNKNOWN_RESOLUTION.md", "\n".join(res_md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
