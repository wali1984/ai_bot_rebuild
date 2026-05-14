"""
risk/market_state_contract.py — Unified Market State Contract.

Merges all risk layer outputs into a single cached Redis object that
provides a health-aware, single-read view of the current market state:

  regime:global:*          → breadth metrics
  risk_budget:state:*      → allocator decision
  reversal:global          → reversal warning
  ingestor health          → data feed freshness / degradation

Key rule:
  **If data health is degraded → allocator CANNOT go EXPAND or MOMENTUM_SHOCK.**

This prevents the system from scaling up risk when feed data is stale,
missing, or unreliable.

Feature-flagged via config.MARKET_STATE_CONTRACT_ENABLED (default: True).

Redis output key: ``market:state:contract`` with TTL.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

try:
    import config
except ImportError:
    config = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ── Defaults ─────────────────────────────────────────────────────────
_CONTRACT_CACHE_TTL_SEC = 300
_CONTRACT_ENABLED = True

# Data-health thresholds (staleness in seconds)
_INGESTOR_HEALTHY_MAX_AGE_SEC = 360     # Feed age above this = degraded (covers 5m candle gap)
_REGIME_HEALTHY_MAX_AGE_SEC = 600       # Regime keys must be this fresh
_BREADTH_HEALTHY_MAX_AGE_SEC = 600      # Breadth must be this fresh
_MIN_HEALTHY_FEEDS_PCT = 0.60           # 60%+ feeds healthy = data_ok
_MIN_REGIME_KEYS_PCT = 0.60             # 60%+ regime keys present = regime_ok


def _cfg(key: str, default):
    if config is not None:
        full_key = f"MSC_{key}"
        val = getattr(config, full_key, None)
        if val is not None:
            return val
        # Also try without prefix
        val2 = getattr(config, key, None)
        if val2 is not None:
            return val2
    return default


class DataHealthReport:
    """Feed-level health assessment."""

    __slots__ = (
        "total_feeds", "healthy_feeds", "degraded_feeds", "missing_feeds",
        "health_pct", "data_ok", "degraded_symbols", "details",
    )

    def __init__(self):
        self.total_feeds: int = 0
        self.healthy_feeds: int = 0
        self.degraded_feeds: int = 0
        self.missing_feeds: int = 0
        self.health_pct: float = 0.0
        self.data_ok: bool = False
        self.degraded_symbols: List[str] = []
        self.details: Dict[str, str] = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_feeds": self.total_feeds,
            "healthy_feeds": self.healthy_feeds,
            "degraded_feeds": self.degraded_feeds,
            "missing_feeds": self.missing_feeds,
            "health_pct": round(self.health_pct, 3),
            "data_ok": self.data_ok,
            "degraded_symbols": self.degraded_symbols[:10],  # Cap for serialization
        }


class MarketStateContract:
    """Unified market state snapshot."""

    __slots__ = (
        "breadth", "allocator_state", "reversal_active", "reversal_triggers",
        "data_health", "regime_coverage_pct", "can_expand",
        "effective_state", "reason", "updated_ts_ms",
    )

    def __init__(self):
        self.breadth: Dict[str, Any] = {}
        self.allocator_state: str = "UNKNOWN"
        self.reversal_active: bool = False
        self.reversal_triggers: int = 0
        self.data_health: DataHealthReport = DataHealthReport()
        self.regime_coverage_pct: float = 0.0
        self.can_expand: bool = False
        self.effective_state: str = "DEFENSIVE"
        self.reason: str = ""
        self.updated_ts_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "breadth": self.breadth,
            "allocator_state": self.allocator_state,
            "reversal_active": self.reversal_active,
            "reversal_triggers": self.reversal_triggers,
            "data_health": self.data_health.to_dict(),
            "regime_coverage_pct": round(self.regime_coverage_pct, 3),
            "can_expand": self.can_expand,
            "effective_state": self.effective_state,
            "reason": self.reason,
            "updated_ts_ms": self.updated_ts_ms,
        }


# ── Data-health computation ──────────────────────────────────────────

def assess_data_health(
    redis_client,
    symbols: Optional[List[str]] = None,
    timeframe: str = "5m",
) -> DataHealthReport:
    """Check freshness of unified_features for each symbol.

    Reads ``ts_ms`` field from each ``unified_features:{symbol}:{tf}``
    and classifies as healthy / degraded / missing.
    """
    report = DataHealthReport()
    if not redis_client:
        return report

    if symbols is None:
        symbols = list(getattr(config, "SYMBOLS", []) or [])
    if not symbols:
        return report

    now_ms = int(time.time() * 1000)
    max_age_ms = int(float(_cfg("INGESTOR_HEALTHY_MAX_AGE_SEC", _INGESTOR_HEALTHY_MAX_AGE_SEC)) * 1000)

    report.total_feeds = len(symbols)

    # Pipeline read for efficiency
    try:
        pipe = redis_client.pipeline(transaction=False)
        for sym in symbols:
            pipe.hget(f"unified_features:{sym}:{timeframe}", "ts_ms")
        results = pipe.execute()
    except Exception:
        results = [None] * len(symbols)

    for i, sym in enumerate(symbols):
        raw = results[i] if i < len(results) else None
        if not raw:
            report.missing_feeds += 1
            report.degraded_symbols.append(sym)
            report.details[sym] = "MISSING"
            continue
        try:
            ts = int(float(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)))
            age_ms = now_ms - ts
            if age_ms <= max_age_ms:
                report.healthy_feeds += 1
                report.details[sym] = "OK"
            else:
                report.degraded_feeds += 1
                report.degraded_symbols.append(sym)
                report.details[sym] = f"STALE({int(age_ms / 1000)}s)"
        except Exception:
            report.degraded_feeds += 1
            report.degraded_symbols.append(sym)
            report.details[sym] = "PARSE_ERROR"

    if report.total_feeds > 0:
        report.health_pct = report.healthy_feeds / report.total_feeds
    min_health = float(_cfg("MIN_HEALTHY_FEEDS_PCT", _MIN_HEALTHY_FEEDS_PCT))
    report.data_ok = report.health_pct >= min_health

    return report


def assess_regime_coverage(
    redis_client,
    symbols: Optional[List[str]] = None,
) -> float:
    """Check what fraction of symbols have fresh regime keys.

    Returns float 0..1 representing regime coverage.
    """
    if not redis_client:
        return 0.0
    if symbols is None:
        symbols = list(getattr(config, "SYMBOLS", []) or [])
    if not symbols:
        return 0.0

    now_ms = int(time.time() * 1000)
    max_age_ms = int(float(_cfg("REGIME_HEALTHY_MAX_AGE_SEC", _REGIME_HEALTHY_MAX_AGE_SEC)) * 1000)

    count = 0
    # Pipeline
    try:
        pipe = redis_client.pipeline(transaction=False)
        for sym in symbols:
            pipe.get(f"regime:{sym}")
        results = pipe.execute()
    except Exception:
        return 0.0

    for i, sym in enumerate(symbols):
        raw = results[i] if i < len(results) else None
        if not raw:
            continue
        try:
            val = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
            data = json.loads(val)
            if isinstance(data, dict):
                ts = int(data.get("updated_ts_ms") or 0)
                if ts > 0 and (now_ms - ts) <= max_age_ms:
                    count += 1
        except Exception:
            continue

    return count / len(symbols) if symbols else 0.0


# ── Contract computation ─────────────────────────────────────────────

def compute_market_state_contract(
    redis_client,
    account_id: str = "primary",
    symbols: Optional[List[str]] = None,
    timeframe: str = "5m",
) -> MarketStateContract:
    """Build the unified market state contract.

    Reads all risk layer caches and data health, determines whether
    the system is allowed to EXPAND.
    """
    contract = MarketStateContract()
    contract.updated_ts_ms = int(time.time() * 1000)

    if not redis_client:
        contract.reason = "NO_REDIS"
        return contract

    if symbols is None:
        symbols = list(getattr(config, "SYMBOLS", []) or [])

    # 1. Data health
    try:
        contract.data_health = assess_data_health(redis_client, symbols, timeframe)
    except Exception as e:
        logger.debug("[MSC] Data health error: %s", e)

    # 2. Regime coverage
    try:
        contract.regime_coverage_pct = assess_regime_coverage(redis_client, symbols)
    except Exception as e:
        logger.debug("[MSC] Regime coverage error: %s", e)

    # 3. Global breadth
    try:
        from risk.global_breadth import read_cached_breadth
        breadth = read_cached_breadth(redis_client, timeframe)
        if breadth and isinstance(breadth, dict):
            contract.breadth = breadth
    except Exception:
        pass

    # 4. Allocator state
    try:
        from risk.risk_budget_allocator import read_cached_allocation
        alloc = read_cached_allocation(redis_client, account_id)
        if alloc:
            contract.allocator_state = alloc.state
    except Exception:
        pass

    # 5. Reversal state
    try:
        from risk.reversal_detector import read_cached_reversal
        rev = read_cached_reversal(redis_client)
        if rev and isinstance(rev, dict):
            contract.reversal_active = bool(rev.get("active", False))
            contract.reversal_triggers = int(rev.get("trigger_count") or 0)
    except Exception:
        pass

    # 6. Determine can_expand
    # EXPAND/MOMENTUM_SHOCK requires ALL of:
    #   - data health OK
    #   - regime coverage >= threshold
    #   - reversal not active
    #   - breadth available
    min_regime_pct = float(_cfg("MIN_REGIME_KEYS_PCT", _MIN_REGIME_KEYS_PCT))
    reasons = []

    if not contract.data_health.data_ok:
        reasons.append(f"DATA_DEGRADED(health={contract.data_health.health_pct:.1%})")
    if contract.regime_coverage_pct < min_regime_pct:
        reasons.append(f"LOW_REGIME_COVERAGE({contract.regime_coverage_pct:.1%})")
    if contract.reversal_active:
        reasons.append(f"REVERSAL_ACTIVE(triggers={contract.reversal_triggers})")
    if not contract.breadth:
        reasons.append("NO_BREADTH_DATA")

    contract.can_expand = len(reasons) == 0

    # 7. Effective state
    if contract.allocator_state in ("EXPAND", "MOMENTUM_SHOCK") and not contract.can_expand:
        contract.effective_state = "DEFENSIVE"
        contract.reason = f"EXPAND_BLOCKED|{contract.allocator_state}|{'|'.join(reasons)}"
    else:
        contract.effective_state = contract.allocator_state
        contract.reason = "OK" if contract.can_expand else "|".join(reasons)

    return contract


def cache_market_state_contract(
    redis_client,
    contract: MarketStateContract,
    ttl_sec: int = 0,
) -> bool:
    """Write contract to Redis."""
    if not redis_client:
        return False
    if ttl_sec <= 0:
        ttl_sec = int(_cfg("CONTRACT_CACHE_TTL_SEC", _CONTRACT_CACHE_TTL_SEC))
    try:
        redis_client.setex(
            "market:state:contract",
            max(10, ttl_sec),
            json.dumps(contract.to_dict(), separators=(",", ":")),
        )
        return True
    except Exception:
        return False


def read_cached_contract(redis_client) -> Optional[Dict[str, Any]]:
    """Read cached contract from Redis. Returns None if missing."""
    if not redis_client:
        return None
    try:
        raw = redis_client.get("market:state:contract")
        if not raw:
            return None
        val = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
        data = json.loads(val)
        return data if isinstance(data, dict) else None
    except Exception:
        return None
