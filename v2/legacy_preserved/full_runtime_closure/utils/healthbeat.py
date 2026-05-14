import time
import threading
from utils.redis_client import get_redis
from utils.logger import get_logger

logger = get_logger("healthbeat")

def start_heartbeat(redis_client_or_name, component_name_or_interval = "unknown", interval: int = 30):
    """
    Start a heartbeat thread for the component
    Support both old (redis_client, component_name) and new (component_name, interval) signatures
    """
    # Handle both calling conventions
    if isinstance(redis_client_or_name, str):
        # New convention: start_heartbeat(component_name, interval)
        component_name = redis_client_or_name
        if isinstance(component_name_or_interval, int):
            interval = component_name_or_interval
    else:
        # Old convention: start_heartbeat(redis_client, component_name)
        component_name = component_name_or_interval if isinstance(component_name_or_interval, str) else "unknown"
    
    def heartbeat_worker():
        redis_client = get_redis()
        while True:
            try:
                key = f"heartbeat:{component_name}"
                current_time = int(time.time())
                redis_client.set(key, str(current_time))
                # Use a reasonable expire time (max 1 hour)
                expire_time = min(interval * 3, 3600)
                redis_client.expire(key, expire_time)
                time.sleep(interval)
            except Exception as e:
                logger.error(f"Heartbeat error for {component_name}: {e}")
                time.sleep(5)  # Wait before retry
    
    thread = threading.Thread(target=heartbeat_worker, daemon=True)
    thread.start()
    logger.info(f"Started heartbeat for {component_name} with {interval}s interval")
    return thread

def report_exit(component_name: str, reason: str = "normal"):
    """
    Report component exit to Redis
    """
    try:
        redis_client = get_redis()
        key = f"exit:{component_name}"
        data = {
            'timestamp': str(int(time.time())),
            'reason': reason
        }
        redis_client.hset(key, mapping=data)
        redis_client.expire(key, 3600)  # Keep for 1 hour
        logger.info(f"Reported exit for {component_name}: {reason}")
    except Exception as e:
        logger.error(f"Failed to report exit for {component_name}: {e}")
