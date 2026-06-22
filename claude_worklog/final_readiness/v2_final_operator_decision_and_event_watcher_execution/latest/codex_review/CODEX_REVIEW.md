# Codex Review: V2 Final Operator Decision and Event Watcher Execution

GO/NO-GO: `V2_FINAL_OPERATOR_DECISION_EVENT_WATCHER_EXECUTION_CODEX_PASS`

This review covers the final operator-decision and event-watcher execution
layer only. It does not approve edge, canary, live trading, legacy shutdown,
Redis trim, exchange mutation, or any approval workflow.

## Findings

No blocking findings remain after scoped fixes during review.

## Fixes Applied During Review

- Added the final operator-decision/event-watcher execution generator:
  `claude_worklog/tools/v2_final_operator_decision_and_event_watcher_execution.py`.
- Registered the lane in the V2 report center.
- Added focused regression tests proving operator decisions are not
  auto-accepted, external-source checks expose names not values, and shutdown
  remains blocked when external/event blockers are unresolved.
- Refreshed the runtime-soak payload/comparator/governor after report-center
  re-index surfaced a fresh stale-payload regression. The runtime-soak lane is
  back to `CODEX_RUNTIME_SOAK_AND_PRODUCTION_EQUIVALENCE_GOVERNOR_READY`.
- Added the recurring automation cycle runner:
  `claude_worklog/tools/v2_final_operator_decision_event_watcher_cycle.py`.
- Installed and enabled the user timer
  `ai-bot-v2-final-operator-decision-event-watcher.timer`, which runs the
  safe recomputation cycle without stopping existing automation.
- External-source task seeding is now fail-closed: paired Spark implementation
  and Codex review tasks are seeded only if source env-var names are present
  and explicit free-tier/Codex-safe env-name markers are present. Raw values are
  not read or stored.

## Verified

- All six operator-required blockers appear in
  `final_operator_decision_center.json`:
  `full_observation_builder.operator_decision_families`,
  `checkpoint_promotion`, `legacy_shutdown.legacy_runtime_owner`,
  `legacy_shutdown.legacy_redis_keys_active`,
  `risk_caps_canary_hard_gates_unset`, and
  `capital_recovery_gate_unset`.
- Operator decisions are not auto-accepted:
  `operator_accepted_count=0`, `operator_selected_count=0`, and every
  `operator_selected_option=null`.
- No approval token or approval artifact is created.
- The external-source blocker is classified as
  `SOURCE_MISSING_KEY_OPERATOR_REQUIRED`. The status checks env var names only
  and reports `raw_values_read=false` and `raw_key_values_exposed=false`.
- Both event-dependent blockers have active watcher status rows:
  `full_observation_builder.event_dependent` and `paper_edge_not_proven`.
- Watchers do not fake completion:
  `event_watcher_count=2`, `event_watchers_completed=0`,
  `fake_completion_allowed=false`, and no watcher has
  `pass_condition_satisfied=true`.
- Final shutdown recommendation is an allowed conservative state:
  `BLOCK_LEGACY_SHUTDOWN_PRODUCTION_EQUIVALENCE_INCOMPLETE`.
- `SAFE_TO_SHUTDOWN` was not emitted:
  `shutdown_safe=false`, `paper_only_shutdown_decision_ready=false`,
  `live_ready=false`, and `canary_ready=false`.
- Report center exposes
  `v2_final_operator_decision_and_event_watcher_execution` as fresh and
  blocking live, shutdown, and production equivalence.
- Existing automation remains active: report-center, replay miner,
  worker-pool, burndown, Claude worker, and Codex worker systemd units returned
  `active`.
- The recurring cycle completed successfully under systemd:
  `V2_FINAL_OPERATOR_DECISION_EVENT_WATCHER_CYCLE_READY`.
- Each cycle refreshes `final_operator_decision_center.json`,
  `external_source_decision_execution_status.json`,
  `event_dependent_watcher_runtime_status.json`,
  `final_shutdown_recommendation.json`, and report-center state.
- The timer is enabled and active with a 120-second cadence. The oneshot
  service exits cleanly with `Result=success` and `ExecMainStatus=0`.
- A natural timer tick completed without manual start at
  `2026-05-25T05:14:53Z`, refreshed report center at the same timestamp, and
  kept `shutdown_safe=false` and `live_ready=false`.

## Safety

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- Scoped scans found no executable old-Redis write path, exchange mutation
  path, truthy approval, non-empty `live_symbols`, premature shutdown-safe
  state, or raw secret material in the reviewed scope.

## Verification

```text
PYTHONPATH=$PWD .venv/bin/python \
  -m v2.backend.app.cli.v2_production_payload_freshness_refresher --once

PYTHONPATH=$PWD .venv/bin/python \
  -m v2.backend.app.cli.v2_production_equivalence_comparator --once

PYTHONPATH=$PWD .venv/bin/python \
  claude_worklog/tools/codex_runtime_soak_and_production_equivalence_governor.py --once

PYTHONPATH=$PWD/claude_worklog/tools .venv/bin/python \
  claude_worklog/tools/v2_final_operator_decision_and_event_watcher_execution.py --json

python -m py_compile \
  claude_worklog/tools/v2_final_operator_decision_and_event_watcher_execution.py \
  claude_worklog/tools/v2_final_production_equivalence_blocker_resolution_sprint.py \
  v2/backend/app/services/report_center/report_registry.py

PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/unit/tools/closed_loop_execution/test_final_operator_decision_event_watcher_execution.py \
  v2/backend/tests/unit/services/report_center/test_report_center.py -q

jq empty \
  claude_worklog/final_readiness/v2_final_operator_decision_and_event_watcher_execution/latest/*.json \
  v2/frontend/public/v2_final_operator_decision_and_event_watcher_execution/latest/*.json

PYTHONPATH=$PWD .venv/bin/python \
  -m v2.backend.app.cli.v2_report_center_indexer --once --json

PYTHONPATH=$PWD/claude_worklog/tools:$PWD .venv/bin/python \
  claude_worklog/tools/v2_final_operator_decision_event_watcher_cycle.py --json

systemctl --user enable --now \
  ai-bot-v2-final-operator-decision-event-watcher.timer

systemctl --user start \
  ai-bot-v2-final-operator-decision-event-watcher.service
```

Results: runtime-soak refresh/governor passed, packet generation passed,
py_compile passed, focused tests passed `16/16`, JSON validation passed,
report-center re-index passed, direct cycle execution passed, timer install
passed, systemd oneshot execution passed, systemd activity checks passed, and
scoped safety scans passed.
