# Codex Review: V2 Native Algorithmic Core Migration From Deep Audit

Generated: `2026-05-15T22:49:00Z`

GO/NO-GO: `V2_NATIVE_ALGORITHMIC_CORE_MIGRATION_CODEX_FAIL`

## Decision

Codex fails `V2_NATIVE_ALGORITHMIC_CORE_MIGRATION_FROM_DEEP_AUDIT_READY`.

The current work contains useful V2-native paper/shadow components, but the
requested native algorithmic core is not fully migrated. The available payloads
explicitly classify the core subprojects as `PARTIALLY_MIGRATED`, not
`MIGRATED_CODEX_PASS`.

This review does not approve live, canary, or legacy shutdown.

## Evidence Reviewed

| Area | Evidence path | Current classification |
| --- | --- | --- |
| RL core | `v2/frontend/public/operator_runtime/v2_rl_core/latest/v2_rl_core_status.json` | `PARTIALLY_MIGRATED` |
| Feature intelligence | `claude_worklog/final_readiness/v2_native_algorithmic_core_migration/latest/subproject_2_feature_intelligence/subproject_2_feature_intelligence_status.json` | `PARTIALLY_MIGRATED` |
| Feature intelligence public payload | `v2/frontend/public/operator_runtime/v2_feature_intelligence/latest/v2_feature_intelligence_status.json` | `PARTIALLY_MIGRATED` |
| Trade management paper | `v2/frontend/public/operator_runtime/v2_trade_management_paper/latest/v2_trade_management_paper_status.json` | `PARTIALLY_MIGRATED` |
| Orchestrator arbitration | `v2/frontend/public/operator_runtime/v2_orchestrator_arbitration/latest/v2_orchestrator_arbitration_status.json` | missing full arbitration behavior |
| Closure manifest | `claude_worklog/final_readiness/legacy_rl_risk_trainer_trader_closure/latest/full_runtime_copied_source_manifest.json` | SHA256 source available |

## Blocking Findings

### P0: RL/MASA/PPO stack not implemented

`v2_rl_core_status.json` lists only paper-only primitives:

- observation schema descriptor
- constrained reward paper scoring
- fee-ratio shaping paper scoring
- drawdown penalty paper scoring
- no-trade-correct credit
- checkpoint filename parser
- temperature calibration math

It also explicitly lists these missing items:

- `ppo_masa_policy_network_MISSING_IN_V2`
- `gymnasium_env_step_reset_loop_MISSING_IN_V2`
- `gpu_training_loop_MISSING_IN_V2`
- `unified_feature_builder_tensor_assembly_MISSING_IN_V2`
- `checkpoint_weight_loader_MISSING_IN_V2`
- `lagrangian_multiplier_state_persistence_MISSING_IN_V2`

This fails the requirement that the RL/MASA/PPO/reward stack be implemented.
The reward pieces are partial paper scoring, not a native algorithmic trainer
core.

### P0: Feature/microstructure/regime stack is partial

Subproject 2 is honest and useful, but it is not complete. It ports a small
microstructure/regime subset and explicitly lists missing behavior:

- full `unified_feature_builder` with 2,000+ derived features
- cross-timeframe aggregations
- funding/OI derived features
- WebSocket/REST native ingestor layer
- regime hysteresis state machine

This fails the full feature/microstructure/regime stack requirement.

### P0: Hedge/stop/TP/anti-churn stack is partial

`v2_trade_management_paper_status.json` contains paper-only implementations for
stealth stop scheduling, ATR stop planning, TP laddering, churn veto, and a
fee-ratio gate. However it explicitly lists missing full legacy behavior:

- full stealth stop state machine
- full regime-adaptive dynamic TP engine
- full regime-adaptive dynamic stop distance
- adaptive hedge builder
- dynamic adaptive hedge
- hedge pair coordinator
- leg manager
- exit coordinator
- stealth/dynamic integration

The hedge/DCA evaluator is a fail-closed stub. That is safe, but it is not a
native migration of the hedge/DCA engine.

### P0: Orchestrator arbitration and signal schema are not full parity

`v2_orchestrator_arbitration_status.json` exposes paper-only proposal scoring,
signal validation, deconflict, and stream-routing metadata. It explicitly lists
missing full legacy behavior:

- full legacy orchestrator worker arbitration logic
- legacy proposal bus integration
- hedge-cage arbitration overlays
- Asjad account publish path
- higher-timeframe consensus full runtime
- tradeplan protection-demand score

The current V2 signal schema is a useful strict schema, but the full legacy
orchestrator arbitration/signal behavior is not implemented.

### P0: Public payload coverage exists for partials, not for full migration

Public payloads exist for the partial V2 workers:

- `v2_rl_core`
- `v2_feature_intelligence`
- `v2_trade_management_paper`
- `v2_orchestrator_arbitration`

Those payloads correctly do not claim live, canary, or shutdown readiness. They
also do not establish `V2_NATIVE_ALGORITHMIC_CORE_MIGRATION_CODEX_PASS`.

### P1: Deep-audit subproject packet coverage is incomplete

Only `subproject_2_feature_intelligence` has a full subproject report under:

`claude_worklog/final_readiness/v2_native_algorithmic_core_migration/latest/`

The RL core, trade-management, and orchestrator arbitration code exists, but
their native algorithmic-core subproject reports and dependency-closure packets
are not present in the same migration packet structure. That prevents a full
core-level PASS even aside from the missing implementation.

## Positive Findings

- Current inspected V2 modules are not live-enabling.
- Current inspected public payloads keep `live_gate=blocked_human_only`.
- Current inspected public payloads keep `live_symbols=[]`.
- Current inspected public payloads do not approve live, canary, legacy
  shutdown, or Redis trim.
- Feature intelligence SHA256 citations match the full runtime copied source
  manifest for:
  - `rl/microstructure_proactive.py`
  - `rl/toxicity_shield.py`
  - `rl/unified_feature_builder.py`
  - `trading/market_regime_detector.py`
- Additional inspected legacy SHA256 citations exist for:
  - `rl/hybrid_trainer.py`
  - `trading/trader.py`
  - `rl/orchestrator_worker.py`
  - `utils/signal_schema.py`
  - `utils/signal_publish.py`
  - `trading/signal_router.py`
  - `trading/churn_prevention.py`
  - `trading/dynamic_tp_engine.py`
  - `trading/dynamic_adaptive_stops.py`
  - `trading/stealth_stops.py`

## Validation Run

Commands:

```bash
PYTHONPATH="$PWD" .venv/bin/pytest \
  v2/backend/tests/integration/cli/test_v2_feature_intelligence_worker.py

PYTHONPATH="$PWD" .venv/bin/pytest \
  v2/backend/tests/integration/cli/test_v2_rl_core_worker.py \
  v2/backend/tests/integration/cli/test_v2_trade_management_paper_worker.py \
  v2/backend/tests/integration/cli/test_v2_orchestrator_arbitration_worker.py
```

Results:

- Feature intelligence: `16 passed`
- RL core / trade management / orchestrator arbitration: `55 passed`

These tests validate the current partial paper-only components. They do not
prove native full algorithmic migration.

## Safety State

| Check | Result |
| --- | --- |
| `live_gate` | `blocked_human_only` |
| `live_symbols` | `[]` |
| Final approval token | absent |
| Redis trim approval token | absent |
| Old Redis write reported | absent in inspected payloads |
| Exchange mutation reported | absent in inspected payloads |
| Leverage/margin mutation | not approved |

## Required Claude Delegation

Codex created the implementation-heavy remediation descriptor:

`claude_worklog/agent_supervisor/tasks/claude_v2_native_algorithmic_core_full_migration_from_deep_audit.json`

Claude must implement or honestly block:

1. Native RL/MASA/PPO policy/runtime stack, including checkpoint loading rules,
   Gymnasium environment loop, reward stack, calibration, and no-live safety.
2. Full native feature/microstructure/regime stack, including unified feature
   builder, cross-timeframe aggregation, funding/OI, and regime hysteresis.
3. Full paper-only hedge/stop/TP/anti-churn trade-management engine.
4. Full orchestrator arbitration and signal schema parity from the legacy
   proposal/signal/routing sources.
5. Per-subproject dependency closure, SHA256 citations, behavior maps, public
   payloads, and non-smoke tests.

Codex must re-review after Claude completes the implementation packet.

## Final

`V2_NATIVE_ALGORITHMIC_CORE_MIGRATION_CODEX_FAIL`
