# Legacy Runtime Process Snapshot

Generated: 2026-05-06T23:37:44.408228+00:00

Read-only process inspection. No services were restarted.

```text
 147111  146976 python3 Desktop/AI BOT/scripts/monitor_trainer_prices.py
1502637 2253730 python3 Desktop/AI BOT/monitor_portfolio_primary.py
1504039  146781 python3 Desktop/AI BOT/scripts/monitor_trainer_predictions.py
2422445  130149 python3 scripts/monitor_trainer_predictions.py
2432997       1 python3 trading/trader.py
2434190  130149 python3 ingest/live_binance.py
2434257  130149 python3 ingest/live_kucoin.py
2434262  130149 python3 ingest/live_coinank.py
2434267  130149 python3 ingest/live_binance_liquidations.py
2434272  130149 python3 ingest/liquidation_bridge.py
2434277  130149 python3 ingest/liquidation_levels_engine.py
2434282  130149 python3 ingest/realtime_price_provider.py
2434939  130149 python3 ohlcv_resampler_hotfix.py
2435072  130149 python3 feature_pipeline.py
2435672       1 python3 -m rl.orchestrator_worker
2435730  130149 python3 ingest/live_technical_analysis.py
2435742  130149 python3 ingest/live_coinank_global_aggregator.py
2435747  130149 python3 -m ingest.live_coinapi_wsds
3355777  130149 python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features
3451261  130149 /bin/bash -O extglob -c snap=$(command cat <&3) && builtin shopt -s extglob && builtin eval -- "$snap" && { builtin set +u 2>/dev/null || true; builtin eval "${__CURSOR_SANDBOX_ENV_RESTORE:-}" 2>/dev/null; builtin export PWD="$(builtin pwd)"; builtin shopt -s expand_aliases 2>/dev/null; builtin eval "$1"; }; COMMAND_EXIT_CODE=$?; dump_bash_state >&4; builtin exit $COMMAND_EXIT_CODE -- cd "/home/wali/Desktop/AI BOT" && export PYTHONPATH="/home/wali/Desktop/AI BOT:${PYTHONPATH}" && nohup nice -n 10 python3 -m ingest.live_coinapi_v1 >> .logs/live_coinapi_v1.log 2>&1 & echo "PID=$!"; sleep 2; pgrep -af "ingest\.live_coinapi_v1" | grep -v pgrep || true; tail -n 15 .logs/live_coinapi_v1.log
3451263 3451261 python3 -m ingest.live_coinapi_v1
```
