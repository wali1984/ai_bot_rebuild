"""
Unified Feature Tensor Builder
Combines all data sources into standardized feature tensors per (symbol, timeframe)
"""

import asyncio
import logging
import numpy as np
import torch
from typing import Dict, List, Optional, Tuple, Set, Union
from dataclasses import dataclass
from enum import Enum
import time
import json
from collections import defaultdict

logger = logging.getLogger(__name__)


class DataSource(Enum):
    """Available data sources for feature extraction"""
    BINANCE_KLINES = "binance_klines"
    BINANCE_ORDERBOOK = "binance_orderbook"
    CCXT_OHLCV = "ccxt_ohlcv"
    LIQUIDATIONS = "liquidations"
    TECHNICAL_ANALYSIS = "technical_analysis"
    TOKEN_METRICS = "token_metrics"
    COINANK = "coinank"
    PORTFOLIO_STATE = "portfolio_state"


@dataclass
class FeatureDimensions:
    """Feature tensor dimensions for each data source"""
    binance_klines: int = 20      # OHLCV + volume metrics
    binance_orderbook: int = 15   # Bid/ask spreads, depth, imbalance
    ccxt_ohlcv: int = 10         # Alternative exchange data
    liquidations: int = 12        # Liquidation volume, direction, intensity
    technical_analysis: int = 25  # RSI, MACD, Bollinger, etc.
    token_metrics: int = 18       # On-chain metrics, sentiment
    coinank: int = 22            # Funding rates, OI, exchange flows
    portfolio_state: int = 15     # Position info, PnL, exposure
    
    @property
    def total_features(self) -> int:
        """Total feature count across all sources"""
        return (
            self.binance_klines + self.binance_orderbook + self.ccxt_ohlcv +
            self.liquidations + self.technical_analysis + self.token_metrics +
            self.coinank + self.portfolio_state
        )


@dataclass 
class UnifiedFeatureVector:
    """Complete feature vector for (symbol, timeframe, timestamp)"""
    symbol: str
    timeframe: str
    timestamp: float
    features: torch.Tensor  # [total_features] tensor
    source_mask: torch.Tensor  # [num_sources] availability mask
    feature_age: Dict[str, float]  # seconds since last update per source
    quality_score: float  # 0.0-1.0 overall data quality


class UnifiedFeatureTensorBuilder:
    """
    Builds unified feature tensors from all ingested data sources.
    
    Features:
    - Standardized tensor format per (symbol, timeframe)
    - Source availability masking for missing data
    - Feature age tracking for staleness detection
    - Quality scoring for data reliability
    - GPU-optimized tensor operations
    """
    
    def __init__(
        self,
        feature_dims: FeatureDimensions = None,
        max_feature_age_seconds: float = 300.0,  # 5 minutes
        quality_decay_rate: float = 0.1,
        device: str = "cuda" if torch.cuda.is_available() else "cpu",
        cache_size: int = 1000
    ):
        """
        Initialize unified feature tensor builder.
        
        Args:
            feature_dims: Feature dimensions configuration
            max_feature_age_seconds: Max age before features considered stale
            quality_decay_rate: Rate at which quality decays with age
            device: PyTorch device for tensor operations
            cache_size: Number of feature vectors to cache
        """
        self.feature_dims = feature_dims or FeatureDimensions()
        self.max_feature_age = max_feature_age_seconds
        self.quality_decay_rate = quality_decay_rate
        self.device = torch.device(device)
        self.cache_size = cache_size
        
        # Feature tensor cache
        self.feature_cache: Dict[Tuple[str, str], UnifiedFeatureVector] = {}
        self.cache_timestamps: Dict[Tuple[str, str], float] = {}
        
        # Data source processors
        self.source_processors = {
            DataSource.BINANCE_KLINES: self._process_binance_klines,
            DataSource.BINANCE_ORDERBOOK: self._process_binance_orderbook,
            DataSource.CCXT_OHLCV: self._process_ccxt_ohlcv,
            DataSource.LIQUIDATIONS: self._process_liquidations,
            DataSource.TECHNICAL_ANALYSIS: self._process_technical_analysis,
            DataSource.TOKEN_METRICS: self._process_token_metrics,
            DataSource.COINANK: self._process_coinank,
            DataSource.PORTFOLIO_STATE: self._process_portfolio_state
        }
        
        logger.info(f"UnifiedFeatureTensorBuilder initialized: {self.feature_dims.total_features} features on {device}")
    
    async def build_unified_tensor(
        self,
        symbol: str,
        timeframe: str,
        raw_data: Dict[str, any] = None,
        force_rebuild: bool = False
    ) -> UnifiedFeatureVector:
        """
        Build unified feature tensor for (symbol, timeframe).
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe (1m, 5m, 15m, 1h, 4h, 1d)
            raw_data: Raw data from all sources (if available)
            force_rebuild: Force rebuild even if cached
            
        Returns:
            UnifiedFeatureVector with complete feature tensor
        """
        cache_key = (symbol, timeframe)
        current_time = time.time()
        
        # Check cache first
        if not force_rebuild and cache_key in self.feature_cache:
            cached_vector = self.feature_cache[cache_key]
            cache_age = current_time - self.cache_timestamps[cache_key]
            
            if cache_age < self.max_feature_age:
                return cached_vector
        
        # Build feature tensor from scratch
        feature_vector = await self._build_feature_vector(
            symbol, timeframe, raw_data, current_time
        )
        
        # Update cache
        self._update_cache(cache_key, feature_vector, current_time)
        
        return feature_vector
    
    async def build_batch_tensors(
        self,
        symbols: List[str],
        timeframes: List[str],
        raw_data_batch: Dict[Tuple[str, str], Dict] = None
    ) -> Dict[Tuple[str, str], UnifiedFeatureVector]:
        """
        Build unified tensors for multiple (symbol, timeframe) pairs.
        
        Args:
            symbols: List of trading symbols
            timeframes: List of timeframes
            raw_data_batch: Batch of raw data keyed by (symbol, timeframe)
            
        Returns:
            Dictionary of unified feature vectors
        """
        tasks = []
        
        for symbol in symbols:
            for timeframe in timeframes:
                cache_key = (symbol, timeframe)
                raw_data = raw_data_batch.get(cache_key) if raw_data_batch else None
                
                task = self.build_unified_tensor(symbol, timeframe, raw_data)
                tasks.append((cache_key, task))
        
        # Execute all tasks concurrently
        results = {}
        for cache_key, task in tasks:
            try:
                feature_vector = await task
                results[cache_key] = feature_vector
            except Exception as e:
                logger.error(f"Failed to build tensor for {cache_key}: {e}")
                # Create fallback tensor with zeros
                results[cache_key] = self._create_fallback_tensor(cache_key[0], cache_key[1])
        
        return results
    
    def get_feature_tensor_batch(
        self,
        feature_vectors: List[UnifiedFeatureVector]
    ) -> torch.Tensor:
        """
        Convert list of feature vectors to batched tensor.
        
        Args:
            feature_vectors: List of unified feature vectors
            
        Returns:
            Batched tensor [batch_size, total_features]
        """
        if not feature_vectors:
            return torch.zeros((0, self.feature_dims.total_features), device=self.device)
        
        feature_tensors = [fv.features for fv in feature_vectors]
        return torch.stack(feature_tensors, dim=0).to(self.device)
    
    def get_source_availability_matrix(
        self,
        feature_vectors: List[UnifiedFeatureVector]
    ) -> torch.Tensor:
        """
        Get source availability matrix for batch.
        
        Args:
            feature_vectors: List of unified feature vectors
            
        Returns:
            Source availability tensor [batch_size, num_sources]
        """
        if not feature_vectors:
            return torch.zeros((0, len(DataSource)), device=self.device)
        
        availability_tensors = [fv.source_mask for fv in feature_vectors]
        return torch.stack(availability_tensors, dim=0).to(self.device)
    
    async def _build_feature_vector(
        self,
        symbol: str,
        timeframe: str,
        raw_data: Dict[str, any],
        timestamp: float
    ) -> UnifiedFeatureVector:
        """Build unified feature vector from all data sources"""
        
        # Initialize feature components
        feature_components = {}
        source_mask = torch.zeros(len(DataSource), device=self.device)
        feature_ages = {}
        
        # Process each data source
        for i, source in enumerate(DataSource):
            try:
                processor = self.source_processors[source]
                source_data = raw_data.get(source.value) if raw_data else None
                
                features, age = await processor(symbol, timeframe, source_data, timestamp)
                
                if features is not None:
                    feature_components[source.value] = features
                    source_mask[i] = 1.0
                    feature_ages[source.value] = age
                else:
                    # Use zero features for missing data
                    feature_dim = getattr(self.feature_dims, source.value.replace('_', '_'))
                    if source.value == 'binance_klines':
                        feature_dim = self.feature_dims.binance_klines
                    elif source.value == 'binance_orderbook':
                        feature_dim = self.feature_dims.binance_orderbook
                    elif source.value == 'ccxt_ohlcv':
                        feature_dim = self.feature_dims.ccxt_ohlcv
                    elif source.value == 'liquidations':
                        feature_dim = self.feature_dims.liquidations
                    elif source.value == 'technical_analysis':
                        feature_dim = self.feature_dims.technical_analysis
                    elif source.value == 'token_metrics':
                        feature_dim = self.feature_dims.token_metrics
                    elif source.value == 'coinank':
                        feature_dim = self.feature_dims.coinank
                    elif source.value == 'portfolio_state':
                        feature_dim = self.feature_dims.portfolio_state
                    
                    feature_components[source.value] = torch.zeros(feature_dim, device=self.device)
                    feature_ages[source.value] = self.max_feature_age
            
            except Exception as e:
                logger.error(f"Error processing {source.value} for {symbol}/{timeframe}: {e}")
                # Fill with zeros on error
                feature_dim = self._get_source_dimension(source)
                feature_components[source.value] = torch.zeros(feature_dim, device=self.device)
                feature_ages[source.value] = self.max_feature_age
        
        # Concatenate all features
        feature_tensors = [
            feature_components['binance_klines'],
            feature_components['binance_orderbook'], 
            feature_components['ccxt_ohlcv'],
            feature_components['liquidations'],
            feature_components['technical_analysis'],
            feature_components['token_metrics'],
            feature_components['coinank'],
            feature_components['portfolio_state']
        ]
        
        unified_features = torch.cat(feature_tensors, dim=0)
        
        # Calculate quality score
        quality_score = self._calculate_quality_score(feature_ages, source_mask)
        
        return UnifiedFeatureVector(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=timestamp,
            features=unified_features,
            source_mask=source_mask,
            feature_age=feature_ages,
            quality_score=quality_score
        )
    
    def _get_source_dimension(self, source: DataSource) -> int:
        """Get feature dimension for a data source"""
        source_dims = {
            DataSource.BINANCE_KLINES: self.feature_dims.binance_klines,
            DataSource.BINANCE_ORDERBOOK: self.feature_dims.binance_orderbook,
            DataSource.CCXT_OHLCV: self.feature_dims.ccxt_ohlcv,
            DataSource.LIQUIDATIONS: self.feature_dims.liquidations,
            DataSource.TECHNICAL_ANALYSIS: self.feature_dims.technical_analysis,
            DataSource.TOKEN_METRICS: self.feature_dims.token_metrics,
            DataSource.COINANK: self.feature_dims.coinank,
            DataSource.PORTFOLIO_STATE: self.feature_dims.portfolio_state
        }
        return source_dims[source]
    
    async def _process_binance_klines(
        self, symbol: str, timeframe: str, data: any, timestamp: float
    ) -> Tuple[Optional[torch.Tensor], float]:
        """Process Binance kline data into features"""
        if data is None:
            return None, self.max_feature_age
        
        try:
            # Extract OHLCV + derived features
            features = [
                data.get('open', 0), data.get('high', 0), data.get('low', 0), data.get('close', 0),
                data.get('volume', 0), data.get('quote_volume', 0), data.get('count', 0),
                data.get('taker_buy_volume', 0), data.get('taker_buy_quote_volume', 0),
                # Price changes
                data.get('price_change_pct', 0), data.get('high_low_ratio', 1),
                # Volume metrics 
                data.get('volume_ma_ratio', 1), data.get('buy_sell_ratio', 1),
                # Volatility
                data.get('volatility', 0), data.get('vwap', data.get('close', 0)),
                # Additional metrics (pad to 20 features)
                0, 0, 0, 0, 0
            ]
            
            feature_tensor = torch.tensor(features[:self.feature_dims.binance_klines], 
                                        dtype=torch.float32, device=self.device)
            age = timestamp - data.get('timestamp', timestamp)
            
            return feature_tensor, age
        
        except Exception as e:
            logger.error(f"Error processing Binance klines: {e}")
            return None, self.max_feature_age
    
    async def _process_binance_orderbook(
        self, symbol: str, timeframe: str, data: any, timestamp: float
    ) -> Tuple[Optional[torch.Tensor], float]:
        """Process Binance orderbook data into features"""
        if data is None:
            return None, self.max_feature_age
        
        try:
            # Extract orderbook features
            features = [
                data.get('bid_price', 0), data.get('ask_price', 0), data.get('spread', 0),
                data.get('spread_pct', 0), data.get('bid_size', 0), data.get('ask_size', 0),
                data.get('book_imbalance', 0), data.get('depth_imbalance', 0),
                data.get('weighted_mid', 0), data.get('microprice', 0),
                # Depth features
                data.get('bid_depth_5', 0), data.get('ask_depth_5', 0),
                data.get('bid_depth_10', 0), data.get('ask_depth_10', 0),
                data.get('order_flow', 0)
            ]
            
            feature_tensor = torch.tensor(features[:self.feature_dims.binance_orderbook], 
                                        dtype=torch.float32, device=self.device)
            age = timestamp - data.get('timestamp', timestamp)
            
            return feature_tensor, age
        
        except Exception as e:
            logger.error(f"Error processing Binance orderbook: {e}")
            return None, self.max_feature_age
    
    async def _process_ccxt_ohlcv(
        self, symbol: str, timeframe: str, data: any, timestamp: float
    ) -> Tuple[Optional[torch.Tensor], float]:
        """Process CCXT OHLCV data from other exchanges"""
        if data is None:
            return None, self.max_feature_age
        
        try:
            # Cross-exchange features
            features = [
                data.get('binance_close', 0), data.get('coinbase_close', 0), 
                data.get('kraken_close', 0), data.get('ftx_close', 0),
                # Price differences
                data.get('binance_coinbase_diff', 0), data.get('binance_kraken_diff', 0),
                # Volume comparisons
                data.get('volume_rank_binance', 0), data.get('volume_share_binance', 0),
                # Arbitrage signals
                data.get('max_spread', 0), data.get('arb_opportunity', 0)
            ]
            
            feature_tensor = torch.tensor(features[:self.feature_dims.ccxt_ohlcv], 
                                        dtype=torch.float32, device=self.device)
            age = timestamp - data.get('timestamp', timestamp)
            
            return feature_tensor, age
        
        except Exception as e:
            logger.error(f"Error processing CCXT data: {e}")
            return None, self.max_feature_age
    
    async def _process_liquidations(
        self, symbol: str, timeframe: str, data: any, timestamp: float
    ) -> Tuple[Optional[torch.Tensor], float]:
        """Process liquidation data into features"""
        if data is None:
            return None, self.max_feature_age
        
        try:
            # Liquidation features
            features = [
                data.get('total_liquidations', 0), data.get('long_liquidations', 0), 
                data.get('short_liquidations', 0), data.get('liquidation_ratio', 0),
                data.get('large_liquidations', 0), data.get('liquidation_intensity', 0),
                # Time-based aggregations
                data.get('liquidations_1h', 0), data.get('liquidations_4h', 0),
                data.get('liquidations_24h', 0),
                # Price impact
                data.get('liquidation_price_impact', 0), data.get('cascade_risk', 0),
                data.get('avg_liquidation_size', 0)
            ]
            
            feature_tensor = torch.tensor(features[:self.feature_dims.liquidations], 
                                        dtype=torch.float32, device=self.device)
            age = timestamp - data.get('timestamp', timestamp)
            
            return feature_tensor, age
        
        except Exception as e:
            logger.error(f"Error processing liquidations: {e}")
            return None, self.max_feature_age
    
    async def _process_technical_analysis(
        self, symbol: str, timeframe: str, data: any, timestamp: float
    ) -> Tuple[Optional[torch.Tensor], float]:
        """Process technical analysis indicators"""
        if data is None:
            return None, self.max_feature_age
        
        try:
            # TA features
            features = [
                data.get('rsi_14', 50), data.get('rsi_7', 50), data.get('rsi_21', 50),
                data.get('macd', 0), data.get('macd_signal', 0), data.get('macd_histogram', 0),
                data.get('bb_upper', 0), data.get('bb_lower', 0), data.get('bb_width', 0),
                data.get('sma_20', 0), data.get('ema_12', 0), data.get('ema_26', 0),
                data.get('stoch_k', 50), data.get('stoch_d', 50),
                data.get('atr', 0), data.get('adx', 0), data.get('cci', 0),
                data.get('williams_r', -50), data.get('mfi', 50),
                data.get('obv', 0), data.get('cmf', 0), data.get('vpt', 0),
                # Support/resistance
                data.get('support_level', 0), data.get('resistance_level', 0), data.get('pivot_point', 0)
            ]
            
            feature_tensor = torch.tensor(features[:self.feature_dims.technical_analysis], 
                                        dtype=torch.float32, device=self.device)
            age = timestamp - data.get('timestamp', timestamp)
            
            return feature_tensor, age
        
        except Exception as e:
            logger.error(f"Error processing TA: {e}")
            return None, self.max_feature_age
    
    async def _process_token_metrics(
        self, symbol: str, timeframe: str, data: any, timestamp: float
    ) -> Tuple[Optional[torch.Tensor], float]:
        """Process TokenMetrics data"""
        if data is None:
            return None, self.max_feature_age
        
        try:
            # TokenMetrics features
            features = [
                data.get('price_prediction', 0), data.get('sentiment_score', 0),
                data.get('technical_score', 0), data.get('fundamental_score', 0),
                data.get('trader_grade', 0), data.get('investor_grade', 0),
                data.get('volatility_risk', 0), data.get('momentum_score', 0),
                # On-chain metrics
                data.get('active_addresses', 0), data.get('transaction_count', 0),
                data.get('large_transactions', 0), data.get('exchange_inflows', 0),
                data.get('exchange_outflows', 0), data.get('whale_activity', 0),
                # Social metrics
                data.get('social_sentiment', 0), data.get('social_volume', 0),
                data.get('github_activity', 0), data.get('developer_activity', 0)
            ]
            
            feature_tensor = torch.tensor(features[:self.feature_dims.token_metrics], 
                                        dtype=torch.float32, device=self.device)
            age = timestamp - data.get('timestamp', timestamp)
            
            return feature_tensor, age
        
        except Exception as e:
            logger.error(f"Error processing TokenMetrics: {e}")
            return None, self.max_feature_age
    
    async def _process_coinank(
        self, symbol: str, timeframe: str, data: any, timestamp: float
    ) -> Tuple[Optional[torch.Tensor], float]:
        """Process Coinank data"""
        if data is None:
            return None, self.max_feature_age
        
        try:
            # Coinank features
            features = [
                data.get('funding_rate', 0), data.get('funding_rate_binance', 0),
                data.get('funding_rate_bybit', 0), data.get('funding_rate_okx', 0),
                data.get('open_interest', 0), data.get('oi_change_24h', 0),
                data.get('oi_weighted_funding', 0),
                # Exchange flows
                data.get('exchange_inflow', 0), data.get('exchange_outflow', 0), 
                data.get('net_flow', 0), data.get('whale_transactions', 0),
                # Market structure
                data.get('long_short_ratio', 1), data.get('top_trader_sentiment', 0),
                data.get('liquidation_heatmap', 0), data.get('volume_profile', 0),
                # Fear/greed
                data.get('fear_greed_index', 50), data.get('stablecoin_supply_ratio', 0),
                # Derivatives
                data.get('put_call_ratio', 1), data.get('basis_spread', 0),
                data.get('perpetual_premium', 0), data.get('futures_basis', 0),
                # Additional metrics
                data.get('correlation_btc', 0), data.get('beta', 1)
            ]
            
            feature_tensor = torch.tensor(features[:self.feature_dims.coinank], 
                                        dtype=torch.float32, device=self.device)
            age = timestamp - data.get('timestamp', timestamp)
            
            return feature_tensor, age
        
        except Exception as e:
            logger.error(f"Error processing Coinank: {e}")
            return None, self.max_feature_age
    
    async def _process_portfolio_state(
        self, symbol: str, timeframe: str, data: any, timestamp: float
    ) -> Tuple[Optional[torch.Tensor], float]:
        """Process portfolio state information"""
        if data is None:
            return None, self.max_feature_age
        
        try:
            # Portfolio features
            features = [
                data.get('long_position_size', 0), data.get('short_position_size', 0),
                data.get('net_position', 0), data.get('unrealized_pnl', 0),
                data.get('realized_pnl_24h', 0), data.get('margin_used', 0),
                data.get('available_margin', 0), data.get('portfolio_value', 0),
                data.get('exposure_pct', 0), data.get('leverage_used', 1),
                # Risk metrics
                data.get('var_95', 0), data.get('sharpe_ratio', 0),
                data.get('max_drawdown', 0), data.get('win_rate', 0),
                data.get('avg_hold_time_hours', 0)
            ]
            
            feature_tensor = torch.tensor(features[:self.feature_dims.portfolio_state], 
                                        dtype=torch.float32, device=self.device)
            age = timestamp - data.get('timestamp', timestamp)
            
            return feature_tensor, age
        
        except Exception as e:
            logger.error(f"Error processing portfolio state: {e}")
            return None, self.max_feature_age
    
    def _calculate_quality_score(
        self, 
        feature_ages: Dict[str, float], 
        source_mask: torch.Tensor
    ) -> float:
        """Calculate overall data quality score"""
        if not feature_ages:
            return 0.0
        
        # Quality based on data freshness and availability
        age_scores = []
        for source, age in feature_ages.items():
            # Exponential decay based on age
            age_score = np.exp(-age * self.quality_decay_rate / self.max_feature_age)
            age_scores.append(age_score)
        
        avg_age_score = np.mean(age_scores)
        availability_score = source_mask.mean().item()
        
        # Combined quality score
        quality_score = 0.7 * avg_age_score + 0.3 * availability_score
        
        return float(quality_score)
    
    def _create_fallback_tensor(self, symbol: str, timeframe: str) -> UnifiedFeatureVector:
        """Create fallback tensor with zeros when data is unavailable"""
        return UnifiedFeatureVector(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=time.time(),
            features=torch.zeros(self.feature_dims.total_features, device=self.device),
            source_mask=torch.zeros(len(DataSource), device=self.device),
            feature_age={source.value: self.max_feature_age for source in DataSource},
            quality_score=0.0
        )
    
    def _update_cache(
        self, 
        cache_key: Tuple[str, str], 
        feature_vector: UnifiedFeatureVector,
        timestamp: float
    ):
        """Update feature vector cache"""
        self.feature_cache[cache_key] = feature_vector
        self.cache_timestamps[cache_key] = timestamp
        
        # Prune cache if too large
        if len(self.feature_cache) > self.cache_size:
            # Remove oldest entries
            oldest_keys = sorted(
                self.cache_timestamps.items(), 
                key=lambda x: x[1]
            )[:len(self.feature_cache) - self.cache_size + 1]
            
            for key, _ in oldest_keys:
                del self.feature_cache[key]
                del self.cache_timestamps[key]


if __name__ == "__main__":
    # Test the unified feature tensor builder
    logging.basicConfig(level=logging.INFO)
    
    async def test_builder():
        builder = UnifiedFeatureTensorBuilder()
        
        print(f"🧪 Testing Unified Feature Tensor Builder...")
        print(f"Total feature dimensions: {builder.feature_dims.total_features}")
        
        # Create mock data
        mock_data = {
            'binance_klines': {
                'open': 50000, 'high': 50500, 'low': 49500, 'close': 50200,
                'volume': 1000, 'timestamp': time.time() - 60
            },
            'technical_analysis': {
                'rsi_14': 65, 'macd': 0.5, 'bb_width': 0.02,
                'timestamp': time.time() - 30
            },
            'portfolio_state': {
                'long_position_size': 0.1, 'unrealized_pnl': 150,
                'timestamp': time.time() - 10
            }
        }
        
        # Build feature tensor
        feature_vector = await builder.build_unified_tensor(
            "BTCUSDT", "15m", mock_data
        )
        
        print(f"\n📊 Feature Vector Results:")
        print(f"  Symbol: {feature_vector.symbol}")
        print(f"  Timeframe: {feature_vector.timeframe}")
        print(f"  Feature shape: {feature_vector.features.shape}")
        print(f"  Quality score: {feature_vector.quality_score:.3f}")
        print(f"  Sources available: {feature_vector.source_mask.sum().item()}/{len(DataSource)}")
        
        # Test batch processing
        symbols = ["BTCUSDT", "ETHUSDT"]
        timeframes = ["5m", "15m"]
        
        batch_results = await builder.build_batch_tensors(symbols, timeframes)
        
        print(f"\n🔄 Batch Processing Results:")
        print(f"  Processed: {len(batch_results)} symbol-timeframe pairs")
        
        # Get batched tensors
        feature_vectors = list(batch_results.values())
        batch_tensor = builder.get_feature_tensor_batch(feature_vectors)
        availability_matrix = builder.get_source_availability_matrix(feature_vectors)
        
        print(f"  Batch tensor shape: {batch_tensor.shape}")
        print(f"  Availability matrix shape: {availability_matrix.shape}")
        print(f"  Average quality: {np.mean([fv.quality_score for fv in feature_vectors]):.3f}")
    
    # Run test
    import asyncio
    asyncio.run(test_builder())