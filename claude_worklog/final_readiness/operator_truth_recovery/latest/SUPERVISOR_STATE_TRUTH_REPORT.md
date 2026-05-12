# Supervisor State Truth Report

Generated at: 2026-05-12T03:33:51.749Z

- Supervisor alive: no
- Heartbeat stale: yes
- Master planner running: no
- Autonomous governor active: no
- Current running task: none
- Last completed task: codex_parallel_review_20260512_021504_06_paper_mode
- Last task status: completed
- True next task: codex_recover_173_phase2r_consolidated_python_source_and_task_json_end_file_leakage_cleanup
- Queue age seconds: 4402
- Planner age seconds: 25118
- Dashboard conflict state: SUPERVISOR_STATUS_STALE_OR_CONFLICTING

Active automation processes:

- `1035556 1011413 250185 python3 ingest/live_binance.py`
- `1035713 1011413 250174 python3 ingest/live_kucoin.py`
- `1035811 1011413 250167 python3 ingest/live_coinank.py`
- `1035965 1011413 250158 python3 ingest/live_coinank_global_aggregator.py`
- `1036143 1011413 250147 python3 ingest/live_binance_liquidations.py`
- `1038292 1011413 250059 python3 feature_pipeline.py`
- `1038859 1011413 250033 python3 ingest/live_technical_analysis.py`
- `1042465 1011413 249940 python3 -m rl.orchestrator_worker`
- `1272209 1272100 205765 tail -f Desktop/AI BOT/logs/orchestrator_worker.log`
- `3324271 1011413 7562 /bin/bash -O extglob -c snap=$(command cat <&3) && builtin shopt -s extglob && builtin eval -- "$snap" && { builtin set +u 2>/dev/null || true; builtin eval "${__CURSOR_SANDBOX_ENV_RESTORE:-}" 2>/dev/null; builtin export...`
- `3324274 3324271 7562 python3 -u trading/trader.py`
- `3446733 1011413 31 python3 -m v2.backend.app.cli.paper_online_runtime --loop --interval 30`

Repair needed:

- Refresh/restart non-live supervisor/governor status generation when safe; dashboard must show stale/conflicting until then.
