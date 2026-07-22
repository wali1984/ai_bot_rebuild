# Profiled Training External Witness Runtime V1

Status: implementation library complete, independently rereviewed, tested,
committed, and pushed. No CLI, systemd unit, external witness, or optimizer
authority is installed at this checkpoint.

Implementation checkpoint:
`5c74039a279af7d498b5fb9291230b60b7bbb65f`.

Primary implementation:

- `v2/backend/app/services/native_trainer/profiled_training_external_witness_runtime_v1.py`

Primary tests:

- `v2/backend/tests/unit/services/native_trainer/test_profiled_training_external_witness_runtime_v1.py`

Related components:

- [PROFILED_TRAINING_EXTERNAL_WITNESS_CLIENT_V1.md](PROFILED_TRAINING_EXTERNAL_WITNESS_CLIENT_V1.md)
- [PROFILED_TRAINING_EXTERNAL_WITNESS_JOURNAL_V1.md](PROFILED_TRAINING_EXTERNAL_WITNESS_JOURNAL_V1.md)

## 1. Role and non-authority boundary

This module is the single-writer caller that orders local candidate staging,
journal durability, network dispatch, receipt verification, and signed-head
anchoring. It closes the gap between having a safe client/journal and using
them in the only crash-safe order.

It stops after a signed remote head is durably anchored. It does not:

- build a profiled observation manifest;
- consume manifest pages;
- stage a local full-consumption completion;
- obtain or verify the distinct completion-authorization envelope;
- admit optimizer samples;
- train or write a model/checkpoint;
- publish a prediction;
- authorize paper/live execution; or
- submit, cancel, or modify an exchange order.

Its result object keeps all 11 downstream authority fields false, including
`external_monotonic_manifest_head_verified`. The separate
`signed_head_durably_anchored=true` field describes a storage fact, not sample
or optimizer authority.

## 2. Public surface

The module exports:

| Symbol | Purpose |
|---|---|
| `restore_pinned_profiled_training_external_witness_client_v1()` | initialize/verify the journal, load latest signed head envelopes, and construct a pinned client that reauthenticates them |
| `ProfiledTrainingExternalWitnessRuntimeV1` | owns ordered recovery and candidate anchoring |
| `recover_pending_appends()` | retry every persisted pending append exactly once in journal order |
| `anchor_head_candidate()` | recover pending operations first, then persist/dispatch/anchor one exact local head candidate |
| `ProfiledTrainingExternalWitnessRuntimeResultV1` | sealed data-only result with append accounting and all downstream authority false |

The runtime constructor requires exact concrete journal and pinned-client types.
An optional supplied `FeatureSnapshotWriterLease` must already match the exact
journal path and current process.

## 3. Startup restoration

`restore_pinned_profiled_training_external_witness_client_v1()` performs this
sequence under one journal writer lease:

1. initialize or verify the exact journal schema;
2. fully verify journal integrity;
3. load the latest CAS-verified signed head envelope for each namespace; and
4. construct the pinned client while the lease is still held.

The client constructor verifies every restored Ed25519 envelope against the
separately supplied raw public key and SHA-256 fingerprint. CAS presence or a
SQLite reference alone never makes an envelope trusted.

Constructing the client before reading the journal can lose the trusted remote
head across restart. Constructing it from unverified local fields can turn a
coherent local rollback into apparent remote truth. Both orderings are
forbidden by this helper.

## 4. Pending recovery algorithm

Before any new candidate work, `_recover_pending_held()`:

1. verifies the complete journal;
2. refuses recovery if pending count exceeds the operational network-count
   ceiling;
3. loads every pending record through the journal, which rederives and compares
   exact request bytes/idempotency identity;
4. dispatches each already-persisted prepared request exactly once;
5. passes the signed receipt to the journal for receipt/head reverification and
   append-only anchoring; and
6. requires each returned record to be `HEAD_ANCHORED`.

There is no internal network retry loop. A timeout or ambiguous result
propagates immediately. The exact request remains pending and the next caller
invocation retries the same bytes and idempotency key.

`recover_pending_appends()` performs a final full journal verification and
requires zero pending operations before reporting success.

## 5. New-candidate algorithm

`anchor_head_candidate()` holds one writer lease across the complete caller
operation:

```text
initialize/verify journal
-> recover every pending operation
-> re-open exact candidate bytes from local staging CAS
-> deterministically prepare compare-and-append request
-> persist operation + APPEND_PREPARED
-> dispatch exact prepared request
-> verify signed receipt/event/latest head
-> persist signed receipt/head + HEAD_ANCHORED
-> full journal verification
-> sealed zero-authority result
```

The local staging CAS read uses the candidate event SHA-256 and byte count. The
prepared request uses:

- candidate namespace;
- expected sequence `candidate.revision - 1`;
- candidate predecessor head hash; and
- exact staged event bytes.

The journal then independently reopens and compares the same candidate/event/
request material before returning `APPEND_PREPARED`. Network dispatch occurs
only after that return.

If the exact candidate is already anchored, replay returns it without network
I/O. If it was pending and recovered at the beginning of the same invocation,
the method does not dispatch it a second time.

## 6. Same-process remote-success/local-failure state

A subtle crash window exists after the client accepts and verifies the remote
append but before SQLite commits `HEAD_ANCHORED`. In that window:

- the journal correctly remains `APPEND_PREPARED`; and
- the live client correctly holds the new pending event as its trusted head.

The journal now accepts exactly two client states while loading a pending
operation:

1. the exact previously persisted signed head; or
2. the exact signed pending event at `expected_sequence + 1`, with matching
   namespace, predecessor, event SHA-256, byte count, exact CAS bytes, and
   pinned Ed25519 signature.

At genesis, an unavailable client head remains valid before first dispatch. An
available genesis head is accepted only when it is the exact pending event.
Every other available genesis head fails as rollback. For successors, a head
that is neither the exact prior envelope nor the exact pending event fails as a
fork/third state.

This exception is reachable only while loading an existing authenticated
pending row. New-operation admission never receives `pending_operation` and
therefore cannot use it to bypass normal genesis/prior-head checks.

## 7. Result contract

`ProfiledTrainingExternalWitnessRuntimeResultV1` is a sealed frozen dataclass.
It records:

```text
operation_id
witness_id
witness_public_key_sha256
namespace
expected_sequence
anchored_sequence
event_sha256
recovered_operation_ids
network_append_attempt_count
candidate_dispatched_after_recovery
candidate_was_recovered
journal_operation_count
journal_transition_count
journal_anchored_count
journal_pending_count
signed_head_durably_anchored
11 downstream authority booleans
```

Constructor validation enforces successor sequence, hashes, unique recovered
operation IDs, exact attempt accounting, consistent recovery flags, journal
count algebra, zero pending rows, and `signed_head_durably_anchored=true`.
All downstream authority booleans must be exact `False`. Replacing or forging
one as true fails construction.

`network_append_attempt_count` equals the number of recovered operation IDs
plus one only when the current candidate required a post-recovery dispatch.
Readback GET requests are not included in this append-attempt count.

## 8. Operational resource ceiling

At most 4,096 pending append attempts are allowed in one recovery invocation.
A successful candidate call may make one additional append attempt after those
recoveries. This is a network-count bound only. It is not an elapsed-time
deadline and it does not select markets, samples, risk, leverage, margin,
rewards, or model behavior.

The intended production topology uses one profiled witness namespace, for
which the journal permits at most one pending operation. The larger bound
protects a future multi-namespace deployment. Exceeding it fails before any
recovery POST and requires an explicit bounded-recovery operational design; it
must never be “fixed” by deleting journal rows.

## 9. Failure matrix

| Failure | Persistent state | Next invocation |
|---|---|---|
| candidate CAS invalid | no new journal operation | fail until exact local evidence is restored |
| journal prepare fails | no allowed POST | verify/repair the local durability fault |
| POST fails before remote accept | pending exact request | retry exact request once |
| remote accepts, response is lost | pending exact request | idempotent server receipt replay |
| remote accepts, local anchor call fails | pending exact request; live client may hold pending head | accept only exact pending head, replay exact request, anchor |
| anchor DB commit succeeds, postcommit reopen fails | durable anchored transition | next full verification sees anchored state; no duplicate POST |
| exact candidate replay | existing anchored operation | zero append attempts |
| wrong witness key after restart | pending load rejected before network | provision the originally pinned key/identity |
| wrong writer lease | constructor rejected | acquire lease for exact journal path |

## 10. Current service insertion map

Read-only inspection found zero production callers for manifest/head/epoch/page/
completion orchestration. The healthy installed base publisher is:

```text
ai-bot-v2-profiled-base-feature-publisher.service
```

Its effective release at the inspection point was
`e34af1e6a6bb9b54818e18f9279fcc9904de0922`; that release does not contain the
witness client, journal, or runtime modules.

The base CLI’s safe per-cycle observation boundary is immediately after
`status = publisher.run_cycle()`: that return occurs after ledger postcommit,
publisher-state persistence, and status persistence. `status["cycle_completed_at"]`
is the deterministic observation cutoff candidate.

The safer production topology is a separate bounded coordinator service that
cursors the publisher status/ledger. Witness/network failure must not terminate
the base evidence publisher. Systemd `After=` alone is insufficient because it
orders process startup, not individual publication cycles.

## 11. Function-level change impact

| Change | Direct effect | Required regression |
|---|---|---|
| restore helper ordering | trusted client head after restart | signed-head restore, wrong key, concurrent/single-writer review |
| recovery ordering | whether old requests can be skipped or reordered | older unrelated pending before new, ambiguity, multiple namespace tests |
| one-attempt policy | duplicate remote mutation/retry behavior | before/after-accept timeout and exact idempotency tests |
| pending-head exception | rollback/fork boundary | genesis pending, successor pending, prior head, third state, changed-key tests |
| candidate CAS/preparation | local head-to-wire identity | changed bytes/count/hash/namespace/revision tests |
| result accounting | monitoring truth and potential downstream misuse | negative construction, attempt-count, recovered/replay tests |
| writer-lease span | concurrent caller behavior | wrong/released/competing lease and postcommit tests |
| pending resource bound | maximum work per invocation | boundary and pre-network refusal tests |

## 12. Verification evidence

At checkpoint `5c74039a27`:

- 354 runtime implementation lines and 370 runtime-test lines were reviewed;
- 10 runtime tests passed;
- 28 journal plus runtime tests passed in the final bounded rereview;
- 90 client, journal, runtime, and profiled manifest/head tests passed together;
- Ruff formatting/lint, Python compilation, and Git whitespace checks passed;
- two bounded independent runtime reviews were completed; and
- the final rereview reported zero defects.

Coverage includes durable-before-POST, ambiguous success/restart, recovered
candidate no-double-dispatch, anchored replay with zero network, changed key
before network, signed-head restoration, recovery resource refusal before
network, unrelated pending before new candidate, wrong lease, same-process
remote success/local anchor failure, exact genesis/successor pending-head
acceptance, and negative authority mutation.

## 13. Remaining production blockers

The runtime library is not the full coordinator. Remaining local work is:

1. dedicated manifest/head/epoch/page/completion coordinator and cursor state;
2. explicit absolute paths for label archive, cost CAS, manifest root, staging
   CAS, witness journal, and status;
3. distinct manifest/head/epoch role credentials and IDs;
4. external witness URL/token/identity/public key/fingerprint credential loader;
5. purpose-specific external completion-authorization client;
6. authenticated optimizer/corpus and checkpoint-writer integration; and
7. immutable release/unit deployment and observed cycle evidence.

Remaining external work is operator provisioning of an actually independent
witness service and credentials. A same-process, same-host local signer is not
an acceptable substitute.
