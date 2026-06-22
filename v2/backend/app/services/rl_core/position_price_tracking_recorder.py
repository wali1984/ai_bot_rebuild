"""V2-owned paper position price tracking recorder.

The recorder builds price-track and position-history payloads from V2
paper/runtime state only. It never reads legacy state, never writes old
Redis keys, never places exchange orders, and never fabricates entry or
latest prices.

The recorder also burns down the entry-price and realized-exit gap that
left MFE/MAE/ROE uncomputable for BTC/ETH and flat for SOL: when the
V2 paper position row does not yet carry an entry price, the recorder
attempts to recover one from V2-owned paper ledger / intent rows only,
and detects realized exit prices from V2-owned close events. Sources
recovered this way are surfaced explicitly via ``entry_price_source``
and ``realized_exit_source`` so downstream consumers can quote the
provenance instead of guessing.
"""
from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

KEY_PRICE_TRACK_TEMPLATE = "v2:paper:position_price_track:{symbol}"
KEY_HISTORY_TEMPLATE = "v2:paper:position_history:{symbol}"
KEY_HEARTBEAT = "v2:paper:position_history:heartbeat"

MISSING_ENTRY_PRICE = "MISSING_ENTRY_PRICE"
MISSING_LATEST_PRICE = "MISSING_LATEST_PRICE"
MISSING_OPEN_POSITION = "FLAT_NO_OPEN_POSITION"
SOURCE_RECORDER = "V2_POSITION_PRICE_TRACKING_RECORDER"

ENTRY_SOURCE_POSITION = "V2_PAPER_POSITION_ROW"
ENTRY_SOURCE_LEDGER_ACCEPTED = "V2_PAPER_LEDGER_ACCEPTED"
ENTRY_SOURCE_LEDGER_HELD = "V2_PAPER_LEDGER_HELD_BY_PAPER_FILL_GATE"
ENTRY_SOURCE_LEDGER_LAST_CLOSED = "V2_PAPER_LEDGER_LAST_CLOSED_POSITION"
ENTRY_SOURCE_LEDGER_GENERIC = "V2_PAPER_LEDGER_GENERIC"
ENTRY_SOURCE_INTENTS = "V2_PAPER_INTENTS"
ENTRY_SOURCE_INTENTS_HELD = "V2_PAPER_INTENTS_HELD_BY_PAPER_FILL_GATE"
ENTRY_SOURCE_PREVIOUS_TRACK = "V2_PREVIOUS_TRACK_RECORDER_CARRYOVER"
ENTRY_SOURCE_MISSING = "MISSING_ENTRY_PRICE_FROM_V2_PAPER_INPUTS"

EXIT_SOURCE_LEDGER_CLOSE_EVENT = "V2_PAPER_LEDGER_CLOSE_EVENT"
EXIT_SOURCE_LEDGER_LAST_CLOSED = "V2_PAPER_LEDGER_LAST_CLOSED_POSITION"
EXIT_SOURCE_PREVIOUS_TRACK = "V2_PREVIOUS_TRACK_RECORDER_CARRYOVER"
EXIT_SOURCE_NONE = "NO_REALIZED_EXIT_RECORDED_YET"

ENTRY_PRICE_FIELDS = (
    "entry_price",
    "entryPrice",
    "fill_price",
    "filled_price",
    "open_price",
    "fillPrice",
    "filledPrice",
    "avg_entry_price",
)
EXIT_PRICE_FIELDS = (
    "exit_price",
    "exitPrice",
    "realized_exit_price",
    "close_price",
    "closing_price",
    "last_exit_price",
)
CLOSED_LEDGER_ACTIONS = {
    "PAPER_POSITION_CLOSED",
    "POSITION_CLOSED",
    "POSITION_CLOSED_PAPER_ONLY",
}
CLOSED_PAPER_RESULTS = {
    "POSITION_CLOSED_PAPER_ONLY",
    "POSITION_CLOSED",
}


def utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        try:
            out = float(value)
        except (TypeError, ValueError):
            return None
        return out if out == out else None
    if isinstance(value, str):
        try:
            out = float(value)
        except (TypeError, ValueError):
            return None
        return out if out == out else None
    return None


def _row_matches_symbol(row: Any, symbol_upper: str) -> bool:
    if not isinstance(row, Mapping):
        return False
    return (row.get("symbol") or "").upper() == symbol_upper


def _find_symbol_row(rows: Iterable[Mapping[str, Any]] | None, symbol: str) -> dict[str, Any] | None:
    symbol_upper = symbol.upper()
    for row in rows or []:
        if _row_matches_symbol(row, symbol_upper):
            return dict(row)
    return None


def _extract_latest_price(market_price: Mapping[str, Any] | None) -> tuple[float | None, str | None]:
    if not isinstance(market_price, Mapping):
        return None, None
    candidates = [
        market_price.get("last_price"),
        market_price.get("latest_price"),
        market_price.get("price"),
        (market_price.get("ticker_24hr") or {}).get("lastPrice")
        if isinstance(market_price.get("ticker_24hr"), Mapping)
        else None,
        (market_price.get("funding") or {}).get("markPrice")
        if isinstance(market_price.get("funding"), Mapping)
        else None,
    ]
    for value in candidates:
        parsed = _coerce_float(value)
        if parsed is not None and parsed > 0.0:
            fetched = market_price.get("fetched_utc") or market_price.get("generated_utc")
            return parsed, str(fetched) if fetched else None
    return None, None


def _scan_row_for_price(row: Mapping[str, Any], fields: tuple[str, ...]) -> float | None:
    for field in fields:
        parsed = _coerce_float(row.get(field))
        if parsed is not None and parsed > 0.0:
            return parsed
    return None


def _extract_entry_price(
    position: Mapping[str, Any] | None,
    paper_ledger: Mapping[str, Any] | None,
    paper_intents: Iterable[Mapping[str, Any]] | None,
    paper_intents_held: Iterable[Mapping[str, Any]] | None,
    previous_track: Mapping[str, Any] | None,
    symbol_upper: str,
) -> tuple[float | None, str]:
    """Return (entry_price, source). Search order is strictly V2-owned.

    The recorder never invents an entry price; it only recovers one
    from a V2-owned paper input. Sources are surfaced verbatim so the
    aggregator and operator dashboard can quote provenance.
    """
    if isinstance(position, Mapping):
        parsed = _scan_row_for_price(position, ENTRY_PRICE_FIELDS)
        if parsed is not None:
            return parsed, ENTRY_SOURCE_POSITION

    ledger_groups: tuple[tuple[str, Any], ...] = ()
    if isinstance(paper_ledger, Mapping):
        ledger_groups = (
            ("accepted", paper_ledger.get("accepted")),
            ("held_by_paper_fill_gate", paper_ledger.get("held_by_paper_fill_gate")),
            ("blocked", paper_ledger.get("blocked")),
        )
        last_closed = paper_ledger.get("last_closed_position")
        if isinstance(last_closed, Mapping) and _row_matches_symbol(last_closed, symbol_upper):
            parsed = _scan_row_for_price(last_closed, ENTRY_PRICE_FIELDS)
            if parsed is not None:
                return parsed, ENTRY_SOURCE_LEDGER_LAST_CLOSED

    for group_name, rows in ledger_groups:
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not _row_matches_symbol(row, symbol_upper):
                continue
            parsed = _scan_row_for_price(row, ENTRY_PRICE_FIELDS)
            if parsed is None:
                continue
            if group_name == "accepted":
                return parsed, ENTRY_SOURCE_LEDGER_ACCEPTED
            if group_name == "held_by_paper_fill_gate":
                return parsed, ENTRY_SOURCE_LEDGER_HELD
            return parsed, ENTRY_SOURCE_LEDGER_GENERIC

    if isinstance(paper_ledger, Mapping):
        for key, value in paper_ledger.items():
            if isinstance(value, Mapping) and _row_matches_symbol(value, symbol_upper):
                parsed = _scan_row_for_price(value, ENTRY_PRICE_FIELDS)
                if parsed is not None:
                    return parsed, ENTRY_SOURCE_LEDGER_GENERIC
            if isinstance(value, list) and key not in {"accepted", "blocked", "held_by_paper_fill_gate"}:
                for row in value:
                    if _row_matches_symbol(row, symbol_upper):
                        parsed = _scan_row_for_price(row, ENTRY_PRICE_FIELDS)
                        if parsed is not None:
                            return parsed, ENTRY_SOURCE_LEDGER_GENERIC

    for row in paper_intents or []:
        if _row_matches_symbol(row, symbol_upper):
            parsed = _scan_row_for_price(row, ENTRY_PRICE_FIELDS)
            if parsed is not None:
                return parsed, ENTRY_SOURCE_INTENTS

    for row in paper_intents_held or []:
        if _row_matches_symbol(row, symbol_upper):
            parsed = _scan_row_for_price(row, ENTRY_PRICE_FIELDS)
            if parsed is not None:
                return parsed, ENTRY_SOURCE_INTENTS_HELD

    if isinstance(previous_track, Mapping):
        parsed = _scan_row_for_price(previous_track, ENTRY_PRICE_FIELDS)
        if parsed is not None:
            return parsed, ENTRY_SOURCE_PREVIOUS_TRACK

    return None, ENTRY_SOURCE_MISSING


def _row_is_close_event(row: Mapping[str, Any]) -> bool:
    if str(row.get("ledger_action") or "").upper() in CLOSED_LEDGER_ACTIONS:
        return True
    if str(row.get("paper_result") or "").upper() in CLOSED_PAPER_RESULTS:
        return True
    if row.get("closed_at") or row.get("close_event") or row.get("realized_delta_usdt") is not None:
        if _scan_row_for_price(row, EXIT_PRICE_FIELDS) is not None:
            return True
    return False


def _extract_realized_exit(
    paper_ledger: Mapping[str, Any] | None,
    paper_intents: Iterable[Mapping[str, Any]] | None,
    previous_track: Mapping[str, Any] | None,
    symbol_upper: str,
) -> tuple[float | None, str, str | None]:
    """Return (exit_price, source, generated_utc) recovered from V2-owned
    paper close events only. ``previous_track`` carryover is used so the
    realized exit price persists once the symbol returns to FLAT.
    """
    best_price: float | None = None
    best_source: str | None = None
    best_ts: str | None = None

    def _consider(price: float, source: str, ts: Any) -> None:
        nonlocal best_price, best_source, best_ts
        candidate_ts = str(ts) if ts else None
        if best_price is None:
            best_price = price
            best_source = source
            best_ts = candidate_ts
            return
        previous_parsed = _parse_utc(best_ts)
        candidate_parsed = _parse_utc(candidate_ts)
        if candidate_parsed is not None and (previous_parsed is None or candidate_parsed >= previous_parsed):
            best_price = price
            best_source = source
            best_ts = candidate_ts

    if isinstance(paper_ledger, Mapping):
        last_closed = paper_ledger.get("last_closed_position")
        if isinstance(last_closed, Mapping) and _row_matches_symbol(last_closed, symbol_upper):
            exit_price = _scan_row_for_price(last_closed, EXIT_PRICE_FIELDS)
            if exit_price is not None:
                _consider(
                    exit_price,
                    EXIT_SOURCE_LEDGER_LAST_CLOSED,
                    last_closed.get("closed_at") or last_closed.get("generated_at"),
                )
        for key in ("closed", "closed_positions", "events", "history", "accepted", "blocked"):
            rows = paper_ledger.get(key)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not _row_matches_symbol(row, symbol_upper):
                    continue
                if not _row_is_close_event(row):
                    continue
                exit_price = _scan_row_for_price(row, EXIT_PRICE_FIELDS)
                if exit_price is not None:
                    _consider(
                        exit_price,
                        EXIT_SOURCE_LEDGER_CLOSE_EVENT,
                        row.get("closed_at") or row.get("generated_at") or row.get("generated_utc"),
                    )

    for row in paper_intents or []:
        if not _row_matches_symbol(row, symbol_upper):
            continue
        if not _row_is_close_event(row):
            continue
        exit_price = _scan_row_for_price(row, EXIT_PRICE_FIELDS)
        if exit_price is not None:
            _consider(
                exit_price,
                EXIT_SOURCE_LEDGER_CLOSE_EVENT,
                row.get("closed_at") or row.get("generated_utc"),
            )

    if best_price is None and isinstance(previous_track, Mapping):
        previous_exit = _coerce_float(previous_track.get("realized_exit_price"))
        if previous_exit is not None and previous_exit > 0.0:
            return (
                previous_exit,
                EXIT_SOURCE_PREVIOUS_TRACK,
                str(previous_track.get("realized_exit_utc") or previous_track.get("generated_utc") or ""),
            )

    if best_price is None:
        return None, EXIT_SOURCE_NONE, None
    return best_price, best_source or EXIT_SOURCE_LEDGER_CLOSE_EVENT, best_ts


def _hold_time_seconds(position: Mapping[str, Any] | None, now: datetime) -> float | None:
    opened = _parse_utc((position or {}).get("generated_utc"))
    if opened is None:
        return None
    return max(0.0, float((now - opened).total_seconds()))


def _age_seconds(ts: str | None, now: datetime) -> int | None:
    parsed = _parse_utc(ts)
    if parsed is None:
        return None
    return max(0, int((now - parsed).total_seconds()))


def _bps_for_side(entry_price: float, latest_price: float, side: str) -> float:
    if side == "short":
        return ((entry_price - latest_price) / entry_price) * 10_000.0
    return ((latest_price - entry_price) / entry_price) * 10_000.0


def _excursion_bps(entry_price: float, min_price: float, max_price: float, side: str) -> tuple[float, float]:
    if side == "short":
        mfe = ((entry_price - min_price) / entry_price) * 10_000.0
        mae = ((entry_price - max_price) / entry_price) * 10_000.0
    else:
        mfe = ((max_price - entry_price) / entry_price) * 10_000.0
        mae = ((min_price - entry_price) / entry_price) * 10_000.0
    return round(mfe, 6), round(mae, 6)


def _allowed_key(key: str) -> bool:
    return (
        key == KEY_HEARTBEAT
        or key.startswith("v2:paper:position_price_track:")
        or key.startswith("v2:paper:position_history:")
    )


def safe_redis_set(redis_client: Any, key: str, payload: Mapping[str, Any], *, ex: int = 900) -> bool:
    if redis_client is None or not isinstance(key, str) or not _allowed_key(key):
        return False
    try:
        redis_client.set(key, json.dumps(dict(payload), sort_keys=True), ex=int(ex))
        return True
    except Exception:
        return False


@dataclasses.dataclass(frozen=True)
class PositionTrack:
    symbol: str
    position_state: str
    side: str | None
    entry_price: float | None
    entry_price_source: str
    latest_price: float | None
    min_price_since_entry: float | None
    max_price_since_entry: float | None
    mfe_bps: float | None
    mae_bps: float | None
    roe_bps: float | None
    hold_time_seconds: float | None
    realized_exit_price: float | None
    realized_exit_source: str
    realized_exit_utc: str | None
    source_freshness_seconds: int | None
    missing_flags: tuple[str, ...]
    stale_flags: tuple[str, ...]
    generated_utc: str

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema_version": "v2_position_price_track_v1",
            "generated_utc": self.generated_utc,
            "symbol": self.symbol,
            "position_state": self.position_state,
            "side": self.side,
            "entry_price": self.entry_price,
            "entry_price_source": self.entry_price_source,
            "latest_price": self.latest_price,
            "min_price_since_entry": self.min_price_since_entry,
            "max_price_since_entry": self.max_price_since_entry,
            "mfe_bps": self.mfe_bps,
            "mae_bps": self.mae_bps,
            "roe_bps": self.roe_bps,
            "hold_time_seconds": self.hold_time_seconds,
            "realized_exit_price": self.realized_exit_price,
            "realized_exit_source": self.realized_exit_source,
            "realized_exit_utc": self.realized_exit_utc,
            "source_freshness_seconds": self.source_freshness_seconds,
            "missing_flags": list(self.missing_flags),
            "stale_flags": list(self.stale_flags),
            "source": SOURCE_RECORDER,
            "no_fake_price_tracks": True,
            "no_silent_zero_fill": True,
            "writes_legacy_redis": False,
            "writes_exchange_orders": False,
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
        }


def _flat_with_optional_exit(
    *,
    symbol_upper: str,
    generated: str,
    realized_exit_price: float | None,
    realized_exit_source: str,
    realized_exit_utc: str | None,
    previous_track: Mapping[str, Any] | None,
) -> PositionTrack:
    """Build a FLAT/CLOSED_REALIZED track when no open V2 paper position exists.

    When a V2-owned realized exit price is available, the track is
    CLOSED_REALIZED and the previous track's entry/min/max are carried
    forward so MFE/MAE/ROE can still be reported against the realized
    exit price without inventing prices.
    """
    if realized_exit_price is None:
        return PositionTrack(
            symbol=symbol_upper,
            position_state="FLAT",
            side=None,
            entry_price=None,
            entry_price_source=ENTRY_SOURCE_MISSING,
            latest_price=None,
            min_price_since_entry=None,
            max_price_since_entry=None,
            mfe_bps=None,
            mae_bps=None,
            roe_bps=None,
            hold_time_seconds=None,
            realized_exit_price=None,
            realized_exit_source=EXIT_SOURCE_NONE,
            realized_exit_utc=None,
            source_freshness_seconds=None,
            missing_flags=(MISSING_OPEN_POSITION,),
            stale_flags=(),
            generated_utc=generated,
        )

    previous_entry = _coerce_float((previous_track or {}).get("entry_price")) if previous_track else None
    previous_min = _coerce_float((previous_track or {}).get("min_price_since_entry")) if previous_track else None
    previous_max = _coerce_float((previous_track or {}).get("max_price_since_entry")) if previous_track else None
    previous_side = str((previous_track or {}).get("side") or "long").lower() if previous_track else "long"
    if previous_side not in {"long", "short"}:
        previous_side = "long"
    missing: list[str] = []
    mfe = mae = roe = None
    min_anchor: float | None = None
    max_anchor: float | None = None
    if previous_entry is not None and previous_entry > 0.0:
        min_anchor = min(v for v in (previous_entry, realized_exit_price, previous_min) if v is not None)
        max_anchor = max(v for v in (previous_entry, realized_exit_price, previous_max) if v is not None)
        mfe, mae = _excursion_bps(previous_entry, min_anchor, max_anchor, previous_side)
        roe = round(_bps_for_side(previous_entry, realized_exit_price, previous_side), 6)
    else:
        missing.append(MISSING_ENTRY_PRICE)
    return PositionTrack(
        symbol=symbol_upper,
        position_state="CLOSED_REALIZED",
        side=previous_side,
        entry_price=round(previous_entry, 12) if previous_entry is not None else None,
        entry_price_source=(
            ENTRY_SOURCE_PREVIOUS_TRACK
            if previous_entry is not None and previous_entry > 0.0
            else ENTRY_SOURCE_MISSING
        ),
        latest_price=round(realized_exit_price, 12),
        min_price_since_entry=round(min_anchor, 12) if min_anchor is not None else None,
        max_price_since_entry=round(max_anchor, 12) if max_anchor is not None else None,
        mfe_bps=mfe,
        mae_bps=mae,
        roe_bps=roe,
        hold_time_seconds=None,
        realized_exit_price=round(realized_exit_price, 12),
        realized_exit_source=realized_exit_source,
        realized_exit_utc=realized_exit_utc,
        source_freshness_seconds=None,
        missing_flags=tuple(missing),
        stale_flags=(),
        generated_utc=generated,
    )


def build_position_track(
    *,
    symbol: str,
    paper_positions: Iterable[Mapping[str, Any]] | None,
    paper_ledger: Mapping[str, Any] | None,
    market_price: Mapping[str, Any] | None,
    prediction: Mapping[str, Any] | None = None,
    paper_intents: Iterable[Mapping[str, Any]] | None = None,
    paper_intents_held: Iterable[Mapping[str, Any]] | None = None,
    previous_track: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    max_source_age_seconds: int = 300,
) -> PositionTrack:
    del prediction
    now = now or datetime.now(timezone.utc)
    generated = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    symbol_upper = symbol.upper()
    paper_intents_list = list(paper_intents or [])
    paper_intents_held_list = list(paper_intents_held or [])
    position = _find_symbol_row(paper_positions, symbol_upper)
    realized_exit_price, realized_exit_source, realized_exit_utc = _extract_realized_exit(
        paper_ledger,
        paper_intents_list,
        previous_track,
        symbol_upper,
    )
    if position is None:
        return _flat_with_optional_exit(
            symbol_upper=symbol_upper,
            generated=generated,
            realized_exit_price=realized_exit_price,
            realized_exit_source=realized_exit_source,
            realized_exit_utc=realized_exit_utc,
            previous_track=previous_track,
        )
    side = str(position.get("side") or "long").lower()
    if side not in {"long", "short"}:
        side = "long"
    latest_price, latest_ts = _extract_latest_price(market_price)
    entry_price, entry_source = _extract_entry_price(
        position,
        paper_ledger,
        paper_intents_list,
        paper_intents_held_list,
        previous_track,
        symbol_upper,
    )
    missing: list[str] = []
    stale: list[str] = []
    age = _age_seconds(latest_ts, now)
    if entry_price is None:
        missing.append(MISSING_ENTRY_PRICE)
    if latest_price is None:
        missing.append(MISSING_LATEST_PRICE)
    if age is not None and age > max_source_age_seconds:
        stale.append(f"STALE_LATEST_PRICE:{age}")
    hold_time = _hold_time_seconds(position, now)
    if entry_price is None or latest_price is None:
        return PositionTrack(
            symbol=symbol_upper,
            position_state="OPEN_MISSING_PRICE_INPUTS",
            side=side,
            entry_price=entry_price,
            entry_price_source=entry_source,
            latest_price=latest_price,
            min_price_since_entry=None,
            max_price_since_entry=None,
            mfe_bps=None,
            mae_bps=None,
            roe_bps=None,
            hold_time_seconds=hold_time,
            realized_exit_price=realized_exit_price,
            realized_exit_source=realized_exit_source,
            realized_exit_utc=realized_exit_utc,
            source_freshness_seconds=age,
            missing_flags=tuple(missing),
            stale_flags=tuple(stale),
            generated_utc=generated,
        )
    previous_min = _coerce_float((previous_track or {}).get("min_price_since_entry"))
    previous_max = _coerce_float((previous_track or {}).get("max_price_since_entry"))
    min_price = min(v for v in (entry_price, latest_price, previous_min) if v is not None)
    max_price = max(v for v in (entry_price, latest_price, previous_max) if v is not None)
    mfe_bps, mae_bps = _excursion_bps(entry_price, min_price, max_price, side)
    roe_bps = round(_bps_for_side(entry_price, latest_price, side), 6)
    return PositionTrack(
        symbol=symbol_upper,
        position_state="OPEN_TRACKING",
        side=side,
        entry_price=round(entry_price, 12),
        entry_price_source=entry_source,
        latest_price=round(latest_price, 12),
        min_price_since_entry=round(min_price, 12),
        max_price_since_entry=round(max_price, 12),
        mfe_bps=mfe_bps,
        mae_bps=mae_bps,
        roe_bps=roe_bps,
        hold_time_seconds=hold_time,
        realized_exit_price=realized_exit_price,
        realized_exit_source=realized_exit_source,
        realized_exit_utc=realized_exit_utc,
        source_freshness_seconds=age,
        missing_flags=tuple(missing),
        stale_flags=tuple(stale),
        generated_utc=generated,
    )


def history_payload(track: PositionTrack) -> dict[str, Any]:
    payload = track.as_payload()
    payload["schema_version"] = "v2_position_history_v1"
    payload["history_source"] = SOURCE_RECORDER
    return payload


def build_heartbeat_payload(
    tracks: Mapping[str, PositionTrack],
    *,
    generated_utc: str | None = None,
) -> dict[str, Any]:
    generated = generated_utc or utc_iso()
    return {
        "schema_version": "v2_position_price_tracking_recorder_status_v1",
        "generated_utc": generated,
        "go_no_go": "V2_POSITION_PRICE_TRACKING_RECORDER_READY",
        "symbol_count": len(tracks),
        "symbols": sorted(tracks.keys()),
        "state_counts": {
            state: sum(1 for t in tracks.values() if t.position_state == state)
            for state in sorted({t.position_state for t in tracks.values()})
        },
        "missing_flags_by_symbol": {
            symbol: list(track.missing_flags) for symbol, track in tracks.items()
        },
        "stale_flags_by_symbol": {
            symbol: list(track.stale_flags) for symbol, track in tracks.items()
        },
        "entry_price_source_by_symbol": {
            symbol: track.entry_price_source for symbol, track in tracks.items()
        },
        "realized_exit_source_by_symbol": {
            symbol: track.realized_exit_source for symbol, track in tracks.items()
        },
        "realized_exit_price_by_symbol": {
            symbol: track.realized_exit_price for symbol, track in tracks.items()
        },
        "allowed_outputs": [
            "v2:paper:position_price_track:{symbol}",
            "v2:paper:position_history:{symbol}",
            KEY_HEARTBEAT,
        ],
        "no_fake_price_tracks": True,
        "no_silent_zero_fill": True,
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }


def write_tracks(redis_client: Any, tracks: Mapping[str, PositionTrack], *, ex: int = 900) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for symbol, track in tracks.items():
        track_key = KEY_PRICE_TRACK_TEMPLATE.format(symbol=symbol)
        history_key = KEY_HISTORY_TEMPLATE.format(symbol=symbol)
        results[track_key] = safe_redis_set(redis_client, track_key, track.as_payload(), ex=ex)
        results[history_key] = safe_redis_set(redis_client, history_key, history_payload(track), ex=ex)
    heartbeat = build_heartbeat_payload(tracks)
    results[KEY_HEARTBEAT] = safe_redis_set(redis_client, KEY_HEARTBEAT, heartbeat, ex=ex)
    return results
