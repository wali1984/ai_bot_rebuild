# Validation Commands

```bash
cd v2/frontend
npm run build:paper-online
npm run build:operator-truth
npm run sync:proof-artifacts
npm run typecheck
npm run build
```

Git snapshot at generation:

- git status: `M claude_worklog/final_readiness/v2_paper_online_recovery/latest/NO_LIVE_MUTATION_SAFETY_REPORT.md
 M claude_worklog/final_readiness/v2_paper_online_recovery/latest/PAPER_RUNTIME_WIRING_REPORT.md
 M claude_worklog/final_readiness/v2_paper_online_recovery/latest/RUNTIME_DATA_VISIBILITY_REPORT.md
 M claude_worklog/final_readiness/v2_paper_online_recovery/latest/V2_PAPER_ONLINE_FULL_OPERATIONAL_RECOVERY_REPORT.md
 M claude_worklog/final_readiness/v2_paper_online_recovery/latest/admin_ai_status.json
 M claude_worklog/final_readiness/v2_paper_online_recovery/latest/current_risk_decisions.json
 M claude_worklog/final_readiness/v2_paper_online_recovery/latest/current_signal_lineage.json
 M claude_worklog/final_readiness/v2_paper_online_recovery/latest/market_feed_status.json
 M claude_worklog/final_readiness/v2_paper_online_recovery/latest/operator_dashboard_payload.json
 M claude_worklog/final_readiness/v2_paper_online_recovery/latest/paper_ledger_tail.json
 M claude_worklog/final_readiness/v2_paper_online_recovery/latest/paper_positions.json
 M claude_worklog/final_readiness/v2_paper_online_recovery/latest/paper_runtime_status.json
 M claude_worklog/final_readiness/v2_paper_online_recovery/latest/supervisor_current_truth.json
 M claude_worklog/final_readiness/v2_paper_online_recovery/latest/trainer_prediction_current_record.json
 M claude_worklog/final_readiness/v2_paper_online_recovery/latest/trainer_runtime_current_status.json
 M claude_worklog/final_readiness/v2_paper_online_recovery/latest/v2_data_plane_status.json
 M v2/frontend/package.json
 M v2/frontend/scripts/sync-proof-artifacts.mjs
 M v2/frontend/src/pages/live-readiness/index.tsx
 M v2/frontend/src/pages/operatorTruthData.ts
?? v2/backend/app/cli/tonight_live_like_paper_shadow.py
?? v2/frontend/scripts/crawl-tonight-routes.mjs`
- git head: `075c81c Add Codex parallel review batch results`
