# Trainer Master Audit — AI BOT V2
Generated: 2026-07-01T22:56:31Z

## System Overview

The AI BOT V2 trainer is a **native PyTorch CUDA trainer** running on a local GPU (RTX 5080), using a **PPO + MASA** (Multi-Agent State Abstraction) architecture. It is entirely V2-native — no dependency on the legacy Stable Baselines trainer at inference/training time.

### Key Facts (from Redis heartbeats)
- **Model source**: V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA
- **Trainer source**: V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW
- **Live gate**: blocked_human_only (constant)
- **paper_shadow_only**: true
- **GPU**: NVIDIA GeForce RTX 5080
- **VRAM used**: ~135 MB (very low — model is compact)
- **Batch size**: ~4,055–4,058 samples
- **Checkpoint ID**: v2_hybrid_ckpt_6d9f8817bed9ead40229baf7
- **Checkpoint format**: numpy .npz (safe format; torch pickle NOT used)
- **Checkpoint size**: ~25.7 MB weights
- **OOM count**: 0
- **Mixed precision**: enabled (fp16/bf16)
- **Optimizer**: AdamW (recreated each cycle; weights persist)

## Architecture

```
Feature Tensor (v2:features:snapshot:*)
    │
    ▼
PPO Actor-Critic Network (native PyTorch)
├── Shared backbone (MLP/transformer layers)
├── Actor head → action probabilities [LONG, SHORT, NO_TRADE]
├── MASA head → multi-agent state abstraction
└── Value head → expected return estimate
    │
    ▼
Prediction Output
├── direction: long | short | no_trade
├── selected_action: long | short | no_trade
├── confidence: [0,1]
├── confidence_calibrated: [0,1] (post-calibration)
├── action_probabilities: {long:float, short:float, no_trade:float}
├── expected_move: float (price target)
├── price_targets: {tp1, tp2, sl}
├── checkpoint_id: v2_hybrid_ckpt_*
├── feature_snapshot_id: v2_fsnap_*
├── feature_vector_hash: v2_hybrid_tensor_*
├── decision_time: ISO8601
├── available_at: ISO8601
└── feature_cutoff: ISO8601 (last feature timestamp used)
```

## Training Loop

### How It Trains
1. **Snapshot builder** (v2_feature_snapshot_builder) continuously writes feature snapshots to Redis at `v2:features:snapshot:v2_fsnap_{hash}`
2. **Native trainer loop** (v2_native_cuda_trainer_persistent_loop) reads snapshot batches from Redis
3. Constructs tensors from feature vectors for each symbol/timeframe
4. Runs forward pass through PPO actor-critic network
5. Computes PPO loss (clip ratio, entropy bonus, value loss)
6. Runs backward pass; updates weights with AdamW
7. Saves checkpoint to `.local_models/v2_native_rl_masa_ppo/{checkpoint_id}.weights.npz`
8. Publishes prediction to `v2:prediction:{sym}:{tf}` for each active symbol/timeframe

### Training Data
- **Input**: v2:features:snapshot:* (feature vectors per symbol/timeframe at each candle close)
- **Labels**: v2:trainer:feedback:outcomes (paper trade outcomes — win/loss/neutral)
- **Timeframes trained on**: 1m, 5m, 15m, 1h, 4h
- **Symbols**: ~93 active, 25+ in current feature pipeline heartbeat

### Future Leakage Prevention
- **decision_time** field: time prediction is made
- **available_at** field: time prediction is available for trading
- **feature_cutoff** field: most recent candle timestamp used in features
- Trainer validates no features post-feature_cutoff are used
- Closed-candle finality: only closed candles enter feature computation (no open candle leakage)

### Paper Outcome Feedback
- Paper trader writes closed trade outcomes to `v2:paper:closed_trades` and `v2:paper:outcome_labels`
- Feedback loop reads these and writes to `v2:trainer:feedback:outcomes`
- Trainer consumes feedback to update reward signal in PPO
- Quarantined feedback (stale, bad labels) goes to `v2:trainer:feedback:outcomes:quarantine`

### Checkpoint Lifecycle
1. Trainer saves checkpoint as `.weights.npz` (safe numpy format, no torch pickle)
2. Checkpoint manifest written to `.local_models/v2_native_rl_masa_ppo/{checkpoint_id}.json`
3. Evidence publisher reads manifest and writes to `v2:trainer:checkpoint:evidence`
4. On restart, trainer loads weights from `.weights.npz` (model_state_restored=true confirmed)
5. Optimizer recreated fresh each cycle (intentional design choice)
6. Durable weight blobs: yes — `.npz` files persist across restarts

## RL Core Sidecar (SIDECAR ONLY — does NOT override trainer)
- **Script**: v2_rl_core_inference_loop.py
- **Service**: ai-bot-v2-rl-core-inference-loop.service
- **Writes**: v2:rl_core:inference:{sym}:{tf} (advisory only)
- **Does NOT**: write v2:prediction:* keys, route to paper/live, override orchestrator
- **Purpose**: Alternative inference for comparison/research only
- **Why sidecar**: Primary RL inference is now native in the CUDA trainer; RL core is kept as secondary research signal

## Prediction Publishing

- **Publisher**: v2_native_trainer_prediction_publisher (sub-service of trainer loop)
- **Output key**: v2:prediction:{symbol}:{timeframe}
- **Additional**: v2:trainer:hybrid_cuda:signals:paper:{symbol}
- **All-timeframe aggregator**: v2_all_timeframe_prediction_signal_price_target_publisher
- **Website aggregator**: v2:website:predictions:{sym}

## Feature Map Summary

| Feature Family | Source | Redis Key Pattern | In Tensor |
|----------------|--------|-------------------|-----------|
| OHLCV (1m-4h) | Binance WSS | v2:features:latest:{sym}:{tf} | yes |
| Technical Indicators | TA-Lib loop | v2:features:ta_full:{sym}:{tf} | yes |
| Cross-exchange OHLCV | KuCoin REST | v2:features:kucoin:{sym}:{tf} | yes |
| CoinAPI OHLCV | CoinAPI WSDS | v2:market:coinapi:ohlcv:{sym}:{tf} | yes |
| Liquidation Events | Liq WSS | v2:liq:events:stream | yes |
| Liquidation Levels | Liq Engine | v2:liq:levels:{sym} | yes |
| Funding Rate / OI | CoinAnk | v2:altdata:coinank:{sym} | yes |
| Long/Short Ratio | CoinAnk | v2:altdata:coinank:{sym} | yes |
| Fear/Greed | Public Intel | v2:altdata:public_intel:global | yes |
| Social Score | LunarCrush | v2:altdata:lunarcrush:{sym} | partial |
| On-chain Flow | Nansen | v2:altdata:nansen:{sym} | partial |
| Whale Walls | AICoin | CRED_BLOCKED | no |

## What Remains Weak or Unproven
1. **AICoin whale wall data missing** — credentials not set; whale wall features absent
2. **LunarCrush/Nansen credential status** — not confirmed; social/on-chain may be partial
3. **Training rows count** — not surfaced in heartbeat at audit time; exact training row count unverified
4. **Validation set leakage test** — formal out-of-sample validation not in heartbeat
5. **Win rate vs profit factor** — no aggregate win rate metric in current heartbeat; paper outcome distribution not yet summarized
6. **MASA head interpretation** — multi-agent state abstraction not fully documented externally
