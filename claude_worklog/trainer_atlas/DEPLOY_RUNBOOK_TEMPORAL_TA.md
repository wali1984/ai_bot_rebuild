# Operator Runbook — Deploy the temporal + TA-expanded model (OPERATOR-GATED)

Prepared for Wali to execute. Claude does NOT restart the persistent trainer or promote
to the deployed checkpoint automatically (per the safety policy). These are the exact
steps + verification. Everything here is paper/shadow training — the gate env (value
`blocked_human_only`) stays unchanged; nothing here enables order placement.

## What this deploys
The offline-proven model that beats the deployed incumbent on every axis:
- Sortino 0.140 -> 0.451, CVaR -648 -> -544, composite -0.508 -> -0.093.
- Two changes vs the currently-deployed trainer:
  1. TA feature expansion (model_vector 1248 -> 1832) — ALREADY in code (committed
     dd10b777ff); the trainer builds 1832-dim examples automatically on restart.
  2. Temporal GRU encoder — needs an env flag + a warm-start checkpoint.

## Pre-checks
```bash
cd "/home/wali/Desktop/AI BOT REBUILD"
git log --oneline -1                             # expect the TA-expansion commits present
redis-cli TYPE v2:features:ta_full:BTCUSDT:1m    # expect "string" (TA data flowing)
ls -la .local_models/v2_native_rl_masa_ppo_temporal_feat/   # the offline candidate
systemctl --user status ai-bot-v2-trainer-scheduled-pretrain.timer  # avoid overlap
```

## Step 1 — add the temporal env to the persistent trainer unit
Append these to the `[Service]` section of
`ai-bot-v2-native-cuda-trainer-persistent.service` (HIDDEN_SIZE/RESIDUAL_BLOCKS are
already 2048/4, which the offline checkpoint used):
```
Environment=V2_TRAINER_TEMPORAL_ENCODER=gru
Environment=V2_TRAINER_TEMPORAL_PROJ_DIM=256
```
Then: `systemctl --user daemon-reload`

## Step 2 — promote the offline candidate to the deployed checkpoint (DRY-RUN FIRST)
The H2L gate compares candidate vs incumbent on held-out rows; run WITH the same temporal
env so both models load at the correct architecture. Dry-run (no --confirm) first:
```bash
export V2_TRAINER_TEMPORAL_ENCODER=gru V2_TRAINER_TEMPORAL_PROJ_DIM=256
export V2_TRAINER_HIDDEN_SIZE=2048 V2_TRAINER_RESIDUAL_BLOCKS=4
export PYTHONPATH="/home/wali/Desktop/AI BOT REBUILD"
.venv/bin/python -m v2.backend.app.cli.v2_trainer_h2l_promote \
  --offline-dir .local_models/v2_native_rl_masa_ppo_temporal_feat --output /tmp/h2l_dryrun.json
cat /tmp/h2l_dryrun.json    # confirm the gate PASSES (candidate beats incumbent)
```
NOTE: the incumbent is single-frame 1248-dim and the candidate is temporal 1832-dim, so
the gate loads two different architectures. If the tool refuses the cross-arch compare,
instead COLD-START: skip the promote and let the restarted trainer build a fresh temporal
1832-dim lineage (Step 3) — it retrains online, and the scheduled offline pretrain
(temporal_feat) becomes the promotion source once both are the same arch. If the dry-run
passes, promote for real:
```bash
.venv/bin/python -m v2.backend.app.cli.v2_trainer_h2l_promote \
  --offline-dir .local_models/v2_native_rl_masa_ppo_temporal_feat --confirm --output /tmp/h2l_promote.json
```

## Step 3 — restart the trainer
```bash
systemctl --user restart ai-bot-v2-native-cuda-trainer-persistent.service
```

## Step 4 — verify (within a few cycles)
```bash
redis-cli --no-raw GET v2:trainer:hybrid_cuda:status | python3 -m json.tool | grep -iE "input_dim|temporal|model_id|cycle"
python tools/tail_native_cuda_trainer.py     # watch a few cycles advance
redis-cli HGET v2:prediction:BTCUSDT:5m direction   # predictions flowing again
```
Expect: input_dim 1832, a temporal-forked model_id, predictions non-nil.

## Rollback (fully reversible)
```bash
# remove the two Environment= lines, daemon-reload, restart:
systemctl --user daemon-reload
systemctl --user restart ai-bot-v2-native-cuda-trainer-persistent.service
```
The prior single-frame deployed checkpoint is untouched unless Step 2 --confirm ran; if it
did, restore from the checkpoint backup the promote tool writes (path in /tmp/h2l_promote.json).

## Safety
- The gate env stays `blocked_human_only`. No order placement, position-size, or
  account-risk-mode changes.
- Paper/shadow trainer only. Reversible via env removal + restart.
- The Step 4c prediction rolling-window buffer activates only with the temporal env set.
