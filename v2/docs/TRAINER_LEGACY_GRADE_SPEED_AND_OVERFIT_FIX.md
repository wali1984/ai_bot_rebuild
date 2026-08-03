# Trainer legacy-grade speed + overfit fix — root cause, legacy architecture, and the genuine fix

**Date:** 2026-07-12  ·  **Live gate:** `blocked_human_only` throughout (paper/shadow only).

## Symptoms (measured)
- Online loop cycle cadence ≈ **9 minutes**; `training_steps_last_hour ≈ 192` (≈ **3 steps/min**).
- GPU ≈ **9%** utilization (idle) while `data_loader_time_ms ≈ 42-60k` vs `gpu_train_time_ms ≈ 16k` per cycle → the CPU data build dominates.
- The model **overfits** each online cycle: train 45.5 → 5.6 while validation **regressed** 14.7 → 21.6 → the promotion guard rejects (`VALIDATION_LOSS_REGRESSED` / previously `TRAIN_VAL_OVERFIT_GAP`), so `online_learning_status = BLOCKED_NO_DURABLE_WEIGHT_UPDATE`, `effective_trainer_mode = INFERENCE_ONLY`.

## Why (V2 vs legacy `hybrid_trainer.py`)
The legacy 90%+ trainer had a fundamentally different operating model:

| Dimension | Legacy | V2 (current online loop) |
|---|---|---|
| Env / rollout | **GPUBatchedVecEnv, 128 envs × 256 steps = 32,768 samples/batch**, 70-85% GPU | reads ~16k rows from the durable archive per cycle (CPU), 40 steps |
| Data regime | **Pure on-policy PPO (no replay)** — fresh rollouts every batch → structurally can't memorize | trains repeatedly on a 16k **replay buffer** from a warm checkpoint → memorizes → overfits |
| Training schedule | **Two-phase: HISTORICAL (train on ALL data first) → H2L transition → LIVE refine** | no historical pre-training phase; goes straight to slow online fine-tuning |
| Policy | LSTM + multi-head attention (temporal memory) | stateless residual MLP |

So V2 is slow **because** each cycle rebuilds features from disk (CPU-bound) and does only 40 steps, and it overfits **because** it repeatedly fine-tunes a warm checkpoint on the same small replay batch — the exact opposite of legacy's on-policy, historical-first, GPU-batched design.

## The genuine fix (proven)
**1. Historical pre-training phase (the big lever) — `v2_trainer_offline_batch_train.py`.**
It is the V2 equivalent of legacy "historical mode": load a large trusted dataset **once** (cached), then run many GPU steps at a large batch. Measured on 8k diverse rows, 12 epochs:
- **98% GPU util, 23,171 rows/s, ~170 steps/min (≈ 57× the online loop).**
- **Generalizes, does NOT overfit:** validation 41.2 → 37.9 (improving), train/val gap −25 → −16 (negative, shrinking) — versus the online loop where val blows up. Fresh-init training on diverse data avoids the warm-checkpoint memorization.
- Produces a non-live offline checkpoint the operator can promote after review.

**2. Durable-weight-update fix (shipped, commit 824ee29b72):** the overfit-gap guard now promotes when validation materially improves (model generalizing) and still hard-rejects true overfit. Removes the `BLOCKED_NO_DURABLE_WEIGHT_UPDATE` deadlock so the online loop can persist generalizing cycles.

**3. Online-loop throughput (the remaining architectural lever, path documented):**
- **Decouple data build from training:** keep the built-tensor dataset resident and refresh it incrementally instead of rebuilding ~16k rows from the archive every cycle (the 42-60s cost). A resident/prefetch pipeline already exists in `runtime.py`; it needs to be the default so the GPU is fed continuously.
- **Restore GPU-batched vectorized rollouts** (legacy `GPUBatchedVecEnv`, 128 envs) so rollout collection runs on GPU rather than CPU archive reads. This is the biggest online-speed lever and is a larger build (coordinate with the Phase-2 vectorized-coverage work).
- **Move toward on-policy freshness** (less replay reuse per warm checkpoint) to reduce online memorization.

## Recommended runbook
1. Run the historical pre-training offline (large dataset, early-stop on best validation) to build a generalizing base brain — GPU-saturated, minutes not days.
2. Promote the offline checkpoint (operator review) as the online loop's warm start.
3. Let the online loop refine; the overfit-gap fix now lets it durably promote generalizing cycles.
4. Land the resident-dataset + GPU-batched-env online throughput work so cycle cadence drops from ~9 min to seconds.

**Safety:** everything here is paper/shadow; no order/leverage/margin paths; offline checkpoints are written to a non-live directory only; the exchange gate stays `blocked_human_only`.
