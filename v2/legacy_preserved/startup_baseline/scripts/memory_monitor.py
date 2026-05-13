#!/usr/bin/env python3
"""
Memory Monitor for WMA AI Trading Bot
Tracks memory usage of all Python processes and logs alerts when thresholds exceeded.
Runs as a background daemon to help identify memory leaks.
"""

import os
import sys
import time
import psutil
import logging
from datetime import datetime
from pathlib import Path
from collections import defaultdict

# Configuration
MONITOR_INTERVAL = 30  # seconds between checks
MEMORY_WARN_THRESHOLD_GB = 10  # Warn when any process exceeds this
MEMORY_CRITICAL_THRESHOLD_GB = 30  # Critical alert
TOTAL_MEMORY_WARN_PCT = 70  # Warn when total usage exceeds this %
TOTAL_MEMORY_CRITICAL_PCT = 85  # Critical when exceeds this %
LOG_TOP_N_PROCESSES = 10  # Log top N memory consumers
HISTORY_RETENTION = 100  # Keep last N snapshots for trend analysis

# Setup logging
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "memory_monitor.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("memory_monitor")

# Track memory history per process
memory_history = defaultdict(list)
total_memory_history = []


def get_bot_python_processes():
    """Get all Python processes related to the trading bot"""
    bot_processes = []
    bot_dir = str(Path(__file__).parent.parent.resolve())
    
    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'memory_info', 'cpu_percent', 'create_time']):
        try:
            info = proc.info
            if info['name'] and 'python' in info['name'].lower():
                cmdline = info.get('cmdline', []) or []
                cmdline_str = ' '.join(cmdline)
                
                # Check if it's a bot-related process
                is_bot_process = any([
                    bot_dir in cmdline_str,
                    'live_binance' in cmdline_str,
                    'live_coinank' in cmdline_str,
                    'hybrid_trainer' in cmdline_str,
                    'trader' in cmdline_str,
                    'feature_pipeline' in cmdline_str,
                    'signal_router' in cmdline_str,
                    'monitor_portfolio' in cmdline_str,
                    'memory_monitor' in cmdline_str,
                ])
                
                if is_bot_process:
                    mem_info = info.get('memory_info')
                    if mem_info:
                        # Extract script name from cmdline
                        script_name = "unknown"
                        for arg in cmdline:
                            if arg.endswith('.py'):
                                script_name = Path(arg).name
                                break
                            elif '.py' in arg:
                                # Handle module style: -m rl.hybrid_trainer
                                script_name = arg.split('.')[-1] + '.py'
                        
                        bot_processes.append({
                            'pid': info['pid'],
                            'script': script_name,
                            'cmdline': cmdline_str[:100],  # Truncate for logging
                            'rss_mb': mem_info.rss / (1024 * 1024),
                            'rss_gb': mem_info.rss / (1024 * 1024 * 1024),
                            'vms_gb': mem_info.vms / (1024 * 1024 * 1024),
                            'cpu_pct': info.get('cpu_percent', 0),
                            'uptime_hours': (time.time() - info.get('create_time', time.time())) / 3600,
                        })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    
    return bot_processes


def get_system_memory():
    """Get overall system memory stats"""
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        'total_gb': mem.total / (1024 ** 3),
        'available_gb': mem.available / (1024 ** 3),
        'used_gb': mem.used / (1024 ** 3),
        'percent': mem.percent,
        'swap_used_gb': swap.used / (1024 ** 3),
        'swap_percent': swap.percent,
    }


def analyze_memory_trend(pid, current_rss_mb):
    """Analyze if a process's memory is growing"""
    history = memory_history[pid]
    history.append((time.time(), current_rss_mb))
    
    # Keep only recent history
    if len(history) > HISTORY_RETENTION:
        history.pop(0)
    
    if len(history) < 5:
        return None, 0
    
    # Calculate growth rate (MB per hour)
    oldest_ts, oldest_mem = history[0]
    newest_ts, newest_mem = history[-1]
    hours_elapsed = (newest_ts - oldest_ts) / 3600
    
    if hours_elapsed > 0:
        growth_rate = (newest_mem - oldest_mem) / hours_elapsed
        trend = "GROWING" if growth_rate > 100 else "STABLE" if abs(growth_rate) < 50 else "SHRINKING"
        return trend, growth_rate
    
    return None, 0


def log_memory_snapshot():
    """Take and log a memory snapshot"""
    processes = get_bot_python_processes()
    sys_mem = get_system_memory()
    
    # Sort by memory usage
    processes.sort(key=lambda x: x['rss_mb'], reverse=True)
    
    # Calculate total bot memory
    total_bot_memory_gb = sum(p['rss_gb'] for p in processes)
    
    # Log system overview
    logger.info("=" * 80)
    logger.info(f"📊 MEMORY SNAPSHOT @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"🖥️  SYSTEM: {sys_mem['used_gb']:.1f}GB / {sys_mem['total_gb']:.1f}GB ({sys_mem['percent']:.1f}%) | Swap: {sys_mem['swap_used_gb']:.1f}GB ({sys_mem['swap_percent']:.1f}%)")
    logger.info(f"🤖 BOT TOTAL: {total_bot_memory_gb:.2f}GB across {len(processes)} processes")
    logger.info("-" * 80)
    
    # Check system-level alerts
    if sys_mem['percent'] >= TOTAL_MEMORY_CRITICAL_PCT:
        logger.critical(f"🚨 CRITICAL: System memory at {sys_mem['percent']:.1f}% - OOM IMMINENT!")
    elif sys_mem['percent'] >= TOTAL_MEMORY_WARN_PCT:
        logger.warning(f"⚠️  WARNING: System memory at {sys_mem['percent']:.1f}%")
    
    # Log top processes
    logger.info(f"{'PID':<8} {'Script':<30} {'RSS (GB)':<10} {'VMS (GB)':<10} {'CPU%':<8} {'Uptime(h)':<10} {'Trend':<12} {'Growth/h'}")
    logger.info("-" * 110)
    
    for i, proc in enumerate(processes[:LOG_TOP_N_PROCESSES]):
        trend, growth_rate = analyze_memory_trend(proc['pid'], proc['rss_mb'])
        trend_str = trend or "N/A"
        growth_str = f"{growth_rate:+.0f}MB" if trend else "N/A"
        
        # Check process-level alerts
        alert = ""
        if proc['rss_gb'] >= MEMORY_CRITICAL_THRESHOLD_GB:
            alert = "🚨 CRITICAL"
            logger.critical(f"🚨 CRITICAL: {proc['script']} (PID {proc['pid']}) using {proc['rss_gb']:.1f}GB RAM!")
        elif proc['rss_gb'] >= MEMORY_WARN_THRESHOLD_GB:
            alert = "⚠️  WARN"
            logger.warning(f"⚠️  WARNING: {proc['script']} (PID {proc['pid']}) using {proc['rss_gb']:.1f}GB RAM")
        elif trend == "GROWING" and growth_rate > 500:
            alert = "📈 LEAK?"
            logger.warning(f"📈 POTENTIAL LEAK: {proc['script']} growing at {growth_rate:.0f}MB/hour")
        
        logger.info(f"{proc['pid']:<8} {proc['script']:<30} {proc['rss_gb']:<10.2f} {proc['vms_gb']:<10.2f} {proc['cpu_pct']:<8.1f} {proc['uptime_hours']:<10.1f} {trend_str:<12} {growth_str} {alert}")
    
    # Track total memory trend
    total_memory_history.append((time.time(), total_bot_memory_gb))
    if len(total_memory_history) > HISTORY_RETENTION:
        total_memory_history.pop(0)
    
    if len(total_memory_history) >= 5:
        oldest = total_memory_history[0]
        newest = total_memory_history[-1]
        hours = (newest[0] - oldest[0]) / 3600
        if hours > 0:
            total_growth = (newest[1] - oldest[1]) / hours
            if total_growth > 2:  # Growing more than 2GB/hour
                logger.warning(f"📈 TOTAL BOT MEMORY GROWING: {total_growth:.1f}GB/hour")
    
    logger.info("=" * 80)
    return processes, sys_mem


def cleanup_dead_processes():
    """Remove history for dead processes"""
    alive_pids = {p.pid for p in psutil.process_iter(['pid'])}
    dead_pids = [pid for pid in memory_history.keys() if pid not in alive_pids]
    for pid in dead_pids:
        del memory_history[pid]


def main():
    logger.info("🚀 Memory Monitor Started")
    logger.info(f"📝 Logging to: {LOG_FILE}")
    logger.info(f"⏱️  Check interval: {MONITOR_INTERVAL}s")
    logger.info(f"⚠️  Warn threshold: {MEMORY_WARN_THRESHOLD_GB}GB per process, {TOTAL_MEMORY_WARN_PCT}% system")
    logger.info(f"🚨 Critical threshold: {MEMORY_CRITICAL_THRESHOLD_GB}GB per process, {TOTAL_MEMORY_CRITICAL_PCT}% system")
    
    iteration = 0
    while True:
        try:
            iteration += 1
            log_memory_snapshot()
            
            # Cleanup every 10 iterations
            if iteration % 10 == 0:
                cleanup_dead_processes()
            
        except Exception as e:
            logger.error(f"Error in monitoring loop: {e}")
        
        time.sleep(MONITOR_INTERVAL)


if __name__ == "__main__":
    main()
