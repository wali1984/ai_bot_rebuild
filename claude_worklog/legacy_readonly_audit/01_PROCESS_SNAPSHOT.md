# Legacy Runtime Process Snapshot

Generated: 2026-05-12T22:35:49.569761+00:00

Read-only process inspection. No services were restarted.

```text
1035556 1011413 python3 ingest/live_binance.py
1035713 1011413 python3 ingest/live_kucoin.py
1035811 1011413 python3 ingest/live_coinank.py
1035965 1011413 python3 ingest/live_coinank_global_aggregator.py
1036143 1011413 python3 ingest/live_binance_liquidations.py
1036304 1011413 python3 ingest/liquidation_bridge.py
1036638 1011413 python3 ingest/liquidation_levels_engine.py
1036817 1011413 python3 ingest/realtime_price_provider.py
1037051 1011413 python3 -m ingest.live_coinapi_wsds
1037308 1011413 python3 -m ingest.live_coinapi_v1
1038032 1011413 python3 ohlcv_resampler_hotfix.py
1038292 1011413 python3 feature_pipeline.py
1038859 1011413 python3 ingest/live_technical_analysis.py
1042465 1011413 python3 -m rl.orchestrator_worker
1272469 1272294 python3 Desktop/AI BOT/monitor_portfolio_primary.py
3324271 1011413 /bin/bash -O extglob -c snap=$(command cat <&3) && builtin shopt -s extglob && builtin eval -- "$snap" && { builtin set +u 2>/dev/null || true; builtin eval "${__CURSOR_SANDBOX_ENV_RESTORE:-}" 2>/dev/null; builtin export PWD="$(builtin pwd)"; builtin shopt -s expand_aliases 2>/dev/null; builtin eval "$1"; }; COMMAND_EXIT_CODE=$?; dump_bash_state >&4; builtin exit $COMMAND_EXIT_CODE -- cd "/home/wali/Desktop/AI BOT" && mkdir -p .logs && nohup python3 -u trading/trader.py >> .logs/trader.log 2>&1 & disown; sleep 1; pgrep -af "python3( -u)? trading/trader\.py" || true
3324274 3324271 python3 -u trading/trader.py
3980694 1011413 python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features
```
