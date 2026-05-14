# -*- coding: utf-8 -*-
"""
Microstructure TF Modifier
==========================
Uses aggregated microstructure data to modify trading actions.

This is a "modifier" layer, not a blocker:
- Reduces position size based on spoof/fast-move risk
- Delays entry when manipulation signals are high
- Boosts urgency for protective actions

The 1m "management-only" invariant is preserved:
- 1m cannot open new risk when flat (enforced elsewhere)
- 1m microstructure can refine timing for higher TF entries
- 1m can manage existing positions

Feature flag: ENABLE_MICROSTRUCTURE_TF_MODIFIER
"""

import os
import time
import logging
from typing import Dict, Optional, Any, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ModifierResult:
    """Result of microstructure modification."""
    # Size adjustment
    size_multiplier: float = 1.0  # 0.3-1.0, applied to position size
    
    # Entry control
    delay_entry: bool = False
    delay_reason: str = ""
    confirm_required: bool = False
    confirm_reason: str = ""
    
    # Protective action boost
    urgency_boost: bool = False
    urgency_reason: str = ""
    
    # Block decision (only for extreme cases)
    block: bool = False
    block_reason: str = ""
    
    # Metadata
    spoof_score: float = 0.0
    fast_move_score: float = 0.0
    source_tf: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'size_multiplier': self.size_multiplier,
            'delay_entry': self.delay_entry,
            'delay_reason': self.delay_reason,
            'confirm_required': self.confirm_required,
            'confirm_reason': self.confirm_reason,
            'urgency_boost': self.urgency_boost,
            'urgency_reason': self.urgency_reason,
            'block': self.block,
            'block_reason': self.block_reason,
            'spoof_score': self.spoof_score,
            'fast_move_score': self.fast_move_score,
            'source_tf': self.source_tf,
        }


class MicrostructureTFModifier:
    """
    Modifies trading actions based on cross-TF microstructure signals.
    
    Rules:
    - OPEN/INCREASE with high spoof: reduce size, maybe delay
    - OPEN/INCREASE with fast-move: reduce size unless direction aligned
    - CLOSE/DECREASE: boost urgency if manipulation detected
    - Never block protective actions
    """
    
    def __init__(self, redis_client=None):
        self.redis = redis_client
        
        # Load thresholds from config
        from config import (
            MICRO_SPOOF_SCORE_REDUCE_THRESHOLD,
            MICRO_SPOOF_SCORE_BLOCK_THRESHOLD,
            MICRO_FAST_MOVE_REDUCE_THRESHOLD,
            MICRO_FAST_MOVE_BLOCK_THRESHOLD,
            MICRO_SIZE_MULTIPLIER_MIN,
        )
        
        self.spoof_reduce_threshold = MICRO_SPOOF_SCORE_REDUCE_THRESHOLD
        self.spoof_block_threshold = MICRO_SPOOF_SCORE_BLOCK_THRESHOLD
        self.fast_move_reduce_threshold = MICRO_FAST_MOVE_REDUCE_THRESHOLD
        self.fast_move_block_threshold = MICRO_FAST_MOVE_BLOCK_THRESHOLD
        self.size_multiplier_min = MICRO_SIZE_MULTIPLIER_MIN
        
        logger.info(f"[MICRO_MOD] Initialized: spoof_reduce={self.spoof_reduce_threshold}, "
                   f"fast_move_reduce={self.fast_move_reduce_threshold}")
    
    def get_micro_aggregate(self, symbol: str, tf: str) -> Optional[Dict[str, Any]]:
        """Get microstructure aggregate from Redis."""
        if not self.redis:
            return None
        
        try:
            key = f"microfeat:{symbol}:{tf}"
            data = self.redis.hgetall(key)
            if data:
                return {
                    (k.decode() if isinstance(k, bytes) else k): 
                    float(v.decode() if isinstance(v, bytes) else v) 
                    if k not in ('symbol', 'timeframe') else (v.decode() if isinstance(v, bytes) else v)
                    for k, v in data.items()
                }
            return None
        except Exception as e:
            logger.debug(f"[MICRO_MOD] Failed to get microfeat for {symbol}:{tf}: {e}")
            return None
    
    def is_entry_action(self, action: str) -> bool:
        """Check if action creates new exposure."""
        action_upper = str(action).upper()
        return any(tok in action_upper for tok in [
            'OPEN', 'INCREASE', 'ADD', 'FLIP', 'BUY', 'SELL'
        ]) and 'CLOSE' not in action_upper[:5]
    
    def is_protective_action(self, action: str) -> bool:
        """Check if action reduces exposure."""
        action_upper = str(action).upper()
        return any(tok in action_upper for tok in [
            'CLOSE', 'DECREASE', 'REDUCE', 'PARTIAL', 'EXIT', 'STOP_LOSS', 'TAKE_PROFIT'
        ])
    
    def modify_action(
        self,
        symbol: str,
        action: str,
        confidence: float,
        tf: str,
        position_side: Optional[str] = None,
    ) -> ModifierResult:
        """
        Apply microstructure-based modifications to a trading action.
        
        Args:
            symbol: Trading symbol
            action: Proposed action (OPEN_LONG, CLOSE_SHORT, etc.)
            confidence: Model confidence
            tf: Signal timeframe
            position_side: Current position side if any (LONG/SHORT)
            
        Returns:
            ModifierResult with size multiplier and control flags
        """
        result = ModifierResult(source_tf=tf)
        
        # Get microstructure data for 1m (highest resolution) and signal TF
        micro_1m = self.get_micro_aggregate(symbol, '1m')
        micro_tf = self.get_micro_aggregate(symbol, tf) if tf != '1m' else micro_1m
        
        # Use 1m for immediate signals, combine with signal TF for context
        if micro_1m:
            result.spoof_score = micro_1m.get('spoof_score_max', 0.0)
            result.fast_move_score = micro_1m.get('fast_move_score_max', 0.0)
        elif micro_tf:
            result.spoof_score = micro_tf.get('spoof_score_max', 0.0)
            result.fast_move_score = micro_tf.get('fast_move_score_max', 0.0)
        else:
            # No microstructure data available - pass through unchanged
            return result
        
        is_entry = self.is_entry_action(action)
        is_protective = self.is_protective_action(action)
        
        # === PROTECTIVE ACTIONS: Never block, may boost urgency ===
        if is_protective:
            # If manipulation detected, boost urgency for exits
            if result.spoof_score > self.spoof_reduce_threshold:
                result.urgency_boost = True
                result.urgency_reason = f"spoof_detected:{result.spoof_score:.2f}"
            elif result.fast_move_score > self.fast_move_reduce_threshold:
                result.urgency_boost = True
                result.urgency_reason = f"fast_move:{result.fast_move_score:.2f}"
            return result
        
        # === ENTRY ACTIONS: May reduce size, delay, or block ===
        if is_entry:
            # Spoof detection: reduce size proportionally
            if result.spoof_score >= self.spoof_block_threshold:
                # Extreme spoof - block
                result.block = True
                result.block_reason = f"MICRO_SPOOF_EXTREME:{result.spoof_score:.2f}"
                logger.warning(f"[MICRO_MOD] BLOCK {symbol} {action}: spoof={result.spoof_score:.2f}")
                return result
            
            elif result.spoof_score >= self.spoof_reduce_threshold:
                # Moderate spoof - reduce size
                # Linear interpolation: at reduce_threshold -> 1.0, at block_threshold -> min_multiplier
                range_span = self.spoof_block_threshold - self.spoof_reduce_threshold
                if range_span > 0:
                    reduction = (result.spoof_score - self.spoof_reduce_threshold) / range_span
                    result.size_multiplier = 1.0 - reduction * (1.0 - self.size_multiplier_min)
                else:
                    result.size_multiplier = self.size_multiplier_min
                
                result.delay_entry = True
                result.delay_reason = f"spoof_risk:{result.spoof_score:.2f}"
                logger.info(f"[MICRO_MOD] REDUCE {symbol} {action}: spoof={result.spoof_score:.2f} -> mult={result.size_multiplier:.2f}")
            
            # Fast-move detection
            if result.fast_move_score >= self.fast_move_block_threshold:
                # Extreme fast-move - block
                result.block = True
                result.block_reason = f"MICRO_FAST_MOVE_EXTREME:{result.fast_move_score:.2f}"
                logger.warning(f"[MICRO_MOD] BLOCK {symbol} {action}: fast_move={result.fast_move_score:.2f}")
                return result
            
            elif result.fast_move_score >= self.fast_move_reduce_threshold:
                # Moderate fast-move - reduce size
                range_span = self.fast_move_block_threshold - self.fast_move_reduce_threshold
                if range_span > 0:
                    reduction = (result.fast_move_score - self.fast_move_reduce_threshold) / range_span
                    fm_multiplier = 1.0 - reduction * (1.0 - self.size_multiplier_min)
                else:
                    fm_multiplier = self.size_multiplier_min
                
                # Take the more conservative multiplier
                result.size_multiplier = min(result.size_multiplier, fm_multiplier)
                result.confirm_required = True
                result.confirm_reason = f"fast_move_risk:{result.fast_move_score:.2f}"
                logger.info(f"[MICRO_MOD] REDUCE {symbol} {action}: fast_move={result.fast_move_score:.2f} -> mult={result.size_multiplier:.2f}")
            
            # If low confidence + any manipulation signal, require confirmation
            if confidence < 0.80 and (result.spoof_score > 0.3 or result.fast_move_score > 0.3):
                result.confirm_required = True
                result.confirm_reason = f"low_conf_manipulation:conf={confidence:.2f},spoof={result.spoof_score:.2f}"
        
        return result
    
    def apply_to_payload(self, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], ModifierResult]:
        """
        Apply modifications to a signal payload.
        
        Returns:
            (modified_payload, result)
        """
        symbol = payload.get('symbol', '')
        action = str(payload.get('action') or payload.get('action_name') or '').upper()
        confidence = float(payload.get('confidence', 0.5))
        tf = payload.get('timeframe') or payload.get('tf') or '5m'
        
        result = self.modify_action(symbol, action, confidence, tf)
        
        # Apply modifications to payload
        modified = dict(payload)
        
        if result.block:
            # Don't modify, caller should handle block
            return modified, result
        
        # Apply size multiplier
        if result.size_multiplier < 1.0:
            if 'margin_usd' in modified:
                modified['margin_usd'] = float(modified['margin_usd']) * result.size_multiplier
            if 'notional_usd' in modified:
                modified['notional_usd'] = float(modified['notional_usd']) * result.size_multiplier
            if 'position_size_pct' in modified:
                modified['position_size_pct'] = float(modified['position_size_pct']) * result.size_multiplier
            if 'recommended_position_pct' in modified:
                modified['recommended_position_pct'] = float(modified['recommended_position_pct']) * result.size_multiplier
            
            modified['micro_size_multiplier'] = result.size_multiplier
        
        # Add metadata
        modified['micro_modifier_applied'] = True
        if result.delay_entry:
            modified['micro_delay_entry'] = True
            modified['micro_delay_reason'] = result.delay_reason
        if result.confirm_required:
            modified['micro_confirm_required'] = True
            modified['micro_confirm_reason'] = result.confirm_reason
        if result.urgency_boost:
            modified['micro_urgency_boost'] = True
            modified['micro_urgency_reason'] = result.urgency_reason
        
        return modified, result


# Singleton instance
_modifier_instance: Optional[MicrostructureTFModifier] = None


def get_microstructure_modifier(redis_client=None) -> Optional[MicrostructureTFModifier]:
    """Get or create the microstructure modifier singleton."""
    global _modifier_instance
    
    from config import ENABLE_MICROSTRUCTURE_TF_MODIFIER
    if not ENABLE_MICROSTRUCTURE_TF_MODIFIER:
        return None
    
    if _modifier_instance is None:
        _modifier_instance = MicrostructureTFModifier(redis_client=redis_client)
    
    return _modifier_instance


def apply_micro_modifier(payload: Dict[str, Any], redis_client=None) -> Tuple[Dict[str, Any], Optional[ModifierResult]]:
    """
    Convenience function to apply microstructure modifications to a payload.
    
    Returns:
        (modified_payload, result) or (original_payload, None) if modifier disabled
    """
    modifier = get_microstructure_modifier(redis_client)
    if modifier is None:
        return payload, None
    
    return modifier.apply_to_payload(payload)

