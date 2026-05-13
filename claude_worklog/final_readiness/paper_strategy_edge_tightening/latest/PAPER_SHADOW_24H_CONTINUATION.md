# Paper Shadow 24H Continuation

Generated at: `2026-05-13T19:39:02Z`

| Field | Value |
| --- | --- |
| generated_at | 2026-05-13T19:39:02Z |
| paper_online_runtime_running | True |
| paper_shadow_observation_running | True |
| process_evidence | ["573824 1011413   43296  0.0  0.0 python3 -m v2.backend.app.cli.paper_online_runtime --loop --interval 30", "573883 1011413   43291  0.0  0.0 bash -c while true; do python3 -m v2.backend.app.cli.paper_shadow_observation --write >> v2/runtime/paper_shadow_observation/latest/paper_shadow_observation.log 2>&1; sleep 300; done"] |
| observation_started_at | 2026-05-13T07:21:34Z |
| elapsed_observation_seconds | 44248 |
| runtime_age_seconds | 0 |
| status_1h | PAPER_SHADOW_1H_COMPLETE |
| status_6h | PAPER_SHADOW_6H_COMPLETE |
| status_24h | PAPER_SHADOW_24H_PENDING |
| paper_events_count | 1316 |
| simulated_fills | 1192 |
| blocked_intents | 124 |
| paper_pnl_current_usdt | -38.33 |
| paper_pnl_6h_delta_usdt | -6.1 |
| paper_pnl_24h_delta_usdt | -11.96 |
| classifications | ["PAPER_SHADOW_6H_COMPLETE", "PAPER_SHADOW_24H_PENDING", "PAPER_SHADOW_MONITOR_RUNNING", "PAPER_SHADOW_PROFITABILITY_PROOF_NEGATIVE_6H", "PAPER_SHADOW_PROFITABILITY_PROOF_PENDING_24H"] |
