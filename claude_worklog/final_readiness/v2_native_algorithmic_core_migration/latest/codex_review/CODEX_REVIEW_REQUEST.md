# Codex Review Request — V2 Native Algorithmic Core Migration

Status: CODEX_REVIEW_COMPLETED_FAIL_RECORDED_AT_LINTER_PATH
Generated: 2026-05-15

## Codex outcome (already recorded)

Codex's review is at
`v2/frontend/public/native_algorithmic_core_migration/latest/operator_dashboard_payload.json`
and resolved to `V2_NATIVE_ALGORITHMIC_CORE_MIGRATION_CODEX_FAIL` with the
following primary blockers:

- RL/MASA/PPO runtime stack is not implemented.
- Full unified feature builder and regime stack are not implemented.
- Hedge/DCA engine remains fail-closed stub.
- Full stealth/dynamic stop/TP/exit coordination is not implemented.
- Full legacy orchestrator arbitration and signal routing are not implemented.
- Subproject dependency-closure packets are incomplete.

`exchange_mutation_observed: false`. `old_redis_write_observed: false`.
`live_gate: blocked_human_only`. `live_symbols: []`.

## What this review request now does

1. Acknowledges the Codex FAIL above.
2. Records the four delivered subprojects with passing tests as
   `PARTIALLY_MIGRATED` (not `MIGRATED_CODEX_PASS`).
3. Names the next round of Codex reviews needed once the listed blockers
   are addressed.

## Next-round per-subproject reviews

Each subproject has its own `codex_review/` directory under
`claude_worklog/final_readiness/v2_native_algorithmic_core_migration/latest/`
and is ready for a per-subproject Codex pass once:

- Subproject 1: PPO+MASA policy network, Gymnasium env step/reset, GPU
  training loop, dependency-closure packet, config/env parity packet.
- Subproject 2: full `unified_feature_builder`, cross-timeframe aggregations,
  funding/OI derived features, dependency-closure packet, config/env parity
  packet.
- Subproject 3: regime-adaptive stealth/dynamic stop machinery, full TP
  scale-out, exit coordinator, leg manager, dependency-closure packet,
  config/env parity packet.
- Subproject 4: full orchestrator_worker arbitration runtime, real proposal
  bus integration, full IntentEngine consensus, dependency-closure packet,
  config/env parity packet.

Each next-round review must Block if:

- Any subproject is labeled `MIGRATED_CODEX_PASS` without satisfying every
  clause of the migration completion contract.
- Any approval token (live, canary, legacy shutdown, Redis trim) appears.
- Old Redis writes appear.
- Exchange mutation appears.

This review does not authorize live, canary, legacy shutdown, or Redis trim.
