# Profiled Training External Witness Journal V1

Status: implemented, independently rereviewed, tested, committed, and pushed as
an isolated durability library. Its ordered runtime caller library is also
implemented; neither is installed as a runtime service.

Runtime authority: none.

External witness provisioned: no.

Implementation checkpoint:
`ab1b6d810cbdd7ea3125c182e1f8b0c1f1778069`.

Primary implementation:

- `v2/backend/app/services/native_trainer/profiled_training_external_witness_journal_v1.py`

Primary adversarial tests:

- `v2/backend/tests/unit/services/native_trainer/test_profiled_training_external_witness_journal_v1.py`

Related signed transport:

- [PROFILED_TRAINING_EXTERNAL_WITNESS_CLIENT_V1.md](PROFILED_TRAINING_EXTERNAL_WITNESS_CLIENT_V1.md)
- [PROFILED_TRAINING_EXTERNAL_WITNESS_RUNTIME_V1.md](PROFILED_TRAINING_EXTERNAL_WITNESS_RUNTIME_V1.md)

## 1. Purpose and exact boundary

The pinned witness client deliberately owns no durable state. This journal is
the caller-side durability boundary around that client. It makes the exact
compare-and-append request replayable across a process crash or an ambiguous
network result, then durably binds the exact signed receipt and signed remote
head returned by the witness.

The journal does not perform network I/O. It does not sign evidence, authorize
a sample, construct an optimizer corpus, train a model, write a checkpoint,
publish a prediction, trade paper, or reach a live exchange. Its operation
rows permanently store all 11 authority fields as SQLite integer zero:

```text
external_monotonic_manifest_head_verified
full_consumption_external_ack_verified
optimizer_admission_authorized
checkpoint_write_authorized
model_write_authorized
prediction_authorized
paper_trading_authorized
live_execution_authorized
order_submission_authorized
execution_authorized
runtime_wired
```

SQLite `CHECK` constraints, Python verification, canonical operation material,
and integrity-report construction all independently require those values to
remain false. A durable remote head is evidence, not optimizer authority.

## 2. State machine and call order

There are exactly two append-only states per operation:

```text
no operation
    -> APPEND_PREPARED
    -> HEAD_ANCHORED
```

There is no transition backward and no update-in-place. An operation has one
`APPEND_PREPARED` transition and zero or one `HEAD_ANCHORED` transition.

The required production call order is:

1. The local manifest/head builder produces a
   `LocalProfiledTrainingObservationHeadCandidateV1` whose exact canonical
   event bytes already exist in its immutable local staging CAS.
2. The pinned client derives a deterministic
   `ProfiledTrainingExternalWitnessPreparedAppendV1` without network I/O.
3. `persist_prepared_append()` reopens the local staging CAS, compares the
   staged bytes, candidate material, prepared event, request, witness identity,
   namespace, predecessor, revision, and false-authority vector.
4. Under the exact single-writer lease and `BEGIN IMMEDIATE`, the journal
   verifies its complete history and admission capacity.
5. Only after those checks, the exact event and request bytes enter the journal
   CAS; the operation row and `APPEND_PREPARED` transition commit.
6. Only after step 5 returns may the runtime caller invoke
   `client.dispatch_prepared_append(record.prepared)`.
7. The caller passes the signed receipt to `commit_head_anchored()`. That method
   reverifies the exact receipt, exact trusted signed head, predecessor, event,
   request hash, idempotency key, and event bytes.
8. The receipt and signed head enter the journal CAS, then an append-only
   `HEAD_ANCHORED` transition commits.
9. The journal closes, reopens, verifies the full history again, reconstructs
   the record, and returns it.

Dispatching before step 5 violates the durability contract. Treating step 8
as completion authorization violates the authority contract.

## 3. Physical storage

The journal uses two storage planes:

| Plane | Contents | Integrity role |
|---|---|---|
| `ImmutableSourcePayloadStore` | exact event, request, signed receipt, signed head, and prior-head envelope bytes | content-addressed SHA-256 and exact byte-count verification |
| SQLite journal | identities, lineage fields, CAS addresses/counts, state transitions, canonical material, and global transition chain | ordered append-only lifecycle and cross-object bindings |

The caller supplies an absolute SQLite path and an exact
`ImmutableSourcePayloadStore`. Subclasses and duck-typed substitutes are not
accepted. The SQLite path cannot contain `..`.

Connection requirements are:

- the exact `FeatureSnapshotWriterLease` must match the journal path and bound
  inode;
- `journal_mode=WAL`;
- `synchronous=FULL`;
- foreign keys enabled;
- `trusted_schema=OFF`;
- 60-second SQLite busy timeout; and
- connection close followed by lease revalidation.

New-database initialization commits schema and metadata first, then fsyncs the
parent directory. The application ID is hexadecimal `0x57544A31` (`WTJ1`) and
the SQLite user version is `1`.

## 4. Exact SQLite schema

The schema contains 3 strict tables, 2 indices, and 10 triggers. On every open,
the implementation compares the complete `(type, name, table, SQL)` schema
signature with a separately constructed in-memory schema. An extra, missing,
or textually changed table, index, or trigger fails closed.

### `witness_journal_metadata`

Exactly one row is allowed:

| Field | Contract |
|---|---|
| `singleton` | integer `1` primary key |
| `schema_version` | exact journal V1 schema string |
| `genesis_transition_sha256` | fixed global transition-chain genesis |
| `created_at` | canonical six-digit UTC clock |

Update and delete triggers make the row append-only after creation.

### `witness_journal_operations`

The immutable operation row stores these field families:

| Family | Fields |
|---|---|
| Operation/witness | `operation_id`, `witness_id`, `witness_public_key_sha256`, `namespace` |
| Manifest/head identity | `manifest_id`, `observation_time`, `head_revision`, `candidate_id`, `candidate_event_sha256`, `candidate_event_byte_count`, `previous_head_event_sha256`, `previous_completion_candidate_sha256` |
| Local provenance | `local_staging_store_root`, `manifest_auth_key_id`, `head_auth_key_id`, `epoch_auth_key_id`, `epoch_auth_key_commitment_sha256`, `allowed_consumer_lane` |
| Remote compare head | `expected_sequence`, `expected_event_sha256` |
| Immutable payload addresses | `event_cas_sha256`, `event_byte_count`, `request_cas_sha256`, `request_byte_count`, `request_sha256`, `idempotency_key` |
| Prior remote anchor | `prior_signed_head_envelope_sha256`, `prior_signed_head_envelope_byte_count` |
| Authority | the 11 false-only fields listed in section 1 |
| Self-authentication | `operation_material_json` |

`request_sha256` and `idempotency_key` are individually unique. Genesis
requires sequence zero, the fixed witness genesis event hash, and no prior
signed head. A successor requires a prior signed-head SHA-256 and positive byte
count. Candidate revision must equal expected sequence plus one; candidate
event identity must equal event-CAS identity; and candidate predecessor must
equal the expected remote head.

`operation_material_json` is exact canonical ASCII JSON. `operation_id` is:

```text
SHA256("v2/native-trainer/profiled-external-witness-journal-operation/v1"
       || NUL || operation_material_json)
```

Operation update and delete are forbidden. A trigger also refuses a second
operation in a namespace while an earlier operation is pending.

### `witness_journal_transitions`

Each transition stores:

```text
transition_sequence
previous_transition_sha256
transition_sha256
operation_id
state
receipt_sequence
receipt_previous_event_sha256
receipt_event_sha256
receipt_accepted_at
signed_receipt_envelope_sha256
signed_receipt_envelope_byte_count
signed_head_envelope_sha256
signed_head_envelope_byte_count
journaled_at
transition_material_json
```

Prepared transitions must have every receipt/head field null. Anchored
transitions must have a positive receipt sequence, every receipt/head identity,
and positive envelope byte counts. `(operation_id, state)` is unique.

The global transition sequence is gapless across all namespaces. Every row
points to the prior transition hash, beginning with the fixed V1 genesis hash.
`transition_sha256` is:

```text
SHA256("v2/native-trainer/profiled-external-witness-journal-transition/v1"
       || NUL || transition_material_json)
```

Triggers enforce append-only rows, gapless global chaining, prepared-before-
anchored lifecycle, and receipt sequence/predecessor/event binding to the
operation.

## 5. Integrity verification

`verify_integrity()` is a complete verification, not a row-count health check.
It performs the following checks under the writer lease:

1. exact schema, application ID, user version, and singleton metadata;
2. operation and transition counts before row/CAS traversal;
3. per-operation identifier, clock, integer, path, size, genesis/successor,
   false-authority, canonical-material, and domain-separated hash checks;
4. exact event/request retrieval from CAS and SHA-256/count verification;
5. exact request field set, canonical JSON, Base64 event equality,
   deterministic idempotency derivation, and operation/request bindings;
6. gapless global transition sequence and predecessor hash chain;
7. canonical transition material and domain-separated transition hash;
8. receipt-to-operation sequence, predecessor, and event bindings;
9. signed receipt/head CAS presence and byte counts;
10. exactly one prepared state followed by zero or one anchored state;
11. per-namespace sequence, predecessor event, prior signed head,
    observation-time progression, and non-reused manifest/candidate identity;
12. no successor after a pending predecessor; and
13. one reserved future transition slot for every pending operation.

Row traversal is streamed. The verifier retains compact identity/lifecycle
tuples rather than full SQLite rows. Counts are checked before expensive row or
CAS inspection, preventing a malformed oversized database from first forcing
unbounded evidence loading.

## 6. Resource ceiling and reservation rule

The journal accepts at most 100,000 transitions. This is a storage/verification
resource bound only; it is not a market, sample, confidence, risk, leverage,
margin, reward, or model threshold.

A pending operation has consumed its prepared transition but still requires an
anchor transition. Therefore integrity requires:

```text
transition_count + pending_count <= 100000
```

A new prepared operation consumes one transition immediately and reserves one
future anchor, so admission requires:

```text
transition_count + pending_count + 2 <= 100000
```

Exact replay of an already persisted operation consumes no new capacity and
remains available at the limit. Capacity, namespace, expected-head, and pinned
client/prior-head checks all run under the same writer lease and transaction
before event/request CAS persistence. A capacity-rejected request therefore
does not leave its event or request in journal CAS.

The V1 journal has no rollover operation. Approaching the ceiling requires a
separately designed, versioned migration that preserves the terminal global
transition hash and every latest namespace anchor. Deleting or truncating rows
is prohibited.

## 7. Crash and ambiguous-result behavior

| Failure point | Durable result | Recovery |
|---|---|---|
| Before prepared commit | no authoritative operation | rebuild and prepare again |
| CAS write succeeds but SQLite prepared commit does not | possible unreferenced immutable blob; no journal authority | do not dispatch; a future audited CAS-reference collector may identify the orphan |
| After prepared commit, before POST | pending exact request | `load_pending_appends()` and dispatch exact bytes |
| Remote append succeeds but response is lost | local state remains pending | retry exact request/idempotency key; server must replay original receipt |
| Receipt arrives but anchor commit does not | local state remains pending | exact request replay, receipt reverification, then anchor |
| Anchor SQLite commit succeeds but close/reopen fails | anchored row is durable | reopen, full verify, and load anchored record |
| Receipt/head CAS write succeeds but anchor row does not | possible unreferenced immutable envelope; no anchor authority | repeat authenticated anchor path; CAS put is content-addressed/idempotent |

Unreferenced CAS data cannot create an operation or state transition and grants
no authority. It must not be deleted casually: any future cleanup must first
prove a complete reference inventory across operation and transition rows.

## 8. Restart API

`load_pending_appends()` returns exact reauthenticated prepared records in
namespace/sequence order and performs no network I/O. Each record is rebuilt by
rederiving the prepared request with the pinned client and comparing exact
request bytes, request hash, idempotency key, witness identity, and public-key
fingerprint.

For a non-genesis pending operation, the client must already trust the exact
persisted prior signed head. The journal compares exact envelope bytes and asks
the pinned client to reverify its Ed25519 signature and event binding. Genesis
rejects a client that already holds a head for the namespace, preventing
rollback to sequence zero.

`persisted_signed_head_envelopes_by_namespace()` returns the latest CAS-verified
signed envelope bytes for each namespace. Those bytes are not trusted merely
because SQLite references them; the pinned client constructor must authenticate
them before they become restored in-memory heads.

## 9. Time semantics

The journal keeps these clocks distinct:

| Clock | Owner/meaning |
|---|---|
| `observation_time` | local profiled head candidate’s market/data observation boundary |
| `receipt_accepted_at` | timestamp signed by the independent witness for the append |
| `journaled_at` | local wall clock when a journal transition was materialized |
| metadata `created_at` | local journal creation clock |

All are canonical UTC with six fractional digits and `Z`. `journaled_at` is not
renamed to or substituted for `event_time`, `ingested_at`, `available_at`,
`generated_at`, `feature_cutoff`, `decision_time`, or `execution_time`. This
module creates none of those downstream temporal authorities.

## 10. Public method change impact

| Method/contract | Direct effect of a change | Required regression surface |
|---|---|---|
| constructor / `writer_lease()` | changes path, type, inode, or single-writer trust | wrong path/lease, concurrent writer, replace-inode tests |
| `initialize()` / schema signature | changes persistent ABI | fresh creation, exact schema, extra/missing object, update/delete tests |
| `_validated_candidate_and_prepared()` | changes which local head/request pairing can be persisted | staging CAS, exact bytes/material, witness/key, namespace, revision, authority tests |
| operation material/domain | changes `operation_id` and replay identity | deterministic hash and existing-operation replay tests; version migration |
| transition material/domain | changes global audit chain | genesis, interleaved namespace, sequence/hash and tamper tests; version migration |
| `persist_prepared_append()` | changes the pre-network durability boundary | no-network-before-commit, idempotency, capacity, CAS-orphan, crash/reopen tests |
| `load_pending_appends()` | changes restart request recovery | exact request replay, changed key, prior-head restore, ambiguous POST tests |
| signed-head export | changes pinned-client bootstrap state | latest-per-namespace, signature, fork/rollback tests |
| `commit_head_anchored()` | changes durable receipt/head acceptance | wrong receipt/head/key/event, idempotent anchor, postcommit failure tests |
| integrity verifier/resource cap | changes corruption detection or operational journal lifetime | full lifecycle, schema/CAS tamper, limit-before-CAS, reserved-anchor tests |

Changing a field set, schema string, hash domain, genesis hash, canonical JSON
rule, state name, or transition order is a versioned persistent-protocol change.
It cannot be deployed as a silent in-place edit.

## 11. Verification evidence

At checkpoint `ab1b6d810c`:

- 2,240 implementation lines and 770 focused-test lines were added/reviewed;
- 16 focused journal tests passed;
- 78 witness-client, journal, and profiled manifest/head tests passed together;
- Ruff formatting and lint passed;
- Python bytecode compilation passed;
- Git whitespace validation passed;
- two bounded independent resource/correctness rereviews completed; and
- the final rereview reported zero remaining defects in scope.

The 16 tests cover empty initialization, no-network durable prepare,
dispatch/anchor/restart, ambiguous remote success, prepared and anchored
postcommit reopen failures, exact replay idempotency, one pending per namespace,
sequential prior-head binding, interleaved namespaces, changed witness key,
forbidden update/delete and wrong lease, CAS tamper, count-before-CAS resource
rejection, per-pending anchor reservation with rejected blobs absent, and
signed-head tamper rejection.

## 12. Remaining activation blockers

This checkpoint resolves local prepared/request/receipt/head durability. It does
not make the trainer publisher operational. Remaining critical work is:

1. production CLI/unit around the implemented runtime caller, plus manifest and
   full-consumption orchestration;
2. operator-selected independent witness host, credentials, Ed25519 public key,
   and separately pinned SHA-256 fingerprint;
3. independently deployed linearizable compare-and-append server with exact
   idempotency replay;
4. purpose-specific completion-authorization endpoint and local verifier;
5. authenticated optimizer/corpus adapter and checkpoint writer integration;
6. immutable service deployment plus fresh-process and observed publish-cycle
   evidence.

Until those exist, `runtime_wired=false` and every optimizer/model/prediction/
trading authority remains false by construction.
