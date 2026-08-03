# PHASE B: ML Trainer Porting Plan
**Duration:** Week 3-4 (10 working days)  
**Objective:** Enable PPO+MASA inference with legacy checkpoint compatibility  
**Target:** Predictions generating 24/7 to `v2:prediction:*` Redis keys

---

## Codex Alignment Note - 2026-07-08

This is a historical Claude/Fable planning artifact, not an approved execution
plan. Trainer, PPO, MASA, reward, action-mask, feedback/replay, and risk-related
logic changes require explicit task scope and tests before implementation.

Do not treat inference-only mode as sufficient if feedback/replay data is
available. Do not mark paper/probation results as final A+ or live-ready. Any
paper/live-dry-run consumption must preserve point-in-time safety:
`available_at <= decision_time` and MASA `feature_cutoff <= PPO decision_time`.

## LEGACY TRAINER ANALYSIS

**Source:** `/home/wali/Desktop/AI BOT - Legacy/rl/hybrid_trainer.py`

**Size:** 57,250 lines (too large for direct port)  
**Key Components:**
- RTX5080FeatureExtractor (feature → tensor encoding)
- RTX5080Policy (actor-critic policy network)
- GPUForcedPPO (PPO training algorithm)
- GPUTradingEnvironment (trade simulation)
- HybridTrainer (orchestrator)

**Available Checkpoints:**
- 6+ saved model states at `/home/wali/Desktop/AI BOT - Legacy/.models/checkpoints/`
- enterprise_modules_*.pt format
- Trained on 19,771+ iterations

---

## V2 PORTING STRATEGY

**Philosophy:** Extract essence, not size. Build lightweight inference-only version.

### LAYER 1: Gymnasium Environment (V2 Native)

Create observation space compatible with 562-field features:

```python
# obs_space: Box(low=-inf, high=inf, shape=(562,))
# action_space: Discrete(5)  # LONG, SHORT, HOLD, EXIT, REDUCE
```

**File:** `v2/backend/app/services/rl_core/gymnasium_environment.py`

### LAYER 2: Feature Adapter

Map unified features (409+ fields) → observation tensor (562 dims):

```python
# unified_features dict (409 fields)
  ↓
# flatten + pad to 562
  ↓
# normalize to [-1, 1]
  ↓
# PyTorch tensor (dtype=float32)
```

**File:** `v2/backend/app/services/rl_core/feature_adapter.py`

### LAYER 3: Policy Network (Minimal)

Extract just the policy network from legacy, remove training logic:

```python
class RTX5080PolicyInference:
  - actor_network (feature_dim=562 → action_logits)
  - critic_network (feature_dim=562 → value_scalar)
  - load_checkpoint(path) → restore weights
  - forward(observation) → action_logits, value
```

**File:** `v2/backend/app/services/rl_core/policy_network.py`

### LAYER 4: Checkpoint Loader

Load legacy `.pt` format checkpoints:

```python
class CheckpointLoader:
  - list_legacy_checkpoints()
  - load(checkpoint_path, policy_network)
  - verify_weights() → checksum
```

**File:** `v2/backend/app/services/rl_core/checkpoint_loader.py`

### LAYER 5: Inference Loop

Run inference 24/7, write predictions to Redis:

```python
while True:
  for symbol in symbols:
    for timeframe in timeframes:
      unified_features = redis.fetch(f"v2:unified_features:{symbol}:{tf}")
      
      observation = feature_adapter.encode(unified_features)
      
      action_logits, value = policy.forward(observation)
      
      direction = sample_action(action_logits)
      confidence = softmax(action_logits)[best_action]
      
      redis.hset(f"v2:prediction:{symbol}:{tf}", {
        "direction": direction,     # LONG/SHORT/HOLD
        "confidence": confidence,
        "value_estimate": value,
        "model_version": "hybrid_trainer_v1",
        "timestamp": now()
      })
      
      sleep(5)  # 5s between symbols to spread load
```

**File:** `v2/backend/app/cli/v2_rl_core_inference_loop.py`

---

## IMPLEMENTATION TIMELINE

### Week 3 (Days 1-5)

**Day 1: Environment Setup**
- Define Gymnasium Box observation/action spaces
- Create feature adapter (unified → tensor)
- Write adapter tests

**Day 2-3: Policy Network**
- Extract RTX5080Policy class logic (< 500 lines)
- Simplify to inference-only (remove training ops)
- Add checkpoint weight loading

**Day 4: Checkpoint Loading**
- Build checkpoint loader
- Test with legacy checkpoint files
- Verify weight shapes match

**Day 5: Integration Testing**
- Test full pipeline: unified features → observation → policy → action
- Mock data validation
- Error handling & logging

### Week 4 (Days 6-10)

**Day 6: Redis Adapter**
- Create data fetcher (unified features from Redis)
- Create data writer (predictions to Redis)
- Handle missing data gracefully

**Day 7-8: Inference Loop**
- Implement main loop with 5s symbol rotation
- Add memory monitoring (keep inference loop <500MB)
- Graceful checkpoint reloading without dropping cycles

**Day 9: Validation**
- Run 24/7 test against paper trading
- Monitor prediction latency (<50ms per symbol)
- Verify Redis writes are continuous

**Day 10: Production Readiness**
- Load test (all 114 symbols)
- Checkpoint recovery on crash
- Monitoring dashboard

---

## KEY DECISIONS

### 1. Inference-Only vs Training
**Decision:** Inference-only  
**Why:** 
- 19,771 iterations already in legacy checkpoints
- No time/GPU budget for retraining in Phase B
- Can retrain later with V2 features if needed
- Checkpoint compatibility requires minimal changes

### 2. Checkpoint Format
**Decision:** Keep legacy `.pt` format  
**Why:**
- 6+ checkpoints already exist
- PyTorch native, no conversion needed
- Weights are authoritative source of truth

### 3. Feature Mismatch (409 vs 562)
**Decision:** Pad with zeros  
**Why:**
- Network trained on 562 dims, safest to provide all
- Zero-padding in unused dimensions is safe
- Later: can use Phase C features to fill gaps

### 4. Confidence Score
**Decision:** Use softmax(action_logits)  
**Why:**
- Direct PPO output gives action probabilities
- Value estimate is orthogonal (expected return)
- Both inform downstream risk gates

---

## RISK MITIGATION

| Risk | Mitigation |
|------|-----------|
| Checkpoint weight mismatch | Verify shapes before loading, early error |
| GPU OOM during inference | Keep model in eval mode, detach gradients |
| Redis latency | Cache features locally, batch writes |
| Stale features | Check freshness flags before inference |
| Missing symbols | Skip symbol, continue loop (don't crash) |

---

## SUCCESS CRITERIA

✅ **Predictions generating continuously**
- `v2:prediction:BTCUSDT:1h` exists and updates every 5s
- 114 symbols × 6 timeframes = 684 Redis keys

✅ **Inference latency < 50ms per symbol**
- 5s rotation = 500ms per symbol max
- Headroom for Redis I/O + GC

✅ **Model using Phase A features**
- 409+ fields flowing into inference
- Zero-padding for unused 153 dims

✅ **Paper trading consuming predictions**
- v2_trade_management_paper_loop gets signals
- Paper-only execution tests must be re-validated; no live/test orders are approved here

✅ **Checkpoint recovery**
- Process crash / restart loads last checkpoint
- No missed prediction cycles > 2 minutes

---

## DEPENDENCIES

- ✅ Phase A complete (409+ feature fields flowing)
- ✅ Legacy checkpoints available (6+ states)
- ✅ Redis connection pool ready
- ✅ V2 infrastructure (FastAPI, Redis, cli scripts)

---

## DELIVERABLES

1. **gymnasium_environment.py** — 562-dim observation space
2. **feature_adapter.py** — Unified features → tensor encoding
3. **policy_network.py** — Inference-only PPO network (<500 lines)
4. **checkpoint_loader.py** — Load legacy `.pt` files
5. **v2_rl_core_inference_loop.py** — 24/7 prediction writer
6. **Phase B completion report** — Validation results, performance metrics

---

## NEXT AFTER PHASE B

**Phase C (Week 5-6):** Microstructure & Advanced Features
- CoinAPI WebSocket ingestor (27 fields)
- Orderbook depth aggregator
- TokenMetrics integration
- Then: Rebuild network with full 562 dims

**Phase D (Week 7-8):** Full Integration
- End-to-end system test
- Live-canary review gates with live still blocked
- Monitoring + alerting

---

## GO/NO-GO GATE FOR PHASE C

✅ **GO if:**
- Predictions generating to all 684 keys
- Latency < 50ms per symbol  
- Paper trading consuming predictions

❌ **NO-GO if:**
- Inference errors exceed 1% of cycles
- Memory leak detected
- Redis writes failing

---

**Status:** Historical planning note; requires fresh scoped approval before implementation  
**Approved:** Not approved by this alignment review
