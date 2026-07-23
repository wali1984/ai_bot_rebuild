# Three-Hour A+ Recovery Checkpoint

- T0: `2026-07-23T17:15:13-04:00`
- Branch / HEAD: `codex/pipeline-trust-refresh` / `94b5860f1d`
- Usage ceiling: Cursor’s remaining-usage figure is not available to this agent; no budget value is asserted.
- Worktree: 96 pre-existing dirty paths, preserved and excluded from this recovery.
- Safety at T0: backend and frontend return HTTP 200; Redis `PONG`; API payloads report `live_gate=blocked_human_only`, `routes_to_live=false`, and `places_real_order=false`.

## Active five-blocker queue

1. **Trainer data supply:** `v2:trainer:champion_challenger_status.backtests_processed` is `train_rows=0`, `validation_rows=0`, `untouched_holdout_rows=0`; the causal PIT importer has not yet written its first completed checkpoint.
2. **Trainer runtime publication:** `/api/v2/trainer/status` is stale by `489367.546s`; `ai-bot-v2-champion-challenger-publisher.service` is inactive.
3. **Moralis usable-data path:** the service is active and CU ledger is ready, but provider status is `ISOLATED_BY_POLICY`, `actual_payload_count=0`, `feature_count=0`, and `last_success_utc=null`.
4. **Liquidation event / level freshness:** raw liquidation and liquidation-level status are stale (`391.5s`) despite both canonical services being active.
5. **Prediction-to-paper supply:** no evaluated challenger exists (`best_challenger_id=null`) and therefore no trusted publisher output can reach orchestrator/paper admission.

## Verified active canonical runtime owners

- Backend `ai-bot-v2-public-website-backend`; frontend `ai-bot-v2-frontend-vite`.
- Binance kline, mark-price, metadata, KuCoin, CoinGlass, CoinAPI optional fallback, CoinAnk, and feature pipeline services are active.
- Moralis, liquidation WSS, Liquidation Level Engine, profiled feature publisher, native CUDA trainer, orchestrator, risk gateway, and paper loop are each represented by one active canonical process in the T0 process sample.

## Deferred for this recovery window

Inactive one-shot/telemetry services not proven to block the five items above; broad audits; frontend/iOS changes; paper-loop source edits; live execution changes.

## Added non-negotiable CUDA trainer constraints

- Neural-network training and promotion evaluation are CUDA-only. CUDA unavailability, CPU-resident trainable parameters, CPU batches/losses/gradients, or a CPU optimizer must fail closed and publish an explicit blocker; no CPU fallback is permitted.
- The online trainer and evidence maintenance are separate responsibilities. An ordinary authenticated shard must be delta-only: no historical archive refreeze or 60,000-snapshot rescan in its critical path. Targets are one row under 10 seconds, a small shard under 30 seconds, and first CUDA update under 60 seconds.
- The current deployed process is accurately classified as `BLOCKED_NO_AUTHENTICATED_ROWS`, not `CUDA_TRAINING_ACTIVE`: PyTorch `2.10.0+cu128`, CUDA `12.8`, one NVIDIA GeForce RTX 5080 (compute capability `12.0`) are available, but current status reports zero authenticated train/validation/holdout rows and exposes no completed CUDA optimizer step.
- Before trainer A+ can be claimed, runtime telemetry must prove the selected CUDA device, model-parameter device, first-batch device, loss device, optimizer-parameter devices, AMP mode, and at least two CUDA optimizer steps. Evidence-maintenance work must not hold the online trainer path.
