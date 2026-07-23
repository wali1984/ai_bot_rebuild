# Profiled Supervised Checkpoint Inventory V1

Status: implemented as an isolated, unwired, in-memory evidence contract.

Runtime authority: none.

Production checkpoint files written: none.

Primary implementation:

- `v2/backend/app/services/native_trainer/profiled_supervised_checkpoint_inventory_v1.py`

Primary adversarial tests:

- `v2/backend/tests/unit/services/native_trainer/test_profiled_supervised_checkpoint_inventory_v1.py`

## 1. Purpose

This component closes one narrow gap between the authenticated profiled
optimizer-input lane and any future supervised checkpoint writer. It creates a
deterministic, content-addressed checkpoint *candidate* in memory after
reauthenticating all of the following:

1. a sealed `AuthenticatedProfiledOptimizerCorpusV1` designated as the
   before-side inventory;
2. a distinct, exact-owner-sealed `AuthenticatedProfiledOptimizerCorpusV1`
   designated as the after-side inventory;
3. the exact sealed
   `AuthenticatedProfiledSupervisedOptimizerExecutionAuthorizationV1` produced
   for that before/after corpus pair;
4. a sealed byte-level before-state inventory;
5. a sealed byte-level after-state inventory;
6. canonical optimizer configuration and environment documents;
7. the exact optimizer implementation artifact bytes; and
8. a strict retrospective clock sequence.

The output is not a PyTorch, TensorFlow, ONNX, safetensors, or serving
checkpoint. It is a V2 self-describing binary evidence envelope whose content
address can later be referenced by a separately designed writer or converter.
An independent strict decoder can replay the envelope's internal semantics
without the originating Python object. No writer or converter is present in
this slice.

## 2. Explicit non-goals and authority boundary

The component does not:

- invoke an optimizer;
- observe CUDA or CPU kernel execution;
- prove that an algorithm produced the supplied after-state;
- write a checkpoint to disk, Redis, object storage, or a model registry;
- publish a model;
- authorize prediction or serving;
- enable behavior-policy or PPO terms;
- route a candidate into paper trading;
- route a candidate into live trading;
- access an exchange;
- authorize deployment, order submission, or execution; or
- wire itself into any runtime service.

It also does **not** prove that the before and after corpus objects were
materialized in different processes, at different times, or on opposite sides
of a real optimizer invocation. Exact object ownership and equal content are
not temporal receipts. Both the upstream authorization and checkpoint result
therefore require `independent_temporal_materialization_verified=false`.

Every result requires these exact values:

| Field | Required value |
|---|---:|
| `checkpoint_write_authorized` | `false` |
| `model_write_authorized` | `false` |
| `prediction_authorized` | `false` |
| `serving_authorized` | `false` |
| `ppo_training_authorized` | `false` |
| `paper_trading_authorized` | `false` |
| `live_execution_authorized` | `false` |
| `exchange_access_authorized` | `false` |
| `deployment_authorized` | `false` |
| `order_submission_authorized` | `false` |
| `execution_authorized` | `false` |
| `runtime_wired` | `false` |

Changing any one of these fields makes result reauthentication fail.

## 3. Upstream trust dependency

The checkpoint inventory accepts exact types, not mappings, duck-typed objects,
or caller booleans:

```text
AuthenticatedProfiledOptimizerCorpusV1 (before)
AuthenticatedProfiledOptimizerCorpusV1 (after, distinct exact factory result)
AuthenticatedProfiledSupervisedOptimizerExecutionAuthorizationV1
```

The builder calls `__post_init__()` on all three objects. That rechecks every
nested corpus row, supervised target, causal clock range, corpus, and execution
authorization plus the process-private corpus-layer seals. Corpus-layer seals
hold a strong reference to the one exact public result that first bound them;
they do not store `id(owner)`. The execution authorization additionally retains
the exact before/after corpus owners. The builder then calls
`validate_authenticated_profiled_optimizer_corpus_inventory_equality_v1()`
again, compares the passed authorization with the freshly derived result, and
requires its retained owners to be the exact supplied pair.

Consequences:

- a dataclass copied from a valid corpus but mutated with
  `object.__setattr__` fails upstream reauthentication;
- a coherently recomputed public corpus hash does not replace the private seal;
- an authorization from another corpus pair is rejected;
- passing the same corpus object as both before and after is rejected upstream;
- shallowly shared or recursively `dataclasses.replace()`-cloned row/corpus
  graphs are rejected upstream;
- an equal authorization created for another exact corpus pair is rejected;
- an input cannot gain checkpoint authority by setting a boolean; and
- the checkpoint layer does not weaken or reinterpret the external Ed25519
  witness boundary.

These checks prove exact in-process factory provenance, pair ownership, nested
material validity, and before/after content equality. They do not prove
independent temporal materialization or optimizer/GPU execution.

The checkpoint also inherits the upstream requirement that manifest head
completion must be independently witnessed. A local HMAC, local completion
candidate, caller assertion, or local coherent CAS history is insufficient.

## 4. Manifest, completion, and witness bindings

The checkpoint header and sealed inventory bind these exact upstream fields:

### Manifest

- `manifest_id`;
- `manifest_metadata_sha256`;
- `manifest_observation_context_sha256`;
- `manifest_entry_chain_head_sha256`; and
- `manifest_ordered_entry_identities_sha256`.

### Full-consumption completion

- `completion_event_sha256`; and
- `completion_ordered_page_root_sha256`.

The admitted, unavailable-label, consumed-entry, and page counts remain bound
transitively by `corpus_contract_sha256` and the sealed upstream corpus.

### Independent external witness

- `external_authorization_envelope_sha256`;
- `witness_id`;
- `witness_namespace`;
- `witness_public_key_sha256`;
- `witness_sequence`;
- `witness_previous_event_sha256`; and
- `witness_accepted_at`.

The private signing key is neither accepted nor stored by this component.

## 5. Exact optimizer input inventory

For every admitted row, in manifest ordinal order, the binary header carries:

- ordinal;
- row inventory identity;
- sample identity;
- finalized-label binding identity;
- feature tensor binding identity;
- logical model-vector identity;
- logical projection identity;
- exact float64 model-input identity;
- supervised target identity; and
- exact float64 target-value identity.

The component also creates separate domain-separated ordered digests for:

- sample identities;
- label bindings;
- tensor bindings;
- logical model vectors;
- logical projections;
- model inputs;
- supervised targets;
- target values; and
- row inventories.

Finally, `before_optimizer_input_inventory_sha256` and
`after_optimizer_input_inventory_sha256` hash the full ordered row material,
including the corpus contract identity. Canonical bytes for the complete
before and after materials are compared with `hmac.compare_digest`. Equality of
only the outer digest is not treated as the comparison operation.

The admitted ordinals and admitted example count are copied from the sealed
corpus and included in the candidate header.

## 6. Feature ABI, projection, and mask bindings

The result binds:

- `feature_registry_sha256`;
- `feature_registry_abi_sha256`;
- the full `logical_profile_selection_mask` tuple;
- `logical_profile_selection_mask_sha256`;
- `projection_schema_version`;
- `projection_implementation_sha256`; and
- `projection_configuration_sha256`.

These values are not supplied independently by the checkpoint caller. They are
copied from the sealed before corpus after before/after equality succeeds. Any
profile, feature registry, projection implementation, or projection
configuration change therefore changes the corpus and checkpoint identities.

## 7. Tensor byte contract

State input is supplied to
`capture_profiled_supervised_optimization_state_snapshot_v1()` as exact tuples:

```text
(name, dtype, shape, little_endian_contiguous_payload_bytes)
```

The caller must also provide an exact positive `resource_budget_bytes`. The
factory prevalidates the tuple count and conservative aggregate metadata charge
against that budget before constructing even one tensor result. It then
prevalidates exact names, dtypes, shapes, payload types, and aggregate payload
bytes before hashing or building the snapshot.

### 7.1 Names

Names must match `[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}`. Model names and optimizer
names are independently required to be unique and already sorted in ascending
lexical order. The factory does not silently reorder caller input.

### 7.2 Supported canonical dtypes

| Dtype | Bytes per element |
|---|---:|
| `bool`, `int8`, `uint8` | 1 |
| `int16`, `uint16`, `bfloat16`, `float16` | 2 |
| `int32`, `uint32`, `float32` | 4 |
| `int64`, `uint64`, `float64` | 8 |

All bytes are declared `LITTLE_ENDIAN` with `CONTIGUOUS_C_ORDER` layout. The
contract does not perform host-native reinterpretation. It checks only exact
byte length and content identity against the declared dtype and shape.

### 7.3 Shape and byte count

- Shape must be an exact tuple of positive exact integers, except that the
  rank-zero scalar form `()` is valid.
- A scalar uses shape `()` and has one element.
- A zero-sized dimension is rejected because state items must contain a
  non-empty payload.
- Rank is capped at 4,096 and accounted shape metadata at 128 KiB before any
  dimension multiplication or iteration.
- Element count is accumulated iteratively. Before every multiplication, the
  factory checks `running_count <= maximum_elements // next_dimension`, where
  `maximum_elements` is derived from the narrowest immutable, per-item, and
  caller resource payload ceiling divided by dtype width. The running product
  therefore never becomes a giant integer.
- `byte_count` must equal `product(shape) * dtype_byte_width`.
- `byte_count` must equal the actual payload length.

### 7.4 Tensor identities

Each tensor has two domain-separated identities:

1. `coordinate_sha256` binds role, name, dtype, shape, byte order, and layout;
2. `tensor_state_identity_sha256` additionally binds payload byte count and
   `SHA256(payload)`.

Raw payload bytes are retained inside the sealed in-process result so the final
binary can be regenerated and compared byte-for-byte during reauthentication.

## 8. Before and after state snapshots

A state snapshot contains independent ordered model and optimizer inventories.
The exact stages are:

- `BEFORE_OPTIMIZATION`; and
- `AFTER_OPTIMIZATION`.

Each snapshot binds:

- canonical `captured_at`;
- model tensor count;
- optimizer tensor count;
- ordered model coordinate inventory;
- ordered model state-content inventory;
- ordered optimizer coordinate inventory; and
- ordered optimizer state-content inventory;
- the caller-supplied resource budget; and
- the exact conservative accounted resource bytes.

At least one model tensor is required. An empty optimizer state is allowed
because some optimizers initialize state lazily; its empty ordered inventory is
still domain-separated and hash-bound.

The checkpoint builder requires before and after model coordinate inventories
to be identical. It also requires the model state-content identities to differ.
Thus a dtype, name, shape, layout, or parameter-inventory drift fails closed,
and a byte-identical no-op update cannot produce this checkpoint candidate.

Optimizer state schemas may differ before and after because lazy optimizer
initialization is valid. Both exact inventories remain independently bound.

## 9. Implementation, configuration, and environment identities

Three exact artifacts are embedded as binary frames and hash-bound in the
header:

1. optimizer implementation artifact bytes;
2. optimizer configuration canonical JSON object bytes; and
3. execution environment canonical JSON object bytes.

The configuration and environment parsers:

- require exact `bytes`;
- require ASCII;
- reject duplicate object keys;
- reject `NaN`, positive infinity, and negative infinity;
- require a JSON object at the root; and
- require byte-for-byte canonical JSON using sorted keys and compact
  separators.

The implementation artifact may be arbitrary non-empty bytes. This permits a
source bundle, wheel, binary, or other exact implementation artifact without
pretending the module can infer which artifact a process executed.

The module also binds a code-owned
`PROFILED_SUPERVISED_CHECKPOINT_IMPLEMENTATION_CONTRACT_SHA256`. That identity
changes when the documented serialization or authority semantics change.

Callers must supply allowlisted, secret-free environment/configuration
documents. The checkpoint contract authenticates bytes; it does not redact
secrets from a caller-provided artifact.

## 10. Clock contract

Every timestamp must be canonical UTC with exactly six fractional digits and a
`Z` suffix. The complete required ordering is strict:

```text
manifest observation_time
  < external witness_accepted_at
  < before_input_inventory_verified_at
  < before_state.captured_at
  < optimizer_started_at
  < optimizer_completed_at
  < after_state.captured_at
  < after_input_inventory_verified_at
  < checkpoint_created_at
```

Duplicate timestamps fail because strict phase ordering would otherwise be
ambiguous. Offset timestamps, timestamps without microseconds, naive clocks,
and non-canonical equivalent strings fail.

These are retrospective evidence clocks supplied to an unwired factory. The
module validates representation and ordering but does not claim a trusted
hardware clock or an independent optimizer-execution observer.

Upstream per-row clocks remain transitively bound by the sealed corpus:

```text
model_feature_cutoff
  <= source_feature_available_at
  <= decision_feature_available_at
  <= feature_generated_at
  <= training_record_generated_at
  <= decision_time
  < trainer_sample_available_at
  < observation_time

decision_time < label_available_at < observation_time
```

No feature clock is renamed or treated as sample availability.

## 11. Binary V2 format and strict replay

The earlier in-memory V1 envelope from commit `a242c61299` was never written or
wired. Its descriptor contained only frame name, byte count, and payload hash,
so it is superseded rather than reinterpreted. The corrected envelope uses V2
schema and magic.

The deterministic in-memory candidate is encoded as:

```text
8 bytes   magic: ASCII "APSCIV2" followed by NUL
8 bytes   unsigned big-endian canonical-header byte length
N bytes   canonical ASCII JSON header
frames    ordered binary frames until end of candidate
```

Each frame is:

```text
4 bytes   unsigned big-endian frame-name byte length
N bytes   ASCII frame name
8 bytes   unsigned big-endian payload byte length
M bytes   exact payload
```

Frame order is:

1. every after-model tensor in canonical name order;
2. every after-optimizer tensor in canonical name order;
3. `ARTIFACT:OPTIMIZER_IMPLEMENTATION`;
4. `ARTIFACT:OPTIMIZER_CONFIGURATION`; and
5. `ARTIFACT:EXECUTION_ENVIRONMENT`.

The canonical header includes an index and ordered descriptor for every frame.
Every tensor descriptor contains all of:

- frame kind, index, and exact frame name;
- role and unprefixed tensor name;
- dtype and full ordered shape;
- byte order and layout;
- coordinate identity;
- tensor-state identity;
- byte count; and
- payload SHA-256.

Artifact descriptors carry their exact kind/name, byte count, and payload
SHA-256. The header also contains full before/after snapshot descriptors,
manifest, witness, optimizer-input, projection, artifact, clock, resource,
limitation, and authority material described above.

`decode_and_validate_profiled_supervised_checkpoint_binary_v2()` is an
independent bytes-only decoder. It requires canonical ASCII JSON with exact key
sets and no duplicate keys. It semantically replays ordered row digests,
projection-mask identity, snapshot identities, tensor coordinate/state
identities, ordered tensor inventory identities, artifact links, causal clock
order, resource accounting, and all authority-false claims. It then consumes
exactly one physical frame for every descriptor and rejects:

- duplicate or ambiguous frame names;
- descriptor or physical-frame reordering;
- duplicate, missing, or extra frames;
- truncated names, lengths, headers, or payloads;
- trailing bytes;
- payload tampering; and
- descriptor dtype/shape/coordinate/state/count/hash mismatches.

The decoder does not require or trust the originating in-process checkpoint
object. A successful replay verifies the envelope's internal byte/semantic
consistency only; it does not confer authority or prove who executed an
optimizer. Its returned report is itself exact-owner sealed, rejects
copy/deepcopy/pickle/`dataclasses.replace()` transfer, and fixes every
checkpoint/model/prediction/paper/live/execution/runtime authority to false.

Reauthentication regenerates the header and all candidate bytes from the
sealed nested state. Both must equal the public result exactly.

Content addresses are:

- `checkpoint_header_json_sha256 = SHA256(canonical_header_bytes)`;
- `checkpoint_bytes_sha256 = SHA256(all_checkpoint_candidate_bytes)`; and
- `checkpoint_inventory_sha256 = stable_sha256(...)` over the candidate
  content address, header address, corpus/authorization identity, before/after
  state identities, artifact identities, creation clock, status, and every
  downstream authority field.

The checkpoint's own content address is not embedded in its bytes, avoiding a
circular hash definition.

## 12. Public-result anti-forgery design

Every capability/evidence-bearing public dataclass result (tensor item, state
snapshot, checkpoint inventory, and binary replay report) has:

- an exact construction token;
- a process-private `_FactorySeal` exact type;
- a domain-specific seal domain;
- an HMAC-SHA256 digest under a random module-private process key; and
- a strong reference to the one exact object on which the seal first bound; and
- full public-material revalidation in `__post_init__()`.

The seal stores the owner object itself, never `id(owner)`. Therefore CPython
object-ID reuse cannot transfer a seal after collection; the seal keeps its
owner alive for the seal lifecycle. It binds on the first valid factory
construction. Reusing it on a different owner or changed material fails even
if a caller coherently recomputes every public SHA-256 field. Nested results are
reauthenticated before their identities are trusted. The upstream corpus row,
causal clock range, corpus, and execution-authorization results use the same
exact-owner rule, and the authorization retains its exact corpus pair.

The public result types explicitly reject:

- `copy.copy`;
- `copy.deepcopy`; and
- pickle serialization/deserialization capability transfer.

`dataclasses.replace()` remains useful as an adversarial test mechanism, but
even an unchanged replacement has a different object identity and fails the
one-time owner binding. A changed replacement also carries the old bound seal
and fails even if every public hash was coherently regenerated. This matters
because frozen dataclasses alone are not an authentication boundary: their
hidden constructor fields can otherwise be carried into a coherent
replacement.

Raw checkpoint bytes can be copied as ordinary bytes. They carry no authority;
only a reauthenticated in-process result is the inventory capability, and even
that capability grants no file-write or runtime authority.

### 12.1 Same-process hostile-code limitation

These seals protect against accidental copying, coherent public-field
replacement, stale capability transfer, and ordinary copy/pickle mechanisms.
They are **not** a security sandbox against arbitrary code executing in the
same Python process. Such code can use Python introspection, `object.__new__`,
`object.__setattr__`, module globals, debugger access, or native memory access.
The random HMAC key and private fields must not be described as protection from
a hostile same-process principal. Durable cross-process trust still requires
external signed receipts and strict bytes-only replay.

## 13. Resource budgets and immutable limits

The following are parser/serialization resource bounds, not market or training
quality thresholds:

| Limit | Value |
|---|---:|
| Immutable whole-envelope/state ceiling | 512 MiB |
| Syntactic state-item count ceiling | 1,000,000 |
| Per-item accounting charge before construction | 1,024 bytes plus exact variable material |
| Tensor rank | 4,096 |
| Accounted tensor-shape metadata | 128 KiB |
| Per-corpus-row checkpoint accounting charge | 2,048 bytes |
| Fixed checkpoint accounting charge | 16 KiB |
| Legacy per-tensor syntactic ceiling | 2 GiB, subordinate to the 512 MiB effective ceiling |
| Implementation artifact | 256 MiB |
| Configuration artifact | 16 MiB |
| Environment artifact | 16 MiB |
| Canonical checkpoint header | 64 MiB |

Both public factories require explicit positive caller budgets no greater than
the immutable 512 MiB ceiling. A million-item tuple is rejected by aggregate
accounting before any tensor result is constructed. A 2 GiB tensor is rejected
before hashing or frame construction because it exceeds the effective
whole-envelope ceiling. The checkpoint factory conservatively charges fixed
metadata, every admitted corpus row, after-state tensor metadata/payload, and
all artifact bytes before constructing the canonical header or any binary
frame. After header generation it computes the exact encoded size before
allocating the output buffer. It never builds a list of full frame-byte copies
and joins it.

The bytes-only decoder applies the same iterative checked element-count helper
before copying a descriptor shape into a tuple or deriving its byte count. A
high-rank descriptor and a `(2, 2, ...)` product attack are therefore rejected
at a deterministic resource reason before an oversized product exists.

These limits do not select symbols, observations, labels, regimes, leverage,
margin, edge, loss, confidence, or optimizer hyperparameters.

## 14. Test coverage

The focused suite covers:

- deterministic binary generation;
- manifest/completion/witness binding;
- ordered sample/label/tensor/projection/input/target binding;
- projection and selection-mask binding;
- exact model and optimizer state identities;
- implementation/configuration/environment content addresses;
- all downstream authorities remaining false;
- malformed tensor byte lengths;
- unordered state names;
- coherent tensor dataclass replacement with recomputed public hashes;
- coherent state snapshot replacement with recomputed public hashes;
- coherent top-level implementation substitution with a regenerated header,
  regenerated checkpoint bytes, and regenerated public inventory hash;
- unchanged `dataclasses.replace()` capability duplication;
- the recursive upstream `dataclasses.replace()` corpus-clone exploit;
- exact authorization-to-corpus-pair ownership;
- actual owner references instead of reusable integer IDs;
- `copy.copy`, `copy.deepcopy`, and pickle rejection for nested and top-level
  capabilities;
- independent bytes-only semantic replay of a valid V2 envelope;
- complete tensor descriptor presence;
- reordered, duplicated, truncated, trailing, and payload-tampered frames;
- ambiguous, malformed, and mismatched tensor descriptors;
- exact snapshot and checkpoint resource-budget preflight before builders;
- direct and decoded-header high-rank/giant-product shape attacks rejected
  before unbounded integer multiplication;
- bytes names, `shape=None`, wrong tuple arity, and malformed member counts
  normalized to `ProfiledSupervisedCheckpointInventoryV1Error`;
- equal, out-of-order, and non-canonical clocks;
- model coordinate drift;
- byte-identical no-op model state;
- duplicate-key, non-canonical, and non-finite JSON;
- checkpoint byte mutation;
- attempted enabling of every downstream authority field;
- upstream corpus mutation followed by reauthentication; and
- absence of any path argument or filesystem write.

## 15. Change-impact matrix

| Change | Direct effect | Required follow-up |
|---|---|---|
| Feature registry or ABI | Corpus and checkpoint identities change | Rebuild manifest, witness completion, admissions, corpus, and checkpoint candidate |
| Logical profile mask | Projection/corpus/checkpoint identity changes | Same full rebuild; old checkpoint is incompatible |
| Projection code/config | Projection/corpus/checkpoint identity changes | Same full rebuild and serving-compatibility review |
| Sample inclusion/order | Ordered inventories and checkpoint bytes change | New externally witnessed manifest and full corpus |
| Label/target value | Target and row inventories change | New finalized label evidence, manifest, witness, corpus, checkpoint |
| Tensor binding/model input | Row and optimizer input inventories change | New authenticated sample path and checkpoint |
| Witness key/sequence/event | Authorization and checkpoint lineage change | Obtain a new independent witness authorization |
| Model parameter names/dtypes/shapes | Coordinate inventory changes | New architecture contract and a separately reviewed serving adapter |
| Optimizer state schema | Before/after optimizer identities change | Update implementation/config/environment evidence; model coordinates may remain compatible |
| Binary format | Implementation contract identity changes | Version schema/magic/parser; never reinterpret V1 bytes |
| Authority requirement | Security boundary changes | Separate review; do not flip a V1 boolean |
| Clock semantics | Causal audit meaning changes | Version the contract and update upstream/downstream clock documentation |

## 16. Remaining work before any checkpoint may serve

This slice intentionally leaves these blockers in place:

1. an independently witnessed, current profiled manifest must exist at runtime;
2. the optimizer must be invoked through a separately reviewed adapter that
   captures before/after state at the declared phases and emits independently
   verifiable temporal receipts;
3. optimizer/GPU execution needs an independent execution receipt if the
   system is to claim more than retrospective supplied-byte lineage;
4. a durable checkpoint writer needs atomic write, fsync, directory fsync,
   readback, content-address verification, immutable-path, rollback, and
   anti-symlink contracts;
5. a framework converter must prove candidate state bytes equal the framework
   checkpoint tensors;
6. model architecture and serving implementation identities must be bound;
7. a fresh-process loader must reauthenticate durable evidence without relying
   on process-private capability seals;
8. serving equivalence tests must compare resident inference against the exact
   checkpoint state;
9. prediction, paper, and live admission require separate explicit gates; and
10. operator-approved immutable deployment and rollback procedures are still
    required.

Until all applicable blockers are closed, this component's correct runtime
state is unwired and non-authoritative.

Explicit current values remain:

- `independent_temporal_materialization_verified=false`;
- `optimizer_execution_independently_observed=false`;
- every checkpoint/model/prediction/paper/live/execution authority `false`;
  and
- `runtime_wired=false`.

## 17. 2026-07-21 independent-review remediation

The NO-GO findings against the original in-memory slice were remediated in
this branch as follows:

1. Corpus-layer and checkpoint-layer seals now retain exact owners, forbid
   ordinary graph transfer, and pair-bind execution authorization.
2. The non-self-describing V1 binary was superseded by V2 with complete tensor
   descriptors and a strict bytes-only semantic replay decoder.
3. No seal stores a CPython integer object ID.
4. State/checkpoint constructors prevalidate exact input/member types and
   normalize malformed inputs to their component error type.
5. Explicit caller resource budgets, conservative aggregate accounting, and a
   512 MiB immutable ceiling run before tensor/frame construction.
6. The implementation and this document now explicitly deny independent
   temporal/GPU/optimizer-execution proof and same-process hostile-code
   resistance.

Verification at this point in the branch:

- 85 admission, corpus, checkpoint, and new adversarial tests passed;
- both modified implementation modules passed `py_compile`;
- all modified Python files passed full Ruff and fatal-rule Ruff; and
- `git diff --check` passed.

No checkpoint was written, no service was started or restarted, no runtime was
wired, and no paper/live/exchange path was touched by this remediation.
