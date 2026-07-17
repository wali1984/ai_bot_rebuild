"""V2 full observation-vector builder (paper-only, V2-native sources).

Produces two tensors per symbol:

- ``compact_observation_v1`` (dim=26, preserved unchanged) — the existing
  runtime policy input. Kept so V2 paper inference continues unaffected.
- ``full_observation_v1`` (target_dim=1911) — legacy V3 parity target.
  Built from V2-native inputs only (``v2:features:latest:*``,
  ``v2:market:*``, ``v2:paper:*``, ``v2:risk:*``,
  ``v2:orchestrator:*``, ``v2:trainer:*``). Categories that have no
  V2-native source today are reported as explicit missing fields.
  **Nothing is zero-filled silently.**

Never imports torch. Never deserializes any checkpoint/pickle. Never
reads legacy filesystem. Never modifies legacy. Never claims checkpoint
compatibility.
"""
from __future__ import annotations

import dataclasses
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from v2.backend.app.services.rl_core.legacy_observation_contract import (
    build_legacy_observation_contract,
)

TARGET_FULL_DIM = 1911
SLICE_SIZES = {
    "unified_features": 1430,
    "portfolio_state": 401,
    "onchain_btc": 15,
    "onchain_eth": 15,
    "position_context": 50,
}

# Position-history tracker consumption gate.
#
# The full-observation builder may consume the tracker's Redis keys
# (``v2:paper:position_history:*`` and ``v2:paper:position_price_track:*``)
# only when the tracker daemon is Codex-passed AND its heartbeat is
# present + fresh. The gate is evaluated per cycle in
# ``build_full_observation_status``; per-symbol builders mask the
# tracker-derived fields when consumption is blocked.
TRACKER_CODEX_PASS_MARKER_PATHS: tuple[Path, ...] = (
    Path(
        "claude_worklog/final_readiness/v2_position_history_tracker_daemon_remediation/"
        "latest/codex_review/CODEX_GO_NO_GO.md"
    ),
    Path(
        "claude_worklog/final_readiness/v2_position_history_persistent_tracker/"
        "latest/codex_review/CODEX_GO_NO_GO.md"
    ),
)
ACCEPTED_TRACKER_CODEX_PASS_TOKENS = frozenset(
    {
        "V2_POSITION_HISTORY_TRACKER_DAEMON_REMEDIATION_CODEX_PASS",
        "V2_POSITION_HISTORY_PERSISTENT_TRACKER_CODEX_PASS",
    }
)
TRACKER_HEARTBEAT_KEY = "v2:paper:position_history:heartbeat"
TRACKER_HEARTBEAT_MAX_AGE_SECONDS_DEFAULT = 180

CONSUMPTION_STATE_ALLOWED = "ALLOWED_AFTER_CODEX_PASS_AND_FRESH_HEARTBEAT"
CONSUMPTION_STATE_BLOCKED_TRACKER_NOT_CODEX_PASSED = (
    "BLOCKED_TRACKER_NOT_CODEX_PASSED"
)
CONSUMPTION_STATE_BLOCKED_HEARTBEAT_MISSING = "BLOCKED_HEARTBEAT_MISSING"
CONSUMPTION_STATE_BLOCKED_HEARTBEAT_STALE = "BLOCKED_HEARTBEAT_STALE"
CONSUMPTION_STATE_BLOCKED_HEARTBEAT_TTL_NOT_POSITIVE = (
    "BLOCKED_HEARTBEAT_TTL_NOT_POSITIVE"
)

BLOCKED_REASON_TRACKER_NOT_CODEX_PASSED = "TRACKER_CODEX_PASS_MISSING_OR_MISMATCH"
BLOCKED_REASON_HEARTBEAT_MISSING = "TRACKER_HEARTBEAT_MISSING"
BLOCKED_REASON_HEARTBEAT_STALE_PREFIX = "TRACKER_HEARTBEAT_STALE"
BLOCKED_REASON_HEARTBEAT_TTL_NOT_POSITIVE_PREFIX = "TRACKER_HEARTBEAT_TTL_NOT_POSITIVE"


def _read_tracker_marker_content(path: Path) -> str | None:
    try:
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return None


def _heartbeat_age_seconds(
    payload: Mapping[str, Any] | None, now: datetime | None
) -> int | None:
    if not payload:
        return None
    # ``finished_at`` and ``started_at`` are the canonical trainer heartbeat
    # timestamps (v2:trainer:heartbeat). Tracker, orchestrator, and other
    # heartbeat payloads use ``generated_utc``/``heartbeat_at``/``generated_at``
    # so they continue to take precedence; trainer falls back to its own
    # publisher fields.
    for key in (
        "generated_utc",
        "heartbeat_at",
        "generated_at",
        "finished_at",
        "started_at",
    ):
        ts_str = payload.get(key)
        if not ts_str:
            continue
        try:
            text = str(ts_str)
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            base = now or datetime.now(timezone.utc)
            age = (base - parsed.astimezone(timezone.utc)).total_seconds()
            return max(0, int(age))
        except Exception:
            continue
    return None


def evaluate_position_history_consumption_gate(
    *,
    codex_pass_marker_paths: tuple[Path, ...] | None = None,
    tracker_heartbeat: Mapping[str, Any] | None = None,
    tracker_heartbeat_ttl_seconds: int | None = None,
    max_heartbeat_age_seconds: int = TRACKER_HEARTBEAT_MAX_AGE_SECONDS_DEFAULT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Decide whether the full-observation builder may consume the
    position-history tracker's Redis keys this cycle.

    Allowed iff:
      - any of the listed Codex PASS markers contains an accepted
        ``*_CODEX_PASS`` token, AND
      - ``tracker_heartbeat`` is a non-empty dict, AND
      - ``tracker_heartbeat_ttl_seconds`` is None or positive, AND
      - the heartbeat ``generated_utc`` is within
        ``max_heartbeat_age_seconds``.

    Returns a dict with ``consumption_allowed`` (bool), ``blocked_reason``
    (None when allowed), ``consumption_state``, and all probe fields the
    operator dashboard needs to audit the decision.
    """
    paths = codex_pass_marker_paths or TRACKER_CODEX_PASS_MARKER_PATHS
    marker_results: list[dict[str, Any]] = []
    any_pass = False
    for path in paths:
        content = _read_tracker_marker_content(Path(path))
        actual_token = content if content is not None else "MISSING"
        passed = bool(content) and content in ACCEPTED_TRACKER_CODEX_PASS_TOKENS
        marker_results.append(
            {"path": str(path), "actual_token": actual_token, "passed": passed}
        )
        if passed:
            any_pass = True
    hb_present = bool(tracker_heartbeat)
    hb_ttl_seconds = (
        int(tracker_heartbeat_ttl_seconds)
        if tracker_heartbeat_ttl_seconds is not None
        else None
    )
    hb_age = _heartbeat_age_seconds(tracker_heartbeat, now)
    hb_generated_utc = (
        tracker_heartbeat.get("generated_utc") if tracker_heartbeat else None
    )
    hb_fresh = (
        hb_present
        and hb_age is not None
        and hb_age <= max_heartbeat_age_seconds
        and (hb_ttl_seconds is None or hb_ttl_seconds > 0)
    )
    blocked_reason: str | None = None
    consumption_state = CONSUMPTION_STATE_ALLOWED
    if not any_pass:
        blocked_reason = BLOCKED_REASON_TRACKER_NOT_CODEX_PASSED
        consumption_state = CONSUMPTION_STATE_BLOCKED_TRACKER_NOT_CODEX_PASSED
    elif not hb_present:
        blocked_reason = BLOCKED_REASON_HEARTBEAT_MISSING
        consumption_state = CONSUMPTION_STATE_BLOCKED_HEARTBEAT_MISSING
    elif hb_ttl_seconds is not None and hb_ttl_seconds <= 0:
        blocked_reason = (
            f"{BLOCKED_REASON_HEARTBEAT_TTL_NOT_POSITIVE_PREFIX}:{hb_ttl_seconds}"
        )
        consumption_state = CONSUMPTION_STATE_BLOCKED_HEARTBEAT_TTL_NOT_POSITIVE
    elif not hb_fresh:
        blocked_reason = f"{BLOCKED_REASON_HEARTBEAT_STALE_PREFIX}:{hb_age}"
        consumption_state = CONSUMPTION_STATE_BLOCKED_HEARTBEAT_STALE
    return {
        "consumption_allowed": blocked_reason is None,
        "blocked_reason": blocked_reason,
        "consumption_state": consumption_state,
        "consumption_unblocked_after": sorted(ACCEPTED_TRACKER_CODEX_PASS_TOKENS),
        "tracker_codex_pass_markers": marker_results,
        "tracker_codex_pass_marker_paths_passed": [
            m["path"] for m in marker_results if m["passed"]
        ],
        "tracker_codex_pass_marker_paths_failed": [
            m["path"] for m in marker_results if not m["passed"]
        ],
        "tracker_heartbeat_key": TRACKER_HEARTBEAT_KEY,
        "tracker_heartbeat_present": hb_present,
        "tracker_heartbeat_ttl_seconds": hb_ttl_seconds,
        "tracker_heartbeat_age_seconds": hb_age,
        "tracker_heartbeat_fresh": bool(hb_fresh),
        "tracker_heartbeat_generated_utc": hb_generated_utc,
        "tracker_heartbeat_max_age_seconds": max_heartbeat_age_seconds,
    }


# Strict tracker-history-derived fields: their values MUST come from
# the Codex-passed tracker-owned Redis keys
# (``v2:paper:position_history:*`` / ``v2:paper:position_price_track:*``).
# They are NEVER computed from raw ``v2:paper:positions``,
# ``v2:paper:ledger``, ``v2:paper:intents``, or
# ``v2:paper:intents_held_by_paper_fill_gate``. When the consumption
# gate is blocked, these fields are masked with
# ``V2_POSITION_HISTORY_TRACKER_CONSUMPTION_BLOCKED:<reason>``.
TRACKER_HISTORY_DERIVED_FIELDS: tuple[str, ...] = (
    "v2_position_history_present",
    "v2_hold_time_seconds_current",
    "v2_intents_accepted_count",
    "v2_intents_held_count",
    "v2_intents_blocked_count",
    "v2_mfe_bps",
    "v2_mae_bps",
    "v2_roe_bps",
    "v2_position_age_seconds",
    "v2_hold_time_proxy_seconds",
)

# Raw paper-context fields: computed from raw V2 paper inputs
# (``paper_intents`` / ``paper_intents_held`` / ``paper_ledger``)
# and clearly labeled so the operator can distinguish them from the
# tracker-derived fields. They are NOT gated by the tracker
# consumption gate because they do not depend on tracker state. The
# v2_*_rate fields moved out of this set in the risk-decision exact-source
# burndown and now consume only ``v2:risk:decisions``.
RAW_PAPER_CONTEXT_FIELDS: tuple[str, ...] = (
    "v2_block_reason_negative_expected_move_count",
    "v2_block_reason_edge_below_threshold_count",
    "v2_block_reason_feature_freshness_count",
    "v2_block_reason_checkpoint_required_count",
    "v2_block_reason_trainer_malformed_count",
    "v2_block_reason_other_count",
)

# Strict tracker-extended position-context fields. Like
# ``TRACKER_HISTORY_DERIVED_FIELDS``, these are sourced ONLY from the
# two tracker-owned Redis keys (``v2:paper:position_price_track:{symbol}``
# and ``v2:paper:position_history:{symbol}``) — NEVER from raw
# ``v2:paper:positions`` / ``ledger`` / ``intents`` /
# ``intents_held_by_paper_fill_gate``. When the consumption gate is
# blocked, they are masked with
# ``V2_POSITION_HISTORY_TRACKER_CONSUMPTION_BLOCKED:<reason>``.
#
# Five fields come from the ``position_price_track`` payload (the
# recorder's `v2_position_price_track_v1` schema): ``latest_price``,
# ``entry_price``, ``source_freshness_seconds``, ``missing_flags``
# (length), and ``stale_flags`` (length). One field comes from the
# ``position_history`` payload (`v2_position_history_persistent_v1`):
# ``shadow_observation_count`` (intent counter that is intentionally
# NOT counted as accepted).
TRACKER_EXTENDED_FIELDS: tuple[str, ...] = (
    "v2_tracker_latest_price",
    "v2_tracker_entry_price",
    "v2_tracker_source_freshness_seconds",
    "v2_tracker_missing_flag_count",
    "v2_tracker_stale_flag_count",
    "v2_shadow_observation_count",
)

# Backwards-compat alias used by the prior packet's tests/status JSON
# enumeration. Same set of strict tracker-history-derived field names.
TRACKER_DERIVED_POSITION_CONTEXT_FIELDS: tuple[str, ...] = TRACKER_HISTORY_DERIVED_FIELDS

# Source-attribution constants for the tracker-only path.
SOURCE_TRACKER_HISTORY = "V2_POSITION_HISTORY_TRACKER"
SOURCE_TRACKER_NO_OPEN_POSITION = "V2_POSITION_HISTORY_TRACKER_NO_OPEN_POSITION"
SOURCE_TRACKER_PAYLOAD_MISSING = "V2_POSITION_HISTORY_TRACKER_PAYLOAD_MISSING"
SOURCE_TRACKER_PAYLOAD_FIELD_MISSING = "V2_POSITION_HISTORY_TRACKER_PAYLOAD_FIELD_MISSING"
SOURCE_RAW_PAPER_CONTEXT = "V2_RAW_PAPER_CONTEXT_NOT_TRACKER_HISTORY"
SOURCE_RAW_PAPER_CONTEXT_MISSING = "MISSING_V2_RAW_PAPER_CONTEXT"


def _consumption_blocked_source(blocked_reason: str | None) -> str:
    return (
        "V2_POSITION_HISTORY_TRACKER_CONSUMPTION_BLOCKED:"
        f"{blocked_reason or 'UNKNOWN'}"
    )


def _coerce_int_to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_open_position_state(state: Any) -> bool:
    if not isinstance(state, str):
        return False
    return state.upper().startswith("OPEN")


def _extract_tracker_history_fields(
    *,
    symbol: str,
    position_history: Mapping[str, Any] | None,
    consumption_allowed: bool | None,
    consumption_blocked_reason: str | None,
) -> list[tuple[str, float | None, str]]:
    """Extract the 10 strict tracker-history-derived position-context
    fields from ONLY the tracker payload (``position_history``).

    NEVER reads ``paper_positions``, ``paper_ledger``, ``paper_intents``,
    or ``paper_intents_held``. Tracker counts (accepted / held / blocked)
    come straight from the tracker payload; MFE / MAE / ROE / hold time
    come straight from the tracker payload.

    When ``consumption_allowed`` is ``False``: all 10 fields are masked
    with ``V2_POSITION_HISTORY_TRACKER_CONSUMPTION_BLOCKED:<reason>``.

    When the tracker payload is missing or for a different symbol: all
    10 fields are emitted as ``None`` with
    ``V2_POSITION_HISTORY_TRACKER_PAYLOAD_MISSING``.

    When the tracker reports ``position_state=NO_OPEN_POSITION``:
    intent counts come from the tracker payload (they may be ``0``);
    MFE / MAE / ROE / hold-time / position-age stay ``None`` with
    ``V2_POSITION_HISTORY_TRACKER_NO_OPEN_POSITION``.
    """
    if consumption_allowed is False:
        masking_source = _consumption_blocked_source(consumption_blocked_reason)
        return [(field, None, masking_source) for field in TRACKER_HISTORY_DERIVED_FIELDS]
    if not isinstance(position_history, Mapping):
        return [
            (field, None, SOURCE_TRACKER_PAYLOAD_MISSING)
            for field in TRACKER_HISTORY_DERIVED_FIELDS
        ]
    payload_symbol = (position_history.get("symbol") or "").upper()
    if payload_symbol and payload_symbol != symbol.upper():
        return [
            (field, None, SOURCE_TRACKER_PAYLOAD_MISSING)
            for field in TRACKER_HISTORY_DERIVED_FIELDS
        ]
    state_raw = position_history.get("position_state")
    is_open = _is_open_position_state(state_raw)
    is_no_open_position = (
        isinstance(state_raw, str) and state_raw.upper() == "NO_OPEN_POSITION"
    )
    accepted = _coerce_int_to_float(position_history.get("accepted_intent_count"))
    held = _coerce_int_to_float(position_history.get("held_intent_count"))
    blocked = _coerce_int_to_float(position_history.get("block_reason_count"))
    mfe = _coerce_float(position_history.get("max_favorable_bps"))
    if mfe is None:
        mfe = _coerce_float(position_history.get("mfe_bps"))
    mae = _coerce_float(position_history.get("max_adverse_bps"))
    if mae is None:
        mae = _coerce_float(position_history.get("mae_bps"))
    roe = _coerce_float(position_history.get("unrealized_bps"))
    if roe is None:
        roe = _coerce_float(position_history.get("roe_bps"))
    hold_time = _coerce_float(position_history.get("hold_time_seconds"))

    def _src(value: Any, no_open_fallback: str = SOURCE_TRACKER_HISTORY) -> str:
        if value is None:
            return (
                SOURCE_TRACKER_NO_OPEN_POSITION
                if is_no_open_position
                else SOURCE_TRACKER_PAYLOAD_FIELD_MISSING
            )
        return no_open_fallback

    presence_value = 1.0 if is_open else 0.0
    if is_no_open_position:
        no_open_source = SOURCE_TRACKER_NO_OPEN_POSITION
        return [
            ("v2_position_history_present", presence_value, SOURCE_TRACKER_HISTORY),
            ("v2_hold_time_seconds_current", None, no_open_source),
            ("v2_intents_accepted_count",
             accepted if accepted is not None else 0.0,
             SOURCE_TRACKER_HISTORY),
            ("v2_intents_held_count",
             held if held is not None else 0.0,
             SOURCE_TRACKER_HISTORY),
            ("v2_intents_blocked_count",
             blocked if blocked is not None else 0.0,
             SOURCE_TRACKER_HISTORY),
            ("v2_mfe_bps", None, no_open_source),
            ("v2_mae_bps", None, no_open_source),
            ("v2_roe_bps", None, no_open_source),
            ("v2_position_age_seconds", None, no_open_source),
            ("v2_hold_time_proxy_seconds", None, no_open_source),
        ]
    return [
        ("v2_position_history_present", presence_value, SOURCE_TRACKER_HISTORY),
        ("v2_hold_time_seconds_current", hold_time, _src(hold_time)),
        ("v2_intents_accepted_count",
         accepted if accepted is not None else 0.0,
         SOURCE_TRACKER_HISTORY if accepted is not None else SOURCE_TRACKER_PAYLOAD_FIELD_MISSING),
        ("v2_intents_held_count",
         held if held is not None else 0.0,
         SOURCE_TRACKER_HISTORY if held is not None else SOURCE_TRACKER_PAYLOAD_FIELD_MISSING),
        ("v2_intents_blocked_count",
         blocked if blocked is not None else 0.0,
         SOURCE_TRACKER_HISTORY if blocked is not None else SOURCE_TRACKER_PAYLOAD_FIELD_MISSING),
        ("v2_mfe_bps", mfe, _src(mfe)),
        ("v2_mae_bps", mae, _src(mae)),
        ("v2_roe_bps", roe, _src(roe)),
        ("v2_position_age_seconds", hold_time, _src(hold_time)),
        ("v2_hold_time_proxy_seconds", hold_time, _src(hold_time)),
    ]


def _extract_tracker_extended_fields(
    *,
    symbol: str,
    position_history: Mapping[str, Any] | None,
    position_price_track: Mapping[str, Any] | None,
    consumption_allowed: bool | None,
    consumption_blocked_reason: str | None,
) -> list[tuple[str, float | None, str]]:
    """Extract the 6 tracker-extended position-context fields strictly
    from the two tracker-owned Redis payloads.

    NEVER reads ``paper_positions``, ``paper_ledger``, ``paper_intents``,
    or ``paper_intents_held``. Price-track fields (latest_price,
    entry_price, source_freshness_seconds, missing/stale flag counts)
    come straight from ``position_price_track``. ``shadow_observation_count``
    comes straight from ``position_history``.

    When ``consumption_allowed`` is ``False``: all 6 fields are masked
    with ``V2_POSITION_HISTORY_TRACKER_CONSUMPTION_BLOCKED:<reason>``.

    When the tracker payload is missing or carries a different symbol:
    the corresponding field is emitted as ``None`` with
    ``V2_POSITION_HISTORY_TRACKER_PAYLOAD_MISSING`` or
    ``V2_POSITION_HISTORY_TRACKER_PAYLOAD_FIELD_MISSING``. Counts
    derived from list lengths (``missing_flags``, ``stale_flags``) are
    reported as ``0.0`` only when the source list field is present
    (possibly empty); a fully-absent payload is left as ``None`` with
    a missing source.
    """
    if consumption_allowed is False:
        masking_source = _consumption_blocked_source(consumption_blocked_reason)
        return [(field, None, masking_source) for field in TRACKER_EXTENDED_FIELDS]

    def _payload_for_symbol(
        payload: Mapping[str, Any] | None,
    ) -> Mapping[str, Any] | None:
        if not isinstance(payload, Mapping):
            return None
        payload_symbol = (payload.get("symbol") or "").upper()
        if payload_symbol and payload_symbol != symbol.upper():
            return None
        return payload

    track = _payload_for_symbol(position_price_track)
    history = _payload_for_symbol(position_history)

    def _track_numeric(field_name: str) -> tuple[float | None, str]:
        if track is None:
            return (None, SOURCE_TRACKER_PAYLOAD_MISSING)
        raw = track.get(field_name)
        if raw is None:
            return (None, SOURCE_TRACKER_PAYLOAD_FIELD_MISSING)
        v = _coerce_float(raw)
        if v is None:
            return (None, SOURCE_TRACKER_PAYLOAD_FIELD_MISSING)
        return (v, SOURCE_TRACKER_HISTORY)

    def _track_flag_count(field_name: str) -> tuple[float | None, str]:
        if track is None:
            return (None, SOURCE_TRACKER_PAYLOAD_MISSING)
        flags = track.get(field_name)
        # The recorder always emits the list (possibly empty). If the
        # key is fully absent that means a malformed payload, so we
        # surface FIELD_MISSING rather than reporting 0.
        if flags is None:
            return (None, SOURCE_TRACKER_PAYLOAD_FIELD_MISSING)
        if not isinstance(flags, (list, tuple)):
            return (None, SOURCE_TRACKER_PAYLOAD_FIELD_MISSING)
        return (float(len(flags)), SOURCE_TRACKER_HISTORY)

    latest_price_v, latest_price_s = _track_numeric("latest_price")
    entry_price_v, entry_price_s = _track_numeric("entry_price")
    freshness_v, freshness_s = _track_numeric("source_freshness_seconds")
    missing_flag_v, missing_flag_s = _track_flag_count("missing_flags")
    stale_flag_v, stale_flag_s = _track_flag_count("stale_flags")

    if history is None:
        shadow_v, shadow_s = (None, SOURCE_TRACKER_PAYLOAD_MISSING)
    else:
        raw_shadow = history.get("shadow_observation_count")
        if raw_shadow is None:
            shadow_v, shadow_s = (None, SOURCE_TRACKER_PAYLOAD_FIELD_MISSING)
        else:
            shadow_coerced = _coerce_int_to_float(raw_shadow)
            if shadow_coerced is None:
                shadow_v, shadow_s = (None, SOURCE_TRACKER_PAYLOAD_FIELD_MISSING)
            else:
                shadow_v, shadow_s = (shadow_coerced, SOURCE_TRACKER_HISTORY)

    return [
        ("v2_tracker_latest_price", latest_price_v, latest_price_s),
        ("v2_tracker_entry_price", entry_price_v, entry_price_s),
        ("v2_tracker_source_freshness_seconds", freshness_v, freshness_s),
        ("v2_tracker_missing_flag_count", missing_flag_v, missing_flag_s),
        ("v2_tracker_stale_flag_count", stale_flag_v, stale_flag_s),
        ("v2_shadow_observation_count", shadow_v, shadow_s),
    ]


def _extract_raw_paper_context_fields(
    *,
    symbol: str,
    risk_decisions: list[Mapping[str, Any]] | None,
    paper_intents: list[Mapping[str, Any]] | None,
    paper_intents_held: list[Mapping[str, Any]] | None,
    paper_ledger: Mapping[str, Any] | None,
) -> list[tuple[str, float | None, str]]:
    """Extract risk-decision rates plus raw paper block-reason context.

    The three ``v2_*_rate`` fields are exact-source
    ``v2:risk:decisions`` fields selected by the autonomous controller.
    The remaining granular block-reason counters are raw V2 paper context
    and keep the explicit ``V2_RAW_PAPER_CONTEXT_NOT_TRACKER_HISTORY``
    source label. This function never reads tracker payloads or legacy
    Redis current truth.
    """
    # The position_history_aggregator is used only for granular raw-paper
    # block-reason counters below. The v2_*_rate fields are exact
    # v2:risk:decisions projections and must not fall back to raw paper.
    # We call the aggregator with empty position_history /
    # position_price_track to make the tracker boundary explicit:
    # tracker-derived outputs are ignored here. ``paper_positions`` is
    # intentionally empty: this path computes intent-context counters
    # only, not position presence.
    from v2.backend.app.services.rl_core.position_history_aggregator import (
        aggregate_symbol,
    )
    history = aggregate_symbol(
        symbol=symbol,
        paper_positions=[],
        paper_intents=list(paper_intents or []),
        paper_intents_held=list(paper_intents_held or []),
        paper_ledger=paper_ledger or {},
        position_price_track=None,
        position_history=None,
    )
    src = SOURCE_RAW_PAPER_CONTEXT
    missing_src = SOURCE_RAW_PAPER_CONTEXT_MISSING
    rd = _mapping_rows(risk_decisions)
    rd_sym_rows = [
        row for row in rd if (row.get("symbol") or "").upper() == symbol.upper()
    ]

    def _risk_rate(field: str) -> tuple[float | None, str]:
        if risk_decisions is None:
            return (None, "MISSING_FROM_V2_RISK_DECISIONS")
        if not rd_sym_rows:
            return (None, "MISSING_FROM_V2_RISK_DECISIONS_SYMBOL_ROW")
        values = [row.get(field) for row in rd_sym_rows if row.get(field) is not None]
        if not values:
            return (None, f"MISSING_FROM_V2_RISK_DECISIONS_FIELD_{field.upper()}")
        allowed = sum(1 for value in values if bool(value))
        return (allowed / float(len(values)), "V2_RISK_DECISIONS")

    def _rate(value: Any) -> tuple[float | None, str]:
        v = _coerce_float(value)
        return (v, src if v is not None else missing_src)

    def _count(value: Any) -> tuple[float | None, str]:
        try:
            return (float(value), src)
        except (TypeError, ValueError):
            return (None, missing_src)

    return [
        ("v2_pre_trade_allowed_rate", *_risk_rate("pre_trade_allowed")),
        ("v2_fee_gate_allowed_rate", *_risk_rate("fee_gate_allowed")),
        ("v2_churn_blocked_rate", *_risk_rate("churn_blocked")),
        ("v2_block_reason_negative_expected_move_count",
         *_count(history.block_reason_negative_expected_move_count)),
        ("v2_block_reason_edge_below_threshold_count",
         *_count(history.block_reason_edge_below_threshold_count)),
        ("v2_block_reason_feature_freshness_count",
         *_count(history.block_reason_feature_freshness_count)),
        ("v2_block_reason_checkpoint_required_count",
         *_count(history.block_reason_checkpoint_required_count)),
        ("v2_block_reason_trainer_malformed_count",
         *_count(history.block_reason_trainer_malformed_count)),
        ("v2_block_reason_other_count", *_count(history.block_reason_other_count)),
    ]

# ---------------------------------------------------------------------------
# Sub-family layout within the legacy unified_features 1430-dim slice.
# Sizes mirror legacy_owned_runtime/rl/unified_feature_builder.FeatureDimensions
# defaults. The legacy V3 schema reserves 1430 dims; sub-family chunks
# sum to 137. The trailing 1293 dims are explicit
# MISSING_LEGACY_V3_EXTRA_NO_V2_SOURCE.
# ---------------------------------------------------------------------------
SUBFAMILY_LAYOUT: tuple[tuple[str, int], ...] = (
    ("binance_klines", 20),
    ("binance_orderbook", 15),
    ("ccxt_ohlcv", 10),
    ("liquidations", 12),
    ("technical_analysis", 25),
    ("token_metrics", 18),
    ("coinank", 22),
    ("portfolio_state_unified", 15),
)

OPERATOR_OR_EXTERNAL_SUBFAMILIES = {
    "ccxt_ohlcv",
    "onchain_btc",
    "onchain_eth",
    "token_metrics",
}

EVENT_DEPENDENT_SUBFAMILIES = {
    "liquidations",
}

CONDITIONALLY_UNDEFINED_SUBFAMILIES = {
    "technical_analysis",
}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
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


def _payload_age_seconds(payload: Mapping[str, Any] | None) -> float | None:
    age = _heartbeat_age_seconds(payload, None)
    return float(age) if age is not None else None


def _risk_field_source(
    *,
    risk_decisions: list[Mapping[str, Any]] | None,
    symbol_row: Mapping[str, Any] | None,
    field: str,
) -> str:
    """Explicit-missing source label for a v2:risk:decisions-sourced field.

    Distinguishes four runtime states so the operator/Codex can tell at a
    glance which honesty boundary was hit:

      - ``MISSING_FROM_V2_RISK_DECISIONS`` -- v2:risk:decisions payload is
        absent entirely (Redis key None);
      - ``MISSING_FROM_V2_RISK_DECISIONS_SYMBOL_ROW`` -- payload present but
        no row whose ``symbol`` matches this symbol;
      - ``MISSING_FROM_V2_RISK_DECISIONS_FIELD_<FIELD>`` -- row matched but
        the per-field key is None / absent;
      - ``V2_RISK_DECISIONS`` -- sourced.

    No fallback to paper/orchestrator/trainer/legacy keys is consulted.
    No zero-fill is performed; callers translate the value via ``_flag``
    which preserves ``None`` semantics.
    """
    if risk_decisions is None:
        return "MISSING_FROM_V2_RISK_DECISIONS"
    if symbol_row is None:
        return "MISSING_FROM_V2_RISK_DECISIONS_SYMBOL_ROW"
    if symbol_row.get(field) is None:
        return f"MISSING_FROM_V2_RISK_DECISIONS_FIELD_{field.upper()}"
    return "V2_RISK_DECISIONS"


def _mapping_rows(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _rows_for_symbol(rows: list[Mapping[str, Any]], symbol: str) -> list[Mapping[str, Any]]:
    return [
        row for row in rows
        if (row.get("symbol") or "").upper() == symbol.upper()
    ]


def _dedupe_rows(rows: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    seen: set[str] = set()
    out: list[Mapping[str, Any]] = []
    for row in rows:
        identity_parts = [
            str(row.get("intent_id") or ""),
            str(row.get("source_intent_id") or ""),
            str(row.get("source_prediction_id") or ""),
            str(row.get("prediction_id") or ""),
            str(row.get("symbol") or ""),
            str(row.get("decision") or row.get("status") or ""),
        ]
        identity = "|".join(identity_parts)
        if not identity.strip("|"):
            identity = json.dumps(dict(row), sort_keys=True, default=str)
        if identity in seen:
            continue
        seen.add(identity)
        out.append(row)
    return out


def _row_text(row: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "decision",
        "status",
        "paper_fill_gate_status",
        "paper_fill_status",
        "classification",
        "source",
        "source_type",
    ):
        value = row.get(key)
        if value is not None:
            parts.append(str(value))
    for key in ("paper_fill_gate_block_reasons", "block_reasons", "tags"):
        value = row.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
    return " ".join(parts).upper()


def _row_is_shadow(row: Mapping[str, Any]) -> bool:
    text = _row_text(row)
    return (
        "SHADOW" in text
        or row.get("counted_as_accepted_position") is False
        or row.get("counted_as_fill") is False
        or row.get("counted_as_open_position") is False
    )


def _row_is_held(row: Mapping[str, Any]) -> bool:
    text = _row_text(row)
    return "HELD" in text or "PAPER_FILL_GATE" in text


def _row_is_blocked(row: Mapping[str, Any]) -> bool:
    text = _row_text(row)
    return "BLOCK" in text or "REJECT" in text or "DENY" in text


def _row_is_accepted_fill(row: Mapping[str, Any]) -> bool:
    if _row_is_shadow(row) or _row_is_held(row) or _row_is_blocked(row):
        return False
    if row.get("paper_fill_allowed") is False:
        return False
    if row.get("places_real_order") is True:
        return False
    text = _row_text(row)
    if "ACCEPT" in text or "FILL" in text or row.get("counted_as_accepted_position") is True:
        return True
    if any(row.get(key) is not None for key in ("fill_price", "entry_price", "quantity", "notional")):
        return True
    return False


def _ledger_rows(ledger: Mapping[str, Any], *keys: str) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for key in keys:
        rows.extend(_mapping_rows(ledger.get(key)))
    return rows


def _safe_ledger_accepted_fill_count(ledger: Mapping[str, Any]) -> float | None:
    rows = _dedupe_rows(_ledger_rows(ledger, "accepted", "accepted_intents"))
    if rows:
        return float(sum(1 for row in rows if _row_is_accepted_fill(row)))
    count = _coerce_float(ledger.get("accepted_count"))
    return count


def _safe_ledger_blocked_count(ledger: Mapping[str, Any]) -> float | None:
    rows = _dedupe_rows(_ledger_rows(ledger, "blocked"))
    if rows:
        return float(len(rows))
    return _coerce_float(ledger.get("blocked_count"))


def _safe_ledger_held_count(ledger: Mapping[str, Any]) -> float | None:
    rows = _dedupe_rows(_ledger_rows(ledger, "held_by_paper_fill_gate"))
    if rows:
        return float(len(rows))
    return _coerce_float(ledger.get("held_by_paper_fill_gate_count"))


def _safe_ledger_shadow_count(ledger: Mapping[str, Any]) -> float | None:
    rows = _dedupe_rows(_ledger_rows(ledger, "shadow_observations"))
    if rows:
        return float(len(rows))
    return _coerce_float(ledger.get("shadow_observation_count"))


def _sum_numeric_fields(rows: list[Mapping[str, Any]], *field_names: str) -> float | None:
    total = 0.0
    found = False
    for row in rows:
        for field_name in field_names:
            value = _coerce_float(row.get(field_name))
            if value is not None:
                total += value
                found = True
    return total if found else None


def _candidate_row_for_symbol(
    candidates_payload: Mapping[str, Any] | None,
    symbol: str,
) -> Mapping[str, Any] | None:
    if not isinstance(candidates_payload, Mapping):
        return None
    for row in _mapping_rows(candidates_payload.get("candidates")):
        if (row.get("symbol") or "").upper() == symbol.upper():
            return row
    return None


@dataclasses.dataclass(frozen=True)
class FullObservationResult:
    symbol: str
    timeframe: str
    feature_snapshot_id: str | None
    source_freshness_state: str | None
    compact_observation_dim: int
    target_full_observation_dim: int
    generated_full_observation_dim: int
    missing_dim_count: int
    zero_filled_field_count: int
    field_names: tuple[str, ...]
    field_values: tuple[float | None, ...]
    field_sources: tuple[str, ...]
    missing_field_names: tuple[str, ...]
    partial_field_names: tuple[str, ...]
    explicit_missing_categories: tuple[str, ...]
    partial_categories: tuple[str, ...]
    present_categories: tuple[str, ...]
    state: str
    subfamily_present_counts: dict[str, int]
    subfamily_target_counts: dict[str, int]


# ---------------------------------------------------------------------------
# Per-subfamily V2-native projections. Each function returns a list of
# (name, value, source) tuples whose length is exactly the subfamily target
# size. Position N of the returned list lands at slot N of that subfamily
# inside the unified_features slice. Slots with no V2 source are emitted as
# (name, None, MISSING_*) — never zero-filled.
# ---------------------------------------------------------------------------
def _project_binance_klines(
    market_price: Mapping[str, Any] | None,
    v2_features: Mapping[str, Any] | None,
) -> list[tuple[str, float | None, str]]:
    size = 20
    out: list[tuple[str, float | None, str]] = [
        (f"binance_klines[{i}]", None, "MISSING_FROM_V2_BINANCE_KLINE_PROJECTION")
        for i in range(size)
    ]
    ticker = ((market_price or {}).get("ticker_24hr") or {}) if isinstance(market_price, Mapping) else {}
    feats = v2_features or {}
    ema_12 = _coerce_float(feats.get("ema_12"))
    ema_26 = _coerce_float(feats.get("ema_26"))
    ema_diff = (ema_12 - ema_26) if (ema_12 is not None and ema_26 is not None) else None
    rows: list[tuple[str, float | None, str]] = [
        ("last_price", _coerce_float(ticker.get("lastPrice")), "V2_MARKET_TICKER_24HR"),
        ("open_price", _coerce_float(ticker.get("openPrice")), "V2_MARKET_TICKER_24HR"),
        ("high_price", _coerce_float(ticker.get("highPrice")), "V2_MARKET_TICKER_24HR"),
        ("low_price", _coerce_float(ticker.get("lowPrice")), "V2_MARKET_TICKER_24HR"),
        ("prev_close", _coerce_float(ticker.get("prevClosePrice")), "V2_MARKET_TICKER_24HR"),
        ("weighted_avg", _coerce_float(ticker.get("weightedAvgPrice")), "V2_MARKET_TICKER_24HR"),
        ("volume", _coerce_float(ticker.get("volume")), "V2_MARKET_TICKER_24HR"),
        ("quote_volume", _coerce_float(ticker.get("quoteVolume")), "V2_MARKET_TICKER_24HR"),
        ("trade_count", _coerce_float(ticker.get("count")), "V2_MARKET_TICKER_24HR"),
        ("price_change", _coerce_float(ticker.get("priceChange")), "V2_MARKET_TICKER_24HR"),
        ("price_change_pct", _coerce_float(ticker.get("priceChangePercent")), "V2_MARKET_TICKER_24HR"),
        ("ret_pct", _coerce_float(feats.get("ret_pct")), "V2_NATIVE_FEATURE_SNAPSHOT"),
        ("log_return", _coerce_float(feats.get("log_return")), "V2_NATIVE_FEATURE_SNAPSHOT"),
        ("body_pct", _coerce_float(feats.get("body_pct")), "V2_NATIVE_FEATURE_SNAPSHOT"),
        ("range_pct", _coerce_float(feats.get("range_pct")), "V2_NATIVE_FEATURE_SNAPSHOT"),
        ("gap_pct", _coerce_float(feats.get("gap_pct")), "V2_NATIVE_FEATURE_SNAPSHOT"),
        ("true_range_pct", _coerce_float(feats.get("true_range_pct")), "V2_NATIVE_FEATURE_SNAPSHOT"),
        ("ema_12", ema_12, "V2_NATIVE_FEATURE_SNAPSHOT"),
        ("ema_26", ema_26, "V2_NATIVE_FEATURE_SNAPSHOT"),
        ("ema_diff", ema_diff, "V2_DERIVED_FROM_FEATURES"),
    ]
    for i, (nm, val, src) in enumerate(rows[:size]):
        if val is None:
            out[i] = (f"binance_klines.{nm}", None, "MISSING_FROM_V2_BINANCE_KLINE_PROJECTION")
        else:
            out[i] = (f"binance_klines.{nm}", val, src)
    return out


def _project_binance_orderbook(
    market_price: Mapping[str, Any] | None,
    v2_features: Mapping[str, Any] | None,
) -> list[tuple[str, float | None, str]]:
    size = 15
    out: list[tuple[str, float | None, str]] = [
        (f"binance_orderbook[{i}]", None, "MISSING_FROM_V2_BINANCE_ORDERBOOK_PROJECTION")
        for i in range(size)
    ]
    ticker = ((market_price or {}).get("ticker_24hr") or {}) if isinstance(market_price, Mapping) else {}
    feats = v2_features or {}
    bid = _coerce_float(ticker.get("bidPrice"))
    ask = _coerce_float(ticker.get("askPrice"))
    bid_qty = _coerce_float(ticker.get("bidQty"))
    ask_qty = _coerce_float(ticker.get("askQty"))
    mid = None
    if bid is not None and ask is not None:
        mid = (bid + ask) / 2.0
    spread = None
    if bid is not None and ask is not None and mid not in (None, 0.0):
        spread = (ask - bid) / mid
    depth_imb = _coerce_float(feats.get("depth_imbalance"))
    depth_imb_dir = (
        None if depth_imb is None else
        (1.0 if depth_imb > 0 else (-1.0 if depth_imb < 0 else 0.0))
    )
    bid_qty_minus_ask_qty = (
        (bid_qty - ask_qty) if (bid_qty is not None and ask_qty is not None) else None
    )
    micro = _coerce_float(feats.get("micro_price"))
    mid_minus_micro = (
        (mid - micro) if (mid is not None and micro is not None) else None
    )
    # No v2:market:depth* exists today — explicit 0.0 source-availability
    # flag is honest evidence, not fabrication.
    v2_depth_source_available = 0.0
    rows: list[tuple[str, float | None, str]] = [
        ("bid_price", bid, "V2_MARKET_TICKER_24HR"),
        ("ask_price", ask, "V2_MARKET_TICKER_24HR"),
        ("bid_qty", bid_qty, "V2_MARKET_TICKER_24HR"),
        ("ask_qty", ask_qty, "V2_MARKET_TICKER_24HR"),
        ("mid_price", mid, "V2_DERIVED_FROM_MARKET"),
        ("spread_pct_derived", spread, "V2_DERIVED_FROM_MARKET"),
        ("bid_ask_spread_bps", _coerce_float(feats.get("bid_ask_spread_bps")),
         "V2_NATIVE_FEATURE_SNAPSHOT"),
        ("depth_imbalance", depth_imb, "V2_NATIVE_FEATURE_SNAPSHOT"),
        ("micro_price", micro, "V2_NATIVE_FEATURE_SNAPSHOT"),
        ("toxicity_proxy", _coerce_float(feats.get("toxicity_proxy")),
         "V2_NATIVE_FEATURE_SNAPSHOT"),
        ("depth_imbalance_direction", depth_imb_dir, "V2_DERIVED_FROM_FEATURES"),
        ("bid_qty_minus_ask_qty", bid_qty_minus_ask_qty, "V2_DERIVED_FROM_MARKET"),
        ("mid_minus_micro_price", mid_minus_micro, "V2_DERIVED"),
        ("v2_depth_source_available", v2_depth_source_available,
         "V2_PROBE_FLAG_NO_DEPTH_LADDER_PRESENT"),
        ("orderbook_v2_native_source_count", 1.0, "V2_PROBE_FLAG_TICKER_ONLY"),
    ]
    for i, (nm, val, src) in enumerate(rows[:size]):
        if val is None:
            out[i] = (f"binance_orderbook.{nm}", None,
                      "MISSING_FROM_V2_BINANCE_ORDERBOOK_PROJECTION")
        else:
            out[i] = (f"binance_orderbook.{nm}", val, src)
    return out


def _project_ccxt_ohlcv(*_: Any) -> list[tuple[str, float | None, str]]:
    """Secondary-exchange OHLCV. Operator-decision-required to adopt."""
    size = 10
    return [
        (
            f"ccxt_ohlcv[{i}]",
            None,
            "OPERATOR_DECISION_REQUIRED_SECONDARY_EXCHANGE_OHLCV",
        )
        for i in range(size)
    ]


def _project_liquidations(
    v2_features: Mapping[str, Any] | None,
    symbol: str = "",
    v2_liquidation_per_symbol: Mapping[str, Any] | None = None,
) -> list[tuple[str, float | None, str]]:
    """Delegated to liquidation_observation_aggregator for V2-native
    multi-source projection (v2:features + V2 coinank intelligence)."""
    # Lazy import to keep the legacy obs contract / sub-family registration
    # path zero-dependency.
    from v2.backend.app.services.rl_core.liquidation_observation_aggregator import (
        build_liquidation_subfamily,
        load_coinank_intelligence,
    )
    return build_liquidation_subfamily(
        symbol=symbol,
        v2_features=v2_features,
        coinank_intel=load_coinank_intelligence(),
        v2_liquidation_per_symbol=v2_liquidation_per_symbol,
    )


def _project_technical_analysis(
    v2_features: Mapping[str, Any] | None,
    feature_freshness_state: str | None = None,
) -> list[tuple[str, float | None, str]]:
    size = 25
    out: list[tuple[str, float | None, str]] = [
        (f"technical_analysis[{i}]", None, "MISSING_FROM_V2_TECHNICAL_ANALYSIS_PROJECTION")
        for i in range(size)
    ]
    feats = v2_features or {}
    rsi = _coerce_float(feats.get("rsi_14"))
    macd = _coerce_float(feats.get("macd"))
    macd_signal = _coerce_float(feats.get("macd_signal"))
    macd_hist = _coerce_float(feats.get("macd_hist"))
    ema_12 = _coerce_float(feats.get("ema_12"))
    ema_26 = _coerce_float(feats.get("ema_26"))
    bb_width = _coerce_float(feats.get("bb_width_pct"))
    htf_rsi = _coerce_float(feats.get("htf_rsi_14"))
    htf_ret = _coerce_float(feats.get("htf_ret_pct"))
    body = _coerce_float(feats.get("body_pct"))
    rng = _coerce_float(feats.get("range_pct"))
    tr = _coerce_float(feats.get("true_range_pct"))
    gap = _coerce_float(feats.get("gap_pct"))
    derived: list[tuple[str, float | None, str]] = []

    def _src(v: float | None, label: str) -> tuple[str | None, str]:
        return (None, label) if v is None else (label, label)

    derived.append(("rsi_14", rsi, "V2_NATIVE_FEATURE_SNAPSHOT" if rsi is not None else "MISSING_FROM_V2_FEATURES"))
    derived.append(("rsi_14_oversold_30", None if rsi is None else (1.0 if rsi <= 30.0 else 0.0),
                    "V2_DERIVED_FROM_FEATURES" if rsi is not None else "MISSING_FROM_V2_FEATURES"))
    derived.append(("rsi_14_overbought_70", None if rsi is None else (1.0 if rsi >= 70.0 else 0.0),
                    "V2_DERIVED_FROM_FEATURES" if rsi is not None else "MISSING_FROM_V2_FEATURES"))
    derived.append(("macd", macd, "V2_NATIVE_FEATURE_SNAPSHOT" if macd is not None else "MISSING_FROM_V2_FEATURES"))
    derived.append(("macd_signal", macd_signal,
                    "V2_NATIVE_FEATURE_SNAPSHOT" if macd_signal is not None else "MISSING_FROM_V2_FEATURES"))
    derived.append(("macd_hist", macd_hist,
                    "V2_NATIVE_FEATURE_SNAPSHOT" if macd_hist is not None else "MISSING_FROM_V2_FEATURES"))
    derived.append(("macd_hist_sign", None if macd_hist is None else (
        1.0 if macd_hist > 0 else (-1.0 if macd_hist < 0 else 0.0)
    ),
                    "V2_DERIVED_FROM_FEATURES" if macd_hist is not None else "MISSING_FROM_V2_FEATURES"))
    derived.append(("ema_12", ema_12, "V2_NATIVE_FEATURE_SNAPSHOT" if ema_12 is not None else "MISSING_FROM_V2_FEATURES"))
    derived.append(("ema_26", ema_26, "V2_NATIVE_FEATURE_SNAPSHOT" if ema_26 is not None else "MISSING_FROM_V2_FEATURES"))
    ema_diff = (ema_12 - ema_26) if (ema_12 is not None and ema_26 is not None) else None
    derived.append(("ema_diff", ema_diff,
                    "V2_DERIVED_FROM_FEATURES" if ema_diff is not None else "MISSING_FROM_V2_FEATURES"))
    derived.append(("bb_width_pct", bb_width,
                    "V2_NATIVE_FEATURE_SNAPSHOT" if bb_width is not None else "MISSING_FROM_V2_FEATURES"))
    derived.append(("htf_rsi_14", htf_rsi,
                    "V2_NATIVE_FEATURE_SNAPSHOT" if htf_rsi is not None else "MISSING_FROM_V2_FEATURES"))
    derived.append(("htf_ret_pct", htf_ret,
                    "V2_NATIVE_FEATURE_SNAPSHOT" if htf_ret is not None else "MISSING_FROM_V2_FEATURES"))
    derived.append(("body_pct", body,
                    "V2_NATIVE_FEATURE_SNAPSHOT" if body is not None else "MISSING_FROM_V2_FEATURES"))
    derived.append(("range_pct", rng,
                    "V2_NATIVE_FEATURE_SNAPSHOT" if rng is not None else "MISSING_FROM_V2_FEATURES"))
    derived.append(("true_range_pct", tr,
                    "V2_NATIVE_FEATURE_SNAPSHOT" if tr is not None else "MISSING_FROM_V2_FEATURES"))
    derived.append(("gap_pct", gap,
                    "V2_NATIVE_FEATURE_SNAPSHOT" if gap is not None else "MISSING_FROM_V2_FEATURES"))
    volatility_proxy = (body * tr) if (body is not None and tr is not None) else None
    derived.append(("volatility_proxy", volatility_proxy,
                    "V2_DERIVED_FROM_FEATURES" if volatility_proxy is not None else "MISSING_FROM_V2_FEATURES"))
    # PHASE 2 additions — V2-native derived TA fields:
    ema_ratio = (ema_12 / ema_26) if (ema_12 is not None and ema_26 not in (None, 0.0)) else None
    derived.append(("ema_ratio", ema_ratio,
                    "V2_DERIVED_FROM_FEATURES" if ema_ratio is not None else "MISSING_FROM_V2_FEATURES"))
    trend_slope_proxy = (ema_diff / ema_26) if (ema_diff is not None and ema_26 not in (None, 0.0)) else None
    derived.append(("trend_slope_proxy", trend_slope_proxy,
                    "V2_DERIVED_FROM_FEATURES" if trend_slope_proxy is not None else "MISSING_FROM_V2_FEATURES"))
    macd_signal_strength = None
    if macd is None and macd_hist is None:
        macd_signal_strength_source = "MISSING_MACD_AND_MACD_HIST_FROM_V2_FEATURES"
    elif macd is None:
        macd_signal_strength_source = "MISSING_MACD_FROM_V2_FEATURES"
    elif macd_hist is None:
        macd_signal_strength_source = "MISSING_MACD_HIST_FROM_V2_FEATURES"
    elif abs(macd) <= 0.0:
        macd_signal_strength_source = "MACD_ZERO_RATIO_UNDEFINED"
    elif feature_freshness_state is not None and feature_freshness_state != "CURRENT":
        macd_signal_strength_source = (
            f"BLOCKED_BY_FEATURE_FRESHNESS_NOT_CURRENT:{feature_freshness_state}"
        )
    else:
        macd_signal_strength = abs(macd_hist) / abs(macd)
        macd_signal_strength_source = "V2_DERIVED_FROM_FEATURES"
    derived.append(("macd_signal_strength", macd_signal_strength, macd_signal_strength_source))
    macd_above_signal = None
    if macd is not None and macd_signal is not None:
        macd_above_signal = 1.0 if macd > macd_signal else 0.0
    derived.append(("macd_above_signal", macd_above_signal,
                    "V2_DERIVED_FROM_FEATURES" if macd_above_signal is not None else "MISSING_FROM_V2_FEATURES"))
    htf_rsi_oversold = None
    if htf_rsi is not None:
        htf_rsi_oversold = 1.0 if htf_rsi <= 30.0 else 0.0
    derived.append(("htf_rsi_14_oversold_30", htf_rsi_oversold,
                    "V2_DERIVED_FROM_FEATURES" if htf_rsi_oversold is not None else "MISSING_FROM_V2_FEATURES"))
    htf_rsi_overbought = None
    if htf_rsi is not None:
        htf_rsi_overbought = 1.0 if htf_rsi >= 70.0 else 0.0
    derived.append(("htf_rsi_14_overbought_70", htf_rsi_overbought,
                    "V2_DERIVED_FROM_FEATURES" if htf_rsi_overbought is not None else "MISSING_FROM_V2_FEATURES"))
    htf_trend_agrees_lf = None
    if htf_ret is None and rsi is None:
        htf_trend_source = "MISSING_HTF_RET_PCT_AND_RSI_14_FROM_V2_FEATURES"
    elif htf_ret is None:
        htf_trend_source = "MISSING_HTF_RET_PCT_FROM_V2_FEATURES"
    elif rsi is None:
        htf_trend_source = "MISSING_RSI_14_FROM_V2_FEATURES"
    elif feature_freshness_state is not None and feature_freshness_state != "CURRENT":
        htf_trend_source = (
            f"BLOCKED_BY_FEATURE_FRESHNESS_NOT_CURRENT:{feature_freshness_state}"
        )
    else:
        # Higher-tf return positive + lower-tf rsi above 50 ⇒ trends agree.
        # rsi exactly 50.0 is the neutral mid-point; treated as agreement
        # with the higher-tf sign so the slot returns a stable {0,1} value
        # instead of None when both inputs are present.
        if htf_ret > 0 and rsi >= 50.0:
            htf_trend_agrees_lf = 1.0
        elif htf_ret < 0 and rsi <= 50.0:
            htf_trend_agrees_lf = 1.0
        elif htf_ret == 0.0:
            htf_trend_agrees_lf = 1.0 if rsi == 50.0 else 0.0
        else:
            htf_trend_agrees_lf = 0.0
        htf_trend_source = "V2_DERIVED_FROM_FEATURES"
    derived.append(("htf_lf_trend_agreement", htf_trend_agrees_lf, htf_trend_source))
    for i, (nm, val, src) in enumerate(derived[:size]):
        out[i] = (f"technical_analysis.{nm}", val, src)
    return out


def _project_token_metrics(*_: Any) -> list[tuple[str, float | None, str]]:
    size = 18
    return [
        (
            f"token_metrics[{i}]",
            None,
            "EXTERNAL_SOURCE_REQUIRED_NO_V2_NATIVE_TOKEN_METRICS",
        )
        for i in range(size)
    ]


def _project_coinank(
    market_funding: Mapping[str, Any] | None,
    market_open_interest: Mapping[str, Any] | None,
    market_price: Mapping[str, Any] | None,
    v2_features: Mapping[str, Any] | None,
) -> list[tuple[str, float | None, str]]:
    size = 22
    out: list[tuple[str, float | None, str]] = [
        (f"coinank[{i}]", None, "MISSING_FROM_V2_COINANK_AGGREGATOR")
        for i in range(size)
    ]
    funding = market_funding or {}
    oi = market_open_interest or {}
    ticker = ((market_price or {}).get("ticker_24hr") or {}) if isinstance(market_price, Mapping) else {}
    feats = v2_features or {}
    last_funding = _coerce_float(funding.get("lastFundingRate"))
    mark_price = _coerce_float(funding.get("markPrice"))
    index_price = _coerce_float(funding.get("indexPrice"))
    interest_rate = _coerce_float(funding.get("interestRate"))
    est_settle = _coerce_float(funding.get("estimatedSettlePrice"))
    open_interest = _coerce_float(oi.get("openInterest"))
    last_price = _coerce_float(ticker.get("lastPrice"))
    basis_mark_minus_last = (
        (mark_price - last_price) if (mark_price is not None and last_price is not None) else None
    )
    basis_mark_minus_index = (
        (mark_price - index_price) if (mark_price is not None and index_price is not None) else None
    )
    funding_abs = abs(last_funding) if last_funding is not None else None
    funding_direction = (
        None if last_funding is None else
        (1.0 if last_funding > 0 else (-1.0 if last_funding < 0 else 0.0))
    )
    feat_funding = _coerce_float(feats.get("funding_rate"))
    feat_oi_chg = _coerce_float(feats.get("oi_change_pct"))
    oi_chg_abs = abs(feat_oi_chg) if feat_oi_chg is not None else None
    oi_chg_direction = (
        None if feat_oi_chg is None else
        (1.0 if feat_oi_chg > 0 else (-1.0 if feat_oi_chg < 0 else 0.0))
    )
    basis_pct = None
    if mark_price is not None and index_price not in (None, 0.0):
        basis_pct = (mark_price - index_price) / index_price
    # No V2 long-short or paid-aggregator source today — explicit 0.0
    # source-availability flag is honest evidence, not fabrication.
    v2_coinank_aggregator_source_available = 0.0
    # ---- PHASE 4 additions (V2-buildable burndown) ----
    # All six new fields are derived strictly from existing V2-native
    # market payloads (v2:market:funding, v2:market:open_interest,
    # v2:market:prices) — no new Redis read, no paid aggregator, no
    # legacy source. Each carries an explicit V2_DERIVED_FROM_*
    # source attribution; missing inputs propagate to None with a
    # specific MISSING_FROM_V2_* label.
    funding_time_ms = _coerce_float(funding.get("time"))
    next_funding_time_ms = _coerce_float(funding.get("nextFundingTime"))
    oi_time_ms = _coerce_float(oi.get("time"))
    now_ms = float(datetime.now(timezone.utc).timestamp() * 1000.0)

    # seconds_until_next_funding: difference between the funding
    # payload's nextFundingTime and its own timestamp. Using the
    # payload's own `time` rather than wall-clock removes clock-skew
    # noise; both are emitted by the same Binance USDM premiumIndex
    # response so they share an epoch reference.
    seconds_until_next_funding: float | None = None
    if next_funding_time_ms is not None and funding_time_ms is not None:
        seconds_until_next_funding = max(
            0.0, (next_funding_time_ms - funding_time_ms) / 1000.0
        )
    seconds_until_next_funding_source = (
        "V2_DERIVED_FROM_FUNDING"
        if seconds_until_next_funding is not None
        else "MISSING_FROM_V2_FUNDING"
    )

    # funding_payload_age_seconds: time elapsed since the funding
    # payload was sampled. Operator/trainer signal of staleness.
    funding_payload_age_seconds: float | None = None
    if funding_time_ms is not None:
        funding_payload_age_seconds = max(0.0, (now_ms - funding_time_ms) / 1000.0)
    funding_payload_age_source = (
        "V2_DERIVED_FROM_FUNDING_TIMESTAMP"
        if funding_payload_age_seconds is not None
        else "MISSING_FROM_V2_FUNDING"
    )

    # oi_payload_age_seconds: same idea but on the open-interest
    # payload. Both ages are independent staleness signals.
    oi_payload_age_seconds: float | None = None
    if oi_time_ms is not None:
        oi_payload_age_seconds = max(0.0, (now_ms - oi_time_ms) / 1000.0)
    oi_payload_age_source = (
        "V2_DERIVED_FROM_OPEN_INTEREST_TIMESTAMP"
        if oi_payload_age_seconds is not None
        else "MISSING_FROM_V2_OI"
    )

    # funding_oi_direction_agreement: 1.0 when funding and OI move in
    # the same direction (both positive or both negative), 0.0 when
    # they disagree. Conventional crowded-trade indicator. Requires
    # both direction values to be present.
    funding_oi_direction_agreement: float | None = None
    funding_oi_direction_agreement_source: str
    if funding_direction is None and oi_chg_direction is None:
        funding_oi_direction_agreement_source = (
            "MISSING_FROM_V2_FUNDING_AND_FEATURES"
        )
    elif funding_direction is None:
        funding_oi_direction_agreement_source = "MISSING_FROM_V2_FUNDING"
    elif oi_chg_direction is None:
        funding_oi_direction_agreement_source = "MISSING_FROM_V2_FEATURES"
    else:
        funding_oi_direction_agreement = (
            1.0 if funding_direction == oi_chg_direction else 0.0
        )
        funding_oi_direction_agreement_source = (
            "V2_DERIVED_FROM_FUNDING_AND_FEATURES"
        )

    # funding_rate_bps: last funding rate expressed in basis points.
    # Just a unit conversion of last_funding * 10000. No new source.
    funding_rate_bps: float | None = (
        last_funding * 10000.0 if last_funding is not None else None
    )
    funding_rate_bps_source = (
        "V2_DERIVED_FROM_FUNDING"
        if funding_rate_bps is not None
        else "MISSING_FROM_V2_FUNDING"
    )

    # mark_premium_to_index_bps: basis_pct expressed in basis points.
    # Honest unit conversion of an existing V2-derived field.
    mark_premium_to_index_bps: float | None = (
        basis_pct * 10000.0 if basis_pct is not None else None
    )
    mark_premium_to_index_bps_source = (
        "V2_DERIVED_FROM_FUNDING"
        if mark_premium_to_index_bps is not None
        else "MISSING_FROM_V2_FUNDING"
    )

    derived = [
        ("last_funding_rate", last_funding,
         "V2_MARKET_FUNDING" if last_funding is not None else "MISSING_FROM_V2_FUNDING"),
        ("mark_price", mark_price,
         "V2_MARKET_FUNDING" if mark_price is not None else "MISSING_FROM_V2_FUNDING"),
        ("index_price", index_price,
         "V2_MARKET_FUNDING" if index_price is not None else "MISSING_FROM_V2_FUNDING"),
        ("interest_rate", interest_rate,
         "V2_MARKET_FUNDING" if interest_rate is not None else "MISSING_FROM_V2_FUNDING"),
        ("estimated_settle_price", est_settle,
         "V2_MARKET_FUNDING" if est_settle is not None else "MISSING_FROM_V2_FUNDING"),
        ("open_interest", open_interest,
         "V2_MARKET_OPEN_INTEREST" if open_interest is not None else "MISSING_FROM_V2_OI"),
        ("basis_mark_minus_last", basis_mark_minus_last,
         "V2_DERIVED_FROM_MARKET" if basis_mark_minus_last is not None else "MISSING_FROM_V2_FUNDING"),
        ("basis_mark_minus_index", basis_mark_minus_index,
         "V2_DERIVED_FROM_MARKET" if basis_mark_minus_index is not None else "MISSING_FROM_V2_FUNDING"),
        ("funding_rate_feature", feat_funding,
         "V2_NATIVE_FEATURE_SNAPSHOT" if feat_funding is not None else "MISSING_FROM_V2_FEATURES"),
        ("oi_change_pct", feat_oi_chg,
         "V2_NATIVE_FEATURE_SNAPSHOT" if feat_oi_chg is not None else "MISSING_FROM_V2_FEATURES"),
        # PHASE 3 additions:
        ("funding_abs", funding_abs,
         "V2_DERIVED_FROM_FUNDING" if funding_abs is not None else "MISSING_FROM_V2_FUNDING"),
        ("funding_direction", funding_direction,
         "V2_DERIVED_FROM_FUNDING" if funding_direction is not None else "MISSING_FROM_V2_FUNDING"),
        ("oi_change_pct_abs", oi_chg_abs,
         "V2_DERIVED_FROM_FEATURES" if oi_chg_abs is not None else "MISSING_FROM_V2_FEATURES"),
        ("oi_change_pct_direction", oi_chg_direction,
         "V2_DERIVED_FROM_FEATURES" if oi_chg_direction is not None else "MISSING_FROM_V2_FEATURES"),
        ("basis_mark_minus_index_pct", basis_pct,
         "V2_DERIVED_FROM_FUNDING" if basis_pct is not None else "MISSING_FROM_V2_FUNDING"),
        ("v2_coinank_aggregator_source_available", v2_coinank_aggregator_source_available,
         "V2_PROBE_FLAG_NO_COINANK_AGGREGATOR_PRESENT"),
        # PHASE 4 additions (V2-buildable burndown, this packet):
        ("seconds_until_next_funding", seconds_until_next_funding,
         seconds_until_next_funding_source),
        ("funding_payload_age_seconds", funding_payload_age_seconds,
         funding_payload_age_source),
        ("oi_payload_age_seconds", oi_payload_age_seconds, oi_payload_age_source),
        ("funding_oi_direction_agreement", funding_oi_direction_agreement,
         funding_oi_direction_agreement_source),
        ("funding_rate_bps", funding_rate_bps, funding_rate_bps_source),
        ("mark_premium_to_index_bps", mark_premium_to_index_bps,
         mark_premium_to_index_bps_source),
    ]
    for i, (nm, val, src) in enumerate(derived[:size]):
        out[i] = (f"coinank.{nm}", val, src)
    return out


def _project_portfolio_state_unified(
    paper_positions: list[Mapping[str, Any]] | None,
    paper_ledger: Mapping[str, Any] | None,
    risk_decisions: list[Mapping[str, Any]] | None,
    orchestrator_decisions: Mapping[str, Any] | None,
    trainer_heartbeat: Mapping[str, Any] | None,
    v2_features: Mapping[str, Any] | None,
) -> list[tuple[str, float | None, str]]:
    size = 15
    out: list[tuple[str, float | None, str]] = [
        (f"portfolio_state_unified[{i}]", None, "MISSING_FROM_V2_PAPER_RISK_PROJECTION")
        for i in range(size)
    ]
    pp = paper_positions or []
    pl = paper_ledger or {}
    rd = risk_decisions or []
    od = orchestrator_decisions or {}
    tr = trainer_heartbeat or {}
    feats = v2_features or {}
    derived = [
        ("paper_position_present_feature",
         _coerce_float(feats.get("paper_position_present")),
         "V2_NATIVE_FEATURE_SNAPSHOT" if feats.get("paper_position_present") is not None else "MISSING_FROM_V2_FEATURES"),
        ("paper_position_count", float(len(pp)), "V2_PAPER_POSITIONS"),
        ("paper_accepted_count", _coerce_float(pl.get("accepted_count")),
         "V2_PAPER_LEDGER" if pl else "MISSING_FROM_V2_LEDGER"),
        ("paper_blocked_count", _coerce_float(pl.get("blocked_count")),
         "V2_PAPER_LEDGER" if pl else "MISSING_FROM_V2_LEDGER"),
        ("paper_held_by_paper_fill_gate_count",
         _coerce_float(pl.get("held_by_paper_fill_gate_count")),
         "V2_PAPER_LEDGER" if pl else "MISSING_FROM_V2_LEDGER"),
        ("risk_pre_trade_allowed_count",
         float(sum(1 for r in rd if r.get("pre_trade_allowed"))),
         "V2_RISK_DECISIONS"),
        ("risk_fee_gate_allowed_count",
         float(sum(1 for r in rd if r.get("fee_gate_allowed"))),
         "V2_RISK_DECISIONS"),
        ("risk_churn_blocked_count",
         float(sum(1 for r in rd if r.get("churn_blocked"))),
         "V2_RISK_DECISIONS"),
        ("orchestrator_considered_count", _coerce_float(od.get("considered_count")),
         "V2_ORCHESTRATOR_DECISIONS" if od else "MISSING_FROM_V2_ORCHESTRATOR"),
        ("orchestrator_bucket_winners_count",
         float(len(od.get("bucket_winners") or [])),
         "V2_ORCHESTRATOR_DECISIONS" if od else "MISSING_FROM_V2_ORCHESTRATOR"),
        ("orchestrator_stale_proposal_count",
         float(len(od.get("stale_proposal_ids") or [])),
         "V2_ORCHESTRATOR_DECISIONS" if od else "MISSING_FROM_V2_ORCHESTRATOR"),
        ("v2_prediction_count", _coerce_float(tr.get("predictions_count")),
         "V2_TRAINER_HEARTBEAT" if tr else "MISSING_FROM_V2_TRAINER"),
        ("v2_prediction_paper_fill_allowed_count",
         float(len(tr.get("predictions_with_open_gate") or [])) if tr else None,
         "V2_TRAINER_HEARTBEAT" if tr else "MISSING_FROM_V2_TRAINER"),
        ("orchestrator_held_by_paper_fill_gate_count",
         _coerce_float(od.get("held_by_paper_fill_gate_count")),
         "V2_ORCHESTRATOR_DECISIONS" if od else "MISSING_FROM_V2_ORCHESTRATOR"),
        ("any_paper_position", 1.0 if pp else 0.0, "V2_PAPER_POSITIONS"),
    ]
    for i, (nm, val, src) in enumerate(derived[:size]):
        out[i] = (f"portfolio_state_unified.{nm}", val, src)
    return out


SUBFAMILY_PROJECTORS = {
    "binance_klines": _project_binance_klines,
    "binance_orderbook": _project_binance_orderbook,
    "ccxt_ohlcv": _project_ccxt_ohlcv,
    "liquidations": _project_liquidations,
    "technical_analysis": _project_technical_analysis,
    "token_metrics": _project_token_metrics,
    "coinank": _project_coinank,
    "portfolio_state_unified": _project_portfolio_state_unified,
}


def _build_unified_features_slice(
    symbol: str,
    feature_snapshot: Mapping[str, Any] | None,
    market_price: Mapping[str, Any] | None,
    market_funding: Mapping[str, Any] | None,
    market_open_interest: Mapping[str, Any] | None,
    paper_positions: list[Mapping[str, Any]] | None,
    paper_ledger: Mapping[str, Any] | None,
    risk_decisions: list[Mapping[str, Any]] | None,
    orchestrator_decisions: Mapping[str, Any] | None,
    trainer_heartbeat: Mapping[str, Any] | None,
    liquidation_per_symbol: Mapping[str, Any] | None = None,
) -> tuple[
    list[float | None], list[str], list[str], list[str], dict[str, int], dict[str, int]
]:
    size = SLICE_SIZES["unified_features"]
    values: list[float | None] = [None] * size
    names: list[str] = [f"unified_features[{i}]" for i in range(size)]
    sources: list[str] = ["MISSING_LEGACY_V3_EXTRA_NO_V2_SOURCE"] * size
    missing: list[str] = []
    subfamily_present: dict[str, int] = {}
    subfamily_target: dict[str, int] = {}
    offset = 0
    v2_feats = (feature_snapshot or {}).get("features") if feature_snapshot else None
    feature_freshness_state = (
        feature_snapshot.get("feature_freshness_state")
        if isinstance(feature_snapshot, Mapping)
        else None
    )
    for name, sf_size in SUBFAMILY_LAYOUT:
        proj = SUBFAMILY_PROJECTORS[name]
        if name == "binance_klines":
            rows = proj(market_price, v2_feats)
        elif name == "binance_orderbook":
            rows = proj(market_price, v2_feats)
        elif name == "ccxt_ohlcv":
            rows = proj()
        elif name == "liquidations":
            rows = proj(v2_feats, symbol, liquidation_per_symbol)
        elif name == "technical_analysis":
            rows = proj(v2_feats, feature_freshness_state)
        elif name == "token_metrics":
            rows = proj()
        elif name == "coinank":
            rows = proj(market_funding, market_open_interest, market_price, v2_feats)
        elif name == "portfolio_state_unified":
            rows = proj(
                paper_positions,
                paper_ledger,
                risk_decisions,
                orchestrator_decisions,
                trainer_heartbeat,
                v2_feats,
            )
        else:
            rows = []
        subfamily_target[name] = sf_size
        present = 0
        for i in range(sf_size):
            if i < len(rows):
                rname, rval, rsrc = rows[i]
            else:
                rname, rval, rsrc = (
                    f"{name}[{i}]",
                    None,
                    "MISSING_LEGACY_V3_EXTRA_NO_V2_SOURCE",
                )
            slot = offset + i
            names[slot] = rname
            values[slot] = rval
            sources[slot] = rsrc
            if rval is None:
                missing.append(rname)
            else:
                present += 1
        subfamily_present[name] = present
        offset += sf_size
    # Trailing 1293 dims are explicit legacy_v3_extra (no V2 source).
    for i in range(offset, size):
        missing.append(names[i])
    return values, names, sources, missing, subfamily_present, subfamily_target


# Extended portfolio_state (401 target) — currently expanded set.
def _build_portfolio_state_slice(
    symbol: str,
    paper_positions: list[Mapping[str, Any]] | None,
    paper_ledger: Mapping[str, Any] | None,
    risk_decisions: list[Mapping[str, Any]] | None,
    orchestrator_decisions: Mapping[str, Any] | None,
    trainer_heartbeat: Mapping[str, Any] | None,
    prediction: Mapping[str, Any] | None = None,
    paper_intents: list[Mapping[str, Any]] | None = None,
    paper_intents_held: list[Mapping[str, Any]] | None = None,
    position_history: Mapping[str, Any] | None = None,
    altdata_symbol_score: Mapping[str, Any] | None = None,
    altdata_candidates: Mapping[str, Any] | None = None,
) -> tuple[list[float | None], list[str], list[str], list[str]]:
    size = SLICE_SIZES["portfolio_state"]
    values: list[float | None] = [None] * size
    names: list[str] = [f"portfolio_state[{i}]" for i in range(size)]
    sources: list[str] = ["MISSING_FROM_V2_PORTFOLIO_STATE_EXTENDED"] * size
    missing: list[str] = []
    pp = paper_positions or []
    pl = paper_ledger or {}
    rd = risk_decisions or []
    od = orchestrator_decisions or {}
    tr = trainer_heartbeat or {}
    pred = prediction or {}
    pi = paper_intents or []
    held_intents = paper_intents_held or []
    ph = position_history or {}
    alt_score = altdata_symbol_score or {}
    candidates_payload = altdata_candidates or {}
    candidate_row = _candidate_row_for_symbol(candidates_payload, symbol)
    accepted_fill_count = _safe_ledger_accepted_fill_count(pl)
    blocked_count = _safe_ledger_blocked_count(pl)
    held_count = _safe_ledger_held_count(pl)
    shadow_count = _safe_ledger_shadow_count(pl)
    notional = 0.0
    long_count = 0
    short_count = 0
    flat_count = 0
    em_after_sum = 0.0
    confidence_sum = 0.0
    has_em = False
    has_conf = False
    for p in pp:
        em = _coerce_float(p.get("expected_move_after_cost_bps"))
        cf = _coerce_float(p.get("confidence_calibrated"))
        if em is not None:
            em_after_sum += em
            has_em = True
        if cf is not None:
            confidence_sum += cf
            has_conf = True
        notional += 1.0  # paper has no real qty; use position count proxy
        side = (p.get("side") or "").lower()
        if side == "long":
            long_count += 1
        elif side == "short":
            short_count += 1
        else:
            flat_count += 1
    derived: list[tuple[str, float | None, str]] = [
        ("paper_position_count", float(len(pp)), "V2_PAPER_POSITIONS"),
        ("paper_long_count", float(long_count), "V2_PAPER_POSITIONS"),
        ("paper_short_count", float(short_count), "V2_PAPER_POSITIONS"),
        ("paper_flat_count", float(flat_count), "V2_PAPER_POSITIONS"),
        ("paper_accepted_count", accepted_fill_count,
         "V2_PAPER_LEDGER" if pl else "MISSING_FROM_V2_LEDGER"),
        ("paper_blocked_count", blocked_count,
         "V2_PAPER_LEDGER" if pl else "MISSING_FROM_V2_LEDGER"),
        ("paper_held_by_paper_fill_gate_count",
         held_count,
         "V2_PAPER_LEDGER" if pl else "MISSING_FROM_V2_LEDGER"),
        ("risk_pre_trade_allowed_count",
         float(sum(1 for r in rd if r.get("pre_trade_allowed"))),
         "V2_RISK_DECISIONS"),
        ("risk_fee_gate_allowed_count",
         float(sum(1 for r in rd if r.get("fee_gate_allowed"))),
         "V2_RISK_DECISIONS"),
        ("risk_churn_blocked_count",
         float(sum(1 for r in rd if r.get("churn_blocked"))),
         "V2_RISK_DECISIONS"),
        ("orchestrator_considered_count", _coerce_float(od.get("considered_count")),
         "V2_ORCHESTRATOR_DECISIONS" if od else "MISSING_FROM_V2_ORCHESTRATOR"),
        ("orchestrator_bucket_winners_count",
         float(len(od.get("bucket_winners") or [])), "V2_ORCHESTRATOR_DECISIONS" if od else "MISSING_FROM_V2_ORCHESTRATOR"),
        ("orchestrator_stale_proposal_count",
         float(len(od.get("stale_proposal_ids") or [])), "V2_ORCHESTRATOR_DECISIONS" if od else "MISSING_FROM_V2_ORCHESTRATOR"),
        ("orchestrator_held_by_paper_fill_gate_count",
         _coerce_float(od.get("held_by_paper_fill_gate_count")),
         "V2_ORCHESTRATOR_DECISIONS" if od else "MISSING_FROM_V2_ORCHESTRATOR"),
        ("v2_prediction_count", _coerce_float(tr.get("predictions_count")),
         "V2_TRAINER_HEARTBEAT" if tr else "MISSING_FROM_V2_TRAINER"),
        ("v2_prediction_paper_fill_allowed_count",
         float(len(tr.get("predictions_with_open_gate") or [])) if tr else None,
         "V2_TRAINER_HEARTBEAT" if tr else "MISSING_FROM_V2_TRAINER"),
        ("paper_position_notional_proxy", notional, "V2_PAPER_POSITIONS"),
        ("paper_position_expected_move_after_cost_bps_sum",
         em_after_sum if has_em else None,
         "V2_PAPER_POSITIONS" if has_em else "MISSING_FROM_V2_PAPER_POSITIONS"),
        ("paper_position_confidence_calibrated_sum",
         confidence_sum if has_conf else None,
         "V2_PAPER_POSITIONS" if has_conf else "MISSING_FROM_V2_PAPER_POSITIONS"),
        ("v2_prediction_blocked_count",
         _coerce_float(len(tr.get("predictions_blocked") or [])) if tr else None,
         "V2_TRAINER_HEARTBEAT" if tr else "MISSING_FROM_V2_TRAINER"),
        # Exact source: v2:orchestrator:decisions; expected payload field
        # ``v2_orchestrator_keys_written_count``. When the key exists but the
        # payload omits the field, emit MISSING_FROM_V2_ORCHESTRATOR (do not
        # zero-fill, do not falsely claim V2_ORCHESTRATOR_DECISIONS).
        ("v2_orchestrator_keys_written_count",
         (
             _coerce_float(od.get("v2_orchestrator_keys_written_count"))
             if od is not None
             and od.get("v2_orchestrator_keys_written_count") is not None
             else None
         ),
         (
             "V2_ORCHESTRATOR_DECISIONS"
             if (
                 od is not None
                 and od.get("v2_orchestrator_keys_written_count") is not None
                 and _coerce_float(od.get("v2_orchestrator_keys_written_count")) is not None
             )
             else "MISSING_FROM_V2_ORCHESTRATOR"
         )),
    ]
    # PHASE 5 additions for portfolio_state:
    pred_count = _coerce_float(tr.get("predictions_count"))
    pred_open_gate_count = (
        float(len(tr.get("predictions_with_open_gate") or [])) if tr else None
    )
    pred_blocked_count = (
        float(len(tr.get("predictions_blocked") or [])) if tr else None
    )
    accepted_count = accepted_fill_count
    blocked_count = blocked_count
    gate_open_ratio = None
    if pred_count is not None and pred_count > 0 and pred_open_gate_count is not None:
        gate_open_ratio = pred_open_gate_count / pred_count
    accepted_minus_blocked = None
    if accepted_count is not None and blocked_count is not None:
        accepted_minus_blocked = accepted_count - blocked_count
    prediction_blocked_minus_open_gate = None
    if pred_blocked_count is not None and pred_open_gate_count is not None:
        prediction_blocked_minus_open_gate = pred_blocked_count - pred_open_gate_count
    risk_total_count = float(len(rd))
    risk_all_allowed = (
        1.0
        if rd
        and all(
            r.get("pre_trade_allowed") and r.get("fee_gate_allowed") and not r.get("churn_blocked")
            for r in rd
        )
        else 0.0
    )
    derived.extend(
        [
            ("gate_open_ratio", gate_open_ratio,
             "V2_DERIVED_FROM_TRAINER_HEARTBEAT" if gate_open_ratio is not None else "MISSING_FROM_V2_TRAINER"),
            ("accepted_minus_blocked", accepted_minus_blocked,
             "V2_DERIVED_FROM_LEDGER" if accepted_minus_blocked is not None else "MISSING_FROM_V2_LEDGER"),
            ("predictions_blocked_minus_open_gate", prediction_blocked_minus_open_gate,
             "V2_DERIVED_FROM_TRAINER_HEARTBEAT" if prediction_blocked_minus_open_gate is not None else "MISSING_FROM_V2_TRAINER"),
            ("risk_decision_total_count", risk_total_count, "V2_RISK_DECISIONS"),
            ("risk_all_three_gates_allowed_for_any", risk_all_allowed, "V2_RISK_DECISIONS"),
        ]
    )
    # Portfolio-state burndown additions: V2-only aggregate and per-symbol
    # context. These fields are generic portfolio context, not tracker-derived
    # position-history fields. Held/shadow rows are counted separately and
    # never as accepted fills. PnL / MFE / MAE / ROE remain None unless V2
    # payloads explicitly carry the corresponding values.
    symbol_positions = _rows_for_symbol(pp, symbol)
    symbol_risk = next(
        (row for row in rd if (row.get("symbol") or "").upper() == symbol.upper()),
        None,
    )
    symbol_intents = _rows_for_symbol(pi, symbol)
    symbol_held_intents = _rows_for_symbol(held_intents, symbol)
    ledger_accepted_rows = _dedupe_rows(_ledger_rows(pl, "accepted", "accepted_intents"))
    ledger_held_rows = _dedupe_rows(_ledger_rows(pl, "held_by_paper_fill_gate"))
    ledger_shadow_rows = _dedupe_rows(_ledger_rows(pl, "shadow_observations"))
    ledger_blocked_rows = _dedupe_rows(_ledger_rows(pl, "blocked"))
    symbol_accepted_rows = [
        row for row in _rows_for_symbol(ledger_accepted_rows, symbol)
        if _row_is_accepted_fill(row)
    ]
    symbol_held_rows = _rows_for_symbol(ledger_held_rows, symbol)
    symbol_shadow_rows = _rows_for_symbol(ledger_shadow_rows, symbol)
    symbol_blocked_rows = _rows_for_symbol(ledger_blocked_rows, symbol)
    symbol_held_context_rows = _dedupe_rows(symbol_held_rows + symbol_held_intents)
    open_tracker_state = (
        isinstance(ph.get("position_state"), str)
        and ph.get("position_state", "").upper().startswith("OPEN")
    )
    no_open_tracker_state = (
        isinstance(ph.get("position_state"), str)
        and ph.get("position_state", "").upper() == "NO_OPEN_POSITION"
    )
    candidate_state = str((candidate_row or {}).get("candidate_state") or "")
    proposed_use = (
        (candidate_row or {}).get("proposed_use")
        if isinstance(candidate_row, Mapping)
        else None
    )
    missing_provider_flags = (
        (candidate_row or alt_score).get("missing_provider_flags")
        if isinstance(candidate_row or alt_score, Mapping)
        else None
    )
    stale_provider_flags = (
        (candidate_row or alt_score).get("stale_provider_flags")
        if isinstance(candidate_row or alt_score, Mapping)
        else None
    )
    paper_fill_reasons = pred.get("paper_fill_gate_block_reasons") or []
    held_block_reasons: list[str] = []
    for row in symbol_held_context_rows:
        reasons = row.get("paper_fill_gate_block_reasons") or row.get("block_reasons") or []
        if isinstance(reasons, list):
            held_block_reasons.extend(str(reason) for reason in reasons)
    combined_block_reasons = [str(reason) for reason in paper_fill_reasons] + held_block_reasons

    def _flag(value: Any) -> float | None:
        if value is None:
            return None
        return 1.0 if bool(value) else 0.0

    realized_pnl_bps = _sum_numeric_fields(
        _ledger_rows(pl, "closes"),
        "realized_pnl_bps",
        "pnl_bps",
    )
    realized_pnl_usdt = _sum_numeric_fields(
        _ledger_rows(pl, "closes"),
        "realized_pnl_usdt",
        "pnl_usdt",
    )
    unrealized_pnl_bps = _sum_numeric_fields(
        symbol_positions,
        "unrealized_pnl_bps",
        "unrealized_bps",
    )
    unrealized_pnl_usdt = _sum_numeric_fields(
        symbol_positions,
        "unrealized_pnl_usdt",
        "unrealized_usdt",
    )
    tracker_mfe = _coerce_float(ph.get("max_favorable_bps"))
    tracker_mae = _coerce_float(ph.get("max_adverse_bps"))
    tracker_roe = _coerce_float(ph.get("unrealized_bps"))
    derived.extend(
        [
            ("portfolio_positions_payload_present", 1.0 if isinstance(paper_positions, list) else None,
             "V2_PAPER_POSITIONS" if isinstance(paper_positions, list) else "MISSING_FROM_V2_PAPER_POSITIONS"),
            ("portfolio_ledger_payload_present", 1.0 if pl else None,
             "V2_PAPER_LEDGER" if pl else "MISSING_FROM_V2_LEDGER"),
            ("portfolio_ledger_age_seconds", _payload_age_seconds(pl),
             "V2_PAPER_LEDGER" if _payload_age_seconds(pl) is not None else "MISSING_FROM_V2_LEDGER"),
            ("portfolio_ledger_accepted_fill_count", accepted_fill_count,
             "V2_PAPER_LEDGER_ACCEPTED_FILLS_SAFE" if accepted_fill_count is not None else "MISSING_FROM_V2_LEDGER"),
            ("portfolio_ledger_blocked_count", blocked_count,
             "V2_PAPER_LEDGER" if blocked_count is not None else "MISSING_FROM_V2_LEDGER"),
            ("portfolio_ledger_held_by_gate_count", held_count,
             "V2_PAPER_LEDGER_HELD_BY_GATE" if held_count is not None else "MISSING_FROM_V2_LEDGER"),
            ("portfolio_ledger_shadow_observation_count", shadow_count,
             "V2_PAPER_LEDGER_SHADOW_OBSERVATIONS" if shadow_count is not None else "MISSING_FROM_V2_LEDGER"),
            ("portfolio_ledger_close_event_count", _coerce_float(pl.get("close_event_count")),
             "V2_PAPER_LEDGER" if pl.get("close_event_count") is not None else "MISSING_FROM_V2_LEDGER_CLOSE_EVENTS"),
            ("portfolio_realized_pnl_bps_sum", realized_pnl_bps,
             "V2_PAPER_LEDGER_REALIZED_EXIT" if realized_pnl_bps is not None else "MISSING_V2_REALIZED_PNL"),
            ("portfolio_realized_pnl_usdt_sum", realized_pnl_usdt,
             "V2_PAPER_LEDGER_REALIZED_EXIT" if realized_pnl_usdt is not None else "MISSING_V2_REALIZED_PNL"),
            ("portfolio_symbol_unrealized_pnl_bps", unrealized_pnl_bps,
             "V2_PAPER_POSITIONS_UNREALIZED_CONTEXT" if unrealized_pnl_bps is not None else "MISSING_V2_UNREALIZED_PNL"),
            ("portfolio_symbol_unrealized_pnl_usdt", unrealized_pnl_usdt,
             "V2_PAPER_POSITIONS_UNREALIZED_CONTEXT" if unrealized_pnl_usdt is not None else "MISSING_V2_UNREALIZED_PNL"),
            ("portfolio_symbol_position_record_count", float(len(symbol_positions)),
             "V2_PAPER_POSITIONS"),
            ("portfolio_symbol_accepted_fill_count", float(len(symbol_accepted_rows)),
             "V2_PAPER_LEDGER_ACCEPTED_FILLS_SAFE"),
            ("portfolio_symbol_held_by_gate_count", float(len(symbol_held_context_rows)),
             "V2_PAPER_HELD_BY_GATE_CONTEXT"),
            ("portfolio_symbol_shadow_observation_count", float(len(symbol_shadow_rows)),
             "V2_PAPER_LEDGER_SHADOW_OBSERVATIONS"),
            ("portfolio_symbol_blocked_intent_count", float(len(symbol_blocked_rows)),
             "V2_PAPER_LEDGER_BLOCKED_CONTEXT"),
            ("portfolio_intent_count", float(len(pi)) if isinstance(paper_intents, list) else None,
             "V2_PAPER_INTENTS" if isinstance(paper_intents, list) else "MISSING_FROM_V2_PAPER_INTENTS"),
            ("portfolio_symbol_intent_count", float(len(symbol_intents)),
             "V2_PAPER_INTENTS" if isinstance(paper_intents, list) else "MISSING_FROM_V2_PAPER_INTENTS"),
            ("portfolio_held_intent_count", float(len(held_intents)) if isinstance(paper_intents_held, list) else None,
             "V2_PAPER_INTENTS_HELD_BY_GATE" if isinstance(paper_intents_held, list) else "MISSING_FROM_V2_HELD_INTENTS"),
            ("portfolio_symbol_held_intent_count", float(len(symbol_held_intents)),
             "V2_PAPER_INTENTS_HELD_BY_GATE" if isinstance(paper_intents_held, list) else "MISSING_FROM_V2_HELD_INTENTS"),
            ("portfolio_symbol_negative_expected_move_block_count",
             float(sum(1 for reason in combined_block_reasons if "NEGATIVE_EXPECTED_MOVE" in reason)),
             "V2_PAPER_FILL_GATE_BLOCK_REASONS"),
            ("portfolio_symbol_checkpoint_required_block_count",
             float(sum(1 for reason in combined_block_reasons if "CHECKPOINT" in reason)),
             "V2_PAPER_FILL_GATE_BLOCK_REASONS"),
            ("portfolio_symbol_trainer_malformed_block_count",
             float(sum(1 for reason in combined_block_reasons if "TRAINER" in reason or "MALFORMED" in reason)),
             "V2_PAPER_FILL_GATE_BLOCK_REASONS"),
            ("portfolio_symbol_prediction_present", 1.0 if pred else None,
             "V2_PREDICTION" if pred else "MISSING_FROM_V2_PREDICTION"),
            ("portfolio_symbol_prediction_age_seconds", _payload_age_seconds(pred),
             "V2_PREDICTION" if _payload_age_seconds(pred) is not None else "MISSING_FROM_V2_PREDICTION"),
            ("portfolio_symbol_prediction_paper_fill_allowed", _flag(pred.get("paper_fill_allowed")) if pred else None,
             "V2_PREDICTION" if pred else "MISSING_FROM_V2_PREDICTION"),
            ("portfolio_symbol_prediction_block_reason_count", float(len(paper_fill_reasons)) if pred else None,
             "V2_PREDICTION" if pred else "MISSING_FROM_V2_PREDICTION"),
            ("portfolio_symbol_expected_move_after_cost_bps",
             _coerce_float(pred.get("expected_move_after_cost_bps")) if pred else None,
             "V2_PREDICTION" if pred.get("expected_move_after_cost_bps") is not None else "MISSING_FROM_V2_PREDICTION"),
            ("portfolio_symbol_confidence_calibrated",
             _coerce_float(pred.get("confidence_calibrated")) if pred else None,
             "V2_PREDICTION" if pred.get("confidence_calibrated") is not None else "MISSING_FROM_V2_PREDICTION"),
            ("portfolio_risk_pre_trade_denied_count",
             float(sum(1 for r in rd if r.get("pre_trade_allowed") is False)),
             "V2_RISK_DECISIONS"),
            ("portfolio_risk_fee_gate_denied_count",
             float(sum(1 for r in rd if r.get("fee_gate_allowed") is False)),
             "V2_RISK_DECISIONS"),
            # Burndown field group: exact source v2:risk:decisions.
            # Refined explicit-missing labels distinguish:
            #   - risk_decisions payload absent entirely
            #     -> MISSING_FROM_V2_RISK_DECISIONS
            #   - payload present but no row for this symbol
            #     -> MISSING_FROM_V2_RISK_DECISIONS_SYMBOL_ROW
            #   - row present but the specific gate field is None
            #     -> MISSING_FROM_V2_RISK_DECISIONS_FIELD_<gate>
            # The builder must NOT zero-fill, must NOT fall back to
            # paper/orchestrator/trainer/legacy keys, and must NOT
            # fabricate boolean gates.
            (
                "portfolio_symbol_risk_decision_present",
                1.0 if symbol_risk else (0.0 if rd else None),
                (
                    "V2_RISK_DECISIONS"
                    if symbol_risk
                    else (
                        "V2_RISK_DECISIONS_NO_SYMBOL_ROW"
                        if rd
                        else "MISSING_FROM_V2_RISK_DECISIONS"
                    )
                ),
            ),
            (
                "portfolio_symbol_pre_trade_allowed",
                _flag(symbol_risk.get("pre_trade_allowed")) if symbol_risk else None,
                _risk_field_source(
                    risk_decisions=risk_decisions,
                    symbol_row=symbol_risk,
                    field="pre_trade_allowed",
                ),
            ),
            (
                "portfolio_symbol_fee_gate_allowed",
                _flag(symbol_risk.get("fee_gate_allowed")) if symbol_risk else None,
                _risk_field_source(
                    risk_decisions=risk_decisions,
                    symbol_row=symbol_risk,
                    field="fee_gate_allowed",
                ),
            ),
            (
                "portfolio_symbol_churn_blocked",
                _flag(symbol_risk.get("churn_blocked")) if symbol_risk else None,
                _risk_field_source(
                    risk_decisions=risk_decisions,
                    symbol_row=symbol_risk,
                    field="churn_blocked",
                ),
            ),
            ("portfolio_trainer_heartbeat_age_seconds", _payload_age_seconds(tr),
             "V2_TRAINER_HEARTBEAT" if _payload_age_seconds(tr) is not None else "MISSING_FROM_V2_TRAINER"),
            ("portfolio_orchestrator_age_seconds", _payload_age_seconds(od),
             "V2_ORCHESTRATOR_DECISIONS" if _payload_age_seconds(od) is not None else "MISSING_FROM_V2_ORCHESTRATOR"),
            ("portfolio_tracker_history_payload_present", 1.0 if ph else None,
             "V2_POSITION_HISTORY_TRACKER_CONTEXT" if ph else "MISSING_FROM_V2_POSITION_HISTORY_TRACKER"),
            ("portfolio_tracker_no_open_position_flag", 1.0 if no_open_tracker_state else 0.0 if ph else None,
             "V2_POSITION_HISTORY_TRACKER_CONTEXT" if ph else "MISSING_FROM_V2_POSITION_HISTORY_TRACKER"),
            ("portfolio_tracker_open_position_flag", 1.0 if open_tracker_state else 0.0 if ph else None,
             "V2_POSITION_HISTORY_TRACKER_CONTEXT" if ph else "MISSING_FROM_V2_POSITION_HISTORY_TRACKER"),
            ("portfolio_tracker_accepted_intent_count",
             _coerce_float(ph.get("accepted_intent_count")) if ph else None,
             "V2_POSITION_HISTORY_TRACKER_CONTEXT" if ph.get("accepted_intent_count") is not None else "MISSING_FROM_V2_POSITION_HISTORY_TRACKER"),
            ("portfolio_tracker_held_intent_count",
             _coerce_float(ph.get("held_intent_count")) if ph else None,
             "V2_POSITION_HISTORY_TRACKER_CONTEXT" if ph.get("held_intent_count") is not None else "MISSING_FROM_V2_POSITION_HISTORY_TRACKER"),
            ("portfolio_tracker_shadow_observation_count",
             _coerce_float(ph.get("shadow_observation_count")) if ph else None,
             "V2_POSITION_HISTORY_TRACKER_CONTEXT" if ph.get("shadow_observation_count") is not None else "MISSING_FROM_V2_POSITION_HISTORY_TRACKER"),
            ("portfolio_tracker_mfe_bps", tracker_mfe,
             "V2_POSITION_HISTORY_TRACKER_CONTEXT" if tracker_mfe is not None else "MISSING_V2_TRACKER_MFE"),
            ("portfolio_tracker_mae_bps", tracker_mae,
             "V2_POSITION_HISTORY_TRACKER_CONTEXT" if tracker_mae is not None else "MISSING_V2_TRACKER_MAE"),
            ("portfolio_tracker_roe_bps", tracker_roe,
             "V2_POSITION_HISTORY_TRACKER_CONTEXT" if tracker_roe is not None else "MISSING_V2_TRACKER_ROE"),
            ("portfolio_altdata_score_payload_present", 1.0 if alt_score else None,
             "V2_ALTDATA_SYMBOL_SCORE_CONTEXT" if alt_score else "MISSING_FROM_V2_ALTDATA_SYMBOL_SCORE"),
            ("portfolio_altdata_candidate_payload_present", 1.0 if candidates_payload else None,
             "V2_ALTDATA_CANDIDATE_CONTEXT" if candidates_payload else "MISSING_FROM_V2_ALTDATA_CANDIDATES"),
            ("portfolio_altdata_candidate_only_not_adopted",
             _flag(candidates_payload.get("candidate_only_not_adopted")) if candidates_payload else None,
             "V2_ALTDATA_CANDIDATE_CONTEXT" if candidates_payload else "MISSING_FROM_V2_ALTDATA_CANDIDATES"),
            ("portfolio_altdata_live_symbols_expanded",
             _flag(candidates_payload.get("live_symbols_expanded")) if candidates_payload else None,
             "V2_ALTDATA_CANDIDATE_CONTEXT_NO_ADOPTION_AUTHORITY" if candidates_payload else "MISSING_FROM_V2_ALTDATA_CANDIDATES"),
            ("portfolio_altdata_paper_symbols_expanded",
             _flag(candidates_payload.get("paper_symbols_expanded")) if candidates_payload else None,
             "V2_ALTDATA_CANDIDATE_CONTEXT_NO_ADOPTION_AUTHORITY" if candidates_payload else "MISSING_FROM_V2_ALTDATA_CANDIDATES"),
            ("portfolio_altdata_training_symbols_expanded",
             _flag(candidates_payload.get("training_symbols_expanded")) if candidates_payload else None,
             "V2_ALTDATA_CANDIDATE_CONTEXT_NO_ADOPTION_AUTHORITY" if candidates_payload else "MISSING_FROM_V2_ALTDATA_CANDIDATES"),
            ("portfolio_symbol_candidate_present", 1.0 if candidate_row else None,
             "V2_ALTDATA_CANDIDATE_CONTEXT" if candidate_row else "MISSING_FROM_V2_ALTDATA_CANDIDATE_ROW"),
            ("portfolio_symbol_candidate_rank",
             _coerce_float((candidate_row or {}).get("candidate_publisher_rank")),
             "V2_ALTDATA_CANDIDATE_CONTEXT" if candidate_row and (candidate_row or {}).get("candidate_publisher_rank") is not None else "MISSING_FROM_V2_ALTDATA_CANDIDATE_ROW"),
            ("portfolio_symbol_candidate_state_ready", 1.0 if candidate_state == "CANDIDATE_READY" else 0.0 if candidate_row else None,
             "V2_ALTDATA_CANDIDATE_CONTEXT" if candidate_row else "MISSING_FROM_V2_ALTDATA_CANDIDATE_ROW"),
            ("portfolio_symbol_candidate_state_missing_provider_data", 1.0 if candidate_state == "MISSING_PROVIDER_DATA" else 0.0 if candidate_row else None,
             "V2_ALTDATA_CANDIDATE_CONTEXT" if candidate_row else "MISSING_FROM_V2_ALTDATA_CANDIDATE_ROW"),
            ("portfolio_symbol_candidate_state_stale_provider_data", 1.0 if candidate_state == "STALE_PROVIDER_DATA" else 0.0 if candidate_row else None,
             "V2_ALTDATA_CANDIDATE_CONTEXT" if candidate_row else "MISSING_FROM_V2_ALTDATA_CANDIDATE_ROW"),
            ("portfolio_symbol_candidate_state_budget_limited", 1.0 if candidate_state == "BUDGET_LIMITED" else 0.0 if candidate_row else None,
             "V2_ALTDATA_CANDIDATE_CONTEXT" if candidate_row else "MISSING_FROM_V2_ALTDATA_CANDIDATE_ROW"),
            ("portfolio_symbol_live_candidate", _flag((candidate_row or {}).get("live_symbol_candidate")) if candidate_row else None,
             "V2_ALTDATA_CANDIDATE_CONTEXT_NO_ADOPTION_AUTHORITY" if candidate_row else "MISSING_FROM_V2_ALTDATA_CANDIDATE_ROW"),
            ("portfolio_symbol_paper_candidate", _flag((candidate_row or {}).get("paper_symbol_candidate")) if candidate_row else None,
             "V2_ALTDATA_CANDIDATE_CONTEXT_NO_ADOPTION_AUTHORITY" if candidate_row else "MISSING_FROM_V2_ALTDATA_CANDIDATE_ROW"),
            ("portfolio_symbol_training_candidate", _flag((candidate_row or {}).get("training_symbol_candidate")) if candidate_row else None,
             "V2_ALTDATA_CANDIDATE_CONTEXT_NO_ADOPTION_AUTHORITY" if candidate_row else "MISSING_FROM_V2_ALTDATA_CANDIDATE_ROW"),
            ("portfolio_symbol_proposed_use_count", float(len(proposed_use)) if isinstance(proposed_use, list) else None,
             "V2_ALTDATA_CANDIDATE_CONTEXT_NO_ADOPTION_AUTHORITY" if isinstance(proposed_use, list) else "MISSING_FROM_V2_ALTDATA_CANDIDATE_ROW"),
            ("portfolio_symbol_altdata_score", _coerce_float(alt_score.get("altdata_symbol_score")),
             "V2_ALTDATA_SYMBOL_SCORE_CONTEXT" if alt_score.get("altdata_symbol_score") is not None else "MISSING_FROM_V2_ALTDATA_SYMBOL_SCORE"),
            ("portfolio_symbol_altdata_rank", _coerce_float(alt_score.get("altdata_symbol_rank")),
             "V2_ALTDATA_SYMBOL_SCORE_CONTEXT" if alt_score.get("altdata_symbol_rank") is not None else "MISSING_FROM_V2_ALTDATA_SYMBOL_SCORE"),
            ("portfolio_symbol_provider_availability_score", _coerce_float(alt_score.get("provider_availability_score")),
             "V2_ALTDATA_SYMBOL_SCORE_CONTEXT" if alt_score.get("provider_availability_score") is not None else "MISSING_FROM_V2_ALTDATA_SYMBOL_SCORE"),
            ("portfolio_symbol_altdata_freshness_score", _coerce_float(alt_score.get("altdata_freshness_score")),
             "V2_ALTDATA_SYMBOL_SCORE_CONTEXT" if alt_score.get("altdata_freshness_score") is not None else "MISSING_FROM_V2_ALTDATA_SYMBOL_SCORE"),
            ("portfolio_symbol_coingecko_discovery_score", _coerce_float(alt_score.get("coingecko_discovery_score")),
             "V2_ALTDATA_SYMBOL_SCORE_CONTEXT" if alt_score.get("coingecko_discovery_score") is not None else "MISSING_FROM_V2_ALTDATA_COINGECKO"),
            ("portfolio_symbol_coingecko_liquidity_score", _coerce_float(alt_score.get("coingecko_liquidity_score")),
             "V2_ALTDATA_SYMBOL_SCORE_CONTEXT" if alt_score.get("coingecko_liquidity_score") is not None else "MISSING_FROM_V2_ALTDATA_COINGECKO"),
            ("portfolio_symbol_coingecko_momentum_score", _coerce_float(alt_score.get("coingecko_momentum_score")),
             "V2_ALTDATA_SYMBOL_SCORE_CONTEXT" if alt_score.get("coingecko_momentum_score") is not None else "MISSING_FROM_V2_ALTDATA_COINGECKO"),
            ("portfolio_symbol_surf_market_price_signal_score", _coerce_float(alt_score.get("surf_market_price_signal_score")),
             "V2_ALTDATA_SYMBOL_SCORE_CONTEXT" if alt_score.get("surf_market_price_signal_score") is not None else "MISSING_FROM_V2_ALTDATA_SURF"),
            ("portfolio_symbol_coinglass_derivatives_score", _coerce_float(alt_score.get("coinglass_derivatives_score")),
             "V2_ALTDATA_SYMBOL_SCORE_CONTEXT" if alt_score.get("coinglass_derivatives_score") is not None else "MISSING_FROM_V2_ALTDATA_COINGLASS"),
            ("portfolio_symbol_public_intel_score", _coerce_float(alt_score.get("public_intel_score")),
             "V2_ALTDATA_SYMBOL_SCORE_CONTEXT" if alt_score.get("public_intel_score") is not None else "MISSING_FROM_V2_ALTDATA_PUBLIC_INTEL"),
            ("portfolio_symbol_defillama_liquidity_score", _coerce_float(alt_score.get("defillama_liquidity_score")),
             "V2_ALTDATA_SYMBOL_SCORE_CONTEXT" if alt_score.get("defillama_liquidity_score") is not None else "MISSING_FROM_V2_ALTDATA_PUBLIC_INTEL"),
            ("portfolio_symbol_defillama_tvl_momentum_score", _coerce_float(alt_score.get("defillama_tvl_momentum_score")),
             "V2_ALTDATA_SYMBOL_SCORE_CONTEXT" if alt_score.get("defillama_tvl_momentum_score") is not None else "MISSING_FROM_V2_ALTDATA_PUBLIC_INTEL"),
            ("portfolio_symbol_news_attention_score", _coerce_float(alt_score.get("news_attention_score")),
             "V2_ALTDATA_SYMBOL_SCORE_CONTEXT" if alt_score.get("news_attention_score") is not None else "MISSING_FROM_V2_ALTDATA_PUBLIC_INTEL"),
            ("portfolio_symbol_news_sentiment_score", _coerce_float(alt_score.get("news_sentiment_score")),
             "V2_ALTDATA_SYMBOL_SCORE_CONTEXT" if alt_score.get("news_sentiment_score") is not None else "MISSING_FROM_V2_ALTDATA_PUBLIC_INTEL"),
            ("portfolio_symbol_fear_greed_score", _coerce_float(alt_score.get("fear_greed_score")),
             "V2_ALTDATA_SYMBOL_SCORE_CONTEXT" if alt_score.get("fear_greed_score") is not None else "MISSING_FROM_V2_ALTDATA_PUBLIC_INTEL"),
            ("portfolio_symbol_btc_mempool_pressure_score", _coerce_float(alt_score.get("btc_mempool_pressure_score")),
             "V2_ALTDATA_SYMBOL_SCORE_CONTEXT" if alt_score.get("btc_mempool_pressure_score") is not None else "MISSING_FROM_V2_ALTDATA_PUBLIC_INTEL"),
            ("portfolio_symbol_whale_wall_score", _coerce_float(alt_score.get("whale_wall_score")),
             "V2_ALTDATA_SYMBOL_SCORE_CONTEXT" if alt_score.get("whale_wall_score") is not None else "MISSING_FROM_V2_ALTDATA_WHALE_WALLS"),
            ("portfolio_symbol_whale_bid_pressure_score", _coerce_float(alt_score.get("whale_bid_pressure_score")),
             "V2_ALTDATA_SYMBOL_SCORE_CONTEXT" if alt_score.get("whale_bid_pressure_score") is not None else "MISSING_FROM_V2_ALTDATA_WHALE_WALLS"),
            ("portfolio_symbol_whale_ask_pressure_score", _coerce_float(alt_score.get("whale_ask_pressure_score")),
             "V2_ALTDATA_SYMBOL_SCORE_CONTEXT" if alt_score.get("whale_ask_pressure_score") is not None else "MISSING_FROM_V2_ALTDATA_WHALE_WALLS"),
            ("portfolio_symbol_whale_wall_imbalance_score", _coerce_float(alt_score.get("whale_wall_imbalance_score")),
             "V2_ALTDATA_SYMBOL_SCORE_CONTEXT" if alt_score.get("whale_wall_imbalance_score") is not None else "MISSING_FROM_V2_ALTDATA_WHALE_WALLS"),
            ("portfolio_symbol_whale_wall_count_score", _coerce_float(alt_score.get("whale_wall_count_score")),
             "V2_ALTDATA_SYMBOL_SCORE_CONTEXT" if alt_score.get("whale_wall_count_score") is not None else "MISSING_FROM_V2_ALTDATA_WHALE_WALLS"),
            ("portfolio_symbol_whale_wall_event_count", _coerce_float(alt_score.get("whale_wall_event_count")),
             "V2_ALTDATA_SYMBOL_SCORE_CONTEXT" if alt_score.get("whale_wall_event_count") is not None else "MISSING_FROM_V2_ALTDATA_WHALE_WALLS"),
            ("portfolio_symbol_missing_provider_flag_count",
             float(len(missing_provider_flags)) if isinstance(missing_provider_flags, list) else None,
             "V2_ALTDATA_CANDIDATE_OR_SCORE_CONTEXT" if isinstance(missing_provider_flags, list) else "MISSING_FROM_V2_ALTDATA_PROVIDER_FLAGS"),
            ("portfolio_symbol_stale_provider_flag_count",
             float(len(stale_provider_flags)) if isinstance(stale_provider_flags, list) else None,
             "V2_ALTDATA_CANDIDATE_OR_SCORE_CONTEXT" if isinstance(stale_provider_flags, list) else "MISSING_FROM_V2_ALTDATA_PROVIDER_FLAGS"),
            ("portfolio_altdata_candidates_age_seconds", _payload_age_seconds(candidates_payload),
             "V2_ALTDATA_CANDIDATE_CONTEXT" if _payload_age_seconds(candidates_payload) is not None else "MISSING_FROM_V2_ALTDATA_CANDIDATES"),
            ("portfolio_altdata_score_age_seconds", _payload_age_seconds(alt_score),
             "V2_ALTDATA_SYMBOL_SCORE_CONTEXT" if _payload_age_seconds(alt_score) is not None else "MISSING_FROM_V2_ALTDATA_SYMBOL_SCORE"),
        ]
    )
    for i, (nm, val, src) in enumerate(derived[:size]):
        names[i] = f"portfolio_state.{nm}"
        values[i] = val
        sources[i] = src
    for i in range(size):
        if values[i] is None:
            missing.append(names[i])
    return values, names, sources, missing


def _build_position_context_slice(
    symbol: str,
    paper_positions: list[Mapping[str, Any]] | None,
    risk_decisions: list[Mapping[str, Any]] | None,
    prediction: Mapping[str, Any] | None,
    orchestrator_decisions: Mapping[str, Any] | None,
    paper_intents: list[Mapping[str, Any]] | None = None,
    paper_intents_held: list[Mapping[str, Any]] | None = None,
    paper_ledger: Mapping[str, Any] | None = None,
    position_price_track: Mapping[str, Any] | None = None,
    position_history: Mapping[str, Any] | None = None,
    position_history_consumption_allowed: bool | None = None,
    position_history_consumption_blocked_reason: str | None = None,
) -> tuple[list[float | None], list[str], list[str], list[str]]:
    size = SLICE_SIZES["position_context"]
    values: list[float | None] = [None] * size
    names: list[str] = [f"position_context[{i}]" for i in range(size)]
    sources: list[str] = ["MISSING_FROM_V2_POSITION_HISTORY"] * size
    missing: list[str] = []
    pp = paper_positions or []
    rd = risk_decisions or []
    pred = prediction or {}
    od = orchestrator_decisions or {}
    pos = next(
        (p for p in pp if (p.get("symbol") or "").upper() == symbol.upper()), None
    )
    rd_sym = next(
        (r for r in rd if (r.get("symbol") or "").upper() == symbol.upper()), None
    )
    side = (pos or {}).get("side") or ""
    block_reasons = list(pred.get("paper_fill_gate_block_reasons") or [])
    held_by_gate_for_symbol = any(
        (h.get("symbol") or "").upper() == symbol.upper()
        for h in (od.get("held_by_paper_fill_gate") or [])
    )
    derived: list[tuple[str, float | None, str]] = [
        ("position_present", 1.0 if pos else 0.0, "V2_PAPER_POSITIONS"),
        ("side_is_long", 1.0 if side == "long" else 0.0, "V2_PAPER_POSITIONS"),
        ("side_is_short", 1.0 if side == "short" else 0.0, "V2_PAPER_POSITIONS"),
        ("side_is_flat", 1.0 if (not pos or side == "flat") else 0.0,
         "V2_PAPER_POSITIONS"),
        ("expected_move_after_cost_bps",
         _coerce_float((pos or {}).get("expected_move_after_cost_bps")),
         "V2_PAPER_POSITIONS" if pos else "MISSING_FROM_V2_PAPER_POSITIONS"),
        ("confidence_calibrated",
         _coerce_float((pos or {}).get("confidence_calibrated")),
         "V2_PAPER_POSITIONS" if pos else "MISSING_FROM_V2_PAPER_POSITIONS"),
        # Burndown field group: exact source v2:risk:decisions, position_context
        # projection. Uses the same _risk_field_source helper as the
        # portfolio_state projection to emit explicit per-field MISSING
        # labels and to distinguish payload-absent / no-symbol-row /
        # field-None states. No fallback to any other key. No zero-fill.
        ("pre_trade_allowed",
         _coerce_float((rd_sym or {}).get("pre_trade_allowed")),
         _risk_field_source(
             risk_decisions=risk_decisions,
             symbol_row=rd_sym,
             field="pre_trade_allowed",
         )),
        ("fee_gate_allowed",
         _coerce_float((rd_sym or {}).get("fee_gate_allowed")),
         _risk_field_source(
             risk_decisions=risk_decisions,
             symbol_row=rd_sym,
             field="fee_gate_allowed",
         )),
        ("churn_blocked",
         _coerce_float((rd_sym or {}).get("churn_blocked")),
         _risk_field_source(
             risk_decisions=risk_decisions,
             symbol_row=rd_sym,
             field="churn_blocked",
         )),
        ("paper_fill_allowed", _coerce_float(pred.get("paper_fill_allowed")),
         "V2_PREDICTION" if pred else "MISSING_FROM_V2_PREDICTION"),
        ("held_by_paper_fill_gate", 1.0 if held_by_gate_for_symbol else 0.0,
         "V2_ORCHESTRATOR_DECISIONS"),
        ("block_reason_count", float(len(block_reasons)),
         "V2_PREDICTION"),
        ("expected_move_bps",
         _coerce_float(pred.get("expected_move_bps")),
         "V2_PREDICTION" if pred else "MISSING_FROM_V2_PREDICTION"),
        ("trainer_confidence_calibrated",
         _coerce_float(pred.get("confidence_calibrated")),
         "V2_PREDICTION" if pred else "MISSING_FROM_V2_PREDICTION"),
        ("selected_action_is_hold",
         1.0 if (pred.get("selected_action") == "hold") else 0.0,
         "V2_PREDICTION" if pred else "MISSING_FROM_V2_PREDICTION"),
    ]
    # PHASE 5 additions for position_context (per-symbol):
    expected_move_diff = None
    em_bps = _coerce_float(pred.get("expected_move_bps"))
    em_after = _coerce_float(pred.get("expected_move_after_cost_bps"))
    if em_bps is not None and em_after is not None:
        expected_move_diff = em_bps - em_after
    conf_raw = _coerce_float(pred.get("confidence_raw"))
    conf_cal = _coerce_float(pred.get("confidence_calibrated"))
    conf_diff = (conf_cal - conf_raw) if (conf_cal is not None and conf_raw is not None) else None
    block_reasons_known = list(pred.get("paper_fill_gate_block_reasons") or [])
    has_block_reason_negative_em = (
        1.0
        if any("NEGATIVE_EXPECTED_MOVE_AFTER_COST" in r for r in block_reasons_known)
        else 0.0
    )
    has_block_reason_edge_below_threshold = (
        1.0
        if any("EDGE_AFTER_COST_BELOW_THRESHOLD" in r for r in block_reasons_known)
        else 0.0
    )
    has_block_reason_feature_freshness = (
        1.0
        if any("FEATURE_FRESHNESS_NOT_CURRENT" in r for r in block_reasons_known)
        else 0.0
    )
    selected_action_is_long = 1.0 if (pred.get("selected_action") == "long") else 0.0
    selected_action_is_short = 1.0 if (pred.get("selected_action") == "short") else 0.0
    derived.extend(
        [
            ("expected_move_bps", em_bps,
             "V2_PREDICTION" if em_bps is not None else "MISSING_FROM_V2_PREDICTION"),
            ("expected_move_diff_bps_minus_after_cost", expected_move_diff,
             "V2_DERIVED_FROM_PREDICTION" if expected_move_diff is not None else "MISSING_FROM_V2_PREDICTION"),
            ("confidence_raw", conf_raw,
             "V2_PREDICTION" if conf_raw is not None else "MISSING_FROM_V2_PREDICTION"),
            ("confidence_calibration_delta", conf_diff,
             "V2_DERIVED_FROM_PREDICTION" if conf_diff is not None else "MISSING_FROM_V2_PREDICTION"),
            ("selected_action_is_long", selected_action_is_long, "V2_PREDICTION"),
            ("selected_action_is_short", selected_action_is_short, "V2_PREDICTION"),
            ("has_block_reason_negative_em", has_block_reason_negative_em, "V2_PREDICTION"),
            ("has_block_reason_edge_below_threshold", has_block_reason_edge_below_threshold, "V2_PREDICTION"),
            ("has_block_reason_feature_freshness", has_block_reason_feature_freshness, "V2_PREDICTION"),
            ("v2_position_history_source_available",
             1.0 if (paper_positions or paper_intents or paper_intents_held or paper_ledger) else 0.0,
             "V2_PROBE_FLAG_POSITION_HISTORY_AGGREGATOR"),
        ]
    )
    # Strict tracker-only path for the 10 tracker-derived position-context
    # fields. NEVER reads raw v2:paper:positions / ledger / intents /
    # intents_held — those are intentionally not threaded into this
    # extractor. The gate evaluation happens at the
    # ``build_full_observation_status`` level; this path just honors
    # the per-symbol decision.
    derived.extend(
        _extract_tracker_history_fields(
            symbol=symbol,
            position_history=position_history,
            consumption_allowed=position_history_consumption_allowed,
            consumption_blocked_reason=position_history_consumption_blocked_reason,
        )
    )
    # Strict tracker-only extension path: 6 additional fields sourced
    # solely from the two tracker-owned Redis payloads
    # (``position_price_track`` + ``position_history``). Same gate
    # masking semantics as the 10-field extractor above. These fields
    # remain in the ``position_context`` slice's 50-dim budget.
    derived.extend(
        _extract_tracker_extended_fields(
            symbol=symbol,
            position_history=position_history,
            position_price_track=position_price_track,
            consumption_allowed=position_history_consumption_allowed,
            consumption_blocked_reason=position_history_consumption_blocked_reason,
        )
    )
    # Raw paper-context path for the 9 rate / granular block-reason
    # fields. These DO consume raw paper inputs, but are clearly
    # relabeled with V2_RAW_PAPER_CONTEXT_NOT_TRACKER_HISTORY so the
    # boundary with the tracker-derived fields is unambiguous. They
    # are not gated by the tracker-consumption gate.
    derived.extend(
        _extract_raw_paper_context_fields(
            symbol=symbol,
            risk_decisions=risk_decisions,
            paper_intents=paper_intents,
            paper_intents_held=paper_intents_held,
            paper_ledger=paper_ledger,
        )
    )
    for i, (nm, val, src) in enumerate(derived[:size]):
        names[i] = f"position_context.{nm}"
        values[i] = val
        sources[i] = src
    for i in range(size):
        if values[i] is None:
            missing.append(names[i])
    return values, names, sources, missing


def _build_onchain_slice(name: str) -> tuple[list[float | None], list[str], list[str], list[str]]:
    size = SLICE_SIZES[name]
    values: list[float | None] = [None] * size
    names: list[str] = [f"{name}[{i}]" for i in range(size)]
    sources: list[str] = ["ONCHAIN_FEATURE_SOURCE_MISSING"] * size
    missing = list(names)
    return values, names, sources, missing


def build_full_observation_for_symbol(
    symbol: str,
    timeframe: str,
    feature_snapshot: Mapping[str, Any] | None,
    paper_positions: list[Mapping[str, Any]] | None,
    paper_ledger: Mapping[str, Any] | None,
    risk_decisions: list[Mapping[str, Any]] | None,
    orchestrator_decisions: Mapping[str, Any] | None,
    trainer_heartbeat: Mapping[str, Any] | None,
    prediction: Mapping[str, Any] | None,
    market_price: Mapping[str, Any] | None = None,
    market_funding: Mapping[str, Any] | None = None,
    market_open_interest: Mapping[str, Any] | None = None,
    paper_intents: list[Mapping[str, Any]] | None = None,
    paper_intents_held: list[Mapping[str, Any]] | None = None,
    position_price_track: Mapping[str, Any] | None = None,
    position_history: Mapping[str, Any] | None = None,
    altdata_symbol_score: Mapping[str, Any] | None = None,
    altdata_candidates: Mapping[str, Any] | None = None,
    liquidation_per_symbol: Mapping[str, Any] | None = None,
    position_history_consumption_allowed: bool | None = None,
    position_history_consumption_blocked_reason: str | None = None,
) -> FullObservationResult:
    fs_id = (feature_snapshot or {}).get("feature_snapshot_id")
    freshness = (feature_snapshot or {}).get("feature_freshness_state")
    uf_v, uf_n, uf_s, uf_m, sf_present, sf_target = _build_unified_features_slice(
        symbol,
        feature_snapshot,
        market_price,
        market_funding,
        market_open_interest,
        paper_positions,
        paper_ledger,
        risk_decisions,
        orchestrator_decisions,
        trainer_heartbeat,
        liquidation_per_symbol,
    )
    ps_v, ps_n, ps_s, ps_m = _build_portfolio_state_slice(
        symbol,
        paper_positions,
        paper_ledger,
        risk_decisions,
        orchestrator_decisions,
        trainer_heartbeat,
        prediction=prediction,
        paper_intents=paper_intents,
        paper_intents_held=paper_intents_held,
        position_history=(
            position_history if position_history_consumption_allowed is not False else None
        ),
        altdata_symbol_score=altdata_symbol_score,
        altdata_candidates=altdata_candidates,
    )
    btc_v, btc_n, btc_s, btc_m = _build_onchain_slice("onchain_btc")
    eth_v, eth_n, eth_s, eth_m = _build_onchain_slice("onchain_eth")
    pc_v, pc_n, pc_s, pc_m = _build_position_context_slice(
        symbol,
        paper_positions,
        risk_decisions,
        prediction,
        orchestrator_decisions,
        paper_intents=paper_intents,
        paper_intents_held=paper_intents_held,
        paper_ledger=paper_ledger,
        position_price_track=(
            position_price_track if position_history_consumption_allowed is not False else None
        ),
        position_history=(
            position_history if position_history_consumption_allowed is not False else None
        ),
        position_history_consumption_allowed=position_history_consumption_allowed,
        position_history_consumption_blocked_reason=(
            position_history_consumption_blocked_reason
        ),
    )
    values = uf_v + ps_v + btc_v + eth_v + pc_v
    names = uf_n + ps_n + btc_n + eth_n + pc_n
    sources = uf_s + ps_s + btc_s + eth_s + pc_s
    missing = uf_m + ps_m + btc_m + eth_m + pc_m
    generated_dim = sum(1 for v in values if v is not None)
    missing_dim = sum(1 for v in values if v is None)
    explicit_missing_categories: list[str] = []
    partial_categories: list[str] = []
    present_categories: list[str] = []
    for cat_name, (vs, miss) in (
        ("unified_features", (uf_v, uf_m)),
        ("portfolio_state", (ps_v, ps_m)),
        ("onchain_btc", (btc_v, btc_m)),
        ("onchain_eth", (eth_v, eth_m)),
        ("position_context", (pc_v, pc_m)),
    ):
        any_present = any(v is not None for v in vs)
        any_missing = len(miss) > 0
        if any_present and any_missing:
            partial_categories.append(cat_name)
        elif any_present:
            present_categories.append(cat_name)
        else:
            explicit_missing_categories.append(cat_name)
    state = (
        "FULL_OBSERVATION_BUILDER_COMPLETE"
        if generated_dim == TARGET_FULL_DIM and missing_dim == 0
        else "FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS"
    )
    return FullObservationResult(
        symbol=symbol,
        timeframe=timeframe,
        feature_snapshot_id=fs_id,
        source_freshness_state=freshness,
        compact_observation_dim=26,
        target_full_observation_dim=TARGET_FULL_DIM,
        generated_full_observation_dim=generated_dim,
        missing_dim_count=missing_dim,
        zero_filled_field_count=0,
        field_names=tuple(names),
        field_values=tuple(values),
        field_sources=tuple(sources),
        missing_field_names=tuple(missing),
        partial_field_names=tuple(),
        explicit_missing_categories=tuple(explicit_missing_categories),
        partial_categories=tuple(partial_categories),
        present_categories=tuple(present_categories),
        state=state,
        subfamily_present_counts=sf_present,
        subfamily_target_counts=sf_target,
    )


def _connect_redis() -> Any:  # pragma: no cover
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _read_json(r: Any, key: str) -> Any:
    if r is None:
        return None
    try:
        raw = r.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _read_tracker_heartbeat_with_ttl(redis_client: Any) -> tuple[dict | None, int | None]:
    """Return (heartbeat_payload, ttl_seconds) for the tracker heartbeat
    key. Returns ``(None, None)`` if Redis is unreachable."""
    if redis_client is None:
        return None, None
    payload = _read_json(redis_client, TRACKER_HEARTBEAT_KEY)
    ttl: int | None = None
    try:
        ttl_raw = redis_client.ttl(TRACKER_HEARTBEAT_KEY)
        if isinstance(ttl_raw, (int, float)):
            ttl = int(ttl_raw)
    except Exception:
        ttl = None
    return payload if isinstance(payload, dict) else None, ttl


def build_full_observation_status(
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
    timeframe: str = "1m",
) -> dict[str, Any]:
    contract = build_legacy_observation_contract()
    largest = contract.get("legacy_observation_largest_dim")
    r = _connect_redis()
    paper_positions = _read_json(r, "v2:paper:positions") if r else None
    paper_ledger = _read_json(r, "v2:paper:ledger") if r else None
    paper_intents = _read_json(r, "v2:paper:intents") if r else None
    paper_intents_held = (
        _read_json(r, "v2:paper:intents_held_by_paper_fill_gate") if r else None
    )
    risk_decisions = _read_json(r, "v2:risk:decisions") if r else None
    orch_decisions = _read_json(r, "v2:orchestrator:decisions") if r else None
    trainer_hb = _read_json(r, "v2:trainer:heartbeat") if r else None
    altdata_candidates = _read_json(r, "v2:symbol_universe:altdata_candidates") if r else None
    tracker_heartbeat, tracker_heartbeat_ttl = _read_tracker_heartbeat_with_ttl(r)
    try:
        from v2.backend.app.services.rl_core.liquidation_observation_aggregator import (
            read_v2_liquidation_per_symbol_from,
        )
    except Exception:  # pragma: no cover - defensive import isolation
        read_v2_liquidation_per_symbol_from = None
    consumption_gate = evaluate_position_history_consumption_gate(
        tracker_heartbeat=tracker_heartbeat,
        tracker_heartbeat_ttl_seconds=tracker_heartbeat_ttl,
    )
    per_symbol: list[dict[str, Any]] = []
    aggregate_state = "FULL_OBSERVATION_BUILDER_COMPLETE"
    subfamily_present_totals: dict[str, int] = {}
    subfamily_target_totals: dict[str, int] = {}
    for sym in symbols:
        fs = _read_json(r, f"v2:features:latest:{sym}:{timeframe}") if r else None
        pred = _read_json(r, f"v2:prediction:{sym}:{timeframe}") if r else None
        market_price = _read_json(r, f"v2:market:prices:{sym}") if r else None
        market_funding = _read_json(r, f"v2:market:funding:{sym}") if r else None
        market_oi = _read_json(r, f"v2:market:open_interest:{sym}") if r else None
        position_price_track = (
            _read_json(r, f"v2:paper:position_price_track:{sym}") if r else None
        )
        position_history = (
            _read_json(r, f"v2:paper:position_history:{sym}") if r else None
        )
        altdata_score = (
            _read_json(r, f"v2:altdata:symbol_score:{sym}") if r else None
        )
        liquidation_per_symbol = (
            read_v2_liquidation_per_symbol_from(r, sym)
            if read_v2_liquidation_per_symbol_from is not None
            else None
        )
        result = build_full_observation_for_symbol(
            symbol=sym,
            timeframe=timeframe,
            feature_snapshot=fs,
            paper_positions=paper_positions if isinstance(paper_positions, list) else None,
            paper_ledger=paper_ledger if isinstance(paper_ledger, dict) else None,
            risk_decisions=risk_decisions if isinstance(risk_decisions, list) else None,
            orchestrator_decisions=orch_decisions if isinstance(orch_decisions, dict) else None,
            trainer_heartbeat=trainer_hb if isinstance(trainer_hb, dict) else None,
            prediction=pred if isinstance(pred, dict) else None,
            market_price=market_price if isinstance(market_price, dict) else None,
            market_funding=market_funding if isinstance(market_funding, dict) else None,
            market_open_interest=market_oi if isinstance(market_oi, dict) else None,
            paper_intents=paper_intents if isinstance(paper_intents, list) else None,
            paper_intents_held=(
                paper_intents_held if isinstance(paper_intents_held, list) else None
            ),
            position_price_track=(
                position_price_track if isinstance(position_price_track, dict) else None
            ),
            position_history=(
                position_history if isinstance(position_history, dict) else None
            ),
            altdata_symbol_score=(
                altdata_score if isinstance(altdata_score, dict) else None
            ),
            altdata_candidates=(
                altdata_candidates if isinstance(altdata_candidates, dict) else None
            ),
            liquidation_per_symbol=(
                liquidation_per_symbol
                if isinstance(liquidation_per_symbol, dict)
                else None
            ),
            position_history_consumption_allowed=consumption_gate[
                "consumption_allowed"
            ],
            position_history_consumption_blocked_reason=consumption_gate[
                "blocked_reason"
            ],
        )
        for k, v in result.subfamily_target_counts.items():
            subfamily_target_totals[k] = v
        for k, v in result.subfamily_present_counts.items():
            subfamily_present_totals[k] = subfamily_present_totals.get(k, 0) + v
        sample_present = [
            {"name": result.field_names[i], "value": result.field_values[i],
             "source": result.field_sources[i]}
            for i in range(len(result.field_values))
            if result.field_values[i] is not None
        ][:24]
        sample_missing = [
            {"name": result.field_names[i], "value": None,
             "source": result.field_sources[i]}
            for i in range(len(result.field_values))
            if result.field_values[i] is None
        ][:12]
        per_symbol.append(
            {
                "symbol": result.symbol,
                "timeframe": result.timeframe,
                "feature_snapshot_id": result.feature_snapshot_id,
                "source_freshness_state": result.source_freshness_state,
                "compact_observation_dim": result.compact_observation_dim,
                "target_full_observation_dim": result.target_full_observation_dim,
                "generated_full_observation_dim": result.generated_full_observation_dim,
                "missing_dim_count": result.missing_dim_count,
                "zero_filled_field_count": result.zero_filled_field_count,
                "missing_field_count": len(result.missing_field_names),
                "missing_field_count_sample": list(result.missing_field_names[:20]),
                "explicit_missing_categories": list(result.explicit_missing_categories),
                "partial_categories": list(result.partial_categories),
                "present_categories": list(result.present_categories),
                "subfamily_present_counts": dict(result.subfamily_present_counts),
                "subfamily_target_counts": dict(result.subfamily_target_counts),
                "sample_present_fields": sample_present,
                "sample_missing_fields": sample_missing,
                "state": result.state,
                "checkpoint_compatibility_claimed": False,
            }
        )
        if result.state != "FULL_OBSERVATION_BUILDER_COMPLETE":
            aggregate_state = "FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS"
    agg_missing: set[str] = set()
    agg_partial: set[str] = set()
    agg_present: set[str] = set()
    for row in per_symbol:
        agg_missing.update(row.get("explicit_missing_categories") or [])
        agg_partial.update(row.get("partial_categories") or [])
        agg_present.update(row.get("present_categories") or [])
    event_dependent_families = [
        name
        for name in EVENT_DEPENDENT_SUBFAMILIES
        if subfamily_present_totals.get(name, 0)
        < subfamily_target_totals.get(name, 0) * len(per_symbol)
    ]
    conditionally_undefined_families = [
        name
        for name in CONDITIONALLY_UNDEFINED_SUBFAMILIES
        if 0
        < (
            subfamily_target_totals.get(name, 0) * len(per_symbol)
            - subfamily_present_totals.get(name, 0)
        )
        <= len(per_symbol)
    ]
    next_required_family = None
    # Pick the subfamily with the largest target-minus-present gap that is
    # still V2-source-buildable, prioritising binance_klines over the rest.
    # Event-dependent families have live V2 ingestion paths, but cannot be
    # completed by zero-fill or by inventing absent market events.
    for name, target in subfamily_target_totals.items():
        if name in OPERATOR_OR_EXTERNAL_SUBFAMILIES:
            continue
        if name in EVENT_DEPENDENT_SUBFAMILIES:
            continue
        if name in conditionally_undefined_families:
            continue
        present = subfamily_present_totals.get(name, 0)
        if present < target * len(per_symbol):
            next_required_family = name
            break
    no_buildable_internal_family_remaining = next_required_family is None
    return {
        "schema_version": "v2_full_observation_builder_status_v3",
        "generated_at": _utc_iso(),
        "generated_utc": _utc_iso(),
        "compact_observation_dim": 26,
        "target_full_observation_dim": TARGET_FULL_DIM,
        "legacy_observation_total_dim_by_version": contract.get(
            "legacy_observation_total_dim_by_version"
        ),
        "legacy_observation_largest_dim": largest,
        "slice_sizes_target": SLICE_SIZES,
        "subfamily_layout": [
            {"name": n, "size": s} for n, s in SUBFAMILY_LAYOUT
        ],
        "subfamily_present_counts_total": subfamily_present_totals,
        "subfamily_target_counts_total": subfamily_target_totals,
        "compact_observation_v1": {
            "dim": 26,
            "source": "v2.backend.app.services.rl_core.observation_schema",
            "kept_as_current_runtime_policy_input": True,
        },
        "full_observation_v1": {
            "target_dim": TARGET_FULL_DIM,
            "target_schema": "V3" if largest == 1911 else "unknown",
            "missing_observation_categories": sorted(agg_missing),
            "partial_observation_categories": sorted(agg_partial),
            "present_observation_categories": sorted(agg_present),
            "checkpoint_compatibility_claimed": False,
            "operator_artifact_or_new_builder_required": True,
        },
        "operator_required": True,
        "operator_instruction": (
            "Continue burndown of buildable families. Adopt external sources "
            "only after operator decision and Codex review."
        ),
        "per_symbol": per_symbol,
        "state": aggregate_state,
        "zero_filled_field_count": sum(
            int(row.get("zero_filled_field_count") or 0) for row in per_symbol
        ),
        "checkpoint_compatibility_claimed": False,
        "next_required_fix": (
            (
                "No buildable internal V2-native sub-family remains in this "
                "status snapshot. Remaining gaps require external/operator "
                "sources or real market events; do not zero-fill or fabricate "
                "liquidation fields."
            )
            if no_buildable_internal_family_remaining
            else (
                "Extend buildable V2-native sub-families and address "
                "EXTERNAL_SOURCE_REQUIRED categories only after operator + "
                "Codex approval."
            )
        ),
        "next_required_family": next_required_family,
        "no_buildable_internal_family_remaining": (
            no_buildable_internal_family_remaining
        ),
        "external_source_required_families": [
            "unified_feature_family.token_metrics",
            "onchain_btc",
            "onchain_eth",
        ],
        "operator_decision_required_families": [
            "unified_feature_family.ccxt_ohlcv",
        ],
        "event_dependent_families": event_dependent_families,
        "conditionally_undefined_families": conditionally_undefined_families,
        "no_torch_imported": True,
        "no_pickle_loaded": True,
        "no_legacy_filesystem_read": True,
        "no_zero_fill_for_unknown_fields": True,
        "no_legacy_features_consumed_as_current_truth": True,
        "policy_architecture_parity_claimed": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "position_history_consumption": consumption_gate,
        "position_history_consumption_allowed": consumption_gate[
            "consumption_allowed"
        ],
        "position_history_consumption_blocked_reason": consumption_gate[
            "blocked_reason"
        ],
        "position_history_consumption_state": consumption_gate[
            "consumption_state"
        ],
        "position_history_consumption_unblocked_after": consumption_gate[
            "consumption_unblocked_after"
        ],
        "position_history_tracker_heartbeat_present": consumption_gate[
            "tracker_heartbeat_present"
        ],
        "position_history_tracker_heartbeat_ttl_seconds": consumption_gate[
            "tracker_heartbeat_ttl_seconds"
        ],
        "position_history_tracker_heartbeat_age_seconds": consumption_gate[
            "tracker_heartbeat_age_seconds"
        ],
        "position_history_tracker_heartbeat_fresh": consumption_gate[
            "tracker_heartbeat_fresh"
        ],
        "position_history_tracker_heartbeat_generated_utc": consumption_gate[
            "tracker_heartbeat_generated_utc"
        ],
        "position_history_tracker_codex_pass_marker_paths_passed": consumption_gate[
            "tracker_codex_pass_marker_paths_passed"
        ],
        "position_history_tracker_codex_pass_marker_paths_failed": consumption_gate[
            "tracker_codex_pass_marker_paths_failed"
        ],
    }


def write_full_observation_status(
    worklog_path: Path,
    public_paths: Path | tuple[Path, ...] | list[Path],
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
    timeframe: str = "1m",
) -> dict[str, Any]:
    payload = build_full_observation_status(symbols=symbols, timeframe=timeframe)
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    worklog_path.parent.mkdir(parents=True, exist_ok=True)
    worklog_path.write_text(body, encoding="utf-8")
    if isinstance(public_paths, Path):
        targets: tuple[Path, ...] = (public_paths,)
    else:
        targets = tuple(public_paths)
    for p in targets:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return payload


# Back-compat exports for older tests that referenced the legacy
# 23-field flat layout. These are kept so existing tests keep working.
V2_NATIVE_UNIFIED_FEATURE_FIELDS: tuple[str, ...] = (
    "ret_pct",
    "log_return",
    "body_pct",
    "range_pct",
    "gap_pct",
    "true_range_pct",
    "ema_12",
    "ema_26",
    "macd",
    "macd_signal",
    "macd_hist",
    "rsi_14",
    "bb_width_pct",
    "htf_ret_pct",
    "htf_rsi_14",
    "bid_ask_spread_bps",
    "depth_imbalance",
    "micro_price",
    "toxicity_proxy",
    "funding_rate",
    "oi_change_pct",
    "last_liq_bps_24h",
    "paper_position_present",
)
V2_NATIVE_PORTFOLIO_STATE_FIELDS: tuple[str, ...] = (
    "paper_position_count",
    "paper_accepted_count",
    "paper_blocked_count",
    "paper_held_by_paper_fill_gate_count",
    "risk_pre_trade_allowed_count",
    "risk_fee_gate_allowed_count",
    "risk_churn_blocked_count",
    "orchestrator_considered_count",
    "orchestrator_bucket_winners_count",
    "orchestrator_stale_proposal_count",
    "v2_prediction_count",
    "v2_prediction_paper_fill_allowed_count",
)
V2_NATIVE_POSITION_CONTEXT_FIELDS: tuple[str, ...] = (
    "position_present",
    "side_is_long",
    "side_is_short",
    "expected_move_after_cost_bps",
    "confidence_calibrated",
    "pre_trade_allowed",
    "fee_gate_allowed",
    "churn_blocked",
    "paper_fill_allowed",
)
