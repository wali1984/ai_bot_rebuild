"""
Unified Symbol Manager - Dynamic symbol management without service restarts

Usage:
    # Add symbols
    python -m utils.symbol_manager add PEPEUSDT WIFUSDT
    
    # Remove symbols
    python -m utils.symbol_manager remove WIFUSDT
    
    # List current symbols
    python -m utils.symbol_manager list
    
    # Check system capacity
    python -m utils.symbol_manager capacity
    
    # Reload from config (reset to config.py defaults)
    python -m utils.symbol_manager reload

All services (trainer, traders, ingestors) will automatically pick up changes
within their next cycle (typically <60 seconds).

USAGE IN OTHER MODULES:
    # Option 1: Direct import (recommended for simple cases)
    from utils.symbol_manager import get_active_symbols
    symbols = get_active_symbols()
    
    # Option 2: With caching (recommended for loops)
    from utils.symbol_manager import get_symbols_cached
    symbols = get_symbols_cached()  # Caches for 30 seconds
    
    # Option 3: Fallback pattern (for backwards compatibility)
    try:
        from utils.symbol_manager import get_active_symbols
        SYMBOLS = get_active_symbols()
    except ImportError:
        from config import SYMBOLS
"""

import os
import sys
import json
import time
import logging
from typing import List, Optional, Set, Dict, Any, Tuple

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

# Redis keys
SYMBOLS_KEY = "config:symbols:active"
SYMBOLS_LOCK_KEY = "config:symbols:lock"
SYMBOLS_HISTORY_KEY = "config:symbols:history"
SYMBOLS_LAST_UPDATE_KEY = "config:symbols:last_update"

# Timeframes (from config)
DEFAULT_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h"]


def get_redis():
    """Get Redis client."""
    try:
        from utils.redis_client import get_redis_client
        return get_redis_client()
    except Exception:
        import redis
        return redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            decode_responses=True,
        )


def get_config_symbols() -> List[str]:
    """Get symbols from config.py (source of truth for defaults)."""
    try:
        from config import SYMBOLS
        return list(SYMBOLS)
    except Exception:
        return []


def get_active_symbols(redis_client=None) -> List[str]:
    """
    Get currently active symbols.
    Priority: Redis > config.py
    
    This is the function services should call to get the symbol list.
    """
    redis_client = redis_client or get_redis()
    
    try:
        # Try Redis first (hot-reloadable)
        raw = redis_client.get(SYMBOLS_KEY)
        if raw:
            # RedisClient wrapper already does JSON parsing, check type
            if isinstance(raw, list):
                return raw
            # Fallback for raw redis.Redis client
            elif isinstance(raw, (str, bytes)):
                symbols = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode())
                if symbols and isinstance(symbols, list):
                    return symbols
    except Exception as e:
        logger.debug(f"Redis symbols lookup failed: {e}")
    
    # Fallback to config.py
    return get_config_symbols()


def set_active_symbols(symbols: List[str], redis_client=None, reason: str = "manual") -> bool:
    """
    Set active symbols in Redis.
    Notifies all services via pub/sub.
    """
    redis_client = redis_client or get_redis()
    
    # Validate symbols
    symbols = [s.upper().strip() for s in symbols if s and isinstance(s, str)]
    symbols = list(dict.fromkeys(symbols))  # Remove duplicates, preserve order
    
    if not symbols:
        logger.error("Cannot set empty symbol list")
        return False
    
    try:
        # Acquire lock
        lock_acquired = redis_client.set(SYMBOLS_LOCK_KEY, "1", nx=True, ex=30)
        if not lock_acquired:
            logger.warning("Could not acquire lock for symbol update")
            return False
        
        try:
            # Get previous symbols for history
            prev_symbols = get_active_symbols(redis_client)
            
            # Store new symbols
            redis_client.set(SYMBOLS_KEY, json.dumps(symbols))
            redis_client.set(SYMBOLS_LAST_UPDATE_KEY, json.dumps({
                "timestamp": time.time(),
                "reason": reason,
                "count": len(symbols),
                "added": list(set(symbols) - set(prev_symbols)),
                "removed": list(set(prev_symbols) - set(symbols)),
            }))
            
            # Add to history (keep last 100 changes)
            history_entry = {
                "ts": time.time(),
                "reason": reason,
                "symbols": symbols,
                "prev_count": len(prev_symbols),
                "new_count": len(symbols),
            }
            redis_client.lpush(SYMBOLS_HISTORY_KEY, json.dumps(history_entry))
            redis_client.ltrim(SYMBOLS_HISTORY_KEY, 0, 99)
            
            # Notify all services via pub/sub
            redis_client.publish("config:symbols:updated", json.dumps({
                "symbols": symbols,
                "timestamp": time.time(),
                "reason": reason,
            }))
            
            logger.info(f"✅ Symbols updated: {len(symbols)} active ({reason})")
            return True
            
        finally:
            redis_client.delete(SYMBOLS_LOCK_KEY)
            
    except Exception as e:
        logger.error(f"Failed to set symbols: {e}")
        return False


def add_symbols(symbols_to_add: List[str], redis_client=None) -> bool:
    """Add symbols to the active list."""
    redis_client = redis_client or get_redis()
    
    current = set(get_active_symbols(redis_client))
    to_add = set(s.upper().strip() for s in symbols_to_add if s)
    
    if not to_add:
        logger.warning("No valid symbols to add")
        return False
    
    already_active = to_add & current
    if already_active:
        logger.info(f"Already active: {', '.join(already_active)}")
    
    new_symbols = to_add - current
    if not new_symbols:
        logger.info("All symbols already active")
        return True
    
    # Check capacity before adding
    capacity = check_capacity(redis_client)
    if capacity["can_add"] < len(new_symbols):
        logger.error(f"❌ Cannot add {len(new_symbols)} symbols. Capacity: {capacity['can_add']} more")
        logger.error(f"   GPU limit: {capacity['gpu_max_symbols']} symbols")
        logger.error(f"   Current: {capacity['current_symbols']} symbols")
        return False
    
    updated = list(current | new_symbols)
    return set_active_symbols(updated, redis_client, reason=f"add:{','.join(new_symbols)}")


def remove_symbols(symbols_to_remove: List[str], redis_client=None) -> bool:
    """Remove symbols from the active list."""
    redis_client = redis_client or get_redis()
    
    current = set(get_active_symbols(redis_client))
    to_remove = set(s.upper().strip() for s in symbols_to_remove if s)
    
    if not to_remove:
        logger.warning("No valid symbols to remove")
        return False
    
    not_active = to_remove - current
    if not_active:
        logger.info(f"Not currently active: {', '.join(not_active)}")
    
    to_actually_remove = to_remove & current
    if not to_actually_remove:
        logger.info("No matching symbols to remove")
        return True
    
    updated = list(current - to_actually_remove)
    if not updated:
        logger.error("Cannot remove all symbols - at least one must remain")
        return False
    
    return set_active_symbols(updated, redis_client, reason=f"remove:{','.join(to_actually_remove)}")


def reload_from_config(redis_client=None) -> bool:
    """Reset symbols to config.py defaults."""
    config_symbols = get_config_symbols()
    if not config_symbols:
        logger.error("No symbols in config.py")
        return False
    return set_active_symbols(config_symbols, redis_client, reason="reload_from_config")


def check_capacity(redis_client=None) -> Dict[str, Any]:
    """Check system capacity for symbols."""
    redis_client = redis_client or get_redis()
    
    current_symbols = len(get_active_symbols(redis_client))
    timeframes = len(DEFAULT_TIMEFRAMES)
    current_models = current_symbols * timeframes
    
    # Get GPU info
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True
        )
        gpu_total, gpu_used = map(float, result.stdout.strip().split(", "))
    except Exception:
        gpu_total, gpu_used = 16000, 14000  # Defaults
    
    # Estimate capacity
    gpu_per_model_mb = gpu_used / max(current_models, 1)
    max_gpu_models = int((gpu_total * 0.85) / max(gpu_per_model_mb, 100))  # 85% headroom
    max_symbols = max_gpu_models // timeframes
    
    return {
        "current_symbols": current_symbols,
        "current_models": current_models,
        "timeframes": timeframes,
        "gpu_total_mb": gpu_total,
        "gpu_used_mb": gpu_used,
        "gpu_per_model_mb": gpu_per_model_mb,
        "gpu_max_models": max_gpu_models,
        "gpu_max_symbols": max_symbols,
        "can_add": max(0, max_symbols - current_symbols),
        "at_capacity": current_symbols >= max_symbols,
    }


def list_symbols(redis_client=None) -> None:
    """Print current symbol status."""
    redis_client = redis_client or get_redis()
    
    symbols = get_active_symbols(redis_client)
    capacity = check_capacity(redis_client)
    
    print("\n" + "="*60)
    print("ACTIVE SYMBOLS")
    print("="*60)
    
    for i, s in enumerate(symbols, 1):
        print(f"  {i:2d}. {s}")
    
    print(f"\nTotal: {len(symbols)} symbols × {capacity['timeframes']} timeframes = {len(symbols) * capacity['timeframes']} models")
    print(f"GPU: {capacity['gpu_used_mb']:.0f} / {capacity['gpu_total_mb']:.0f} MB ({capacity['gpu_used_mb']/capacity['gpu_total_mb']*100:.1f}%)")
    print(f"Capacity: Can add {capacity['can_add']} more symbols")
    
    if capacity['at_capacity']:
        print("⚠️  AT CAPACITY - Remove symbols before adding more")
    
    print("="*60 + "\n")


def get_last_update(redis_client=None) -> Optional[Dict]:
    """Get information about the last symbol update."""
    redis_client = redis_client or get_redis()
    
    try:
        raw = redis_client.get(SYMBOLS_LAST_UPDATE_KEY)
        if raw:
            return json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode())
    except Exception:
        pass
    return None


# ============================================================================
# SERVICE INTEGRATION: Call these from trainer/traders to get dynamic symbols
# ============================================================================

_cached_symbols: Optional[List[str]] = None
_cached_symbols_ts: float = 0.0
_CACHE_TTL_SECONDS = 30.0


def get_symbols_cached(redis_client=None, force_refresh: bool = False) -> List[str]:
    """
    Get active symbols with caching for performance.
    Services should call this in their main loops.
    """
    global _cached_symbols, _cached_symbols_ts
    
    now = time.time()
    if not force_refresh and _cached_symbols and (now - _cached_symbols_ts) < _CACHE_TTL_SECONDS:
        return _cached_symbols
    
    _cached_symbols = get_active_symbols(redis_client)
    _cached_symbols_ts = now
    return _cached_symbols


def subscribe_to_symbol_updates(callback, redis_client=None):
    """
    Subscribe to symbol update notifications.
    
    Usage in service:
        def on_symbols_updated(symbols):
            logger.info(f"Symbols updated: {symbols}")
            # Reinitialize models/positions for new symbols
        
        # In a background thread:
        subscribe_to_symbol_updates(on_symbols_updated)
    """
    redis_client = redis_client or get_redis()
    pubsub = redis_client.pubsub()
    pubsub.subscribe("config:symbols:updated")
    
    logger.info("Subscribed to symbol updates")
    
    for message in pubsub.listen():
        if message["type"] == "message":
            try:
                data = json.loads(message["data"])
                symbols = data.get("symbols", [])
                callback(symbols)
            except Exception as e:
                logger.error(f"Error processing symbol update: {e}")


# ============================================================================
# SYMBOL NORMALIZATION & VALIDATION
# ============================================================================

def normalize_symbol(symbol: str) -> str:
    """
    Normalize any symbol format to canonical Binance format (BTCUSDT).
    
    Handles:
    - BTC/USDT (CCXT) -> BTCUSDT
    - BTC-USDT (KuCoin) -> BTCUSDT
    - btcusdt (lowercase) -> BTCUSDT
    - BINANCEFTS_PERP_BTC_USDT (CoinAPI) -> BTCUSDT
    - BTC/USDT:USDT (CCXT Futures) -> BTCUSDT
    - 1000PEPEUSDT (keeps as-is)
    """
    if not symbol:
        return ""
    
    symbol = str(symbol).strip().upper()
    
    # Futures format: BTC/USDT:USDT - handle FIRST before separator check
    if ':' in symbol:
        symbol = symbol.split(':')[0]
        # Continue processing the left part (don't return yet)
    
    # Already canonical format
    if symbol.endswith('USDT') and '/' not in symbol and '-' not in symbol and '_PERP_' not in symbol:
        return symbol
    
    # CoinAPI format: BINANCEFTS_PERP_BTC_USDT or BINANCE_SPOT_BTC_USDT
    if '_PERP_' in symbol or '_SPOT_' in symbol:
        parts = symbol.split('_')
        if len(parts) >= 4:
            base = parts[-2]
            quote = parts[-1]
            return f"{base}{quote}"
    
    # Remove common separators (CCXT: BTC/USDT, KuCoin: BTC-USDT)
    for sep in ['/', '-']:
        if sep in symbol:
            parts = symbol.split(sep)
            if len(parts) == 2:
                return f"{parts[0]}{parts[1]}"
    
    return symbol


def validate_symbol(symbol: str) -> Dict[str, Any]:
    """
    Validate a symbol and return details.
    
    Returns:
        {
            "valid": bool,
            "normalized": str,
            "original": str,
            "reason": str,
            "is_active": bool,
        }
    """
    redis_client = get_redis()
    
    result = {
        "valid": False,
        "normalized": "",
        "original": symbol,
        "reason": "",
        "is_active": False,
    }
    
    if not symbol:
        result["reason"] = "Empty symbol"
        return result
    
    normalized = normalize_symbol(symbol)
    result["normalized"] = normalized
    
    # Basic format check
    if not normalized:
        result["reason"] = "Could not normalize symbol"
        return result
    
    if not normalized.endswith('USDT'):
        result["reason"] = f"Symbol must end with USDT (got: {normalized})"
        return result
    
    if len(normalized) < 5:
        result["reason"] = f"Symbol too short (got: {normalized})"
        return result
    
    # Check if it's a valid Binance symbol (basic heuristic)
    base = normalized[:-4]  # Remove USDT
    if not base.replace('1000', '').isalpha():
        # Allow 1000PEPE, 1000SHIB etc but not other numeric prefixes
        if not (base.startswith('1000') and base[4:].isalpha()):
            result["reason"] = f"Invalid base currency: {base}"
            return result
    
    result["valid"] = True
    result["reason"] = "Valid symbol"
    
    # Check if active
    active = get_active_symbols(redis_client)
    result["is_active"] = normalized in active
    
    return result


def validate_and_fix_symbols(symbols: List[str]) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Validate and normalize a list of symbols.
    
    Returns:
        (valid_normalized_symbols, issues_list)
    """
    valid = []
    issues = []
    seen = set()
    
    for s in symbols:
        result = validate_symbol(s)
        
        if result["valid"]:
            normalized = result["normalized"]
            if normalized not in seen:
                valid.append(normalized)
                seen.add(normalized)
            else:
                issues.append({
                    "symbol": s,
                    "issue": "duplicate",
                    "normalized": normalized,
                })
        else:
            issues.append({
                "symbol": s,
                "issue": result["reason"],
                "normalized": result.get("normalized", ""),
            })
    
    return valid, issues


def sync_normalizer():
    """Sync the SymbolNormalizer with current active symbols."""
    try:
        from utils.data_normalizer import SymbolNormalizer
        SymbolNormalizer.refresh()
        logger.info("SymbolNormalizer synced with active symbols")
    except Exception as e:
        logger.warning(f"Could not sync SymbolNormalizer: {e}")


def convert_symbol(symbol: str, target_format: str) -> Optional[str]:
    """
    Convert a symbol to a specific format.
    
    Args:
        symbol: Symbol in any format
        target_format: One of "binance", "ccxt", "kucoin", "coinapi"
    
    Returns:
        Symbol in target format or None if invalid
    """
    normalized = normalize_symbol(symbol)
    if not normalized or not normalized.endswith('USDT'):
        return None
    
    base = normalized[:-4]  # Remove USDT
    
    if target_format == "binance":
        return normalized
    elif target_format == "ccxt":
        return f"{base}/USDT"
    elif target_format == "kucoin":
        return f"{base}-USDT"
    elif target_format == "coinapi":
        return f"BINANCEFTS_PERP_{base}_USDT"
    elif target_format == "futures":
        return f"{base}/USDT:USDT"
    else:
        return normalized


def get_symbol_formats(symbol: str) -> Dict[str, str]:
    """
    Get a symbol in all supported formats.
    
    Returns:
        {
            "binance": "BTCUSDT",
            "ccxt": "BTC/USDT",
            "kucoin": "BTC-USDT",
            "coinapi": "BINANCEFTS_PERP_BTC_USDT",
            "futures": "BTC/USDT:USDT",
        }
    """
    normalized = normalize_symbol(symbol)
    if not normalized:
        return {}
    
    return {
        "binance": convert_symbol(normalized, "binance"),
        "ccxt": convert_symbol(normalized, "ccxt"),
        "kucoin": convert_symbol(normalized, "kucoin"),
        "coinapi": convert_symbol(normalized, "coinapi"),
        "futures": convert_symbol(normalized, "futures"),
    }


# ============================================================================
# CLI
# ============================================================================

def main():
    """CLI entry point."""
    import argparse
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    
    parser = argparse.ArgumentParser(
        description="Unified Symbol Manager - Manage trading symbols without restarts"
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # List command
    subparsers.add_parser("list", help="List active symbols")
    
    # Add command
    add_parser = subparsers.add_parser("add", help="Add symbols")
    add_parser.add_argument("symbols", nargs="+", help="Symbols to add (e.g., PEPEUSDT WIFUSDT)")
    
    # Remove command
    remove_parser = subparsers.add_parser("remove", help="Remove symbols")
    remove_parser.add_argument("symbols", nargs="+", help="Symbols to remove")
    
    # Capacity command
    subparsers.add_parser("capacity", help="Check system capacity")
    
    # Reload command
    subparsers.add_parser("reload", help="Reload symbols from config.py")
    
    # Set command (replace all)
    set_parser = subparsers.add_parser("set", help="Set exact symbol list (replaces all)")
    set_parser.add_argument("symbols", nargs="+", help="Complete symbol list")
    
    args = parser.parse_args()
    
    redis_client = get_redis()
    
    if args.command == "list":
        list_symbols(redis_client)
        
    elif args.command == "add":
        if add_symbols(args.symbols, redis_client):
            print("✅ Symbols added successfully")
            list_symbols(redis_client)
        else:
            print("❌ Failed to add symbols")
            sys.exit(1)
            
    elif args.command == "remove":
        if remove_symbols(args.symbols, redis_client):
            print("✅ Symbols removed successfully")
            list_symbols(redis_client)
        else:
            print("❌ Failed to remove symbols")
            sys.exit(1)
            
    elif args.command == "capacity":
        capacity = check_capacity(redis_client)
        print("\n" + "="*60)
        print("SYSTEM CAPACITY")
        print("="*60)
        print(f"Current symbols: {capacity['current_symbols']}")
        print(f"Current models: {capacity['current_models']} ({capacity['current_symbols']} × {capacity['timeframes']} TFs)")
        print(f"")
        print(f"GPU Memory:")
        print(f"  Total: {capacity['gpu_total_mb']:.0f} MB")
        print(f"  Used: {capacity['gpu_used_mb']:.0f} MB ({capacity['gpu_used_mb']/capacity['gpu_total_mb']*100:.1f}%)")
        print(f"  Per model: ~{capacity['gpu_per_model_mb']:.0f} MB")
        print(f"")
        print(f"Maximum capacity:")
        print(f"  Max models: {capacity['gpu_max_models']}")
        print(f"  Max symbols: {capacity['gpu_max_symbols']}")
        print(f"  Can add: {capacity['can_add']} more symbols")
        print(f"")
        if capacity['at_capacity']:
            print("⚠️  AT CAPACITY - Remove symbols to add new ones")
        else:
            print(f"✅ Room for {capacity['can_add']} more symbols")
        print("="*60 + "\n")
        
    elif args.command == "reload":
        if reload_from_config(redis_client):
            print("✅ Symbols reloaded from config.py")
            list_symbols(redis_client)
        else:
            print("❌ Failed to reload symbols")
            sys.exit(1)
            
    elif args.command == "set":
        if set_active_symbols(args.symbols, redis_client, reason="cli_set"):
            print("✅ Symbols set successfully")
            list_symbols(redis_client)
        else:
            print("❌ Failed to set symbols")
            sys.exit(1)
            
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
