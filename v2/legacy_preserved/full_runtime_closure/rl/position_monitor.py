"""
Dynamic Position Monitor for Trainer
Continuously monitors positions and generates dynamic stop/profit signals
Based on unified features (OHLCV, Coinank, TA-Lib, volatility, confidence, time, PnL)

ENHANCED with LIQUIDATION-AWARE PROFIT TAKING:
- Uses liquidation levels to protect profits
- Exits before adverse liquidation cascades
- Captures squeeze opportunities
- Ensures we stay in profit and don't lose equity
"""
import logging
import time
import json
import redis
import numpy as np
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

# Import liquidation-aware profit taker
try:
    from trading.adaptive_edge_gate import (
        LiquidationAwareProfitTaker, 
        MarketConditions,
        get_liq_profit_taker
    )
    LIQ_PROFIT_TAKER_AVAILABLE = True
except ImportError as e:
    logging.warning(f"LiquidationAwareProfitTaker not available: {e}")
    LIQ_PROFIT_TAKER_AVAILABLE = False

logger = logging.getLogger(__name__)


class DynamicPositionMonitor:
    """
    Monitor all open positions and dynamically calculate stop/profit levels
    Integrated into trainer for real-time feature-based decision making
    """
    
    def __init__(self, redis_client, binance_client=None, config=None):
        """
        Initialize position monitor
        
        Args:
            redis_client: Redis connection for reading unified features
            binance_client: Binance client for position data
            config: Main config object
        """
        self.redis = redis_client
        self.binance_client = binance_client
        self.config = config
        self.logger = logging.getLogger(__name__)  # Add logger instance
        
        # Monitoring state
        self.monitored_positions = {}  # symbol -> {side, entry_price, entry_time, etc}
        self.last_check_time = time.time()
        self.check_interval = 5.0  # Check every 5 seconds
        
        # Dynamic thresholds cache
        self.dynamic_thresholds = {}  # symbol:side -> {stop_loss, take_profit, trailing_stop}
        
        # Initialize liquidation-aware profit taker
        self.liq_profit_taker = None
        if LIQ_PROFIT_TAKER_AVAILABLE:
            try:
                self.liq_profit_taker = get_liq_profit_taker(redis_client=redis_client)
                logger.info("🎯 Liquidation-aware profit taker initialized")
            except Exception as e:
                logger.warning(f"⚠️ Could not initialize liquidation profit taker: {e}")
        
        logger.info("🎯 Dynamic Position Monitor initialized")
    
    def should_check_positions(self) -> bool:
        """Check if enough time has passed to monitor positions"""
        current_time = time.time()
        if current_time - self.last_check_time >= self.check_interval:
            self.last_check_time = current_time
            return True
        return False
    
    def sync_positions_from_binance(self) -> Dict[str, Any]:
        """
        Sync current positions from Binance
        Returns dict of positions keyed by symbol:side
        """
        if not self.binance_client:
            return {}
        
        try:
            positions = self.binance_client.futures_position_information()
            active_positions = {}
            
            for pos in positions:
                amt = float(pos['positionAmt'])
                if amt == 0:
                    continue
                
                # Debug: Log the position structure to understand what fields are available
                if len(active_positions) == 0:  # Only log first position to avoid spam
                    self.logger.debug(f"📊 Binance position structure: {list(pos.keys())}")
                
                symbol = pos['symbol']
                side = 'LONG' if amt > 0 else 'SHORT'
                entry_price = float(pos['entryPrice'])
                notional = abs(amt * entry_price)
                pnl = float(pos['unRealizedProfit'])
                
                # Handle missing leverage field gracefully
                leverage = 1.0  # Default fallback
                try:
                    leverage = float(pos['leverage'])
                except (KeyError, ValueError, TypeError):
                    # Leverage might be in a different field or missing
                    try:
                        # Check common alternative field names
                        leverage = float(pos.get('isolatedMargin', 1.0))
                    except:
                        self.logger.warning(f"⚠️ No leverage data for {symbol}, using default 1x")
                        leverage = 1.0
                
                # Ensure leverage is never zero to prevent division by zero
                if leverage <= 0:
                    leverage = 1.0
                
                pnl_pct = (pnl / (notional / leverage)) * 100 if notional > 0 and leverage > 0 else 0
                
                key = f"{symbol}:{side}"
                active_positions[key] = {
                    'symbol': symbol,
                    'side': side,
                    'size': abs(amt),
                    'entry_price': entry_price,
                    'mark_price': float(pos['markPrice']),
                    'notional': notional,
                    'leverage': leverage,  # Use the safely extracted leverage
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'liquidation_price': float(pos.get('liquidationPrice', 0))
                }
            
            return active_positions
        
        except Exception as e:
            logger.error(f"Error syncing positions from Binance: {e}")
            return {}
    
    def get_unified_features(self, symbol: str, timeframe: str = '5m') -> Dict[str, Any]:
        """
        Fetch unified features from Redis for a symbol
        
        Returns dict with OHLCV, Coinank, TA-Lib indicators, volatility, etc
        """
        try:
            feature_key = f"unified_features:{symbol}:{timeframe}"
            features = self.redis.hgetall(feature_key)
            
            if not features:
                return {}
            
            # Convert bytes to proper types
            parsed = {}
            for k, v in features.items():
                key = k.decode() if isinstance(k, bytes) else k
                value = v.decode() if isinstance(v, bytes) else v
                
                try:
                    # Try to parse as float
                    parsed[key] = float(value)
                except (ValueError, AttributeError):
                    parsed[key] = value
            
            return parsed
        
        except Exception as e:
            logger.error(f"Error fetching unified features for {symbol}:{timeframe}: {e}")
            return {}
    
    def calculate_dynamic_stop_loss(self, position: Dict, features: Dict, 
                                    confidence: float, time_held_hours: float) -> float:
        """
        Calculate dynamic stop loss based on multiple factors
        
        Args:
            position: Position data (entry_price, side, pnl_pct, etc)
            features: Unified features (volatility, indicators, etc)
            confidence: Original signal confidence
            time_held_hours: Hours since position opened
        
        Returns:
            stop_loss_pct: Stop loss percentage (e.g., 2.5 means 2.5% from entry)
        """
        # Base stop loss scales with confidence
        # TIGHTENED THRESHOLDS per updatedplan.md Section 2.2:
        # High confidence (≥95%) = tight stop (2.0%)
        # Medium confidence (85-95%) = normal stop (2.5%)
        # Lower confidence (75-85%) = wider stop (3.5%)
        
        if confidence >= 0.95:
            base_stop_pct = 2.0  # Tightened from 1.5% to 2.0%
        elif confidence >= 0.85:
            base_stop_pct = 2.5  # Keep at 2.5%
        else:
            base_stop_pct = 3.5  # Tightened from 4.0% to 3.5%
        
        # Adjust for volatility
        volatility = features.get('volatility_5m', 0.01)
        atr = features.get('atr_14', 0.0)
        
        # Higher volatility = wider stop
        volatility_mult = 1.0 + (volatility * 2.0)  # 0.02 vol = 1.04x, 0.05 vol = 1.10x
        
        # Adjust for time held - tighten stop as position ages
        # After 1 hour, start tightening
        if time_held_hours > 1.0:
            time_mult = max(0.7, 1.0 - (time_held_hours - 1.0) * 0.05)  # Tighten 5% per hour, min 70%
        else:
            time_mult = 1.0
        
        # Adjust for current PnL - if in profit, use trailing logic
        current_pnl_pct = position.get('pnl_pct', 0.0)
        if current_pnl_pct > base_stop_pct:
            # In profit beyond initial stop - use trailing stop at breakeven + buffer
            pnl_mult = 0.5  # Tighten to 50% of normal stop
        elif current_pnl_pct > 0:
            # Small profit - slightly tighter stop
            pnl_mult = 0.8
        elif current_pnl_pct < -base_stop_pct * 0.5:
            # Approaching stop - don't widen further
            pnl_mult = 1.0
        else:
            # Normal stop
            pnl_mult = 1.0
        
        # Final stop loss calculation
        dynamic_stop_pct = base_stop_pct * volatility_mult * time_mult * pnl_mult
        
        # Cap at reasonable limits: min 1.0%, max 5-6% as per document
        dynamic_stop_pct = max(1.0, min(dynamic_stop_pct, 6.0))  # Tightened from 8.0% to 6.0% max
        
        return dynamic_stop_pct
    
    def calculate_dynamic_take_profit(self, position: Dict, features: Dict,
                                      confidence: float, time_held_hours: float) -> float:
        """
        Calculate dynamic take profit based on multiple factors
        
        Returns:
            take_profit_pct: Take profit percentage
        """
        # Base take profit scales with confidence
        if confidence >= 0.95:
            base_tp_pct = 8.0  # High confidence = ambitious target
        elif confidence >= 0.90:
            base_tp_pct = 6.0
        elif confidence >= 0.85:
            base_tp_pct = 4.0
        else:
            base_tp_pct = 3.0
        
        # Adjust for momentum indicators
        rsi = features.get('rsi_14', 50.0)
        macd = features.get('macd', 0.0)
        adx = features.get('adx_14', 20.0)
        
        # Strong trend = wider target
        if adx > 30:
            trend_mult = 1.3
        elif adx > 25:
            trend_mult = 1.15
        else:
            trend_mult = 1.0
        
        # RSI extremes = take profit sooner
        side = position.get('side')
        if side == 'LONG' and rsi > 70:
            rsi_mult = 0.7  # Overbought, take profit earlier
        elif side == 'SHORT' and rsi < 30:
            rsi_mult = 0.7  # Oversold, take profit earlier
        else:
            rsi_mult = 1.0
        
        # Time decay - reduce target as position ages
        if time_held_hours > 4.0:
            time_mult = max(0.6, 1.0 - (time_held_hours - 4.0) * 0.05)
        else:
            time_mult = 1.0
        
        dynamic_tp_pct = base_tp_pct * trend_mult * rsi_mult * time_mult
        
        # Cap at reasonable limits
        dynamic_tp_pct = max(2.0, min(dynamic_tp_pct, 20.0))
        
        return dynamic_tp_pct
    
    def calculate_trailing_stop(self, position: Dict, features: Dict,
                                confidence: float) -> Optional[float]:
        """
        Calculate trailing stop percentage if position is in profit
        
        Returns:
            trailing_stop_pct: Trailing stop percentage, or None if not applicable
        """
        current_pnl_pct = position.get('pnl_pct', 0.0)
        
        # Only use trailing stop if in profit
        if current_pnl_pct <= 1.0:
            return None
        
        # Base trailing stop = confidence-based
        if confidence >= 0.95:
            base_trail_pct = 1.0  # Tight trailing for high confidence
        elif confidence >= 0.90:
            base_trail_pct = 1.5
        else:
            base_trail_pct = 2.0
        
        # Adjust for volatility
        volatility = features.get('volatility_5m', 0.01)
        vol_mult = 1.0 + volatility
        
        # Tighten trailing stop as profit increases
        if current_pnl_pct > 10.0:
            profit_mult = 0.5  # Very tight at 10%+ profit
        elif current_pnl_pct > 5.0:
            profit_mult = 0.7
        else:
            profit_mult = 1.0
        
        trailing_stop_pct = base_trail_pct * vol_mult * profit_mult
        
        # Cap at reasonable limits
        trailing_stop_pct = max(0.5, min(trailing_stop_pct, 3.0))
        
        return trailing_stop_pct
    
    def check_liquidation_based_profit_take(
        self,
        position: Dict,
        features: Dict,
        is_hedge: bool = False
    ) -> Optional[Dict]:
        """
        Check if position should be closed/reduced based on liquidation levels.
        
        This ensures we PROTECT PROFITS and don't give back gains to adverse
        liquidation cascades.
        
        Args:
            position: Position data with symbol, side, entry_price, etc.
            features: Unified features with liquidation data
            is_hedge: Whether this is a hedge position
        
        Returns:
            Signal dict if should take profit, None otherwise
        """
        if not self.liq_profit_taker:
            return None
        
        symbol = position.get('symbol')
        side = position.get('side')
        entry_price = position.get('entry_price', 0)
        current_price = position.get('current_price', 0)
        notional = position.get('notional', 500)
        
        if not all([symbol, side, entry_price, current_price]):
            return None
        
        try:
            # Build market conditions from features
            conditions = MarketConditions(
                symbol=symbol,
                current_price=current_price,
                atr_pct=features.get('atr_14', features.get('ind_atr_pct', 1.0)),
                momentum_score=features.get('momentum_score', 0.0),
                rsi=features.get('rsi_14', features.get('ind_rsi', 50.0)),
                liq_long_level=features.get('liquidation_long_level', 0.0),
                liq_short_level=features.get('liquidation_short_level', 0.0),
                liq_long_strength=features.get('liquidation_long_strength', 0.0),
                liq_short_strength=features.get('liquidation_short_strength', 0.0),
                liq_long_distance_pct=features.get('liquidation_long_distance_pct', 10.0),
                liq_short_distance_pct=features.get('liquidation_short_distance_pct', 10.0),
                liq_volume_long_1h=features.get('binance_liq_volume_long_usd', 0.0),
                liq_volume_short_1h=features.get('binance_liq_volume_short_usd', 0.0),
                liq_ratio=features.get('binance_liq_ratio', 1.0),
                squeeze_potential=features.get('squeeze_potential', 0.0)
            )
            
            # Analyze profit take
            decision = self.liq_profit_taker.analyze_profit_take(
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                current_price=current_price,
                position_size_usd=notional,
                conditions=conditions,
                is_hedge=is_hedge
            )
            
            if decision.should_take_profit:
                # Map urgency to confidence
                urgency_to_conf = {
                    'CRITICAL': 0.95,
                    'HIGH': 0.90,
                    'MEDIUM': 0.85,
                    'LOW': 0.80
                }
                
                # Determine action based on target_exit_pct
                if decision.target_exit_pct >= 75:
                    action = f'CLOSE_{side}'
                elif decision.target_exit_pct >= 50:
                    action = f'REDUCE_{side}_50'
                else:
                    action = f'REDUCE_{side}_25'
                
                return {
                    'action': action,
                    'reason': f'LIQ_PROFIT_TAKE: {decision.reason}',
                    'urgency': decision.urgency,
                    'confidence': urgency_to_conf.get(decision.urgency, 0.85),
                    'target_exit_pct': decision.target_exit_pct,
                    'pnl_pct': decision.pnl_pct,
                    'liquidation_context': decision.liquidation_context,
                    'squeeze_risk': decision.squeeze_risk
                }
            
        except Exception as e:
            logger.warning(f"⚠️ Liquidation profit check failed for {symbol}: {e}")
        
        return None

    def should_close_position(self, position: Dict, dynamic_thresholds: Dict,
                              current_price: float, features: Optional[Dict] = None) -> Optional[Dict]:
        """
        Determine if position should be closed based on dynamic thresholds
        
        NOW INCLUDES LIQUIDATION-AWARE PROFIT TAKING
        
        Returns:
            Signal dict if should close, None otherwise
        """
        symbol = position['symbol']
        side = position['side']
        entry_price = position['entry_price']
        pnl_pct = position['pnl_pct']
        
        stop_loss_pct = dynamic_thresholds['stop_loss_pct']
        take_profit_pct = dynamic_thresholds['take_profit_pct']
        trailing_stop_pct = dynamic_thresholds.get('trailing_stop_pct')
        
        # ========================================================================
        # PRIORITY 0: LIQUIDATION-AWARE PROFIT PROTECTION
        # Check this FIRST to ensure we protect profits before adverse cascades
        # ========================================================================
        if features and pnl_pct > 0:
            # Update position with current price for liq analysis
            position_with_price = {**position, 'current_price': current_price}
            is_hedge = position.get('is_hedge', False) or 'hedge' in symbol.lower()
            
            liq_signal = self.check_liquidation_based_profit_take(
                position=position_with_price,
                features=features,
                is_hedge=is_hedge
            )
            
            if liq_signal:
                logger.info(
                    f"🛡️ LIQ_PROFIT_PROTECT: {symbol} {side} | "
                    f"PnL={pnl_pct:.2f}% | {liq_signal['reason']}"
                )
                return liq_signal
        
        # Check stop loss
        if pnl_pct <= -stop_loss_pct:
            return {
                'action': f'CLOSE_{side}',
                'reason': f'DYNAMIC_STOP_LOSS: {pnl_pct:.2f}% <= -{stop_loss_pct:.2f}%',
                'urgency': 'HIGH',
                'confidence': 0.85  # Lower confidence for stop loss
            }
        
        # Check take profit
        if pnl_pct >= take_profit_pct:
            return {
                'action': f'CLOSE_{side}',
                'reason': f'DYNAMIC_TAKE_PROFIT: {pnl_pct:.2f}% >= {take_profit_pct:.2f}%',
                'urgency': 'MEDIUM',
                'confidence': 0.90
            }
        
        # Check trailing stop (if in profit)
        if trailing_stop_pct and pnl_pct > 1.0:
            # Calculate high water mark from entry
            if side == 'LONG':
                high_water_pct = ((current_price / entry_price) - 1.0) * 100
                drawdown_from_high = high_water_pct - pnl_pct
            else:  # SHORT
                high_water_pct = ((entry_price / current_price) - 1.0) * 100
                drawdown_from_high = high_water_pct - pnl_pct
            
            if drawdown_from_high >= trailing_stop_pct:
                return {
                    'action': f'CLOSE_{side}',
                    'reason': f'TRAILING_STOP: Drawdown {drawdown_from_high:.2f}% >= {trailing_stop_pct:.2f}%',
                    'urgency': 'MEDIUM',
                    'confidence': 0.88
                }
        
        return None
    
    def monitor_and_generate_signals(self) -> List[Dict]:
        """
        Main monitoring function - checks all positions and generates signals
        
        Returns:
            List of signal dicts to be published
        """
        if not self.should_check_positions():
            return []
        
        # Sync positions from Binance
        positions = self.sync_positions_from_binance()
        
        if not positions:
            return []
        
        signals = []
        
        for key, position in positions.items():
            symbol = position['symbol']
            side = position['side']
            
            try:
                # Get unified features for primary timeframe (5m)
                features_5m = self.get_unified_features(symbol, '5m')
                
                if not features_5m:
                    logger.warning(f"No features available for {symbol}:5m - skipping monitor")
                    continue
                
                # Get original signal confidence from Redis (or use default)
                signal_key = f"position_metadata:{symbol}:{side}"
                metadata = self.redis.hgetall(signal_key)
                
                if metadata:
                    confidence = float(metadata.get(b'confidence', b'0.85').decode())
                    entry_time = float(metadata.get(b'entry_time', time.time()).decode())
                else:
                    # Default values if no metadata
                    confidence = 0.85
                    entry_time = time.time()
                
                time_held_hours = (time.time() - entry_time) / 3600.0
                
                # Calculate dynamic thresholds
                stop_loss_pct = self.calculate_dynamic_stop_loss(
                    position, features_5m, confidence, time_held_hours
                )
                take_profit_pct = self.calculate_dynamic_take_profit(
                    position, features_5m, confidence, time_held_hours
                )
                trailing_stop_pct = self.calculate_trailing_stop(
                    position, features_5m, confidence
                )
                
                dynamic_thresholds = {
                    'stop_loss_pct': stop_loss_pct,
                    'take_profit_pct': take_profit_pct,
                    'trailing_stop_pct': trailing_stop_pct
                }
                
                # Cache thresholds
                self.dynamic_thresholds[key] = dynamic_thresholds
                
                # Log dynamic thresholds
                safe_trail = trailing_stop_pct if trailing_stop_pct is not None else 0.0
                logger.info(
                    f"📊 {symbol} {side}: Stop={stop_loss_pct:.2f}%, "
                    f"TP={take_profit_pct:.2f}%, Trail={safe_trail:.2f}%, "
                    f"PnL={position['pnl_pct']:.2f}%, Time={time_held_hours:.1f}h"
                )
                
                # Check if position should be closed
                # Now includes LIQUIDATION-AWARE PROFIT TAKING via features
                close_signal = self.should_close_position(
                    position, dynamic_thresholds, position['mark_price'], features=features_5m
                )
                
                if close_signal:
                    # Generate full signal payload
                    signal = {
                        'timestamp': time.time(),
                        'symbol': symbol,
                        'timeframe': '5m',  # Monitor based on 5m features
                        'action': close_signal['action'],
                        'confidence': close_signal['confidence'],
                        'reason': close_signal['reason'],
                        'urgency': close_signal['urgency'],
                        'source': 'dynamic_position_monitor',
                        'position_data': {
                            'entry_price': position['entry_price'],
                            'current_price': position['mark_price'],
                            'pnl_pct': position['pnl_pct'],
                            'time_held_hours': time_held_hours
                        },
                        'dynamic_thresholds': dynamic_thresholds
                    }
                    
                    signals.append(signal)
                    logger.warning(
                        f"🚨 DYNAMIC CLOSE SIGNAL: {symbol} {side} | "
                        f"{close_signal['reason']} | Confidence: {close_signal['confidence']:.2%}"
                    )
            
            except Exception as e:
                logger.error(f"Error monitoring {key}: {e}", exc_info=True)
                continue
        
        return signals
    
    def store_position_metadata(self, symbol: str, side: str, 
                                confidence: float, entry_time: float = None):
        """
        Store position metadata for later reference
        Called when a position is opened
        """
        if entry_time is None:
            entry_time = time.time()
        
        signal_key = f"position_metadata:{symbol}:{side}"
        self.redis.hset(signal_key, mapping={
            'confidence': confidence,
            'entry_time': entry_time,
            'symbol': symbol,
            'side': side
        })
        self.redis.expire(signal_key, 86400 * 7)  # Expire after 7 days
