# Trainer/Trader Runtime Monitor Status

Generated at: 2026-05-13T06:26:43.149Z

Read-only process observations:

| item | status |
| --- | --- |
| legacy_trainer_observed | true |
| legacy_trader_observed | true |
| legacy_orchestrator_observed | true |
| v2_paper_runtime_observed | true |

Monitor rows:

| item | status |
| --- | --- |
| legacy trainer process | OBSERVED_READONLY |
| trainer GPU state | PROCESS_OBSERVED_METRICS_PENDING |
| orchestrator process | OBSERVED_READONLY |
| trader process | OBSERVED_READONLY |
| latest V2 paper signal | MISSING_EVIDENCE |
| missing signal_id/confidence blocker | RISK_GATEWAY_POLICY_REQUIRED_CONTINUES |
| duplicate exchange order identifier audit | DEDUPE_POLICY_REQUIRED_CONTINUES |
| leverage-risk action audit | NO_CHANGE_BY_THIS_TASK |

No legacy service was restarted and no legacy code was modified by this task.
