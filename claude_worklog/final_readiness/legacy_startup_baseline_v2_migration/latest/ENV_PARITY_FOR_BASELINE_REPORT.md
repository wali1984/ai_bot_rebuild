# ENV_PARITY_FOR_BASELINE_REPORT — Phase E

Inventory-only audit. **No packages installed in this turn.** Inventory results in [env_parity_for_baseline.json](env_parity_for_baseline.json).

## Py3 interpreters available

- V2 venv: `.venv/bin/python3` — version 3.12.3
- system: `/usr/bin/python3` — 3.12.3
- legacy venv: `BASE_DIR/venv/bin/python3` if present; inspected read-only only

V2 runs on `.venv/bin/python3` (requires-python ">=3.11"). Legacy uses its own venv activated in PHASE 3 of the startup script. The V2 control plane will not touch the legacy venv.

## External package profile (from Phase D closure)

The closure scan identified 11 external modules. Detailed counts in [env_parity_for_baseline.json](env_parity_for_baseline.json).

- `redis` (19 files) — already in V2 pyproject; V2 uses it read-only against legacy keys.
- `requests`, `psutil`, `websockets`, `aiohttp`, `numpy` — install per-port under operator approval.
- `binance`, `ccxt` — install with audit; wrap read-only only in V2.
- `torch`, `stable_baselines3` — **deferred** to the trainer-bridge port task; do not install in V2 venv until then.
- `pynvml` — optional monitoring telemetry.
- `python-dotenv`, `urllib3` — V2 does not need.

## Rules

- `.venv/bin/python3` and `.venv/bin/pytest` are the only V2 invocation paths.
- No installs in this phase. Each port records its own installs in its worker report under operator approval.
- Legacy venv is read-only — no V2 writes there.
- A port that cannot install a required package classifies itself `V2_ENV_BLOCKED_MISSING_DEPENDENCY`.

## CUDA / GPU

- `nvidia-smi` available — already used by the legacy startup script Phase 0.
- `torch.cuda.is_available()` will be verified by the trainer-bridge port at port time.

## Frontend

Already alive: `npm run dev` pid 14711 (V2 frontend vite). No frontend dependency changes in this phase.

## Forbidden during Phase E

- No installs into the legacy venv.
- No installs into V2 venv in this phase.
- No edits to `requirements*.txt` in the V2 root.
