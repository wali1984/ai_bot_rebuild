"""
Data Normalization Utilities
Canonical symbol mapping, timestamp standardization, and schema normalization

Feature Flag: ENABLE_NORMALIZATION in config.py (default: True for new behavior, False for legacy)
"""

import time
from typing import Any, Dict, Optional, Union
from datetime import datetime


class SymbolNormalizer:
    """
    Canonical symbol mapping across different exchange formats
    
    Handles:
    - BTCUSDT (Binance format) - CANONICAL
    - BTC/USDT (CCXT format)
    - BTC-USDT (KuCoin/Some APIs)
    - BTC_USDT (Some APIs)
    - btcusdt (lowercase)
    - BINANCEFTS_PERP_BTC_USDT (CoinAPI format)
    
    All normalized to: BTCUSDT (uppercase, no separator)
    """
    
    # Mapping of alternative formats to canonical
    _symbol_map = {}
    _initialized = False
    _last_refresh = 0
    _REFRESH_INTERVAL = 60  # Refresh symbol list every 60 seconds
    
    @classmethod
    def _get_canonical_symbols(cls) -> list:
        """Get canonical symbols from dynamic symbol manager or config fallback."""
        try:
            from utils.symbol_manager import get_active_symbols
            symbols = get_active_symbols()
            if symbols:
                return symbols
        except ImportError:
            pass
        except Exception:
            pass
        
        # Fallback to config
        try:
            from config import SYMBOLS
            return list(SYMBOLS)
        except ImportError:
            # Last resort defaults
            return [
                "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
                "LINKUSDT", "UNIUSDT", "LTCUSDT"
            ]
    
    @classmethod
    def initialize(cls, force_refresh: bool = False):
        """Build symbol mapping table from dynamic symbol list."""
        now = time.time()
        
        # Check if refresh is needed
        if cls._initialized and not force_refresh:
            if (now - cls._last_refresh) < cls._REFRESH_INTERVAL:
                return  # Use cached mapping
        
        # Get current canonical symbols
        canonical_symbols = cls._get_canonical_symbols()
        
        # Rebuild mapping
        cls._symbol_map = {}
        
        for canonical in canonical_symbols:
            cls._add_symbol_variants(canonical)
        
        cls._initialized = True
        cls._last_refresh = now
    
    @classmethod
    def _add_symbol_variants(cls, canonical: str):
        """Add all format variants for a canonical symbol."""
        canonical = canonical.upper().strip()
        
        # Base canonical
        cls._symbol_map[canonical] = canonical
        cls._symbol_map[canonical.lower()] = canonical
        
        # Extract base and quote
        # Handle common quote currencies
        for quote in ['USDT', 'BUSD', 'USD', 'USDC']:
            if canonical.endswith(quote):
                base = canonical[:-len(quote)]
                
                # Slash format (CCXT)
                cls._symbol_map[f"{base}/{quote}"] = canonical
                cls._symbol_map[f"{base.lower()}/{quote.lower()}"] = canonical
                cls._symbol_map[f"{base}/{quote}".lower()] = canonical
                
                # Dash format (KuCoin)
                cls._symbol_map[f"{base}-{quote}"] = canonical
                cls._symbol_map[f"{base.lower()}-{quote.lower()}"] = canonical
                
                # Underscore format
                cls._symbol_map[f"{base}_{quote}"] = canonical
                cls._symbol_map[f"{base.lower()}_{quote.lower()}"] = canonical
                
                # Base only (when quote is implied)
                cls._symbol_map[base] = canonical
                cls._symbol_map[base.lower()] = canonical
                
                # CoinAPI format: BINANCEFTS_PERP_BTC_USDT
                cls._symbol_map[f"BINANCEFTS_PERP_{base}_{quote}"] = canonical
                cls._symbol_map[f"BINANCE_PERP_{base}_{quote}"] = canonical
                cls._symbol_map[f"BINANCE_SPOT_{base}_{quote}"] = canonical
                
                # Futures suffix format
                cls._symbol_map[f"{base}{quote}:USDT"] = canonical
                cls._symbol_map[f"{base}/{quote}:USDT"] = canonical
                
                break
    
    @classmethod
    def normalize(cls, symbol: str) -> Optional[str]:
        """
        Normalize symbol to canonical format
        
        Args:
            symbol: Symbol in any format
        
        Returns:
            Canonical symbol (BTCUSDT format) or None if unknown
        """
        # Initialize/refresh if needed
        cls.initialize()
        
        if not symbol:
            return None
        
        symbol = str(symbol).strip()
        
        # Direct lookup
        if symbol in cls._symbol_map:
            return cls._symbol_map[symbol]
        
        # Try uppercase
        upper = symbol.upper()
        if upper in cls._symbol_map:
            return cls._symbol_map[upper]
        
        # Try removing common separators
        for sep in ['/', '-', '_', ' ', ':']:
            if sep in symbol:
                cleaned = symbol.replace(sep, '').upper()
                if cleaned in cls._symbol_map:
                    return cls._symbol_map[cleaned]
        
        # Try extracting from CoinAPI format: BINANCEFTS_PERP_BTC_USDT
        if '_PERP_' in symbol.upper() or '_SPOT_' in symbol.upper():
            parts = symbol.upper().split('_')
            if len(parts) >= 4:
                base = parts[-2]
                quote = parts[-1]
                candidate = f"{base}{quote}"
                if candidate in cls._symbol_map:
                    return cls._symbol_map[candidate]
        
        # Unknown symbol - but might be a new one we should recognize
        # Try auto-normalizing if it looks like a valid symbol
        cleaned = ''.join(c for c in symbol.upper() if c.isalnum())
        if cleaned.endswith('USDT') and len(cleaned) > 4:
            # Looks like a valid USDT pair - add it dynamically
            cls._add_symbol_variants(cleaned)
            return cleaned
        
        return None
    
    @classmethod
    def is_valid(cls, symbol: str) -> bool:
        """Check if symbol is valid (can be normalized)"""
        return cls.normalize(symbol) is not None
    
    @classmethod
    def refresh(cls):
        """Force refresh the symbol mapping from dynamic source."""
        cls.initialize(force_refresh=True)
    
    @classmethod
    def get_all_canonical(cls) -> list:
        """Get all canonical symbols."""
        cls.initialize()
        return cls._get_canonical_symbols()
    
    @classmethod
    def to_ccxt(cls, symbol: str) -> Optional[str]:
        """Convert canonical symbol to CCXT format (BTC/USDT)."""
        canonical = cls.normalize(symbol)
        if canonical and canonical.endswith('USDT'):
            base = canonical[:-4]
            return f"{base}/USDT"
        return None
    
    @classmethod
    def to_kucoin(cls, symbol: str) -> Optional[str]:
        """Convert canonical symbol to KuCoin format (BTC-USDT)."""
        canonical = cls.normalize(symbol)
        if canonical and canonical.endswith('USDT'):
            base = canonical[:-4]
            return f"{base}-USDT"
        return None
    
    @classmethod
    def to_coinapi(cls, symbol: str, market_type: str = "PERP") -> Optional[str]:
        """Convert canonical symbol to CoinAPI format (BINANCEFTS_PERP_BTC_USDT)."""
        canonical = cls.normalize(symbol)
        if canonical and canonical.endswith('USDT'):
            base = canonical[:-4]
            prefix = "BINANCEFTS" if market_type == "PERP" else "BINANCE"
            return f"{prefix}_{market_type}_{base}_USDT"
        return None


class TimestampNormalizer:
    """
    Standardize timestamp formats across all sources
    
    Canonical format: milliseconds since epoch (int)
    
    Handles:
    - Seconds (float or int)
    - Milliseconds (int)
    - Datetime strings (ISO 8601)
    - Datetime objects
    """
    
    @staticmethod
    def normalize(ts: Union[int, float, str, datetime, None]) -> int:
        """
        Convert any timestamp format to milliseconds
        
        Args:
            ts: Timestamp in various formats
        
        Returns:
            Timestamp in milliseconds (int)
        """
        if ts is None:
            return int(time.time() * 1000)
        
        # Already milliseconds (> year 2200 in seconds)
        if isinstance(ts, int) and ts > 10**12:
            return ts
        
        # Seconds (float or int)
        if isinstance(ts, (int, float)) and ts > 0:
            return int(ts * 1000)
        
        # ISO 8601 string
        if isinstance(ts, str):
            try:
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                return int(dt.timestamp() * 1000)
            except:
                # Try parsing as float
                try:
                    return TimestampNormalizer.normalize(float(ts))
                except:
                    return int(time.time() * 1000)
        
        # Datetime object
        if isinstance(ts, datetime):
            return int(ts.timestamp() * 1000)
        
        # Default to current time
        return int(time.time() * 1000)
    
    @staticmethod
    def to_seconds(ts_ms: int) -> float:
        """Convert milliseconds to seconds (float)"""
        return ts_ms / 1000.0
    
    @staticmethod
    def to_datetime(ts_ms: int) -> datetime:
        """Convert milliseconds to datetime object"""
        return datetime.fromtimestamp(ts_ms / 1000.0)
    
    @staticmethod
    def is_fresh(ts_ms: int, max_age_sec: int = 60) -> bool:
        """
        Check if timestamp is fresh (within max_age_sec of now)
        
        Args:
            ts_ms: Timestamp in milliseconds
            max_age_sec: Maximum age in seconds
        
        Returns:
            True if fresh, False if stale
        """
        now_ms = int(time.time() * 1000)
        age_ms = now_ms - ts_ms
        return age_ms <= (max_age_sec * 1000)


class SchemaStandardizer:
    """
    Standardize field names and data types across sources
    
    Canonical schema:
    - All field names: lowercase with underscores
    - Prefixes by source: ohlcv_, ta_, tm_, coinank_, ccxt_
    - Numeric fields: float (except timestamps)
    - Timestamps: int (milliseconds)
    """
    
    # Field name mappings (alternative → canonical)
    FIELD_MAPPINGS = {
        # OHLCV fields
        'OPEN': 'open',
        'HIGH': 'high',
        'LOW': 'low',
        'CLOSE': 'close',
        'VOLUME': 'volume',
        'o': 'open',
        'h': 'high',
        'l': 'low',
        'c': 'close',
        'v': 'volume',
        'vol': 'volume',
        
        # Timestamp fields
        'timestamp': 'ts_ms',
        'time': 'ts_ms',
        'ts': 'ts_ms',
        'datetime': 'ts_ms',
        'date': 'ts_ms',
        
        # Symbol field
        'pair': 'symbol',
        'market': 'symbol',
        'ticker': 'symbol',
        'instrument': 'symbol',
        
        # Timeframe field
        'interval': 'timeframe',
        'period': 'timeframe',
        'tf': 'timeframe'
    }
    
    @staticmethod
    def standardize_field_name(name: str, prefix: str = '') -> str:
        """
        Standardize a field name
        
        Args:
            name: Original field name
            prefix: Source prefix (e.g., 'ohlcv_', 'ta_')
        
        Returns:
            Standardized field name
        """
        # Convert to lowercase
        name_lower = name.lower()
        
        # Check if it needs mapping
        if name_lower in SchemaStandardizer.FIELD_MAPPINGS:
            canonical = SchemaStandardizer.FIELD_MAPPINGS[name_lower]
        else:
            canonical = name_lower
        
        # Add prefix if not already present
        if prefix and not canonical.startswith(prefix):
            canonical = f"{prefix}{canonical}"
        
        return canonical
    
    @staticmethod
    def standardize_dict(data: Dict[str, Any], 
                         prefix: str = '',
                         normalize_symbol: bool = True,
                         normalize_timestamp: bool = True) -> Dict[str, Any]:
        """
        Standardize all fields in a dictionary
        
        Args:
            data: Original data dictionary
            prefix: Source prefix for field names
            normalize_symbol: Apply symbol normalization
            normalize_timestamp: Apply timestamp normalization
        
        Returns:
            Standardized dictionary
        """
        standardized = {}
        
        for key, value in data.items():
            # Standardize field name
            std_key = SchemaStandardizer.standardize_field_name(key, prefix)
            
            # Apply normalization based on field
            if normalize_symbol and std_key in ['symbol', f'{prefix}symbol']:
                value = SymbolNormalizer.normalize(str(value)) or value
            
            if normalize_timestamp and std_key in ['ts_ms', f'{prefix}ts_ms', 'timestamp']:
                value = TimestampNormalizer.normalize(value)
            
            # Type conversion for numeric fields
            if isinstance(value, str) and std_key not in ['symbol', f'{prefix}symbol', 'timeframe', f'{prefix}timeframe']:
                try:
                    # Try converting to float
                    value = float(value)
                except (ValueError, TypeError):
                    pass  # Keep as string if conversion fails
            
            standardized[std_key] = value
        
        return standardized


class DataNormalizer:
    """
    Main normalization facade - combines all normalizers
    
    Usage:
        # Initialize on startup
        DataNormalizer.initialize()
        
        # Normalize data from any source
        normalized = DataNormalizer.normalize(
            raw_data,
            source='binance',
            data_type='ohlcv'
        )
    """
    
    # Source-specific prefixes
    SOURCE_PREFIXES = {
        'binance': 'ohlcv_',
        'kucoin': 'ohlcv_',
        'ccxt': 'ccxt_',
        'tokenmetrics': 'tm_',
        'coinank': 'coinank_',
        'talib': 'ta_',
        'historical': 'ohlcv_',
        'unified': ''  # No prefix for unified features
    }
    
    _initialized = False
    
    @classmethod
    def initialize(cls):
        """Initialize all normalizers"""
        if cls._initialized:
            return
        
        SymbolNormalizer.initialize()
        cls._initialized = True
    
    @classmethod
    def normalize(cls,
                  data: Dict[str, Any],
                  source: str = 'unknown',
                  data_type: str = 'generic',
                  enable_normalization: bool = True) -> Dict[str, Any]:
        """
        Normalize data from any source
        
        Args:
            data: Raw data dictionary
            source: Data source name (binance, tokenmetrics, coinank, etc.)
            data_type: Data type (ohlcv, ta, features, etc.)
            enable_normalization: Feature flag (False = passthrough for legacy)
        
        Returns:
            Normalized data dictionary
        """
        # Feature flag: disable for legacy mode
        if not enable_normalization:
            return data
        
        # Ensure initialized
        if not cls._initialized:
            cls.initialize()
        
        # Get prefix for source
        prefix = cls.SOURCE_PREFIXES.get(source.lower(), '')
        
        # Standardize the dictionary
        normalized = SchemaStandardizer.standardize_dict(
            data,
            prefix=prefix,
            normalize_symbol=True,
            normalize_timestamp=True
        )
        
        return normalized
    
    @classmethod
    def normalize_symbol(cls, symbol: str) -> Optional[str]:
        """Convenience method for symbol normalization"""
        if not cls._initialized:
            cls.initialize()
        return SymbolNormalizer.normalize(symbol)
    
    @classmethod
    def normalize_timestamp(cls, ts: Any) -> int:
        """Convenience method for timestamp normalization"""
        return TimestampNormalizer.normalize(ts)


# Initialize on module import
DataNormalizer.initialize()


# Convenience functions for direct use
def normalize_symbol(symbol: str) -> Optional[str]:
    """Normalize symbol to canonical format"""
    return DataNormalizer.normalize_symbol(symbol)


def normalize_timestamp(ts: Any) -> int:
    """Normalize timestamp to milliseconds"""
    return DataNormalizer.normalize_timestamp(ts)


def normalize_data(data: Dict[str, Any], 
                   source: str = 'unknown',
                   enable: bool = True) -> Dict[str, Any]:
    """Normalize data dictionary from any source"""
    return DataNormalizer.normalize(data, source=source, enable_normalization=enable)


if __name__ == '__main__':
    # Test normalization
    print("Testing Data Normalization")
    print("=" * 80)
    
    # Test symbol normalization
    test_symbols = [
        'BTCUSDT', 'btcusdt', 'BTC/USDT', 'BTC-USDT', 'BTC',
        'ETHUSDT', 'eth/usdt', 'ETH-USDT'
    ]
    
    print("\n1. Symbol Normalization:")
    for sym in test_symbols:
        normalized = normalize_symbol(sym)
        print(f"  {sym:15s} → {normalized}")
    
    # Test timestamp normalization
    test_timestamps = [
        1728345600,           # Seconds
        1728345600000,        # Milliseconds
        1728345600.123,       # Seconds with decimals
        '2025-10-07T12:00:00Z',  # ISO string
        time.time()           # Current time
    ]
    
    print("\n2. Timestamp Normalization:")
    for ts in test_timestamps:
        normalized = normalize_timestamp(ts)
        print(f"  {str(ts):25s} → {normalized} ms")
    
    # Test data normalization
    test_data = {
        'symbol': 'btc/usdt',
        'OPEN': '50000.5',
        'HIGH': '51000.25',
        'low': '49500',
        'c': 50500.75,
        'vol': 1234567,
        'timestamp': 1728345600
    }
    
    print("\n3. Data Normalization (Binance OHLCV):")
    print(f"  Input: {test_data}")
    normalized_data = normalize_data(test_data, source='binance')
    print(f"  Output: {normalized_data}")
    
    print("\n✅ Normalization tests complete")
