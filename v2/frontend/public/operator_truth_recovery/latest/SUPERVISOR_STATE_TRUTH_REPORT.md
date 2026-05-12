# Supervisor State Truth Report

Generated at: 2026-05-12T04:40:58.582Z

- Supervisor alive: no
- Heartbeat stale: no
- Master planner running: no
- Autonomous governor active: no
- Current running task: none
- Last completed task: codex_parallel_review_20260512_043705_10_no_live_side_effects
- Last task status: completed
- True next task: codex_recover_173_phase2r_consolidated_python_source_and_task_json_end_file_leakage_cleanup
- Queue age seconds: 120
- Planner age seconds: 29144
- Dashboard conflict state: CURRENT_SNAPSHOT

Active automation processes:

- `1035556 1011413 254211 python3 ingest/live_binance.py`
- `1035713 1011413 254200 python3 ingest/live_kucoin.py`
- `1035811 1011413 254194 python3 ingest/live_coinank.py`
- `1035965 1011413 254185 python3 ingest/live_coinank_global_aggregator.py`
- `1036143 1011413 254173 python3 ingest/live_binance_liquidations.py`
- `1038292 1011413 254086 python3 feature_pipeline.py`
- `1038859 1011413 254060 python3 ingest/live_technical_analysis.py`
- `1042465 1011413 253967 python3 -m rl.orchestrator_worker`
- `1272209 1272100 209792 tail -f Desktop/AI BOT/logs/orchestrator_worker.log`
- `3324271 1011413 11589 /bin/bash -O extglob -c snap=$(command cat <&3) && builtin shopt -s extglob && builtin eval -- "$snap" && { builtin set +u 2>/dev/null || true; builtin eval "${__CURSOR_SANDBOX_ENV_RESTORE:-}" 2>/dev/null; builtin export...`
- `3324274 3324271 11589 python3 -u trading/trader.py`
- `3446733 1011413 4058 python3 -m v2.backend.app.cli.paper_online_runtime --loop --interval 30`

Repair needed:

- No supervisor truth repair required from this snapshot.
