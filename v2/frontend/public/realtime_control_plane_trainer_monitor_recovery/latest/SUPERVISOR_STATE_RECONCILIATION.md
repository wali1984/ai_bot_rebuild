# Supervisor State Reconciliation

Generated at: 2026-05-12T21:28:24.906Z

- Queue status age seconds: 7
- Planner status age seconds: 89591
- Supervisor daemon observed: yes
- Master planner observed: yes
- Autonomous governor observed: no
- Current running task: none
- Last completed task: none
- Next pending task: LEGACY_TRAINER_RESTART_RUNTIME_CAPTURE_AND_V2_PARITY_SYNC_UNBLOCK
- Dashboard state: CURRENT_SNAPSHOT

If the control-plane daemon is expected to be active, launch/repair it through a separate non-live supervisor recovery task. This pass does not restart live trainer/trader/orchestrator/Redis/VPN.
