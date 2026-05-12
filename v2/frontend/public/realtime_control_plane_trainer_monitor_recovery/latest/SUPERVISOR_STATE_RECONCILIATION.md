# Supervisor State Reconciliation

Generated at: 2026-05-12T20:46:20.231Z

- Queue status age seconds: 1151
- Planner status age seconds: 87066
- Supervisor daemon observed: no
- Master planner observed: no
- Autonomous governor observed: no
- Current running task: none
- Last completed task: codex_parallel_review_20260512_202241_10_no_live_side_effects
- Next pending task: codex_recover_codex_recover_codex_recover_177_phase2t_decision_explainability_replay_backtest_projection_implementation
- Dashboard state: CURRENT_SNAPSHOT

If the control-plane daemon is expected to be active, launch/repair it through a separate non-live supervisor recovery task. This pass does not restart live trainer/trader/orchestrator/Redis/VPN.
