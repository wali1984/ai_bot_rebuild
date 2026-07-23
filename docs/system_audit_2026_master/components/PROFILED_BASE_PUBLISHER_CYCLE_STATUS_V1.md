# Profiled Base-Publisher Cycle Status Reader V1

Status: strict local cycle-status reader complete, independently rereviewed,
tested against synthetic adversarial cases and the current publisher status,
committed, pushed and installed atomically with its producer in immutable
release `974caa6c263eeadf09fad5028d0883d304a14075`. Independent witness,
promotion, serving, prediction, paper/live and execution authority remain
separate and false.

Original implementation checkpoint: `c61ee6ba3b`. Current installed contract:
`974caa6c263eeadf09fad5028d0883d304a14075`.

Primary implementation:

- `v2/backend/app/services/native_trainer/profiled_base_publisher_cycle_status_v1.py`

Primary tests:

- `v2/backend/tests/unit/services/native_trainer/test_profiled_base_publisher_cycle_status_v1.py`

Related components:

- [PROFILED_TRAINING_OBSERVATION_COORDINATOR_STATE_V1.md](PROFILED_TRAINING_OBSERVATION_COORDINATOR_STATE_V1.md)
- [PROFILED_TRAINING_EXTERNAL_WITNESS_RUNTIME_V1.md](PROFILED_TRAINING_EXTERNAL_WITNESS_RUNTIME_V1.md)

## 1. Role and authority boundary

The base publisher atomically replaces one canonical JSON status file after a
cycle. This reader verifies that exact local file and returns only the cycle
identity and counts required to begin a coordinator cursor.

The status contains a writer-computed SHA-256. Recomputing that hash proves
local serialization integrity only. It does not prove an independent writer,
external monotonic ordering, complete sample consumption, optimizer admission,
checkpoint/model authority, prediction authority, paper/live authority, order
submission, execution, or runtime wiring. The returned object sets local
integrity to `true` and all of those stronger claims to `false`.

## 2. File and parser checks

The configured path must be absolute and normalized. Every parent component
and the final file are checked with `lstat`; symlinked parents and final
symlinks fail closed. The opened descriptor must identify the same regular
file, owned by the effective user, with one hard link and no group/other write
permission.

The reader records descriptor size, device and inode, performs a bounded exact
read, checks for growth, and rechecks descriptor size, mtime and ctime. The
parser then requires:

- one terminal newline and no carriage return;
- ASCII canonical JSON with sorted keys and compact separators;
- no duplicate keys or nonfinite values;
- no more than the writer's existing 16 MiB state/status ceiling; and
- exactly 60 top-level fields.

The ceiling is a parser/resource safety bound. It is not a market, symbol,
sample, training, risk, leverage, or performance threshold.

## 3. Identity and time contract

The reader requires the exact status and publisher schema versions, a
lowercase 64-character `state_sha256`, and a lowercase 64-character
`status_sha256`. It removes only `status_sha256`, recomputes the publisher's
canonical `stable_sha256` over the remaining object, and compares the result.

These four clocks must use canonical UTC microsecond notation and be
nondecreasing:

```text
cycle_started_at
  <= discovery_completed_at
  <= selection_at
  <= cycle_completed_at
```

`cycle_elapsed_seconds` must be a finite nonnegative integer or float. It is
not substituted for any wall-clock field.

## 4. Symbol inventories and writer set algebra

All ten count/list pairs require an integer nonnegative count, exact list
length, unique canonical uppercase symbols, and no unhashable or malformed
entries:

1. discovered;
2. eligible;
3. selected;
4. resource deferred;
5. published;
6. exact replay;
7. masked-cost observation;
8. masked-cost replay;
9. unchanged; and
10. failed.

The reader also enforces relationships produced by the writer's cycle loop:

```text
eligible subset discovered
selected subset eligible
resource_deferred subset eligible
selected intersection resource_deferred = empty
failed subset discovered
failed intersection eligible subset selected
each outcome subset selected
all five outcome sets pairwise disjoint
outcome_union intersection failed = empty
selected = outcome_union union (selected intersection failed)
```

Discovery-time missing-timeframe failures may be discovered but ineligible.
An eligible failure, however, can exist only for a symbol actually selected in
that cycle. These rules reject coherent-looking but writer-impossible status
documents even if their self-hash is recomputed.

## 5. Source-provenance shard preflight contract

The current 60-field status adds three exact top-level fields:

```text
source_provenance_shard_preflight_count
source_provenance_shard_rollover_count
source_provenance_shard_preflights
```

The count must equal the list length; rollover count must be nonnegative and no
larger than the preflight count. Each preflight is an exact-field object keyed
by its zero-based `status_preflight_index`, canonical symbol and publication
attempt. Duplicate `(symbol, attempt)` identities fail closed. The symbol must
belong to that cycle's selected inventory.

Before any market capture, the producer enumerates the contiguous
`shard-NNNNNNNN` directory sequence and completely verifies the active ledger.
The evidence binds active presence/index/path, byte and entry count, committed
head sequence/SHA, verification start/completion clocks and monotonic elapsed
seconds. For a nonempty shard, head sequence must equal entry count and the head
digest must be canonical. Absence or an empty active shard has no synthetic
head. Corruption fails before rollover and before market capture; rollover is
not a way to bypass a damaged predecessor.

The producer derives the remaining verification work from the actual route:
five full passes for a new two-timeframe append and seven for the retry-safe
route. It multiplies the measured full-pass duration by seven, adds the
persisted adaptive materialized-symbol elapsed estimate, and compares the
combined projection with the strictly positive window returned by the actual
injected decision planner. Both the verification-only and combined projections
and Boolean comparisons are persisted and recomputed by the reader. The
decision must be strictly later than preflight completion; equality fails.

For a present, nonempty shard, combined work that fits retains the active
shard. Work that cannot fit creates exactly `active_index + 1`, mode `0700`,
and fsyncs its parent before capture. No-active and active-empty cases retain
their exact bootstrap path without claiming a rollover. The evidence explicitly
states that no market/performance threshold was applied.

After capture, the existing 512 MiB/1,000,000-entry integrity ceilings remain a
separate hard safety check. The final publication shard must be either the
preflight selection or its exact successor. The status records whether that
selection was reconciled and whether a second hard-cap roll occurred. These are
resource/integrity ceilings, not signal, sample-quality, risk, leverage or
profit thresholds.

Nested publications/failures carry only bounded references: status index,
preflight hash, symbol and attempt. The full preflight object occurs once at
top level, preventing retry detail from duplicating a potentially large status
payload. The status remains subject to the existing 16 MiB parser ceiling.

Changing source-ledger scan behavior, required timeframes, append/readback
pass count, decision planner, shard naming, hard caps, preflight fields or
reference hashing affects the producer, this reader and every trainer consumer
atomically. Never deploy only one side of this exact schema.

## 6. Authority checks

The five publisher `authority` keys must be present as exact booleans and all
must be `false`:

```text
trainer_admission_authorized
prediction_authorized
paper_trading_authorized
live_execution_authorized
runtime_wired
```

The five `authority_semantics` keys must also be exact booleans. Publisher
runtime authority, masked-parent admission, automatic trainer transition, and
prediction/paper/live authority must remain false. The only contextual flag,
`published_child_trainer_admission_authorized`, must equal the writer formula:

```text
bool(published_symbols or exact_replay_symbols)
```

It is still a publisher child classification, not optimizer admission.
`legacy_feature_redis_write_performed` and
`market_performance_thresholds_applied` must be false. The dynamic selection
universe must explicitly state that it confers no trainer evidence or
authority.

## 7. Returned data and downstream impact

The immutable result exposes file identity, status/state hashes,
classification, four clocks, seven summary counts, and explicit
trust/authority booleans. It does not return the nested mutable payload. The
coordinator must pin the exact `status_sha256` and `cycle_completed_at` before
building a manifest. A newer publisher cycle cannot replace an inflight cursor.

Changing any publisher status field, count/list relationship, timestamp
format, authority semantic, hash serialization, ownership/mode, or atomic-file
behavior affects this reader first and then the coordinator manifest trigger.
Such a change requires writer-reader contract tests before deployment; it must
not be bypassed by accepting a partial schema or treating the self-hash as
independent authentication.

## 8. Verification evidence

The original reader checkpoint had:

- 57 of 57 top-level fields checked;
- 10 of 10 count/list pairs checked;
- four ordered clocks checked;
- five authority fields and five authority-semantics fields checked;
- 29 focused unit tests passed;
- Ruff and Python compilation passed;
- one current production status read successfully as local integrity only; and
- final bounded independent rereview: zero high, medium, or low defects.

At that historical live read, status SHA-256 was
`f5ffe9fd3e39a34a02b131b2e4f7a73290d5efaf5cf877ad6880bacaffbbe812`,
cycle completion was `2026-07-22T14:59:49.357107Z`, local integrity was true,
and independent authentication was false. These are timestamped observations,
not permanent state.

The installed preflight extension adds three top-level fields for an exact
60-field contract. Final regression evidence was 35/35 strict-reader cases and
73/73 producer cases, with Ruff and `git diff --check` clean. The first
installed live read accepted status SHA-256
`ef498003ef2747a624d5f635bee7a98e1ca50af66711652f461c8eaf1a810e3d`,
32,030 bytes, completion `2026-07-23T03:19:06.573459Z`, one selected and
published symbol, zero failures/deferred symbols, one verified preflight and
one proactive rollover. Local integrity was true; all independent witness,
optimizer admission, serving, prediction, paper/live, order and execution
authority returned by this reader remained false.
