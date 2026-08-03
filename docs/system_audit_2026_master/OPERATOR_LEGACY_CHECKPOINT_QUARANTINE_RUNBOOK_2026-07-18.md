# Native Trainer Legacy Checkpoint Quarantine and Fresh Bootstrap Runbook

Date: 2026-07-18 UTC

Scope: `.local_models/v2_native_rl_masa_ppo` only

Tool: `tools/quarantine_legacy_native_trainer_checkpoints.sh`

## Purpose and non-goals

The current native-trainer checkpoint root contains legacy manifests and NPZ
artifacts that predate the hardened causal lineage and semantic weight-evidence
contracts. The current checkpoint loader correctly refuses to call those
artifacts verified serving generations. Retention sees the legacy generations,
so leaving them in the active root can keep readiness blocked even though the
loader fails closed.

This runbook provides a reversible way to move the **entire** legacy root out
of the active path and create an empty mode-`0775` root from which the hardened
trainer can later bootstrap. It is not a migration. The tool never edits,
upgrades, copies into the new root, or synthesizes an individual checkpoint.
It does not prove that a subsequent trainer cycle is correct or profitable.

The tool does not stop or start services, change Redis, activate a trainer,
promote a model, or touch exchange/live-order paths. Those remain separate
operator decisions and validation steps.

## Immutable transaction contract

The tool enforces these conditions:

1. Dry-run is the default. It writes no repository or checkpoint artifact.
2. Apply requires both `--apply` and the exact acknowledgement
   `--ack-legacy-checkpoint-quarantine`.
3. Both `ai-bot-v2-native-cuda-trainer-persistent.service` and
   `ai-bot-v2-trainer-checkpoint-evidence.service` must be loaded and exactly
   `inactive` during repeated observations. `failed`, `activating`, `active`,
   `deactivating`, `not-found`, and query failure all block apply.
4. Recursive `lsof` observations under the checkpoint root must return no open
   file or directory handle. An incomplete or failed scan blocks apply.
5. Every regular file is inventoried twice before mutation with relative path,
   SHA-256, byte size, and nanosecond-rendered mtime. Any path/content/size/mtime
   change blocks apply. Symlinks and special filesystem entries are rejected.
6. The source and quarantine parent must have the same filesystem device ID.
   `mv --no-copy -T` makes the operation fail instead of falling back to a
   copy/delete move.
7. The complete directory is renamed to
   `.local_models/quarantine/v2_native_rl_masa_ppo_legacy_<UTC>`. The captured
   inventory is checked again against the renamed tree.
8. Only after that verification does the tool create a fresh, empty
   `.local_models/v2_native_rl_masa_ppo` with exact mode `0775`.
9. A single global transaction reservation prevents concurrent invocations,
   including invocations that cross a UTC-second boundary. A sibling inventory
   and active receipt record the quarantine location and inventory digest. A
   receipt, abandoned reservation, or prior quarantine directory makes later
   runs fail closed instead of guessing or quarantining the fresh root twice.
10. An internal failure attempts to restore the original root only when the
    new root is still empty. If anything writes to the fresh root, both trees
    are preserved and the tool tells the operator to escalate rather than
    deleting ambiguous state.

## Read-only preflight

The following command is safe while the evidence publisher is still active;
it will report `APPLY READINESS: BLOCKED` and make no changes:

```bash
tools/quarantine_legacy_native_trainer_checkpoints.sh
```

Review the complete inventory, both service observations, both open-handle
observations, planned source/destination, and planned root mode. Preserve the
terminal output with the maintenance record.

The current audit observed the persistent trainer inactive under its repair
hold while the checkpoint-evidence publisher remained active. That state is
intentionally **not apply-ready**. This document does not authorize changing
either service.

## Separately authorized apply window

Only after the operator has independently placed both exact units into
inactive/dead state and confirmed they cannot be restarted by a supervisor:

```bash
tools/quarantine_legacy_native_trainer_checkpoints.sh \
  --apply \
  --ack-legacy-checkpoint-quarantine
```

Do not add a force flag; none exists. Do not manually move individual manifest
or NPZ files into the new root. Keep the printed inventory, receipt, and exact
quarantine directory together as the rollback evidence set.

## Post-apply validation before any trainer release

An apply success establishes only filesystem separation and an empty bootstrap
root. Before releasing the persistent trainer, independently verify:

- both service units remained inactive throughout the transaction;
- the quarantined tree hashes match the sibling inventory;
- the active root is empty and mode `0775`;
- no legacy checkpoint was copied into the active root;
- the first future trainer cycle produces a new hardened manifest and NPZ with
  causal generation/parent ordering, exact weight SHA-256, model parameter
  fingerprint, semantic metadata, evidence digest, and current feature ABI;
- that generation reloads through the same hardened verifier before any model
  output is treated as `VERIFIED_SERVING`;
- PIT/finality, optimizer-delta, behavior-receipt, current-cycle, prediction,
  orchestrator, risk, allocator, and paper lifecycle evidence all remain
  fail-closed until their own current attributable proofs exist.

An empty root is not an A+ result and is not evidence of learning, edge, or a
return target.

## Rollback boundary

The successful tool output prints shell-quoted rollback commands using the
exact timestamped path. Rollback is safe only while both services remain
inactive and the fresh root contains no new checkpoint data.

If the fresh root is empty, remove that empty directory and atomically rename
the quarantined directory back with `mv --no-copy -T`. Recompute and compare
every restored file against the preserved inventory before removing the active
receipt. If the fresh root is nonempty, do not delete or merge either tree;
preserve both and perform a separate lineage review.

No rollback step starts a service. Service release remains a separate,
explicitly authorized operation.
