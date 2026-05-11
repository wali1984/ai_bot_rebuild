# Codex V2 Data Plane Independence Review

Review date: 2026-05-11

Scope: read-only parallel review of the V2 data-plane independence plan and supporting committed artifacts. No Redis mutation, legacy tree mutation, exchange order action, leverage/margin/position-mode action, or live execution enablement was performed.

## Decision

PASS for plan/policy approval.

This is not final cutover approval and does not authorize live execution. It only confirms that the committed V2 data-plane independence plan assigns durable truth away from Redis/legacy, keeps Redis bounded, keeps legacy passive/read-only until cutover, and defines required cutover gates.

## Review Findings

1. V2 Redis is bounded transport/cache only: PASS.
   Evidence: `V2_DATA_PLANE_INDEPENDENCE_PLAN.md` says V2 owns bounded Redis transport/cache and durable DB history/audit/features/predictions/signals/executions, while legacy remains passive evidence/facade only until V2 proves independent ingress and storage contracts. `bounded_v2_redis_policy.md` requires every stream/key to have maxlen/TTL/namespace owner, source freshness, producer/consumer mapping, and dashboard memory bands, and forbids audit/history accumulation in Redis.

2. Durable history belongs in V2 storage: PASS.
   Evidence: `durable_history_storage_policy.md` assigns liquidation history, feature snapshots, predictions, signals, execution intents, paper/shadow fills, positions, PnL, risk decisions, and audit events to durable V2 storage. It explicitly says Redis cannot be permanent historical truth and requires IDs, timestamps, source freshness, schema version, and evidence pointers.

3. Old Redis is not treated as permanent truth: PASS.
   Evidence: `old_redis_bridge_or_retire_decision.md` keeps old Redis as a read-only bridge only for required runtime evidence until V2 durable stores and bounded streams replace legacy responsibilities. `legacy_to_v2_contract_map.md` maps legacy Redis liquidation history to V2 durable history/archive and keeps Redis as transport/cache only.

4. Clean cutover has backup/freeze/sync/rollback gates: PASS with specificity caveat.
   Evidence: `freeze_backup_sync_rollback_cutover_plan.md` requires freezing legacy write sources, final backup/export verification, final read-only sync into V2, counts/hashes, rollback point, V2 reader validation, blocked live gate, and an explicit human-reviewed cutover packet. Caveat: this is a policy-level gate list, not yet an executable checklist with owners, thresholds, artifact names, or rollback commands.

5. No legacy writes are introduced by the plan: PASS.
   Evidence: the plan says not to add net-new legacy logic. `requirements/19_REDIS_POLICY.md` permits V2 writes only under `v2:*` when allowed and forbids writes to legacy keys such as `signals:trading*`, `executed_signals`, `positions:*`, `portfolio:*`, and any old legacy runtime keys. Current reviewed V2 Redis code only constructs a latest-ID reader and calls `xrevrange`; no legacy write path was found in that reviewed V2 source path.

## Caveats To Carry Forward

- Redis enforcement is not complete in the current scaffold. `make_real_redis_stream_latest_id_reader` accepts an arbitrary `V2_REDIS_URL`, and the current read-only reader does not itself enforce a `v2:` prefix or separate-DB isolation. This is acceptable for the plan gate because it does not write, but it must be closed before adding V2 Redis producers.
- The read-only market/exchange data-plane proof exposes an optional `--fetch-binance` path that performs public Binance GET requests. It does not place, cancel, or modify orders, and mutation methods raise before action, but it should remain opt-in and must not be conflated with live execution approval.
- Final cutover remains blocked until backup/export artifacts, freeze proof, sync hashes/counts, rollback point, and human-reviewed cutover packet exist.

Result: CODEX_V2_DATA_PLANE_INDEPENDENCE_PASS
