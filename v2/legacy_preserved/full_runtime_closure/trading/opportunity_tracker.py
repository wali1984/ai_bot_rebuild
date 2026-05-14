#!/usr/bin/env python3
"""
Opportunity Tracker - Compares live vs canary performance
Alerts when canary significantly outperforms live
Zero code changes required - works via Redis metrics
"""

import time
import json
import redis
from datetime import datetime, timedelta
from typing import Dict, List, Optional

class OpportunityTracker:
    def __init__(self):
        self.redis = redis.Redis(decode_responses=True)
        self.live_pnl_history = []
        self.canary_pnl_history = []
        self.alert_threshold_pct = 5.0  # Alert if canary beats live by 5%+
        self.window_trades = 50  # Rolling window
        self.last_alert = None
        
    def get_signals_count(self, account_id: str) -> int:
        """Count signals processed by account"""
        try:
            key = f"trader:{account_id}:signals_processed"
            count = self.redis.get(key)
            return int(count) if count else 0
        except:
            return 0
    
    def get_account_pnl(self, account_id: str) -> Optional[float]:
        """Get current PnL for account"""
        try:
            # Try to get from Redis metrics
            key = f"trader:{account_id}:pnl"
            pnl = self.redis.get(key)
            if pnl:
                return float(pnl)
            
            # Fallback: load from portfolio state
            if account_id == 'canary_aggressive':
                with open('data/canary_portfolio.json', 'r') as f:
                    portfolio = json.load(f)
                    return portfolio.get('balance', 10000) - 10000  # PnL from initial
            
            return None
        except Exception as e:
            print(f"Error getting PnL for {account_id}: {e}")
            return None
    
    def calculate_delta(self) -> Dict:
        """Calculate performance delta"""
        if len(self.live_pnl_history) < 10:
            return {
                'status': 'warming_up',
                'message': f'Collecting data... ({len(self.live_pnl_history)}/10 points)'
            }
        
        # Recent window
        window = min(self.window_trades, len(self.live_pnl_history))
        live_window = self.live_pnl_history[-window:]
        canary_window = self.canary_pnl_history[-window:]
        
        # Calculate PnL %
        live_start = live_window[0] if live_window[0] != 0 else 1
        canary_start = canary_window[0] if canary_window[0] != 0 else 1
        
        live_pnl_pct = ((live_window[-1] - live_start) / abs(live_start)) * 100
        canary_pnl_pct = ((canary_window[-1] - canary_start) / abs(canary_start)) * 100
        
        delta_pct = canary_pnl_pct - live_pnl_pct
        
        return {
            'status': 'active',
            'live_pnl': live_window[-1],
            'canary_pnl': canary_window[-1],
            'live_pnl_pct': live_pnl_pct,
            'canary_pnl_pct': canary_pnl_pct,
            'delta_pct': delta_pct,
            'window_size': window,
            'alert': delta_pct > self.alert_threshold_pct
        }
    
    def generate_alert(self, delta: Dict):
        """Generate opportunity loss alert"""
        alert_msg = f"""
{'='*80}
🚨 OPPORTUNITY ALERT 🚨
{'='*80}
Canary lane outperforming live by {delta['delta_pct']:.2f}%

Live PnL (last {delta['window_size']} samples):   {delta['live_pnl_pct']:+.2f}%
Canary PnL (last {delta['window_size']} samples): {delta['canary_pnl_pct']:+.2f}%

💡 RECOMMENDATION: Widen live lane guardrails

Suggested config changes (.env.live):
  MIN_TRADING_CONFIDENCE=0.80  # Down from 0.85
  MAX_CONCURRENT_POSITIONS=3   # Up from 2
  MAX_POSITION_SIZE_PCT=7      # Up from 5

After adjusting:
  export $(cat .env.live | xargs)
  # Restart trader with new config

{'='*80}
"""
        print(alert_msg)
        
        # Log to file
        with open('logs/opportunity_alerts.log', 'a') as f:
            timestamp = datetime.now().isoformat()
            f.write(f"{timestamp} | Delta: {delta['delta_pct']:.2f}% | "
                   f"Live: {delta['live_pnl_pct']:.2f}% | Canary: {delta['canary_pnl_pct']:.2f}%\n")
    
    def run(self):
        """Main tracking loop"""
        print("📊 Opportunity Tracker Started")
        print("=" * 80)
        print(f"Alert threshold: {self.alert_threshold_pct}%")
        print(f"Rolling window: {self.window_trades} samples")
        print(f"Update interval: 5 minutes")
        print("=" * 80)
        print()
        print("Monitoring live vs canary performance...")
        print("(This is a SIMULATION - actual traders not yet deployed)")
        print()
        
        iteration = 0
        
        while True:
            try:
                iteration += 1
                
                # Simulate PnL for demo (replace with real data)
                # Live: conservative, slower growth
                live_pnl = iteration * 2.0 + (iteration % 10) * 0.5
                # Canary: aggressive, faster growth
                canary_pnl = iteration * 3.0 + (iteration % 10) * 0.8
                
                # Track history
                self.live_pnl_history.append(live_pnl)
                self.canary_pnl_history.append(canary_pnl)
                
                # Keep last 1000 points
                if len(self.live_pnl_history) > 1000:
                    self.live_pnl_history = self.live_pnl_history[-500:]
                if len(self.canary_pnl_history) > 1000:
                    self.canary_pnl_history = self.canary_pnl_history[-500:]
                
                # Calculate delta
                delta = self.calculate_delta()
                
                # Print status
                timestamp = datetime.now().strftime('%H:%M:%S')
                if delta['status'] == 'active':
                    status_line = (
                        f"[{timestamp}] "
                        f"Live: ${delta['live_pnl']:.2f} ({delta['live_pnl_pct']:+.2f}%) | "
                        f"Canary: ${delta['canary_pnl']:.2f} ({delta['canary_pnl_pct']:+.2f}%) | "
                        f"Delta: {delta['delta_pct']:+.2f}%"
                    )
                    
                    if delta['alert']:
                        print(status_line + " 🚨")
                        # Alert every 30 minutes
                        now = datetime.now()
                        if self.last_alert is None or (now - self.last_alert) > timedelta(minutes=30):
                            self.generate_alert(delta)
                            self.last_alert = now
                    else:
                        print(status_line + " ✅")
                    
                    # Store to Redis
                    metrics = {
                        'timestamp': time.time(),
                        'live_pnl': delta['live_pnl'],
                        'canary_pnl': delta['canary_pnl'],
                        'delta': delta
                    }
                    self.redis.setex(
                        'opportunity:latest',
                        300,
                        json.dumps(metrics)
                    )
                else:
                    print(f"[{timestamp}] {delta['message']}")
                
                # Sleep 5 minutes (or 10 seconds for demo)
                time.sleep(10)  # Change to 300 for production
                
            except KeyboardInterrupt:
                print("\n\n📊 Opportunity Tracker stopped")
                break
            except Exception as e:
                print(f"\n❌ Error: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(60)

if __name__ == '__main__':
    print("🔧 NOTE: This is a demonstration tracker")
    print("   Real implementation requires:")
    print("   1. Actual trader deployments (live + canary)")
    print("   2. Redis metrics from traders")
    print("   3. Portfolio state tracking")
    print()
    
    tracker = OpportunityTracker()
    tracker.run()
