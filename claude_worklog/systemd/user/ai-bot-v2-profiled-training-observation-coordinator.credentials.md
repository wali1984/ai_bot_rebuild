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
supplies all six bindings:

- HTTPS base URL;
- witness ID;
- expected lowercase SHA-256 of the witness public key;
- timeout between 0.1 and 60 seconds;
- protected bearer token (16–4096 printable ASCII bytes); and
- protected **raw 32-byte** Ed25519 public key.

The two secret files are `witness-bearer.cred` and
`witness-ed25519-public-key.raw`. The four public values are unit environment
bindings, not secrets. Any partial mixture of public values or protected files
is a configuration error; it never silently becomes witness-absent mode. The
loader hashes the raw key and requires the exact separately supplied pin
before it constructs a client.

The client uses system trust roots, HTTPS only, no redirects, no environment
proxy, identity encoding, bounded canonical JSON, bearer authentication, and
Ed25519 verification of both event and append receipt. It carries no signing
private key. A same-host signer, token, or key generated on this host would
defeat the independent monotonic-history requirement and must not be used as
go-live evidence.

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
state pointer, optional witness journal, and
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
| active + signed-head/local-completion fields | witness append and local inventory receipts completed | still all false |
| `FAIL_CLOSED` status or nonzero unit exit | credential, PIT, lineage, storage, witness, or protocol failure | all false |

Local completion is only an authenticated inventory traversal. It is not a
`TrainingExample` tensor read, optimizer step, checkpoint write, model
publication, prediction, or runtime-wired proof. A separate independently
acknowledged completion/admission layer is required before those claims may
change.
