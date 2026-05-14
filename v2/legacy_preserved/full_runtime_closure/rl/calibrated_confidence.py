"""
Phase 2C: Apply Temperature-Calibrated Confidence in Live Trading
Integrates temperature scaling into hybrid_trainer.py signal generation
"""
import redis
import json
import numpy as np
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)


class CalibratedConfidenceManager:
    """Manages temperature-scaled confidence for live trading"""
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.enabled = self._check_feature_flag()
        self.temperature = self._load_temperature()
        
        if self.enabled and self.temperature is not None:
            logger.info(f"✅ Calibrated confidence ENABLED (temp={self.temperature:.4f})")
        elif self.enabled and self.temperature is None:
            logger.warning(f"⚠️ Calibrated confidence ENABLED but no temperature found - using raw confidence")
        else:
            logger.info(f"ℹ️  Calibrated confidence DISABLED - using raw confidence")
    
    def _check_feature_flag(self) -> bool:
        """Check if calibration is enabled via Redis config"""
        try:
            flag = self.redis.hget("rl:config:features", "calibrated_confidence")
            if flag:
                return flag.decode().lower() in ('true', '1', 'yes', 'on')
        except:
            pass
        return False
    
    def _load_temperature(self) -> Optional[float]:
        """Load optimal temperature from Redis"""
        try:
            temp = self.redis.hget("rl:calibration:temperature", "temperature")
            if temp:
                return float(temp)
        except:
            pass
        return None
    
    def reload(self):
        """Reload feature flag and temperature (call periodically)"""
        self.enabled = self._check_feature_flag()
        self.temperature = self._load_temperature()
    
    def apply_temperature_to_logit(self, logit: float) -> float:
        """Apply temperature scaling to logit before converting to confidence"""
        if not self.enabled or self.temperature is None:
            return logit
        
        # Temperature scaling: logit / T
        # Higher T (>1.0) = softer/less confident
        # Lower T (<1.0) = sharper/more confident
        scaled_logit = logit / self.temperature
        
        return scaled_logit
    
    def get_calibrated_confidence(
        self, 
        raw_confidence: float,
        blended_logit: float,
        ppo_logit: float,
        masa_logit: float = 0.0
    ) -> Dict[str, float]:
        """
        Calculate both raw and calibrated confidence
        
        Returns dict with:
        - raw_confidence: Original uncalibrated confidence
        - calibrated_confidence: Temperature-scaled confidence
        - temperature: Applied temperature value
        - blended_logit: Original logit
        - scaled_logit: Temperature-scaled logit
        - used_calibrated: Whether calibration was applied
        """
        result = {
            'raw_confidence': raw_confidence,
            'calibrated_confidence': raw_confidence,  # Default to raw
            'temperature': self.temperature if self.temperature else 1.0,
            'blended_logit': blended_logit,
            'scaled_logit': blended_logit,
            'used_calibrated': False
        }
        
        if not self.enabled or self.temperature is None:
            return result
        
        # Apply temperature scaling to logit
        scaled_logit = self.apply_temperature_to_logit(blended_logit)
        result['scaled_logit'] = scaled_logit
        
        # Recalculate confidence from scaled logit
        # The confidence calculation in hybrid_trainer.py is based on:
        # 1. Base confidence from PPO action agreement (0.33 to 1.0)
        # 2. Boosted if MASA agrees (multiplier 1.0 to 1.35)
        # 3. Penalized if MASA disagrees (multiplier 0.90)
        
        # For calibrated confidence, we adjust the final confidence
        # by applying sigmoid to the scaled logit and blending with raw
        
        # Convert scaled logit to probability using sigmoid
        scaled_prob = 1.0 / (1.0 + np.exp(-scaled_logit))
        
        # Blend raw confidence with scaled probability
        # Give more weight to scaled probability if temperature is well-calibrated
        blend_weight = 0.6  # 60% scaled, 40% raw
        calibrated = blend_weight * scaled_prob + (1 - blend_weight) * raw_confidence
        
        # Ensure calibrated confidence is in valid range
        calibrated = np.clip(calibrated, 0.0, 1.0)
        
        result['calibrated_confidence'] = calibrated
        result['used_calibrated'] = True
        
        logger.debug(
            f"Calibration applied: raw={raw_confidence:.3f}, "
            f"scaled_logit={scaled_logit:.3f}, "
            f"scaled_prob={scaled_prob:.3f}, "
            f"calibrated={calibrated:.3f}, "
            f"temp={self.temperature:.4f}"
        )
        
        return result
    
    def should_use_calibrated(self) -> bool:
        """Check if calibrated confidence should be used"""
        return self.enabled and self.temperature is not None
    
    def log_prediction_comparison(
        self,
        symbol: str,
        timeframe: str,
        raw_conf: float,
        cal_conf: float,
        action: int,
        blended_logit: float
    ):
        """Log comparison between raw and calibrated confidence"""
        if not self.should_use_calibrated():
            return
        
        comparison = {
            'timestamp': int(time.time()),
            'symbol': symbol,
            'timeframe': timeframe,
            'raw_confidence': raw_conf,
            'calibrated_confidence': cal_conf,
            'difference': cal_conf - raw_conf,
            'action': action,
            'blended_logit': blended_logit,
            'temperature': self.temperature
        }
        
        # Store in Redis stream for analysis
        try:
            self.redis.xadd(
                "rl:calibration:comparisons",
                comparison,
                maxlen=1000  # Keep last 1000 comparisons
            )
        except Exception as e:
            logger.warning(f"Failed to log calibration comparison: {e}")


# Example integration into hybrid_trainer.py
def example_integration():
    """
    This shows how to integrate CalibratedConfidenceManager into hybrid_trainer.py
    
    In HybridRLTrainer.__init__():
        self.calibration_manager = CalibratedConfidenceManager(self.redis_client)
    
    In the signal generation loop (around line 12450):
        # After calculating raw confidence
        confidence = base_confidence  # Raw confidence from PPO agreement
        
        # ... existing MASA agreement/disagreement logic ...
        
        # Apply calibration if enabled
        calibration_result = self.calibration_manager.get_calibrated_confidence(
            raw_confidence=confidence,
            blended_logit=blended_logit,
            ppo_logit=ppo_logit,
            masa_logit=masa_logit
        )
        
        # Use calibrated confidence for trading decisions
        final_confidence = calibration_result['calibrated_confidence']
        
        # Log both for comparison
        logger.debug(
            f"{symbol}:{timeframe} Confidence: "
            f"raw={calibration_result['raw_confidence']:.3f}, "
            f"calibrated={final_confidence:.3f}, "
            f"temp={calibration_result['temperature']:.4f}"
        )
        
        # Store both in signal payload
        signal_payload['raw_confidence'] = calibration_result['raw_confidence']
        signal_payload['calibrated_confidence'] = final_confidence
        signal_payload['temperature'] = calibration_result['temperature']
        
        # Use calibrated confidence for threshold check
        if final_confidence < MIN_TRADING_CONFIDENCE:
            logger.info(f"⏭️ Skipping signal with low confidence: {final_confidence:.1%} < {MIN_TRADING_CONFIDENCE:.1%}")
            continue
    """
    pass


if __name__ == "__main__":
    import time
    
    # Example usage
    r = redis.Redis(host='localhost', port=6379, db=0)
    
    # Enable calibration
    r.hset("rl:config:features", "calibrated_confidence", "true")
    
    # Set temperature (normally done by temperature_calibration.py)
    r.hset("rl:calibration:temperature", "temperature", "0.8")
    
    manager = CalibratedConfidenceManager(r)
    
    # Test calibration
    test_cases = [
        {'raw': 0.75, 'logit': 0.5, 'ppo': 0.6, 'masa': 0.4},
        {'raw': 0.85, 'logit': 1.0, 'ppo': 0.9, 'masa': 1.1},
        {'raw': 0.65, 'logit': -0.2, 'ppo': 0.1, 'masa': -0.5},
    ]
    
    print("\n" + "="*70)
    print("CALIBRATED CONFIDENCE TEST")
    print("="*70)
    print(f"Enabled: {manager.enabled}")
    print(f"Temperature: {manager.temperature}")
    print()
    
    for i, case in enumerate(test_cases, 1):
        result = manager.get_calibrated_confidence(
            raw_confidence=case['raw'],
            blended_logit=case['logit'],
            ppo_logit=case['ppo'],
            masa_logit=case['masa']
        )
        
        print(f"Test {i}:")
        print(f"  Raw Confidence:        {result['raw_confidence']:.3f}")
        print(f"  Calibrated Confidence: {result['calibrated_confidence']:.3f}")
        print(f"  Difference:            {result['calibrated_confidence'] - result['raw_confidence']:+.3f}")
        print(f"  Blended Logit:         {result['blended_logit']:.3f}")
        print(f"  Scaled Logit:          {result['scaled_logit']:.3f}")
        print(f"  Temperature:           {result['temperature']:.4f}")
        print(f"  Used Calibration:      {result['used_calibrated']}")
        print()
