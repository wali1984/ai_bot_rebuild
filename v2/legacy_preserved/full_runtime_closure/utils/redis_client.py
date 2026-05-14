import redis
import logging
import json
import os
from typing import Any, Dict, Optional, Union

from redis import BlockingConnectionPool

# Import centralized config
import sys
from pathlib import Path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import importlib.util
config_spec = importlib.util.spec_from_file_location("config_module", project_root / "config.py")
config_module = importlib.util.module_from_spec(config_spec)
config_spec.loader.exec_module(config_module)

from utils.redis_key_audit import wrap_redis_client

logger = logging.getLogger(__name__)

# Shared singleton pool/client (per-process)
_POOL = None
_CLIENT = None
_CLIENT_PID = None


def _get_or_init_client(live_config) -> redis.Redis:
    global _POOL, _CLIENT, _CLIENT_PID
    current_pid = os.getpid()
    if _CLIENT is not None and _CLIENT_PID == current_pid:
        return _CLIENT

    max_conns = 64
    try:
        max_conns = int(os.getenv("REDIS_MAX_CONNS", getattr(live_config, "REDIS_MAX_CONNECTIONS", 64)) or 64)
    except Exception:
        max_conns = 64

    try:
        timeout = float(os.getenv("REDIS_BLOCK_TIMEOUT_SEC", "5"))
    except Exception:
        timeout = 5.0

    _POOL = BlockingConnectionPool(
        host=live_config.REDIS_HOST,
        port=live_config.REDIS_PORT,
        db=live_config.REDIS_DB,
        password=live_config.REDIS_PASSWORD if live_config.REDIS_PASSWORD else None,
        max_connections=max_conns,
        timeout=timeout,
        socket_connect_timeout=1.0,
        socket_timeout=1.5,
        socket_keepalive=True,
        socket_keepalive_options={},
        retry_on_timeout=True,
        health_check_interval=30,
        decode_responses=True,
    )
    _CLIENT = wrap_redis_client(redis.Redis(connection_pool=_POOL))
    _CLIENT_PID = current_pid
    return _CLIENT


class RedisClient:
    """Redis client wrapper for the WMA AI Bot"""

    def __init__(self):
        self.redis_client = None
        self.connect()

    def connect(self):
        """Connect to Redis server with connection pooling and multiprocessing-optimized timeouts"""
        live_config = config_module.get_live_config()

        logger.info(f"🔧 [REDIS] Initializing connection pool for SubprocVecEnv (PID: {os.getpid()})")

        # Robust connect: SubprocVecEnv can spawn many workers that connect at once.
        # Add a small retry/backoff to avoid transient "broken pipe"/reset errors.
        last_exc: Optional[Exception] = None
        for attempt in range(1, 6):
            try:
                self.redis_client = _get_or_init_client(live_config)
                self.redis_client.ping()
                logger.info(
                    f"✅ Connected to Redis at {live_config.REDIS_HOST}:{live_config.REDIS_PORT} "
                    f"with connection pool (attempt {attempt}/5)"
                )
                return
            except Exception as e:
                last_exc = e
                logger.error(f"Failed to connect to Redis (attempt {attempt}/5): {e}")
                # Backoff: 0.2s, 0.4s, 0.8s, 1.6s, 3.2s
                try:
                    import time
                    time.sleep(0.2 * (2 ** (attempt - 1)))
                except Exception:
                    pass

        raise last_exc if last_exc else RuntimeError("Failed to connect to Redis")
    
    def set(self, key: str, value: Any, ex: Optional[int] = None, nx: bool = False) -> bool:
        """Set a key-value pair with optional expiration and conditional set
        
        Args:
            key: Redis key
            value: Value to set (will be JSON-encoded if dict/list)
            ex: Expiration in seconds
            nx: Only set if key doesn't exist (SET NX)
        """
        try:
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            return self.redis_client.set(key, value, ex=ex, nx=nx)
        except Exception as e:
            logger.error(f"Failed to set key {key}: {e}")
            return False
    
    def get(self, key: str) -> Optional[Any]:
        """Get value by key"""
        try:
            value = self.redis_client.get(key)
            if value is None:
                return None
            
            # Try to parse as JSON, fall back to string
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        except Exception as e:
            logger.error(f"Failed to get key {key}: {e}")
            return None
    
    def hset(self, name: str, mapping: Dict[str, Any]) -> int:
        """Set hash fields"""
        try:
            # Convert values to strings, handling JSON serialization
            string_mapping = {}
            for k, v in mapping.items():
                if isinstance(v, (dict, list)):
                    string_mapping[k] = json.dumps(v)
                else:
                    string_mapping[k] = str(v)
            return self.redis_client.hset(name, mapping=string_mapping)
        except Exception as e:
            logger.error(f"Failed to set hash {name}: {e}")
            return 0
    
    def hgetall(self, name: str) -> Dict[str, Any]:
        """Get all hash fields"""
        try:
            result = self.redis_client.hgetall(name)
            # Convert values back to appropriate types
            converted = {}
            for k, v in result.items():
                try:
                    # Try to parse as JSON first
                    converted[k] = json.loads(v)
                except json.JSONDecodeError:
                    # Try to parse as number
                    try:
                        if '.' in v:
                            converted[k] = float(v)
                        else:
                            converted[k] = int(v)
                    except ValueError:
                        # Keep as string
                        converted[k] = v
            return converted
        except Exception as e:
            logger.error(f"Failed to get hash {name}: {e}")
            return {}
    
    def hget(self, name: str, key: str) -> Optional[Any]:
        """Get single hash field"""
        try:
            value = self.redis_client.hget(name, key)
            if value is None:
                return None
            
            # Try to parse as JSON, then number, finally string
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                try:
                    if '.' in value:
                        return float(value)
                    else:
                        return int(value)
                except ValueError:
                    return value
        except Exception as e:
            logger.error(f"Failed to get hash field {name}:{key}: {e}")
            return None
    
    def lpush(self, name: str, *values) -> int:
        """Push values to the left of a list"""
        try:
            # Convert to JSON if needed
            json_values = []
            for v in values:
                if isinstance(v, (dict, list)):
                    json_values.append(json.dumps(v))
                else:
                    json_values.append(str(v))
            return self.redis_client.lpush(name, *json_values)
        except Exception as e:
            logger.error(f"Failed to push to list {name}: {e}")
            return 0
    
    def lrange(self, name: str, start: int, end: int) -> list:
        """Get range of list elements"""
        try:
            values = self.redis_client.lrange(name, start, end)
            result = []
            for v in values:
                try:
                    result.append(json.loads(v))
                except json.JSONDecodeError:
                    result.append(v)
            return result
        except Exception as e:
            logger.error(f"Failed to get list range {name}: {e}")
            return []
    
    def expire(self, name: str, time: int) -> bool:
        """Set expiration time for a key"""
        try:
            return self.redis_client.expire(name, time)
        except Exception as e:
            logger.error(f"Failed to set expiration for {name}: {e}")
            return False
    
    def delete(self, *names) -> int:
        """Delete keys"""
        try:
            return self.redis_client.delete(*names)
        except Exception as e:
            logger.error(f"Failed to delete keys: {e}")
            return 0
    
    def publish(self, channel: str, message: Any) -> int:
        """Publish message to a Redis pub/sub channel
        
        Args:
            channel: Channel name
            message: Message to publish (will be JSON-encoded if dict/list)
            
        Returns:
            Number of subscribers that received the message
        """
        try:
            if isinstance(message, (dict, list)):
                message = json.dumps(message)
            return self.redis_client.publish(channel, message)
        except Exception as e:
            logger.error(f"Failed to publish to channel {channel}: {e}")
            return 0
    
    def ltrim(self, name: str, start: int, end: int) -> bool:
        """Trim a list to the specified range
        
        Args:
            name: List key
            start: Start index (inclusive)
            end: End index (inclusive)
        """
        try:
            return self.redis_client.ltrim(name, start, end)
        except Exception as e:
            logger.error(f"Failed to trim list {name}: {e}")
            return False
    
    def ping(self) -> bool:
        """Test connection"""
        try:
            return self.redis_client.ping()
        except Exception as e:
            logger.error(f"Redis ping failed: {e}")
            return False

# Global Redis client instance (per-process singleton)
_redis_client = None
_redis_client_pid = None  # Track which process created the client

def get_redis_client() -> RedisClient:
    """Get or create Redis client instance (per-process singleton)
    
    CRITICAL: Each process must have its own Redis connection.
    SubprocVecEnv spawns new processes that reimport this module,
    and we create a NEW connection for each process (not shared/pickled).
    """
    global _redis_client, _redis_client_pid
    import os
    current_pid = os.getpid()
    
    # Create new client if none exists or if we're in a different process (fork/spawn safety)
    if _redis_client is None or _redis_client_pid != current_pid:
        if _redis_client_pid is not None and _redis_client_pid != current_pid:
            logger.info(f"🔧 [REDIS] Creating new connection for PID {current_pid} (parent was {_redis_client_pid})")
        _redis_client = RedisClient()
        _redis_client_pid = current_pid
    return _redis_client

def get_redis():
    """Get raw Redis connection for compatibility
    
    Creates per-process Redis client lazily (safe for SubprocVecEnv workers).
    """
    try:
        live_config = config_module.get_live_config()
    except Exception:
        live_config = None
    if live_config is None:
        client = get_redis_client()
        return client.redis_client if client is not None else None
    return _get_or_init_client(live_config)


def get_redis_config() -> dict:
    """Get Redis connection configuration (picklable, no live connections)
    
    Use this in environments that need to be pickled for SubprocVecEnv.
    The config can be pickled; the actual connection is created lazily per-process.
    """
    live_config = config_module.get_live_config()
    return {
        'host': live_config.REDIS_HOST,
        'port': live_config.REDIS_PORT,
        'db': live_config.REDIS_DB,
        'password': live_config.REDIS_PASSWORD if live_config.REDIS_PASSWORD else None,
        'decode_responses': True,
    }


def create_redis_from_config(config: dict):
    """Create a Redis client from config dict (for use in spawned workers)
    
    Args:
        config: Dict with host, port, db, password, decode_responses
    
    Returns:
        redis.Redis client
    """
    pool = BlockingConnectionPool(
        host=config['host'],
        port=config['port'],
        db=config['db'],
        password=config.get('password'),
        max_connections=int(os.getenv("REDIS_MAX_CONNS", "64")),
        timeout=float(os.getenv("REDIS_BLOCK_TIMEOUT_SEC", "5")),
        decode_responses=config.get('decode_responses', True),
    )
    return wrap_redis_client(redis.Redis(connection_pool=pool))
