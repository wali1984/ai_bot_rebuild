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
    "order_create": ["futures_create_order", "create_order(", "new_order", "order_market", "order_limit"],
    "order_cancel": ["cancel_order", "futures_cancel_order", "cancel_all_orders", "cancel_open_orders"],
    "leverage_change": ["change_leverage", "futures_change_leverage", "set_leverage", "leverage="],
    "margin_change": ["change_margin_type", "futures_change_margin_type", "set_margin", "margin_type"],
    "stop_loss": ["stop_loss", "stop_market", "stopprice"],
    "take_profit": ["take_profit", "take_profit_market", "tp_price"],
    "reduce_only": ["reduce_only", "reduceonly", "closeposition"],
    "position_query": ["futures_position_information", "positionrisk", "fetch_positions", "get_position", "positionamt"],
    "balance_query": ["futures_account_balance", "account_balance", "wallet_balance"],
    "account_query": ["futures_account", "account_info", "account_status", "get_account"],
    "market_data": ["futures_klines", "get_klines", "ticker_price", "book_ticker", "depth", "agg_trades"],
    "websocket_market_data": ["websocket", "ws_", "socket", "stream", "listen_key"],
    "exchange_client_init": ["client(", "asyncclient.create", "binance.client", "ccxt.binance", "umfutures("],
    "exchange_error_handling": ["binanceapiexception", "apierror", "except", "retry", "backoff", "rate limit"],
    "exchange_config": ["base_url", "testnet", "api_key", "api_secret", "recvwindow"],
    "exchange_symbol_metadata": ["exchangeinfo", "filters", "ticksize", "stepsize", "precision", "lot_size"],
    "exchange_time_sync": ["server_time", "servertime", "timestamp", "time_offset", "sync_time"],
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
    "account_query",
    "exchange_unresolved_tier_a_review",
}


def tok(s: str) -> set[str]:
    return set(re.findall(r"[a-z_][a-z0-9_]*", (s or "").lower()))


def classify_production_relevance(path: str) -> str:
    p = (path or "").lower()
    if p.endswith(".md") or any(x in p for x in ["/docs/", "readme", "report", "audit", "runbook", "changelog"]):
        return "docs"
    if any(x in p for x in ["/tests/", "/test/"]) or p.startswith("test_") or p.endswith("_test.py"):
        return "tests"
    if "claude_worklog/" in p or p.endswith(".json"):
        return "generated"
    if any(x in p for x in ["/rl/", "/trading/", "/ingest/", "/services/", "/api/", "/core/"]):
        return "production"
    if p.endswith(tuple(CODE_SUFFIXES)):
        return "production"
    return "unknown"


def is_comment_only(line: str) -> bool:
    s = (line or "").strip()
    return bool(s) and (s.startswith("#") or s.startswith("//") or s.startswith("/*") or s.startswith("*"))


def has_any(patterns: list[str], text: str) -> bool:
    low = text.lower()
    return any(p.lower() in low for p in patterns)


def generic_only(line: str) -> bool:
    t = {x for x in tok(line) if x not in {"if", "for", "in", "and", "or", "not", "def", "class", "return"}}
    return bool(t) and all(x in GENERIC_TERMS for x in t)


def unresolved_priority(path: str, context: str) -> str:
    p = (path or "").lower()
    c = (context or "").lower()
    if p in {"trading/trader.py", "trading/base_executor.py", "trading/stealth_stops.py"}:
        return "P0"
    if p in {"rl/hybrid_trainer.py", "rl/orchestrator_worker.py"}:
        if any(k in c for k in ["order", "create_order", "cancel_order", "leverage", "margin", "stop", "reduceonly", "reduce_only"]):
            return "P0"
        return "P1"
    if p.startswith("ingest/"):
        if any(k in c for k in ["signals:trading", "signal", "unified_features", "feature", "trainer"]):
            return "P1"
        return "P2"
    return "P1"


def classify_line(path: str, line: str, context: str) -> tuple[str, str, str, bool, bool, str | None]:
    rel = classify_production_relevance(path)
    l = line.lower()
    c = context.lower()

    has_exchange_hint = bool(tok(c) & GENERIC_TERMS) or "binance" in c or "ccxt" in c
    if not has_exchange_hint:
        return "not_exchange", "low", "no exchange indicators", False, False, None

    if rel == "docs":
        return "docs_exchange_context", "high", "docs/report exchange context", False, False, None
    if rel == "tests":
        return "test_exchange_context", "high", "test/example exchange context", False, False, None
    if is_comment_only(line):
        return "comment_exchange_context", "high", "comment-only exchange context", False, False, None

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
        "websocket_market_data",
        "market_data",
    ]:
        if has_any(CONCRETE_PATTERNS.get(cls, []), c):
            conf = "high"
            if cls in {"exchange_config", "exchange_error_handling", "market_data", "websocket_market_data"}:
                conf = "medium"
            return cls, conf, f"matched concrete pattern for {cls}", False, False, None

    if any(k in c for k in ["position", "balance", "account", "equity", "notional", "margin_util", "pnl"]) and not any(
        k in c for k in ["create_order", "cancel_order", "change_leverage", "change_margin_type"]
    ):
        return "exchange_state_accounting", "medium", "local exchange state/accounting logic without concrete API mutation", False, False, None

    if generic_only(line):
        return "exchange_context_only", "high", "generic exchange term without concrete API effect", False, False, None

    # unknown allowed only if no evidence-backed raw review range can be formed.
    # scanner always has file/line/context range here, so unresolved production logic is queued for Tier A review.
    if rel == "production":
        prio = unresolved_priority(path, c)
        return (
            "exchange_unresolved_tier_a_review",
            "low" if prio != "P0" else "medium",
            "unresolved production exchange logic queued for Tier A raw review",
            False,
            True,
            prio,
        )

    return "exchange_context_only", "medium", "exchange hint without concrete API action", False, False, None


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
    unknown_before = 0
    unknown_after = 0
    blocking_unknown = 0
    unresolved_tier_a = 0
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
            if not (tok(line) & GENERIC_TERMS or "binance" in line.lower() or "ccxt" in line.lower()):
                continue

            unknown_before += 1
            s = max(1, i - 5)
            e = min(len(lines), i + 5)
            context_lines = lines[s - 1 : e]
            context = "\n".join(context_lines)

            cls, conf, reason, is_blocking_unknown, requires_review, review_priority = classify_line(rel, line, context)
            if cls == "not_exchange":
                continue

            if cls == "unknown_exchange_use":
                unknown_after += 1
                if is_blocking_unknown:
                    blocking_unknown += 1
                unresolved_by_file[rel] += 1
            if cls == "exchange_unresolved_tier_a_review":
                unresolved_tier_a += 1
                unresolved_by_file[rel] += 1

            tier = "Tier A" if cls in TIER_A_CLASSES else "Tier B"
            if tier == "Tier A":
                tier_a_files.add(rel)

            red_line = (redact_text(line.strip()[:500]) or "")
            vc = f"python3 tools/show_file_range.py --file ./legacy_reference/{rel} --start {s} --end {e}"

            matches.append(
                {
                    "file": rel,
                    "line": i,
                    "matched_text": red_line,
                    "text": red_line,
                    "context_start": s,
                    "context_end": e,
                    "context_lines": [(redact_text(x[:500]) or "") for x in context_lines],
                    "classification": cls,
                    "classifications": [cls],
                    "confidence": conf,
                    "production_relevance": classify_production_relevance(rel),
                    "is_blocking_unknown": bool(is_blocking_unknown),
                    "requires_raw_review": bool(requires_review),
                    "raw_review_priority": review_priority,
                    "reason": reason,
                    "verification_command": vc,
                    "tier": tier,
                    "evidence": evidence_record(f"./legacy_reference/{rel}", i, line.strip()[:400], cls, reason),
                }
            )

    class_counts = Counter(m.get("classification") for m in matches)
    payload = {
        "matches": matches,
        "tier_a_files": sorted(tier_a_files),
        "class_counts": dict(class_counts),
        "unknown_exchange_use_count_before": unknown_before,
        "unknown_exchange_use_count_after": unknown_after,
        "blocking_unknown_exchange_use_count": blocking_unknown,
        "exchange_unresolved_tier_a_review_count": unresolved_tier_a,
    }
    write_json(out / "EXCHANGE_ACTION_MAP.json", payload)

    md = [
        "# Exchange Action Map",
        "",
        f"Total matches: {len(matches)}",
        f"Tier A files: {len(tier_a_files)}",
        f"unknown_exchange_use before: {unknown_before}",
        f"unknown_exchange_use after: {unknown_after}",
        f"blocking_unknown_exchange_use: {blocking_unknown}",
        f"exchange_unresolved_tier_a_review: {unresolved_tier_a}",
        "",
        "| file | line | class | confidence | relevance | blocking_unknown | requires_raw_review | raw_review_priority | reason |",
        "|---|---:|---|---|---|---:|---:|---|---|",
    ]
    for m in matches[:700]:
        md.append(
            f"| {m['file']} | {m['line']} | {m['classification']} | {m['confidence']} | {m['production_relevance']} | {str(m['is_blocking_unknown'])} | {str(m['requires_raw_review'])} | {m.get('raw_review_priority') or '-'} | {str(m['reason']).replace('|','/')} |"
        )
    write_markdown(out / "EXCHANGE_ACTION_MAP.md", "\n".join(md))

    top = sorted(unresolved_by_file.items(), key=lambda x: x[1], reverse=True)
    res = [
        "# Exchange Unknown Resolution",
        "",
        f"- unknown_exchange_use_before: {unknown_before}",
        f"- unknown_exchange_use_after: {unknown_after}",
        f"- blocking_unknown_exchange_use: {blocking_unknown}",
        f"- exchange_unresolved_tier_a_review: {unresolved_tier_a}",
        "",
        "## Top unresolved production review queues",
    ]
    for fpath, c in top[:200]:
        res.append(f"- {fpath}: {c}")
    write_markdown(out / "EXCHANGE_UNKNOWN_RESOLUTION.md", "\n".join(res))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
