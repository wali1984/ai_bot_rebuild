"""
Supervised Pre-Training Module for Hybrid Trainer

Adds supervised pre-training capability to learn from historical data.
Integrates with hybrid_trainer.py.

Usage:
    from rl.supervised_pretrainer import SupervisedPretrainer
    pretrainer = SupervisedPretrainer(model, config)
    pretrainer.train(dataloader, epochs=10)
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.cuda.amp import autocast, GradScaler
import logging
from typing import Dict, Optional
from tqdm import tqdm
import time

logger = logging.getLogger(__name__)


class SupervisedPretrainer:
    """
    Supervised pre-training for LSTM+Attention policy.
    
    Trains on historical data to learn patterns before RL fine-tuning.
    """
    
    def __init__(
        self,
        model,  # PPO model (contains LSTM feature extractor)
        checkpoint_manager,
        learning_rate: float = 3e-4,
        gradient_accumulation_steps: int = 4,
        max_grad_norm: float = 1.0,
        use_amp: bool = True,
        device: str = 'cuda',
    ):
        """
        Args:
            model: PPO model with LSTM feature extractor
            checkpoint_manager: CheckpointManager instance
            learning_rate: Learning rate for pre-training
            gradient_accumulation_steps: Accumulate gradients (effective larger batch)
            max_grad_norm: Gradient clipping
            use_amp: Use mixed precision (FP16)
            device: Device to train on
        """
        self.model = model
        self.checkpoint_manager = checkpoint_manager
        self.gradient_accumulation_steps = gradient_accumulation_steps
        self.max_grad_norm = max_grad_norm
        self.use_amp = use_amp
        self.device = torch.device(device)
        
        # Move model to device
        self.model.policy.to(self.device)
        
        # Optimizer (AdamW for better regularization)
        self.optimizer = torch.optim.AdamW(
            self.model.policy.parameters(),
            lr=learning_rate,
            weight_decay=0.01,
        )
        
        # Mixed precision scaler
        self.scaler = GradScaler(enabled=use_amp)
        
        # Loss functions
        self.value_criterion = nn.MSELoss()
        self.policy_criterion = nn.CrossEntropyLoss()
        
        logger.info("✅ SupervisedPretrainer initialized")
        logger.info(f"   Learning rate: {learning_rate}")
        logger.info(f"   Gradient accumulation: {gradient_accumulation_steps}")
        logger.info(f"   Mixed precision: {use_amp}")
        logger.info(f"   Device: {device}")
    
    def train_epoch(
        self,
        dataloader,
        epoch: int,
    ) -> Dict[str, float]:
        """
        Train for one epoch.
        
        Args:
            dataloader: DataLoader with historical data
            epoch: Current epoch number
        
        Returns:
            Dict with metrics (loss, value_loss, policy_loss, etc.)
        """
        self.model.policy.train()
        
        total_loss = 0.0
        total_value_loss = 0.0
        total_policy_loss = 0.0
        total_samples = 0
        
        self.optimizer.zero_grad()
        
        # Progress bar
        pbar = tqdm(dataloader, desc=f"Epoch {epoch}")
        
        for batch_idx, batch in enumerate(pbar):
            # Move to device
            sequences = batch['sequence'].to(self.device, non_blocking=True)  # [batch, 10, 256]
            value_targets = batch['value_target'].to(self.device, non_blocking=True)  # [batch]
            action_targets = batch['action_target'].to(self.device, non_blocking=True)  # [batch]
            
            batch_size = sequences.shape[0]
            
            # Forward pass with mixed precision
            with autocast(enabled=self.use_amp):
                # Get features from LSTM
                # We need to process through the feature extractor
                # Then through value and policy heads
                
                # The feature extractor expects full observations (1041 dims)
                # which include: [market_features(256), portfolio_state, positions, etc.]
                # Since we only have market features from historical data,
                # we need to pad to match the expected input size
                
                # Get expected input size from the LSTM
                expected_input_size = self.model.policy.features_extractor.lstm.input_size  # Should be 1041
                market_feature_size = sequences.shape[-1]  # 256
                
                # Create full observation by padding
                # sequences shape: [batch, 10, 256]
                batch_size, seq_len, _ = sequences.shape
                full_sequences = torch.zeros(
                    batch_size, seq_len, expected_input_size,
                    device=self.device, dtype=sequences.dtype
                )
                # Copy market features to the first 256 dims
                full_sequences[:, :, :market_feature_size] = sequences
                # Rest is zeros (portfolio state, positions, etc.)
                
                # Process through feature extractor (handles LSTM internally)
                last_obs = full_sequences[:, -1, :]  # [batch, 1041] - last timestep
                features = self.model.policy.features_extractor(last_obs)  # [batch, 2048]
                
                # Process through MLP extractor (hidden layers)
                # The mlp_extractor has separate networks for policy and value
                latent_pi, latent_vf = self.model.policy.mlp_extractor(features)  # Both [batch, 256]
                
                # Value prediction
                values = self.model.policy.value_net(latent_vf).squeeze(-1)  # [batch]
                
                # Policy prediction (action logits)
                action_logits = self.model.policy.action_net(latent_pi)  # [batch, n_actions]
                
                # Losses
                value_loss = self.value_criterion(values, value_targets)
                policy_loss = self.policy_criterion(action_logits, action_targets)
                
                # Total loss
                loss = value_loss + policy_loss
                
                # Scale for gradient accumulation
                loss = loss / self.gradient_accumulation_steps
            
            # Backward pass
            self.scaler.scale(loss).backward()
            
            # Accumulate metrics
            total_loss += loss.item() * self.gradient_accumulation_steps
            total_value_loss += value_loss.item()
            total_policy_loss += policy_loss.item()
            total_samples += batch_size
            
            # Optimizer step (every N batches)
            if (batch_idx + 1) % self.gradient_accumulation_steps == 0:
                # Unscale gradients and clip
                self.scaler.unscale_(self.optimizer)
                grad_norm = torch.nn.utils.clip_grad_norm_(
                    self.model.policy.parameters(),
                    self.max_grad_norm
                )
                
                # Optimizer step
                self.scaler.step(self.optimizer)
                self.scaler.update()
                self.optimizer.zero_grad()
            
            # Update progress bar
            pbar.set_postfix({
                'loss': f"{total_loss / (batch_idx + 1):.4f}",
                'value': f"{total_value_loss / (batch_idx + 1):.4f}",
                'policy': f"{total_policy_loss / (batch_idx + 1):.4f}",
            })
        
        # Compute average metrics
        avg_metrics = {
            'loss': total_loss / len(dataloader),
            'value_loss': total_value_loss / len(dataloader),
            'policy_loss': total_policy_loss / len(dataloader),
            'samples': total_samples,
        }
        
        return avg_metrics
    
    def train(
        self,
        dataloader,
        epochs: int = 10,
        save_interval: int = 1,
    ) -> Dict:
        """
        Full training loop.
        
        Args:
            dataloader: DataLoader with historical data
            epochs: Number of epochs
            save_interval: Save checkpoint every N epochs
        
        Returns:
            Training history
        """
        logger.info(f"🎓 Starting supervised pre-training for {epochs} epochs")
        logger.info(f"   Total samples: {len(dataloader.dataset):,}")
        logger.info(f"   Batches per epoch: {len(dataloader):,}")
        logger.info(f"   Effective batch size: {dataloader.batch_size * self.gradient_accumulation_steps:,}")
        
        history = {
            'epoch': [],
            'loss': [],
            'value_loss': [],
            'policy_loss': [],
            'time': [],
        }
        
        best_loss = float('inf')
        start_time = time.time()
        
        for epoch in range(1, epochs + 1):
            epoch_start = time.time()
            
            # Train epoch
            metrics = self.train_epoch(dataloader, epoch)
            epoch_time = time.time() - epoch_start
            
            # Log results
            logger.info(f"📊 Epoch {epoch}/{epochs} completed:")
            logger.info(f"   Loss: {metrics['loss']:.4f}")
            logger.info(f"   Value Loss: {metrics['value_loss']:.4f}")
            logger.info(f"   Policy Loss: {metrics['policy_loss']:.4f}")
            logger.info(f"   Time: {epoch_time:.1f}s")
            
            # Update history
            history['epoch'].append(epoch)
            history['loss'].append(metrics['loss'])
            history['value_loss'].append(metrics['value_loss'])
            history['policy_loss'].append(metrics['policy_loss'])
            history['time'].append(epoch_time)
            
            # Save checkpoint
            if epoch % save_interval == 0:
                is_best = metrics['loss'] < best_loss
                if is_best:
                    best_loss = metrics['loss']
                
                # Get model and optimizer state
                model_state = self.model.policy.state_dict()
                optimizer_state = self.optimizer.state_dict()
                
                # Save checkpoint
                checkpoint_type = "best" if is_best else "live"
                self.checkpoint_manager.save_checkpoint(
                    model_state=model_state,
                    optimizer_state=optimizer_state,
                    epoch=epoch,
                    step=epoch * len(dataloader),
                    metrics=metrics,
                    checkpoint_type=checkpoint_type,
                )
        
        # Save final checkpoint as historical_baseline
        logger.info("💾 Saving final model as historical_baseline...")
        model_state = self.model.policy.state_dict()
        optimizer_state = self.optimizer.state_dict()
        
        final_metrics = {
            'loss': history['loss'][-1],
            'value_loss': history['value_loss'][-1],
            'policy_loss': history['policy_loss'][-1],
            'total_time': time.time() - start_time,
        }
        
        self.checkpoint_manager.save_checkpoint(
            model_state=model_state,
            optimizer_state=optimizer_state,
            epoch=epochs,
            step=epochs * len(dataloader),
            metrics=final_metrics,
            checkpoint_type="historical_baseline",
        )
        
        total_time = time.time() - start_time
        logger.info(f"✅ Supervised pre-training completed!")
        logger.info(f"   Total time: {total_time / 60:.1f} minutes")
        logger.info(f"   Final loss: {history['loss'][-1]:.4f}")
        logger.info(f"   Best loss: {best_loss:.4f}")
        
        return history


def run_supervised_pretraining(
    model,
    data_dir: str = "./data/live",
    symbols: Optional[list] = None,
    batch_size: int = 4096,
    epochs: int = 10,
    checkpoint_dir: str = "./models/checkpoints/live",
):
    """
    Convenience function to run supervised pre-training.
    
    Args:
        model: PPO model
        data_dir: Directory with JSONL files
        symbols: Symbols to train on (None = all)
        batch_size: Batch size
        epochs: Number of epochs
        checkpoint_dir: Where to save checkpoints
    """
    from rl.historical_data_loader import create_historical_dataloader
    from rl.checkpoint_manager import CheckpointManager
    from config import TIMEFRAMES
    
    logger.info("=" * 80)
    logger.info("🎓 SUPERVISED PRE-TRAINING MODE")
    logger.info("=" * 80)
    
    # Create dataloader
    logger.info("📊 Creating dataloader...")
    logger.info(f"   Timeframes: {TIMEFRAMES}")
    dataloader = create_historical_dataloader(
        data_dir=data_dir,
        batch_size=batch_size,
        num_workers=4,  # Reduced from 8 to avoid potential multiprocessing issues
        pin_memory=True,
        shuffle=True,
        symbols=symbols,
        timeframes=TIMEFRAMES,  # Use ALL timeframes from config: ['1m', '5m', '15m', '1h', '4h']
    )
    logger.info(f"✅ DataLoader ready: {len(dataloader.dataset):,} samples")
    
    # Create checkpoint manager
    checkpoint_manager = CheckpointManager(checkpoint_dir=checkpoint_dir)
    
    # Create pretrainer
    pretrainer = SupervisedPretrainer(
        model=model,
        checkpoint_manager=checkpoint_manager,
        learning_rate=3e-4,
        gradient_accumulation_steps=4,
        use_amp=True,
    )
    
    # Train
    history = pretrainer.train(dataloader, epochs=epochs)
    
    logger.info("=" * 80)
    logger.info("✅ SUPERVISED PRE-TRAINING COMPLETE")
    logger.info("=" * 80)
    
    return history
