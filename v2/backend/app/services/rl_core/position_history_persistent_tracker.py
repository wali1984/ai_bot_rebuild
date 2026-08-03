"""V2-only paper position-history persistent tracker.

Wraps the existing :mod:`position_price_tracking_recorder` math (MFE,
MAE, ROE, hold time, entry-price recovery) and adds the
persistent-daemon fields needed by the full-observation builder:

- ``first_seen_utc`` / ``last_seen_utc`` per symbol (carried over
  from previously published payloads)
- ``accepted_intent_count`` / ``held_intent_count`` /
  ``block_reason_count`` per symbol (from V2 paper ledger / intent
  rows only)
- ``unrealized_bps`` (alias of ROE for OPEN positions)
- ``max_favorable_bps`` / ``max_adverse_bps`` (aliases of MFE/MAE)
- explicit ``NO_OPEN_POSITION`` state when the V2 paper position
  row is absent (the recorder's ``FLAT`` state is renamed so the
  full-observation consumer can detect it without ambiguity)

The tracker NEVER fabricates accepted positions and NEVER counts
shadow / held / blocked intents as accepted. Shadow observations
and held intents are surfaced as distinct counts.

Writes only:

- ``v2:paper:position_history:{symbol}``
- ``v2:paper:position_price_track:{symbol}``
- ``v2:paper:position_history:heartbeat``

The allowlist is enforced by
:func:`position_price_tracking_recorder.safe_redis_set`.
"""
from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from v2.backend.app.services.rl_core.position_price_tracking_recorder import (
    KEY_HEARTBEAT,
    KEY_HISTORY_TEMPLATE,
    KEY_PRICE_TRACK_TEMPLATE,
    PositionTrack,
    SOURCE_RECORDER,
    build_heartbeat_payload as _base_heartbeat,
    build_position_track,
    history_payload as _base_history_payload,
    safe_redis_set,
)

NO_OPEN_POSITION_STATE = "NO_OPEN_POSITION"
SOURCE_PERSISTENT_TRACKER = "V2_POSITION_HISTORY_PERSISTENT_TRACKER"


def utc_iso(now: datetime | None = None) -> str:
    return (
        (now or datetime.now(timezone.utc))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _row_matches_symbol(row: Any, symbol_upper: str) -> bool:
    if not isinstance(row, Mapping):
        return False
    return (row.get("symbol") or "").upper() == symbol_upper


def _row_is_shadow_observation(row: Mapping[str, Any]) -> bool:
    """Shadow observations are recorded in the ledger but must NOT be
    counted as accepted intents."""
    flags = (
        str(row.get("paper_result") or "").upper(),
        str(row.get("ledger_action") or "").upper(),
        str(row.get("status") or "").upper(),
        str(row.get("category") or "").upper(),
    )
    shadow_tokens = {
        "SHADOW",
        "SHADOW_ONLY",
        "SHADOW_OBSERVATION",
        "SHADOW_OBSERVED",
        "OBSERVED_ONLY",
    }
    return any(token in flags for token in shadow_tokens)


def _row_is_held_by_fill_gate(row: Mapping[str, Any]) -> bool:
    flags = (
        str(row.get("paper_result") or "").upper(),
        str(row.get("ledger_action") or "").upper(),
        str(row.get("status") or "").upper(),
    )
    held_tokens = {
        "HELD_BY_PAPER_FILL_GATE",
        "PAPER_FILL_GATE_HELD",
        "PAPER_HELD",
        "HELD",
    }
    return any(token in flags for token in held_tokens)


def _row_is_blocked(row: Mapping[str, Any]) -> bool:
    flags = (
        str(row.get("paper_result") or "").upper(),
        str(row.get("ledger_action") or "").upper(),
        str(row.get("status") or "").upper(),
        str(row.get("category") or "").upper(),
    )
    blocked_tokens = {
        "BLOCKED",
        "BLOCKED_BY_RISK",
        "BLOCKED_BY_PAPER_FILL_GATE",
        "REJECTED",
        "REFUSED",
    }
    return any(token in flags for token in blocked_tokens)


def _row_block_reason(row: Mapping[str, Any]) -> str | None:
    for key in (
        "block_reason",
        "reason",
        "risk_block_reason",
        "paper_fill_gate_reason",
    ):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


@dataclasses.dataclass(frozen=True)
class IntentCounts:
    accepted_intent_count: int
    held_intent_count: int
    shadow_observation_count: int
    block_reason_count: int
    block_reasons: tuple[str, ...]


def compute_intent_counts(
    *,
    symbol_upper: str,
    paper_ledger: Mapping[str, Any] | None,
    paper_intents: Iterable[Mapping[str, Any]] | None,
    paper_intents_held: Iterable[Mapping[str, Any]] | None,
) -> IntentCounts:
    """Count accepted / held / blocked / shadow intents for ``symbol_upper``.

    Sources read are V2-only and disjoint:

    - ``v2:paper:ledger`` exposes ``accepted`` / ``held_by_paper_fill_gate``
      / ``blocked`` / ``shadow_observations`` lists. Their lengths after
      symbol filtering define accepted / held / blocked / shadow.
    - ``v2:paper:intents`` is a flat list. Shadow rows there are counted
      as shadow_observation_count, NOT as accepted. Held rows there are
      counted as held_intent_count, NOT as accepted. Accepted-only rows
      that are not shadow / held / blocked count as accepted.
    - ``v2:paper:intents_held_by_paper_fill_gate`` is union'd into the
      held set.
    """
    accepted = 0
    held = 0
    shadow = 0
    blocked = 0
    block_reasons: list[str] = []

    if isinstance(paper_ledger, Mapping):
        for row in paper_ledger.get("accepted") or []:
            if not _row_matches_symbol(row, symbol_upper):
                continue
            if _row_is_shadow_observation(row):
                shadow += 1
                continue
            if _row_is_held_by_fill_gate(row):
                held += 1
                continue
            if _row_is_blocked(row):
                blocked += 1
                reason = _row_block_reason(row)
                if reason:
                    block_reasons.append(reason)
                continue
            accepted += 1
        for row in paper_ledger.get("held_by_paper_fill_gate") or []:
            if _row_matches_symbol(row, symbol_upper):
                held += 1
        for row in paper_ledger.get("blocked") or []:
            if not _row_matches_symbol(row, symbol_upper):
                continue
            blocked += 1
            reason = _row_block_reason(row)
            if reason:
                block_reasons.append(reason)
        for row in paper_ledger.get("shadow_observations") or []:
            if _row_matches_symbol(row, symbol_upper):
                shadow += 1

    for row in paper_intents or []:
        if not _row_matches_symbol(row, symbol_upper):
            continue
        if _row_is_shadow_observation(row):
            shadow += 1
            continue
        if _row_is_held_by_fill_gate(row):
            held += 1
            continue
        if _row_is_blocked(row):
            blocked += 1
            reason = _row_block_reason(row)
            if reason:
                block_reasons.append(reason)
            continue
        # Bare paper intent rows are NOT counted as accepted unless the
        # ledger explicitly accepted them. This preserves the rule
        # "do not count shadow/held intents as accepted" without
        # double-counting accepted ledger rows.

    for row in paper_intents_held or []:
        if _row_matches_symbol(row, symbol_upper):
            held += 1

    return IntentCounts(
        accepted_intent_count=accepted,
        held_intent_count=held,
        shadow_observation_count=shadow,
        block_reason_count=blocked,
        block_reasons=tuple(sorted(set(block_reasons))),
    )


def _carry_seen_timestamps(
    *,
    previous_history: Mapping[str, Any] | None,
    track: PositionTrack,
    generated: str,
) -> tuple[str, str]:
    """Return ``(first_seen_utc, last_seen_utc)``.

    ``last_seen_utc`` is always the current generated timestamp.
    ``first_seen_utc`` is carried over from the previous history
    payload when the track still indicates an OPEN position. When the
    position is flat / closed / no-open, ``first_seen_utc`` is reset
    to the current timestamp; this means the next OPEN cycle starts a
    fresh hold-time observation.
    """
    last_seen = generated
    if track.position_state.startswith("OPEN") and isinstance(previous_history, Mapping):
        previous_first = previous_history.get("first_seen_utc")
        if isinstance(previous_first, str) and previous_first:
            return previous_first, last_seen
    return generated, last_seen


def persistent_history_payload(
    *,
    track: PositionTrack,
    intent_counts: IntentCounts,
    first_seen_utc: str,
    last_seen_utc: str,
) -> dict[str, Any]:
    """Build the per-symbol persistent-tracker payload.

    The payload is a SUPERSET of the recorder's history payload, so
    existing consumers that read ``v2:paper:position_history:{symbol}``
    keep working. ``position_state="NO_OPEN_POSITION"`` replaces the
    recorder's ``FLAT`` state so the full-observation consumer can
    detect the explicit "no position" branch without string matching
    on ``FLAT``. Both states still surface ``side=None`` and null
    MFE/MAE/ROE when there is no open position.
    """
    base = _base_history_payload(track)
    base["history_source"] = SOURCE_PERSISTENT_TRACKER
    base["schema_version"] = "v2_position_history_persistent_v1"
    if base.get("position_state") == "FLAT":
        base["position_state"] = NO_OPEN_POSITION_STATE
    base["first_seen_utc"] = first_seen_utc
    base["last_seen_utc"] = last_seen_utc
    base["entry_price_proxy"] = track.entry_price
    base["entry_price_proxy_source"] = track.entry_price_source
    base["max_favorable_bps"] = track.mfe_bps
    base["max_adverse_bps"] = track.mae_bps
    base["unrealized_bps"] = track.roe_bps if track.position_state.startswith("OPEN") else None
    base["accepted_intent_count"] = intent_counts.accepted_intent_count
    base["held_intent_count"] = intent_counts.held_intent_count
    base["shadow_observation_count"] = intent_counts.shadow_observation_count
    base["block_reason_count"] = intent_counts.block_reason_count
    base["block_reasons"] = list(intent_counts.block_reasons)
    base["no_synthesized_accepted_positions"] = True
    base["no_fabricated_excursion_metrics"] = True
    base["no_synthetic_intent_counts"] = True
    base["no_shadow_observations_counted_as_accepted"] = True
    base["full_observation_consumption_allowed"] = False
    base["full_observation_consumption_unblocked_after"] = (
        "V2_POSITION_HISTORY_PERSISTENT_TRACKER_CODEX_PASS"
    )
    return base


def persistent_heartbeat_payload(
    *,
    tracks: Mapping[str, PositionTrack],
    intent_counts: Mapping[str, IntentCounts],
    generated_utc: str,
    process_mode: str,
    cycle_count: int,
    open_position_symbols: tuple[str, ...],
    no_open_position_symbols: tuple[str, ...],
    service_active: bool = True,
    opt_in_enabled: bool = True,
) -> dict[str, Any]:
    base = _base_heartbeat(tracks, generated_utc=generated_utc)
    base["schema_version"] = "v2_position_history_persistent_tracker_status_v1"
    base["go_no_go"] = (
        "V2_POSITION_HISTORY_PERSISTENT_TRACKER_PAPER_SHADOW_READY"
    )
    base["process_mode"] = process_mode
    base["service_active"] = service_active
    base["opt_in_enabled"] = opt_in_enabled
    base["cycle_count"] = cycle_count
    base["open_position_symbols"] = list(open_position_symbols)
    base["no_open_position_symbols"] = list(no_open_position_symbols)
    base["no_open_position_state"] = NO_OPEN_POSITION_STATE
    base["accepted_intent_count_by_symbol"] = {
        symbol: counts.accepted_intent_count for symbol, counts in intent_counts.items()
    }
    base["held_intent_count_by_symbol"] = {
        symbol: counts.held_intent_count for symbol, counts in intent_counts.items()
    }
    base["shadow_observation_count_by_symbol"] = {
        symbol: counts.shadow_observation_count for symbol, counts in intent_counts.items()
    }
    base["block_reason_count_by_symbol"] = {
        symbol: counts.block_reason_count for symbol, counts in intent_counts.items()
    }
    base["allowed_outputs"] = [
        "v2:paper:position_history:{symbol}",
        "v2:paper:position_price_track:{symbol}",
        KEY_HEARTBEAT,
    ]
    base["heartbeat_writer"] = SOURCE_PERSISTENT_TRACKER
    base["recorder_writer"] = SOURCE_RECORDER
    base["no_synthesized_accepted_positions"] = True
    base["no_fabricated_excursion_metrics"] = True
    base["no_synthetic_intent_counts"] = True
    base["no_shadow_observations_counted_as_accepted"] = True
    base["full_observation_consumption_allowed"] = False
    base["full_observation_consumption_unblocked_after"] = (
        "V2_POSITION_HISTORY_PERSISTENT_TRACKER_CODEX_PASS"
    )
    return base


def build_and_publish(
    *,
    redis_client: Any,
    symbols: Iterable[str],
    process_mode: str,
    cycle_count: int,
    now: datetime | None = None,
    ttl_seconds: int = 900,
) -> dict[str, Any]:
    """Read V2 paper inputs, build tracks + intent counts per symbol,
    and write all outputs.

    Returns the heartbeat payload (also written to the heartbeat key).
    """
    now = now or datetime.now(timezone.utc)
    generated = utc_iso(now)
    paper_positions = _redis_get_json(redis_client, "v2:paper:positions")
    paper_ledger = _redis_get_json(redis_client, "v2:paper:ledger")
    paper_intents = _redis_get_json(redis_client, "v2:paper:intents")
    paper_intents_held = _redis_get_json(
        redis_client, "v2:paper:intents_held_by_paper_fill_gate"
    )

    tracks: dict[str, PositionTrack] = {}
    intent_counts_by_symbol: dict[str, IntentCounts] = {}
    history_payloads: dict[str, dict[str, Any]] = {}
    track_payloads: dict[str, dict[str, Any]] = {}
    open_symbols: list[str] = []
    no_open_symbols: list[str] = []

    for symbol in sorted({str(s).strip().upper() for s in symbols if str(s).strip()}):
        market_price = _redis_get_json(redis_client, f"v2:market:prices:{symbol}")
        prediction = _redis_get_json(redis_client, f"v2:prediction:{symbol}:1m")
        previous_track = _redis_get_json(
            redis_client, KEY_PRICE_TRACK_TEMPLATE.format(symbol=symbol)
        )
        previous_history = _redis_get_json(
            redis_client, KEY_HISTORY_TEMPLATE.format(symbol=symbol)
        )
        track = build_position_track(
            symbol=symbol,
            paper_positions=paper_positions if isinstance(paper_positions, list) else [],
            paper_ledger=paper_ledger if isinstance(paper_ledger, dict) else {},
            market_price=market_price if isinstance(market_price, dict) else None,
            prediction=prediction if isinstance(prediction, dict) else None,
            paper_intents=paper_intents if isinstance(paper_intents, list) else [],
            paper_intents_held=paper_intents_held if isinstance(paper_intents_held, list) else [],
            previous_track=previous_track if isinstance(previous_track, dict) else None,
            now=now,
        )
        intent_counts = compute_intent_counts(
            symbol_upper=symbol,
            paper_ledger=paper_ledger if isinstance(paper_ledger, dict) else None,
            paper_intents=paper_intents if isinstance(paper_intents, list) else [],
            paper_intents_held=paper_intents_held if isinstance(paper_intents_held, list) else [],
        )
        first_seen, last_seen = _carry_seen_timestamps(
            previous_history=previous_history if isinstance(previous_history, dict) else None,
            track=track,
            generated=generated,
        )
        history = persistent_history_payload(
            track=track,
            intent_counts=intent_counts,
            first_seen_utc=first_seen,
            last_seen_utc=last_seen,
        )
        tracks[symbol] = track
        intent_counts_by_symbol[symbol] = intent_counts
        history_payloads[symbol] = history
        track_payloads[symbol] = track.as_payload()
        if track.position_state.startswith("OPEN"):
            open_symbols.append(symbol)
        else:
            no_open_symbols.append(symbol)

    heartbeat = persistent_heartbeat_payload(
        tracks=tracks,
        intent_counts=intent_counts_by_symbol,
        generated_utc=generated,
        process_mode=process_mode,
        cycle_count=cycle_count,
        open_position_symbols=tuple(open_symbols),
        no_open_position_symbols=tuple(no_open_symbols),
    )

    write_results: dict[str, bool] = {}
    if redis_client is not None:
        for symbol, payload in track_payloads.items():
            key = KEY_PRICE_TRACK_TEMPLATE.format(symbol=symbol)
            write_results[key] = safe_redis_set(redis_client, key, payload, ex=ttl_seconds)
        for symbol, payload in history_payloads.items():
            key = KEY_HISTORY_TEMPLATE.format(symbol=symbol)
            write_results[key] = safe_redis_set(redis_client, key, payload, ex=ttl_seconds)
        write_results[KEY_HEARTBEAT] = safe_redis_set(
            redis_client, KEY_HEARTBEAT, heartbeat, ex=ttl_seconds
        )

    heartbeat["redis_write_results"] = write_results
    heartbeat["per_symbol_history"] = history_payloads
    heartbeat["per_symbol_track"] = track_payloads
    return heartbeat


def _redis_get_json(redis_client: Any, key: str) -> Any:
    if redis_client is None:
        return None
    try:
        raw = redis_client.get(key)
    except Exception:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None
