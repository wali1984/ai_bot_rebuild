"""V2 native per-symbol liquidation source classifier + Redis writer
contract (paper-only, public-data-first).

Decides whether V2 can compute per-symbol liquidation observations
from an approved native source today. Public Binance Futures
``!forceOrder@arr`` is a continuous WebSocket stream (no auth) — V2
needs an operator-approved WSS client scope before adopting it. This
module never opens a connection; it only classifies the source state
and defines the write contract for future ingestion.

V2 Redis keys this module is permitted to write (all under v2:*):

- ``v2:market:liquidations:{symbol}``               — latest event
- ``v2:market:liquidations:latest:{symbol}``        — latest snapshot
- ``v2:market:liquidations:aggregate:{symbol}``     — 1h/24h aggregates
- ``v2:market:liquidations:heartbeat``              — ingestor status

NEVER imports torch. NEVER deserializes any blob. NEVER touches legacy
filesystem. NEVER writes any non-v2 Redis key. NEVER fabricates
events.
"""
from __future__ import annotations

import dataclasses
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

V2_REDIS_PREFIX = "v2:"
V2_LIQUIDATION_KEY_PATTERNS = (
    "v2:market:liquidations:{symbol}",
    "v2:market:liquidations:latest:{symbol}",
    "v2:market:liquidations:aggregate:{symbol}",
    "v2:market:liquidations:heartbeat",
)

# Source-classification states.
SOURCE_AVAILABLE_V2_NATIVE = "V2_PER_SYMBOL_LIQUIDATION_SOURCE_AVAILABLE_V2_NATIVE"
SOURCE_BLOCKED_BY_SOURCE_UNAVAILABLE = (
    "V2_PER_SYMBOL_LIQUIDATION_SOURCE_BLOCKED_BY_SOURCE_UNAVAILABLE"
)
SOURCE_BLOCKED_BY_OPERATOR_DECISION = (
    "V2_PER_SYMBOL_LIQUIDATION_SOURCE_BLOCKED_BY_OPERATOR_DECISION"
)
SOURCE_BLOCKED_BY_RATE_LIMIT = (
    "V2_PER_SYMBOL_LIQUIDATION_SOURCE_BLOCKED_BY_RATE_LIMIT"
)


@dataclasses.dataclass(frozen=True)
class LiquidationSourceClassification:
    classification: str
    rationale: str
    operator_decision_required: bool
    public_no_credential_path_known: bool
    public_no_credential_path_description: str | None
    v2_write_contract: tuple[str, ...]


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def classify_liquidation_source() -> LiquidationSourceClassification:
    """Static classification: no network IO. Reads env-name probes only.

    Today V2 has no operator-approved continuous WebSocket client
    targeting `!forceOrder@arr`, and there is no public REST endpoint
    for per-symbol Binance Futures liquidation history without auth.
    The public WSS path is known and documented, but adopting it is an
    operator-scoped decision (process lifetime, reconnect policy, rate
    limit, storage cap).
    """
    public_path_description = (
        "wss://fstream.binance.com/market/ws/!forceOrder@arr "
        "(Binance Futures public liquidation stream; no API key required; "
        "requires a continuous WSS client with operator-approved scope, "
        "reconnect policy, and storage retention cap)."
    )
    # If a future V2 WSS client opts in by setting V2_LIQUIDATION_WSS_OPT_IN
    # in .env, we can flip the classification. Default today: blocked by
    # operator decision (no opt-in).
    if os.environ.get("V2_LIQUIDATION_WSS_OPT_IN") == "true":
        return LiquidationSourceClassification(
            classification=SOURCE_AVAILABLE_V2_NATIVE,
            rationale=(
                "Operator opt-in observed via V2_LIQUIDATION_WSS_OPT_IN=true. "
                "Adopt the public Binance Futures forceOrder WebSocket "
                "stream under V2-owned client."
            ),
            operator_decision_required=False,
            public_no_credential_path_known=True,
            public_no_credential_path_description=public_path_description,
            v2_write_contract=V2_LIQUIDATION_KEY_PATTERNS,
        )
    return LiquidationSourceClassification(
        classification=SOURCE_BLOCKED_BY_OPERATOR_DECISION,
        rationale=(
            "No V2-native per-symbol liquidation client is currently "
            "running. Public Binance Futures forceOrder WSS path is "
            "known (no credentials required) but requires operator "
            "approval to scope a long-running V2-owned WSS client with "
            "reconnect/backoff/storage retention rules. Today: BLOCKED "
            "by operator decision."
        ),
        operator_decision_required=True,
        public_no_credential_path_known=True,
        public_no_credential_path_description=public_path_description,
        v2_write_contract=V2_LIQUIDATION_KEY_PATTERNS,
    )


def aggregator_keys_present(redis_client: Any, symbol: str) -> dict[str, bool]:
    """Probe whether any V2 *per-symbol* liquidation Redis keys are
    populated for the given symbol. The global heartbeat key is
    excluded from per-symbol counting.
    """
    result: dict[str, bool] = {}
    per_symbol_patterns = tuple(
        p for p in V2_LIQUIDATION_KEY_PATTERNS if "{symbol}" in p
    )
    if redis_client is None:
        for pat in per_symbol_patterns:
            result[pat.format(symbol=symbol)] = False
        return result
    for pat in per_symbol_patterns:
        key = pat.format(symbol=symbol)
        try:
            raw = redis_client.get(key)
        except Exception:
            raw = None
        result[key] = bool(raw)
    return result


def build_ingestor_status(
    redis_client: Any = None,
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
) -> dict[str, Any]:
    cls = classify_liquidation_source()
    heartbeat_available = False
    heartbeat_payload: dict[str, Any] | None = None
    if redis_client is not None:
        try:
            raw_hb = redis_client.get("v2:market:liquidations:heartbeat")
            heartbeat_ttl = redis_client.ttl("v2:market:liquidations:heartbeat")
            if raw_hb and heartbeat_ttl > 0:
                heartbeat_available = True
                try:
                    parsed_hb = json.loads(raw_hb)
                    heartbeat_payload = parsed_hb if isinstance(parsed_hb, dict) else None
                except Exception:
                    heartbeat_payload = None
        except Exception:
            heartbeat_available = False
    if heartbeat_available:
        cls = LiquidationSourceClassification(
            classification=SOURCE_AVAILABLE_V2_NATIVE,
            rationale=(
                "V2-native liquidation WSS heartbeat is fresh in Redis. "
                "The public Binance Futures forceOrder stream is running "
                "under V2 paper/shadow scope; zero events is valid when no "
                "matching forceOrder events have arrived in the current window."
            ),
            operator_decision_required=False,
            public_no_credential_path_known=True,
            public_no_credential_path_description=(
                heartbeat_payload.get("url") if heartbeat_payload else None
            ),
            v2_write_contract=V2_LIQUIDATION_KEY_PATTERNS,
        )
    per_symbol: list[dict[str, Any]] = []
    aggregate_populated_count = 0
    for sym in symbols:
        keys_present = aggregator_keys_present(redis_client, sym)
        any_populated = any(keys_present.values())
        if any_populated:
            aggregate_populated_count += 1
        per_symbol.append(
            {
                "symbol": sym,
                "redis_keys_populated": keys_present,
                "any_populated": any_populated,
            }
        )
    return {
        "schema_version": "v2_liquidation_ingestor_status_v1",
        "generated_utc": _utc_iso(),
        "go_no_go": (
            "V2_PER_SYMBOL_LIQUIDATION_SOURCE_READY"
            if cls.classification == SOURCE_AVAILABLE_V2_NATIVE
            else "V2_PER_SYMBOL_LIQUIDATION_SOURCE_BLOCKED"
        ),
        "source_classification": cls.classification,
        "rationale": cls.rationale,
        "operator_decision_required": cls.operator_decision_required,
        "v2_wss_heartbeat_available": heartbeat_available,
        "v2_wss_heartbeat": heartbeat_payload,
        "public_no_credential_path_known": cls.public_no_credential_path_known,
        "public_no_credential_path_description": cls.public_no_credential_path_description,
        "v2_write_contract": list(cls.v2_write_contract),
        "symbols": list(symbols),
        "per_symbol_redis_state": per_symbol,
        "symbols_with_any_v2_liquidation_key_populated_count": aggregate_populated_count,
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
        "no_synthetic_liquidation_events": True,
        "no_torch_imported": True,
        "no_pickle_loaded": True,
        "no_legacy_filesystem_modified": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }


def write_heartbeat(redis_client: Any, payload: dict[str, Any]) -> bool:
    """Write the V2 liquidation ingestor heartbeat key. Refuses any
    non-v2:* key path. Returns whether the write occurred.
    """
    if redis_client is None:
        return False
    key = "v2:market:liquidations:heartbeat"
    if not key.startswith(V2_REDIS_PREFIX):  # pragma: no cover - defensive
        return False
    try:
        redis_client.set(key, json.dumps(payload), ex=300)
        return True
    except Exception:
        return False
