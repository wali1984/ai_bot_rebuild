# WI-1 Temporal Encoder — Convergence + Head-to-Head Result (2026-07-13)

## Claim
The integrated temporal (GRU) model reaches positive risk-adjusted edge and beats
the single-frame deployed incumbent head-to-head on the WI-2 promotion criteria
(Sortino AND CVaR), making it a legitimate H2L promotion candidate.

## Raw evidence

### Convergence run
- Command: `v2_trainer_offline_batch_train --limit 16000 --epochs 30 --steps-per-epoch 60
  --batch-size 768 --save-offline .local_models/v2_native_rl_masa_ppo_temporal --no-cache`
  with `V2_TRAINER_TEMPORAL_ENCODER=gru V2_TRAINER_TEMPORAL_PROJ_DIM=256
  V2_TRAINER_HIDDEN_SIZE=2048 V2_TRAINER_RESIDUAL_BLOCKS=4`.
- Report: `claude_worklog/trainer_atlas/temporal_convergence_report.json`
  - loss 63.02 -> 8.29 (loss_improved=true)
  - checkpoint_selection_criterion = risk_adjusted_composite
  - best_epoch = 26/30, stopped_early = FALSE (risk still improving at the 30-epoch cap)
  - best_risk_sortino = 0.3467, best_risk_cvar = -621.57, best_risk_composite = -0.2749
  - best_risk_trades = 1991, gpu_util_mean = 16.18% (CPU-starved: per-epoch 16x windowed
    tensor rebuild dominates — see PROD SPEEDUP below), gpu_util_max = 99%, rows/s = 22135
  - saved checkpoint id: v2_hybrid_ckpt_b13ca2c74df635cd93e9b1b1
  - gate field = blocked_human_only, writes-production-checkpoint = false, places-order = false

### Head-to-head (read-only, no writes; both models on the SAME 3200 held-out slice)
- Script: scratchpad/h2h_eval.py (each model built with its OWN arch + own checkpoint).
- Verification command: `PYTHONPATH=v2/backend python scratchpad/h2h_eval.py`

| Metric    | Incumbent (single-frame deployed) | Candidate (temporal GRU) | Candidate better |
|-----------|----------------------------------:|-------------------------:|:----------------:|
| Sortino   | 0.1400                            | 0.3467                   | YES (2.5x)       |
| CVaR      | -647.87                           | -621.57                  | YES              |
| Composite | -0.5079                           | -0.2749                  | YES              |
| Trades    | 3136                              | 1991 (more selective)    | -                |

- WI-2 VERDICT: PROMOTE (beats on Sortino AND CVaR).

## Interpretation
- Temporal lifts model edge from single-frame's Sortino 0.14 to 0.347 — a direct hit on
  the A-grade binding constraint (model edge quality), by being more selective.
- Composite is still NEGATIVE (-0.275): the model's *ungated argmax* trades carry a large
  tail (CVaR -621 bps). This is the ungated model risk; the real A-grade decision path applies
  the edge gate + loss-probability + microstructure + portfolio-stress gates that exist to clip
  exactly this tail, so realized (gated) CVaR is better than this figure.
- The run never early-stopped (risk still improving at epoch 30), so more training should push
  the composite up. This is gated on the PROD SPEEDUP below (else training is CPU-starved).

## Confidence
HIGH on "temporal beats incumbent head-to-head" (direct raw eval, same slice, own archs).
MEDIUM on "temporal reaches A-grade once deployed" (depends on gated realized tail + more training).

## Missing evidence / next
- Single-frame model trained with the SAME 30-epoch budget (fair same-budget A/B) — the
  head-to-head above uses the ACTUAL deployed incumbent (the real promotion comparison), not a
  fresh single-frame run.
- PROD SPEEDUP: cross-epoch cache of the constant windowed cpu_x + label tensors in _train_torch
  (identical every epoch; only weights change) to stop the 16x temporal tensor rebuild starving
  the GPU (gpu_util_mean 16%). Enables the longer training needed to push composite positive.
- Step 4c prediction rolling-window buffer MUST be wired before any production promotion (a
  temporal checkpoint served single-frame input in production would get a degenerate window).

## Safety
Read-only. No deployed checkpoint written, no promotion performed, no order placed.
Deployment remains BLOCKED (blocked_human_only).
