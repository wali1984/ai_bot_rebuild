# Profiled Training Observation Coordinator V1

Status: the crash-resuming local coordinator is packaged, installed, enabled,
and running from immutable release `b0116f706f...`. Its first production
observation reached `HEAD_STAGED` and canonical
`WAITING_EXTERNAL_WITNESS_CONFIGURATION` with 18/18 manifest examples
admitted and zero label gaps. No independent witness is provisioned, so
external completion acknowledgment, optimizer admission, example reopening by
an optimizer, and checkpoint/model publication remain unavailable and all
downstream authority flags remain false.

Implementation checkpoints: caller `20a92dc75b`; protected credentials
`29504e5bcd`; resident CLI `6e34cce0c2`; service package `0936557c84`;
resident/read-only remediation `3d2ac428b0`; bounded provenance verification
`b0116f706f`; immutable pin `16f99785cb`.

Primary implementation:

- `v2/backend/app/services/native_trainer/profiled_training_observation_coordinator_v1.py`
- `v2/backend/app/services/native_trainer/profiled_training_observation_coordinator_state_v1.py`

Primary tests:

- `v2/backend/tests/unit/services/native_trainer/test_profiled_training_observation_coordinator_v1.py`

Related contracts:

- [PROFILED_BASE_PUBLISHER_CYCLE_STATUS_V1.md](PROFILED_BASE_PUBLISHER_CYCLE_STATUS_V1.md)
- [PROFILED_TRAINING_OBSERVATION_COORDINATOR_STATE_V1.md](PROFILED_TRAINING_OBSERVATION_COORDINATOR_STATE_V1.md)
- [PROFILED_TRAINING_EXTERNAL_WITNESS_RUNTIME_V1.md](PROFILED_TRAINING_EXTERNAL_WITNESS_RUNTIME_V1.md)

## 1. Scope and non-authority boundary

The caller turns one locally verified publisher-cycle status into an ordered,
crash-resumable evidence chain:

```text
publisher status
  -> PREPARED cursor
  -> immutable authenticated manifest
  -> local head candidate
  -> independently signed durable head
  -> consumption epoch
  -> contiguous authenticated inventory-page receipts
  -> local completion candidate
```

It does not reopen `TrainingExample` tensors for an optimizer, acknowledge
completion at the independent witness, admit an optimizer batch, write a
checkpoint/model, publish a prediction, authorize paper/live trading, submit
an order, or mark runtime wiring complete. All 11 downstream authority fields
remain exact `false` in its result.

`signed_head_durably_anchored=true` means the local witness journal contains a
verified remote append receipt and signed readback for that head. The current
protocol still reports `external_monotonic_manifest_head_verified=false` until
the separately designed authorization layer consumes that evidence.

## 2. Runtime bindings

Construction requires exact concrete types for the coordinator state store,
feature ledger, label archive, staging CAS, and optional witness runtime. It
also requires absolute normalized paths, namespace/lane, page size, and the
manifest/head/epoch key IDs and raw keys.

The state store now exposes `require_runtime_binding()`. Before a status or
cursor is read, it recomputes the three role-key commitments and requires:

- exact namespace and consumer lane;
- exact manifest, head, and epoch key IDs; and
- exact manifest, head, and epoch raw-key commitments.

This closes the gap where a caller could use different raw artifact keys that
shared the IDs stored in a cursor. The coordinator-state HMAC remains private
to the state-store object. Four-role distinctness and rotation rules are still
enforced by the state-store constructor and persisted chain.

## 3. Lock and recovery order

If a witness runtime is configured, every invocation first calls
`recover_pending_appends()`. Older durable network requests are retried in
journal order before the caller inspects a new publisher status.

The caller then holds the coordinator state's stable writer lease through the
entire local invocation. Every state transition receives that exact held
lease. The witness journal uses its own distinct lease; the two lease targets
are never interchanged.

Recovery accounting includes both:

- requests recovered by the preflight call; and
- requests recovered internally by `anchor_head_candidate()` if another
  pending operation appears between preflight and head anchoring.

The result requires `recovered <= network attempts <= recovered + 1`, because
one invocation can retry recovered requests and dispatch at most one new head.

## 4. Status selection and inflight rule

The strict 57-field status reader is called only when there is no cursor or
the latest cursor is already `LOCAL_COMPLETION_STAGED`.

An inflight cursor never reads or switches to a newer status. It resumes its
pinned `publisher_status_sha256`, observation cutoff, prepared factory clock,
manifest, head, epoch, page, and completion addresses. This prevents a rapid
publisher update from replacing a partially processed fixed observation.

For a completed cursor:

- exact same status hash plus cutoff returns `NO_NEW_PUBLISHER_CYCLE` with no
  state transition or witness append;
- same cutoff with a different status hash fails as binding conflict;
- an older cutoff fails as rollback;
- a reused status hash at a different cutoff fails; and
- a cutoff after the sampled factory clock fails before manifest creation.

The factory wall clock is persisted in `PREPARED` before manifest construction
and replayed exactly after a crash, preserving deterministic manifest identity.

## 5. Phase-by-phase behavior

| Cursor phase on entry | Caller action |
|---|---|
| no cursor/completed | verify status and begin a new prepared cycle, or return exact no-op |
| `PREPARED` | build deterministic immutable manifest and persist its address/counts |
| `MANIFEST_STAGED` | rehydrate prior completed head/completion, stage the successor head, persist address |
| `HEAD_STAGED` without witness | return `WAITING_EXTERNAL_WITNESS_CONFIGURATION` |
| `HEAD_STAGED` with witness | rehydrate exact head, compare-and-append remotely, persist durable anchor result |
| `HEAD_ANCHORED` | rehydrate head, stage exact lane/page-size epoch, persist address |
| `EPOCH_STAGED` | authenticate complete manifest and stage first inventory receipt, or zero-inventory completion |
| `PAGE_STAGED` | rehydrate latest receipt and continue at its exact end ordinal |
| terminal page | stage and persist local completion |

The successor-head path reopens both prior addresses carried by the completed
cursor. A new head cannot be staged with only one, with a different staging
root, or with a prior completion that belongs to another head/lane/manifest.

## 6. Page continuity and clocks

Before page work, the caller fully authenticates the pinned manifest again.
Each receipt is bound by the underlying protocol to:

- exact epoch and manifest summary;
- requested and resulting ordinals;
- previous receipt event;
- previous page transition;
- previous ordered-page root;
- entry-chain start and end;
- scanned/admitted/unavailable counts; and
- terminal `has_more_manifest_entries` state.

The caller persists each receipt before advancing in memory. On restart, it
reopens the latest persisted receipt and continues from its exact end ordinal.

Every page clock is canonical UTC microsecond text and must be no earlier than
the manifest factory clock or the preceding receipt's `verified_at`. A host
wall-clock rollback therefore fails closed instead of creating a descending
page chronology.

For zero inventory, no page is fabricated. The epoch advances directly to a
completion containing the protocol genesis receipt/transition/root values.

## 7. Result contract

The immutable result contains 33 public fields covering:

- classification, cycle/status/cutoff and final phase;
- current and newly committed transition counts;
- whether status was read and a cycle was started in this invocation;
- witness configuration, recovered operations and network attempts;
- page receipts staged in this invocation;
- manifest identity and sample counts;
- head revision and durable-anchor fact;
- local-completion and complete-state-chain facts; and
- 11 exact-false downstream authority fields.

The three classifications have separate invariants:

- waiting requires `HEAD_STAGED`, no witness runtime, no anchor/completion,
  and zero witness/page work;
- no-new requires completed phase, a status read, zero new state/page work,
  and no candidate dispatch; and
- local-completion requires completed phase, durable head, local completion,
  and at least one state transition in the invocation.

This prevents a no-op result from being relabeled as newly completed while
retaining its construction token.

## 8. Crash and retry matrix

| Interruption | Durable state on restart | Caller behavior |
|---|---|---|
| before prepared pointer | prior cursor | reread status and begin |
| after prepared pointer | `PREPARED` | rebuild exact manifest with persisted factory clock |
| after manifest CAS/file | prior or `MANIFEST_STAGED` | deterministic manifest replay or head staging |
| after head CAS | prior or `HEAD_STAGED` | deterministic head replay or witness append |
| ambiguous remote success | `HEAD_STAGED` plus pending journal request | recover exact idempotent request before cursor work |
| after durable witness journal commit | `HEAD_STAGED` or `HEAD_ANCHORED` | replay anchored operation without duplicate remote event |
| after epoch/page CAS | prior persisted cursor | harmless orphan or resume exact persisted address |
| after terminal page | terminal `PAGE_STAGED` | construct exact completion |
| after completion pointer | `LOCAL_COMPLETION_STAGED` | reauthenticate artifacts and return no-op until newer status |

## 9. Verification evidence

The checkpoint changed three files with 1,493 inserted lines: 918 caller
lines, a 74-line raw-binding method in the state store, and 501 caller-test
lines.

Final scoped evidence:

- seven cursor phases and three result classifications exercised;
- normal witness append, preflight/internal ambiguous recovery, restart from
  `HEAD_STAGED`, completed no-op, successor revision, and zero inventory;
- same-cutoff conflict, cutoff rollback, future cutoff, invalid clock, and
  wrong raw manifest-key commitment rejection;
- nondecreasing page-clock and hostile result-reclassification checks;
- 165 of 165 protocol-family tests passed in 117.30 seconds;
- Ruff passed all 17 selected implementation/test targets;
- Python compilation and Git whitespace checks passed; and
- bounded independent review reported zero remaining correctness defects.

## 10. Deployment and change impact

The original caller checkpoint changed no installed service and had no live exchange,
strategy, PPO/MASA, risk, sizing, leverage, margin, paper execution, or model
write effect.

The installed observation-only runtime now has protected local role
credentials, stable paths, a resident CLI, a hardened user-systemd unit,
resource controls, canonical self-hashed status, and an immutable release pin.
It deliberately has no active external-witness drop-in. The remaining next
layer must supply an independently hosted witness endpoint, bearer token,
witness ID, pinned Ed25519 public key and key digest; then a distinct external
completion acknowledgment and optimizer-admission verifier must be
implemented. Inventory receipt completion must never be relabeled as optimizer
training completion.

Observed commissioning evidence at `2026-07-22T16:28:03Z`:

- service active/running at PID `4047055`, `NRestarts=0`;
- immutable code SHA `b0116f706f12f115acc03197eef6765e1a2f36ea`;
- phase `HEAD_STAGED`, transition sequence 3;
- manifest `669f74c344752fda7a4a7e86824ab3291d7947a28fc344930554cfa3eb99bfe8`;
- total/admitted/label-unavailable counts `18/18/0`;
- status self-hash and complete manifest HMAC/entry stream independently
  reverified;
- witness configured/attempts `false/0`;
- peak memory `1,432,330,240` bytes, below `MemoryHigh=2G` and
  `MemoryMax=4G`; and
- all optimizer/checkpoint/model/prediction/paper/live/order/execution/runtime
  authorities false.

The source reader uses the existing ledger lock as `O_RDONLY + LOCK_SH`; it
does not create or write a lock. A loader invocation retains at most one
compact root projection and scalar count/head identities for evicted roots.
Same-root parents reuse the projection; revisiting an evicted root rereads the
complete ledger and fails closed if count/head moved. No full entry JSON,
record graph, raw ledger bytes, or shared lock survives projection.

Recoverable source/storage/protocol failures write canonical `FAIL_CLOSED`
status and retry inside the resident process with operational backoff. Invalid
arguments, credentials, or completed witness URL configuration exit 78 and do
not consume systemd restart budget. This behavior changes availability only;
it does not relax sample, finality, PIT, witness, admission, or trading gates.

Changing the status trigger, state phase map, staging root, role credentials,
page size, page-clock rule, witness recovery order, or result fields affects
this caller and requires the corresponding status/state/manifest/head/witness
protocol regression before deployment.

One nonblocking hardening item remains: a SIGKILL during the monolithic
manifest build can leave a uniquely named private temporary SQLite file.
Normal exceptions and graceful completion remove it, and none was present at
commissioning. A separately tested lock-held stale-temp cleanup/cancellation
slice is still required before claiming crash-artifact cleanup complete.
