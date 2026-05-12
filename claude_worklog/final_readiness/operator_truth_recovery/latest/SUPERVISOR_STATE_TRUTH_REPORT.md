# Supervisor State Truth Report

Generated at: 2026-05-12T05:07:18.942Z

- Supervisor alive: yes
- Heartbeat stale: no
- Master planner running: no
- Autonomous governor active: no
- Current running task: none
- Last completed task: codex_recover_173_phase2r_decision_explainability_data_contract_python_source_end_file_marker_leakage_cleanup
- Last task status: completed
- True next task: codex_recover_173_phase2r_reconciliation_residual_end_file_marker_leakage_cleanup
- Queue age seconds: 8
- Planner age seconds: 30725
- Dashboard conflict state: CURRENT_SNAPSHOT

Active automation processes:

- `1035556 1011413 255792 python3 ingest/live_binance.py`
- `1035713 1011413 255781 python3 ingest/live_kucoin.py`
- `1035811 1011413 255774 python3 ingest/live_coinank.py`
- `1035965 1011413 255765 python3 ingest/live_coinank_global_aggregator.py`
- `1036143 1011413 255754 python3 ingest/live_binance_liquidations.py`
- `1038292 1011413 255666 python3 feature_pipeline.py`
- `1038859 1011413 255640 python3 ingest/live_technical_analysis.py`
- `1042465 1011413 255547 python3 -m rl.orchestrator_worker`
- `1272209 1272100 211372 tail -f Desktop/AI BOT/logs/orchestrator_worker.log`
- `3324271 1011413 13169 /bin/bash -O extglob -c snap=$(command cat <&3) && builtin shopt -s extglob && builtin eval -- "$snap" && { builtin set +u 2>/dev/null || true; builtin eval "${__CURSOR_SANDBOX_ENV_RESTORE:-}" 2>/dev/null; builtin export...`
- `3324274 3324271 13169 python3 -u trading/trader.py`
- `3446733 1011413 5638 python3 -m v2.backend.app.cli.paper_online_runtime --loop --interval 30`
- `3516630 1029421 553 python3 claude_worklog/tools/agent_supervisor.py --daemon --poll-seconds 30`

Repair needed:

- No supervisor truth repair required from this snapshot.
