# Supervisor State Truth Report

Generated at: 2026-05-11T23:57:56.729Z

- Supervisor alive: no
- Heartbeat stale: yes
- Master planner running: no
- Autonomous governor active: no
- Current running task: parallel_capacity_readonly_review_phase2f_b_evidence_reconciliation_passed
- True next task: codex_recover_173_phase2r_consolidated_python_source_and_task_json_end_file_leakage_cleanup
- Queue age seconds: 2011
- Planner age seconds: 12163
- Dashboard conflict state: SUPERVISOR_STATUS_STALE_OR_CONFLICTING

Active automation processes:

- `1042465 1011413  236985 python3 -m rl.orchestrator_worker`
- `1272209 1272100  192810 tail -f Desktop/AI BOT/logs/orchestrator_worker.log`

Repair needed:

- Refresh/restart non-live supervisor/governor status generation when safe; dashboard must show stale/conflicting until then.
