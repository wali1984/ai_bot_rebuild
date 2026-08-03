# Configuration keys, contracts and change impact

**Generated inventory:** 2026-07-16 static atlas

**Purpose:** answer “where is this key/field/function/route used and what will a change affect?” without pretending that a manually curated table can stay complete in a 9,272-path, actively changing repository.

The canonical low-level registries are the JSON artifacts in `../atlas/`. This document defines their meaning, query procedure and safety limits. The expanded JSON is intentionally ignored by Git because it is deterministic and hundreds of megabytes; regenerate it after a material source change.

## 1. Inventory coverage

| Surface | Records | Canonical artifact |
|---|---:|---|
| Tracked paths | 9,272 | `FILE_MODULE_CATALOG.json` |
| Python module/function/class/method symbols | 32,272 | `PYTHON_SYMBOL_CATALOG.json` |
| TypeScript/JavaScript symbols | 3,334 | `TYPESCRIPT_JAVASCRIPT_ATLAS.json` |
| Swift declarations | 693 | `SWIFT_SYMBOL_CONTRACT_CATALOG.json` |
| Shell functions | 116 | symbol/entrypoint records |
| Python import edges | 25,389, 8,708 internal-resolved | `PYTHON_IMPORT_GRAPH.json` |
| Python call references | 161,112, 38,744 internal-resolved | `PYTHON_CALL_GRAPH.json` |
| Declared contracts | 1,807 | `DATA_CONTRACTS.json` |
| Field names | 39,538 | `DATA_CONTRACT_FIELD_REGISTRY.json` |
| Environment key names | 2,918 | `CONFIG_ENV_REGISTRY.json` |
| Redis key patterns | 2,040 | `REDIS_KEY_USAGE_REGISTRY.json` |
| API definitions/references | 905 | `API_ROUTE_REGISTRY.json` |
| Exchange-mutation references | 37 | `EXCHANGE_MUTATION_REFERENCE_REGISTRY.json` |

Counts describe static records, not unique runtime instances. The API registry includes server and client/reference sites; it is not the same as current OpenAPI’s 193 HTTP operations.

## 2. File and module catalog

`FILE_MODULE_CATALOG.json` separates two schemas. `files[]` records every tracked
path with source stratum, language/kind, bytes, line count and SHA-256.
`python_modules[]` records Python parse status/error plus module-level constants,
imports, aliases, environment/Redis/API/exchange references and main-guard state.
Parse status is not a `files[]` field.

Use it to answer:

- Is this file versioned or generated/ignored?
- Is it active backend source, preserved legacy, test, evidence, client or deployment tooling?
- Did the parser see the exact content/hash I am changing?
- Is a “duplicate” actually byte-identical or merely similarly named?
- Which files could not be parsed?

Two parse failures are confined to preserved legacy microstructure files with existing indentation errors. No active first-party backend parse failure was found in the runtime trace.

Query examples:

```bash
jq '.files[] | select(.path == "v2/backend/app/cli/v2_trade_management_paper_loop.py")' \
  docs/system_audit_2026_master/atlas/FILE_MODULE_CATALOG.json

jq '.python_modules[] | select(.parse_error != null)' \
  docs/system_audit_2026_master/atlas/FILE_MODULE_CATALOG.json
```

Check the actual top-level array/key with `jq 'keys'` after a schema-version change.

## 3. Python symbol catalog

Each symbol ID is stable within a scanned source snapshot and has this form:

```text
relative/path.py:<module>
relative/path.py:ClassName@line_start
relative/path.py:ClassName.method@line_start
relative/path.py:function@line_start
relative/path.py:outer.nested@line_start
```

The `@line_start` suffix disambiguates non-module definitions and can change when
source lines move; “stable within a snapshot” does not mean stable across edits.

Records retain:

- path, line/end line and qualified name;
- kind, signature/arguments, decorators and docstring summary;
- nested definitions as separate qualified symbol records;
- raw call expressions;
- environment reads;
- Redis reads/writes;
- mapping/data fields read and written;
- decorator text plus network/subprocess/filesystem/exchange side-effect markers.

Resolved caller/callee edges do not live in the symbol record; use
`PYTHON_CALL_GRAPH.json` and `CHANGE_IMPACT_INDEX.json`. Imports are module-level
records in `PYTHON_IMPORT_GRAPH.json` and `FILE_MODULE_CATALOG.json` rather than
per-symbol fields. Keeping those schemas separate prevents a missing field from
being mistaken for “no dependency.” Contract/field declarations are normalized
in `DATA_CONTRACTS.json` and `DATA_CONTRACT_FIELD_REGISTRY.json`; route
definitions/references are normalized in `API_ROUTE_REGISTRY.json`.

`<module>` is behavior too: imports can create files, initialize locks/caches, read environment or register routes. Auth currently creates/loads process-secret state during import, so module scope must not be ignored.

Unresolved calls remain in the graph. A call can be unresolved because it is external, injected, dynamic, an instance method whose type is unknown, or constructed by reflection. “Unresolved” is a manual-review flag, not proof that there is no downstream behavior.

## 4. Import and call graphs

### 4.1 Imports

`PYTHON_IMPORT_GRAPH.json` records importer, raw imported name, relative-import level, resolved internal target where possible and confidence.

Special system risk: imports mix `app.*` and `v2.backend.app.*`. Effective systemd `PYTHONPATH` varies, including invalid truncated values. A refactor that normalizes imports can change module identity and duplicate/collapse global state. Review effective unit environments before changing imports.

### 4.2 Calls

`PYTHON_CALL_GRAPH.json` records caller symbol, raw call expression and resolved callee where statically possible. Resolution is direct/static only. Framework dispatch, dependency injection, FastAPI callbacks, Redis pub/sub, systemd, subprocesses and filesystem polling form implicit edges outside the call graph.

For a behavioral change:

1. inspect direct callers;
2. inspect callers of callers until reaching entrypoints or API handlers;
3. inspect unresolved/external calls in each affected symbol;
4. inspect side effects and shared state;
5. add non-code edges from Redis, files, routes, units and timers.

## 5. Configuration registry

`CONFIG_ENV_REGISTRY.json` has:

- `metadata` — schema/provenance/counts;
- `environment_keys` — each key name and all source sites;
- `static_configuration_files` — versioned config-like files and references;
- `security_note` — redaction/secret handling.

An environment site includes path, line, symbol and a safe-default state. Defaults are present only when statically recoverable and safe. Secret-like defaults/values are redacted; `.env` and other secret-like artifacts are excluded. The registry tells you a key name is consumed, not what value is deployed.

Example:

```bash
jq '.environment_keys[] | select(.key == "V2_TRAINER_HIDDEN_SIZE")' \
  docs/system_audit_2026_master/atlas/CONFIG_ENV_REGISTRY.json
```

### 5.1 Config precedence

For any key, determine effective precedence in this order:

1. explicit constructor/function argument;
2. process environment from effective systemd unit and every drop-in;
3. `EnvironmentFile` values;
4. launcher shell exports;
5. application environment loader/`.env` handling;
6. source default;
7. derived/adaptive override;
8. hard-coded branch value.

Do not assume an environment key controls behavior merely because it is reported in status. The persistent trainer has target settings while parts of its adaptive controller use hard-coded bands; `PPO_GAMMA` is read/reported but not used to build native returns.

### 5.2 Config impact classes

| Class | Examples | Required review |
|---|---|---|
| Deployment | ports, paths, worker counts, `PYTHONPATH` | units/drop-ins, clients, module identity, rollback |
| Temporal/data | TTL, finality, max age, cutoff, provider freshness | PIT tests, replay/history, dirty-sample gate |
| Schema/model | feature list, width, blocks, encoder/action count | input/order, checkpoint fork, GPU, clients |
| Training | LR, entropy, epochs, batch, replay/holdout | algorithm meaning, clean split, promotion evidence |
| Strategy/risk/paper | confidence, edge, fee, tier, size, loss caps | explicit operator approval, branch/invariant tests |
| Live execution | release/live/armed/dry-run/symbol/notional/order flags | explicit live approval; do not modify under this audit |
| Persistence/retention | Redis memory, archive root, rollover limits | backup/restore, deletion manifest, reader coordination |
| Auth/security | secret, cookie, role, MFA, store backend, origins | credential rotation, multi-worker/durable-state review |

## 6. Redis key registry

`REDIS_KEY_USAGE_REGISTRY.json` contains `keys`, each grouping a normalized key pattern with literal/formatted references, operation, access classification, path, line, symbol and client expression. The scanner records known `get`/`set`/list/hash/stream/publish/delete/expire operations and retains literal declarations whose access could not be inferred.

Example:

```bash
jq '.keys[] | select(.key_pattern | contains("v2:prediction"))' \
  docs/system_audit_2026_master/atlas/REDIS_KEY_USAGE_REGISTRY.json
```

### 6.1 Key contract dimensions

Every Redis key must be documented by:

- exact pattern and placeholder normalization (symbol/timeframe/ID/cycle);
- data type: string JSON, hash, list, set, sorted set, stream, counter or lock;
- producer(s) and sole-authority rule;
- consumers;
- schema version and required fields;
- timestamp semantics;
- TTL/retention and refresh behavior;
- dedupe/idempotency;
- atomicity/transaction expectation;
- error/fallback behavior;
- eviction/loss consequence;
- migration/dual-read/dual-write plan;
- privacy/credential content classification.

The static registry cannot reliably infer a runtime type or TTL for every dynamically built key. Confirm with source and safe `TYPE`, `TTL` and `MEMORY USAGE` commands; do not dump values indiscriminately.

### 6.2 Redis change impact

A key rename or field change must coordinate:

1. all writers;
2. all direct/static readers;
3. dynamic scan-pattern readers;
4. Lua/pipeline/transaction use;
5. public artifact publishers;
6. tests/fixtures;
7. TTL/status monitors;
8. backward-compatible migration;
9. cleanup only after old-reader proof;
10. capacity and eviction impact.

Redis is currently near its configured limit with `allkeys-lru`; adding an unbounded key family is a production-impacting change even in non-live mode.

## 7. Data contracts and fields

`DATA_CONTRACTS.json` inventories Python dataclasses, TypedDicts and Pydantic-like declarations, plus TypeScript and Swift interface/model contracts. `DATA_CONTRACT_FIELD_REGISTRY.json` groups every field name with declaration/write sites, read sites and a temporal-semantic marker.

Example:

```bash
jq '.fields[] | select(.field == "feature_cutoff")' \
  docs/system_audit_2026_master/atlas/DATA_CONTRACT_FIELD_REGISTRY.json
```

The same field name can have unrelated meanings in different contracts. Join on path/symbol/contract, not name alone.

### 7.1 Temporal fields

The atlas flags names such as:

- `event_time`;
- `ingested_at`;
- `available_at`;
- `generated_at`/`generated_utc`;
- `feature_cutoff`;
- `decision_time`;
- `execution_time`.

Before renaming or deriving any of them, trace feature snapshot, tensor, prediction, archive/replay, orchestrator, risk, paper lifecycle, feedback, tests, API and clients together. A compatibility alias that maps two different meanings is worse than a hard failure.

### 7.2 Schema evolution rules

- Additive optional fields need explicit default/null/missing behavior in Python, TypeScript and Swift.
- Required fields require producer-first/client-compatible rollout or version fork.
- Numeric zero must not be conflated with absent/null.
- Enums/actions must preserve stable numeric/index mapping.
- Field removal requires proof that all consumers have migrated.
- Temporal/lineage fields must never be fabricated to satisfy a validator.
- Training-label changes require a dataset schema/version fork and regeneration boundary.
- Model-input order changes require checkpoint incompatibility/fork, even when dimension is unchanged.

## 8. API route registry

`API_ROUTE_REGISTRY.json` contains `routes_and_references`: backend decorators/handlers and web/mobile/string references. Use it to find server and client dependencies for a path.

```bash
jq '.routes_and_references[] | select((.path // .route // "") | contains("live"))' \
  docs/system_audit_2026_master/atlas/API_ROUTE_REGISTRY.json
```

Confirm current server truth with `/openapi.json`, but remember:

- WebSockets may not appear;
- OpenAPI declares no security despite route dependencies;
- mounted SPA/static routes and health aliases differ;
- dynamically generated paths can escape static scanning;
- client string presence does not prove the route is called;
- the V2 API has mutations despite read-only descriptions.

For a route change review method/path, auth dependency, middleware, request/response contract, Redis/file/process side effects, idempotency, multi-worker behavior, TypeScript/Swift clients, CORS/tunnel routing, tests and backwards compatibility.

## 9. Entrypoints and services

`ENTRYPOINT_SERVICE_REGISTRY.json` separates:

- `python_main_guards`;
- `shell_entrypoints`;
- `package_scripts`;
- `make_targets`;
- `systemd_units`.

This is the versioned entrypoint inventory. It does not include every installed unit/drop-in under `/home/wali/.config/systemd/user`, so deployed impact analysis must compare both sets.

An entrypoint change affects:

- import namespace and current working directory;
- environment/default precedence;
- process ownership/restart semantics;
- concurrency/duplicate authority;
- output/log/state paths;
- timers/dependencies;
- graceful shutdown and partial writes;
- active mutable-repo versus release provenance.

## 10. Exchange-mutation registry

`EXCHANGE_MUTATION_REFERENCE_REGISTRY.json` contains source references whose call names match order/cancel/modify/leverage/margin/transfer operations. It intentionally includes tests, stubs and blocked paths; every record requires manual classification.

```bash
jq '.references[] | select(.path | startswith("v2/backend/app/"))' \
  docs/system_audit_2026_master/atlas/EXCHANGE_MUTATION_REFERENCE_REGISTRY.json
```

Classify each as:

- real adapter/transport;
- caller/entrypoint/API;
- paper-only simulation;
- test/stub;
- preserved legacy;
- documentation/reference.

Any edit to a real adapter or reachable caller requires explicit operator approval. “Service inactive” is not a code-level safety proof.

## 11. Change-impact index

`CHANGE_IMPACT_INDEX.json` has seven maps:

- `modules`;
- `symbols`;
- `environment_keys`;
- `redis_keys`;
- `data_fields`;
- `api_routes`;
- `metadata`.

A module record includes hash/LOC/stratum, symbols, internal dependencies, direct importers and importing tests, config, Redis/data/API/exchange surfaces and side effects. A symbol record includes direct callers, resolved callees, unresolved/external calls and its state surfaces.

### 11.1 Exact procedure for a function change

1. Select the symbol record by `symbol_id`.
2. Read the source range and every exit/exception/fallback path.
3. Traverse `direct_callers` upward to entrypoints, jobs and routes.
4. Traverse `resolved_callees` downward to side effects.
5. Inspect `unresolved_or_external_calls` manually.
6. Select its module record for importers and tests.
7. Join every Redis key, env key, field and API surface to their reverse registries.
8. Search installed systemd effective commands for the module/symbol family.
9. Trace public artifact, TypeScript and Swift consumers.
10. Classify temporal, training, risk, position and live-execution implications.
11. Write isolated negative tests and an explicit rollback.
12. Regenerate the atlas and diff affected reverse edges.

### 11.2 Exact procedure for a field/key/config change

Start from its dedicated index, collect all sites, then map each site back to module/symbol impact. Do not start from text replacement alone: one key name can be built dynamically and one field name can belong to multiple contracts.

### 11.3 Recursive impact

The index is intentionally direct, not a precomputed infinite transitive closure. Recurse until you reach:

- a process entrypoint/timer/API/client;
- a durable state boundary;
- an external provider/exchange;
- a user-visible artifact;
- a training/promotion decision;
- a fill/position/accounting boundary.

Record cycles and shared hubs. The symbol-universe module, unified Binance transport, feature schema/trust modules, publisher, orchestrator schema and paper loop are high-centrality surfaces.

## 12. Worked impact examples

### 12.1 Change `FEATURE_SPEC`

Impacts ordered snapshot extraction, values/masks/availability, input dimension/order, model architecture ID, NPZ shapes, checkpoint load, replay/cache reconstruction, status fields, inference, prediction IDs and all downstream decisions. Even a reorder with the same 477 length silently changes semantic weights and must fork the checkpoint/schema.

### 12.2 Change `feature_cutoff`

Impacts canonical MTF snapshot, data loader, tensor trust, prediction, archive/replay, MASA/PPO ordering, orchestrator/risk/paper validation, feedback, holdout and UI explainability. Correcting minimum to a truthful newest-information boundary requires keeping the per-timeframe/per-source vector and versioning affected evidence.

### 12.3 Change risk action semantics

Impacts risk gateway writer, orchestrator provisional lineage, paper dereference and every admission classifier/owner/invariant, exploration policy, live transport, lifecycle, tests and dashboards. Current code often checks ID presence instead of allow; a local risk-gateway edit alone will not fix paper control authority.

### 12.4 Change a confidence threshold

Impacts far more than presentation. Current thresholds can override strategy, pre-trade, fee, A+, temporal, tier, direction, sizing, churn, portfolio freeze and preemptive loss gates, and a 0.65 threshold selects a shortcut that omits PPO stamping and invariants. Treat it as strategy/risk/training behavior requiring approval.

### 12.5 Change Redis TTL/retention

Impacts reader fallback, keyspace/memory/eviction, freshness/status, replay reproducibility and incident evidence. Removing a TTL can exhaust Redis; shortening it can make downstream workers fabricate missing/default state; deletion can invalidate manifests/holdout/paper investigations.

### 12.6 Change backend worker count

Impacts process-local auth/user locks, revocation/cache state, metrics history, WebSocket/resources and race frequency. It does not repair file-store concurrency and can change which worker’s in-memory state a request sees.

## 13. Static-analysis limits

The atlas is a lower bound because it cannot prove:

- runtime configuration values;
- installed unit/drop-in/cloud state;
- dynamically assembled Redis keys or import paths;
- dependency-injection and framework callback targets;
- shell/subprocess behavior hidden in strings;
- provider-side schema and timing;
- whether a branch is reachable under current data;
- concurrency, atomicity and race behavior;
- whether a status write succeeded;
- semantic correctness of a field with a familiar name.

The Swift and shell catalogs use conservative line/brace heuristics. Always open the cited source line.

## 14. Regeneration and acceptance

```bash
python3 tools/build_system_reverse_engineering_atlas.py \
  --repo-root . \
  --out-dir docs/system_audit_2026_master/atlas
```

Accept only if:

- start/end Git HEAD match;
- `snapshot_consistent` is true;
- secret-like paths/values remain excluded;
- Python/Node/self-tests pass;
- parse failures are understood;
- counts/diffs are reviewed;
- newly unresolved edges or exchange references are classified;
- human docs are updated for semantic changes.

The machine index answers “where.” The source trace and tests answer “what it means.” The runtime snapshot answers “what is active now.” All three are required before changing this system safely.
