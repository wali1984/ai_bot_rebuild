"""
Data Archiver Service
Periodically archives critical Redis data to SATA HDD for persistence and recovery

Archives hourly:
- Coinank data (funding, OI, liquidations)
- TokenMetrics data (grades, signals, predictions)
- OHLCV data (all sources)
- Unified features (aggregated trading features)

Storage: /mnt/sata/aibot_data/{category}/{date}/{hour}00.jsonl.gz
Compression: gzip for space efficiency
Retention: Configurable (default 1 year)
Auto-creates directory with sudo if needed
"""

import os
import sys
import json
import gzip
import time
import redis
import signal
import traceback
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config import REDIS_URL, TIMEFRAMES

# Dynamic symbol loading - supports hot-reload without restart
try:
    from utils.symbol_manager import get_symbols_cached
    SYMBOLS = get_symbols_cached()
except ImportError:
    from config import SYMBOLS
from utils.logger import get_logger

logger = get_logger("data_archiver")


class DataArchiver:
    """
    Archives Redis data to persistent storage on SATA HDD
    """
    
    def __init__(self, 
                 base_path: str = "/mnt/sata/aibot_data",
                 archive_interval: int = 3600,  # 1 hour
                 retention_days: int = 365):
        """
        Initialize data archiver
        
        Args:
            base_path: Base directory for archives (default: /mnt/sata/aibot_data)
            archive_interval: Seconds between archives (default 3600 = 1 hour)
            retention_days: Days to keep archives (default 365)
        """
        self.base_path = Path(base_path)
        self.archive_interval = archive_interval
        self.retention_days = retention_days
        
        # Redis connection
        self.redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        
        # Categories to archive with their Redis key patterns
        self.archive_categories = {
            'coinank': [
                'coinank:*',
                'funding:*',
                'oi:*',
                'liquidations:*',
                'long_short_ratio:*'
            ],
            'tokenmetrics': [
                'tokenmetrics:*',
                'features:tokenmetrics:*',
                'features:global_tm:*',
                'tm:archive:*'
            ],
            'ohlcv': [
                'ccxt:latest:*',
                'latest:binance:ohlcv:*',
                'latest:kucoin:ohlcv:*',
                'historical:ohlcv:*',
                'chart:ccxt:*'
            ],
            'unified_features': [
                'unified_features:*'
            ],
            'orders': [
                'order:*',
                'position:*',
                'trade:*'
            ]
        }
        
        # Running state
        self.running = False
        self.last_archive_time = 0
        self.archive_stats = {
            'total_archives': 0,
            'total_keys_archived': 0,
            'total_bytes_written': 0,
            'last_archive_duration': 0
        }
        
        # Create base directory with elevated permissions if needed
        try:
            self.base_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"✅ Data archiver initialized: {self.base_path}")
        except PermissionError:
            # Try with sudo if permission denied
            logger.warning(f"⚠️ Permission denied for {self.base_path}, attempting with elevated privileges...")
            try:
                import subprocess
                subprocess.run(['sudo', 'mkdir', '-p', str(self.base_path)], check=True)
                # Set ownership to current user
                import pwd
                username = pwd.getpwuid(os.getuid()).pw_name
                subprocess.run(['sudo', 'chown', '-R', f'{username}:{username}', str(self.base_path)], check=True)
                logger.info(f"✅ Created directory with elevated privileges: {self.base_path}")
            except Exception as e:
                logger.error(f"❌ Failed to create directory even with sudo: {e}")
                raise
        
        logger.info(f"📊 Archive interval: {self.archive_interval}s ({self.archive_interval/3600:.1f}h)")
        logger.info(f"📅 Retention: {self.retention_days} days")
    
    def _get_archive_path(self, category: str, timestamp: Optional[float] = None) -> Path:
        """
        Get archive file path for a category and timestamp
        
        Args:
            category: Data category (coinank, tokenmetrics, etc.)
            timestamp: Unix timestamp (defaults to now)
        
        Returns:
            Path to archive file: /mnt/sata/aibot_data/{category}/{YYYY-MM-DD}/{HH}00.jsonl.gz
        """
        if timestamp is None:
            timestamp = time.time()
        
        dt = datetime.fromtimestamp(timestamp)
        date_str = dt.strftime("%Y-%m-%d")
        hour_str = dt.strftime("%H")
        
        archive_dir = self.base_path / category / date_str
        archive_dir.mkdir(parents=True, exist_ok=True)
        
        return archive_dir / f"{hour_str}00.jsonl.gz"
    
    def _archive_category(self, category: str, patterns: List[str]) -> Dict[str, Any]:
        """
        Archive all keys matching patterns for a category
        
        Args:
            category: Category name
            patterns: List of Redis key patterns
        
        Returns:
            Dict with archive statistics
        """
        start_time = time.time()
        archived_keys = 0
        bytes_written = 0
        
        try:
            # Get archive file path
            archive_path = self._get_archive_path(category)
            
            # Collect all keys for this category
            all_keys = set()
            for pattern in patterns:
                try:
                    # Use SCAN to avoid blocking Redis
                    cursor = 0
                    while True:
                        cursor, keys = self.redis.scan(cursor, match=pattern, count=1000)
                        all_keys.update(keys)
                        if cursor == 0:
                            break
                except Exception as e:
                    logger.warning(f"Error scanning pattern {pattern}: {e}")
                    continue
            
            if not all_keys:
                logger.debug(f"No keys found for category: {category}")
                return {
                    'category': category,
                    'keys_archived': 0,
                    'bytes_written': 0,
                    'duration': time.time() - start_time
                }
            
            # Archive all keys to gzip file
            with gzip.open(archive_path, 'wt', encoding='utf-8') as f:
                for key in all_keys:
                    try:
                        # Get key type and value
                        key_type = self.redis.type(key)
                        
                        if key_type == 'string':
                            value = self.redis.get(key)
                        elif key_type == 'hash':
                            value = self.redis.hgetall(key)
                        elif key_type == 'list':
                            value = self.redis.lrange(key, 0, -1)
                        elif key_type == 'set':
                            value = list(self.redis.smembers(key))
                        elif key_type == 'zset':
                            value = self.redis.zrange(key, 0, -1, withscores=True)
                        else:
                            logger.debug(f"Skipping unsupported key type {key_type}: {key}")
                            continue
                        
                        # Write as JSON line
                        record = {
                            'timestamp': time.time(),
                            'key': key,
                            'type': key_type,
                            'value': value,
                            'ttl': self.redis.ttl(key)
                        }
                        
                        line = json.dumps(record) + '\n'
                        f.write(line)
                        bytes_written += len(line.encode('utf-8'))
                        archived_keys += 1
                        
                    except Exception as e:
                        logger.warning(f"Error archiving key {key}: {e}")
                        continue
            
            duration = time.time() - start_time
            logger.info(
                f"✅ Archived {category}: {archived_keys} keys, "
                f"{bytes_written/1024/1024:.2f} MB, {duration:.1f}s → {archive_path}"
            )
            
            return {
                'category': category,
                'keys_archived': archived_keys,
                'bytes_written': bytes_written,
                'duration': duration,
                'path': str(archive_path)
            }
            
        except Exception as e:
            logger.error(f"Error archiving category {category}: {e}\n{traceback.format_exc()}")
            return {
                'category': category,
                'keys_archived': 0,
                'bytes_written': 0,
                'duration': time.time() - start_time,
                'error': str(e)
            }
    
    def _cleanup_old_archives(self):
        """
        Remove archives older than retention_days
        """
        try:
            cutoff_date = datetime.now() - timedelta(days=self.retention_days)
            deleted_count = 0
            deleted_bytes = 0
            
            for category_dir in self.base_path.iterdir():
                if not category_dir.is_dir():
                    continue
                
                for date_dir in category_dir.iterdir():
                    if not date_dir.is_dir():
                        continue
                    
                    # Parse date from directory name
                    try:
                        dir_date = datetime.strptime(date_dir.name, "%Y-%m-%d")
                        
                        if dir_date < cutoff_date:
                            # Delete entire date directory
                            for archive_file in date_dir.iterdir():
                                if archive_file.is_file():
                                    deleted_bytes += archive_file.stat().st_size
                                    archive_file.unlink()
                                    deleted_count += 1
                            
                            # Remove empty directory
                            date_dir.rmdir()
                            logger.info(f"Deleted old archives: {date_dir} ({deleted_count} files)")
                    
                    except ValueError:
                        logger.warning(f"Invalid date directory name: {date_dir.name}")
                        continue
            
            if deleted_count > 0:
                logger.info(
                    f"🗑️  Cleanup: Deleted {deleted_count} old archives, "
                    f"freed {deleted_bytes/1024/1024/1024:.2f} GB"
                )
        
        except Exception as e:
            logger.error(f"Error cleaning up old archives: {e}")
    
    def archive_now(self) -> Dict[str, Any]:
        """
        Perform archive operation now (manual trigger)
        
        Returns:
            Dict with archive statistics for all categories
        """
        logger.info("=" * 80)
        logger.info("📦 Starting data archive operation")
        logger.info("=" * 80)
        
        start_time = time.time()
        results = []
        
        # Archive each category
        for category, patterns in self.archive_categories.items():
            result = self._archive_category(category, patterns)
            results.append(result)
        
        # Update statistics
        total_keys = sum(r['keys_archived'] for r in results)
        total_bytes = sum(r['bytes_written'] for r in results)
        duration = time.time() - start_time
        
        self.archive_stats['total_archives'] += 1
        self.archive_stats['total_keys_archived'] += total_keys
        self.archive_stats['total_bytes_written'] += total_bytes
        self.archive_stats['last_archive_duration'] = duration
        self.last_archive_time = time.time()
        
        # Cleanup old archives
        self._cleanup_old_archives()
        
        logger.info("=" * 80)
        logger.info(
            f"✅ Archive complete: {total_keys} keys, "
            f"{total_bytes/1024/1024:.2f} MB in {duration:.1f}s"
        )
        logger.info("=" * 80)
        
        return {
            'timestamp': time.time(),
            'duration': duration,
            'total_keys': total_keys,
            'total_bytes': total_bytes,
            'categories': results
        }
    
    def run(self):
        """
        Main archive loop - archives data at regular intervals
        """
        logger.info("🚀 Data archiver started")
        logger.info(f"Archive interval: {self.archive_interval}s ({self.archive_interval/3600:.1f}h)")
        
        self.running = True
        
        # Perform initial archive
        try:
            self.archive_now()
        except Exception as e:
            logger.error(f"Error in initial archive: {e}")
        
        while self.running:
            try:
                # Calculate time until next archive
                time_since_last = time.time() - self.last_archive_time
                time_until_next = max(0, self.archive_interval - time_since_last)
                
                if time_until_next > 0:
                    logger.debug(f"Next archive in {time_until_next/60:.1f} minutes")
                    time.sleep(min(60, time_until_next))  # Check every minute
                    continue
                
                # Time for next archive
                self.archive_now()
                
            except KeyboardInterrupt:
                logger.info("Received interrupt signal, shutting down...")
                break
            except Exception as e:
                logger.error(f"Error in archive loop: {e}\n{traceback.format_exc()}")
                time.sleep(60)  # Wait before retrying
        
        logger.info("Data archiver stopped")
    
    def stop(self):
        """Stop the archiver"""
        self.running = False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get archiver statistics"""
        return {
            **self.archive_stats,
            'running': self.running,
            'base_path': str(self.base_path),
            'retention_days': self.retention_days,
            'archive_interval': self.archive_interval
        }


def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"Received signal {signum}, shutting down...")
    if hasattr(signal_handler, 'archiver'):
        signal_handler.archiver.stop()
    sys.exit(0)


def main():
    """Main entry point"""
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Create and run archiver
    archiver = DataArchiver(
        base_path="/mnt/sata/aibot_data",
        archive_interval=3600,  # 1 hour
        retention_days=365
    )
    
    # Store reference for signal handler
    signal_handler.archiver = archiver
    
    # Run archiver
    archiver.run()


if __name__ == "__main__":
    main()
