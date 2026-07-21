# AI Bot V2 master operator manual

**Updated:** 2026-07-16

**Audience:** operator/SRE/developer maintaining the audited workstation

**Default stance:** observe first, preserve state, fail closed, keep live trading disarmed.

This is the safe operating manual for the current system. It reflects the deployed workstation, not merely checked-in service files. Commands are run from `/home/wali/Desktop/AI BOT REBUILD` unless an absolute path is shown.

## 1. Non-negotiable safety rules

1. **Do not enable, arm or test real order submission from this manual.** Real Binance order transport exists even though no authorized submitter was active at audit time.
2. **Do not edit exchange-touching, order, cancellation, modification, strategy, PPO, MASA or risk logic without explicit operator approval.**
3. **Do not repair/reload/start the failed orderbook replay rollover without approval.** Its enabled persistent timer already retries every six hours. Repairing the broken service path would let the next scheduled trigger apply a conflicting 100 GiB deletion policy to a replay tree observed between roughly 247 and 259 GiB during this audit.
4. **Do not run the full backend integration suite against the current workspace/Redis.** Tests have previously overwritten real paper state and destroyed closed-trade history.
5. **Do not treat a process, heartbeat, status JSON, dashboard, risk ID or “accepted” counter as proof of success.** Verify the authoritative contract and lineage.
6. **Do not use unfinished candles or a feature whose `available_at` is later than `decision_time`.** Preserve each timestamp’s meaning.
7. **Do not put passwords, API keys, cookies, bearer tokens, private URLs or raw environment values in commands, tickets, docs or chat.** No approved credential-retrieval mechanism or named security owner was proven at audit time. Do not retrieve credentials until the authorized human operator/security owner establishes a protected mechanism and a non-secret procedure reference.
8. **Do not repair/restart multiple services at once.** Capture before-state, change one authority, observe a full cycle, and retain rollback evidence.
9. **Do not assume Git describes deployment.** Effective user-systemd units/drop-ins run from mutable repo state and diverge from versioned files.
10. **Do not add manual deletion or change/pause/disable/mask retention without approval and a before-state capture.** A separate enabled 15-minute janitor is already non-dry-run and mutates replay/cache/log/temporary holdout artifacts; evidence preservation is racing that automation until authorities and protected datasets are reconciled.

## 2. What is running

The earlier 2026-07-16 operations snapshot found 157 installed `ai-bot*` user-unit files, 81 running services, 36 active timers and 3 failed services. A direct recheck found 156 installed basenames and 35 active timers. Counts change continuously.

> **Post-cut update (2026-07-16, evening):** re-measured **159** installed units, **84** running services, **36** active timers, **2** failed (`ai-bot-v2-autonomous-no-manual-next-task-policy`, `ai-bot-v2-closed-candle-replay-evidence`). Operational hardening this session: `out-of-sample-evidence-producer` **removed** (OOM-restart loop), `adaptive-capital-productivity` **memory-capped** (`MemoryHigh=6G`/`MemoryMax=8G`, was uncapped/leaking to ~15.5 GiB), `paper-equity-reconciliation-loop` set **`StandardOutput=null`** (had flooded syslog to ~35 GiB). Operator-pending: `tools/OPERATOR_crash_hardening_sudo.sh` (syslog truncate + journald cap, needs sudo), `tools/fix_cursor_state_bloat.sh` (Cursor `state.vscdb` reclaim, run with Cursor closed). See MASTER_SYSTEM_DOC.md → Post-cut reconciliation. LIVE remains BLOCKED.

Functional flow:

```text
provider/exchange readers
  → Redis market/provider keys
  → feature/TA/context/snapshot workers
  → persistent/offline trainers and publishers
  → all-timeframe publisher
  → orchestrator
  → risk records + paper signals
  → paper trade-management/lifecycle/accounting
  → portfolio/guardian/outcomes/replay
  → API/public artifacts/web/mobile
```

Automation supervisors, watchdogs, retention and report publishers operate around that flow. Two trainer authorities and two portfolio publishers were active. Backend ran four Uvicorn workers from the mutable repository on loopback port 8000. Vite preview served ignored `dist` on all interfaces at port 5173.

## 3. Operator truth hierarchy

Use the narrowest primary truth for the question:

| Question | Check first | Confirm with |
|---|---|---|
| Is a worker running? | `systemctl --user show` effective unit/PID/result | sanitized process identity and worker-specific heartbeat |
| Is data fresh? | producer payload’s event/available/generated/cutoff fields | TTL and upstream heartbeat |
| Did a prediction publish durably? | prediction payload plus replay/archive write evidence | lineage and archive/blob existence; publisher return handling is currently defective |
| Did risk allow? | matched risk record action | ID, decision/prediction hash and time; ID existence is not allow |
| Is a paper fill valid? | lifecycle/ledger record after invariant checks | admission path, risk action, position transition, accounting and execution time |
| Is the trainer learning? | accepted rows, optimizer/weight delta and checkpoint load evidence | rejection reasons and clean holdout exclusion |
| Is UI accurate? | primary Redis/file contract | public artifact age and client decode |
| Is live safe? | effective release/live/armed/transport state and active callers | live-readiness gates; never infer from one flag |

## 4. Start-of-shift snapshot

Run read-only checks and save the output in an operator-controlled incident/worklog location with secrets redacted.

### 4.1 Repository provenance

```bash
date --iso-8601=seconds
git rev-parse HEAD
git status --short --untracked-files=all
git log -5 --oneline --decorate
```

Interpretation:

- A dirty worktree is expected in this active workspace. Do not discard or overwrite changes you do not own.
- Git HEAD can advance while auditing. Record start/end commits and start/end
  content fingerprints for every in-scope mutable artifact; commit equality alone
  does not prove stable dirty-worktree bytes.
- Git status records path state, not file content. Preserve owned/concurrent diff
  provenance separately without copying secret values.
- Ignored runtime/model/frontend-build/effective-deployment files are not shown by
  ordinary Git status. Record their sizes and SHA-256 values in a secret-safe
  bundle manifest together with canonical docs, atlas, units/drop-ins, dist and
  checkpoints. No complete global bundle manifest was proven at audit time.

### 4.2 Installed/running systemd state

```bash
systemctl --user list-unit-files 'ai-bot*' --no-pager
systemctl --user list-units 'ai-bot*' --type=service --all --no-pager
systemctl --user list-timers 'ai-bot*' --all --no-pager
systemctl --user --failed --no-pager
```

For one service:

```bash
systemctl --user show SERVICE.service \
  -p Id -p LoadState -p ActiveState -p SubState -p Result \
  -p MainPID -p NRestarts -p FragmentPath -p DropInPaths \
  -p WorkingDirectory -p ExecStart --no-pager
```

Do not paste effective `Environment` or an unredacted process command into a report; credentials can be embedded in arguments.

### 4.3 Listener and HTTP liveness

Inspect listeners first:

```bash
ss -ltnp
```

Run each HTTP check separately so its captured output remains one valid JSON
document. Backend process liveness:

```bash
curl --fail --connect-timeout 3 --max-time 10 --silent --show-error \
  http://127.0.0.1:8000/health | \
  python3 -c 'import json,sys; p=json.load(sys.stdin); print(json.dumps(p, indent=2, sort_keys=True)); sys.exit(0 if p.get("status") == "ok" else "ERROR: backend health is not ok")'
```

Redis-backed backend health:

```bash
curl --fail --connect-timeout 3 --max-time 10 --silent --show-error \
  http://127.0.0.1:8000/api/v2/system/health | \
  python3 -c 'import json,sys; p=json.load(sys.stdin); print(json.dumps(p, indent=2, sort_keys=True)); sys.exit(0 if p.get("data", {}).get("redis_available") is True else "ERROR: backend answered but Redis is unavailable")'
```

Frontend listener:

```bash
curl --fail --connect-timeout 3 --max-time 10 --silent --show-error \
  http://127.0.0.1:5173/ >/dev/null
```

`/health` proves only that the FastAPI process answered with its expected status.
`/api/v2/system/health` itself returns HTTP 200 in degraded mode, so `curl
--fail` alone is insufficient; the parser above exits nonzero unless
`data.redis_available` is exactly true. Neither check proves providers, trainer,
paper lifecycle or public tunnel routing.

### 4.4 Redis capacity and persistence

These commands do not dump values:

```bash
redis-cli --no-auth-warning PING
redis-cli --no-auth-warning DBSIZE
redis-cli --no-auth-warning INFO memory | \
  rg '^(used_memory_human|maxmemory_human|maxmemory_policy|used_memory_rss_human|used_memory_peak_human):'
redis-cli --no-auth-warning INFO persistence | \
  rg '^(rdb_last_bgsave_status|rdb_last_bgsave_time_sec|rdb_changes_since_last_save|aof_enabled):'
redis-cli --no-auth-warning INFO stats | \
  rg '^(evicted_keys|expired_keys|keyspace_hits|keyspace_misses|rejected_connections):'
```

Escalate if:

- `used_memory` approaches the 32 GiB cap;
- `evicted_keys` increases;
- RDB background save fails;
- changes-since-save remains large;
- RSS or swap pressure threatens the host.

Because policy is `allkeys-lru`, critical keys have no protected namespace. Do not respond by deleting keys ad hoc.

### 4.5 Disk state

```bash
df -hT /
du -sh v2/runtime .local_models claude_worklog goal_state legacy_reference raw_evidence logs 2>/dev/null
```

Do not start rollover or run cleanup from pressure alone. Capture the largest consumers, protected replay/evidence/model sets, active writers and both retention policies first.

At the read-only `2026-07-16T08:32:41Z` observation, both
`ai-bot-v2-orderbook-replay-rollover.timer` and
`ai-bot-v2-disk-retention-janitor.timer` were loaded, enabled, active and
persistent. The former last triggered at `03:06:24 EDT` and was next scheduled
for `09:06:24 EDT`; the latter last triggered at `04:27:21 EDT` and was next
scheduled for `04:42:21 EDT`. Refresh those values before acting:

```bash
systemctl --user list-timers \
  ai-bot-v2-orderbook-replay-rollover.timer \
  ai-bot-v2-disk-retention-janitor.timer --all --no-pager
systemctl --user cat \
  ai-bot-v2-orderbook-replay-rollover.timer \
  ai-bot-v2-orderbook-replay-rollover.service \
  ai-bot-v2-disk-retention-janitor.timer \
  ai-bot-v2-disk-retention-janitor.service --no-pager
```

The effective 15-minute service invokes
`claude_worklog/tools/v2_disk_retention_janitor.py` without `--dry-run`. That
script deletes replay day directories older than five days or beyond its 300 GiB
and free-space policies, tail-replaces oversized JSONL, truncates oversized `.out`
logs, and deletes `/tmp/holdout_tail_*` older than six hours
(`claude_worklog/tools/v2_disk_retention_janitor.py:31-62`, `:99-173`,
`:176-255`). Its status at `2026-07-16T08:27:21.352199+00:00` reported
`dry_run=false`, ten temporary holdout files deleted and 89,478 bytes reclaimed;
no replay directory, JSONL tail or `.out` log was changed in that particular
cycle. Mutation during the audit is therefore observed, not hypothetical.

> **Post-cut update (2026-07-16, evening):** the rollover/janitor conflict is
> **unchanged** — `ai-bot-v2-orderbook-replay-rollover.timer` remains enabled/active
> and the 15-minute janitor still runs without `--dry-run`. Repairing the rollover
> would let its timer invoke the harsher policy, so it stays an operator decision, not
> an automatic repair. Separately, `tools/OPERATOR_crash_hardening_sudo.sh` (needs sudo)
> truncates the 35 GiB `/var/log/syslog` flood and caps journald so a runaway service
> can no longer fill the disk; it is pending operator execution.

### 4.6 Live-readiness observation

```bash
curl --fail --connect-timeout 3 --max-time 10 --silent --show-error \
  http://127.0.0.1:8000/api/v2/live-readiness | python3 -m json.tool
```

This is observation only. At audit time zero of eight gates passed. Never use the endpoint as an activation command or as proof that dormant live callers are absent.

## 5. Service-family checks

Service names may drift. Resolve the effective unit before relying on an example.

### 5.1 Market/provider ingestion

Check:

- unit active/result/restarts;
- producer heartbeat generated time;
- representative key TTL and payload timestamps;
- upstream connectivity/rate-limit state;
- symbol/timeframe coverage;
- final-candle and availability fields;
- error-rate/log growth.

Do not label a provider healthy merely because a credential name is present. Do not print credential values.

For a key, prefer metadata over content:

```bash
redis-cli --no-auth-warning TYPE 'v2:KEY'
redis-cli --no-auth-warning TTL 'v2:KEY'
redis-cli --no-auth-warning MEMORY USAGE 'v2:KEY'
```

When payload inspection is necessary, select only non-secret fields with a local parser. Never dump an entire provider/auth/order payload into a shared log.

### 5.2 Feature pipeline

Primary entrypoint: `v2.backend.app.cli.v2_feature_pipeline_native_loop`.

For a representative symbol/timeframe verify:

1. the newest candle is explicitly closed;
2. candle close is not later than `model_decision_time`;
3. every contributing source `available_at` is not later than `model_decision_time`;
4. snapshot `feature_cutoff` describes the newest information used;
5. MASA `feature_cutoff` is not later than the PPO `model_decision_time`;
6. per-source enrichment lineage exists;
7. missing/stale masks match data;
8. latest and archive writes succeeded;
9. snapshot age is within timeframe policy.

Current limitation: enrichment sources merged by `_merge_a_plus_context_features` and `_merge_external_v2_features` do not all carry a checked per-source temporal envelope. A green `feature_freshness_state` proves the core closed OHLCV state, not every merged field.

Use the exact stage fields throughout prediction, risk and paper investigation:

```text
each source available_at <= model_decision_time
MASA feature_cutoff <= PPO model_decision_time
model_decision_time <= paper_admission_decision_time <= execution_time
signal generated/available time <= paper_admission_decision_time < signal expiry/freshness deadline
```

`event_time` is when the source event occurred, `ingested_at` is receipt/persist
time, and `generated_at` is when a derived record was computed. They retain those
semantic roles; do not collapse them into generic `decision_time` or infer one
universal total ordering between `available_at` and `feature_cutoff`.

### 5.3 Trainer

Relevant active authorities at audit time:

- persistent native CUDA trainer;
- continuous offline GPU trainer;
- RL inference sidecar and checkpoint/evidence publishers.

Before diagnosing:

```bash
systemctl --user show ai-bot-v2-native-cuda-trainer-persistent.service \
  -p ActiveState -p SubState -p Result -p MainPID -p NRestarts \
  -p FragmentPath -p DropInPaths -p WorkingDirectory -p ExecStart --no-pager
systemctl --user show ai-bot-v2-continuous-offline-gpu-trainer.service \
  -p ActiveState -p SubState -p Result -p MainPID -p NRestarts \
  -p FragmentPath -p DropInPaths -p WorkingDirectory -p ExecStart --no-pager
nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu,temperature.gpu \
  --format=csv,noheader
```

Trainer health requires all of:

- clean accepted-row count greater than zero;
- rejection reasons accounted for;
- input dimension 1,908 and exact feature schema hash/order;
- finite loss/gradients/parameters;
- actual parameter/weight delta when a learning step is claimed;
- checkpoint blob safely loadable and tied to the reported manifest;
- publication/replay/archive success propagated;
- train/validation/holdout identities non-overlapping;
- no promotion by disabled/forced validation guard unless explicitly approved and labeled.

The audit-time ordered 477-feature contract is documented in
[TRAINER_PPO_MASA_REPLAY_AND_CHECKPOINTS.md](components/TRAINER_PPO_MASA_REPLAY_AND_CHECKPOINTS.md#51-ordered-feature-contract).
Its compact-JSON SHA-256 is
`263b7ce4feae6fcbc34ff4aad593bb8bde7aa3e6469d6662ab8b5186c200b239`.
Dimension 1,908 alone cannot detect a same-length reorder. This read-only AST
check avoids importing trainer runtime code and exits nonzero on count/order
drift:

```bash
python3 - <<'PY'
import ast
import hashlib
import json
from pathlib import Path

path = Path("v2/backend/app/services/native_trainer/hybrid_cuda_trainer/tensor_builder.py")
tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
node = next(
    item for item in tree.body
    if isinstance(item, ast.AnnAssign)
    and getattr(item.target, "id", None) == "FEATURE_SPEC"
)
spec = ast.literal_eval(node.value)
expected = "263b7ce4feae6fcbc34ff4aad593bb8bde7aa3e6469d6662ab8b5186c200b239"
actual = hashlib.sha256(
    json.dumps(spec, separators=(",", ":")).encode()
).hexdigest()
print(json.dumps({
    "feature_count": len(spec),
    "ordered_spec_sha256": actual,
    "matches_audit_contract": actual == expected,
}, sort_keys=True))
raise SystemExit(0 if len(spec) == 477 and actual == expected else 1)
PY
```

Do not restart trainers casually. AdamW and the AMP scaler are recreated on every
`train()` call, not only at process restart, so there is no ordinary cycle-to-cycle
optimizer/scaler continuity to preserve. A process restart additionally clears
the in-memory replay deque and GRU temporal buffers, then follows the configured
checkpoint-load/promotion path; that can change the effective prediction
authority. The scheduled pretrain unit includes auto-promote/auto-restart flags
and was failed at audit time.

### 5.4 Prediction and publication

Verify:

- required trainer/model/live-block fields;
- feature snapshot/tensor/checkpoint IDs;
- per-source `event_time`, `ingested_at`, `available_at`, derived `generated_at`,
  `feature_cutoff`, and the stage-specific ordering above;
- replay snapshot ready and actual write success;
- durable archive write success;
- prediction Redis write return;
- downstream lineage emitted only after success.

Known defect: the publisher copies the payload, mutates only that copy on archive/replay failure, and the caller ignores its boolean before publishing lineage from the original. Treat lineage as unproven unless the durable writes are independently verified.

### 5.5 Orchestrator and risk

The orchestrator’s `risk_decision_id` is provisional lineage. It is not an allow action.

For every candidate/fill being investigated, join on:

- prediction ID;
- orchestrator decision ID;
- exact risk decision ID;
- symbol/side/timeframe;
- model/checkpoint and feature snapshot IDs;
- `model_decision_time`, signal generated/available/expiry fields,
  `paper_admission_decision_time`, and `execution_time`;
- payload hashes where available.

Then require the matched risk action to be explicit allow. Current ordinary paper code does not reliably do this; a recorded `DENY` can coexist with a fill-allowed proposal.

### 5.6 Paper trade-management

Primary entrypoint: `v2.backend.app.cli.v2_trade_management_paper_loop`.

Do not judge it from the cycle summary alone. Inspect a candidate’s full path:

```text
prediction trust
→ orchestrator lineage
→ matched risk action
→ strategy/pre-trade/fee/A+/1m/temporal gates
→ tier and sizing
→ churn and portfolio freeze
→ preemptive admission
→ position transition
→ fill-write invariant
→ lifecycle reconciliation
→ accounting and PPO entry fields
```

Known current behaviors:

- supply bridge is marked temporarily disabled;
- confidence thresholds relax multiple gates;
- fee is omitted from the strict local conjunction;
- confidence ≥0.65 fast path skips later checks;
- one fee override raises `FrozenInstanceError`;
- risk `DENY` is not a universal ordinary-paper block.

Any paper performance window must identify and segregate rows created by those paths.

For cross-margin, authenticated mark/bracket evidence, adaptive stress,
cascade force-close, hedge queue expiry, and pair-close atomicity, use the
[paper cross-margin and adaptive-hedge authority contract](PAPER_CROSS_MARGIN_AND_HEDGE_AUTHORITY_CONTRACT.md).
In particular, Redis hedge-queue TTL is garbage collection only. Confirm each
directive's content hash, parent ID and generation, paper session, derived
`valid_until`, and a fresh synthesis-time mark; TTL presence is never proof
that a directive remains authorized.

### 5.7 Portfolio and guardian

Portfolio state is derived from valid paper state and market prices. Verify:

- duplicate portfolio publisher processes;
- source ledger/session IDs;
- exclusion of invalid admission lineage;
- price freshness;
- initial-capital source rather than fallback;
- equity/PnL reconciliation;
- artifact generated time and Redis TTL.

Guardian output combines disk and Redis evidence. A stale disk artifact can disagree with current Redis state. Trace every blocker to its source artifact and generated time.

## 6. Backend, frontend and mobile

### 6.1 Backend

Effective deployment is four Uvicorn workers from mutable `v2/backend`, not the old release symlink. Before a backend restart capture:

```bash
systemctl --user show ai-bot-v2-public-website-backend.service \
  -p FragmentPath -p DropInPaths -p WorkingDirectory -p ExecStart \
  -p MainPID -p ActiveEnterTimestamp --no-pager
git rev-parse HEAD
git status --short --untracked-files=all
```

A restart can load dirty source. Four workers also mean:

- local JSON locks are not cross-process;
- in-memory metrics/history are fragmented;
- module globals/caches exist per worker;
- mixed import namespaces can duplicate state within a process.

### 6.2 API/auth

Do not infer auth from OpenAPI; it declares security on zero operations. Inspect route dependencies and actual middleware. Nine middleware layers are pass-through. Some API operations mutate paper/admin state or launch subprocesses.

Auth health:

```bash
curl --fail --connect-timeout 3 --max-time 10 --silent --show-error \
  http://127.0.0.1:8000/api/auth/health | python3 -m json.tool
```

At audit time auth was local-file/non-production, durable stores and MFA were not ready, and token/cookie behavior was development-oriented. Never include a login password in documentation. Tighten local file modes and rotate/migrate credentials only through an approved security change.

### 6.3 Frontend

Vite preview serves ignored `v2/frontend/dist`; source edits have no effect until a controlled build. The backend can also serve the same dist. Before deployment compare:

```bash
stat -c '%y %s %n' v2/frontend/dist/index.html v2/frontend/src/main.tsx v2/frontend/src/router.tsx
find v2/frontend/src -type f -newer v2/frontend/dist/index.html | wc -l
npm --prefix v2/frontend ls --depth=0
```

The last command currently fails because dependencies are incomplete; do not treat a failed build as a runtime outage without preserving the existing dist.

Runtime public assets require explicit build inclusion because ordinary public-directory copying is disabled.

### 6.4 Mobile/watch/CLI

Swift targets duplicate endpoint/client/model contracts. A backend schema change requires:

1. atlas lookup for the API path and field;
2. TypeScript client/reference review;
3. both Swift API/model definition reviews;
4. decode tests with missing/additional/null fields;
5. backwards-compatible server rollout before client release.

## 7. Failure triage playbooks

### 7.1 A service is failed or restarting

1. Capture effective unit, drop-ins, result, PID, restart count and Git state.
2. Identify whether nonzero is deliberate policy output, path/env syntax, worker exception, dependency failure or OOM.
3. Read the unit’s configured output destination; user journal may be empty.
4. Check whether a supervisor will restart it automatically.
5. Determine whether starting it is mutating/destructive.
6. Reproduce only in isolated non-live state if possible.
7. Change one thing, run `systemd-analyze --user verify`, then restart only with approval.

Do not “fix” the orderbook rollover failure under this generic playbook.

### 7.2 Redis memory/eviction pressure

1. Record memory/persistence/stats and key count.
2. Determine whether evictions are already increasing.
3. Capture key-pattern counts and memory sampling without dumping values.
4. Identify TTL/no-TTL producers in the atlas.
5. Protect paper/auth/risk/lineage evidence before any pruning.
6. Obtain approval for export/backup and for any maxmemory/retention change.
7. Validate restore before deleting.

Increasing memory or deleting keys without finding unbounded producers only delays recurrence.

### 7.3 Feature/prediction becomes stale

Trace upstream, do not restart everything:

```text
provider heartbeat/key
→ final candle/availability
→ feature worker heartbeat/latest/archive
→ tensor eligibility/rejection
→ trainer prediction/publication
→ all-timeframe/orchestrator consumption
```

If core OHLCV is current but an enrichment is stale/missing, the current pipeline may still mark aggregate freshness current. Inspect source-specific context.

### 7.4 Trainer reports no learning

Check, in order:

1. loaded row count;
2. clean trust classification and rejection reasons;
3. on-policy field completeness versus outcome-supervised mode;
4. batch/train/validation selection;
5. finite loss and optimizer steps;
6. parameter hash/delta;
7. checkpoint write/load;
8. prediction publication result;
9. feedback/replay label version and cost model;
10. holdout overlap.

A heartbeat and GPU utilization alone are insufficient.

### 7.5 Paper fills stop

Do not lower gates reflexively. Count rejection reasons at each stage and distinguish:

- no candidate supply;
- stale/dirty data;
- publication/archive failure;
- orchestrator arbitration;
- risk deny;
- local strategy/pre-trade/A+/temporal gates;
- tier/sizing/churn/freeze;
- invalid position transition;
- lifecycle/accounting quarantine;
- runtime exception such as frozen fee mutation.

Gate relaxation changes the research policy and requires explicit approval and tests.

### 7.6 Paper fills occur despite risk deny

This is a known defect. Preserve:

- exact prediction/orchestrator/risk/fill IDs and payload hashes;
- risk action and generated time;
- local gate result and override markers;
- admission tier/path;
- fast-path marker;
- position/lifecycle/accounting records;
- whether PPO entry fields exist.

Quarantine the row from performance/training evidence. Do not rewrite/delete history.

### 7.7 Website is wrong but workers look healthy

Trace:

```text
primary Redis/file state
→ backend route/resource-plane payload
→ public runtime JSON generated time
→ explicit Vite build copy/prune
→ dist artifact
→ Vite/backend static serving
→ browser cache/client decode
```

Remember that source can be newer than dist and remote tunnel routing is provider-side.

## 8. Restart and deployment change protocol

There is no trustworthy global “restart all” procedure. For a single non-live service:

### Before

- explicit scope/approval;
- Git HEAD, dirty-state and in-scope content-fingerprint capture;
- effective unit/drop-ins and environment-key names (not values);
- authoritative state and last-good artifact/checkpoint IDs;
- consumer list/change-impact review;
- rollback command/path;
- proof the service is non-destructive and not a live submitter;
- one-cycle acceptance criteria.

### Validate definition

```bash
systemd-analyze --user verify /home/wali/.config/systemd/user/SERVICE.service
```

For a timer, verify both service and timer. Warnings about paths with spaces, bad URL escapes, wrong sections and unknown escapes are material.

### Restart only after approval

```bash
systemctl --user restart SERVICE.service
systemctl --user show SERVICE.service \
  -p ActiveState -p SubState -p Result -p MainPID -p NRestarts --no-pager
```

Then verify primary outputs and downstream consumers for a complete cycle. Do not use this protocol for live transport, order, destructive retention, trainer promotion, paper/risk policy or multi-service restarts without a dedicated approved plan.

## 9. Backup and recovery requirements

The current system has no proven full recovery. Before claiming backup readiness, capture and restore-test:

- Redis consistent snapshot/export, config, key/TTL schema and version;
- model NPZ blobs, manifests, architecture/schema and checksums;
- replay/archive blobs, indexes, manifest/tombstones and label versions;
- paper lifecycle/ledger/closed trades/portfolio source state;
- auth users/revocations with protected permissions;
- SQLite main DB plus WAL/SHM using SQLite backup/checkpoint semantics;
- installed unit files/drop-ins and enable/mask/link state;
- frontend dist hash and exact source/dependency build provenance;
- Cloudflare routing export and newly rotated credential reference;
- OS/Python/Node/Swift/CUDA/Redis package versions;
- operator/runbook commit plus exact content hashes for dirty/untracked canonical
  docs and the validated `atlas/ATLAS_BUILD_MANIFEST.json`;
- secret-safe bundle manifest for effective units/drop-ins, dist, checkpoints and
  other ignored deployment artifacts whose bytes Git cannot identify.

Copying a live SQLite main file without its WAL is not a backup. A checkpoint directory is not a full-system backup. An RDB without a tested restore and post-snapshot loss bound is not disaster recovery.

## 10. Retention/change control

Current automatic mutation must be recorded even when the operator initiates no
cleanup. The six-hour persistent rollover timer repeatedly invokes a currently
broken service whose source would delete oldest replay directories until the
tree is at most 100 GiB (`tools/orderbook_replay_rollover.py:10-12`, `:46-83`).
Merely fixing/reloading that service can let the already-active timer execute it.
The separate 15-minute non-dry-run janitor is already executing the mutation
surfaces listed in §4.5. Pausing, disabling or masking either timer is itself a
state change and requires approval; until then, preservation/holdout work must
account for the race and capture every trigger/result.

Before changing retention:

1. inventory all writers and readers;
2. classify raw replay, derived cache, audit evidence, current authority and reconstructible data;
3. reconcile 100 GiB and 300 GiB policies;
4. produce a dry-run deletion manifest with bytes/date/count;
5. protect manifest/checksum/index integrity;
6. confirm no holdout/training/paper investigation references the candidate data;
7. back up and restore-test;
8. obtain approval;
9. delete in bounded batches with free-space and service monitoring.

## 11. Change-impact checklist

For every code/config/unit/schema change:

- exact file/symbol/line and owner;
- why current behavior is wrong;
- callers/importers from `atlas/CHANGE_IMPACT_INDEX.json`;
- Redis readers/writers and TTLs;
- env/config consumers and safe default behavior;
- data fields and client decoders;
- API producers/consumers;
- timestamp/finality/dirty-sample consequences;
- strategy/PPO/MASA/risk/live-execution classification;
- position-state transition impact;
- tests using isolated state;
- deployment/drop-in/import-namespace impact;
- rollback and evidence preservation;
- atlas regeneration and doc update.

## 12. Incident severity

| Severity | Examples | Immediate stance |
|---|---|---|
| SEV-0 | active unauthorized real order/mutation, credential compromise | do not improvise: no single vetted repository-wide kill procedure was proven; immediately escalate to the authorized human operator/security incident owner, preserve evidence, and contain/rotate only under an approved scope-specific procedure |
| SEV-1 | invalid paper fills contaminating training, future leakage, Redis data loss/eviction, destructive retention activation | stop affected producer/consumer with approval, quarantine evidence, preserve state |
| SEV-2 | trainer/publisher outage, stale features, broken API/auth state, repeated crash loop | isolate component, prevent bad downstream data, restore last-good non-live state |
| SEV-3 | dashboard/report drift, optional provider outage, noncritical automation failure | record and repair without broad restarts |

Never use severity as permission to enable live behavior or make an unreviewed strategy/risk change.

The two discovered disarm tools are not interchangeable and do not constitute a
vetted repository-wide SEV-0 procedure. `v2_live_canary_kill_switch.py` writes only
the `v2:live_canary:*` namespace and its default arm expires after 86,400 seconds
(`v2/backend/app/cli/v2_live_canary_kill_switch.py:1-18`, `:86-102`;
`v2/backend/app/services/live_canary/execution_adapter.py:106`).
`v2_live_submit_disarm.py` can mutate broader live-gate, trader-execution and
transport state; it requires an explicit Redis URL, reason and `--apply`, and its
backups expire by default (`v2/backend/app/cli/v2_live_submit_disarm.py:128-197`,
`:200-217`). Before either is promoted into emergency guidance, an authorized
owner must identify every active caller/transport, approve exact stop/disarm
actions, define credential-containment and evidence-preservation steps, and test
post-action verification and escalation.

## 13. End-of-shift handoff

Record:

- time/timezone, Git start/end HEAD and in-scope start/end content fingerprints;
- dirty/untracked files separated into owned versus concurrent, with secret-safe
  hashes/bundle-manifest references for bytes not identified by HEAD;
- installed/running/failed service/timer counts;
- Redis memory, eviction and persistence state;
- disk state; every automatic janitor/rollover trigger, result, deletion count
  and bytes reclaimed; and any separate operator-initiated retention action;
- trainer authorities, checkpoint IDs/load state and clean-row metrics;
- feature/prediction/risk/paper/portfolio sample lineage;
- readiness blockers;
- incidents and quarantined sample IDs;
- exact commands run and exit status;
- files changed;
- approvals and next safe action.

The canonical issue list is `CURRENT_FINDINGS_AND_RISK_REGISTER.md`; exact source/contract impact is in `atlas/`; reconstruction requirements are in `REBUILD_BLUEPRINT.md`.
