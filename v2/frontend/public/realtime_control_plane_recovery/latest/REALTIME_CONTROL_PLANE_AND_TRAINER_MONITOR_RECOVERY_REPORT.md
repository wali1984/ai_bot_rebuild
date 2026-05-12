# Realtime Control Plane And Trainer Monitor Recovery Report

Status: REALTIME_CONTROL_PLANE_AND_TRAINER_MONITOR_RECOVERY_READY

Generated at: 2026-05-12T21:40:18.138Z

Mission Control is now treated as an operational truth surface, not a proof dump. The first screen prioritizes live/safety state, actual observed runtime processes, current/next task, trainer runtime status, orchestrator/risk/execution status, signal lineage classification, payload freshness, blockers, and links to detail pages.

Current facts:

- Live trading: blocked_human_only
- Redis trim: deferred_non_blocking
- Supervisor observed: yes
- Current task: none
- Last completed task: none
- Next task: LEGACY_TRAINER_RESTART_RUNTIME_CAPTURE_AND_V2_PARITY_SYNC_UNBLOCK
- Trainer runtime state: V2_PAPER_TRAINER_WRAPPER_CURRENT
- Market ingestors observed: 6
- Feature pipeline observed: 1
- Orchestrator observed: 2
- Trader observed: 1
- Stale payloads: 11
- Warning payloads: 1
- Missing evidence rows: 1

No live, Redis write, exchange, leverage, margin, or legacy-code mutation was performed.
