# Trainer Offline Retrain & Hyperparameter Sweep — Runbook

**Purpose:** recover / stabilize the native CUDA MASA/PPO trainer without online experimentation. The running model was observed to diverge (supervised loss climbing 3.6 → 16+) under an over-strong entropy bonus; the correct fix is an **offline** hyperparameter search, then apply the winning config and let the trainer promote a stable checkpoint.

**Safety:** every step here is paper/shadow. Nothing places an order or mutates leverage/margin. The sweep is report-only and does not write checkpoints; the `--promote` flag intentionally fails closed. The exchange gate stays `blocked_human_only`.

---

## Step 1 — Run the offline hyperparameter sweep (report-only)

The sweep loads one fixed batch of trusted rows from the replay archive and trains the **real** `V2HybridPPOTrainer` under a grid of `(learning_rate, entropy_coefficient, weight_decay, dropout)`, ranking by out-of-sample validation loss with divergence rejected. Before any training, it fails closed if row-level timing implies point-in-time leakage (`available_at`, `feature_cutoff`, `source_available_time`, `masa_feature_cutoff`, or `ppo_feature_cutoff` after `decision_time`) or an unfinished candle is marked usable.

```bash
cd "/home/wali/Desktop/AI BOT REBUILD"
PYTHONPATH=. .venv/bin/python -m v2.backend.app.cli.v2_trainer_offline_hyperparameter_sweep \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT \
  --timeframes 1m,5m,15m,1h \
  --limit 4096 --steps 300 --batch-size 4096 \
  --output claude_worklog/trainer_atlas/offline_sweep.json
```

- `--from-checkpoint` starts each config from the **current** checkpoint (realistic recovery scenario). Omit it to test training from a fresh init.
- Output ends with `BEST_STABLE_CONFIG: {...} | val_loss: ... | gap: ...`.
- The JSON includes `point_in_time_safety`, `writes_checkpoint: false`, `places_real_order: false`, `routes_to_live: false`, `leverage_mutated: false`, and `margin_mutated: false`.

**Interpret:** a good config has `diverged: false`, the lowest `validation_supervised_loss`, and a small `train_val_generalization_gap` (≤ ~0.5). If **every** config diverges, lower the LR grid (e.g. add `1e-5`) — LR is the most likely divergence cause at this loss scale.
If `point_in_time_safety.passed` is false, do not tune around it; repair the replay/feedback row timing first.

---

## Step 2 — Apply the winning config (env-tunable, reversible)

All knobs are env vars, so no code change is needed. Set them on the trainer service, e.g. via a systemd drop-in (operator action — a persistent config change, so do it deliberately):

```
[Service]
Environment=V2_TRAINER_LEARNING_RATE=3e-5
Environment=V2_TRAINER_ENTROPY_COEF=0.01
Environment=V2_TRAINER_SUPERVISED_ENTROPY_BONUS=0.0
Environment=V2_TRAINER_WEIGHT_DECAY=0.02
Environment=V2_TRAINER_DROPOUT=0.10
```

Reload + restart:
```bash
systemctl --user daemon-reload
systemctl --user restart ai-bot-v2-native-cuda-trainer-persistent.service
```

**Instant revert:** remove the drop-in (or set the values back) and restart.

---

## Step 3 — Let it recover, or force a clean promotion

If the current checkpoint is degraded, the validation guard will keep rejecting until the model trains back below its loss. These are operator-controlled service config choices; the offline sweep does not promote or write checkpoint files. Two options:

- **Patient:** with a stable config the loss trends down and the guard passes naturally (`online_learning_status: WEIGHTS_UPDATING`, `checkpoint_promotion_reason: VALIDATION_GUARD_PASS`).
- **Assisted (temporary):** to let the model persist recovering weights sooner, either lower the streak escape:
  ```
  Environment=V2_TRAINER_MAX_PROMOTION_REJECTION_STREAK=5
  ```
  or temporarily set `V2_TRAINER_VALIDATION_CHECKPOINT_GUARD=false` and re-enable it once stable.

---

## Step 4 — Validate recovery

Read `v2:trainer:hybrid_cuda:status` and check:
- `online_learning_status == WEIGHTS_UPDATING`
- `last_successful_weight_update_at` advancing every cycle
- `learning_metrics.loss_after` trending down and stable (not climbing)
- `learning_metrics.ppo_entropy` ~0.3–0.6
- no persistent `TRAIN_VAL_OVERFIT_GAP` / `VALIDATION_LOSS_REGRESSED` in `checkpoint_promotion_reason`

---

## Step 5 — Re-enable guards + confirm A-grade path

Once stable, re-enable the validation guard (remove `V2_TRAINER_VALIDATION_CHECKPOINT_GUARD=false`) and restore the streak-escape default. The strict A-grade guardian and the paper-only, exchange-blocked posture are unchanged throughout — a stable, generalizing model is the prerequisite for the A-grade economic runway to begin accumulating.

---

## Notes
- The sweep and this runbook reuse the **actual** trainer components (`V2HybridPPOTrainer`, `V2HybridTrainerDataLoader`, checkpoint manager), so results transfer directly to the online loop.
- Architecture (`V2_TRAINER_HIDDEN_SIZE`, `V2_TRAINER_RESIDUAL_BLOCKS`) is a separate lever — changing it invalidates existing weight blobs (a fresh init), which the checkpoint manager handles gracefully.
- Keep runs paper/shadow. Do not add any order-submitting or exchange-mutation step to this flow.
