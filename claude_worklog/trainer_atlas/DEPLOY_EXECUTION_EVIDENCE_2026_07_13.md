# Deploy Execution Evidence — temporal + TA model (2026-07-13, operator-authorized)

## Claim
The temporal+TA (1832-dim) model is deployed on the persistent trainer, an
offline-trained checkpoint was PROMOTED through the H2L Sortino/CVaR gate, the
replay archive now captures the full tensor feature view, and every GUI/iOS
surface serves the new runtime truths.

## Timeline + raw evidence (all times EDT 2026-07-13)

1. **10:32** — temporal env (`V2_TRAINER_TEMPORAL_ENCODER=gru`, `PROJ_DIM=256`)
   added to `ai-bot-v2-native-cuda-trainer-persistent.service` +
   `ai-bot-v2-trainer-scheduled-pretrain.service`; daemon-reload; trainer restart.
   Verified via `/proc/<pid>/environ`.
2. **10:41** — cycle 1 published `input_dim: 1832` to `v2:trainer:hybrid_cuda:status`;
   fresh lineage cold-started (`checkpoint_promotion_reason: NO_PRIOR_CHECKPOINT_TO_RESTORE`,
   shape guard active); predictions flowing (14:39:51Z, new model_id 28e95fec...).
   Archive records jumped 380 -> 593 features (publisher full-feature-view fix live).
3. **10:34 pretrain fire OOM'd** — collided with cold-start + default `--batch-size 4096`
   (16x temporal memory). Fix: unit now runs `--batch-size 512 --train-rows 16000` +
   `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`.
4. **10:45 manual pretrain (round 1)** — trained on a STALE pre-expansion cache
   (h2l input_dim 1248) -> `ABORT_CHECKPOINT_LOAD_FAILED_OR_SHAPE_MISMATCH`.
   Lesson: purge `scheduled_pretrain_cache.pkl` + `h2l_heldout_cache.pkl` whenever
   the feature spec/arch changes.
5. **10:56 manual pretrain (round 2, fresh 1832 caches)** — **PROMOTED.**
   Report `scheduled_pretrain_1783955269.json`:
   - offline val loss 37.76 vs incumbent 49.91
   - risk gate (`head_to_head.risk_adjusted_validation.gate`): `passed: true`,
     offline_sortino 0.2651 vs live 0.0582, offline_cvar -814.2 vs live -833.3,
     offline OOS trades 2253
   - backup: `.local_models/v2_native_rl_masa_ppo_backup_20260713T150743Z`
6. **11:12** — trainer restarted; loads the PROMOTED checkpoint; publishes
   `model_architecture.temporal_encoder: gru / seq 16 / input_dim 1832`.
7. **11:50** — prediction fast-path parity fix (commit 6206c56ad7): supplemental
   payloads `microstructure_trust` / `moralis_features` / `altdata_confluence` /
   `smart_money_signals` added (slow path had them; fast path didn't). Trainer
   restarted. Verified: BTCUSDT 1m record at 16:02:49Z has **639 features** incl.
   `microstructure_trust_score` + `altdata_confluence_long_score`.
8. **GUI truth chain** (commits 6011574397 + 63fc9f59c1): `/api/v2/trainer/status`
   serves input_dim/feature_count/temporal/offline_pretrain_status(+risk gate);
   `/api/v2/ai/predictions` calibration truth fixed; mobile routes + iOS
   structs/views updated; web rebuilt + redeployed on :5173.

## Verification commands
- `redis-cli GET v2:trainer:hybrid_cuda:status | jq '.input_dim, .model_architecture'`
- `curl -s localhost:8000/api/v2/trainer/status | jq '.input_dim, .feature_count, .temporal_encoder, .offline_pretrain_status'`
- newest archive blob via `manifest.jsonl` -> features count + family spot-checks

## Honest gaps (source-side, not pipeline)
- `fvg_*` / `structure_*`: publisher emits a masked shell when no event is active.
- `moralis_*`: provider `features` dict empty (token-map gap; Codex bootstrap goal).
- trust/confluence publish per-(symbol,tf) subsets (e.g. trust only at 1m) — honest masks elsewhere.

## Safety
Gate env `blocked_human_only` unchanged throughout; paper/shadow only; no order
placement; promoted checkpoint fully backed up; every restart operator-authorized.
