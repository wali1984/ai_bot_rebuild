# V2 Autonomous Full-Rebuild Self-Healing Controller — Ready Report

GO/NO-GO: `V2_AUTONOMOUS_FULL_REBUILD_SELF_HEALING_CONTROLLER_READY`

Purpose: a permanent automation layer that keeps every V2 rebuild lane
moving without operator hand-feeding. Read-only with respect to legacy,
Redis writes outside `v2:*`, exchange endpoints, approval tokens, and
shutdown / live state.

## Components installed

| Phase | Artifact | Path |
|---|---|---|
| 1 | Objective lock | [claude_worklog/final_readiness/v2_autonomous_full_rebuild_self_healing/latest/objective_lock.json](objective_lock.json) |
| 2 | Lane registry (19 lanes) | [lane_registry.json](lane_registry.json) |
| 3 | Issue classifier | [claude_worklog/tools/v2_autonomous_issue_classifier.py](../../../../tools/v2_autonomous_issue_classifier.py) |
| 4 | Pending-task watchdog | [claude_worklog/tools/v2_pending_task_watchdog.py](../../../../tools/v2_pending_task_watchdog.py) |
| 5 | Work selector | [claude_worklog/tools/v2_autonomous_work_selector.py](../../../../tools/v2_autonomous_work_selector.py) |
| 6 | Self-healing controller | [claude_worklog/tools/v2_autonomous_full_rebuild_self_healing_controller.py](../../../../tools/v2_autonomous_full_rebuild_self_healing_controller.py) |
| 8 | File-lock registry (7 locks) | [file_lock_registry.json](file_lock_registry.json) |
| 10 | systemd user units (controller + watchdog .service / .timer) | [claude_worklog/tools/systemd/](../../../../tools/systemd/) |
| 10 | Non-destructive installer (operator must opt-in) | [claude_worklog/tools/systemd/install_user_units.sh](../../../../tools/systemd/install_user_units.sh) |
| 11 | Live status JSON (operator + worklog mirrors) | [autonomous_full_rebuild_self_healing_status.json](autonomous_full_rebuild_self_healing_status.json), [public mirror](../../../../../v2/frontend/public/v2_autonomous_full_rebuild_self_healing/latest/operator_dashboard_payload.json) |

## Categories supported by the classifier (23)

`RUNTIME_PROCESS_DOWN`, `PAYLOAD_STALE`, `REDIS_NAMESPACE_EMPTY`,
`FRONTEND_TRUTH_MISMATCH`, `CODEX_REVIEW_FAIL`, `CLAUDE_TASK_STALLED`,
`CODEX_TASK_STALLED`, `EXACT_SOURCE_IMPLEMENTATION_GAP`,
`MISSING_RUNTIME_PAYLOAD_FIELD`, `SCHEMA_MISMATCH`, `TEST_FAILURE`,
`SECRET_LEAK_RISK`, `OLD_REDIS_WRITE_RISK`, `EXCHANGE_MUTATION_RISK`,
`LIVE_GATE_DRIFT`, `SYMBOL_UNIVERSE_MUTATION_RISK`,
`CHECKPOINT_ARTIFACT_REQUIRED`, `POLICY_ARCHITECTURE_GATE_REQUIRED`,
`EXTERNAL_SOURCE_REQUIRED`, `OPERATOR_DECISION_REQUIRED`,
`EVENT_DEPENDENT`, `POSITION_DEPENDENT`, `NO_AUTOMATABLE_WORK_REMAINING`.

Each emitted issue carries: source, detected_at, severity (P0/P1/P2/INFO),
exact evidence, exact remediation action, owner (CLAUDE / CODEX /
OPERATOR), `duplicate_key`, and an optional `task_descriptor` /
`codex_review_descriptor` pointer for when the issue is generated from a
supervisor task scan.

## Priority order used by the selector

1. safety drift (`LIVE_GATE_DRIFT`, `SYMBOL_UNIVERSE_MUTATION_RISK`,
   `OLD_REDIS_WRITE_RISK`, `EXCHANGE_MUTATION_RISK`, `SECRET_LEAK_RISK`)
2. runtime liveness (`RUNTIME_PROCESS_DOWN`, `REDIS_NAMESPACE_EMPTY`)
3. stale payloads (`PAYLOAD_STALE`)
4. failed Codex reviews (`CODEX_REVIEW_FAIL`)
5. pending/stalled exact-source tasks (`CLAUDE_TASK_STALLED`,
   `CODEX_TASK_STALLED`)
6. full-observation exact-source tasks
   (`EXACT_SOURCE_IMPLEMENTATION_GAP`, `MISSING_RUNTIME_PAYLOAD_FIELD`)
7. frontend truth (`FRONTEND_TRUTH_MISMATCH`)
8. schema / test (`SCHEMA_MISMATCH`, `TEST_FAILURE`)
9–11. operator / external / event / position gates — reported but never
auto-picked.

The selector explicitly refuses to pick: policy architecture,
checkpoint load, live, canary, shutdown acceptance, paid endpoints,
automatic Symbol Universe adoption, external source adoption without
operator decision. These categories surface in
`operator_owned_blockers` so the operator can decide.

When no automatable work remains, the selector emits
`no_automatable_work_remaining.json` and the controller's GO/NO-GO
stays `READY` with `status=NO_AUTOMATABLE_WORK_REMAINING`.

## First-cycle dry-run

Output: `selector_status=AUTOMATABLE_WORK_SELECTED`,
`automatable_issue_count=157`, `operator_owned_issue_count=7`,
top-priority candidate `RUNTIME_PROCESS_DOWN` (P1) for
`continuous_remediation_governor`. The controller annotates the plan
under `latest_action_plan.json`; it does NOT itself restart the
governor or run any destructive action — routing remains the
supervisor's / operator's responsibility.

## Live status snapshot

`autonomous_full_rebuild_self_healing_status.json` carries each cycle's:

- `controller`, `timestamp_utc`, `mode`, `dry_run`,
- `live_gate=blocked_human_only`, `live_symbols=[]`,
- `approves_live=false`, `approves_canary=false`,
  `approves_legacy_shutdown=false`, `approves_redis_trim=false`,
- `preflight` (objective-lock present, lane-registry present, file-lock
  registry present, queue remediated, queue Codex pass),
- `issue_summary`, `automatable_issue_count`,
  `operator_owned_issue_count`,
- `watchdog_summary` (pending/stale Claude + Codex counts, actions),
- `selector_status`, `selected_work`, `operator_owned_blockers`,
- `action_result` (annotate-only for now),
- `go_no_go`, `next_action`.

Mirrored to
`v2/frontend/public/v2_autonomous_full_rebuild_self_healing/latest/operator_dashboard_payload.json`
for Monitor Center.

## Codex review integration

Per the spec, the controller does not mark a lane complete until the
matching Codex PASS marker file exists with the expected GO/NO-GO token,
tests pass, safety scans pass, and the public payload has been
refreshed. On Codex FAIL, the classifier emits a `CODEX_REVIEW_FAIL`
issue with the fail-marker path so the controller can route a focused
remediation task; unrelated independent lanes can still advance if
their file locks do not conflict (see `file_lock_registry.json`).

## File lock / lane lock

7 locks defined (full-observation builder, policy architecture,
checkpoint files, symbol universe, alt-data providers, frontend monitor
center, live/canary safety). Policy architecture, checkpoint, and
live/canary locks carry the `blocked_by_operator_gate=true` flag.
Concurrent edits are only allowed when candidate file sets are
disjoint.

## Phase 10 — systemd units

Installed (not enabled) under
[claude_worklog/tools/systemd/](../../../../tools/systemd/):

- `ai-bot-v2-autonomous-full-rebuild-self-healing-controller.service`
  (oneshot, `--once`),
- `ai-bot-v2-autonomous-full-rebuild-self-healing-controller.timer`
  (every 5 min, accuracy 30 s),
- `ai-bot-v2-pending-task-watchdog.service` (oneshot, annotation-only),
- `ai-bot-v2-pending-task-watchdog.timer` (every 2 min, accuracy 15 s),
- `install_user_units.sh` — copies unit files into
  `~/.config/systemd/user/` and runs `systemctl --user daemon-reload`,
  but does NOT enable or start any timer. The operator must explicitly
  run `systemctl --user enable --now …` to switch on the cadence.

Existing services / governors / observers / comparators are not
touched.

## Phase 9 — Frontend operator truth

Operator dashboard payload mirrors include:
`controller running`, current selected work, pending / stalled
task counts, Codex failure counts, no-automatable-work reason when
applicable, `live_gate=blocked_human_only`, `live_symbols=[]`,
approval flags `false`, current observation dims (carried in the
lane registry's `full_observation_builder` lane).

## Safety scoreboard (this controller, this cycle)

- did_not_modify_legacy_bot
- did_not_stop_v2_runtime
- did_not_stop_continuous_remediation
- did_not_stop_legacy_log_observer
- did_not_stop_v2_vs_legacy_comparator
- did_not_stop_liquidation_wss_daemon
- did_not_stop_position_history_daemon
- did_not_write_old_redis
- did_not_call_exchange
- did_not_create_approval_marker
- did_not_create_shutdown_acceptance_file
- did_not_start_policy_architecture
- did_not_claim_checkpoint_compatibility
- did_not_deserialize_checkpoint_blobs
- did_not_expose_raw_api_keys
- did_not_auto_adopt_symbol_universe
- did_not_auto_adopt_external_sources
- live_gate=blocked_human_only
- live_symbols=[]

## Next operator step (manual)

```
bash claude_worklog/tools/systemd/install_user_units.sh
# then opt-in:
systemctl --user enable --now ai-bot-v2-pending-task-watchdog.timer
systemctl --user enable --now ai-bot-v2-autonomous-full-rebuild-self-healing-controller.timer
```

When the operator enables the timers, the controller will run every
5 minutes and the watchdog every 2 minutes. Until then, the controller
can still be driven manually:

```
python3 claude_worklog/tools/v2_autonomous_full_rebuild_self_healing_controller.py --once
python3 claude_worklog/tools/v2_autonomous_full_rebuild_self_healing_controller.py --status
python3 claude_worklog/tools/v2_autonomous_full_rebuild_self_healing_controller.py --loop \
    --loop-max-cycles 6 --loop-interval-seconds 300
```
