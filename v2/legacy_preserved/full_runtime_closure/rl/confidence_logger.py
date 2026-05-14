"""
Phase 2A: Confidence Logging Infrastructure
Logs logits + actions + outcomes for temperature calibration
"""
import redis
import json
import time
import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from collections import deque


@dataclass
class EvalRecord:
    """Evaluation record for calibration"""
    timestamp: float
    symbol: str
    timeframe: str
    ppo_logit: float
    masa_logit: float
    blended_logit: float
    raw_confidence: float
    predicted_action: int
    actual_action: int  # What actually happened
    outcome_pnl: Optional[float] = None  # PnL if trade executed
    outcome_pnl_pct: Optional[float] = None
    outcome_correct: Optional[bool] = None  # True if prediction matched outcome
    execution_delay: Optional[float] = None  # Seconds between prediction and execution


class ConfidenceLogger:
    """Logs confidence predictions and outcomes for calibration"""
    
    def __init__(self, redis_client: redis.Redis, max_records: int = 10000):
        self.redis = redis_client
        self.max_records = max_records
        self.pending_records = {}  # symbol:timeframe -> EvalRecord
        
    def log_prediction(
        self, 
        symbol: str, 
        timeframe: str, 
        ppo_logit: float, 
        masa_logit: float,
        blended_logit: float,
        raw_confidence: float,
        predicted_action: int
    ) -> str:
        """Log a prediction, returns record_id for later outcome update"""
        record = EvalRecord(
            timestamp=time.time(),
            symbol=symbol,
            timeframe=timeframe,
            ppo_logit=ppo_logit,
            masa_logit=masa_logit,
            blended_logit=blended_logit,
            raw_confidence=raw_confidence,
            predicted_action=predicted_action,
            actual_action=-1  # Unknown yet
        )
        
        record_id = f"{symbol}:{timeframe}:{int(record.timestamp * 1000)}"
        self.pending_records[record_id] = record
        
        # Also store in Redis immediately
        self.redis.hset(
            "rl:eval:pending",
            record_id,
            json.dumps(asdict(record))
        )
        
        return record_id
    
    def log_outcome(
        self,
        record_id: str,
        actual_action: int,
        outcome_pnl: Optional[float] = None,
        outcome_pnl_pct: Optional[float] = None,
        execution_delay: Optional[float] = None
    ):
        """Update a prediction with actual outcome"""
        # Try to get from pending
        record = self.pending_records.get(record_id)
        
        if not record:
            # Try to load from Redis
            pending = self.redis.hget("rl:eval:pending", record_id)
            if pending:
                record = EvalRecord(**json.loads(pending))
        
        if not record:
            return  # Record not found
        
        # Update outcome
        record.actual_action = actual_action
        record.outcome_pnl = outcome_pnl
        record.outcome_pnl_pct = outcome_pnl_pct
        record.outcome_correct = (record.predicted_action == actual_action)
        record.execution_delay = execution_delay
        
        # Move to completed records
        self.redis.rpush(
            "rl:eval:completed",
            json.dumps(asdict(record))
        )
        
        # Remove from pending
        self.redis.hdel("rl:eval:pending", record_id)
        if record_id in self.pending_records:
            del self.pending_records[record_id]
        
        # Trim completed to max_records
        self.redis.ltrim("rl:eval:completed", -self.max_records, -1)
    
    def get_calibration_data(
        self, 
        min_records: int = 100,
        max_age_hours: Optional[float] = 24
    ) -> List[Dict]:
        """Get records for calibration fitting"""
        records = self.redis.lrange("rl:eval:completed", -min_records * 2, -1)
        
        parsed = []
        cutoff_time = time.time() - (max_age_hours * 3600 if max_age_hours else float('inf'))
        
        for rec in records:
            try:
                data = json.loads(rec)
                if data['timestamp'] >= cutoff_time and data['outcome_correct'] is not None:
                    parsed.append(data)
            except:
                pass
        
        return parsed[-min_records:] if len(parsed) >= min_records else parsed
    
    def calculate_calibration_metrics(self, records: Optional[List[Dict]] = None) -> Dict:
        """Calculate ECE and other calibration metrics"""
        if records is None:
            records = self.get_calibration_data()
        
        if len(records) < 10:
            return {
                'ece': None,
                'accuracy': None,
                'avg_confidence': None,
                'num_records': len(records)
            }
        
        # Extract confidences and correctness
        confidences = np.array([r['raw_confidence'] for r in records])
        correct = np.array([r['outcome_correct'] for r in records])
        
        # Calculate Expected Calibration Error (ECE)
        # Bin predictions by confidence
        n_bins = 10
        bin_edges = np.linspace(0, 1, n_bins + 1)
        bin_indices = np.digitize(confidences, bin_edges) - 1
        bin_indices = np.clip(bin_indices, 0, n_bins - 1)
        
        ece = 0.0
        for i in range(n_bins):
            bin_mask = bin_indices == i
            if np.sum(bin_mask) > 0:
                bin_confidence = np.mean(confidences[bin_mask])
                bin_accuracy = np.mean(correct[bin_mask])
                bin_weight = np.sum(bin_mask) / len(confidences)
                ece += bin_weight * abs(bin_confidence - bin_accuracy)
        
        return {
            'ece': float(ece),
            'accuracy': float(np.mean(correct)),
            'avg_confidence': float(np.mean(confidences)),
            'num_records': len(records),
            'timestamp': time.time()
        }
    
    def push_metrics(self):
        """Calculate and push calibration metrics to Redis"""
        metrics = self.calculate_calibration_metrics()
        if metrics['ece'] is not None:
            self.redis.hset("rl:metrics:calibration", mapping={
                k: json.dumps(v) if isinstance(v, (dict, list)) else v 
                for k, v in metrics.items()
            })


if __name__ == "__main__":
    # Test the confidence logger
    r = redis.Redis(host='localhost', port=6379, db=0)
    logger = ConfidenceLogger(r)
    
    # Simulate predictions and outcomes
    import random
    for i in range(200):
        ppo_logit = random.uniform(-2, 5)
        masa_logit = random.uniform(-2, 5)
        blended = 0.7 * ppo_logit + 0.3 * masa_logit
        confidence = 1 / (1 + np.exp(-blended * 2.5))
        predicted = random.choice([0, 1, 2, 3, 4])
        
        record_id = logger.log_prediction(
            "BTCUSDT", "1h",
            ppo_logit, masa_logit, blended, confidence, predicted
        )
        
        # Simulate outcome (80% accurate)
        if random.random() < 0.8:
            actual = predicted
        else:
            actual = random.choice([0, 1, 2, 3, 4])
        
        logger.log_outcome(
            record_id,
            actual,
            outcome_pnl=random.uniform(-50, 100),
            outcome_pnl_pct=random.uniform(-1, 2),
            execution_delay=random.uniform(0.1, 2.0)
        )
    
    logger.push_metrics()
    print("Calibration Metrics:")
    print(json.dumps(logger.calculate_calibration_metrics(), indent=2))
