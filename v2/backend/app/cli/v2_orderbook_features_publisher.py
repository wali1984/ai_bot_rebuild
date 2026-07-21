"""Read-only validator for canonical direct-Binance order-book pairs.

The direct recorder is the sole owner of the per-symbol depth and feature
keys.  This process takes one Redis-atomic observation of each exact pair,
validates the source bytes and independently replays every economic claim,
then writes only a non-authoritative supervision summary.  It cannot publish
or repair a per-symbol feature.

Freshness is learned from observed sequence/availability transitions.  A
process cold start therefore reports UNKNOWN until a later, causally-new
record establishes cadence evidence.  Redis expiry is evidence, but never a
substitute for source-clock and observed-cadence evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, NoReturn

from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

SUMMARY_KEY = "v2:orderbook:features:summary"
LIVE_GATE = "blocked_human_only"
WORKER_ID = "v2_orderbook_features_publisher"
DEFAULT_INTERVAL_SECONDS = 20
DEFAULT_SUMMARY_TTL_SECONDS = 900
DIRECT_DEPTH_SCHEMA = "direct_orderbook_depth_v1"
DIRECT_FEATURES_SCHEMA = "direct_orderbook_features_v1"
REDIS_CREDENTIAL_NAME = "V2_ORDERBOOK_SUPERVISOR_REDIS_URL"

# Resource/protocol limits only.  These values are not market-freshness gates.
MAX_RECORD_BYTES = 2 * 1024 * 1024
CADENCE_HISTORY_LENGTH = 32
MAX_JSON_NESTING_DEPTH = 64

# Redis executes a Lua script without interleaving another command.  TIME,
# both exact values, and both expiry observations therefore share one read
# boundary.  The script deliberately contains no write command.
ATOMIC_PAIR_READ_LUA = """
local observed = redis.call('TIME')
local values = redis.call('MGET', KEYS[1], KEYS[2])
local depth_pttl = redis.call('PTTL', KEYS[1])
local features_pttl = redis.call('PTTL', KEYS[2])
return {observed[1], observed[2], values[1] or false, values[2] or false,
        depth_pttl, features_pttl}
""".strip()
ATOMIC_PAIR_READ_LUA_SHA256 = hashlib.sha256(ATOMIC_PAIR_READ_LUA.encode("utf-8")).hexdigest()

_CANONICAL_UTC_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$"
)
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,32}$")

_PAIR_FIELDS = frozenset(
    {
        "source",
        "exchange",
        "symbol",
        "sequence_id",
        "previous_sequence_id",
        "sequence_gap",
        "sequence_gap_flag",
        "event_time",
        "transaction_time",
        "received_at",
        "available_at",
        "generated_at",
        "update_type",
        "depth_level",
        "feed_speed_ms",
        "bid",
        "ask",
        "best_bid",
        "best_ask",
        "best_bid_size",
        "best_ask_size",
        "bid_size",
        "ask_size",
        "mid",
        "bid_ask_mid",
        "spread_bps",
        "source_latency_ms",
        "update_age_ms",
    }
)
_PAIR_MATCH_FIELDS = _PAIR_FIELDS - frozenset(
    {
        "bid",
        "ask",
        "best_bid",
        "best_ask",
        "best_bid_size",
        "best_ask_size",
        "bid_size",
        "ask_size",
        "mid",
        "bid_ask_mid",
        "spread_bps",
        "source_latency_ms",
        "update_age_ms",
    }
)
_DEPTH_FIELDS = _PAIR_FIELDS | frozenset(
    {"schema_version", "bids", "asks", "bid_levels", "ask_levels"}
)
_FEATURE_FIELDS = _PAIR_FIELDS | frozenset(
    {
        "schema_version",
        "depth_5_bid_usd",
        "depth_5_ask_usd",
        "depth_20_bid_usd",
        "depth_20_ask_usd",
        "depth_50_bid_usd",
        "depth_50_ask_usd",
        "depth_500_bid_usd",
        "depth_500_ask_usd",
        "orderbook_imbalance",
        "depth_imbalance",
        "depth_slope",
        "estimated_price_impact_bps",
        "price_impact_notional_usd",
        "orderbook_depth_usd",
        "depth_total_usd",
        "microstructure_liquidity_depth",
    }
)
_SUPPORTED_PARTIAL_DEPTH_LEVELS = frozenset({5, 10, 20})
_SUPPORTED_BINANCE_WSS_CADENCES_MS = frozenset({100, 250, 500})


class PairValidationError(ValueError):
    """Fail-closed semantic rejection with a stable summary reason."""


class SummaryPublicationError(RuntimeError):
    """The required supervision summary could not be published."""


def _reject(reason: str) -> NoReturn:
    raise PairValidationError(reason)


def _positive_int(value: Any, *, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name}_must_be_positive_exact_int")
    return value


def _positive_int_argument(value: str) -> int:
    try:
        parsed = int(value, 10)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0 or str(parsed) != value.strip():
        raise argparse.ArgumentTypeError("must be a canonical positive integer")
    return parsed


def _redis_url_from_systemd_credential() -> str | None:
    directory = os.environ.get("CREDENTIALS_DIRECTORY")
    if not directory:
        return None
    try:
        root = Path(directory)
        if not root.is_absolute():
            return None
        credential = root / REDIS_CREDENTIAL_NAME
        if credential.parent != root or not credential.is_file() or credential.is_symlink():
            return None
        value = credential.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None
    if not value.startswith(("redis://", "rediss://")) or any(char in value for char in "\r\n\0"):
        return None
    return value


def _redis_client() -> Any:
    """Connect only with the dedicated operator-provisioned Redis ACL URL."""

    url = _redis_url_from_systemd_credential()
    if url is None:
        return None
    try:
        import redis  # type: ignore

        client = redis.Redis.from_url(
            url,
            decode_responses=False,
            socket_connect_timeout=2.0,
            socket_timeout=5.0,
        )
        client.ping()
        return client
    except Exception:
        return None


def _canonical_utc_from_ms(value: int) -> str:
    return (
        datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _canonical_utc_ms(value: Any, *, reason: str) -> int:
    if type(value) is not str or _CANONICAL_UTC_RE.fullmatch(value) is None:
        _reject(reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _reject(reason)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _reject(reason)
    parsed_ms = int(parsed.astimezone(timezone.utc).timestamp() * 1000)
    if _canonical_utc_from_ms(parsed_ms) != value:
        _reject(reason)
    return parsed_ms


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PairValidationError("JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> NoReturn:
    raise PairValidationError("JSON_NONFINITE_CONSTANT")


def _raw_bytes(value: Any) -> bytes | None:
    if value is None or value is False:
        return None
    if isinstance(value, bytes):
        return value
    raise PairValidationError("ATOMIC_READ_VALUE_TYPE_INVALID")


def _reject_nonfinite_tree(value: Any) -> None:
    pending: list[tuple[Any, int]] = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        if type(current) is float and not math.isfinite(current):
            _reject("JSON_NONFINITE_NUMBER")
        if type(current) is dict:
            nested_values = list(current.values())
        elif type(current) is list:
            nested_values = current
        else:
            continue
        if nested_values and depth >= MAX_JSON_NESTING_DEPTH:
            _reject("JSON_NESTING_LIMIT_EXCEEDED")
        pending.extend((nested, depth + 1) for nested in nested_values)


def _strict_json(raw: bytes | None) -> dict[str, Any]:
    if raw is None:
        _reject("PAIR_MISSING")
    if not 0 < len(raw) <= MAX_RECORD_BYTES:
        _reject("JSON_BYTE_LENGTH_INVALID")
    try:
        text = raw.decode("utf-8", errors="strict")
        payload = json.loads(
            text,
            object_pairs_hook=_json_object,
            parse_constant=_reject_json_constant,
        )
    except PairValidationError:
        raise
    except RecursionError:
        _reject("JSON_NESTING_LIMIT_EXCEEDED")
    except (UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        _reject("JSON_INVALID")
    if type(payload) is not dict:
        _reject("JSON_ROOT_INVALID")
    _reject_nonfinite_tree(payload)
    return payload


def _exact_finite(value: Any, *, reason: str, positive: bool = False) -> float:
    if type(value) not in {int, float}:
        _reject(reason)
    try:
        parsed = float(value)
    except (OverflowError, TypeError, ValueError):
        _reject(reason)
    if not math.isfinite(parsed) or (positive and parsed <= 0.0):
        _reject(reason)
    return parsed


def _number_matches(value: Any, expected: float | None) -> bool:
    if expected is None:
        return value is None
    if type(value) not in {int, float}:
        return False
    try:
        parsed = float(value)
    except (OverflowError, TypeError, ValueError):
        return False
    return math.isfinite(parsed) and parsed.hex() == float(expected).hex()


def _levels(rows: Any, *, side: str) -> list[tuple[float, float]]:
    if type(rows) is not list or not rows:
        _reject("DEPTH_SHAPE_INVALID")
    result: list[tuple[float, float]] = []
    for row in rows:
        if type(row) is not dict or set(row) != {"price", "quantity"}:
            _reject("DEPTH_LEVEL_SHAPE_INVALID")
        price = _exact_finite(row["price"], reason="DEPTH_PRICE_INVALID", positive=True)
        quantity = _exact_finite(row["quantity"], reason="DEPTH_QUANTITY_INVALID", positive=True)
        result.append((price, quantity))
    prices = [price for price, _ in result]
    if side == "bids" and any(left <= right for left, right in zip(prices, prices[1:])):
        _reject("BID_ORDER_INVALID")
    if side == "asks" and any(left >= right for left, right in zip(prices, prices[1:])):
        _reject("ASK_ORDER_INVALID")
    return result


def _depth_usd(levels: list[tuple[float, float]], depth: int) -> float:
    return float(sum(price * quantity for price, quantity in levels[:depth]))


def _depth_quantity(levels: list[tuple[float, float]], depth: int) -> float:
    return float(sum(quantity for _, quantity in levels[:depth]))


def _depth_imbalance(
    bids: list[tuple[float, float]],
    asks: list[tuple[float, float]],
    depth: int,
) -> float | None:
    bid_quantity = _depth_quantity(bids, depth)
    ask_quantity = _depth_quantity(asks, depth)
    denominator = bid_quantity + ask_quantity
    if denominator <= 0.0:
        return None
    return float((bid_quantity - ask_quantity) / denominator)


def _depth_slope_bps(
    bids: list[tuple[float, float]],
    asks: list[tuple[float, float]],
    depth: int,
) -> float:
    best_bid = bids[0][0]
    best_ask = asks[0][0]
    mid = (best_bid + best_ask) / 2.0
    bid_far = bids[min(depth, len(bids)) - 1][0]
    ask_far = asks[min(depth, len(asks)) - 1][0]
    bid_slope = max(0.0, (best_bid - bid_far) / mid * 10_000.0)
    ask_slope = max(0.0, (ask_far - best_ask) / mid * 10_000.0)
    return float((bid_slope + ask_slope) / 2.0)


def _side_impact_bps(
    levels: list[tuple[float, float]],
    *,
    notional_usd: float,
    reference_price: float,
) -> float | None:
    remaining = notional_usd
    cost = 0.0
    quantity = 0.0
    for price, available_quantity in levels:
        level_notional = price * available_quantity
        take = min(remaining, level_notional)
        cost += take
        quantity += take / price
        remaining -= take
        if remaining <= 1e-9:
            break
    if quantity <= 0.0 or remaining > 1e-6:
        return None
    average_price = cost / quantity
    return abs(average_price - reference_price) / reference_price * 10_000.0


def _estimated_impact_bps(
    bids: list[tuple[float, float]],
    asks: list[tuple[float, float]],
    *,
    notional_usd: float,
) -> float | None:
    mid = (bids[0][0] + asks[0][0]) / 2.0
    buy = _side_impact_bps(asks, notional_usd=notional_usd, reference_price=mid)
    sell = _side_impact_bps(bids, notional_usd=notional_usd, reference_price=mid)
    candidates = [value for value in (buy, sell) if value is not None]
    return float(max(candidates)) if candidates else None


def _validate_claims(payload: Mapping[str, Any], expected: Mapping[str, float | None], *, role: str) -> None:
    for name, expected_value in expected.items():
        if not _number_matches(payload.get(name), expected_value):
            _reject(f"{role}_{name.upper()}_SUBSTITUTION")


@dataclass(frozen=True)
class ValidatedPair:
    sequence_id: int
    available_at_ms: int
    generated_at_ms: int
    feed_speed_ms: int


def _validate_pair(
    *,
    symbol: str,
    depth: Mapping[str, Any],
    features: Mapping[str, Any],
    redis_server_time_ms: int,
) -> ValidatedPair:
    if set(depth) != _DEPTH_FIELDS or set(features) != _FEATURE_FIELDS:
        _reject("SCHEMA_FIELDS_INVALID")
    expected_identity = {"source": "direct_binance", "exchange": "binance", "symbol": symbol}
    if depth.get("schema_version") != DIRECT_DEPTH_SCHEMA or any(
        depth.get(name) != value for name, value in expected_identity.items()
    ):
        _reject("DEPTH_IDENTITY_INVALID")
    if features.get("schema_version") != DIRECT_FEATURES_SCHEMA or any(
        features.get(name) != value for name, value in expected_identity.items()
    ):
        _reject("FEATURE_IDENTITY_INVALID")
    if depth.get("update_type") != "partial_depth":
        _reject("TRANSPORT_NOT_DIRECT_PARTIAL_DEPTH_WSS")
    depth_level = depth.get("depth_level")
    feed_speed_ms = depth.get("feed_speed_ms")
    if type(depth_level) is not int or depth_level not in _SUPPORTED_PARTIAL_DEPTH_LEVELS:
        _reject("PARTIAL_DEPTH_LEVEL_INVALID")
    if type(feed_speed_ms) is not int or feed_speed_ms not in _SUPPORTED_BINANCE_WSS_CADENCES_MS:
        _reject("PARTIAL_DEPTH_WSS_CADENCE_INVALID")

    sequence_id = depth.get("sequence_id")
    previous_sequence_id = depth.get("previous_sequence_id")
    if type(sequence_id) is not int or sequence_id <= 0:
        _reject("SEQUENCE_ID_INVALID")
    if (
        type(previous_sequence_id) is not int
        or previous_sequence_id <= 0
        or previous_sequence_id >= sequence_id
    ):
        _reject("PREVIOUS_SEQUENCE_ID_INVALID")
    if depth.get("sequence_gap") is not False or depth.get("sequence_gap_flag") != 0:
        _reject("SEQUENCE_GAP")
    if type(depth.get("sequence_gap_flag")) is not int:
        _reject("SEQUENCE_GAP_FLAG_INVALID")
    if any(depth.get(name) != features.get(name) for name in _PAIR_MATCH_FIELDS):
        _reject("PAIR_FIELD_MISMATCH")

    clocks = {
        name: _canonical_utc_ms(depth.get(name), reason=f"{name.upper()}_INVALID")
        for name in ("transaction_time", "event_time", "received_at", "available_at", "generated_at")
    }
    if not (
        clocks["transaction_time"]
        <= clocks["event_time"]
        <= clocks["received_at"]
        <= clocks["available_at"]
        <= clocks["generated_at"]
        <= redis_server_time_ms
    ):
        _reject("CLOCK_CHAIN_INVALID")

    bids = _levels(depth.get("bids"), side="bids")
    asks = _levels(depth.get("asks"), side="asks")
    if len(bids) > depth_level or len(asks) > depth_level:
        _reject("DEPTH_LEVEL_COUNT_EXCEEDS_TRANSPORT")
    if asks[0][0] <= bids[0][0]:
        _reject("CROSSED_OR_ZERO_SPREAD")
    if type(depth.get("bid_levels")) is not int or depth.get("bid_levels") != len(bids):
        _reject("BID_LEVEL_COUNT_INVALID")
    if type(depth.get("ask_levels")) is not int or depth.get("ask_levels") != len(asks):
        _reject("ASK_LEVEL_COUNT_INVALID")

    best_bid, best_bid_size = bids[0]
    best_ask, best_ask_size = asks[0]
    mid = (best_bid + best_ask) / 2.0
    spread_bps = (best_ask - best_bid) / mid * 10_000.0
    source_latency_ms = float(clocks["received_at"] - clocks["event_time"])
    update_age_ms = float(clocks["generated_at"] - clocks["available_at"])
    top_claims = {
        "bid": best_bid,
        "ask": best_ask,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "best_bid_size": best_bid_size,
        "best_ask_size": best_ask_size,
        "bid_size": best_bid_size,
        "ask_size": best_ask_size,
        "mid": mid,
        "bid_ask_mid": mid,
        "spread_bps": spread_bps,
        "source_latency_ms": source_latency_ms,
        "update_age_ms": update_age_ms,
    }
    _validate_claims(depth, top_claims, role="DEPTH")
    _validate_claims(features, top_claims, role="FEATURE")

    reference_notional = _exact_finite(
        features.get("price_impact_notional_usd"),
        reason="FEATURE_PRICE_IMPACT_NOTIONAL_INVALID",
        positive=True,
    )
    depth_20_bid = _depth_usd(bids, 20)
    depth_20_ask = _depth_usd(asks, 20)
    imbalance = _depth_imbalance(bids, asks, 20)
    feature_claims = {
        "depth_5_bid_usd": _depth_usd(bids, 5),
        "depth_5_ask_usd": _depth_usd(asks, 5),
        "depth_20_bid_usd": depth_20_bid,
        "depth_20_ask_usd": depth_20_ask,
        "depth_50_bid_usd": _depth_usd(bids, 50),
        "depth_50_ask_usd": _depth_usd(asks, 50),
        "depth_500_bid_usd": _depth_usd(bids, 500),
        "depth_500_ask_usd": _depth_usd(asks, 500),
        "orderbook_imbalance": imbalance,
        "depth_imbalance": imbalance,
        "depth_slope": _depth_slope_bps(bids, asks, 20),
        "estimated_price_impact_bps": _estimated_impact_bps(
            bids,
            asks,
            notional_usd=reference_notional,
        ),
        "orderbook_depth_usd": min(depth_20_bid, depth_20_ask),
        "depth_total_usd": depth_20_bid + depth_20_ask,
        "microstructure_liquidity_depth": min(depth_20_bid, depth_20_ask),
    }
    _validate_claims(features, feature_claims, role="FEATURE")
    return ValidatedPair(
        sequence_id=sequence_id,
        available_at_ms=clocks["available_at"],
        generated_at_ms=clocks["generated_at"],
        feed_speed_ms=feed_speed_ms,
    )


def _exact_redis_int(value: Any, *, reason: str, allow_negative: bool = False) -> int:
    if isinstance(value, bytes):
        try:
            value = value.decode("ascii", errors="strict")
        except UnicodeError:
            _reject(reason)
    if isinstance(value, str):
        if re.fullmatch(r"-?[0-9]+", value) is None:
            _reject(reason)
        value = int(value, 10)
    if type(value) is not int or (not allow_negative and value < 0):
        _reject(reason)
    return value


@dataclass(frozen=True)
class AtomicPairRead:
    symbol: str
    depth_key: str
    features_key: str
    redis_server_time_ms: int
    depth_raw: bytes | None
    features_raw: bytes | None
    depth_pttl_ms: int
    features_pttl_ms: int

    def receipt(self) -> dict[str, Any]:
        return {
            "schema_version": "v2_orderbook_atomic_pair_read_receipt_v1",
            "symbol": self.symbol,
            "redis_server_observed_at": _canonical_utc_from_ms(self.redis_server_time_ms),
            "redis_server_time_ms": self.redis_server_time_ms,
            "depth_key": self.depth_key,
            "features_key": self.features_key,
            "depth_present": self.depth_raw is not None,
            "features_present": self.features_raw is not None,
            "depth_exact_bytes": len(self.depth_raw or b""),
            "features_exact_bytes": len(self.features_raw or b""),
            "pair_exact_bytes": len(self.depth_raw or b"") + len(self.features_raw or b""),
            "depth_sha256": hashlib.sha256(self.depth_raw).hexdigest() if self.depth_raw is not None else None,
            "features_sha256": (
                hashlib.sha256(self.features_raw).hexdigest() if self.features_raw is not None else None
            ),
            "depth_pttl_ms": self.depth_pttl_ms,
            "features_pttl_ms": self.features_pttl_ms,
            "atomic_read_lua_sha256": ATOMIC_PAIR_READ_LUA_SHA256,
        }


def _atomic_pair_read(client: Any, symbol: str) -> AtomicPairRead:
    if client is None:
        _reject("REDIS_UNAVAILABLE")
    if type(symbol) is not str or _SYMBOL_RE.fullmatch(symbol) is None:
        _reject("SYMBOL_INVALID")
    depth_key = f"v2:orderbook:depth:binance:{symbol}"
    features_key = f"v2:orderbook:features:binance:{symbol}"
    try:
        result = client.eval(ATOMIC_PAIR_READ_LUA, 2, depth_key, features_key)
    except Exception as exc:
        raise PairValidationError("ATOMIC_READ_FAILED") from exc
    if type(result) not in {list, tuple} or len(result) != 6:
        _reject("ATOMIC_READ_SHAPE_INVALID")
    seconds = _exact_redis_int(result[0], reason="REDIS_TIME_INVALID")
    microseconds = _exact_redis_int(result[1], reason="REDIS_TIME_INVALID")
    if microseconds >= 1_000_000:
        _reject("REDIS_TIME_INVALID")
    return AtomicPairRead(
        symbol=symbol,
        depth_key=depth_key,
        features_key=features_key,
        redis_server_time_ms=seconds * 1000 + microseconds // 1000,
        depth_raw=_raw_bytes(result[2]),
        features_raw=_raw_bytes(result[3]),
        depth_pttl_ms=_exact_redis_int(result[4], reason="DEPTH_PTTL_INVALID", allow_negative=True),
        features_pttl_ms=_exact_redis_int(result[5], reason="FEATURE_PTTL_INVALID", allow_negative=True),
    )


@dataclass
class _CadenceState:
    sequence_id: int
    available_at_ms: int
    last_observed_server_ms: int
    depth_sha256: str
    features_sha256: str
    observed_intervals_ms: deque[int] = field(
        default_factory=lambda: deque(maxlen=CADENCE_HISTORY_LENGTH)
    )


class AdaptiveCadenceTracker:
    """Process-local evidence; state is never silently restored from a summary."""

    def __init__(self) -> None:
        self._states: dict[str, _CadenceState] = {}

    def assess(
        self,
        *,
        read: AtomicPairRead,
        pair: ValidatedPair,
    ) -> dict[str, Any]:
        if read.depth_pttl_ms <= 0 or read.features_pttl_ms <= 0:
            return {"status": "HELD", "reason": "EXPIRY_EVIDENCE_INVALID"}
        if abs(read.depth_pttl_ms - read.features_pttl_ms) > pair.feed_speed_ms:
            return {"status": "HELD", "reason": "PAIR_EXPIRY_MISMATCH"}

        depth_hash = hashlib.sha256(read.depth_raw or b"").hexdigest()
        features_hash = hashlib.sha256(read.features_raw or b"").hexdigest()
        age_ms = read.redis_server_time_ms - pair.available_at_ms
        expiry_horizon_ms = min(read.depth_pttl_ms, read.features_pttl_ms) + (
            read.redis_server_time_ms - pair.generated_at_ms
        )
        evidence: dict[str, Any] = {
            "observed_age_ms": age_ms,
            "observed_expiry_horizon_ms": expiry_horizon_ms,
            "observed_cadence_sample_count": 0,
            "observed_cadence_intervals_ms": [],
            "adaptive_freshness_budget_ms": None,
        }
        previous = self._states.get(read.symbol)
        if previous is None:
            self._states[read.symbol] = _CadenceState(
                sequence_id=pair.sequence_id,
                available_at_ms=pair.available_at_ms,
                last_observed_server_ms=read.redis_server_time_ms,
                depth_sha256=depth_hash,
                features_sha256=features_hash,
            )
            return {
                "status": "UNKNOWN",
                "reason": "COLD_START_NO_OBSERVED_CADENCE",
                **evidence,
            }
        if read.redis_server_time_ms <= previous.last_observed_server_ms:
            return {"status": "HELD", "reason": "REDIS_TIME_NOT_MONOTONIC", **evidence}
        if pair.sequence_id < previous.sequence_id:
            return {"status": "HELD", "reason": "SEQUENCE_REGRESSION", **evidence}

        intervals = deque(previous.observed_intervals_ms, maxlen=CADENCE_HISTORY_LENGTH)
        if pair.sequence_id == previous.sequence_id:
            if depth_hash != previous.depth_sha256 or features_hash != previous.features_sha256:
                return {"status": "HELD", "reason": "SEQUENCE_CONTENT_MUTATION", **evidence}
        else:
            if pair.available_at_ms <= previous.available_at_ms:
                return {"status": "HELD", "reason": "AVAILABILITY_NOT_ADVANCING", **evidence}
            if pair.available_at_ms < previous.last_observed_server_ms:
                return {"status": "HELD", "reason": "REPLAYED_AVAILABILITY", **evidence}
            observed_interval_ms = pair.available_at_ms - previous.available_at_ms
            if observed_interval_ms <= 0:
                return {"status": "HELD", "reason": "CADENCE_EVIDENCE_INVALID", **evidence}
            intervals.append(observed_interval_ms)

        self._states[read.symbol] = _CadenceState(
            sequence_id=pair.sequence_id,
            available_at_ms=pair.available_at_ms,
            last_observed_server_ms=read.redis_server_time_ms,
            depth_sha256=depth_hash,
            features_sha256=features_hash,
            observed_intervals_ms=intervals,
        )
        evidence["observed_cadence_sample_count"] = len(intervals)
        evidence["observed_cadence_intervals_ms"] = list(intervals)
        if not intervals:
            return {"status": "UNKNOWN", "reason": "NO_SEQUENCE_TRANSITION", **evidence}

        # Both inputs are observed evidence: recent source availability
        # intervals and the producer's currently observed key-expiry horizon.
        # There is no fixed seconds-based market threshold or multiplier.
        adaptive_budget_ms = min(max(intervals), expiry_horizon_ms)
        evidence["adaptive_freshness_budget_ms"] = adaptive_budget_ms
        if adaptive_budget_ms <= 0:
            return {"status": "HELD", "reason": "ADAPTIVE_BUDGET_INVALID", **evidence}
        if age_ms > adaptive_budget_ms:
            return {"status": "HELD", "reason": "OBSERVED_CADENCE_STALE", **evidence}
        return {"status": "HEALTHY", "reason": None, **evidence}


def _write_summary(client: Any, payload: Mapping[str, Any], *, ttl_seconds: int) -> None:
    ttl = _positive_int(ttl_seconds, name="ttl_seconds")
    if client is None:
        raise SummaryPublicationError("SUMMARY_REDIS_UNAVAILABLE")
    try:
        encoded = json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        raise SummaryPublicationError("SUMMARY_SERIALIZATION_FAILED") from None
    try:
        written = client.set(SUMMARY_KEY, encoded, ex=ttl)
    except Exception:
        raise SummaryPublicationError("SUMMARY_WRITE_FAILED") from None
    if written is not True:
        raise SummaryPublicationError("SUMMARY_WRITE_NOT_ACKNOWLEDGED")


def run_cycle(
    client: Any,
    *,
    symbols: list[str],
    ttl_seconds: int,
    cadence_tracker: AdaptiveCadenceTracker,
) -> dict[str, Any]:
    ttl = _positive_int(ttl_seconds, name="ttl_seconds")
    if type(symbols) is not list or type(cadence_tracker) is not AdaptiveCadenceTracker:
        raise ValueError("cycle_configuration_invalid")
    if client is None:
        raise SummaryPublicationError("SUMMARY_REDIS_UNAVAILABLE")
    normalized_symbols: list[str] = []
    for symbol in symbols:
        if type(symbol) is not str or _SYMBOL_RE.fullmatch(symbol) is None:
            raise ValueError("symbols_must_be_unique_canonical_strings")
        normalized_symbols.append(symbol)
    if len(set(normalized_symbols)) != len(normalized_symbols):
        raise ValueError("symbols_must_be_unique_canonical_strings")

    reasons: dict[str, int] = {}
    receipts: list[dict[str, Any]] = []
    healthy = 0
    integrity_valid = 0
    unknown = 0
    last_server_ms: int | None = None
    for symbol in normalized_symbols:
        read: AtomicPairRead | None = None
        try:
            read = _atomic_pair_read(client, symbol)
            receipt = read.receipt()
            last_server_ms = read.redis_server_time_ms
            depth = _strict_json(read.depth_raw)
            features = _strict_json(read.features_raw)
            pair = _validate_pair(
                symbol=symbol,
                depth=depth,
                features=features,
                redis_server_time_ms=read.redis_server_time_ms,
            )
            integrity_valid += 1
            freshness = cadence_tracker.assess(read=read, pair=pair)
            receipt.update(
                {
                    "integrity_valid": True,
                    "source_sequence_id": pair.sequence_id,
                    "freshness": freshness,
                }
            )
            if freshness["status"] == "HEALTHY":
                healthy += 1
            else:
                reason = str(freshness["reason"])
                reasons[reason] = reasons.get(reason, 0) + 1
                if freshness["status"] == "UNKNOWN":
                    unknown += 1
        except PairValidationError as exc:
            reason = str(exc)
            reasons[reason] = reasons.get(reason, 0) + 1
            receipt = {
                "schema_version": "v2_orderbook_atomic_pair_read_receipt_v1",
                "symbol": symbol,
                "integrity_valid": False,
                "rejection_reason": reason,
                "atomic_read_lua_sha256": ATOMIC_PAIR_READ_LUA_SHA256,
            }
            if isinstance(read, AtomicPairRead):
                receipt = {**read.receipt(), **receipt}
        except OverflowError:
            reason = "VALIDATION_NUMERIC_RANGE_EXCEEDED"
            reasons[reason] = reasons.get(reason, 0) + 1
            receipt = {
                "schema_version": "v2_orderbook_atomic_pair_read_receipt_v1",
                "symbol": symbol,
                "integrity_valid": False,
                "rejection_reason": reason,
                "atomic_read_lua_sha256": ATOMIC_PAIR_READ_LUA_SHA256,
            }
            if isinstance(read, AtomicPairRead):
                receipt = {**read.receipt(), **receipt}
        except RecursionError:
            reason = "JSON_NESTING_LIMIT_EXCEEDED"
            reasons[reason] = reasons.get(reason, 0) + 1
            receipt = {
                "schema_version": "v2_orderbook_atomic_pair_read_receipt_v1",
                "symbol": symbol,
                "integrity_valid": False,
                "rejection_reason": reason,
                "atomic_read_lua_sha256": ATOMIC_PAIR_READ_LUA_SHA256,
            }
            if isinstance(read, AtomicPairRead):
                receipt = {**read.receipt(), **receipt}
        receipts.append(receipt)

    observed_at = _canonical_utc_from_ms(last_server_ms) if last_server_ms is not None else None
    summary: dict[str, Any] = {
        "schema_version": "v2_orderbook_pair_supervision_summary_v3",
        "worker_id": WORKER_ID,
        "generated_at": observed_at,
        "generated_at_authority": "REDIS_SERVER_TIME_FROM_LAST_ATOMIC_PAIR_READ" if observed_at else None,
        "symbols_total": len(normalized_symbols),
        "atomic_pair_reads_attempted": len(normalized_symbols),
        "exact_pair_receipts_count": len(receipts),
        "exact_depth_bytes_observed": sum(int(row.get("depth_exact_bytes") or 0) for row in receipts),
        "exact_features_bytes_observed": sum(int(row.get("features_exact_bytes") or 0) for row in receipts),
        "canonical_pair_integrity_valid": integrity_valid,
        "canonical_pair_healthy": healthy,
        "canonical_pair_unknown": unknown,
        "canonical_pair_unhealthy": len(normalized_symbols) - healthy - unknown,
        "canonical_pair_reasons": dict(sorted(reasons.items())),
        "atomic_read_protocol": "REDIS_LUA_TIME_MGET_PTTL_V1",
        "atomic_read_lua_sha256": ATOMIC_PAIR_READ_LUA_SHA256,
        "pair_read_receipts": receipts,
        "freshness_contract": "OBSERVED_SEQUENCE_AVAILABILITY_CADENCE_AND_REDIS_EXPIRY_V1",
        "cold_start_policy": "UNKNOWN_HELD_UNTIL_CAUSALLY_NEW_SEQUENCE",
        "features_written": 0,
        "per_symbol_feature_write_authorized": False,
        "canonical_per_symbol_owner": "v2_direct_orderbook_recorder",
        "summary_only_supervision": True,
        "summary_publication_required": True,
        "summary_publication_failure_policy": "PROCESS_FAILS_FOR_SYSTEMD_RESTART",
        "summary_ttl_seconds": ttl,
        "trainer_admission_authorized": False,
        "consumer_eligible": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
        "paper_only": True,
        "places_real_order": False,
        "writes_legacy_redis": False,
        "live_gate": LIVE_GATE,
    }
    _write_summary(client, summary, ttl_seconds=ttl)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--symbols", default=None, help="comma-separated; defaults to runtime universe")
    parser.add_argument(
        "--interval-seconds",
        type=_positive_int_argument,
        default=DEFAULT_INTERVAL_SECONDS,
    )
    parser.add_argument(
        "--summary-ttl-seconds",
        type=_positive_int_argument,
        default=DEFAULT_SUMMARY_TTL_SECONDS,
    )
    args = parser.parse_args(argv)
    client = _redis_client()
    cadence_tracker = AdaptiveCadenceTracker()
    while True:
        if client is None:
            client = _redis_client()
        symbols = resolve_symbols(explicit=args.symbols)
        summary = run_cycle(
            client,
            symbols=symbols,
            ttl_seconds=args.summary_ttl_seconds,
            cadence_tracker=cadence_tracker,
        )
        print(json.dumps(summary, sort_keys=True, separators=(",", ":"), allow_nan=False), flush=True)
        if not args.loop:
            return 0
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    sys.exit(main())
