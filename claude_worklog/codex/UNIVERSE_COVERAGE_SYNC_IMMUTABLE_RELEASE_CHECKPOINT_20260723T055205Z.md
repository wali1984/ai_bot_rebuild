# Universe Coverage-Sync Immutable Release Checkpoint — 2026-07-23T05:52:05Z

## Immutable checkpoint

- Branch: `codex/strategy-receipt-promotion-20260723`
- Source commit: `f22c201bff07fac80b8bfc1f3b306286c3ed33b1`
- Source push divergence before deployment: `0 ahead / 0 behind`
- Immutable release root:
  `/home/wali/ai_bot_local_data/deployments/ai_bot_rebuild/f22c201bff07fac80b8bfc1f3b306286c3ed33b1`
- Service result: **success**, exit status **0**
- Timer state: **active/waiting**, next run at
  `2026-07-23 02:06:08 EDT`
- Known defects in this family: **0**

## Scoped change

The periodic universe-coverage worker can now write its operator status outside
an immutable release through one validated target:

- CLI: `--status-file=/absolute/file/path`
- Environment fallback: `V2_UNIVERSE_COVERAGE_SYNC_STATUS_FILE`
- Precedence: CLI, then environment, then the existing repository-derived path
- Relative, empty-name, root-only, and NUL-bearing targets fail argument
  parsing before the worker opens Redis or performs provider work.

The existing status schema and compact-summary behavior are unchanged. The
change does not alter universe resolution, source clocks, candle finality,
coverage classification, REST budgeting, backfill admission, Redis keys,
trainer authority, strategy authority, or execution behavior.

## Deployment binding

The systemd override is external deployment state at:

`/home/wali/.config/systemd/user/ai-bot-v2-universe-coverage-sync.service.d/90-immutable-release.conf`

Its SHA-256 is
`10f223d1db6a5b7dfc82aa0774b760b32f67496c2e40a51e3ffc6b5c78f57365`.
The deployed module SHA-256 is
`ed400a27f1acbc80a389ad827c90a7898065f142e5401bb5a6d08cd8dd799ad8`.

The oneshot now runs the exact release Python with `-P -B`, an explicit
immutable `PYTHONPATH`, release-scoped external pycache, and
`AI_BOT_CODE_SHA=f22c201bff07fac80b8bfc1f3b306286c3ed33b1`. Both the release and shared
Python environment are mounted read-only in the service. `ExecStartPre`
rejects a dirty release tree. The mutable status target is an explicit path in
the operator-runtime tree outside the release.

`systemd-analyze --user verify` returned success for this service and timer.
Its output listed pre-existing warnings from unrelated user units; it reported
no coverage-sync unit error.

## Runtime evidence

The manual post-deployment cycle ran from `01:51:08` through `01:51:14 EDT`:

- Exit status / result: **0 / success**
- Universe symbols classified: **159**
- Coverage families classified per symbol: **6**
- OHLCV source gaps found: **0**
- REST backfill attempts: **0**
- REST budget deferrals/exhaustion: **0 / false**
- Redis canonical backfill writes: **0**
- Backfill errors / unresolved pairs: **0 / 0**
- Current canonical receipt pointers before/after: **795 / 795**
- Status artifact updated at: `2026-07-23T05:51:14Z`
- Live gate: `blocked_human_only`
- Unit `V2_LIVE`: `0`
- Orders / leverage changes / margin changes: **0 / 0 / 0**

The zero `symbols_fully_covered` value is not hidden or relabeled. The cycle
reported these downstream admission states:

- OHLCV: **159 source-ready / consumer-unbound**
- Feature snapshots: **159 consumer-held**
- TA full: **68 partial / 91 consumer-held**
- Prices / order book / open interest: **159/159 `ok` each**

Those holds are the intended handoff to the strategy input receipt and
deterministic transform work. They are not repaired by inventing availability
or forcing a backfill, and they do not indicate a coverage-sync runtime error.

## Verification evidence

- Production files changed: **1**
- Test files changed: **1**
- Total source files committed: **2**
- Source diff: **79 insertions / 4 deletions**
- New focused test cases: **4**
- Focused tests, agent run: **81/81 passed**
- Focused tests, primary-agent independent run: **81/81 passed**
- Files compiled: **2/2**
- Files checked with fatal Ruff selectors: **2/2**
- Fatal lint findings / whitespace findings: **0 / 0**
- Immutable import/path checks: **1/1 passed**
- Release Git-tree integrity checks: **1/1 passed**
- Systemd service/timer verifications: **2/2 passed**
- Deployment cycles: **1/1 passed**
- Runtime symbols / family states checked: **159 / 954**
- Selected status leaf values checked: **68** (**67** non-null scalars and
  **1** explicit null)
- Routes inspected / screenshots captured / endpoints compared / product
  builds passed: **0 / 0 / 0 / 0**
- Runtime defects in this family: **0**
- Downstream held family states remaining: **3**

One pre-existing `pytest-asyncio` configuration deprecation warning appeared
in each focused test run. It is not caused by this slice and did not affect the
81 passing tests.

## Exact files in the source commit

1. `v2/backend/app/cli/v2_universe_coverage_sync.py`
2. `v2/backend/tests/unit/cli/test_v2_universe_coverage_sync.py`

## Deployment artifact

1. `/home/wali/.config/systemd/user/ai-bot-v2-universe-coverage-sync.service.d/90-immutable-release.conf`

## Commands executed

```text
rg/sed targeted reads of v2_universe_coverage_sync.py, its focused test module, and comparable CLI path options
PYTHONPATH=<worktree>:<backend> <venv-python> -m pytest -q v2/backend/tests/unit/cli/test_v2_universe_coverage_sync.py
<venv-python> -m py_compile <two changed Python files>
<venv-python> -m ruff check --select E9,F63,F7,F82 <two changed Python files>
git diff --check
git add -- <two exact source/test files>
git commit -m 'feat(ohlcv): externalize coverage sync status path'
git push origin codex/strategy-receipt-promotion-20260723
systemctl --user cat/show ai-bot-v2-universe-coverage-sync.service and .timer
jq <coverage status fields> v2_universe_coverage_sync_status.json
git worktree add --detach <immutable-release-root> f22c201bff07fac80b8bfc1f3b306286c3ed33b1
ln -s <shared-python-environment> <immutable-release-root>/.venv
find/chmod release directories and files to 0555/0444, restoring tracked executable files to 0555
git -C <immutable-release-root> diff --quiet --exit-code <source-commit> --
sha256sum <systemd override> <deployed coverage module>
systemd-analyze --user verify ai-bot-v2-universe-coverage-sync.service ai-bot-v2-universe-coverage-sync.timer
env PYTHONPATH=<immutable-release-root> <release-python> -P -B - <import/argument-path check>
systemctl --user daemon-reload
systemctl --user start ai-bot-v2-universe-coverage-sync.service
systemctl --user show/list-timers <coverage service/timer properties>
stat <external status artifact>
redis-cli --scan --pattern 'v2:market:ohlcv_closed:publication_receipt:latest:*'
redis-cli INFO memory
journalctl --user -u ai-bot-v2-universe-coverage-sync.service --since <cycle-start> --no-pager
```

The user-journal query returned no stored entries on this host; the systemd
result/status/exit timestamps and the external status artifact provide the
cycle evidence.

## Next gate

Implement and test the independent strategy input exact-read receipt, genuine
WSS/REST producer allow-list, and deterministic transform manifest. Do not
start the strategy publisher or convert the explicit downstream holds into
paper/live authority until that consumer contract is complete.
