# Trainer, PPO, MASA, Replay, and Checkpoints

> **2026-07-17 source addendum:** temporal windows now require canonical decision time; labels carry resolved availability; in-cycle validation is chronological and label-purged; checkpoint promotion requires positive uncertainty-adjusted held-out serving-policy edge. Trusted replay separates side-specific after-cost counterfactual targets from actual behavior outcome. PPO freezes the entry action and requires categorical `RAW_LOGITS_SOFTMAX_V1` sampling; the current deterministic expected-move-aligned selector is explicitly PPO-ineligible and outcome-supervised. Trajectory semantics, global final-holdout isolation, and complete upstream PIT lineage remain open. Prediction publication propagates successful replay metadata to the caller and suppresses lineage on publication failure. See [../ADAPTIVE_END_TO_END_CONTROL_AND_ACCOUNTING_2026-07-17.md](../ADAPTIVE_END_TO_END_CONTROL_AND_ACCOUNTING_2026-07-17.md).

> **Leverage-study addendum:** `leverage_margin_exploration` v2 removes the old algebraic 1x tie and can select 1x/2x/3x only from complete PIT lower-bound-edge/account/tail evidence under tighten-only safety caps. The existing `policy_backtest` caller does not provide that contract and now returns no recommendation. This is study-only; it does not size paper or live orders.

> **Feature-ABI generation warning:** the 477-feature/1,908-value figures below describe the 2026-07-16 audited deployment. The intended 2026-07-17 worktree contract resolves 446 ordered features and 1,784 model values, and the reconciled trainer/PIT suite passed 374 tests at its recorded source cut. That source/test reconciliation does not migrate or identify deployed checkpoints, caches, replay rows, backtests, or historical predictions. Treat 477/1,908 as the audited deployed/history generation and 446/1,784 as the intended current source generation until a versioned feature-spec digest and checkpoint/data migration prove compatibility.

Audit date: 2026-07-16

Repository revision observed during the audit: `2dd584d632790c54c1054f7c4453cb9d36d0987c`

Scope: V2 native hybrid trainer only; documentation analysis, no trainer, strategy, risk, or execution behavior was changed.

## 1. Executive truth

The currently deployed learner is a 38,958,347-parameter PyTorch residual MLP plus a GRU temporal branch. It receives a 16-frame sequence of 1,908-float vectors built from 477 ordered features and three 477-element masks. It exposes seven policy logits and four scalar heads: value, expected move, confidence, and MASA.

The name `PPO` is only conditionally accurate. Current native serving is deterministic expected-move alignment, so its paper rows are explicitly excluded from PPO and use outcome supervision. A clipped surrogate can activate only for a row whose immutable action was genuinely sampled categorically from `RAW_LOGITS_SOFTMAX_V1`; current/new probabilities are then gathered at that same action. No action-generation repair in this turn creates such rows. There is no GAE, temporal return recursion, or bootstrap, and configured `gamma` is reported but unused. The value head is trained against expected directional move divided by 100, not a discounted return.

The most important rebuild and change-safety conclusions are:

1. The exact ordered `FEATURE_SPEC` is an ABI. Its audit-time length is 477 and the model ABI is 1,908 floats per frame.
2. Training windows now use canonical `TrainingExample.decision_time` and fail closed without it; upstream per-source availability truth and padding-mask use remain open.
3. Online validation now uses a chronological label-horizon-purged split and cannot promote a checkpoint unless that split is PIT-safe and serving-policy after-cost edge has a positive one-standard-error lower bound.
4. The published final holdout window is still not enforced as one immutable exclusion ledger across all online/offline consumers. Calling the final holdout untouched is therefore not currently provable.
5. Model and checkpoint IDs identify a subset of architecture settings, not learned weight content. Live and offline artifacts can have the same IDs but different bytes and predictions.
6. AdamW and AMP scaler state are recreated on every `train()` call. Several head biases are then mutated directly outside the optimizer.
7. Replay, paper feedback, shaped reward, and prediction gating use inconsistent cost assumptions and, in places, different target semantics.
8. Checkpoint weight and manifest files are individually atomic but are not an atomic pair, are not content-addressed, and have no interprocess writer lock.
9. Prediction publication now commits persisted replay metadata back to the caller and suppresses lineage on a false publication result. Deployed failure injection and multi-key transactional proof remain absent.
10. The running RL-core sidecar does not load the native hybrid model or its NPZ. It publishes a separate sidecar and stamps checkpoint evidence while explicitly declaring that the weights were not loaded into that process.

These are reconstruction findings, not authorization to alter training, risk, paper, or live behavior. Any fix affecting the objective, labels, gating, cost model, action semantics, or checkpoint promotion requires explicit operator approval and a new offline proof.

## 2. Authoritative source map

The rebuild boundary is distributed across these files:

| Responsibility | Authoritative implementation |
|---|---|
| Ordered feature ABI and tensor assembly | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/tensor_builder.py:17-670`, `673-697`, `1772-1810` |
| Training record and feedback/replay loaders | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py:136-172`, `424-619`, `1369-1399`, `1481-1809`, `1935-1986`, `2116-2233` |
| Temporal training windows | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/temporal_windowing.py:24-179` |
| Network, inference selector, temporal inference buffer, NPZ format | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/model.py:56-140`, `180-408`, `440-526`, `528-733` |
| Actions and baseline runtime config | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/config.py:9-35`, `94-128` |
| MASA adapter | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/masa.py:7-41` |
| Confidence calibration | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/confidence.py:121-147`, `168-233` |
| Trainer row selection, objective, optimizer, direct mutations | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/ppo_trainer.py:211-479`, `481-770`, `916-1785`, `2074-2233` |
| Shaped reward and paper environment proof | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/rewards.py:7-100`, `environment.py:13-127`, `parallel_env.py:41-135` |
| Trusted replay target construction | `v2/backend/app/services/native_trainer/trusted_replay/dataset.py:250-412` |
| Replay temporal split manifest | `v2/backend/app/services/native_trainer/trusted_replay/bootstrap.py:220-245` |
| Checkpoint manager | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/checkpoint.py:19-269` |
| Online cycle, promotion, prediction order | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/runtime.py:84-123`, `152-355`, `444-735` |
| Persistent replay buffer, GPU controller, prefetch | `v2/backend/app/services/native_trainer/persistent_cuda_trainer_runtime.py:2569-2703`, `2820-2908`, `3054-3102` |
| Prediction construction and publication | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/publisher.py:893-1130`, `1172-1515` |
| Runtime trust validation | `v2/backend/app/services/market_state_integrity/trust.py:320-384` |
| Paper close-to-PPO materialization | `v2/backend/app/cli/v2_trade_management_paper_loop.py:1268-1445`, `30175-30220` |
| Offline batch training and pickle cache | `v2/backend/app/cli/v2_trainer_offline_batch_train.py:242-345`, `351-404`, `407-615` |
| Offline point-in-time report | `v2/backend/app/cli/v2_trainer_offline_hyperparameter_sweep.py:68-147` |
| H2L split, scoring, risk gate, promotion | `v2/backend/app/cli/v2_trainer_h2l_promote.py:36-179`, `182-355`, `358-484` |
| Scheduled offline pretrain | `v2/backend/app/cli/v2_trainer_scheduled_pretrain.py:110-225` |
| Continuous offline loop | `tools/continuous_offline_gpu_trainer_loop.sh:1-82` |
| Separate RL-core sidecar | `v2/backend/app/cli/v2_rl_core_inference_loop.py:1-30`, `198-370` |

The systemd files under `/home/wali/.config/systemd/user/` are deployment state, not repository source. They are nevertheless the effective configuration at the audit time and must be captured for a faithful copy.

## 3. Audit-time deployed state

At approximately 2026-07-16 07:58 UTC, these services were active:

| Service | Role | Audit-time effective facts |
|---|---|---|
| `ai-bot-v2-native-cuda-trainer-persistent.service` | Online resident train/predict/publish loop | `--interval-seconds 5`, `--max-rows 16384`; hidden 2048, four residual blocks, GRU temporal encoder, projection 256, checkpoint validation guard disabled. See `/home/wali/.config/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.service:7-20`. |
| `ai-bot-v2-continuous-offline-gpu-trainer.service` | Repeated offline warm-start training to an offline directory | Nice 15, CPU weight 20, idle I/O, 150-second inter-run interval, five epochs, batch 1,024, 40% CUDA memory cap. See `/home/wali/.config/systemd/user/ai-bot-v2-continuous-offline-gpu-trainer.service:6-47`. |
| `ai-bot-v2-trainer-scheduled-pretrain.timer` | Scheduled prefix/suffix H2L run | Active; the observed next run was 05:16:11 EDT. The service passes both `--auto-promote` and `--auto-restart`. Its comment says no auto-restart, but its `ExecStart` contains the flag. See `/home/wali/.config/systemd/user/ai-bot-v2-trainer-scheduled-pretrain.service:13-16`. |
| `ai-bot-v2-rl-core-inference-loop.service` | Separate paper-only inference sidecar | 60-second loop; does not own primary prediction keys. See `/home/wali/.config/systemd/user/ai-bot-v2-rl-core-inference-loop.service:4-16`. |

The hybrid status sampled at `2026-07-16T07:57:02Z` reported 477 features, 1,908 input values, hidden 2,048, four residual blocks, GRU sequence length 16, a 16,384-row replay buffer, and `online_learning_status=WEIGHTS_UPDATING`. It also reported the checkpoint guard disabled and promotion allowed for reason `VALIDATION_GUARD_DISABLED`.

The separately stored metrics object sampled during the same inspection represented 2,015 accepted outcome rows, 1,612 training rows, 403 validation rows, 32 optimizer steps, zero PPO rows, `ppo_objective_used=false`, learning rate `0.0001`, entropy coefficient `0.01`, gamma `0.99` with `ppo_gamma_applied_to_advantage=false`, weight decay `0.02`, and dropout `0.1`. Its validation loss moved from approximately `18.20479584` to `18.21330070` and its reported train/validation gap was `18.074326`. Status and metrics are separate mutable Redis values and may describe adjacent cycles if read between writes; they are evidence, not an atomic snapshot.

The audit-time active architecture produced:

- model ID `v2_hybrid_policy_4260cdcc506bf3393b2ac488`;
- checkpoint ID `v2_hybrid_ckpt_4260cdcc506bf3393b2ac488`;
- 38,958,347 trainable parameters;
- 60 entries in `state_dict()`;
- live NPZ at 07:58:15Z: 144,237,406 bytes, SHA-256 `b3bff3ba0a240b963a930b4fc1507207e4147fd033db9a081874db11dd902d57`;
- offline NPZ at 07:57:27Z: 144,243,736 bytes, SHA-256 `f9932cb13c83df236258221977a0ef3f58ec426187e01ddcea09fe6627387988`.

The live and offline artifacts had the same model and checkpoint IDs but different bytes. This is direct evidence that those IDs are architecture-lineage labels, not learned-model identities.

## 4. End-to-end data and control flow

One resident cycle follows this order (`runtime.py:444-735`):

1. Validate that the trainer remains paper/shadow only.
2. Build the current prediction grid from current snapshots.
3. Load closed-trade/counterfactual/exploration feedback rows.
4. Advance the trusted-replay frontier cursor.
5. Optionally drain or synchronously build historical backfill rows.
6. Append `[backfill, frontier replay, feedback]` to the process-local replay deque.
7. Keep only the deque tail up to the configured row limit.
8. Infer input dimension from the first training row, or a prediction row if training is empty.
9. Construct a fresh model object and load the latest compatible NPZ.
10. Filter trusted rows; choose PPO, outcome, or mixed lane; take a deterministic prefix; split its tail into validation.
11. Rebuild AdamW, repeat full-batch optimizer steps, apply direct head mutations, and calculate validation metrics.
12. Promote or restore a checkpoint according to the promotion decision.
13. Run a policy backtest and shaped-environment proof for evidence.
14. Run inference using the promoted/restored in-memory model.
15. Build primary prediction payloads, attempt publication, then publish orchestrator/risk/paper lineage.
16. Publish hybrid status and metrics.

Two consequences are easy to miss:

- Prediction uses the post-training model if promotion succeeds, or the restored prior model if promotion fails (`runtime.py:575-620`, `675-717`).
- When the feedback lane alone fills all 16,384 deque slots, earlier backfill and frontier rows appended in the same cycle are evicted before selection. The audit-time status showed `fresh_examples_built=16384` and 346 frontier rows, while the final buffer was 16,384, so insertion order can make the nominal replay lanes contribute no final rows.

## 5. Tensor ABI: historical 477/1,908 and current 446/1,784 generations

### 5.1 Ordered feature contract

`FEATURE_SPEC` is an ordered tuple of `(feature_name, source_label)` pairs (`tensor_builder.py:17-670`). At the 2026-07-16 deployed audit time:

- feature count: 477;
- feature names were unique;
- ordered-spec SHA-256, using compact JSON serialization of the imported tuple: `263b7ce4feae6fcbc34ff4aad593bb8bde7aa3e6469d6662ab8b5186c200b239`.

The ordered source-label distribution was:

| Source label | Features | Source label | Features |
|---|---:|---|---:|
| `v2:altdata:aicoin` | 11 | `v2:altdata:confluence` | 15 |
| `v2:altdata:lunarcrush` | 1 | `v2:altdata:nansen` | 2 |
| `v2:altdata:public_intel` | 10 | `v2:altdata:santiment` | 17 |
| `v2:altdata:symbol_score` | 10 | `v2:altdata:whale_walls` | 11 |
| `v2:features:latest` | 57 | `v2:features:moralis` | 7 |
| `v2:features:ta` | 11 | `v2:features:ta_full` | 155 |
| `v2:features:ta_full:1h` | 8 | `v2:liquidations:events` | 2 |
| `v2:liquidations:levels` | 6 | `v2:market:cvd` | 3 |
| `v2:market:funding` | 1 | `v2:market:fvg` | 12 |
| `v2:market:liquidation_levels` | 14 | `v2:market:liquidations:aggregate` | 3 |
| `v2:market:liquidity_zones` | 8 | `v2:market:long_short` | 3 |
| `v2:market:microstructure` | 9 | `v2:market:ohlcv` | 15 |
| `v2:market:open_interest` | 1 | `v2:market:open_interest_hist` | 2 |
| `v2:market:orderbook` | 12 | `v2:market:prices` | 5 |
| `v2:market:structure` | 11 | `v2:market:sweep_risk` | 5 |
| `v2:market:trade_tape_features` | 3 | `v2:market:volume_profile` | 5 |
| `v2:market:vwap` | 4 | `v2:microstructure:adversarial_features` | 3 |
| `v2:microstructure:cascade_context` | 7 | `v2:microstructure:cross_venue_confirmation` | 1 |
| `v2:microstructure:feed_quality` | 1 | `v2:microstructure:sweep_risk` | 2 |
| `v2:microstructure:trade_tape_confirmation` | 1 | `v2:microstructure:trust_score` | 6 |
| `v2:orchestrator:decisions` | 1 | `v2:orderbook:features` | 13 |
| `v2:paper:positions` | 2 | `v2:risk:decisions` | 1 |

The complete per-feature order should be regenerated directly from `FEATURE_SPEC`; another component document, `DATA_TEMPORAL_LINEAGE_AND_FEATURES.md`, owns the broader feature/source lineage inventory. A copy implementation must never sort this tuple or reconstruct it from a set or mapping.

The current worktree is a later schema generation. Commit `e88e2318e3` removed 31 AiCoin/Nansen/LunarCrush/Santiment entries by operator directive while retaining 155 `taf_*` entries, leaving 446 ordered features and 1,784 concatenated values. The historical distribution/table above explains old deployed checkpoints and must not be silently relabeled as current. Local count/width tests now assert 446/1,784 and the combined trainer/pipeline suite passes 374 tests; cross-generation checkpoint/replay/cache compatibility remains RE-044.

### 5.2 Record and four contiguous blocks

`FeatureTensorRecord` carries the fields defined at `tensor_builder.py:673-688`. Its `model_vector` is concatenated exactly as follows (`tensor_builder.py:690-697`):

| Offset, audit-time | Length | Meaning | Encoding |
|---|---:|---|---|
| `[0, 477)` | 477 | `values` | finite feature value; missing/non-finite becomes `0.0` |
| `[477, 954)` | 477 | `missing_mask` | `1.0` when missing, else `0.0` |
| `[954, 1431)` | 477 | `stale_mask` | `1.0` when stale, else `0.0` |
| `[1431, 1908)` | 477 | `source_availability` | `1.0` when the value is present, else `0.0` |

For the current 446-feature generation, the same concatenation contract uses `[0,446)`, `[446,892)`, `[892,1338)`, and `[1338,1784)` respectively. Segment meaning did not change; width and ordered feature membership did.

The builder implements those masks at `tensor_builder.py:1772-1789`. `source_availability` is currently the complement of missingness. It is not proof that a source was point-in-time available, nor does it encode `available_at <= decision_time`. The record also contains a duplicate-named `source_availability_vector`; the returned record sets it to the same vector.

Coverage is `100 * nonmissing / 477` (`tensor_builder.py:1791-1792`). Stale values remain in `values`; staleness is represented by the parallel mask. Missing values are zero-filled, so consuming values without the masks makes a real zero indistinguishable from missing data.

### 5.3 Tensor identity limitations

`tensor_id` hashes symbol, timeframe, snapshot ID, values, missing mask, and stale mask (`tensor_builder.py:1793-1800`). It does not hash:

- source availability;
- ordered feature names or source labels;
- the temporal envelope (`feature_cutoff`, `available_at`, `decision_time`);
- candle-finality evidence;
- source hashes;
- code revision or feature-spec digest.

The same tensor ID can therefore survive changes in non-hashed lineage. Caches and overlap checks that treat it as a complete sample identity inherit this limitation.

### 5.4 Valid-zero fallthrough defects

Several feature fallbacks use Python `or`, so a valid numeric zero is treated as absent:

- the generic feature fallback at `tensor_builder.py:1633-1636`;
- spread, depth imbalance, micro-price, and toxicity fallback assignments at `tensor_builder.py:1697-1700`.

This can silently replace a real zero with another source or `None`. A rebuild must use explicit `is None` semantics for numeric fields and add zero-preservation tests.

## 6. Temporal sequence construction

### 6.1 Intended behavior

`build_example_windows()` groups rows by uppercase symbol and lowercase timeframe, sorts each group by decision time, takes the current and preceding frames, and left-pads by repeating the oldest frame (`temporal_windowing.py:74-130`). The intended output is 16 frames, oldest first, with the current frame last.

### 6.2 Repaired training chronology contract

`TrainingExample.__post_init__` now resolves a top-level immutable `decision_time` from the explicit field or named trust-row decision fields and canonicalizes it to UTC microseconds. Missing/invalid time remains `None`. `build_example_windows()` rejects rows without a usable positive time, sorts each `(symbol,timeframe)` group by `(decision_time, original_index)`, and asserts that every frame is no newer than its target. `model_batch_tensor()` raises when temporal mode lacks a lookup/window; it cannot repeat the current frame to conceal missing chronology.

This removes the active list-index chronology fallback even though incoming assembly can still be backfill/frontier/feedback and PPO/outcome priority order. Rows with missing temporal evidence now lose their causal window rather than borrowing that input order. Remaining PIT risk is upstream: a canonical row timestamp cannot prove every enriched field preserved its own truthful `available_at`.

### 6.3 Training/validation history coupling and padding

The trainer builds one lookup from `train_rows + validation_rows`. Validation frames may use earlier training frames, which is causal history only because the windower now orders by immutable decision time and asserts no future frame.

`WindowedExample` builds a `pad_mask`, but `build_window_lookup()` stores only the window (`temporal_windowing.py:133-140`). `model_batch_tensor()` never returns the mask (`143-179`). The GRU therefore sees repeated left-padding frames as real observations.

The input cache fingerprint limitation remains: it does not content-bind every ordered row/value/time/label. Different equal-length batches with matching sampled boundary tokens can theoretically reuse stale tensors.

### 6.4 Inference temporal state

Inference keeps process-lifetime buffers keyed first by `(input_dim, seq_len)` and then `(symbol, timeframe)` (`model.py:105-120`, `553-588`). This keeps history alive even though the resident cycle creates a fresh model object.

The buffer key omits model ID, checkpoint hash, feature-spec digest, temporal hidden size, and temporal projection size. A checkpoint or learned-weight change with the same input width and sequence length inherits frames collected under the prior model. Frames are deduplicated by snapshot/tensor ID but are not ordered or rejected by timestamp. Process restart clears all temporal state; checkpoint restore does not restore it.

## 7. Model architecture

### 7.1 Source defaults versus deployed configuration

| Setting | Source default | Audit-time deployment | Identity coverage |
|---|---:|---:|---|
| Input feature count | dynamic | 477 | indirectly, via input dimension |
| Input dimension | dynamic, `4 * features` | 1,908 | yes |
| Hidden width | 1,024 | 2,048 | yes |
| Residual blocks | 3 | 4 | yes |
| Dropout | 0.10 | 0.10 | **no** |
| Spatial attention | off | off | included only when effectively enabled |
| Requested attention heads | 4 | 4, inactive | included only when attention is enabled |
| Temporal encoder | off | GRU | yes, enabled kind only |
| Temporal sequence length | 16 | 16 | **no** |
| Temporal hidden width | 256 | 256 | yes when enabled |
| Temporal projection width | 256 | 256 | yes when enabled |
| Seed | `0xC0DE_55` | same unless constructor changed | yes |
| Action count/order | seven fixed labels | seven | **not explicitly hashed** |

Source defaults are at `model.py:59-104`. Deployment overrides are at `/home/wali/.config/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.service:10-15`.

The source-default, non-temporal 1,024-by-3 network has 8,280,075 parameters. The deployed 2,048-by-4 GRU network has 38,958,347.

### 7.2 Exact deployed forward topology

For a batch of windows `x` with shape `(B, 16, 1908)` (`model.py:229-354`):

1. Replace NaN and infinities, clamp absolute magnitude to 1,000,000, and apply signed `log1p` normalization.
2. Temporal branch, every frame:
   - Linear `1908 -> 256`;
   - LayerNorm 256;
   - GELU;
   - one-layer, batch-first GRU `256 -> 256`;
   - take the final GRU output;
   - Linear `256 -> 2048`, LayerNorm 2048, GELU.
3. Current-frame branch, newest frame only:
   - Linear `1908 -> 2048`;
   - LayerNorm 2048;
   - GELU.
4. Add temporal fusion output to the current-frame projection.
5. Run four residual blocks. Each block is Linear `2048 -> 2048`, LayerNorm, GELU, Dropout 0.10, Linear `2048 -> 2048`, LayerNorm, residual addition, GELU.
6. Apply encoder LayerNorm 2048.
7. Apply five heads:
   - policy: Linear `2048 -> 7`;
   - value: Linear `2048 -> 1`, raw output;
   - expected move: Linear `2048 -> 1`, then `120 * tanh`, in bps;
   - confidence: Linear `2048 -> 1`, then sigmoid;
   - MASA: Linear `2048 -> 1`, then tanh.

The 60 saved state tensors are grouped as:

| Module | State shapes |
|---|---|
| `temporal_input_proj.0` | weight `(256,1908)`, bias `(256)` |
| `temporal_input_proj.1` | LayerNorm weight/bias `(256)` |
| `temporal_gru` | `weight_ih_l0` and `weight_hh_l0` `(768,256)`; two biases `(768)` |
| `temporal_fuse.0` | weight `(2048,256)`, bias `(2048)` |
| `temporal_fuse.1` | LayerNorm weight/bias `(2048)` |
| `input_projection.0` | weight `(2048,1908)`, bias `(2048)` |
| `input_projection.1` | LayerNorm weight/bias `(2048)` |
| each `residual_blocks.0..3` | two weights `(2048,2048)`, two biases `(2048)`, two LayerNorm weight/bias pairs `(2048)` |
| `encoder_norm` | weight/bias `(2048)` |
| `policy_head` | weight `(7,2048)`, bias `(7)` |
| each scalar head | weight `(1,2048)`, bias `(1)` |

Dropout has no saved tensor. CPU/CUDA device, precision mode, and runtime temporal buffers are not saved.

### 7.3 Reproducibility settings

CUDA initialization enables TF32, cuDNN benchmark mode, flash/memory-efficient scaled dot-product attention when available, and explicitly sets cuDNN deterministic mode false (`model.py:180-210`). A fixed seed therefore does not guarantee bit-for-bit repeatability across runs, devices, PyTorch/CUDA versions, or kernel selection.

### 7.4 Model identity

The model ID hashes a string containing input dimension, seed, hidden width, residual-block count, effective attention configuration when enabled, and temporal kind/hidden/projection when enabled (`model.py:125-137`). It omits:

- learned parameters;
- dropout;
- temporal sequence length;
- action label order/count;
- activation functions and head transforms;
- normalization and finite-value policy;
- software revision and PyTorch version;
- confidence calibration state;
- MASA blend formula.

Changing an omitted behavior can silently retain the same ID and load an old checkpoint. A rebuild should separate `architecture_id`, `training_contract_id`, `feature_schema_id`, and content-derived `weights_id`.

## 8. Actions, inference selection, confidence, and MASA

### 8.1 Seven-action contract

The order is fixed at `config.py:17-27`:

| Index | Label | Selected by current inference selector? |
|---:|---|---|
| 0 | `hold` | yes |
| 1 | `long` | yes |
| 2 | `short` | yes |
| 3 | `close_long` | no |
| 4 | `close_short` | no |
| 5 | `reduce` | no |
| 6 | `hedge_reserved_fail_closed` | no |

The policy head still emits and trains all seven logits, but `_expected_move_aligned_policy()` chooses only among the opening triple (`model.py:378-408`):

- expected move `>= +4` bps selects long only if raw opening argmax is long; otherwise hold;
- expected move `<= -4` bps selects short only if raw opening argmax is short; otherwise hold;
- otherwise hold;
- the probabilities are directionally adjusted and renormalized, and the selected probability is forced above the other opening probabilities.

This means close/reduce/hedge classes can affect normalization and training loss but can never be returned by the normal hybrid inference path. Any change to action order affects policy-head tensor meaning, labels, saved weights, paper lineage, PPO old probabilities, H2L scoring, and downstream state machines.

### 8.2 Confidence

For the torch path, raw confidence is the maximum of the selected adjusted action probability and the learned confidence head (`model.py:653-680`). It then passes through temperature scaling and proportional data-quality downrating (`confidence.py:168-233`). Temperature resolution is:

1. `V2_TRAINER_CONFIDENCE_TEMPERATURE`;
2. an mtime-cached JSON state file;
3. default 1.4 (`confidence.py:121-147`).

The confidence target during training is `clamp(abs(expected_move_target) / 100, 0, 1)`. It is not an empirical win probability target. The later temperature calibration can use outcomes, but the head itself is supervised by move magnitude.

### 8.3 MASA is a scalar auxiliary blend

The current MASA implementation is not a multi-agent system. `V2MASAAdapter.evaluate()` computes (`masa.py:23-40`):

- `directional = P(long) - P(short)`;
- `edge = clamp(expected_move_bps / 100, -1, 1)`;
- `coverage = clamp(data_coverage_percent / 100, 0, 1)`;
- adapter signal `= clamp(0.6 * directional + 0.4 * edge, -1, 1) * coverage`;
- auxiliary target `= edge * coverage`.

Torch inference returns `0.5 * learned_masa_head + 0.5 * adapter_signal` (`model.py:663-680`). CPU fallback returns only the adapter signal. Training does not use the adapter's coverage-weighted auxiliary target; it trains the learned head against `tanh(expected_move_training_target / 100)` (`ppo_trainer.py:1180-1191`, `1344-1349`). This is a train/serve target mismatch.

### 8.4 Runtime after-cost gate

Prediction construction applies a 12-bps default round trip, derived from two sides of 5-bps fee plus 1-bps slippage (`config.py:104-105`, `runtime.py:683-690`). It subtracts 12 from long expected move, adds 12 to short expected move, and assigns zero to non-directional actions (`publisher.py:893-940`).

Paper eligibility requires coverage at least 70%, calibrated confidence at least 0.55, action/edge direction agreement, absolute after-cost edge at least 4 bps, and successful integrity/trust/replay gates (`publisher.py:924-1006`). These gates do not change the training labels already loaded.

## 9. Training-row lanes and deterministic selection

### 9.1 `TrainingExample` contract

The trainer consumes:

- `symbol` and `timeframe`;
- `tensor`;
- `label_action_index`;
- `label_expected_move_after_cost_bps`;
- `payload_keys`;
- `row_classification`;
- optional `trust_row`;
- immutable resolved `decision_time` and `label_available_at`, plus label timing source/validity/error;
- immutable `behavior_action_index` and `behavior_action`.

Most rollout fields, outcome data, sample identity, and execution lineage still live inside the untyped `trust_row` mapping. Misspelling a key usually changes lane eligibility rather than causing a schema error. Decision/label timing and behavior-action identity are resolved once so later trust-row mutation cannot silently change split or action semantics.

### 9.2 Lane classification

After trust filtering, `train()` partitions rows (`ppo_trainer.py:294-440`):

- PPO row: has all required on-policy fields;
- outcome row: has an `outcome_targets` mapping with realized net bps and directional outcome, plus `realized_after_cost_reward`, and explicitly says expected move was not used as realized reward;
- mixed: PPO rows are put first, then outcome-only rows;
- PPO-only: only PPO rows are retained;
- outcome-only: only outcome rows are retained.

Rows accepted by trust filtering but satisfying neither contract are discarded from learning. The chosen lane takes `learnable_rows[:tuned_batch_size]`, then `_chronological_purged_split` restores chronological order for the selected population. By default it begins with a nominal last 20%, keeps every equal decision timestamp on the validation side, and purges candidate training rows whose outcome label was not available strictly before the validation boundary. If timing/boundary/purge proof fails, all selected rows remain candidate-learning rows, validation is empty, and promotion receives `validation_split_pit_safe=false`.

### 9.3 PPO eligibility fields

`_has_on_policy_ppo_fields()` now requires:

- `old_log_prob`;
- `old_value`;
- `reward`;
- `done`;
- `rollout_id`;
- either `trajectory_index` or `trajectory_step`;
- finite numeric `old_log_prob`, `old_value`, and `reward`;
- a boolean `done`;
- an immutable `behavior_action_index`/`behavior_action` pair that agrees with `ACTION_LABELS`, vector bounds, and every present behavior/legacy selected-action alias;
- `behavior_policy_sampling_mode=CATEGORICAL_SAMPLE`;
- `behavior_policy_distribution_contract=RAW_LOGITS_SOFTMAX_V1`.

`TrainingExample.__post_init__` freezes that identity from canonical behavior fields or the entry-time `selected_action_index`/`selected_action` aliases. It deliberately never uses hindsight `label_action_index`. Missing, out-of-range, non-integral, or conflicting identity disables PPO for the row. If its realized outcome contract is otherwise valid, the row may still train through the outcome-supervised lane.

The current publisher does **not** sample. It labels its selector `DETERMINISTIC_ARGMAX_ALIGNMENT` and its adjusted probability transform `EXPECTED_MOVE_ALIGNED_POLICY_V1`, sets the on-policy-present flag false, and records `DETERMINISTIC_POLICY_NOT_ON_POLICY_SAMPLED`. Replay/prediction/signal publication, paper entry enrichment, bounded entry snapshot, accepted-fill persistence, lifecycle/outcome construction, and closed feedback preserve that evidence. Therefore present native-policy paper rows are outcome-supervised, not PPO, even if they carry entry probability/value fields.

To create a genuine PPO row, action generation itself—not a later annotation—must draw a categorical action from the exact raw-softmax distribution, persist the sampled action and distribution/version, and keep that immutable identity through close feedback. This task did not enable such sampling.

Only `old_log_prob`, `old_value`, and `reward` affect the objective. `done`, rollout ID, and trajectory position are eligibility flags only. They are not used to group, order, bootstrap, or terminate trajectories.

## 10. The actual objective

### 10.1 Supervised component

For every selected training row, the base supervised loss is (`ppo_trainer.py:1180-1191`):

`CE(policy_logits, policy_target_action)`

`+ 0.01 * MSE(expected_move, move_target_bps)`

`+ 0.001 * MSE(value, move_target_bps / 100)`

`+ 0.001 * MSE(masa, tanh(move_target_bps / 100))`

`+ 0.05 * MSE(confidence, clamp(abs(move_target_bps) / 100, 0, 1))`.

Expected-move labels are sanitized and clamped to `[-120, +120]` before training (`ppo_trainer.py:1001-1013`).

### 10.2 PPO component

When at least one PPO row exists and the lane is PPO or mixed:

- stored advantage is `reward - old_value` (`ppo_trainer.py:1206-1229`);
- advantage is clamped to `[-5, +5]` (`1325`);
- log-ratio is clamped to `[-20, +20]`;
- ratio is exponentiated and the usual epsilon-clipped minimum surrogate is used (`1320-1328`);
- default epsilon is 0.2.

The total PPO-active loss is (`ppo_trainer.py:1351-1360`):

`supervised_loss + 0.1 * clipped_policy_loss + 0.1 * value_loss + 0.01 * move_loss + 0.1 * masa_loss + 0.05 * confidence_loss - entropy_coefficient * entropy`.

Because the auxiliary losses are already in `supervised_loss`, the effective coefficients are:

| Term | Effective coefficient in PPO-active lane |
|---|---:|
| Policy cross entropy | 1.0 |
| Clipped PPO policy loss | 0.1 |
| Expected-move MSE | 0.02 |
| Value MSE against move/100 | 0.101 |
| MASA MSE | 0.101 |
| Confidence MSE | 0.10 |
| PPO-row entropy | `-entropy_coefficient`, default `-0.01` |

Only the clipped surrogate and entropy use the PPO-row mask. The supervised and auxiliary losses use the entire mixed batch.

Outcome-only mode is `supervised_loss - supervised_entropy_bonus * entropy`; the bonus defaults to zero (`ppo_trainer.py:1361-1366`). An optional differentiable tail-CVaR term can be enabled with `V2_TRAINER_TAIL_CVAR_WEIGHT`; its default is zero and its return proxy is `(P(long)-P(short)) * raw_move_target/100` over all rows (`1301-1378`).

### 10.3 PPO eligibility repair and remaining semantic breaks

The source now separates two formerly collapsed action tensors:

1. `behavior_actions` is the immutable entry action and controls the PPO current/new log-probability gather.
2. `policy_target_actions` is the hindsight/supervised label and controls cross entropy only. The single-direction guard can rewrite it to HOLD without changing the PPO gather.

The same-action half of the PPO invariant is repaired. The transformation mismatch is now prevented from becoming an active ratio by eligibility: only a categorically sampled `RAW_LOGITS_SOFTMAX_V1` entry may use the clipped objective. Current deterministic expected-move-aligned entries are explicitly excluded and remain outcome-supervised. This is deliberately a fail-closed repair, not evidence that PPO is flowing. Stored old log probability is still not numerically cross-checked against stored action probability, and full checkpoint/policy-transform/trajectory provenance is not yet one immutable contract.

### 10.4 No GAE, discounted return, or trajectory learning

`PPO_GAMMA` is parsed with default 0.99 (`ppo_trainer.py:270-276`) but metrics explicitly report that it is not applied (`1759-1763`). There is no lambda, GAE recursion, next-state value, return-to-go, advantage normalization, rollout grouping, or multi-step bootstrap. All observed paper PPO rows are one-step closed-position records.

The value head is not a PPO critic in the conventional sense. It is trained against expected directional move divided by 100 (`ppo_trainer.py:1185`, `1344`), while its entry output is subtracted from realized reward to form advantage. This mixes a move regressor with a return baseline.

### 10.5 Purged validation and serving-policy edge

Validation loss still evaluates only policy cross entropy plus `0.01 * expected-move MSE`; it omits value, MASA, confidence, entropy, tail-CVaR, and clipped PPO terms. A checkpoint can improve the optimized total while worsening this loss, or vice versa.

The split itself is now strict within the selected batch. `TrainingExample` resolves the latest valid outcome availability from explicit close/outcome timestamps and positive label horizons. `_chronological_purged_split` sorts by decision time, keeps timestamp ties together, and excludes every training row whose label overlaps the validation start. Invalid/missing timing produces zero represented validation rows and `validation_split_pit_safe=false`.

Promotion additionally evaluates the actual expected-move-aligned serving selector on all validation rows. LONG receives the signed after-cost label, SHORT its negative, and HOLD zero; HOLD remains in the denominator. It requires positive mean edge and `mean - one standard error > 0` over exactly the full validation set. Missing/negative evidence blocks promotion before validation-loss logic. This is stronger in-cycle evidence, but it is still not the repository-wide immutable final holdout: repeated online/offline consumers need a shared sample-exclusion ledger before any live-readiness claim.

### 10.6 Full-batch repeated steps

The optional DataLoader uses `batch_size=len(rows)` and `shuffle=False`, then consumes exactly its first batch (`ppo_trainer.py:1040-1050`). Every optimizer step in a call reuses the same full tensor (`1309+`). The external `batch_size` controls the selected row count; it does not create shuffled minibatches.

### 10.7 Optimizer recreation and direct mutations

`AdamW` is constructed inside `_train_torch()` on every call (`ppo_trainer.py:1120-1131`). Momentum and variance estimates are lost every online cycle and every offline epoch. AMP scaler state is also recreated. Neither is checkpointed.

After all optimizer steps, code directly mutates parameters under `no_grad` (`ppo_trainer.py:1470-1675`):

- expected-move bias adds `0.05 * mean(target) / 120`;
- policy bias adds `0.02 * class-balance nudge`;
- saturation recovery may replace the expected-move bias with a recentered value when both long and short targets exist and output/bias/mismatch thresholds fire.

These changes bypass AdamW state, gradient clipping, and loss attribution. The reported post-update supervised loss includes their effect, but no optimizer moment does.

There are two additional inconsistencies:

- the policy supervision guard rewrites a one-direction batch to hold, while the post-step policy nudge counts the raw action labels; a hold-plus-one-direction batch can receive opposing signals;
- temporal expected-move saturation recovery drops the sequence to the newest frame and computes the residual path without adding `temporal_fuse` (`ppo_trainer.py:1479-1495`), so its bias estimate does not match the deployed GRU forward path.

### 10.8 Class balancing and single-direction guard

Policy class weights are inverse-frequency over present classes, clipped to `[0.25, 4.0]`; absent classes receive zero weight (`ppo_trainer.py:2088-2105`). If a batch contains long but no short, or short but no long, all directional policy labels are rewritten to hold and their move targets are rewritten to zero (`ppo_trainer.py:1073-1096`, `2116-2199`).

This protects against one-sided collapse but can discard valid one-sided supervised market evidence. It no longer changes the action at which PPO new log probability is evaluated; PPO uses the frozen behavior action.

## 11. Reward, cost, and label semantics

### 11.1 Shaped reward is mostly an evidence path

`compute_hybrid_reward()` includes after-cost return, fees, slippage, drawdown, churn, correct no-trade credit, false-positive/negative penalties, liquidation penalty, and risk penalty (`rewards.py:25-82`). The parallel environment proof chooses each row's target action and runs a one-step paper environment (`parallel_env.py:41-135`). Runtime invokes this after training (`runtime.py:660-674`).

That proof does not generate PPO rows and its shaped total is not the outcome-supervised loss. `reward_stack_status()` can therefore say the full reward stack is active while the weight update did not consume it.

### 11.2 Zero fallback and double-cost defects

`compute_hybrid_reward()` uses `realized_after_cost_bps or expected_move_after_cost_bps` (`rewards.py:47`). A legitimate realized zero falls back to expected move.

It then subtracts fee and slippage again for trade actions (`rewards.py:48-49`). The environment already subtracts round-trip fee/slippage on close-long and close-short (`environment.py:65-71`) and otherwise passes an already-after-cost expected label (`81-87`). The proof can therefore double-charge costs. It is not safe to use its reward numbers as evidence of the trainer's actual economic objective without reconciling this path.

### 11.3 Cost-regime mismatch

The primary runtime/paper gate defaults to 12 bps round trip. `build_trusted_replay_row()` defaults to 2 bps (`trusted_replay/dataset.py:267-306`), and the main loader calls it without overriding that value (`data_loader.py:1619`). Replay training labels and current prediction gates therefore represent different execution-cost regimes.

Changing fee or slippage config changes prediction eligibility immediately but does not relabel existing replay rows, feedback caches, or offline pickle caches. A cost-model change requires a new label schema/version and replay regeneration.

### 11.4 Trusted replay labels

Trusted replay uses the first finalized candle at or after 5m, 15m, 1h, and 4h horizons; the 15-minute return becomes the label (`trusted_replay/dataset.py:291-306`). Directional action threshold is +/-4 bps. It is a future-candle outcome label, not executed PnL.

The 2026-07-17 repair computes both counterfactual sides independently:

`long_net = raw_return - costs`; `short_net = -raw_return - costs`.

It chooses a direction only when that side is positive and clears the threshold; otherwise it chooses HOLD. The row separately records counterfactual LONG/SHORT/selected net PnL and the actual normalized behavior action's net PnL/outcome. Costs can no longer turn a losing direction into a fabricated win, and `action_was_profitable` is based on the selected side's signed net result.

Remaining limitations:

- MFE and MAE are still raw future high/low price moves rather than side-relative excursions.
- the label is a best-action counterfactual from future finalized candles, not an executed behavior outcome;
- replay reward is counterfactual target net bps divided by 100, while outcome-only training uses directional target fields; it is not on-policy PPO reward;
- historical replay created under the old sign/cost schema must be versioned/regenerated rather than silently re-certified.

### 11.5 Closed-trade labels

Closed feedback translates explicit `directional_outcome` as UP -> `abs(PnL)`, DOWN -> `-abs(PnL)`, FLAT -> zero; without an explicit direction, a short's position PnL sign is inverted to recover price direction (`data_loader.py:2173-2188`). Realized reward is position PnL bps divided by 100 (`2191-2224`). Thus directional label and reward intentionally have different sign semantics for shorts.

The general snapshot matcher filters by symbol and optional timeframe but only requires that some entry prediction/snapshot ID is present; it does not compare those IDs to the current tensor. It chooses the latest exit (`data_loader.py:2128-2171`). The dedicated closed-trade snapshot path is safer because it reconstructs each row's own entry snapshot.

Several label reads also use `or`, so valid zero values can fall through to alternate PnL fields (`data_loader.py:2175`, `2192-2203`).

## 12. Trust filtering and dirty-row exceptions

The system has meaningful PIT checks:

- current raw candles require a passed close time and explicit closed marker (`data_loader.py:710-744`);
- trusted replay rejects cutoff/availability after decision and open candles (`trusted_replay/dataset.py:250-264`);
- trainer filtering requires explicit trust evidence, candle finality, replay/MTF IDs, and rejects invalid features and future availability (`ppo_trainer.py:481-652`);
- feedback reconstruction compares `available_at` and `feature_cutoff` with decision time (`data_loader.py:551-568`);
- MASA/PPO cutoff mismatch is checked (`data_loader.py:579-585`, `ppo_trainer.py:634-637`);
- offline batch training runs a row-level point-in-time report before GPU work (`v2_trainer_offline_batch_train.py:423-441`, `v2_trainer_offline_hyperparameter_sweep.py:76-147`).

The 2026-07-17 repair narrows historical `MISSING_MASKED` admission. The replay loader now requires all of the following: only optional/event-dependent missing names, no `critical_family_absent:*`, no stale names, actual snapshot lineage, and an independent source attestation that the family was introduced after snapshot time. Unproven schema introduction and critical-family absence receive explicit rejection counters. The final training override independently rejects any critical-family marker even when the row self-asserts safety.

Explicit exceptions nevertheless remain and require a unified field-family contract before closure:

- `_example_trusted_for_training()` can accept a loader-approved `MISSING_MASKED` row;
- PPO filtering has narrowly defined optional/event-dependent and derived-cost-only training masks;
- a high-confidence losing feedback path can remove `MISSING_TRUST_*` reasons. Temporal violations remain, but the trust envelope may still be incomplete.

These exceptions are not permission to use unfinished candles, future availability, stale fields, NaN-required values, or critical missing feature families. A rebuild should express optionality and schema introduction in a versioned feature schema, not mutable row assertions.

The offline PIT report fails closed on a missing trust row or decision time and checks several ordering fields, but it only rejects an unfinished candle when an explicit finality flag is false. A missing finality flag is not independently rejected there (`v2_trainer_offline_hyperparameter_sweep.py:103-145`).

Reconstruction invariant: never infer that `source_availability=1` means point-in-time safe. PIT safety must be based on the named timestamps and finality evidence.

## 13. Replay and feedback persistence

### 13.1 Feedback priority and starvation

Closed feedback is read in fixed source order (`data_loader.py:1770-1809`):

1. `v2:trainer:feedback:outcomes`;
2. `v2:trainer:feedback:counterfactuals`;
3. paper-exploration materialization feedback.

`load_training_examples()` applies the limit while iterating the combined list and returns immediately when full (`data_loader.py:1369-1399`). Earlier sources can starve later sources. There is no cross-source sample ledger or deduplication.

The module-level successful-example LRU is keyed by a hash of row content and speeds reconstruction, but it does not prevent the same example from entering the process replay deque on repeated cycles.

### 13.2 Durable replay cursors

Trusted replay uses:

- oldest-first archive traversal;
- a 4.5-hour label embargo;
- a persistent frontier cursor;
- a separate historical backfill cursor;
- scan multiplier 4, minimum 512, maximum 16,384 (`data_loader.py:53-71`, `1518-1768`).

The cursor JSON write uses direct `Path.write_text()` and swallows `OSError` (`data_loader.py:1481-1516`). It is not temp-and-rename atomic and has no file lock. A partial write resets the next read to an uninitialized sentinel, which can restart scanning. Multiple loader processes have independent archive views in some workflows, but online cold-start fallback and background prefetch can both reach the live backfill path and deserve an explicit single-writer test.

### 13.3 Process-local replay deque

The persistent trainer has `deque(maxlen=16384)` (`persistent_cuda_trainer_runtime.py:2569-2579`). It is not persisted and is lost on restart. The source comment estimates 374 floats and about 25 MB, but the current source vector is 1,784 floats and the historical deployed vector was 1,908 before Python object/tuple overhead; either generation makes the comment stale and materially understates memory.

Backfill is built in a daemon thread with its own Redis client and loader, then transferred through a locked queue (`persistent_cuda_trainer_runtime.py:2844-2908`). The replay deque itself is assembled on the main cycle. There is no dedupe by sample ID or tensor ID.

### 13.4 Manifest holdout contamination

Bootstrap can generate a strict 70/15/15 temporal manifest (`trusted_replay/bootstrap.py:220-245`). The persistent holdout evaluator later reads its holdout window and materializes examples (`persistent_cuda_trainer_runtime.py:468-694`).

Normal online training does not read this manifest or exclude that window (`runtime.py:444-522`, `data_loader.py:1518-1768`). The same archive rows can therefore be consumed by the normal frontier/backfill trainer and later labeled `untouched_holdout_window=true` by the evaluator. No global trained-sample ledger is consulted. This invalidates a strong untouched-holdout claim until exclusion is enforced at loading time and proven by immutable sample IDs.

## 14. Offline training, H2L, and concurrency

### 14.1 Continuous offline process

`tools/continuous_offline_gpu_trainer_loop.sh` repeatedly:

- warm-starts from the current live checkpoint;
- loads or reuses a large example cache;
- trains several epochs;
- writes only to `.local_models/v2_native_rl_masa_ppo_offline`;
- sleeps and repeats (`tools/continuous_offline_gpu_trainer_loop.sh:21-82`).

The active unit overrides the script defaults to five epochs, batch 1,024, interval 150 seconds, and CUDA fraction 0.40. Unless overridden, steps per epoch remain 60, early-stop patience 4, minimum epochs 6, limit 49,152, and cache rebuild every 20 iterations (`tools/continuous_offline_gpu_trainer_loop.sh:36-49`). With the unit's five epochs and the script's minimum-six setting, early stopping cannot occur before the run naturally completes.

Each epoch calls `trainer.train()` again (`v2_trainer_offline_batch_train.py:522-528`), recreating AdamW and reusing the deterministic batch and split. Risk-based best-checkpoint selection evaluates the tail slice with raw policy-logit argmax (`351-404`, `508-583`), not the expected-move-aligned inference selector.

### 14.2 Pickle caches

Offline and H2L caches call `pickle.load()` and `pickle.dump()` directly (`v2_trainer_offline_batch_train.py:242-345`). The only compatibility guard checks the first example's vector width against `4 * len(FEATURE_SPEC)`. It does not bind cache content to code revision, schema digest, cost assumptions, labels, trust policy, or source archive.

Loading a pickle from a path writable by an untrusted actor is arbitrary code execution. A rebuild must use an explicit non-executable format plus hashes and a schema version.

### 14.3 H2L split and overlap check

H2L loads `offset + limit` rows, treats the prefix as excluded training rows and the suffix as heldout, and falls back to a 76/24 split if supply is shorter than the requested offset (`v2_trainer_h2l_promote.py:69-126`). Its overlap identity contains symbol, timeframe, tensor ID, snapshot ID, label action, and payload keys (`40-65`).

This proves disjointness only between the two current lists. It does not prove that suffix rows were never seen by:

- a prior scheduled run;
- the online replay frontier/backfill loop;
- the continuous offline pickle cache;
- another cache path;
- an earlier version whose sample identity changed.

H2L supervised scoring uses validation CE plus expected-move MSE. Risk scoring uses raw `argmax(net(x)["logits"])` and returns long `+label`, short `-label` (`v2_trainer_h2l_promote.py:129-236`). Production inference applies expected-move agreement and can turn the same raw argmax into hold. H2L therefore evaluates a different action policy from serving.

Promotion first requires a supervised loss improvement. When the risk gate is required, offline must produce trades, meet minimum Sortino, stay within optional CVaR limit, and not be worse than live on Sortino/CVaR (`v2_trainer_h2l_promote.py:247-304`, `385-484`). Confirmed promotion copies the entire live directory to a timestamped backup, loads the offline model, then asks the live checkpoint manager to write it as a fresh live checkpoint (`307-355`).

### 14.4 Scheduled pretrain

Scheduled pretrain trains the prefix from scratch, uses 20% of that prefix as its repeated validation slice, saves the offline candidate, scores the suffix, and can automatically promote and restart the resident service (`v2_trainer_scheduled_pretrain.py:124-225`). The deployed systemd command enables both actions despite a contradictory adjacent comment.

### 14.5 Concurrent writers and resource owners

At audit time the resident trainer, continuous offline loop, scheduled H2L timer, and RL sidecar were all enabled. The important interactions are:

- online and continuous offline have separate output directories, but offline reads a live checkpoint that the resident can replace while the offline run is starting;
- online and H2L can both write the live checkpoint directory;
- there is no checkpoint directory lock or generation transaction;
- the scheduled unit can restart the resident after promotion;
- online and offline share one GPU; the offline 40% memory cap and nice/I/O priorities reduce but do not serialize contention;
- archive and cache readers can observe different moving frontiers.

A rebuild needs an explicit ownership protocol: one checkpoint publisher, immutable candidate IDs, a compare-and-swap promotion, and a reader-visible atomic generation pointer.

## 15. Checkpoint persistence and identity

### 15.1 Manifest

`CheckpointManifest` contains checkpoint/source IDs, path, generation time, model ID, input dimension, device/CUDA flags, weight-written flag, file path/format/size, and an external-deserialization flag (`checkpoint.py:39-53`). It contains no:

- weight SHA-256;
- feature-spec digest;
- architecture hyperparameter object;
- training-contract or cost-model version;
- optimizer/scaler state;
- parent checkpoint ID;
- dataset/sample-set identity;
- software revision;
- promotion evidence.

### 15.2 Naming and overwrite behavior

Checkpoint ID is `v2_hybrid_ckpt_` plus the last 24 characters of model ID (`checkpoint.py:81`, `110`). Every update with the same partial architecture identity overwrites the same JSON and NPZ. There is no immutable per-update checkpoint history in that lineage.

The audit-time live/offline same-ID, different-hash pair demonstrates the ambiguity. A prediction's `checkpoint_id` is insufficient to reproduce its weights.

### 15.3 NPZ format and loading

`save_weight_blob()` writes a compressed NPZ with format version, input dimension, seed, torch-availability flag, and every state tensor, using a temp file then rename (`model.py:440-477`). `load_weight_blob()` uses `allow_pickle=False`, validates input dimension, requires every expected tensor, validates exact shape and finite values, and calls strict `load_state_dict()` (`479-526`). These are good fail-closed properties.

Remaining gaps:

- extra arrays in the NPZ are ignored;
- manifest size is informational only;
- no stored checksum is verified before load;
- manifest model ID is not reconciled with a content hash;
- same-shaped but behaviorally incompatible configurations can load;
- CPU fallback and torch model use different payload branches;
- optimizer/scaler state is absent by design.

### 15.4 Atomicity and latest selection

Weight and manifest writes are individually temp-and-rename atomic (`model.py:458-472`, `checkpoint.py:19-37`). The pair is not atomic: weight is replaced first, then manifest. A crash or concurrent reader can see a mixed generation.

Latest selection scans manifests, filters input dimension, optionally requires an existing weight, and sorts by manifest file mtime (`checkpoint.py:149-252`). It does not sort by a signed generation number or validate content before choosing. Shape checks later catch many architecture differences, but semantic differences with identical shapes are invisible.

Runtime computes a SHA-256 after checkpoint handling (`runtime.py:113-123`, `616-620`) but does not store it in the manifest or require it on reload.

### 15.5 Promotion guard

Promotion now has a mandatory PIT/economic evidence layer even if the configurable validation-loss guard is disabled. Before bootstrap or existing-checkpoint comparison, it requires:

1. `validation_split_pit_safe=true` with at least one validation row;
2. serving-policy edge evaluated for exactly every validation row;
3. positive mean after-cost edge;
4. positive `mean - one standard error` lower bound.

Missing/invalid timing, absent edge, nonpositive edge, and uncertainty-nonpositive edge are hard rejections. Only after that mandatory pass does the optional validation-loss guard apply. With a prior loadable checkpoint, regression tolerance remains `max(0.02, 0.15 * abs(before_loss))`; overfit-gap rejection is separately configurable. A material validation improvement can promote with an overfit-gap advisory unless strict-overfit mode is enabled.

The process-local rejection streak is now diagnostic only. Even when its threshold is reached, it records why force promotion was blocked; it does not release PIT/edge, divergence, overfit, or other rejections. The environment flag named `V2_TRAINER_FORCE_PROMOTE_AFTER_REJECTION_STREAK` therefore does not grant an actual bypass in this source state.

The deployed unit's validation-guard configuration must be re-read after reload rather than inferred from an older snapshot. Regardless of that value, the mandatory PIT/edge gate remains active in source.

If promotion is rejected, runtime attempts to reload the prior checkpoint into the same model. When a prior loadable checkpoint was expected, an unverifiable restore aborts; when no verifiable prior generation exists, the serving guard below suppresses all model-derived evidence. This is an important invariant to preserve.

The current repair makes that invariant explicit at every serving consumer. A rejected candidate can be used only after verified restoration of the prior checkpoint. Otherwise `model_serving_allowed=false`, source `NONE_REJECTED_CANDIDATE_SUPPRESSED`, and reason `REJECTED_CANDIDATE_WITHOUT_VERIFIED_PRIOR_RESTORE`; policy backtest, model forward, prediction publication and lineage do not run. Status/policy backtest report `SUPPRESSED_REJECTED_CANDIDATE_NO_VERIFIED_RESTORE`, `prediction_suppressed_count`, and evidence class `NO_EVIDENCE_REJECTED_CANDIDATE_SUPPRESSED`.

## 16. Publication split-brain

The 2026-07-17 repair closes the known caller/copy escape in source. `publish_prediction()` still works on a private payload copy, but after successful replay and primary prediction persistence it commits the exact persisted replay metadata and fail-closed mutations back to the caller-owned payload. `run_hybrid_trainer_cycle()` checks the boolean and calls downstream lineage publication only on success. Archive/replay/prediction failure therefore suppresses orchestrator/risk/signal lineage instead of continuing with the stale pre-write object.

The publisher also propagates exact candle finality, source times, MASA/PPO cutoffs, PPO decision time, and behavior-policy sampling/distribution contract through the prediction/replay/decision/signal surfaces. Candle finality is never inferred; persisted replay success is evidence only after the write succeeds.

Decision surfaces returned by this publisher are proposals, not authorities. Every trainer orchestrator/risk/paper preview and signal carries `authoritative_decision=false`, `record_authority=TRAINER_NON_AUTHORITATIVE_PROPOSAL`, and the trainer proposal source. The publisher no longer writes any `v2:decision:risk:*`, `v2:decision:orchestrator:*`, or `v2:decision:index:*` key. Canonical risk belongs to the risk worker; canonical orchestrator persistence must belong to the orchestrator worker. Consumer code must never upgrade a trainer preview to ALLOW.

Residual closure work remains: deployed failure injection must prove archive, replay, and primary-key failure each suppress all following keys; the multi-key set is still not one Redis transaction or content-addressed generation; and a routeable row has not yet proven byte/field equality across every surface.

The canonical primary key `v2:prediction:{symbol}:{timeframe}` is mutable last-write-wins (`config.py:42`, `publisher.py:1225-1229`). Immutable prediction-by-ID records and explicit owner/generation metadata are needed for exact replay.

## 17. RL-core sidecar is a separate truth plane

`v2_rl_core_inference_loop.py` reads `v2:features:latest:{symbol}:{tf}`, calls the separate `rl_core.trainer_output` chain, and writes `v2:trainer:rl_core_prediction_sidecar:{symbol}:{timeframe}` with 600-second TTL (`v2_rl_core_inference_loop.py:1-30`, `198-299`). It never constructs `V2HybridPolicyModel` or loads the hybrid NPZ.

The payload reads checkpoint evidence and can stamp the active checkpoint ID, while explicitly declaring:

- `model_weights_loaded_into_v2_process=false`;
- `rl_core_sidecar_loaded_active_native_checkpoint=false` (`v2_rl_core_inference_loop.py:250-270`).

It does not overwrite primary `v2:prediction:*` keys and declares itself non-routing. It does, however, write generic `v2:trainer:status` and `v2:trainer:heartbeat`, while the hybrid trainer writes `v2:trainer:hybrid_cuda:*` (`v2_rl_core_inference_loop.py:321-370`, `config.py:39-41`). Operator tooling must not treat those namespaces as the same model process or infer that the sidecar loaded the checkpoint it cites.

## 18. Configuration key families

The following inventory distinguishes source knobs from effective deployment. Environment values must be captured alongside every reproducible training run.

### 18.1 Model and tensor behavior

| Keys | Effect |
|---|---|
| `V2_TRAINER_HIDDEN_SIZE`, `V2_TRAINER_RESIDUAL_BLOCKS` | Encoder width/depth; shape and model ID change. |
| `V2_TRAINER_DROPOUT` | Training stochasticity; same current model ID and shapes. |
| `V2_TRAINER_ATTENTION_ENCODER`, `V2_TRAINER_ATTENTION_HEADS` | Optional spatial attention over the four vector blocks. |
| `V2_TRAINER_TEMPORAL_ENCODER` | Enables GRU for value `gru`. |
| `V2_TRAINER_TEMPORAL_SEQ_LEN` | Window length; omitted from model ID. |
| `V2_TRAINER_TEMPORAL_HIDDEN`, `V2_TRAINER_TEMPORAL_PROJ_DIM` | GRU and frame projection widths. |
| `V2_TRAINER_CPU_THREADS` | PyTorch CPU thread count in CUDA initialization. |

### 18.2 Optimization

| Keys | Default/cap and meaning |
|---|---|
| `PPO_LEARNING_RATE`, alias `V2_TRAINER_LEARNING_RATE` | Default `1e-4`; environment path capped at `2e-4`. |
| `PPO_ENT_COEF`, alias `V2_TRAINER_ENTROPY_COEF` | PPO-lane entropy coefficient; default `0.01`, environment path capped at `0.015`. |
| `PPO_GAMMA` | Default `0.99`; reported but not applied. |
| `V2_TRAINER_SUPERVISED_ENTROPY_BONUS` | Outcome-lane entropy bonus; default `0`. |
| `V2_TRAINER_WEIGHT_DECAY` | AdamW weight decay; default `0.02`. |
| `V2_TRAINER_FAST_STEP_METRICS` | Reduces synchronous per-step telemetry; intended not to change math. |
| `V2_TRAINER_TAIL_CVAR_WEIGHT`, `V2_TRAINER_TAIL_CVAR_ALPHA` | Optional tail loss; default weight `0`, alpha `0.1`. |

Constructor arguments can bypass the environment safety caps in offline sweeps (`ppo_trainer.py:211-292`).

### 18.3 Resident runtime and GPU controller

| Keys | Effect |
|---|---|
| `RL_SAFE_ENV_CAP`, `RL_N_ENVS` | Parallel proof environment count; default cap 256. |
| `RL_N_STEPS` | Proof rollout setting; minimum/default 512. |
| `RL_BATCH_SIZE` | Selected full-batch row cap; hard maximum 4,096. |
| `RL_ALLOW_ENV_TRUNCATION`, `VEC_ENV_TYPE` | Legacy-parity reporting/coverage settings. |
| `PPO_N_EPOCHS` | Multiplies resident steps; default 1, max 16. |
| `PREDICTION_LOOP_SECONDS`, `POST_TRAINING_PAUSE_SECONDS` | Loop cadence settings; deployed service also passes interval 5 directly. |
| `ENABLE_AUTO_GPU_SCALE`, `V2_NATIVE_TRAINER_ADAPTIVE_GPU_CONTROLLER` | Enables step multiplier controller. |
| `TRAINER_TARGET_GPU_UTIL`, `TRAINER_TARGET_VRAM_UTIL` | GPU controller targets. |

Internal resident caps are 64 base steps, 512 rows per step for scaling, 4,096 rows in one full batch, 128 adaptive hard-ceiling steps, and a 600-second cycle watchdog (`persistent_cuda_trainer_runtime.py:2569-2580`, `2826-2834`). With 16,384 configured rows, base steps are 32 before adaptive multiplication (`2628-2631`, `3070-3090`).

### 18.4 Promotion

| Keys | Effect/default |
|---|---|
| `V2_TRAINER_VALIDATION_CHECKPOINT_GUARD` | Source default true; deployed false. |
| `V2_TRAINER_REJECT_OVERFIT_CHECKPOINTS` | Default true. |
| `V2_TRAINER_VALIDATION_MAX_LOSS_INCREASE` | Absolute tolerance floor, default 0.02. |
| `V2_TRAINER_VALIDATION_MAX_LOSS_INCREASE_FRAC` | Relative tolerance, default 0.15. |
| `V2_TRAINER_REJECT_OVERFIT_EVEN_IF_VALIDATION_IMPROVED` | Restores strict overfit rejection, default false. |
| `V2_TRAINER_OVERFIT_GAP_ABS_FLOOR`, `V2_TRAINER_OVERFIT_GAP_REL_FRAC` | Trainer overfit-warning thresholds. |
| `V2_TRAINER_MAX_PROMOTION_REJECTION_STREAK` | Default 50. |
| `V2_TRAINER_FORCE_PROMOTE_AFTER_REJECTION_STREAK` | Optional non-hard-reason escape, default false. |
| `V2_TRAINER_STREAK_ESCAPE_RELEASES_OVERFIT_GAP` | Default true. |

### 18.5 Replay, offline, H2L, calibration

| Keys | Effect |
|---|---|
| `V2_TRAINER_CLOSED_TRADE_EXAMPLE_CACHE` | Closed-feedback reconstruction cache kill switch. |
| `V2_TRUSTED_REPLAY_HOLDOUT_SCAN_LIMIT`, `V2_TRUSTED_REPLAY_HOLDOUT_EVAL_LIMIT`, `V2_TRUSTED_REPLAY_HOLDOUT_MIN_INTERVAL_SECONDS` | Holdout evaluator cost/cadence. |
| `V2_OFFLINE_LOOP_INTERVAL_SECONDS`, `V2_OFFLINE_EPOCHS`, `V2_OFFLINE_STEPS_PER_EPOCH`, `V2_OFFLINE_BATCH_SIZE` | Continuous offline cadence/work. |
| `V2_OFFLINE_MIN_EPOCHS`, `V2_OFFLINE_EARLY_STOP`, `V2_OFFLINE_LIMIT`, `V2_OFFLINE_REBUILD_EVERY` | Offline selection/cache cadence. |
| `V2_OFFLINE_CACHE_PATH`, `V2_OFFLINE_REPLAY_MAX_SCAN`, `V2_OFFLINE_SEED_HOURS_BACK` | Offline pickle/archive view. |
| `V2_OFFLINE_CUDA_MEMORY_FRACTION` | Per-process CUDA memory fraction; deployed 0.40. |
| `V2_OFFLINE_SELECT_BY_VAL_LOSS` | Switch from default risk composite to validation loss for best checkpoint. |
| `V2_H2L_HELDOUT_OFFSET` | Default 20,000. |
| `V2_H2L_REQUIRE_RISK_GATE`, `V2_H2L_MIN_SORTINO`, `V2_H2L_MAX_CVAR_LOSS_BPS` | H2L risk requirements. |
| `V2_PRETRAIN_MIN_FREE_VRAM_MB` | Scheduled pretrain admission; default 4,096 MB. |
| `V2_TRAINER_CONFIDENCE_TEMPERATURE`, `V2_CONFIDENCE_TEMPERATURE_STATE_PATH` | Runtime confidence calibration. |

### 18.6 Safety posture

`LIVE_GATE=blocked_human_only`, empty live symbols, and `V2_LIVE=0` are the intended deployment posture. `HybridTrainerConfig.validate_safety()` rejects a different live gate or nonempty live symbols and limits model writes to `.local_models` (`config.py:119-128`). This document does not authorize relaxing them.

## 19. Change-impact matrix

| Proposed change | Immediate affected surfaces | Hidden/secondary impact | Required migration/proof |
|---|---|---|---|
| Add/remove a `FEATURE_SPEC` item | Tensor width/order, source labels, masks | Model input projection/ID and NPZ shapes, tensor IDs, pickle/input caches, H2L, `(input_dim, seq_len)` temporal-buffer key, downstream feature-name hashes | New feature-schema ID; invalidate caches/buffers; fresh checkpoint lineage; ABI tests; PIT review. |
| Reorder `FEATURE_SPEC` at unchanged length | Tensor meaning/order and downstream feature-name hashes change while width does not | Existing NPZ shapes and architecture/model ID still match; `(input_dim, seq_len)` key is unchanged, so frames with old feature semantics can be silently reused; pickle/input caches and H2L retain old order assumptions | New feature-schema ID; invalidate every cache/buffer; fresh checkpoint lineage; ordered-digest/golden-vector tests; PIT review. |
| Change only a feature extraction fallback | Values and tensor IDs | Labels may join to different tensors; replay/cache population; prediction gates | Zero-preservation and source-priority tests; replay comparison. |
| Change stale/missing policy | Training population and coverage | Confidence, paper eligibility, replay balance, promotion metrics | Dirty-row matrix, historical replay regeneration, holdout isolation proof. |
| Change timestamp/finality semantics | PIT admission and windows | Replay labels, holdout, paper lineage | Full timestamp ordering tests; final-candle proof; archive migration. |
| Change hidden/blocks/attention/temporal widths | Parameter shapes and current model ID | Existing NPZ will fail shape load or new ID starts fresh | Explicit architecture manifest, cold/warm-start plan, H2L proof. |
| Change dropout | Behavior changes but current model ID does not | Old NPZ loads silently; the same process-lifetime temporal-buffer key is reused | Fix identity first; clear buffer/cache; new checkpoint lineage; OOS comparison. |
| Change temporal sequence length | Behavior changes but current model ID does not | Old NPZ loads silently; `(input_dim, temporal_seq_len)` selects a different registry entry, while the old keyed buffer can remain resident (`model.py:115-120`) | Fix identity first; clear all old/new temporal-buffer and input-cache state; new checkpoint lineage; sequence/padding/OOS tests. |
| Change action labels/order/count | Policy-head semantics, labels, selector | Existing policy tensors, paper intent, state machine, PPO log probs, H2L action mapping | Versioned action ABI; model/label migration; invalid-transition fail-closed tests. |
| Change expected-move threshold | Inference action and paper gate | PPO entry distribution/action, feedback mix, H2L mismatch | Serving/H2L parity test; new policy-contract version. |
| Change fee/slippage | Current after-cost gate | Replay remains 2-bps labels; old feedback/cache semantics | Version cost model; regenerate labels/caches; long/short/zero matrix. |
| Change PPO fields or objective | Weight updates and advantage | Checkpoint comparability, metrics meanings, H2L | Offline A/B; exact action/log-prob invariant; GAE/return golden tests; operator approval. |
| Persist optimizer state | Checkpoint format/size | Online/offline warm-start dynamics | Versioned optimizer schema, device-safe load, rollback proof. |
| Remove direct head nudges | Learned trajectories and output calibration | Checkpoint performance, saturation behavior | Offline ablation and saturation regression tests. |
| Change replay insertion priority/cap | Effective sample distribution | Temporal windows, validation, GPU batch, memory | Deduped sample ledger, distribution telemetry, deterministic selection test. |
| Change holdout boundaries | Calibration and H2L evidence | Prior training contamination remains | Global immutable train ledger; new untouched holdout. |
| Change checkpoint naming | Load/latest, sidecar evidence, lineage | Rollback, retention, H2L copy | Content-addressed manifest migration and compatibility reader. |
| Change publisher return semantics | Canonical predictions and lineage | Paper/risk feedback loop | Failure injection and transaction/idempotency tests. |
| Disable/rename sidecar keys | Operator dashboards | Generic trainer health consumers | Consumer inventory and namespace-owner migration. |

## 20. Rebuild-grade invariants

A faithful but safe replacement should make these executable invariants, not comments:

### Data and time

1. Preserve the exact ordered feature ABI and record its digest in every sample/checkpoint.
2. Distinguish `event_time`, `ingested_at`, `available_at`, `generated_at`, `feature_cutoff`, `decision_time`, and `execution_time`.
3. Require every used feature's `available_at <= decision_time`.
4. Require `MASA feature_cutoff <= PPO decision_time`; equality between MASA/PPO cutoffs must be an explicit contract, not an accidental default.
5. Reject unfinished higher-timeframe candles.
6. Reject stale, missing-required, NaN-required, invalid-lineage, or coverage-gate-failed rows; exceptions must be separately versioned datasets, never silent overrides.
7. Sort temporal windows by parsed decision time from the trust record and assert that every frame time is `<=` the target time.
8. Carry and consume a padding mask, or use packed sequences.

### Samples, labels, and economics

9. Give each sample an immutable content identity covering tensor values/order, masks, time envelope, label, cost-model version, and source hashes.
10. Deduplicate across feedback, frontier, backfill, process restarts, and offline caches.
11. Use one versioned round-trip cost model for replay labeling, training, H2L, prediction, and paper evaluation.
12. Preserve legitimate zero values; never use truthiness for numeric fallback.
13. Define whether MFE/MAE and labels are price-directional or position-relative and encode the side.
14. Keep training, validation, and final holdout sample identities in an append-only ledger; training loaders must exclude final holdout IDs.

### PPO and model

15. Store action taken, action index, raw behavior logits/probabilities, selector version, value estimate, reward, done, next value, rollout ID, and step index.
16. Evaluate new log probability for the same action under the same policy transformation as old log probability.
17. Either implement discounted returns/GAE using ordered trajectories or name the algorithm honestly as one-step clipped policy optimization.
18. Train the critic against the return used in advantage, not a differently scaled move target.
19. Make supervised/PPO/MASA/confidence loss weights a versioned config and emit exact per-term reductions.
20. Persist optimizer/scaler state for true continuation, or explicitly define each update as a stateless optimizer restart.
21. Eliminate out-of-optimizer mutations or version and checkpoint their state/logic as part of the training algorithm.
22. Use the identical action-selection function in serving, policy backtest, offline selection, and H2L.

### Checkpoints and publication

23. Make every weight generation immutable and content-addressed.
24. Store and verify weight SHA-256, architecture config, feature ABI, action ABI, objective/cost versions, parent ID, code revision, and sample-set ID.
25. Publish weight, manifest, optimizer, and evidence as one generation, then atomically swap a single current pointer.
26. Allow only one live checkpoint publisher or use an interprocess lock and compare-and-swap.
27. Clear/version temporal inference state when model or feature generation changes.
28. Treat durable snapshot, replay snapshot, canonical prediction, and downstream lineage as a committed state machine. Never continue from a failed boolean.
29. A process may cite a checkpoint as loaded only after it verifies and loads the exact content hash itself.
30. Preserve the paper-only/live-blocked posture and validate invalid position transitions before any order path.

## 21. Tests, current evidence, and gaps

### 21.1 Existing relevant coverage

The repository contains focused tests for:

- action selection and attention identity: `v2/backend/tests/unit/services/native_trainer/test_hybrid_policy_model_action_selection.py`;
- class weights, single-direction guards, direct recovery, and non-finite checkpoint rejection: `test_hybrid_ppo_action_balance.py`;
- validation/regularization: `test_hybrid_trainer_regularization_and_validation.py`;
- temporal windows/encoder/inference buffer: `test_temporal_windowing.py`, `test_temporal_encoder_integration.py`, `test_temporal_prediction_window.py`;
- input-cache fingerprinting: `test_train_input_cache.py`;
- replay PIT, future labels, open-candle rejection, and temporal split: `test_trusted_replay_bootstrap.py`;
- replay cursor: `test_trusted_replay_cursor.py`;
- closed feedback and label paths: `test_hybrid_trainer_feedback_labels.py`, `test_closed_trade_example_cache.py`, `test_feedback_enrichment_quarantine_fix.py`;
- tail objective: `test_tail_cvar_objective.py`;
- offline directory/cursor isolation: `v2/backend/tests/unit/cli/test_v2_trainer_offline_batch_train.py`;
- H2L load, overlap, split, loss, and risk gates: `v2/backend/tests/unit/cli/test_v2_trainer_h2l_promote.py`.

These tests verify many local contracts but do not close the cross-component findings above.

### 21.2 Historical audit validation result

The audit ran:

`PYTHONPATH=v2/backend .venv/bin/pytest -q v2/backend/tests/unit/test_canonical_candles_and_mtf_snapshot.py v2/backend/tests/unit/test_pipeline_trust.py v2/backend/tests/unit/test_pipeline_trust_runtime_enforcement.py`

Result: 66 passed and 6 failed. All six failures occur in publisher `_trusted_replay_snapshot` because the tests' `example().tensor` `SimpleNamespace` fixture lacks the newly required `missing_mask`. The intended publisher/trust assertions are not reached. This is stale test-fixture/contract drift; it is not evidence that canonical temporal guards themselves failed. The fixtures must be updated deliberately, then those six assertions rerun.

### 21.3 2026-07-17 source-repair validation

The final focused PIT/promotion/PPO/authority suite passed 100 tests. A targeted publication-commit plus rejected-candidate serving-suppression pair passed two tests and the affected trainer/integrity modules compiled cleanly.

The initial full native-trainer plus pipeline-trust run produced 371 passed and three failures in `test_ta_full_feature_expansion.py`. Investigation established that commit `e88e2318e3` intentionally removed 31 AiCoin/Nansen/LunarCrush/Santiment features by operator directive while retaining all 155 `taf_*` features; current source is therefore 446 ordered features and a 1,784-value four-segment vector. The three stale test expectations were updated from 477/1,908 to 446/1,784, and the same combined suite then passed 374 tests.

That result validates the local current-source contract; it does not retroactively make older 477/1,908 checkpoints, caches, temporal buffers, or replay rows compatible. RE-044 remains open until the exact ordered-name digest and width are schema-versioned across publisher, trainer, backtest, restore, and archived data, with incompatible generations invalidated or quarantined.

The focused coverage proves source behavior for:

- chronological decision-time split, equal-time grouping and label-horizon purge;
- fail-closed missing/invalid label timing;
- positive held-out serving-policy mean and one-standard-error lower-bound promotion requirements;
- rejection-streak non-override;
- deterministic-policy PPO ineligibility and categorical raw-softmax eligibility;
- critical-family missing-mask rejection despite self-attestation;
- zero backtest/inference/prediction/lineage from a rejected candidate without verified restore;
- replay publication metadata committed before lineage;
- zero trainer canonical decision/index writes and explicit non-authoritative proposal fields.

### 21.4 Required missing tests

Before rebuilding or changing this component, add:

1. **Tensor ABI golden test:** exact 446 count, ordered digest, unique names, four 446-element segments, 1,784 total, feature/source alignment, and explicit rejection of older incompatible generations.
2. **Valid-zero matrix:** zero must survive every fallback, reward, PnL, and cost path.
3. **Availability semantics:** source presence must not be accepted as timestamp availability.
4. **Temporal shuffle test:** randomly reorder examples while keeping trust times; windows must remain time-sorted and contain no future frame.
5. **Top-level/trust-row time test:** normal `TrainingExample` objects must use `trust_row.decision_time`.
6. **Padding test:** GRU must receive or honor a pad mask.
7. **Temporal state generation test:** model/checkpoint/schema change must not inherit an old process buffer.
8. **Identity tests:** dropout, sequence length, action ABI, selector, feature digest, and objective change the training-contract identity; learned bytes change weight ID.
9. **PPO ratio golden test:** old/new log probabilities use the same stored action and the same raw/adjusted policy.
10. **Trajectory test:** multiple rollouts with terminal/nonterminal steps prove return, gamma, bootstrap, and GAE semantics; if intentionally one-step, assert gamma is absent from the public contract.
11. **Loss golden test:** calculate every coefficient for supervised, PPO, mixed, outcome-only, and tail-CVaR lanes.
12. **Optimizer continuation test:** uninterrupted and save/reload training must have defined, tested equivalence or documented divergence.
13. **Serving/H2L parity:** identical rows and weights produce identical selected actions in production, backtest, offline selection, and H2L.
14. **Long/short cost-label matrix:** gross/after-cost, win/loss, MFE/MAE, value/reward, and zero cases.
15. **Replay priority/dedupe test:** prove exact final sample IDs after backfill, frontier, feedback, deque truncation, and repeated cycles.
16. **Holdout non-overlap test:** compare immutable holdout IDs with every online/offline trained ID across restarts.
17. **Cursor crash/concurrency test:** partial write, two writers, wrap, and recovery.
18. **Checkpoint corruption test:** manifest/NPZ checksum mismatch, extra/missing arrays, mixed-generation pair, and concurrent publisher.
19. **Publisher failure injection:** archive failure, replay failure, primary-key failure, and lineage failure must leave a single consistent committed state.
20. **RL sidecar truth test:** cited checkpoint ID cannot imply loaded weights; generic and hybrid trainer namespaces must remain distinguishable.

## 22. Operator change protocol

Before approving any trainer-related change, record:

1. exact source and deployed config before/after;
2. feature, action, architecture, training-contract, label, and cost schema IDs;
3. old/new checkpoint content hashes and parent relationship;
4. exact training, validation, and untouched holdout sample IDs and time ranges;
5. PIT/finality audit results;
6. per-lane row counts and rejected reasons;
7. full loss decomposition and whether PPO was actually active;
8. serving/H2L action parity;
9. risk metrics using the same production selector and costs;
10. publication failure-injection results;
11. rollback generation and proof that the resident process loaded it;
12. confirmation that `LIVE_GATE` and exchange-mutation behavior were unchanged.

Do not infer durable learning solely from `WEIGHTS_UPDATING`, optimizer-step count, checkpoint ID, or sidecar checkpoint evidence. Require a changed verified weight content hash, a committed manifest generation, successful reload by the owning process, and uncontaminated out-of-sample evidence.

## 23. Known audit limitations

- Runtime observations are a point-in-time sample and continue changing while the services run.
- Redis status and metrics are separate last-write values, not a transactional snapshot.
- This audit did not deserialize pickle caches or expose their contents.
- No secrets, credentials, Redis connection material, or private payload values are reproduced here.
- This document describes current behavior and defects; it does not claim the named `PPO`, `MASA`, holdout, or checkpoint labels have conventional semantics beyond the code paths documented above.
