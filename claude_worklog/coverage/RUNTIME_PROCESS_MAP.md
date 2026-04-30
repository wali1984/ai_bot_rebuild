# Runtime Process Map

Processes tracked: 48
Unmapped bot-looking: 0

| pid | status | cwd | command |
|---:|---|---|---|
| 1910 | not_bot_related |  | /usr/bin/python3 -m proton.vpn.daemon |
| 1925 | not_bot_related |  | /usr/bin/redis-server 127.0.0.1:6379 |
| 1931 | not_bot_related |  | /usr/bin/python3 /usr/share/unattended-upgrades/unattended-upgrade-shutdown --wait-for-signal |
| 130251 | not_bot_related |  | fusermount3 -o rw,nosuid,nodev,fsname=portal,auto_unmount,subtype=portal -- /run/user/1000/doc |
| 133521 | not_bot_related | /home/wali | /proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --crash |
| 133522 | not_bot_related | /home/wali | /proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --crash |
| 133523 | not_bot_related | /home/wali | /proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --dns-r |
| 133619 | not_bot_related | /home/wali | /proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --crash |
| 133660 | not_bot_related | /home/wali | /proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --dns-r |
| 133661 | not_bot_related | /home/wali | /proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --dns-r |
| 133743 | not_bot_related | /home/wali/.cursor/extensions/anysphere.cursorpyright-1.0.10/dist | /usr/share/cursor/resources/app/resources/helpers/node --max-old-space-size=32768 /home/wali/.cursor/extensions/anyspher |
| 133898 | mapped | /home/wali/Desktop/AI BOT | /usr/share/cursor/cursor /usr/share/cursor/resources/app/extensions/markdown-language-features/dist/serverWorkerMain --n |
| 137941 | not_bot_related | /home/wali | /proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --crash |
| 137942 | not_bot_related | /home/wali | /proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --crash |
| 138052 | not_bot_related | /home/wali | /proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --crash |
| 147111 | mapped | /home/wali | python3 Desktop/AI BOT/scripts/monitor_trainer_prices.py |
| 188345 | mapped | /home/wali/Desktop/AI BOT | /usr/share/cursor/cursor /usr/share/cursor/resources/app/extensions/json-language-features/server/dist/node/jsonServerMa |
| 2249013 | mapped | /home/wali/Desktop/AI BOT | /usr/share/code/code /usr/share/code/resources/app/extensions/markdown-language-features/dist/serverWorkerMain --node-ip |
| 2249016 | mapped | /home/wali/Desktop/AI BOT | /usr/share/code/code /home/wali/.vscode/extensions/ms-azuretools.vscode-containers-2.4.1/dist/dockerfile-language-server |
| 2249025 | mapped | /home/wali/Desktop/AI BOT | /usr/share/code/code /home/wali/.vscode/extensions/ms-azuretools.vscode-containers-2.4.1/dist/compose-language-service/l |
| 2249034 | not_bot_related | /home/wali | /home/wali/.vscode/extensions/ms-python.vscode-python-envs-1.20.1-linux-x64/python-env-tools/bin/pet server |
| 2249078 | mapped | /home/wali/Desktop/AI BOT | /usr/share/code/code /usr/share/code/resources/app/extensions/json-language-features/server/dist/node/jsonServerMain --n |
| 2250346 | not_bot_related | /home/wali | /usr/share/code/code /home/wali/.vscode/extensions/dbaeumer.vscode-eslint-3.0.24/server/out/eslintServer.js --node-ipc - |
| 2250660 | not_bot_related | /home/wali/.vscode/extensions/ms-python.vscode-pylance-2026.2.1/dist | /usr/share/code/code /home/wali/.vscode/extensions/ms-python.vscode-pylance-2026.2.1/dist/server.bundle.js --cancellatio |
| 2379258 | mapped | /home/wali | tail -f Desktop/AI BOT/logs/trader.log |
| 2421895 | mapped | /home/wali/Desktop/AI BOT | bash -c          cd '/home/wali/Desktop/AI BOT'         echo '💾 Memory Monitor - Press Ctrl+C to exit'         echo '═══ |
| 2422220 | mapped | /home/wali/Desktop/AI BOT | python3 scripts/memory_monitor.py |
| 2422250 | mapped | /home/wali/Desktop/AI BOT | python3 scripts/ingestors_watchdog.py |
| 2422445 | mapped | /home/wali/Desktop/AI BOT | python3 scripts/monitor_trainer_predictions.py |
| 2422607 | mapped | /home/wali/Desktop/AI BOT | python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features |
| 2423543 | mapped | /home/wali/Desktop/AI BOT | /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.resource_tracker import main;main(68) |
| 2430102 | mapped | /home/wali | tail -f Desktop/AI BOT/logs/hybrid_trainer.log |
| 2432997 | mapped | /home/wali/Desktop/AI BOT | python3 trading/trader.py |
| 2434190 | mapped | /home/wali/Desktop/AI BOT | python3 ingest/live_binance.py |
| 2434257 | mapped | /home/wali/Desktop/AI BOT | python3 ingest/live_kucoin.py |
| 2434262 | mapped | /home/wali/Desktop/AI BOT | python3 ingest/live_coinank.py |
| 2434267 | mapped | /home/wali/Desktop/AI BOT | python3 ingest/live_binance_liquidations.py |
| 2434272 | mapped | /home/wali/Desktop/AI BOT | python3 ingest/liquidation_bridge.py |
| 2434277 | mapped | /home/wali/Desktop/AI BOT | python3 ingest/liquidation_levels_engine.py |
| 2434282 | mapped | /home/wali/Desktop/AI BOT | python3 ingest/realtime_price_provider.py |
| 2434939 | mapped | /home/wali/Desktop/AI BOT | python3 ohlcv_resampler_hotfix.py |
| 2435072 | mapped | /home/wali/Desktop/AI BOT | python3 feature_pipeline.py |
| 2435672 | mapped | /home/wali/Desktop/AI BOT | python3 -m rl.orchestrator_worker |
| 2435730 | mapped | /home/wali/Desktop/AI BOT | python3 ingest/live_technical_analysis.py |
| 2435742 | mapped | /home/wali/Desktop/AI BOT | python3 ingest/live_coinank_global_aggregator.py |
| 2435747 | mapped | /home/wali/Desktop/AI BOT | python3 -m ingest.live_coinapi_wsds |
| 2485660 | not_bot_related |  | redis-rdb-bgsave 127.0.0.1:6379 |
| 2486423 | mapped | /home/wali/Desktop/AI BOT REBUILD | python3 tools/collect_runtime_processes.py --legacy-root ./legacy_reference --out-dir ./claude_worklog/coverage |
