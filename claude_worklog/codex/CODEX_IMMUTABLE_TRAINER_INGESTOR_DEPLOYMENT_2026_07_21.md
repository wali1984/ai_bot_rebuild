# Codex immutable trainer-observer and native-ingestor deployment — 2026-07-21

## Result

Deployment verdict: **GO for the two scoped paper/data services; NO-GO for
training activation**.

The exact code release is the pushed Git object:

- branch: `codex/pipeline-trust-refresh`
- commit: `0f9b5c93b75b11b2f21f70663b9cc1ba34413423`
- release worktree:
  `/home/wali/ai_bot_local_data/deployments/ai_bot_rebuild/0f9b5c93b75b11b2f21f70663b9cc1ba34413423`
- local and remote branch heads were equal when the release was created
- the release has no tracked or untracked changes

No exchange order, cancellation, leverage-setting, margin-setting, transfer,
or live-execution path was changed or activated. The native ingestor consumes
public/read-only market data and writes the V2 Redis namespace. The trainer
resident process remains an observation-only authenticated-sample waiting
process.

## Why an immutable release was required

The development workspace contains many unrelated Claude/operator changes.
Both original units used that moving workspace as `WorkingDirectory` and
`PYTHONPATH`; restarting them there could therefore load code that had not been
reviewed, committed, or tested as one coherent release.

The deployed units now have all of these controls:

1. `WorkingDirectory` and `PYTHONPATH` identify the full immutable SHA path.
2. `AI_BOT_CODE_SHA` records that exact SHA in the process environment.
3. `ExecStartPre` compares the release tree to that SHA and fails before Python
   starts if any tracked byte differs.
4. `ReadOnlyPaths` mounts the release read-only in the service mount namespace.
5. `-B`, `PYTHONDONTWRITEBYTECODE=1`, and a release-specific
   `PYTHONPYCACHEPREFIX` prevent adjacent ignored bytecode from becoming the
   runtime code source or being created by the service.
6. The existing shared virtual environment supplies dependencies only.
   Runtime inspection confirmed every loaded `v2.*` module resolves below the
   release path despite the virtual environment's editable path metadata.

The trainer's `--repo-root "/home/wali/Desktop/AI BOT REBUILD"` is deliberately
retained only because this waiting runtime validates and atomically replaces
one status file under `v2/runtime/`. The audited waiting runtime does not use
that argument for imports, configuration, models, checkpoints, or training
data. Its ledger and prospective trusted cost store are explicit absolute
paths under `/home/wali/ai_bot_local_data/v2_native_trainer`.

The ingestor receives an explicit absolute `--out` path so existing operator
consumers continue to see its status after `WorkingDirectory` moves to the
release. Dynamic symbol-universe data is intentionally read from the existing
operator payload in the main workspace; Python code is not.

## Installed reversible drop-ins

External deployment files, not repository secrets:

- `/home/wali/.config/systemd/user/ai-bot-v2-native-ingestors-live-loop.service.d/90-immutable-release.conf`
- `/home/wali/.config/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.service.d/90-immutable-release.conf`

The ingestor override resets `ExecStart` to:

```text
/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python3 -B -m v2.backend.app.cli.v2_native_ingestors_live_loop --loop --interval-seconds 60 --out /home/wali/Desktop/AI BOT REBUILD/v2/frontend/public/operator_runtime/v2_native_ingestors/live/latest/v2_native_ingestors_live_status.json
```

The trainer-observer override resets `ExecStart` to:

```text
/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python -B -m v2.backend.app.cli.v2_native_cuda_trainer_persistent_loop --mode waiting-for-authenticated-samples --repo-root /home/wali/Desktop/AI BOT REBUILD --ledger-path /home/wali/ai_bot_local_data/v2_native_trainer/durable_feature_snapshot_ledger.sqlite3 --trusted-cost-store-root /home/wali/ai_bot_local_data/v2_native_trainer/profiled_base_publisher_v1/profiled-training-enrichment-cas --interval-seconds 30 --max-rows 250000
```

## Post-restart evidence

### Native ingestor

- PID after restart: `2120727`
- start: `2026-07-21 11:24:28 EDT`
- state: `active/running`
- `NRestarts=0`
- CWD, `PYTHONPATH`, and `AI_BOT_CODE_SHA`: exact release SHA
- `/proc/2120727/mountinfo`: release mount is `ro,relatime`
- first completed cycle: `15:24:28Z` through `15:24:34Z`
- classification: `NATIVE_V2_PUBLIC_WEBSOCKET_CACHE_OK`
- Redis healthy: `true`
- symbols reported: `157`
- V2 keys written: `1,823`
- `trader_execution_enabled=false`
- `places_exchange_orders=false`
- `live_gate=blocked_human_only`

A post-restart Redis scan used the committed finality verifier against every
BTCUSDT, ETHUSDT, and SOLUSDT row for `1m`, `5m`, `15m`, `1h`, and `4h`:

- rows checked: `1,239`
- source: `binance_wss` for all `1,239`
- invalid causal-finality rows: `0`
- rows lacking explicit `source_receipt_authority=false`: `0`
- rows lacking explicit `trainer_authority=false`: `0`

The old stderr file contains disk-full warnings, but it was last modified on
2026-07-07. At deployment time the filesystem had approximately `634G` free;
those lines are historical, not a current fault.

### Authenticated-sample waiting observer

- PID after restart: `2121888`
- start: `2026-07-21 11:25:33 EDT`
- state: `active/running`
- `NRestarts=0`
- CWD, `PYTHONPATH`, and `AI_BOT_CODE_SHA`: exact release SHA
- `/proc/2121888/mountinfo`: release mount is `ro,relatime`
- independently observed second cycle: `2026-07-21T15:26:04.191245Z`
- later local observation: `2026-07-21T15:26:35.049508Z`
- probe succeeded: `true`
- ledger integrity verified: `true`
- scan complete: `true`
- integrity-verified records / append receipts: `2 / 2`
- strict training-eligible rows: `0`
- profiled child candidates: `0`
- trusted cost CAS: `NOT_YET_MATERIALIZED`

Every training, prediction, paper, live, checkpoint, model, runtime, and
automatic-transition authority remains false. This proves the resident process
is healthy; it does **not** prove the trainer is training.

## Remaining keystone blocker

The authenticated profiled-pair publisher is not installed/running as a user
service, its three distinct encrypted credential files are absent, and the
`profiled-training-enrichment-cas` has not materialized. A prior manually run
publisher process produced two authenticated quarantined base records using an
older resident image; it ended and produced no profiled children. Those base
records cannot be relabeled as profiled training rows.

Activation still requires:

1. the account-specific read-only Binance API key and secret bound to
   `trader-wajidali1984` (the available `ASJAD` environment pair is not a valid
   substitute);
2. an independent fingerprint HMAC credential unequal to either exchange
   credential;
3. a deployable external monotonic witness, or explicit continued quarantine
   while rollback resistance is unavailable;
4. an immutable publisher release/unit validation;
5. fresh profiled pairs that pass full cost-CAS authentication and the waiting
   observer's structural contract.

The host exposes TPM2, but user `wali` cannot access `/dev/tpmrm0` because it is
not in group `tss`; passwordless elevation and TPM2 command-line tools are not
available. Local HMAC/CAS state alone must not be described as rollback-proof.

## CoinAnk boundary

CoinAnk remains optional and unavailable to this trainer path when its payload
lacks `request_started_at_ms`. The active direct CoinAnk service is an old
resident process loading an ignored, materially changed runtime copy. It was
not restarted. Restarting it would load uncommitted code and is therefore
NO-GO until a tracked producer and immutable unit are established.

## Deterministic rollback

Deleting either override and restarting is **not** a provenance-safe rollback:
that would load the dirty development workspace. A rollback must first
materialize and validate another detached release, then replace only the exact
release path and SHA in the same override.

The deterministic parent is
`055dc96c8b615aa81151b864c4c95d7c5dce879f`; rolling back to it deliberately
removes the ingestor finality fix, so forward correction is preferred.

If a process fails repeatedly, stop it before the unit's five-restart/600-second
limit is exhausted, inspect status/log evidence, repair the immutable override,
then `daemon-reload`, `reset-failed`, and start it once.

## Commands used for this deployment slice

```text
git push origin codex/pipeline-trust-refresh
git ls-remote --heads origin codex/pipeline-trust-refresh
git worktree add --detach <release-path> 0f9b5c93b75b11b2f21f70663b9cc1ba34413423
PYTHONPATH=<release-path> <shared-venv-python> -m pytest -q v2/backend/tests/unit/cli/test_v2_native_ingestors_finality_contract.py
PYTHONPATH=<release-path> <shared-venv-python> -m py_compile <ingestor> <finality-test>
systemd-run --user --wait --pipe --collect --property=Type=oneshot --property=ReadOnlyPaths=<release-path> /usr/bin/findmnt -n -o TARGET,OPTIONS -T <release-path>
systemctl --user daemon-reload
systemd-analyze --user verify <native-ingestor-unit> <trainer-observer-unit>
systemctl --user restart ai-bot-v2-native-ingestors-live-loop.service
systemctl --user restart ai-bot-v2-native-cuda-trainer-persistent.service
systemctl --user show <unit> -p ActiveState -p SubState -p MainPID -p NRestarts -p ExecMainStartTimestamp -p WorkingDirectory -p ReadOnlyPaths
readlink -f /proc/<pid>/cwd
tr '\0' '\n' </proc/<pid>/environ
tr '\0' '\n' </proc/<pid>/cmdline
rg -F <release-path> /proc/<pid>/mountinfo
git -C <release-path> diff --quiet --exit-code <sha> --
jq -e <paper-only ingestor health contract> <ingestor-status-json>
jq -e <waiting-observer authority contract> <trainer-waiting-status-json>
redis-cli --raw GET <ohlcv-key>
```

`systemd-analyze verify` reported unrelated pre-existing syntax warnings in
other user units; neither scoped unit produced a verification error. Direct
`nsenter` mount inspection was denied by the host, so the same evidence was
obtained from `/proc/<pid>/mountinfo`; an independent review additionally used
`findmnt -N <pid>` successfully.
