# Supervisor State Reconciliation

Generated at: 2026-05-12T19:58:03.594Z

- Queue status age seconds: 482
- Planner status age seconds: 84169
- Supervisor daemon observed: no
- Master planner observed: no
- Autonomous governor observed: no
- Current running task: none
- Last completed task: codex_parallel_review_20260512_194507_07_shadow_readiness
- Next pending task: codex_recover_codex_recover_codex_recover_177_phase2t_decision_explainability_replay_backtest_projection_implementation
- Dashboard state: CURRENT_SNAPSHOT

If the control-plane daemon is expected to be active, launch/repair it through a separate non-live supervisor recovery task. This pass does not restart live trainer/trader/orchestrator/Redis/VPN.
