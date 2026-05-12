# Operator Truth Dashboard And Realtime Trainer Monitor Report

Status: OPERATOR_TRUTH_DASHBOARD_AND_REALTIME_TRAINER_MONITOR_RECOVERY_READY

Generated at: 2026-05-12T20:46:20.231Z

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
- Current next task: codex_recover_codex_recover_codex_recover_177_phase2t_decision_explainability_replay_backtest_projection_implementation
- Stale payload count: 14
- Missing evidence count: 1

The dashboard now labels fixture/static data instead of treating it as live runtime truth.
