# Commands Run

Generated: 2026-06-15

## Build, Replay, And Runtime Commands

```bash
PYTHONPATH='/home/wali/Desktop/AI BOT REBUILD:/home/wali/Desktop/AI BOT REBUILD/v2/backend' ./.venv/bin/python -m v2.backend.app.cli.v2_major_move_replay_future_window_completion --repo-root '/home/wali/Desktop/AI BOT REBUILD'
```

```bash
PYTHONPATH=/home/wali/Desktop/AI\ BOT\ REBUILD:/home/wali/Desktop/AI\ BOT\ REBUILD/v2/backend ./.venv/bin/python -m v2.backend.app.cli.v2_native_rl_masa_ppo_cuda_trainer_loop --symbols BTCUSDT,ETHUSDT,SOLUSDT --timeframes 1m,5m,15m,1h,4h --cycles 1 --max-rows 128 --write-artifacts --risk-caps-configured
```

```bash
PYTHONPATH=/home/wali/Desktop/AI\ BOT\ REBUILD:/home/wali/Desktop/AI\ BOT\ REBUILD/v2/backend ./.venv/bin/python -m v2.backend.app.cli.v2_all_timeframe_prediction_signal_price_target_publisher --repo-root /home/wali/Desktop/AI\ BOT\ REBUILD --prediction-stale-seconds 3600
```

```bash
setsid -f bash -lc "cd '/home/wali/Desktop/AI BOT REBUILD' && PYTHONPATH='/home/wali/Desktop/AI BOT REBUILD:/home/wali/Desktop/AI BOT REBUILD/v2/backend' ./.venv/bin/python -u -m v2.backend.app.cli.v2_adaptive_allocation_trade_lifecycle_24h_paper_soak --loop --interval-seconds 300 --duration-hours 12 --required-hours 12 >> '/home/wali/Desktop/AI BOT REBUILD/v2/runtime/major_move_postfix_12h_soak.log' 2>&1"
```

## Validation Commands

```bash
PYTHONPATH='/home/wali/Desktop/AI BOT REBUILD:/home/wali/Desktop/AI BOT REBUILD/v2/backend' ./.venv/bin/python -m py_compile v2/backend/app/cli/v2_major_move_replay_future_window_completion.py v2/backend/app/services/native_trainer/feedback_enrichment.py v2/backend/app/services/paper_trade_management/outcomes.py v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/app/services/risk_gateway/service.py
```

```bash
PYTHONPATH='/home/wali/Desktop/AI BOT REBUILD:/home/wali/Desktop/AI BOT REBUILD/v2/backend' ../.venv/bin/python -m pytest backend/tests/unit/cli/test_v2_major_move_replay_future_window_completion.py backend/tests/unit/services/market_move_detection/test_breakout_squeeze.py backend/tests/integration/cli/test_v2_native_rl_masa_ppo_cuda_trainer.py backend/tests/integration/cli/test_v2_all_timeframe_prediction_signal_price_target_publisher.py backend/tests/unit/services/risk_gateway/test_envelope_aware_boundary.py
```

```bash
npm run typecheck
```

```bash
npm run build
```

```bash
npm run preview -- --host 127.0.0.1 --port 4173
```

```bash
DASHBOARD_BASE_URL='http://127.0.0.1:4173' DASHBOARD_CRAWL_PHASE='major_move_local_after' npm run crawl:dashboard
```

```bash
PRODUCTION_CRAWL_BASE_URL='http://127.0.0.1:4173' PRODUCTION_CRAWL_PHASE='major_move_local_after' PRODUCTION_CRAWL_ARTIFACT_SLUG='v2_major_move_replay_future_window_completion_trainer_docs_and_website_wiring' npm run crawl:production-website
```

## Safety And Evidence Inspection Commands

```bash
rg -n "(create_order|test_order|testOrder|cancel_order|modify_order|futures_create_order|futures_change_leverage|futures_change_margin|change_margin_type|change_initial_leverage|marginType|submit_market_order)" v2/backend/app/cli/v2_major_move_replay_future_window_completion.py v2/backend/app/services/native_trainer/feedback_enrichment.py v2/backend/app/services/paper_trade_management/outcomes.py v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/app/services/risk_gateway/service.py v2/frontend/src/components/trading/MajorMoveReplayStatusPanel.tsx v2/docs/trainer-instructions.md
```

```bash
rg -n "(guaranteed profit|guaranteed 10k|guarantee 10k|guaranteed return|api[_-]?key|secret|password|PRIVATE|BEGIN RSA|BINANCE_|OPENAI_API|200 USDT|200\\.0|fixed runtime sizing|latest:)" v2/backend/app/cli/v2_major_move_replay_future_window_completion.py v2/backend/app/services/native_trainer/feedback_enrichment.py v2/backend/app/services/paper_trade_management/outcomes.py v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/app/services/risk_gateway/service.py v2/frontend/src/components/trading/MajorMoveReplayStatusPanel.tsx v2/docs/trainer-instructions.md
```

```bash
rg -n "(redis\\.(set|rpush|lpush|xadd)|set_json|\\.set\\()" v2/backend/app/cli/v2_major_move_replay_future_window_completion.py v2/backend/app/services/native_trainer/feedback_enrichment.py v2/backend/app/services/paper_trade_management/outcomes.py v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/app/services/risk_gateway/service.py
```

```bash
jq '{gate,status,blockers,future_window_evidence_complete,trainer_docs_status,feedback_status,website_status,durable_checkpoint_loadable,paper_runtime_grid_aligned,live_order_submitted,test_order_called,exchange_leverage_mutation,exchange_margin_mode_mutation,old_redis_write,fixed_runtime_sizing,guaranteed_profit_claimed,guaranteed_10k_claimed}' v2/frontend/public/v2_major_move_replay_future_window_completion_trainer_docs_and_website_wiring/latest/operator_dashboard_payload.json
```

```bash
ps -p 4092980 -o pid,etime,cmd
```

```bash
tail -n 20 v2/runtime/major_move_postfix_12h_soak.log
```

Additional read-only inspection commands used during debugging: `rg --files`, `rg`, `nl -ba`, `sed`, `jq`, `find`, `ls`, `cat`, `wc -l`, `git status --short`, and `git diff --stat` against the touched files and generated artifacts.
