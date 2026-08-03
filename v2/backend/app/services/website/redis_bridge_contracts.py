"""V2 Website Rebuild — Phase 1 Redis bridge contracts.

The frontend never reads Redis directly. Every Redis-backed view goes
through a backend bridge that:

- declares the exact key (or key family) consumed;
- labels the source honestly as one of
  ``V2_NATIVE_PUBLIC_PAYLOAD``, ``V2_BRIDGE_FROM_LEGACY_REDIS``,
  ``LEGACY_REFERENCE_ONLY``, or ``PLACEHOLDER_NOT_READY``;
- documents the freshness window the bridge enforces;
- records the placeholder state when the underlying key is absent /
  stale / has no V2-native client yet.

This module is pure data + a small safe Redis reader that refuses any
key that is not in the declared allowlist. It writes no Redis key, calls
no exchange endpoint, and never returns raw API keys.
"""
from __future__ import annotations

import enum
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from .page_contracts import PlaceholderState, SourceType


# All key families the website is allowed to bridge. Anything outside
# this allowlist is rejected by ``safe_bridge_read``.
ALLOWED_KEY_FAMILIES: tuple[re.Pattern[str], ...] = (
    # V2-native namespaces.
    re.compile(r"^v2:[A-Za-z0-9_:{}.\-]+$"),
    # Legacy bridge keys we explicitly allow as REFERENCE_ONLY / bridge.
    re.compile(r"^price:(?:realtime|last):[A-Z0-9]+$"),
    re.compile(r"^prediction:[A-Z0-9]+:(?:multi|\d+[mhd])$"),
    re.compile(r"^signals:trading:primary$"),
    re.compile(r"^unified_features:[A-Z0-9]+:[0-9]+[mhd]$"),
    re.compile(r"^features:coinank:[A-Za-z0-9_:.{}-]+$"),
    re.compile(r"^features:global_coinank:[A-Za-z0-9_:.{}-]+$"),
    re.compile(r"^orderbook:(?:bids|asks):[A-Z0-9]+$"),
    re.compile(r"^liquidations:events$"),
    re.compile(r"^liq_levels:[A-Z0-9]+$"),
    re.compile(r"^ta:[A-Z0-9]+:[0-9]+[mhd]$"),
    re.compile(r"^heartbeat:[A-Za-z0-9_:.{}-]+$"),
    re.compile(r"^ohlcv:list:binance:[A-Z0-9]+:[0-9]+[mhd]$"),
    re.compile(r"^v2:dashboards:binance_top10:[A-Za-z0-9_:.{}-]+$"),
    re.compile(r"^v2:altdata:[A-Za-z0-9_:.{}-]+$"),
    re.compile(r"^v2:market:liquidations:[A-Za-z0-9_:.{}-]+$"),
)

FORBIDDEN_KEY_HINTS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\b(api[_-]?key|secret|token|bearer|password)\b"),
    re.compile(r"\.local_secrets[^\s]*"),
)


@dataclass(frozen=True)
class BridgeContract:
    bridge_id: str
    key_template: str
    source_type: SourceType
    freshness_window_seconds: int
    placeholder_state_when_absent: PlaceholderState
    used_by_pages: tuple[str, ...]
    description: str
    is_v2_native: bool


BRIDGES: tuple[BridgeContract, ...] = (
    # ── V2 native lanes ────────────────────────────────────────────────
    BridgeContract(
        bridge_id="v2_prediction_native",
        key_template="v2:prediction:{symbol}:1m",
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        freshness_window_seconds=120,
        placeholder_state_when_absent=PlaceholderState.V2_NATIVE_NOT_READY,
        used_by_pages=("ai-brain",),
        description="V2-native trainer prediction for the symbol on the 1m timeframe.",
        is_v2_native=True,
    ),
    BridgeContract(
        bridge_id="v2_paper_positions",
        key_template="v2:paper:positions",
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        freshness_window_seconds=120,
        placeholder_state_when_absent=PlaceholderState.MISSING_PAYLOAD,
        used_by_pages=("trader", "paper-trading"),
        description="Current V2 paper positions (paper/shadow only).",
        is_v2_native=True,
    ),
    BridgeContract(
        bridge_id="v2_paper_intents",
        key_template="v2:paper:intents",
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        freshness_window_seconds=120,
        placeholder_state_when_absent=PlaceholderState.MISSING_PAYLOAD,
        used_by_pages=("trader", "paper-trading"),
        description="V2 paper trade intents.",
        is_v2_native=True,
    ),
    BridgeContract(
        bridge_id="v2_paper_intents_held",
        key_template="v2:paper:intents_held_by_paper_fill_gate",
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        freshness_window_seconds=120,
        placeholder_state_when_absent=PlaceholderState.MISSING_PAYLOAD,
        used_by_pages=("trader", "paper-trading"),
        description="V2 paper intents held by the paper fill gate.",
        is_v2_native=True,
    ),
    BridgeContract(
        bridge_id="v2_paper_ledger",
        key_template="v2:paper:ledger",
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        freshness_window_seconds=300,
        placeholder_state_when_absent=PlaceholderState.MISSING_PAYLOAD,
        used_by_pages=("trader", "paper-trading", "history"),
        description="V2 paper ledger.",
        is_v2_native=True,
    ),
    BridgeContract(
        bridge_id="v2_risk_decisions",
        key_template="v2:risk:decisions",
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        freshness_window_seconds=120,
        placeholder_state_when_absent=PlaceholderState.MISSING_PAYLOAD,
        used_by_pages=("trader", "risk-control"),
        description="V2 risk gateway decisions.",
        is_v2_native=True,
    ),
    BridgeContract(
        bridge_id="v2_orchestrator_decisions",
        key_template="v2:orchestrator:decisions",
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        freshness_window_seconds=120,
        placeholder_state_when_absent=PlaceholderState.MISSING_PAYLOAD,
        used_by_pages=("trader",),
        description="V2 orchestrator decisions.",
        is_v2_native=True,
    ),
    BridgeContract(
        bridge_id="v2_market_prices",
        key_template="v2:market:prices:{symbol}",
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        freshness_window_seconds=60,
        placeholder_state_when_absent=PlaceholderState.MISSING_PAYLOAD,
        used_by_pages=("markets",),
        description="V2 market prices for the symbol (BTC/ETH/SOL today).",
        is_v2_native=True,
    ),
    BridgeContract(
        bridge_id="v2_market_funding",
        key_template="v2:market:funding:{symbol}",
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        freshness_window_seconds=300,
        placeholder_state_when_absent=PlaceholderState.MISSING_PAYLOAD,
        used_by_pages=("markets",),
        description="V2 funding rate for the symbol.",
        is_v2_native=True,
    ),
    BridgeContract(
        bridge_id="v2_market_open_interest",
        key_template="v2:market:open_interest:{symbol}",
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        freshness_window_seconds=300,
        placeholder_state_when_absent=PlaceholderState.MISSING_PAYLOAD,
        used_by_pages=("markets",),
        description="V2 open interest for the symbol.",
        is_v2_native=True,
    ),
    BridgeContract(
        bridge_id="v2_market_long_short",
        key_template="v2:market:long_short:{symbol}",
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        freshness_window_seconds=300,
        placeholder_state_when_absent=PlaceholderState.MISSING_PAYLOAD,
        used_by_pages=("markets",),
        description="V2 Binance global long/short account ratio for the symbol.",
        is_v2_native=True,
    ),
    BridgeContract(
        bridge_id="v2_market_state",
        key_template="v2:market:state",
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        freshness_window_seconds=300,
        placeholder_state_when_absent=PlaceholderState.MISSING_PAYLOAD,
        used_by_pages=("markets", "mission-control"),
        description="V2 replacement for the legacy market:state aggregate.",
        is_v2_native=True,
    ),
    BridgeContract(
        bridge_id="v2_symbol_universe_contract",
        key_template="v2:symbol_universe:contract",
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        freshness_window_seconds=600,
        placeholder_state_when_absent=PlaceholderState.MISSING_PAYLOAD,
        used_by_pages=("markets", "config"),
        description="V2 replacement for legacy config:symbols.",
        is_v2_native=True,
    ),
    BridgeContract(
        bridge_id="v2_market_liquidations_heartbeat",
        key_template="v2:market:liquidations:heartbeat",
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        freshness_window_seconds=300,
        placeholder_state_when_absent=PlaceholderState.MISSING_PAYLOAD,
        used_by_pages=("markets",),
        description="V2 liquidation WSS daemon heartbeat.",
        is_v2_native=True,
    ),
    BridgeContract(
        bridge_id="v2_dashboards_binance_top10",
        key_template="v2:dashboards:binance_top10:*",
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        freshness_window_seconds=300,
        placeholder_state_when_absent=PlaceholderState.MISSING_PAYLOAD,
        used_by_pages=("markets", "public-landing"),
        description="V2 top-10 dashboards namespace.",
        is_v2_native=True,
    ),
    BridgeContract(
        bridge_id="v2_altdata_namespace",
        key_template="v2:altdata:*",
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        freshness_window_seconds=600,
        placeholder_state_when_absent=PlaceholderState.KEY_PRESENT_NO_CLIENT_YET,
        used_by_pages=("markets", "public-landing"),
        description="Alt-data candidate publisher / symbol score namespace (paper/shadow only).",
        is_v2_native=True,
    ),

    # ── V2 bridge from legacy Redis (clearly labelled) ────────────────
    BridgeContract(
        bridge_id="legacy_prediction_multi",
        key_template="prediction:{symbol}:multi",
        source_type=SourceType.V2_BRIDGE_FROM_LEGACY_REDIS,
        freshness_window_seconds=300,
        placeholder_state_when_absent=PlaceholderState.LEGACY_BRIDGE_SOURCE,
        used_by_pages=("ai-brain",),
        description=(
            "Legacy multi-timeframe prediction. Bridge-only — exposed because"
            " V2-native prediction is not yet ready."
        ),
        is_v2_native=False,
    ),
    BridgeContract(
        bridge_id="legacy_prediction_5m",
        key_template="prediction:{symbol}:5m",
        source_type=SourceType.V2_BRIDGE_FROM_LEGACY_REDIS,
        freshness_window_seconds=300,
        placeholder_state_when_absent=PlaceholderState.LEGACY_BRIDGE_SOURCE,
        used_by_pages=("ai-brain",),
        description="Legacy 5m prediction. Bridge-only.",
        is_v2_native=False,
    ),
    BridgeContract(
        bridge_id="legacy_prediction_1m",
        key_template="prediction:{symbol}:1m",
        source_type=SourceType.V2_BRIDGE_FROM_LEGACY_REDIS,
        freshness_window_seconds=120,
        placeholder_state_when_absent=PlaceholderState.LEGACY_BRIDGE_SOURCE,
        used_by_pages=("ai-brain",),
        description="Legacy 1m prediction. Bridge-only.",
        is_v2_native=False,
    ),
    BridgeContract(
        bridge_id="legacy_signals_trading_primary",
        key_template="signals:trading:primary",
        source_type=SourceType.LEGACY_REFERENCE_ONLY,
        freshness_window_seconds=600,
        placeholder_state_when_absent=PlaceholderState.LEGACY_BRIDGE_SOURCE,
        used_by_pages=("history",),
        description=(
            "Legacy primary trading signal stream. Reference only — never used"
            " to drive V2 trading or live action."
        ),
        is_v2_native=False,
    ),
    BridgeContract(
        bridge_id="legacy_ta",
        key_template="ta:{symbol}:5m",
        source_type=SourceType.V2_BRIDGE_FROM_LEGACY_REDIS,
        freshness_window_seconds=600,
        placeholder_state_when_absent=PlaceholderState.LEGACY_BRIDGE_SOURCE,
        used_by_pages=("ai-brain", "markets"),
        description="Legacy technical-analysis indicator hash for 5m.",
        is_v2_native=False,
    ),
    BridgeContract(
        bridge_id="legacy_unified_features",
        key_template="unified_features:{symbol}:5m",
        source_type=SourceType.V2_BRIDGE_FROM_LEGACY_REDIS,
        freshness_window_seconds=600,
        placeholder_state_when_absent=PlaceholderState.LEGACY_BRIDGE_SOURCE,
        used_by_pages=("ai-brain",),
        description="Legacy 562-field unified-feature hash on the 5m timeframe.",
        is_v2_native=False,
    ),
    BridgeContract(
        bridge_id="legacy_orderbook_bids",
        key_template="orderbook:bids:{symbol}",
        source_type=SourceType.V2_BRIDGE_FROM_LEGACY_REDIS,
        freshness_window_seconds=15,
        placeholder_state_when_absent=PlaceholderState.LEGACY_BRIDGE_SOURCE,
        used_by_pages=("markets",),
        description="Legacy orderbook bids snapshot.",
        is_v2_native=False,
    ),
    BridgeContract(
        bridge_id="legacy_orderbook_asks",
        key_template="orderbook:asks:{symbol}",
        source_type=SourceType.V2_BRIDGE_FROM_LEGACY_REDIS,
        freshness_window_seconds=15,
        placeholder_state_when_absent=PlaceholderState.LEGACY_BRIDGE_SOURCE,
        used_by_pages=("markets",),
        description="Legacy orderbook asks snapshot.",
        is_v2_native=False,
    ),
    BridgeContract(
        bridge_id="legacy_liquidations_events",
        key_template="liquidations:events",
        source_type=SourceType.V2_BRIDGE_FROM_LEGACY_REDIS,
        freshness_window_seconds=600,
        placeholder_state_when_absent=PlaceholderState.KEY_PRESENT_NO_CLIENT_YET,
        used_by_pages=("markets",),
        description="Legacy liquidations event stream — bridge-only.",
        is_v2_native=False,
    ),
    BridgeContract(
        bridge_id="legacy_liq_levels",
        key_template="liq_levels:{symbol}",
        source_type=SourceType.V2_BRIDGE_FROM_LEGACY_REDIS,
        freshness_window_seconds=600,
        placeholder_state_when_absent=PlaceholderState.LEGACY_BRIDGE_SOURCE,
        used_by_pages=("markets",),
        description="Legacy liquidation levels.",
        is_v2_native=False,
    ),
    BridgeContract(
        bridge_id="legacy_coinank_features",
        key_template="features:coinank:{symbol}:1h",
        source_type=SourceType.V2_BRIDGE_FROM_LEGACY_REDIS,
        freshness_window_seconds=600,
        placeholder_state_when_absent=PlaceholderState.LEGACY_BRIDGE_SOURCE,
        used_by_pages=("markets", "ai-brain"),
        description="Legacy CoinAnk per-symbol feature hash at 1h.",
        is_v2_native=False,
    ),
    BridgeContract(
        bridge_id="legacy_coinank_global",
        key_template="features:global_coinank:*",
        source_type=SourceType.V2_BRIDGE_FROM_LEGACY_REDIS,
        freshness_window_seconds=600,
        placeholder_state_when_absent=PlaceholderState.LEGACY_BRIDGE_SOURCE,
        used_by_pages=("markets",),
        description="Legacy CoinAnk global aggregates.",
        is_v2_native=False,
    ),
    BridgeContract(
        bridge_id="legacy_heartbeats",
        key_template="heartbeat:*",
        source_type=SourceType.V2_BRIDGE_FROM_LEGACY_REDIS,
        freshness_window_seconds=300,
        placeholder_state_when_absent=PlaceholderState.LEGACY_BRIDGE_SOURCE,
        used_by_pages=("public-status",),
        description="Legacy ingestor heartbeats. Reference only.",
        is_v2_native=False,
    ),
)


_BRIDGE_IDS = {b.bridge_id for b in BRIDGES}
assert len(_BRIDGE_IDS) == len(BRIDGES), "duplicate bridge_id"


def _validate_key(key: str) -> tuple[bool, str]:
    if not isinstance(key, str) or not key:
        return False, "empty_or_non_string_key"
    for pat in FORBIDDEN_KEY_HINTS:
        if pat.search(key):
            return False, "forbidden_secret_like_token"
    for pat in ALLOWED_KEY_FAMILIES:
        if pat.match(key):
            return True, "allowed"
    return False, "not_in_allowlist"


def safe_bridge_read(key: str) -> dict[str, Any]:
    """Read one allowlisted Redis key for the bridge layer.

    Returns ``{"ok": bool, "value": Any | None, "reason": str}``.
    Never writes Redis. Never calls the exchange. Refuses any key that
    is not in ``ALLOWED_KEY_FAMILIES``. Returns ``None`` value when the
    key does not exist.
    """
    allowed, reason = _validate_key(key)
    if not allowed:
        return {"ok": False, "value": None, "reason": reason, "key": key}
    try:
        import redis  # type: ignore

        r = redis.Redis(decode_responses=True, socket_connect_timeout=2)
        r.ping()
        ktype = r.type(key)
        raw: Any
        if ktype == "string":
            raw = r.get(key)
            try:
                value = json.loads(raw) if raw is not None else None
            except Exception:  # noqa: BLE001
                value = raw
        elif ktype == "hash":
            value = r.hgetall(key)
        elif ktype == "list":
            value = r.lrange(key, 0, 0)  # only the head; never the full list
        elif ktype == "set":
            value = list(r.sscan_iter(key, count=8))[:8]
        elif ktype == "stream":
            # Streams: peek the most recent entry id only.
            try:
                entries = r.xrevrange(key, count=1)
                value = entries[0][0] if entries else None
            except Exception:  # noqa: BLE001
                value = None
        elif ktype == "none":
            value = None
        else:
            value = None
        return {"ok": True, "value": value, "reason": reason, "key": key}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "value": None, "reason": f"redis_error: {exc}", "key": key}


def list_bridge_contracts() -> dict[str, Any]:
    payload = {
        "schema_version": "v2_website_rebuild_phase_1_redis_bridge_contracts_v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "bridge_count": len(BRIDGES),
        "bridges": [
            {
                "bridge_id": b.bridge_id,
                "key_template": b.key_template,
                "source_type": b.source_type.value,
                "freshness_window_seconds": b.freshness_window_seconds,
                "placeholder_state_when_absent": b.placeholder_state_when_absent.value,
                "used_by_pages": list(b.used_by_pages),
                "description": b.description,
                "is_v2_native": b.is_v2_native,
            }
            for b in BRIDGES
        ],
        "allowed_key_family_count": len(ALLOWED_KEY_FAMILIES),
        "forbidden_key_hint_count": len(FORBIDDEN_KEY_HINTS),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "frontend_must_not_read_redis_directly": True,
    }
    return payload


# ---------------------------------------------------------------------------
# Phase-5: prediction-key resolution contract.
# ---------------------------------------------------------------------------

PREDICTION_KEY_CANDIDATE_ORDER: tuple[tuple[str, SourceType], ...] = (
    ("v2:prediction:{symbol}:1m", SourceType.V2_NATIVE_PUBLIC_PAYLOAD),
    ("prediction:{symbol}:multi", SourceType.V2_BRIDGE_FROM_LEGACY_REDIS),
    ("prediction:{symbol}:5m", SourceType.V2_BRIDGE_FROM_LEGACY_REDIS),
    ("prediction:{symbol}:1m", SourceType.V2_BRIDGE_FROM_LEGACY_REDIS),
)


def resolve_prediction_key(
    symbol: str,
    *,
    redis_reader=safe_bridge_read,
) -> dict[str, Any]:
    """Pick the first available prediction key per the documented order.

    Never claims a non-V2 source as V2-native. Always returns the source
    type of the chosen key. When no candidate is available, returns the
    explicit ``missing_reason``.
    """
    sym = symbol.upper()
    candidates_tried: list[dict[str, Any]] = []
    for tmpl, source_type in PREDICTION_KEY_CANDIDATE_ORDER:
        key = tmpl.replace("{symbol}", sym)
        read = redis_reader(key)
        candidates_tried.append({
            "key": key,
            "source_type": source_type.value,
            "ok": read.get("ok"),
            "value_present": read.get("value") is not None,
        })
        if read.get("ok") and read.get("value") is not None:
            value = read["value"]
            confidence = None
            direction = None
            freshness_seconds = None
            if isinstance(value, dict):
                confidence = value.get("confidence") or value.get("ppo_confidence")
                direction = (
                    value.get("direction")
                    or value.get("action")
                    or value.get("action_name")
                )
                ts_ms = value.get("ts_ms") or value.get("timestamp_ms")
                if isinstance(ts_ms, (int, float)) and ts_ms > 0:
                    freshness_seconds = max(0.0, time.time() - (ts_ms / 1000.0))
            return {
                "symbol": sym,
                "chosen_prediction_key": key,
                "source_type": source_type.value,
                "is_v2_native": source_type == SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
                "confidence": confidence,
                "direction": direction,
                "freshness_seconds": freshness_seconds,
                "missing_reason": None,
                "candidates_tried": candidates_tried,
                "live_gate": "blocked_human_only",
                "live_symbols": [],
            }
    return {
        "symbol": sym,
        "chosen_prediction_key": None,
        "source_type": None,
        "is_v2_native": False,
        "confidence": None,
        "direction": None,
        "freshness_seconds": None,
        "missing_reason": "no_prediction_key_present_in_any_candidate",
        "candidates_tried": candidates_tried,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }


def build_prediction_key_resolution_status(
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
    *,
    redis_reader=None,
) -> dict[str, Any]:
    reader = redis_reader if redis_reader is not None else safe_bridge_read
    per_symbol = [resolve_prediction_key(s, redis_reader=reader) for s in symbols]
    v2_native_count = sum(1 for r in per_symbol if r.get("is_v2_native"))
    bridged_count = sum(
        1 for r in per_symbol if r.get("source_type") == "V2_BRIDGE_FROM_LEGACY_REDIS"
    )
    missing = sum(1 for r in per_symbol if r["chosen_prediction_key"] is None)
    return {
        "schema_version": "v2_website_rebuild_phase_1_prediction_key_resolution_v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "candidate_order": [
            {"key_template": t, "source_type": st.value}
            for (t, st) in PREDICTION_KEY_CANDIDATE_ORDER
        ],
        "per_symbol": per_symbol,
        "symbol_count": len(symbols),
        "v2_native_count": v2_native_count,
        "bridged_count": bridged_count,
        "missing_count": missing,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
