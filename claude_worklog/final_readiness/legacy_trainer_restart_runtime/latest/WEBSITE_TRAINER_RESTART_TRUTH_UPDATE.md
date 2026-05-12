# Website Trainer Restart Truth Update

Generated: 2026-05-12T16:50:13Z

Updated payloads:

- `claude_worklog/final_readiness/legacy_trainer_restart_runtime/latest/operator_dashboard_payload.json`
- `v2/frontend/public/legacy_trainer_restart_runtime/latest/operator_dashboard_payload.json`
- `v2/frontend/public/operator_truth/latest/operator_truth_bridge_payload.json` after `npm run build:operator-truth`

Frontend support was added so Mission Control, Trainer Prediction Monitor, Signal Explainability, and Risk-adjacent truth panels can display:

- legacy trainer process state,
- legacy GPU state,
- legacy output status,
- V2 paper wrapper status,
- parity status,
- legacy publish/execution risk,
- live gate `blocked_human_only`.
