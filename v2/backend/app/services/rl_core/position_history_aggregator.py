"""V2-owned position-history aggregator (paper/shadow only).

Consumes V2-owned paper-trading payloads from Redis and computes a
per-symbol summary of the position-history-style fields that the
full-observation builder needs:

  - hold_time_seconds_current      (from generated_utc to now)
  - intents_accepted_count
  - intents_blocked_count
  - intents_held_count
  - block reason counts            (from V2 paper/ledger/held rows)
  - churn_blocked_rate
  - pre_trade_allowed_rate
  - fee_gate_allowed_rate
  - mfe_bps_v2                     (from V2 price track when present)
  - mae_bps_v2                     (from V2 price track when present)
  - roe_bps_v2                     (from V2 price track when present)
  - position_history_present       (1 iff symbol has at least one V2-owned
                                    paper position record)

The aggregator NEVER reads legacy filesystem state. It NEVER reads
the legacy Redis namespace. It NEVER fabricates fields that V2 does
not yet record; missing fields surface as None with an explicit
source string the builder can quote.

Allowed inputs are limited to these V2 keys:
  - v2:paper:positions
  - v2:paper:ledger
  - v2:paper:intents
  - v2:paper:intents_held_by_paper_fill_gate
  - v2:paper:position_price_track:{symbol}
  - v2:paper:position_history:{symbol}

The aggregator NEVER writes Redis.
"""
from __future__ import annotations

import dataclasses
import json
import time
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

SOURCE_V2_PAPER_POSITIONS = "V2_PAPER_POSITIONS"
SOURCE_V2_PAPER_LEDGER = "V2_PAPER_LEDGER"
SOURCE_V2_PAPER_INTENTS = "V2_PAPER_INTENTS"
SOURCE_V2_PAPER_INTENTS_HELD = "V2_PAPER_INTENTS_HELD"
SOURCE_V2_PROBE_FLAG = "V2_PROBE_FLAG"

MISSING_NO_V2_POSITION_RECORD = "MISSING_V2_OWNED_POSITION_RECORD"
MISSING_V2_OWNED_PRICE_TRACK = "MISSING_V2_OWNED_PRICE_TRACK_NOT_YET_RECORDED"
MISSING_V2_OWNED_REALIZED_EXIT = "MISSING_V2_OWNED_REALIZED_EXIT_NOT_YET_RECORDED"
MISSING_V2_PAPER_LEDGER = "MISSING_FROM_V2_LEDGER"
SOURCE_V2_POSITION_PRICE_TRACK = "V2_POSITION_PRICE_TRACKING_RECORDER"


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if isinstance(value, str):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


@dataclasses.dataclass(frozen=True)
class SymbolHistory:
    symbol: str
    position_present: bool
    hold_time_seconds_current: float | None
    intents_accepted_count: int
    intents_blocked_count: int
    intents_held_count: int
    pre_trade_allowed_rate: float | None
    fee_gate_allowed_rate: float | None
    churn_blocked_rate: float | None
    mfe_bps_v2: float | None
    mae_bps_v2: float | None
    roe_bps_v2: float | None
    mfe_source: str
    mae_source: str
    roe_source: str
    block_reason_negative_expected_move_count: int = 0
    block_reason_edge_below_threshold_count: int = 0
    block_reason_feature_freshness_count: int = 0
    block_reason_checkpoint_required_count: int = 0
    block_reason_trainer_malformed_count: int = 0
    block_reason_other_count: int = 0

    def as_payload(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "position_present": self.position_present,
            "hold_time_seconds_current": self.hold_time_seconds_current,
            "intents_accepted_count": int(self.intents_accepted_count),
            "intents_blocked_count": int(self.intents_blocked_count),
            "intents_held_count": int(self.intents_held_count),
            "pre_trade_allowed_rate": self.pre_trade_allowed_rate,
            "fee_gate_allowed_rate": self.fee_gate_allowed_rate,
            "churn_blocked_rate": self.churn_blocked_rate,
            "mfe_bps_v2": self.mfe_bps_v2,
            "mae_bps_v2": self.mae_bps_v2,
            "roe_bps_v2": self.roe_bps_v2,
            "mfe_source": self.mfe_source,
            "mae_source": self.mae_source,
            "roe_source": self.roe_source,
            "block_reason_negative_expected_move_count": int(
                self.block_reason_negative_expected_move_count
            ),
            "block_reason_edge_below_threshold_count": int(
                self.block_reason_edge_below_threshold_count
            ),
            "block_reason_feature_freshness_count": int(
                self.block_reason_feature_freshness_count
            ),
            "block_reason_checkpoint_required_count": int(
                self.block_reason_checkpoint_required_count
            ),
            "block_reason_trainer_malformed_count": int(
                self.block_reason_trainer_malformed_count
            ),
            "block_reason_other_count": int(self.block_reason_other_count),
        }


def _per_symbol_rate(
    rows: Iterable[Mapping[str, Any]], symbol: str, field: str
) -> float | None:
    matching = [r for r in rows if (r.get("symbol") or "").upper() == symbol.upper()]
    if not matching:
        return None
    truthy = sum(1 for r in matching if r.get(field))
    return float(truthy) / float(len(matching))


def _hold_time_seconds_current(
    paper_positions: Iterable[Mapping[str, Any]],
    symbol: str,
    *,
    now: datetime | None = None,
) -> float | None:
    now = now or datetime.now(timezone.utc)
    candidates = [
        p for p in paper_positions if (p.get("symbol") or "").upper() == symbol.upper()
    ]
    if not candidates:
        return None
    # Earliest generated_utc represents the position's open time. We pick
    # the smallest non-None timestamp so multiple intents on the same
    # symbol roll up to one continuous hold-time observation.
    timestamps = [_parse_utc(p.get("generated_utc")) for p in candidates]
    timestamps = [t for t in timestamps if t is not None]
    if not timestamps:
        return None
    open_at = min(timestamps)
    delta = (now - open_at).total_seconds()
    return max(0.0, float(delta))


def _row_block_reasons(row: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    for field in (
        "paper_fill_gate_block_reasons",
        "block_reasons",
        "missing_flags",
        "stale_flags",
    ):
        value = row.get(field)
        if isinstance(value, str):
            reasons.append(value)
        elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, Mapping)):
            reasons.extend(str(item) for item in value if item is not None)
    for field in ("checkpoint_blocker", "paper_fill_gate_status", "realized_exit_blocker"):
        value = row.get(field)
        if value:
            reasons.append(str(value))
    return reasons


def _block_reason_counts(rows: Iterable[Mapping[str, Any]], symbol: str) -> dict[str, int]:
    counts = {
        "negative_expected_move": 0,
        "edge_below_threshold": 0,
        "feature_freshness": 0,
        "checkpoint_required": 0,
        "trainer_malformed": 0,
        "other": 0,
    }
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if (row.get("symbol") or "").upper() != symbol.upper():
            continue
        for reason in _row_block_reasons(row):
            identity = str(row.get("intent_id") or row.get("source_intent_id") or id(row))
            dedupe_key = (identity, reason)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            text = reason.upper()
            if "NEGATIVE_EXPECTED_MOVE" in text:
                counts["negative_expected_move"] += 1
            elif "EDGE_AFTER_COST_BELOW_THRESHOLD" in text:
                counts["edge_below_threshold"] += 1
            elif "FEATURE_FRESHNESS" in text:
                counts["feature_freshness"] += 1
            elif "CHECKPOINT" in text:
                counts["checkpoint_required"] += 1
            elif "TRAINER_OUTPUT_MALFORMED" in text:
                counts["trainer_malformed"] += 1
            else:
                counts["other"] += 1
    return counts


def aggregate_symbol(
    *,
    symbol: str,
    paper_positions: Iterable[Mapping[str, Any]] | None,
    paper_intents: Iterable[Mapping[str, Any]] | None,
    paper_intents_held: Iterable[Mapping[str, Any]] | None,
    paper_ledger: Mapping[str, Any] | None,
    position_price_track: Mapping[str, Any] | None = None,
    position_history: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> SymbolHistory:
    paper_positions = list(paper_positions or [])
    paper_intents = list(paper_intents or [])
    paper_intents_held = list(paper_intents_held or [])
    paper_ledger = dict(paper_ledger or {})
    symbol_upper = symbol.upper()
    accepted_source = list(paper_ledger.get("accepted") or [])
    if not accepted_source:
        accepted_source = [
            i
            for i in paper_intents
            if i.get("counted_as_accepted_position") is True
            or i.get("paper_fill_allowed") is True
        ]
    accepted = [
        i
        for i in accepted_source
        if (i.get("symbol") or "").upper() == symbol_upper
    ]
    blocked = [
        i
        for i in (paper_ledger.get("blocked") or [])
        if (i.get("symbol") or "").upper() == symbol_upper
    ]
    held = [
        i
        for i in (paper_ledger.get("held_by_paper_fill_gate") or paper_intents_held or [])
        if (i.get("symbol") or "").upper() == symbol_upper
    ]
    block_reason_rows = (
        list(paper_positions)
        + list(paper_intents)
        + list(paper_intents_held)
        + list(paper_ledger.get("accepted") or [])
        + list(paper_ledger.get("blocked") or [])
        + list(paper_ledger.get("held_by_paper_fill_gate") or [])
        + list(paper_ledger.get("shadow_observations") or [])
    )
    block_counts = _block_reason_counts(block_reason_rows, symbol_upper)
    pre_rate = _per_symbol_rate(paper_intents, symbol_upper, "pre_trade_allowed")
    fee_rate = _per_symbol_rate(paper_intents, symbol_upper, "fee_gate_allowed")
    churn_rate = _per_symbol_rate(paper_intents, symbol_upper, "churn_blocked")
    has_position = any(
        (p.get("symbol") or "").upper() == symbol_upper for p in paper_positions
    )
    hold_time = (
        _hold_time_seconds_current(paper_positions, symbol_upper, now=now)
        if has_position
        else None
    )
    track = dict(position_price_track or position_history or {})
    track_symbol_matches = (track.get("symbol") or "").upper() == symbol_upper
    track_source = str(track.get("source") or track.get("history_source") or "")
    track_allowed = (
        track_symbol_matches
        and track_source in {SOURCE_V2_POSITION_PRICE_TRACK, ""}
        and track.get("no_fake_price_tracks") is True
    )
    track_missing_flags = list(track.get("missing_flags") or [])
    mfe = _coerce_float(track.get("mfe_bps")) if track_allowed else None
    mae = _coerce_float(track.get("mae_bps")) if track_allowed else None
    roe = _coerce_float(track.get("roe_bps")) if track_allowed else None
    if track_allowed and _coerce_float(track.get("hold_time_seconds")) is not None:
        hold_time = _coerce_float(track.get("hold_time_seconds"))
    if has_position:
        if mfe is not None:
            mfe_source = SOURCE_V2_POSITION_PRICE_TRACK
        elif "MISSING_ENTRY_PRICE" in track_missing_flags:
            mfe_source = "MISSING_ENTRY_PRICE"
        elif "MISSING_LATEST_PRICE" in track_missing_flags:
            mfe_source = "MISSING_LATEST_PRICE"
        else:
            mfe_source = MISSING_V2_OWNED_PRICE_TRACK
        if mae is not None:
            mae_source = SOURCE_V2_POSITION_PRICE_TRACK
        elif "MISSING_ENTRY_PRICE" in track_missing_flags:
            mae_source = "MISSING_ENTRY_PRICE"
        elif "MISSING_LATEST_PRICE" in track_missing_flags:
            mae_source = "MISSING_LATEST_PRICE"
        else:
            mae_source = MISSING_V2_OWNED_PRICE_TRACK
        if roe is not None:
            roe_source = SOURCE_V2_POSITION_PRICE_TRACK
        elif "MISSING_ENTRY_PRICE" in track_missing_flags:
            roe_source = "MISSING_ENTRY_PRICE"
        elif "MISSING_LATEST_PRICE" in track_missing_flags:
            roe_source = "MISSING_LATEST_PRICE"
        else:
            roe_source = MISSING_V2_OWNED_REALIZED_EXIT
    else:
        mfe_source = MISSING_NO_V2_POSITION_RECORD
        mae_source = MISSING_NO_V2_POSITION_RECORD
        roe_source = MISSING_NO_V2_POSITION_RECORD
    return SymbolHistory(
        symbol=symbol_upper,
        position_present=has_position,
        hold_time_seconds_current=hold_time,
        intents_accepted_count=len(accepted),
        intents_blocked_count=len(blocked),
        intents_held_count=len(held),
        pre_trade_allowed_rate=pre_rate,
        fee_gate_allowed_rate=fee_rate,
        churn_blocked_rate=churn_rate,
        mfe_bps_v2=mfe,
        mae_bps_v2=mae,
        roe_bps_v2=roe,
        mfe_source=mfe_source,
        mae_source=mae_source,
        roe_source=roe_source,
        block_reason_negative_expected_move_count=block_counts[
            "negative_expected_move"
        ],
        block_reason_edge_below_threshold_count=block_counts[
            "edge_below_threshold"
        ],
        block_reason_feature_freshness_count=block_counts["feature_freshness"],
        block_reason_checkpoint_required_count=block_counts["checkpoint_required"],
        block_reason_trainer_malformed_count=block_counts["trainer_malformed"],
        block_reason_other_count=block_counts["other"],
    )


def aggregate_all(
    *,
    symbols: Iterable[str],
    paper_positions: Iterable[Mapping[str, Any]] | None,
    paper_intents: Iterable[Mapping[str, Any]] | None,
    paper_intents_held: Iterable[Mapping[str, Any]] | None,
    paper_ledger: Mapping[str, Any] | None,
    position_price_tracks: Mapping[str, Mapping[str, Any]] | None = None,
    position_histories: Mapping[str, Mapping[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, SymbolHistory]:
    """Build the per-symbol history map for the requested symbols.

    Returns a dict keyed by uppercase symbol so the builder can look
    up each symbol's history payload while projecting that symbol's
    position_context slice.
    """
    pp = list(paper_positions or [])
    pi = list(paper_intents or [])
    ph = list(paper_intents_held or [])
    pl = dict(paper_ledger or {})
    tracks = dict(position_price_tracks or {})
    histories = dict(position_histories or {})
    out: dict[str, SymbolHistory] = {}
    for symbol in symbols:
        sym = symbol.upper()
        out[symbol.upper()] = aggregate_symbol(
            symbol=symbol,
            paper_positions=pp,
            paper_intents=pi,
            paper_intents_held=ph,
            paper_ledger=pl,
            position_price_track=tracks.get(sym),
            position_history=histories.get(sym),
            now=now,
        )
    return out


def load_paper_inputs_from_redis(redis_client: Any) -> dict[str, Any]:
    """Read the four V2-owned paper keys plus the heartbeat as a single
    snapshot. Returns a dict with safe defaults if keys are absent or
    malformed. Never writes Redis.
    """

    def _get(key: str) -> Any:
        if redis_client is None:
            return None
        try:
            raw = redis_client.get(key)
        except Exception:
            return None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return None

    return {
        "paper_positions": _get("v2:paper:positions") or [],
        "paper_intents": _get("v2:paper:intents") or [],
        "paper_intents_held": _get("v2:paper:intents_held_by_paper_fill_gate") or [],
        "paper_ledger": _get("v2:paper:ledger") or {},
        "paper_heartbeat": _get("v2:paper:heartbeat") or {},
    }


def aggregator_payload(
    histories: Mapping[str, SymbolHistory],
    *,
    generated_utc: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "v2_position_history_aggregator_v1",
        "generated_utc": generated_utc or _utc_iso(),
        "symbol_count": int(len(histories)),
        "symbols": sorted(histories.keys()),
        "per_symbol": {sym: h.as_payload() for sym, h in histories.items()},
        "no_legacy_filesystem_read": True,
        "no_legacy_redis_read": True,
        "no_silent_zero_fill": True,
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
        "credential_in_payload": "NEVER",
        "gate": "blocked_human_only",
        "symbols_real": [],
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "checkpoint_compatibility_claimed": False,
        "policy_architecture_parity_claimed": False,
        "approves_real": False,
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
