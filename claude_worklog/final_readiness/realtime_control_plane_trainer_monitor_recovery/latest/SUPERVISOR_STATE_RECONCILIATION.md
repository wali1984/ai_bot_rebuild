# Supervisor State Reconciliation

Generated at: 2026-05-12T23:05:32.391Z

- Queue status age seconds: 25
- Planner status age seconds: 95418
- Supervisor daemon observed: yes
- Master planner observed: no
- Autonomous governor observed: no
- Current running task: none
- Last completed task: none
- Next pending task: SAFE_LEGACY_TRAINER_BRIDGE_AND_GPU_PARITY_SANDBOX
- Dashboard state: CURRENT_SNAPSHOT

If the control-plane daemon is expected to be active, launch/repair it through a separate non-live supervisor recovery task. This pass does not restart live trainer/trader/orchestrator/Redis/VPN.
