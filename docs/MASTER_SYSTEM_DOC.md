# AI Bot V2 master system document

**Current documentation cut:** 2026-07-16, with scoped 2026-07-22 trainer-publisher addendum

**Mode observed:** paper/shadow; live transport disarmed but present in source

**Decision:** NO-GO for live trading and NO-GO for using current paper results as clean promotion evidence.

> A dated **[Post-cut reconciliation (2026-07-16, evening)](#post-cut-reconciliation-2026-07-16-evening)** section below records verified current deltas and the operational hardening applied after this cut. The NO-GO decision is unchanged.

## Scoped trainer-publisher addendum (2026-07-22)

### Authenticated resident commissioned at 18:51 EDT

The persistent native-trainer unit is now an authenticated profiled
**non-serving candidate publisher**, not the earlier passive observer. The
effective process is pinned to immutable release
`7ff0e617d76bf83d6b69e6b6ec6814a3ec1b249c`; the tracked deployment boundary
and clean-start namespace repair are committed through
`6de36d8651814a903225b3611a9557ef6dada93b`. At the final verification it was
`active/running` with PID `302319`, `NRestarts=0`, and the observation
coordinator remained `active/running` with PID `4074206`, `NRestarts=0`.

Four resident heartbeats advanced from `2026-07-22T22:51:20.194460Z` through
`2026-07-22T22:52:50.225146Z` without a PID change or restart. Each 16-field
top-level status had a verified local self-hash, an exact 30-field resident
result, a 10-field side-effect contract, and all 18 resident Boolean result
fields false. The service loaded the four distinct local HMAC verification
roles, imported no optimizer runtime, and truthfully reported
`WAITING_EXTERNAL_WITNESS_CONFIGURATION` because the optional independent
Ed25519 verifier bundle is absent.

The coordinator's anchored local state is `HEAD_STAGED`: 18 admitted examples,
zero label-unavailable rows, a complete state chain, no witness runtime, no
signed head, no external full-consumption acknowledgement, and no optimizer,
checkpoint/model, prediction, paper/live, execution, or order authority. Thus
the **publisher process is online**, but optimizer execution and candidate
publication remain correctly blocked on independently supplied witness
identity, public-key pin/key, and the coordinator's purpose-scoped external
authorization. A same-host witness or fabricated receipt is not acceptable.

The resident receives no bearer, endpoint, exchange, wallet, Moralis, CoinAPI,
prediction, trading, or order credential. Its coordinator root, feature ledger
and WAL/SHM, immutable cost CAS, repository, and deployed code are mounted
read-only. Its only write roots are the non-serving candidate model directory
and the private resident status/cache directory. GPU device visibility is
retained, while Internet address families are denied. The complete credential
and authority contract is
[authenticated profiled trainer resident credential contract](../claude_worklog/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.credentials.md).

The profiled base-feature publisher is active from immutable release
`e34af1e6a6bb9b54818e18f9279fcc9904de0922`, pinned by commit
`cb927adaabecac0dab6e68827f8f4b6b8d37a2aa`.
The preceding `9fcea85f...` release produced valid rows, but SQLite could remove
and recreate the ledger WAL/SHM files after its last per-cycle connection
closed. The read-only trainer observer correctly failed closed during that
coordination-file gap, so its status alternated between valid and
`DatabaseError` even though the ledger remained intact.

The current publisher holds the exact singleton writer lease plus one
transaction-free, `query_only` WAL coordination connection for its complete
process lifetime. A 39-sample live burn-in covered 13 distinct observer scans
and two complete publisher append cycles. TAOUSDT sequences 39/40 and TREEUSDT
sequences 41/42 were appended as parent/strict-child pairs; both cycles had one
published pair and zero failures. The WAL and SHM inodes remained unchanged
while the WAL grew from 0 to 515,032 to 1,030,032 bytes. Both services remained
active with zero restarts. The final observer scan verified 42 records, 27
append receipts and 15 exact strict candidates with zero exclusions and a
complete integrity scan.

The earlier independent strict-loader proof also reopened LDOUSDT sequence 14
and NIGHTUSDT sequence 16: two admitted, zero excluded, with exact 39 physical,
446 logical and 1,784 model-vector values.

The trainer's canonical mark-price Redis key is now also single-writer. Before
commit `2f05742c48d09b6018381a99535703321c4be06e`, both the Binance USD-M
WebSocket seeder and the public-metadata ingestor wrote
`v2:market:mark_price:{symbol}`. The metadata writer could temporarily replace
the canonical, causal WebSocket document with a differently shaped cache
document. The WebSocket seeder now exclusively owns that key; the metadata
ingestor writes `v2:market:premium_index:{symbol}`. Both services are pinned by
commit `ad4ce92a15172b76bf9bb5f9ffc807bdb13fe48c` to the read-only
`2f05742c...` release. A 70.047-second post-cutover probe sampled TRUMPUSDT
1,373 times: 1,373 canonical/causal WebSocket mark documents, zero missing or
invalid mark documents, and zero JSON errors. The separate premium-index key
was present in 1,363 samples and advanced through two source event times. The
publisher cycle completing at `2026-07-22T12:24:01.572529Z` selected one,
published one and failed zero. The following cycle isolated ONEUSDT for
unavailable canonical OHLCV REST provenance; it did not report a mark-price
schema/JSON failure and appended no orphan row.

The canonical mark document carries `event_time <= received_at`, with
`received_at == available_at == generated_at`, a one-second expected source
cadence, canonical finite JSON, source/schema/transport identity, and explicit
false order/leverage/margin mutation flags. This corrects data ownership and
PIT lineage only; it does not change strategy, risk, sizing, leverage, paper
execution, live execution, or optimizer authority.

This supersedes older claims that the profiled base publisher is staged,
credential-blocked or only producing masked rows, and older claims that the
persistent resident is still a passive observer. It does not supersede the
live NO-GO. The strict samples have trainer-candidate input authority only;
prediction, paper, live and `runtime_wired` remain false. The resident process
is online, while its optimizer is intentionally not authorized until the
external completion receipt exists. See the
[authenticated recovery checkpoint](../claude_worklog/codex/CODEX_AUTHENTICATED_TRAINER_PUBLISHER_RECOVERY_2026_07_22.md)
for the 21-object CAS contract, exact clocks/keys/fields, tests, runtime counts
and change-impact map.

The strict cycle-status reader originally checkpointed at `c61ee6ba3b` is now
in the installed resident release lineage. It verifies the base publisher's
exact 57-field local status contract, all ten symbol inventories and their
writer set algebra, canonical clocks, file-race safety, and authority
semantics. A self-hash remains local integrity, not independent authentication
or trainer admission. See
[Profiled base-publisher cycle status reader V1](system_audit_2026_master/components/PROFILED_BASE_PUBLISHER_CYCLE_STATUS_V1.md).

The crash-resuming coordinator is installed from immutable release
`37080a1cd015d5d51c0248f7b7e7fabbb9c24253`. It orders the base status through
deterministic manifest, witnessed head, epoch, contiguous inventory receipts,
and local completion. In witness-absent mode it deliberately parks after one
`HEAD_STAGED` status rather than emitting a misleading heartbeat. It grants no
external-completion, optimizer, checkpoint/model, prediction, paper/live,
order, execution, or runtime authority. See
[Profiled training observation coordinator V1](system_audit_2026_master/components/PROFILED_TRAINING_OBSERVATION_COORDINATOR_V1.md).

This is the repository-level entrypoint. The complete current audit is [AI_BOT_V2_FULL_REBUILD_MASTER_AUDIT_REPORT.md](system_audit_2026_master/AI_BOT_V2_FULL_REBUILD_MASTER_AUDIT_REPORT.md); the document map is [REVERSE_ENGINEERING_INDEX.md](system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md).

Older June/July documents remain historical snapshots. They are not current when they claim one trainer, read-only V2 APIs, operational SQL persistence, risk as final paper authority, no order transport, or the earlier service/module/test counts.

## System identity

AI Bot V2 is a Redis-centered distributed crypto trading research platform. On the audited workstation it comprises market/provider ingestion, temporal feature assembly, a native GPU policy/trainer, prediction/signal publication, orchestration, risk records, paper execution/lifecycle/accounting, portfolio/guardian/feedback loops, a FastAPI backend, React/Vite web client, SwiftUI/watch/CLI clients and a large autonomous operations/evidence layer.

It is not reproducible from a Git clone alone. Effective systemd units/drop-ins, mutable runtime/model/replay data, Redis state/config, local auth, ignored frontend build, machine packages/CUDA and Cloudflare provider-side routing are also required.

## Verified scale

- 9,272 tracked paths in the content-revalidated atlas snapshot.
- 3,213 parsed Python modules; 32,272 Python symbols.
- 3,334 TypeScript/JavaScript and 693 Swift symbols.
- 25,389 Python import edges and 161,112 call references retained.
- 1,807 declared data/schema contracts and 39,538 field names.
- 2,918 environment-key names, 2,040 Redis patterns and 905 API definition/reference records.
- 157 installed `ai-bot*` user units at the earlier operations snapshot; 81 services running, 36 active timers and 3 failed services. The direct recheck found 156 installed basenames and 35 active timers, confirming deployed topology is mutable.
- Current OpenAPI snapshot: 189 paths/193 HTTP operations, plus seven mounted WebSocket paths outside OpenAPI.
- Redis snapshot: about 1.11 million keys and 31 GiB against a 32 GiB `allkeys-lru` limit, RDB-only/AOF disabled.
- Native model contract: 477 ordered features × values/missing/stale/availability = 1,908 inputs.

## Post-cut reconciliation (2026-07-16, evening)

The cut above is a point-in-time snapshot. The deltas below were directly re-measured later the same day, after operational hardening and web/mobile work in this session. The audit decision is unchanged: **NO-GO for live; LIVE TRADING BLOCKED.** The paper trade loop (`v2_trade_management_paper_loop.py`) is owned by a separate agent and was not modified here.

**Re-measured scale** (`systemctl --user list-units 'ai-bot*'`, `redis-cli DBSIZE`/`INFO memory`/`CONFIG GET save`, `/openapi.json`):

- Installed `ai-bot*` user units: **159** (was 156/157). Running services: **84** (was 81). Active timers: **36**. Failed services: **2** — `ai-bot-v2-autonomous-no-manual-next-task-policy` and `ai-bot-v2-closed-candle-replay-evidence` (was 3).
- Redis: **941,651 keys / 31.50 GiB** against the 32 GiB `allkeys-lru` cap; `save "900 1"`, `appendonly no` (RDB-only confirmed). Key count fell from ~1.11M as LRU eviction ran under sustained memory pressure.
- OpenAPI: **189 paths / 193 operations — unchanged.** The derivatives work added `/api/v2/derivatives` and `/api/v2/market/{symbol}/derivatives` as enrichment of the existing surface; net path/operation count did not move.

**Operational hardening applied this session** (effective systemd drop-ins, not tracked in git — verify with `systemctl --user show`):

- `ai-bot-v2-out-of-sample-evidence-producer` — **removed** (stopped + disabled). It was in an OOM-restart loop (~4.2 GiB per restart) and a primary contributor to the workstation OOM event.
- `ai-bot-v2-adaptive-capital-productivity` — **memory-capped** via drop-in `MemoryHigh=6G / MemoryMax=8G` (previously uncapped; leaked to ~15.5 GiB loading millions of counterfactual configs).
- `ai-bot-v2-paper-equity-reconciliation-loop` — **`StandardOutput=null`** drop-in (had flooded `/var/log/syslog` at ~600 lines/s to ~35 GiB, starving disk I/O).
- New operator scripts: `tools/OPERATOR_crash_hardening_sudo.sh` (truncate the 35 GiB syslog + cap journald to `SystemMaxUse=2G`; **needs sudo — pending operator**) and `tools/fix_cursor_state_bloat.sh` (reclaim Cursor's ~18 GiB `state.vscdb` AI-history cache behind the "Codex loading" hang; **run with Cursor closed — pending operator**).

**Still open (unchanged by this session):**

- The retention conflict in §"Deployment/operations truth" persists: `ai-bot-v2-orderbook-replay-rollover.timer` is still enabled/active and the 15-minute `ai-bot-v2-disk-retention-janitor.timer` still runs without `--dry-run`. Repairing the rollover would let its timer invoke the harsher policy — treat as an operator decision, not an automatic repair.
- Persistent/offline trainers and duplicate portfolio publishers remain concurrently active (`continuous-offline-gpu-trainer`, `native-cuda-trainer-persistent`, `trainer-training-live-loop`, `trainer-checkpoint-evidence`; `portfolio-state-publisher` + `portfolio-cascade-guard`).
- Redis remains near its cap with no discovered HA/tested restore.

**Web/mobile changes this session** (source edits, deployed via controlled build): derivatives + markets pages rebuilt for full real-time coverage; AI page trainer telemetry expanded; natural-language signal reasoning; a reusable NERVYX chart library (Recharts) across dashboard/portfolio/AI/signals/derivatives; matching Path-based SwiftUI charts on iOS dashboard/positions with backend `equity_curve`/`win_rate` payloads.

## Architecture

```text
exchange/provider readers
  → Redis market/provider truth
  → closed-candle/native feature/TA/context snapshot
  → 477-field + masks tensor
  → native policy/trainer/checkpoint
  → prediction/replay/archive publication
  → all-timeframe publisher
  → orchestrator proposal
       ├─→ risk ALLOW/DENY record
       └─→ paper signal
  → paper trade-management/lifecycle/accounting
  → positions/portfolio/guardian/outcome/replay/feedback

FastAPI REST/WebSocket/static → React/Vite + SwiftUI/watch/CLI

Dormant guarded branch → Binance WebSocket order.place
```

## Temporal contract

The following are never interchangeable:

- `event_time`: source event occurred;
- `ingested_at`: system received/persisted it;
- `available_at`: exact value became safe to use;
- `generated_at`: derived record was computed;
- `feature_cutoff`: newest information represented;
- `decision_time`: policy decision was fixed;
- `execution_time`: paper/live materialization occurred.

All contributing availability and final candle close times must be no later than decision time; MASA cutoff must be no later than PPO decision time; decision must be no later than execution. The canonical candle/trust modules enforce much of this. Current external feature enrichment does not preserve/check every contributing source envelope, so end-to-end point-in-time proof is incomplete.

## Current model/training truth

The native network is a residual PyTorch policy with optional attention/GRU and policy/value/expected-move/confidence/MASA heads. Active config used larger width/depth than source defaults. Inference selects only hold/long/short from the seven-action head. MASA is one learned auxiliary scalar blended with a deterministic adapter, not a multi-agent system.

The trainer is a hybrid PPO-shaped/supervised implementation. It requires on-policy entry fields when using the PPO term, but advantage is immediate reward minus old value; gamma/done do not create GAE/discounted trajectory returns. Its clipped ratio does not prove that old and new probabilities describe the same behavior action or probability transformation; a supervised single-direction guard can substitute hold for a taken long/short target. AdamW is recreated, optimizer state is not checkpointed, and direct output-head nudges occur after gradient updates.

Training evidence has current blockers: external temporal lineage gaps, masked/missing-trust exceptions, a signed-direction replay label defect, transaction-cost disagreement, holdout not enforced by the main loader, architecture rather than weight identity, and archive/replay publication failure that can still leak downstream lineage. The active GRU windower also falls back to incoming list index because `TrainingExample` lacks a top-level `decision_time`; after source/PPO reordering, a target can receive a frame whose real nested decision time is later, which is future leakage.

### 2026-07-22 authenticated profiled-observation delta

The strict profiled path now has three relevant active, zero-restart services:
the base feature publisher, profiled training observation coordinator and
authenticated non-serving trainer resident. The coordinator runs from detached
read-only release `37080a1cd015d5d51c0248f7b7e7fabbb9c24253`; the trainer
runs from detached read-only release
`7ff0e617d76bf83d6b69e6b6ec6814a3ec1b249c`. Manifest
`669f74c...b99bfe8` contains 18 total/admitted examples and zero unavailable
labels. The coordinator intentionally parks at `HEAD_STAGED` without an
external witness, while the trainer emits a truthful 30-second heartbeat at
`WAITING_EXTERNAL_WITNESS_CONFIGURATION`.

This restores process availability, not optimizer authorization. No external
witness drop-in is installed, no witness network request occurred, and every
optimizer, checkpoint/model, prediction, paper/live, order, execution and
runtime-wired flag remains false. The coordinator requires an independently
operated HTTPS witness with two purpose-scoped bearer credentials, identity,
pinned raw Ed25519 public key and separate digest. The trainer receives only
the identity, public key and pin after provisioning, never either bearer.
Generating any of them on this host would not prove independent monotonic
history.

The runtime corrections are non-semantic. State is read through a
descriptor-anchored, pointer-double-read complete-chain verifier. The
authorization journal is copied as a stable verified main/WAL pair to private
scratch and queried read-only; coordinator source fingerprints must remain
unchanged. Recoverable cycle failures remain observable and fail closed;
malformed arguments or credentials terminate with non-restarting status 78.
No strategy, reward, PPO/MASA objective, risk, allocation, leverage, margin,
paper position or exchange/order behavior changed.

## Current decision/execution truth

The orchestrator creates a provisional risk ID and paper flag before gateway evaluation. The gateway may write a real `DENY`; paper dereference records it, but ordinary A-grade admission tests ID existence plus local pre-trade rather than requiring action `ALLOW`.

The active paper loop also contains confidence overrides. At confidence ≥0.65 a fast path accepts and continues before tier/upstream enforcement, direction, sizing, churn, portfolio freeze, preemptive admission, fill invariant, accounting annotations and PPO entry stamping. Higher thresholds relax additional gates. One fee override writes a frozen dataclass and causes runtime exceptions.

Therefore current paper fills are research artifacts until individually classified by risk action, admission path, temporal completeness, invariant/position state, label/cost version, durability and PPO-field completeness.

## Live boundary

No active authorized real submitter was observed; release mode was effectively non-live and live gate disarmed. Real Binance order transport and dormant callers exist, including a runtime whose transport call defaults non-dry-run. Any edit/enablement of live/order/cancel/modify behavior requires explicit operator approval and a new safety audit.

## Deployment/operations truth

- Effective backend: four Uvicorn workers, `127.0.0.1:8000`, mutable repo source, stacked user-systemd drop-ins overriding an older release symlink.
- Effective frontend: Vite preview, `0.0.0.0:5173`, ignored prebuilt `dist`; source edits are not deployed until a controlled build.
- Installed and versioned unit sets diverge; eight units have invalid unquoted path-with-spaces `PYTHONPATH`; some services mask child failures.
- Persistent/offline trainers and duplicate portfolio publishers are concurrently active.
- Two destructive retention policies conflict. At the `2026-07-16T08:32:41Z` observation, the failed 100 GiB rollover still had an enabled active persistent six-hour timer, while the 15-minute 300 GiB/five-day janitor was already running without `--dry-run`. Its `08:27:21Z` status recorded ten temporary holdout files deleted, so evidence preservation was actively racing retention automation; repairing the rollover would let its existing timer invoke the harsher policy.
- Redis is near its limit without discovered HA/tested restore.
- The central application/paper ORM and Alembic plane is uninitialized, while optional user/revocation/alert/trader-account SQL repositories are implemented but can create tables outside Alembic. The observed deployment used local JSON, Redis, files and one separate closed-loop SQLite WAL database instead.
- Auth/security middleware is mostly pass-through; route dependencies protect some handlers; four workers can race on local JSON state.
- Tunnel credential handling is unsafe and provider-side routing is not captured locally.
- Backend/frontend CI and dependency manifests are incomplete; full tests are unsafe against current live-like workspace state.

## Canonical documents

- [Full master audit](system_audit_2026_master/AI_BOT_V2_FULL_REBUILD_MASTER_AUDIT_REPORT.md)
- [Operator manual](system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md)
- [Technical reference](../v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md)
- [Findings/risk register](system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md)
- [Validation and limitations](system_audit_2026_master/VALIDATION_AND_LIMITATIONS_2026-07-16.md)
- [Historical artifact classification](system_audit_2026_master/HISTORICAL_ARTIFACT_CLASSIFICATION.md)
- [Rebuild blueprint](system_audit_2026_master/REBUILD_BLUEPRINT.md)
- [Runtime/deployment internals](system_audit_2026_master/components/RUNTIME_PROCESS_AND_DEPLOYMENT.md)
- [Temporal data/features](system_audit_2026_master/components/DATA_TEMPORAL_LINEAGE_AND_FEATURES.md)
- [Trainer/PPO/MASA/replay/checkpoints](system_audit_2026_master/components/TRAINER_PPO_MASA_REPLAY_AND_CHECKPOINTS.md)
- [Profiled trainer external witness client V1](system_audit_2026_master/components/PROFILED_TRAINING_EXTERNAL_WITNESS_CLIENT_V1.md)
- [Profiled trainer external witness journal V1](system_audit_2026_master/components/PROFILED_TRAINING_EXTERNAL_WITNESS_JOURNAL_V1.md)
- [Profiled trainer external witness runtime V1](system_audit_2026_master/components/PROFILED_TRAINING_EXTERNAL_WITNESS_RUNTIME_V1.md)
- [Profiled trainer observation coordinator state V1](system_audit_2026_master/components/PROFILED_TRAINING_OBSERVATION_COORDINATOR_STATE_V1.md)
- [Profiled base-publisher cycle status reader V1](system_audit_2026_master/components/PROFILED_BASE_PUBLISHER_CYCLE_STATUS_V1.md)
- [Profiled training observation coordinator V1](system_audit_2026_master/components/PROFILED_TRAINING_OBSERVATION_COORDINATOR_V1.md)
- [Decision/risk/paper/live execution](system_audit_2026_master/components/DECISION_RISK_PAPER_AND_LIVE_EXECUTION.md)
- [API/auth/storage/web/mobile](system_audit_2026_master/components/API_AUTH_STORAGE_WEB_AND_MOBILE.md)
- [Config/contracts/change impact](system_audit_2026_master/components/CONFIG_KEYS_CONTRACTS_AND_CHANGE_IMPACT.md)
- [Function-level atlas summary](system_audit_2026_master/atlas/ATLAS_SUMMARY.md)
- [One-row-per-module index](system_audit_2026_master/atlas/MODULE_BY_MODULE_INDEX.md)
- [Exact audit command/tool ledger](system_audit_2026_master/COMMANDS_RUN.md)

## Change protocol

Before any change:

1. find the exact symbol/key/field/config/route/unit in the atlas;
2. read direct and recursive callers/importers plus dynamic state consumers;
3. identify temporal, model, risk, position, persistence and client implications;
4. compare effective installed units/drop-ins, not only tracked files;
5. isolate tests from current Redis/paper/auth/runtime state;
6. preserve evidence and rollback;
7. obtain explicit approval for strategy, PPO, MASA, risk, live execution or destructive retention;
8. regenerate the atlas and update docs after implementation.

The full machine-level answer to “what will this small function affect?” is `docs/system_audit_2026_master/atlas/CHANGE_IMPACT_INDEX.json`, joined with the Redis/config/data/API/entrypoint registries and the effective runtime snapshot.
