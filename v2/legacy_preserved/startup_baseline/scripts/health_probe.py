#!/usr/bin/env python3
"""
System Health Probe - Quick Status Check
=========================================

Purpose: Single-screen health check for all critical system components

Checks:
  1. All 50 combinations have OHLCV + ts_ms
  2. Freshness per-TF (1m≤5min, 5m≤15min, 15m≤30min, 1h≤2h, 4h≤8h)
  3. Heartbeat keys (slow_lane, resampler)
  4. Process status (live_binance, feature_pipeline, resampler, trainer, traders)
  5. Signal stream health

Usage:
  ./scripts/health_probe.sh
  or
  python3 scripts/health_probe.py
"""

import redis
import json
import time
import subprocess
import sys
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Sequence, Union

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
# Defaults (fallback only). Prefer config.py at runtime to avoid drift.
DEFAULT_SYMBOLS = [
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT',
    'LINKUSDT', 'UNIUSDT', 'LTCUSDT'
]
DEFAULT_TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h']

try:
    # When running as `python3 scripts/health_probe.py`, the project root isn't on sys.path.
    # Add it so `import config` resolves to `<repo>/config.py`.
    from pathlib import Path
    _PROJECT_ROOT = Path(__file__).resolve().parents[1]
    if str(_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT))

    import config as _config
    SYMBOLS = list(getattr(_config, "SYMBOLS", DEFAULT_SYMBOLS))
    TIMEFRAMES = list(getattr(_config, "TIMEFRAMES", DEFAULT_TIMEFRAMES))
    SIGNAL_OUTPUT_STREAM = getattr(_config, "SIGNAL_OUTPUT_STREAM", "signals:trading")
    SIGNAL_HEARTBEAT_STREAM = getattr(_config, "SIGNAL_HEARTBEAT_STREAM", "signals:trainer:heartbeat")
    ENABLE_PER_ACCOUNT_STREAMS = getattr(_config, "ENABLE_PER_ACCOUNT_STREAMS", False)
    SIGNAL_STREAM_PER_ACCOUNT = getattr(_config, "SIGNAL_STREAM_PER_ACCOUNT", {}) or {}
except Exception:
    SYMBOLS = DEFAULT_SYMBOLS
    TIMEFRAMES = DEFAULT_TIMEFRAMES
    SIGNAL_OUTPUT_STREAM = "signals:trading"
    SIGNAL_HEARTBEAT_STREAM = "signals:trainer:heartbeat"
    ENABLE_PER_ACCOUNT_STREAMS = False
    SIGNAL_STREAM_PER_ACCOUNT = {}

# Per-TF freshness thresholds (in seconds)
FRESHNESS_THRESHOLDS = {
    '1m': 300,      # 5 minutes
    '5m': 900,      # 15 minutes
    '15m': 1800,    # 30 minutes
    '1h': 7200,     # 2 hours
    '4h': 28800     # 8 hours
}

class HealthProbe:
    """System health checker"""
    
    def __init__(self):
        self.redis = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        self.current_time_ms = time.time() * 1000
        self.issues = []
        
    def print_header(self, title: str):
        """Print section header"""
        print("\n" + "=" * 80)
        print(f"{title}")
        print("=" * 80)
    
    def check_process(self, name: str, patterns: Union[str, Sequence[str]]) -> bool:
        """Check if a process is running (simple ps substring match)."""
        try:
            if isinstance(patterns, str):
                patterns = [patterns]

            result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
            lines = result.stdout.splitlines()

            matched_line = None
            for pat in patterns:
                matches = [l for l in lines if pat in l and 'grep' not in l]
                if matches:
                    matched_line = matches[0]
                    break

            if matched_line:
                parts = matched_line.split()
                if len(parts) > 10:
                    print(f"  ✅ {name}: Running (PID {parts[1]}, CPU {parts[2]}%)")
                    return True

            print(f"  ❌ {name}: NOT RUNNING")
            self.issues.append(f"{name} not running")
            return False
        except Exception as e:
            print(f"  ❌ {name}: Error checking - {e}")
            return False
    
    def check_ohlcv_completeness(self):
        """Check all 50 combinations have OHLCV + ts_ms"""
        self.print_header("1. OHLCV COMPLETENESS CHECK")
        
        missing = []
        incomplete = []
        fresh_count = 0
        stale_count = 0
        
        required_fields = ['open', 'high', 'low', 'close', 'volume', 'ts_ms']
        
        for symbol in SYMBOLS:
            for tf in TIMEFRAMES:
                key = f"unified_features:{symbol}:{tf}"
                
                # Check if all required fields exist
                fields = self.redis.hmget(key, required_fields)
                
                if not any(fields):
                    missing.append(f"{symbol}:{tf}")
                    continue
                
                if not all(fields):
                    incomplete.append(f"{symbol}:{tf} (missing fields)")
                    continue
                
                # Check freshness
                ts_ms = float(fields[-1]) if fields[-1] else 0
                age_s = (self.current_time_ms - ts_ms) / 1000
                threshold = FRESHNESS_THRESHOLDS.get(tf, 300)
                
                if age_s <= threshold:
                    fresh_count += 1
                else:
                    stale_count += 1
        
        total = len(SYMBOLS) * len(TIMEFRAMES)
        complete = total - len(missing) - len(incomplete)
        
        print(f"\n  Total combinations: {total}")
        print(f"  ✅ Complete: {complete}")
        print(f"  ⚠️  Incomplete: {len(incomplete)}")
        print(f"  ❌ Missing: {len(missing)}")
        print(f"\n  Freshness: {fresh_count} fresh, {stale_count} stale")
        
        if missing:
            print(f"\n  Missing: {', '.join(missing[:10])}" + (" ..." if len(missing) > 10 else ""))
            self.issues.append(f"{len(missing)} combinations missing OHLCV")
        
        if incomplete:
            print(f"  Incomplete: {', '.join(incomplete[:10])}" + (" ..." if len(incomplete) > 10 else ""))
            self.issues.append(f"{len(incomplete)} combinations incomplete")
        
        return complete == total and fresh_count >= total * 0.8
    
    def check_per_tf_freshness(self):
        """Check per-TF freshness thresholds"""
        self.print_header("2. PER-TF FRESHNESS CHECK")
        
        results = {}
        
        for tf in TIMEFRAMES:
            threshold = FRESHNESS_THRESHOLDS[tf]
            fresh = 0
            stale = 0
            missing = 0
            
            for symbol in SYMBOLS:
                key = f"unified_features:{symbol}:{tf}"
                ts_ms = self.redis.hget(key, 'ts_ms')
                
                if not ts_ms:
                    missing += 1
                    continue
                
                age_s = (self.current_time_ms - float(ts_ms)) / 1000
                
                if age_s <= threshold:
                    fresh += 1
                else:
                    stale += 1
            
            status = "✅" if fresh == len(SYMBOLS) else ("⚠️" if fresh >= len(SYMBOLS) * 0.8 else "❌")
            print(f"  {status} {tf:3s}: {fresh}/{len(SYMBOLS)} fresh (threshold: {threshold}s = {threshold/60:.0f}min)")
            
            if stale > 0 or missing > 0:
                self.issues.append(f"{tf}: {stale} stale, {missing} missing")
            
            results[tf] = (fresh, stale, missing)
        
        return all(r[0] >= len(SYMBOLS) * 0.8 for r in results.values())
    
    def check_heartbeats(self):
        """Check heartbeat keys"""
        self.print_header("3. HEARTBEAT CHECK")
        
        heartbeats = [
            ('features:slow_lane:last_run_ms', 'Slow Lane Last Run', 600),
            ('features:slow_lane:last_success_ms', 'Slow Lane Last Success', 600),
            ('features:resampler:last_run_ms', 'Resampler Last Run', 60),
            ('features:resampler:last_success_ms', 'Resampler Last Success', 60),
            ('heartbeat:FeaturePipeline', 'Feature Pipeline', 30)
        ]
        
        all_ok = True
        
        for key, name, max_age_s in heartbeats:
            value = self.redis.get(key)
            
            if not value:
                print(f"  ⚠️  {name}: No heartbeat")
                continue
            
            try:
                if key == 'heartbeat:FeaturePipeline':
                    hb_data = json.loads(value)
                    hb_ms = hb_data.get('timestamp_ms', 0)
                else:
                    hb_ms = float(value)
                
                age_s = (self.current_time_ms - hb_ms) / 1000
                
                if age_s <= max_age_s:
                    print(f"  ✅ {name}: {age_s:.0f}s ago")
                else:
                    print(f"  ❌ {name}: {age_s:.0f}s ago (stale, max {max_age_s}s)")
                    self.issues.append(f"{name} heartbeat stale")
                    all_ok = False
                    
            except Exception as e:
                print(f"  ❌ {name}: Error - {e}")
                all_ok = False
        
        return all_ok
    
    def check_processes(self):
        """Check all required processes"""
        self.print_header("4. PROCESS CHECK")
        
        processes = [
            ('live_binance', ['ingest/live_binance.py', '-m ingest.live_binance']),
            ('feature_pipeline', ['feature_pipeline.py']),
            ('ohlcv_resampler', ['ohlcv_resampler_hotfix.py', 'ohlcv_resampler']),
        ]
        
        all_running = True
        for name, pattern in processes:
            if not self.check_process(name, pattern):
                all_running = False
        
        # Optional processes (but recommended for full live operation)
        print("\n  Optional:")
        self.check_process('coinapi_wsds', ['-m ingest.live_coinapi_wsds', 'ingest/live_coinapi_wsds.py'])
        self.check_process('coinapi_v1', ['-m ingest.live_coinapi_v1', 'ingest/live_coinapi_v1.py'])
        self.check_process('technical_analysis', ['ingest/live_technical_analysis.py'])
        self.check_process('liq_bridge', ['ingest/liquidation_bridge.py'])
        self.check_process('liq_levels', ['ingest/liquidation_levels_engine.py'])
        self.check_process('signal_router', ['trading/signal_router.py'])
        self.check_process('hybrid_trainer', ['-m rl.hybrid_trainer', 'rl/hybrid_trainer.py'])
        # Traders may be started with extra flags (e.g. `python3 -u ...`), so match on script path.
        self.check_process('trader_primary', ['trading/trader.py'])
        self.check_process('trader_asjad', ['trading/trader-asjad.py'])
        
        return all_running
    
    def _stream_last_age_seconds(self, stream_key: str) -> Optional[float]:
        """Return age (seconds) of newest entry by Redis stream id, or None if empty/unavailable."""
        try:
            messages = self.redis.xrevrange(stream_key, '+', '-', count=1)
            if not messages:
                return None
            stream_id = messages[0][0]
            ms_part = float(str(stream_id).split('-')[0])
            return (self.current_time_ms - ms_part) / 1000.0
        except Exception:
            return None

    def check_signal_stream(self):
        """Check trainer heartbeat + signal stream health (LIVE contract)."""
        self.print_header("5. SIGNAL STREAM CHECK")
        
        try:
            # 1) Heartbeat stream (primary liveness indicator)
            hb_len = self.redis.xlen(SIGNAL_HEARTBEAT_STREAM)
            hb_age = self._stream_last_age_seconds(SIGNAL_HEARTBEAT_STREAM)
            if hb_len > 0 and hb_age is not None:
                status = "✅" if hb_age <= 90 else "⚠️"
                print(f"  {status} Trainer heartbeat: stream={SIGNAL_HEARTBEAT_STREAM} | len={hb_len} | last={hb_age:.0f}s ago")
                if hb_age > 180:
                    self.issues.append("trainer heartbeat stale")
            else:
                print(f"  ❌ Trainer heartbeat: stream={SIGNAL_HEARTBEAT_STREAM} | empty/missing")
                self.issues.append("trainer heartbeat missing")

            # 2) Signal streams (routing-aware)
            stream_candidates: List[str] = []
            if ENABLE_PER_ACCOUNT_STREAMS and SIGNAL_STREAM_PER_ACCOUNT:
                stream_candidates.extend(list(SIGNAL_STREAM_PER_ACCOUNT.values()))
            stream_candidates.append(SIGNAL_OUTPUT_STREAM)
            # de-dupe (preserve order)
            seen = set()
            stream_keys = []
            for s in stream_candidates:
                if s and s not in seen:
                    stream_keys.append(s)
                    seen.add(s)

            best_stream = None
            for stream_key in stream_keys:
                length = self.redis.xlen(stream_key)
                age = self._stream_last_age_seconds(stream_key)
                if length > 0 and age is not None:
                    print(f"  ✅ Signals: stream={stream_key} | len={length} | last={age:.0f}s ago")
                    if best_stream is None:
                        best_stream = stream_key
                else:
                    # Canonical stream is expected to be empty when per-account streams are enabled
                    if ENABLE_PER_ACCOUNT_STREAMS and stream_key == SIGNAL_OUTPUT_STREAM:
                        print(f"  ℹ️  Signals: stream={stream_key} | empty (expected: per-account streams enabled)")
                    else:
                        print(f"  ⚠️  Signals: stream={stream_key} | empty")

            # 3) Validate structure of newest signal (best-effort)
            if best_stream:
                messages = self.redis.xrevrange(best_stream, '+', '-', count=1)
                if messages:
                    fields = messages[0][1] or {}
                    payload_raw = fields.get("data")
                    try:
                        payload = json.loads(payload_raw) if payload_raw else {}
                        required = ['symbol', 'action_name', 'confidence', 'ts_ms', 'signal_id']
                        missing = [f for f in required if f not in payload]
                        if missing:
                            print(f"  ⚠️  Signal structure: missing fields {missing}")
                        else:
                            print(f"  ✅ Signal structure: OK")
                    except Exception:
                        print("  ℹ️  Signal structure: cannot parse (unexpected format)")

            # Pass criteria: heartbeat must exist and be reasonably fresh
            if hb_len <= 0 or hb_age is None:
                return False
            return hb_age <= 180
                
        except Exception as e:
            print(f"  ❌ Error checking stream: {e}")
            return False
    
    def run(self):
        """Run all health checks"""
        print("\n" + "🏥" * 40)
        print(f"SYSTEM HEALTH PROBE - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("🏥" * 40)
        
        checks = [
            ("OHLCV Completeness", self.check_ohlcv_completeness),
            ("Per-TF Freshness", self.check_per_tf_freshness),
            ("Heartbeats", self.check_heartbeats),
            ("Processes", self.check_processes),
            ("Signal Stream", self.check_signal_stream),
        ]
        
        results = {}
        for name, check_func in checks:
            try:
                results[name] = check_func()
            except Exception as e:
                print(f"\n  ❌ {name} check failed: {e}")
                results[name] = False
        
        # Summary
        self.print_header("SUMMARY")
        
        passed = sum(1 for r in results.values() if r)
        total = len(results)
        
        for name, result in results.items():
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"  {status}: {name}")
        
        print(f"\n  Overall: {passed}/{total} checks passed")
        
        if self.issues:
            print(f"\n  Issues found:")
            for issue in self.issues[:10]:
                print(f"    - {issue}")
            if len(self.issues) > 10:
                print(f"    ... and {len(self.issues) - 10} more")
        
        # GO/NO-GO
        print("\n" + "=" * 80)
        if passed == total and not self.issues:
            print("🚀 STATUS: GO FOR LAUNCH")
        elif passed >= total * 0.8:
            print("⚠️  STATUS: CAUTION - Review issues before launch")
        else:
            print("🛑 STATUS: NO-GO - Critical issues must be resolved")
        print("=" * 80 + "\n")
        
        return passed == total


def main():
    probe = HealthProbe()
    success = probe.run()
    return 0 if success else 1


if __name__ == '__main__':
    exit(main())
