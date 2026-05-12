# Supervisor State Truth Report

Generated at: 2026-05-12T00:01:49.073Z

- Supervisor alive: no
- Heartbeat stale: yes
- Master planner running: no
- Autonomous governor active: no
- Current running task: parallel_capacity_readonly_review_phase2f_b_evidence_reconciliation_passed
- True next task: codex_recover_173_phase2r_consolidated_python_source_and_task_json_end_file_leakage_cleanup
- Queue age seconds: 2243
- Planner age seconds: 12395
- Dashboard conflict state: SUPERVISOR_STATUS_STALE_OR_CONFLICTING

Active automation processes:

- `1042465 1011413  237217 python3 -m rl.orchestrator_worker`
- `1272209 1272100  193042 tail -f Desktop/AI BOT/logs/orchestrator_worker.log`

Repair needed:

- Refresh/restart non-live supervisor/governor status generation when safe; dashboard must show stale/conflicting until then.
