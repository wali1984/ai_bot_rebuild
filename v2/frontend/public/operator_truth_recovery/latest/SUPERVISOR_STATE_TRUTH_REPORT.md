# Supervisor State Truth Report

Generated at: 2026-05-12T21:40:18.138Z

- Supervisor alive: yes
- Heartbeat stale: no
- Master planner running: no
- Autonomous governor active: no
- Current running task: none
- Last completed task: none
- Last task status: pending
- True next task: LEGACY_TRAINER_RESTART_RUNTIME_CAPTURE_AND_V2_PARITY_SYNC_UNBLOCK
- Queue age seconds: 0
- Planner age seconds: 90304
- Dashboard conflict state: CURRENT_SNAPSHOT

Active automation processes:

- `68607 1029421 272 bash -c cd '/home/wali/Desktop/AI BOT REBUILD' && while true; do if [ -f '/home/wali/Desktop/AI BOT REBUILD/claude_worklog/agent_supervisor/runtime/control_plane/STOP_REBUILD_CONTROL_PLANE' ]; then echo stop-file-seen; e...`
- `68613 68607 272 python3 claude_worklog/tools/agent_supervisor.py --daemon --poll-seconds 30`
- `73068 1014838 0 /bin/bash -c python3 claude_worklog/tools/build_claude_automation_non_drift_governor_lock.py && python3 -m py_compile claude_worklog/tools/build_claude_automation_non_drift_governor_lock.py claude_worklog/tools/agent_sup...`
- `1035556 1011413 315371 python3 ingest/live_binance.py`
- `1035713 1011413 315360 python3 ingest/live_kucoin.py`
- `1035811 1011413 315353 python3 ingest/live_coinank.py`
- `1035965 1011413 315344 python3 ingest/live_coinank_global_aggregator.py`
- `1036143 1011413 315333 python3 ingest/live_binance_liquidations.py`
- `1038292 1011413 315245 python3 feature_pipeline.py`
- `1038859 1011413 315219 python3 ingest/live_technical_analysis.py`
- `1042465 1011413 315126 python3 -m rl.orchestrator_worker`
- `1272209 1272100 270951 tail -f Desktop/AI BOT/logs/orchestrator_worker.log`
- `3324271 1011413 72749 /bin/bash -O extglob -c snap=$(command cat <&3) && builtin shopt -s extglob && builtin eval -- "$snap" && { builtin set +u 2>/dev/null || true; builtin eval "${__CURSOR_SANDBOX_ENV_RESTORE:-}" 2>/dev/null; builtin export...`
- `3324274 3324271 72749 python3 -u trading/trader.py`
- `3446733 1011413 65217 python3 -m v2.backend.app.cli.paper_online_runtime --loop --interval 30`
- `3980694 3980692 20515 python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features`

Repair needed:

- No supervisor truth repair required from this snapshot.
