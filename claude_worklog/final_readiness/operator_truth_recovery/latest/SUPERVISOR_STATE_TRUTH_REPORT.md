# Supervisor State Truth Report

Generated at: 2026-05-12T04:38:38.794Z

- Supervisor alive: yes
- Heartbeat stale: no
- Master planner running: no
- Autonomous governor active: no
- Current running task: codex_parallel_review_20260512_043705_10_no_live_side_effects
- Last completed task: none
- Last task status: running
- True next task: codex_recover_173_phase2r_consolidated_python_source_and_task_json_end_file_leakage_cleanup
- Queue age seconds: 91
- Planner age seconds: 29005
- Dashboard conflict state: CURRENT_SNAPSHOT

Active automation processes:

- `1035556 1011413 254072 python3 ingest/live_binance.py`
- `1035713 1011413 254061 python3 ingest/live_kucoin.py`
- `1035811 1011413 254054 python3 ingest/live_coinank.py`
- `1035965 1011413 254045 python3 ingest/live_coinank_global_aggregator.py`
- `1036143 1011413 254034 python3 ingest/live_binance_liquidations.py`
- `1038292 1011413 253946 python3 feature_pipeline.py`
- `1038859 1011413 253920 python3 ingest/live_technical_analysis.py`
- `1042465 1011413 253827 python3 -m rl.orchestrator_worker`
- `1272209 1272100 209652 tail -f Desktop/AI BOT/logs/orchestrator_worker.log`
- `3324271 1011413 11449 /bin/bash -O extglob -c snap=$(command cat <&3) && builtin shopt -s extglob && builtin eval -- "$snap" && { builtin set +u 2>/dev/null || true; builtin eval "${__CURSOR_SANDBOX_ENV_RESTORE:-}" 2>/dev/null; builtin export...`
- `3324274 3324271 11449 python3 -u trading/trader.py`
- `3446733 1011413 3918 python3 -m v2.backend.app.cli.paper_online_runtime --loop --interval 30`
- `3500059 2399536 91 python3 claude_worklog/tools/agent_supervisor.py --task-id codex_parallel_review_20260512_043705_10_no_live_side_effects`
- `3500061 3500059 91 node /home/wali/.local/bin/codex exec [prompt redacted]`
- `3500072 3500061 90 /home/wali/.local/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/codex/codex exec [prompt redacted]`

Repair needed:

- No supervisor truth repair required from this snapshot.
