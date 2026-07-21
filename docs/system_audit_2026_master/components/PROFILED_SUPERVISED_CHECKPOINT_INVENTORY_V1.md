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
2. a distinct sealed `AuthenticatedProfiledOptimizerCorpusV1` designated as
   the after-side inventory;
3. the exact sealed
   `AuthenticatedProfiledSupervisedOptimizerExecutionAuthorizationV1` produced
   for that before/after corpus pair;
4. a sealed byte-level before-state inventory;
5. a sealed byte-level after-state inventory;
6. canonical optimizer configuration and environment documents;
7. the exact optimizer implementation artifact bytes; and
8. a strict retrospective clock sequence.

The output is not a PyTorch, TensorFlow, ONNX, safetensors, or serving
checkpoint. It is a self-describing binary evidence envelope whose content
address can later be referenced by a separately designed writer or converter.
No such writer or converter is present in this slice.

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
AuthenticatedProfiledOptimizerCorpusV1 (after, distinct object graph)
AuthenticatedProfiledSupervisedOptimizerExecutionAuthorizationV1
```

The builder calls `__post_init__()` on all three objects. That rechecks the
process-private seals introduced by the authenticated admission/corpus layers.
It then calls
`validate_authenticated_profiled_optimizer_corpus_inventory_equality_v1()`
again and compares the passed authorization with the freshly derived result.

Consequences:

- a dataclass copied from a valid corpus but mutated with
  `object.__setattr__` fails upstream reauthentication;
- a coherently recomputed public corpus hash does not replace the private seal;
- an authorization from another corpus pair is rejected;
- passing the same corpus object as both before and after is rejected upstream;
- shallowly shared row, target, or clock-range graphs are rejected upstream;
- an input cannot gain checkpoint authority by setting a boolean; and
- the checkpoint layer does not weaken or reinterpret the external Ed25519
  witness boundary.

The checkpoint therefore inherits the upstream requirement that manifest head
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

- Shape must be an exact tuple of non-negative exact integers.
- A scalar uses shape `()` and has one element.
- A zero-sized dimension is rejected because state items must contain a
  non-empty payload.
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
- ordered optimizer state-content inventory.

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

## 11. Binary format

The deterministic in-memory candidate is encoded as:

```text
8 bytes   magic: ASCII "APSCIV1" followed by NUL
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

The canonical header includes an ordered descriptor for every frame: frame
name, byte count, and payload SHA-256. It also contains all manifest, witness,
optimizer-input, projection, state, artifact, clock, limitation, and authority
material described above.

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

Every public dataclass result has:

- an exact construction token;
- a process-private `_FactorySeal` exact type;
- a domain-specific seal domain;
- an HMAC-SHA256 digest under a random module-private process key; and
- the identity of the one exact object on which the seal first bound; and
- full public-material revalidation in `__post_init__()`.

The seal binds on the first valid factory construction. Reusing it on changed
material fails even if a caller coherently recomputes every public SHA-256
field. Nested results are reauthenticated before their identities are trusted.

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

## 13. Resource limits

The following are parser/serialization resource bounds, not market or training
quality thresholds:

| Limit | Value |
|---|---:|
| State items | 1,000,000 |
| One tensor payload | 2 GiB |
| Implementation artifact | 256 MiB |
| Configuration artifact | 16 MiB |
| Environment artifact | 16 MiB |
| Canonical checkpoint header | 64 MiB |

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
- `copy.copy`, `copy.deepcopy`, and pickle rejection for nested and top-level
  capabilities;
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
   captures before/after state at the declared phases;
3. optimizer execution needs an independent execution receipt if the system is
   to claim more than retrospective supplied-byte lineage;
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
