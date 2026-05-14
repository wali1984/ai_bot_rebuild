import logging
from utils.redis_client import get_redis

logger = logging.getLogger(__name__)

def create_hardened_redis_client():
    """
    Create a hardened Redis client with error handling
    """
    return get_redis()

def safe_redis_operation(redis_client, operation, *args, **kwargs):
    """
    Safely execute a Redis operation with error handling
    
    Args:
        redis_client: Redis client instance
        operation: Redis operation function (e.g., redis_client.set)
        *args, **kwargs: Arguments for the operation
        
    Returns:
        Result of the operation or None if failed
    """
    try:
        return operation(*args, **kwargs)
    except Exception as e:
        logger.warning(f"Redis operation failed: {e}")
        return None
