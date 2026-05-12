# Operator Truth Dashboard And Realtime Trainer Monitor Report

Status: OPERATOR_TRUTH_DASHBOARD_AND_REALTIME_TRAINER_MONITOR_RECOVERY_READY

Generated at: 2026-05-12T03:20:00.556Z

This pass creates a single operator truth payload and wires the dashboard to it so the operator can distinguish current runtime evidence, runtime monitor payloads, static proof fixtures, stale payloads, and missing evidence.

Key truths:

- Live trading: blocked_human_only
- Redis trim: deferred_non_blocking
- Supervisor truth: SUPERVISOR_STATUS_STALE_OR_CONFLICTING
- Trainer monitor: TRAINER_RUNTIME_EVIDENCE_MISSING
- Legacy orchestrator process: PROCESS_OBSERVED_READONLY
- Trader process: PROCESS_OBSERVED_READONLY
- Market ingestors: PROCESS_OBSERVED_READONLY (6)
- Feature pipeline: PROCESS_OBSERVED_READONLY (1)
- Current next task: codex_recover_173_phase2r_consolidated_python_source_and_task_json_end_file_leakage_cleanup
- Stale payload count: 12
- Missing evidence count: 3

The dashboard now labels fixture/static data instead of treating it as live runtime truth.
