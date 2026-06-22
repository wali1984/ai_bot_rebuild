# Legacy Shutdown Readiness Packet

- Sprint: TWELVE_HOUR_NATIVE_CORE_MIGRATION_AND_SHUTDOWN_READINESS_SPRINT
- Generated: 2026-05-16T05:15:00Z
- Git HEAD: 31a7fd70319f0d586c454b5ea2ea530ba9cb1541
- Decision: BLOCK_LEGACY_SHUTDOWN_PARITY_INCOMPLETE

## Why BLOCK and not SAFE

Every P0 phase reached READY at its respective scope and the
v2-owned non-live startup verified end-to-end paper-only operation.
That is enough to recommend continued V2 paper/shadow soak. It is
NOT enough to retire the legacy runtime, because final parity gates
required to safely shut down the legacy bot are still incomplete:

- Full PPO clip + GAE training is not in V2.
- Checkpoint weight promotion is still CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED.
- Several MISSING_IN_V2 / OPERATOR_DECISION_REQUIRED ingestors.
- Adaptive hedge paper engine is FAIL_CLOSED_STUB.
- Full legacy orchestrator worker logic is not ported.
- Codex review has not yet swept the new phases.

## Why not KEEP_LEGACY_RUNTIME_FOR_TRAINER_PARITY_REFERENCE

KEEP also denies shutdown, but it implies the only remaining blocker
is a parity-reference need. That is not accurate today: the missing
items are not merely "reference only" - they are required preconditions
for SAFE in a future sprint. BLOCK reflects the real state.

## Phase summary (READY at respective contract scope)

| Phase | GO/NO-GO | Codex |
| --- | --- | --- |
| P0.2B | V2_NATIVE_RL_MASA_PPO_P0_2B_POLICY_FORWARD_READY | pending |
| P0.2C | V2_NATIVE_RL_MASA_PPO_P0_2C_CHECKPOINT_READY | pending |
| P0.2D | V2_NATIVE_RL_MASA_PPO_P0_2D_TINY_CPU_UPDATE_READY | pending |
| P0.2E | V2_NATIVE_RL_MASA_PPO_P0_2E_GPU_READY | pending |
| P0.2F | V2_NATIVE_RL_MASA_PPO_P0_2F_TRAINER_OUTPUT_READY | pending |
| P0.3 | V2_ORCHESTRATOR_ARBITRATION_P0_3_READY | pending |
| P0.4 | V2_TRADE_MANAGEMENT_PAPER_P0_4_READY | pending |
| P0.5 | V2_NATIVE_INGESTORS_P0_5_READY | pending |
| P9 | V2_OWNED_NON_LIVE_STARTUP_READY | pending |

## Safety posture (sprint-wide invariants enforced)

- live_gate: blocked_human_only
- live_symbols: []
- approves_live: false
- approves_canary: false
- approves_legacy_shutdown: false
- approves_redis_trim: false
- no_legacy_redis_writes_attempted: true
- no_exchange_mutation_attempted: true
- no_legacy_imports_from_old_bot_directory: true

## Remaining blockers (for a future SAFE)

1. Full PPO clip loss and GAE advantage estimation.
2. PPO optimizer state persistence.
3. Checkpoint weight blob (operator-approved subprocess export +
   Codex review).
4. live_kucoin native V2 build.
5. live_coinapi_v1 secret or native alternative.
6. live_coinapi_wsds paid subscription decision.
7. live_coinank_global_aggregator operator decision.
8. Adaptive hedge paper engine (currently FAIL_CLOSED_STUB).
9. Full legacy orchestrator worker logic port.
10. Live Redis proposal bus integration (intentionally NOT ported).
11. asjad_account_publish_path port.
12. Codex review pass on every phase.

## Evidence paths

See `legacy_shutdown_readiness_packet.json` for the
machine-readable evidence_paths block.

## Final state

`BLOCK_LEGACY_SHUTDOWN_PARITY_INCOMPLETE`
