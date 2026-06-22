# Codex Review: V2 Native Core P0 True Migration Sprint

Generated: `2026-05-15T23:07:30Z`

GO/NO-GO: `V2_NATIVE_CORE_P0_TRUE_MIGRATION_CODEX_FAIL`

## Blocking Findings

1. Native feature pipeline is not yet proven.
   - Required: `v2/backend/app/services/feature_pipeline_native/service.py`, `v2/backend/app/cli/v2_feature_pipeline_native.py`, SHA256-cited legacy baseline, dependency closure, config/env mapping, tests proving V2 computes native features, and public payload.

2. RL/MASA/PPO/reward stack is not yet implemented to migration-contract depth.
   - Required: environment/reset/step loop, observation tensor schema, unified feature builder, reward suite, MASA/Hybrid PPO policy behavior, checkpoint/forward-pass evidence, CPU training loop, and GPU parity milestone evidence.

3. Native orchestrator arbitration is not yet implemented to migration-contract depth.
   - Required: proposal scoring, regime filtering, signal routing, deconflict, shadow mode, stale/duplicate handling, and behavior tests against preserved legacy source. Schema-only decision records are not arbitration.

4. Stop/TP/stealth exit and trade-management engine is not yet implemented to migration-contract depth.
   - Required: stealth stops, dynamic adaptive stops, dynamic TP, exit coordination, churn prevention, and hedge/DCA fail-closed classification in paper mode.

5. Native ingestor independence is not yet proven.
   - Required: per-ingestor proof that V2 opens its own WebSocket/REST source, or explicit `READONLY_BRIDGED` downgrade.

## Safety Invariants

- `live_gate` remains `blocked_human_only`.
- `live_symbols` remains `[]`.
- No live/canary/shutdown approval is granted by this review.
- Old Redis writes and exchange mutation remain forbidden.

## Decision

`V2_NATIVE_CORE_P0_TRUE_MIGRATION_CODEX_FAIL`

The sprint is correctly routed, but it is not complete. Legacy shutdown remains blocked and live/canary remain disallowed.
