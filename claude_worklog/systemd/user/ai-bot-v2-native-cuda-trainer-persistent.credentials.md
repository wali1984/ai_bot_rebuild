# Authenticated profiled trainer resident credential contract

This service is a local research checkpoint publisher. The commissioned mode
may enter the optimizer after it has independently reopened the complete
authenticated base-publisher corpus and authorized that exact corpus with a
dedicated local HMAC role. Its output is isolated under a distinct
``local_profiled_research_candidates`` lineage and is **not promotable** to
serving, prediction, paper, or live execution. The separate external-witness
mode remains available for producing a promotion-eligible candidate, but that
mode can enter the optimizer only after the observation coordinator has
anchored an independently signed completion authorization for the exact
positive corpus.

Neither mode loads a witness bearer token, witness signing key, exchange key,
wallet key, Moralis key, CoinAPI key, prediction credential, paper-trading
credential, live-trading credential, or order transport.

## Mandatory local verification and research roles

The base unit mounts the same four local integrity sources used by the
observation coordinator plus one purpose-separated local research
authorization role:

| Runtime name | Protected source | Read purpose |
| --- | --- | --- |
| `profiled_observation_state_hmac_key` | `state-hmac.cred` | verify the complete state-event chain and authenticated pointer |
| `profiled_observation_manifest_hmac_key` | `manifest-hmac.cred` | verify the immutable observation manifest and admitted rows |
| `profiled_observation_head_hmac_key` | `head-hmac.cred` | verify the local successor-head binding |
| `profiled_observation_epoch_hmac_key` | `epoch-hmac.cred` | verify epoch, page receipt, and local-completion bindings |
| `profiled_local_research_authorization_hmac_key` | `local-research-hmac.cred` | authenticate the exact local-only research corpus and resident status; never grants downstream authority |

The loader accepts them only from systemd's credential directory for
`ai-bot-v2-native-cuda-trainer-persistent.service`. It requires an exact
owner-only `0500` directory, one-link owner-only `0400` regular files, at least
32 bytes per HMAC role. All five values must be pairwise distinct when the
local research role is present. The protected source directory remains
`0700`; its files remain `0600`. The trainer does not read the coordinator's
source directory directly.

The fifth role is optional to the credential loader so the independently
witnessed mode remains backward compatible. It is mandatory for the
commissioned ``locally-authenticated-profiled-research-publisher`` mode; a
missing or reused value exits with configuration status `78` before the model
or corpus is loaded.

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

When the external-witness mode is selected without this optional verifier
bundle, the process remains active and reports
`WAITING_EXTERNAL_WITNESS_CONFIGURATION`. That is a correct fail-closed state,
not a signed publication and not optimizer completion. The commissioned local
research mode does not consume this verifier bundle and cannot manufacture or
substitute independent-witness authority.

## Filesystem and authority boundary

The commissioned local research mode reads the immutable deployed code
release, desktop serving activation manifest, authenticated base-publisher
status, finalized-label archive, point-in-time feature ledger, and trusted
immutable cost CAS. The ledger plus WAL/SHM, label archive plus WAL/SHM, cost
CAS, publisher status, and repository are mounted read-only. The external mode
also reads the coordinator state/staging/authorization evidence read-only.

It writes only:

- `/home/wali/Desktop/AI BOT REBUILD/.local_models/v2_native_rl_masa_ppo`, for
  the isolated local research candidate and its causal ledger; and
- `/home/wali/ai_bot_local_data/v2_native_trainer/local_profiled_research_v1`,
  for local caches and the atomic owner-only status file.

The status is authenticated with the dedicated local research HMAC but remains
explicitly `local_status_integrity_only` evidence; it is not independent
provenance. Every returned reusable authority flag remains false, including prediction, serving
activation, serving promotion, paper/live trading, exchange, deployment,
execution, and order submission. Resource byte budgets, page and scan limits,
validation split, and cadence are operational memory/I/O or research-sampling
bounds only; none is a market, regime, signal, risk, leverage, margin, or
strategy threshold.
