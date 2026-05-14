"""
Market Context Snapshot (Jan 2026)
===================================

Provides a unified market context snapshot for orchestrator decision-making.

Every proposal must link to a MarketContext snapshot (ctx_id) to ensure
decisions are made with the same market data view.

Components:
- Price/Spread: mid, spread, imbalance, microprice
- Order Book: book_slope, topN_depth, bid_ask_ratio
- Toxicity: spoof_score, churn_score, toxicity_score
- Liquidation: nearest liq bands, density gradient, heatmap
- Fast Move: fast_move_pct, fast_move_persistence
- Regime: trend/range/squeeze classification

This ensures the orchestrator can compute comparable utility scores
across all proposals in the same decision window.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from config import OPEN_RISK_FEATURES_MAX_AGE_MS  # type: ignore
except Exception:
    OPEN_RISK_FEATURES_MAX_AGE_MS = int(os.getenv("OPEN_RISK_FEATURES_MAX_AGE_MS", "120000"))

# MarketContext-specific staleness thresholds
MARKET_CTX_PRICE_MAX_AGE_MS = int(os.getenv("MARKET_CTX_PRICE_MAX_AGE_MS", "60000"))


@dataclass
class LiquidationContext:
    """Liquidation map context for a symbol."""
    nearest_liq_above_usd: float = 0.0       # Nearest liquidation level above
    nearest_liq_below_usd: float = 0.0       # Nearest liquidation level below
    distance_to_above_pct: float = 0.0       # Distance to nearest above (%)
    distance_to_below_pct: float = 0.0       # Distance to nearest below (%)
    density_above: float = 0.0              # Liquidation density above (0-1)
    density_below: float = 0.0              # Liquidation density below (0-1)
    heatmap_bias: float = 0.0               # -1 (shorts concentrated) to +1 (longs concentrated)
    total_liq_volume_24h: float = 0.0       # Total liquidated volume in 24h
    
    @property
    def liq_risk_score(self) -> float:
        """
        Compute liquidation risk score (0-1).
        Higher = more risk from nearby liquidation levels.
        """
        # Distance factor: closer = higher risk
        dist_factor = 0.0
        if self.distance_to_above_pct > 0:
            dist_factor = max(dist_factor, max(0, 1 - self.distance_to_above_pct / 5))  # 5% = safe
        if self.distance_to_below_pct > 0:
            dist_factor = max(dist_factor, max(0, 1 - self.distance_to_below_pct / 5))
        
        # Density factor: higher density = higher risk
        density_factor = (self.density_above + self.density_below) / 2
        
        return min(1.0, dist_factor * 0.6 + density_factor * 0.4)


@dataclass
class OrderBookContext:
    """Order book microstructure context."""
    mid_price: float = 0.0
    spread_bps: float = 0.0                 # Spread in basis points
    bid_depth_usd: float = 0.0              # Top N bid depth in USD
    ask_depth_usd: float = 0.0              # Top N ask depth in USD
    imbalance: float = 0.0                  # -1 (ask heavy) to +1 (bid heavy)
    microprice: float = 0.0                 # Volume-weighted mid
    book_slope: float = 0.0                 # Price sensitivity to size
    
    # Toxicity indicators
    spoof_score: float = 0.0                # Spoofing detection (0-1)
    churn_score: float = 0.0                # Order churn rate (0-1)
    toxicity_score: float = 0.0             # Combined toxicity (0-1)
    
    @property
    def fill_prob_maker(self) -> float:
        """Estimated fill probability for maker order."""
        # Higher imbalance in our favor = higher fill prob
        # Lower toxicity = higher fill prob
        base = 0.5
        imbalance_boost = self.imbalance * 0.2  # ±20% from imbalance
        toxicity_penalty = self.toxicity_score * 0.3  # -30% max from toxicity
        
        return max(0.1, min(0.95, base + imbalance_boost - toxicity_penalty))
    
    @property
    def fill_prob_taker(self) -> float:
        """Estimated fill probability for taker order (generally high)."""
        # Taker almost always fills, but wide spread or low depth = risk
        spread_penalty = min(0.1, self.spread_bps / 100)  # -10% max for 100bps spread
        depth_penalty = 0.05 if (self.bid_depth_usd < 10000 or self.ask_depth_usd < 10000) else 0.0
        
        return max(0.8, 0.99 - spread_penalty - depth_penalty)
    
    @property
    def expected_slippage_bps(self) -> float:
        """Expected slippage in basis points."""
        # Base slippage from spread + depth-based component
        return self.spread_bps / 2 + max(0, 10 - self.book_slope * 5)


@dataclass
class RegimeContext:
    """Market regime classification."""
    regime: str = "unknown"                 # "trend_up", "trend_down", "range", "squeeze", "unknown"
    regime_confidence: float = 0.0          # 0-1 confidence in regime classification
    volatility_percentile: float = 0.5      # Current vol vs historical (0-1)
    trend_strength: float = 0.0             # -1 (strong down) to +1 (strong up)
    mean_reversion_prob: float = 0.5        # Probability of mean reversion
    fast_move_pct: float = 0.0              # Recent fast move %
    fast_move_persistence: float = 0.0      # Fast move continuation probability
    
    def get_weight_multipliers(self) -> Dict[str, float]:
        """
        Get regime-dependent weight multipliers for utility scoring.
        
        In trending markets: favor edge, reduce toxicity sensitivity
        In ranging markets: favor capital efficiency, increase toxicity sensitivity
        In squeeze: favor fill probability, high toxicity sensitivity
        """
        if self.regime == "trend_up" or self.regime == "trend_down":
            return {
                "edge_weight": 1.2,
                "fill_prob_weight": 0.8,
                "toxicity_weight": 0.7,
                "liq_risk_weight": 1.0,
                "capital_eff_weight": 0.9,
            }
        elif self.regime == "range":
            return {
                "edge_weight": 0.9,
                "fill_prob_weight": 1.0,
                "toxicity_weight": 1.2,
                "liq_risk_weight": 1.1,
                "capital_eff_weight": 1.1,
            }
        elif self.regime == "squeeze":
            return {
                "edge_weight": 0.8,
                "fill_prob_weight": 1.3,
                "toxicity_weight": 1.4,
                "liq_risk_weight": 1.2,
                "capital_eff_weight": 0.8,
            }
        else:
            # Default/unknown regime
            return {
                "edge_weight": 1.0,
                "fill_prob_weight": 1.0,
                "toxicity_weight": 1.0,
                "liq_risk_weight": 1.0,
                "capital_eff_weight": 1.0,
            }


@dataclass
class MarketContext:
    """
    Complete market context snapshot for a symbol at a point in time.
    
    Every proposal must reference a ctx_id to ensure decisions are made
    with the same market data view.
    """
    # Identity
    ctx_id: str = field(default_factory=lambda: f"ctx_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}")
    symbol: str = ""
    account_id: str = ""
    created_ts_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    
    # Price data
    mark_price: float = 0.0
    index_price: float = 0.0
    last_trade_price: float = 0.0
    price_source: str = ""                  # "binance_ws", "coinapi", "redis_cache"
    price_ts_ms: int = 0
    
    # Sub-contexts
    orderbook: OrderBookContext = field(default_factory=OrderBookContext)
    liquidation: LiquidationContext = field(default_factory=LiquidationContext)
    regime: RegimeContext = field(default_factory=RegimeContext)
    
    # Feature data
    featureset_version: str = ""            # Feature pipeline version
    feature_ts_ms: int = 0                  # When features were computed
    top_features: List[Dict[str, Any]] = field(default_factory=list)  # Top influential features
    
    # Data health
    is_stale: bool = False
    stale_reason: str = ""
    data_quality_score: float = 1.0         # 0-1, lower = worse quality
    
    def __post_init__(self):
        """Validate and compute derived fields."""
        self.symbol = str(self.symbol or "").strip().upper()
        self.account_id = str(self.account_id or "").strip().lower()

    def recompute_staleness(self, now_ms: Optional[int] = None) -> None:
        """
        Recompute staleness + data_quality_score based on current timestamps.

        Design:
        - Missing price/features are treated as stale (fail-closed for OPEN_RISK).
        - Uses OPEN_RISK_FEATURES_MAX_AGE_MS so trader/trainer/orchestrator agree.
        - Idempotent: never *increases* data_quality_score; only reduces.
        """
        now_i = int(now_ms or int(time.time() * 1000))
        existing = [r for r in str(self.stale_reason or "").split(",") if r]
        reasons = list(existing)

        dq_factor = 1.0

        # Price freshness
        if int(self.price_ts_ms or 0) > 0:
            age = now_i - int(self.price_ts_ms or 0)
            if age > int(MARKET_CTX_PRICE_MAX_AGE_MS):
                reasons.append(f"price_stale:{age}ms")
                dq_factor *= 0.5
        else:
            reasons.append("price_missing")
            dq_factor *= 0.3

        # Feature freshness (unified_features:{sym}:5m)
        if int(self.feature_ts_ms or 0) > 0:
            age = now_i - int(self.feature_ts_ms or 0)
            if age > int(OPEN_RISK_FEATURES_MAX_AGE_MS):
                reasons.append(f"features_stale:{age}ms")
                dq_factor *= 0.7
        else:
            reasons.append("features_missing")
            dq_factor *= 0.3

        # Deduplicate while preserving order
        deduped = []
        seen = set()
        for r in reasons:
            if r in seen:
                continue
            seen.add(r)
            deduped.append(r)

        computed_stale = any(
            r.startswith("price_stale:")
            or r.startswith("features_stale:")
            or r in ("price_missing", "features_missing")
            for r in deduped
        )

        if computed_stale:
            self.is_stale = True
            self.stale_reason = ",".join(deduped)
            try:
                staleness_score = float(dq_factor)
            except Exception:
                staleness_score = 0.3
            try:
                current_dq = float(self.data_quality_score if self.data_quality_score is not None else 1.0)
            except Exception:
                current_dq = 1.0
            self.data_quality_score = float(min(current_dq, max(0.0, min(1.0, staleness_score))))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "ctx_id": self.ctx_id,
            "symbol": self.symbol,
            "account_id": self.account_id,
            "created_ts_ms": self.created_ts_ms,
            "mark_price": self.mark_price,
            "index_price": self.index_price,
            "last_trade_price": self.last_trade_price,
            "price_source": self.price_source,
            "price_ts_ms": self.price_ts_ms,
            "orderbook": asdict(self.orderbook),
            "liquidation": asdict(self.liquidation),
            "regime": asdict(self.regime),
            "featureset_version": self.featureset_version,
            "feature_ts_ms": self.feature_ts_ms,
            "top_features": self.top_features,
            "is_stale": self.is_stale,
            "stale_reason": self.stale_reason,
            "data_quality_score": self.data_quality_score,
        }
    
    def to_json(self) -> str:
        """Serialize to JSON."""
        return json.dumps(self.to_dict(), separators=(",", ":"), default=str)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MarketContext":
        """Create from dictionary."""
        ctx = cls(
            ctx_id=data.get("ctx_id", ""),
            symbol=data.get("symbol", ""),
            account_id=data.get("account_id", ""),
            created_ts_ms=data.get("created_ts_ms", 0),
            mark_price=data.get("mark_price", 0.0),
            index_price=data.get("index_price", 0.0),
            last_trade_price=data.get("last_trade_price", 0.0),
            price_source=data.get("price_source", ""),
            price_ts_ms=data.get("price_ts_ms", 0),
            featureset_version=data.get("featureset_version", ""),
            feature_ts_ms=data.get("feature_ts_ms", 0),
            top_features=data.get("top_features", []),
            is_stale=data.get("is_stale", False),
            stale_reason=data.get("stale_reason", ""),
            data_quality_score=data.get("data_quality_score", 1.0),
        )
        
        # Parse sub-contexts
        if "orderbook" in data and isinstance(data["orderbook"], dict):
            ctx.orderbook = OrderBookContext(**data["orderbook"])
        if "liquidation" in data and isinstance(data["liquidation"], dict):
            ctx.liquidation = LiquidationContext(**data["liquidation"])
        if "regime" in data and isinstance(data["regime"], dict):
            ctx.regime = RegimeContext(**data["regime"])
        
        return ctx


class MarketContextProvider:
    """
    Provides MarketContext snapshots for symbols.
    
    Fetches data from Redis (prices, orderbook, liquidation, features)
    and constructs a unified context for orchestrator decision-making.
    """
    
    def __init__(self, redis_client: Any):
        self.redis = redis_client
        self._context_cache: Dict[str, MarketContext] = {}
        self._cache_ttl_ms = 500  # 500ms cache
    
    def get_context(self, symbol: str, account_id: str = "primary") -> MarketContext:
        """
        Get or create a MarketContext for a symbol.
        
        Caches contexts for 500ms to ensure proposals in the same
        decision window share the same context.
        """
        cache_key = f"{account_id}:{symbol}"
        now_ms = int(time.time() * 1000)
        
        # Check cache
        if cache_key in self._context_cache:
            cached = self._context_cache[cache_key]
            if (now_ms - cached.created_ts_ms) < self._cache_ttl_ms:
                return cached
        
        # Build fresh context
        ctx = self._build_context(symbol, account_id)
        self._context_cache[cache_key] = ctx
        
        return ctx
    
    def _build_context(self, symbol: str, account_id: str) -> MarketContext:
        """Build a MarketContext from Redis data sources."""
        ctx = MarketContext(symbol=symbol, account_id=account_id)
        
        try:
            # 1. Price data
            self._load_price_data(ctx)
            
            # 2. Order book data
            self._load_orderbook_data(ctx)
            
            # 3. Liquidation data
            self._load_liquidation_data(ctx)
            
            # 4. Regime/volatility data
            self._load_regime_data(ctx)
            
            # 5. Feature data
            self._load_feature_data(ctx)

            # Recompute staleness after loading timestamps
            try:
                ctx.recompute_staleness()
            except Exception:
                pass
            
        except Exception as e:
            logger.warning(f"[MARKET_CTX] Error building context for {symbol}: {e}")
            ctx.is_stale = True
            ctx.stale_reason = f"build_error:{e}"
            ctx.data_quality_score = 0.3
        
        return ctx
    
    def _load_price_data(self, ctx: MarketContext):
        """Load price data from Redis."""
        try:
            import json as _json_mc

            sym = str(ctx.symbol or "").strip().upper()
            if not sym:
                return

            # ------------------------------------------------------------------
            # Preferred sources (current Redis contracts)
            # ------------------------------------------------------------------
            # 1) price:realtime:{SYMBOL}  (JSON string) written by realtime_price_provider
            raw_rt = self.redis.get(f"price:realtime:{sym}")
            if raw_rt:
                try:
                    if isinstance(raw_rt, (bytes, bytearray)):
                        raw_rt = raw_rt.decode("utf-8", errors="ignore")
                    if isinstance(raw_rt, str) and raw_rt.strip().startswith("{"):
                        d = _json_mc.loads(raw_rt)
                        if isinstance(d, dict):
                            ctx.mark_price = float(d.get("mark_price") or d.get("mark") or d.get("price") or 0.0)
                            ctx.index_price = float(d.get("index_price") or d.get("index") or ctx.mark_price)
                            ctx.last_trade_price = float(d.get("last_trade_price") or d.get("last") or ctx.mark_price)
                            ctx.price_source = str(d.get("source") or d.get("price_source") or "price:realtime")
                            ctx.price_ts_ms = int(
                                d.get("ts_ms")
                                or d.get("timestamp_ms")
                                or d.get("timestamp")
                                or d.get("ts")
                                or 0
                            )
                            return
                except Exception:
                    pass

            # 2) latest:binance:mark_price:{SYMBOL} (JSON string) written by live_binance
            raw_mp = self.redis.get(f"latest:binance:mark_price:{sym}")
            if raw_mp:
                try:
                    if isinstance(raw_mp, (bytes, bytearray)):
                        raw_mp = raw_mp.decode("utf-8", errors="ignore")
                    if isinstance(raw_mp, str) and raw_mp.strip().startswith("{"):
                        d = _json_mc.loads(raw_mp)
                        if isinstance(d, dict):
                            ctx.mark_price = float(d.get("mark_price") or d.get("price") or 0.0)
                            ctx.index_price = float(d.get("index_price") or d.get("index") or ctx.mark_price)
                            ctx.last_trade_price = float(d.get("mark_price") or ctx.mark_price)
                            ctx.price_source = "latest:binance:mark_price"
                            ctx.price_ts_ms = int(
                                d.get("ts_ms")
                                or d.get("timestamp_ms")
                                or d.get("timestamp")
                                or d.get("ts")
                                or 0
                            )
                            return
                except Exception:
                    pass

            # ------------------------------------------------------------------
            # Legacy sources (older/alternate contracts)
            # ------------------------------------------------------------------
            # 3) realtime:prices:{SYMBOL} (HASH)
            price_key = f"realtime:prices:{sym}"
            price_data = self.redis.hgetall(price_key) or {}

            if price_data:
                ctx.mark_price = float(price_data.get("mark", 0) or price_data.get("price", 0) or 0)
                ctx.index_price = float(price_data.get("index", 0) or ctx.mark_price)
                ctx.last_trade_price = float(price_data.get("last", 0) or ctx.mark_price)
                ctx.price_source = str(price_data.get("source", "redis_cache"))
                ctx.price_ts_ms = int(price_data.get("ts_ms", 0) or price_data.get("timestamp", 0) or 0)
                return

            # 4) market:{SYMBOL} (HASH)
            market_key = f"market:{sym}"
            market_data = self.redis.hgetall(market_key) or {}
            if market_data:
                ctx.mark_price = float(market_data.get("mark_price", 0) or market_data.get("price", 0) or 0)
                ctx.price_source = "market_hash"
                ctx.price_ts_ms = int(market_data.get("timestamp", 0) or 0)
                return

            # 5) price:{SYMBOL} (string; sometimes JSON, sometimes numeric)
            raw_p = self.redis.get(f"price:{sym}")
            if raw_p:
                try:
                    if isinstance(raw_p, (bytes, bytearray)):
                        raw_p = raw_p.decode("utf-8", errors="ignore")
                    s = str(raw_p).strip()
                    if s.startswith("{"):
                        d = _json_mc.loads(s)
                        if isinstance(d, dict):
                            ctx.mark_price = float(d.get("mark_price") or d.get("price") or ctx.mark_price or 0.0)
                            ctx.index_price = float(d.get("index_price") or d.get("index") or ctx.mark_price)
                            ctx.last_trade_price = float(d.get("last_trade_price") or d.get("last") or ctx.mark_price)
                            ctx.price_source = str(d.get("source") or d.get("price_source") or "price")
                            ctx.price_ts_ms = int(
                                d.get("ts_ms")
                                or d.get("timestamp_ms")
                                or d.get("timestamp")
                                or d.get("ts")
                                or 0
                            )
                    else:
                        ctx.mark_price = float(s)
                        if ctx.index_price <= 0 and ctx.mark_price > 0:
                            ctx.index_price = float(ctx.mark_price)
                        if ctx.last_trade_price <= 0 and ctx.mark_price > 0:
                            ctx.last_trade_price = float(ctx.mark_price)
                        if not ctx.price_source:
                            ctx.price_source = "price"
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"[MARKET_CTX] Price load error for {ctx.symbol}: {e}")
    
    def _load_orderbook_data(self, ctx: MarketContext):
        """Load order book data from Redis."""
        try:
            # Order book microstructure
            ob_key = f"orderbook:{ctx.symbol}"
            ob_data = self.redis.hgetall(ob_key)
            
            if ob_data:
                ctx.orderbook.mid_price = float(ob_data.get("mid", 0) or ctx.mark_price)
                ctx.orderbook.spread_bps = float(ob_data.get("spread_bps", 0) or 0)
                ctx.orderbook.bid_depth_usd = float(ob_data.get("bid_depth_usd", 0) or 0)
                ctx.orderbook.ask_depth_usd = float(ob_data.get("ask_depth_usd", 0) or 0)
                ctx.orderbook.imbalance = float(ob_data.get("imbalance", 0) or 0)
                ctx.orderbook.microprice = float(ob_data.get("microprice", 0) or ctx.orderbook.mid_price)
                ctx.orderbook.book_slope = float(ob_data.get("book_slope", 0) or 0)
            
            # Toxicity scores
            tox_key = f"toxicity:{ctx.symbol}"
            tox_data = self.redis.hgetall(tox_key)
            
            if tox_data:
                ctx.orderbook.spoof_score = float(tox_data.get("spoof_score", 0) or 0)
                ctx.orderbook.churn_score = float(tox_data.get("churn_score", 0) or 0)
                ctx.orderbook.toxicity_score = float(tox_data.get("toxicity_score", 0) or 0)
        except Exception as e:
            logger.debug(f"[MARKET_CTX] Orderbook load error for {ctx.symbol}: {e}")
    
    def _load_liquidation_data(self, ctx: MarketContext):
        """Load liquidation map data from Redis."""
        try:
            liq_key = f"liquidation_levels:{ctx.symbol}"
            liq_data = self.redis.hgetall(liq_key)
            
            if liq_data:
                ctx.liquidation.nearest_liq_above_usd = float(liq_data.get("nearest_above", 0) or 0)
                ctx.liquidation.nearest_liq_below_usd = float(liq_data.get("nearest_below", 0) or 0)
                ctx.liquidation.distance_to_above_pct = float(liq_data.get("dist_above_pct", 0) or 0)
                ctx.liquidation.distance_to_below_pct = float(liq_data.get("dist_below_pct", 0) or 0)
                ctx.liquidation.density_above = float(liq_data.get("density_above", 0) or 0)
                ctx.liquidation.density_below = float(liq_data.get("density_below", 0) or 0)
                ctx.liquidation.heatmap_bias = float(liq_data.get("heatmap_bias", 0) or 0)
                ctx.liquidation.total_liq_volume_24h = float(liq_data.get("total_volume_24h", 0) or 0)
        except Exception as e:
            logger.debug(f"[MARKET_CTX] Liquidation load error for {ctx.symbol}: {e}")
    
    def _load_regime_data(self, ctx: MarketContext):
        """Load regime/volatility data from Redis."""
        try:
            # Regime classification
            regime_key = f"regime:{ctx.symbol}"
            _regime_raw = self.redis.get(regime_key)
            regime_data = None
            if _regime_raw:
                import json as _json_mc
                if isinstance(_regime_raw, (bytes, bytearray)):
                    _regime_raw = _regime_raw.decode("utf-8", errors="ignore")
                regime_data = _json_mc.loads(_regime_raw)
            
            if regime_data:
                ctx.regime.regime = str(regime_data.get("move_regime") or regime_data.get("regime", "unknown") or "unknown")
                ctx.regime.regime_confidence = float(regime_data.get("confidence", 0) or 0)
                ctx.regime.volatility_percentile = float(regime_data.get("volatility_score") or regime_data.get("vol_percentile", 0.5) or 0.5)
                ctx.regime.trend_strength = float(regime_data.get("tf_alignment") or regime_data.get("trend_strength", 0) or 0)
                ctx.regime.mean_reversion_prob = float(regime_data.get("mr_prob", 0.5) or 0.5)
            
            # Fast move detection
            fm_key = f"fast_move:{ctx.symbol}"
            fm_data = self.redis.hgetall(fm_key)
            
            if fm_data:
                ctx.regime.fast_move_pct = float(fm_data.get("move_pct", 0) or 0)
                ctx.regime.fast_move_persistence = float(fm_data.get("persistence", 0) or 0)
        except Exception as e:
            logger.debug(f"[MARKET_CTX] Regime load error for {ctx.symbol}: {e}")
    
    def _load_feature_data(self, ctx: MarketContext):
        """Load feature data from Redis."""
        try:
            # Check unified features
            feat_key = f"unified_features:{ctx.symbol}:5m"
            feat_data = self.redis.hgetall(feat_key)
            
            if feat_data:
                ctx.featureset_version = str(feat_data.get("version", "") or "")
                ctx.feature_ts_ms = int(feat_data.get("ts_ms", 0) or feat_data.get("timestamp", 0) or 0)
                
                # Extract top features if available
                top_feats_raw = feat_data.get("top_features", "")
                if top_feats_raw:
                    try:
                        ctx.top_features = json.loads(top_feats_raw)
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"[MARKET_CTX] Feature load error for {ctx.symbol}: {e}")
    
    def clear_cache(self):
        """Clear the context cache."""
        self._context_cache.clear()


# Global instance (lazy init)
_global_provider: Optional[MarketContextProvider] = None


def get_market_context_provider(redis_client: Any) -> MarketContextProvider:
    """Get or create the global MarketContextProvider."""
    global _global_provider
    if _global_provider is None:
        _global_provider = MarketContextProvider(redis_client)
    return _global_provider


def get_market_context(redis_client: Any, symbol: str, account_id: str = "primary") -> MarketContext:
    """Convenience function to get a MarketContext."""
    provider = get_market_context_provider(redis_client)
    return provider.get_context(symbol, account_id)
