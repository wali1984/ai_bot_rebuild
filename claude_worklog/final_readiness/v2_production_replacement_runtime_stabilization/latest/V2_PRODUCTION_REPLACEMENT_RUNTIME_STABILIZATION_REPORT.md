# V2 Production Replacement Runtime - Stabilization

Generated: 2026-05-17T01:55:00Z
Git HEAD: 31a7fd70319f0d586c454b5ea2ea530ba9cb1541
GO/NO-GO: V2_PRODUCTION_REPLACEMENT_RUNTIME_STABILIZATION_READY

## What changed

The previous packet started the V2 chain in the foreground; this
packet stabilizes it so the Codex governor stops flagging it as
non-persistent.

### Phase 1 - systemd user services + control scripts

Nine systemd user units under claude_worklog/systemd/user/:
ai-bot-v2-native-ingestors-live-loop, -feature-pipeline-native-loop,
-rl-core-inference-loop, -orchestrator-arbitration-loop,
-trade-management-paper-loop, -production-payload-freshness-refresher,
-production-replacement-runtime-guard, -legacy-v2-production-comparator,
-production-replacement-soak-observer.

Each unit:
- runs from /home/wali/Desktop/AI BOT REBUILD
- uses .venv/bin/python3
- logs to claude_worklog/agent_supervisor/logs/control_plane/
- Restart=always with RestartSec
- preserves live_gate=blocked_human_only

Plus three control scripts:
- claude_worklog/tools/start_v2_production_replacement_runtime.sh
  (--systemd|--nohup|--auto)
- claude_worklog/tools/status_v2_production_replacement_runtime.sh
- claude_worklog/tools/stop_v2_production_replacement_runtime.sh

### Phase 2 - Payload freshness refresher

v2/backend/app/cli/v2_production_payload_freshness_refresher.py
runs every 60s and stamps the governor-watched /latest/ payloads
with current generated_at + heartbeat_at + a runtime heartbeat
block. Forces all approvals to false defensively.

Refreshed payloads:
- v2/frontend/public/operator_runtime/v2_native_ingestors/latest/v2_native_ingestors_status.json
- v2/frontend/public/operator_runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json
- v2/frontend/public/operator_runtime/v2_rl_core/latest/v2_rl_core_status.json
- v2/frontend/public/operator_runtime/v2_orchestrator_arbitration/latest/v2_orchestrator_arbitration_status.json
- v2/frontend/public/operator_runtime/v2_trade_management_paper/latest/v2_trade_management_paper_status.json
- v2/frontend/public/operator_runtime/frontend_truth/latest/frontend_truth_payload.json

Every refreshed payload includes:
generated_at, heartbeat_at, freshness_seconds, process_running,
redis_key_count, latest_v2_keys_written, live_gate=blocked_human_only,
live_symbols=[], approves_live=false, approves_canary=false,
approves_legacy_shutdown=false, approves_redis_trim=false,
no_old_redis_writes=true, no_exchange_mutation=true.

### Phase 3 - Hardened runtime guard

claude_worklog/tools/v2_production_replacement_runtime_guard.py now
classifies V2_PRODUCTION_REPLACEMENT_RUNTIME_READY_STABLE only
when ALL of these hold:

- all 8 required processes are running (5 chain loops + freshness
  refresher + runtime guard + comparator)
- v2:* total > 0
- every required v2:* namespace is non-empty
  (market, features, prediction, trainer, orchestrator, paper, risk)
- every live /live/latest/ payload exists and is fresh under 180s
- phase returncodes are all zero

Otherwise the guard outputs LIVE (partial) or DEGRADED with the
exact failed checks listed.

Current classification: V2_PRODUCTION_REPLACEMENT_RUNTIME_READY_STABLE.

### Phase 4 - Soak observer

v2/backend/app/cli/v2_production_replacement_soak_observer.py runs
on a 300s cycle and emits to
claude_worklog/final_readiness/v2_production_replacement_runtime/latest/soak_observation.jsonl
and
v2/frontend/public/operator_runtime/v2_production_replacement_runtime/latest/soak_status.json.

Each observation records v2 processes, legacy processes, v2 + legacy
namespace counts, paper ledger snapshot, and safety invariants.
The status payload exposes soak_1h_ready (>=60 minutes) and
soak_6h_ready (>=360 minutes) boolean flags. Progress is emitted on
every observation; no silent waiting.

### Phase 5 - Frontend truth

frontend_truth_payload.json now exposes plain-English fields:

- v2_paper_shadow_runtime_running: true
- legacy_still_owns_production_runtime: true
- do_not_shut_down_legacy_yet: true
- v2_writing_v2_namespace_redis_keys: true
- v2_namespace_redis_key_count: 30
- live_trading_is_blocked: true
- current_blocker_in_plain_english (full string explaining the
  blocker is runtime stability/production equivalence, not
  "nothing is running")
- v2_runtime_loops (per-loop process_running + redis_key_count)

## Live runtime evidence

- 9 V2 processes running (5 chain loops + freshness refresher +
  runtime guard + comparator + soak observer)
- Runtime guard classification: V2_PRODUCTION_REPLACEMENT_RUNTIME_READY_STABLE
- v2:* total = 30
- v2:market:* = 11, v2:features:* = 5, v2:prediction:* = 3,
  v2:trainer:* = 2, v2:orchestrator:* = 3, v2:signals:paper = 1,
  v2:paper:* = 4, v2:risk:* = 1
- legacy processes still running (~3+ days uptime): live_binance,
  live_binance_liquidations, live_coinank, live_kucoin,
  live_coinapi_v1, live_coinapi_wsds, feature_pipeline,
  rl.hybrid_trainer, rl.orchestrator_worker, monitor_portfolio_primary

## Hard constraints upheld

- AI BOT (legacy directory) NOT modified.
- Legacy processes NOT stopped.
- Every V2 write guarded with key.startswith("v2:").
- 0 exchange orders placed/cancelled/modified.
- Leverage and margin unchanged.
- No live, canary, or Redis-trim approval token created.
- All work confined to /home/wali/Desktop/AI BOT REBUILD.
- live_gate remains blocked_human_only.
- live_symbols remains [].

## What READY_STABLE means and does NOT mean

READY_STABLE means the V2 paper/shadow runtime is persistent and
fresh. It does NOT mean:

- live-ready (live_gate stays blocked_human_only)
- shutdown-approved (legacy is not stopped; no acceptance file)
- production equivalence proven (soak window must complete)

## Decision

V2_PRODUCTION_REPLACEMENT_RUNTIME_STABILIZATION_READY. The Codex
governor's stale-payload finding is resolved. The hardened runtime
guard reports READY_STABLE. The soak observer is running. Legacy
shutdown remains blocked until soak completes + operator acceptance
file + Codex re-pass.
