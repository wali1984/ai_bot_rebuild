"""Supervised pretraining for MASA (Meta-Action Selection Agent).

This module provides an offline warm-start for the MASA network using historical JSONL data
(via `HistoricalDataLoader`). It trains:
- A categorical policy head over discrete hedge actions (act_dim=7)
- A value head (regression)

It intentionally mirrors the approach used by `rl.supervised_pretrainer.SupervisedPretrainer`.

Historical data format
----------------------
The pretrainer relies on `HistoricalDataLoader` which expects JSONL files named like:
  BTCUSDT_5m.jsonl
Each line should contain at least:
  {"ts": 1700000000000, "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}

Outputs
-------
Saves a checkpoint (state_dict + metadata) to:
  <checkpoint_dir>/masa_historical_baseline.pth

Note
----
This is a warm-start. Live training can continue to refine MASA weights and save separate
runtime checkpoints.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

from rl.historical_data_loader import HistoricalDataLoader
from rl.agents.masa_agent import MASAAgent, MASAConfig


class _LastStepDataset(torch.utils.data.Dataset):
    def __init__(
        self,
        X: np.ndarray,
        y_action: np.ndarray,
        y_value: np.ndarray,
    ):
        assert X.ndim == 2, "X must be (N, obs_dim)"
        self.X = torch.tensor(X, dtype=torch.float32)
        self.y_action = torch.tensor(y_action, dtype=torch.long)
        self.y_value = torch.tensor(y_value, dtype=torch.float32)

    def __len__(self) -> int:
        return self.X.shape[0]

    def __getitem__(self, idx: int):
        return self.X[idx], self.y_action[idx], self.y_value[idx]


class MASASupervisedPretrainer:
    def __init__(
        self,
        masa_agent: MASAAgent,
        obs_dim: int,
        act_dim: int = 7,
        device: str = "cuda",
        lr: float = 3e-4,
        weight_decay: float = 1e-5,
        entropy_coeff: float = 0.0,
        value_coeff: float = 0.5,
        max_grad_norm: float = 1.0,
        logger=None,
    ):
        self.masa_agent = masa_agent
        self.obs_dim = int(obs_dim)
        self.act_dim = int(act_dim)
        self.device = torch.device(device if torch.cuda.is_available() and device.startswith("cuda") else "cpu")
        self.lr = lr
        self.weight_decay = weight_decay
        self.entropy_coeff = entropy_coeff
        self.value_coeff = value_coeff
        self.max_grad_norm = max_grad_norm
        self.logger = logger

        self.model = self.masa_agent.model.to(self.device)
        self.model.train()

        self.optimizer = optim.AdamW(self.model.parameters(), lr=self.lr, weight_decay=self.weight_decay)
        self.ce_loss = nn.CrossEntropyLoss()
        self.mse_loss = nn.MSELoss()

    def _log(self, msg: str):
        if self.logger is not None:
            try:
                self.logger.info(msg)
                return
            except Exception:
                pass
        print(msg)

    @staticmethod
    def _normalize(X: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        mean = np.mean(X, axis=0, keepdims=True)
        std = np.std(X, axis=0, keepdims=True)
        std[std < 1e-8] = 1.0
        return (X - mean) / std, mean.squeeze(0), std.squeeze(0)

    def _prepare_dataset(
        self,
        sequences: np.ndarray,
        action_targets: np.ndarray,
        value_targets: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Map (N, seq_len, 256) to (N, obs_dim) by taking last step and padding."""
        X_last = sequences[:, -1, :]
        # Pad/truncate to obs_dim
        X = np.zeros((X_last.shape[0], self.obs_dim), dtype=np.float32)
        use = min(X_last.shape[1], self.obs_dim)
        X[:, :use] = X_last[:, :use]
        y_action = action_targets.astype(np.int64)
        y_value = value_targets.astype(np.float32)
        return X, y_action, y_value

    def fit(
        self,
        data_dir: str,
        timeframe: str,
        symbols: Optional[List[str]] = None,
        batch_size: int = 4096,
        epochs: int = 5,
        validation_split: float = 0.1,
        seed: int = 42,
        num_workers: int = 4,
    ) -> Dict[str, float]:
        np.random.seed(seed)
        torch.manual_seed(seed)

        loader = HistoricalDataLoader(data_dir, timeframe)

        if symbols is None:
            # Best-effort: infer from files in dir
            symbols = []
            for p in Path(data_dir).glob(f"*_{timeframe}.jsonl"):
                sym = p.name.split(f"_{timeframe}.jsonl")[0]
                if sym:
                    symbols.append(sym)
            symbols = sorted(set(symbols))

        self._log(f"[MASA-PRETRAIN] Loading historical data: dir={data_dir}, tf={timeframe}, symbols={len(symbols)}")

        combined_X: List[np.ndarray] = []
        combined_y_action: List[np.ndarray] = []
        combined_y_value: List[np.ndarray] = []

        for sym in symbols:
            try:
                seq, a_t, v_t = loader.load_symbol_data(sym)
                X, y_a, y_v = self._prepare_dataset(seq, a_t, v_t)
                combined_X.append(X)
                combined_y_action.append(y_a)
                combined_y_value.append(y_v)
                self._log(f"[MASA-PRETRAIN] {sym}: {X.shape[0]} samples")
            except FileNotFoundError:
                self._log(f"[MASA-PRETRAIN] {sym}: missing file, skipping")
            except Exception as e:
                self._log(f"[MASA-PRETRAIN] {sym}: error {e}, skipping")

        if not combined_X:
            raise RuntimeError("No historical samples loaded for MASA pretraining")

        X_all = np.concatenate(combined_X, axis=0)
        y_action_all = np.concatenate(combined_y_action, axis=0)
        y_value_all = np.concatenate(combined_y_value, axis=0)

        # Normalize inputs
        X_norm, X_mean, X_std = self._normalize(X_all)

        # Split
        n = X_norm.shape[0]
        idx = np.arange(n)
        np.random.shuffle(idx)
        split = int(n * (1 - validation_split))
        train_idx, val_idx = idx[:split], idx[split:]

        train_ds = _LastStepDataset(X_norm[train_idx], y_action_all[train_idx], y_value_all[train_idx])
        val_ds = _LastStepDataset(X_norm[val_idx], y_action_all[val_idx], y_value_all[val_idx])

        train_loader = torch.utils.data.DataLoader(
            train_ds, batch_size=batch_size, shuffle=True, num_workers=num_workers, pin_memory=True
        )
        val_loader = torch.utils.data.DataLoader(
            val_ds, batch_size=batch_size, shuffle=False, num_workers=max(1, num_workers // 2), pin_memory=True
        )

        best_val = float("inf")
        metrics: Dict[str, float] = {}

        for epoch in range(1, epochs + 1):
            self.model.train()
            tr_loss = 0.0
            tr_n = 0

            for Xb, y_ab, y_vb in train_loader:
                Xb = Xb.to(self.device, non_blocking=True)
                y_ab = y_ab.to(self.device, non_blocking=True)
                y_vb = y_vb.to(self.device, non_blocking=True)

                self.optimizer.zero_grad(set_to_none=True)

                action_logits, value_pred = self.model(Xb)
                # action_logits: (B, act_dim)
                if action_logits.shape[-1] != self.act_dim:
                    raise RuntimeError(f"MASA act_dim mismatch: logits={action_logits.shape[-1]} expected={self.act_dim}")

                loss_policy = self.ce_loss(action_logits, y_ab)
                loss_value = self.mse_loss(value_pred.squeeze(-1), y_vb)

                # Optional: entropy regularization
                if self.entropy_coeff > 0.0:
                    probs = torch.softmax(action_logits, dim=-1)
                    entropy = -(probs * torch.log(probs.clamp_min(1e-12))).sum(dim=-1).mean()
                    loss = loss_policy + self.value_coeff * loss_value - self.entropy_coeff * entropy
                else:
                    loss = loss_policy + self.value_coeff * loss_value

                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.max_grad_norm)
                self.optimizer.step()

                tr_loss += float(loss.item()) * Xb.size(0)
                tr_n += Xb.size(0)

            tr_loss /= max(1, tr_n)

            # Validation
            self.model.eval()
            val_loss = 0.0
            val_n = 0
            correct = 0

            with torch.no_grad():
                for Xb, y_ab, y_vb in val_loader:
                    Xb = Xb.to(self.device, non_blocking=True)
                    y_ab = y_ab.to(self.device, non_blocking=True)
                    y_vb = y_vb.to(self.device, non_blocking=True)

                    action_logits, value_pred = self.model(Xb)
                    loss_policy = self.ce_loss(action_logits, y_ab)
                    loss_value = self.mse_loss(value_pred.squeeze(-1), y_vb)
                    loss = loss_policy + self.value_coeff * loss_value

                    val_loss += float(loss.item()) * Xb.size(0)
                    val_n += Xb.size(0)

                    preds = torch.argmax(action_logits, dim=-1)
                    correct += int((preds == y_ab).sum().item())

            val_loss /= max(1, val_n)
            val_acc = correct / max(1, val_n)

            self._log(f"[MASA-PRETRAIN] Epoch {epoch}/{epochs} | train_loss={tr_loss:.6f} | val_loss={val_loss:.6f} | val_acc={val_acc:.4f}")

            metrics = {
                "train_loss": tr_loss,
                "val_loss": val_loss,
                "val_acc": float(val_acc),
                "samples": float(n),
            }

            if val_loss < best_val:
                best_val = val_loss
                self._best_state = {
                    "model_state_dict": {k: v.detach().cpu() for k, v in self.model.state_dict().items()},
                    "obs_dim": self.obs_dim,
                    "act_dim": self.act_dim,
                    "input_mean": X_mean,
                    "input_std": X_std,
                    "metrics": metrics,
                    "masa_config": asdict(self.masa_agent.config) if hasattr(self.masa_agent, "config") else None,
                }

        return metrics

    def save(self, checkpoint_dir: str, filename: str = "masa_historical_baseline.pth") -> Path:
        if not hasattr(self, "_best_state"):
            raise RuntimeError("No trained state to save; call fit() first")

        out_dir = Path(checkpoint_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename
        torch.save(self._best_state, out_path)
        self._log(f"[MASA-PRETRAIN] Saved MASA baseline checkpoint: {out_path}")
        return out_path


def run_masa_supervised_pretraining(
    obs_dim: int,
    data_dir: str,
    timeframe: str,
    checkpoint_dir: str,
    symbols: Optional[List[str]] = None,
    device: str = "cuda",
    epochs: int = 5,
    batch_size: int = 4096,
) -> Path:
    """Convenience entrypoint."""
    config = MASAConfig(obs_dim=int(obs_dim), act_dim=7)
    agent = MASAAgent(config, device=device)
    pre = MASASupervisedPretrainer(agent, obs_dim=obs_dim, act_dim=7, device=device)
    pre.fit(data_dir=data_dir, timeframe=timeframe, symbols=symbols, epochs=epochs, batch_size=batch_size)
    return pre.save(checkpoint_dir)
