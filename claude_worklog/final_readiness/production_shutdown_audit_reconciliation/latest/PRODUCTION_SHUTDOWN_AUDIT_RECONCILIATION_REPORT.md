# Production Shutdown Audit Reconciliation - HARD NO-GO

Generated: 2026-05-17T01:05:00Z
Git HEAD: 31a7fd70319f0d586c454b5ea2ea530ba9cb1541
Reconciliation GO/NO-GO: PRODUCTION_SHUTDOWN_AUDIT_HARD_NO_GO

## TL;DR

Do NOT shut down legacy. The operator's independent production
shutdown audit is correct. V2 is paper/shadow/observer only and
writes zero v2:* Redis keys. Legacy still runs production
ingestion, trainer, orchestrator, feature pipeline, portfolio
monitor, and produces Redis predictions/signals. Earlier packets
were correct at their respective paper-only scope; they did NOT
prove production-equivalence. The acceptance file is also missing.

## Three gates

Shutdown safety has three independent gates. ALL three must be
open before legacy shutdown can be considered:

| Gate | State | Blocks shutdown |
| --- | --- | --- |
| PAPER_ONLY_ACCEPTANCE_GATE | OPERATOR_ACCEPTANCE_FILE_ABSENT | yes |
| PRODUCTION_EQUIVALENCE_GATE | NOT_MET | yes |
| LIVE_TRADING_GATE | BLOCKED_HUMAN_ONLY (intentional) | yes |

All three are currently closed.

## Process evidence (ps -eo etime,cmd)

Legacy production processes (uptime ~3 days each):

- ingest/live_binance.py
- ingest/live_binance_liquidations.py
- ingest/live_coinank.py
- ingest/live_kucoin.py
- ingest/live_coinapi_v1.py
- ingest/live_coinapi_wsds.py
- feature_pipeline.py
- rl.hybrid_trainer --mode hybrid --epochs 1000 --batch-size 64
- rl.orchestrator_worker
- monitor_portfolio_primary.py

V2 processes (paper/shadow/observer only):

- v2.backend.app.cli.v2_feature_snapshot_builder --loop --read-from-paper-runtime --interval 60
- v2.backend.app.cli.v2_trainer_bridge --once --readonly-only (in loop)
- claude_worklog/tools/v2_worker_porting_orchestrator.py --daemon
- claude_worklog/tools/codex_legacy_v2_realtime_decision_observatory.py --daemon
- claude_worklog/tools/codex_non_live_watchdog.py --daemon
- vite frontend dev server

No V2 process is performing production ingestion, training, or
arbitration to Redis.

## Redis evidence (redis-cli SCAN)

- v2:* key count: 0
- prediction:* present (populated by legacy hybrid_trainer)
- signals:* present (populated by legacy orchestrator: signals:trading:asjad, signals:ensemble:diagnostic, signals:overlay:intents, signals:execution:skips, signals:proactive:alerts)
- kc:* present (populated by legacy KuCoin ingestor)
- rl:* present (legacy trainer telemetry: rl:metrics:1m/5m/15m/1h/4h, rl:obs_length, rl:episodes:total)
- heartbeat:* present (legacy ingestor heartbeats: heartbeat:writer:coinank, heartbeat:writer:tokenmetrics, heartbeat:OrderBook:* per-symbol, heartbeat:CoinAnkIngest)
- binance:force:raw present (legacy Binance liquidation raw feed)
- DBSIZE: 12742

V2 writes nothing to Redis at production scope.

## V2 source self-declarations

- v2/backend/app/services/rl_core/service.py components_missing:
  ppo_masa_policy_network_MISSING_IN_V2,
  gymnasium_env_step_reset_loop_MISSING_IN_V2,
  gpu_training_loop_MISSING_IN_V2,
  unified_feature_builder_tensor_assembly_MISSING_IN_V2,
  checkpoint_weight_loader_MISSING_IN_V2.
- v2/backend/app/services/rl_core/environment.py:
  scope=PAPER_ONLY_SIMULATION, approves_legacy_shutdown=False.
- v2/backend/app/services/trade_management_paper/service.py:
  hedge/DCA classification=FAIL_CLOSED_STUB, scope=PAPER_ONLY.
- v2/backend/app/services/rl_core/trainer_output.py: strict
  P0.2F gate currently blocks the live sample with
  NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK.
- v2/backend/app/services/orchestrator_arbitration/service.py:
  components_missing_in_v2 includes
  full_10523_line_orchestrator_worker_arbitration_logic,
  live_order_routing, live_redis_proposal_bus_integration,
  hedge_cage_arbitration_overlays, asjad_account_publish_path.

These are V2 telling itself: I am paper-only. Do not shut down legacy.

## Reconciliation matrix

See production_shutdown_audit_matrix.json. Every audit claim
verified AUDIT_CLAIM_CONFIRMED. Each entry includes the V2
evidence, legacy process evidence, Redis evidence, and the
required remediation (e.g. "Implement V2 production X daemon" or
"Operator-approved Codex pass for production parity").

## What earlier packets actually proved

- 12h native core sprint Phases 0-12: paper-only contract scope.
- P0.2F strict paper-fill gate: blocks malformed/negative-edge
  trainer output (paper-only).
- P0.2G PPO/GAE/AdamW: paper-only algorithm scope.
- Core completion blocker burndown + truth remediation: every
  blocker IMPLEMENTED_AND_TESTED or
  CONVERTED_TO_OPERATOR_DECISION_REQUIRED; matrix and runtime
  ingestor classification agree.
- Final paper-only shutdown decision packet:
  OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN
  (acceptance file absent).

None of these earlier packets claimed PRODUCTION_EQUIVALENCE.

## What needs to happen before shutdown is reconsidered

1. PRODUCTION_EQUIVALENCE_GATE (NOT MET):
   - Implement and operate V2 production ingestor daemons that
     write to v2:* Redis namespace at production rate
     (live_binance/live_binance_liquidations/live_coinank/live_kucoin/
     live_coinapi_v1 - if accepted).
   - Implement and operate V2 production trainer that produces
     V2-namespace predictions with operator-approved checkpoint
     and full PPO/GAE training Codex pass.
   - Implement and operate V2 production orchestrator daemon with
     full legacy worker parity (or explicit operator acceptance of
     paper-only orchestration for shutdown).
   - Implement and operate V2 production feature pipeline daemon
     with proven equivalence + Codex pass.
   - Implement and operate V2 production portfolio monitor.
   - Verify v2:* Redis key count > 0 at production rate over a
     soak window before shutdown.

2. PAPER_ONLY_ACCEPTANCE_GATE (file absent):
   - The acceptance file at
     claude_worklog/approvals/OPERATOR_ACCEPTS_V2_PAPER_ONLY_SHUTDOWN_LIMITATIONS.md
     must be created by the operator. This packet does NOT create
     it. The acceptance file alone is NOT sufficient to flip the
     PRODUCTION_EQUIVALENCE_GATE.

3. LIVE_TRADING_GATE:
   - Stays blocked_human_only. Not affected by this packet.

## Safety scans on this packet

- Old Redis writes attempted by this packet: 0.
- Exchange orders placed or modified: 0.
- Legacy stopped or restarted by this packet: NO.
- Final live approval token created: NO.
- Operator paper-only acceptance file created: NO.
- live_gate: blocked_human_only.
- live_symbols: [].

## Decision

PRODUCTION_SHUTDOWN_AUDIT_HARD_NO_GO. Legacy must remain running.
V2 must continue paper/shadow/observer operation. No approvals are
created by this packet.
