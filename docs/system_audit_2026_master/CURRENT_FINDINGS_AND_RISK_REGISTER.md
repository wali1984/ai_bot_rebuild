# Current findings and risk register

**Evidence cut:** 2026-07-16 03:04 America/New_York, with source continuing to change during the audit.

**Operational recommendation:** **NO-GO for live trading and NO-GO for treating current paper results as clean model evidence.**

**Scope rule:** this register documents defects and drift; it does not authorize changes to strategy, PPO, MASA, risk, or exchange-touching behavior.

Severity means consequence if the path is exercised, not how hard it is to fix. Finding IDs are append-only, so a later ID can appear in an earlier severity section. “Observed” means live read-only evidence agreed with source; “source-proven” means control flow was traced but the path was not deliberately exercised; “inferred” is called out explicitly.

## P0 — integrity or control-authority failures

### RE-001 — risk `DENY` is not authoritative for ordinary paper admission

- **Evidence:** source-proven and observed in Redis.
- **Source:** `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:744`; `v2/backend/app/cli/v2_risk_gateway_live_loop.py:567`; `v2/backend/app/cli/v2_trade_management_paper_loop.py:16738`, `:17167`, `:21938`, `:28720`, `:29193`; `v2/backend/app/services/paper_exploration/policy.py:1434`.
- **Mechanism:** the orchestrator creates a provisional risk ID and sets its paper flag before gateway evaluation. The paper loop dereferences and records the real `DENY`, but its ordinary A+ admission tests whether a risk ID exists plus whether local pre-trade passed; it does not require the action to be allow. Exploration policy does require allow, so the two admission paths disagree.
- **Impact:** risk lineage can look complete while the risk decision does not control a paper fill. Paper outcomes, position history, and trainer feedback can therefore be produced from risk-denied entries.
- **Required proof before closure:** one canonical risk-decision contract, an allow-action assertion at the sole fill-write boundary, negative tests for `DENY`, missing/stale/mismatched IDs, and end-to-end evidence that a denied candidate cannot materialize a fill.

### RE-002 — high-confidence paper fast path skips downstream safeguards

- **Evidence:** source-proven; committed while this audit was running.
- **Source:** `v2/backend/app/cli/v2_trade_management_paper_loop.py:29755` and subsequent normal path through roughly `:30415`.
- **Mechanism:** when local gates pass and confidence is at least 0.65, the loop appends `ACCEPTED_PAPER_FILL` and immediately continues.
- **Skipped behavior:** final tier/upstream enforcement, directional-collapse guard, sizing completeness, current-cycle prediction/signal/same-candle churn, portfolio new-entry freeze, preemptive admission, fill-write invariant validation, accounting-blocker annotation, and PPO entry-time probability/value/rollout stamping.
- **Impact:** a small threshold/configuration change affects lifecycle validity, exposure, accounting, duplicate-entry behavior, and whether closed rows can be used as genuine on-policy PPO evidence.
- **Required proof before closure:** remove multiple fill authorities, route every candidate through one immutable admission object and one invariant validator, and add branch-complete tests for every skipped gate.

### RE-003 — feature enrichment is not point-in-time complete

- **Evidence:** source-proven.
- **Source:** `v2/backend/app/cli/v2_feature_pipeline_native_loop.py:657`, `:768`, `:1499-1650`.
- **Mechanism:** current Redis values for higher-timeframe context, cross-asset context, regime, tape, TA, liquidations, unified features, orderbook, WSDS, microstructure and alternative data are merged numerically without preserving or checking a per-source `event_time`/`available_at`/`feature_cutoff <= decision_time`. The aggregate snapshot then stamps its own receipt/availability/generated fields with the current time.
- **Impact:** core OHLCV can be clean while an enriched value came from a future, stale, or untraceable upstream state. The merged values flow into the 1,908-element tensor, prediction, archive, replay and training.
- **Required proof before closure:** an envelope per source and field family, explicit availability/cutoff gates before merge, preserved upstream lineage, and property tests that future or unfinished inputs never reach a tensor.

### RE-004 — dirty lineage can be admitted to training by exceptions

- **Evidence:** source-proven.
- **Source:** `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py:527-584`; trainer filtering in `ppo_trainer.py:481-620`.
- **Mechanism:** high-confidence loss handling removes missing-trust reasons in one loader path; historical/schema-evolution paths can accept `MISSING_MASKED` or missing critical-family classifications when missing names are considered cost/optional masks.
- **Impact:** “trainer consumable” is not equivalent to “all required event-time lineage is valid.” Model updates and promotion evidence can include rows that the repository rules define as dirty.
- **Required proof before closure:** no confidence-based exception for temporal/lineage requirements; field-family-specific masks; a single final `classify_training_sample` immediately before batching; rejected-row reason accounting that cannot be rewritten downstream.

### RE-005 — validation and holdout are not demonstrably untouched

- **Evidence:** source-proven.
- **Source:** `v2/backend/app/services/native_trainer/trusted_replay/bootstrap.py:220-245`; `hybrid_cuda_trainer/ppo_trainer.py:294-479`, `:920-970`; persistent runtime holdout helpers around `persistent_cuda_trainer_runtime.py:468-705`.
- **Mechanism:** a strict temporal 70/15/15 manifest is generated, but the main training loader does not use its holdout boundaries to exclude rows. The online trainer takes a deterministic prefix and labels the last 20% of that selected batch validation. The persistent evaluator can later evaluate a manifest window that may already have appeared in training.
- **Impact:** reported out-of-sample performance can be contaminated and cannot support promotion/live-readiness claims.
- **Required proof before closure:** immutable sample IDs and cutoff-bounded train/validation/holdout manifests enforced at load time, overlap hashes against every training epoch, and a never-trained holdout lineage proof.

### RE-006 — trusted-replay directional label sign is wrong

- **Evidence:** source-proven.
- **Source:** `v2/backend/app/services/native_trainer/trusted_replay/dataset.py:305-322`.
- **Mechanism:** `trade_outcome` receives `abs(after_cost)` for both long and short target actions, making every non-flat directional counterfactual look like a win regardless of sign. MFE/MAE are also computed from raw price direction rather than side-adjusted excursion.
- **Impact:** supervised direction/confidence/reward targets can reward losing counterfactuals and distort evaluation.
- **Required proof before closure:** side-aware signed net return, side-adjusted MFE/MAE, golden long/short/up/down/flat examples, and regeneration/versioning of affected replay rows.

### RE-007 — publisher fail-closed state is split from downstream lineage

- **Evidence:** source-proven.
- **Source:** `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/publisher.py:1092-1098`, `:1176-1229`, `:1288-1291`; `runtime.py:675-717`; `market_state_integrity/trust.py:348-352`.
- **Mechanism:** `publish_prediction` shallow-copies its payload. Archive or replay failures mutate only the private copy and its boolean return is ignored. The caller unconditionally invokes `publish_lineage` on the original. That original already contains a replay ID and key, and the trust validator accepts their presence without checking Redis when no client is supplied.
- **Impact:** archive/replay write failure can still produce orchestrator/risk/paper lineage; status and prediction counts can overstate durable publication.
- **Required proof before closure:** return a typed immutable publication result, propagate the mutated/validated payload, require positive durable-write evidence, suppress all downstream lineage on failure, and test Redis/archive failure injection.

### RE-036 — temporal GRU windows can attach future frames

- **Evidence:** source-proven.
- **Source:** `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py:136-145`; `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/temporal_windowing.py:74-105`; trainer selection/reordering at `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/ppo_trainer.py:294-326`, `:442-456`.
- **Mechanism:** `TrainingExample` has no top-level `decision_time`. The windower therefore substitutes the incoming list index for every active training row even though the real time remains nested in `trust_row`. Replay/feedback assembly and PPO-first selection are not a global chronological sort, so an earlier list element can have a later real decision time than the target row.
- **Impact:** with the deployed GRU temporal branch enabled, a training window can contain a future feature frame. That is look-ahead leakage even when every individual row passed its own point-in-time checks.
- **Required proof before closure:** parse and require the nested trust-row decision time, sort within symbol/timeframe by that time, reject missing/unparseable time instead of using list position, assert every frame time is no later than the target time, and add shuffled/future-frame rejection tests.

## P1 — high operational or model-evidence risk

### RE-008 — frozen fee-gate result is assigned directly

- **Evidence:** source-proven and repeated runtime traceback observed.
- **Source:** `v2/backend/app/cli/v2_trade_management_paper_loop.py:28252-28306`; frozen `FeeRatioGateResult` at `v2/backend/app/services/trade_management_paper/service.py:126-133`.
- **Impact:** qualifying cycles raise `dataclasses.FrozenInstanceError`; downstream behavior depends on outer exception handling and can interrupt normal candidate processing.

### RE-009 — paper override policy defeats documented gates

- **Evidence:** source-proven.
- **Source:** paper loop around `:28225-28345`, `:29211-29300`, `:29755-30027`; preemptive helper around `:15447-15511`.
- **Behavior:** confidence thresholds can override strategy router, pre-trade, fee ratio, A+ classification, one-minute strict gate, the entire temporal-rejection list, tier, directional guard, sizing, churn, portfolio freeze, and missing loss probability. The fee gate is advisory in the strict local conjunction.
- **Impact:** documentation and emitted sub-gate evidence do not describe the effective admission policy. Some payloads can say A+ false while the effective mutable local result is true.

### RE-010 — multi-timeframe `feature_cutoff` understates newest information

- **Evidence:** source-proven.
- **Source:** `v2/backend/app/services/market_state_integrity/canonical_candles.py:468-473`; similar bootstrap derivation.
- **Mechanism:** cutoff is the minimum close time among selected 1m/5m/15m/1h/4h candles. If every selected candle contributes, the newest information boundary is the maximum, while the complete vector of per-timeframe close/availability times must be preserved.
- **Impact:** a record can claim an earlier cutoff than information actually used, weakening MASA/PPO ordering checks.

### RE-011 — REST-array candle lineage fabricates/loses receipt semantics

- **Evidence:** source-proven.
- **Source:** `_closed_klines` at `v2_feature_pipeline_native_loop.py:411-436`; canonicalization paths in the trainer loader.
- **Mechanism:** list-format klines are accepted from close timestamp alone, with no explicit finality or availability field. Historical REST arrays may be canonicalized with `ingested_at` equal to candle close, not actual backfill receipt.
- **Impact:** a backfilled candle can appear available at market close and leak into a historical decision window.

### RE-012 — tensor fallback treats valid zero as missing/fallback

- **Evidence:** source-proven.
- **Source:** `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/tensor_builder.py:1633-1700`.
- **Mechanism:** chained Python `or` expressions replace legitimate numeric zero with another source or `None`. Source-availability bits mean only “numeric value present,” not “source was temporally valid and available.”
- **Impact:** zero-valued market features can be silently rewritten and masks overstate provenance quality.

### RE-013 — model identity does not identify weights or all behavior

- **Evidence:** source-proven.
- **Source:** `hybrid_cuda_trainer/model.py:56-140`; checkpoint manager `checkpoint.py:198-251`.
- **Mechanism:** `model_id` hashes input dimension, seed, hidden size, residual blocks and optional encoder settings, but not weights and not every behavior-affecting parameter such as dropout. Architecture-derived checkpoint names can be overwritten. Latest load filters primarily by input dimension and does not fall back to an older valid manifest after the selected blob fails.
- **Impact:** two materially different learned policies can share identity, lineage cannot prove exact weights, and a corrupt latest blob can prevent otherwise possible recovery.

### RE-014 — the “PPO” objective lacks behavior-policy/action identity

- **Evidence:** source-proven.
- **Source:** `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/model.py:378-408`; `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/publisher.py:1387-1410`; `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/ppo_trainer.py:998-1001`, `:1193-1216`, `:1312-1324`, `:2116-2145`; data targets at `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py:2178-2224`.
- **Behavior:** entry `old_log_prob` describes the selected action under the expected-move-adjusted and renormalized published policy. The new log probability is gathered from raw current logits at `policy_target_actions`, a future outcome-supervised label rather than a preserved behavior-action index. The single-direction guard can replace a taken long/short target with hold while retaining the long/short old log probability. The resulting ratio is therefore not guaranteed to compare the same action or probability transformation. Separately, advantage is immediate `reward - old_value`, with no GAE or discounted return; `gamma`, `done`, and trajectory fields do not build a multi-step return. Supervised action/value/move/MASA/confidence losses coexist, AdamW is recreated, and optimizer state is not checkpointed.
- **Impact:** the clipped ratio can be mathematically invalid, and reported PPO activity can be dominated by supervised outcomes. Changing a “PPO” knob may not have the expected algorithmic effect.
- **Required proof before closure:** persist the behavior-action index and behavior-policy transformation/version, evaluate the new probability for that same action under the same transformation, prohibit supervised hold substitution from changing PPO action identity, and add ratio-one/no-weight-change golden tests before interpreting the objective as PPO.

### RE-015 — runtime and replay transaction costs disagree

- **Evidence:** source-proven.
- **Mechanism:** trusted replay uses a 2 bps round-trip default in one path while current paper/runtime evidence uses materially higher round-trip costs (observed 12 bps policy in the runtime trace). Environment actions may charge round trip on entry and again on close.
- **Impact:** training labels, paper economics, and evaluation are not calibrated to one cost model.

### RE-016 — installed runtime is not reproducible from the repository

- **Evidence:** observed.
- **Snapshot:** 157 installed `ai-bot*` user unit files; 81 running services; 36 timers; 3 failed units. Fifty-seven installed unit basenames were absent from all versioned unit directories, while 33 versioned names were not installed.
- **Source/state:** `/home/wali/.config/systemd/user`; versioned fragments in `claude_worklog/systemd/user`, `tools/systemd_units`, `claude_worklog/tools/systemd`, and `v2/tools/systemd`.
- **Impact:** cloning the repository does not reproduce the workstation. An operator cannot prove which manifest is canonical or safely roll back.

### RE-017 — deployed backend bypasses the release artifact

- **Evidence:** observed.
- **Mechanism:** user-systemd drop-ins ultimately run four Uvicorn workers directly from mutable `v2/backend`, overriding the release symlink. The release symlink points to an older build.
- **Impact:** Git working-tree changes can affect the next restart without a build/promote step; rollback and provenance claims are weak.

### RE-018 — unit syntax/path defects and failure masking

- **Evidence:** observed with `systemd-analyze --user verify`.
- **Behavior:** eight units have an unquoted `Environment=PYTHONPATH=...AI BOT REBUILD...`, truncating the effective value. The orderbook rollover ExecStart path is invalid. Ten installed services use `|| true` or equivalent wrappers that can make a failed worker look successful. Eighty-three specify `Restart=always`.
- **Impact:** import behavior differs per unit, failures can be hidden/restarted indefinitely, and a seemingly small path edit changes module identity.

### RE-019 — conflicting destructive retention policies

- **Evidence:** observed/source-proven.
- **Source:** installed user units `ai-bot-v2-orderbook-replay-rollover.{timer,service}` and `ai-bot-v2-disk-retention-janitor.{timer,service}`; `tools/orderbook_replay_rollover.py:10-12,46-83`; `claude_worklog/tools/v2_disk_retention_janitor.py:31-62`, `:99-173`, `:176-255`; current result `claude_worklog/disk_janitor/disk_janitor_status.json`.
- **Observed state:** at `2026-07-16T08:32:41Z`, both timers were loaded, enabled, active and persistent. The broken 100 GiB rollover service was scheduled every six hours; the non-dry-run janitor was scheduled every 15 minutes. The janitor’s `2026-07-16T08:27:21.352199+00:00` status reported deletion of ten `/tmp/holdout_tail_*` files and 89,478 bytes, proving mutation occurred during the audit. That cycle deleted no replay directories and changed no capped JSONL or `.out` log.
- **Behavior:** rollover deletes oldest replay directories until a 100 GiB cap. The janitor separately deletes replay days older than five days or beyond its 300 GiB/free-space policies, tail-replaces oversized JSONL, truncates oversized logs, and deletes temporary holdout tails older than six hours. The replay tree was observed at about 259 GiB early and 247 GiB later; the audit does not attribute that size change to either process. Merely repairing/reloading the rollover service can let its already-active persistent timer execute and make roughly 147–159 GiB eligible at those observed sizes.
- **Impact:** evidence preservation, holdout work and audit measurements race automatic deletion. “Fixing” one service can destroy a large replay corpus and invalidate evidence/checksums.
- **Required proof before closure:** approved single retention authority, protected-dataset manifest, dry-run deletion manifest, checksum/index/tombstone handling, tested recovery, and captured timer state. Pausing, disabling or masking an installed timer is an approval-gated operational change, not an implicit audit action.

### RE-020 — Redis is near its configured limit without durable HA

- **Evidence:** observed snapshot.
- **State:** about 1.11 million keys and 31.03 GiB used against a 32 GiB limit, `allkeys-lru`, AOF disabled, RDB-only, no replica/backup timer or tested restore runbook found.
- **Impact:** eviction can silently remove lineage/features/status; a crash can lose post-snapshot state; Redis key presence is not durable proof.

### RE-021 — security controls are mostly scaffolds

- **Evidence:** source-proven and observed.
- **Source:** `v2/backend/app/main.py`; middleware/auth modules; `auth/security.py:28-329`; `auth/users.py:309-330`; `auth_rbac.py:192-221`.
- **Behavior:** nine of eleven middleware layers are pass-through; current OpenAPI declares security on zero operations even though dependencies protect some handlers. Approval/step-up/RBAC middleware does not enforce. Some subprocess-launching and paper mutation endpoints are unauthenticated or optional-auth. Login returns a token in JSON as well as an HttpOnly cookie. Non-production step-up can pass without a configured TOTP secret.
- **Impact:** route names and middleware ordering overstate protection. Exposure through the public tunnel must be evaluated route by route.

### RE-022 — credentials and auth state have unsafe local exposure

- **Evidence:** observed without reading or recording secret values.
- **Behavior:** `v2/.env.local`, auth/revocation state, and related files were group/world-readable (0664). A system-level tunnel service embeds a bearer credential in its command line, making it visible to process inspection. Auth writes a process secret during import if the environment variable is absent.
- **Impact:** local users/processes and copied logs can expose credentials; import-time file creation complicates reproducibility. The exposed tunnel credential should be rotated through the provider and moved to a protected credential mechanism.

### RE-023 — four backend workers race on local JSON state

- **Evidence:** source-proven and deployed topology observed.
- **Source:** `auth/users.py:309-330`; backend drop-ins.
- **Mechanism:** atomic file replace is guarded only by a process-local lock. Four Uvicorn workers can read the same old state and lose one update. Per-process metrics/history and revocation/cache state are fragmented.

### RE-024 — central ORM/Alembic persistence is uninitialized and optional schemas bypass migrations

- **Evidence:** observed/source-proven.
- **State:** `v2/backend/v2_paper_trading.db` is empty; central application metadata and Alembic have no initialized schema/versions. Optional user, revocation, alert and trader-account SQL repositories are implemented, but can auto-create their tables outside Alembic and were not the observed default deployment. Runtime truth was Redis, local JSON, public artifacts, JSONL/logs, model/archive files, and one separate closed-loop SQLite WAL database.
- **Impact:** architecture diagrams implying one migrated relational authority are incorrect; enabling an optional repository can create environment-specific schema without a reviewed upgrade/rollback history.

### RE-025 — backup/rollback is not WAL-safe

- **Evidence:** source-proven.
- **Source:** closed-loop `SQLiteLeaseStore` and `claude_worklog/tools/v2_codex_spark_rollback.py:135-147`.
- **Mechanism:** rollback copies only the main SQLite file while a live WAL exists.
- **Impact:** uncheckpointed tasks/leases/workers can be omitted from the backup.

### RE-026 — dual Python import namespaces can duplicate singleton state

- **Evidence:** source-proven and deployment-observed.
- **State:** hundreds of imports mix `app.*` and `v2.backend.app.*`; units use different `PYTHONPATH` arrangements.
- **Impact:** one physical file can load under two module identities, duplicating locks, caches, registries, classes and import-time side effects.

### RE-027 — concurrent trainer/publisher authorities are ambiguous

- **Evidence:** observed.
- **Behavior:** persistent CUDA and continuous offline GPU trainer services were both active despite older “one trainer” documentation. Two identical portfolio publisher processes were active. The RL inference sidecar does not load the native checkpoint even when it reports the active checkpoint ID.
- **Impact:** last-writer-wins state, duplicated work, misleading lineage and unclear promotion ownership.

### RE-028 — checkpoint/archive integrity is incomplete

- **Evidence:** source-proven.
- **Behavior:** NPZ loading correctly uses `allow_pickle=False` and validates shape/finite tensors, but the manifest has no cryptographic weight checksum. Durable archive manifest updates are disabled on ordinary prediction writes; rollover deletes blobs/index entries without durable tombstones. Offline cache/H2L paths deserialize pickle without an artifact trust boundary.
- **Impact:** model and replay provenance cannot be independently verified; archive absence can be ambiguous; untrusted pickle remains a code-execution risk if its input boundary expands.

### RE-029 — observability has multiple non-authoritative truth planes

- **Evidence:** observed/source-proven.
- **Behavior:** Redis, public runtime JSON, worklog artifacts, process-local metrics and large logs can disagree. Logging setup is a placeholder; user journals were empty; webhook/Telegram paths were not actually sending. Prometheus rules exist without the corresponding installed stack. More than 10,000 log/JSONL files occupied roughly 266 GiB.
- **Impact:** a green dashboard may be a stale derived artifact, not current worker truth. Incident reconstruction and disk pressure compete with replay retention.

### RE-030 — build, dependency and test gates are incomplete

- **Evidence:** observed/source-proven.
- **Behavior:** no active root-enforced backend/frontend GitHub Actions workflow; the tracked `v2/.github/workflows/ci.yml` is a dormant definition that must be installed under repository-root `.github/workflows/` before GitHub enforces it. The Python manifest omits runtime packages such as Torch/NumPy/Gymnasium/psutil; frontend dependency tree is unmet; Docker compose is empty; `gitleaks` is absent and the secret-scan script exits success when missing; frontend checks can skip; a test wrapper targets an absent path. A focused canonical-candle/pipeline-trust run passed 66 tests and failed six publisher tests before their assertions because the test tensor fixture lacks the production `missing_mask` field now read by `_trusted_replay_snapshot` (`publisher.py:562`; `test_pipeline_trust_runtime_enforcement.py:653-670`).
- **Impact:** a clean checkout is not build-reproducible, a green shell exit can mean a check never ran, and six intended publisher/trust assertions currently provide no protection. The six failures are test-fixture contract drift, not evidence that the canonical temporal assertions failed.

### RE-031 — integration tests have touched real paper state before

- **Evidence:** source documentation.
- **Source:** `v2/backend/tests/integration/cli/conftest.py:1-10` records prior overwriting of runtime paper state and loss of closed-trade history; its fixture isolates only one path.
- **Impact:** running the full suite in this workspace can mutate authoritative state. This audit intentionally ran only the isolated, scoped checks listed in the master audit and did not run the full suite.

## P2 — drift and maintainability

### RE-032 — documentation is materially stale

- Older documents report 53 services/40 timers/one failure, 226 CLI modules, 1,419 tests, one trainer, read-only V2 APIs, port assumptions, and risk “final authority” that do not match the 2026-07-16 source/runtime.
- `v2/README.md` still describes a planning-only system.
- Generic docs under `docs/master`, `docs/operator`, and `docs/sre` are short clones and are not subsystem specifications.

### RE-033 — public deployment routing is external state

- Backend binds loopback:8000; frontend preview binds all interfaces:5173; local CORS allows only localhost origins. The Cloudflare tunnel route is provider-side state with no complete local config.
- A clone cannot reproduce the public hostname, TLS, or origin routing from this repository.

### RE-034 — API contract counts require definitions

- The regenerated static atlas contains 905 route definitions/references across server and clients; AST found 248 decorators; current OpenAPI exposed 189 paths/193 HTTP operations plus seven mounted WebSocket paths outside OpenAPI. These counts answer different questions and must not be substituted for one another.

### RE-035 — frontend and mobile contracts can drift

- Runtime JSON beneath `frontend/public/operator_runtime` is not automatically copied because the build disables normal public-directory behavior.
- Swift app/core targets duplicate endpoint, API-client and model definitions. A backend field rename must be checked against both TypeScript and Swift registries.

## Closure rules

A finding is not closed by a code comment, status JSON, or a passing happy-path unit test. Closure requires:

1. the exact source change and impact analysis;
2. isolated negative/edge tests;
3. point-in-time and dirty-sample proofs where data is involved;
4. deployed-unit reconciliation where operations are involved;
5. regenerated atlas and contract registries;
6. a read-only runtime verification snapshot;
7. explicit operator approval before any live-execution, order, risk, strategy, PPO, MASA, or destructive-retention change.
