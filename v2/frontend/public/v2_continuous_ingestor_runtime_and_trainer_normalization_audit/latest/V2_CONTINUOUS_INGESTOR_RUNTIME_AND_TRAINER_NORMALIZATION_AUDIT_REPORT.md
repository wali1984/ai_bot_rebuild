# V2 Continuous Ingestor Runtime And Trainer Normalization Audit Report

Gate: `V2_CONTINUOUS_INGESTOR_RUNTIME_AND_TRAINER_NORMALIZATION_AUDIT_READY`
Generated EST: `2026-06-09T21:01:26-04:00`
Core ingestors: `RUNNING_AND_CURRENT`
Ingestor status: `INGESTORS_OK`
Active ingestors: `19/21`
Bridge/wrapper units: `MASKED`
Trainer status: `V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW`
Training rows: `655`
CoinAnk status: `DIRECT_COINANK_RUNTIME_OK`
CoinAnk recent endpoint calls: `298 success / 0 error / 2 empty`
Trade terminal payload: `CURRENT_RUNTIME_PAYLOAD_BUILT`
Derivatives payload: `CURRENT_OR_RECENT`
Live gate: `enabled_operator_approved`
Trader state: `LIVE_ARMED_BALANCE_HOLD`
Live submit allowed: `False`
Live submit blocker: `INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER`

## Runtime

The continuous core market path is running: Binance kline WSS, CoinAPI WSDS/REST, KuCoin public REST, direct CoinAnk, native ingestors, native feature pipeline, TA, liquidation WSS/levels, status publishers, trainer, risk, orchestrator, and paper loops.

The wrapper/bridge policy is still enforced. CoinAnk bridge, liquidation bridge, and trainer bridge units are masked. Legacy CoinAPI/KuCoin ingestor units are disabled. Direct legacy-owned CoinAnk is running as-is through the direct service path, not through a V2 bridge wrapper.

## Freshness

- `v2:features:latest`: `660/660` fresh
- `v2:market:ohlcv` aggregate: `1222/1222` fresh
- Binance kline WSS source rows: `610/610` fresh
- CoinAPI WSDS: `121/121` fresh
- CoinAPI WSDS microfeatures: `360/360` fresh
- KuCoin market: `582/582` fresh
- KuCoin features: `117/117` fresh
- Liquidation levels: `661/661` fresh
- Prices: `122/122` fresh
- Technical analysis: `610/610` fresh

## Normalization

Provider data is normalized into trainer tensors in this order:

1. Provider ingestors publish current Redis payloads.
2. Native feature and TA loops publish canonical `v2:features:*` payloads.
3. The trainer data loader reads V2 keys and narrow read-only `latest:coinank:*` direct current-source keys.
4. The tensor builder maps provider-specific shapes into a fixed `FEATURE_SPEC`.
5. Missing values are zero-filled only with `missing_mask=1`; stale values are tracked separately in `stale_mask`.
6. `source_availability` and `source_labels` preserve provider lineage for the trainer and website.
7. Market-state integrity decides which rows can train, predict, pass risk, pass orchestrator, and enter paper/live candidates.

Code references:

- Data loader direct CoinAnk guard: `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py:49`
- Data loader V2 payload contract: `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py:100`
- Data loader direct CoinAnk keys: `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py:143`
- Tensor builder missing/stale mask contract: `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/tensor_builder.py:410`
- Tensor builder CoinAnk fallbacks: `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/tensor_builder.py:484`
- Tensor builder source lineage output: `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/tensor_builder.py:731`
- Website trade/derivatives source merger: `v2/backend/app/services/operator_truth/trade_derivatives_runtime.py:300`

## Caveats

Nansen and LunarCrush services are alive, but their latest provider responses are not clean:

- Nansen: intermittent `API_FORBIDDEN_403`
- LunarCrush: `API_PAYMENT_REQUIRED_402`

Those fields are optional and masked for trainer normalization. They are not fabricated, and they are not core market/trainer blockers.

The only failed unit observed is `ai-bot-v2-no-status-change-sla-watchdog.service`, which is not an ingestor and is not part of the trainer normalization path.

## Validation

- CoinAnk direct status refresh: `PASS`
- Ingestor status refresh: `PASS`
- Native CUDA trainer one-shot: `PASS`
- Runtime truth refresh: `PASS`
- Trade terminal payload refresh: `PASS`
- Derivatives payload refresh: `PASS`
- py_compile: `PASS`
- focused backend tests: `PASS: 4 passed`

Safety: no real order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, no Redis trim, and no raw credential output.
