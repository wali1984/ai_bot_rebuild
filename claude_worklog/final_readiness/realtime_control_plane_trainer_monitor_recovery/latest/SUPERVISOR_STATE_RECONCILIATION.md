# Supervisor State Reconciliation

Generated at: 2026-05-12T03:20:00.556Z

- Queue status age seconds: 3570
- Planner status age seconds: 24286
- Supervisor daemon observed: no
- Master planner observed: no
- Autonomous governor observed: no
- Current running task: none
- Last completed task: codex_parallel_review_20260512_021504_06_paper_mode
- Next pending task: codex_recover_173_phase2r_consolidated_python_source_and_task_json_end_file_leakage_cleanup
- Dashboard state: SUPERVISOR_STATUS_STALE_OR_CONFLICTING

If the control-plane daemon is expected to be active, launch/repair it through a separate non-live supervisor recovery task. This pass does not restart live trainer/trader/orchestrator/Redis/VPN.
