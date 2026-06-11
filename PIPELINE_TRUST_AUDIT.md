# Pipeline Trust Audit

Generated: `2026-06-11`

Scope: static repository audit of the current V2 crypto futures bot pipeline. No production trading logic was changed. No refactor, strategy, PPO, MASA, live execution, Redis trim, restart, or validation run was performed.

Audit stance: do not assume the pipeline is correct. A stage is considered trusted only when the code carries explicit point-in-time metadata, validates it, and enforces rejection before training or execution.

## Executive verdict

The current pipeline is not yet point-in-time trusted end to end.

Primary reasons:

- Unfinished Binance candles can be written into the same OHLCV arrays consumed by features, training tensors, and predictions.
- Candle finality metadata is either absent or stored separately from the OHLCV record, and downstream consumers generally ignore it.
- Market-state integrity scoring can infer `candle_closed_confirmed=True` from generated snapshot time when source candle finality is missing.
- Multi-timeframe alignment is not enforced by a shared decision cutoff across all source timeframes.
- MASA and PPO do not have a strict independent contract with shared feature cutoff, input hash, forecast horizon, model version, and prediction id linkage.
- Training examples are assembled from latest mutable Redis state, not immutable point-in-time snapshots, and dirty classifications are not rejected before PPO training.
- Live execution has strong operator and lineage gates, but it does not revalidate candle finality, multi-timeframe cutoff consistency, or an execution state-machine transition before submit.

## A. Architecture map

| Stage | Mode | Source path and function/class | Evidence and trust assessment |
|---|---:|---|---|
| Binance REST candles | Batch/polling | `v2/backend/app/services/market_ingest/service.py`, `MarketIngestService.ingest_klines`, `_binance_rest_klines`, `_binance_kline_to_bar` | REST klines are converted into bars with `ts`, OHLCV, and source only. The current open candle is not filtered and close/finality metadata is not stored in the bar. Unsafe until normalized. |
| Binance WSS candles | Streaming | `v2/backend/app/cli/v2_binance_kline_wss_loop.py`, `_to_kline_row`, `run` | The WSS loop records `closed_candle` in a sidecar source object, but writes every row into `v2:market:ohlcv:binance:{symbol}:{timeframe}`. Consumers read the OHLCV list and ignore the sidecar. Unsafe for closed-candle features. |
| CoinAPI REST candles | Batch/polling | `v2/backend/app/services/market_ingest/service.py`, `_coinapi_v1_klines`, `_coinapi_to_bar` | Uses `time_period_start` as `ts`. `time_period_end`, `available_at`, finality, and ingestion time are not carried into the normalized bar. Timestamp meaning is incomplete. |
| KuCoin native ingestor | Streaming/polling mixed | `v2/backend/app/services/native_ingestors/kucoin.py` | Native source exists and is read by trainer loader from `v2:market:kucoin:{symbol}`. No evidence found in downstream tensor builder that KuCoin timestamps are aligned with the decision cutoff. |
| CoinAPI WSDS/native ingestor | Streaming | `v2/backend/app/services/native_ingestors/coinapi_wsds.py` | Native source exists and is read by trainer loader from `v2:market:coinapi:{symbol}`. Downstream code treats it as latest payload without enforcing a source availability cutoff. |
| CoinAnk bridge | Streaming/polling mixed | `v2/backend/app/services/coinank_bridge/service.py`, plus trainer loader `_get_current_coinank` | Trainer loader explicitly reads `latest:coinank:*` current keys, not only `v2:*` namespaced keys. This is read-only but weakens V2 lineage and backfill/live separation. |
| Liquidations | Streaming | `v2/backend/app/services/native_ingestors/liquidations.py`, `v2/backend/app/services/native_ingestors/liquidations_wss.py` | Liquidation events are available as `v2:market:liquidations:*` and `v2:liquidations:events`. Tensor builder consumes latest liquidation data but does not enforce cutoff alignment with candles. |
| In-memory market storage | Mixed | `v2/backend/app/services/market_ingest/service.py`, `self.data_plane[...]` | Market service writes bars/prices to an in-process `data_plane`. This is not an immutable point-in-time store and does not preserve source close/finality metadata. |
| Redis storage | Mixed | `v2/backend/app/services/v2_owned_runtime/redis_namespace_adapter.py`, `RedisNamespaceAdapter` | V2 write adapter rejects non-`v2:` writes for wrapped calls. It does not protect readers from stale/current non-V2 reads and not every direct Redis call is necessarily wrapped. |
| DB storage scaffold | Batch | `v2/backend/app/adapters/db/base.py`, `v2/backend/app/adapters/db/repositories/*` | DB base/repository files are placeholders. No enforced candle uniqueness, source timestamp, or immutable snapshot constraints were found in the runtime path. |
| Candle normalization | Mixed | `market_ingest/service.py`, `_binance_kline_to_bar`, `_coinapi_to_bar`; `v2_binance_kline_wss_loop.py`, `_to_kline_row` | There is no single canonical candle schema carrying `event_time`, `open_time`, `close_time`, `ingested_at`, `available_at`, `is_closed`, `source`, and `source_sequence`. Normalization is fragmented. |
| Multi-timeframe aggregation | Mixed | `v2/backend/app/services/feature_pipeline_native/service.py`, `compute_feature_snapshot`; `v2/backend/app/services/native_dynamic_runtime/execution.py`, `TIMEFRAMES`; `v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py`, `REQUIRED_TIMEFRAMES` | Higher timeframe values may be exchange-native or latest Redis payloads. No shared cutoff enforcement was found across 1m/5m/15m/1h/4h before feature or prediction publication. |
| Feature builder | Mixed | `v2/backend/app/services/feature_pipeline_native/service.py`, `compute_feature_snapshot`, `emit_feature_snapshot`; `v2/backend/app/cli/v2_feature_pipeline_native_loop.py`, `_features_from_market`, `run_once` | Features use latest candle arrays and latest side inputs. The loop marks feature freshness `CURRENT` with empty stale flags in the visible path. No closed-candle filter is enforced. |
| Feature tensor builder | Mixed | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/tensor_builder.py`, `V2UnifiedFeatureTensorBuilder.build`, `_latest_kline` | Uses `ohlcv[-1]` and latest side payloads. NaN/inf are masked, but timestamp cutoff and candle finality are not enforced. |
| MASA | Online inference/training-adjacent | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/masa.py`, `MASAOutput`, `V2MASAAdapter.evaluate`; `model.py`, `_forward_torch` | MASA receives expected move, PPO action probabilities, and coverage. It is not an independent time-aligned model input contract. Output lacks model version, generated_at, feature_cutoff, forecast_horizon, confidence, and input hash. |
| PPO observation/model | Online inference/training | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/model.py`, `forward`; `ppo_trainer.py`, `train`; `rl_core/observation_schema.py` | PPO receives `FeatureTensorRecord` values and masks. Observation schema is descriptive, not enforced. Missing fields include observation_time, feature_cutoff, action mask, position state, and MASA prediction id. |
| Training sample creation | Batch/latest-state mixed | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py`, `load_payloads`, `build_example`; `ppo_trainer.py`, `train` | Samples are built from latest Redis payloads and labels are derived from prediction/features/TA. Rows classified missing/stale are still returned and can enter training. |
| Prediction publication | Mixed | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/publisher.py`, `build_prediction_payload`, `publish_lineage` | Publication includes many lineage and market-integrity fields, but relies on upstream feature tensor and market-state scoring. Missing hard input cutoff and candle finality proof. |
| Orchestrator/risk | Streaming/latest-state | `v2/backend/app/services/orchestrator_decision/service.py`, `decide`; `v2/backend/app/services/risk_gateway/service.py`, `evaluate` | Blocks missing/stale freshness and low confidence. It trusts prediction payload integrity fields rather than rebuilding source cutoff/finality itself. |
| Paper execution | Streaming/latest-state | `v2/backend/app/cli/v2_paper_execution_worker.py`, `_build_simulated_fill`, `run`; `paper_execution_ledger/service.py`, `mirror_risk_decision` | Paper uses deterministic fills, fees, and slippage. It is safer than live but not market-parity complete. It can consume upstream signals built from dirty candles if those were marked valid. |
| Paper position tracking | Streaming/latest-state | `v2/backend/app/services/rl_core/position_price_tracking_recorder.py`, `build_position_track`; `position_history_persistent_tracker.py` | Paper position tracking is V2-only and avoids fake price fabrication, but it is separate from exchange position state and cannot prove live state-machine parity. |
| Live execution | Streaming/operator-gated | `v2/backend/app/services/live_gate/binance_live_order_transport.py`, `evaluate_live_order_transport`, `submit_market_order`; `runtime_execution_state.py` | Live submit is heavily gated and uses signed reads. It submits market orders but does not implement a complete open/close/flip/reduce-only state transition validator or fill lifecycle reconciliation. |
| Replay/backtest | Batch/post-hoc | `v2/backend/app/services/replay_backtest_runner/service.py`, `assemble_replay_backtest_step`; `edge_proof/replay_miner.py` | Replay/backtest mirrors paper ledger and mines post-hoc windows. It is not live-parity simulation and should not be treated as proof of live point-in-time behavior. |
| Training feedback | Mixed | `publisher.py`, `publish_lineage`; `paper_execution_worker.py`; `edge_proof/replay_miner.py`; `runtime.py` | Feedback is spread across paper ledger, intents, replay miner, and trainer runtime. No single immutable decision-outcome sample contract was found. |

## B. Timestamp lineage

| Stage | Timestamp fields observed | Meaning status | Trust assessment |
|---|---|---|---|
| Binance REST normalization | `ts=row[0]` | Candle open time | `close_time`, `available_at`, `ingested_at`, and finality are missing from normalized bars. |
| Binance WSS normalization | `open_time`, `close_time`, sidecar `closed_candle`, sidecar `event_time` | Mostly clear in WSS source object | Unsafe because OHLCV consumers read only the list row and not the sidecar finality object. |
| CoinAPI normalization | `time_period_start` mapped to `ts` | Candle open time | `time_period_end` and availability are dropped. Unsafe for finality proof. |
| Market price snapshots | `ts_ms`, `timestamp`, `fetched_utc`, `generated_utc` depending path | Mixed | Timestamp meaning varies by payload. Some price paths use latest bar open time as price timestamp. |
| Feature snapshots | `generated_at`, `generated_utc`, source freshness seconds | Generated time | No explicit `feature_cutoff` or source candle close time in core loop output. |
| Native feature service | `generated_utc`, `ohlcv_window_age_seconds` | Generated time and age | The age is useful but does not prove closed candle availability. |
| Market-state integrity | `decision_cutoff`, `decision_time`, `generated_at`, `source_event_time`, `source_available_time`, `candle_close_time`, `trained_until` | Intended PIT schema | Some fields are inferred if missing, which can convert unknown state into apparently safe state. |
| Tensor builder | `feature_snapshot_id`, source labels, masks | Content hash and source labels | No `observation_time`, `feature_cutoff`, `available_at`, or `trained_until`. |
| MASA | None in `MASAOutput` | Missing | MASA output has no generated time, model version, horizon, cutoff, confidence, or input hash. |
| PPO output | `model_id`, `feature_snapshot_id` | Model and tensor id | No policy version, observation time, decision cutoff, action mask, or position-state timestamp. |
| Prediction publisher | `generated_est`, `source_generated_est`, `decision_cutoff` from integrity score | Generated and scoring cutoff | Payload improves lineage, but cutoff can be derived from inferred values rather than source proof. |
| Orchestrator/risk | Prediction freshness fields | Trusts prediction | Does not independently validate source event/candle/finality timestamps. |
| Paper execution | `generated_utc`, `fill_generated_utc`, `source_generated_est` | Simulated execution generated time | Useful for audit, but not exchange execution time. |
| Live execution | `generated_est`, `source_generated_est`, `order_submitted` result time, signed read times | Mixed decision and execution time | Live gate has age checks but no full source cutoff/finality revalidation. |
| Replay/backtest | Paper ledger generated time, post-hoc price sample times | Post-hoc | Must not be mixed with live-style training unless explicitly marked. |

Timestamp fields specifically requested:

| Field | Current status |
|---|---|
| `event_time` | Present in some WSS/source payloads but not consistently propagated into features/tensors/predictions. |
| `candle_open_time` | Present as Binance REST/WSS open time or normalized `ts`; not consistently named. |
| `candle_close_time` | Present in WSS rows and Binance raw row, but dropped or ignored by key consumers; may be inferred later. |
| `ingested_at` | Present in some source/loop payloads, not canonical. |
| `available_at` | Not consistently present. Critical missing field for PIT safety. |
| `generated_at` | Common in features, predictions, paper, status. Often used where source cutoff would be stronger. |
| `trained_until` | Supported by market-state validator but not consistently populated by trainer samples/predictions. |
| `decision_time` | Supported in market-state scoring and prediction/risk paths but not always tied to source cutoff. |
| `execution_time` | Simulated/paper generated time and live submit time exist, but fill lifecycle timestamps are incomplete. |

## C. Point-in-time safety audit

| Check | Status | Evidence | Risk |
|---|---|---|---|
| Unfinished candles used as closed candles | Fails | `v2_binance_kline_wss_loop.py:260-279` writes WSS kline rows regardless of `closed_candle`; `v2_feature_pipeline_native_loop.py:83-93` reads OHLCV arrays without sidecar finality; `tensor_builder.py:208-227` consumes `ohlcv[-1]`. | Critical look-ahead or live/current-bar leakage into features and training. |
| Higher timeframe candles used before close | Not proven safe | Higher timeframe values are consumed as latest windows in `feature_pipeline_native/service.py:332-405`; no evidence of close confirmation before `higher_tf_close_window[-1]`. | Critical for MTF leakage. |
| Backfilled data treated as live data | Not proven safe | `market_state_integrity/scoring.py:148-196` can infer source and candle metadata when missing; trainer loader reads latest mutable keys. | High. Backfilled rows can become trainable/live-like if not marked. |
| Future candles leaking into labels/features | Features risk present; future-label risk less direct | Feature builders use latest/current candles. `data_loader.py:240-265` labels from current expected move/features rather than explicitly future candles. | Critical for features, Medium for labels because labels are not true future labels in this path. |
| MASA newer than PPO observation cutoff | Contract missing | `masa.py:23-41` receives PPO probabilities and expected move in the same forward call. No independent timestamp/cutoff fields exist. | High. Cannot prove same market state if MASA becomes independent later. |
| PPO observations using mixed-timeframe inconsistent cutoffs | Fails by absence | `data_loader.py:100-193` and `tensor_builder.py:410-438` read latest payloads from many Redis keys independently. | Critical. No atomic snapshot or cutoff lock. |
| Feature normalization using future/global statistics | Not found in inspected runtime tensor path | Tensor builder uses finite conversion/masks and latest features; no centered/global scaler was found in inspected files. | Low in inspected path, but unresolved for any external model artifacts. |
| Training labels using future data beyond intended horizon | Not found directly; objective is weak | `data_loader.py:240-265` does not build horizon labels from future candles; it reuses expected move or same-snapshot indicators. | Medium. Less leakage, but poor supervised target integrity. |
| Rolling indicators with centered windows/future values | Not proven safe | Runtime code computes indicators from latest arrays; no centered-window use was observed in inspected snippets, but current open candle use makes rolling values non-final. | High because current candle contamination remains. |
| Train/test split leakage | Fails | `ppo_trainer.py:39-58` takes the current rows and uses the tail as validation without chronological/source isolation. | High. Validation can be contaminated by adjacent/latest mutable state. |
| Replay/backtest using corrected historical data unavailable live | Not proven safe | `edge_proof/replay_miner.py` intentionally mines future windows post-hoc; `replay_backtest_runner` mirrors paper ledger rather than live replay. | High if used for model trust rather than separated edge proof. |

## D. Data integrity audit

| Integrity issue | Current state | Evidence | Severity |
|---|---|---|---:|
| Missing candles | Detected only indirectly | Feature/tensor masks can mark missing, but no canonical candle gap detector/sequence validator was found before feature use. | High |
| Duplicate candles | Not enforced in inspected storage | Redis arrays/lists are used as mutable latest payloads. No DB uniqueness constraint or canonical dedupe key was found. | High |
| Out-of-order candles/events | Not enforced end to end | Tensor builder takes latest list element. If an array is out of order, `ohlcv[-1]` wins. | High |
| Exchange reconnect gaps | Not proven safe | WSS and native ingestors expose heartbeat/source metadata, but downstream feature builder does not require a gap-free candle series. | High |
| Websocket/API mismatch | Not reconciled | Binance REST and WSS write different market keys/schemas. No canonical merger was found. | High |
| Source disagreement between Binance/KuCoin/CoinAPI/CoinAnk | Mostly logged/masked | Trainer loader gathers multiple sources, but no hard source-consensus gate was found before tensor construction. | Medium |
| Stale Redis messages | Partially guarded | Orchestrator blocks stale/missing prediction freshness. Feature loop visible path writes `CURRENT` with empty stale flags. | High |
| Stale feature vectors | Partially guarded | `domain/features/freshness.py` exists, but native loop output can mark current without source cutoff proof. | High |
| Stale MASA outputs | Contract missing | MASA output has no generated timestamp or cutoff. | High |
| Stale PPO observations | Contract missing | `FeatureTensorRecord` has no observation time/cutoff. | High |
| NaN/inf/null feature values | Partially guarded | `tensor_builder.py:174-181` rejects NaN/inf into missing masks. | Medium |
| Silent forward-filling | Not directly found | No explicit interpolation was found in inspected snippets. Absence of canonical gap checks means implicit latest-value reuse remains possible. | Medium |
| Silent interpolation | Not directly found | No direct interpolation path found in inspected runtime files. | Low |
| Retry duplicates | Not proven safe | Ingestors write latest payloads/arrays. No idempotent event key was found at the canonical candle layer. | Medium |
| Partial candles in final candle tables | Fails | WSS writes open candles into OHLCV list; REST keeps current klines. | Critical |
| Timezone inconsistencies | Partially guarded | Many payloads use UTC/EST generated strings. Canonical timestamps are not normalized into one schema before model use. | Medium |
| Millisecond/second conversion bugs | Risk present | Code uses `time.time() * 1000`, raw Binance ms, ISO strings, and parsed seconds in different places. No canonical timestamp object was found. | Medium |

## E. Multi-timeframe audit

Observed timeframes include `1m`, `5m`, `15m`, `1h`, and `4h`.

| Timeframe | Where created/read | Native or resampled | Close confirmation | Gap handling | Alignment at decision time | Risk |
|---|---|---|---|---|---|---|
| `1m` | Binance WSS/REST keys, dynamic runtime, feature loop, trainer loader | Exchange-native in inspected paths | Not enforced by consumers | Not enforced before features | Latest key read independently | Critical |
| `5m` | Binance WSS/REST keys, feature loop, trainer loader, native dynamic runtime `FEATURE_TFS` | Exchange-native in inspected paths | Not enforced by consumers | Not enforced before features | Latest key read independently | Critical |
| `15m` | Binance WSS/REST keys, all-timeframe publisher required TFs | Exchange-native in inspected paths | Not enforced by consumers | Not enforced before predictions/status | Latest key read independently | High |
| `1h` | Binance WSS/REST keys, all-timeframe publisher required TFs, dynamic runtime | Exchange-native in inspected paths | Not enforced by consumers | Not enforced before predictions/status | Latest key read independently | High |
| `4h` | All-timeframe publisher required TFs | Likely exchange-native/latest prediction input | Not proven | Not proven | Required by status publisher, not proven aligned | High |

Multi-timeframe conclusions:

| Question | Answer |
|---|---|
| Where is MTF created? | Fragmented across Binance REST/WSS ingestion, native dynamic runtime, feature native service higher-TF input, trainer loader latest Redis reads, and all-timeframe publisher. |
| Exchange-native or resampled lower TF? | Inspected candle paths are exchange-native. No trusted resampling layer with finality proof was found. |
| How is candle close confirmed? | WSS sidecar records `closed_candle`; most downstream paths do not read it. REST/CoinAPI normalized bars do not carry finality. |
| How are gaps handled? | No canonical gap detector before feature/tensor construction was found. |
| How is alignment done at `decision_time`? | Latest Redis payloads are read independently. Market-state scoring can create a decision cutoff, but it is not a source-level atomic snapshot cutoff. |
| Can lower and higher TF become misaligned? | Yes. Lower and higher timeframe payloads can be updated at different moments and consumed together as latest state. |
| Are predictions at different TFs generated from same cutoff? | Not proven. Publication status aggregates required timeframes, but exact shared source cutoff is not enforced in inspected code. |

## F. MASA/PPO contract audit

| Contract item | Current state | Evidence |
|---|---|---|
| Exactly what MASA receives | Expected move, PPO action probabilities, coverage, and optional context. | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/masa.py:23-41` |
| Exactly what MASA outputs | `masa_signal`, `auxiliary_loss_target`, `regime_score`, `explanation`. | `masa.py:7-13` |
| MASA model version | Missing | No field in `MASAOutput`. |
| MASA generated_at | Missing | No field in `MASAOutput`. |
| MASA feature_cutoff | Missing | No field in `MASAOutput`. |
| MASA forecast_horizon | Missing | No field in `MASAOutput`. |
| MASA confidence | Missing | `regime_score` exists but is not a calibrated confidence contract. |
| MASA input feature hash | Missing | No input hash in `MASAOutput`. |
| Exactly what PPO receives | `FeatureTensorRecord` values, masks, coverage, source labels, and model inputs. | `tensor_builder.py:148-163`; `model.py:206-221` |
| PPO policy_version | Partial | `model_id` exists; no explicit policy version in observation. |
| PPO observation_time | Missing | Not in `FeatureTensorRecord`. |
| PPO feature_cutoff | Missing | Not in `FeatureTensorRecord`. |
| PPO observation hash | Partial | `tensor_id` and `feature_snapshot_id` exist, but no named observation hash with timestamp/cutoff contract. |
| PPO action mask | Missing | No action mask in inspected observation record. |
| PPO position state | Missing in observation | Position state is handled elsewhere, not embedded in `FeatureTensorRecord`. |
| MASA prediction id if used | Missing | MASA is an internal auxiliary signal, not an id-linked prediction. |
| Can MASA and PPO disagree? | The current MASA is derived from PPO-related values, so independent disagreement is limited. A separate disagreement classifier exists for rows. | `market_state_integrity/masa_ppo_disagreement.py:6-43` |
| What happens on disagreement? | Disagreement is classified/logged in integrity/status flows. It is not a direct model contract blocker in the inspected forward path. | `market_state_integrity/publisher.py:218-229`; `publisher.py:179-276` |
| Can disagreement block or reduce trades? | Only indirectly if market-state score/gates mark the row invalid. No dedicated risk reduction or hard block on MASA/PPO disagreement was found. | `publisher.py:179-276`; `orchestrator_decision/service.py:34-118` |

## G. Training sample audit

| Requirement | Current state | Evidence | Risk |
|---|---|---|---|
| Samples built from immutable PIT snapshots | No | `data_loader.py:100-193` reads latest Redis keys and current CoinAnk payloads. | Critical |
| Reject incomplete candle data | Not enforced | Missing data changes row classification, but `build_example` returns the example. | Critical |
| Reject stale source data | Not enforced before PPO train | Classification can be `STALE_MASKED`, but `ppo_trainer.py` trains over supplied rows. | High |
| Reject future leakage | Not enforceable with current metadata | Source `available_at`, candle finality, and cutoff are absent or inferred. | Critical |
| Reject MASA/PPO cutoff mismatch | Not possible | MASA/PPO cutoff fields are missing. | High |
| Reject NaN/inf/null features | Partially | `tensor_builder.py:174-181` converts invalid floats into missing mask/0.0. | Medium |
| Reject missing execution result | Not in training sample builder | Loader uses latest risk/orch/paper keys as inputs but no required execution outcome contract was found. | High |
| Reject missing fees/slippage | Not consistently | Paper worker uses deterministic defaults; trainer sample path does not require fee/slippage provenance. | High |
| Reject invalid position state | Not in tensor builder | Position state is not required in `FeatureTensorRecord`. | High |
| Reject backfilled data marked live | Not enforceable | Backfilled markers are not canonical from ingestion through training. | Critical |

Training path findings:

| File/function | Finding |
|---|---|
| `data_loader.py`, `load_payloads` | Loads latest mutable Redis payloads for market, features, predictions, risk, paper, and current CoinAnk data. |
| `data_loader.py`, `build_example` | Returns examples even when classified `MISSING_MASKED` or `STALE_MASKED`. |
| `data_loader.py`, `_label_expected_move_after_cost` | Uses existing expected move or same-snapshot TA fallback, not a clean future-horizon realized return label. |
| `ppo_trainer.py`, `train` | Does not filter examples by row classification, source cutoff, candle completeness, or backfill/live status before training. |
| `ppo_trainer.py`, train/validation split | Uses current row ordering and tail validation; no chronological split or symbol/time isolation. |

## H. Execution and position audit

| Topic | Current state | Evidence | Risk |
|---|---|---|---|
| Current position state storage | Paper uses `v2:paper:positions`, `v2:paper:position_price_track:{symbol}`, and history keys. Live exchange positions are read separately. | `publisher.py:324-387`; `position_price_tracking_recorder.py:24-26`; `account_position_monitor/service.py:232-277` | Medium |
| Hedge mode representation | Live transport reads Binance position mode and maps `positionSide` for dual-side. Paper hedge engine is paper-only and fail-closed. | `binance_live_order_transport.py:327-362`, `695-704`; `hedge_engine.py:96-260` | Medium |
| Open/close/flip validation | Not complete | Live transport derives side from selected signal and submits market order. No full state-machine validation with reduce-only/open/close/flip intent was found. | Critical |
| Invalid transitions submitting orders | Possible if upstream gates pass | Live transport gates many conditions, but does not prove intended transition against current exchange position quantity and local state. | Critical |
| Exchange/local drift | Risk present | Exchange position monitor is read-only; local paper state and live exchange state are not a single reconciled state machine. | High |
| Partial fills | Not fully handled | `submit_market_order` returns submitted/error with redacted response. No order lifecycle reconciliation was found in inspected path. | High |
| Rejected/canceled orders | Partial | Submit errors are captured; later cancellation/rejection lifecycle reconciliation was not found. | High |
| Execution feedback into training | Weak | Paper ledger/status exist; training loader reads some paper/risk keys, but no strict outcome sample contract with fill status, fees, slippage, and position transition exists. | High |

Live execution safety strengths:

| Safeguard | Evidence |
|---|---|
| Operator-gated live state | `runtime_execution_state.py:106-166` builds live gate and write-guard state. |
| Kill switch and dedupe | `binance_live_order_transport.py:583-919` checks kill switch and dedupe keys. |
| Signed read preflight | `binance_live_order_transport.py:327-462` fetches position mode, margin status, and symbol filters. |
| Balance/min-order checks | `binance_live_order_transport.py:583-919` includes available balance and filter checks. |
| Market/leverage mutation disabled | Runtime state and transport status preserve no margin/leverage mutation posture. |

## I. Live vs backtest parity audit

| Area | Live | Paper | Replay/backtest | Parity verdict |
|---|---|---|---|---|
| Fees | Exchange fees not fully reconciled from fills in inspected submit path | Deterministic fee defaults, e.g. paper worker constants | Replay mirrors paper or uses edge-proof defaults | Not equal |
| Slippage | Real market order slippage possible | Deterministic slippage bps | Edge proof uses default/override | Not equal |
| Latency | Live gate checks signal age, but actual latency/fill timing not modeled | Generated-time simulated fill | Post-hoc projection | Not equal |
| Candle finality | Live path trusts upstream signal | Paper path trusts upstream risk/signal | Replay mirrors paper ledger | Same upstream weakness |
| Order fills | Binance market order submit only in inspected path | Immediate deterministic simulated fill | Ledger projection/post-hoc | Not equal |
| Spread | Live real spread | Paper default spread/slippage fields | Edge proof defaults | Not equal |
| Liquidation/funding | Live exchange risk real | Some funding fields/status exist; not full liquidation simulator | Not full parity | Not equal |
| Available data at decision time | Not fully proven | Not fully proven | Post-hoc data may be used intentionally | Not equal |
| Position state | Exchange positions read separately | Paper positions local | Replay from paper ledger | Not equal |
| MASA/PPO input construction | Same upstream trainer/publisher weaknesses | Same upstream weaknesses | Not live replay of model inputs | Not trusted parity |

## J. Existing safeguards

| Safeguard | File/function | Protects against | Enforced or logged | Mode coverage | Tests found in static audit |
|---|---|---|---|---|---|
| V2 Redis namespace write guard | `v2_owned_runtime/redis_namespace_adapter.py`, `_reject_legacy_write`, `set`, `hset`, `xadd` | Accidental non-`v2:` writes through adapter | Enforced when adapter is used | Runtime paths using adapter | Not inspected |
| Feature invalid float masking | `tensor_builder.py`, `_finite_float`, `_add_value` | NaN/inf tensor values | Enforced into missing mask/0.0 | Training/inference tensor path | Not inspected |
| Feature readiness validation | `domain/features/validation.py`, `validate_feature_snapshot_for_trainer` | Missing/stale/source key feature snapshots | Enforced where called | Feature snapshot service path | Not proven in native trainer loop |
| Market-state validators | `market_state_integrity/validators.py`, `validate_event_time_alignment`, `validate_candle_completion` | Future source times, backfill timing, unclosed candles | Enforced when real fields exist | Prediction/training scoring path | Not inspected |
| Market-state scoring | `market_state_integrity/scoring.py`, `score_market_state` | Aggregated source/training/prediction validity | Enforced in publisher gates | Prediction/risk/paper publication | Not inspected |
| Orchestrator freshness and confidence gate | `orchestrator_decision/service.py`, `decide` | Missing/stale prediction, low confidence, flat actions | Enforced | Orchestrator | Not inspected |
| Risk gateway deny by default | `risk_gateway/service.py`, `evaluate` | Non-open actions and missing caps | Enforced | Risk/paper/live lineage | Not inspected |
| Paper edge/fill gates | `v2_paper_execution_worker.py`, `run`, `_paper_edge_status_fields`, `_build_simulated_fill` | Missing risk, bad paper edge, fill-block conditions | Enforced for paper worker | Paper | Not inspected |
| Paper hedge fail-closed | `hedge_engine.py`, `evaluate_hedge` | Accidental live hedge/missing operator approvals | Enforced | Paper hedge | Not inspected |
| Position price no-fake-price guard | `position_price_tracking_recorder.py`, `build_position_track` | Fabricated mark prices | Enforced | Paper position tracking | Not inspected |
| Live runtime operator gate | `runtime_execution_state.py`, `build_runtime_state_payload`; `binance_live_order_transport.py`, `evaluate_live_order_transport` | Unauthorized live submit | Enforced | Live | Not inspected |
| Live transport signed-read preflight | `binance_live_order_transport.py`, `fetch_position_mode`, `fetch_account_margin_status`, `fetch_symbol_filters` | Missing exchange state/balance/filter data | Enforced before submit | Live | Not inspected |
| Live canary write allowlist | `live_canary/execution_adapter.py`, `_safe_redis_set` | Accidental non-canary Redis writes | Enforced | Live canary | Not inspected |
| Replay/post-hoc separation comments | `edge_proof/replay_miner.py` module docstring | Warns that future outcome windows are post-hoc | Documentation/logging | Replay/edge proof | Not inspected |

## K. Missing safeguards ranked

| Rank | Severity | Missing safeguard | Why required | Fix size |
|---:|---|---|---|---|
| 1 | Critical | Canonical candle schema with `event_time`, `candle_open_time`, `candle_close_time`, `ingested_at`, `available_at`, `is_closed`, `source`, and idempotency key | Prevents unfinished/current candles and timestamp ambiguity from entering features/training/execution | Medium |
| 2 | Critical | Closed-candle-only normalization table/key separate from live/current kline key | Prevents partial candles being treated as final | Small/medium |
| 3 | Critical | Remove or invert finality inference in market-state scoring | Unknown candle finality must block trusted prediction/training instead of being inferred as safe | Small |
| 4 | Critical | Atomic decision snapshot with shared `feature_cutoff` across all sources/timeframes | Prevents mixed latest Redis state from creating impossible market observations | Large |
| 5 | Critical | Training sample builder from immutable PIT snapshots with hard rejection rules | Prevents dirty/backfilled/stale/misaligned data from entering PPO/MASA training | Large |
| 6 | Critical | Multi-timeframe alignment gate | Ensures higher timeframe candles are closed and aligned to the same decision cutoff as lower timeframe features | Medium |
| 7 | High | MASA/PPO contract fields and hash linkage | Required to prove both model components operate on the same market state | Medium |
| 8 | High | PPO observation contract with policy version, observation time, feature cutoff, observation hash, action mask, position state | Required to audit and reproduce decisions | Medium |
| 9 | High | Execution state machine for open/close/flip/hedge/reduce-only | Prevents invalid transitions and live/local exchange drift | Large |
| 10 | High | Order lifecycle reconciliation for partial fills, rejects, cancels, average fill, fees | Required for trustworthy training feedback and live risk | Large |
| 11 | High | Source gap/duplicate/out-of-order detector before feature publication | Prevents corrupt candles/events from becoming model input | Medium |
| 12 | High | Backfill/live data provenance and training quarantine | Prevents historical corrected data from contaminating live-style training | Medium |
| 13 | Medium | Source disagreement policy across Binance/KuCoin/CoinAPI/CoinAnk | Reduces bad signals from stale or disagreeing providers | Medium |
| 14 | Medium | Timestamp unit normalization wrapper | Reduces ms/sec/ISO/EST/UTC conversion bugs | Small/medium |
| 15 | Low | Documentation of mode-specific safeguards and expected keys | Makes audits and operations simpler | Small |

## L. Evidence findings

### Finding 1: Binance REST candles are normalized without close/finality metadata

| Field | Detail |
|---|---|
| File | `v2/backend/app/services/market_ingest/service.py` |
| Function/class | `_binance_rest_klines`, `_binance_kline_to_bar` |
| Line reference | `558-590`, `704-715` |
| Snippet | `return [self._binance_kline_to_bar(row, symbol=symbol, timeframe=timeframe) for row in payload]` and `"ts": int(row[0])` |
| Why unsafe | Binance kline REST responses include the current in-progress candle. The code converts all rows and stores only open-time `ts` plus OHLCV. It does not drop the current candle or persist `close_time`/`is_closed`/`available_at`. |
| Recommended fix | Normalize REST candles into a canonical schema and write only confirmed closed candles to closed-candle keys. Keep current candle in a separate live-tick/current-kline key. |
| Fix size | Medium |

### Finding 2: Binance WSS writes unfinished candles into the consumed OHLCV key

| Field | Detail |
|---|---|
| File | `v2/backend/app/cli/v2_binance_kline_wss_loop.py` |
| Function/class | `_to_kline_row`, `run` |
| Line reference | `126-153`, `260-279` |
| Snippet | `row = _merge_kline_row(existing, row)` and source metadata includes `"closed_candle": bool(message.get("k", {}).get("x"))` |
| Why unsafe | The source sidecar preserves `closed_candle`, but the OHLCV list receives the row even when `closed_candle` is false. Downstream feature and tensor builders read the OHLCV list, not the sidecar. |
| Recommended fix | Do not publish open WSS candles into the closed OHLCV key. Publish current/open candle separately and require `x == true` before final-candle storage. |
| Fix size | Small/medium |

### Finding 3: Feature loop reads OHLCV arrays without finality sidecar

| Field | Detail |
|---|---|
| File | `v2/backend/app/cli/v2_feature_pipeline_native_loop.py` |
| Function/class | `_read_klines`, `_klines_to_ohlc_series`, `_features_from_market`, `run_once` |
| Line reference | `83-93`, `305-321`, `331-383`, `479-585` |
| Snippet | `_read_klines(redis_client, f"v2:market:ohlcv:binance:{symbol}:{interval}")` and `"feature_freshness_state": "CURRENT"` |
| Why unsafe | Feature generation consumes latest OHLCV arrays and marks features current in the visible path without checking candle closed status, source availability, or gap-free sequence. |
| Recommended fix | Make feature construction accept only canonical closed-candle snapshots and require source freshness/finality validation before writing `CURRENT`. |
| Fix size | Medium |

### Finding 4: Tensor builder consumes the latest candle row directly

| Field | Detail |
|---|---|
| File | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/tensor_builder.py` |
| Function/class | `_latest_kline`, `V2UnifiedFeatureTensorBuilder.build` |
| Line reference | `208-227`, `410-438`, `687-701` |
| Snippet | `row = ohlcv[-1]` and fallback features are derived from latest kline open/close. |
| Why unsafe | If ingestion wrote an unfinished or out-of-order candle into the OHLCV list, the model tensor uses it. No closed flag, close time, or available time is checked. |
| Recommended fix | Replace `ohlcv[-1]` consumption with a validated closed-candle selector that enforces monotonic open times, expected interval, close confirmation, and cutoff <= decision time. |
| Fix size | Medium |

### Finding 5: Market-state scoring can infer candle finality when it is missing

| Field | Detail |
|---|---|
| File | `v2/backend/app/services/market_state_integrity/scoring.py` |
| Function/class | `_with_training_snapshot_time_inference`, `score_market_state` |
| Line reference | `148-196`, `199-330` |
| Snippet | The inference path sets `candle_closed_confirmed = True`, derives `candle_close_time` from `generated_at`, and derives `candle_open_time` from timeframe seconds. |
| Why unsafe | This converts unknown source finality into asserted finality. It can mask the exact missing metadata that should block point-in-time trusted prediction/training. |
| Recommended fix | Remove finality inference for trusted modes. Unknown finality should produce `CANDLE_COMPLETION_UNKNOWN` and block training/prediction/risk unless a specific non-closed-candle model is declared. |
| Fix size | Small |

### Finding 6: CoinAPI normalization drops end/availability metadata

| Field | Detail |
|---|---|
| File | `v2/backend/app/services/market_ingest/service.py` |
| Function/class | `_coinapi_v1_klines`, `_coinapi_to_bar` |
| Line reference | `522-556`, `718-729` |
| Snippet | `"ts": self._parse_iso_ms(row.get("time_period_start"))` |
| Why unsafe | CoinAPI OHLCV has period start/end semantics. Only period start is retained in normalized bars, so downstream code cannot prove the candle was closed and available before the decision. |
| Recommended fix | Preserve `time_period_start`, `time_period_end`, `ingested_at`, `available_at`, and source id in the canonical candle record. |
| Fix size | Medium |

### Finding 7: Training loader reads latest mutable Redis state and non-V2 current CoinAnk keys

| Field | Detail |
|---|---|
| File | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py` |
| Function/class | `_get_current_coinank`, `load_payloads` |
| Line reference | `49-82`, `100-193` |
| Snippet | Current CoinAnk reads use `latest:coinank:*`; payloads read many `v2:*:latest` and latest market keys. |
| Why unsafe | Latest mutable state is not an immutable decision snapshot. Reading current non-V2 CoinAnk keys also weakens V2 namespace lineage and backfill/live provenance. |
| Recommended fix | Build training samples from immutable `decision_id` or `snapshot_id` records with explicit source cutoff and source namespace provenance. Quarantine current/backfill sources unless explicitly marked. |
| Fix size | Large |

### Finding 8: Dirty or stale training examples are not rejected before PPO training

| Field | Detail |
|---|---|
| File | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py`; `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/ppo_trainer.py` |
| Function/class | `build_example`, `train` |
| Line reference | `195-223`; `39-58`, `114-123` |
| Snippet | `row_classification` may be `MISSING_MASKED` or `STALE_MASKED`, while trainer builds tensors/actions from `rows`. |
| Why unsafe | Classification is informative but not a hard training rejection in the inspected path. PPO can learn from masked/stale/incomplete samples. |
| Recommended fix | Require `TRAINABLE` plus valid PIT, candle finality, fee/slippage/outcome, and position-state checks before constructing training batches. |
| Fix size | Medium |

### Finding 9: PPO train/validation split is not chronological or source-isolated

| Field | Detail |
|---|---|
| File | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/ppo_trainer.py` |
| Function/class | `train` |
| Line reference | `39-58` |
| Snippet | `rows = available_rows[:tuned_batch_size]` followed by validation as the tail fraction. |
| Why unsafe | Current Redis row ordering is not a robust chronological split. Adjacent rows can share mutable source state or leakage. |
| Recommended fix | Split by event-time/decision-time with purge gaps by symbol/timeframe and separate backfill/live domains. |
| Fix size | Medium |

### Finding 10: MASA output lacks audit contract fields

| Field | Detail |
|---|---|
| File | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/masa.py` |
| Function/class | `MASAOutput`, `V2MASAAdapter.evaluate` |
| Line reference | `7-13`, `23-41` |
| Snippet | `MASAOutput(masa_signal=..., auxiliary_loss_target=..., regime_score=..., explanation=...)` |
| Why unsafe | Without model version, generated time, feature cutoff, horizon, confidence, and input hash, MASA output cannot be independently audited or matched to PPO observations. |
| Recommended fix | Add a strict MASA prediction record and treat current MASA adapter as an auxiliary head unless it satisfies the full contract. |
| Fix size | Medium |

### Finding 11: PPO observation contract is descriptive, not enforced

| Field | Detail |
|---|---|
| File | `v2/backend/app/services/rl_core/observation_schema.py`; `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/tensor_builder.py` |
| Function/class | Module descriptor; `FeatureTensorRecord` |
| Line reference | `observation_schema.py:1-17`; `tensor_builder.py:148-163` |
| Snippet | Observation schema says it does not assemble runtime tensors; `FeatureTensorRecord` stores tensor ids, values, masks, source labels, and coverage. |
| Why unsafe | The runtime observation lacks enforced policy version, observation time, feature cutoff, action mask, position state, and MASA prediction id. |
| Recommended fix | Promote observation schema into the actual tensor builder output and require it before model forward/publish. |
| Fix size | Medium |

### Finding 12: Prediction payload improves lineage but still depends on inferred market state

| Field | Detail |
|---|---|
| File | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/publisher.py` |
| Function/class | `build_prediction_payload`, `publish_lineage` |
| Line reference | `179-276`, `324-387` |
| Snippet | Payload includes market-state fields and paper gate fields, then writes orchestrator/risk/paper lineage. |
| Why unsafe | Publication is a useful safeguard, but source finality/cutoff can be missing upstream and inferred by market-state scoring. The payload cannot repair an untrusted feature tensor. |
| Recommended fix | Require canonical feature cutoff and closed-candle proof before prediction payload construction, not after. |
| Fix size | Medium |

### Finding 13: Live transport has strong gates but no full transition validator

| Field | Detail |
|---|---|
| File | `v2/backend/app/services/live_gate/binance_live_order_transport.py` |
| Function/class | `evaluate_live_order_transport`, `submit_market_order` |
| Line reference | `583-919`, `274-325` |
| Snippet | Live transport selects a current signal, derives side/position side, checks gates, and posts a Binance `MARKET` order. |
| Why unsafe | The transport checks many preconditions, but no full open/close/flip/reduce-only state machine or fill lifecycle reconciliation was found. Dirty upstream signals can also pass if lineage fields were inferred as valid. |
| Recommended fix | Add a pre-submit state transition validator using exchange position, local intent, reduce-only/open intent, hedge mode, current quantity, and post-submit fill reconciliation. |
| Fix size | Large |

### Finding 14: Replay/backtest is not live-parity simulation

| Field | Detail |
|---|---|
| File | `v2/backend/app/services/replay_backtest_runner/service.py`; `v2/backend/app/services/edge_proof/replay_miner.py` |
| Function/class | `assemble_replay_backtest_step`, `extract_paper_rows`, module edge-proof mining |
| Line reference | `replay_backtest_runner/service.py:30-128`; `edge_proof/replay_miner.py:1-20`, `396-440` |
| Snippet | Replay mirrors paper ledger entries; edge proof mines post-hoc outcome windows. |
| Why unsafe | This is useful reporting/evidence, but it is not a live simulator with identical candle finality, spreads, fills, latency, funding, liquidation, and available data. |
| Recommended fix | Separate post-hoc edge proof from live-style replay and build a deterministic event replay from immutable source snapshots. |
| Fix size | Large |

### Finding 15: Existing finality validator is good but undermined by missing fields/inference

| Field | Detail |
|---|---|
| File | `v2/backend/app/services/market_state_integrity/validators.py` |
| Function/class | `validate_candle_completion`, `validate_event_time_alignment` |
| Line reference | `19-80` |
| Snippet | Missing finality returns `CANDLE_COMPLETION_UNKNOWN`; unclosed candles return `UNCLOSED_CANDLE`. |
| Why safe/unsafe | The validator is correct in isolation. The unsafe part is upstream fields are often absent and scoring can infer them as confirmed. |
| Recommended fix | Wire validator directly to canonical source metadata and forbid inference in trusted modes. |
| Fix size | Small/medium |

## M. Final verdict

1. Is the current pipeline point-in-time safe?

No. It has partial validators and live gates, but unfinished candles, missing availability metadata, inferred candle finality, and latest Redis state sampling prevent an end-to-end point-in-time safety claim.

2. Are multi-timeframe features aligned correctly?

Not proven. Lower and higher timeframe payloads are read as latest independent Redis values, and no shared source cutoff is enforced across `1m`, `5m`, `15m`, `1h`, and `4h`.

3. Are MASA and PPO operating on the same market state?

In the current implementation MASA is mostly derived inside the PPO/model forward path, so it is not an independent contradictory market-state consumer. However, the contract is insufficient: neither MASA nor PPO carries the full cutoff/hash/version fields required to prove same-market-state operation.

4. Can dirty data enter training?

Yes. Training examples are built from latest mutable Redis state, missing/stale examples can still be returned, and the PPO trainer does not enforce hard rejection by PIT validity, candle completeness, backfill status, or execution outcome completeness.

5. Can dirty data reach execution?

Yes. Dirty data can reach paper execution if upstream features/predictions are marked valid. Live execution has stronger gates, but it trusts upstream lineage/integrity fields and does not independently revalidate candle finality or multi-timeframe cutoff consistency.

6. Can backfilled data contaminate live-style training?

Yes. Backfilled/live provenance is not canonical from ingestion through training samples. Market-state scoring can detect backfilled flags when present, but ingestion and latest Redis sample building do not guarantee those flags exist.

7. Can position state become inconsistent?

Yes. Paper position state, live exchange position reads, and live order submit are separate paths. A complete transition validator and fill lifecycle reconciler were not found, so local/exchange drift and invalid open/close/flip behavior remain possible risks.

8. What are the top 10 fixes required before adding any new data source?

| Rank | Fix |
|---:|---|
| 1 | Implement canonical candle/event schema with explicit close, availability, ingestion, source, and finality fields. |
| 2 | Split open/current candles from confirmed closed-candle storage and make features consume only closed candles. |
| 3 | Remove trusted-mode candle finality inference; unknown finality must block training/prediction/paper/live. |
| 4 | Add atomic decision snapshots with shared `feature_cutoff` across all sources and timeframes. |
| 5 | Add MTF alignment gate requiring every timeframe to be closed and cutoff-consistent at decision time. |
| 6 | Rebuild training samples from immutable PIT snapshots and reject incomplete, stale, backfilled-live, NaN/inf, missing outcome, or invalid position samples. |
| 7 | Define and enforce MASA output contract with version, generated time, cutoff, horizon, confidence, and input hash. |
| 8 | Define and enforce PPO observation contract with policy version, observation time, cutoff, observation hash, action mask, position state, and MASA id if used. |
| 9 | Add live execution state-machine validation for open/close/flip/hedge/reduce-only plus exchange/local reconciliation. |
| 10 | Add order lifecycle and live/paper/backtest parity layer for fills, partial fills, rejects, cancels, fees, slippage, spread, funding, liquidation, and latency. |

---

# Phase Refresh Addendum: Trainer and Config Updates

Generated: `2026-06-11`

Scope: repeat of the three prior phases after trainer/runtime/config additions were detected in the worktree. This addendum does not change strategy logic, PPO, MASA, or live execution behavior.

## Refreshed phase 1: audit deltas

| Area | New or refreshed evidence | Trust impact |
|---|---|---|
| Trainer subprocess boundary | `v2/backend/app/api/v2/trainer.py`, `validate_trainer_argv`, `_FORBIDDEN_FLAGS_EXACT`, `ALLOWED_MODES` | Positive safeguard. Trainer summary route restricts subprocess modes to `status`, `export`, and `read_only`, and blocks flags such as `--enable-trader`, `--write`, `--kill-switch-off`, and margin mutation flags. This protects the API read boundary, but it does not by itself prove training samples are PIT-clean. |
| Trainer liveness SLA | `v2/backend/app/domain/trainer_liveness/evaluator.py`, `evaluate_liveness`; `v2/backend/app/domain/trainer_liveness/sla_config.py`, `LivenessSLAConfig` | Positive runtime-observability safeguard. It flags stale predictions, stale GPU batches, stale proposals, zero stream growth, dead prediction workers, and fatal log signatures. This improves runtime health detection but is not a candle/finality/training-sample rejection gate. |
| Trainer worker health | `v2/backend/app/domain/trainer_worker_health/health_evaluator.py`, `evaluate_trainer_worker_health` | Positive health classification. It distinguishes `UNKNOWN`, `DEGRADED`, `CRITICAL`, and `HEALTHY`; critical conditions include stale prediction/GPU/proposal age, zero stream growth, worker dead, and fatal log signatures. It should be consumed by prediction/training gates to block dirty decisions. |
| Training sample rejection helper | `v2/backend/app/services/market_state_integrity/sample_rejection.py`, `classify_training_sample` | Positive safeguard if wired into trainer batching. It delegates to `score_market_state` and returns `accepted_for_training`, `valid_for_training`, score, lineage, and reject reasons. The open risk remains whether every actual trainer batch requires this accepted result before learning. |
| Market-state contracts | `v2/backend/app/services/market_state_integrity/contracts.py`, `IntegrityThresholds`, `MarketStateScore` | Positive contract expansion. Thresholds now distinguish training, prediction, risk, paper, and live. The earlier critical concern remains: the trust value depends on source timestamp/finality fields being real, not inferred. |
| Replay snapshot | `v2/backend/app/services/market_state_integrity/replay_snapshot.py`, `build_replay_snapshot` | Positive replayability improvement. Snapshot includes decision id, all-TF candle timestamps, all source event times, feature vector hash, missing/stale mask hashes, MASA/PPO timestamps, strategy router fields, and source lineage. This helps replay clean decisions if populated from trusted inputs. |
| Config/admin manager | `v2/backend/app/cli/v2_config_admin_manager.py`, `build_status`; `v2/backend/app/api/v1/config_admin.py`, `list_settings`, `config_admin_status` | Positive fail-closed config posture. Status reports `live_gate=blocked_human_only`, `approval_token_created=False`, `approval_token_self_creatable=False`, `old_redis_write=False`, `exchange_action_taken=False`, `leverage_or_margin_change=False`, and `secrets_written_to_payload=False`. This should be continuously verified because unsafe config state can invalidate trust even if model inputs are clean. |

## Refreshed phase 2: verification tool deltas

The read-only verifier now includes a config/admin section in addition to the prior candle, MTF, feature, MASA/PPO, training, execution, and parity checks.

| Check family | Implementation | Critical failures detected |
|---|---|---|
| Config/admin safety | `v2/backend/app/cli/verify_pipeline_trust.py`, `check_config_records` | Secret leakage markers, self-created approval tokens, old Redis writes, exchange action markers, leverage/margin mutation markers. |
| MASA/PPO cutoff parity | `verify_pipeline_trust.py`, `check_masa_ppo_consistency` | MASA future cutoff and MASA/PPO cutoff mismatch. |
| Training execution false positives | `verify_pipeline_trust.py`, `check_training_samples` | Rejected/canceled/expired orders becoming positive accepted training samples. |
| Position drift | `verify_pipeline_trust.py`, `check_execution_records` | Local/exchange position mismatch is now critical. |
| Future feature availability | `verify_pipeline_trust.py`, `source_candle_timestamps` | `available_at` and `source_available_time` after decision cutoff are treated as future feature use. |

## Refreshed phase 3: synthetic trust tests

Synthetic end-to-end tests now include a clean config/admin record and an unsafe config/admin mutation case.

| Test file | Coverage |
|---|---|
| `v2/backend/tests/unit/test_pipeline_trust.py` | Clean path, missing candle, duplicate candle, out-of-order candle, unfinished higher timeframe candle, future `available_at`, MASA future cutoff, MASA/PPO cutoff mismatch, null features, backfilled-live sample, stale event message, source disagreement, invalid position transition, local/exchange position drift, partial fill handling, rejected/canceled order handling, rejected-order false-positive training sample, unsafe config/admin state. |
| `v2/backend/tests/unit/test_verify_pipeline_trust.py` | Direct verifier exit-code smoke coverage for clean and critical-dirty synthetic records. |
| `docs/pipeline_trust_testing.md` | Documents the synthetic safety matrix and expected behavior. |
| `PIPELINE_TRUST_VERIFICATION.md` | Documents verifier usage, read-only Redis/file behavior, report outputs, and config/admin safety scope. |

## Refreshed verdict

The new trainer/config additions improve observability and fail-closed control-plane evidence. They do not eliminate the original core trust gaps unless they are enforced before every trainer batch and execution candidate.

Current trust verdict remains conditional:

| Question | Refreshed answer |
|---|---|
| Is the pipeline point-in-time safe? | Not proven end to end. New liveness/config controls help, but candle finality, shared cutoffs, and immutable sample acceptance remain the decisive blockers. |
| Can dirty data enter training? | Still possible unless `classify_training_sample` or equivalent hard rejection is enforced on every training row. The verifier and synthetic tests now detect this condition. |
| Can dirty data reach execution? | Still possible if upstream prediction lineage is inferred or incomplete. The verifier now detects invalid transition, drift, and unsafe config state. |
| Are clean decisions replayable? | Improved if `build_replay_snapshot` is populated with trusted all-TF candle timestamps, source event times, hashes, MASA/PPO timestamps, and strategy router fields. |
| Are config changes safely represented? | Improved. Config/admin status is fail-closed by design and is now included in read-only verification. |

## Updated top fixes before adding new data sources

| Rank | Fix |
|---:|---|
| 1 | Enforce canonical closed-candle schema and reject current/open candles before features. |
| 2 | Require atomic shared `feature_cutoff` across all timeframes and sources. |
| 3 | Forbid trusted-mode finality inference; unknown finality must block. |
| 4 | Wire `classify_training_sample` or equivalent hard rejection into every actual trainer batch. |
| 5 | Require replay snapshots for every clean decision with all-TF timestamps, source event times, hashes, MASA/PPO timestamps, and strategy fields. |
| 6 | Block prediction/training/execution when trainer worker health is `CRITICAL` or unknown where evidence is required. |
| 7 | Keep config/admin status fail-closed and continuously verify no self-approval, secret leakage, old Redis writes, exchange action, or leverage/margin mutation. |
| 8 | Add full execution state-machine and exchange/local reconciliation before live submit. |
| 9 | Persist order lifecycle outcomes and prevent rejected/canceled orders from becoming positive training samples. |
| 10 | Run `verify_pipeline_trust` and synthetic trust tests as required gates before promoting new data sources. |
