# Paper Online Canonical Truth Verification Report

Generated at: 2026-05-12T05:10:44.420Z

- Runtime age seconds: `1`
- Runtime state: `PAPER_RUNTIME_ONLINE_ACTIVE`
- Bridge status: `PAPER_ONLINE_CANONICAL_TRUTH_ACTIVE`
- Bridge source: `v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json`
- Bridge uses paper runtime as canonical source: `true`
- Stale operator_truth_payload overrides bridge: `false`
- Trainer: `V2_PAPER_TRAINER_WRAPPER_CURRENT`
- Signal lineage: `REALTIME_RUNTIME_EVIDENCE`
- Live gate: `blocked_human_only`
- Legacy Redis writes: `false`
- Exchange orders: `false`

## Current IDs

- prediction_id: `pred_paper_tick_1778562643286`
- feature_snapshot_id: `fs_paper_tick_1778562643286`
- signal_id: `sig_paper_tick_1778562643286`
- orchestrator_decision_id: `orch_paper_tick_1778562643286`
- risk_decision_id: `risk_paper_tick_1778562643286`
- execution_intent_id: `pei_paper_tick_1778562643286`
- paper ledger tail entries: `1`

Verdict: PASS for canonical runtime truth. Final READY is blocked until the recovered supervisor queue stops adding unrelated non-live recovery artifacts and the worktree can be made clean without interfering with active worker output.
