# V2 Continuous Remediation Governor State-Binding Fix Report

GO/NO-GO: `V2_CONTINUOUS_LEGACY_LOG_TO_REBUILD_REMEDIATION_READY`

This packet does NOT approve live, canary, leverage/margin, exchange
mutation, legacy shutdown, or Redis trim.

## What was broken

`claude_worklog/tools/codex_continuous_remediation_review_governor.py`
emitted `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_BLOCKED` with the
single fail-blocker `SOAK_GOVERNOR_NOT_READY`, even though its own runtime
checks reported `12/12` remediation processes running, V2 Redis namespaces
non-empty, soak minutes observed `>1h`, and `soak_1h_ready=true`.

Root cause was a binding bug at the boundary between two different
governors:

- The upstream Codex 15-minute "runtime soak and production equivalence"
  governor (`codex_runtime_soak_and_production_equivalence_governor.py`) is
  designed to gate the *shutdown* decision. It naturally returns BLOCKED
  while legacy still owns the production runtime, 6h soak is incomplete,
  or other shutdown blockers exist.
- The downstream Codex 5-minute "continuous remediation review" governor
  (the one whose status the operator was reading) was incorrectly requiring
  the upstream governor to be `_READY` before declaring the remediation
  loop healthy. That conflated *shutdown readiness* with
  *remediation-loop runtime health*.

## Fix applied

### 1. `codex_continuous_remediation_review_governor.py`

Replaced the upstream `_READY` requirement with raw runtime-health checks
derived from `soak_status.json` directly:

- `soak_status` must exist and be fresh (`<=600s` old) ->
  `SOAK_RUNTIME_STATUS_STALE_OR_MISSING`.
- `soak_status.all_v2_processes_uninterrupted == True` ->
  `SOAK_RUNTIME_PROCESS_INTERRUPTION_DETECTED`.
- `soak_status.v2_namespaces_never_empty == True` ->
  `SOAK_RUNTIME_V2_NAMESPACE_EMPTY_DETECTED`.
- `soak_status.soak_1h_ready == True` -> `SOAK_RUNTIME_1H_NOT_READY`.

The upstream shutdown-governor decision is preserved as an informational
field for the operator (`summary.soak_governor_shutdown_ready` and
`summary.soak_governor_shutdown_decision`) but is no longer a fail blocker.

Edited locations (current file lines):
- [claude_worklog/tools/codex_continuous_remediation_review_governor.py:384-397](claude_worklog/tools/codex_continuous_remediation_review_governor.py#L384-L397)
- [claude_worklog/tools/codex_continuous_remediation_review_governor.py:444-454](claude_worklog/tools/codex_continuous_remediation_review_governor.py#L444-L454)
- [claude_worklog/tools/codex_continuous_remediation_review_governor.py:495-499](claude_worklog/tools/codex_continuous_remediation_review_governor.py#L495-L499) (markdown render)

### 2. `v2_continuous_legacy_log_to_rebuild_remediation.py`

Bumped status schema to `v2_continuous_legacy_log_remediation_status_v2`
and added the required top-level fields the operator dashboard reads:

- `go_no_go` (self-declared READY/BLOCKED — does NOT imply live/shutdown)
- `self_fail_blockers`
- `continuous_remediation_running` (self pgrep)
- `legacy_log_observer_running` (pgrep)
- `soak_runtime_active` (raw `soak_status` health)
- `soak_governor_shutdown_ready` and `soak_governor_shutdown_decision`
  (informational only; remains BLOCKED while shutdown gates open)
- `production_equivalence_gaps_open`
- `remediation_tasks_created_count`
- `duplicate_task_suppression_count` (count of pairs whose Claude task
  already existed and were preserved-with-status — fulfills PHASE 3
  "no duplicate task per cycle" requirement)

GAP_MATRIX also gained `production_equivalence_gaps_open`.

Edited locations:
- [claude_worklog/tools/v2_continuous_legacy_log_to_rebuild_remediation.py:1-30](claude_worklog/tools/v2_continuous_legacy_log_to_rebuild_remediation.py#L1-L30) (imports + helpers)
- [claude_worklog/tools/v2_continuous_legacy_log_to_rebuild_remediation.py:268-360](claude_worklog/tools/v2_continuous_legacy_log_to_rebuild_remediation.py#L268-L360) (run_once body)

### 3. Monitor Center frontend

Extended `ContinuousRemediationPayload` TypeScript interface and replaced
the four existing remediation cards with eight that now surface:

- Continuous remediation loop: RUNNING/NOT_RUNNING + self GO/NO-GO
- Legacy log observer: RUNNING/NOT_RUNNING
- Soak runtime: ACTIVE/INACTIVE with minutes + 1h/6h flags
- Shutdown governor (informational): READY/NOT_READY + raw decision
- Production-equivalence gaps open
- Tasks created (this cycle) + duplicate-suppressed
- Task pairs total
- Remediation safety (live_gate + approves_* flags)

The frontend no longer surfaces "SOAK_GOVERNOR_NOT_READY" terminology as a
blocker for the remediation loop.

Edited location:
- [v2/frontend/src/pages/monitor-center/index.tsx:118-152](v2/frontend/src/pages/monitor-center/index.tsx#L118-L152) (interface)
- [v2/frontend/src/pages/monitor-center/index.tsx:331-385](v2/frontend/src/pages/monitor-center/index.tsx#L331-L385) (cards)

## Production-equivalence gaps remain visible

PHASE 3 explicitly required that production-equivalence gaps NOT be
hidden. Current public gap matrix shows:

- `production_equivalence_gaps_open = 3`
- gap classification counts: `BLOCKS_PRODUCTION_EQUIVALENCE=3`,
  `OPERATOR_DECISION_REQUIRED=3`, `NO_ACTION_REQUIRED_SAFE_BLOCK=3`,
  `CLAUDE_FIX_IN_FLIGHT=1`.

The checkpoint-weight blocker remains an `OPERATOR_DECISION_REQUIRED` /
`BLOCKS_PRODUCTION_EQUIVALENCE` row, properly routed to operator. Tasks
are NOT recreated each cycle — `duplicate_task_suppression_count=6` and
`remediation_tasks_created_count=1` after the regeneration run.

## Verification (raw)

- `py_compile` on both edited tools -> OK.
- Frontend `tsc --noEmit` -> exit 0.
- `pytest v2/backend/tests/integration/cli/test_v2_legacy_log_intelligence_observer.py -q` -> `7 passed`.
- JSON validation of all 5 emitted payloads -> all parse.
- Approval/live-gate guard scan -> 0 violations (live_gate=blocked_human_only, live_symbols=[], all approves_* false).
- Approval-token absence scan -> no live/canary/shutdown/redis_trim tokens.
- Exchange-mutation scan over new modules -> single `"change leverage or margin"` text in `forbidden_actions` guard list (not an action).
- Old-Redis-write scan -> 0 hits.
- Codex 5M governor self-run -> `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY` with empty `fail_blockers`.
- Continuous remediation tool self-run ->
  `go_no_go=V2_CONTINUOUS_LEGACY_LOG_TO_REBUILD_REMEDIATION_READY`,
  `self_fail_blockers=[]`,
  `continuous_remediation_running=true`,
  `legacy_log_observer_running=true`,
  `soak_runtime_active=true`,
  `soak_governor_shutdown_ready=false` (intentional, informational only),
  `soak_minutes_observed=142.83`,
  `soak_1h_ready=true`,
  `soak_6h_ready=false`.

## Safety invariants (raw)

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- no legacy mutation
- no legacy script executed
- no old Redis writes
- no exchange mutation
- shutdown still recommended `BLOCK_LEGACY_SHUTDOWN_PARITY_INCOMPLETE`

## What this report does NOT claim

- Not live-ready.
- Not canary-ready.
- Not legacy-shutdown-ready.
- Not Redis-trim-ready.
- Does not declare 6h soak complete.
- Does not approve the checkpoint-weight blocker.
- Does not modify legacy in any way.
- Does not execute legacy monitor scripts.
