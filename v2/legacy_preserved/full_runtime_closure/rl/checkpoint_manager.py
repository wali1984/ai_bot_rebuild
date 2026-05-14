"""
Checkpoint Manager for Hybrid Trainer

Handles checkpoint saving, loading, and automatic cleanup.
Keeps historical_baseline permanent, auto-deletes old live checkpoints.

Features:
- Intelligent checkpoint naming with metadata
- Auto-cleanup (keep 3 days for live, permanent for historical)
- Best model tracking
- Checkpoint validation
- Storage optimization
"""

import os
import json
import shutil
import torch
from pathlib import Path
from typing import Dict, Optional, List
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class CheckpointManager:
    """
    Manages model checkpoints with automatic cleanup and tracking.
    """
    
    def __init__(
        self,
        checkpoint_dir: str = "./models/checkpoints/live",
        keep_days: int = 3,
        keep_best: int = 3,
    ):
        """
        Args:
            checkpoint_dir: Directory to save checkpoints
            keep_days: Days to keep live checkpoints (historical_baseline永久保留)
            keep_best: Number of best checkpoints to keep
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        
        self.keep_days = keep_days
        self.keep_best = keep_best
        
        # Metadata file to track checkpoints
        self.metadata_file = self.checkpoint_dir / "checkpoints_metadata.json"
        self.metadata = self._load_metadata()
        
        logger.info(f"✅ CheckpointManager initialized:")
        logger.info(f"   Directory: {checkpoint_dir}")
        logger.info(f"   Keep days: {keep_days}")
        logger.info(f"   Keep best: {keep_best}")
    
    def _load_metadata(self) -> Dict:
        """Load checkpoint metadata"""
        if self.metadata_file.exists():
            with open(self.metadata_file, 'r') as f:
                return json.load(f)
        return {
            'checkpoints': [],
            'best_checkpoints': [],
            'historical_baseline': None,
        }
    
    def _save_metadata(self):
        """Save checkpoint metadata"""
        with open(self.metadata_file, 'w') as f:
            json.dump(self.metadata, f, indent=2)
    
    def save_checkpoint(
        self,
        model_state: Dict,
        optimizer_state: Dict,
        epoch: int,
        step: int,
        metrics: Dict,
        checkpoint_type: str = "live",  # "live", "best", or "historical_baseline"
        name: Optional[str] = None,
    ) -> str:
        """
        Save a checkpoint.
        
        Args:
            model_state: Model state dict
            optimizer_state: Optimizer state dict
            epoch: Training epoch
            step: Training step
            metrics: Dict with loss, accuracy, etc.
            checkpoint_type: Type of checkpoint
            name: Optional custom name
        
        Returns:
            Path to saved checkpoint
        """
        timestamp = int(datetime.now().timestamp())
        
        if name is None:
            if checkpoint_type == "historical_baseline":
                name = "historical_baseline"
            else:
                name = f"checkpoint_epoch{epoch}_step{step}_{timestamp}"
        
        checkpoint_path = self.checkpoint_dir / f"{name}.pth"
        
        # Prepare checkpoint dict
        checkpoint = {
            'model_state_dict': model_state,
            'optimizer_state_dict': optimizer_state,
            'epoch': epoch,
            'step': step,
            'metrics': metrics,
            'timestamp': timestamp,
            'checkpoint_type': checkpoint_type,
        }
        
        # Save checkpoint
        logger.info(f"💾 Saving checkpoint: {checkpoint_path.name}")
        torch.save(checkpoint, checkpoint_path)
        
        # Update metadata
        checkpoint_info = {
            'name': name,
            'path': str(checkpoint_path),
            'epoch': epoch,
            'step': step,
            'timestamp': timestamp,
            'type': checkpoint_type,
            'metrics': metrics,
            'size_mb': checkpoint_path.stat().st_size / 1024**2,
        }
        
        if checkpoint_type == "historical_baseline":
            self.metadata['historical_baseline'] = checkpoint_info
        else:
            self.metadata['checkpoints'].append(checkpoint_info)
            
            # Track best checkpoints
            if 'loss' in metrics:
                self.metadata['best_checkpoints'].append(checkpoint_info)
                # Sort by loss and keep only best N
                self.metadata['best_checkpoints'].sort(key=lambda x: x['metrics'].get('loss', float('inf')))
                self.metadata['best_checkpoints'] = self.metadata['best_checkpoints'][:self.keep_best]
        
        self._save_metadata()
        
        logger.info(f"✅ Checkpoint saved: {name}")
        logger.info(f"   Size: {checkpoint_info['size_mb']:.1f} MB")
        logger.info(f"   Metrics: {metrics}")
        
        return str(checkpoint_path)
    
    def load_checkpoint(
        self,
        name: Optional[str] = None,
        checkpoint_type: str = "latest",  # "latest", "best", or "historical_baseline"
    ) -> Optional[Dict]:
        """
        Load a checkpoint.
        
        Args:
            name: Checkpoint name (if None, uses checkpoint_type)
            checkpoint_type: Type to load if name not specified
        
        Returns:
            Checkpoint dict or None if not found
        """
        checkpoint_path = None
        
        if name:
            # Load specific checkpoint by name
            checkpoint_path = self.checkpoint_dir / f"{name}.pth"
        elif checkpoint_type == "historical_baseline":
            # Load historical baseline
            if self.metadata['historical_baseline']:
                checkpoint_path = Path(self.metadata['historical_baseline']['path'])
        elif checkpoint_type == "best":
            # Load best checkpoint
            if self.metadata['best_checkpoints']:
                checkpoint_path = Path(self.metadata['best_checkpoints'][0]['path'])
        elif checkpoint_type == "latest":
            # Load most recent checkpoint
            if self.metadata['checkpoints']:
                latest = max(self.metadata['checkpoints'], key=lambda x: x['timestamp'])
                checkpoint_path = Path(latest['path'])
        
        if checkpoint_path is None or not checkpoint_path.exists():
            logger.warning(f"⚠️  Checkpoint not found: {checkpoint_type}")
            return None
        
        logger.info(f"📂 Loading checkpoint: {checkpoint_path.name}")
        checkpoint = torch.load(checkpoint_path, map_location='cuda' if torch.cuda.is_available() else 'cpu')
        
        logger.info(f"✅ Checkpoint loaded:")
        logger.info(f"   Epoch: {checkpoint.get('epoch', 'N/A')}")
        logger.info(f"   Step: {checkpoint.get('step', 'N/A')}")
        logger.info(f"   Metrics: {checkpoint.get('metrics', {})}")
        
        return checkpoint
    
    def cleanup_old_checkpoints(self):
        """
        Remove checkpoints older than keep_days.
        Keeps historical_baseline and best checkpoints permanent.
        """
        logger.info(f"🧹 Cleaning up old checkpoints (keeping {self.keep_days} days)...")
        
        cutoff_time = datetime.now() - timedelta(days=self.keep_days)
        cutoff_timestamp = int(cutoff_time.timestamp())
        
        # Get list of checkpoints to delete
        to_delete = []
        for ckpt in self.metadata['checkpoints']:
            # Skip if it's in best checkpoints
            if any(b['name'] == ckpt['name'] for b in self.metadata['best_checkpoints']):
                continue
            
            # Skip if recent
            if ckpt['timestamp'] > cutoff_timestamp:
                continue
            
            # Skip if it's historical_baseline
            if ckpt['type'] == 'historical_baseline':
                continue
            
            to_delete.append(ckpt)
        
        # Delete old checkpoints
        deleted_count = 0
        freed_space = 0
        
        for ckpt in to_delete:
            path = Path(ckpt['path'])
            if path.exists():
                size_mb = ckpt['size_mb']
                path.unlink()
                freed_space += size_mb
                deleted_count += 1
                logger.info(f"   🗑️  Deleted: {ckpt['name']} ({size_mb:.1f} MB)")
        
        # Update metadata
        self.metadata['checkpoints'] = [
            c for c in self.metadata['checkpoints']
            if c not in to_delete
        ]
        self._save_metadata()
        
        logger.info(f"✅ Cleanup complete:")
        logger.info(f"   Deleted: {deleted_count} checkpoints")
        logger.info(f"   Freed: {freed_space:.1f} MB")
    
    def get_storage_stats(self) -> Dict:
        """Get storage statistics"""
        total_size = 0
        checkpoint_count = 0
        
        for ckpt_file in self.checkpoint_dir.glob("*.pth"):
            total_size += ckpt_file.stat().st_size
            checkpoint_count += 1
        
        return {
            'total_size_mb': total_size / 1024**2,
            'total_size_gb': total_size / 1024**3,
            'checkpoint_count': checkpoint_count,
            'directory': str(self.checkpoint_dir),
            'historical_baseline_exists': self.metadata['historical_baseline'] is not None,
            'best_checkpoints': len(self.metadata['best_checkpoints']),
        }
    
    def list_checkpoints(self) -> List[Dict]:
        """List all checkpoints"""
        return self.metadata['checkpoints']
    
    def get_best_checkpoint_path(self) -> Optional[str]:
        """Get path to best checkpoint"""
        if self.metadata['best_checkpoints']:
            return self.metadata['best_checkpoints'][0]['path']
        return None
    
    def get_historical_baseline_path(self) -> Optional[str]:
        """Get path to historical_baseline"""
        if self.metadata['historical_baseline']:
            return self.metadata['historical_baseline']['path']
        return None


if __name__ == "__main__":
    """Test checkpoint manager"""
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 80)
    print("🧪 TESTING CHECKPOINT MANAGER")
    print("=" * 80)
    print()
    
    # Create test checkpoint manager
    test_dir = "./test_checkpoints"
    manager = CheckpointManager(checkpoint_dir=test_dir, keep_days=3)
    
    # Create dummy checkpoint
    print("💾 Saving test checkpoint...")
    dummy_model_state = {'layer1.weight': torch.randn(10, 10)}
    dummy_optimizer_state = {'state': {}}
    
    path = manager.save_checkpoint(
        model_state=dummy_model_state,
        optimizer_state=dummy_optimizer_state,
        epoch=1,
        step=1000,
        metrics={'loss': 0.5, 'accuracy': 0.8},
        checkpoint_type="live",
    )
    print(f"✅ Saved to: {path}")
    print()
    
    # Save historical baseline
    print("💾 Saving historical_baseline...")
    path = manager.save_checkpoint(
        model_state=dummy_model_state,
        optimizer_state=dummy_optimizer_state,
        epoch=10,
        step=10000,
        metrics={'loss': 0.1, 'accuracy': 0.95},
        checkpoint_type="historical_baseline",
    )
    print(f"✅ Saved to: {path}")
    print()
    
    # Get storage stats
    print("📊 Storage statistics:")
    stats = manager.get_storage_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")
    print()
    
    # List checkpoints
    print("📋 All checkpoints:")
    for ckpt in manager.list_checkpoints():
        print(f"   {ckpt['name']}: epoch={ckpt['epoch']}, loss={ckpt['metrics'].get('loss')}")
    print()
    
    # Load checkpoint
    print("📂 Loading historical_baseline...")
    checkpoint = manager.load_checkpoint(checkpoint_type="historical_baseline")
    if checkpoint:
        print(f"✅ Loaded successfully")
        print(f"   Epoch: {checkpoint['epoch']}")
        print(f"   Metrics: {checkpoint['metrics']}")
    print()
    
    # Cleanup test directory
    print("🧹 Cleaning up test directory...")
    shutil.rmtree(test_dir)
    print("✅ Test complete!")
    print("=" * 80)
