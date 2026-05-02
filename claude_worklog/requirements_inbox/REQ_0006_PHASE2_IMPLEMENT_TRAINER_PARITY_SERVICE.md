# Requirement 0006 - Implement V2 Trainer GPU Parity Service

Implement the non-live V2 trainer parity service based on the approved trainer GPU parity plan.

Inputs:
- claude_worklog/phase2_core_rebuild/trainer_gpu_parity/
- legacy_reference trainer files
- legacy service map
- feature snapshot foundation
- trainer/GPU parity requirements
- local secret/config key manifests, names only

Rules:
- Do not modify /home/wali/Desktop/AI BOT.
- Do not run or restart the live trainer.
- Do not write Redis.
- Do not send secrets to Claude/Codex/Ollama.
- Do not enable live trading.
- Do not build a basic trainer.
- Preserve GPU utilization assumptions, batching, checkpoint behavior, model-loading behavior, hybrid trainer architecture, confidence/reward lessons, and proposal/prediction flow.
- Add V2 service boundaries, liveness checks, prediction worker health, feature_snapshot_id, prediction_id, confidence attribution, freshness flags, stale/missing/unused flags, and local non-live tests.
- Codex review is required before advancing.

Expected result:
- V2 trainer parity service foundation implemented.
- Local tests pass.
- Codex review pass.
- No live behavior.

REQ_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE_READY
