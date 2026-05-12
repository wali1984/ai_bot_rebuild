# Supervisor State Truth Report

Generated at: 2026-05-12T20:27:47.226Z

- Supervisor alive: no
- Heartbeat stale: no
- Master planner running: no
- Autonomous governor active: no
- Current running task: none
- Last completed task: codex_parallel_review_20260512_202241_10_no_live_side_effects
- Last task status: completed
- True next task: codex_recover_codex_recover_codex_recover_177_phase2t_decision_explainability_replay_backtest_projection_implementation
- Queue age seconds: 38
- Planner age seconds: 85953
- Dashboard conflict state: CURRENT_SNAPSHOT

Active automation processes:

- `1035556 1011413 311020 python3 ingest/live_binance.py`
- `1035713 1011413 311009 python3 ingest/live_kucoin.py`
- `1035811 1011413 311002 python3 ingest/live_coinank.py`
- `1035965 1011413 310993 python3 ingest/live_coinank_global_aggregator.py`
- `1036143 1011413 310982 python3 ingest/live_binance_liquidations.py`
- `1038292 1011413 310894 python3 feature_pipeline.py`
- `1038859 1011413 310868 python3 ingest/live_technical_analysis.py`
- `1042465 1011413 310775 python3 -m rl.orchestrator_worker`
- `1272209 1272100 266600 tail -f Desktop/AI BOT/logs/orchestrator_worker.log`
- `3324271 1011413 68398 /bin/bash -O extglob -c snap=$(command cat <&3) && builtin shopt -s extglob && builtin eval -- "$snap" && { builtin set +u 2>/dev/null || true; builtin eval "${__CURSOR_SANDBOX_ENV_RESTORE:-}" 2>/dev/null; builtin export...`
- `3324274 3324271 68398 python3 -u trading/trader.py`
- `3446733 1011413 60866 python3 -m v2.backend.app.cli.paper_online_runtime --loop --interval 30`
- `3980694 3980692 16164 python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features`

Repair needed:

- No supervisor truth repair required from this snapshot.
