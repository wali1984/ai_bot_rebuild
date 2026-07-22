# Profiled Training External Witness Client V1

Status: implemented, tested, committed, and pushed as an isolated client
library. It is not wired to a runtime service.

Runtime authority: none.

External witness service provisioned: no.

Primary implementation:

- `v2/backend/app/services/native_trainer/profiled_training_external_witness_client_v1.py`

Primary adversarial tests:

- `v2/backend/tests/unit/services/native_trainer/test_profiled_training_external_witness_client_v1.py`

Implementation checkpoint: `c602491e9b8d7a1949b0f85396721e2c59bdaed2`.

## 1. Purpose and trust boundary

The local profiled manifest/head/page/completion stores can prove local
content integrity, but they cannot detect a coherent rollback of all local
state. This client implements the consumer side of a separate monotonic
compare-and-append witness. It verifies that one pinned Ed25519 witness signed
the exact event and receipt envelopes returned over an owned HTTPS client.

A successful call proves only the signed witness history and exact append
bindings. It does not by itself authorize:

- optimizer admission or execution;
- checkpoint or model writes;
- prediction or serving;
- paper trading;
- live execution;
- exchange access; or
- order submission.

The append request sets every one of those authority fields to `false` and
sets `runtime_wired=false`. The module contains no Ed25519 private key, signing
function, optimizer, model, exchange client, or order path.

## 2. Transport contract

`ProfiledTrainingExternalWitnessHttpsTransportV1` owns its `httpx.Client` and
enforces:

- HTTPS only;
- no URL user info, query, fragment, path traversal, encoded path ambiguity,
  invalid port, non-ASCII host, or ambiguous backslash;
- `verify=true`;
- `trust_env=false`;
- redirects disabled at both client and request level;
- bearer authentication;
- `Accept-Encoding: identity`;
- rejection of non-identity content encoding;
- `application/json` for every non-empty response;
- raw streamed body accounting before concatenation; and
- a 6 MiB maximum wire response.

The only injectable HTTP transport is the exact `httpx.MockTransport` type,
under the private `_test_http_transport` argument. A normal or custom
`httpx.HTTPTransport` is rejected. Production construction therefore has no
generic network transport escape hatch.

The configured timeout must be between 0.1 and 60 seconds. These are transport
resource-safety bounds, not market, feature, label, risk, leverage, margin, or
optimizer thresholds.

The client calls exactly these endpoint shapes beneath the pinned base URL:

```text
GET  /namespaces/{percent-encoded-namespace}/latest
GET  /namespaces/{percent-encoded-namespace}/events/{sequence}
POST /namespaces/{percent-encoded-namespace}/events:compare-and-append
```

The concrete external server does not yet exist in this repository.

## 3. Canonical wire encoding

All authenticated material is exact canonical ASCII JSON:

- object keys sorted;
- separators `,` and `:` with no whitespace;
- no duplicate keys;
- no floats, NaN, Infinity, or non-ASCII text;
- signed 64-bit integers only;
- bounded nesting, nodes, container items, and text; and
- exact byte-for-byte recanonicalization equality.

A byte-level structural preflight runs before `json.loads`, so an adversarial
document cannot first allocate an unbounded object tree and only then fail the
node/depth checks.

Every signature is verified over:

```text
ASCII_DOMAIN || NUL || canonical_unsigned_JSON
```

The event domain is:

```text
v2/native-trainer/profiled-observation-external-witness-wire-event/v1
```

The receipt domain is:

```text
v2/native-trainer/profiled-observation-external-witness-wire-receipt/v1
```

The public key is exactly 32 raw Ed25519 bytes. Its SHA-256 fingerprint must
exactly match the separately configured lowercase 64-hex fingerprint. A
signature is exactly 64 bytes represented as 128 lowercase hex characters.

## 4. Signed event envelope

The event field set is exact:

```text
schema_version
signature_algorithm
signature_domain
witness_id
namespace
sequence
previous_event_sha256
event_sha256
event_byte_count
event_base64
signed_at
signature_hex
```

The client verifies schema, algorithm, domain, witness identity, namespace,
positive non-boolean sequence, predecessor hash, decoded byte count, canonical
Base64, event SHA-256, canonical six-digit UTC `signed_at`, and signature.

On first observation without a restored anchor, the client reads and verifies
the signed history from sequence 1 to the signed latest event. Sequence 1 must
point to `PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256`. A signed orphan,
broken predecessor, sequence gap, or unsigned `404` absence fails closed.

Bootstrap reads are capped at 8,192 events per operation. That cap protects
memory/network resources only. A long-lived runtime must restore a previously
verified signed head envelope instead of repeatedly walking an ever-growing
history.

For an already observed sequence, equality includes:

- sequence;
- previous-event hash;
- event hash;
- `signed_at`;
- signed-envelope hash; and
- exact signed-envelope bytes.

Any difference is a signed fork. A lower sequence is a rollback. Forward
movement reopens every missing signed event and validates the chain before an
optimistic lock-protected head commit. No network I/O occurs while the head
lock is held.

## 5. Compare-and-append request

The caller supplies:

- namespace;
- expected prior sequence, including zero for genesis;
- expected prior event SHA-256; and
- exact new event bytes.

For sequence zero, the expected hash must be the fixed genesis hash. The
client derives the new event hash and emits a canonical request containing the
expected head, exact event Base64/count/hash, witness identity, schema/domain,
and all authority fields fixed to false.

The idempotency key is:

```text
SHA256(compare_append_domain || NUL || canonical_base_request_without_key)
```

The final request hash is SHA-256 over the exact canonical request including
that idempotency key. The same inputs therefore reproduce the same request
bytes, request hash, and idempotency key after a timeout or restart.

The server contract must check idempotency before treating a now-advanced head
as a conflict. A caller must never invent a new expected head after an
ambiguous POST. It must durably retain and retry the original inputs exactly.

## 6. Signed append receipt

The receipt field set is exact:

```text
schema_version
signature_algorithm
signature_domain
witness_id
namespace
sequence
previous_event_sha256
event_sha256
accepted_at
request_sha256
idempotency_key
receipt_payload_sha256
receipt_payload_byte_count
receipt_payload_base64
signature_hex
```

The client binds the receipt to the exact namespace, successor sequence,
predecessor, new event, request hash, and idempotency key. It verifies the
canonical clock, payload count/Base64/hash, exact integer type, field set, and
Ed25519 signature.

`receipt_bytes` is the exact signed outer envelope—not only the inner opaque
payload. `verify_append_receipt_envelope()` can therefore reverify persisted
receipt evidence after restart when the expected request bindings are
restored.

After receipt verification, the client reads the exact appended event and
latest head again. Both must agree with the receipt and original event bytes.

## 7. Crash, restart, and persistence contract

The library supports but does not itself perform durable persistence:

- `trusted_head_envelope_bytes()` exports the exact verified signed head;
- `trusted_head_envelope_bytes_by_namespace` restores and re-verifies it;
- deterministic append inputs make an ambiguous request retryable; and
- the exact signed receipt can be persisted and reverified.

The runtime caller must atomically persist, before dispatch:

1. namespace;
2. expected sequence;
3. expected event hash;
4. exact event bytes;
5. the last trusted signed head envelope; and
6. a pending-operation identity/version.

After success it must atomically persist the exact signed receipt and new
signed head before clearing the pending operation. Local state remains a cache
and audit artifact; the remote compare-and-append result is the monotonic
authority.

This durable caller/journal is not implemented at the recorded checkpoint.

## 8. Completion authorization remains separate

The monotonic witness protocol stores opaque profiled head/page/completion
events. Optimizer admission additionally requires the distinct canonical
Ed25519 completion-authorization envelope verified by
`authenticated_profiled_optimizer_admission_v1.py`.

Implementing this client does not satisfy that envelope. A production witness
must expose a purpose-specific endpoint that independently reopens the final
manifest/page/completion bindings and signs only the exact completion
authorization schema. It must never expose a generic sign-arbitrary-bytes
endpoint, and the trainer must never receive the private signing key.

## 9. Function-level change impact

| Changed function/contract | Direct effect | Required regression surface |
|---|---|---|
| `_parse_exact_json` / structural preflight | Changes every signed event and receipt accepted from the witness | canonicality, duplicate, float, depth/node, fixed-vector tests |
| `_verify_signature` or signature domains | Changes witness identity/authentication ABI | independent fixed event and receipt vectors, wrong-key/domain tests |
| HTTPS base/path/header logic | Changes credential destination and response resource safety | URL ambiguity, redirect, encoding, content-type, oversize tests |
| `_verified_event` | Changes event semantic bindings | payload/hash/count/clock/field-set/signature tests |
| `_observe_head` / chain validation | Changes rollback, fork, genesis, and successor acceptance | orphan, rollback, fork, gap, restored-anchor, concurrency review |
| append request/idempotency derivation | Changes remote CAS replay identity | exact request, ambiguous retry, server replay tests |
| `_receipt` / receipt reverification | Changes append authority evidence | wrong binding, boolean sequence, fixed receipt vector, restart reverification |
| resource limits | Changes only parser/transport denial-of-service boundary | limit-edge and oversize tests; no strategy/risk retuning |

Any wire schema, domain, field name, canonicalization rule, or idempotency
derivation change is a versioned protocol change. Client and independent
server must be rolled together under a new schema/domain; silently accepting
both forms would create signature and replay ambiguity.

## 10. Verification evidence

At checkpoint `c602491e9b`:

- 46 focused witness-client test cases passed;
- 156 manifest/head/admission/corpus/checkpoint/witness tests passed;
- Python bytecode compilation passed;
- Ruff passed;
- Git whitespace checks passed;
- two bounded independent static reviews were completed; and
- the final review reported zero remaining high- or medium-severity defects in
  the two-file implementation family.

The tests include independent literal Ed25519 event and receipt vectors. Those
vectors do not call the test signing helper, so a shared wrong domain between
the production verifier and fake witness cannot make both vectors pass.

## 11. Remaining activation blockers

The trainer optimizer publisher remains fail-closed until all of these exist:

1. operator-selected independent witness trust domain;
2. externally provisioned endpoint, bearer/client authentication, signing key,
   and pinned public-key fingerprint;
3. server-side linearizable compare-and-append with exact idempotency replay;
4. durable local pending-operation/head/receipt journal;
5. purpose-specific completion-authorization endpoint and caller;
6. dedicated supervised optimizer adapter with PPO/behavior terms disabled;
7. actual optimizer execution receipts and atomic checkpoint writer/verifier;
8. immutable service deployment and fresh-process/burn-in evidence.

No local HMAC, SQLite file, local immutable CAS, or same-host signing stub can
be described as the independent external witness.
