"""V2 Binance public-metadata ingestor (read-only, paper-safe).

Reads Binance WebSocket-backed Redis/cache data first for mark-price /
funding / open-interest / orderbook signals. Public REST is fallback-only and
requires ``BINANCE_REST_FALLBACK_ALLOWED=true``. Writes only ``v2:market:*``
Redis keys and a public payload. Never makes a signed request, never calls a
mutation endpoint, never reads or prints any credential value.

Fallback endpoints (all public, no auth):
  * ``/fapi/v1/premiumIndex`` -> mark price + funding rate per symbol
  * ``/fapi/v1/openInterest`` -> open interest per symbol
  * ``/fapi/v1/depth?limit=20`` -> top-of-book orderbook per symbol

The loop emits a heartbeat per cycle and an aggregated public payload
under ``v2/frontend/public/v2_binance_public_metadata/latest/``.

Hard rules (enforced by code + tests):
  * no ``order``, ``leverage``, ``margin``, ``transfer``, ``withdraw`` token
    in any code path here
  * no signed request
  * ``LIVE_GATE = blocked_human_only`` throughout
  * Redis writes use only the ``v2:market:*`` namespace
  * one TTL applied to every Redis key
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo


EST = ZoneInfo("America/New_York")
REPO = Path("/home/wali/Desktop/AI BOT REBUILD")
FAPI_BASE = "https://fapi.binance.com"

# NOTE: V2_DYNAMIC_SYMBOL_AND_COPIED_COMPONENT_RUNTIME_REMEDIATION removed the
# legacy 3-symbol default; the resolver in
# ``v2.backend.app.services.v2_symbol_runtime_universe`` is the single source
# of truth. The 3 symbols below are smoke-test-only and surfaced only when
# ``--smoke-test`` or ``V2_SYMBOL_PROFILE=smoke_test`` is set.
from v2.backend.app.services.v2_symbol_runtime_universe import (  # noqa: E402
    resolve_symbols,
)
from v2.backend.app.services.binance_unified_websocket_transport import (  # noqa: E402
    REST_FALLBACK_ENV,
    binance_rest_fallback_allowed,
    report_binance_rest_response,
    require_binance_rest_fallback,
)
# Shared CoinAnk open-interest backup mapper (contracts; single source of
# truth for provider-tier semantics lives in the native ingestors loop).
from v2.backend.app.cli.v2_native_ingestors_live_loop import (  # noqa: E402
    _coinank_point_open_interest,
)
DEFAULT_INTERVAL_S = 30
DEFAULT_TTL_S = 300
HTTP_TIMEOUT_S = 6.0

LIVE_GATE = "blocked_human_only"

# This is an upstream publication-cadence safety bound, not an entry or
# strategy threshold.  Both metadata loops read keys they also write; without
# an event-time age check a dead premium-index sample can be re-published with
# a fresh Redis TTL forever.
PREMIUM_INDEX_CACHE_MAX_AGE_SECONDS = 120.0

PUBLIC_OUT_DIR = REPO / "v2/frontend/public/v2_binance_public_metadata/latest"


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON number rejected: {value}")


def _est_iso() -> str:
    return datetime.now(EST).strftime("%Y-%m-%dT%H:%M:%S%z")


def _http_get_json(url: str) -> Any:
    try:
        require_binance_rest_fallback(
            endpoint=urllib.parse.urlparse(url).path or url,
            fallback_reason="public_metadata_websocket_cache_missing",
            role="public_metadata_cache_recovery",
        )
    except RuntimeError as exc:
        message = str(exc).replace(
            "REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY",
            "BINANCE_REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY",
            1,
        )
        raise RuntimeError(message) from exc
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            return json.loads(
                resp.read().decode(),
                parse_constant=_reject_nonfinite_json,
            )
    except urllib.error.HTTPError as exc:
        # Ban protection: 429/418 arms the shared cross-process cooldown so
        # ALL Binance fallback traffic on this host stops before escalation.
        if "binance.com" in url:
            try:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
            except Exception:
                retry_after = None
            report_binance_rest_response(
                status_code=int(exc.code),
                retry_after_seconds=float(retry_after) if retry_after else None,
            )
        raise


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
        return json.loads(
            raw if isinstance(raw, str) else raw.decode("utf-8", errors="ignore"),
            parse_constant=_reject_nonfinite_json,
        )
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _cache_transport(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "websocket_cache_primary"
    provenance = " ".join(
        str(payload.get(field) or "") for field in ("source", "transport")
    ).lower()
    return "rest_fallback_cache" if "rest" in provenance else "websocket_cache_primary"


def _premium_index_cache_event_epoch_seconds(payload: dict[str, Any]) -> float | None:
    """Return a non-future producer event epoch for candidate ordering."""
    event_value = (
        payload.get("event_time")
        or payload.get("time")
        or payload.get("timestamp")
        or payload.get("binance_time_ms")
        or payload.get("E")
    )
    event_number = _safe_float(event_value)
    if event_number is not None and event_number > 0:
        epoch_seconds = event_number / 1000.0 if event_number > 10_000_000_000 else event_number
    elif isinstance(event_value, str) and event_value:
        try:
            parsed = datetime.fromisoformat(event_value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        epoch_seconds = parsed.timestamp()
    else:
        return None
    return epoch_seconds if epoch_seconds <= time.time() else None


def _premium_index_cache_age_seconds(payload: dict[str, Any]) -> float | None:
    """Return source-event age; never use a refreshed Redis TTL as freshness."""
    event_epoch_seconds = _premium_index_cache_event_epoch_seconds(payload)
    return (
        time.time() - event_epoch_seconds
        if event_epoch_seconds is not None
        else None
    )


def _premium_index_cache_candidates(
    symbol: str,
    *,
    redis_client: Any,
) -> list[tuple[str, dict[str, Any]]]:
    candidates: list[tuple[str, dict[str, Any]]] = []
    for key in (
        f"v2:market:mark_price:{symbol}",
        f"v2:market:funding:{symbol}",
        f"v2:market:prices:{symbol}",
    ):
        payload = _read_json(redis_client, key)
        if not isinstance(payload, dict):
            continue
        if key.endswith(f"prices:{symbol}") and isinstance(payload.get("funding"), dict):
            candidates.append((f"{key}.funding", payload["funding"]))
        candidates.append((key, payload))
    return candidates


def fetch_premium_index(symbol: str, *, redis_client: Any = None) -> Dict[str, Any]:
    valid_candidates: list[tuple[float, bool, str, dict[str, Any], float, float, float | None]] = []
    for source_key, source_payload in _premium_index_cache_candidates(
        symbol,
        redis_client=redis_client,
    ):
        event_epoch_seconds = _premium_index_cache_event_epoch_seconds(source_payload)
        if event_epoch_seconds is None:
            continue
        if time.time() - event_epoch_seconds > PREMIUM_INDEX_CACHE_MAX_AGE_SECONDS:
            continue
        mark_price = _safe_float(source_payload.get("mark_price") or source_payload.get("markPrice"))
        index_price = _safe_float(source_payload.get("index_price") or source_payload.get("indexPrice"))
        funding_rate = _safe_float(
            source_payload.get("lastFundingRate")
            or source_payload.get("last_funding_rate")
            or source_payload.get("funding_rate")
        )
        if (
            mark_price is None
            or index_price is None
            or mark_price <= 0.0
            or index_price <= 0.0
        ):
            continue
        valid_candidates.append(
            (
                event_epoch_seconds,
                _cache_transport(source_payload) == "websocket_cache_primary",
                source_key,
                source_payload,
                mark_price,
                index_price,
                funding_rate,
            )
        )
    if valid_candidates:
        (
            _,
            _,
            source_key,
            source_payload,
            mark_price,
            index_price,
            funding_rate,
        ) = max(valid_candidates, key=lambda candidate: (candidate[0], candidate[1]))
        observed_at = _utc_now_iso()
        event_time = (
            source_payload.get("event_time")
            or source_payload.get("time")
            or source_payload.get("timestamp")
            or source_payload.get("binance_time_ms")
            or source_payload.get("E")
        )
        binance_time_ms: int | None = None
        raw_binance_time = (
            source_payload.get("binance_time_ms")
            or source_payload.get("time")
            or source_payload.get("E")
        )
        parsed_binance_time = _safe_float(raw_binance_time)
        if parsed_binance_time is not None and parsed_binance_time >= 10_000_000_000:
            binance_time_ms = int(parsed_binance_time)
        source_generated_at = source_payload.get("generated_at")
        source_available_at = source_payload.get("available_at") or source_payload.get(
            "received_at"
        )
        source_update_interval = _safe_float(
            source_payload.get("expected_update_interval_seconds")
        )
        if source_update_interval is not None and source_update_interval <= 0.0:
            source_update_interval = None
        return {
            "symbol": symbol,
            "mark_price": mark_price,
            "index_price": index_price,
            "estimated_settle_price": _safe_float(
                source_payload.get("estimatedSettlePrice")
                or source_payload.get("estimated_settle_price")
            ),
            "last_funding_rate": funding_rate,
            "next_funding_time_ms": source_payload.get("nextFundingTime")
            or source_payload.get("next_funding_time_ms"),
            "interest_rate": _safe_float(
                source_payload.get("interestRate") or source_payload.get("interest_rate")
            ),
            "binance_time_ms": binance_time_ms,
            "event_time": event_time,
            "generated_at": source_generated_at,
            "available_at": source_available_at,
            "consumer_observed_at": observed_at,
            "republished_at": observed_at,
            "expected_update_interval_seconds": source_update_interval,
            "source_key": source_key,
            "source": source_payload.get("source")
            or "binance_public_websocket_cache_primary",
            "transport": _cache_transport(source_payload),
        }
    body = _http_get_json(
        f"{FAPI_BASE}/fapi/v1/premiumIndex?symbol={urllib.parse.quote(symbol)}"
    )
    if not isinstance(body, dict):
        raise ValueError("BINANCE_PREMIUM_INDEX_RESPONSE_NOT_OBJECT")
    mark_price = _safe_float(body.get("markPrice"))
    index_price = _safe_float(body.get("indexPrice"))
    if mark_price is None or index_price is None or mark_price <= 0.0 or index_price <= 0.0:
        raise ValueError("BINANCE_PREMIUM_INDEX_RESPONSE_PRICE_INVALID")
    observed_at = _utc_now_iso()
    out: Dict[str, Any] = {
        "symbol": body.get("symbol"),
        "mark_price": mark_price,
        "index_price": index_price,
        "estimated_settle_price": _safe_float(body.get("estimatedSettlePrice")),
        "last_funding_rate": _safe_float(body.get("lastFundingRate")),
        "next_funding_time_ms": body.get("nextFundingTime"),
        "interest_rate": _safe_float(body.get("interestRate")),
        "binance_time_ms": body.get("time"),
        "event_time": body.get("time"),
        "generated_at": observed_at,
        "available_at": observed_at,
        "consumer_observed_at": observed_at,
        "republished_at": observed_at,
        "expected_update_interval_seconds": float(DEFAULT_INTERVAL_S),
        "source": "binance_public_rest_premium_index_fallback",
        "transport": "rest_fallback",
    }
    return out


# An open-interest cache payload older than this — or carrying no timestamp
# at all — must NOT be echoed back into v2:market:open_interest:*: this fetch
# reads its OWN output key (also written by the native ingestors loop), and
# the 2026-07-16 18:03Z incident left an UNDATED payload echoing between the
# two services forever while REST stayed unreachable. The old echo also
# re-mapped time/timestamp into binance_time_ms without ever reading
# binance_time_ms back, so the first echo destroyed the timestamp and every
# later cycle re-published an undated snapshot. Same bug class as the
# ticker/orderbook cache-echo fixes.
OPEN_INTEREST_CACHE_MAX_AGE_SECONDS = 120.0


def _utc_now_iso() -> str:
    return (
        datetime.now(ZoneInfo("UTC"))
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _open_interest_cache_age_seconds(payload: Dict[str, Any]) -> Optional[float]:
    """Age of an open-interest cache payload, or None when it is undated."""
    event_ms = _safe_float(
        payload.get("time") or payload.get("timestamp") or payload.get("binance_time_ms")
    )
    if event_ms is not None and event_ms > 0:
        return max(0.0, time.time() - event_ms / 1000.0)
    for field in ("fetched_utc", "available_at"):
        value = payload.get(field)
        if isinstance(value, str) and value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
            return max(0.0, time.time() - parsed.timestamp())
    return None


def fetch_open_interest(symbol: str, *, redis_client: Any = None) -> Dict[str, Any]:
    cached = _read_json(redis_client, f"v2:market:open_interest:{symbol}")
    if isinstance(cached, dict) and cached:
        value = _safe_float(
            cached.get("open_interest_contracts")
            or cached.get("openInterest")
            or cached.get("open_interest")
        )
        cache_age = _open_interest_cache_age_seconds(cached)
        if (
            value is not None
            and cache_age is not None
            and cache_age <= OPEN_INTEREST_CACHE_MAX_AGE_SECONDS
        ):
            # Fresh, dated payload: echo it while PRESERVING its original
            # timestamps (re-stamping an echo would launder staleness).
            return {
                "symbol": cached.get("symbol") or symbol,
                "open_interest": value,
                "open_interest_contracts": value,
                "binance_time_ms": (
                    cached.get("time")
                    or cached.get("timestamp")
                    or cached.get("binance_time_ms")
                ),
                "fetched_utc": cached.get("fetched_utc") or cached.get("available_at"),
                "source": cached.get("source") or "binance_public_websocket_cache_primary",
                "transport": _cache_transport(cached),
            }
        # Stale or undated cache payload: fail closed on the echo and fall
        # through to the provider-backup tier / public REST snapshot.
    provider = _coinank_point_open_interest(symbol, redis_client=redis_client)
    if isinstance(provider, dict):
        provider_age = _open_interest_cache_age_seconds(provider)
        if provider_age is not None and provider_age <= OPEN_INTEREST_CACHE_MAX_AGE_SECONDS:
            # CoinAnk rows (contracts) as fresh as the cache bar: prefer them
            # over REST to conserve the shared Binance fallback budget.
            return {
                **provider,
                "open_interest_contracts": provider.get("open_interest"),
                "binance_time_ms": provider.get("time"),
            }
    body = _http_get_json(
        f"{FAPI_BASE}/fapi/v1/openInterest?symbol={urllib.parse.quote(symbol)}"
    )
    value = _safe_float(body.get("openInterest"))
    return {
        "symbol": body.get("symbol"),
        # ``open_interest`` is the canonical field the feature pipeline reads
        # (open_interest/openInterest/sumOpenInterest); keep the legacy
        # ``open_interest_contracts`` alias for existing GUI consumers.
        "open_interest": value,
        "open_interest_contracts": value,
        "binance_time_ms": body.get("time"),
        "fetched_utc": _utc_now_iso(),
        "source": "binance_public_rest_open_interest_fallback",
        "transport": "rest_fallback",
    }


# A cached order book older than this must NOT be echoed into
# v2:market:orderbook_top:* — the keys read below are written by the direct
# recorder / native ingestors loop, and when their upstream WSS transport
# dies the frozen snapshot would otherwise propagate here forever while the
# public REST depth fallback stays unreachable (2026-07-16 incident: books
# frozen at 18:03:18Z for 4.5h). Same bug class as the ticker cache-echo fix.
ORDERBOOK_CACHE_MAX_AGE_SECONDS = 120.0


def _orderbook_cache_age_seconds(payload: Dict[str, Any]) -> Optional[float]:
    for field in ("available_at", "received_at", "generated_at", "fetched_utc"):
        value = payload.get(field)
        if isinstance(value, str) and value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
            return max(0.0, time.time() - parsed.timestamp())
    # REST depth snapshots carry Binance ms timestamps and no ISO fields.
    event_ms = _safe_float(payload.get("E") or payload.get("T") or payload.get("ev_time_ms"))
    if event_ms is not None and event_ms > 0:
        return max(0.0, time.time() - event_ms / 1000.0)
    return None


def fetch_orderbook(symbol: str, limit: int = 20, *, redis_client: Any = None) -> Dict[str, Any]:
    for key in (
        f"v2:orderbook:top:binance:{symbol}",
        f"v2:market:orderbook:binance:{symbol}",
        f"v2:market:orderbook:{symbol}",
    ):
        cached = _read_json(redis_client, key)
        if not isinstance(cached, dict):
            continue
        cache_age = _orderbook_cache_age_seconds(cached)
        if cache_age is None or cache_age > ORDERBOOK_CACHE_MAX_AGE_SECONDS:
            # Stale or undated cache payload: fail closed on the echo and
            # fall through to the next source / REST depth snapshot.
            continue
        bids = cached.get("bids") if isinstance(cached.get("bids"), list) else []
        asks = cached.get("asks") if isinstance(cached.get("asks"), list) else []
        best_bid = _safe_float(cached.get("best_bid") or cached.get("bid"))
        best_ask = _safe_float(cached.get("best_ask") or cached.get("ask"))
        if best_bid is None and bids:
            first = bids[0]
            best_bid = _safe_float(first[0] if isinstance(first, (list, tuple)) and first else None)
        if best_ask is None and asks:
            first = asks[0]
            best_ask = _safe_float(first[0] if isinstance(first, (list, tuple)) and first else None)
        if best_bid is None and best_ask is None:
            continue
        mid = (best_bid + best_ask) / 2 if best_bid is not None and best_ask is not None else None
        spread_bps = ((best_ask - best_bid) / mid) * 1e4 if mid and best_bid is not None and best_ask is not None else None
        return {
            "symbol": symbol,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid": mid,
            "spread_bps": spread_bps,
            "bid_levels": len(bids),
            "ask_levels": len(asks),
            # Carry the level arrays through: downstream derived-feature
            # consumers (v2:orderbook:features publisher, cascade squeeze
            # inputs, tensor depth features) need the actual book, and the
            # summary-only payload stranded 42+ universe symbols without any
            # usable depth evidence (2026-07-16 coverage census).
            "bids": bids,
            "asks": asks,
            "update_id": cached.get("lastUpdateId") or cached.get("update_id"),
            "ev_time_ms": cached.get("E") or cached.get("event_time"),
            "received_at": cached.get("received_at") or cached.get("available_at"),
            "available_at": cached.get("available_at") or cached.get("received_at"),
            "source": cached.get("source") or "binance_public_websocket_orderbook_cache_primary",
            "transport": _cache_transport(cached),
            "source_key": key,
        }
    body = _http_get_json(
        f"{FAPI_BASE}/fapi/v1/depth?symbol={urllib.parse.quote(symbol)}&limit={limit}"
    )
    bids = [[float(p), float(q)] for p, q in body.get("bids", [])[:limit]]
    asks = [[float(p), float(q)] for p, q in body.get("asks", [])[:limit]]
    best_bid = bids[0][0] if bids else None
    best_ask = asks[0][0] if asks else None
    spread_bps = None
    mid = None
    if best_bid is not None and best_ask is not None and best_ask > 0:
        mid = (best_bid + best_ask) / 2
        spread_bps = ((best_ask - best_bid) / mid) * 1e4 if mid else None
    fetched_iso = datetime.now(ZoneInfo("UTC")).isoformat(timespec="milliseconds")
    return {
        "symbol": symbol,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid": mid,
        "spread_bps": spread_bps,
        "bid_levels": len(bids),
        "ask_levels": len(asks),
        "bids": bids,
        "asks": asks,
        "update_id": body.get("lastUpdateId"),
        "ev_time_ms": body.get("E"),
        "event_time": body.get("E"),
        "transaction_time": body.get("T"),
        "received_at": fetched_iso,
        "available_at": fetched_iso,
        "source": "binance_public_rest_depth_snapshot_fallback",
        "transport": "rest_fallback",
    }


def _rest_endpoint_used(field_name: str, payload: Any) -> str | None:
    if not isinstance(payload, dict) or payload.get("transport") != "rest_fallback":
        return None
    return {
        "premium_index": "/fapi/v1/premiumIndex",
        "open_interest": "/fapi/v1/openInterest",
        "orderbook_top": "/fapi/v1/depth",
    }.get(field_name)


def _rest_fallback_blocked_errors(entry: Dict[str, Any]) -> int:
    count = 0
    for key in ("premium_index_error", "open_interest_error", "orderbook_error"):
        value = entry.get(key)
        if isinstance(value, str) and "BINANCE_REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY" in value:
            count += 1
    return count


def _redis_client():
    try:
        import redis  # type: ignore
    except ImportError:
        return None
    try:
        r = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _orderbook_gap_fill_payload(r, symbol: str, book: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Raw-book gap-fill for symbols the WSS depth transport does not cover.

    ``v2:market:orderbook:{symbol}`` is the canonical raw-book key every
    downstream consumer (trainer tensor, cascade squeeze inputs, orderbook
    feature derivation) reads. The WSS transport maintains it for only part
    of the universe; for the rest this ingestor already fetched a REST depth
    snapshot each cycle and then threw the arrays away. Persist them —
    but never fight a live writer: only when the existing key is missing or
    older than ORDERBOOK_CACHE_MAX_AGE_SECONDS.
    """
    bids = book.get("bids") if isinstance(book.get("bids"), list) else []
    asks = book.get("asks") if isinstance(book.get("asks"), list) else []
    if not bids or not asks:
        return None
    existing = _read_json(r, f"v2:market:orderbook:{symbol}")
    if isinstance(existing, dict):
        age = _orderbook_cache_age_seconds(existing)
        if age is not None and age <= ORDERBOOK_CACHE_MAX_AGE_SECONDS:
            return None
    return {
        "symbol": symbol,
        "exchange": "binance",
        "bids": bids,
        "asks": asks,
        "lastUpdateId": book.get("update_id"),
        "E": book.get("ev_time_ms") or book.get("event_time"),
        "T": book.get("transaction_time"),
        "event_time": book.get("ev_time_ms") or book.get("event_time"),
        "received_at": book.get("received_at"),
        "available_at": book.get("available_at"),
        "fetched_utc": _est_iso(),
        "source": book.get("source") or "binance_public_rest_depth_snapshot_fallback",
        "transport": book.get("transport") or "rest_fallback",
        "gap_fill_writer": "v2_binance_public_metadata_ingestor",
    }


def write_redis(r, symbol: str, *, premium: Dict[str, Any], oi: Dict[str, Any],
                book: Dict[str, Any], ttl_s: int) -> Dict[str, int]:
    """Write three V2 keys per symbol with the configured TTL."""
    if r is None:
        return {"v2:market:mark_price": 0, "v2:market:open_interest": 0, "v2:market:orderbook_top": 0}
    written: Dict[str, int] = {}
    payloads = [
        (f"v2:market:mark_price:{symbol}", premium),
        (f"v2:market:open_interest:{symbol}", oi),
        (f"v2:market:orderbook_top:{symbol}", book),
    ]
    gap_fill = _orderbook_gap_fill_payload(r, symbol, book if isinstance(book, dict) else {})
    if gap_fill is not None:
        # Longer TTL than the summary keys: under the shared REST budget a
        # WSS-uncovered symbol only wins a depth call every few minutes, so a
        # short TTL made its book blink out between refreshes. The payload
        # carries received_at/available_at — readers see the true age.
        try:
            r.set(
                f"v2:market:orderbook:{symbol}",
                json.dumps(gap_fill, separators=(",", ":")),
                ex=max(ttl_s, 1200),
            )
            written[f"v2:market:orderbook:{symbol}"] = 1
        except Exception:
            written[f"v2:market:orderbook:{symbol}"] = 0
    for key, payload in payloads:
        # Fail closed: when every fetch tier failed the entry is an empty
        # dict — never overwrite a real (even expiring) payload with ``{}``
        # (2026-07-16 incident class: empty-object writes masking outages).
        if not payload:
            written[key] = 0
            continue
        try:
            r.set(key, json.dumps(payload, separators=(",", ":")), ex=ttl_s)
            written[key] = 1
        except Exception:
            written[key] = 0
    return written


def run_once(symbols: List[str], *, ttl_s: int) -> Dict[str, Any]:
    started_at = _est_iso()
    r = _redis_client()
    redis_available = r is not None
    per_symbol: Dict[str, Any] = {}
    error_count = 0
    write_count = 0
    for symbol in symbols:
        entry: Dict[str, Any] = {"symbol": symbol}
        try:
            entry["premium_index"] = fetch_premium_index(symbol, redis_client=r)
        except Exception as e:
            entry["premium_index_error"] = str(e)
            error_count += 1
        try:
            entry["open_interest"] = fetch_open_interest(symbol, redis_client=r)
        except Exception as e:
            entry["open_interest_error"] = str(e)
            error_count += 1
        try:
            entry["orderbook_top"] = fetch_orderbook(symbol, redis_client=r)
        except Exception as e:
            entry["orderbook_error"] = str(e)
            error_count += 1
        wrote = write_redis(
            r,
            symbol,
            premium=entry.get("premium_index", {}),
            oi=entry.get("open_interest", {}),
            book=entry.get("orderbook_top", {}),
            ttl_s=ttl_s,
        )
        entry["redis_keys_written"] = wrote
        write_count += sum(wrote.values())
        per_symbol[symbol] = entry
    cache_primary_count = sum(
        1
        for entry in per_symbol.values()
        for payload in (entry.get("premium_index"), entry.get("open_interest"), entry.get("orderbook_top"))
        if isinstance(payload, dict) and payload.get("transport") in {"websocket_cache_primary", "rest_fallback_cache"}
    )
    rest_fallback_count = sum(
        1
        for entry in per_symbol.values()
        for payload in (entry.get("premium_index"), entry.get("open_interest"), entry.get("orderbook_top"))
        if isinstance(payload, dict) and payload.get("transport") == "rest_fallback"
    )
    endpoints_used_this_cycle = sorted(
        {
            endpoint
            for entry in per_symbol.values()
            for field_name in ("premium_index", "open_interest", "orderbook_top")
            for endpoint in [_rest_endpoint_used(field_name, entry.get(field_name))]
            if endpoint
        }
    )
    rest_fallback_blocked_count = sum(_rest_fallback_blocked_errors(entry) for entry in per_symbol.values())
    finished_at = _est_iso()
    return {
        "started_at_est": started_at,
        "finished_at_est": finished_at,
        "symbols": symbols,
        "redis_available": redis_available,
        "redis_keys_written_total": write_count,
        "errors": error_count,
        "per_symbol": per_symbol,
        "cache_primary_field_count": cache_primary_count,
        "rest_fallback_field_count": rest_fallback_count,
        "live_gate": LIVE_GATE,
        "writes_exchange_orders": False,
        "transport_policy": "binance_public_websocket_cache_primary_rest_fallback_only",
        "rest_fallback_allowed": binance_rest_fallback_allowed(),
        "rest_fallback_env": REST_FALLBACK_ENV,
        "rest_used_as_primary": False,
        "endpoints_used_this_cycle": endpoints_used_this_cycle,
        "rest_fallback_blocked_count": rest_fallback_blocked_count,
        "rest_fallback_endpoints": [
            "/fapi/v1/premiumIndex",
            "/fapi/v1/openInterest",
            "/fapi/v1/depth",
        ],
        "endpoints_never_called": [
            "/fapi/v1/order",
            "/fapi/v1/order/test",
            "/fapi/v1/leverage",
            "/fapi/v1/marginType",
            "/sapi/v1/futures/transfer",
            "/sapi/v1/capital/withdraw",
        ],
    }


def write_public_payload(report: Dict[str, Any]) -> Path:
    PUBLIC_OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = PUBLIC_OUT_DIR / "operator_dashboard_payload.json"
    with target.open("w") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return target


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbols", default=None,
                   help="comma-separated; defaults to dynamic-universe + 25 baseline")
    p.add_argument("--smoke-test", action="store_true",
                   help="opt in to the 3-symbol smoke-test set (never the production default)")
    p.add_argument("--once", action="store_true")
    p.add_argument("--loop", action="store_true")
    p.add_argument("--interval-seconds", type=int, default=DEFAULT_INTERVAL_S)
    p.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_S)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    symbols = resolve_symbols(
        explicit=args.symbols, smoke_test=args.smoke_test, include_baseline=True
    )
    if not (args.once or args.loop):
        args.once = True
    if args.loop:
        cycle_index = 0
        while True:
            # Fair-share rotation: the host-wide REST fallback budget
            # (~120/min) exhausts partway through a fixed-order pass, which
            # permanently starved the SAME tail symbols every cycle (their
            # books/OI never gap-filled). Rotating the start offset spreads
            # the budget across the whole universe over successive cycles.
            offset = (cycle_index * 29) % max(1, len(symbols))
            rotated = symbols[offset:] + symbols[:offset]
            report = run_once(rotated, ttl_s=args.ttl_seconds)
            write_public_payload(report)
            if args.json:
                print(json.dumps(report))
            cycle_index += 1
            try:
                time.sleep(max(5, args.interval_seconds))
            except KeyboardInterrupt:
                return 0
    else:
        report = run_once(symbols, ttl_s=args.ttl_seconds)
        write_public_payload(report)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print("WROTE", PUBLIC_OUT_DIR / "operator_dashboard_payload.json")
            print(f"keys_written={report['redis_keys_written_total']}  "
                  f"errors={report['errors']}  redis_available={report['redis_available']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
