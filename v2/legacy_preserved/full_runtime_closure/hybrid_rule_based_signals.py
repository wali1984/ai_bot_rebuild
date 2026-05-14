#!/usr/bin/env python3
"""
Hybrid Rule-Based Signal Generator
==================================
Generates intelligent trading signals using technical analysis while PPO model trains
Uses the same excellent feature data that shows 95% confidence
"""
import numpy as np
import redis
import json
import time
from typing import Dict, Optional, Tuple, Any
from datetime import datetime

class HybridRuleBasedSignalGenerator:
    def __init__(self):
        self.redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)
        
        # Signal generation thresholds (relaxed for testing hybrid mode)
        self.thresholds = {
            '1m': {'min_confidence': 0.45, 'rsi_oversold': 45, 'rsi_overbought': 55},
            '5m': {'min_confidence': 0.40, 'rsi_oversold': 45, 'rsi_overbought': 55},
            '15m': {'min_confidence': 0.35, 'rsi_oversold': 48, 'rsi_overbought': 52},
            '1h': {'min_confidence': 0.30, 'rsi_oversold': 48, 'rsi_overbought': 52},
            '4h': {'min_confidence': 0.25, 'rsi_oversold': 49, 'rsi_overbought': 51}
        }
        
        # Multi-timeframe weights for signal confirmation
        self.tf_weights = {
            '1m': 0.15,
            '5m': 0.20,
            '15m': 0.25,
            '1h': 0.25,
            '4h': 0.15
        }
    
    def generate_rule_based_signal(self, symbol: str, timeframe: str, features: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Generate intelligent rule-based trading signal"""
        try:
            # Extract key technical indicators from features
            indicators = self._extract_indicators(features)
            if not indicators:
                return None
            
            # Calculate rule-based confidence
            confidence = self._calculate_rule_confidence(indicators, timeframe)
            
            # Check minimum confidence threshold
            min_conf = self.thresholds[timeframe]['min_confidence']
            if confidence < min_conf:
                return None
            
            # Generate primary signal
            primary_signal = self._generate_primary_signal(indicators, timeframe)
            
            # Add multi-timeframe confirmation
            mtf_confirmation = self._get_multi_timeframe_confirmation(symbol, indicators)
            
            # Calculate final action and confidence
            final_action, final_confidence = self._combine_signals(
                primary_signal, mtf_confirmation, confidence
            )
            
            if final_action == 'HOLD':
                return None  # Don't generate HOLD signals
            
            # Create comprehensive signal payload with new action format
            action_code = 1 if final_action == 'LONG' else 2 if final_action == 'SHORT' else 0
            action_name = f"OPEN_{final_action}" if final_action in ['LONG', 'SHORT'] else final_action
            
            signal_payload = {
                "timestamp": time.time(),
                "ts_ms": int(time.time() * 1000),
                "symbol": symbol,
                "timeframe": timeframe,
                "action": action_code,
                "action_name": action_name,
                "model_confidence": float(final_confidence),
                
                # Rule-based specific fields
                "signal_source": "rule_based_hybrid",
                "rule_confidence": float(confidence),
                "primary_signal": primary_signal['action'],
                "primary_reason": primary_signal['reason'],
                "mtf_confirmation": mtf_confirmation,
                
                # Technical indicator values
                "indicators": {
                    "rsi": indicators.get('rsi', 50),
                    "macd_signal": indicators.get('macd_signal', 0),
                    "bb_position": indicators.get('bb_position', 0.5),
                    "ema_trend": indicators.get('ema_trend', 0),
                    "volume_surge": indicators.get('volume_surge', False)
                },
                
                # Trading parameters (conservative for rule-based)
                "recommended_leverage": self._calculate_rule_leverage(final_confidence, timeframe),
                "recommended_position_pct": self._calculate_rule_position_size(final_confidence, timeframe),
                "risk_score": float(1.0 - final_confidence),  # Lower confidence = higher risk
                "expected_hold_time": self._estimate_rule_hold_time(timeframe),
                
                # Trading configuration
                "hedge_mode": True,
                "margin_mode": "cross",
                "position_side": "BOTH",
                
                # Metadata
                "model": "rule_based_hybrid_v1",
                "reasoning": self._generate_rule_reasoning(primary_signal, mtf_confirmation, indicators)
            }
            
            return signal_payload
            
        except Exception as e:
            print(f"❌ Rule-based signal generation failed for {symbol}:{timeframe}: {e}")
            return None
    
    def _extract_indicators(self, features: Dict[str, str]) -> Dict[str, float]:
        """Extract key technical indicators from feature data"""
        indicators = {}
        
        try:
            # RSI (Relative Strength Index)
            rsi_keys = [k for k in features.keys() if 'rsi' in k.lower() and 'ta_RSI_14' in k]
            if rsi_keys:
                indicators['rsi'] = float(features[rsi_keys[0]])
            
            # MACD
            macd_keys = [k for k in features.keys() if 'macd' in k.lower() and not 'signal' in k.lower()]
            macd_signal_keys = [k for k in features.keys() if 'macd' in k.lower() and 'signal' in k.lower()]
            
            if macd_keys and macd_signal_keys:
                macd = float(features[macd_keys[0]])
                macd_signal = float(features[macd_signal_keys[0]])
                indicators['macd'] = macd
                indicators['macd_signal'] = macd_signal
                indicators['macd_histogram'] = macd - macd_signal
            
            # Bollinger Bands
            bb_upper_keys = [k for k in features.keys() if 'bb_upper' in k.lower() or 'BBANDS_upper' in k]
            bb_lower_keys = [k for k in features.keys() if 'bb_lower' in k.lower() or 'BBANDS_lower' in k]
            close_keys = [k for k in features.keys() if k.endswith('_close') or 'close' in k.lower()]
            
            if bb_upper_keys and bb_lower_keys and close_keys:
                bb_upper = float(features[bb_upper_keys[0]])
                bb_lower = float(features[bb_lower_keys[0]])
                close = float(features[close_keys[0]])
                
                # BB position: 0 = at lower band, 1 = at upper band, 0.5 = middle
                bb_range = bb_upper - bb_lower
                if bb_range > 0:
                    indicators['bb_position'] = (close - bb_lower) / bb_range
                else:
                    indicators['bb_position'] = 0.5
            
            # EMA trend (compare EMAs of different periods)
            ema_12_keys = [k for k in features.keys() if 'ema_12' in k.lower() or 'EMA_12' in k]
            ema_26_keys = [k for k in features.keys() if 'ema_26' in k.lower() or 'EMA_26' in k]
            
            if ema_12_keys and ema_26_keys:
                ema_12 = float(features[ema_12_keys[0]])
                ema_26 = float(features[ema_26_keys[0]])
                indicators['ema_trend'] = (ema_12 - ema_26) / ema_26  # Percentage difference
            
            # Volume surge detection
            volume_keys = [k for k in features.keys() if 'volume' in k.lower()]
            if volume_keys:
                current_volume = float(features[volume_keys[0]])
                # Simple volume surge: if current volume is in top 20% of recent values
                indicators['volume_surge'] = current_volume > 0  # Placeholder logic
            
            # Price momentum
            close_keys = [k for k in features.keys() if k.endswith('_close')]
            if close_keys and len(close_keys) > 1:
                current_close = float(features[close_keys[0]])
                # Look for price change indicators
                change_keys = [k for k in features.keys() if 'change' in k.lower() or 'return' in k.lower()]
                if change_keys:
                    price_change = float(features[change_keys[0]])
                    indicators['price_momentum'] = price_change
            
            return indicators
            
        except Exception as e:
            print(f"⚠️ Indicator extraction failed: {e}")
            return {}
    
    def _calculate_rule_confidence(self, indicators: Dict[str, float], timeframe: str) -> float:
        """Calculate confidence based on indicator alignment"""
        confidence_factors = []
        
        # RSI confidence
        rsi = indicators.get('rsi', 50)
        if rsi < 30 or rsi > 70:  # Strong oversold/overbought
            confidence_factors.append(0.9)
        elif rsi < 40 or rsi > 60:  # Moderate levels  
            confidence_factors.append(0.7)
        else:
            confidence_factors.append(0.5)
        
        # MACD confidence
        if 'macd_histogram' in indicators:
            macd_hist = indicators['macd_histogram']
            if abs(macd_hist) > 0.001:  # Strong MACD signal
                confidence_factors.append(0.85)
            else:
                confidence_factors.append(0.6)
        
        # Bollinger Band confidence
        bb_pos = indicators.get('bb_position', 0.5)
        if bb_pos < 0.1 or bb_pos > 0.9:  # Near bands
            confidence_factors.append(0.8)
        elif bb_pos < 0.3 or bb_pos > 0.7:
            confidence_factors.append(0.7)
        else:
            confidence_factors.append(0.5)
        
        # EMA trend confidence
        ema_trend = indicators.get('ema_trend', 0)
        if abs(ema_trend) > 0.02:  # Strong trend
            confidence_factors.append(0.8)
        elif abs(ema_trend) > 0.01:
            confidence_factors.append(0.7)
        else:
            confidence_factors.append(0.5)
        
        # Volume confirmation
        if indicators.get('volume_surge', False):
            confidence_factors.append(0.85)
        else:
            confidence_factors.append(0.6)
        
        # Calculate weighted average confidence
        if confidence_factors:
            return np.mean(confidence_factors)
        return 0.5
    
    def _generate_primary_signal(self, indicators: Dict[str, float], timeframe: str) -> Dict[str, Any]:
        """Generate primary trading signal based on indicators"""
        signals = []
        reasons = []
        
        # RSI signal
        rsi = indicators.get('rsi', 50)
        rsi_oversold = self.thresholds[timeframe]['rsi_oversold']
        rsi_overbought = self.thresholds[timeframe]['rsi_overbought']
        
        if rsi < rsi_oversold:
            signals.append('LONG')
            reasons.append(f'RSI oversold ({rsi:.1f})')
        elif rsi > rsi_overbought:
            signals.append('SHORT')
            reasons.append(f'RSI overbought ({rsi:.1f})')
        
        # MACD signal
        if 'macd_histogram' in indicators:
            macd_hist = indicators['macd_histogram']
            if macd_hist > 0.001:
                signals.append('LONG')
                reasons.append('MACD bullish crossover')
            elif macd_hist < -0.001:
                signals.append('SHORT')
                reasons.append('MACD bearish crossover')
        
        # Bollinger Band signal
        bb_pos = indicators.get('bb_position', 0.5)
        if bb_pos < 0.1:  # Near lower band
            signals.append('LONG')
            reasons.append('BB oversold')
        elif bb_pos > 0.9:  # Near upper band
            signals.append('SHORT')
            reasons.append('BB overbought')
        
        # EMA trend signal
        ema_trend = indicators.get('ema_trend', 0)
        if ema_trend > 0.01:
            signals.append('LONG')
            reasons.append('EMA bullish trend')
        elif ema_trend < -0.01:
            signals.append('SHORT')
            reasons.append('EMA bearish trend')
        
        # Determine primary signal by majority vote
        if signals:
            long_votes = signals.count('LONG')
            short_votes = signals.count('SHORT')
            
            if long_votes > short_votes:
                return {'action': 'LONG', 'reason': ', '.join(reasons)}
            elif short_votes > long_votes:
                return {'action': 'SHORT', 'reason': ', '.join(reasons)}
            else:
                return {'action': 'HOLD', 'reason': 'Mixed signals'}
        
        return {'action': 'HOLD', 'reason': 'No clear signals'}
    
    def _get_multi_timeframe_confirmation(self, symbol: str, current_indicators: Dict[str, float]) -> float:
        """Get multi-timeframe confirmation score"""
        try:
            timeframes = ['1m', '5m', '15m', '1h', '4h']
            confirmation_scores = []
            
            for tf in timeframes:
                try:
                    # Get features for this timeframe
                    feature_key = f'unified_features:{symbol}:{tf}'
                    features = self.redis_client.hgetall(feature_key)
                    
                    if features:
                        indicators = self._extract_indicators(features)
                        if indicators:
                            # Simple trend alignment check
                            ema_trend = indicators.get('ema_trend', 0)
                            current_ema_trend = current_indicators.get('ema_trend', 0)
                            
                            # Same direction trends get positive score
                            if (ema_trend > 0 and current_ema_trend > 0) or \
                               (ema_trend < 0 and current_ema_trend < 0):
                                confirmation_scores.append(self.tf_weights[tf])
                            else:
                                confirmation_scores.append(-self.tf_weights[tf])
                
                except Exception as e:
                    continue
            
            # Return average confirmation score
            if confirmation_scores:
                return np.mean(confirmation_scores)
            return 0.0
            
        except Exception as e:
            return 0.0
    
    def _combine_signals(self, primary_signal: Dict[str, Any], mtf_confirmation: float, 
                        base_confidence: float) -> Tuple[str, float]:
        """Combine primary signal with multi-timeframe confirmation"""
        
        action = primary_signal['action']
        
        # Adjust confidence based on multi-timeframe confirmation
        confirmation_boost = abs(mtf_confirmation) * 0.2  # Up to 20% boost
        final_confidence = min(0.95, base_confidence + confirmation_boost)
        
        # If confirmation contradicts primary signal, reduce confidence
        if ((action == 'LONG' and mtf_confirmation < -0.1) or 
            (action == 'SHORT' and mtf_confirmation > 0.1)):
            final_confidence *= 0.7  # Reduce confidence by 30%
        
        return action, final_confidence
    
    def _calculate_rule_leverage(self, confidence: float, timeframe: str) -> int:
        """Calculate conservative leverage for rule-based signals"""
        base_leverage = {
            '1m': 3,   # Lower leverage for scalping
            '5m': 5,   # Moderate leverage
            '15m': 8,  # Higher leverage for swing
            '1h': 10,  # Position trades
            '4h': 12   # Long-term positions
        }
        
        # Adjust based on confidence
        leverage = int(base_leverage[timeframe] * confidence)
        return max(1, min(leverage, 15))  # Cap at 15x
    
    def _calculate_rule_position_size(self, confidence: float, timeframe: str) -> float:
        """Calculate position size percentage"""
        base_size = {
            '1m': 15.0,  # Smaller positions for scalping
            '5m': 20.0,
            '15m': 25.0,
            '1h': 30.0,
            '4h': 35.0   # Larger for long-term
        }
        
        # Adjust based on confidence
        size = base_size[timeframe] * confidence
        return max(5.0, min(size, 50.0))  # 5-50% range
    
    def _estimate_rule_hold_time(self, timeframe: str) -> str:
        """Estimate expected hold time"""
        hold_times = {
            '1m': '5-15 minutes',
            '5m': '30-60 minutes', 
            '15m': '2-4 hours',
            '1h': '8-24 hours',
            '4h': '1-3 days'
        }
        return hold_times.get(timeframe, '1-4 hours')
    
    def _generate_rule_reasoning(self, primary_signal: Dict[str, Any], 
                                mtf_confirmation: float, indicators: Dict[str, float]) -> str:
        """Generate human-readable reasoning for the signal"""
        
        reason_parts = [
            f"Rule-based signal: {primary_signal['action']}",
            f"Primary reason: {primary_signal['reason']}"
        ]
        
        # Add indicator details
        if 'rsi' in indicators:
            reason_parts.append(f"RSI: {indicators['rsi']:.1f}")
        
        if 'bb_position' in indicators:
            bb_pos = indicators['bb_position']
            if bb_pos < 0.2:
                reason_parts.append("Near BB lower band")
            elif bb_pos > 0.8:
                reason_parts.append("Near BB upper band")
        
        # Multi-timeframe confirmation
        if mtf_confirmation > 0.1:
            reason_parts.append("MTF confirmation: Bullish")
        elif mtf_confirmation < -0.1:
            reason_parts.append("MTF confirmation: Bearish")
        else:
            reason_parts.append("MTF confirmation: Neutral")
        
        return " | ".join(reason_parts)

if __name__ == "__main__":
    # Test the rule-based signal generator
    generator = HybridRuleBasedSignalGenerator()
    
    # Test with BTCUSDT 15m
    redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)
    features = redis_client.hgetall('unified_features:BTCUSDT:15m')
    
    if features:
        signal = generator.generate_rule_based_signal('BTCUSDT', '15m', features)
        if signal:
            print(f"Generated signal: {signal['action_name']} with {signal['model_confidence']:.2f} confidence")
            print(f"Reasoning: {signal['reasoning']}")
        else:
            print("No signal generated (below threshold)")
    else:
        print("No feature data available")