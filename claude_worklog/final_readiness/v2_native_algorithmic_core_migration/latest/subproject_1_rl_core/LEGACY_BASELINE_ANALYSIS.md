# Subproject 1 (RL Core) — Legacy Baseline Analysis

Generated: `2026-05-15`
Migration contract: `claude_worklog/final_readiness/permanent_migration_runtime/latest/MIGRATION_COMPLETION_CONTRACT.md`
Scope: `PAPER_ONLY`. Live gate: `blocked_human_only`. Live symbols: `[]`.

## Purpose

This document is the honest baseline for what the legacy RL core does, which
behaviors V2 ports natively in this subproject, which it partially ports, and
which remain `MISSING_IN_V2`. Every legacy file consulted is cited by SHA256.

The migration audit confirmed the RL core (PPO+MASA, GPU env, SB3 loop) is
not migrated. V2 only has a subprocess wrapper and a read-only bridge today.
This subproject does NOT close that gap. It ports the small, safe, paper-only
pieces (observation descriptor, reward math, checkpoint filename parsing,
temperature scaling) so V2 can score paper outcomes natively without going
through the legacy process.

## Legacy files consulted

All paths are inside `v2/legacy_preserved/full_runtime_closure/` and are
read-only. SHA256 values are cited from
`claude_worklog/legacy_runtime_closure/full_runtime_copied_source_manifest.json`.

| Legacy path | sha256 | size_bytes | V2 preserved path |
|---|---|---|---|
| `rl/obs_schema.py` | `9ec040fa1306ac28f4395aac103b104eb02644866ca8acec5577b155fd925f5f` | 17346 | `v2/legacy_preserved/full_runtime_closure/rl/obs_schema.py` |
| `rl/reward_functions.py` | `87ef4602012cbbd944bdf506fb8f1646375e7732c3a93e87b0946db7a1cca853` | 31805 | `v2/legacy_preserved/full_runtime_closure/rl/reward_functions.py` |
| `rl/constrained_reward.py` | `69ff3c75b53d8d3d7844894954cf9d16f334e79e0c1bd39e9624a4482a459b2e` | 10861 | `v2/legacy_preserved/full_runtime_closure/rl/constrained_reward.py` |
| `rl/fee_ratio_reward_shaping.py` | `e7edce3e29a6bf7236329245ba4a14436dc6f6b0a249ad0ad3d05760570bfc06` | 19427 | `v2/legacy_preserved/full_runtime_closure/rl/fee_ratio_reward_shaping.py` |
| `rl/calibrated_confidence.py` | `03c56d7e3345444e9f285de3bee596573b3ca8d05ee4f3a26aef56e032806d90` | 9767 | `v2/legacy_preserved/full_runtime_closure/rl/calibrated_confidence.py` |
| `rl/temperature_calibration.py` | `302355f82bbed15dd4db75600eb058406a0a08bd44ef86ef44f19c43f54cc221` | 4993 | `v2/legacy_preserved/full_runtime_closure/rl/temperature_calibration.py` |
| `rl/environment.py` | `39866005417554c7f9552a64eddc14ec1024db7e22b432c844cfd1a8e7800b1d` | 66775 | `v2/legacy_preserved/full_runtime_closure/rl/environment.py` |
| `rl/gymnasium_wrapper.py` | `61a086cb4a0a406ca67fe2035cf776b0c991bb9d7391572ce86e77aea0a16574` | 14062 | `v2/legacy_preserved/full_runtime_closure/rl/gymnasium_wrapper.py` |
| `rl/agents/masa_agent.py` | `0c7496336ca00c0f006d9a294ea67e736e2c3f2a3e4202b98cd6925dff891080` | 21109 | `v2/legacy_preserved/full_runtime_closure/rl/agents/masa_agent.py` |
| `rl/enhanced_architectures.py` | `d7b2071a6c83edee5eb940d50e5578fb0b4dd14d54f9e577c65d2533409b8236` | 23252 | `v2/legacy_preserved/full_runtime_closure/rl/enhanced_architectures.py` |
| `rl/hybrid_trainer.py` | `b7dad66b63b57c0d5c29e0fbaf67466d9c2aab81baf7a4f67b6e681e38c5b102` | 3165342 | `v2/legacy_preserved/full_runtime_closure/rl/hybrid_trainer.py` |

## What each legacy file does (high level)

- `rl/obs_schema.py` — Registry of three legacy observation schemas
  (V1=1053 dims, V2=1061 dims, V3=1911 dims) with slice descriptors and a
  manager that auto-detects checkpoint schema and activates a SAFE_MODE that
  only allows protective actions when the schema is unknown.
- `rl/reward_functions.py` — Advanced reward calculator covering realized PnL
  credit, fee penalty, slippage penalty, and step shaping for the legacy
  training loop.
- `rl/constrained_reward.py` — Lagrangian-multiplier-based constraint shaping
  for liquidation buffer, margin utilisation, and drawdown, plus a transaction
  cost penalty. Multipliers auto-tune across training steps.
- `rl/fee_ratio_reward_shaping.py` — Step-function penalty mapping based on
  the realized fee-to-profit ratio. Caches state through `trading.fee_ratio_gate`
  and amplifies penalties on losses when the ratio is high.
- `rl/calibrated_confidence.py` — Loads a temperature parameter and feature
  flag from legacy Redis, applies `logit/T` then sigmoid, blends with raw
  confidence, and logs comparisons to a Redis stream.
- `rl/temperature_calibration.py` — Offline temperature optimizer (NLL/ECE)
  used to choose the T parameter consumed by `calibrated_confidence.py`.
- `rl/environment.py` — Gymnasium env with step/reset/reward orchestration,
  ~1455 lines of behavior. Bridges feature pipeline, fees, leverage, and
  action ontology into the training step.
- `rl/gymnasium_wrapper.py` — Vectorized SB3-compatible wrapping for parallel
  envs.
- `rl/agents/masa_agent.py` — MASA agent policy used to blend with PPO logits.
- `rl/enhanced_architectures.py` — PyTorch policy network definitions and
  feature extractors.
- `rl/hybrid_trainer.py` — The ~3.16 MB hybrid training loop file that drives
  training, checkpoint save/load/promotion, and emits signals to legacy Redis.

## What V2 ports in this subproject

| Legacy behavior | V2 module | Status |
|---|---|---|
| Observation schema descriptor | `v2/backend/app/services/rl_core/observation_schema.py` | **PORTED** as field-level descriptor (legacy was slice-level). |
| Realized PnL credit + fee/slippage penalties | `v2/backend/app/services/rl_core/reward.py` (`compute_constrained_reward`) | **PARTIALLY PORTED** (paper-only, fixed weights). |
| Fee-ratio step penalty | `v2/backend/app/services/rl_core/reward.py` | **PARTIALLY PORTED** (no stateful fee-ratio gate). |
| Drawdown Lagrangian penalty | `v2/backend/app/services/rl_core/reward.py` | **PARTIALLY PORTED** (fixed multiplier; no auto-tune). |
| No-trade-correct credit | `v2/backend/app/services/rl_core/reward.py` | **PORTED** (paper-only). |
| Reward hard clamp | `v2/backend/app/services/rl_core/reward.py` | **PORTED**. |
| Checkpoint filename parsing | `v2/backend/app/services/rl_core/checkpoint_metadata.py` | **PORTED** (no weight load). |
| Temperature scaling math | `v2/backend/app/services/rl_core/service.py::calibrate_confidence` | **PORTED** (no Redis IO; explicit identity fallback). |

## What is NOT ported (MISSING_IN_V2)

- **PPO+MASA policy network** (PyTorch model). V2 must not import torch.
- **Gymnasium env step/reset/reward loop** (`rl/environment.py`,
  ~1455 lines). The full state transition + action decoding + feature
  composition stays in the legacy runtime.
- **GPU training loop** and SB3 vectorized wrapping.
- **Unified feature builder tensor assembly** (depends on Subproject 2).
- **Checkpoint weight loader.** V2 only parses filenames and metadata.
- **Lagrangian multiplier state persistence** across training steps.
- **Offline temperature optimizer** (`rl/temperature_calibration.py`).
- **Redis signal emission pipeline.** V2 never writes to any Redis instance.

## Mapping to the migration completion contract

This subproject does NOT claim `MIGRATED_CODEX_PASS`. Under the contract:

- Clauses 1, 2, 4, 5, 6, 7, 8, 10, 11, 12, 13 are satisfied for the ported
  pieces (paths identified, SHA256 cited, config/env documented, behavior
  mapping done, V2 implementation present with tests, public runtime payload
  emitted, no legacy Redis writes, no exchange mutation, `live_gate` and
  `live_symbols` remain blocked).
- Clause 3 (full closed dependency graph) and Clause 9 (Codex PASS) are NOT
  yet satisfied at the subproject level; they are deferred to the
  `codex_review/` workflow for this migration.

Therefore the subproject is classified `PARTIALLY_MIGRATED` and the
`go_no_go` label emitted is
`SUBPROJECT_1_RL_CORE_PARTIALLY_MIGRATED_PAPER_ONLY`.

## Live readiness statement

Live remains `blocked_human_only`. V2 still depends on the legacy runtime for
policy decisions and training. This subproject does not change that and does
not authorize fills, canary, or legacy shutdown.
