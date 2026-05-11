# Codex V2 Data Plane Independence Review

Review date: 2026-05-11

Scope: read-only Codex parallel review of the V2 data-plane independence plan and supporting V2 artifacts. No mutation of `/home/wali/Desktop/AI BOT`, Redis, exchange orders, leverage, margin, position mode, or live execution was performed.

## Decision

NO-GO for V2 data-plane independence cutover approval.

The plan direction is sound: V2 Redis is bounded transport/cache by policy, durable history is assigned to V2 storage, old Redis is not intended as permanent truth, and the reviewed code paths did not introduce legacy writes or live exchange side effects. The plan does not yet pass as a clean independence/cutover packet because the backup/freeze/sync/rollback gates and old-Redis retirement criteria are policy-level statements, not concrete verifiable gates.

## Parallel Review Findings

1. V2 Redis is bounded transport/cache only: PASS.
   Evidence: `bounded_v2_redis_policy.md:3` says V2 Redis is transport/cache only, requires maxlen/TTL/namespace owner/source freshness/producer-consumer mapping/memory bands, and forbids audit/history accumulation in Redis. `claude_worklog/v2_architecture/04_REDIS_NAMESPACE_AND_RETENTION_PLAN.md:5-11` keeps legacy Redis read-only, requires bounded hot streams, offloads audit ledger to DB, and states Redis is not infinite history.

2. Durable history belongs in V2 storage: PASS.
   Evidence: `durable_history_storage_policy.md:3` assigns liquidation history, feature snapshots, predictions, signals, execution intents, paper/shadow fills, positions, PnL, risk decisions, and audit events to durable V2 storage, and says Redis cannot be permanent historical truth. `legacy_to_v2_contract_map.md:6` maps legacy Redis liquidation history to V2 durable history/archive.

3. Old Redis is not permanent truth: PASS.
   Evidence: `old_redis_bridge_or_retire_decision.md:3` keeps old Redis as a read-only bridge only for required runtime evidence until V2 durable stores and bounded streams replace legacy Redis responsibilities. `V2_DATA_PLANE_INDEPENDENCE_PLAN.md:7-9` says V2 becomes source of truth, legacy remains passive evidence/facade only until independent V2 ingress/storage contracts are proven, and no net-new legacy logic should be added.

4. Clean cutover has backup/freeze/sync/rollback gates: FAIL for final cutover readiness.
   Evidence: `freeze_backup_sync_rollback_cutover_plan.md:3` names the right gates: freeze legacy write sources, verify final backup/export, run final read-only sync into V2, compute counts/hashes, define rollback point, validate V2 readers, keep live gate blocked, and create a human-reviewed cutover packet. The artifact is still a single policy sentence with no required artifact names, owners, acceptance thresholds, freeze proof, count/hash criteria, rollback command/procedure, or cutover packet schema. It is adequate direction but not a verifiable cutover gate.

5. Old Redis bridge/retire decision is not concrete enough: FAIL for independence closure.
   Evidence: `old_redis_bridge_or_retire_decision.md:3` limits old Redis to a read-only bridge until V2 durable stores and bounded streams replace legacy responsibilities, but it does not define measurable retirement criteria, bridge-disablement proof, post-cutover dependency checks, or a hard post-cutover prohibition against continued operational dependence on old Redis.

6. No legacy writes are introduced by active V2 code: PASS with preserved-code warning.
   Evidence: `requirements/19_REDIS_POLICY.md:13-21` permits V2 writes only under `v2:*` when allowed and forbids writes to legacy runtime keys. Active Redis V2 adapter code only constructs a Redis client from `V2_REDIS_URL` and reads latest stream IDs with `xrevrange` (`v2/backend/app/adapters/redis_v2/factory.py:22`, `v2/backend/app/adapters/redis_v2/stream_latest_id_reader.py:48`). The preserved legacy copy `v2/legacy_preserved/ingestors/live_coinank.py` contains Redis writers, but static review found no active V2 import or invocation of it.

7. No live exchange side effects are introduced: PASS.
   Evidence: `v2/backend/app/proof/readonly_market_exchange_data_plane.py:38-48` lists order, leverage, margin, position-mode, transfer, withdrawal, and live-trading methods as forbidden; `v2/backend/app/proof/readonly_market_exchange_data_plane.py:95-108` implements order/leverage/margin/position-mode methods by raising `ExchangeMutationForbidden`; `v2/backend/app/api/middleware/live_block_guard.py:43` default-denies live API routes before handlers run. Public Binance paths in this proof are read-only GET market data and remain separate from live execution approval.

## Required Carry-Forward Caveats

- Final cutover remains blocked until backup/export artifacts, freeze proof, sync hashes/counts, rollback point, V2 reader validation, and a human-reviewed cutover packet exist.
- Old Redis retirement remains blocked until the bridge has measurable disablement and post-cutover dependency criteria.
- Before V2 Redis producers are added, implementation must enforce `v2:` namespace or separate-DB isolation at the writer boundary. The current reader is read-only, but it does not itself enforce a `v2:` stream prefix.
- The policy assigns liquidation history to durable V2 storage, but the canonical DB/schema artifacts should explicitly model that durable liquidation-history/archive table before implementation/cutover approval.

Result: CODEX_V2_DATA_PLANE_INDEPENDENCE_FAIL
