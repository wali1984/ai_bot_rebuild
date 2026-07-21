# AI Bot V2 system technical reference

**Reconstructed:** 2026-07-16

**Runtime evidence:** audited workstation, read-only observation 2026-07-16 America/New_York

**Current safety mode:** non-live/paper-shadow; real exchange mutation code exists but no active authorized submitter was observed

**Recommendation:** live NO-GO; current paper/training evidence is not clean enough for promotion.

This reference describes implementation, not aspiration. It supersedes the 2026-07-11 version, which was already stale. Function-level details are generated in `docs/system_audit_2026_master/atlas/`; operational procedures are in the master operator manual.

## 1. How to use this reference

Three evidence planes must agree:

1. **Source plane:** tracked files and the static atlas.
2. **Deployment plane:** effective installed systemd units/drop-ins, working directories, commands and environments.
3. **State plane:** Redis, disk, model/archive, API, process and provider observations at a specific time.

Do not infer deployment from a unit file in Git or behavior from a service name. Do not infer success from a heartbeat/status write. Do not infer risk approval from an identifier. Do not infer temporal validity from a field called `feature_cutoff` without checking how it was derived.

The exhaustive static atlas covers 9,272 tracked paths, 32,272 Python symbols, 3,334 TypeScript/JavaScript symbols, 693 Swift symbols, 161,112 call references with 38,744 resolved, 25,389 imports with 8,708 resolved, 1,807 contracts, 905 API definition/reference records, 2,918 env keys, 2,040 Redis patterns and 39,538 field names.

Canonical artifacts:

```text
docs/system_audit_2026_master/atlas/
  FILE_MODULE_CATALOG.json
  PYTHON_SYMBOL_CATALOG.json
  PYTHON_IMPORT_GRAPH.json
  PYTHON_CALL_GRAPH.json
  TYPESCRIPT_JAVASCRIPT_ATLAS.json
  SWIFT_SYMBOL_CONTRACT_CATALOG.json
  DATA_CONTRACTS.json
  DATA_CONTRACT_FIELD_REGISTRY.json
  CONFIG_ENV_REGISTRY.json
  REDIS_KEY_USAGE_REGISTRY.json
  API_ROUTE_REGISTRY.json
  ENTRYPOINT_SERVICE_REGISTRY.json
  EXCHANGE_MUTATION_REFERENCE_REGISTRY.json
  CHANGE_IMPACT_INDEX.json
  ATLAS_BUILD_MANIFEST.json
```

`ATLAS_BUILD_MANIFEST.json` is published last as the generation commit marker.
It records source/analyzer provenance and the size/SHA-256 of every staged atlas
artifact; validate the machine catalogs against it before consuming them.

## 2. Repository architecture

```text
v2/backend/app/
  adapters/            external/storage/integration adapters
  api/                 FastAPI v1/v2/auth routes and middleware
  auth/                user store, token, revocation and role logic
  cli/                 hundreds of service/job entrypoints
  composition/         dependency composition/builders
  core/                shared primitives
  domain/              contracts/value/state models
  services/            feature/model/risk/paper/live/business logic
  closed_loop/         automation lease/task state

v2/frontend/           React/TypeScript/Vite application
v2/mobile/             SwiftUI iOS/watch and CLI package
v2/scripts/            deployment/validation scripts
v2/ops/                partial CI/ops scaffolding
tools/                 operational and atlas tooling
claude_worklog/         large automation/evidence/runtime corpus
legacy_reference/       historical legacy system inputs
docs/                   canonical and historical documentation
```

The first-party backend trace found 1,181 application modules and about 423,000 lines. The paper loop and large market API modules are unusually monolithic. Preserved legacy code is not automatically inactive: two deployed CoinAnk units call direct legacy-style scripts.

### Import-root defect

Source mixes `app.*` and `v2.backend.app.*`; active processes use both. With different cwd/PYTHONPATH, Python can load one physical file twice under two module identities, duplicating module globals, locks, caches, classes, registries and import-time side effects. Eight installed unit files also contain invalid unquoted `PYTHONPATH` paths with spaces.

## 3. Effective deployed topology

At the main operations snapshot:

- 157 installed `ai-bot*` user units;
- 81 running services;
- 36 active timers in the earlier trace and 35 on direct recheck;
- 3 failed services;
- 57 installed basenames absent from versioned unit directories and 33 versioned names not installed;
- 10 failure-masking service wrappers and 83 `Restart=always` declarations;
- duplicate portfolio publisher processes;
- persistent CUDA and continuous offline GPU trainers active concurrently.

The detailed service/timer inventory is in `docs/system_audit_2026_master/components/RUNTIME_PROCESS_AND_DEPLOYMENT.md`.

Core runtime:

```text
providers/exchanges
 → Redis raw/derived market plane
 → native feature/TA/context/snapshot workers
 → persistent native trainer + offline candidate trainer
 → prediction/all-timeframe publishers
 → orchestrator
 → risk gateway records
 → paper trade-management/lifecycle/accounting
 → portfolio/guardian/outcomes/replay/feedback
 → API/public artifacts/web/mobile
```

Effective backend is four Uvicorn workers on `127.0.0.1:8000` from mutable repo `v2/backend`; drop-ins override the older immutable release symlink. Effective frontend is Vite preview on `0.0.0.0:5173`, serving ignored prebuilt `dist`. Public routing is Cloudflare-side external state.

## 4. Time and lineage contract

### 4.1 Canonical meanings

| Field | Meaning |
|---|---|
| `event_time` | Economic/source time the fact occurred. |
| `ingested_at` | Time this system received or first persisted it. |
| `available_at` | Earliest time the exact fact was safe for a consumer. |
| `generated_at` | Time a derived record was computed/published. |
| `feature_cutoff` | Newest information actually represented; preserve per-source/timeframe cutoffs too. |
| `decision_time` | Immutable policy-decision cutoff. |
| `execution_time` | Paper/live materialization or exchange acknowledgment time. |

Required order:

```text
source event/finality → ingestion/availability
all contributing close_time <= decision_time
all contributing available_at <= decision_time
truthful feature_cutoff <= decision_time
MASA feature_cutoff <= PPO decision_time
decision_time <= execution_time
```

`generated_at` is not a substitute for event, available, decision or execution time.

### 4.2 Canonical trust code

Principal modules:

- `services/market_state_integrity/canonical_candles.py`
- `services/market_state_integrity/trust.py`
- `services/market_state_integrity/sample_rejection.py`
- `services/market_state_integrity/scoring.py`
- `services/market_state_integrity/validators.py`

`TRUST_SCHEMA_VERSION` is `pipeline_trust_v3`, with an enforcement epoch. `ACTIVE_TRUST_REQUIRED_FIELDS` includes decision/prediction/MTF/replay IDs, cutoff, availability and all timeframe timestamps. Active flags span prediction/risk/paper/trainer usage.

Canonical candle/aligner code rejects future availability/cutoff, unfinished/missing required candles, gaps/latency and MASA/PPO ordering violations. This is the strongest point-in-time layer.

### 4.3 Temporal gaps

- current Redis enrichment values are merged without all per-source availability/cutoff checks;
- list/REST candle arrays use close time without explicit finality/receipt time;
- provider bridge can accept missing timestamps/stale values;
- MTF scalar cutoff uses the minimum selected close, understating newer information;
- publisher can set top-level decision time to publication time while preserving original separately;
- source availability bits mostly mean a numeric value exists;
- native prediction lineage lacks one canonical execution time until later paper paths.

End-to-end point-in-time safety is therefore incomplete even though canonical candle tests are strong.

## 5. Market/provider ingestion

Source families under `app/cli`, adapters and provider services ingest:

- Binance USDM/COINM klines, aggregate trades, order book and liquidations;
- KuCoin public market state;
- CoinAPI WebSocket/REST;
- CoinAnk derivatives context;
- CoinGlass, Santiment, Moralis, Nansen, LunarCrush, AICoin and public-intel/news sources;
- derived funding/OI/long-short, microstructure and liquidation state.

Current deployment is read-only at these market-data boundaries, but credentialed providers exist. A provider health record must include source event/receipt/availability/generated times, symbol/timeframe, finality, schema/hash, rate/latency and missing/stale reasons. Credential presence is not health.

Typical state families include `v2:market:*`, `v2:orderbook:*`, `v2:microstructure:*`, `v2:liquidations:*`, `v2:features:*`, provider-specific and context keys. Use the Redis atlas for exact producer/consumer sites.

## 6. Candle finality and MTF snapshot

`canonical_candles.py` recognizes explicit closed flags (including WebSocket finality), parses close and availability, and builds the required 1m/5m/15m/1h/4h decision snapshot. `_latest_available_closed_candle_at_or_before` chooses a final available candle no later than decision.

`build_multi_timeframe_decision_snapshot` records selected candle IDs/open/close/availability/event/source/hash and rejection reasons. At lines around 468-473 it currently chooses `min(close_times)` as scalar `feature_cutoff`; this is a known semantic defect if the field means newest information. The full selected-candle vector remains necessary even after correcting it.

The native feature loop’s `_closed_klines`:

- requires explicit closed flags for dict rows;
- rejects dict availability later than decision;
- accepts list rows with at least seven values using the close timestamp at index 6;
- includes rows whose close is no later than decision.

List rows cannot prove the final value’s actual ingestion/availability.

## 7. Native feature pipeline

Primary entrypoint: `cli/v2_feature_pipeline_native_loop.py`.

`run_once`:

1. captures current generation/decision time;
2. reads raw/canonical closed klines;
3. builds market state and derived OHLCV/TA/cost features;
4. reads orderbook, OI, long-short and liquidation evidence;
5. merges A+ context and external V2 features;
6. marks missing/stale core fields and candle finality;
7. constructs a `v2_native_feature_snapshot_v1` payload;
8. adds provider consumer context when available;
9. hashes the payload into a snapshot ID;
10. writes latest, archive and related feature/TA surfaces with TTLs.

Snapshot core fields include symbol/timeframe, feature map/counts, missing/stale flags, finality/open/close, source event/received/available, feature cutoff, decision estimate, external source names/count, cost evidence, live block and generated times.

### Enrichment gap

`_merge_a_plus_context_features` and `_merge_external_v2_features` read latest Redis HTF/cross-asset/regime/tape/TA/liquidation/unified/orderbook/WSDS/microstructure/alternative data and merge numeric fields. They do not preserve and gate a complete source envelope per contributing value before merge. `run_once` then stamps aggregate receipt/availability/generated as current time. Historical/as-of reconstruction can therefore attach present state to older candle context.

Provider context built with a decision time is better, but missing timestamps/freshness rules are not uniformly fail-closed and optional exceptions are swallowed.

## 8. Feature and tensor contract

The authoritative ordered contract is `services/native_trainer/hybrid_cuda_trainer/tensor_builder.py::FEATURE_SPEC` with **477 feature slots**.

Model vector:

```text
values[477]
|| missing_mask[477]
|| stale_mask[477]
|| source_availability[477]
= 1,908 inputs
```

For each feature, the builder resolves prioritized source values, converts finite numeric values, inserts zero only as a placeholder when missing and sets masks. Important caveats:

- truthiness `a or b` fallback can replace a valid zero;
- family-level stale markers may not match every field name;
- availability is numeric presence, not temporal proof;
- current source state cannot safely reconstruct an archived historical tensor unless archived source context is complete;
- tensor/snapshot IDs do not independently encode the full temporal envelope.

Any feature addition/removal/reorder affects snapshot schema, input dimension/order, architecture/checkpoint compatibility, replay/cache, prediction identity, status, tests and every downstream policy. Reorder with unchanged length is still incompatible.

### Parallel snapshot abstractions

Domain feature models under `domain/features/*` and `services/feature_snapshots/*` are distinct from the active native snapshot in the CLI/data loader. API/domain schema names must not be assumed to describe native trainer input.

## 9. Dataset and dirty-sample admission

Principal sources:

- `hybrid_cuda_trainer/data_loader.py`
- `market_state_integrity/sample_rejection.py`
- `native_trainer/feedback_enrichment.py`
- `native_trainer/trusted_replay/dataset.py`
- `native_trainer/trusted_replay/bootstrap.py`

The loader combines fresh prediction examples, trusted replay/backfill/frontier rows and closed feedback. Correct gates reject future availability/cutoff, invalid/unfinalized MTF/replay lineage, missing price targets, non-finite required values, stale mandatory features and explicit quarantine/coverage failures.

Weaknesses:

- high-confidence feedback logic can remove missing-trust rejection reasons;
- optional/cost/schema-evolution masked rows can remain trainable;
- historical REST receipt timing can be fabricated from close time;
- a rebuilt closed-trade path does not uniformly re-run the complete final classifier;
- normal training does not enforce persistent holdout boundaries/IDs.

“Missing masked” is not globally dirty, but temporal/required lineage must never be waived as if optional data.

## 10. Native model

Primary source: `hybrid_cuda_trainer/model.py`.

### 10.1 Architecture

Default source configuration:

- input 1,908 from current schema;
- hidden width 1,024;
- 3 residual blocks;
- dropout 0.10;
- optional four-block multihead attention off;
- optional GRU temporal encoder off;
- seven action logits;
- scalar value;
- expected move bounded to ±120 bps;
- sigmoid confidence;
- tanh MASA.

Observed persistent service configured hidden 2,048 and 4 blocks. The network normalizes finite values with signed `log1p`, applies projection/LayerNorm/GELU, residual blocks and five heads. Optional attention treats values/missing/stale/availability as four tokens; optional temporal path projects frames, runs a GRU and fuses the final state.

### 10.2 Actions

The configured seven-action head includes position-management actions, but `_expected_move_aligned_policy` selects only the first three opening actions: hold, long and short. Close/reduce/hedge actions are architecturally present without equivalent selection lifecycle in this native inference helper.

Expected move biases long/short probability and disagreement can force hold.

### 10.3 MASA

`masa.py` is a deterministic auxiliary adapter. Model inference blends its learned tanh head with the adapter signal 50/50. This implementation is not multiple communicating agents. Reproducing current MASA means reproducing the scalar target/head/blend.

### 10.4 Identity

`model_id` hashes input dimension, seed, hidden size, block count and some optional encoder config. It omits exact weights and some behavior configuration such as dropout/sequence length. Multiple trained states can share a model/prediction identity.

## 11. Training/PPO implementation

Primary source: `hybrid_cuda_trainer/ppo_trainer.py`.

### 11.1 Row modes

On-policy PPO requires `old_log_prob`, `old_value`, `reward`, `done`, `rollout_id` and trajectory index/step. Outcome-supervised rows need realized net PnL, directional outcome, realized reward and an explicit assertion that expected move is not substituted as reward. Training can be PPO-only, supervised-only or mixed.

The learner takes a bounded deterministic prefix, then the last 20% of that selection as validation. On-policy rows are moved toward the train prefix to avoid losing scarce PPO rows. This is not a globally time-reserved out-of-sample split.

### 11.2 Objective

Supervised base approximates:

```text
cross_entropy(action)
+ 0.01  * expected_move_mse
+ 0.001 * value_mse
+ 0.001 * masa_mse
+ 0.05  * confidence_mse
```

PPO mode adds clipped policy/value and additional auxiliary terms. Because base and PPO auxiliary losses coexist, effective move/value/MASA/confidence weights are larger in PPO batches than their individual labels suggest.

The clipped ratio does not currently preserve one behavior-policy/action identity. Published `old_log_prob` is the selected-action probability after `_expected_move_aligned_policy` adjusts and renormalizes raw softmax output. The new log probability is gathered from raw current logits at `policy_target_actions`, a future outcome-supervised label. The single-direction guard can rewrite a taken long/short target to hold while the stored old probability still describes long/short. A valid PPO ratio requires the same preserved action under the same probability transformation on both sides.

Advantage is immediate realized reward minus old value. `PPO_GAMMA` is parsed/reported but native training does not construct discounted returns or GAE; `done` and trajectory fields gate row presence rather than drive a multi-step return. Critic/auxiliary targets include move-oriented supervision.

### 11.3 Optimizer and direct mutations

AdamW is recreated in the training function; optimizer moments are not persisted/checkpointed. Post-optimizer logic can directly nudge expected-move and policy-head biases and recover saturation/runaway. Those mutations bypass optimizer-state/weight-decay accounting.

A single-direction batch guard neutralizes directional expected-move labels in some all-long/all-short batches. `TrainingExample` has no top-level `decision_time`, so temporal windowing cannot see the real time nested in `trust_row` and substitutes incoming list index. PPO-first/source-priority ordering is not global chronology; a target can therefore receive a frame whose real decision time is later, creating future leakage when GRU training is enabled. Correct windowing must parse and require trust-row time, sort within symbol/timeframe, and assert every frame time is no later than the target. Missing history is left-padded by repeating the oldest frame.

This is accurately described as a hybrid one-step PPO-shaped/supervised trainer, not conventional trajectory PPO.

## 12. Rewards, costs and labels

Runtime prediction cost uses:

```text
2 × (fee_per_side + slippage_per_side)
```

Current defaults imply 12 bps round trip. Trusted replay/backtest paths contain a 2 bps assumption. Environment actions may charge round trip on entry and close. These differences change eligibility, reward, confidence target, label, paper economics and promotion.

`trusted_replay/dataset.py` calculates directional trade outcome with `abs(after_cost)` for long and short, making a non-flat directional counterfactual a win regardless of sign. MFE/MAE use raw price direction rather than side-adjusted excursion. Expected-move negative penalties can also mis-handle valid shorts in some reward paths.

Cost/label corrections require new schema/version and replay regeneration, not in-place reinterpretation of historical rows.

## 13. Replay, feedback and holdout

Ordinary selection prioritizes trusted replay backfill/frontier then fresh closed feedback. A bounded in-memory replay buffer is configured up to 16,384 rows. With 1,908-wide Python objects plus trust metadata, memory is far above old small-schema estimates.

Strengths:

- finalized outcome horizon/embargo;
- explicit trust and replay IDs;
- completeness/rejection scan reports;
- immutable-ish archived source concept.

Gaps:

- masked/missing-trust exceptions;
- historical rows rely on stored temporal assertions;
- provider state is not reproducible unless archived;
- strict 70/15/15 manifest exists but normal training does not exclude holdout;
- H2L overlap is against a heldout cache, not cryptographically bound actual training IDs;
- pickle caches can outlive raw-data assumptions.

The persistent holdout evaluator can evaluate rows that may already have been used for training. Current out-of-sample evidence is not demonstrably untouched.

## 14. Checkpoints

Primary source: `hybrid_cuda_trainer/checkpoint.py`, with weight serialization in `model.py`.

Strengths:

- NPZ tensors;
- `allow_pickle=False`;
- strict name/shape and finite checks;
- temporary/atomic replacement behavior;
- input-dimension filtering.

Gaps:

- manifest lacks weight checksum as identity;
- model/checkpoint ID is architecture-derived and can represent changing weights;
- latest compatible chosen by modification time;
- load failure does not robustly fall back through older candidates;
- compatibility does not encode all behavior config;
- optimizer state intentionally absent;
- architecture-derived files can be overwritten.

Offline/H2L dataset caches use pickle and must remain trusted-local; loading an untrusted pickle executes code.

## 15. Prediction publication

Primary sources: `hybrid_cuda_trainer/publisher.py` and `runtime.py`.

`build_prediction_payload` produces policy/model/data IDs, times, probabilities/move/confidence/MASA, costs/eligibility, replay snapshot and live-block assertions. `publish_prediction` validates required source/safety fields, appends durable snapshot, writes replay snapshot and prediction key, and validates trust.

### Split-brain failure

1. Payload begins with replay key/ID but write success false.
2. `publish_prediction` shallow-copies the payload.
3. Archive/replay success/failure blocks mutate only the copy.
4. Runtime appends the original to predictions, ignores publisher boolean and calls `publish_lineage` on the original.
5. Trust accepts replay key+ID presence when no client verifies existence.

Thus replay/archive failure can still emit orchestrator/risk/paper lineage. Successful writes also do not update the caller’s original success flag. Counts measure payload construction more than confirmed publication.

Correct contract is archive → replay → prediction → lineage, with one immutable typed receipt and no downstream write after required failure.

## 16. Orchestrator and risk

`cli/v2_orchestrator_arbitration_loop.py` reads/normalizes predictions, arbitrates/group-selects candidates and emits proposals/paper signals. It creates a provisional risk-decision ID and paper-fill flag before risk evaluation.

`cli/v2_risk_gateway_live_loop.py` emits independent allow/deny records. In current non-live state it denies live-disabled/invalid state. Correct consumers must match exact proposal/prediction/hash/time and require action allow.

Current ordinary paper code records a real deny but later constructs `risk_result.allowed` from risk-ID existence plus local pre-trade. Exploration policy does explicitly require allow, so paths disagree. See the execution component document for exact source order.

## 17. Paper trade management

Primary owner: `cli/v2_trade_management_paper_loop.py`; supporting modules under `services/paper_trade_management`, `services/trade_management_paper` and `services/paper_exploration`.

Responsibilities include:

- proposal/prediction/risk dereference;
- runtime/market trust;
- strategy router, pre-trade, fee, A+, one-minute and temporal gates;
- opportunity tiering and adaptive capital/sizing;
- direction, churn, exposure and portfolio freeze;
- preemptive loss/admission;
- position transition and fill invariant;
- lifecycle, exits, dedupe/netting and accounting;
- outcome/PPO/feedback and status artifacts.

### Current behavior defects

- risk `DENY` not authoritative;
- supply bridge temporarily disabled;
- confidence-based relaxation of strategy/pre-trade/fee/A+/1m/temporal/tier/direction/sizing/churn/freeze/loss gates;
- strict local conjunction omits fee;
- confidence ≥0.65 fast path skips later tier/invariant/position-related and PPO/accounting stages;
- direct assignment to frozen `FeeRatioGateResult` raises `FrozenInstanceError`;
- multiple early/late admission authorities and partial Redis writes.

Later lifecycle/churn/non-relaxable filters catch some rows, not all skipped invariants. Paper results must be classified before feedback/evaluation.

The current low-level paper cross-margin, authenticated mark/bracket, adaptive
stress, cascade-directive, hedge validity, and atomic pair-close contracts are
specified in
[`docs/system_audit_2026_master/PAPER_CROSS_MARGIN_AND_HEDGE_AUTHORITY_CONTRACT.md`](../../docs/system_audit_2026_master/PAPER_CROSS_MARGIN_AND_HEDGE_AUTHORITY_CONTRACT.md).
The hedge queue's Redis TTL is operational cleanup; per-directive adaptive
validity is derived from observed lifecycle cadence plus authenticated mark
freshness, bounded by an immutable safety ceiling, and re-derived by the
consumer.

## 18. Position, lifecycle, portfolio and guardian

Paper subservices implement entry/exit validity, lifecycle reconciliation, net position state, dedupe/netting, accounting, outcome generation and performance telemetry. Invalid transitions must fail before a fill/order boundary; the required model is explicit flat/open/close/replace state, not ID presence.

`cli/v2_portfolio_state_publisher.py` rebuilds open positions/equity/PnL from paper state/current prices, filters invalid admission and writes `v2:portfolio:state` with TTL plus public artifact. It can fall back to nominal capital and uses fixed UTC−4 “EST.” Duplicate publishers were active.

`cli/v2_portfolio_cascade_guard_loop.py` produces close/tighten intents from cascade/liquidation state; Redis failures can be swallowed. `services/continuous_edge_guardian/guardian.py` aggregates disk/Redis evidence into readiness/A-grade gates and can disagree when artifacts are stale.

## 19. Live execution

Real transport: `services/live_gate/binance_live_order_transport.py`.

It validates release/live/armed state, symbols, decision/risk lineage and action, notional/order/filter constraints, position state, dedupe/write guards, then can send signed Binance WebSocket `order.place` and persist execution state.

At audit time effective release mode was absent/non-live, gate disarmed and no active unit executed real submit. Dormant callers remain; `cli/v2_trader_runtime_loop.py` calls the evaluator whose `dry_run` defaults false. Any caller/unit/environment change requires a fresh audit.

Live source/callers cannot be edited without explicit operator approval. This reference contains no activation procedure.

## 20. FastAPI application

Factory: `app/main.py::create_app`.

It registers middleware, V1 routers, auth/RBAC, V2 router, market-stream router, health aliases and SPA/static serving. Effective deployment has four workers, so globals/locks/caches/history are process-local.

Current OpenAPI observation:

- 189 paths;
- 193 HTTP operations: 158 GET, 27 POST, 4 PUT, 4 DELETE;
- zero OpenAPI operations declare security;
- seven mounted WebSocket paths beyond OpenAPI.

Static AST sees more decorators/references because it includes OPTIONS/aliases/clients/unmounted/static source.

The API is not read-only. Mutations include auth/user/account, admin/live-gate control, paper reset/order CRUD/fill, alert CRUD, backtest/subprocess launch, push tokens, cache and pipeline requests.

`/health` and `/api/health` are unconditional liveness; `/api/v2/system/health` pings Redis.

## 21. Middleware and authentication

Eleven registered middleware layers include request ID, IP/rate/MFA/RBAC/idempotency/lineage/approval/live-block/DB/CORS concerns. Nine are essentially pass-through scaffolds; material middleware enforcement is CORS and a narrow live-block guard. Route dependencies provide some real auth/role protection.

Auth modules:

- `auth/security.py`: custom HS256 token, process-secret, cookies/session, revocation, MFA helpers;
- `auth/users.py`: local JSON and optional SQL user stores;
- `api/auth_rbac.py`: login/logout/register/admin/account routes.

Current health reported local-file/non-production users/revocations, issuer/audience and MFA not production-ready. Login returns access token in JSON plus HttpOnly cookie. Four workers have only process-local file locks, so atomic replace prevents torn files but not lost updates. Import can create a process-secret file if env is missing.

Sensitive local files had mode 0664; the tunnel service exposes a credential in command arguments. Values are intentionally not recorded.

## 22. Web and mobile clients

### React/Vite

`src/main.tsx` mounts StrictMode/App/AuthProvider/RealtimeProvider/RouterProvider. Router/pages and clients consume REST, WebSocket/SSE and public runtime artifacts. Vite disables ordinary public directory copying and performs curated copy/prune, so `public/operator_runtime` is not automatically deployed.

Effective process only previews existing `dist`; restart does not build. Dependency tree is incomplete and no frontend-local lockfile provides a clean reproducible install.

### Swift

Swift package provides iOS app, watch app and `aibot` CLI. API endpoint/client/model definitions are duplicated between app/core targets, creating contract drift. Any API or field change must inspect both Swift and TypeScript atlases.

## 23. Persistence and storage

### Redis

At snapshot: roughly 1.11 million keys, 31 GiB/32 GiB, `allkeys-lru`, AOF disabled, RDB enabled and no discovered replica/backup/restore proof. Redis holds critical coordination, paper and lineage state but can evict any key and lose post-snapshot changes.

### Relational/SQLite

`v2/backend/v2_paper_trading.db` is empty and central application metadata/Alembic have no initialized schema or versions. Optional user, revocation, alert and trader-account SQL repositories are implemented and can create their own tables outside Alembic, but the observed auth/state selection used local JSON. Closed-loop automation separately uses one SQLite WAL database; its rollback helper copies only the main DB and can omit WAL changes.

### Files/models/archive

Runtime, replay, model, public JSON, JSONL/logs and worklog evidence occupy hundreds of GiB. Archive records have content hashes but ordinary publisher writes skip checksum-manifest update; rollover can remove blobs/index without durable tombstones. Logs are decentralized and very large.

Two retention policies conflict: 100 GiB FIFO rollover versus 300 GiB/five-day janitor. The former is failed because of an invalid path; repairing it without approval can delete a large dataset.

## 24. Observability and automation

`app/logging.py` is a placeholder. User journals returned no entries; services write journal/files/runtime artifacts inconsistently. Prometheus rules exist without installed Prometheus/Grafana/Alertmanager. Webhook/Telegram sending was not active. Four API workers fragment in-memory metrics history.

Self-healing supervises dozens of non-ingestor components and can restart services; its rate ledger is Redis and can be evicted. Autonomous Claude/Codex workers can edit and commit the mutable worktree from which services restart. Git HEAD and dirty state are operational inputs.

## 25. Tests, dependencies and build

Runtime-oriented count: 1,446 backend test files (1,307 unit, 137 integration, 2 contract). A conftest documents previous destruction of real paper history; global isolation is incomplete, so full suite was not run.

No active root-enforced backend/frontend GitHub Actions workflow was found. A tracked dormant definition exists at `v2/.github/workflows/ci.yml`; its own header says it must be installed under the repository-root `.github/workflows/` before GitHub will enforce it. `v2/pyproject.toml` omits actual runtime packages such as Torch/NumPy/Gymnasium/psutil; the ad-hoc venv has many more. Frontend `npm ls` fails, Docker compose is empty, gitleaks is absent and its wrapper exits success when absent.

Scoped validation results were: atlas Python/Node checks passed and atlas pytest passed 4; frontend typecheck passed; Swift Core passed 32 with iOS/watch application targets excluded; middleware order passed 1/failed 2 because expectations are stale; and the canonical-candle/pipeline-trust group passed 66/failed 6. All six latter failures occur before intended publisher assertions because the synthetic tensor fixture lacks `missing_mask`, which production `_trusted_replay_snapshot` now reads (`publisher.py:562`; `test_pipeline_trust_runtime_enforcement.py:653-670`). That is test-fixture contract drift, not evidence that canonical temporal checks failed.

## 26. Change-impact method

For a function:

1. find `symbol_id` in `CHANGE_IMPACT_INDEX.json`;
2. read exact source and every return/exception/fallback;
3. traverse direct callers/importers upward and callees downward;
4. inspect unresolved/dynamic calls;
5. join Redis/env/data/API/exchange registries;
6. inspect effective installed units/drop-ins/import roots;
7. trace TypeScript/Swift/public artifact consumers;
8. classify temporal/training/risk/position/live/destructive implications;
9. write isolated negative tests and rollback;
10. regenerate atlas and docs.

For high-blast-radius surfaces:

| Change | Affected system |
|---|---|
| Symbol universe | subscriptions, feature coverage, trainer/publish/UI universe |
| Candle/finality | all decisions, replay/labels/evaluation |
| Feature spec/order | tensor/model/checkpoint/prediction and clients |
| Temporal fields | trust, archive/replay, risk/paper/live validity |
| Publisher schema | prediction, orchestrator, risk, paper, UI/feedback |
| Risk action | paper and live control authority |
| Paper condition | lifecycle/accounting/portfolio/outcome/training |
| Cost model | gates, rewards, labels, sizing and promotion |
| Model/checkpoint ID | exact policy provenance and every future decision |
| Redis key/TTL | nearly every service and recovery |
| Worker/import config | locks/singletons/auth/metrics |
| Frontend/API fields | React and duplicated Swift decoders |
| Retention | irreversible replay/evidence deletion |

## 27. Rebuild requirements

A clean copy requires pinned dependencies/hardware, immutable releases, canonical import root, complete unit installer, secret-name/rotation manifest, exported tunnel routing, versioned Redis/key/TTL contracts, PIT envelopes, reproducible 477/1,908 tensor, exact weight identity, clean split manifests, one risk/paper authority, one fill state-machine boundary, durable publication receipts, isolated tests, centralized observability and tested backup/restore/rollback.

The ordered reconstruction stages and acceptance tests are in `docs/system_audit_2026_master/REBUILD_BLUEPRINT.md`.

## 28. Current blocking defects

The detailed register is `docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md`. Highest priority:

1. paper risk deny not authoritative;
2. high-confidence fast path/invariant bypass;
3. incomplete per-source feature PIT lineage;
4. dirty training exceptions and holdout contamination;
5. wrong signed directional replay label/cost mismatch;
6. publisher archive/replay fail-open split;
7. model/checkpoint identity not exact weights;
8. non-reproducible installed deployment/import roots;
9. near-full evicting Redis and unproven recovery;
10. security, retention, CI/test isolation and external-state gaps.

These conclusions do not authorize fixes to strategy, PPO, MASA, risk or live-execution code. Each requires a separately scoped approved change with tests.

## 29. Definition of safe system understanding

The system is “understood” only when a proposed change can identify:

- exact source symbol and semantic invariant;
- every direct/static and dynamic caller/consumer;
- environment/default/effective deployment value;
- Redis/file/API/client contracts and temporal fields;
- model/replay/checkpoint consequences;
- risk/position/paper/live consequences;
- tests and state isolation;
- deployment/restart/rollback;
- evidence preservation and atlas diff.

The atlas supplies the exhaustive static lower bound. This reference supplies subsystem semantics. The operator manual supplies safe actions. Runtime evidence must be refreshed because resident automation continuously changes the source and deployed state.
