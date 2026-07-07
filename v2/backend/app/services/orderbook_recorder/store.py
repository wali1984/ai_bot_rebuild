"""Local forward replay store for direct orderbook recordings."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .features import utc_now_iso


@dataclass(frozen=True)
class ReplayStoreWrite:
    path: Path
    bytes_written: int
    record_type: str


class LocalReplayStore:
    """Append-only JSONL replay store partitioned by exchange/symbol/date/hour."""

    def __init__(self, root: Path | str = "v2/runtime/orderbook_replay") -> None:
        self.root = Path(root)

    def append(
        self,
        *,
        exchange: str,
        symbol: str,
        record_type: str,
        payload: dict[str, Any],
        event_time: str | None = None,
    ) -> ReplayStoreWrite:
        partition = self._partition_path(
            exchange=exchange,
            symbol=symbol,
            record_type=record_type,
            event_time=event_time or str(payload.get("event_time") or payload.get("available_at") or ""),
        )
        partition.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "record_type": record_type,
            "stored_at": utc_now_iso(),
            "exchange": exchange,
            "symbol": symbol,
            "payload": payload,
        }
        line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        with partition.open("a", encoding="utf-8") as fh:
            written = fh.write(line)
        return ReplayStoreWrite(path=partition, bytes_written=written, record_type=record_type)

    def status(self) -> dict[str, Any]:
        files = [path for path in self.root.rglob("*.jsonl") if path.is_file()]
        symbols: set[str] = set()
        symbols_by_exchange: dict[str, set[str]] = {}
        raw_delta_symbols: set[str] = set()
        feature_only_symbols: set[str] = set()
        historical_sequence_gap_symbols: set[str] = set()
        latest_gap_by_symbol: dict[str, tuple[str, bool]] = {}
        update_type_counts: dict[str, int] = {}
        feed_coverage: dict[str, dict[str, Any]] = {}
        oldest: str | None = None
        newest: str | None = None
        total_bytes = 0
        per_hour: dict[str, int] = {}
        files_with_usable_orderbook_rows = 0
        for path in files:
            total_bytes += path.stat().st_size
            try:
                relative_parts = path.relative_to(self.root).parts
                exchange = relative_parts[0]
                symbol = relative_parts[1]
            except (ValueError, IndexError):
                exchange = "unknown"
                symbol = "unknown"
            if "raw_delta" in path.name:
                raw_delta_symbols.add(f"{exchange}:{symbol}")
            if "features" in path.name:
                feature_only_symbols.add(f"{exchange}:{symbol}")
            hour_key = "/".join(path.parts[-5:-1])
            per_hour[hour_key] = per_hour.get(hour_key, 0) + path.stat().st_size
            file_had_usable_row = False
            for stamp, sequence_gap, update_type, depth_level, feed_speed_ms in self._iter_file_timestamps(path):
                file_had_usable_row = True
                symbol_key = f"{exchange}:{symbol}"
                symbols.add(symbol_key)
                symbols_by_exchange.setdefault(exchange, set()).add(symbol)
                if oldest is None or stamp < oldest:
                    oldest = stamp
                if newest is None or stamp > newest:
                    newest = stamp
                if sequence_gap:
                    historical_sequence_gap_symbols.add(symbol_key)
                latest = latest_gap_by_symbol.get(symbol_key)
                if latest is None or stamp >= latest[0]:
                    latest_gap_by_symbol[symbol_key] = (stamp, sequence_gap)
                if update_type:
                    update_type_counts[f"{exchange}:{update_type}"] = update_type_counts.get(f"{exchange}:{update_type}", 0) + 1
                    item = feed_coverage.setdefault(
                        symbol_key,
                        {
                            "exchange": exchange,
                            "symbol": symbol,
                            "update_types": {},
                            "depth_levels": [],
                            "feed_speeds_ms": [],
                            "has_book_ticker": False,
                            "has_diff_depth": False,
                            "has_partial_depth": False,
                            "has_kucoin_increment_best_500": False,
                        },
                    )
                    item["update_types"][update_type] = int(item["update_types"].get(update_type, 0)) + 1
                    if depth_level is not None and depth_level not in item["depth_levels"]:
                        item["depth_levels"].append(depth_level)
                    if feed_speed_ms is not None and feed_speed_ms not in item["feed_speeds_ms"]:
                        item["feed_speeds_ms"].append(feed_speed_ms)
                    if update_type == "book_ticker":
                        item["has_book_ticker"] = True
                    if update_type == "diff_depth":
                        item["has_diff_depth"] = True
                    if update_type == "partial_depth":
                        item["has_partial_depth"] = True
                    if depth_level == "increment_best_500" or update_type in {"obu_increment", "obu_increment@10ms"}:
                        item["has_kucoin_increment_best_500"] = True
            if file_had_usable_row:
                files_with_usable_orderbook_rows += 1
        raw_delta_symbol_set = set(raw_delta_symbols)
        feature_only_symbol_set = feature_only_symbols - raw_delta_symbol_set
        active_exchanges = sorted(exchange for exchange, exchange_symbols in symbols_by_exchange.items() if exchange_symbols)
        current_sequence_gap_symbols = sorted(
            symbol_key
            for symbol_key, (_stamp, sequence_gap) in latest_gap_by_symbol.items()
            if sequence_gap
        )
        for item in feed_coverage.values():
            item["depth_levels"] = sorted(item["depth_levels"], key=lambda value: str(value))
            item["feed_speeds_ms"] = sorted(item["feed_speeds_ms"])
        return {
            "generated_at": utc_now_iso(),
            "root": str(self.root),
            "format": "jsonl",
            "files": len(files),
            "files_with_usable_orderbook_rows": files_with_usable_orderbook_rows,
            "disk_usage": total_bytes,
            "symbols_recorded": len(symbols),
            "active_exchanges": active_exchanges,
            "exchange_symbol_counts": {
                exchange: len(exchange_symbols)
                for exchange, exchange_symbols in sorted(symbols_by_exchange.items())
            },
            "symbols_by_exchange": {
                exchange: sorted(exchange_symbols)
                for exchange, exchange_symbols in sorted(symbols_by_exchange.items())
            },
            "raw_delta_symbols": sorted(raw_delta_symbol_set),
            "feature_only_symbols": sorted(feature_only_symbol_set),
            "raw_delta_symbol_count": len(raw_delta_symbol_set),
            "feature_only_symbol_count": len(feature_only_symbol_set),
            "sequence_gap_symbols": current_sequence_gap_symbols,
            "sequence_gap_symbol_count": len(current_sequence_gap_symbols),
            "historical_sequence_gap_symbols": sorted(historical_sequence_gap_symbols),
            "historical_sequence_gap_symbol_count": len(historical_sequence_gap_symbols),
            "feed_coverage": dict(sorted(feed_coverage.items())),
            "update_type_counts": dict(sorted(update_type_counts.items())),
            "bytes_per_hour": per_hour,
            "oldest_replay_timestamp": oldest,
            "newest_replay_timestamp": newest,
        }

    def _partition_path(
        self,
        *,
        exchange: str,
        symbol: str,
        record_type: str,
        event_time: str,
    ) -> Path:
        dt = _parse_time(event_time) or datetime.now(timezone.utc)
        return (
            self.root
            / exchange
            / symbol.upper()
            / f"{dt:%Y-%m-%d}"
            / f"{dt:%H}"
            / f"{record_type}.jsonl"
        )

    @staticmethod
    def _iter_file_timestamps(path: Path) -> Iterable[tuple[str, bool, str | None, Any, int | None]]:
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    payload = row.get("payload") if isinstance(row, dict) else None
                    if isinstance(payload, dict):
                        if not _payload_has_usable_book(payload):
                            continue
                        sequence_gap = bool(payload.get("sequence_gap") or payload.get("sequence_gap_flag"))
                        update_type = str(payload.get("update_type") or "") or None
                        depth_level = payload.get("depth_level")
                        feed_speed_ms = _int_or_none(payload.get("feed_speed_ms"))
                        for key in ("event_time", "available_at", "received_at", "generated_at"):
                            value = payload.get(key)
                            if isinstance(value, str) and value:
                                yield value, sequence_gap, update_type, depth_level, feed_speed_ms
                                break
        except OSError:
            return


def _parse_time(value: str) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _payload_has_usable_book(payload: dict[str, Any]) -> bool:
    if payload.get("bid") is not None and payload.get("ask") is not None:
        return True
    if payload.get("best_bid") is not None and payload.get("best_ask") is not None:
        return True
    bids = payload.get("bids") or []
    asks = payload.get("asks") or []
    return bool(bids) and bool(asks)
