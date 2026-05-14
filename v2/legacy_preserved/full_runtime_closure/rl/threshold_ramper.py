"""
Phase 4: Threshold Ramping Infrastructure
Gradually increase confidence threshold: 0.55 → 0.65 → 0.75 → 0.85 → 0.90
Monitor ECE < 0.05 and realized accuracy 88-92%
Starting from config.MIN_TRADING_CONFIDENCE (0.55) not 0.75 — signals cap at ~59% due to
entropy penalty; starting too high creates a deadlock where no trades execute to prove the model.
"""
import redis
import json
import time
from typing import Dict, Optional, Tuple, List
from datetime import datetime, timedelta


class ThresholdRamper:
    """Gradually ramps up confidence threshold based on calibration metrics.
    
    IMPORTANT: Schedule starts at MIN_TRADING_CONFIDENCE (0.55) not 0.75.
    Signals are entropy-penalized and typically cap at 55-65%. Starting at 0.75
    creates a permanent deadlock: no trades execute, so model is never 'proven',
    so threshold never drops. The schedule now ramps from the config floor upward.
    """
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

        # Import config floor — fall back to 0.55 if config unavailable
        try:
            import config as _cfg
            _floor = float(getattr(_cfg, 'MIN_TRADING_CONFIDENCE', 0.55))
        except Exception:
            _floor = 0.55
        self._floor = _floor
        
        # Threshold schedule — ramp from config floor upward, not from 0.75
        self.schedule = [
            {'threshold': max(0.60, _floor + 0.05), 'min_ece': 0.12, 'min_accuracy': 0.60, 'min_trades': 20},
            {'threshold': 0.65, 'min_ece': 0.10, 'min_accuracy': 0.65, 'min_trades': 50},
            {'threshold': 0.70, 'min_ece': 0.09, 'min_accuracy': 0.70, 'min_trades': 100},
            {'threshold': 0.75, 'min_ece': 0.08, 'min_accuracy': 0.73, 'min_trades': 150},
            {'threshold': 0.80, 'min_ece': 0.07, 'min_accuracy': 0.76, 'min_trades': 200},
            {'threshold': 0.85, 'min_ece': 0.06, 'min_accuracy': 0.80, 'min_trades': 300},
            {'threshold': 0.90, 'min_ece': 0.05, 'min_accuracy': 0.85, 'min_trades': 400},
        ]
        
        # Safety thresholds (revert if violated)
        self.safety = {
            'max_ece': 0.15,
            'min_accuracy': 0.60,
            'min_win_rate': 0.45,
            'max_drawdown': -25.0
        }
    
    def get_current_threshold(self) -> float:
        """Get current threshold from Redis or config.
        
        Falls back to config.MIN_TRADING_CONFIDENCE (not 0.75) to avoid the
        deadlock where no trades execute because threshold starts too high.
        """
        try:
            threshold = self.redis.hget("rl:config:threshold", "current")
            if threshold:
                return float(threshold)
        except:
            pass
        
        # Default to config floor, not 0.75 (which caused the deadlock)
        return self._floor
    
    def get_calibration_metrics(self) -> Optional[Dict]:
        """Get latest calibration metrics"""
        try:
            metrics = self.redis.hgetall("rl:metrics:calibration")
            if not metrics:
                return None
            
            return {
                k.decode(): json.loads(v) if v.startswith(b'{') or v.startswith(b'[') else float(v)
                for k, v in metrics.items()
            }
        except:
            return None
    
    def get_trading_metrics(self) -> Optional[Dict]:
        """Get latest trading performance metrics"""
        try:
            metrics = self.redis.hgetall("rl:metrics:continuous")
            if not metrics:
                return None
            
            return {
                k.decode(): json.loads(v) if v.startswith(b'{') or v.startswith(b'[') else float(v)
                for k, v in metrics.items()
            }
        except:
            return None
    
    def check_safety(self, calibration: Dict, trading: Dict) -> Tuple[bool, List[str]]:
        """Check if safety thresholds are met"""
        violations = []
        
        # Check ECE
        if calibration.get('ece', 1.0) > self.safety['max_ece']:
            violations.append(f"ECE {calibration['ece']:.4f} > {self.safety['max_ece']}")
        
        # Check accuracy
        if calibration.get('accuracy', 0.0) < self.safety['min_accuracy']:
            violations.append(f"Accuracy {calibration['accuracy']:.2%} < {self.safety['min_accuracy']:.2%}")
        
        # Check win rate
        if trading.get('win_rate', 0.0) < self.safety['min_win_rate'] * 100:
            violations.append(f"Win rate {trading['win_rate']:.2f}% < {self.safety['min_win_rate']*100:.0f}%")
        
        # Check drawdown
        if trading.get('max_drawdown', 0.0) < self.safety['max_drawdown']:
            violations.append(f"Drawdown {trading['max_drawdown']:.2f}% < {self.safety['max_drawdown']:.0f}%")
        
        return len(violations) == 0, violations
    
    def should_ramp_up(self, calibration: Dict, trading: Dict) -> Tuple[bool, float, str]:
        """Check if threshold should be ramped up"""
        current = self.get_current_threshold()
        
        # Find next threshold level
        next_level = None
        for level in self.schedule:
            if level['threshold'] > current:
                next_level = level
                break
        
        if not next_level:
            return False, current, "Already at maximum threshold"
        
        # Check requirements
        ece = calibration.get('ece', 1.0)
        accuracy = calibration.get('accuracy', 0.0)
        num_trades = trading.get('total_trades', 0)
        
        if ece > next_level['min_ece']:
            return False, current, f"ECE {ece:.4f} > {next_level['min_ece']:.2f}"
        
        if accuracy < next_level['min_accuracy']:
            return False, current, f"Accuracy {accuracy:.2%} < {next_level['min_accuracy']:.0%}"
        
        if num_trades < next_level['min_trades']:
            return False, current, f"Trades {num_trades} < {next_level['min_trades']}"
        
        return True, next_level['threshold'], "All requirements met"
    
    def ramp_threshold(self, new_threshold: float, reason: str = ""):
        """Update threshold in Redis and .env"""
        old_threshold = self.get_current_threshold()
        
        # Update Redis
        self.redis.hset("rl:config:threshold", mapping={
            'current': new_threshold,
            'previous': old_threshold,
            'updated_at': time.time(),
            'reason': reason
        })
        
        # Log the change
        log_entry = {
            'timestamp': time.time(),
            'old_threshold': old_threshold,
            'new_threshold': new_threshold,
            'reason': reason
        }
        self.redis.rpush("rl:config:threshold:history", json.dumps(log_entry))
        
        print(f"\n{'='*70}")
        print(f"🎯 THRESHOLD RAMP")
        print(f"{'='*70}")
        print(f"   Old: {old_threshold:.2f}")
        print(f"   New: {new_threshold:.2f}")
        print(f"   Reason: {reason}")
        print(f"   Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*70}\n")
        
        # TODO: Update .env file
        # For now, just notify that manual update needed
        print(f"⚠️  Manual action required:")
        print(f"   Update MIN_TRADING_CONFIDENCE={new_threshold} in .env")
        print(f"   Then restart trader process\n")
    
    def auto_ramp(self, dry_run: bool = False) -> Dict:
        """Automatically check and ramp threshold if conditions met"""
        calibration = self.get_calibration_metrics()
        trading = self.get_trading_metrics()
        
        if not calibration or not trading:
            return {
                'status': 'insufficient_data',
                'message': 'Missing calibration or trading metrics'
            }
        
        # Check safety first
        safe, violations = self.check_safety(calibration, trading)
        if not safe:
            return {
                'status': 'safety_violation',
                'violations': violations,
                'current_threshold': self.get_current_threshold()
            }
        
        # Check if should ramp up
        should_ramp, new_threshold, reason = self.should_ramp_up(calibration, trading)
        
        if not should_ramp:
            return {
                'status': 'conditions_not_met',
                'current_threshold': self.get_current_threshold(),
                'reason': reason,
                'calibration': calibration,
                'trading': {k: v for k, v in trading.items() if k in ['total_trades', 'win_rate', 'max_drawdown']}
            }
        
        if dry_run:
            return {
                'status': 'ready_to_ramp',
                'current_threshold': self.get_current_threshold(),
                'new_threshold': new_threshold,
                'reason': reason,
                'dry_run': True
            }
        
        # Execute ramp
        self.ramp_threshold(new_threshold, reason)
        
        return {
            'status': 'ramped',
            'old_threshold': self.get_current_threshold(),
            'new_threshold': new_threshold,
            'reason': reason
        }


def run_threshold_check(dry_run: bool = True):
    """Run threshold ramping check from command line"""
    r = redis.Redis(host='localhost', port=6379, db=0)
    ramper = ThresholdRamper(r)
    
    print("\n" + "="*70)
    print("THRESHOLD RAMPING CHECK")
    print("="*70)
    
    result = ramper.auto_ramp(dry_run=dry_run)
    
    print(f"\n📊 Status: {result['status']}")
    print(f"   Current Threshold: {result.get('current_threshold', 'N/A')}")
    
    if result['status'] == 'insufficient_data':
        print(f"\n⚠️  {result['message']}")
        print("   Continue trading to collect metrics")
    
    elif result['status'] == 'safety_violation':
        print(f"\n🚨 Safety violations detected:")
        for v in result['violations']:
            print(f"   - {v}")
        print("\n   Threshold will NOT be increased until resolved")
    
    elif result['status'] == 'conditions_not_met':
        print(f"\n⏳ Conditions not yet met:")
        print(f"   Reason: {result['reason']}")
        print(f"\n   Current Metrics:")
        if 'calibration' in result:
            print(f"   - ECE: {result['calibration'].get('ece', 'N/A'):.4f}")
            print(f"   - Accuracy: {result['calibration'].get('accuracy', 'N/A'):.2%}")
        if 'trading' in result:
            print(f"   - Trades: {result['trading'].get('total_trades', 'N/A')}")
            print(f"   - Win Rate: {result['trading'].get('win_rate', 'N/A'):.2f}%")
    
    elif result['status'] == 'ready_to_ramp':
        print(f"\n✅ Ready to ramp!")
        print(f"   New Threshold: {result['new_threshold']}")
        print(f"   Reason: {result['reason']}")
        if dry_run:
            print(f"\n   ⚠️  DRY RUN - no changes made")
            print(f"   Run with --execute to apply changes")
    
    elif result['status'] == 'ramped':
        print(f"\n🎉 Threshold ramped successfully!")
        print(f"   Old: {result['old_threshold']}")
        print(f"   New: {result['new_threshold']}")
        print(f"   Reason: {result['reason']}")
    
    print("\n" + "="*70 + "\n")
    
    return result


if __name__ == "__main__":
    import sys
    
    # Check for --execute flag
    dry_run = '--execute' not in sys.argv
    
    if dry_run:
        print("ℹ️  Running in DRY RUN mode (add --execute to apply changes)\n")
    
    run_threshold_check(dry_run=dry_run)
