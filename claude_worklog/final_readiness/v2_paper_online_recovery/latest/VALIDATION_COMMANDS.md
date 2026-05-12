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
 M claude_worklog/final_readiness/v2_paper_online_recovery/latest/v2_data_plane_status.json`
- git head: `a8e6f7d Codex watchdog recover dirty non-live automation artifacts`
