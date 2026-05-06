#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

WORKSPACE = Path("/home/wali/Desktop/AI BOT REBUILD")
LEGACY = Path("/home/wali/Desktop/AI BOT")
OUT = WORKSPACE / "claude_worklog/historical_pnl_audit"
BINANCE_FAPI = os.environ.get("BINANCE_FAPI_BASE_URL", "https://fapi.binance.com")

API_KEY_ENV_CANDIDATES = [
    "BINANCE_API_KEY",
    "BINANCE_FUTURES_API_KEY",
    "BINANCE_USDM_API_KEY",
]
API_SECRET_ENV_CANDIDATES = [
    "BINANCE_API_SECRET",
    "BINANCE_FUTURES_API_SECRET",
    "BINANCE_USDM_API_SECRET",
]
READONLY_ENDPOINTS = {
    "income": "/fapi/v1/income",
    "user_trades": "/fapi/v1/userTrades",
    "all_orders": "/fapi/v1/allOrders",
}
FORBIDDEN_METHODS = {"POST", "PUT", "DELETE"}
FORBIDDEN_PATH_TERMS = (
    "batchOrders",
    "leverage",
    "marginType",
    "positionSide/dual",
    "multiAssetsMargin",
    "countdownCancelAll",
    "transfer",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return Decimal("0")


def get_env_first(names: list[str]) -> tuple[str | None, str | None]:
    for name in names:
        value = os.environ.get(name)
        if value:
            return name, value
    return None, None


def sign_query(params: dict[str, Any], secret: str) -> str:
    query = urllib.parse.urlencode(params, doseq=True)
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    return f"{query}&signature={signature}"


def assert_readonly(method: str, path: str) -> None:
    if method.upper() in FORBIDDEN_METHODS:
        raise RuntimeError(f"forbidden_http_method:{method}")
    if path not in READONLY_ENDPOINTS.values():
        raise RuntimeError(f"non_allowlisted_binance_path:{path}")
    for term in FORBIDDEN_PATH_TERMS:
        if term in path:
            raise RuntimeError(f"forbidden_path_term:{term}")


def binance_get(
    path: str,
    params: dict[str, Any],
    api_key: str,
    api_secret: str,
) -> list[dict[str, Any]] | dict[str, Any]:
    assert_readonly("GET", path)
    query_params = dict(params)
    query_params["timestamp"] = int(time.time() * 1000)
    query_params.setdefault("recvWindow", 5000)
    signed = sign_query(query_params, api_secret)
    request = urllib.request.Request(
        f"{BINANCE_FAPI}{path}?{signed}",
        method="GET",
        headers={"X-MBX-APIKEY": api_key},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def chunk_windows(days: int, max_days: int = 7) -> list[tuple[int, int]]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    chunks: list[tuple[int, int]] = []
    cursor = start
    while cursor < end:
        nxt = min(cursor + timedelta(days=max_days) - timedelta(milliseconds=1), end)
        chunks.append((to_ms(cursor), to_ms(nxt)))
        cursor = nxt + timedelta(milliseconds=1)
    return chunks


def load_local_possible_sources() -> dict[str, list[str]]:
    roots = [WORKSPACE / "claude_worklog", LEGACY]
    patterns = ("*pnl*", "*trade*", "*order*", "*trainer*", "*prediction*", "*orchestrator*", "*trader*")
    found: dict[str, list[str]] = {}
    for root in roots:
        if not root.exists():
            continue
        rows: list[str] = []
        for pattern in patterns:
            for path in root.rglob(pattern):
                if path.is_file():
                    rows.append(str(path))
                if len(rows) >= 200:
                    break
            if len(rows) >= 200:
                break
        found[str(root)] = sorted(set(rows))[:200]
    return found


def pull_binance_history(days: int, symbols: list[str]) -> dict[str, Any]:
    key_name, api_key = get_env_first(API_KEY_ENV_CANDIDATES)
    secret_name, api_secret = get_env_first(API_SECRET_ENV_CANDIDATES)
    result: dict[str, Any] = {
        "generated_at": now_iso(),
        "days_requested": days,
        "api_key_env_present": bool(api_key),
        "api_key_env_name": key_name,
        "api_secret_env_present": bool(api_secret),
        "api_secret_env_name": secret_name,
        "base_url": BINANCE_FAPI,
        "income": [],
        "trades": [],
        "orders": [],
        "errors": [],
    }
    if not api_key or not api_secret:
        result["errors"].append("BINANCE_API_CREDENTIALS_NOT_FOUND_IN_ENV")
        return result

    for start_ms, end_ms in chunk_windows(days):
        try:
            rows = binance_get(
                READONLY_ENDPOINTS["income"],
                {"startTime": start_ms, "endTime": end_ms, "limit": 1000},
                api_key,
                api_secret,
            )
            if isinstance(rows, list):
                result["income"].extend(rows)
        except Exception as exc:
            result["errors"].append(f"income:{type(exc).__name__}:{exc}")

    for symbol in symbols:
        for start_ms, end_ms in chunk_windows(days):
            try:
                trades = binance_get(
                    READONLY_ENDPOINTS["user_trades"],
                    {"symbol": symbol, "startTime": start_ms, "endTime": end_ms, "limit": 1000},
                    api_key,
                    api_secret,
                )
                if isinstance(trades, list):
                    result["trades"].extend(trades)
            except Exception as exc:
                result["errors"].append(f"userTrades:{symbol}:{type(exc).__name__}:{exc}")

            try:
                orders = binance_get(
                    READONLY_ENDPOINTS["all_orders"],
                    {"symbol": symbol, "startTime": start_ms, "endTime": end_ms, "limit": 1000},
                    api_key,
                    api_secret,
                )
                if isinstance(orders, list):
                    result["orders"].extend(orders)
            except Exception as exc:
                result["errors"].append(f"allOrders:{symbol}:{type(exc).__name__}:{exc}")

    return result


def summarize_income(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_day: dict[str, Decimal] = defaultdict(Decimal)
    by_symbol: dict[str, Decimal] = defaultdict(Decimal)
    by_type: dict[str, Decimal] = defaultdict(Decimal)
    for row in rows:
        ts = row.get("time") or row.get("timestamp")
        day = "unknown"
        if ts:
            day = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc).date().isoformat()
        symbol = row.get("symbol") or "NO_SYMBOL"
        income_type = row.get("incomeType") or row.get("type") or "UNKNOWN"
        amount = dec(row.get("income"))
        by_day[day] += amount
        by_symbol[symbol] += amount
        by_type[income_type] += amount
    return {
        "row_count": len(rows),
        "by_day": {key: str(value) for key, value in sorted(by_day.items())},
        "by_symbol": {key: str(value) for key, value in sorted(by_symbol.items(), key=lambda item: item[1])},
        "by_type": {key: str(value) for key, value in sorted(by_type.items())},
    }


def summarize_trades(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count_by_symbol: dict[str, int] = defaultdict(int)
    quote_by_symbol: dict[str, Decimal] = defaultdict(Decimal)
    qty_by_symbol: dict[str, Decimal] = defaultdict(Decimal)
    for row in rows:
        symbol = row.get("symbol") or "NO_SYMBOL"
        count_by_symbol[symbol] += 1
        quote_by_symbol[symbol] += dec(row.get("quoteQty"))
        qty_by_symbol[symbol] += dec(row.get("qty"))
    return {
        "row_count": len(rows),
        "count_by_symbol": dict(sorted(count_by_symbol.items())),
        "quote_qty_by_symbol": {key: str(value) for key, value in sorted(quote_by_symbol.items())},
        "qty_by_symbol": {key: str(value) for key, value in sorted(qty_by_symbol.items())},
    }


def md_table(mapping: dict[str, str], key_header: str, value_header: str) -> str:
    lines = [f"| {key_header} | {value_header} |", "|---|---:|"]
    if not mapping:
        lines.append("| `NO_DATA` | 0 |")
        return "\n".join(lines)
    for key, value in mapping.items():
        lines.append(f"| `{key}` | {value} |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--symbols", default="")
    parser.add_argument("--binance", action="store_true")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    local_sources = load_local_possible_sources()
    binance_data = (
        pull_binance_history(args.days, symbols)
        if args.binance
        else {
            "generated_at": now_iso(),
            "days_requested": args.days,
            "api_key_env_present": False,
            "api_secret_env_present": False,
            "income": [],
            "trades": [],
            "orders": [],
            "errors": ["BINANCE_PULL_NOT_REQUESTED"],
        }
    )
    income_summary = summarize_income(binance_data.get("income", []))
    trade_summary = summarize_trades(binance_data.get("trades", []))

    write(
        OUT / "00_AUDIT_INDEX.md",
        "\n".join(
            [
                "# Historical PnL / Trade / Trainer Audit Index",
                "",
                f"Generated: {now_iso()}",
                "",
                "- `01_DATA_SOURCE_STATUS.md`",
                "- `02_BINANCE_READONLY_PULL_SUMMARY.md`",
                "- `03_30D_REALIZED_PNL_BY_DAY.md`",
                "- `04_30D_PNL_BY_SYMBOL.md`",
                "- `05_30D_FEES_FUNDING_COMMISSION.md`",
                "- `06_LARGE_WINNERS_AND_LOSERS.md`",
                "- `07_LEGACY_TRAINER_DECISION_EVIDENCE.md`",
                "- `08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md`",
                "- `09_V2_BUILD_IMPACT_MAP.md`",
                "- `10_GO_NO_GO.md`",
                "",
            ]
        ),
    )
    write(
        OUT / "01_DATA_SOURCE_STATUS.md",
        "\n".join(
            [
                "# Data Source Status",
                "",
                f"Generated: {now_iso()}",
                "",
                f"- requested_days: {args.days}",
                f"- binance_pull_requested: {args.binance}",
                f"- binance_api_key_env_present: {binance_data.get('api_key_env_present')}",
                f"- binance_api_key_env_name: {binance_data.get('api_key_env_name')}",
                f"- binance_api_secret_env_present: {binance_data.get('api_secret_env_present')}",
                f"- binance_api_secret_env_name: {binance_data.get('api_secret_env_name')}",
                f"- symbols_requested_for_trade_order_history: {', '.join(symbols) if symbols else 'none'}",
                "",
                "## Local candidate evidence files",
                "```json",
                json.dumps(local_sources, indent=2)[:20000],
                "```",
                "",
                "No secret values are printed.",
                "",
            ]
        ),
    )
    write(
        OUT / "02_BINANCE_READONLY_PULL_SUMMARY.md",
        "\n".join(
            [
                "# Binance Read-Only Pull Summary",
                "",
                f"Generated: {now_iso()}",
                "",
                "Only read-only GET endpoints are allowed.",
                "",
                f"- income_rows: {len(binance_data.get('income', []))}",
                f"- trade_rows: {len(binance_data.get('trades', []))}",
                f"- order_rows: {len(binance_data.get('orders', []))}",
                "",
                "## Errors / gaps",
                "```json",
                json.dumps(binance_data.get("errors", []), indent=2),
                "```",
                "",
            ]
        ),
    )
    write(OUT / "03_30D_REALIZED_PNL_BY_DAY.md", "# 30D Realized PnL By Day\n\n" + md_table(income_summary["by_day"], "day", "income_sum") + "\n")
    write(OUT / "04_30D_PNL_BY_SYMBOL.md", "# 30D PnL By Symbol\n\n" + md_table(income_summary["by_symbol"], "symbol", "income_sum") + "\n")
    write(OUT / "05_30D_FEES_FUNDING_COMMISSION.md", "# 30D Fees / Funding / Commission\n\n" + md_table(income_summary["by_type"], "income_type", "income_sum") + "\n")

    sorted_symbols = sorted(income_summary["by_symbol"].items(), key=lambda item: dec(item[1]))
    losers = dict(sorted_symbols[:20])
    winners = dict(reversed(sorted_symbols[-20:]))
    write(
        OUT / "06_LARGE_WINNERS_AND_LOSERS.md",
        "# Large Winners and Losers\n\n## Largest losers\n"
        + md_table(losers, "symbol", "income_sum")
        + "\n\n## Largest winners\n"
        + md_table(winners, "symbol", "income_sum")
        + "\n",
    )
    write(
        OUT / "07_LEGACY_TRAINER_DECISION_EVIDENCE.md",
        "\n".join(
            [
                "# Legacy Trainer / Decision Evidence",
                "",
                f"Generated: {now_iso()}",
                "",
                "Candidate local evidence is indexed without dumping secrets.",
                "",
                "## Trade summary",
                "```json",
                json.dumps(trade_summary, indent=2)[:20000],
                "```",
                "",
            ]
        ),
    )
    write(
        OUT / "08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md",
        "\n".join(
            [
                "# Failure Patterns and V2 Requirements",
                "",
                f"Generated: {now_iso()}",
                "",
                "- identify symbols with repeated realized losses",
                "- identify fee/funding drag",
                "- compare large losers to trainer confidence and feature freshness",
                "- detect hedge unwind residual exposure failures",
                "- detect shorting bottoms / longing tops",
                "- require risk gateway default-deny on stale/missing data",
                "- require replay/backtest scenarios for large loser patterns",
                "",
            ]
        ),
    )
    write(
        OUT / "09_V2_BUILD_IMPACT_MAP.md",
        "\n".join(
            [
                "# V2 Build Impact Map",
                "",
                f"Generated: {now_iso()}",
                "",
                "| Historical evidence | V2 impact | MVP lane |",
                "|---|---|---|",
                "| Realized PnL by symbol | risk gateway symbol risk, replay cases | paper_backtest_mvp |",
                "| Fee/funding/commission drag | risk-adjusted paper ledger, net PnL accounting | paper_backtest_mvp |",
                "| Large winners/losers | trainer attribution, strategy regime scoring | paper_backtest_mvp |",
                "| Trainer/orchestrator evidence | prediction_id, decision_id, lineage | paper_backtest_mvp |",
                "| LAB hedge unwind | residual exposure risk gate, hedge close test | paper_backtest_mvp |",
                "",
            ]
        ),
    )
    marker = "HISTORICAL_PNL_TRADE_TRAINER_AUDIT_READY"
    if binance_data.get("errors") and not binance_data.get("income"):
        marker = "HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY"
    write(OUT / "10_GO_NO_GO.md", marker + "\n")
    print(marker)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
