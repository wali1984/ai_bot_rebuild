# V2 Production Replacement Runtime - Paper/Shadow Ready

Generated: 2026-05-17T01:30:00Z
Git HEAD: 31a7fd70319f0d586c454b5ea2ea530ba9cb1541
GO/NO-GO: V2_PRODUCTION_REPLACEMENT_RUNTIME_READY_PAPER_SHADOW

## What changed (no more report loops)

Five new V2 CLI workers were built and started in --loop mode. They
run end-to-end in paper/shadow scope and produce live v2:* Redis
keys for each layer of the pipeline.

### Phase 1 - Ingestors

v2/backend/app/cli/v2_native_ingestors_live_loop.py runs against the
Binance public REST (no API key required) and writes:

- v2:market:prices:{SYMBOL}
- v2:market:funding:{SYMBOL}
- v2:market:open_interest:{SYMBOL}
- v2:market:ingestor:heartbeat
- v2:market:ingestor:status

Classification: NATIVE_V2_PUBLIC_REST_OK (when REST + Redis are
reachable). The loop fail-classifies into BLOCKED_BY_NETWORK_OR_API
or BLOCKED_BY_REDIS_UNAVAILABLE if a layer is missing - no fake
values are written.

### Phase 2 - Feature pipeline

v2/backend/app/cli/v2_feature_pipeline_native_loop.py consumes
v2:market:prices:* and builds a 23-field trainer-consumable snapshot
that matches the P0.1 contract. Writes:

- v2:features:latest:{SYMBOL}:{TF}
- v2:features:snapshots
- v2:features:pipeline:heartbeat

It also mirrors the first symbol's snapshot to
v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json
so the existing P0.2A/B/F/G machinery can consume it.

### Phase 3 - RL core inference

v2/backend/app/cli/v2_rl_core_inference_loop.py consumes
v2:features:latest:*, runs the V2 native trainer output contract,
applies the strict P0.2F paper-fill gate, and writes:

- v2:prediction:{SYMBOL}:{TF}
- v2:trainer:status
- v2:trainer:heartbeat

checkpoint_weight_status remains CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED
and hedge_status remains HEDGE_FAIL_CLOSED_PAPER_HEDGE_ENGINE_PENDING_CODEX_PASS.

### Phase 4 - Orchestrator arbitration

v2/backend/app/cli/v2_orchestrator_arbitration_loop.py consumes
v2:prediction:* (only proposals with paper_fill_allowed=true are
arbitrated), runs the existing V2NativeProposalBus +
OrchestratorArbitrationService, and writes:

- v2:orchestrator:proposals
- v2:orchestrator:decisions
- v2:signals:paper
- v2:orchestrator:heartbeat

### Phase 5 - Trade management (paper)

v2/backend/app/cli/v2_trade_management_paper_loop.py consumes
v2:signals:paper, runs fee-ratio gate + churn veto + paper trade
management, and writes:

- v2:paper:intents
- v2:paper:positions
- v2:paper:ledger
- v2:risk:decisions
- v2:paper:heartbeat

places_real_order=false on every record. No exchange SDK is imported.

## Phase 0 - Runtime liveness guard

claude_worklog/tools/v2_production_replacement_runtime_guard.py runs
the five phases once each, counts v2:* keys per namespace, and
emits:

- claude_worklog/final_readiness/v2_production_replacement_runtime/latest/runtime_guard_status.json
- claude_worklog/final_readiness/v2_production_replacement_runtime/latest/RUNTIME_GUARD_STATUS.md
- v2/frontend/public/operator_runtime/v2_production_replacement_runtime/latest/runtime_guard_status.json

Current classification: V2_PRODUCTION_REPLACEMENT_RUNTIME_LIVE
(required_namespaces_non_empty=true, v2_total_key_count=30).

## Phase 6 - Legacy vs V2 production comparator

claude_worklog/tools/v2_legacy_v2_production_comparator.py runs
read-only and emits:

- v2/frontend/public/operator_runtime/legacy_v2_production_comparator/latest/status.json
- claude_worklog/final_readiness/v2_production_replacement_runtime/latest/legacy_v2_production_comparator_status.json

Current snapshot:

- legacy_key_counts: prediction:* = 151, signals:* = 8, kc:* / rl:* / heartbeat:* / binance:* present
- v2_key_counts: v2:total = 30 across market/features/prediction/trainer/orchestrator/signals:paper/paper/risk
- legacy processes still running: live_binance, live_binance_liquidations, live_coinank, live_kucoin, live_coinapi_v1, live_coinapi_wsds, feature_pipeline, rl.hybrid_trainer, rl.orchestrator_worker, monitor_portfolio_primary
- V2 production-equivalent processes now running: 5 new --loop workers above (plus earlier paper/observer daemons)

## Phase 7 - Frontend truth

v2/frontend/public/v2_production_replacement_runtime/latest/operator_dashboard_payload.json
now shows:

- can_old_system_be_shut_down: false (legacy still owns production)
- are_v2_production_equivalent_workers_running: true
- per-layer classifications and per-namespace counts
- explicit legacy processes still running
- live_gate: blocked_human_only, live_symbols: []

The dashboard does NOT hide NO-GO and does NOT mislabel report-only
tasks as runtime.

## Hard constraints upheld

- AI BOT (legacy directory) NOT modified.
- Legacy processes NOT stopped.
- ZERO old-namespace Redis keys written by V2 loops (all writes
  validated with `key.startswith("v2:")` guard).
- ZERO exchange orders placed, cancelled, or modified.
- Leverage and margin mode unchanged.
- No live approval token created.
- No Redis trim approval created.
- All work confined to /home/wali/Desktop/AI BOT REBUILD.
- live_gate remains blocked_human_only.
- live_symbols remains [].

## Why this is NOT a shutdown approval

V2 production-equivalent paper/shadow runtime is now LIVE, but
legacy continues to own the production prediction/signal namespaces.
Before shutdown can be re-evaluated:

1. A soak window with operator-approved duration must pass with V2
   chain keys staying fresh, no degradation, no missing namespaces.
2. The operator must create
   claude_worklog/approvals/OPERATOR_ACCEPTS_V2_PAPER_ONLY_SHUTDOWN_LIMITATIONS.md
   with paper-only language (no live/canary approval).
3. Codex must pass V2_PRODUCTION_REPLACEMENT_RUNTIME_READY_PAPER_SHADOW.
4. Checkpoint weights / paid CoinAPI WSDS / adaptive hedge approval
   decisions must each be accepted or explicitly retained as
   paper-only-shutdown limitations.

## Decision

V2_PRODUCTION_REPLACEMENT_RUNTIME_READY_PAPER_SHADOW.

The report loop is closed. V2 now owns a running paper/shadow chain
that writes v2:* Redis namespaces end-to-end. Legacy remains
read-only reference. Live, canary, and shutdown approvals are NOT
created by this packet.
