# P0.2B Legacy Baseline Analysis — MASA/PPO Policy Forward

- Scope: CPU-first deterministic forward pass over the P0.1 trainer-consumable feature snapshot.
- Strictly paper-only. No torch, no SB3, no Redis, no exchange SDK, no checkpoint weights.

## Legacy modules consulted

| Path | SHA256 | Size | Role |
| ---- | ------ | ---- | ---- |
| `v2/legacy_owned_runtime/rl/agents/masa_agent.py` | `0c7496336ca00c0f006d9a294ea67e736e2c3f2a3e4202b98cd6925dff891080` | 21109 | `MASAAgent`, `GPUOptimizedMASANetwork`, `HybridPPO` |
| `v2/legacy_owned_runtime/rl/enhanced_architectures.py` | `d7b2071a6c83edee5eb940d50e5578fb0b4dd14d54f9e577c65d2533409b8236` | 23252 | `RecurrentFeatureExtractor`, `MarketRegimeObserver` |
| `v2/legacy_owned_runtime/rl/gpu_cnn_policy.py` | `881cfdad7650e9114e14c24a8d3d7bc2cbb5a4c1ce2a5fa8cb3fe2d50d3b4062` | 7843 | GPU CNN policy variant |
| `v2/legacy_owned_runtime/rl/hybrid_action_space.py` | `abc7ecf1e655e4a018eeedcb4ad675c7bb35e101d4b5a42d432132243aed6c23` | 16553 | `HybridActionDecoder`, `HybridActionHead`, `ConfidenceBasedSizer`, `DynamicLeverageScheduler` |

## Behavior contract preserved in V2 P0.2B

- 26-dim observation tensor (matches `OBSERVATION_FEATURE_ORDER` from P0.2A).
- 5-class discrete action set: `hold`, `long`, `short`, `close`, `hedge` (hedge fail-closed).
- Deterministic forward pass: identical seed produces identical weights, logits, probabilities, selected action.
- Scalar value/expected-move head computed from the policy hidden layer (no constant return).

## Behavior contract NOT preserved in V2 P0.2B (deferred)

- PPO clip loss, GAE advantage, AdamW optimizer state.
- LSTM/GRU recurrence and hidden-state cache.
- Regime observer head, dynamic leverage scheduler, confidence-based sizer.
- Torch tensor ops, AMP, GPU placement.
- Checkpoint weight load.
- Lagrangian safety constraints.

## Dependency closure (legacy imports)

- `torch`, `torch.nn`, `torch.nn.functional`, `torch.optim` — not imported by V2 P0.2B.
- `stable_baselines3` (PPO, ActorCriticPolicy, BaseFeaturesExtractor) — not imported by V2 P0.2B.
- `numpy` — not imported by V2 P0.2B.
- `redis` — not imported by V2 P0.2B.
- `gymnasium` (spaces) — not imported by V2 P0.2B.

## Config / env mapping

| Legacy key | V2 P0.2B mapping |
| ---------- | ---------------- |
| `MASAConfig.obs_dim` | `POLICY_OBSERVATION_DIM = 26` |
| `MASAConfig.action_dim` | `ACTION_COUNT = 5` |
| `MASAConfig.amp_enabled` | not used (no torch, no AMP) |
| `torch.optim.AdamW` lr | not used (no optimizer in P0.2B) |
| Any `redis://...` URL | not used (policy is pure stdlib) |

## Safety posture

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`
- No old Redis writes, no exchange mutation, no checkpoint weight load.

## What this analysis allows

This is the legacy baseline that the V2 P0.2B forward pass mirrors at the
surface level. It does NOT claim full trainer parity. Full parity is gated
by P0.2C (checkpoint), P0.2D (CPU update), P0.2E (GPU parity), P0.2F
(trainer output contract).
