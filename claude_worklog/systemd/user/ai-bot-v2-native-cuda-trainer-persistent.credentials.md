# Authenticated profiled trainer resident credential contract

This service is a non-serving checkpoint-candidate publisher. It can enter the
optimizer only after the observation coordinator has anchored an independently
signed completion authorization for the exact positive corpus. It never loads
a witness bearer token, witness signing key, exchange key, wallet key, Moralis
key, CoinAPI key, prediction credential, paper-trading credential, live-trading
credential, or order transport.

## Mandatory local verification roles

The base unit mounts the same four local integrity sources used by the
observation coordinator:

| Runtime name | Protected source | Read purpose |
| --- | --- | --- |
| `profiled_observation_state_hmac_key` | `state-hmac.cred` | verify the complete state-event chain and authenticated pointer |
| `profiled_observation_manifest_hmac_key` | `manifest-hmac.cred` | verify the immutable observation manifest and admitted rows |
| `profiled_observation_head_hmac_key` | `head-hmac.cred` | verify the local successor-head binding |
| `profiled_observation_epoch_hmac_key` | `epoch-hmac.cred` | verify epoch, page receipt, and local-completion bindings |

The loader accepts them only from systemd's credential directory for
`ai-bot-v2-native-cuda-trainer-persistent.service`. It requires an exact
owner-only `0500` directory, one-link owner-only `0400` regular files, at least
32 bytes per HMAC role, and four pairwise-distinct values. The protected source
directory remains `0700`; its files remain `0600`. The trainer does not read
the coordinator's source directory directly.

## Optional independent witness verifier

The tracked `80-external-witness-verifier.conf.example` is deliberately
inactive. A completed local drop-in may add exactly three verifier bindings:

- the already-established witness ID;
- the separately supplied lowercase SHA-256 pin; and
- the witness's raw 32-byte Ed25519 **public** key mounted as
  `profiled_observation_witness_ed25519_public_key`.

All three are required together. Any partial bundle exits with configuration
status `78`. The trainer intentionally receives neither of the coordinator's
two bearer tokens and performs no network request. It verifies the signed
authorization already anchored in the coordinator's immutable CAS and
read-only journal snapshot. The ID and key pin must exactly match the
coordinator's independently provisioned witness; generating a same-host
witness or key does not satisfy this boundary.

Without this optional verifier bundle, the process remains active and reports
`WAITING_EXTERNAL_WITNESS_CONFIGURATION`. That is the correct commissioned
state, not a signed publication and not optimizer completion.

## Filesystem and authority boundary

The service reads the immutable deployed code release, desktop serving
activation manifest, coordinator state/staging/authorization evidence,
point-in-time feature ledger, and trusted immutable cost CAS. The coordinator
root, ledger plus WAL/SHM, cost CAS, and repository are mounted read-only.

It writes only:

- `/home/wali/Desktop/AI BOT REBUILD/.local_models/v2_native_rl_masa_ppo`, for
  a verified non-serving candidate and its causal ledger; and
- `/home/wali/ai_bot_local_data/v2_native_trainer/authenticated_profiled_resident_v1`,
  for local caches and the atomic owner-only status file.

The status self-hash is explicitly marked `local_status_integrity_only`; it is
not independent provenance. Every returned reusable authority flag remains
false, including prediction, serving activation, paper/live trading, exchange,
deployment, execution, and order submission. Resource byte budgets, page size,
and cadence are operational memory/I/O bounds only; none is a market, regime,
signal, risk, leverage, margin, or strategy threshold.
