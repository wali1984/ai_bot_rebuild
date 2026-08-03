# Legacy Trainer Redis Namespace Quarantine Runbook

Date: 2026-07-18 UTC

Tool: `tools/quarantine_legacy_trainer_redis_namespace.py`
Exact namespace: `v2:trainer:hybrid_cuda:`

## Purpose

This tool provides a reversible cleanup boundary before a fresh native-trainer
bootstrap. It prevents stale, immortal legacy trainer status, preview, and
paper-signal records from continuing to look current after the legacy
checkpoint root is quarantined.

The default operation is read-only. Apply archives the complete exact-prefix
inventory and deletes only a much narrower candidate set. It does not start or
stop a service, modify a checkpoint, enable live execution, submit an order,
change leverage, or prove profitability/readiness.

The utility is intentionally hard-bound to loopback Redis database 0 at
`redis://127.0.0.1:6379/0`. It does not inherit `REDIS_URL`; remote hosts,
credentials, TLS URLs, alternate ports, query parameters, and alternate
database indexes fail closed. The local systemd writer gates cannot govern a
remote Redis server, so broad target selection is not permitted here.

## What is archived and what can be deleted

The second scan archives every supported Redis key whose raw bytes begin with
the exact prefix `v2:trainer:hybrid_cuda:`. For each key the archive records:

- the key bytes as base64 and, when valid UTF-8, a display form;
- Redis type;
- the lossless Redis `DUMP` payload as base64;
- SHA-256 of the `DUMP` payload;
- both `TTL` and `PTTL` observations;
- the normalized loopback Redis target contract and database index;
- cleanup classification;
- scan/server timestamps and full-inventory and cleanup-candidate digests.

The lossless value is a Redis RDB serialization payload, not parsed JSON. This
is intentional: `RESTORE` can reconstitute lists, sets, sorted sets, hashes,
streams, strings, and embedded binary bytes without normalisation. The tool
refuses an unsupported/module Redis type rather than making a lossy archive.

A key is cleanup-eligible only when all of the following are true:

1. It is in the exact prefix.
2. It is one of the known legacy fixed records or a legacy
   `signals:paper:*` record.
3. It has `PTTL=-1` and `TTL=-1` in both scans.
4. Its type and exact `DUMP` bytes do not change between scans.

The following are always preserved:

- every positive-TTL/current-cycle key;
- every `v2:trainer:hybrid_cuda:on_policy_receipt:*` key, including an
  intentionally immortal behavior receipt;
- every unclassified immortal key;
- every key outside the exact prefix.

Positive-TTL keys are allowed to expire, refresh, or change between scans.
That noncandidate drift is recorded in the archive. A change to the legacy
immortal candidate set fails closed.

## Writer and service gate inventory

Apply and rollback require two observations in which all five canonical user
units are `LoadState=loaded` and `ActiveState=inactive`:

- `ai-bot-v2-native-cuda-trainer-persistent.service` — direct writer through
  the hybrid trainer runtime/publisher;
- `ai-bot-v2-trainer-checkpoint-evidence.service` — checkpoint-root observer;
  its Redis keys are outside this prefix, but it must be held across the
  coordinated trainer bootstrap;
- `ai-bot-v2-trainer-training-live-loop.service` — canonical trainer adjunct;
  its normal Redis keys are also outside this prefix.
- `ai-bot-v2-native-ppo-masa-continuous-training-guard.service` — guard that
  can request trainer unit activation;
- `ai-bot-v2-native-ppo-masa-continuous-training-guard.timer` — scheduler for
  that guard, which must remain inactive across the bracket.

The tool also inspects `/proc` for known manual writer entrypoints. It refuses
apply/rollback if it sees the persistent trainer, the older native trainer
loop, or the one-shot trusted publisher running outside the service gate.

The paper-management loop does **not** need to be stopped. It can consume
current behavior receipts, and those receipts are explicitly excluded from
cleanup. The paper loop is not the direct publisher of the legacy fixed
namespace records.

## 1. Read-only inventory

From the repository root:

```bash
.venv/bin/python tools/quarantine_legacy_trainer_redis_namespace.py \
  --repo-root "/home/wali/Desktop/AI BOT REBUILD" \
  --redis-url redis://127.0.0.1:6379/0
```

The output is a bounded JSON summary only. It does not print raw values, Redis
credentials, or key payloads. Verify:

- `mode` is `dry_run`;
- `dry_run_only` is `true`;
- `namespace` is exactly `v2:trainer:hybrid_cuda:`;
- the candidate count and classification counts are plausible;
- `paper_loop_stop_required` is `false`;
- `live_or_exchange_path_touched` is `false`.

Dry-run does not create the proposed archive path and does not delete a Redis
key. An active required service makes `service_gate_ready=false`; this is an
expected readiness result and does not make the read-only inventory mutating.

### Read-only implementation validation on 2026-07-18

The first real dry run after implementation observed 905 exact-prefix keys.
All 905 were known legacy immortal candidates; no current positive-TTL or
on-policy receipt key was present in that observation. Candidate digest was
`c920154deb6c369a6407c2195749deb502772d1f0a6afad56b3b2e474d81c009`.
The service gate correctly reported not ready because trainer adjunct services
were still active. `changed_key_count` was zero, and a filesystem check
confirmed that the proposed archive file was not created. This is a
point-in-time observation, not authority to assume the same count at apply.

## 2. Operator-controlled maintenance bracket

The cleanup tool never performs this step. Before apply, the operator must
place the three required units into a loaded/inactive state and ensure no
manual trainer publisher is running. Use read-only checks first:

```bash
systemctl --user show \
  ai-bot-v2-native-cuda-trainer-persistent.service \
  ai-bot-v2-trainer-checkpoint-evidence.service \
  ai-bot-v2-trainer-training-live-loop.service \
  ai-bot-v2-native-ppo-masa-continuous-training-guard.service \
  ai-bot-v2-native-ppo-masa-continuous-training-guard.timer \
  --property=LoadState --property=ActiveState --no-pager
```

Service stop/start decisions are separate operator actions. Do not apply while
a trainer or checkpoint maintenance process is still active. Do not remove the
persistent trainer repair hold merely to perform this cleanup.

## 3. Apply the reversible archive and cleanup

Only after the maintenance bracket is confirmed:

```bash
.venv/bin/python tools/quarantine_legacy_trainer_redis_namespace.py \
  --repo-root "/home/wali/Desktop/AI BOT REBUILD" \
  --redis-url redis://127.0.0.1:6379/0 \
  --apply \
  --ack-legacy-immortal-trainer-redis-cleanup
```

Apply performs this sequence:

1. Observe service and manual-writer gates.
2. Scan and losslessly inventory the exact namespace.
3. Scan again and require the cleanup candidate set to be unchanged.
4. Observe the gates again.
5. Atomically write a mode-`0600` archive beneath the mode-`0700` directory
   `.local_models/quarantine/trainer_redis_namespace/`.
6. Reopen the archive, verify ownership/mode/schema/target/digests, and require
   its canonical material to match the in-memory payload.
7. `WATCH` the exact archived candidate keys and compare type, exact `DUMP`
   bytes, `PTTL=-1`, and `TTL=-1` immediately before deletion.
8. Delete the complete candidate set in one Redis transaction.
9. Verify every deleted candidate is absent.

There is no TTL drift tolerance on deletion candidates because every candidate
must be immortal. Time-decaying positive-TTL keys are noncandidates and are
preserved. A watch conflict, value mismatch, type mismatch, key disappearance,
unsupported type, failed service observation, active writer, or digest mismatch
returns a `REFUSING:` error and exit status 2.

If Redis disconnects at or after `EXEC`, the archive remains durable but the
client can no longer prove whether deletion committed. The tool reports this
as an explicit verification failure. Keep writers inactive and run the
read-only inventory before any retry; never infer success or failure from the
exit code alone in that ambiguity window.

Record the archive path printed by the successful apply command. Do not edit,
move, broaden permissions on, or delete that archive until the new trainer
generation has completed its separately governed validation/retention period.
Apply and rollback refuse archive paths outside the dedicated
`.local_models/quarantine/trainer_redis_namespace/` directory.

## 4. Post-cleanup verification

Run the read-only command again while the trainer maintenance bracket remains
in place. The known legacy immortal candidate count should be zero. Current
positive-TTL keys or preserved behavior receipts can still appear in the full
prefix count and are not cleanup failures.

Checkpoint-root quarantine, empty-root bootstrap, trainer canary execution,
model promotion, and continuous-service release are separate procedures. A
successful Redis cleanup must never be labeled an A+ grade or serving-model
promotion by itself.

## 5. Rollback/import

Rollback restores only the keys that apply was authorized to delete. It never
imports preserved/current records from the full archive inventory.

With the same three units loaded/inactive and no manual writer process:

```bash
.venv/bin/python tools/quarantine_legacy_trainer_redis_namespace.py \
  --repo-root "/home/wali/Desktop/AI BOT REBUILD" \
  --redis-url redis://127.0.0.1:6379/0 \
  --rollback "/absolute/path/to/hybrid_cuda_legacy_TIMESTAMP.json" \
  --ack-legacy-immortal-trainer-redis-rollback
```

Rollback verifies archive, inventory, candidate, and per-value SHA-256
bindings; refuses a symlink or archive broader than mode `0600`; refuses to
overwrite any existing candidate key; restores candidates with `TTL=0`
(immortal); and verifies the restored `DUMP` payload and `PTTL=-1`.

If a candidate key already exists, stop and investigate. Do not use `REPLACE`
or manually splice records from the archive: an existing key may belong to a
new trainer generation.

Redis transactions prevent interleaving, but Redis does not roll back earlier
commands when a later `RESTORE` command has a runtime error. An incompatible
RDB payload or an out-of-memory error can therefore leave a partial restored
set even though the tool exits with `REFUSING:`. This limitation applies only
to rollback/import, not apply's single watched `DEL`. After any rollback exit
status 2, keep all writer units inactive, inventory the exact keys, and do not
retry or delete a partial set without a separate reviewed recovery plan.

## Operational boundaries

- Exact-prefix scope is immutable in this tool.
- No wildcard delete command (`KEYS | DEL`, `FLUSHDB`, or `FLUSHALL`) is used.
- The full archive can contain sensitive model/trading telemetry. Keep it
  local and mode `0600`.
- Redis `DUMP`/`RESTORE` compatibility must be evaluated before moving an
  archive to a different Redis major version. The intended rollback target is
  the same local Redis environment.
- The utility does not stop readers. Removal of stale signals should make
  hardened consumers fail closed until a fresh verified publisher supplies
  current evidence.
- This maintenance operation cannot guarantee returns or the 1000x objective.
