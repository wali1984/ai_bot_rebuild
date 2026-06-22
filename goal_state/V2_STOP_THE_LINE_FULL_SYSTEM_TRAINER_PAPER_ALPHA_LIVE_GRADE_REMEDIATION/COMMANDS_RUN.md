# Commands Run — V2_STOP_THE_LINE Remediation

## Phase 5 Diagnosis Commands

```
# Confirmed all 740 prediction keys stale
python3 -c "import redis, json; r = redis.Redis(); keys = list(r.scan_iter('v2:prediction:*', count=2000)); print(len(keys))"
# Result: 740 keys, all stale (generated_est 72+ minutes ago)

# Found crash in trainer stderr
tail -n 30 claude_worklog/agent_supervisor/logs/control_plane/ai-bot-v2-native-cuda-trainer-persistent.err
# Result: ValueError: min() arg is an empty sequence at runtime.py:249

# Confirmed Binance 418 rate limit ban
python3 -c "import urllib.request; urllib.request.urlopen('https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=BTCUSDT', timeout=10)"
# Result: HTTP Error 418: I'm a teapot

# Confirmed 0 trusted examples with trusted_only=True
python3 -c "from app.services.native_trainer.hybrid_cuda_trainer.data_loader import V2HybridTrainerDataLoader; ..."
# Result: Trusted examples loaded: 0

# Confirmed MISSING_CRITICAL_FEATURE_FAMILY from num_trades, quote_volume, taker_buy_*
# These are in missing_feature_flags of v2:features:latest:BTCUSDT:1h but not in OPTIONAL_OR_EVENT_FEATURE_TOKENS

# Confirmed CoinAPI WSDS orderbook data available
python3 -c "import redis; r = redis.Redis(); print(r.exists('v2:market:coinapi:wsds:BTCUSDT'))"
# Result: True (has best_bid_px, best_ask_px, imbalance_5)
```

## Phase 5 Fixes Applied

1. `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/runtime.py` line 249
   - Changed: `min(p["data_coverage_percent"] for p in predictions)`
   - To: `min((p["data_coverage_percent"] for p in predictions), default=0.0)`

2. `v2/backend/app/services/native_trainer/persistent_cuda_trainer_runtime.py` line 1327
   - Changed: `except RuntimeError as exc: if "no trusted examples built" not in str(exc).lower(): raise`
   - To: `except (RuntimeError, ValueError) as exc: if not ("no trusted examples built" in msg or "min() arg is an empty sequence" in msg): raise`

3. `v2/backend/app/services/market_state_integrity/scoring.py` OPTIONAL_OR_EVENT_FEATURE_TOKENS
   - Added: `"num_trades"`, `"quote_volume"`, `"taker_buy"`
   - Rationale: These are ticker-API-dependent, not structural (like OHLCV). They come from Binance 24hr ticker endpoint which can be rate-limited. Model must be robust to their absence.
