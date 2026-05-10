# Autonomy Simulation Results

Generated: `2026-05-10T21:01:12.695136+00:00`

Overall: `PASS`

| Case | Expected | Actual | Result |
| --- | --- | --- | --- |
| non_live_decision_packet | global_queue_continues | global_queue_continues | PASS |
| final_live_gate_task | blocked_final_live_gate | blocked_final_live_gate | PASS |
| codex_fail_safe_remediation | claude_remediation_scheduled | claude_remediation_scheduled | PASS |
| stale_running_task | recovery_scheduled | recovery_scheduled | PASS |
| redis_trim_hold_blocker | phase3h_deferred_next_safe_task_selected | phase3h_deferred_next_safe_task_selected | PASS |
