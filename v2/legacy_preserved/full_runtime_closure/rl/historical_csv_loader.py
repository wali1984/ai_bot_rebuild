"""
Historical CSV Data Loader for Supervised Pre-Training

Loads historical OHLCV data from CSV files in data/historical/
and creates training samples for supervised pre-training.

Data Format Expected:
    data/historical/{SYMBOL}/{timeframe}.csv
    Columns: datetime, open, high, low, close, volume, volume_usdt, trade_count, symbol, timestamp
"""

import pandas as pd
import numpy as np
import torch
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from torch.utils.data import Dataset, DataLoader
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class HistoricalCSVDataset(Dataset):
    """
    PyTorch Dataset for historical OHLCV CSV data.
    
    Creates feature sequences and action labels from raw OHLCV candles.
    """
    
    # Action labels
    ACTION_HOLD = 0
    ACTION_LONG = 1
    ACTION_SHORT = 2
    
    def __init__(
        self,
        data_dir: str = "./data/historical",
        symbols: List[str] = None,
        timeframes: List[str] = None,
        sequence_length: int = 10,
        lookahead: int = 5,  # Candles to look ahead for label generation
        min_profit_pct: float = 0.3,  # 0.3% threshold for long/short labels
        max_samples_per_symbol: int = None,  # Limit samples per symbol
    ):
        """
        Args:
            data_dir: Root directory containing symbol subdirectories
            symbols: List of symbols to load (default: all found)
            timeframes: List of timeframes to load (default: 5m, 15m, 1h)
            sequence_length: Number of candles per input sequence
            lookahead: Candles to look ahead for profit calculation
            min_profit_pct: Minimum profit % to label as long/short
            max_samples_per_symbol: Limit samples per symbol (for faster testing)
        """
        self.data_dir = Path(data_dir)
        self.sequence_length = sequence_length
        self.lookahead = lookahead
        self.min_profit_pct = min_profit_pct
        self.max_samples_per_symbol = max_samples_per_symbol
        
        # Default timeframes (higher quality for pretraining)
        if timeframes is None:
            timeframes = ['5m', '15m', '1h']
        self.timeframes = timeframes
        
        # Discover symbols from directory structure
        available_symbols = self._discover_symbols()
        if symbols is None:
            self.symbols = available_symbols
        else:
            self.symbols = [s for s in symbols if s in available_symbols]
        
        logger.info(f"📊 Loading historical data from: {data_dir}")
        logger.info(f"   Symbols: {self.symbols}")
        logger.info(f"   Timeframes: {self.timeframes}")
        
        # Load and process all data
        self.samples = self._load_and_process_data()
        
        logger.info(f"✅ Created {len(self.samples):,} training samples")
        
    def _discover_symbols(self) -> List[str]:
        """Find available symbols from directory structure."""
        symbols = []
        for item in self.data_dir.iterdir():
            if item.is_dir() and item.name not in ['enhanced', '__pycache__']:
                # Check if it has any CSV files
                if list(item.glob("*.csv")):
                    symbols.append(item.name)
        return sorted(symbols)
    
    def _load_and_process_data(self) -> List[Dict]:
        """Load all CSV files and create training samples."""
        all_samples = []
        
        for symbol in self.symbols:
            symbol_dir = self.data_dir / symbol
            
            for tf in self.timeframes:
                csv_path = symbol_dir / f"{tf}.csv"
                if not csv_path.exists():
                    logger.debug(f"   Skipping {symbol}/{tf}.csv (not found)")
                    continue
                
                try:
                    samples = self._process_csv_file(csv_path, symbol, tf)
                    all_samples.extend(samples)
                    logger.info(f"   Loaded {len(samples):,} samples from {symbol}/{tf}")
                except Exception as e:
                    logger.warning(f"   ⚠️ Error loading {csv_path}: {e}")
        
        return all_samples
    
    def _process_csv_file(self, csv_path: Path, symbol: str, timeframe: str) -> List[Dict]:
        """Process a single CSV file into training samples."""
        # Load CSV
        df = pd.read_csv(csv_path)
        
        # Ensure required columns
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            raise ValueError(f"Missing columns: {missing}")
        
        # Sort by datetime/timestamp
        if 'timestamp' in df.columns:
            df = df.sort_values('timestamp').reset_index(drop=True)
        elif 'datetime' in df.columns:
            df = df.sort_values('datetime').reset_index(drop=True)
        
        # Create features (normalized OHLCV)
        features = self._create_features(df)
        
        # Create samples with sequences and labels
        samples = []
        total_candles = len(df)
        
        # Need enough candles for sequence + lookahead
        min_idx = self.sequence_length
        max_idx = total_candles - self.lookahead
        
        if max_idx <= min_idx:
            return []
        
        for i in range(min_idx, max_idx):
            # Sequence: [i-seq_len : i]
            seq_features = features[i - self.sequence_length:i]
            
            # Label: based on future price movement
            current_close = df.iloc[i]['close']
            future_close = df.iloc[i + self.lookahead]['close']
            future_return = (future_close - current_close) / current_close * 100  # Percentage
            
            # Action label
            if future_return > self.min_profit_pct:
                action = self.ACTION_LONG
            elif future_return < -self.min_profit_pct:
                action = self.ACTION_SHORT
            else:
                action = self.ACTION_HOLD
            
            samples.append({
                'sequence': seq_features,  # [seq_len, feature_dim]
                'value_target': future_return / 100,  # Normalized return
                'action_target': action,
                'symbol': symbol,
                'timeframe': timeframe,
            })
            
            # Limit samples if specified
            if self.max_samples_per_symbol and len(samples) >= self.max_samples_per_symbol:
                break
        
        return samples
    
    def _create_features(self, df: pd.DataFrame) -> np.ndarray:
        """
        Create normalized features from OHLCV data.
        
        Returns:
            np.ndarray of shape [num_candles, feature_dim]
        """
        # Basic features
        open_prices = df['open'].values
        high_prices = df['high'].values
        low_prices = df['low'].values
        close_prices = df['close'].values
        volumes = df['volume'].values
        
        # Derived features
        # 1. Price returns
        returns = np.zeros_like(close_prices)
        returns[1:] = (close_prices[1:] - close_prices[:-1]) / close_prices[:-1]
        
        # 2. Candle features (normalized by close)
        body = (close_prices - open_prices) / close_prices
        upper_wick = (high_prices - np.maximum(open_prices, close_prices)) / close_prices
        lower_wick = (np.minimum(open_prices, close_prices) - low_prices) / close_prices
        range_pct = (high_prices - low_prices) / close_prices
        
        # 3. Volume features (log-normalized, relative to rolling mean)
        log_volume = np.log1p(volumes)
        vol_mean = pd.Series(log_volume).rolling(20, min_periods=1).mean().values
        vol_std = pd.Series(log_volume).rolling(20, min_periods=1).std().fillna(1).values
        vol_zscore = (log_volume - vol_mean) / (vol_std + 1e-8)
        
        # 4. Moving averages
        close_series = pd.Series(close_prices)
        sma_5 = close_series.rolling(5, min_periods=1).mean().values
        sma_10 = close_series.rolling(10, min_periods=1).mean().values
        sma_20 = close_series.rolling(20, min_periods=1).mean().values
        
        # Relative to close
        sma_5_rel = (close_prices - sma_5) / close_prices
        sma_10_rel = (close_prices - sma_10) / close_prices
        sma_20_rel = (close_prices - sma_20) / close_prices
        
        # 5. Momentum indicators
        # RSI approximation (simplified)
        price_diff = np.diff(close_prices, prepend=close_prices[0])
        gain = np.where(price_diff > 0, price_diff, 0)
        loss = np.where(price_diff < 0, -price_diff, 0)
        avg_gain = pd.Series(gain).rolling(14, min_periods=1).mean().values
        avg_loss = pd.Series(loss).rolling(14, min_periods=1).mean().values
        rs = avg_gain / (avg_loss + 1e-8)
        rsi = 100 - (100 / (1 + rs))
        rsi_norm = (rsi - 50) / 50  # Normalize to [-1, 1]
        
        # 6. Volatility
        volatility = pd.Series(returns).rolling(20, min_periods=1).std().values
        
        # Stack features [num_candles, 14]
        features = np.stack([
            returns,           # 0: Returns
            body,              # 1: Candle body
            upper_wick,        # 2: Upper wick
            lower_wick,        # 3: Lower wick  
            range_pct,         # 4: Range %
            vol_zscore,        # 5: Volume z-score
            sma_5_rel,         # 6: SMA5 relative
            sma_10_rel,        # 7: SMA10 relative
            sma_20_rel,        # 8: SMA20 relative
            rsi_norm,          # 9: RSI normalized
            volatility,        # 10: Volatility
            np.zeros_like(returns),  # 11: Placeholder
            np.zeros_like(returns),  # 12: Placeholder
            np.zeros_like(returns),  # 13: Placeholder
        ], axis=1)  # [num_candles, 14]
        
        # Clip extreme values
        features = np.clip(features, -5, 5)
        
        # Replace NaN with 0
        features = np.nan_to_num(features, nan=0.0, posinf=5.0, neginf=-5.0)
        
        return features.astype(np.float32)
    
    def __len__(self) -> int:
        return len(self.samples)
    
    def __getitem__(self, idx: int) -> Dict[str, torch.Tensor]:
        sample = self.samples[idx]
        return {
            'sequence': torch.tensor(sample['sequence'], dtype=torch.float32),
            'value_target': torch.tensor(sample['value_target'], dtype=torch.float32),
            'action_target': torch.tensor(sample['action_target'], dtype=torch.long),
        }


def create_historical_csv_dataloader(
    data_dir: str = "./data/historical",
    symbols: List[str] = None,
    timeframes: List[str] = None,
    batch_size: int = 2048,
    num_workers: int = 4,
    pin_memory: bool = True,
    shuffle: bool = True,
    sequence_length: int = 10,
    max_samples_per_symbol: int = None,
) -> DataLoader:
    """
    Create a DataLoader for historical CSV data.
    
    Args:
        data_dir: Root directory with symbol subdirectories
        symbols: List of symbols (default: all)
        timeframes: List of timeframes (default: 5m, 15m, 1h)
        batch_size: Batch size for training
        num_workers: Number of worker processes
        pin_memory: Pin memory for GPU transfer
        shuffle: Shuffle samples
        sequence_length: Candles per sequence
        max_samples_per_symbol: Limit samples per symbol
    
    Returns:
        PyTorch DataLoader
    """
    dataset = HistoricalCSVDataset(
        data_dir=data_dir,
        symbols=symbols,
        timeframes=timeframes,
        sequence_length=sequence_length,
        max_samples_per_symbol=max_samples_per_symbol,
    )
    
    dataloader = DataLoader(
        dataset,
        batch_size=batch_size,
        num_workers=num_workers,
        pin_memory=pin_memory,
        shuffle=shuffle,
        drop_last=True,  # Drop incomplete batches
    )
    
    return dataloader


if __name__ == "__main__":
    # Test the loader
    logging.basicConfig(level=logging.INFO)
    
    print("Testing HistoricalCSVDataset...")
    dataset = HistoricalCSVDataset(
        data_dir="./data/historical",
        timeframes=['5m'],
        sequence_length=10,
        max_samples_per_symbol=1000,  # Limit for testing
    )
    
    print(f"\nTotal samples: {len(dataset):,}")
    
    if len(dataset) > 0:
        sample = dataset[0]
        print(f"Sample sequence shape: {sample['sequence'].shape}")
        print(f"Value target: {sample['value_target']:.4f}")
        print(f"Action target: {sample['action_target']}")
        
        # Test dataloader
        dataloader = create_historical_csv_dataloader(
            data_dir="./data/historical",
            batch_size=64,
            num_workers=0,  # 0 for testing
            max_samples_per_symbol=1000,
        )
        
        batch = next(iter(dataloader))
        print(f"\nBatch sequence shape: {batch['sequence'].shape}")
        print(f"Batch value targets: {batch['value_target'].shape}")
        print(f"Batch action targets: {batch['action_target'].shape}")
