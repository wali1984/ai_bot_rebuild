"""
CoinAPI Symbol Mapping
======================
Maps internal symbols (e.g., BTCUSDT) to CoinAPI symbol IDs.

Uses REST /v1/symbols endpoint with caching in Redis.
Supports manual overrides via config for problematic pairs.

Author: WMA AI Trading System
Date: December 24, 2025
"""

import os
import json
import time
import logging
import requests
from typing import Dict, Optional, List, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CoinAPISymbol:
    """CoinAPI symbol mapping result."""
    internal_symbol: str
    coinapi_symbol_id: str
    exchange_id: str
    asset_base: str
    asset_quote: str
    market_type: str  # "futures" or "spot"
    updated_ts_ms: int
    source: str = "api"  # "api", "override", "cache"


class CoinAPISymbolMapper:
    """
    Maps internal trading symbols to CoinAPI symbol IDs.
    
    Features:
    - REST /v1/symbols discovery with filters
    - Redis caching with configurable TTL
    - Manual overrides from config
    - Graceful fallback on failures
    """
    
    CACHE_KEY_PREFIX = "coinapi:symbolmap"
    
    def __init__(
        self,
        redis_client: Any = None,
        api_key: str = "",
        rest_url: str = "https://rest.coinapi.io",
        primary_exchange_id: str = "BINANCEFTS",
        cache_ttl_sec: int = 86400,
        overrides: Optional[Dict[str, str]] = None,
    ):
        self.redis = redis_client
        self.api_key = api_key or os.getenv("COINAPI_API_KEY", "")
        self.rest_url = rest_url
        self.primary_exchange_id = primary_exchange_id
        self.cache_ttl_sec = cache_ttl_sec
        
        # Load overrides
        self.overrides = overrides or {}
        overrides_json = os.getenv("COINAPI_SYMBOL_OVERRIDES_JSON", "{}")
        try:
            env_overrides = json.loads(overrides_json)
            self.overrides.update(env_overrides)
        except json.JSONDecodeError:
            logger.warning(f"[COINAPI_SYMBOLMAP] Invalid COINAPI_SYMBOL_OVERRIDES_JSON: {overrides_json}")
        
        # In-memory cache
        self._memory_cache: Dict[str, CoinAPISymbol] = {}
        self._all_symbols_cache: Optional[List[Dict]] = None
        self._all_symbols_cache_ts: float = 0
        
        # Rate limiting for REST calls
        self._last_api_call_ts: float = 0
        self._min_api_interval_sec: float = 2.0
        
        logger.info(
            f"CoinAPISymbolMapper initialized | "
            f"exchange={self.primary_exchange_id} | "
            f"cache_ttl={self.cache_ttl_sec}s | "
            f"overrides={len(self.overrides)}"
        )
    
    def _get_cache_key(self, internal_symbol: str) -> str:
        """Get Redis cache key for a symbol."""
        return f"{self.CACHE_KEY_PREFIX}:{internal_symbol}"
    
    def _get_from_cache(self, internal_symbol: str) -> Optional[CoinAPISymbol]:
        """Try to get mapping from cache."""
        # Check memory cache first
        if internal_symbol in self._memory_cache:
            cached = self._memory_cache[internal_symbol]
            age_ms = int(time.time() * 1000) - cached.updated_ts_ms
            if age_ms < self.cache_ttl_sec * 1000:
                return cached
        
        # Check Redis cache
        if self.redis:
            try:
                key = self._get_cache_key(internal_symbol)
                raw = self.redis.hgetall(key)
                if raw:
                    data = {}
                    for k, v in raw.items():
                        k_str = k.decode('utf-8') if isinstance(k, bytes) else k
                        v_str = v.decode('utf-8') if isinstance(v, bytes) else v
                        data[k_str] = v_str
                    
                    if data.get('coinapi_symbol_id'):
                        result = CoinAPISymbol(
                            internal_symbol=internal_symbol,
                            coinapi_symbol_id=data['coinapi_symbol_id'],
                            exchange_id=data.get('exchange_id', ''),
                            asset_base=data.get('asset_base', ''),
                            asset_quote=data.get('asset_quote', ''),
                            market_type=data.get('market_type', 'futures'),
                            updated_ts_ms=int(data.get('updated_ts_ms', 0)),
                            source='cache',
                        )
                        self._memory_cache[internal_symbol] = result
                        return result
            except Exception as e:
                logger.debug(f"[COINAPI_SYMBOLMAP] Redis cache read error: {e}")
        
        return None
    
    def _save_to_cache(self, mapping: CoinAPISymbol):
        """Save mapping to cache."""
        self._memory_cache[mapping.internal_symbol] = mapping
        
        if self.redis:
            try:
                key = self._get_cache_key(mapping.internal_symbol)
                self.redis.hset(key, mapping={
                    'coinapi_symbol_id': mapping.coinapi_symbol_id,
                    'exchange_id': mapping.exchange_id,
                    'asset_base': mapping.asset_base,
                    'asset_quote': mapping.asset_quote,
                    'market_type': mapping.market_type,
                    'updated_ts_ms': str(mapping.updated_ts_ms),
                    'source': mapping.source,
                })
                self.redis.expire(key, self.cache_ttl_sec)
            except Exception as e:
                logger.debug(f"[COINAPI_SYMBOLMAP] Redis cache write error: {e}")
    
    def _fetch_all_symbols(self, force: bool = False) -> List[Dict]:
        """Fetch all symbols from REST API (cached)."""
        now = time.time()
        
        # Check cache
        if not force and self._all_symbols_cache is not None:
            if now - self._all_symbols_cache_ts < 3600:  # 1 hour cache
                return self._all_symbols_cache
        
        # Rate limit
        if now - self._last_api_call_ts < self._min_api_interval_sec:
            time.sleep(self._min_api_interval_sec - (now - self._last_api_call_ts))
        
        if not self.api_key:
            logger.warning("[COINAPI_SYMBOLMAP] No API key configured")
            return []
        
        try:
            url = f"{self.rest_url}/v1/symbols"
            params = {
                'filter_exchange_id': self.primary_exchange_id,
            }
            headers = {'X-CoinAPI-Key': self.api_key}
            
            self._last_api_call_ts = time.time()
            response = requests.get(url, params=params, headers=headers, timeout=30)
            
            if response.status_code == 429:
                logger.warning("[COINAPI_SYMBOLMAP] Rate limited (429) - backing off")
                return self._all_symbols_cache or []
            
            response.raise_for_status()
            symbols = response.json()
            
            self._all_symbols_cache = symbols
            self._all_symbols_cache_ts = now
            
            logger.info(f"[COINAPI_SYMBOLMAP] Fetched {len(symbols)} symbols from CoinAPI")
            return symbols
            
        except requests.exceptions.RequestException as e:
            logger.error(f"[COINAPI_SYMBOLMAP] REST API error: {e}")
            return self._all_symbols_cache or []
        except Exception as e:
            logger.error(f"[COINAPI_SYMBOLMAP] Error fetching symbols: {e}")
            return self._all_symbols_cache or []
    
    def _find_best_match(
        self,
        internal_symbol: str,
        all_symbols: List[Dict],
        market_type: str = "futures",
    ) -> Optional[Dict]:
        """Find the best matching CoinAPI symbol for an internal symbol."""
        # Parse internal symbol (e.g., BTCUSDT -> BTC, USDT)
        # Common patterns: BTCUSDT, 1000SHIBUSDT, BTCUSD_PERP
        internal_upper = internal_symbol.upper()
        
        # Try to extract base and quote
        quote_candidates = ['USDT', 'USD', 'BUSD', 'USDC', 'BTC', 'ETH']
        base = internal_upper
        quote = ''
        
        for q in quote_candidates:
            if internal_upper.endswith(q):
                base = internal_upper[:-len(q)]
                quote = q
                break
        
        # Handle special prefixes like 1000
        base_clean = base
        if base.startswith('1000'):
            base_clean = base[4:]  # Remove 1000 prefix
        
        # Score each symbol
        candidates = []
        for sym in all_symbols:
            sym_id = sym.get('symbol_id', '')
            sym_type = sym.get('symbol_type', '')
            asset_base = sym.get('asset_id_base', '')
            asset_quote = sym.get('asset_id_quote', '')
            exchange_id = sym.get('exchange_id', '')
            
            # Filter by exchange
            if exchange_id != self.primary_exchange_id:
                continue
            
            # Filter by market type
            if market_type == "futures":
                if 'PERP' not in sym_id and 'FUT' not in sym_id and sym_type != 'PERPETUAL':
                    continue
            elif market_type == "spot":
                if 'PERP' in sym_id or 'FUT' in sym_id or sym_type == 'PERPETUAL':
                    continue
            
            # Score match
            score = 0
            
            # Exact base match
            if asset_base.upper() == base.upper() or asset_base.upper() == base_clean.upper():
                score += 10
            elif base.upper() in sym_id or base_clean.upper() in sym_id:
                score += 5
            
            # Quote match
            if asset_quote.upper() == quote.upper():
                score += 5
            elif quote.upper() in sym_id:
                score += 2
            
            # PERP bonus for futures
            if market_type == "futures" and 'PERP' in sym_id:
                score += 3
            
            if score > 0:
                candidates.append((score, sym))
        
        # Sort by score and return best
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]
        
        return None
    
    def get_coinapi_symbol_id(
        self,
        internal_symbol: str,
        market_type: str = "futures",
    ) -> Optional[CoinAPISymbol]:
        """
        Get CoinAPI symbol ID for an internal symbol.
        
        Args:
            internal_symbol: Internal symbol like "BTCUSDT"
            market_type: "futures" or "spot"
            
        Returns:
            CoinAPISymbol with mapping, or None if not found
        """
        internal_upper = internal_symbol.upper()
        
        # Check for manual override first
        if internal_upper in self.overrides:
            coinapi_id = self.overrides[internal_upper]
            result = CoinAPISymbol(
                internal_symbol=internal_upper,
                coinapi_symbol_id=coinapi_id,
                exchange_id=self.primary_exchange_id,
                asset_base='',
                asset_quote='',
                market_type=market_type,
                updated_ts_ms=int(time.time() * 1000),
                source='override',
            )
            self._save_to_cache(result)
            return result
        
        # Check cache
        cached = self._get_from_cache(internal_upper)
        if cached:
            return cached
        
        # Fetch from API
        all_symbols = self._fetch_all_symbols()
        if not all_symbols:
            logger.warning(f"[COINAPI_SYMBOLMAP] No symbols available for mapping {internal_symbol}")
            return None
        
        # Find best match
        match = self._find_best_match(internal_upper, all_symbols, market_type)
        if not match:
            logger.warning(f"[COINAPI_SYMBOLMAP] No match found for {internal_symbol}")
            return None
        
        result = CoinAPISymbol(
            internal_symbol=internal_upper,
            coinapi_symbol_id=match['symbol_id'],
            exchange_id=match.get('exchange_id', ''),
            asset_base=match.get('asset_id_base', ''),
            asset_quote=match.get('asset_id_quote', ''),
            market_type=market_type,
            updated_ts_ms=int(time.time() * 1000),
            source='api',
        )
        
        self._save_to_cache(result)
        logger.info(f"[COINAPI_SYMBOLMAP] Mapped {internal_symbol} -> {result.coinapi_symbol_id}")
        
        return result
    
    def get_all_mapped_symbols(
        self,
        internal_symbols: List[str],
        market_type: str = "futures",
    ) -> Dict[str, CoinAPISymbol]:
        """Map multiple symbols and return dict of successful mappings."""
        results = {}
        for sym in internal_symbols:
            mapping = self.get_coinapi_symbol_id(sym, market_type)
            if mapping:
                results[sym] = mapping
        return results
    
    def clear_cache(self, internal_symbol: Optional[str] = None):
        """Clear cache for a symbol or all symbols."""
        if internal_symbol:
            self._memory_cache.pop(internal_symbol.upper(), None)
            if self.redis:
                self.redis.delete(self._get_cache_key(internal_symbol.upper()))
        else:
            self._memory_cache.clear()
            self._all_symbols_cache = None
            self._all_symbols_cache_ts = 0


# Global instance
_symbol_mapper: Optional[CoinAPISymbolMapper] = None


def get_symbol_mapper(
    redis_client: Any = None,
    force_new: bool = False,
) -> CoinAPISymbolMapper:
    """Get global symbol mapper instance."""
    global _symbol_mapper
    if _symbol_mapper is None or force_new:
        from config import (
            COINAPI_API_KEY, COINAPI_REST_URL, COINAPI_PRIMARY_EXCHANGE_ID,
            COINAPI_SYMBOL_MAP_TTL_SEC,
        )
        _symbol_mapper = CoinAPISymbolMapper(
            redis_client=redis_client,
            api_key=COINAPI_API_KEY,
            rest_url=COINAPI_REST_URL,
            primary_exchange_id=COINAPI_PRIMARY_EXCHANGE_ID,
            cache_ttl_sec=COINAPI_SYMBOL_MAP_TTL_SEC,
        )
    elif redis_client is not None and _symbol_mapper.redis is None:
        _symbol_mapper.redis = redis_client
    return _symbol_mapper

