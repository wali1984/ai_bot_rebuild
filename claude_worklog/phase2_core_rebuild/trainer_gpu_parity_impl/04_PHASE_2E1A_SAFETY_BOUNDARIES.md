# Phase 2E1.A Safety Boundaries

Binding for supervisor tasks `053` and `054`. Each line is a hard
constraint; violation is a Codex hard fail.

## Read/write boundaries

- Allowed write prefixes for task `053`:
  - `v2/backend/app/adapters/trainer/`
  - `v2/backend/tests/unit/adapters/trainer/`
  - `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`
  - `claude_worklog/agent_supervisor/runs/053_trainer_parity_2e1a_implementation/`
- Allowed write prefixes for task `054`:
  - `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`
  - `claude_worklog/agent_supervisor/runs/054_trainer_parity_2e1a_codex_review/`

## Forbidden actions

- No modification of `legacy_reference/**`.
- No access to `/home/wali/Desktop/AI BOT`.
- No modification of any `.env` file.
- No modification of `v2/legacy_preserved/**` (including
  `v2/legacy_preserved/ingestors/live_coinank.py`).
- No modification of `legacy_reference/feature_pipeline.py`.
- No invocation of any Redis client at runtime.
- No invocation of any Redis administration tool.
- No append to or removal from any Redis stream.
- No clear of any Redis namespace.
- No restart of any legacy service.
- No exchange-side action.
- No leverage- or margin-config-write action.
- No switch from non-live to live operating mode.
- No deployment.
- No production migration.
- No emission of any secret value into Claude/Codex/Ollama transcripts.
- No actual spawn of the legacy trainer process during tests.
- No real subprocess call against `legacy_python_path` during tests
  (tests must use the injected `FakeRunner`).
- No network call from the adapter or its tests.
- No use of `eval`, `exec`, or `os.system` anywhere.
- No use of `shell=True` anywhere.

## Default-deny envelope

- The adapter `extra_argv` allowlist is empty for Phase 2E1.A. Any
  caller that supplies a non-empty `extra_argv` raises
  `TrainerSubprocessSafetyError`. The allowlist may only be expanded
  by a future planner cycle whose Codex review pass marker is recorded
  under `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`.

## Live trading status

`LIVE TRADING: BLOCKED` — unchanged by Phase 2E1.A. The default-deny
envelope on adapter argv ensures that even if a future caller imports
the adapter, no live training, exchange, or Redis-mutating mode value
can pass the validator.

PHASE2E1A_TRAINER_PARITY_SAFETY_BOUNDARIES_READY
