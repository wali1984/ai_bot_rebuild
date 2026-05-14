#!/usr/bin/env python3
"""
Automatic Service Monitor and Failover System
Monitors all critical services and automatically restarts failed processes

Monitors:
- 6 Ingestors (CCXT, Binance, CoinAnk, TokenMetrics, OrderBook, Indicators)
- 1 Trainer (hybrid_trainer.py)
- 2 Traders (trader.py, trader-asjad.py)
- 1 Feature Pipeline (feature_pipeline.py)

Features:
- Health checks every 60 seconds
- Exponential backoff for restart attempts
- Telegram alerts on failures
- Process resource monitoring
- Redis connectivity checks
- Automatic recovery from crashes
"""

import os
import sys
import time
import psutil
import subprocess
import redis
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('service_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('ServiceMonitor')

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
HEALTH_CHECK_INTERVAL = int(os.getenv("HEALTH_CHECK_INTERVAL", "60"))  # seconds
MAX_RESTART_ATTEMPTS = int(os.getenv("MAX_RESTART_ATTEMPTS", "5"))
RESTART_BACKOFF_BASE = int(os.getenv("RESTART_BACKOFF_BASE", "2"))  # exponential base
TELEGRAM_ENABLED = os.getenv("TELEGRAM_ALERTS_ENABLED", "false").lower() == "true"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Project root
PROJECT_ROOT = Path(__file__).parent.parent

# Service definitions
SERVICES = {
    'ingestor_ccxt': {
        'name': 'CCXT Ingestor',
        'command': ['python3', 'ingest/live_data_collector.py'],
        'check_pattern': 'live_data_collector.py',
        'priority': 'HIGH',
        'startup_delay': 0,
        'health_check': lambda r: len(r.keys('features:ccxt:*:latest')) > 0,
    },
    'ingestor_binance': {
        'name': 'Binance WebSocket',
        'command': ['python3', 'ingest/live_binance.py'],
        'check_pattern': 'live_binance.py',
        'priority': 'HIGH',
        'startup_delay': 2,
        'health_check': lambda r: r.exists('binance:websocket:status'),
    },
    'ingestor_coinank': {
        'name': 'CoinAnk Ingestor',
        'command': ['python3', 'ingest/live_coinank.py'],
        'check_pattern': 'live_coinank.py',
        'priority': 'HIGH',
        'startup_delay': 4,
        'health_check': lambda r: len(r.keys('features:coinank:*:latest')) > 0,
    },
    'ingestor_tokenmetrics': {
        'name': 'TokenMetrics Ingestor',
        'command': ['python3', 'ingest/live_tokenmetrics.py'],
        'check_pattern': 'live_tokenmetrics.py',
        'priority': 'HIGH',
        'startup_delay': 6,
        'health_check': lambda r: len(r.keys('features:tokenmetrics:*:latest')) > 0,
    },
    'ingestor_orderbook': {
        'name': 'OrderBook Ingestor',
        'command': ['python3', 'ingest/live_orderbook.py'],
        'check_pattern': 'live_orderbook.py',
        'priority': 'MEDIUM',
        'startup_delay': 8,
        'health_check': lambda r: len(r.keys('orderbook:*')) > 0,
    },
    'ingestor_indicators': {
        'name': 'Indicators Ingestor',
        'command': ['python3', 'ingest/live_indicators.py'],
        'check_pattern': 'live_indicators.py',
        'priority': 'MEDIUM',
        'startup_delay': 10,
        'health_check': lambda r: len(r.keys('indicators:*')) > 0,
    },
    'feature_pipeline': {
        'name': 'Feature Pipeline',
        'command': ['python3', 'feature_pipeline.py'],
        'check_pattern': 'python3 feature_pipeline.py',  # More specific pattern to avoid false negatives
        'priority': 'HIGH',
        'startup_delay': 12,
        'health_check': lambda r: r.exists('pipeline:last_update'),
    },
    'signal_router': {
        'name': 'Signal Router',
        'command': ['python3', 'trading/signal_router.py'],
        'check_pattern': 'python3 trading/signal_router.py',  # Fixed: signal_router is in trading/ not services/
        'priority': 'CRITICAL',
        'startup_delay': 10,
        'health_check': lambda r: len(r.keys('indicators:*')) > 0,
    },
        'trainer': {
        'name': 'Hybrid Trainer',
        'command': ['python3', 'rl/hybrid_trainer.py', '--mode', 'hybrid', '--training-mode', 'live'],
        'check_pattern': 'python3 rl/hybrid_trainer.py',  # More specific pattern
        'priority': 'CRITICAL',
        'startup_delay': 15,
        'health_check': lambda r: r.exists('wma:trainer:predictions'),
    },
    'trader': {
        'name': 'Trader (primary)',
        'command': ['python3', 'trading/trader.py'],
        'check_pattern': 'python3 trading/trader.py',  # More specific pattern
        'priority': 'CRITICAL',
        'startup_delay': 20,
        'health_check': lambda r: r.exists('wma:trader:status'),
    },
    'trader_asjad': {
        'name': 'Trader (asjad)',
        'command': ['python3', 'trading/trader-asjad.py'],
        'check_pattern': 'python3 trading/trader-asjad.py',
        'priority': 'CRITICAL',
        'startup_delay': 22,
        'health_check': lambda r: r.exists('wma:trader:status'),
    },
}


class ServiceMonitor:
    def __init__(self):
        self.redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        self.restart_attempts: Dict[str, int] = {svc: 0 for svc in SERVICES}
        self.last_restart_time: Dict[str, Optional[datetime]] = {svc: None for svc in SERVICES}
        self.service_pids: Dict[str, Optional[int]] = {svc: None for svc in SERVICES}
        self.health_history: Dict[str, List[bool]] = {svc: [] for svc in SERVICES}
        
        logger.info("🚀 Service Monitor initialized")
        logger.info(f"   Monitoring {len(SERVICES)} services")
        logger.info(f"   Health check interval: {HEALTH_CHECK_INTERVAL}s")
        logger.info(f"   Telegram alerts: {'✅ Enabled' if TELEGRAM_ENABLED else '❌ Disabled'}")
    
    def send_telegram_alert(self, message: str):
        """Send alert via Telegram"""
        if not TELEGRAM_ENABLED or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return
        
        try:
            import requests
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML"
            }
            requests.post(url, data=data, timeout=5)
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")
    
    def is_process_running(self, pattern: str) -> Optional[int]:
        """Check if process matching pattern is running, return PID if found"""
        try:
            result = subprocess.run(
                ['pgrep', '-f', pattern],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.stdout.strip():
                pids = [int(p) for p in result.stdout.strip().split('\n')]
                return pids[0] if pids else None
            return None
        except Exception as e:
            logger.error(f"Error checking process {pattern}: {e}")
            return None
    
    def get_process_info(self, pid: int) -> Optional[Dict]:
        """Get process resource usage"""
        try:
            proc = psutil.Process(pid)
            return {
                'cpu_percent': proc.cpu_percent(interval=0.1),
                'memory_mb': proc.memory_info().rss / 1024 / 1024,
                'num_threads': proc.num_threads(),
                'status': proc.status(),
                'create_time': datetime.fromtimestamp(proc.create_time()),
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None
    
    def check_redis_health(self) -> bool:
        """Check if Redis is accessible"""
        try:
            self.redis_client.ping()
            return True
        except Exception as e:
            logger.error(f"❌ Redis health check failed: {e}")
            return False
    
    def check_service_health(self, service_id: str, config: Dict) -> Tuple[bool, str]:
        """Check if service is healthy"""
        # 1. Check if process is running
        pid = self.is_process_running(config['check_pattern'])
        if pid is None:
            return False, "Process not running"
        
        # 2. Check if process is responsive (not zombie)
        proc_info = self.get_process_info(pid)
        if proc_info is None:
            return False, "Process not accessible"
        
        if proc_info['status'] == 'zombie':
            return False, "Process is zombie"
        
        # 3. Check Redis health (if configured)
        if 'health_check' in config:
            try:
                if not config['health_check'](self.redis_client):
                    return False, "Health check failed (no data in Redis)"
            except Exception as e:
                return False, f"Health check exception: {e}"
        
        # 4. Check if process has been running for at least 30 seconds
        uptime = datetime.now() - proc_info['create_time']
        if uptime.total_seconds() < 30:
            return True, f"Starting up ({uptime.total_seconds():.0f}s)"
        
        return True, "Healthy"
    
    def calculate_backoff_delay(self, service_id: str) -> int:
        """Calculate exponential backoff delay"""
        attempts = self.restart_attempts[service_id]
        if attempts == 0:
            return 0
        
        # Exponential backoff: 2^attempts seconds, capped at 300s (5 minutes)
        delay = min(RESTART_BACKOFF_BASE ** attempts, 300)
        return delay
    
    def should_restart(self, service_id: str) -> bool:
        """Check if service should be restarted based on backoff and attempt limits"""
        attempts = self.restart_attempts[service_id]
        
        # Check if we've exceeded max attempts
        if attempts >= MAX_RESTART_ATTEMPTS:
            logger.error(f"⛔ {service_id} exceeded max restart attempts ({MAX_RESTART_ATTEMPTS})")
            return False
        
        # Check if we're in backoff period
        last_restart = self.last_restart_time[service_id]
        if last_restart:
            backoff_delay = self.calculate_backoff_delay(service_id)
            time_since_restart = datetime.now() - last_restart
            if time_since_restart.total_seconds() < backoff_delay:
                remaining = backoff_delay - time_since_restart.total_seconds()
                logger.info(f"⏳ {service_id} in backoff period ({remaining:.0f}s remaining)")
                return False
        
        return True
    
    def restart_service(self, service_id: str, config: Dict) -> bool:
        """Restart a failed service"""
        if not self.should_restart(service_id):
            return False
        
        logger.warning(f"🔄 Restarting {config['name']}...")
        
        try:
            # Kill existing process if it exists
            pid = self.is_process_running(config['check_pattern'])
            if pid:
                try:
                    proc = psutil.Process(pid)
                    proc.terminate()
                    proc.wait(timeout=5)
                except (psutil.NoSuchProcess, psutil.TimeoutExpired):
                    # Force kill if graceful termination fails
                    try:
                        proc.kill()
                    except:
                        pass
            
            # Wait for startup delay
            time.sleep(config.get('startup_delay', 0))
            
            # Start service
            log_file = PROJECT_ROOT / 'backend.log'
            with open(log_file, 'a') as f:
                process = subprocess.Popen(
                    config['command'],
                    cwd=str(PROJECT_ROOT),
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    start_new_session=True
                )
            
            # Update restart tracking
            self.restart_attempts[service_id] += 1
            self.last_restart_time[service_id] = datetime.now()
            
            # Wait a moment for process to start
            time.sleep(2)
            
            # Verify it started
            new_pid = self.is_process_running(config['check_pattern'])
            if new_pid:
                logger.info(f"✅ {config['name']} restarted successfully (PID: {new_pid})")
                
                # Send Telegram alert
                attempts = self.restart_attempts[service_id]
                self.send_telegram_alert(
                    f"🔄 <b>{config['name']}</b> restarted\n"
                    f"Attempt: {attempts}/{MAX_RESTART_ATTEMPTS}\n"
                    f"PID: {new_pid}\n"
                    f"Priority: {config['priority']}"
                )
                return True
            else:
                logger.error(f"❌ {config['name']} failed to start")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error restarting {config['name']}: {e}")
            return False
    
    def reset_restart_counter(self, service_id: str):
        """Reset restart counter when service is healthy for extended period"""
        # If service has been healthy for 5 consecutive checks, reset counter
        if len(self.health_history[service_id]) >= 5:
            if all(self.health_history[service_id][-5:]):
                if self.restart_attempts[service_id] > 0:
                    logger.info(f"✅ {service_id} stable, resetting restart counter")
                    self.restart_attempts[service_id] = 0
    
    def monitor_loop(self):
        """Main monitoring loop"""
        logger.info("🔍 Starting monitoring loop...")
        
        check_count = 0
        
        while True:
            try:
                check_count += 1
                logger.info(f"\n{'='*80}")
                logger.info(f"🔍 Health Check #{check_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                logger.info(f"{'='*80}")
                
                # Check Redis first
                redis_healthy = self.check_redis_health()
                if not redis_healthy:
                    logger.error("❌ Redis is down! Cannot perform health checks")
                    self.send_telegram_alert("❌ <b>Redis is down!</b>\nService monitoring paused")
                    time.sleep(HEALTH_CHECK_INTERVAL)
                    continue
                
                # Check all services
                status_summary = []
                unhealthy_count = 0
                
                for service_id, config in SERVICES.items():
                    healthy, reason = self.check_service_health(service_id, config)
                    
                    # Update health history
                    self.health_history[service_id].append(healthy)
                    if len(self.health_history[service_id]) > 10:
                        self.health_history[service_id].pop(0)
                    
                    # Get PID
                    pid = self.is_process_running(config['check_pattern'])
                    
                    # Log status
                    status_icon = "✅" if healthy else "❌"
                    priority_icon = {
                        'CRITICAL': '🔴',
                        'HIGH': '🟡',
                        'MEDIUM': '🟢'
                    }.get(config['priority'], '⚪')
                    
                    attempts = self.restart_attempts[service_id]
                    attempt_str = f" (attempts: {attempts}/{MAX_RESTART_ATTEMPTS})" if attempts > 0 else ""
                    
                    logger.info(f"{status_icon} {priority_icon} {config['name']:25} PID:{pid or 'N/A':>7} {reason:30}{attempt_str}")
                    
                    if not healthy:
                        unhealthy_count += 1
                        
                        # Attempt restart
                        if config['priority'] in ['CRITICAL', 'HIGH']:
                            logger.warning(f"⚠️  {config['name']} is unhealthy: {reason}")
                            self.restart_service(service_id, config)
                        else:
                            logger.info(f"ℹ️  {config['name']} is unhealthy but low priority")
                    
                    else:
                        # Reset restart counter if healthy
                        self.reset_restart_counter(service_id)
                    
                    status_summary.append({
                        'service': config['name'],
                        'healthy': healthy,
                        'pid': pid,
                        'reason': reason,
                        'priority': config['priority']
                    })
                
                # Summary
                healthy_count = len(SERVICES) - unhealthy_count
                logger.info(f"\n📊 Summary: {healthy_count}/{len(SERVICES)} services healthy")
                
                # Alert if critical services are down
                critical_down = [s for s in status_summary 
                                if not s['healthy'] and s['priority'] == 'CRITICAL']
                if critical_down:
                    services_list = ', '.join([s['service'] for s in critical_down])
                    self.send_telegram_alert(
                        f"🚨 <b>CRITICAL SERVICES DOWN</b>\n{services_list}"
                    )
                
                # Store monitoring status in Redis
                try:
                    self.redis_client.setex(
                        'service_monitor:status',
                        HEALTH_CHECK_INTERVAL * 2,
                        json.dumps({
                            'timestamp': datetime.now().isoformat(),
                            'healthy_count': healthy_count,
                            'total_count': len(SERVICES),
                            'services': status_summary
                        })
                    )
                except Exception as e:
                    logger.error(f"Failed to store status in Redis: {e}")
                
                # Wait for next check
                logger.info(f"\n⏰ Next check in {HEALTH_CHECK_INTERVAL}s...")
                time.sleep(HEALTH_CHECK_INTERVAL)
                
            except KeyboardInterrupt:
                logger.info("\n🛑 Monitoring stopped by user")
                break
            except Exception as e:
                logger.error(f"❌ Error in monitoring loop: {e}", exc_info=True)
                time.sleep(10)  # Brief pause before retrying


def main():
    logger.info("="*80)
    logger.info("🚀 SERVICE MONITOR & AUTOMATIC FAILOVER SYSTEM")
    logger.info("="*80)
    
    monitor = ServiceMonitor()
    
    try:
        monitor.monitor_loop()
    except KeyboardInterrupt:
        logger.info("\n👋 Shutting down service monitor...")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
