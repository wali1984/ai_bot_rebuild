"""Binance public archive backfill for trades, aggTrades, and klines only.

This is not an L2 orderbook replay source. It is a price/trade/candle backfill
tool for regimes before the direct orderbook recorder start date.

Runtime market data is WebSocket/cache primary. Binance archive HTTP downloads
are allowed only as an explicit REST fallback/backfill operation when
``BINANCE_REST_FALLBACK_ALLOWED=true`` is set.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from v2.backend.app.services.orderbook_recorder.features import utc_now_iso
from v2.backend.app.services.orderbook_recorder.status import GOAL_ID, LIVE_GATE, status_output_dirs
from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols
from v2.backend.app.services.binance_unified_websocket_transport import (
    REST_FALLBACK_ENV,
    binance_rest_fallback_allowed,
    require_binance_rest_fallback,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
DATA_BASE = "https://data.binance.vision/data"
ALLOWED_DATA_TYPES = {"trades", "aggTrades", "klines"}
ALLOWED_MARKETS = {"spot", "futures_um", "futures_cm"}
DEFAULT_OUT_DIR = REPO_ROOT / "v2/runtime/binance_public_backfill"


@dataclass(frozen=True)
class ArchiveRequest:
    market: str
    frequency: str
    data_type: str
    symbol: str
    day_or_month: str
    interval: str | None = None

    @property
    def relative_path(self) -> str:
        market_path = {
            "spot": "spot",
            "futures_um": "futures/um",
            "futures_cm": "futures/cm",
        }[self.market]
        if self.data_type == "klines":
            if not self.interval:
                raise ValueError("klines require interval")
            filename = f"{self.symbol}-{self.interval}-{self.day_or_month}.zip"
            return f"{market_path}/{self.frequency}/klines/{self.symbol}/{self.interval}/{filename}"
        filename = f"{self.symbol}-{self.data_type}-{self.day_or_month}.zip"
        return f"{market_path}/{self.frequency}/{self.data_type}/{self.symbol}/{filename}"

    @property
    def url(self) -> str:
        return f"{DATA_BASE}/{self.relative_path}"

    @property
    def checksum_url(self) -> str:
        return f"{self.url}.CHECKSUM"


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _iter_daily(start: date, end: date) -> Iterable[str]:
    current = start
    while current <= end:
        yield current.isoformat()
        current = date.fromordinal(current.toordinal() + 1)


def _iter_monthly(start: date, end: date) -> Iterable[str]:
    year = start.year
    month = start.month
    while (year, month) <= (end.year, end.month):
        yield f"{year:04d}-{month:02d}"
        month += 1
        if month > 12:
            year += 1
            month = 1


def build_archive_requests(
    *,
    symbols: list[str],
    market: str,
    frequency: str,
    data_types: list[str],
    intervals: list[str],
    start: date,
    end: date,
) -> list[ArchiveRequest]:
    if market not in ALLOWED_MARKETS:
        raise ValueError(f"unsupported_market:{market}")
    if frequency not in {"daily", "monthly"}:
        raise ValueError(f"unsupported_frequency:{frequency}")
    for data_type in data_types:
        if data_type not in ALLOWED_DATA_TYPES:
            raise ValueError(f"unsupported_data_type:{data_type}")
    windows = list(_iter_daily(start, end) if frequency == "daily" else _iter_monthly(start, end))
    requests: list[ArchiveRequest] = []
    for symbol in symbols:
        normalized = symbol.upper()
        for data_type in data_types:
            if data_type == "klines":
                for interval in intervals:
                    for window in windows:
                        requests.append(
                            ArchiveRequest(
                                market=market,
                                frequency=frequency,
                                data_type=data_type,
                                symbol=normalized,
                                interval=interval,
                                day_or_month=window,
                            )
                        )
            else:
                for window in windows:
                    requests.append(
                        ArchiveRequest(
                            market=market,
                            frequency=frequency,
                            data_type=data_type,
                            symbol=normalized,
                            day_or_month=window,
                        )
                    )
    return requests


def _download(url: str, target: Path, *, timeout: float = 30.0) -> int:
    try:
        require_binance_rest_fallback(
            endpoint=urllib.parse.urlparse(url).path or url,
            fallback_reason="operator_requested_public_archive_backfill",
            role="public_archive_backfill_recovery",
        )
    except RuntimeError as exc:
        message = str(exc).replace(
            "REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY",
            "BINANCE_REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY",
            1,
        )
        raise RuntimeError(message) from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "ai-bot-v2-binance-public-backfill"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read()
    target.write_bytes(data)
    return len(data)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _expected_checksum(text: str) -> str | None:
    for token in text.replace("*", " ").split():
        if len(token) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in token):
            return token.lower()
    return None


def verify_checksum(zip_path: Path, checksum_path: Path) -> bool:
    expected = _expected_checksum(checksum_path.read_text(encoding="utf-8"))
    return expected is not None and _sha256(zip_path).lower() == expected


def _zip_row_count(path: Path) -> int:
    try:
        with zipfile.ZipFile(path) as archive:
            total = 0
            for name in archive.namelist():
                if name.endswith("/"):
                    continue
                with archive.open(name) as fh:
                    total += sum(1 for _ in fh)
            return total
    except Exception:
        return 0


def run_backfill(args: argparse.Namespace) -> dict[str, Any]:
    symbols = resolve_symbols(explicit=args.symbols, smoke_test=args.smoke_test, include_baseline=True)
    data_types = [item.strip() for item in args.data_types.split(",") if item.strip()]
    intervals = [item.strip() for item in args.intervals.split(",") if item.strip()]
    start = _parse_date(args.start_date)
    end = _parse_date(args.end_date)
    requests = build_archive_requests(
        symbols=symbols,
        market=args.market,
        frequency=args.frequency,
        data_types=data_types,
        intervals=intervals,
        start=start,
        end=end,
    )
    out_dir = Path(args.out_dir)
    rows: list[dict[str, Any]] = []
    checksum_verified = 0
    downloaded = 0
    row_counts = {"trades": 0, "aggTrades": 0, "klines": 0}
    for request in requests[: max(0, int(args.max_files))]:
        target = out_dir / request.relative_path
        checksum_target = target.with_name(target.name + ".CHECKSUM")
        row: dict[str, Any] = {
            "symbol": request.symbol,
            "market": request.market,
            "frequency": request.frequency,
            "data_type": request.data_type,
            "interval": request.interval,
            "window": request.day_or_month,
            "url": request.url,
            "checksum_url": request.checksum_url,
            "target": str(target),
            "downloaded": False,
            "checksum_verified": False,
            "row_count": 0,
        }
        if args.download:
            try:
                _download(request.url, target)
                _download(request.checksum_url, checksum_target)
                row["downloaded"] = True
                row["checksum_verified"] = verify_checksum(target, checksum_target)
                row["row_count"] = _zip_row_count(target)
                downloaded += 1
                if row["checksum_verified"]:
                    checksum_verified += 1
                row_counts[request.data_type] += int(row["row_count"] or 0)
            except Exception as exc:  # noqa: BLE001
                row["error"] = f"{type(exc).__name__}:{exc}"
        rows.append(row)
    status = {
        "goal_id": GOAL_ID,
        "generated_at": utc_now_iso(),
        "worker_id": "v2_binance_public_data_backfill",
        "download_enabled": bool(args.download),
        "transport_policy": "binance_public_archive_backfill_rest_fallback_only",
        "websocket_primary_runtime_market_data": True,
        "rest_fallback_allowed": binance_rest_fallback_allowed(),
        "rest_fallback_env": REST_FALLBACK_ENV,
        "download_requires_env": f"{REST_FALLBACK_ENV}=true",
        "market": args.market,
        "frequency": args.frequency,
        "symbols_backfilled": sorted({row["symbol"] for row in rows if row.get("downloaded")}),
        "symbols_planned": symbols,
        "timeframes_backfilled": sorted({row["interval"] for row in rows if row.get("downloaded") and row.get("interval")}),
        "trades_backfilled": row_counts["trades"],
        "aggTrades_backfilled": row_counts["aggTrades"],
        "klines_backfilled": row_counts["klines"],
        "checksum_verified": checksum_verified == downloaded if downloaded else False,
        "checksum_verified_count": checksum_verified,
        "downloaded_files": downloaded,
        "planned_files": len(requests),
        "future_label_safe": True,
        "no_future_leakage": True,
        "available_at_rule": "archive rows must be available_at <= decision_time before trainer consumption",
        "historical_l2_claimed": False,
        "old_l2_replay_status": "NOT_PROVIDED_BY_BINANCE_PUBLIC_ARCHIVE",
        "live_gate": LIVE_GATE,
        "places_real_order": False,
        "test_orders": False,
        "rows": rows,
    }
    return status


def write_status(status: dict[str, Any]) -> None:
    public_dir, goal_dir = status_output_dirs(REPO_ROOT)
    for directory in (public_dir, goal_dir):
        target = directory / "binance_public_backfill_status.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="v2_binance_public_data_backfill")
    parser.add_argument("--symbols", default="BTCUSDT")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--market", choices=sorted(ALLOWED_MARKETS), default="futures_um")
    parser.add_argument("--frequency", choices=("daily", "monthly"), default="daily")
    parser.add_argument("--data-types", default="trades,aggTrades,klines")
    parser.add_argument("--intervals", default="1m")
    parser.add_argument("--start-date", default=datetime.now(timezone.utc).date().isoformat())
    parser.add_argument("--end-date", default=datetime.now(timezone.utc).date().isoformat())
    parser.add_argument("--max-files", type=int, default=12)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--write-status", action="store_true")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    status = run_backfill(args)
    if args.write_status:
        write_status(status)
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
