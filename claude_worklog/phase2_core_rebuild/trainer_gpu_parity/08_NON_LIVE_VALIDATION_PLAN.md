```
# Non-Live Validation Plan

This phase validates the plan only. Code-level validation occurs in a later
phase, gated on Codex pass on this plan.

## Phase 2E gate validations (this phase)

- Atlas inputs exist and parse:
  `claude_worklog/trainer_atlas/HYBRID_TRAINER_*.json` and
  `claude_worklog/trainer_atlas/HYBRID_TRAINER_*.md`.
- Coverage report shows zero unknowns:
  `claude_worklog/trainer_atlas/HYBRID_TRAINER_COVERAGE_REPORT.md`.
- All ten plan documents exist under
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/`.
- The semantic markers `PHASE2_TRAINER_GPU_PARITY_*_READY` and
  `PHASE2_TRAINER_GPU_PARITY_PLAN_READY_FOR_CODEX_REVIEW` are present.
- No Redis-state modifications proposed, no live-mode actions proposed, no
  exchange-side actions proposed, no leverage or margin-mode configuration
  changes proposed, no transition from non-live to live mode proposed.
- `legacy_reference/**` not modified.
- `/home/wali/Desktop/AI BOT` not touched.
- `v2/legacy_preserved/ingestors/live_coinank.py` not modified.
- The Codex review supervisor task
  `claude_worklog/agent_supervisor/tasks/050_trainer_gpu_parity_rebuild_plan.json`
  exists and was executed; remediation cycle is tracked by
  `claude_worklog/agent_supervisor/tasks/051_trainer_gpu_parity_plan_codex_rerun.json`.

## Future phase 2E1 validations (later phase, not this one)

- Subprocess adapter dry-run against `--mode status` only, captured under
  `claude_worklog/agent_supervisor/runtime/master_planner/`.
- Read-only liveness monitor produces an evidence packet that demonstrates
  detection of `TRAINER_PREDICTION_WORKER_DEAD_PROCESS_ALIVE`.
- Replay run produces a per-prediction lineage tuple that satisfies the
  contract in `06_TRAINER_OUTPUT_CONTRACT_AND_LINEAGE_IDS.md`, including
  the full legacy-preservation explainability field set bound by
  `04_REWARD_AND_CONFIDENCE_PARITY_MAP.md`.
- Paper run uses the trainer fleet paper adapter, not live execution.

## Live-readiness gate

Live execution against this trainer remains blocked. Final live trading
authorization is governed by
`claude_worklog/final_readiness/03_LIVE_BLOCKERS_AND_REQUIRED_APPROVALS.md`
and requires explicit human approval.

PHASE2_TRAINER_GPU_PARITY_VALIDATION_PLAN_READY
```
