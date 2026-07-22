# CoinAnk Active Producer Provenance Baseline — 2026-07-21

## Checkpoint identity

- Branch: `codex/liquidation-levels-bridge-remediation-20260721`
- Baseline commit: `a9ace78eb4`
- Parent: `31d9926daa`
- Behavioral changes in this commit: 0
- Service/provider/Redis calls: 0

## Why this baseline was required

The user-level systemd unit executes this path directly:

```text
/home/wali/Desktop/AI BOT REBUILD/v2/legacy_owned_runtime/ingest/live_coinank.py
```

That source was ignored by `.gitignore` and had zero commits at its path.
Consequently, changing it in place would have produced an uncommitted runtime
mutation that downstream validation could not reproduce.

Only the directly executed runtime was force-added. No other file under
`legacy_owned_runtime` was admitted. Its already-imported scheduler and unit
tests were recovered byte-for-byte from the explicit non-release preservation
commit `d61c2acdc2`.

## Evidence counts

- Active runtime files newly tracked: 1
- Scheduler implementation files recovered: 1
- Scheduler test files recovered: 1
- Total files in baseline commit: 3
- Total lines admitted: 4,315
- Scheduler tests: 17 passed, 0 failed
- Python modules compiled: 2
- Git commits previously containing active runtime path: 0
- Git commits containing exact scheduler bytes: 1 (`d61c2acdc2`)
- Provider calls: 0
- Redis reads/writes: 0
- Service mutations: 0
- Secret literals found by scoped scan: 0

## Exact byte identities

```text
d794b2258dcb02a4652f0e17137241d54f43f827b8a27f8230345d136d1f5c35  v2/legacy_owned_runtime/ingest/live_coinank.py
da4c4b10ab469984c83a6479e78d3433cabc1d8f223031d494149fd4e478a5f8  v2/backend/app/services/altdata/coinank_scheduler.py
5779a6fb9ae534a053192c24b15ad258769778a691933e2c22251e727f02884b  v2/backend/tests/unit/services/altdata/test_coinank_scheduler.py
```

The scheduler and test hashes match both the active working-tree copies and
commit `d61c2acdc2`. The runtime hash matches the exact file referenced by the
active user systemd unit at baseline capture time.

## Verification commands

```text
systemctl --user cat ai-bot-v2-coinank-live-direct.service
git log --all --oneline -- v2/legacy_owned_runtime/ingest/live_coinank.py
git log --all --oneline -- v2/backend/app/services/altdata/coinank_scheduler.py
sha256sum \
  v2/legacy_owned_runtime/ingest/live_coinank.py \
  v2/backend/app/services/altdata/coinank_scheduler.py \
  v2/backend/tests/unit/services/altdata/test_coinank_scheduler.py
PYTHONPATH="$PWD/v2/backend:$PWD" \
  '/home/wali/Desktop/AI BOT REBUILD/.venv/bin/pytest' -q \
  v2/backend/tests/unit/services/altdata/test_coinank_scheduler.py
'/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python' -m compileall -q \
  v2/backend/app/services/altdata/coinank_scheduler.py \
  v2/legacy_owned_runtime/ingest/live_coinank.py
```

Result: `17 passed in 0.15s`; compilation succeeded.

## Exceptional baseline note

The active 3,099-line runtime already contained trailing whitespace. It was
preserved byte-for-byte in this no-behavior-change baseline, so the initial
all-added diff reports those pre-existing lines. Subsequent behavior commits
are ordinary tracked diffs and must pass scoped `git diff --check`. No broad
formatting or refactor is authorized by this checkpoint.

## Next bounded change

The next commit may change only the request/response receipt path, Plan3 OI
coverage scheduling needed by the prospective liquidation surface, raw-header
debug redaction, and their tests. It must record request start after rate-gate
admission and before network I/O; record response observation after the
response; preserve exact parameters; reject incomplete clocks; and prove the
real producer payload passes the strict source adapter without using any
Plan4 map or heatmap endpoint.
