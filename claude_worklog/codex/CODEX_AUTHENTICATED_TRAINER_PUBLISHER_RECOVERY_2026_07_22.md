# Authenticated trainer-publisher recovery checkpoint — 2026-07-22

## Scope and decision

This checkpoint covers the profiled base-feature publisher, its authenticated
Binance USD-M commission-evidence transport, adaptive paper-capital notional
evidence, the immutable cost CAS, and the independent strict-training ledger
loader. It does not wire samples into an optimizer, publish predictions, alter
paper positions, or authorize live execution.

The publisher slice is online and accepted. The optimizer/trainer runtime is
not yet online through this new path because every admitted sample still says
`runtime_wired=false`, and the loader remains a factory-only O(total-ledger)
consumer.

## Pushed identities and immutable runtime

| Item | Exact identity |
| --- | --- |
| Loader correction commit | `9fcea85f27a56b757a3b0af362e35ac9a58a9df3` |
| Resident WAL/SHM liveness commit | `e34af1e6a6bb9b54818e18f9279fcc9904de0922` |
| Current immutable pin commit | `cb927adaabecac0dab6e68827f8f4b6b8d37a2aa` |
| Branch | `codex/trainer-commission-integration-20260722` |
| Code release | `/home/wali/ai_bot_local_data/deployments/ai_bot_rebuild/e34af1e6a6bb9b54818e18f9279fcc9904de0922` |
| Dependency release | `/home/wali/ai_bot_local_data/deployments/python_envs/6360ea33fcfb9f9a81724989bbd32ace2b02bf7eaa7a8771d64d282f423173f0` |
| Service | `ai-bot-v2-profiled-base-feature-publisher.service` |
| Installed drop-in | `/home/wali/.config/systemd/user/ai-bot-v2-profiled-base-feature-publisher.service.d/90-immutable-release.conf` |

The code checkout is detached at the exact SHA, has no tracked diff, retains
Git executable bits, has no writable regular file/directory, and is mounted
read-only in the service. The observed process used that release for its CWD,
`PYTHONPATH`, executable, bytecode-cache namespace, and `AI_BOT_CODE_SHA`.
`LIVE_GATE=blocked_human_only` remained effective.

## Resident WAL/SHM liveness correction

The original publisher opened and closed its SQLite connections within each
publication cycle. SQLite could checkpoint, delete, and later recreate the
`-wal`/`-shm` coordination files when the last connection closed. The hardened
read-only observer is forbidden from creating those writer-owned files. It
therefore alternated between a valid readiness artifact and fail-closed
`DatabaseError` artifacts while the old publisher continued to append valid
rows. This was a real availability defect, not ledger corruption and not a
reason to relax the observer.

The correction has three boundaries:

1. the CLI acquires one exact-path `FeatureSnapshotWriterLease` for the complete
   resident process;
2. one exact-path `DurableFeatureSnapshotLedger` instance is injected into the
   publisher instead of being recreated per cycle; and
3. `resident_wal_sidecar_guard()` keeps one private connection open after
   initialization, immediately sets `PRAGMA query_only=ON`, requires WAL mode,
   requires no active transaction, verifies both sidecars before and after the
   loop, never exposes the connection, and closes before releasing the writer
   lease.

This is a storage-coordination invariant, not a market threshold. It does not
change sample selection, model inputs, reward/strategy logic, leverage, margin,
paper execution, live execution, or downstream authority. Failures still exit
the publisher closed with status 78.

Liveness-slice files:

- `v2/backend/app/cli/v2_profiled_base_feature_publisher.py`
- `v2/backend/app/services/native_trainer/durable_feature_snapshot_ledger.py`
- `v2/backend/app/services/native_trainer/profiled_base_feature_publisher_v1.py`
- `v2/backend/tests/unit/services/native_trainer/test_durable_feature_snapshot_ledger.py`
- `v2/backend/tests/unit/services/native_trainer/test_profiled_base_feature_publisher_v1.py`
- `v2/backend/tests/unit/services/native_trainer/test_profiled_training_waiting_runtime_v1.py`

## End-to-end component path

```text
paper loop atomic cycle
  ├─ v2:paper:adaptive_sizing_runtime_status
  └─ v2:paper:account_margin_status
           │ same paper_cycle:<64 hex>, same generated_utc
           ▼
adaptive cold-start expected-notional policy
  + NIGHTUSDT visible bid/ask depth
  + NIGHTUSDT order-book features
  + NIGHTUSDT mark price
           │ 5 bound source objects, no static default
           ▼
profiled base publisher
  + closed/final 5m and 1h source provenance
  + authenticated commission broker envelope/receipt
           ▼
causal cost artifact + exact 21-object immutable CAS inventory
           ▼
atomic SQLite append: parent 35 + strict child 39
           ▼
independent loader: physical 39 -> logical 446 -> model vector 1,784
           │
           └─ trainer candidate only; prediction/paper/live/runtime false
```

## Original loader correction code boundary

Changed files:

- `v2/backend/app/services/native_trainer/profiled_training_ledger_loader_v1.py`
- `v2/backend/tests/unit/services/native_trainer/test_profiled_base_feature_publisher_v1.py`
- `claude_worklog/systemd/user/ai-bot-v2-profiled-base-feature-publisher.service.d/90-immutable-release.conf`
- `v2/backend/tests/unit/services/native_trainer/test_profiled_base_publisher_runtime_credentials.py`

The defect was in `_reopen_cost_cas`. The cost artifact inventory contained 21
objects, but the loader reconstructed only 19. The two omitted objects were
the authenticated broker envelope and the signed consumer receipt. Merely
allowing two extra hashes would have weakened the exact-inventory invariant,
so the loader now independently reopens and validates both objects before its
`inventory == expected_inventory` comparison.

The loader deliberately does not recompute either HMAC because it has no HMAC
secret. The credentialless broker reader owns cryptographic HMAC verification.
The loader independently verifies immutable bytes, canonical JSON, content
checksums, exact schemas/fields, payload/CAS hashes, mirrored HMAC digests,
source bindings, timestamp ordering, and false authority flags.

## Fee-transport contract

`fee_transport_provenance` has exactly 23 fields:

```text
schema_version
source_transport
verification_status
broker_envelope_sha256
broker_envelope_cas_address
broker_envelope_evidence_hmac_sha256
consumer_receipt_payload_sha256
consumer_receipt_cas_address
consumer_receipt_evidence_hmac_sha256
rotation_receipt_sha256
source_available_at
broker_available_at
consumer_observed_at
consumer_checked_at
decision_time
expires_at
evidence_auth_algorithm
evidence_auth_key_id
exchange_credentials_read
trainer_authority
prediction_authority
paper_authority
live_authority
```

The persisted broker envelope has exactly 61 fields. The signed consumer
receipt has exactly 32 fields and an ordered eight-item verification list. The
loader enforces these identities and bindings:

- broker schema/producer/source, `GET /fapi/v1/commissionRate`, `USER_DATA`,
  symbol, `HMAC-SHA256`, request weight 20, and host-Redis shared budget;
- read-only transport; no credentials stored; no order, leverage, or margin
  mutation; no trainer, prediction, paper, or live authority;
- receipt schema/kind, broker schema, symbol and decision identity, exact eight
  verification checks, and `broker_cas_object_count=8`;
- canonical ASCII JSON and canonical content checksum for each object;
- actual envelope and receipt bytes bound to their two CAS addresses;
- raw fee response, fee artifact, and fee input-receipt hashes bound back to
  `fee_source`;
- envelope hash/HMAC, rotation receipt, credential fingerprint, key ID and
  clock fields mirrored through the consumer receipt and provenance record;
- `source_available_at <= broker_available_at <= consumer_observed_at <=
  consumer_checked_at <= decision_time < expires_at`;
- broker request/response/source/generated/available/expiry clocks in causal
  order; and decision time identical to the cost artifact and ledger binding.

The other six addresses referenced by the broker envelope are structurally
validated but are not added to the causal-cost inventory. The broker already
authenticated all eight broker-side CAS objects; the causal-cost artifact
intentionally persists only the envelope and signed consumer receipt as the
two additional transport objects. Raw response, fee artifact and fee receipt
are already present through `fee_source`.

## Adaptive notional and paper-margin evidence

At `2026-07-22T10:51:40.241Z`, the two paper producer records shared
`paper_cycle:dfb8240ebf03c279b08b6f1447fa99568c2042cb1df14f26c753596273e39eb0`.

Observed values:

- candidate allocations: 0;
- accepted allocations: 0;
- fixed runtime notional removed: true;
- margin status: `PASS`;
- numeric, buffer and aggregate invariants: true;
- free margin after buffer: `$2,498.45775782`;
- newly reserved margin: `$0.00`;
- paper only: true;
- routes to live / places real order: false;
- leverage and margin-mode mutation: false.

Zero candidates therefore did not kill publication or invent a nominal amount.
The cold-start policy derived `$2,498.45775782` from causal paper free margin
after buffer and symbol-visible depth, with policy
`adaptive-paper-capital-symmetric-visible-depth-cold-start-v1`. Its provenance
bound five source objects and reported
`FACTORY_TOKEN_SOURCE_RECEIPT_CAS_POLICY_VERSION_AND_BOUND_OBJECTS_VERIFIED`.

## Live acceptance counts

The newly pinned process started at `2026-07-22T10:49:38Z` and completed its
first cycle at `2026-07-22T10:53:12.241726Z`.

| Evidence | Count/value |
| --- | --- |
| Main PID at observation | `3647686` |
| Service restarts | `0` |
| Selected symbols | 1 (`NIGHTUSDT`) |
| Published strict pairs | 1 |
| Failed symbols | 0 |
| Masked cost observations | 0 |
| Publication attempts | 2 (whole-window temporal retry) |
| Source timeframe appends | 2 (`5m`, `1h`) |
| Feature-ledger rows inserted atomically | 2 |
| Parent/child sequences | 15 / 16 |
| Duplicate rows | 0 |
| Transaction committed/read back | true / true |
| Cost CAS objects | 21 |
| Fee transport fields | 23 |
| Broker envelope bytes | 5,117 |
| Consumer receipt bytes | 2,061 |
| Expected notional | `$2,498.45775782` |
| Legacy feature Redis writes | 0 |

NIGHTUSDT cost artifact:
`c8edb0bd00f85da76482e89ddfde9c7903327635037280821ff86718d9ff0527`.
The envelope and consumer receipt payloads are respectively
`5dafdcebc7c941ea9ed071bce01681ffe841d96e05a664791711c3674142d5ba`
and `1796d525be9d674361cd251c91a84ef997804e79ec53f8db5e06288fa5036b1f`.

The immutable-release loader then reopened the complete ledger observation:

- scanned strict rows: 2;
- admitted samples: 2 (`LDOUSDT` sequence 14, `NIGHTUSDT` sequence 16);
- exclusions: 0;
- physical values per sample: 39;
- logical values per sample: 446;
- model-vector values per sample: 1,784;
- trainer-admission flags true: 2;
- prediction, paper, live and runtime-wired flags true: 0.

## Resident-release live acceptance

The resident release started at `2026-07-22T11:54:33Z`. A 39-sample,
15-second-cadence burn-in observed 13 distinct observer artifacts across two
complete publisher cycles and their intervening idle boundary:

| Evidence | Count/value |
| --- | --- |
| Publisher PID / restarts | `3727644` / 0 |
| Observer PID / restarts | `3670540` / 0 |
| Sampled service/sidecar observations | 39 |
| Distinct observer artifacts | 13, all successful |
| Publisher cycles accepted | 2 |
| First new pair | TAOUSDT sequences 39/40 |
| Second new pair | TREEUSDT sequences 41/42 |
| Per-cycle selected / published / failed | 1 / 1 / 0 |
| Final verified ledger records | 42 |
| Final verified append receipts | 27 |
| Final strict child candidates | 15 |
| Final exclusions | 0 |
| Final integrity / scan complete | true / true |
| WAL inode | `59941802`, unchanged |
| SHM inode | `59942438`, unchanged |
| Observed WAL sizes | 0, 515,032, 1,030,032 bytes |

Cycle one ran from `2026-07-22T11:54:34.860494Z` through
`2026-07-22T11:58:44.300142Z`; cycle two ran from
`2026-07-22T11:59:34.861301Z` through
`2026-07-22T12:03:47.100840Z`. The observer artifact generated at
`2026-07-22T12:05:06.810763Z` remained
`PROFILED_CHILD_CANDIDATES_AVAILABLE_OPERATOR_PROMOTION_REQUIRED`, with
`probe_error=null`. Every resident-runtime training/checkpoint/model/prediction/
paper/live/execution/runtime authority flag remained false.

## Regression evidence

- Complete affected ledger/publisher/observer/loader family: **201 passed** in
  607.48 seconds.
- Focused resident-guard and observer integration tests from the immutable
  release: **7 passed** in 14.97 seconds.
- Complete publisher credential/unit/pin suite: **33 passed** in 0.33 seconds.
- Full strict-loader suite from the immutable release: **32 passed** in
  115.94 seconds.
- Full profiled-publisher suite from the immutable release: **62 passed** in
  504.97 seconds.
- Authenticated broker plus loader integration paths: **2 passed**.
- Immutable pin regression: **1 passed**, 32 deselected.
- Python compile failures: 0.
- Ruff failures on changed Python files: 0.
- Scoped systemd unit verification errors: 0. `systemd-analyze` still printed
  unrelated pre-existing warnings from other user units.
- Release tracked diffs: 0.

## Change-impact map

| Small change | Direct impact | Required revalidation |
| --- | --- | --- |
| Add/remove a fee-transport field | Cost builder, canonical artifact hash, loader exact field set, strict child admission | causal-cost tests, publisher tests, loader tests, new live child |
| Add a persisted CAS object | Publisher inventory and `_reopen_cost_cas.expected_inventory` | exact object-count, byte/hash readback, omission/substitution failure |
| Change broker envelope/receipt schema | Broker reader, HMAC/checksum material, cost transport provenance, loader | broker + cost + publisher + loader suites; rotate only with versioned schema |
| Change either paper Redis payload | Atomic paper-cycle binding and cold-start notional provenance | paper producer, cold-start policy, cost and loader integration |
| Change `available_at`/decision clocks | PIT admission and expiry | boundary retry plus negative future-leak tests |
| Change the 39/446/1,784 projection | Model ABI, checkpoint compatibility and every trainer consumer | versioned projection and full trainer/checkpoint migration |
| Change immutable release SHA | systemd CWD, executable, `PYTHONPATH`, pycache and diff preflight | detached release, pin test, unit verify, restart, process proof, live cycle |

## Operator checks

```bash
systemctl --user show ai-bot-v2-profiled-base-feature-publisher.service \
  -p ActiveState -p SubState -p MainPID -p NRestarts -p ExecMainStartTimestamp

jq '{cycle_started_at,cycle_completed_at,classification,selected_symbols,
     published_symbols,failures,masked_cost_observation_symbol_count}' \
  /home/wali/ai_bot_local_data/v2_native_trainer/profiled_base_publisher_v1/profiled_base_publisher_status_v1.json

git -C /home/wali/ai_bot_local_data/deployments/ai_bot_rebuild/e34af1e6a6bb9b54818e18f9279fcc9904de0922 \
  diff --quiet --exit-code e34af1e6a6bb9b54818e18f9279fcc9904de0922 --
```

A cycle with `feature_window_tail_is_stale` or unavailable closed-window
provenance is a safe isolated retryable failure, not proof that the process is
dead. Distinguish service state/PID/restarts from the most recent per-symbol
cycle classification. Never force a child through those gates.

## Remaining blockers and next safe slice

The publisher and its waiting observer are fully online; the persistent
optimizer is not. The exact next keystone is a bounded authenticated
observation manifest/adapter that lets the persistent trainer consume these
strict rows without doing an O(total-ledger) integrity scan for every page and
without trusting a mutable cursor. Local manifest, stage-head/page-completion,
sealed-corpus, and admission contracts exist, but there is no production
caller and no provisioned independent Ed25519 witness implementation,
credential, or signed artifact. Until those boundaries are implemented,
independently witnessed, and tested, `runtime_wired=false` is correct. There is
no honest fixed optimizer-online ETA until the operator selects and provisions
that independent witness.

Two strict samples prove end-to-end correctness, not statistical sufficiency,
model quality, an A+ grade, or any return target. Candidate supply must grow
only from fresh closed windows and authenticated evidence. This checkpoint
does not guarantee 1000x returns and does not authorize live trading.
