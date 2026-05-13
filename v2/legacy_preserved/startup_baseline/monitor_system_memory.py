#!/usr/bin/env python3
"""
Comprehensive System Memory and OOM Monitor

Tracks memory usage across all system processes with focus on:
- Python processes (trainer, ingestors, services)
- GPU memory (CUDA)
- System-wide memory pressure
- OOM killer events from system journal
- Real-time alerts and logging
"""

import psutil
import subprocess
import time
import logging
import os
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple
import signal
import sys

# Configure logging
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "memory_monitor.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("memory_monitor")

# Configuration
CHECK_INTERVAL = 10  # seconds between checks
WARNING_THRESHOLD = 75  # % RAM usage warning
CRITICAL_THRESHOLD = 85  # % RAM usage critical
EMERGENCY_THRESHOLD = 95  # % RAM usage emergency - log more aggressively
OOM_CHECK_INTERVAL = 30  # seconds between OOM journal checks

# Swap pressure thresholds (root cause of 2026-03-04 freeze: RAM was 57% OK but swap was 77%)
# The memory monitor only checked RAM %, completely missing the swap crisis.
SWAP_WARNING_THRESHOLD = 50   # % swap used → warn
SWAP_CRITICAL_THRESHOLD = 65  # % swap used → kill trainer (prevent freeze)
SWAP_KILL_COOLDOWN = 300       # seconds between successive trainer kills

# Trainer patterns used to locate the process for emergency kill
TRAINER_CMDLINE_PATTERNS = ["rl.hybrid_trainer", "hybrid_trainer"]

# Process name patterns to monitor
MONITORED_PROCESSES = [
    "hybrid_trainer.py",
    "live_binance",
    "live_coinank",
    "unified_trainer",
    "backend.py",
    "signal_publisher",
    "liquidation_intelligence"
]

class MemoryMonitor:
    def __init__(self):
        self.start_time = time.time()
        self.last_oom_check = 0
        self.last_critical_alert = 0
        self.alert_cooldown = 60  # seconds between repeated critical alerts
        self.metrics_history = []
        self.max_history = 360  # Keep 1 hour of data (at 10s intervals)
        
        # Track per-process peak memory
        self.process_peaks = {}

        # Track swap kill timing to avoid killing trainer in a tight loop
        self.last_swap_kill_time = 0
        
        logger.info("🚀 Memory Monitor started")
        logger.info(f"⚙️  Configuration:")
        logger.info(f"   Check interval: {CHECK_INTERVAL}s")
        logger.info(f"   Warning threshold: {WARNING_THRESHOLD}%")
        logger.info(f"   Critical threshold: {CRITICAL_THRESHOLD}%")
        logger.info(f"   Emergency threshold: {EMERGENCY_THRESHOLD}%")
    
    def get_gpu_memory(self) -> Tuple[float, float, float]:
        """Get GPU memory usage via nvidia-smi"""
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=memory.used,memory.total,memory.free', 
                 '--format=csv,noheader,nounits'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                used, total, free = map(int, result.stdout.strip().split(','))
                return used, total, free
        except Exception as e:
            logger.debug(f"GPU check failed: {e}")
        
        return 0, 0, 0
    
    def get_process_memory(self) -> List[Dict]:
        """Get memory usage for monitored processes"""
        processes = []
        
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'memory_info', 'cpu_percent']):
            try:
                info = proc.info
                cmdline = ' '.join(info['cmdline']) if info['cmdline'] else ''
                
                # Check if this is a monitored process
                is_monitored = any(pattern in cmdline for pattern in MONITORED_PROCESSES)
                
                if is_monitored:
                    mem_info = info['memory_info']
                    rss_mb = mem_info.rss / 1024 / 1024
                    vms_mb = mem_info.vms / 1024 / 1024
                    
                    # Track peak memory for this process
                    proc_key = f"{info['pid']}_{info['name']}"
                    if proc_key not in self.process_peaks or rss_mb > self.process_peaks[proc_key]:
                        self.process_peaks[proc_key] = rss_mb
                    
                    processes.append({
                        'pid': info['pid'],
                        'name': info['name'],
                        'cmdline': cmdline[:100],  # Truncate
                        'rss_mb': rss_mb,
                        'vms_mb': vms_mb,
                        'cpu_percent': info['cpu_percent'],
                        'peak_mb': self.process_peaks[proc_key]
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # Sort by memory usage
        processes.sort(key=lambda x: x['rss_mb'], reverse=True)
        return processes
    
    def check_oom_events(self) -> List[str]:
        """Check system journal for recent OOM killer events"""
        try:
            # Check last 60 seconds of journal for OOM events
            result = subprocess.run(
                ['journalctl', '--since', '60 seconds ago', '-k', '--no-pager'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                oom_lines = []
                for line in result.stdout.split('\n'):
                    if 'oom' in line.lower() or 'out of memory' in line.lower():
                        oom_lines.append(line)
                return oom_lines
        except Exception as e:
            logger.debug(f"OOM check failed: {e}")
        
        return []
    
    def get_system_metrics(self) -> Dict:
        """Get comprehensive system metrics"""
        # Memory
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        # CPU
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_count = psutil.cpu_count()
        
        # Disk
        disk = psutil.disk_usage('/')
        
        # GPU
        gpu_used, gpu_total, gpu_free = self.get_gpu_memory()
        
        # Load average
        load_avg = os.getloadavg()
        
        return {
            'timestamp': datetime.now().isoformat(),
            'uptime_seconds': time.time() - self.start_time,
            'memory': {
                'total_gb': mem.total / 1024 / 1024 / 1024,
                'available_gb': mem.available / 1024 / 1024 / 1024,
                'used_gb': mem.used / 1024 / 1024 / 1024,
                'percent': mem.percent,
                'free_gb': mem.free / 1024 / 1024 / 1024
            },
            'swap': {
                'total_gb': swap.total / 1024 / 1024 / 1024,
                'used_gb': swap.used / 1024 / 1024 / 1024,
                'percent': swap.percent
            },
            'cpu': {
                'percent': cpu_percent,
                'count': cpu_count,
                'load_avg_1m': load_avg[0],
                'load_avg_5m': load_avg[1],
                'load_avg_15m': load_avg[2]
            },
            'disk': {
                'total_gb': disk.total / 1024 / 1024 / 1024,
                'used_gb': disk.used / 1024 / 1024 / 1024,
                'free_gb': disk.free / 1024 / 1024 / 1024,
                'percent': disk.percent
            },
            'gpu': {
                'used_mb': gpu_used,
                'total_mb': gpu_total,
                'free_mb': gpu_free,
                'percent': (gpu_used / gpu_total * 100) if gpu_total > 0 else 0
            }
        }
    
    def log_metrics(self, metrics: Dict, processes: List[Dict]):
        """Log metrics with appropriate severity level"""
        mem_percent = metrics['memory']['percent']
        
        # Determine severity
        if mem_percent >= EMERGENCY_THRESHOLD:
            level = "🚨 EMERGENCY"
            log_func = logger.error
        elif mem_percent >= CRITICAL_THRESHOLD:
            level = "🔴 CRITICAL"
            log_func = logger.error
        elif mem_percent >= WARNING_THRESHOLD:
            level = "🟡 WARNING"
            log_func = logger.warning
        else:
            level = "🟢 OK"
            log_func = logger.info
        
        # System summary
        log_func(
            f"{level} | RAM: {mem_percent:.1f}% ({metrics['memory']['used_gb']:.2f}/{metrics['memory']['total_gb']:.2f} GB) | "
            f"GPU: {metrics['gpu']['percent']:.1f}% ({metrics['gpu']['used_mb']}/{metrics['gpu']['total_mb']} MB) | "
            f"CPU: {metrics['cpu']['percent']:.1f}% | Load: {metrics['cpu']['load_avg_1m']:.2f}"
        )
        
        # Log top memory consumers if at warning level or above
        if mem_percent >= WARNING_THRESHOLD and processes:
            logger.warning("📊 Top memory consumers:")
            for proc in processes[:5]:  # Top 5
                logger.warning(
                    f"   PID {proc['pid']} ({proc['name']}): "
                    f"{proc['rss_mb']:.1f} MB (peak: {proc['peak_mb']:.1f} MB) | "
                    f"CPU: {proc['cpu_percent']:.1f}%"
                )
        
        # Emergency actions — RAM threshold
        if mem_percent >= EMERGENCY_THRESHOLD:
            current_time = time.time()
            if current_time - self.last_critical_alert > self.alert_cooldown:
                logger.error("=" * 80)
                logger.error("🚨 EMERGENCY: MEMORY USAGE CRITICAL - SYSTEM MAY CRASH!")
                logger.error(f"💾 RAM: {metrics['memory']['used_gb']:.2f} GB / {metrics['memory']['total_gb']:.2f} GB ({mem_percent:.1f}%)")
                logger.error(f"🔄 SWAP: {metrics['swap']['used_gb']:.2f} GB / {metrics['swap']['total_gb']:.2f} GB ({metrics['swap']['percent']:.1f}%)")
                logger.error(f"🆓 FREE: {metrics['memory']['free_gb']:.2f} GB available")
                logger.error("=" * 80)
                self.last_critical_alert = current_time

        # ── SWAP PRESSURE GUARD (added 2026-03-04) ──────────────────────────────
        # Root cause of system freeze: RAM was 57% (fine) but swap was 77% (crisis).
        # The original monitor never checked swap, so it did nothing while the
        # system descended into kernel thrashing and a hard freeze.
        swap_pct = metrics['swap']['percent']
        if swap_pct >= SWAP_CRITICAL_THRESHOLD:
            logger.error(
                f"🔴 SWAP CRITICAL: {swap_pct:.1f}% used "
                f"({metrics['swap']['used_gb']:.2f}/{metrics['swap']['total_gb']:.2f} GB) "
                f"— killing trainer to prevent system freeze"
            )
            self.kill_trainer_for_swap_pressure(swap_pct)
        elif swap_pct >= SWAP_WARNING_THRESHOLD:
            logger.warning(
                f"🟡 SWAP WARNING: {swap_pct:.1f}% used "
                f"({metrics['swap']['used_gb']:.2f}/{metrics['swap']['total_gb']:.2f} GB) "
                f"— approaching kill threshold ({SWAP_CRITICAL_THRESHOLD}%)"
            )
    
    def save_snapshot(self, metrics: Dict, processes: List[Dict]):
        """Save detailed snapshot for emergency analysis"""
        snapshot_file = LOG_DIR / f"memory_snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        snapshot = {
            'metrics': metrics,
            'processes': processes,
            'process_peaks': self.process_peaks
        }
        
        try:
            with open(snapshot_file, 'w') as f:
                json.dump(snapshot, f, indent=2)
            logger.info(f"📸 Snapshot saved: {snapshot_file}")
        except Exception as e:
            logger.error(f"❌ Failed to save snapshot: {e}")
    
    def _find_trainer_pid(self) -> int:
        """Return the PID of the running hybrid_trainer, or 0 if not found."""
        for proc in psutil.process_iter(['pid', 'cmdline']):
            try:
                cmdline = ' '.join(proc.info['cmdline'] or [])
                if any(p in cmdline for p in TRAINER_CMDLINE_PATTERNS):
                    return proc.info['pid']
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return 0

    def set_trainer_oom_score(self, pid: int, score: int = 200):
        """
        Raise the OOM score of the trainer so the kernel kills it first
        instead of freezing the system when memory is exhausted.
        Score range: -1000 (never kill) to +1000 (kill first).
        """
        try:
            oom_path = f"/proc/{pid}/oom_score_adj"
            with open(oom_path, 'w') as f:
                f.write(str(score))
            logger.info(f"🛡️  Trainer PID {pid} oom_score_adj set to +{score} (kernel kills trainer before freezing)")
        except Exception as e:
            logger.warning(f"⚠️  Could not set oom_score_adj for PID {pid}: {e}")

    def kill_trainer_for_swap_pressure(self, swap_pct: float):
        """
        Kill the trainer process when swap pressure is dangerously high.
        This is the primary fix for the 2026-03-04 freeze:
          - RAM was 57% (below all thresholds → monitor did nothing)
          - Swap was 77% → system froze 2 hours later
        Killing the trainer frees VMS pressure and prevents kernel thrash.
        The watchdog/startup script will restart it automatically.
        """
        now = time.time()
        if now - self.last_swap_kill_time < SWAP_KILL_COOLDOWN:
            remaining = int(SWAP_KILL_COOLDOWN - (now - self.last_swap_kill_time))
            logger.warning(f"⏳ Swap kill cooldown active ({remaining}s remaining) — skipping")
            return

        trainer_pid = self._find_trainer_pid()
        if trainer_pid == 0:
            logger.warning("⚠️  High swap but trainer not found — cannot kill")
            return

        logger.error(
            f"🚨 SWAP PRESSURE KILL: swap={swap_pct:.1f}% >= {SWAP_CRITICAL_THRESHOLD}% threshold. "
            f"Sending SIGTERM to trainer PID {trainer_pid} to prevent system freeze."
        )
        try:
            import signal as _signal
            os.kill(trainer_pid, _signal.SIGTERM)
            self.last_swap_kill_time = now
            logger.error(f"💀 SIGTERM sent to trainer PID {trainer_pid} — system protected from freeze")
        except ProcessLookupError:
            logger.warning(f"Trainer PID {trainer_pid} already gone")
        except PermissionError as e:
            logger.error(f"❌ Cannot kill trainer PID {trainer_pid}: {e}")

    def run(self):
        """Main monitoring loop"""
        logger.info("🔍 Monitoring started - Press Ctrl+C to stop")

        # On startup, immediately set trainer OOM score so the kernel kills it
        # before freezing the whole system if memory pressure hits.
        trainer_pid = self._find_trainer_pid()
        if trainer_pid:
            self.set_trainer_oom_score(trainer_pid, score=200)
        else:
            logger.info("ℹ️  Trainer not running yet — OOM score will be set when detected")

        _oom_score_set_for: set = set()

        try:
            while True:
                # Collect metrics
                metrics = self.get_system_metrics()
                processes = self.get_process_memory()

                # Set OOM score for trainer if not already done for this PID
                _trainer_pid = self._find_trainer_pid()
                if _trainer_pid and _trainer_pid not in _oom_score_set_for:
                    self.set_trainer_oom_score(_trainer_pid, score=200)
                    _oom_score_set_for.add(_trainer_pid)
                    # Prune stale PIDs from the set to avoid unbounded growth
                    if len(_oom_score_set_for) > 50:
                        _oom_score_set_for.clear()
                        _oom_score_set_for.add(_trainer_pid)

                # Log metrics
                self.log_metrics(metrics, processes)
                
                # Store in history
                self.metrics_history.append({
                    'time': metrics['timestamp'],
                    'ram_percent': metrics['memory']['percent'],
                    'gpu_percent': metrics['gpu']['percent']
                })
                if len(self.metrics_history) > self.max_history:
                    self.metrics_history.pop(0)
                
                # Save snapshot if critical
                if metrics['memory']['percent'] >= CRITICAL_THRESHOLD:
                    self.save_snapshot(metrics, processes)
                
                # Check for OOM events periodically
                current_time = time.time()
                if current_time - self.last_oom_check > OOM_CHECK_INTERVAL:
                    oom_events = self.check_oom_events()
                    if oom_events:
                        logger.error("💀 OOM EVENTS DETECTED:")
                        for event in oom_events:
                            logger.error(f"   {event}")
                    self.last_oom_check = current_time
                
                # Sleep
                time.sleep(CHECK_INTERVAL)
        
        except KeyboardInterrupt:
            logger.info("⏹️  Monitor stopped by user")
        except Exception as e:
            logger.error(f"❌ Monitor error: {e}", exc_info=True)
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Cleanup on shutdown"""
        logger.info("🛑 Monitor shutting down...")
        
        # Generate summary report
        if self.metrics_history:
            max_ram = max(m['ram_percent'] for m in self.metrics_history)
            avg_ram = sum(m['ram_percent'] for m in self.metrics_history) / len(self.metrics_history)
            
            logger.info("📊 Session Summary:")
            logger.info(f"   Runtime: {(time.time() - self.start_time) / 60:.1f} minutes")
            logger.info(f"   Peak RAM: {max_ram:.1f}%")
            logger.info(f"   Average RAM: {avg_ram:.1f}%")
            logger.info(f"   Samples: {len(self.metrics_history)}")
        
        logger.info("✅ Monitor shutdown complete")


def main():
    """Entry point"""
    # Handle signals gracefully
    monitor = MemoryMonitor()
    
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        monitor.shutdown()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start monitoring
    monitor.run()


if __name__ == "__main__":
    main()
