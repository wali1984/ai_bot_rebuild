# Phase 2E1.B — Safety Boundaries

The Phase 2E1.B implementation is a pure-domain layer.

The boundaries below are mechanical guarantees that the implementer
must preserve. The Codex review at gate 057 will check each one.

## Hard scope limits

Allowed write paths:
- `v2/backend/app/domain/trainer_parity/`
- `v2/backend/tests/unit/domain/trainer_parity/`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`

Forbidden write paths:
- `/home/wali/Desktop/AI BOT/` (legacy live bot — never touched).
- `legacy_reference/` (read only).
- Any `.env` file or secret file.
- `v2/backend/app/adapters/trainer/` (already Codex-passed for 2E1.A;
  Phase 2E1.B does not touch it).
- Any frontend path.

## Forbidden imports

The new modules under `v2/backend/app/domain/trainer_parity/` must not
import any of the following at runtime:

- `redis`, `aioredis`, `redis.asyncio`.
- `subprocess`, `os.system`, `os.popen`, `pty`.
- `socket`, `urllib`, `requests`, `httpx`, `aiohttp`.
- `torch`, `tensorflow`, `numpy.random`, `cuda*`.
- `legacy_reference.*` or any path-injected legacy module.
- `v2.backend.app.adapters.trainer.*` (the subprocess adapter — domain
  layer must not depend on adapters).
- `os.environ` reads.
- `time.time`, `datetime.now`, `datetime.utcnow` (timestamps come in as
  int parameters).

The Codex review must grep each module file for the forbidden names
above and report any hit as a hard fail.

## Forbidden runtime behaviors

The new modules must not:
- Open any file.
- Spawn any subprocess.
- Open any socket.
- Allocate any GPU memory.
- Construct any Redis client, even in unreachable code.
- Call any legacy bot entrypoint.
- Place, cancel, or simulate any exchange order.
- Read environment variables.
- Mutate any global state.

## Test isolation

Tests must:
- Not import `redis`, `subprocess`, or any network library.
- Not read environment variables.
- Not write to disk outside pytest's tmp_path (and ideally not at all).
- Not depend on the subprocess adapter from Phase 2E1.A.
- Not import legacy modules.

## Mode declarations

The Phase 2E1.B work is:
- Non-live.
- Non-Redis.
- Non-subprocess.
- Non-legacy-mutating.
- Non-deploying.
- Non-secret-bearing.

V2_MODE remains paper / read_only.

LIVE TRADING: BLOCKED.

## Codex stop conditions

Codex must hard-fail Phase 2E1.B if any of:
- Any forbidden import is found in the new modules.
- Any forbidden import is found in the new tests.
- Any new file is added outside the allowed paths.
- Any legacy file is modified.
- The public surface of `__init__.py` exports more than the eight
  spec names.
- Any test result is not pass/zero-warning.
- The implementation log fails to record the exact pytest summary
  line.
- Any timestamp call (`time.time()`, `datetime.now()`,
  `datetime.utcnow()`) is found in the new modules.

PHASE2E1B_TRAINER_PARITY_IMPL_SAFETY_BOUNDARIES_READY
