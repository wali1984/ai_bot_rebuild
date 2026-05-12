# Supervisor State Truth Report

Generated at: 2026-05-12T21:28:24.906Z

- Supervisor alive: yes
- Heartbeat stale: no
- Master planner running: yes
- Autonomous governor active: no
- Current running task: none
- Last completed task: none
- Last task status: pending
- True next task: LEGACY_TRAINER_RESTART_RUNTIME_CAPTURE_AND_V2_PARITY_SYNC_UNBLOCK
- Queue age seconds: 7
- Planner age seconds: 89591
- Dashboard conflict state: CURRENT_SNAPSHOT

Active automation processes:

- `56997 1029421 248 bash -c cd '/home/wali/Desktop/AI BOT REBUILD' && while true; do if [ -f '/home/wali/Desktop/AI BOT REBUILD/claude_worklog/agent_supervisor/runtime/control_plane/STOP_REBUILD_CONTROL_PLANE' ]; then echo stop-file-seen; e...`
- `57003 56997 248 python3 claude_worklog/tools/agent_supervisor.py --daemon --poll-seconds 30`
- `60656 1014838 0 /bin/bash -c python3 -m py_compile claude_worklog/tools/build_claude_automation_non_drift_governor_lock.py claude_worklog/tools/agent_supervisor.py claude_worklog/tools/claude_master_rebuild_planner.py claude_worklog/too...`
- `1035556 1011413 314658 python3 ingest/live_binance.py`
- `1035713 1011413 314647 python3 ingest/live_kucoin.py`
- `1035811 1011413 314640 python3 ingest/live_coinank.py`
- `1035965 1011413 314631 python3 ingest/live_coinank_global_aggregator.py`
- `1036143 1011413 314620 python3 ingest/live_binance_liquidations.py`
- `1038292 1011413 314532 python3 feature_pipeline.py`
- `1038859 1011413 314506 python3 ingest/live_technical_analysis.py`
- `1042465 1011413 314413 python3 -m rl.orchestrator_worker`
- `1272209 1272100 270238 tail -f Desktop/AI BOT/logs/orchestrator_worker.log`
- `3324271 1011413 72035 /bin/bash -O extglob -c snap=$(command cat <&3) && builtin shopt -s extglob && builtin eval -- "$snap" && { builtin set +u 2>/dev/null || true; builtin eval "${__CURSOR_SANDBOX_ENV_RESTORE:-}" 2>/dev/null; builtin export...`
- `3324274 3324271 72035 python3 -u trading/trader.py`
- `3446733 1011413 64504 python3 -m v2.backend.app.cli.paper_online_runtime --loop --interval 30`
- `3980694 3980692 19802 python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features`

Repair needed:

- No supervisor truth repair required from this snapshot.
