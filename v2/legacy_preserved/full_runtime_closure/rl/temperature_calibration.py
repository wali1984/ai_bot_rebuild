"""
Phase 2B: Temperature Calibration
"""
import redis
import numpy as np
from scipy.optimize import minimize_scalar
import json
import time
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class TemperatureCalibrator:
    """Calibrates model confidence using temperature scaling"""
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
    
    def get_completed_records(self) -> List[Dict]:
        """Get all completed evaluation records"""
        try:
            records = self.redis.lrange("rl:eval:completed", 0, -1)
            return [json.loads(r) for r in records]
        except:
            return []
    
    def calculate_ece(self, confidences: np.ndarray, correctness: np.ndarray, n_bins: int = 10) -> float:
        """Calculate Expected Calibration Error"""
        bin_boundaries = np.linspace(0, 1, n_bins + 1)
        ece = 0.0
        
        for i in range(n_bins):
            bin_mask = (confidences >= bin_boundaries[i]) & (confidences < bin_boundaries[i + 1])
            
            if np.sum(bin_mask) > 0:
                avg_confidence = np.mean(confidences[bin_mask])
                avg_accuracy = np.mean(correctness[bin_mask])
                bin_weight = np.sum(bin_mask) / len(confidences)
                ece += bin_weight * abs(avg_confidence - avg_accuracy)
        
        return ece
    
    def fit_temperature(self, min_records: int = 100, n_bins: int = 10) -> Optional[Dict]:
        """Fit optimal temperature to minimize ECE"""
        records = self.get_completed_records()
        
        if len(records) < min_records:
            logger.warning(f"Insufficient records: {len(records)} < {min_records}")
            return None
        
        logits = []
        confidences = []
        correctness = []
        
        for rec in records:
            logits.append(rec.get('blended_logit', 0.0))
            confidences.append(rec.get('raw_confidence', 0.5))
            correctness.append(1.0 if rec.get('outcome_correct', False) else 0.0)
        
        logits = np.array(logits)
        confidences = np.array(confidences)
        correctness = np.array(correctness)
        
        ece_before = self.calculate_ece(confidences, correctness, n_bins)
        
        def objective(T):
            scaled_logits = logits / T
            scaled_confidences = 1.0 / (1.0 + np.exp(-scaled_logits))
            return self.calculate_ece(scaled_confidences, correctness, n_bins)
        
        result = minimize_scalar(objective, bounds=(0.1, 10.0), method='bounded')
        
        optimal_T = result.x
        ece_after = result.fun
        accuracy = np.mean(correctness)
        avg_conf_before = np.mean(confidences)
        scaled_confidences = 1.0 / (1.0 + np.exp(-logits / optimal_T))
        avg_conf_after = np.mean(scaled_confidences)
        
        calibration_result = {
            'temperature': optimal_T,
            'last_calibration': time.time(),
            'ece_before': ece_before,
            'ece_after': ece_after,
            'improvement': (ece_before - ece_after) / ece_before * 100,
            'accuracy': accuracy,
            'num_records': len(records),
            'avg_confidence_before': avg_conf_before,
            'avg_confidence_after': avg_conf_after
        }
        
        self.redis.hset(
            "rl:calibration:temperature",
            mapping={k: json.dumps(v) if isinstance(v, (list, dict)) else v 
                     for k, v in calibration_result.items()}
        )
        
        return calibration_result
    
    def get_temperature(self) -> Optional[float]:
        """Get current temperature from Redis"""
        try:
            temp = self.redis.hget("rl:calibration:temperature", "temperature")
            if temp:
                return float(temp)
        except:
            pass
        return None


def run_calibration(min_records: int = 100):
    """Run calibration"""
    r = redis.Redis(host='localhost', port=6379, db=0)
    calibrator = TemperatureCalibrator(r)
    
    print("\nTEMPERATURE CALIBRATION")
    print("="*70)
    
    num_records = r.llen("rl:eval:completed")
    print(f"Completed records: {num_records}")
    
    if num_records < min_records:
        print(f"Need {min_records - num_records} more records\n")
        return
    
    result = calibrator.fit_temperature(min_records=min_records)
    
    if result:
        print(f"\nResults:")
        print(f"  Temperature:   {result['temperature']:.4f}")
        print(f"  ECE Before:    {result['ece_before']:.4f}")
        print(f"  ECE After:     {result['ece_after']:.4f}")
        print(f"  Improvement:   {result['improvement']:.1f}%")
        print(f"  Accuracy:      {result['accuracy']:.2%}\n")
    else:
        print("Calibration failed\n")


if __name__ == "__main__":
    import sys
    min_records = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    run_calibration(min_records)
