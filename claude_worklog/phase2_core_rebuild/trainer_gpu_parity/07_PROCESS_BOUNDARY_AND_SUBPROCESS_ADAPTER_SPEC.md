```
# Process Boundary and Subprocess Adapter Specification

## Mandatory boundary

`CLAUDE.md` defines the protected runtime policy: V2 must not import the
legacy trainer modules into the FastAPI process unless dependency safety is
proven. Phase 2E does not attempt to prove dependency safety. Phase 2E
mandates the subprocess boundary unconditionally.

## Adapter contract

The adapter must:

- Spawn the legacy trainer runtime via:
  `LEGACY_TRAINER_PYTHON /path/to/script.py --mode read_only|status|export`.
- Resolve `LEGACY_TRAINER_PYTHON` and `LEGACY_BOT_ROOT` from the V2
  environment, never hard-coded.
- Capture stdout / stderr to V2-controlled paths under
  `claude_worklog/agent_supervisor/runtime/` or another V2-write-allowed
  prefix.
- Apply per-call timeouts.
- Never inherit V2 secrets (no env passthrough by default; explicit allowlist
  only).
- Never pass arguments that could trigger any of the action categories
  classified as forbidden under CLAUDE.md hard stops, including
  exchange-side state changes, leverage or margin-mode configuration
  changes, or a switch from non-live to live mode. The adapter argument
  vocabulary is restricted to `read_only`, `status`, and `export`.
- Log every invocation to the audit ledger with `task_id`, `pid`,
  `start_ts`, `end_ts`, `returncode`, and a digest of the captured output.

## Forbidden adapter behaviors

- No invocation of the legacy hybrid trainer module with any training-mode
  argument other than `read_only`, `status`, or `export`. The legacy
  command surface is enumerated read-only in
  `claude_worklog/phase2_core_rebuild/legacy_service_map/06_TRAINER_ORCHESTRATOR_TRADER_MAP.md`.
- No invocation of `python3 -m rl.orchestrator_worker`.
- No invocation of `trading/trader.py` or `trading/trader-asjad.py`.
- No invocation of any legacy script classified as exchange-write under
  `claude_worklog/phase2_core_rebuild/legacy_service_map/`.
- No invocation of any legacy script classified as leverage- or
  margin-config-write under the same legacy service map.
- No invocation of any Redis administration command-line tool.
- No invocation of any Redis-mutating side effect classified `unsafe_write`
  or `mutates_state` in
  `claude_worklog/trainer_atlas/HYBRID_TRAINER_REDIS_WRITE_CLASSIFICATION.md`,
  including but not limited to stream append, stream entry removal, and
  Redis namespace clear.

## Reference

- Legacy commands of record:
  `claude_worklog/phase2_core_rebuild/legacy_service_map/06_TRAINER_ORCHESTRATOR_TRADER_MAP.md`.
- Local-native runtime constraints: `CLAUDE.md` Local-Native First Runtime
  Constraints section.

PHASE2_TRAINER_GPU_PARITY_PROCESS_BOUNDARY_READY
```
