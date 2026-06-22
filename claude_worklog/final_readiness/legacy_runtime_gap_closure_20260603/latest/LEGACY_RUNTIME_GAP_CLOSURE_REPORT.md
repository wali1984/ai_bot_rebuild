# Legacy Runtime Gap Closure Report - 2026-06-03

Generated UTC: 2026-06-03T23:42:18Z

## Go / No-Go

- Paper/V2 runtime: GO for paper/shadow operation.
- Live/canary: NO-GO. `live_gate=blocked_human_only`, `live_symbols=[]`.
- Legacy shutdown: NO-GO. Full parity is still not claimed.

## What Is Online Now

- KuCoin legacy adapter: active user service, `v2:kc:*=150`, `v2:features:kucoin:*=117`.
- KuCoin public REST: active user service, `v2:market:kucoin:*=109`.
- CoinAPI v1 WSS: active user service, `v2:latest:coinapi:ohlcv:*=6`.
- CoinAPI REST fallback: active user service, `v2:market:coinapi:rest:*=53`, `v2:features:coinapi_rest:*=25`.
- CoinAnk global bridge: active user service, `v2:features:global_coinank:*=11`.
- Liquidation WSS: active user service; event keys are currently `0` because the forceOrder stream is event-dependent.
- Feature/TA pipeline evidence: `v2:features:latest:*=38`, `v2:features:ta:*=24`.
- Trainer/RL core: `V2_NATIVE_RL_CORE_PRODUCTION_INFERENCE_OK`, predictions=27, open_gate=['BTCUSDT', 'ETHUSDT'], mode=`V2_NATIVE_RL_CORE_WITH_LEGACY_CHECKPOINT_EVIDENCE`.
- Trainer checkpoint evidence: `LEGACY_CHECKPOINT_METADATA_PRESENT`, selected=`ppo_checkpoint_1777264095`, candidates=15388, weights_loaded_into_v2=False.
- Native trainer baseline packet: `V2_NATIVE_TRAINER_DATASET_AND_BASELINE_MODEL_READY`; evaluator reported publishable_baseline_available=false and published_count=0.
- Orchestrator: `V2_ORCHESTRATOR_PRODUCTION_OK`, proposals=2, winners=2.
- Paper trade management: `V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK`, signals=2, intents=2, accepted_positions=0.
- Frontend truth: trainer_runtime=`V2_NATIVE_RL_CORE_PRODUCTION_INFERENCE_OK`, checkpoint=`ppo_checkpoint_1777264095`, full_parity=`BLOCKS_LEGACY_SHUTDOWN`.

## Trainer Status Versus Legacy

The V2 trainer path is online for paper predictions and now carries copied legacy checkpoint metadata evidence. It does **not** deserialize legacy PPO/MASA weights in-process and does **not** claim full legacy hybrid trainer parity. The old `v2_trainer_bridge` parity verdict remains `BLOCKS_LEGACY_SHUTDOWN`; this is intentional because it gates legacy shutdown, not paper runtime liveness.

GPU parity probe ran a paper-only CUDA training step successfully during validation: RTX 5080 visible, torch CUDA 12.8, no weight artifact written.

## Fixes Applied

- Added `v2_trainer_checkpoint_evidence_publisher` and `ai-bot-v2-trainer-checkpoint-evidence.service`.
- Parsed real legacy checkpoint names: `ppo_checkpoint_*`, `masa_checkpoint_*`, `enterprise_modules_*`.
- Wired checkpoint evidence into `v2_rl_core_inference_loop` predictions and heartbeat.
- Fixed native trainer dataset artifact writer race with unique temp files.
- Updated frontend truth payload/cards for trainer runtime versus parity.
- Fixed paper execution worker edge/filter ordering so edge, cooldown/churn, and fills classify correctly.
- Accepted `V2_NATIVE_RL_CORE` as a paper trainer source.
- Fixed systemd quoting in `ai-bot-v2-trade-management-paper-loop.service`.

## Validation

- Focused combined regression: `237 passed, 1 warning`.
- Paper execution worker after fix: `36 passed`.
- Orchestrator/trader group after fix: `98 passed`.
- Frontend truth tests: `12 passed`.
- Trainer checkpoint focused tests: `9 passed`.

## Remaining Non-Bypassable Constraints

- Live trading remains blocked and was not enabled.
- No old live trainer/trader was restarted or modified.
- V2 checkpoint evidence is metadata-only; weight promotion/deserialization remains a separate reviewed path.
- Full legacy shutdown parity remains blocked until the parity bridge can prove native equivalence.
