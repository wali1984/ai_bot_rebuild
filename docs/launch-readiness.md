# Launch Readiness Register

Generated: 2026-07-24T06:16:00Z

Scope: fresh publisher → trainer → decision → paper recovery audit

Stance: **NOT OPERATIONALLY READY; LIVE SAFELY BLOCKED**

## Binding verdict

The runtime does not pass the five recovery gates. Kline, mark-price, and raw
liquidation ingestion are current, the backend and frontend answer quickly,
and the live gate remains closed. The profiled publisher has not yet emitted a
new row, the active trainer lane is deliberately non-promotable, predictions
and signals are stale, and the paper loop has no current signals or intents.

Do not report an operational A/A+ result. Economic A+ is a separate, much
longer statistical goal and is not evaluated here.

## Authoritative inventory

### Repository

| item | observed state |
|---|---|
| branch | `codex/pipeline-trust-refresh` |
| HEAD | `0d876a760adbbef37f8f23e288e0eba7a9553967` |
| tracked worktree state | 96 modified tracked paths and 1 tracked deletion; preserved, not normalized by this recovery |
| untracked paths in main checkout | 0 |
| Git worktrees | 94 total: 48 deployment worktrees and 39 under `/tmp` |
| runtime topology | mixed immutable releases and services executing from the dirty main checkout |

The dirty tree predates this recovery. It remains a launch blocker for every
critical service that executes directly from the main checkout.

### Critical runtime pointers

| component | runtime code/release | state |
|---|---|---|
| Binance kline WSS | `82c7fbfb4441e4357b8adc17e0018a0d4c023d55` | active, fresh, clean immutable release |
| Binance mark-price WSS | `2f05742c48d09b6018381a99535703321c4be06e` | active and fresh; restart-resilience drop-in installed |
| universe coverage sync | `f22c201bff07fac80b8bfc1f3b306286c3ed33b1` | successful census-only run; `--no-backfill`; zero REST writes |
| profiled base publisher | `1f2de7cda4ddef7b5cfbaa6389cfb98f8df120e2` | active; tracked release clean, untracked `.venv` symlink present |
| commissioned trainer | `8f67d8fabf9f29ff3ab74a0cef536c9a9c06260c` | active, non-promotable local research only |
| paper loop | `6f5dd649b1a962c2f16b08b3beb7caa3bb375ba0` | active; one canonical writer |
| feature pipeline / snapshot builder | dirty main checkout | active but not release-isolated |
| Moralis / liquidation engines | dirty main checkout | active but not release-isolated |
| inference / orchestrator | dirty main checkout | active but not release-isolated |
| backend / frontend | dirty main checkout | active; HTTP 200 with millisecond-scale local probes |

The offline GPU trainer is intentionally held. The trainer bridge is masked.
No live execution service was enabled or changed.

### Installed controls retained

- Propagate-only producer admission: commit `644af55550`, trainer runtime
  `8f67d8fabf`. An absent upstream `trainer_consumable` claim remains absent;
  the archive does not infer it.
- Coverage sync `95-no-rest-backfill.conf`: census continues without inserting
  REST rows into WSS-only training windows.
- Mark-price `95-restart-resilience.conf`: restart backoff is installed and
  mark-price keys were current at inspection time.
- Bounded/direct Redis reads: retained provisionally; the broad source commit
  still requires subsystem isolation before it can be accepted as one unit.

Rejected/quarantined changes remain rejected: `94e0c81289`, release
`ed93c6bc94`, archive-derived admission claims, historical admission rewriting,
and broad commit `8770260496` as a single review unit.

## Five recovery gates

### 1. Ingestor gate — PARTIAL / FAIL

- Kline WSS: 159 symbols × 5 timeframes, seven connected chunks, fresh final
  events, zero observed kline process restarts, and no unfinished candle used
  as final.
- Mark price: fresh BTC/ETH observations with explicit event/availability/
  generation clocks. The seeder is active under restart backoff.
- Liquidation raw WSS: fresh real force-order events with `event_time`,
  `ingested_at`, `available_at`, `generated_at`, and `feature_cutoff`.
- Liquidation level engine: current and caught up, but 8,110 older events were
  quarantined for missing clock lineage; only 155/795 heatmap rows were current
  at inspection, and enhanced liquidation remained unconfigured.
- Moralis: transport/auth is ready, but the useful feature path is precisely
  blocked: heartbeat-only, no actual admitted payload, no `available_at`, no
  postcommit receipt, `provider_ready=false`, `feature_bridge_ready=false`, and
  policy isolation active.

### 2. Publisher gate — FAIL

The 06:14 UTC completed cycle selected 16 and published 0. Failures were the
strict WSS-only provenance gate or minimum contiguous-window coverage.

Direct bounded inspection of every eligible symbol found no symbol with both a
valid 71×5m and 34×1h decision window. Each 5m window still contained either
the 01:05 REST repair or the corresponding missing interval. This is expected
to roll out naturally, but an ETA is not recovery evidence. The gate remains
failed until a fresh completed cycle has `published_symbol_count > 0` and the
new archive append is verified.

No candle was relabeled, rewritten, or REST-backfilled during this recovery.

### 3. Trainer gate — FAIL

- The active `8f67d8f` process continuously builds authenticated fixed-observation
  manifests. The latest inspected manifest had 250 samples, including 239
  finalized-label admissions and 11 unavailable labels.
- Its temporal contract was verified on a sample: feature cutoff precedes
  decision time; durable postcommit availability follows decision time; label
  availability follows decision time.
- The lane explicitly declares `runtime_wired=false`,
  `optimizer_admission_authorized=false`, `prediction_authorized=false`,
  `paper_trading_authorized=false`, and `local_research_non_promotable=true`.
- No current promotable CUDA step was proved. Historical local candidates are
  not current recovery evidence.
- Current producer snapshots publish `trainer_consumable=false`. The concrete
  blockers include `FEATURE_PUBLICATION_RECEIPT_REQUIRED`,
  `REQUIRED_MODEL_FEATURE_PIT_LEDGER_REQUIRED`, immutable OHLCV history receipt
  requirements, and missing required model values. These claims must not be
  flipped or inferred downstream.
- Champion/challenger remains blocked by
  `ACTION_SPECIFIC_COST_COVERAGE_INCOMPLETE` and `INSUFFICIENT_TRAIN_ROWS`.

The requested two real CUDA optimizer steps, CUDA tensor proof, increasing
train rows, and genuine upstream `trainer_consumable=true` are not established.

### 4. Decision gate — FAIL

- 1,285 predictions existed, but all were stale; none were current.
- 1,285 signal rows existed, but all were stale; `v2:signals:paper` was empty.
- Inference processed the universe but emitted zero predictions because the
  market-state trust gate rejected all symbols and the active checkpoint path
  reported `CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED`.
- The outer `/api/v2/signals/current` wrapper was fresh while its embedded
  signal was stale. The inner evidence is authoritative.
- No matching fresh prediction/orchestrator/risk identity chain exists.

Checkpoint promotion or selection was not attempted: it requires an explicit
operator decision and would change model/decision behavior.

### 5. Paper gate — FAIL

- The loop is fresh and completes roughly every minute, but its current
  classification is `NO_PAPER_SIGNALS_PRESENT` with zero signals, intents,
  accepted positions, and open positions.
- Exactly one canonical writer (PID 759182 at inspection) holds the canonical
  writer lock; duplicate writer count is zero.
- The zero-position margin identity passes, with unique canonical identities
  and no negative free margin. No current fill exists on which to prove
  notional and leverage identities.
- Historical state is not recovery proof: 92 closed trades, realized P&L
  `-14.405279486563265`, 25 trainer-consumable feedback rows and 67 quarantined
  rows.
- Two successful fresh signal/fill cycles were not demonstrated.

## Live safety

The current gate remains `blocked_human_only`:

- `live_trading_enabled=false`
- `trader_execution_enabled=false`
- `order_transport_submit_enabled=false`
- empty live and execution symbol sets
- `places_real_order=false`
- no order submission, leverage change, margin-mode change, or exchange
  mutation was performed

The Redis live-state timestamp is old, but fresh API wrappers preserve the
block. Stale enable-history rows are not current enablement evidence.

## Scoped repair performed

The only operational mutation was a systemd drop-in for
`ai-bot-v2-trainer-fail-closed-watchdog.service`. The base unit's unquoted path
with spaces was parsed as `/home/wali/Desktop/AI`, producing `203/EXEC`.

The override clears `ExecStart` and invokes the existing paper-only watchdog
through `bash -lc` with both paths quoted. After `daemon-reload`, the oneshot
completed with status 0 and logged:

```text
watchdog: healthy (LOCAL_PROFILED_RESEARCH_CYCLE_RUNNING); no action
```

It did not restart the trainer or alter Redis, model, strategy, risk, paper, or
live behavior.

## Test and runtime evidence

- watchdog unit tests: **3 passed**
- propagate-only archive tests from the `8f67d8f` release: **10 passed**
- coverage-sync tests from the `f22c201` release: **81 passed**
- mark-price seeder tests from the `2f05742` release: **4 passed**
- systemd unit verification: repaired watchdog has a valid effective
  `ExecStart`; unrelated pre-existing warnings were reported for other units
- repaired watchdog runtime: status 0/success
- independent read-only review: **recovery rejected as incomplete**; the
  reviewer independently failed publisher, trainer, decision, and paper gates

## Change inventory

Created outside the repository:

- `/home/wali/.config/systemd/user/ai-bot-v2-trainer-fail-closed-watchdog.service.d/90-exec-path-with-spaces.conf`

Updated in the repository:

- `docs/launch-readiness.md`

The independent reviewer also created two temporary HTTP probe bodies under
`/tmp` and disclosed that deviation. No source, release, Redis, or branch state
was changed by the reviewer.

## Command register

The recovery used read-only inventory commands plus the one declared systemd
repair. Command families and exact targets were:

```bash
sed -n ... /home/wali/.codex/attachments/.../pasted-text.txt
date -Is
git branch --show-current
git rev-parse HEAD
git status --short
git status --porcelain=v1
git worktree list --porcelain
git log ...
git show ... 644af55550
git -C IMMUTABLE_RELEASE rev-parse HEAD
git -C IMMUTABLE_RELEASE status --porcelain=v1
rg / rg --files / sed / find / stat / ls / readlink against named source, test, status, release, and unit paths
systemctl --user list-units --all
systemctl --user list-unit-files
systemctl --user --failed
systemctl --user show CRITICAL_UNIT -p ...
systemctl --user cat CRITICAL_UNIT
systemctl --user status CRITICAL_UNIT --no-pager -l
journalctl --user -u CRITICAL_UNIT ...
ps -eo ...
pgrep -af ...
ss -ltnp
lsof /run/user/1000/ai-bot-v2-trade-management-paper-loop/writer.lock
nvidia-smi --query-compute-apps=...
nvidia-smi --query-gpu=...
redis-cli PING
redis-cli GET KNOWN_V2_KEY
curl LOCAL_BACKEND_OR_FRONTEND_ENDPOINT
python3 read-only JSON/Redis/SQLite summaries shown in this report
systemctl --user daemon-reload
systemd-analyze --user verify ai-bot-v2-trainer-fail-closed-watchdog.service
systemctl --user start ai-bot-v2-trainer-fail-closed-watchdog.service
.venv/bin/python3 -m pytest -q v2/backend/tests/unit/tools/test_trainer_fail_closed_watchdog.py
env PYTHONPATH=8F67_RELEASE .venv/bin/python3 -P -B -m pytest -q -o cache_dir=/tmp/codex-pytest-cache-8f67 ARCHIVE_TEST
F22C201_RELEASE/.venv/bin/python3 -P -B -m pytest -q COVERAGE_SYNC_TEST
2F05742_RELEASE/.venv/bin/python3 -P -B -m pytest -q MARK_PRICE_TEST
```

One attempted archive-test command referenced a nonexistent release-local
`.venv/bin/python3`; it failed before collecting tests and was rerun with the
shared environment plus the immutable release on `PYTHONPATH`.

## Acceptance rule

Do not close recovery until a new independent read-only review sees all five
gates pass from fresh evidence. In particular, do not substitute service
activity, CUDA availability, an outer fresh wrapper, historical trades, or a
forecasted recovery time for the required runtime outputs.
