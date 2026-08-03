# Script-by-Script Reference — AI BOT V2 CLI

> **Historical snapshot — superseded by the 2026-07-16 reconstruction.** Do not use this file alone for current behavior, operations, safety, or change-impact decisions. Start with [REVERSE_ENGINEERING_INDEX.md](REVERSE_ENGINEERING_INDEX.md).
Generated: 2026-07-01
Total: 231 scripts in v2/backend/app/cli/

All scripts are in: `v2/backend/app/cli/`
Run from repo root: `cd "/home/wali/Desktop/AI BOT REBUILD/v2/backend" && source .venv/bin/activate`

Safety default: **All scripts below are read-only or simulation unless explicitly noted as dangerous.**

---

## Category A — Active Trading Pipeline (Core Loops)

### `v2_trade_management_paper_loop.py`
- **Purpose**: Sole paper trader. Manages paper positions, fills, PnL, feedback
- **Inputs**: `v2:signals:paper`, `v2:risk:gateway:paper_online_decisions`, mark price feed
- **Outputs**: `v2:paper:ledger`, `v2:paper:closed_trades`, `v2:paper:heartbeat`
- **Systemd**: `ai-bot-v2-trade-management-paper-loop.service`
- **Safe to run manually**: NO — singleton; run only via systemd
- **Command**: managed by systemd only
- **Expected output**: Continuous loop; heartbeat TTL = 3600s
- **Failure modes**: Stops filling if risk gateway has no ALLOW decisions
- **Safety warning**: ONLY paper fills. places_real_order=false always.

### `v2_risk_gateway_live_loop.py`
- **Purpose**: Risk gateway — evaluates orchestrator proposals; blocks/allows fills
- **Inputs**: `v2:orchestrator:decisions`, `v2:live_gate:state`, risk rules
- **Outputs**: `v2:risk:gateway:decisions`, `v2:risk:gateway:heartbeat`
- **Systemd**: `ai-bot-v2-risk-gateway-live-loop.service`
- **Safe to run manually**: NO — singleton
- **Expected output**: 130 DENY decisions per cycle (deny_default in effect)
- **Failure modes**: fail_closed=true — if gateway stops, paper fills also stop
- **Safety warning**: Do not disable; deny_default protects against live exposure

### `v2_orchestrator_arbitration_loop.py`
- **Purpose**: Arbitrates predictions into 130 bucket winners per cycle
- **Inputs**: `v2:prediction:{sym}:{tf}` (1,070 keys), live gate state
- **Outputs**: `v2:orchestrator:decisions`, `v2:orchestrator:heartbeat`
- **Systemd**: `ai-bot-v2-orchestrator-arbitration-loop.service` (or v2_orchestrator_arbitration_loop.service)
- **Safe to run manually**: NO — singleton
- **Expected output**: 393 preds → 130 winners per ~6-second cycle
- **Failure modes**: If no predictions are fresh, outputs empty decisions
- **Safety warning**: cannot_bypass_risk_gateway=true always enforced

### `v2_native_cuda_trainer_persistent_loop.py`
- **Purpose**: Native PyTorch PPO+MASA trainer on RTX 5080; continuous training
- **Inputs**: `v2:features:snapshot:*`, `v2:trainer:feedback:outcomes`
- **Outputs**: `.local_models/v2_native_rl_masa_ppo/*.weights.npz`, `v2:trainer:hybrid_cuda:heartbeat`
- **Systemd**: `ai-bot-v2-native-cuda-trainer-persistent-loop.service`
- **Safe to run manually**: NO — singleton; uses GPU exclusively
- **Expected output**: Checkpoint saved periodically; GPU utilization ~40-80%
- **Failure modes**: CUDA OOM stops training (currently 0 OOM events)
- **Safety warning**: Do not run a second instance; GPU contention will cause OOM

### `v2_feature_pipeline_native_loop.py`
- **Purpose**: Core feature computation pipeline; aggregates all ingestor data
- **Inputs**: Candle data, TA indicators, alt-data from Redis
- **Outputs**: `v2:features:latest:{sym}:{tf}`, `v2:features:pipeline:heartbeat`
- **Systemd**: `ai-bot-v2-feature-pipeline-native-loop.service`
- **Safe to run manually**: NO — singleton continuous loop
- **Expected output**: Features written every 60s-300s per symbol/timeframe
- **Failure modes**: If ingestors are stale, features become stale; trainer degrades
- **Safety warning**: Restart only when no trainer batch is in progress

### `v2_continuous_edge_guardian.py`
- **Purpose**: A-grade execution gate; evaluates signal quality threshold
- **Inputs**: Recent prediction quality metrics, confidence distributions
- **Outputs**: `v2:continuous_edge_guardian:a_grade_execution_gate`
- **Systemd**: `ai-bot-v2-continuous-edge-guardian.service`
- **Safe to run manually**: NO — continuous gate keeper
- **Expected output**: PASS/FAIL gate status published every cycle
- **Failure modes**: If stale, orchestrator may hold or drop signals

---

## Category B — Ingestors

### `v2_binance_kline_wss_loop.py`
- **Purpose**: Binance USDM futures kline websocket; primary price/volume data
- **Inputs**: Binance USDM futures public WebSocket
- **Outputs**: `v2:market:kline:{sym}:{tf}`, candle data for feature pipeline
- **Systemd**: `ai-bot-v2-binance-kline-wss-loop.service`
- **Safe to run manually**: YES (read-only; uses public WebSocket)
- **Command**: `python app/cli/v2_binance_kline_wss_loop.py`
- **Expected output**: Streaming candle updates; TTL < 120s per key
- **Failure modes**: WebSocket disconnection → auto-reconnect; connection failure → keys go stale

### `v2_liquidation_wss_loop.py`
- **Purpose**: Binance forceOrder WebSocket; captures liquidation events
- **Inputs**: Binance liquidation stream (public)
- **Outputs**: `v2:liq:events:stream`
- **Systemd**: `ai-bot-v2-liquidation-wss-paper-shadow.service`
- **Safe to run manually**: YES (read-only)
- **Command**: `python app/cli/v2_liquidation_wss_loop.py`
- **Expected output**: Liquidation events streamed in real-time

### `v2_liquidation_levels_engine.py`
- **Purpose**: Computes estimated liquidation price levels from recent events
- **Inputs**: `v2:liq:events:stream`, mark prices
- **Outputs**: `v2:liq:levels:{sym}`
- **Systemd**: `ai-bot-v2-liquidation-levels-engine.service`
- **Safe to run manually**: YES
- **Command**: `python app/cli/v2_liquidation_levels_engine.py`

### `v2_coinapi_wsds_loop.py`
- **Purpose**: CoinAPI WebSocket data stream; supplemental OHLCV
- **Inputs**: CoinAPI WebSocket (COINAPI_KEY required)
- **Outputs**: `v2:market:coinapi:ohlcv:{sym}:{tf}`
- **Systemd**: `ai-bot-v2-coinapi-wsds-loop.service`
- **Safe to run manually**: YES if COINAPI_KEY is set
- **Failure modes**: If COINAPI_KEY missing, service exits; falls back to REST

### `v2_coinapi_rest_ingestor_worker.py`
- **Purpose**: CoinAPI REST fallback for OHLCV data
- **Inputs**: CoinAPI REST API (COINAPI_KEY)
- **Outputs**: `v2:market:coinapi:rest:{sym}:{tf}`
- **Systemd**: `ai-bot-v2-coinapi-rest-fallback-loop.service`
- **Safe to run manually**: YES if COINAPI_KEY is set

### `v2_kucoin_ingestor_worker.py`
- **Purpose**: KuCoin public REST; cross-exchange price enrichment
- **Inputs**: KuCoin public REST (no credentials)
- **Outputs**: `v2:features:kucoin:{sym}:{tf}`
- **Systemd**: `ai-bot-v2-kucoin-public-rest-loop.service`
- **Safe to run manually**: YES (public API)
- **Command**: `python app/cli/v2_kucoin_ingestor_worker.py`

### `v2_coinank_and_liquidation_bridge.py`
- **Purpose**: CoinAnk bridge; funding rate, OI, long/short ratio
- **Inputs**: CoinAnk API (COINANK_KEY required)
- **Outputs**: `v2:altdata:coinank:{sym}`, `v2:altdata:coinank:global`
- **Systemd**: `ai-bot-v2-coinank-live-direct.service`
- **Safe to run manually**: YES if COINANK_KEY is set

### `v2_aicoin_whale_intel_free_tier.py`
- **Purpose**: AICoin whale wall order book data
- **Inputs**: AICoin API (5 credentials MISSING: AICOIN_ACCESS_KEY_ID, AICOIN_ACCESS_SECRET, AICOIN_API_KEY, AICOIN_API_SECRET, AICOIN_API_BASE_URL)
- **Outputs**: `v2:altdata:aicoin:symbol:{sym}`
- **Systemd**: `ai-bot-v2-aicoin-whale-intel-loop.service`
- **Safe to run manually**: NO — will fail with credential error
- **Failure modes**: CREDENTIAL_BLOCKED; all 5 env vars absent
- **Action needed**: Set 5 AICoin env vars to restore whale wall data

### `v2_lunarcrush_altdata_ingestor.py`
- **Purpose**: LunarCrush social sentiment data
- **Inputs**: LunarCrush API (LUNARCRUSH_KEY)
- **Outputs**: `v2:altdata:lunarcrush:{sym}`
- **Systemd**: `ai-bot-v2-lunarcrush-altdata-loop.service`
- **Safe to run manually**: YES if LUNARCRUSH_KEY is set

### `v2_nansen_altdata_ingestor.py`
- **Purpose**: Nansen on-chain analytics
- **Inputs**: Nansen API (NANSEN_KEY)
- **Outputs**: `v2:altdata:nansen:{sym}`
- **Systemd**: `ai-bot-v2-nansen-altdata-loop.service`
- **Safe to run manually**: YES if NANSEN_KEY is set

### `v2_public_intel_free_tier.py`
- **Purpose**: Public data sources: Fear & Greed Index, CoinGecko, CoinGlass
- **Inputs**: Public APIs (no credentials)
- **Outputs**: `v2:altdata:public_intel:global`
- **Systemd**: `ai-bot-v2-public-intel-free-tier-loop.service`
- **Safe to run manually**: YES

### `v2_arkham_presence_only_worker.py`
- **Purpose**: Arkham on-chain presence detection (stub/enrichment)
- **Inputs**: Arkham presence endpoint
- **Outputs**: `v2:alt_data:arkham:presence`
- **Systemd**: `ai-bot-v2-arkham-presence-loop.service`
- **Safe to run manually**: YES

### `v2_dynamic_symbol_discovery_free_tier.py`
- **Purpose**: Discovers tradeable symbols from Binance exchange info
- **Inputs**: Binance exchange info REST
- **Outputs**: `v2:altdata:symbol_score:{sym}`, symbol universe
- **Systemd**: `ai-bot-v2-dynamic-symbol-discovery-loop.service`
- **Safe to run manually**: YES

### `v2_market_ingestor.py`
- **Purpose**: General market data ingestor (OHLCV aggregation)
- **Inputs**: Multiple market data sources
- **Outputs**: Aggregated market data keys
- **Systemd**: Listed in manifest
- **Safe to run manually**: YES

### `v2_binance_kline_rest_backfill.py`
- **Purpose**: REST backfill for historical Binance candles (one-shot)
- **Inputs**: Binance REST klines
- **Outputs**: Candle data in Redis for feature pipeline bootstrap
- **Safe to run manually**: YES — one-shot read operation
- **Command**: `python app/cli/v2_binance_kline_rest_backfill.py`
- **Expected output**: "Backfill complete for N symbols"

### `v2_binance_public_metadata_ingestor.py`
- **Purpose**: Exchange metadata: tick sizes, lot sizes, filters
- **Inputs**: Binance exchange info REST
- **Outputs**: Exchange filter constraints
- **Safe to run manually**: YES

---

## Category C — Feature Engineering

### `v2_full_talib_ta_loop.py`
- **Purpose**: TA-Lib technical indicator computation loop
- **Inputs**: Candle data from Redis
- **Outputs**: `v2:features:ta_full:{sym}:{tf}`
- **Systemd**: `ai-bot-v2-full-talib-ta-loop.service`
- **Safe to run manually**: NO — singleton loop
- **Failure modes**: If candles are stale, TA values are stale

### `v2_feature_snapshot_builder.py`
- **Purpose**: Builds immutable hashed feature snapshots for trainer
- **Inputs**: `v2:features:latest:{sym}:{tf}`
- **Outputs**: `v2:features:snapshot:v2_fsnap_{hash}`
- **Systemd**: `ai-bot-v2-feature-snapshot-builder.service`
- **Safe to run manually**: NO — singleton
- **Expected output**: ~290k+ snapshots in Redis

### `v2_feature_pipeline_native.py`
- **Purpose**: One-shot feature pipeline run (vs loop variant)
- **Safe to run manually**: YES — single pass
- **Command**: `python app/cli/v2_feature_pipeline_native.py --symbol BTCUSDT --tf 1h`
- **Expected output**: Feature vector written to Redis for specified symbol/tf

### `v2_feature_pipeline_and_ta_worker.py`
- **Purpose**: Combined feature + TA worker
- **Safe to run manually**: YES (standalone)

### `v2_feature_intelligence_worker.py`
- **Purpose**: Feature quality analysis and intelligence
- **Safe to run manually**: YES (read-only)

### `v2_full_talib_ta_loop.py`
- See Category C above.

### `v2_owned_feature_pipeline_runtime.py`
- **Purpose**: Ownership-scoped feature pipeline runtime starter
- **Safe to run manually**: YES for diagnostics

### `v2_closed_candle_resampler.py`
- **Purpose**: Resamples 1m candles to higher timeframes
- **Safe to run manually**: YES

### `v2_native_trainer_dataset_builder.py`
- **Purpose**: Builds training dataset from feature snapshots
- **Inputs**: Feature snapshots from Redis
- **Outputs**: Dataset for trainer initialization
- **Safe to run manually**: YES — read-only build

---

## Category D — Trainer Management

### `v2_native_rl_masa_ppo_cuda_trainer_loop.py`
- **Purpose**: Alternative trainer loop entry point (same as persistent loop)
- **Systemd**: variant
- **Safe to run manually**: NO — will conflict with running trainer

### `v2_trainer_bridge.py`
- **Purpose**: Bridge adapter between V2 and legacy trainer (now deprecated — bridge exit complete)
- **Safe to run manually**: NO — bridge exit is complete; do not re-enable

### `v2_trainer_checkpoint_evidence_publisher.py`
- **Purpose**: Publishes checkpoint metadata to Redis for website display
- **Inputs**: `.local_models/v2_native_rl_masa_ppo/`
- **Outputs**: `v2:trainer:checkpoint:evidence`
- **Systemd**: `ai-bot-v2-trainer-checkpoint-evidence.service`
- **Safe to run manually**: YES
- **Command**: `python app/cli/v2_trainer_checkpoint_evidence_publisher.py`

### `v2_trainer_training_live_loop.py`
- **Purpose**: Training-only loop entry point (no inference)
- **Safe to run manually**: NO — will conflict with GPU resources

### `v2_native_trainer_baseline_evaluator.py`
- **Purpose**: Evaluates trainer baseline before new training epochs
- **Safe to run manually**: YES — read-only evaluation
- **Command**: `python app/cli/v2_native_trainer_baseline_evaluator.py`

### `v2_native_ppo_masa_continuous_training_guard.py`
- **Purpose**: Guards continuous training; enforces training contract
- **Safe to run manually**: YES — guard check only

### `v2_checkpoint_promotion_status.py`
- **Purpose**: Shows checkpoint promotion history and current status
- **Safe to run manually**: YES
- **Command**: `python app/cli/v2_checkpoint_promotion_status.py`
- **Expected output**: Current checkpoint ID, promotion date, model metrics

### `v2_challenger_v2_evidence_collector.py`
- **Purpose**: Collects evidence for challenger v2 checkpoint evaluation
- **Safe to run manually**: YES
- **Command**: `python app/cli/v2_challenger_v2_evidence_collector.py`

### `v2_challenger_v2_reproducible_pipeline.py`
- **Purpose**: Reproducible challenger evaluation pipeline
- **Safe to run manually**: YES

### `v2_model_edge_recovery_champion_challenger.py`
- **Purpose**: Champion/challenger framework for model selection
- **Safe to run manually**: YES — analysis/reporting only

### `v2_native_trainer_dataset_insufficient_evidence_classification_remediation.py`
- **Purpose**: Remediates missing/insufficient training data classification
- **Safe to run manually**: YES — analysis tool

### `v2_out_of_sample_reverify_evidence_producer.py`
- **Purpose**: Produces out-of-sample verification evidence
- **Safe to run manually**: YES

### `v2_native_edge_proof_evaluator.py`
- **Purpose**: Evaluates edge proof for current model
- **Safe to run manually**: YES
- **Command**: `python app/cli/v2_native_edge_proof_evaluator.py`

### `v2_run_real_inference_paper_batch.py`  
- **Purpose**: Runs inference on paper batch (one-shot)
- **Safe to run manually**: YES — read-only inference

### `v2_native_hybrid_trainer_full_function_parity_and_paper_reverify.py`
- **Purpose**: Full parity check between native trainer and paper expectations
- **Safe to run manually**: YES

---

## Category E — Prediction / Signal Publishing

### `v2_all_timeframe_prediction_signal_price_target_publisher.py`
- **Purpose**: Aggregates predictions and publishes to Redis + static files for website
- **Inputs**: All `v2:prediction:{sym}:{tf}` keys
- **Outputs**: `v2:signals:paper`, static JSON files
- **Systemd**: `ai-bot-v2-all-timeframe-prediction-signal-price-target-publisher.service`
- **Safe to run manually**: YES — one-shot publish
- **Command**: `python app/cli/v2_all_timeframe_prediction_signal_price_target_publisher.py`
- **Expected output**: "Published N signals to Redis and N static files"

### `v2_native_trainer_prediction_publisher.py`
- **Purpose**: Trainer inference → prediction publication
- **Inputs**: Latest trainer checkpoint
- **Outputs**: `v2:prediction:{sym}:{tf}`
- **Safe to run manually**: YES — one-shot inference

### `v2_signal_publisher.py`
- **Purpose**: Signal publication from orchestrator decisions
- **Safe to run manually**: YES

### `v2_signal_lineage_worker.py`
- **Purpose**: Maintains lineage chain for each published signal
- **Safe to run manually**: YES

### `v2_prediction_signal_natural_language_explainer.py`
- **Purpose**: Generates natural-language explanation for each prediction/signal
- **Safe to run manually**: YES
- **Command**: `python app/cli/v2_prediction_signal_natural_language_explainer.py --symbol BTCUSDT`

### `v2_prediction_signal_quality_audit.py`
- **Purpose**: Quality audit for current prediction/signal batch
- **Safe to run manually**: YES — reporting only
- **Command**: `python app/cli/v2_prediction_signal_quality_audit.py`
- **Expected output**: Quality score table for each symbol/timeframe

### `v2_run_trusted_prediction_publisher_once.py`
- **Purpose**: One-shot prediction publisher with trusted lineage
- **Safe to run manually**: YES

### `v2_realtime_signal_visibility.py`
- **Purpose**: Shows realtime signal visibility status
- **Safe to run manually**: YES — read-only display

### `v2_paper_decision_lineage_publisher.py`
- **Purpose**: Publishes paper decision lineage for audit trail
- **Safe to run manually**: YES

### `v2_decision_improvement_recommender.py`
- **Purpose**: Recommends improvements to decision quality
- **Safe to run manually**: YES — analysis/reporting only

### `v2_confidence_calibration_and_paper_actionability_improvement.py`
- **Purpose**: Confidence calibration analysis and paper actionability improvement
- **Safe to run manually**: YES — analysis only

---

## Category F — Orchestrator

### `v2_orchestrator_arbitration_worker.py`
- **Purpose**: Worker variant of arbitration loop (vs persistent loop)
- **Safe to run manually**: NO — will conflict with running orchestrator

### `v2_orchestrator_adapter.py`
- **Purpose**: Adapter to wrap orchestrator decisions for downstream consumers
- **Safe to run manually**: YES — read-only adapter

### `v2_owned_orchestrator_runtime.py`
- **Purpose**: Ownership-scoped orchestrator runtime starter
- **Safe to run manually**: YES — diagnostics

---

## Category G — Risk Gateway

### `v2_risk_gateway_runtime_worker.py`
- **Purpose**: Worker variant of risk gateway (vs live loop)
- **Safe to run manually**: NO — singleton constraint

### `v2_exchange_filter_risk_profile_alignment_and_min_order_execution.py`
- **Purpose**: Aligns risk profiles with exchange filter constraints
- **Safe to run manually**: YES — analysis
- **Command**: `python app/cli/v2_exchange_filter_risk_profile_alignment_and_min_order_execution.py`

---

## Category H — Paper Trading / Outcome / Feedback

### `v2_trade_management_paper_worker.py`
- **Purpose**: Worker variant of paper loop (vs persistent loop)
- **Safe to run manually**: NO — will conflict with running paper loop

### `v2_paper_execution_worker.py`
- **Purpose**: Paper execution fill worker
- **Safe to run manually**: NO — managed by paper loop

### `v2_paper_shadow_outcome_observer.py`
- **Purpose**: Observes paper shadow outcomes for analysis
- **Safe to run manually**: YES — read-only
- **Command**: `python app/cli/v2_paper_shadow_outcome_observer.py`

### `v2_paper_shadow_metrics_analyzer.py`
- **Purpose**: Analyzes paper shadow metrics
- **Safe to run manually**: YES
- **Command**: `python app/cli/v2_paper_shadow_metrics_analyzer.py`
- **Expected output**: Win rate, MFE/MAE, hold time distribution

### `v2_paper_shadow_observation.py`
- **Purpose**: Observation report for paper shadow state
- **Safe to run manually**: YES

### `v2_paper_shadow_negative_pnl.py`
- **Purpose**: Analysis of negative PnL patterns in paper shadow
- **Safe to run manually**: YES — very useful for debugging
- **Command**: `python app/cli/v2_paper_shadow_negative_pnl.py`

### `v2_paper_outcome_memory_rebuild.py`
- **Purpose**: Rebuilds outcome memory for trainer feedback
- **Safe to run manually**: YES — WARNING: modifies `v2:trainer:feedback:outcomes`; test in isolated environment first
- **Safety warning**: This may affect trainer feedback key; backup first with `redis-cli get v2:trainer:feedback:outcomes > /tmp/feedback_backup.json`

### `v2_paper_equity_ledger_reconciliation_and_website_truth_repair.py`
- **Purpose**: Reconciles paper equity ledger and repairs website truth payload
- **Safe to run manually**: YES — repair script
- **Command**: `python app/cli/v2_paper_equity_ledger_reconciliation_and_website_truth_repair.py`

### `v2_paper_fill_position_mark_to_market_equity_repair.py`
- **Purpose**: Repairs mark-to-market equity calculation for paper positions
- **Safe to run manually**: YES

### `v2_paper_only_confidence_threshold_trial_and_outcome_monitor.py`
- **Purpose**: Tests different confidence thresholds for paper fills
- **Safe to run manually**: YES — analysis tool

### `v2_paper_path_telemetry_backfill.py`
- **Purpose**: Backfills paper path telemetry for audit chain
- **Safe to run manually**: YES

### `v2_paper_timeframe_churn_governance_audit.py`
- **Purpose**: Audits paper timeframe churn and governance compliance
- **Safe to run manually**: YES

### `v2_paper_fill_gate_live_blocker_burndown_and_controlled_live_enable_ready.py`
- **Purpose**: Paper fill gate analysis and live enable readiness check
- **Safe to run manually**: YES — analysis; does NOT enable live
- **Command**: `python app/cli/v2_paper_fill_gate_live_blocker_burndown_and_controlled_live_enable_ready.py`

### `v2_paper_policy_activation_funding_repair.py`
- **Purpose**: Repairs paper policy activation and funding allocation
- **Safe to run manually**: YES

### `v2_current_paper_fill_gate_acceptance_recovery.py`
- **Purpose**: Recovery for paper fill gate acceptance issues
- **Safe to run manually**: YES

### `v2_paper_only_confidence_threshold_trial_and_outcome_monitor.py`
- See above.

### `run_paper_shadow_edge_report.py`
- **Purpose**: Generates paper shadow edge analysis report
- **Safe to run manually**: YES
- **Command**: `python app/cli/run_paper_shadow_edge_report.py`

### `run_pass2b_paper_shadow_edge_proof.py`
- **Purpose**: Pass 2B paper shadow edge proof generation
- **Safe to run manually**: YES

### `paper_shadow_outcome_observer.py`
- **Purpose**: Earlier version of paper shadow outcome observer
- **Safe to run manually**: YES

---

## Category I — Live Gate / Live Canary (DANGEROUS — DO NOT RUN WITHOUT OPERATOR APPROVAL)

### `v2_live_canary_executor.py`
- **Purpose**: Live canary execution script (DRY RUN only in current state)
- **DANGER**: This script touches the live order submission path
- **Current state**: DRY_RUN_FAKE_ADAPTER_ONLY — no real orders
- **Safe to run manually**: NO — requires operator approval
- **Safety warning**: Verify live_gate:state is blocked before any interaction

### `v2_live_canary_kill_switch.py`
- **Purpose**: Emergency kill switch for live canary
- **Safe to run manually**: YES in emergency
- **Command**: `python app/cli/v2_live_canary_kill_switch.py`
- **Expected output**: "Kill switch activated; submit_enabled=False"

### `v2_live_submit_disarm.py`
- **Purpose**: Disarms live order submission
- **Safe to run manually**: YES in emergency
- **Command**: `python app/cli/v2_live_submit_disarm.py`

### `v2_live_canary_permission_probe.py`
- **Purpose**: Probes API key permissions (read-only probe)
- **Safe to run manually**: YES — read-only probe
- **Command**: `python app/cli/v2_live_canary_permission_probe.py`

### `v2_live_canary_one_order_enablement.py`
- **Purpose**: Enables one-order live canary
- **DANGER**: This enables a real order if live gate is active
- **Safe to run manually**: NO — requires operator approval + live gate active
- **Safety warning**: NEVER run when live gate is blocked_human_only

### `v2_final_live_gate_blocker_burndown_and_operator_enable_packet.py`
- **Purpose**: Generates live gate blocker burndown analysis and operator enable packet
- **Safe to run manually**: YES — analysis only; does NOT enable live
- **Command**: `python app/cli/v2_final_live_gate_blocker_burndown_and_operator_enable_packet.py`

### `run_pass3a_live_canary_safety_dry_run.py`
- **Purpose**: Pass 3A live canary safety dry run
- **Safe to run manually**: YES — dry run only
- **Command**: `python app/cli/run_pass3a_live_canary_safety_dry_run.py`

### `run_pass3b_exact_live_path_dry_run.py`
- **Purpose**: Pass 3B exact live path dry run
- **Safe to run manually**: YES — dry run only

### `run_pass3c_tiny_live_canary_readiness_check.py`
- **Purpose**: Pass 3C tiny live canary readiness check
- **Safe to run manually**: YES — readiness check only

### `v2_cuda_trainer_gpu_trader_binance_live_gate_single_pass.py`
- **Purpose**: Single-pass live gate check combining trainer + trading
- **DANGER**: Contains live path; do not run without operator approval

### `v2_native_cuda_trainer_runtime_signal_burn_in_live_gate.py`
- **Purpose**: Signal burn-in live gate check
- **Safe to run manually**: YES for analysis; verify live gate is blocked first

### `v2_binance_live_order_transport_binding_and_first_hour_monitoring.py`
- **Purpose**: Live order transport binding and monitoring (used for first live order setup)
- **DANGER**: THIS IS THE LIVE ORDER TRANSPORT — DO NOT RUN
- **Safe to run manually**: NO — requires operator approval and live gate enabled
- **Safety warning**: Generates real exchange orders when live gate is active

### `v2_live_order_transport_state_lineage_and_write_guard_repair.py`
- **Purpose**: Repairs live transport write guard state
- **Safe to run manually**: YES — repair to write guard only; does not place orders

### `v2_live_transport_balance_aware_hold_and_first_order_resume.py`
- **Purpose**: Balance-aware hold and order resume for live transport
- **DANGER**: Involves live transport
- **Safe to run manually**: NO — requires operator approval

### `v2_signed_read_recovered_balance_hold_and_first_order_resume.py`
- **Purpose**: Signed read + balance recovery for live order resume
- **DANGER**: Live order path
- **Safe to run manually**: NO

---

## Category J — Monitoring / Status Publishers

### `v2_ingestors_status_publisher.py`
- **Purpose**: Publishes ingestor status to Redis for website display
- **Outputs**: `v2:ingestors:status`
- **Systemd**: `ai-bot-v2-ingestors-status-publisher.service`
- **Safe to run manually**: YES

### `v2_system_observability_status_publisher.py`
- **Purpose**: Publishes system observability status
- **Safe to run manually**: YES

### `v2_log_errors_status_publisher.py`
- **Purpose**: Monitors logs for errors; publishes status
- **Systemd**: `ai-bot-v2-log-errors-status-publisher.service`
- **Safe to run manually**: YES

### `v2_technical_analysis_status_publisher.py`
- **Purpose**: Publishes TA pipeline status
- **Systemd**: `ai-bot-v2-technical-analysis-status-publisher.service`
- **Safe to run manually**: YES

### `v2_liquidation_runtime_status_publisher.py`
- **Purpose**: Publishes liquidation engine status
- **Systemd**: `ai-bot-v2-liquidation-runtime-status-publisher.service`
- **Safe to run manually**: YES

### `v2_coinank_direct_runtime_status_publisher.py`
- **Purpose**: Publishes CoinAnk ingestor runtime status
- **Systemd**: `ai-bot-v2-coinank-direct-status-publisher.service`
- **Safe to run manually**: YES

### `v2_liquidation_bridge_status_publisher.py`
- **Purpose**: Publishes liquidation bridge status
- **Safe to run manually**: YES

### `v2_liquidation_observation_aggregator_status.py`
- **Purpose**: Aggregates liquidation observation status
- **Safe to run manually**: YES

### `v2_realtime_runtime_truth_publisher.py`
- **Purpose**: Publishes real-time runtime truth to static files + Redis
- **Safe to run manually**: YES
- **Command**: `python app/cli/v2_realtime_runtime_truth_publisher.py`

### `v2_operator_runtime_truth_publisher.py`
- **Purpose**: Publishes operator-level runtime truth
- **Safe to run manually**: YES

### `v2_operator_review_publisher.py`
- **Purpose**: Generates operator review payload
- **Safe to run manually**: YES

### `v2_opportunity_tracker_publisher.py`
- **Purpose**: Publishes opportunity tracker data
- **Safe to run manually**: YES

### `v2_portfolio_state_publisher.py`
- **Purpose**: Publishes portfolio state for website display
- **Safe to run manually**: YES

### `v2_pipeline_control_status_publisher.py`
- **Purpose**: Publishes pipeline control status
- **Safe to run manually**: YES

### `v2_derivatives_runtime_payload_publisher.py`
- **Purpose**: Publishes derivatives data (funding, OI) for website
- **Safe to run manually**: YES

### `v2_market_chart_payload_publisher.py`
- **Purpose**: Publishes market chart payloads to static files
- **Systemd**: `ai-bot-v2-market-chart-payload-publisher.service`
- **Safe to run manually**: YES

### `v2_professional_market_chart_payload_publisher.py`
- **Purpose**: Publishes professional-grade market chart payloads
- **Systemd**: `ai-bot-v2-professional-market-chart-payload-publisher.service`
- **Safe to run manually**: YES

### `v2_misc_state_keys_publisher.py`
- **Purpose**: Publishes miscellaneous state keys
- **Safe to run manually**: YES

### `v2_website_redis_bridge_status.py`
- **Purpose**: Status of website Redis bridge
- **Safe to run manually**: YES

### `v2_continuous_hourly_monitor.py`
- **Purpose**: Continuous hourly monitoring snapshot
- **Systemd**: `ai-bot-v2-continuous-hourly-monitor.service`
- **Safe to run manually**: YES — one-shot snapshot
- **Command**: `python app/cli/v2_continuous_hourly_monitor.py`

### `v2_script_monitor.py`
- **Purpose**: Monitors all registered scripts for health
- **Safe to run manually**: YES — diagnostic

### `v2_one_hour_trainer_risk_orchestrator_data_website_monitor.py`
- **Purpose**: 1-hour system monitoring for all core services
- **Safe to run manually**: YES
- **Command**: `python app/cli/v2_one_hour_trainer_risk_orchestrator_data_website_monitor.py`

### `v2_full_observation_builder_status.py`
- **Purpose**: Shows full observation builder status (feature completeness)
- **Safe to run manually**: YES

### `v2_full_observation_missing_feature_source_map_status.py`
- **Purpose**: Maps missing feature sources in observation builder
- **Safe to run manually**: YES

### `v2_model_parity_sprint_status.py`
- **Purpose**: Model parity sprint status check
- **Safe to run manually**: YES

### `v2_policy_architecture_shape_contract_status.py`
- **Purpose**: Policy architecture shape contract verification
- **Safe to run manually**: YES

### `v2_website_contracts_status.py`
- **Purpose**: Website contract compliance status
- **Safe to run manually**: YES

### `v2_alternative_data_status.py`
- **Purpose**: Status of all alternative data sources
- **Safe to run manually**: YES
- **Command**: `python app/cli/v2_alternative_data_status.py`

### `v2_account_position_monitor.py`
- **Purpose**: Read-only position monitor (reads exchange positions for verification)
- **Safe to run manually**: YES — read-only

### `v2_monthly_10k_profit_target_monitor.py`
- **Purpose**: Monthly $10k profit target progress monitor
- **Safe to run manually**: YES — analysis/reporting

---

## Category K — Audit / Evidence / Validation

### `v2_audit_2026_06_19_runtime_validator.py`
- **Purpose**: 2026-06-19 runtime validation snapshot
- **Safe to run manually**: YES — validation only

### `v2_runtime_trust_evidence_quarantine.py`
- **Purpose**: Quarantines untrusted runtime evidence
- **Safe to run manually**: YES — analysis tool

### `v2_paper_shadow_outcome_metrics.py`
- **Purpose**: Paper shadow outcome metrics report
- **Safe to run manually**: YES
- **Command**: `python app/cli/v2_paper_shadow_outcome_metrics.py`

### `quarantine_pipeline_trust_stale_records.py`
- **Purpose**: Quarantines stale records from pipeline trust
- **Safe to run manually**: YES — quarantine (read+mark, no delete)

### `verify_pipeline_trust.py`
- **Purpose**: Verifies pipeline trust enforcement
- **Safe to run manually**: YES
- **Command**: `python app/cli/verify_pipeline_trust.py`
- **Expected output**: "enforcement_epoch=pipeline_trust_v3_20260612; PASS"

### `export_pipeline_trust_evidence.py`
- **Purpose**: Exports pipeline trust evidence to files
- **Safe to run manually**: YES
- **Command**: `python app/cli/export_pipeline_trust_evidence.py`

### `non_live_operational_proof.py`
- **Purpose**: Generates operational proof that system is non-live
- **Safe to run manually**: YES — critical verification
- **Command**: `python app/cli/non_live_operational_proof.py`
- **Expected output**: "places_real_order=False; routes_to_live=False; PROOF=PASS"

### `v2_final_live_gate_blocker_burndown_and_operator_enable_packet.py`
- **Purpose**: Full live gate blocker analysis
- **Safe to run manually**: YES

### `run_e2e_verification.py`
- **Purpose**: End-to-end verification suite
- **Safe to run manually**: YES
- **Command**: `python app/cli/run_e2e_verification.py`
- **Expected output**: Green checks for all core subsystems

### `v2_production_equivalence_comparator.py`
- **Purpose**: Compares V2 production with expected equivalence
- **Safe to run manually**: YES

### `v2_out_of_sample_reverify_evidence_producer.py`
- **Purpose**: Produces out-of-sample reverification evidence
- **Safe to run manually**: YES

### `run_recorded_state_verification.py`
- **Purpose**: Verifies recorded runtime state
- **Safe to run manually**: YES

### `v2_native_cuda_trainer_edge_calibration_outcome_burn_in.py`
- **Purpose**: Edge calibration and outcome burn-in for native trainer
- **Safe to run manually**: YES — analysis

### `v2_runtime_alpha_remediated_1h_soak_proof_window_and_symbol_scope_reverify.py`
- **Purpose**: 1h soak proof window and symbol scope reverification
- **Safe to run manually**: YES

### `zero_miss_atlas_builder.py`
- **Purpose**: Builds zero-miss coverage atlas for audit completeness
- **Safe to run manually**: YES
- **Command**: `python app/cli/zero_miss_atlas_builder.py`

### `zero_miss_dependency_closure.py`
- **Purpose**: Dependency closure check for zero-miss coverage
- **Safe to run manually**: YES

### `legacy_dependency_closure.py`
- **Purpose**: Legacy dependency closure analysis
- **Safe to run manually**: YES — read-only analysis

### `legacy_v2_function_gap_detector.py`
- **Purpose**: Detects function gaps between legacy and V2 implementations
- **Safe to run manually**: YES

### `legacy_v2_decision_comparator.py`
- **Purpose**: Compares legacy and V2 decision outputs
- **Safe to run manually**: YES

### `v2_expected_move_model_review.py`
- **Purpose**: Reviews expected move model accuracy
- **Safe to run manually**: YES

---

## Category L — Startup / Boot / Recovery

### `v2ctl.py`
- **Purpose**: V2 control CLI — start/stop/status commands
- **Safe to run manually**: YES — status commands; be careful with start/stop
- **Command**: `python app/cli/v2ctl.py status`
- **Expected output**: Status table for all V2 services

### `v2_owned_non_live_startup.py`
- **Purpose**: Non-live safe startup sequence
- **Safe to run manually**: YES — starts non-live services only
- **Command**: `python app/cli/v2_owned_non_live_startup.py`

### `v2_owned_ingestors_runtime.py`
- **Purpose**: Starts ingestors runtime group
- **Safe to run manually**: YES — non-live ingestors

### `v2_owned_monitoring_runtime.py`
- **Purpose**: Starts monitoring runtime group
- **Safe to run manually**: YES

### `v2_owned_paper_trade_management_runtime.py`
- **Purpose**: Starts paper trade management runtime
- **Safe to run manually**: YES — paper only

### `v2_owned_trainer_runtime.py`
- **Purpose**: Starts trainer runtime group
- **Safe to run manually**: YES — uses GPU exclusively; do not run if trainer already running

### `v2_full_paper_only_startup_manifest_runtime.py`
- **Purpose**: Full paper-only startup manifest runner
- **Safe to run manually**: YES

### `v2_full_paper_only_startup_manifest_role_coverage_remediation.py`
- **Purpose**: Remediates startup manifest role coverage
- **Safe to run manually**: YES

---

## Category M — Website / Data Alignment

### `production_website_full_rebuild.py`
- **Purpose**: Full website frontend rebuild trigger
- **Safe to run manually**: YES — triggers npm build
- **Command**: `python app/cli/production_website_full_rebuild.py`

### `production_website_public_route_rebuild.py`
- **Purpose**: Rebuilds public routes for website
- **Safe to run manually**: YES

### `frontend_truth_payload_builder.py`
- **Purpose**: Builds frontend truth payload files
- **Safe to run manually**: YES

### `public_payload_freshness_guard.py`
- **Purpose**: Guards freshness of public payload files
- **Safe to run manually**: YES — read-only guard check

### `symbol_universe_public_payload.py`
- **Purpose**: Builds symbol universe public payload
- **Safe to run manually**: YES

### `v2_website_data_alignment_and_control_plane.py`
- **Purpose**: Website data alignment and control plane
- **Safe to run manually**: YES

### `v2_website_data_alignment_primary_artifact_integration_remediation.py`
- **Purpose**: Remediates website data alignment artifacts
- **Safe to run manually**: YES

### `v2_website_data_alignment_route_coverage_and_bridge_label_remediation.py`
- **Purpose**: Route coverage and bridge label remediation
- **Safe to run manually**: YES

### `v2_production_payload_freshness_refresher.py`
- **Purpose**: Refreshes production payload freshness
- **Safe to run manually**: YES

### `v2_top10_binance_dashboard_feed.py`
- **Purpose**: Top-10 Binance symbols dashboard feed
- **Safe to run manually**: YES

### `v2_top10_dashboards_renderer.py`
- **Purpose**: Renders top-10 dashboards
- **Safe to run manually**: YES

### `v2_top10_market_and_altdata_dashboard_contracts.py`
- **Purpose**: Dashboard contracts for top-10 market + altdata
- **Safe to run manually**: YES

### `v2_trade_terminal_runtime_payload_publisher.py`
- **Purpose**: Publishes trade terminal runtime payload
- **Safe to run manually**: YES

---

## Category N — Replay / Backtest

### `v2_backtest_runner.py`
- **Purpose**: Runs historical backtests
- **Safe to run manually**: YES — simulation only
- **Command**: `python app/cli/v2_backtest_runner.py --strategy challenger_v2 --period 30d`

### `v2_replay_worker.py`
- **Purpose**: Replays historical scenarios for validation
- **Safe to run manually**: YES

### `historical_30d_replay_and_paper_proof.py`
- **Purpose**: 30-day historical replay with paper proof generation
- **Safe to run manually**: YES — no live orders
- **Command**: `python app/cli/historical_30d_replay_and_paper_proof.py`

### `v2_trusted_replay_bootstrap.py`
- **Purpose**: Bootstrap replay with trusted data
- **Safe to run manually**: YES

### `v2_state_replay_debugger.py`
- **Purpose**: State replay debugger for root cause analysis
- **Safe to run manually**: YES

### `v2_post_hoc_replay_outcome_miner.py`
- **Purpose**: Post-hoc outcome mining from replay data
- **Safe to run manually**: YES

### `v2_accelerated_closed_candle_replay_evidence.py`
- **Purpose**: Accelerated closed candle replay evidence
- **Safe to run manually**: YES

### `v2_major_move_replay_future_window_completion.py`
- **Purpose**: Replays major moves for future window completion
- **Safe to run manually**: YES

---

## Category O — Miscellaneous / Utility

### `v2_config_admin_manager.py`
- **Purpose**: Config admin manager (versioned config updates)
- **Safe to run manually**: YES — versioned; mutations require approval
- **Command**: `python app/cli/v2_config_admin_manager.py --read`

### `v2_adaptive_capital_productivity_status.py`
- **Purpose**: 13,098-line comprehensive capital productivity analysis
- **Safe to run manually**: YES — read-only analysis
- **Command**: `python app/cli/v2_adaptive_capital_productivity_status.py`
- **Expected output**: Capital efficiency metrics, leverage utilization report

### `v2_adaptive_allocation_trade_lifecycle_24h_paper_soak.py`
- **Purpose**: 24h paper soak with adaptive allocation lifecycle
- **Safe to run manually**: YES — paper simulation

### `v2_24h_parallel_recovery_war_room.py`
- **Purpose**: 24h parallel recovery war room — orchestrates multiple recovery tasks
- **Safe to run manually**: YES — analysis/recovery coordination

### `v2_high_throughput_ai_war_room_scheduler.py`
- **Purpose**: High-throughput AI war room scheduler
- **Safe to run manually**: YES — scheduling/analysis

### `v2_execution_ledger_worker.py`
- **Purpose**: Execution ledger maintenance worker
- **Safe to run manually**: YES

### `v2_position_history_persistent_tracker.py`
- **Purpose**: Persists position history
- **Safe to run manually**: YES

### `v2_position_price_tracking_recorder.py`
- **Purpose**: Records position price tracking
- **Safe to run manually**: YES

### `v2_report_center_indexer.py`
- **Purpose**: Indexes reports for report center
- **Safe to run manually**: YES

### `v2_worker_inventory.py`
- **Purpose**: Generates worker inventory
- **Safe to run manually**: YES
- **Command**: `python app/cli/v2_worker_inventory.py`
- **Expected output**: Full worker status table

### `v2_model_state_ai_predictions_signals_runtime_truth_semantic_repair.py`
- **Purpose**: Repairs model state, prediction, signal, and runtime truth semantic issues
- **Safe to run manually**: YES — repair tool

### `v2_market_state_integrity_paper_equity_and_website_realtime_full_repair.py`
- **Purpose**: Full market state and website repair
- **Safe to run manually**: YES — repair

### `v2_market_state_integrity_rejection_burndown_and_paper_training_recovery.py`
- **Purpose**: Market state rejection burndown and paper training recovery
- **Safe to run manually**: YES

### `v2_market_state_brain_worker.py`
- **Purpose**: Market state brain computation worker
- **Safe to run manually**: YES

### `v2_rl_core_inference_loop.py`
- **Purpose**: RL core sidecar inference loop (advisory only)
- **Systemd**: `ai-bot-v2-rl-core-inference-loop.service`
- **Safe to run manually**: NO — singleton; advisory only

### `v2_rl_core_worker.py`
- **Purpose**: RL core worker variant
- **Safe to run manually**: NO — will conflict

### `v2_major_move_false_negative_remediation.py`
- **Purpose**: Remediates false negatives in major move detection
- **Safe to run manually**: YES — analysis/remediation

### `v2_dynamic_93_edge_recovery_signal_quality_burndown.py`
- **Purpose**: Dynamic 93-signal edge recovery and quality burndown
- **Safe to run manually**: YES

### `v2_dynamic_93_symbol_runtime_burn_in_edge_and_website_sync.py`
- **Purpose**: 93-symbol runtime burn-in, edge analysis, and website sync
- **Safe to run manually**: YES

### `v2_ai_throughput_acceleration.py`
- **Purpose**: AI throughput acceleration analysis
- **Safe to run manually**: YES

### `v2_ai_throughput_acceleration_cli_command_remediation.py`
- **Purpose**: CLI command remediation for AI throughput acceleration
- **Safe to run manually**: YES

### `v2_alt_data_symbol_candidate_publisher.py`
- **Purpose**: Publishes alt data symbol candidates
- **Systemd**: `ai-bot-v2-alt-data-candidate-publisher-loop.service`
- **Safe to run manually**: YES

### `v2_alt_data_symbol_universe_scoring.py`
- **Purpose**: Scores symbols from alt data sources
- **Systemd**: `ai-bot-v2-alt-data-symbol-scoring-loop.service`
- **Safe to run manually**: YES

### `v2_symbol_universe_diff_buffer.py`
- **Purpose**: Buffers symbol universe diffs
- **Safe to run manually**: YES

### `v2_native_dynamic_ingestor_runtime_and_symbol_expansion.py`
- **Purpose**: Dynamic ingestor runtime + symbol expansion
- **Safe to run manually**: YES

### `v2_native_dynamic_runtime_and_trainer_bridge_exit_execution.py`
- **Purpose**: Bridge exit execution (historical — completed)
- **Safe to run manually**: YES — historical; bridge exit already complete

### `v2_legacy_ingestor_adapter.py`
- **Purpose**: Legacy ingestor adapter for compatibility
- **Safe to run manually**: YES — read-only adapter

### `v2_legacy_log_intelligence_observer.py`
- **Purpose**: Observes legacy bot logs (read-only)
- **Safe to run manually**: YES — read-only

### `legacy_runtime_readonly_observer.py`
- **Purpose**: Read-only observer of legacy runtime state
- **Safe to run manually**: YES

### `legacy_signal_outcome_observer.py`
- **Purpose**: Observes legacy signal outcomes (read-only)
- **Safe to run manually**: YES

### `live_observer_bridge.py`
- **Purpose**: Read-only observer bridge to live state
- **Safe to run manually**: YES — read-only

### `readonly_market_exchange_data_plane.py`
- **Purpose**: Read-only market + exchange data plane
- **Safe to run manually**: YES — strictly read-only

### `v2_github_only_credential_purge.py`
- **Purpose**: Purges credentials from GitHub-visible paths
- **Safe to run manually**: YES — credential cleanup (idempotent)

### `v2_github_visible_credential_purge_remediation.py`
- **Purpose**: Remediates GitHub-visible credential issues
- **Safe to run manually**: YES

### `external_manual_position_quarantine.py`
- **Purpose**: Quarantines manually-entered external positions
- **Safe to run manually**: YES — quarantine (protective action)

### `account_permission_and_soak.py`
- **Purpose**: Account permission validation and soak test
- **Safe to run manually**: YES — read-only permission check

### `account_permission_contract_checker.py`
- **Purpose**: Checks account permission contracts
- **Safe to run manually**: YES

### `decision_quality_scoreboard.py`
- **Purpose**: Decision quality scoreboard display
- **Safe to run manually**: YES
- **Command**: `python app/cli/decision_quality_scoreboard.py`

### `env_dependency_parity.py`
- **Purpose**: Checks environment dependency parity
- **Safe to run manually**: YES
- **Command**: `python app/cli/env_dependency_parity.py`

### `v2_native_ingestors_live_loop.py`
- **Purpose**: Native ingestors live loop (all ingestors in one process)
- **Safe to run manually**: NO — will conflict with running ingestors

### `v2_native_ingestors_worker.py`
- **Purpose**: Native ingestors worker variant
- **Safe to run manually**: NO — singleton

### `v2_legacy_production_service_parity_repair.py`
- **Purpose**: Repairs legacy-V2 production service parity
- **Safe to run manually**: YES

### `v2_legacy_startup_manifest_parity_and_bridge_exit.py`
- **Purpose**: Legacy startup manifest parity check + bridge exit status
- **Safe to run manually**: YES

### `tonight_live_like_paper_shadow.py`
- **Purpose**: Full live-like paper shadow simulation for tonight
- **Safe to run manually**: YES — paper simulation

### `v2_runtime_alpha_remediated_adaptive_lifecycle_24h_paper_soak.py`
- **Purpose**: 24h adaptive lifecycle soak in paper mode
- **Safe to run manually**: YES

### `v2_runtime_alpha_remediated_dynamic_strategy_leverage_margin.py`
- **Purpose**: Dynamic strategy leverage/margin analysis in remediated alpha
- **Safe to run manually**: YES

### `v2_run_runtime_alpha_decision_chain_remediation.py`
- **Purpose**: Remediates decision chain in runtime alpha
- **Safe to run manually**: YES

### `v2_production_replacement_soak_observer.py`
- **Purpose**: Observes production replacement soak
- **Safe to run manually**: YES

### `v2_startup_parity_first_batch_execution.py`
- **Purpose**: First batch execution parity check
- **Safe to run manually**: YES

### `v2_unified_feature_parity_and_backtest_edge_completion.py`
- **Purpose**: Unified feature parity + backtest edge completion
- **Safe to run manually**: YES

### `v2_native_runtime_bridge_exit_and_dynamic_symbol_migration.py`
- **Purpose**: Bridge exit + symbol migration (historical — completed)
- **Safe to run manually**: YES — historical

### `v2_cuda_trainer_false_negative_reduction_actionability.py`
- **Purpose**: CUDA trainer false negative reduction and actionability analysis
- **Safe to run manually**: YES

### `run_real_inference_paper_batch.py`
- **Purpose**: Runs real inference on paper batch
- **Safe to run manually**: YES — inference only

### `v2_paper_strategy_edge_tightening.py`
- **Purpose**: Paper strategy edge tightening analysis
- **Safe to run manually**: YES

### `paper_strategy_edge_tightening.py`
- Same as above.

### `v2_native_ppo_masa_continuous_training_guard.py`
- See Category D above.

### `v2_market_state_brain_worker.py`
- See above.

### `v2_full_paper_only_startup_manifest_role_coverage_remediation.py`
- See Category L above.

---

## Unclassified / Low Activity

### `v2_default_blocked_execution_adapter_stub.py`
- **Purpose**: Default blocked execution adapter stub — placeholder for exchange adapter
- **Safe to run manually**: YES — stub only

### `v2_binance_usdm_adapter_stub.py`
- **Purpose**: Binance USDM adapter stub — placeholder for exchange adapter
- **Safe to run manually**: YES — stub only

### `v2_exchange_filter_risk_profile_alignment_and_min_order_execution.py`
- See Category G above.

### `v2_legacy_log_intelligence_observer.py`
- See above.

---

*End of Script Reference. Total documented: 231 scripts.*
