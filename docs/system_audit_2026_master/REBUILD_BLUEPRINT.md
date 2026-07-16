# AI Bot V2 reconstruction blueprint

**Goal:** reproduce the behavior of the audited non-live system on a clean host while removing undocumented host state and proving temporal, training and execution integrity.

**Current result:** the source is mapped deeply enough to plan a copy, but a Git clone alone is not reproducible and current behavioral defects must not be copied as approved design.

This blueprint distinguishes:

- **behavioral parity:** reproduce what current code actually does;
- **safe target design:** preserve intended behavior while fixing proven defects;
- **historical evidence:** retain current artifacts without treating them as valid training/promotion truth.

Never silently “improve” behavior while claiming parity. Every intentional deviation needs an explicit compatibility decision, migration and test.

## 1. Reconstruction deliverables

A complete copy requires all of the following:

1. Versioned source at a recorded commit.
2. Pinned OS, Python, Node, Swift, CUDA/driver, Redis and Cloudflare client dependencies.
3. Canonical environment-key manifest with secret references, never secret values.
4. Canonical systemd unit/drop-in/timer manifest and idempotent installer.
5. Redis key/type/schema/TTL/producer/consumer manifest.
6. Disk layout, permissions, ownership and retention manifest.
7. Model feature/action/architecture/checkpoint contracts.
8. Data-source/provider configuration and rate/availability contracts.
9. Temporal-lineage schema and point-in-time acceptance tests.
10. Paper position/lifecycle/accounting and risk-decision contracts.
11. API/OpenAPI/WebSocket/static/client compatibility contracts.
12. Auth/RBAC/MFA/durable-store and network/tunnel configuration.
13. Backup, restore, rollback and disaster-recovery proof.
14. Isolated unit/integration/replay/soak/security tests.
15. Operator manual and change-impact atlas generated from the final build.

## 2. Target host bill of materials

The current host must be captured, then converted into pinned declarations:

| Layer | Required capture |
|---|---|
| OS/kernel | distribution/release, kernel, libc, timezone/locale, users/groups, limits |
| Python | exact interpreter, venv creation, every package hash/version, import root |
| GPU | GPU model, driver, CUDA runtime/toolkit, PyTorch build, compute capability |
| Redis | version, config, bind/security, maxmemory/policy, RDB/AOF, system unit |
| Node/web | Node/npm versions, lockfile, build command/env, dist content hash |
| Swift/mobile | Swift/Xcode platform versions and package lock/resolution |
| systemd | system/user versions, linger/session behavior, all unit/drop-in states |
| tunnel/network | Cloudflare client version, route/origin export, firewall/DNS/TLS |
| storage | mount/filesystem, free-space thresholds, directory permissions, backup target |

The current `v2/pyproject.toml` and frontend manifests are insufficient. The ad-hoc venv has many packages omitted from the project manifest, the frontend dependency tree is incomplete, and `docker-compose.yml` is empty.

## 3. Canonical filesystem layout

Define immutable/release and mutable/state roots separately:

```text
/opt or /home/.../releases/<release-id>/       immutable application release
/home/.../releases/current -> <release-id>     atomic promoted symlink
/var/lib or /home/.../state/                   auth, Redis/archive/replay/model state
/var/log or journal                            bounded logs
/etc or protected credential store            secret references/config
/run                                           locks/PIDs/ephemeral sockets
```

Do not run production-like services directly from a dirty Git checkout. The current drop-ins do exactly that and must be modeled as a migration input, not the target deployment.

For every mutable directory record:

- owner/group/mode/ACL;
- writer authority;
- readers;
- schema/version;
- atomicity/locking;
- backup/restore;
- retention;
- maximum growth;
- whether reconstructible;
- credential/PII classification.

## 4. Canonical process manifest

The observed 157 installed unit files are not represented by one versioned set. Build a manifest with one row per service/timer:

| Field | Meaning |
|---|---|
| unit ID | stable unique service/timer name |
| functional owner | ingestion/feature/trainer/decision/paper/API/automation |
| code entrypoint | exact module/script and release path |
| authority | sole writer, derived publisher, monitor or experimental |
| environment schema | required/optional key names and defaults |
| dependencies | Redis/network/files/direct unit ordering |
| schedule/restart | timer cadence, timeout, restart/backoff/rate limit |
| state/output | exact Redis/file/log writes and TTL |
| safety class | read-only, paper mutation, model mutation, destructive, live mutation |
| health contract | primary heartbeat/result and stale threshold |
| shutdown semantics | partial-write/drain/checkpoint behavior |
| install state | enabled/disabled/masked/static/link |

Before copying, decide explicitly:

- which of the 57 host-only units are supported;
- which of the 33 versioned-but-uninstalled units are historical/experimental;
- whether both GPU trainers are intended authorities;
- why two portfolio publishers exist;
- which supervisors may restart which workers;
- which direct legacy CoinAnk scripts remain;
- which dormant live callers stay masked/absent.

The installer must quote paths correctly, reject `|| true` failure masking unless explicitly justified, validate with `systemd-analyze`, and produce a machine-readable installed-versus-manifest diff.

## 5. State and contract reconstruction

### 5.1 Redis

Generate a key manifest from the atlas plus safe runtime type/TTL sampling:

```text
pattern → producer → consumers → Redis type → schema → temporal fields
        → TTL/refresh → cardinality/growth → authority → loss consequence
```

Then:

1. choose protected persistence/HA (AOF/RDB/replica/backup) intentionally;
2. separate critical state from evictable caches or use non-evicting policy for authority data;
3. set bounded TTL/cardinality for snapshots/status/caches;
4. define versioned migrations and dual-read windows;
5. implement backup and full restore verification;
6. alarm on eviction, save failure, memory and unbounded key growth.

Do not copy the current near-full `allkeys-lru`, RDB-only posture as a reliable design.

### 5.2 Files/JSON/JSONL

For every artifact writer specify atomic temp/write/fsync/rename behavior, interprocess locking, schema/version, checksum, rotation and reader fallback. Remove dual truth where possible: public/dashboard artifacts should identify their primary source and generated/source times.

### 5.3 SQLite/relational state

The central application/paper SQLAlchemy metadata, DB and Alembic path are uninitialized. Optional user, revocation, alert and trader-account SQL repositories exist, but can create tables directly outside Alembic. Choose one explicit target:

- remove all relational paths from the reconstructed architecture; or
- consolidate every selected repository under one owned schema and reviewed migrations, then migrate an explicitly selected state set. Prohibit application-side production schema invention.

For closed-loop SQLite, use the SQLite backup API or checkpoint/consistent copy including WAL semantics. Prove restore with integrity and logical row counts.

### 5.4 Models/archive

Bind checkpoint identity to:

- feature schema/order hash;
- action schema hash;
- full architecture and behavior config;
- exact weight-blob SHA-256;
- optimizer state policy;
- training sample-manifest hash;
- code/release commit;
- training start/end/cutoff;
- promotion/holdout evidence.

Archive records need per-record content hash, append durability, interprocess coordination, manifest checksum updates and rollover tombstones.

## 6. Temporal data contract

Make a single envelope required at every source/derived boundary:

```text
source_id
symbol / market / timeframe
event_time
ingested_at
available_at
generated_at
feature_cutoff or source_cutoff
decision_time (only after a decision exists)
execution_time (only after materialization)
is_final / finality evidence
schema_version
content/source hash
quality/freshness flags
```

Rules:

```text
raw source: event_time <= ingested_at <= available_at
derived record: max(input available_at) <= generated_at <= derived available_at
all contributing available_at <= decision_time
all contributing close_time <= decision_time
truthful newest-information feature_cutoff <= decision_time
MASA feature_cutoff <= PPO decision_time
decision_time <= execution_time
unfinished higher-timeframe candle is never final
missing timestamps are rejection, not proof
```

If clock skew or malformed provider metadata appears to violate these relations, quarantine and preserve the original record. Do not silently clamp or rewrite timestamps into compliance.

Preserve a vector/map of each contributing source/timeframe cutoff and availability. Do not collapse it to a minimum timestamp.

### Required property tests

- unfinished 1h/4h candle cannot enter a 1m decision;
- backfilled candle arriving later cannot enter an earlier decision;
- provider value without availability is masked/rejected;
- future/stale external Redis enrichment cannot enter tensor;
- valid numeric zero remains zero and available;
- one source after decision invalidates/masks its fields;
- aggregate cutoff equals the newest contributing information and remains ≤ decision;
- MASA/PPO ordering failure quarantines the sample;
- archived replay reproduces the same tensor without reading current provider state.

## 7. Feature and tensor reconstruction

Freeze `FEATURE_SPEC` as a generated, versioned contract:

- 477 ordered names;
- source/family for each;
- dtype/unit/range/normalization;
- missing/stale/availability semantics;
- required versus optional/event-dependent;
- per-source time envelope;
- schema/order hash.

The current model vector is exactly:

```text
values[477] || missing[477] || stale[477] || availability[477]
```

The copy must reproduce ordering byte-for-byte for checkpoint parity. Any correction/reorder adds a new schema and incompatible checkpoint lineage.

## 8. Model/training reconstruction

### 8.1 Native model parity

Implement/verify:

- log-like finite normalization;
- input projection and LayerNorm/GELU;
- configured residual blocks/dropout;
- optional four-block attention;
- optional temporal projection/GRU/fusion;
- seven policy logits;
- scalar value, expected move, confidence and MASA heads;
- expected-move action-alignment behavior;
- confidence calibration and 50/50 learned/heuristic MASA blend;
- CPU fallback policy behavior.

Record the observed active 2,048-wide/four-block config separately from 1,024/three-block defaults.

### 8.2 Training parity versus corrected target

Current parity includes immediate `reward - old_value` advantage, hybrid PPO/supervised losses, optimizer recreation, no persistent moments and direct post-step head-bias nudges. A corrected PPO design may use GAE/returns/persistent optimizer, but that is a strategy/PPO change requiring explicit approval and a new model lineage.

Two integrity defects are `DEFECT_NOT_COPIED`, not acceptable parity. Temporal GRU windows must use a required parsed trust-row `decision_time`, sort within symbol/timeframe, and assert every frame time is no later than the target; incoming list position is never a time proxy. A PPO ratio must persist the behavior-action index and behavior-policy transformation/version, then evaluate that same action under the same transformation; supervised hold substitution must remain separate from PPO action identity.

First write golden tests that reproduce current outputs, then fork behavior intentionally.

### 8.3 Labels/costs

Define one signed, side-aware contract:

- raw market move;
- long/short strategy return;
- per-side fee/slippage/funding;
- net realized return;
- side-adjusted MFE/MAE;
- outcome/class/confidence/reward target;
- cost-model version.

Fixing absolute directional labels or 2-versus-12-bps disagreement requires regenerating affected replay and separating old/new evidence.

### 8.4 Splits and promotion

Create immutable sample manifests sorted by decision time:

- training 70%;
- validation 15%;
- untouched holdout 15%;
- embargo around boundaries where labels look forward;
- hashes of exact sample IDs and source snapshots;
- no overlap with any training epoch/cache/H2L candidate;
- evaluation only after the model is frozen.

Promotion must require loadable weight checksum, clean data manifest, generalization/economic/risk thresholds and explicit policy for any override. “Validation guard disabled” or force-promotion must never be represented as ordinary pass.

## 9. Prediction/publication reconstruction

Replace mutable split-brain publication with one typed transaction/result:

```text
build candidate
→ validate temporal/model contract
→ write durable archive
→ write replay snapshot
→ write prediction
→ publish downstream lineage
→ return complete success/failure receipt
```

No downstream lineage on any required-write failure. IDs/keys alone are not write proof. Include per-write result, hash and time. Status counts successful publication, not payload construction.

## 10. Decision, risk and paper reconstruction

Define one immutable proposal and one immutable risk decision:

```text
Prediction → OrchestratorProposal (not approved)
           → RiskDecision(action=ALLOW|DENY, exact proposal hash)
           → PaperAdmission / LiveAdmission
```

Paper and live admission must both require exact matched `ALLOW`, not ID presence.

Create one paper fill-write boundary. Every candidate passes:

1. prediction/replay/archive trust;
2. exact orchestrator/risk match and allow;
3. strategy/pre-trade/cost/A+/temporal policy;
4. tier and sizing;
5. churn/exposure/portfolio freeze;
6. preemptive loss/admission;
7. valid position state-machine transition;
8. fill invariant and idempotency;
9. lifecycle/accounting initialization;
10. on-policy PPO entry stamping when applicable;
11. execution timestamp and immutable receipt.

Confidence may be a model input to approved policy, but it must not mutate arbitrary denial reasons or jump past invariant stages.

Golden negative tests:

- risk deny/missing/stale/mismatched proposal;
- long→long without close;
- duplicate prediction/signal/same candle;
- incomplete size;
- frozen portfolio/new-entry block;
- missing fee/edge/loss probability;
- stale/future/unfinished data;
- archive/replay failure;
- double fill/retry;
- partial lifecycle/accounting write;
- close/reduce/hedge transition validity.

## 11. Live transport boundary

The reconstruction should omit/mask live callers until a separate explicitly approved live program exists. Preserve source for review, but enforce:

- build-time non-live profile;
- absent live credentials from paper services;
- masked/absent submitter units;
- release/live/armed/symbol/risk/state-machine/dedupe checks;
- fake adapter in automated tests;
- network-level inability for non-live workers to reach private order endpoints;
- human-controlled two-person activation and rollback procedure.

No live activation instructions belong in this blueprint.

## 12. API/security/client reconstruction

### Backend

- one canonical import namespace;
- declared auth/security in OpenAPI;
- real middleware or removal of scaffolds;
- route-by-route mutation/auth/idempotency inventory;
- durable multi-process-safe users/revocations/tasks;
- explicit production environment defaults that fail closed;
- structured centralized logs/metrics/traces;
- readiness for Redis/providers/trainer, not just liveness.

### Web/mobile

- generated API schema/client where practical;
- pinned frontend lockfile and reproducible dist;
- explicit runtime-asset build manifest;
- one Swift API/model layer shared by iOS/watch/CLI;
- backwards-compatible field/version rollout;
- public origin/CORS/tunnel configuration captured and tested.

### Credentials

- rotate the currently exposed tunnel credential;
- use protected systemd credentials/files with least-privilege modes;
- keep values out of Git/process args/logs;
- document key names, provider, owner, rotation and dependent units;
- test missing/expired/revoked behavior without printing values.

## 13. Observability and recovery target

Each authority emits:

- structured event with schema/version/release;
- heartbeat with source event time and generated time;
- success/failure counters;
- latency/freshness/capacity;
- stable IDs/hashes for correlation;
- bounded logs with centralized collection;
- alert route proven end-to-end.

Minimum recovery exercises:

1. restore Redis to isolated instance and validate key/schema/count/checksums;
2. restore SQLite through backup API and validate integrity/logical counts;
3. load model/checkpoint by checksum and reproduce golden inference;
4. rebuild replay index/manifest and reproduce tensor/label;
5. deploy prior immutable release and prove rollback;
6. rebuild frontend dist from lockfile and match content hash;
7. restore auth users/revocations without exposing secrets;
8. recreate all units/timers from manifest on a clean account;
9. recreate tunnel route with a new credential;
10. survive Redis/process/host restart without invalid fills or dirty training.

## 14. Build stages and gates

### Stage 0 — freeze and capture

- record commit/worktree, effective units/drop-ins, packages, configs, key/type/TTL stats and storage layout;
- export provider/tunnel routing metadata and secret-name manifest;
- create verified backups;
- mark current source/runtime evidence immutable.

**Gate:** another engineer can enumerate all external inputs without accessing the old host interactively.

### Stage 1 — reproducible skeleton

- build pinned environment, immutable releases, canonical import root, Redis and empty state directories;
- install only liveness/API with fake data.

**Gate:** clean-host install/remove/reinstall is idempotent and hashes match.

### Stage 2 — read-only ingestion

- provider/exchange readers, canonical time envelopes, closed-candle storage and coverage.

**Gate:** finality/PIT tests and multi-day soak, no mutation credentials present.

### Stage 3 — features/archive/replay

- reproduce 477 fields/1,908 tensor, per-source lineage and durable archive.

**Gate:** golden snapshot/tensor hashes and injected future/stale/write-failure rejection.

### Stage 4 — model/trainer shadow

- load known checkpoint and reproduce inference; train only on immutable clean manifests.

**Gate:** deterministic golden outputs, no holdout overlap, load/checksum/rollback proof.

### Stage 5 — decision/risk/paper

- orchestrator proposal, risk authority, single paper admission boundary, lifecycle/accounting.

**Gate:** branch-complete negative tests and long non-live soak with zero invalid transitions/fills.

### Stage 6 — API/web/mobile/security

- production auth/durable stores, explicit route security, generated clients/builds and tunnel.

**Gate:** security tests, multi-worker races resolved, reproducible dist/client compatibility.

### Stage 7 — operations/recovery

- complete units, monitoring, bounded retention, backup/restore, upgrade/rollback.

**Gate:** clean-host disaster-recovery and controlled restart drills pass.

### Stage 8 — independent audit

- regenerate atlas; compare every entrypoint/key/field/route/model contract; review deviations.

**Gate:** no undocumented external state or unexplained parity difference. Live remains out of scope until separately approved.

## 15. Parity ledger

For every current behavior classify:

| Classification | Meaning |
|---|---|
| `PARITY_REQUIRED` | reproduce exactly and test |
| `PARITY_WITH_VERSION_FORK` | reproduce old path for history, new corrected behavior under a new schema/model version |
| `DEFECT_NOT_COPIED` | proven unsafe behavior blocked in target with explicit test |
| `HISTORICAL_ONLY` | preserve evidence/source but do not install |
| `EXTERNAL_REQUIRED` | provider/credential/cloud/hardware input needed |
| `UNKNOWN_NEEDS_DECISION` | insufficient evidence; cannot assume |

Examples:

- closed-candle selection: `PARITY_REQUIRED` plus stronger per-source availability;
- 477 field ordering for old checkpoint: `PARITY_REQUIRED`;
- risk-ID-existence-as-allow: `DEFECT_NOT_COPIED`;
- high-confidence invariant bypass: `DEFECT_NOT_COPIED` unless explicitly approved as a versioned research policy;
- absolute directional replay label: `PARITY_WITH_VERSION_FORK` for historical reproducibility, corrected for new data;
- dormant live submitter units: `HISTORICAL_ONLY`/separately approved scope;
- Cloudflare route: `EXTERNAL_REQUIRED`;
- duplicate trainers/publishers: `UNKNOWN_NEEDS_DECISION`.

## 16. Definition of reconstructed

The system is reconstructed only when a clean host can be built from versioned declarations and protected secret references, then demonstrate:

- every supported service installed from the manifest;
- every input/output contract identified;
- exact timestamp lineage and closed-candle proof;
- golden 477/1,908 tensor parity;
- exact checkpoint/weight identity and reproducible inference;
- clean, non-overlapping training/evaluation data;
- risk deny and invalid transition fail closed;
- paper lifecycle/accounting reconciliation;
- API/web/mobile compatibility;
- bounded storage and observable failures;
- successful backup/restore/rollback;
- regenerated atlas with no unexplained high-risk edge;
- no real order capability enabled.

Anything less is a partial port, not a copy of the system.
