# Profiled training observation coordinator credential contract

This contract packages the crash-resuming observation coordinator without
granting optimizer, checkpoint, model, prediction, paper, live, order,
execution, leverage, or margin authority. The base unit can run with four
local integrity roles and no network witness; in that state it stages one
exact head and remains active with classification
`WAITING_EXTERNAL_WITNESS_CONFIGURATION`.

## Mandatory local roles

The base unit mounts exactly four local HMAC credentials from
`%h/.config/ai-bot-v2/credentials/profiled-training-observation-coordinator`:

| Runtime name | Protected source | Authenticated object |
| --- | --- | --- |
| `profiled_observation_state_hmac_key` | `state-hmac.cred` | coordinator state events and mutable authenticated pointer |
| `profiled_observation_manifest_hmac_key` | `manifest-hmac.cred` | immutable observation manifest |
| `profiled_observation_head_hmac_key` | `head-hmac.cred` | local successor-head candidate |
| `profiled_observation_epoch_hmac_key` | `epoch-hmac.cred` | epoch, page receipts, and local completion candidate |

Each value is a single-line UTF-8 secret of at least 32 bytes. All four values
and all four public key IDs must be pairwise distinct. The loader accepts them
only from
`/run/user/<uid>/credentials/ai-bot-v2-profiled-training-observation-coordinator.service`,
opens every path without following symlinks, and requires the systemd mount to
be owner-only `0500` and each credential to be a one-link regular owner-only
`0400` file. It never reads `.env`, `EnvironmentFile`, Binance, CoinAPI,
Moralis, exchange, wallet, or order credentials.

Provisioning creates random local authentication material, not an external
witness and not any downstream authority. The protected source directory must
be `0700` and each source file `0600`. Rotation is not an in-place overwrite:
change the corresponding public key ID and use a new versioned runtime root or
a separately reviewed authenticated rotation protocol. An old pointer with a
new role key fails closed by design.

## Optional independent witness bundle

The tracked `80-external-witness.conf.example` is intentionally not active.
Install a completed copy only after another independently operated system
supplies all seven bindings:

- HTTPS base URL;
- witness ID;
- expected lowercase SHA-256 of the witness public key;
- timeout between 0.1 and 60 seconds;
- protected head-append bearer token (16–4096 printable ASCII bytes), mounted
  as `profiled_observation_witness_bearer_token`;
- protected completion-authorization bearer token (16–4096 printable ASCII
  bytes), mounted as
  `profiled_observation_completion_authorization_bearer_token`; and
- protected **raw 32-byte** Ed25519 public key, mounted as
  `profiled_observation_witness_ed25519_public_key`.

The three secret files are `witness-bearer.cred`,
`completion-authorization-bearer.cred`, and
`witness-ed25519-public-key.raw`. The two bearer credentials are
purpose-scoped: the first can call only the monotonic head-append route and the
second can call only the compare-and-authorize completion route. Their values
must be distinct; role reuse fails closed. The four public values are unit
environment bindings, not secrets. Any partial mixture of public values or
protected files is a configuration error; it never silently becomes
witness-absent mode. The loader hashes the raw key and requires the exact
separately supplied pin before it constructs either client. Both clients must
use the same witness ID and public-key fingerprint.

Both clients use the CA bundle supplied by the pinned Python environment's
`certifi` package, HTTPS only, no redirects, no environment proxy, identity
encoding, bounded canonical JSON, purpose-scoped bearer authentication, and
Ed25519 verification. The head client verifies event and append receipts. The
completion client verifies the exact manifest/head/final-page/completion
binding and signed authorization envelope. Neither carries a signing private
key. A same-host signer, token, or key generated on this host would defeat the
independent monotonic-history requirement and must not be used as go-live
evidence.

## Filesystem and process boundary

The service reads only:

- the strict publisher cycle status and immutable cost CAS under
  `profiled_base_publisher_v1`;
- `durable_feature_snapshot_ledger.sqlite3` plus existing WAL/SHM sidecars; and
- `canonical_finalized_5m_label_archive.sqlite3` plus existing WAL/SHM
  sidecars.

It writes only under
`/home/wali/ai_bot_local_data/v2_native_trainer/profiled_training_observation_coordinator_v1`.
That root contains manifests, staging/state/witness CAS, the authenticated
state pointer, optional head-witness journal, completion-authorization CAS and
journal, and
`coordinator_status_v1.json`. The status is canonical, atomically replaced,
owner-only `0600`, self-hashed, and explicitly marked local-integrity-only.

The unit has no `OnSuccess`, `ExecStartPost`, downstream trainer dependency,
paper/live dependency, exchange secret, or order transport. `page_size=256`
and the 30-second resident cadence are memory/I/O controls only; neither
classifies a market, sample, label, regime, risk, leverage, margin, or model.

## Observable states

| State | Meaning | Downstream authority |
| --- | --- | --- |
| active + `WAITING_EXTERNAL_WITNESS_CONFIGURATION` | local manifest/head staged; independent bundle absent | all false |
| active + `WAITING_COMPLETION_AUTHORIZATION_CONFIGURATION` | signed head and positive admitted local completion exist, but the completion runtime is absent | all false |
| active + `COMPLETION_AUTHORIZATION_ANCHORED` | exact positive corpus admission was signed by the pinned witness and durably journaled | admission evidence true; optimizer execution and every downstream authority false |
| `FAIL_CLOSED` status or nonzero unit exit | credential, PIT, lineage, storage, witness, or protocol failure | all false |

Local completion by itself is only an authenticated inventory traversal. The
separate completion route can authorize admission of that exact positive
corpus after the pinned signed head is replay-verified and the request is
durably prepared. It still is not an optimizer step, a `TrainingExample`
tensor read, checkpoint write, model publication, prediction, or runtime-wired proof;
those authorities remain false until their separately reviewed workers earn
and publish their own evidence.
