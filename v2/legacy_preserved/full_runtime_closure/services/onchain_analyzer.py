"""
On-Chain Analytics Service
Provides blockchain metrics for trading model enhancement
"""
import os
import time
import logging
import requests
import numpy as np
from typing import Dict, Optional, List
from datetime import datetime, timedelta
import json
from redis import Redis

logger = logging.getLogger(__name__)


class OnChainAnalyzer:
    """
    On-chain data analyzer for cryptocurrency metrics.
    Integrates with Glassnode and Whale Alert APIs.
    """
    
    def __init__(self, redis_client: Optional[Redis] = None):
        """
        Initialize on-chain analyzer.
        
        Args:
            redis_client: Redis client for caching
        """
        self.glassnode_key = os.getenv('GLASSNODE_API_KEY', '')
        self.whale_alert_key = os.getenv('WHALE_ALERT_KEY', '')
        self.redis = redis_client
        
        # API endpoints
        self.glassnode_base = 'https://api.glassnode.com/v1/metrics'
        self.whale_alert_base = 'https://api.whale-alert.io/v1'
        
        # Cache TTL (1 hour for on-chain data)
        self.cache_ttl = 3600
        
        # Symbol mapping
        self.symbol_map = {
            'BTCUSDT': 'BTC',
            'ETHUSDT': 'ETH',
            'BTC': 'BTC',
            'ETH': 'ETH'
        }
        
        logger.info("OnChainAnalyzer initialized")
    
    def get_all_metrics(self, symbol: str) -> Dict[str, float]:
        """
        Get all on-chain metrics for a symbol.
        
        Args:
            symbol: Trading symbol (e.g., 'BTCUSDT')
            
        Returns:
            Dictionary of normalized on-chain features
        """
        # Check cache first
        cache_key = f'onchain:metrics:{symbol}:1h'
        if self.redis:
            cached = self.redis.get(cache_key)
            if cached:
                try:
                    return json.loads(cached)
                except:
                    pass
        
        # Fetch fresh metrics
        base_symbol = self.symbol_map.get(symbol, symbol.replace('USDT', ''))
        
        metrics = {}
        
        try:
            # Network Activity (3 features)
            metrics.update(self._get_network_activity(base_symbol))
            
            # Exchange Flows (4 features)
            metrics.update(self._get_exchange_flows(base_symbol))
            
            # Whale Activity (3 features)
            metrics.update(self._get_whale_metrics(base_symbol))
            
            # Holder Behavior (2 features)
            metrics.update(self._get_holder_metrics(base_symbol))
            
            # Miner Activity (2 features) - BTC only
            if base_symbol == 'BTC':
                metrics.update(self._get_miner_metrics(base_symbol))
            else:
                metrics['miner_balance_normalized'] = 0.5
                metrics['miner_outflow_normalized'] = 0.5
            
            # Supply Metrics (1 feature)
            metrics.update(self._get_supply_metrics(base_symbol))
            
            # Cache results
            if self.redis:
                self.redis.setex(cache_key, self.cache_ttl, json.dumps(metrics))
            
            logger.info(f"Fetched {len(metrics)} on-chain metrics for {symbol}")
            
        except Exception as e:
            logger.error(f"Error fetching on-chain metrics: {e}")
            # Return neutral values on error
            metrics = self._get_neutral_metrics()
        
        return metrics
    
    def _get_network_activity(self, symbol: str) -> Dict[str, float]:
        """Get network activity metrics."""
        metrics = {}
        
        try:
            # Active addresses (24h)
            active_addr = self._fetch_glassnode(
                'addresses/active_count',
                symbol
            )
            metrics['active_addresses_normalized'] = self._normalize(
                active_addr, 
                min_val=10000, 
                max_val=1000000
            )
            
            # Transaction count (24h)
            tx_count = self._fetch_glassnode(
                'transactions/count',
                symbol
            )
            metrics['transaction_count_normalized'] = self._normalize(
                tx_count,
                min_val=50000,
                max_val=500000
            )
            
            # Transaction volume (USD)
            tx_volume = self._fetch_glassnode(
                'transactions/transfers_volume_sum',
                symbol
            )
            metrics['transaction_volume_normalized'] = self._normalize(
                tx_volume,
                min_val=1e9,
                max_val=50e9
            )
            
        except Exception as e:
            logger.warning(f"Network activity fetch failed: {e}")
            metrics = {
                'active_addresses_normalized': 0.5,
                'transaction_count_normalized': 0.5,
                'transaction_volume_normalized': 0.5
            }
        
        return metrics
    
    def _get_exchange_flows(self, symbol: str) -> Dict[str, float]:
        """Get exchange flow metrics."""
        metrics = {}
        
        try:
            # Exchange inflow
            inflow = self._fetch_glassnode(
                'transactions/transfers_volume_to_exchanges_sum',
                symbol
            )
            
            # Exchange outflow
            outflow = self._fetch_glassnode(
                'transactions/transfers_volume_from_exchanges_sum',
                symbol
            )
            
            # Net flow (negative = accumulation, positive = distribution)
            net_flow = inflow - outflow if inflow and outflow else 0
            
            metrics['exchange_inflow_normalized'] = self._normalize(
                inflow,
                min_val=0,
                max_val=10e9
            )
            
            metrics['exchange_outflow_normalized'] = self._normalize(
                outflow,
                min_val=0,
                max_val=10e9
            )
            
            # Net flow: -1 (strong accumulation) to +1 (strong distribution)
            metrics['exchange_net_flow_normalized'] = np.tanh(net_flow / 5e9)
            
            # Exchange supply ratio
            exchange_balance = self._fetch_glassnode(
                'distribution/balance_exchanges',
                symbol
            )
            total_supply = self._fetch_glassnode(
                'supply/current',
                symbol
            )
            
            if exchange_balance and total_supply:
                ratio = exchange_balance / total_supply
                metrics['exchange_supply_ratio'] = min(ratio, 1.0)
            else:
                metrics['exchange_supply_ratio'] = 0.15  # Typical value
            
        except Exception as e:
            logger.warning(f"Exchange flows fetch failed: {e}")
            metrics = {
                'exchange_inflow_normalized': 0.5,
                'exchange_outflow_normalized': 0.5,
                'exchange_net_flow_normalized': 0.0,
                'exchange_supply_ratio': 0.15
            }
        
        return metrics
    
    def _get_whale_metrics(self, symbol: str) -> Dict[str, float]:
        """Get whale activity metrics."""
        metrics = {}
        
        try:
            if not self.whale_alert_key:
                raise ValueError("Whale Alert API key not configured")
            
            # Fetch large transactions (last 24h)
            url = f'{self.whale_alert_base}/transactions'
            params = {
                'api_key': self.whale_alert_key,
                'currency': symbol.lower(),
                'min_value': 100000,  # $100k minimum
                'start': int((datetime.now() - timedelta(hours=24)).timestamp()),
                'limit': 100
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                transactions = data.get('transactions', [])
                
                # Count whale transactions
                whale_count = len(transactions)
                
                # Total whale volume
                whale_volume = sum([tx.get('amount_usd', 0) for tx in transactions])
                
                # Whale exchange flow (to exchanges = bearish, from = bullish)
                to_exchange = sum([
                    tx.get('amount_usd', 0) 
                    for tx in transactions 
                    if tx.get('to', {}).get('owner_type') == 'exchange'
                ])
                from_exchange = sum([
                    tx.get('amount_usd', 0)
                    for tx in transactions
                    if tx.get('from', {}).get('owner_type') == 'exchange'
                ])
                
                metrics['whale_transaction_count_normalized'] = self._normalize(
                    whale_count,
                    min_val=0,
                    max_val=100
                )
                
                metrics['whale_volume_normalized'] = self._normalize(
                    whale_volume,
                    min_val=0,
                    max_val=10e9
                )
                
                # Whale exchange flow: -1 (accumulation) to +1 (distribution)
                net_whale_exchange = to_exchange - from_exchange
                metrics['whale_exchange_flow_normalized'] = np.tanh(net_whale_exchange / 1e9)
                
            else:
                raise ValueError(f"Whale Alert API error: {response.status_code}")
            
        except Exception as e:
            logger.warning(f"Whale metrics fetch failed: {e}")
            metrics = {
                'whale_transaction_count_normalized': 0.5,
                'whale_volume_normalized': 0.5,
                'whale_exchange_flow_normalized': 0.0
            }
        
        return metrics
    
    def _get_holder_metrics(self, symbol: str) -> Dict[str, float]:
        """Get holder behavior metrics."""
        metrics = {}
        
        try:
            # Long-term holder supply
            lth_supply = self._fetch_glassnode(
                'supply/long_term_holder',
                symbol
            )
            total_supply = self._fetch_glassnode(
                'supply/current',
                symbol
            )
            
            if lth_supply and total_supply:
                lth_ratio = lth_supply / total_supply
                metrics['long_term_holder_supply_ratio'] = min(lth_ratio, 1.0)
            else:
                metrics['long_term_holder_supply_ratio'] = 0.65  # Typical
            
            # Supply in profit
            profit_supply = self._fetch_glassnode(
                'supply/profit_relative',
                symbol
            )
            
            metrics['supply_in_profit_pct'] = profit_supply if profit_supply else 0.70
            
        except Exception as e:
            logger.warning(f"Holder metrics fetch failed: {e}")
            metrics = {
                'long_term_holder_supply_ratio': 0.65,
                'supply_in_profit_pct': 0.70
            }
        
        return metrics
    
    def _get_miner_metrics(self, symbol: str) -> Dict[str, float]:
        """Get miner activity metrics (BTC only)."""
        metrics = {}
        
        if symbol != 'BTC':
            return {
                'miner_balance_normalized': 0.5,
                'miner_outflow_normalized': 0.5
            }
        
        try:
            # Miner balance
            miner_balance = self._fetch_glassnode(
                'mining/miners_balance',
                symbol
            )
            
            metrics['miner_balance_normalized'] = self._normalize(
                miner_balance,
                min_val=1e6,
                max_val=3e6
            )
            
            # Miner outflow (selling pressure)
            miner_outflow = self._fetch_glassnode(
                'mining/miners_outflow_multiple',
                symbol
            )
            
            # Multiple > 2 = high selling pressure
            metrics['miner_outflow_normalized'] = self._normalize(
                miner_outflow,
                min_val=0,
                max_val=4
            )
            
        except Exception as e:
            logger.warning(f"Miner metrics fetch failed: {e}")
            metrics = {
                'miner_balance_normalized': 0.5,
                'miner_outflow_normalized': 0.5
            }
        
        return metrics
    
    def _get_supply_metrics(self, symbol: str) -> Dict[str, float]:
        """Get supply metrics."""
        metrics = {}
        
        try:
            # Illiquid supply (held by long-term holders)
            illiquid = self._fetch_glassnode(
                'supply/illiquid_sum',
                symbol
            )
            total_supply = self._fetch_glassnode(
                'supply/current',
                symbol
            )
            
            if illiquid and total_supply:
                illiquid_ratio = illiquid / total_supply
                metrics['illiquid_supply_ratio'] = min(illiquid_ratio, 1.0)
            else:
                metrics['illiquid_supply_ratio'] = 0.75  # Typical
            
        except Exception as e:
            logger.warning(f"Supply metrics fetch failed: {e}")
            metrics = {'illiquid_supply_ratio': 0.75}
        
        return metrics
    
    def _fetch_glassnode(self, endpoint: str, symbol: str) -> Optional[float]:
        """
        Fetch data from Glassnode API.
        
        Args:
            endpoint: API endpoint (e.g., 'addresses/active_count')
            symbol: Asset symbol (e.g., 'BTC')
            
        Returns:
            Latest value or None if error
        """
        if not self.glassnode_key:
            logger.warning("Glassnode API key not configured")
            return None
        
        try:
            url = f'{self.glassnode_base}/{endpoint}'
            params = {
                'a': symbol,
                'api_key': self.glassnode_key,
                's': int((datetime.now() - timedelta(days=1)).timestamp()),
                'i': '24h'
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data and len(data) > 0:
                    return float(data[-1]['v'])
            else:
                logger.warning(f"Glassnode API error {response.status_code} for {endpoint}")
            
        except Exception as e:
            logger.warning(f"Glassnode fetch error for {endpoint}: {e}")
        
        return None
    
    def _normalize(self, value: Optional[float], min_val: float, max_val: float) -> float:
        """
        Normalize value to [0, 1] range.
        
        Args:
            value: Value to normalize
            min_val: Minimum expected value
            max_val: Maximum expected value
            
        Returns:
            Normalized value between 0 and 1
        """
        if value is None:
            return 0.5  # Neutral value
        
        normalized = (value - min_val) / (max_val - min_val)
        return np.clip(normalized, 0.0, 1.0)
    
    def _get_neutral_metrics(self) -> Dict[str, float]:
        """Return neutral values for all metrics (fallback)."""
        return {
            # Network Activity
            'active_addresses_normalized': 0.5,
            'transaction_count_normalized': 0.5,
            'transaction_volume_normalized': 0.5,
            
            # Exchange Flows
            'exchange_inflow_normalized': 0.5,
            'exchange_outflow_normalized': 0.5,
            'exchange_net_flow_normalized': 0.0,
            'exchange_supply_ratio': 0.15,
            
            # Whale Activity
            'whale_transaction_count_normalized': 0.5,
            'whale_volume_normalized': 0.5,
            'whale_exchange_flow_normalized': 0.0,
            
            # Holder Behavior
            'long_term_holder_supply_ratio': 0.65,
            'supply_in_profit_pct': 0.70,
            
            # Miner Activity
            'miner_balance_normalized': 0.5,
            'miner_outflow_normalized': 0.5,
            
            # Supply Metrics
            'illiquid_supply_ratio': 0.75
        }
    
    def get_feature_vector(self, symbol: str) -> np.ndarray:
        """
        Get on-chain features as numpy array.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            15-dimensional feature vector
        """
        metrics = self.get_all_metrics(symbol)
        
        # Fixed order for consistency
        features = np.array([
            metrics['active_addresses_normalized'],
            metrics['transaction_count_normalized'],
            metrics['transaction_volume_normalized'],
            metrics['exchange_inflow_normalized'],
            metrics['exchange_outflow_normalized'],
            metrics['exchange_net_flow_normalized'],
            metrics['exchange_supply_ratio'],
            metrics['whale_transaction_count_normalized'],
            metrics['whale_volume_normalized'],
            metrics['whale_exchange_flow_normalized'],
            metrics['long_term_holder_supply_ratio'],
            metrics['supply_in_profit_pct'],
            metrics['miner_balance_normalized'],
            metrics['miner_outflow_normalized'],
            metrics['illiquid_supply_ratio']
        ], dtype=np.float32)
        
        return features
    
    def get_feature_names(self) -> List[str]:
        """Get ordered list of feature names."""
        return [
            'active_addresses_normalized',
            'transaction_count_normalized',
            'transaction_volume_normalized',
            'exchange_inflow_normalized',
            'exchange_outflow_normalized',
            'exchange_net_flow_normalized',
            'exchange_supply_ratio',
            'whale_transaction_count_normalized',
            'whale_volume_normalized',
            'whale_exchange_flow_normalized',
            'long_term_holder_supply_ratio',
            'supply_in_profit_pct',
            'miner_balance_normalized',
            'miner_outflow_normalized',
            'illiquid_supply_ratio'
        ]


if __name__ == '__main__':
    # Test the analyzer
    logging.basicConfig(level=logging.INFO)
    
    analyzer = OnChainAnalyzer()
    
    # Test BTC metrics
    print("Testing BTC on-chain metrics...")
    metrics = analyzer.get_all_metrics('BTCUSDT')
    print(f"\nBTC Metrics ({len(metrics)} features):")
    for key, value in metrics.items():
        print(f"  {key}: {value:.4f}")
    
    # Test feature vector
    features = analyzer.get_feature_vector('BTCUSDT')
    print(f"\nFeature vector shape: {features.shape}")
    print(f"Feature vector: {features}")
