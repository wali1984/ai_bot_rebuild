"""
Historical Data Manager for Hybrid Trainer

Integrated historical data ingestion that:
1. Bootstraps with historical data on first run
2. Schedules incremental updates automatically
3. Provides a mixed replay buffer for training cycles
4. Persists state to checkpoints

Usage:
    manager = HistoricalDataManager(config)
    manager.bootstrap()  # First run: download + process
    manager.start_scheduler()  # Background updates every 4h
    
    # During training:
    historical_batch = manager.sample_batch(batch_size=256)
"""

import os
import sys
import json
import time
import torch
import numpy as np
import threading
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from collections import deque
import random

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from config import SYMBOLS, TIMEFRAMES
except ImportError:
    SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "1000SHIBUSDT", 
               "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "UNIUSDT", "LTCUSDT"]
    TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h"]

logger = logging.getLogger(__name__)


class HistoricalReplayBuffer:
    """
    GPU-optimized replay buffer that stores historical experiences.
    Supports mixing with live data at configurable ratios.
    """
    
    def __init__(
        self,
        capacity: int = 1_000_000,  # 1M samples
        device: str = 'cuda',
        feature_dim: int = 256,
        sequence_length: int = 10,
    ):
        self.capacity = capacity
        self.device = device
        self.feature_dim = feature_dim
        self.sequence_length = sequence_length
        
        # Pre-allocate tensors on GPU for fast sampling
        self.sequences = torch.zeros(
            (capacity, sequence_length, feature_dim),
            dtype=torch.float32,
            device='cpu'  # Store on CPU, transfer on sample
        )
        self.value_targets = torch.zeros(capacity, dtype=torch.float32, device='cpu')
        self.action_targets = torch.zeros(capacity, dtype=torch.long, device='cpu')
        self.timestamps = torch.zeros(capacity, dtype=torch.long, device='cpu')
        self.priorities = torch.ones(capacity, dtype=torch.float32, device='cpu')
        
        self.size = 0
        self.position = 0
        self.lock = threading.Lock()
        
        logger.info(f"📊 HistoricalReplayBuffer initialized: capacity={capacity:,}, device={device}")
    
    def add(
        self,
        sequence: torch.Tensor,
        value_target: float,
        action_target: int,
        timestamp: int = 0,
        priority: float = 1.0,
    ):
        """Add a single experience to the buffer"""
        with self.lock:
            self.sequences[self.position] = sequence.cpu()
            self.value_targets[self.position] = value_target
            self.action_targets[self.position] = action_target
            self.timestamps[self.position] = timestamp
            self.priorities[self.position] = priority
            
            self.position = (self.position + 1) % self.capacity
            self.size = min(self.size + 1, self.capacity)
    
    def add_batch(
        self,
        sequences: torch.Tensor,
        value_targets: torch.Tensor,
        action_targets: torch.Tensor,
        timestamps: Optional[torch.Tensor] = None,
        priorities: Optional[torch.Tensor] = None,
    ):
        """Add a batch of experiences efficiently"""
        batch_size = sequences.shape[0]
        
        with self.lock:
            # Handle wraparound
            if self.position + batch_size <= self.capacity:
                self.sequences[self.position:self.position + batch_size] = sequences.cpu()
                self.value_targets[self.position:self.position + batch_size] = value_targets.cpu()
                self.action_targets[self.position:self.position + batch_size] = action_targets.cpu()
                if timestamps is not None:
                    self.timestamps[self.position:self.position + batch_size] = timestamps.cpu()
                if priorities is not None:
                    self.priorities[self.position:self.position + batch_size] = priorities.cpu()
            else:
                # Split across wraparound
                first_part = self.capacity - self.position
                self.sequences[self.position:] = sequences[:first_part].cpu()
                self.sequences[:batch_size - first_part] = sequences[first_part:].cpu()
                
                self.value_targets[self.position:] = value_targets[:first_part].cpu()
                self.value_targets[:batch_size - first_part] = value_targets[first_part:].cpu()
                
                self.action_targets[self.position:] = action_targets[:first_part].cpu()
                self.action_targets[:batch_size - first_part] = action_targets[first_part:].cpu()
            
            self.position = (self.position + batch_size) % self.capacity
            self.size = min(self.size + batch_size, self.capacity)
    
    def sample(self, batch_size: int, prioritized: bool = False) -> Dict[str, torch.Tensor]:
        """Sample a batch from the buffer"""
        if self.size == 0:
            return None
        
        actual_batch_size = min(batch_size, self.size)
        
        with self.lock:
            if prioritized:
                # Prioritized sampling (higher priority = more likely)
                probs = self.priorities[:self.size] / self.priorities[:self.size].sum()
                indices = torch.multinomial(probs, actual_batch_size, replacement=False)
            else:
                # Uniform sampling
                indices = torch.randint(0, self.size, (actual_batch_size,))
            
            return {
                'sequence': self.sequences[indices].to(self.device),
                'value_target': self.value_targets[indices].to(self.device),
                'action_target': self.action_targets[indices].to(self.device),
                'indices': indices,
            }
    
    def update_priorities(self, indices: torch.Tensor, priorities: torch.Tensor):
        """Update priorities after learning (for PER)"""
        with self.lock:
            self.priorities[indices] = priorities.cpu()
    
    def __len__(self) -> int:
        return self.size
    
    def get_stats(self) -> Dict:
        """Get buffer statistics"""
        return {
            'size': self.size,
            'capacity': self.capacity,
            'fill_ratio': self.size / self.capacity,
            'action_distribution': {
                'hold': (self.action_targets[:self.size] == 0).sum().item(),
                'long': (self.action_targets[:self.size] == 1).sum().item(),
                'short': (self.action_targets[:self.size] == 2).sum().item(),
            }
        }


class HistoricalDataManager:
    """
    Manages historical data for the Hybrid Trainer:
    - Downloads from CDD API on first run
    - Converts to JSONL format
    - Loads into GPU replay buffer
    - Schedules incremental updates
    - Checkpoints state
    """
    
    def __init__(
        self,
        data_dir: str = "./data/historical",
        live_data_dir: str = "./data/live",
        checkpoint_dir: str = "./models/checkpoints",
        device: str = 'cuda',
        buffer_capacity: int = 1_000_000,
        feature_dim: int = 256,
        sequence_length: int = 10,
        lookahead: int = 10,
        min_profit: float = 0.002,
        update_interval_hours: int = 4,
        historical_mix_ratio: float = 0.3,  # 30% historical, 70% live
    ):
        self.data_dir = Path(data_dir)
        self.live_data_dir = Path(live_data_dir)
        self.checkpoint_dir = Path(checkpoint_dir)
        self.device = device
        self.feature_dim = feature_dim
        self.sequence_length = sequence_length
        self.lookahead = lookahead
        self.min_profit = min_profit
        self.update_interval_hours = update_interval_hours
        self.historical_mix_ratio = historical_mix_ratio
        
        # Create directories
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.live_data_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        
        # State
        self.state = {
            'last_download': None,
            'last_update': None,
            'symbols_downloaded': [],
            'total_samples_loaded': 0,
            'bootstrap_complete': False,
        }
        
        # Replay buffer
        self.buffer = HistoricalReplayBuffer(
            capacity=buffer_capacity,
            device=device,
            feature_dim=feature_dim,
            sequence_length=sequence_length,
        )
        
        # Scheduler
        self._scheduler_thread = None
        self._scheduler_stop = threading.Event()
        
        # Load state from checkpoint
        self._load_state()
        
        logger.info(f"📚 HistoricalDataManager initialized")
        logger.info(f"   Data dir: {self.data_dir}")
        logger.info(f"   Buffer capacity: {buffer_capacity:,}")
        logger.info(f"   Historical mix ratio: {historical_mix_ratio:.1%}")
    
    def _load_state(self):
        """Load state from checkpoint"""
        state_file = self.checkpoint_dir / "historical_data_state.json"
        if state_file.exists():
            try:
                with open(state_file, 'r') as f:
                    self.state = json.load(f)
                logger.info(f"📂 Loaded historical data state: {self.state['total_samples_loaded']:,} samples")
            except Exception as e:
                logger.warning(f"Could not load state: {e}")
    
    def _save_state(self):
        """Save state to checkpoint"""
        state_file = self.checkpoint_dir / "historical_data_state.json"
        try:
            with open(state_file, 'w') as f:
                json.dump(self.state, f, indent=2, default=str)
            logger.debug(f"💾 Saved historical data state")
        except Exception as e:
            logger.warning(f"Could not save state: {e}")
    
    def is_bootstrap_needed(self) -> bool:
        """Check if we need to bootstrap (first run)"""
        if not self.state['bootstrap_complete']:
            return True
        
        # Check if we have JSONL files
        jsonl_files = list(self.live_data_dir.glob("*_5m.jsonl"))
        return len(jsonl_files) < 5  # Need at least 5 symbols
    
    def bootstrap(self, days: int = 365, force: bool = False) -> bool:
        """
        Bootstrap historical data:
        1. Download from CDD API
        2. Convert to JSONL
        3. Load into replay buffer
        
        Returns True if successful
        """
        if not force and not self.is_bootstrap_needed():
            logger.info("✅ Bootstrap not needed - data already available")
            return self._load_into_buffer()
        
        logger.info("=" * 60)
        logger.info("🚀 BOOTSTRAPPING HISTORICAL DATA")
        logger.info("=" * 60)
        
        try:
            # Step 1: Download OHLCV data
            logger.info("\n📥 Step 1/3: Downloading OHLCV data from CDD...")
            if not self._download_ohlcv(days):
                logger.warning("⚠️  Download incomplete, using existing data")
            
            # Step 2: Convert to JSONL
            logger.info("\n🔄 Step 2/3: Converting to JSONL format...")
            self._convert_to_jsonl()
            
            # Step 3: Load into buffer
            logger.info("\n📊 Step 3/3: Loading into replay buffer...")
            self._load_into_buffer()
            
            # Mark bootstrap complete
            self.state['bootstrap_complete'] = True
            self.state['last_download'] = datetime.now().isoformat()
            self._save_state()
            
            logger.info("\n" + "=" * 60)
            logger.info("✅ BOOTSTRAP COMPLETE")
            logger.info(f"   Samples in buffer: {len(self.buffer):,}")
            logger.info("=" * 60)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Bootstrap failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _download_ohlcv(self, days: int = 365) -> bool:
        """Download OHLCV data from CDD API"""
        try:
            # Import the CDD functions (standalone, not class methods)
            from ingest.cdd_historical import CDDClient, download_symbol_data
            
            # Only download if we don't have recent data
            last_download = self.state.get('last_download')
            if last_download:
                last_dt = datetime.fromisoformat(last_download)
                if datetime.now() - last_dt < timedelta(hours=self.update_interval_hours):
                    logger.info("📂 Using cached data (downloaded recently)")
                    return True
            
            # Create client for API calls
            client = CDDClient()
            
            # Download for all symbols using standalone function
            success_count = 0
            for symbol in SYMBOLS:
                try:
                    logger.info(f"  Downloading {symbol}...")
                    download_symbol_data(
                        client=client,
                        symbol=symbol,
                        days_back=days,
                        output_dir=str(self.data_dir),
                        output_format='csv',
                    )
                    success_count += 1
                except Exception as e:
                    logger.warning(f"  Failed {symbol}: {e}")
            
            self.state['symbols_downloaded'] = [s for s in SYMBOLS[:success_count]]
            return success_count > 0
            
        except ImportError:
            logger.warning("CDD client not available, using existing data")
            return True
        except Exception as e:
            logger.error(f"Download error: {e}")
            return False
    
    def _convert_to_jsonl(self) -> bool:
        """Convert CSV files to JSONL format"""
        try:
            import pandas as pd
            
            converted = 0
            
            for symbol_dir in self.data_dir.iterdir():
                if not symbol_dir.is_dir():
                    continue
                
                symbol = symbol_dir.name
                
                for csv_file in symbol_dir.glob("*.csv"):
                    timeframe = csv_file.stem  # e.g., "5m"
                    output_file = self.live_data_dir / f"{symbol}_{timeframe}.jsonl"
                    
                    # Skip if already converted and recent
                    if output_file.exists():
                        csv_mtime = csv_file.stat().st_mtime
                        jsonl_mtime = output_file.stat().st_mtime
                        if jsonl_mtime > csv_mtime:
                            continue
                    
                    try:
                        df = pd.read_csv(csv_file)
                        
                        with open(output_file, 'w') as f:
                            for _, row in df.iterrows():
                                record = {
                                    'open': float(row.get('open', 0)),
                                    'high': float(row.get('high', 0)),
                                    'low': float(row.get('low', 0)),
                                    'close': float(row.get('close', 0)),
                                    'volume': float(row.get('volume', 0)),
                                    'ts': int(row.get('timestamp', 0)),
                                }
                                f.write(json.dumps(record) + '\n')
                        
                        converted += 1
                        logger.debug(f"  Converted {output_file.name}")
                        
                    except Exception as e:
                        logger.warning(f"  Failed to convert {csv_file}: {e}")
            
            logger.info(f"✅ Converted {converted} files to JSONL")
            return True
            
        except Exception as e:
            logger.error(f"Conversion error: {e}")
            return False
    
    def _load_into_buffer(self) -> bool:
        """Load JSONL files into the replay buffer"""
        try:
            total_loaded = 0
            
            # Focus on 5m timeframe for training (best signal quality)
            jsonl_files = sorted(self.live_data_dir.glob("*_5m.jsonl"))
            
            for jsonl_file in jsonl_files:
                samples_loaded = self._load_jsonl_file(jsonl_file)
                total_loaded += samples_loaded
                
                if total_loaded >= self.buffer.capacity * 0.95:
                    logger.info("Buffer nearly full, stopping load")
                    break
            
            self.state['total_samples_loaded'] = total_loaded
            self._save_state()
            
            logger.info(f"✅ Loaded {total_loaded:,} samples into buffer")
            return total_loaded > 0
            
        except Exception as e:
            logger.error(f"Buffer load error: {e}")
            return False
    
    def _load_jsonl_file(self, filepath: Path) -> int:
        """Load a single JSONL file into the buffer"""
        candles = []
        
        try:
            with open(filepath, 'r') as f:
                for line in f:
                    try:
                        candle = json.loads(line.strip())
                        candles.append(candle)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning(f"Error reading {filepath}: {e}")
            return 0
        
        if len(candles) < self.sequence_length + self.lookahead:
            return 0
        
        # Create sequences and labels
        samples_added = 0
        batch_sequences = []
        batch_values = []
        batch_actions = []
        batch_timestamps = []
        
        for i in range(len(candles) - self.sequence_length - self.lookahead):
            # Get sequence
            sequence = candles[i:i + self.sequence_length]
            
            # Get prices for PnL
            current = candles[i + self.sequence_length - 1]
            future = candles[i + self.sequence_length + self.lookahead - 1]
            
            current_price = float(current['close'])
            future_price = float(future['close'])
            
            if current_price == 0:
                continue
            
            # Calculate return
            price_return = (future_price - current_price) / current_price
            
            # Determine action label
            if price_return > self.min_profit:
                action = 1  # LONG
            elif price_return < -self.min_profit:
                action = 2  # SHORT
            else:
                action = 0  # HOLD
            
            # Convert sequence to features
            seq_features = self._sequence_to_features(sequence)
            
            batch_sequences.append(seq_features)
            batch_values.append(price_return)
            batch_actions.append(action)
            batch_timestamps.append(current.get('ts', 0))
            
            # Batch add every 1000 samples
            if len(batch_sequences) >= 1000:
                self.buffer.add_batch(
                    torch.stack(batch_sequences),
                    torch.tensor(batch_values, dtype=torch.float32),
                    torch.tensor(batch_actions, dtype=torch.long),
                    torch.tensor(batch_timestamps, dtype=torch.long),
                )
                samples_added += len(batch_sequences)
                batch_sequences = []
                batch_values = []
                batch_actions = []
                batch_timestamps = []
        
        # Add remaining
        if batch_sequences:
            self.buffer.add_batch(
                torch.stack(batch_sequences),
                torch.tensor(batch_values, dtype=torch.float32),
                torch.tensor(batch_actions, dtype=torch.long),
                torch.tensor(batch_timestamps, dtype=torch.long),
            )
            samples_added += len(batch_sequences)
        
        return samples_added
    
    def _sequence_to_features(self, sequence: List[Dict]) -> torch.Tensor:
        """Convert a sequence of candles to feature tensor"""
        features = torch.zeros(self.sequence_length, self.feature_dim, dtype=torch.float32)
        
        for i, candle in enumerate(sequence):
            features[i] = self._candle_to_features(candle)
        
        return features
    
    def _candle_to_features(self, candle: Dict) -> torch.Tensor:
        """Convert a single candle to feature vector"""
        features = torch.zeros(self.feature_dim, dtype=torch.float32)
        
        open_p = float(candle.get('open', 0))
        high_p = float(candle.get('high', 0))
        low_p = float(candle.get('low', 0))
        close_p = float(candle.get('close', 0))
        volume = float(candle.get('volume', 0))
        
        if close_p > 0:
            features[0] = (high_p - low_p) / close_p  # Range
            features[1] = (close_p - open_p) / close_p  # Body
            features[2] = (high_p - max(open_p, close_p)) / close_p  # Upper wick
            features[3] = (min(open_p, close_p) - low_p) / close_p  # Lower wick
        
        if volume > 0:
            features[4] = np.log1p(volume) / 20.0
        
        # Price levels (normalized)
        features[5] = open_p / 100000.0
        features[6] = high_p / 100000.0
        features[7] = low_p / 100000.0
        features[8] = close_p / 100000.0
        
        return features
    
    # ========================
    # Scheduler for incremental updates
    # ========================
    
    def start_scheduler(self):
        """Start background scheduler for incremental data updates"""
        if self._scheduler_thread is not None and self._scheduler_thread.is_alive():
            logger.warning("Scheduler already running")
            return
        
        self._scheduler_stop.clear()
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()
        logger.info(f"🕐 Historical data scheduler started (interval: {self.update_interval_hours}h)")
    
    def stop_scheduler(self):
        """Stop the background scheduler"""
        self._scheduler_stop.set()
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=5)
        logger.info("🛑 Historical data scheduler stopped")
    
    def _scheduler_loop(self):
        """Background thread for incremental updates"""
        while not self._scheduler_stop.is_set():
            # Wait for next update
            self._scheduler_stop.wait(timeout=self.update_interval_hours * 3600)
            
            if self._scheduler_stop.is_set():
                break
            
            # Perform incremental update
            logger.info("🔄 Running scheduled incremental data update...")
            try:
                self._incremental_update()
            except Exception as e:
                logger.error(f"Incremental update failed: {e}")
    
    def _incremental_update(self):
        """Fetch and load new data (incremental)"""
        try:
            # Download last 24h of data
            self._download_ohlcv(days=1)
            self._convert_to_jsonl()
            
            # Load new samples into buffer
            # (buffer will naturally evict oldest samples)
            self._load_into_buffer()
            
            self.state['last_update'] = datetime.now().isoformat()
            self._save_state()
            
            logger.info("✅ Incremental update complete")
            
        except Exception as e:
            logger.error(f"Incremental update error: {e}")
    
    # ========================
    # Training interface
    # ========================
    
    def sample_batch(self, batch_size: int = 256, prioritized: bool = False) -> Optional[Dict[str, torch.Tensor]]:
        """Sample a batch of historical data for training"""
        return self.buffer.sample(batch_size, prioritized)
    
    def get_mixed_batch(
        self,
        live_batch: Dict[str, torch.Tensor],
        historical_batch_size: Optional[int] = None,
    ) -> Dict[str, torch.Tensor]:
        """
        Mix live batch with historical samples.
        
        Args:
            live_batch: Batch from live trading
            historical_batch_size: How many historical samples to add
        
        Returns:
            Combined batch with both live and historical samples
        """
        if len(self.buffer) == 0:
            return live_batch
        
        if historical_batch_size is None:
            # Calculate based on mix ratio
            live_size = live_batch['sequence'].shape[0]
            historical_batch_size = int(live_size * self.historical_mix_ratio / (1 - self.historical_mix_ratio))
        
        historical = self.buffer.sample(historical_batch_size)
        if historical is None:
            return live_batch
        
        # Combine batches
        combined = {
            'sequence': torch.cat([live_batch['sequence'], historical['sequence']], dim=0),
            'value_target': torch.cat([live_batch['value_target'], historical['value_target']], dim=0),
            'action_target': torch.cat([live_batch['action_target'], historical['action_target']], dim=0),
        }
        
        # Shuffle
        perm = torch.randperm(combined['sequence'].shape[0])
        for key in combined:
            combined[key] = combined[key][perm]
        
        return combined
    
    def get_stats(self) -> Dict:
        """Get manager statistics"""
        return {
            'state': self.state,
            'buffer': self.buffer.get_stats(),
            'scheduler_running': self._scheduler_thread is not None and self._scheduler_thread.is_alive(),
        }
    
    # ========================
    # Checkpoint interface
    # ========================
    
    def save_checkpoint(self, path: str):
        """Save full checkpoint (state + buffer sample)"""
        checkpoint = {
            'state': self.state,
            'buffer_size': len(self.buffer),
            'buffer_stats': self.buffer.get_stats(),
        }
        
        checkpoint_path = Path(path)
        with open(checkpoint_path, 'w') as f:
            json.dump(checkpoint, f, indent=2, default=str)
        
        logger.info(f"💾 Saved historical data checkpoint: {path}")
    
    def load_checkpoint(self, path: str) -> bool:
        """Load checkpoint and restore buffer"""
        try:
            with open(path, 'r') as f:
                checkpoint = json.load(f)
            
            self.state = checkpoint.get('state', self.state)
            
            # Reload buffer from files
            if self.state.get('bootstrap_complete'):
                self._load_into_buffer()
            
            logger.info(f"📂 Loaded historical data checkpoint: {path}")
            return True
            
        except Exception as e:
            logger.warning(f"Could not load checkpoint: {e}")
            return False


# ========================
# Integration helper
# ========================

def create_historical_manager(
    config: Optional[Any] = None,
    device: str = 'cuda',
) -> HistoricalDataManager:
    """
    Factory function to create a HistoricalDataManager with default settings.
    
    Args:
        config: Optional config object with settings
        device: Device for tensors
    
    Returns:
        Configured HistoricalDataManager
    """
    kwargs = {
        'device': device,
        'buffer_capacity': 1_000_000,
        'historical_mix_ratio': 0.3,
        'update_interval_hours': 4,
    }
    
    if config:
        if hasattr(config, 'historical_buffer_capacity'):
            kwargs['buffer_capacity'] = config.historical_buffer_capacity
        if hasattr(config, 'historical_mix_ratio'):
            kwargs['historical_mix_ratio'] = config.historical_mix_ratio
        if hasattr(config, 'historical_update_hours'):
            kwargs['update_interval_hours'] = config.historical_update_hours
    
    return HistoricalDataManager(**kwargs)


if __name__ == "__main__":
    """Test the historical data manager"""
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 60)
    print("🧪 TESTING HISTORICAL DATA MANAGER")
    print("=" * 60)
    
    manager = HistoricalDataManager(
        buffer_capacity=100_000,  # Smaller for testing
        device='cuda' if torch.cuda.is_available() else 'cpu',
    )
    
    # Test bootstrap
    print("\n📥 Testing bootstrap...")
    manager.bootstrap(days=7, force=False)
    
    # Test sampling
    print("\n📊 Testing sampling...")
    batch = manager.sample_batch(batch_size=64)
    if batch:
        print(f"   Sequence shape: {batch['sequence'].shape}")
        print(f"   Value targets: {batch['value_target'][:5]}")
        print(f"   Action targets: {batch['action_target'][:5]}")
    
    # Print stats
    print("\n📈 Stats:")
    stats = manager.get_stats()
    print(f"   Buffer size: {stats['buffer']['size']:,}")
    print(f"   Action distribution: {stats['buffer']['action_distribution']}")
    
    print("\n✅ Test complete!")

