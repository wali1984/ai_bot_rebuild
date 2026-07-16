# AI Bot V2 — full rebuild master audit report

**Rebuilt:** 2026-07-16

**Runtime observation:** 2026-07-16T03:04:21-04:00

**Audit method:** full tracked-file atlas, Python/TypeScript AST analysis, Swift/shell contract heuristics, direct source tracing, installed systemd/process inspection, safe Redis/API/filesystem reads, and isolated documentation-tool tests.

**Decision:** **NO-GO for live trading. NO-GO for treating current paper outcomes as clean promotion evidence.**

This report replaces the 2026-07-01 master snapshot. The earlier report was useful historical evidence but several of its strongest claims are now false: the deployed process count changed; two trainer authorities are active; real order transport exists; the V2 API is not read-only; risk `DENY` is not the final authority for ordinary paper admission; and newer paper confidence overrides alter the documented gate order.

## 1. Executive answer

The system is a large, actively changing, Redis-centered trading research platform, not a single bot process. The audited workstation combines:

- 9,272 tracked repository paths;
- 3,213 parsed Python modules and 32,272 Python symbols across source, tests and tooling;
- 1,181 first-party backend application modules and roughly 423,000 backend source lines in the runtime-focused trace;
- 157 installed `ai-bot*` user-unit files, 81 running services, 36 active timers and 3 failed services at the earlier operations observation;
- 1.11 million Redis keys and about 31.03 GiB used against a 32 GiB `allkeys-lru` limit;
- a 477-feature native tensor schema expanded to 1,908 model inputs by concatenating values, missing masks, stale masks and source-availability bits;
- a native PyTorch residual policy/value/move/confidence/MASA model, persistent and offline training processes, replay/archive/checkpoint machinery, orchestration, risk records, paper lifecycle/accounting, and dormant live Binance mutation code;
- FastAPI with four Uvicorn workers, a React/Vite interface, SwiftUI/watch/CLI clients, and a Cloudflare tunnel whose routing is external provider state;
- hundreds of automation, evidence and monitoring workers around the core trading loop.

The architecture can be reconstructed from the new atlas and component documents, but the deployed machine cannot yet be reproduced from the repository alone. Installed systemd units and drop-ins diverge from versioned definitions, secrets and tunnel routing live outside version control, dependency manifests are incomplete, Redis has no proven restore/HA path, and several runtime truth surfaces disagree.

The most consequential behavioral conclusions are:

1. **Live trading is currently disarmed, not nonexistent.** No active service was authorized to submit a real order and the effective release mode was non-live. Nevertheless, real `order.place` transport and dormant callers exist. Enabling a caller or changing gates changes that conclusion immediately.
2. **Paper risk control is not authoritative.** A real gateway `DENY` can be resolved and recorded while ordinary A-grade paper admission treats the existence of its risk ID as sufficient.
3. **A high-confidence fast path bypasses later paper safeguards.** It can skip tier/upstream enforcement, direction, sizing, churn, portfolio freeze, preemptive admission, the fill invariant, accounting annotations and PPO entry stamping.
4. **Point-in-time protection is strong in canonical candle/trust code but incomplete in enriched feature assembly.** Current Redis enrichment values are merged without preserving and validating each source’s availability/cutoff.
5. **Training and evaluation evidence is not clean enough for promotion.** Dirty-lineage exceptions exist, replay has a directional label defect, holdout exclusion is not enforced by the main loader, publication failures can leak downstream lineage, and model/checkpoint identity does not prove exact weights.
6. **Operational recovery is unsafe to improvise.** Redis is near its memory cap; the failed replay-rollover service has an active persistent six-hour timer and would apply a conflicting destructive 100 GiB policy if repaired, while a separate 15-minute non-dry-run janitor already mutates replay/cache/log/temporary holdout artifacts. Its `2026-07-16T08:27:21.352199+00:00` status recorded ten temporary holdout files deleted. The replay tree was observed at roughly 259 GiB early and 247 GiB later, but that size change is observed drift, not proof of its cause. The closed-loop SQLite backup is not WAL-safe, and full tests have previously overwritten real paper state.

## 2. Evidence and confidence model

Every statement in this documentation set should be read using these labels:

| Label | Meaning |
|---|---|
| Source-proven | Control flow or contract was directly traced in the audited source. |
| Runtime-observed | A read-only process, systemd, Redis, API, file or log observation agreed at the snapshot time. |
| Test-proven | An isolated deterministic test executed and passed. |
| Inferred | Multiple facts support the conclusion, but the path was not safely exercised; the inference is named. |
| Unknown | Evidence was absent, external, stale, or contradictory. |

The first full atlas was generated at `f88c53b8c553600f03b9990e5d71d76cd2171668`; resident automation then advanced the checkout. Final regeneration held Git HEAD stable from start through end at `2dd584d632790c54c1054f7c4453cb9d36d0987c`. This proves the final static scan is internally consistent, not that the mutable checkout or runtime will remain unchanged. A runtime count or Redis value is never a timeless design constant.

## 3. System boundary and truth planes

### 3.1 Versioned repository

The repository contains backend/domain/service/CLI code, web and mobile clients, tests, partial systemd/deployment definitions, operational tooling, preserved legacy source and a very large worklog/evidence corpus.

The atlas classifies the tracked files as:

| Stratum | Files |
|---|---:|
| Backend adapter | 60 |
| Backend API | 90 |
| Backend CLI | 298 |
| Backend composition | 53 |
| Backend core | 32 |
| Backend domain | 127 |
| Backend services | 527 |
| Configuration | 143 |
| Documentation | 2,612 |
| Evidence/runtime artifacts | 2,112 |
| Mobile | 82 |
| Operational tooling | 272 |
| Preserved legacy source | 279 |
| Repository support | 297 |
| Service definitions | 131 |
| Tests | 1,645 |
| Web frontend | 511 |

### 3.2 Deployed host state

The actual runtime additionally depends on:

- `/home/wali/.config/systemd/user` for installed user units and stacked drop-ins;
- `/home/wali/state/nervyx-one` for auth/local state;
- Redis server configuration and RDB state;
- ignored `v2/runtime`, `.local_models`, frontend `dist` and virtual environments;
- a system Cloudflare unit and provider-side tunnel configuration;
- machine packages, CUDA/driver, Node/Swift tooling and ad-hoc Python packages;
- runtime-generated public JSON, worklog JSON/JSONL/logs, replay archives and checkpoints;
- operator-managed credentials.

These are not fully captured by a Git clone.

### 3.3 Authoritative-state rule

There is no universal single source of truth. Authority is per contract:

| Contract | Primary current truth | Derived/secondary truth |
|---|---|---|
| Running process and command | effective systemd unit/drop-ins plus `/proc` | versioned unit file, status JSON |
| Market/feature state | producer-specific Redis key and temporal envelope | dashboard/public JSON |
| Model weights | validated NPZ blob plus manifest and runtime load evidence | reported checkpoint ID alone |
| Paper fill | invariant-valid lifecycle/ledger record with complete lineage | candidate/accepted status counters |
| Portfolio | recomputed valid paper positions plus current prices | cached public artifact |
| Auth users/revocations | current local JSON in this non-production deployment | per-worker cache |
| Public route | Cloudflare provider state plus local bind/proxy | repository URL strings |
| Audit evidence | immutable content plus generation provenance | “PASS” field in a mutable report |

Any code change must identify which authority it reads, writes and invalidates.

## 4. End-to-end architecture

```text
EXCHANGES / PROVIDERS
  Binance · KuCoin · CoinAPI · CoinAnk · CoinGlass · Santiment · Moralis
  Nansen · LunarCrush · AICoin · public-intel/news sources
        │ read-only market/provider ingestion in current deployment
        ▼
REDIS RAW/DERIVED MARKET PLANE
  candles · prices · order books · trades · funding/OI · liquidations
  provider context · microstructure · regimes · symbol universe
        ▼
FEATURE PLANE
  closed-candle selection → native features → TA → enrichment
  → latest snapshot + immutable-ish IDs + durable/replay archive attempts
        ▼
TENSOR PLANE
  477 ordered feature values
  + 477 missing bits + 477 stale bits + 477 availability bits = 1,908
        ▼
MODEL / TRAINING
  residual MLP [optional attention/GRU] → seven-action policy
  + value + expected move + confidence + MASA scalar
  mixed PPO-shaped and supervised outcome losses
        ▼
PREDICTION / PUBLICATION
  prediction key + lineage + all-timeframe aggregation
        ▼
ORCHESTRATOR
  candidate normalization, arbitration, provisional lineage/risk ID
        ├──────────────► RISK GATEWAY → ALLOW/DENY records
        ▼
PAPER SIGNAL / TRADE-MANAGEMENT LOOP
  local gates + tiering + overrides + lifecycle/reconciliation/accounting
        ▼
POSITIONS / CLOSED TRADES / PORTFOLIO / GUARDIAN
        ▼
OUTCOME / REPLAY / TRAINER FEEDBACK
        └──────────────────────────────► training inputs

PRESENTATION (parallel consumers)
  FastAPI REST/WebSocket/static → React/Vite and SwiftUI/watch/CLI

DORMANT LIVE BRANCH
  authorized decision + live gates + state machine + Binance WS order.place
  (code exists; no active authorized submitter observed)
```

## 5. Current deployed runtime

At the snapshot:

- 157 installed `ai-bot*` user-unit files: 112 enabled, 29 disabled, 4 linked, 4 masked, 6 static and 2 indirect.
- 81 services were running and 36 timers were active in the earlier trace; the direct recheck found 35 active timers.
- Three services were failed: the autonomous no-manual-next-task policy reporter (cause unproven because no journal evidence was available), the replay rollover, and scheduled pretrain.
- 57 installed unit basenames did not exist in any audited versioned unit directory; 33 versioned names were not installed.
- Ten installed services contained failure-masking shell wrappers; 83 declared `Restart=always`.
- Two identical portfolio publishers were running.
- Persistent native CUDA and continuous offline GPU trainer services were both active.
- Backend used four Uvicorn workers on `127.0.0.1:8000` directly from the mutable repository.
- Vite preview bound `0.0.0.0:5173` and served an ignored prebuilt `dist`.

Eight installed units have invalid unquoted `PYTHONPATH` assignments containing the repository’s spaces. Systemd truncates the effective path. The codebase also mixes `app.*` and `v2.backend.app.*` imports, so one physical source can be loaded under two module identities with duplicated globals, locks and registries.

The installed runtime falls into these functional groups:

1. Exchange/provider ingestion.
2. Feature, TA, microstructure, context and snapshot publication.
3. Persistent/offline training, inference and checkpoint/evidence publication.
4. Signal aggregation, orchestration, risk and adaptive tuning.
5. Paper trade management, lifecycle, positions, portfolio and guardians.
6. Backend/frontend/mobile/public-runtime presentation.
7. Supervisors, watchdogs, autonomous workers, retention and report publishers.

The exact effective unit inventory and timer cadence must be captured from the host before a restart or clone; no repository script installs all of it.

## 6. Temporal and data integrity

### 6.1 Required timestamp semantics

These fields are distinct:

- `event_time`: when the market/provider event occurred.
- `ingested_at`: when this system received/persisted it.
- `available_at`: earliest time the exact value could be used by a decision.
- `generated_at`: when a derived record was computed or published.
- `feature_cutoff`: newest market information actually represented in the feature vector; a per-source/per-timeframe vector must also be retained.
- `decision_time`: immutable time at which the policy decision was made.
- `execution_time`: time a paper or live execution was materialized/acknowledged.

Mandatory inequalities are `candle_close <= available_at <= decision_time <= execution_time`, with every contributing source’s `available_at <= decision_time` and MASA cutoff not later than PPO decision time.

### 6.2 What is correctly enforced

Canonical candle and trust modules:

- model finality from Binance WSS `k.x` and explicit closed flags;
- select only closed 1m/5m/15m/1h/4h candles at or before a decision;
- reject missing/future availability and future closes;
- reject feature cutoff or availability later than decision;
- reject MASA cutoff later than PPO decision and mismatched cross-model cutoffs;
- reject gaps, latency, stale/missing required state and many dirty classifications;
- apply a replay label embargo before looking at later finalized candles.

### 6.3 Where protection breaks

- List-format REST klines are accepted from close time alone and can lose actual receipt/backfill availability.
- Feature enrichment merges current Redis numeric values without a per-source temporal envelope, then stamps aggregate availability as “now.”
- The multi-timeframe snapshot uses the minimum selected close as its scalar cutoff, understating newer inputs.
- Provider bridge paths can accept missing timestamps and do not uniformly reject stale values.
- Tensor `or` fallback can replace valid zero; availability bits represent numeric presence, not point-in-time validity.
- Training loader exceptions can admit masked or missing-trust rows.

Therefore the system has **partial point-in-time safety**, not end-to-end proof.

## 7. Trainer, PPO, MASA and replay truth

### 7.1 Input and architecture

`FEATURE_SPEC` is an ordered 477-field contract. Each tensor concatenates:

```text
[477 numeric values]
[477 missing-mask bits]
[477 stale-mask bits]
[477 source-availability bits]
= 1,908 inputs
```

Older 1,248-input documentation is stale.

The default model is a normalized residual MLP with environment-controlled width/depth/dropout, seven policy logits and scalar value, expected-move, confidence and MASA heads. Spatial four-block attention and GRU temporal encoding exist but are off by default in source. The observed service used a larger configured width/depth than defaults.

Inference aligns actions to expected move and only selects the opening subset `hold`, `long` or `short`; close/reduce/hedge logits are not eligible in that selection helper. MASA is a single learned tanh head blended 50/50 with a deterministic adapter signal; it is not a network of multiple independent agents.

### 7.2 What the PPO trainer actually does

On-policy rows require old log probability, old value, reward, done, rollout ID and trajectory position. Advantage is immediate reward minus old value; the implementation does not build GAE or discounted returns from trajectories, and recorded gamma/done do not create a multi-step return. The optimizer mixes clipped PPO terms with supervised action/value/move/MASA/confidence objectives. AdamW is recreated each online cycle and optimizer state is intentionally not restored.

The clipped ratio also lacks a proven behavior-policy/action identity. Entry `old_log_prob` is taken from the selected action after expected-move adjustment and renormalization, while the new probability comes from raw current logits at a future outcome-supervised target action. The single-direction guard can replace a taken long/short target with hold without changing the stored old long/short probability. The ratio is not mathematically interpretable as PPO until both sides use the same preserved action and the same probability transformation.

This is a hybrid PPO-shaped one-step trainer. Algorithm changes must be evaluated against implementation, not the label “PPO.”

### 7.3 Replay/label defects

- Trusted replay passes absolute signed return to directional trade outcome for long and short, turning non-flat counterfactuals into wins.
- Excursion labels are not side-adjusted.
- Replay cost assumptions disagree with current paper cost assumptions.
- Historical/masked exceptions can admit incomplete lineage.
- Temporal split manifests are generated but not enforced by the main training load path.
- The active temporal windower cannot see the real nested trust-row decision time because `TrainingExample` has no top-level `decision_time`; it substitutes list index. PPO-first and source-priority reordering can therefore attach a later real-decision frame to an earlier target, producing future leakage in GRU training. Windows must be sorted by parsed trust-row time and assert every frame time is no later than the target; padding also repeats the oldest frame.

### 7.4 Checkpoint/publication defects

NPZ loading is relatively safe: pickle is disabled and tensors are shape/finite checked. But model IDs describe architecture rather than exact weights; manifests lack a weight checksum; the selected latest bad blob does not fall back; optimizer state is absent; ordinary archive writes skip manifest checksum updates.

Publication is split-brain: a private payload copy receives archive/replay failure blocks, the caller ignores the boolean, and downstream lineage uses the original prepopulated key/ID. Durable failure can therefore leak into orchestrator/risk/paper lineage.

## 8. Decision, risk and execution truth

### 8.1 Orchestrator

The orchestrator reads/normalizes predictions, arbitrates candidates and emits paper signals. It stamps a provisional risk-decision ID and paper-fill eligibility before the risk gateway creates its own decision record. That makes its output a proposal, not a risk approval, even though some downstream code treats it as approval-like.

### 8.2 Risk gateway

The risk gateway emits explicit allow/deny records and currently denies under non-live/missing required state. Its live transport consumers validate the action. The ordinary paper path does not consistently do so.

### 8.3 Paper admission

The paper loop is roughly 34,000 lines and centralizes candidate normalization, dereference, strategy/pre-trade/fee/A+/temporal/tier gates, adaptive sizing, position lifecycle, accounting, outcome and feedback preparation. It has multiple admission authorities and confidence-based mutations.

The critical defect is:

```text
risk gateway action = DENY
    ↓ correctly dereferenced and recorded
ordinary A+ synthetic risk allowed = risk ID exists AND local pre-trade passed
    ↓
paper fill can still be admitted
```

Newer confidence overrides then relax strategy, pre-trade, fee, A+, one-minute, temporal, tier, direction, sizing, churn, freeze and loss-probability behavior. A confidence ≥0.65 fast path exits before several invariant and PPO-stamping stages. One override directly assigns a frozen fee result and is generating `FrozenInstanceError` tracebacks.

### 8.4 Paper lifecycle, portfolio and feedback

Paper subservices implement lifecycle reconciliation, entry/exit validation, net position state, accounting, outcomes, side performance and dedupe/netting. The portfolio publisher recomputes positions/equity/PnL from paper state and current prices, filtering invalid admissions; it falls back to a nominal initial capital when session truth is missing. A cascade guard writes close/tighten intents consumed by lifecycle. The guardian combines Redis and disk evidence and can disagree when artifacts are stale.

Because admission, labels and temporal lineage are not clean, downstream closed trades and feedback must be classified by provenance before training or performance claims.

### 8.5 Dormant live transport

The Binance live order transport includes release/live/armed/symbol/lineage/risk/notional/filter/state-machine/dedupe gates and WebSocket `order.place`. No active authorized submitter was observed. Several inactive callers exist, and one observer-like runtime defaults `dry_run=False`. No documentation or command in this audit enables it.

## 9. API, security, storage and clients

### 9.1 API surface

The current OpenAPI described 189 paths and 193 HTTP operations (158 GET, 27 POST, 4 PUT, 4 DELETE), plus seven mounted WebSocket paths outside OpenAPI. The regenerated atlas contains 905 server/client route references and the AST trace found 248 decorators; these are different metrics.

The V2 surface includes real mutations: user/account/auth changes, live-gate controls, admin actions, paper reset/order lifecycle, alert CRUD, backtest/process launch, push-token writes, cache/pipeline actions and previews. Route-by-route dependencies—not the “read-only” description—determine authorization.

### 9.2 Middleware/auth

Nine of eleven middleware layers are pass-through scaffolds. CORS and a narrow live-block guard materially enforce at middleware level; route dependencies enforce some auth/RBAC. OpenAPI declares security on zero operations. Local-file users/revocations are non-production, login returns a token in JSON and cookie, non-production step-up can accept a missing TOTP configuration, and some subprocess-launching routes are unauthenticated or optional-auth.

Four Uvicorn workers make process-local locks/caches insufficient for shared JSON state and fragment in-memory metrics. Credential/auth files had overly broad modes. A public tunnel credential is embedded in a systemd command line and should be rotated/moved without recording it in this repo.

### 9.3 Persistence

- Redis is primary runtime state, near its max, evicting by allkeys LRU, RDB-only and without discovered replica/backup/restore proof.
- The central application/paper ORM and Alembic layer is uninitialized: the application DB is empty and migrations have no versions. Optional user, revocation, alert and trader-account SQL repositories are implemented, but they can auto-create tables outside Alembic and were not the observed default state plane.
- Auth is local JSON in this deployment.
- Closed-loop automation alone uses a live SQLite WAL database; its rollback copy omits the WAL.
- Models, replay, runtime JSON/JSONL/logs and public artifacts live on disk with inconsistent checksums, retention and atomicity.

### 9.4 Web/mobile

FastAPI and Vite can both serve the SPA build. Vite’s build disables normal public-directory copying, so runtime JSON under `public/operator_runtime` needs explicit inclusion. The Swift package has iOS, watch and CLI entrypoints and duplicates API/model layers across targets. Any route or field change must be checked in both TypeScript and Swift registries.

## 10. Operations, observability and recovery

### 10.1 Deployment drift

Stacked drop-ins bypass the versioned release symlink and run directly from the mutable repository. The release link points to an older build. Frontend source can differ from ignored `dist`. No installer captures all 157 units, and Docker compose is empty.

### 10.2 Retention danger

At `2026-07-16T08:32:41Z`, the orderbook-rollover and disk-janitor timers were both loaded, enabled, active and persistent. The failed rollover is retried every six hours; repairing/reloading it would let the existing timer invoke a 100 GiB FIFO deletion policy. The separate 15-minute service already runs `claude_worklog/tools/v2_disk_retention_janitor.py` without `--dry-run`; it enforces five-day/300 GiB/free-space replay pruning, JSONL tail replacement, log truncation and six-hour temporary-holdout deletion. Its status five minutes earlier recorded ten temporary holdout files deleted and 89,478 bytes reclaimed, with no replay-directory/JSONL/log change in that cycle. Evidence preservation is racing this automation. Do not change, pause, disable, mask, repair or manually run either authority without approval, captured timer state, protected-dataset and dry-run manifests, and recovery proof.

### 10.3 Observability

Logging is not centralized; the application logging module is a placeholder, user journals were empty, and more than 10,000 log/JSONL files occupied roughly 266 GiB. Prometheus rules exist without an installed Prometheus/Grafana/Alertmanager stack. Telegram status explicitly performs no send and the webhook path was unconfigured. Derived dashboards must not be treated as primary truth.

### 10.4 Tests/build

There are 1,446 backend test files (1,307 unit, 137 integration, 2 contract) in the runtime-oriented count. No active root-enforced backend/frontend GitHub Actions workflow was found. The tracked `v2/.github/workflows/ci.yml` is a dormant definition whose header requires installation under repository-root `.github/workflows/`; it is not currently enforced. Python and frontend dependency manifests are incomplete; `npm ls` failed; gitleaks is absent and the wrapper treats absence as success. A full suite was not run because integration-test history documents destruction of live paper state and isolation is not global.

Observed scoped validation:

| Scope | Result | Interpretation |
|---|---|---|
| Atlas Python compile + Node syntax/self-test | Passed | Generator/helper parse and the TypeScript AST fixture is recognized. |
| Atlas pytest | 4 passed | Secret-path, extraction and build contracts covered by the focused tests pass. |
| Frontend TypeScript typecheck | Passed | Current frontend checkout typechecks; this is not a build/browser/deployment proof. |
| Swift Core tests with application targets excluded | 32 passed | Shared Core passes on Linux; iOS/watch application and real API compatibility remain unproved. |
| Middleware-order contract | 1 passed, 2 failed | Test expectations are stale relative to the eleven installed layers/CORS. |
| Canonical candle + pipeline trust unit group | 66 passed, 6 failed | Six publisher tests fail before assertions because their synthetic tensor lacks the now-required `missing_mask`; canonical temporal failures were not reported. |

The six pipeline failures are test-fixture/production-contract drift at `publisher.py:562` and `test_pipeline_trust_runtime_enforcement.py:653-670`. They leave the intended publisher/trust assertions unexecuted; they do not establish that the temporal guards themselves failed.

## 11. Highest-blast-radius change surfaces

| Surface | Direct impact | Downstream impact |
|---|---|---|
| Symbol universe | provider subscriptions, snapshot coverage | tensors, predictions, arbitration, UI universe |
| Candle canonicalization/finality | training/decision eligibility | replay, labels, all performance evidence |
| Feature spec/order | input dimension and checkpoint compatibility | every model output and client schema |
| Temporal fields | trust classifiers and lineage | model/paper/live validity and audits |
| Publisher schema | Redis predictions/archive/lineage | orchestrator, risk, paper, replay, UI |
| Orchestrator paper flags/risk ID | candidate proposal semantics | current paper admission authority defect |
| Risk action contract | allow/deny semantics | paper and live execution tests |
| Paper loop condition | admission, lifecycle, accounting | portfolio, outcomes, PPO/replay and UI |
| Cost model | edge gates and rewards | sizing, labels, evaluation and promotion |
| Checkpoint/model ID | load/promotion/restart | every subsequent prediction lineage |
| Redis key/TTL/eviction | producer/consumer availability | nearly every runtime service and dashboard |
| Worker count/import namespace | locks, caches, singleton identity | auth, metrics and mutable local state |
| Systemd/drop-ins | source, env, mode and command | entire deployed behavior on restart |
| Frontend API/model field | client decode/rendering | web and duplicated Swift clients |
| Retention policy | disk use | irreversible replay/evidence deletion |

For symbol/function/field-level impact, use `atlas/CHANGE_IMPACT_INDEX.json` and recursively inspect callers/importers plus Redis/config/data/API/test registries.

## 12. Rebuild/copy readiness

The new documentation makes the codebase navigable at function and contract level, but a faithful clean-room copy still requires these missing reproducibility inputs:

1. Canonical, versioned installed unit/drop-in manifest and an idempotent installer.
2. Pinned Python/Node/Swift/OS/CUDA/Redis dependencies and frontend lock/build artifact provenance.
3. Secret manifest by name and provider—not values—plus rotation/bootstrap procedure.
4. Exported Cloudflare route/origin configuration.
5. Redis schema/TTL/retention inventory, backup and tested restore.
6. WAL-safe closed-loop/auth/model/archive backup and restore.
7. One explicit authority for trainer promotion, prediction publication, risk and paper fills.
8. Fixed point-in-time enrichment and preserved per-source lineage.
9. Correct, versioned label/cost semantics and uncontaminated holdout.
10. Isolated test environments that cannot reach live Redis, auth or paper state.
11. End-to-end negative safety tests, including invalid position transitions and risk denies.
12. A controlled non-live deployment/restart/rollback drill from a clean host.

`REBUILD_BLUEPRINT.md` expands these into ordered stages and acceptance evidence.

## 13. GO/NO-GO

### Live trading: NO-GO

Live remains blocked by current configuration, but the following prevent approval even if the gate were changed:

- paper risk `DENY` not authoritative;
- confidence overrides and fast-path invariant bypass;
- incomplete point-in-time enrichment lineage;
- contaminated/incorrect training evidence;
- incomplete publication/checkpoint integrity;
- non-reproducible deployment and unproven recovery;
- incomplete auth/security/CI controls;
- current readiness endpoint at zero of eight gates with active guardian/generalization/loss/feed blockers.

### Paper learning evidence: NO-GO for promotion

Paper mode may continue only as explicitly labeled research/diagnostic activity. Rows must not be assumed trainable merely because they were filled or closed. Preserve raw evidence and classify affected rows by risk action, fast-path use, temporal completeness, label version, costs, PPO fields and archive-write success.

### Documentation/understanding goal

The repository now has:

- an exhaustive static atlas down to functions, calls, fields, keys, env keys, routes and tests;
- reconciled runtime, data/model, execution and operations traces;
- current master, operator and technical references;
- component-specific low-level documents;
- a defect/risk register and reconstruction blueprint.

Because the system is actively changing, “understood” is maintained by regenerating the atlas and runtime snapshot after material commits—not by freezing this report as timeless truth.

## 14. Canonical navigation

Start with `REVERSE_ENGINEERING_INDEX.md`. Use `CURRENT_FINDINGS_AND_RISK_REGISTER.md` for defects, the component documents for subsystem semantics, `v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md` for source-level integration, and the atlas JSON for exact change impact. Use the operator manual before any process, Redis, checkpoint, retention or deployment action.
