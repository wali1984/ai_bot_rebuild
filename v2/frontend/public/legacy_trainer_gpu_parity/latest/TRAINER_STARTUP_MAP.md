# Trainer Startup Map

Generated: 2026-05-12T06:11:36Z

## Legacy Startup Candidates

| Path | Command/behavior | Risk |
|---|---|---|
| `legacy_reference/start_hybrid_trainer_live.sh` | `python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features` | Live-mode trainer can publish Redis signals/proposals; not run in this task. |
| `legacy_reference/launch_hybrid_trainer.sh` | `nohup python -u rl/hybrid_trainer.py --mode hybrid` from `/home/wali/Desktop/AI BOT` | Points outside AI BOT REBUILD and can write legacy Redis; not run. |
| `legacy_reference/restart_trainer_gpu.sh` | restart helper for GPU trainer | Can affect legacy trainer; not run. |
| `legacy_reference/run_hybrid_trainer_with_signals.py` | starts hybrid training with concurrent signal generation | Can publish signals; not run. |
| `legacy_reference/scripts/monitor_trainer_predictions.py` | read Redis prediction/proposal streams and display monitor | Read-only-ish monitor, but not running currently. |

## Observed Processes

```text
1910       1 1404551 /usr/bin/python3 -m proton.vpn.daemon
   1931       1 1404551 /usr/bin/python3 /usr/share/unattended-upgrades/unattended-upgrade-shutdown --wait-for-signal
1015133 1014681  260400 /home/wali/.vscode/extensions/ms-python.vscode-python-envs-1.20.1-linux-x64/python-env-tools/bin/pet server
1015500 1014681  260399 /usr/share/code/code /home/wali/.vscode/extensions/ms-python.vscode-pylance-2026.2.1/dist/server.bundle.js --cancellationReceive=file:23e69c9a063d670c9d0c55abb906ca7159b815af70 --node-ipc --clientProcessId=1014681
1029421 1011413  260141 tmux new-session -d -s ai_bot_legacy_readonly_audit_sentinel cd '/home/wali/Desktop/AI BOT REBUILD' && while true; do python3 claude_worklog/tools/legacy_readonly_audit_sentinel.py; sleep 1800; done
1029422 1029421  260141 bash -c cd '/home/wali/Desktop/AI BOT REBUILD' && while true; do python3 claude_worklog/tools/legacy_readonly_audit_sentinel.py; sleep 1800; done
1034494 1011413  259764 python3 vpn_monitor.py
1034613 1011413  259744 python3 system_telegram_monitor.py
1034673 1011413  259735 python3 monitor_system_memory.py
1035327 1011413  259669 python3 scripts/memory_monitor.py
1035410 1011413  259662 python3 scripts/ingestors_watchdog.py
1035556 1011413  259649 python3 ingest/live_binance.py
1035713 1011413  259638 python3 ingest/live_kucoin.py
1035811 1011413  259631 python3 ingest/live_coinank.py
1035965 1011413  259623 python3 ingest/live_coinank_global_aggregator.py
1036143 1011413  259611 python3 ingest/live_binance_liquidations.py
1036304 1011413  259604 python3 ingest/liquidation_bridge.py
1036638 1011413  259590 python3 ingest/liquidation_levels_engine.py
1036817 1011413  259582 python3 ingest/realtime_price_provider.py
1037051 1011413  259574 python3 -m ingest.live_coinapi_wsds
1037308 1011413  259565 python3 -m ingest.live_coinapi_v1
1038032 1011413  259532 python3 ohlcv_resampler_hotfix.py
1038292 1011413  259524 python3 feature_pipeline.py
1038859 1011413  259497 python3 ingest/live_technical_analysis.py
1042465 1011413  259405 python3 -m rl.orchestrator_worker
1272469 1272294  215205 python3 Desktop/AI BOT/monitor_portfolio_primary.py
2142277 1029421  129360 python3 claude_worklog/tools/codex_non_live_watchdog.py --daemon --poll-seconds 300
2399536 1029421   92324 python3 claude_worklog/tools/parallel_capacity_scheduler.py --daemon --poll-seconds 600
2458000 1271878   85555 bash -lc cd "$HOME/Desktop/AI BOT REBUILD"; python3 claude_worklog/tools/agent_supervisor_dashboard.py --refresh-seconds 10; echo; echo "dashboard exited with status $?"; exec bash
2458008 2458000   85555 python3 claude_worklog/tools/agent_supervisor_dashboard.py --refresh-seconds 10
3324274 3324271   17027 python3 -u trading/trader.py
3446733 1011413    9495 python3 -m v2.backend.app.cli.paper_online_runtime --loop --interval 30
3587215 3587214       0 python3 -
```

## Decision

Legacy trainer startup is not approved in this task. A separate containment decision is required before any legacy trainer start because the known startup path is live-mode and Redis-publishing capable.
