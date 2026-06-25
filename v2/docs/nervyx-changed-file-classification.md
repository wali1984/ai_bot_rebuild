# NERVYX Changed File Classification

- Generated at: `2026-06-23T19:49:38.527122+00:00`
- Current branch: `codex/pipeline-trust-refresh`
- Current HEAD: `5b0a4997dae6ab50b1f3aba3327ad9959e126247`
- Merge base: `680ddfb12d2810d950f7a465a39a4fb8a77ec205`
- Complete tracked/untracked status record count: `471957`
- Compressed inventory: `artifacts/nervyx-changed-file-inventory.jsonl.gz`
- Inventory checksum: `07f3b30844d3b1cca9882b008f97d73baaa632754636eaf52140c062b2716b2b`
- Machine-readable summary: `artifacts/nervyx-changed-file-classification-summary.json`

## Classification Counts

| Classification | Count |
|---|---:|
| `DOCUMENTATION` | 143 |
| `GENERATED_ARTIFACT` | 471736 |
| `IOS_PRESENTATION` | 24 |
| `PREEXISTING_UNRELATED_CHANGE` | 601 |
| `PROTECTED_LANE_EXCEPTION` | 23 |
| `READ_ONLY_API_ADAPTER` | 2 |
| `REALTIME_TRANSPORT_ADAPTER` | 74 |
| `TEST` | 53 |
| `THEME_OR_TOKEN` | 3 |
| `WATCH_PRESENTATION` | 4 |
| `WEB_PRESENTATION` | 354 |

## Current Notes

- This is a current-state classification of every tracked and untracked changed path from `git status --porcelain=v1 -z --untracked-files=all`.
- The full per-file inventory is stored as compressed JSONL because the worktree contains hundreds of thousands of generated/runtime records.
- `PREEXISTING_UNRELATED_CHANGE` dominates because large generated/log/runtime surfaces already exist outside the NERVYX presentation lane.
- `PROTECTED_LANE_EXCEPTION` is non-zero and keeps lane isolation unproven until each protected exception is diffed, justified, and tested.
- `READ_ONLY_API_ADAPTER` covers current read-only presentation/data adapters only; it does not approve execution, risk, trainer, PPO, MASA, strategy, live-gate, order-routing, Redis producer, or database semantic changes.

## Sample Records

| Status | Classification | Path |
|---|---|---|
| ` M` | `PREEXISTING_UNRELATED_CHANGE` | `.gitignore` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/agent_supervisor/tasks/claude_continuous_remediation_review_governor_blocker_fix.json` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/agent_supervisor/tasks/claude_v2_production_replacement_runtime_loop_implementation.json` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/agent_supervisor/tasks/claude_v2_runtime_soak_and_production_equivalence_remediation.json` |
| ` M` | `DOCUMENTATION, GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/CODEX_SHUTDOWN_TAKEOVER_STATUS.md` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/blocker_matrix.json` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/codex_shutdown_takeover_status.json` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/current_recommendation.json` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/operator_dashboard_payload.json` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/shutdown_readiness_state.json` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_feature_snapshot_builder_status.json` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_risk_gateway_runtime_worker_status.json` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/legacy_runtime_gap_closure_20260603/latest/v2_trainer_checkpoint_evidence_status.json` |
| ` M` | `DOCUMENTATION, GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE, REALTIME_TRANSPORT_ADAPTER` | `claude_worklog/final_readiness/legacy_v2_realtime_decision_observatory/latest/LEGACY_V2_REALTIME_DECISION_OBSERVATORY_REPORT.md` |
| ` M` | `DOCUMENTATION, GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE, REALTIME_TRANSPORT_ADAPTER` | `claude_worklog/final_readiness/legacy_v2_realtime_decision_observatory/latest/NEXT_DECISION_IMPROVEMENT_TASKS.md` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE, REALTIME_TRANSPORT_ADAPTER` | `claude_worklog/final_readiness/legacy_v2_realtime_decision_observatory/latest/codex_legacy_v2_realtime_decision_observatory_status.json` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE, REALTIME_TRANSPORT_ADAPTER` | `claude_worklog/final_readiness/legacy_v2_realtime_decision_observatory/latest/decision_quality_scoreboard_status.json` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE, REALTIME_TRANSPORT_ADAPTER` | `claude_worklog/final_readiness/legacy_v2_realtime_decision_observatory/latest/legacy_runtime_observer_status.json` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE, REALTIME_TRANSPORT_ADAPTER` | `claude_worklog/final_readiness/legacy_v2_realtime_decision_observatory/latest/legacy_signal_outcome_observer_status.json` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE, REALTIME_TRANSPORT_ADAPTER` | `claude_worklog/final_readiness/legacy_v2_realtime_decision_observatory/latest/legacy_v2_decision_comparator_status.json` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE, REALTIME_TRANSPORT_ADAPTER` | `claude_worklog/final_readiness/legacy_v2_realtime_decision_observatory/latest/next_decision_improvement_tasks.json` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE, REALTIME_TRANSPORT_ADAPTER` | `claude_worklog/final_readiness/legacy_v2_realtime_decision_observatory/latest/operator_dashboard_payload.json` |
| ` M` | `DOCUMENTATION, GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/observatory_to_action_controller_patch/latest/OBSERVATORY_TO_ACTION_CONTROLLER_PATCH_REPORT.md` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/observatory_to_action_controller_patch/latest/operator_dashboard_payload.json` |
| ` M` | `DOCUMENTATION, GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/PRODUCTION_URL_ROUTE_CRAWL_REPORT.md` |
| ` M` | `DOCUMENTATION, GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/ROUTE_FAILURE_CLASSIFICATION.md` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/production_route_matrix.json` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/production_route_matrix_before.json` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_.png` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin.png` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_audit-ledger_role_admin.png` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_build-validation-status_role_admin.png` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_claude-admin-ai_role_admin.png` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_codex-review-center_role_admin.png` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_config-admin_role_admin.png` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_coverage-system-atlas_role_admin.png` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_exchange-manager_role_admin.png` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_execution-admin_role_admin.png` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_executions_role_admin.png` |
| ` M` | `GENERATED_ARTIFACT, PREEXISTING_UNRELATED_CHANGE` | `claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_external-manual-position-quarantine_role_admin.png` |
