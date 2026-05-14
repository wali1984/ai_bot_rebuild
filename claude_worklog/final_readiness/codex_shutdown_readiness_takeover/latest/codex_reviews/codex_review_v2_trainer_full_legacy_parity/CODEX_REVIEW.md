# Codex Review: V2 Trainer Bridge Full Legacy Parity

Verdict: PASS for Claude's conservative blocked classification. This does not clear trainer parity and does not approve legacy shutdown.

Findings:

- No blocking review finding against the emitted result. Claude did not silently drop the legacy trainer gap: the task status keeps `accepted_as_legacy_hybrid_prediction=false`, `runtime_evidence_status=WRAPPER_NOT_LEGACY_HYBRID_PARITY`, `checkpoint_evidence_status=MISSING_OR_REJECTED`, and `trainer_bridge_parity=BLOCKED`.
- Current readiness still blocks shutdown on trainer parity: `WRAPPER_NOT_LEGACY_HYBRID_PARITY`, `CHECKPOINT_EVIDENCE_MISSING_OR_REJECTED`, and `TRAINER_EXTERNAL_DEPS_MISSING_IN_V2_VENV` remain present in the current blocker matrix/status payloads.
- Required SHA evidence is present and verified for the cited preserved legacy trainer sources:
  `rl/hybrid_trainer.py=b7dad66b63b57c0d5c29e0fbaf67466d9c2aab81baf7a4f67b6e681e38c5b102`,
  `rl/orchestrator_worker.py=a7ff83f992c6b0add14e4563241080cce431906642c0de6aa778d3fb9eb217c6`,
  `rl/unified_feature_builder.py=2af5c68d812c0a0a5db2e037204f0b2165d9084dea983d1737e09034e8c739a5`,
  `rl/obs_schema.py=9ec040fa1306ac28f4395aac103b104eb02644866ca8acec5577b155fd925f5f`.
- V2 trainer bridge source remains fail-closed for wrapper predictions: `V2_PAPER_TRAINER_WRAPPER` is rejected as `WRAPPER_NOT_LEGACY_HYBRID_PARITY`, `predictions_emitted_total` stays `0`, and current public payload reports `subprocess_invocation=not_started_by_bridge`.
- No old Redis writer, exchange mutation, leverage mutation, margin-mode mutation, or live enablement path was found in the reviewed V2 trainer bridge source/tests. Current payloads report `live_gate=blocked_human_only`, `live_symbols=[]`, approval tokens absent, `exchange_action_taken=false`, `legacy_mutation_performed=false`, and `old_redis_write_performed=false`.
- V2 environment dependency evidence is still blocked as reported: `torch`, `stable_baselines3`, `cloudpickle`, and `gymnasium` are not importable from `.venv`.
- Tests exist for the touched/relevant behavior: wrapper rejection, accepted legacy-shaped payload mapping, stale/generic source rejection, feature flag blocking, symbol scope preservation, mutation-token scan, subprocess argv/env/audit/timeout, and `shell=False`.

Validation:

- `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/pytest -q v2/backend/tests/integration/cli/test_v2_trainer_bridge.py v2/backend/tests/unit/adapters/trainer -p no:cacheprovider --basetemp=/tmp/codex_trainer_bridge_pytest` passed: 38 tests.
