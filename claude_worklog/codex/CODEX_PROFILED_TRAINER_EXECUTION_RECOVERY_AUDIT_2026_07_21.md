# Authenticated Profiled Trainer Execution Recovery Audit

**Audit date:** 2026-07-21 (America/New_York)

**Audited source commit:** `9fc6c55ebdea7b79afa8bbe21a5043b8579463b6`

**Audited source subject:** `fix(trainer): enforce causal WSS policy migration`

**Audit method:** isolated detached worktree, read-only service inspection, targeted unit tests, and a synthetic end-to-end authenticated sample reconstruction

**Runtime changes made:** none

**Services restarted or deployed:** none

**Live/order paths touched:** none

## Executive verdict

**NO-GO for optimizer activation, checkpoint writing, model promotion, prediction, or paper/live use.**

The persistent process is healthy as an integrity observer. It is not a trainer and it cannot become one automatically. The currently implemented local authenticated-profile path proves a useful causal sample and canonical outcome label, but four independent boundaries remain:

1. There is no concrete independent rollback-resistant witness, witness service, or authenticated witness client.
2. A valid profiled example is rejected by the current PPO admission path because two different `available_at` clocks are conflated and because the example intentionally does not impersonate legacy trust schemas.
3. The checkpoint inventory accepts only the legacy `trusted_replay_archive` row source, so a profiled row cannot reach durable weights even if PPO admission were bypassed.
4. The checkpoint and serving paths do not bind or reproduce the authenticated sparse feature-selection policy. Training on the 35-slot profiled projection and serving on a different 446-slot availability pattern would be unproven train/serve skew.

The minimum safe recovery is therefore not a boolean flip and not a restart. It is a new, explicit authenticated-profiled training lane, introduced in ordered slices and left fail-closed until each preceding boundary is independently proven.

This conclusion does **not** mean the local authentication work is wasted. The current ledger, cost evidence, point-in-time checks, canonical label archive, fixed observation manifest, and page-consumption candidates provide much of the data-plane foundation. They must remain intact while the missing authority and model-lifecycle contracts are added.

## What is running now

Read-only inspection at approximately 18:12 EDT showed:

> **Superseding deployment observation, 18:16 EDT:** after this isolated audit
> completed, the root agent deployed the exact audited commit
> `9fc6c55ebdea7b79afa8bbe21a5043b8579463b6` to the observation-only trainer
> service. The new process is PID `2350183`, active/running with `NRestarts=0`
> since 18:14:55 EDT. Its release mount is read-only in the service namespace,
> its integrity probe remains successful across repeated cycles, and it still
> reports 0 strict/profiled candidates with every training/checkpoint/model/
> prediction/paper/live authority false. The table below is retained as the
> audit-time evidence that preceded that controlled cutover; its release/PID
> rows are no longer current.

| Item | Observed state | Meaning |
|---|---|---|
| `ai-bot-v2-native-cuda-trainer-persistent.service` | loaded, active/running, PID `2121888`, `NRestarts=0`, active since 11:25:33 EDT | Process health is good. |
| Immutable release | `0f9b5c93b75b11b2f21f70663b9cc1ba34413423` | The running release is pinned through a systemd drop-in. It is not this audit worktree. |
| Resident CLI mode | `waiting-for-authenticated-samples` | Observation only; no CUDA/model/training construction. |
| Publisher unit | `LoadState=not-found`, inactive/dead | No installed profiled producer service exists under the queried unit name. |
| Manifest/head/consumer unit | none found | No resident factory or external-witness consumer is installed. |
| Latest status timestamp | `2026-07-21T18:12:12.351821Z` | Observer continues to write its one permitted status file. |
| Ledger integrity | 2 records and 2 append receipts verified | The ledger is readable and internally coherent. |
| Strict/profiled candidates | 0 / 0 | No consumable authenticated profile corpus exists in the resident path. |
| Full sample authentication | false | The waiting process expressly does not do it. |
| Training/checkpoint/model/runtime | all false | Correct fail-closed state. |

The service command is the waiting CLI with ledger and trusted-cost CAS paths. The drop-in pins the working directory and `PYTHONPATH` to immutable release `0f9b5c...`, sets `LIVE_GATE=blocked_human_only`, and checks the deployment tree is clean before start.

The CLI itself exposes exactly one enum value in `v2/backend/app/cli/v2_native_cuda_trainer_persistent_loop.py`: `WAITING_FOR_AUTHENTICATED_SAMPLES`. It lazy-imports only `profiled_training_waiting_runtime_v1`. It does not import the legacy persistent CUDA trainer, and no automatic transition is present. That is deliberate safety behavior, not a crash or scheduling defect.

## Actual data and control flow

The implemented path stops at local staging:

```text
canonical finalized Binance WSS candles
  -> authenticated profile transform
  -> 35 selected OHLCV logical feature slots
  -> profiled model-feature snapshot record
  -> causal cost evidence
  -> atomic parent/child ledger append + postcommit receipts
  -> ProfiledTrainingLedgerSampleV1 reopen
  -> fixed-cutoff observation manifest
       + canonical finalized 5m future label archive
       + HMAC-authenticated immutable manifest entries
  -> bounded direct page reopen
  -> local head candidate
  -> local consumption epoch
  -> ordered local page receipts
  -> local completion candidate
  -X- independent external witness acknowledgement (not implemented)
  -X- profiled optimizer admission adapter (not implemented)
  -X- profiled checkpoint inventory/binding (not implemented)
  -X- train/serve profile-equivalent projection (not implemented)
  -X- authenticated-profiled resident training mode (not implemented)
```

Repository-wide non-test call-site searches found no service or CLI invoking:

- `build_profiled_training_observation_manifest_v1`
- `stage_profiled_training_observation_head_candidate_v1`
- `stage_profiled_training_observation_consumption_epoch_v1`
- `stage_profiled_training_observation_page_receipt_v1`
- `stage_profiled_training_observation_completion_candidate_v1`
- `read_profiled_training_observation_page_v1`

The functions call one another within their factory modules and are exercised by tests, but there is no production orchestrator around them.

## Component-by-component findings

### Waiting observer

`profiled_training_waiting_runtime_v1.py` is intentionally read-only except for its status JSON. Its status contract explicitly denies:

- CUDA or model construction
- full sample authentication
- legacy prefetch
- Redis access
- checkpoint access
- publisher access
- paper-guard access

It performs a bounded ledger integrity and structural profile-child readiness probe. It cannot safely be called a trainer publisher, trainer loop, or model updater.

### Profiled ledger loader

`profiled_training_ledger_loader_v1.py` reopens authenticated ledger children, their exact parents, append receipts, source payloads, profile evidence, and cost CAS objects. A returned `ProfiledTrainingLedgerSampleV1` can set `trainer_admission_authorized=True` for the local sample contract while retaining prediction, checkpoint, paper, live, execution, and runtime authority as false.

That local admission flag is not external anti-rollback authority and is not sufficient to run an optimizer.

The loader/factory path is currently unsuitable as an unbounded resident scan: it may inspect the total ledger to establish a fixed high-water. The manifest makes subsequent page reopening bounded, but a service still needs resource limits, scheduling, crash recovery, and observation-cutoff ownership.

### Observation manifest

`profiled_training_observation_manifest_v1.py` constructs a fixed-observation, HMAC-authenticated SQLite manifest. It binds:

- the ledger high-water and every observed entry disposition
- exact sample/parent/receipt identities
- source/cost CAS identities
- feature tensor and availability identities
- finalized canonical 5m label path and receipts
- observation cutoff and per-entry availability
- manifest entry order and roots

Unavailable or rejected entries remain part of the manifest stream. This is important: consumers may not silently skip them when proving full consumption.

The manifest grants no optimizer, checkpoint, model, prediction, paper, live, execution, or runtime authority.

### Local head and consumption candidates

`profiled_training_observation_manifest_head_v1.py` explicitly states that a coherent rollback or fork of the complete local CAS is not detectable locally. It defines deterministic local head, epoch, page, and completion candidates, all with authority false.

It defines a `ProfiledTrainingObservationExternalWitnessV1` protocol with `read_latest`, `compare_and_append`, and `read_event`, plus opaque event/receipt containers. No concrete implementation or non-test consumer exists.

The opaque witness values prove byte-hash integrity only. They do not by themselves authenticate a witness identity, establish freshness/latest state, prevent a locally coherent rollback, or prove that a successor event was durably acknowledged by an independent system.

### Generic PPO trainer

`V2HybridPPOTrainer._filter_trusted_training_rows` applies legacy trust-row requirements through `_extra_rejection_reasons`. Those requirements include a legacy trust schema, MTF snapshot identity, replay snapshot identity, market-state integrity evidence, feature freshness, latency/payload age, and decision-candle clocks.

The authenticated profile example intentionally does not fabricate those unrelated legacy objects. It carries its own stronger source/profile/ledger/label lineage instead. Therefore it needs a distinct typed validator, not relaxed generic checks and not fake legacy IDs.

### Hybrid trainer runtime

`run_hybrid_trainer_cycle` constructs `V2HybridTrainerDataLoader`, which loads the existing Redis/trusted-replay lane. It does not accept an authenticated observation-manifest corpus or witness authorization object.

Re-enabling this legacy runtime would therefore re-admit a different input lane and would bypass the new manifest/witness boundary. It cannot be used as the shortcut for restoring the profiled trainer.

### Checkpoint inventory

`hybrid_cuda_trainer/training_sample_identity.py` hard-codes:

```text
SUPPORTED_DURABLE_LABEL_ROW_SOURCE = "trusted_replay_archive"
```

Both authenticated trust evidence and durable label binding reject any other row source with `TRAINING_SAMPLE_LABEL_LANE_UNSUPPORTED`. `run_hybrid_trainer_cycle` builds the inventory before optimization and again after optimization, so failure removes optimizer rows and prevents durable checkpoint creation.

A profiled checkpoint path must bind the manifest and external witness evidence directly. It must not reconstruct a different identity from the generic replay archive.

### Feature ABI and serving

The generic feature registry and profiled projection both produce 446 logical slots, represented as 1,784 model inputs when value, availability, selection, and age planes are flattened. Dimension equality is not semantic equality.

The current authenticated profile selects 35 OHLCV slots. Remaining values are zero with availability and selection masks set to zero. Its lineage contains `logical_profile_selection_mask_sha256`, but repository searches found no corresponding binding in the hybrid checkpoint/model lane or prediction runtime.

Without that binding, a model could be trained on one availability/selection distribution and served on another. Activation must choose one of these explicit contracts:

1. Project serving inputs through the same authenticated profile and bind its policy/configuration/implementation hashes in every checkpoint; or
2. Define and validate an adaptive mask contract whose train and serve semantics are identical and whose policy changes are versioned and checkpoint-bound.

Until then, matching the integer input dimension is insufficient.

## Point-in-time and clock audit

The local profiled sample/manifest path enforces the important causal ordering. Those checks must not be weakened during integration.

| Clock | Meaning | Required ordering |
|---|---|---|
| `event_time` | Time the source market event occurred | Must be within the final source candle/path being represented. |
| source `available_at` | When the feature source data was actually usable | `source available_at <= feature_cutoff <= decision_time`. |
| `ingested_at` | When the local ingestor received/persisted source data | Must not be substituted for `event_time` or finality. |
| `generated_at` | When the derived profile/sample record was generated | Must not create pre-decision availability; it is lineage, not event time. |
| `feature_cutoff` | Latest source information included in features | Must be `<= decision_time`; no unfinished higher-timeframe candle may cross it. |
| `decision_time` | The simulated/model decision boundary | Every decision feature must have been available by this instant. |
| `label_available_at` | When the future outcome became final and usable for supervised training | Must be strictly after `decision_time` and before the observation cutoff. |
| `postcommit_readback_at` / `trainer_sample_available_at` | When the complete training sample was durably readable after its append | Correctly occurs after `decision_time`; it is not feature availability. |
| manifest observation time | Frozen knowledge cutoff for the corpus | Sample and label receipts must be committed before it; manifest uses a strict prior-microsecond cutoff. |
| `execution_time` | When an order would execute | Not authorized anywhere in this lane and must never be inferred from decision or observation time. |

Additional verified invariants include:

- source records must identify `source=binance_wss` and `is_backfilled=False` under the audited V2 policy;
- parent, child, cost, source payload, and append/postcommit CAS identities are reopened and matched;
- `feature_cutoff`, source availability, and causal cost evidence cannot exceed `decision_time`;
- record generation cannot exceed `decision_time` under this source contract;
- sample postcommit is strictly after the decision and strictly before the manifest observation;
- canonical label candles must be closed/final, contiguous, and cover the exact endpoint/horizon;
- label append and postcommit receipts must precede the manifest observation;
- the label becomes available strictly after the decision, preventing target leakage;
- bounded runtime page reopen is tied to the manifest's fixed high-water and exact ledger receipts.

No future-leaking, unfinished-candle, or missing-lineage bypass was found in the audited local factory path.

## Reproduced optimizer incompatibility

An isolated synthetic test used the repository's authenticated test builders to create a valid profiled ledger chain, a valid finalized canonical label, a fixed observation manifest, and a directly reopened training example. Passing that real example to `V2HybridPPOTrainer._filter_trusted_training_rows` produced:

```text
trusted_count 0
reasons {
  'AVAILABLE_AT_AFTER_DECISION_TIME': 1,
  'FEATURE_FRESHNESS_MISSING_OR_EXPIRED': 1,
  'LATENCY_OR_PAYLOAD_AGE_MISSING': 1,
  'MARKET_STATE_INTEGRITY_SCORE_BELOW_TRAINING_MIN': 1,
  'MTF_SNAPSHOT_ID_MISSING': 1,
  'MTF_SNAPSHOT_INVALID': 1,
  'REPLAY_SNAPSHOT_ID_MISSING': 1,
  'TRUST_SCHEMA_MISSING': 1,
  'candle_open_or_close_time_missing': 1,
  'decision_cutoff_time_missing': 1,
  'source_event_time_missing': 1
}
outcome_supervised False
decision_time 2026-07-21T12:00:00.900000Z
feature_cutoff 2026-07-21T11:59:59.999000Z
available_at 2026-07-21T18:03:36.195830Z
label_available_at 2026-07-21T12:20:00.000000Z
```

The first rejection exposes the clock collision:

- `_example_from_authenticated_entry` currently sets `trust_row["available_at"]` to `sample.postcommit_readback_at`.
- The manifest contract also correctly names this value `trainer_sample_available_at` and states it must exceed the decision.
- The generic PPO validator interprets `available_at` as feature availability and requires it not to exceed the decision.

Both components are internally consistent with different meanings of the same key. The safe repair is to keep feature availability and trainer-sample durability in separate typed fields. Do not move the postcommit clock backward, relabel it as a feature clock, or delete the causal check.

The example also has a valid authenticated future label but lacks the legacy `outcome_targets`/`realized_after_cost_reward` representation, so `_has_outcome_supervised_targets` returns false. The profile adapter must construct a typed supervised target from the authenticated canonical label binding. PPO/behavior-policy terms must remain disabled unless genuine behavior receipts exist.

## External witness requirements

The external witness is a hard authority prerequisite, but it is not the only blocker. A compliant witness integration must provide all of the following:

- independent durability outside the locally rollbackable CAS;
- authenticated server/witness identity pinned in configuration;
- authenticated responses or signed events, not caller-supplied opaque hashes;
- linearizable or otherwise explicitly modeled compare-and-append semantics;
- verifiable latest/head reads and event reads;
- fork and stale-head rejection;
- monotonic successor linkage to the previously externally acknowledged completion;
- exact manifest head acknowledgement before consumption starts;
- externally acknowledged page consumption in order, including unavailable entries;
- externally acknowledged full completion before optimizer authorization;
- replay/idempotency semantics for crashes and restarts;
- separate role keys/identities for manifest, local head/epoch/page staging, and independent witness verification.

A local HMAC, local SQLite database, local immutable payload store, or the existing opaque witness event dataclass cannot satisfy independence on its own.

Choosing and provisioning the external witness changes external state and trust ownership. It requires an operator decision and credentials; this audit does not fabricate or silently choose that authority.

## Data-source implications

This recovery lane currently authenticates the strict 35-slot OHLCV profile from finalized Binance WSS source records. It does not consume Moralis or every other ingestor merely because those ingestors exist elsewhere in the system.

That is acceptable for a causal bootstrap only if the checkpoint truthfully binds the selection policy and the serving path uses the identical policy. It must not be described as training on all available data.

Moralis and other optional providers need separate freshness, availability, source-time, and point-in-time contracts before their features can join this lane. Optional-source absence should reduce an authenticated availability mask and selection policy, not invent values, silently use stale data, or fail the entire trainer. A source's reappearance should flow only after its own freshness/finality and lineage gates pass.

CoinAPI may remain optional and dormant when there is no active subscription. Its absence must not block the strict profile. It should not be disabled or removed in a way that prevents future authenticated recovery, and subscription failures must not be interpreted as fresh zero-valued market evidence.

## Minimal fail-closed activation plan

Each slice below has a hard exit criterion. Later slices must not be merged into runtime authority before earlier evidence exists.

### Slice A — materialize the producer and fixed corpus

1. Provision the profiled publisher with exact read-only account-scoped Binance credentials, endpoint permission proof, an independent fingerprint HMAC key, immutable release pinning, clock/resource preflight, and no order permissions.
2. Install and run a bounded observation-manifest factory using the canonical finalized 5m label archive, fixed observation cutoff, dedicated manifest root, and a distinct manifest HMAC role key.
3. Confirm fresh V2 parent/child pairs, exact cost CAS objects, full manifest coverage, and direct bounded reopen.

**Exit criterion:** a complete local manifest can be reproduced and page-read, but every optimizer/checkpoint/prediction/paper/live/runtime authority remains false.

### Slice B — add independent anti-rollback witness

1. Operator selects and provisions the independent protected witness.
2. Implement a concrete authenticated client behind the protocol.
3. Append and verify a head event with compare-and-append semantics.
4. Consume every ordered page, including unavailable entries, and append witness acknowledgements.
5. Append and verify the completion event; bind it into the next observed head.

**Exit criterion:** forged, replayed, stale, forked, rolled-back, incomplete, or unauthenticated witness histories fail closed. Local candidates alone still cannot authorize optimization.

### Slice C — typed profiled optimizer admission

1. Define an immutable `AuthenticatedProfiledOptimizerAuthorization` assembled only from a fully verified external head and completion chain.
2. Separate decision-time feature `available_at` from `trainer_sample_available_at`.
3. Validate source/profile/ledger/cost/label/manifest/witness lineage directly; do not manufacture legacy MTF/replay identities.
4. Build supervised targets from the authenticated canonical label binding.
5. Keep PPO behavior-policy loss disabled without real behavior receipts; permit only the explicitly validated supervised objective.
6. Preserve non-finite checks, chronological/purged split rules, embargoes, label-observation cutoff, and sample identity before/after optimization.

**Exit criterion:** the valid witnessed fixture is admitted; the identical local-only, forged-witness, future-label, unfinished-candle, or altered-feature fixture is rejected.

### Slice D — profiled checkpoint inventory and model lineage

1. Add a separate profiled inventory implementation instead of weakening the `trusted_replay_archive` lane.
2. Bind manifest ID/root, witness head event, completion acknowledgement, ordered page root, sample IDs, label IDs, tensor identities, and exact optimizer inventory.
3. Require pre- and post-optimization inventories to match exactly.
4. Bind feature registry ABI, logical profile selection-mask hash, projection implementation/configuration, and source policy in checkpoint metadata.
5. Write only to a distinct candidate model directory and retain an explicit parent-checkpoint lineage.

**Exit criterion:** no checkpoint can be written from local-only state or an inventory that changes during optimization.

### Slice E — serving equivalence and explicit resident mode

1. Implement the same authenticated projection for prediction, or a separately versioned train/serve adaptive-mask contract.
2. Prove tensor values, availability, selection, ages, slot ordering, feature registry ABI, and projection policy are identical across training and serving fixtures.
3. Add an explicit `authenticated-profiled-training` CLI mode. It must import only the witnessed profile runtime and must not fall through to legacy Redis/trusted-replay loaders.
4. Use an immutable systemd unit/drop-in, separate state/model directories, bounded resource limits, crash-safe page consumption, and no automatic promotion from waiting mode.
5. Begin with optimizer/checkpoint candidate generation only, then holdout evaluation, then prediction shadowing, then paper-only use after independent gates. Live remains operator-controlled and outside this recovery.

**Exit criterion:** a restart cannot duplicate/omit consumption; profile-policy drift fails closed; a candidate cannot publish or trade without its later explicit gates.

## Required adversarial test matrix

At minimum, implementation must cover:

- valid profiled example accepted only after independently authenticated full witness completion;
- the same bytes without witness authority rejected;
- forged witness identity/signature, stale latest read, compare-and-append race, fork, rollback, and replay rejected;
- page omission, duplication, reordering, altered disposition, and skipped unavailable entry rejected;
- crash after local page receipt but before witness acknowledgement resumes idempotently;
- feature `available_at > decision_time` rejected while `trainer_sample_available_at > decision_time` is required;
- `feature_cutoff > decision_time` and MASA cutoff beyond PPO decision rejected;
- unfinished or noncontiguous label candles rejected;
- label availability at/before decision, after observation, or label postcommit after observation rejected;
- missing or altered parent/child/source/cost/append receipt rejected;
- generic legacy row cannot enter the profiled lane and profiled row cannot self-authorize through booleans;
- authenticated label produces only the intended supervised target; PPO term remains off without behavior receipts;
- exact optimizer input identity is unchanged before/after optimization;
- checkpoint binds witness, manifest, sample, label, ABI, profile selection, and projection identities;
- one-slot, one-mask-bit, slot-order, or projection-version train/serve drift rejected;
- missing/stale optional ingestor degrades only its authenticated availability, never fabricates freshness;
- local-only state never grants checkpoint, prediction, paper, live, execution, or runtime authority.

## Validation performed

Targeted tests at the audited commit:

```text
40 passed in 79.84s
```

Files exercised:

- `test_v2_native_cuda_trainer_persistent_loop_waiting_mode.py`
- `test_profiled_training_observation_manifest_v1.py`
- `test_profiled_training_observation_manifest_head_v1.py`
- `test_profiled_training_waiting_runtime_v1.py`

Additional diagnostics:

- reconstructed a valid authenticated profiled sample and label, built/read its manifest, and reproduced the zero-row PPO result shown above;
- verified generic and profiled shapes are 446 logical slots / 1,784 flattened model inputs;
- searched production call sites for manifest/head/epoch/page/completion orchestration and found none;
- searched for a concrete external-witness implementation and found none;
- searched the hybrid checkpoint and serving paths for `logical_profile_selection_mask_sha256` binding and found none;
- inspected systemd unit/drop-ins and latest observer status read-only.

The focused passing suite proves that the current observer and local factory remain fail-closed. It does not prove trainability or authorize promotion.

## Activation prerequisites checklist

The authenticated trainer is eligible for a controlled training-only GO only when every item is true:

- [ ] Fresh profiled producer is installed with proven read-only permissions and immutable release.
- [ ] Fixed observation-manifest factory is installed with dedicated keys/state and resource bounds.
- [ ] Canonical finalized label archive is fresh and its receipts precede the observation cutoff.
- [ ] Independent witness is selected, provisioned, identity-pinned, and adversarially tested.
- [ ] Full ordered manifest consumption has an externally verified completion acknowledgement.
- [ ] Typed profiled optimizer adapter separates all clock semantics and admits the valid fixture.
- [ ] Legacy/untrusted rows cannot enter the profile lane.
- [ ] Profiled checkpoint inventory passes before and after optimization.
- [ ] Checkpoint binds source/profile/projection/witness/manifest/sample/label identities.
- [ ] Training and prediction projection equivalence is proven.
- [ ] Explicit authenticated-profiled resident mode exists with no legacy-loader fallback.
- [ ] Crash/restart/idempotency and resource-limit tests pass.
- [ ] Candidate training runs produce finite metrics and reproducible checkpoints in an isolated candidate lane.

Paper or live authorization requires additional downstream evidence and is not implied by completing this list.

## Honest recovery interpretation

The trainer publisher cannot safely “come back” merely by restarting the healthy waiting observer. The earliest truthful milestone is local corpus materialization after exact read-only credentials and publisher/manifest service wiring. The earliest optimizer milestone follows only after an independent witness plus the optimizer and checkpoint adapters. No fixed hour estimate is defensible until the external witness choice and credentials exist, because they are outside the repository and define the authority boundary.

What can be guaranteed operationally is the process: use every causal, final, fresh, authenticated datum available; degrade optional missing sources explicitly; preserve full lineage; test each authority transition adversarially; and refuse to convert unknown or stale data into confidence. No software audit can guarantee a 1,000x market return, and bypassing these gates would reduce rather than improve the chance of achieving the stated objective.

## Files changed by this audit

- Created `claude_worklog/codex/CODEX_PROFILED_TRAINER_EXECUTION_RECOVERY_AUDIT_2026_07_21.md`.

No source, test, service, runtime-state, credential, model, checkpoint, paper-trading, or live-execution file was modified.
