# Profiled Training Observation Coordinator State V1

Status: authenticated crash-cursor library complete, independently rereviewed,
tested, committed, and pushed. The manifest/full-consumption runtime caller,
CLI, systemd unit, external completion authorization, and optimizer admission
remain separate unfinished slices.

Implementation checkpoint:
`43427d0d30ea027033904ec76b4ff3984570e87b`.

Primary implementation:

- `v2/backend/app/services/native_trainer/profiled_training_observation_coordinator_state_v1.py`

Primary tests:

- `v2/backend/tests/unit/services/native_trainer/test_profiled_training_observation_coordinator_state_v1.py`

Related components:

- [PROFILED_TRAINING_EXTERNAL_WITNESS_CLIENT_V1.md](PROFILED_TRAINING_EXTERNAL_WITNESS_CLIENT_V1.md)
- [PROFILED_TRAINING_EXTERNAL_WITNESS_JOURNAL_V1.md](PROFILED_TRAINING_EXTERNAL_WITNESS_JOURNAL_V1.md)
- [PROFILED_TRAINING_EXTERNAL_WITNESS_RUNTIME_V1.md](PROFILED_TRAINING_EXTERNAL_WITNESS_RUNTIME_V1.md)

## 1. Role and strict non-authority boundary

The immutable manifest and head/epoch/page/completion artifacts already have
their own authentication and content-addressed persistence. This component
stores only the exact addresses and scalar bindings required to resume their
ordered construction after a crash.

It prevents a restart from guessing any of the following:

- which publisher cycle supplied the observation cutoff;
- which manifest file was built;
- which local head was staged or witnessed;
- which consumption epoch was opened;
- which exact page receipt was last committed;
- which receipt branch and ordered-page root are current; or
- which local completion belongs to the terminal page.

It does not train, admit samples, write a checkpoint/model, publish a
prediction, authorize paper/live trading, or touch an exchange. Every state
snapshot authenticates all 11 downstream authority fields as exact `false`.
`signed_head_durably_anchored=true` is a witnessed-storage fact only; it does
not set `external_monotonic_manifest_head_verified` or any downstream
authority.

## 2. Storage topology

The component has three local storage surfaces:

```text
stable single-writer lock file
  -> authenticated mutable pointer file
       -> immutable HMAC-authenticated state snapshot in SHA-256 CAS
            -> exact immutable manifest/staging-CAS addresses
```

The configured pointer path is never used as the writer-lease target because
the pointer is replaced atomically. A separate sibling `*.lease-target` path
is deliberately kept absent while its stable `*.writer.lock` file provides the
exclusive `FeatureSnapshotWriterLease` capability.

Each transition persists in this order:

1. validate the supplied current cursor is still the latest pointer;
2. construct and validate the complete next state snapshot;
3. HMAC-seal and durably put the exact snapshot bytes in immutable CAS;
4. construct and HMAC-seal the pointer to that CAS address;
5. write the pointer to an exclusive temporary file with mode `0600`;
6. fsync the temporary file;
7. atomically replace the configured pointer;
8. fsync the parent directory; and
9. reopen and compare the exact pointer and CAS state bytes.

A crash before pointer replacement leaves the old cursor authoritative and an
unreferenced, zero-authority CAS object. The transition is deterministic and
may be retried. A crash after replacement resumes the new cursor; a stale
caller cannot overwrite it.

## 3. Local rollback limitation

The pointer and every referenced snapshot are authenticated, but a host
administrator can restore an older coherent pointer plus its still-valid CAS
history. Every state therefore carries this exact limitation:

```text
AUTHENTICATED_LOCAL_POINTER_CAN_BE_ROLLED_BACK_BY_HOST_ADMIN;
INDEPENDENT_WITNESS_JOURNAL_IS_REQUIRED_FOR_EXTERNAL_MONOTONICITY
```

This component must not be described as an external monotonic head. The
independent witness journal/client/runtime remain the source of truth for
remote compare-and-append ordering.

## 4. Credential roles and commitments

Construction requires four distinct HMAC roles:

| Role | Protects |
|---|---|
| coordinator state | state snapshots and the mutable pointer |
| manifest | fixed-observation manifest metadata and entries |
| head | local manifest-head candidate and reproduction receipt |
| epoch | consumption epoch, page receipts, and local completion |

Both the four key IDs and the four raw key byte strings must be pairwise
distinct. Different IDs pointing to the same bytes fail before any state is
written.

The state stores a SHA-256 commitment for each `(role, key_id, raw_key)` under
the dedicated coordinator key-commitment domain. The state-store object keeps
only the state HMAC bytes after construction; it retains commitments, not the
other three raw role keys.

Every load requires the exact four configured IDs and commitments. After a
completed cycle, a successor cannot rotate an ID or key and then strand the
prior head/completion. Key rotation requires a future explicit migration
protocol; changing credentials in place fails closed.

## 5. Publisher-cycle identity

The prepared cursor pins both:

- authenticated `publisher_status_sha256`; and
- canonical `cycle_completed_at`, stored as `observation_time`.

The cycle ID is the SHA-256 of canonical identity material containing:

```text
schema_version
namespace
consumer_lane
publisher_status_sha256
observation_time
factory_wall_clock_observed_at
```

The state verifier recomputes this identity on every load. The observation
clock must not exceed the prepared factory clock.

An inflight cycle must finish before a newer publisher status can begin. A
same-cutoff/different-status request is equivocation and fails. A completed
cycle can advance only to a strictly later observation with a different status
hash.

## 6. Seven-phase state machine

| Phase | Newly committed evidence | Allowed predecessor |
|---|---|---|
| `PREPARED` | publisher/status cutoff, prepared factory clock, credentials, prior completed addresses | genesis or prior cycle `LOCAL_COMPLETION_STAGED` |
| `MANIFEST_STAGED` | exact manifest path/id and total/admitted/unavailable counts | `PREPARED` |
| `HEAD_STAGED` | exact local head event SHA/bytes/revision | `MANIFEST_STAGED` |
| `HEAD_ANCHORED` | witness operation/identity/key/sequence/event and durable-anchor fact | `HEAD_STAGED` |
| `EPOCH_STAGED` | exact epoch event SHA/bytes/id | `HEAD_ANCHORED` |
| `PAGE_STAGED` | exact latest page address/cursor/transition/ordered root | `EPOCH_STAGED` or `PAGE_STAGED` |
| `LOCAL_COMPLETION_STAGED` | exact local completion SHA/bytes/id | terminal `PAGE_STAGED`, or `EPOCH_STAGED` only for zero inventory |

No page consumption is allowed before the head is durably witness-anchored.
The final phase proves local exact consumption only; external completion
acknowledgement and optimizer admission remain false.

## 7. State and pointer schemas

The state schema contains 63 exact fields. They are grouped as follows:

| Group | Fields |
|---|---|
| schema/auth | schema version, state key ID/commitment, state ID, state auth tag |
| chain | global transition sequence, prior state event SHA-256 |
| cycle | namespace, consumer lane, cycle ID, publisher status SHA-256, phase, observation/factory clocks |
| role bindings | manifest/head/epoch key IDs and commitments |
| manifest | path, ID, total/admitted/unavailable counts |
| head | event SHA-256, byte count, revision |
| witness | operation ID, witness ID/key hash, anchored sequence/event hash, anchor fact |
| epoch | event SHA-256, byte count, epoch ID |
| page | receipt SHA-256/bytes, sequence/end ordinal/has-more, transition SHA-256, ordered-page root |
| completion | event SHA-256, byte count, completion ID |
| predecessor cycle | prior completed head and completion SHA-256/byte-count pairs |
| limitation/authority | local rollback text and 11 exact-false authority fields |

The pointer schema contains 10 exact fields:

```text
schema_version
state_auth_key_id
namespace
consumer_lane
state_event_sha256
state_event_byte_count
transition_sequence
cycle_id
pointer_id
pointer_auth_tag
```

Both parsers require bounded canonical ASCII JSON, reject duplicate keys and
nonfinite numbers, and require the exact field set. The pointer is framed by
one terminal newline; carriage returns and extra bytes are rejected.

## 8. Manifest persistence contract

`persist_manifest()` accepts only the exact
`ProfiledTrainingObservationManifestBuildV1` type in `PREPARED` phase. It
requires:

- build observation equals the pinned publisher cutoff;
- build factory clock equals the durably prepared factory clock;
- `checkpoint_write_authorized=false`;
- `runtime_wired=false`; and
- total samples equals admitted plus label-unavailable counts.

The optional prepared factory-clock input added to the manifest builder makes
this crash-replay deterministic. A crash after manifest publication but before
cursor publication reuses the exact clock and therefore the exact content
address instead of producing a same-cutoff/different-manifest orphan.

## 9. Head and witness persistence contracts

`persist_head()` binds the local head to:

- exact namespace and consumer lane;
- exact current manifest ID and observation time;
- exact three role key IDs;
- genesis predecessor hashes for the first cycle; or
- exact prior completed head and completion addresses for a successor.

`persist_head_anchor()` accepts only the sealed runtime result. It requires the
same namespace/event, anchored sequence equal to the head revision,
`signed_head_durably_anchored=true`, zero pending journal records, and all 11
downstream authority fields false.

## 10. Epoch, page, and completion contracts

`persist_epoch()` binds the epoch to the exact head event/revision,
manifest/cutoff, lane, three role key IDs, and manifest counts.

`persist_page()` requires a contiguous ordinal cursor and also binds every page
to the exact persisted receipt branch:

- previous page-receipt event SHA-256;
- previous page-transition SHA-256; and
- previous ordered-page-root SHA-256.

The first page must use the protocol genesis transition/root. Later pages must
use the exact current cursor values. Sequence, start ordinal, end ordinal, and
cumulative scanned count must agree. Advancing after a terminal page is
forbidden.

`persist_completion()` binds the completion to the exact terminal page:

- completion page count equals the persisted page sequence;
- final receipt hash equals the persisted receipt address;
- final transition equals the persisted transition; and
- ordered-page root equals the persisted root.

For zero inventory, page count is zero and the protocol completion/transition/
root genesis hashes are required. This prevents a valid completion from one
receipt branch being paired with a different terminal branch in the cursor.

## 11. Full-chain verification

`verify_integrity()` starts from the authenticated pointer and walks every
prior CAS state back to genesis. It checks:

- content address and bounded canonical JSON;
- state HMAC, identity, exact fields, clock and count algebra;
- descending transition sequence with no gap;
- exact predecessor event address;
- all same-cycle allowed phase edges;
- that only the fields assigned to the new phase changed;
- zero-inventory versus paged completion predecessor;
- completed-to-prepared cross-cycle ordering;
- strictly increasing observation cutoff;
- changed publisher status;
- unchanged namespace/lane/key IDs/key commitments; and
- exact carry-forward of prior completed head/completion addresses.

Only after all of those checks does the report set
`complete_chain_verified=true`. All downstream authority fields in the report
remain false.

## 12. Resource bounds

| Bound | Value | Purpose |
|---|---:|---|
| minimum HMAC key bytes | 32 | credential-strength floor |
| maximum state bytes | 128 KiB | serialization/memory safety |
| maximum pointer bytes | 16 KiB | pointer parser safety |
| maximum transitions | 1,000,000 | finite local chain traversal/storage guard |

These are integrity and resource limits. They do not select symbols, samples,
market regimes, leverage, margin, risk, rewards, or optimizer behavior.

## 13. Failure and restart matrix

| Failure | Durable truth | Recovery behavior |
|---|---|---|
| crash before state CAS | old pointer/state | rerun same phase |
| state CAS succeeds, pointer not replaced | old pointer plus harmless orphan CAS | deterministically recreate/select same next snapshot |
| pointer replace succeeds, caller crashes | new pointer/state | reopen new phase; reject stale cursor |
| malformed/tampered pointer | no trusted current cursor | fail before trusting CAS |
| missing/tampered state CAS | authenticated pointer cannot resolve | fail closed; never guess another object |
| wrong state key | pointer HMAC fails | provision original credential |
| changed manifest/head/epoch ID or key | state commitment mismatch | explicit future migration required |
| newer status while inflight | old inflight cursor | finish pinned cycle first |
| page branch mismatch | current page remains | reject alternate receipt/transition/root |
| completion branch mismatch | terminal page remains | reject alternate completion |
| local pointer rollback | older coherent state may authenticate | external witness recovery must detect remote mismatch |

## 14. Function-level change impact

| Change | Direct effect | Required regression |
|---|---|---|
| pointer write ordering | crash recovery and stale-cursor behavior | pre-pointer/post-pointer crash tests |
| state/pointer canonicalization | HMAC and CAS identity | duplicate/noncanonical/tamper tests |
| role IDs or commitments | ability to reopen prior artifacts | reused bytes/IDs and rotated-ID/key tests |
| cycle identity fields | publisher cutoff/status pinning | same-cutoff conflict, rollback, newer-inflight tests |
| phase transition map | resumable construction order | full seven-phase and semantic-chain tests |
| page cursor fields | gaps, overlap, receipt-branch splicing | exact three-predecessor-binding tests |
| completion bindings | full-consumption branch identity | alternate valid terminal-page completion test |
| prior completed pointers | successor head reproduction | completed-to-prepared carry-forward test |
| authority field set | accidental downstream enablement | exact-false construction/load tests |
| transition limit | maximum retained cursor history | boundary/resource review before changing |

## 15. Verification evidence

At implementation checkpoint `43427d0d30`:

- 1,888 implementation lines and 712 test lines were in the scoped checkpoint;
- 63 state fields, 10 pointer fields, 7 phases, and 11 authority fields were checked;
- 19 focused tests passed;
- Ruff formatting/lint, Python compilation, and Git whitespace checks passed;
- a first independent review found four successor-integrity defects;
- fixes added raw-key commitments, immutable credential binding, exact page and
  completion branch binding, premature-field rejection, and semantic adjacent
  chain verification; and
- the independent rereview reported zero remaining defects in scope.

The tests cover authenticated durability, idempotent same-cycle resume,
status equivocation, raw-key and ID reuse, inflight supersession, the complete
seven-phase chain, successor carry-forward, credential rotation, exact page
predecessor bindings, exact completion/terminal-page binding, crashes on both
sides of pointer commit, stale cursors, wrong state key, pointer tampering, and
zero-inventory completion.

## 16. Deployment truth and remaining blockers

This checkpoint is a library, not a running service. It has not changed the
installed base feature publisher, trainer observer, checkpoint publisher,
paper loop, risk controller, allocator, leverage, margin, or live exchange
behavior.

Remaining coordinator work is:

1. runtime caller that restores exact cursor artifacts and invokes each phase;
2. strict authenticated reader for publisher status/cycle hash;
3. startup recovery of all pending witness journal appends before new status;
4. bounded page work per invocation without losing cursor continuity;
5. distinct external completion-authorization client and verifier;
6. protected credential/path configuration loader;
7. standalone CLI and user-systemd unit isolated from the base publisher;
8. immutable release deployment and observed restart/cycle evidence; and
9. optimizer/corpus/checkpoint integration only after external completion
   authority verifies.

An independent witness URL/token/identity/Ed25519 public key/fingerprint is
still an external provisioning dependency. A same-host signer must not be used
as a substitute.
