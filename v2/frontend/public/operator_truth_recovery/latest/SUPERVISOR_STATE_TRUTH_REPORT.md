# Supervisor State Truth Report

Generated at: 2026-05-12T02:54:53.029Z

- Supervisor alive: no
- Heartbeat stale: yes
- Master planner running: no
- Autonomous governor active: no
- Current running task: none
- Last completed task: codex_parallel_review_20260512_021504_06_paper_mode
- Last task status: completed
- True next task: codex_recover_173_phase2r_consolidated_python_source_and_task_json_end_file_leakage_cleanup
- Queue age seconds: 2063
- Planner age seconds: 22779
- Dashboard conflict state: SUPERVISOR_STATUS_STALE_OR_CONFLICTING

Active automation processes:

- `1035556 1011413 247846 python3 ingest/live_binance.py`
- `1035713 1011413 247835 python3 ingest/live_kucoin.py`
- `1035811 1011413 247828 python3 ingest/live_coinank.py`
- `1035965 1011413 247819 python3 ingest/live_coinank_global_aggregator.py`
- `1036143 1011413 247808 python3 ingest/live_binance_liquidations.py`
- `1038292 1011413 247720 python3 feature_pipeline.py`
- `1038859 1011413 247694 python3 ingest/live_technical_analysis.py`
- `1042465 1011413 247601 python3 -m rl.orchestrator_worker`
- `1272209 1272100 203426 tail -f Desktop/AI BOT/logs/orchestrator_worker.log`
- `3324271 1011413 5223 /bin/bash -O extglob -c snap=$(command cat <&3) && builtin shopt -s extglob && builtin eval -- "$snap" && { builtin set +u 2>/dev/null || true; builtin eval "${__CURSOR_SANDBOX_ENV_RESTORE:-}" 2>/dev/null; builtin export...`
- `3324274 3324271 5223 python3 -u trading/trader.py`

Repair needed:

- Refresh/restart non-live supervisor/governor status generation when safe; dashboard must show stale/conflicting until then.
