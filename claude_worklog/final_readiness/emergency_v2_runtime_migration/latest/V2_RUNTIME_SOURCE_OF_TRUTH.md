# V2_RUNTIME_SOURCE_OF_TRUTH

Authoritative table of which V2 file or path is the source-of-truth for each runtime concern. If two sources disagree, the row below wins.

| concern | source-of-truth file/path | how to refresh |
|---|---|---|
| live gate state | `v2/frontend/public/operator_runtime/<worker>/latest/*.json` field `current_gate_state` | every worker writes it on every loop; must equal `blocked_human_only` |
| paper runtime status | `v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json` | run `paper_online_runtime` CLI |
| paper-shadow observation | `v2/frontend/public/operator_runtime/paper_shadow_observation/latest/paper_shadow_observation_status.json` | run `paper_shadow_observation` CLI |
| trainer prediction (paper) | `v2/frontend/public/operator_runtime/paper_online/latest/trainer_prediction_current_record.json` | written by paper_online_runtime |
| trainer prediction (real, future) | `v2/frontend/public/operator_runtime/v2_trainer_bridge/latest/v2_trainer_bridge_status.json` | written by P1 trainer bridge worker (not yet shipped) |
| signal lineage | `v2/frontend/public/operator_runtime/v2_signal_lineage_worker/latest/v2_signal_lineage_worker_status.json` | written by P0 signal lineage worker (queued) |
| risk gateway decision | `v2/frontend/public/operator_runtime/v2_risk_gateway_runtime_worker/latest/v2_risk_gateway_runtime_worker_status.json` | written by P0 risk gateway runtime worker (queued) |
| paper execution result | `v2/frontend/public/operator_runtime/v2_paper_execution_worker/latest/v2_paper_execution_worker_status.json` | written by P0 paper execution worker (queued) |
| execution ledger tail | `v2/frontend/public/operator_runtime/v2_execution_ledger_worker/latest/v2_execution_ledger_worker_status.json` + `v2/runtime/v2_execution_ledger_worker/latest/paper_events.jsonl` | written by P0 execution ledger worker (queued) |
| account/position state | `v2/frontend/public/operator_runtime/v2_account_position_monitor/latest/v2_account_position_monitor_status.json` | written by P0 account/position monitor (queued); paper simulations NEVER substitute |
| feature snapshot | `v2/frontend/public/operator_runtime/v2_feature_snapshot_builder/latest/v2_feature_snapshot_builder_status.json` | written by P0 feature snapshot builder (queued) |
| market intelligence (CoinAnk) | `v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json` | written by P1 CoinAnk bridge worker (queued) |
| script monitor | `v2/frontend/public/operator_runtime/v2_script_monitor/latest/v2_script_monitor_status.json` | written by P1 script monitor (queued) |
| config admin records | `v2/frontend/public/operator_runtime/v2_config_admin_manager/latest/v2_config_admin_manager_status.json` | written by P1 config/admin manager (queued) |
| dangerous-action approval tokens | `claude_worklog/approvals/` | manually created by human only; presence blocks bootstrap preflight |
| migration progress | `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/operator_dashboard_payload.json` | written by this task |
| Codex aggregate audit | `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/CODEX_GO_NO_GO.md` | updated by aggregate audit job after each per-worker review |

## Anti-patterns (never use these as source-of-truth)

- `STATIC_PROOF_FIXTURE`, `DESIGN_MOCK_DATA` — never primary on trading-platform pages.
- `hist_*` records — never as current.
- paper simulations — never as real account/PnL evidence.
- Backlog docs — never as migration evidence.
- Legacy `/home/wali/Desktop/AI BOT` paths — frozen reference only, never current.

## Freshness contract

Every payload above must include a `freshness_seconds` (or equivalent age field). The GUI must surface stale payloads with a visible badge; the Admin AI must say "Evidence missing — cannot explain without guessing" when freshness exceeds an explainability threshold.
