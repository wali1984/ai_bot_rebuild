# Operator Truth Dashboard And Realtime Trainer Monitor Report

Status: OPERATOR_TRUTH_DASHBOARD_AND_REALTIME_TRAINER_MONITOR_RECOVERY_READY

Generated at: 2026-05-12T23:05:32.391Z

This pass creates a single operator truth payload and wires the dashboard to it so the operator can distinguish current runtime evidence, runtime monitor payloads, static proof fixtures, stale payloads, and missing evidence.

Key truths:

- Live trading: blocked_human_only
- Redis trim: deferred_non_blocking
- Supervisor truth: CURRENT_SNAPSHOT
- Trainer monitor: V2_PAPER_TRAINER_WRAPPER_CURRENT
- Legacy orchestrator process: PROCESS_OBSERVED_READONLY
- Trader process: PROCESS_OBSERVED_READONLY
- Market ingestors: PROCESS_OBSERVED_READONLY (6)
- Feature pipeline: PROCESS_OBSERVED_READONLY (1)
- Current next task: SAFE_LEGACY_TRAINER_BRIDGE_AND_GPU_PARITY_SANDBOX
- Stale payload count: 13
- Missing evidence count: 1

The dashboard now labels fixture/static data instead of treating it as live runtime truth.
