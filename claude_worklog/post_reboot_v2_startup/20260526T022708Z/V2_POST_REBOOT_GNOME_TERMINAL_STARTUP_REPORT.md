# V2 Post-Reboot GNOME Terminal Startup Report

**Result: V2_POST_REBOOT_GNOME_TERMINAL_STARTUP_READY**

- Timestamp (UTC): `20260526T022708Z`
- Output directory: [claude_worklog/post_reboot_v2_startup/20260526T022708Z](.)
- Launcher: [claude_worklog/tools/start_v2_rebuild_gnome_terminals.sh](../../tools/start_v2_rebuild_gnome_terminals.sh)
- Per-terminal log directory: `claude_worklog/agent_supervisor/logs/v2_gnome_startup/20260526T022708Z/`
- Public payload: [operator_dashboard_payload.json](../../../v2/frontend/public/v2_post_reboot_gnome_terminal_startup/latest/operator_dashboard_payload.json)

## Summary

| Item | Value |
| --- | --- |
| V2 rebuild started after reboot | **YES** |
| V2 primary paper runtime active | **YES** (23 ai-bot-v2-* systemd services running) |
| Legacy runtime frozen | **YES** (0 legacy bot processes; legacy root preserved at 613 GB) |
| GNOME terminals launched | **22** (one per category) |
| Failed startup categories | **0** |
| Live trading enabled | **NO** |
| Real orders enabled | **NO** |
| Real orders attempted/submitted | **0 / 0** |
| Exchange mutation matches in startup logs | **0** |
| Approval-token matches in startup logs | **0** |
| Old-Redis writes detected | **0** (no `orchestrator:*`, `live_orders:*`, `exchange:order:*` keys) |
| live_symbols | `[]` |
| LIVE_GATE | `blocked_human_only` |

## Phase 1 - Preflight ([post_reboot_v2_startup_preflight.json](post_reboot_v2_startup_preflight.json))

- repo_root_exists: true
- venv_exists: true (`.venv/bin/python3`)
- redis.reachable: true, dbsize: ~9k, v2:* keys at preflight: ~232
- gpu_visible: true (RTX 5080)
- gnome_terminal_available: true (`/usr/bin/gnome-terminal`, GNOME Terminal 3.52.0)
- legacy_runtime_processes_present_count: 0
- systemd v2 active service count at preflight: 23

## Phase 2 - Manifest ([v2_gnome_terminal_startup_manifest.json](v2_gnome_terminal_startup_manifest.json))

22 categories, 0 missing. Each entry includes terminal_title, command, working_directory,
log_path, expected_redis_keys, expected_public_payload, safety_env, restart_behavior,
paper_only=true.

Categories (in spawn order) and their mechanism:

1. redis_status_monitor - bash watch loop
2. market_runtime - journal tail `ai-bot-v2-paper-online-runtime.service`
3. feature_pipeline - journal tail `ai-bot-v2-feature-snapshot-builder.service`
4. technical_analysis - `python3 -m v2.backend.app.cli.v2_feature_pipeline_and_ta_worker --loop`
5. symbol_universe - journal tail `ai-bot-v2-symbol-universe-publisher.service`
6. trainer_prediction_publisher - journal tail `ai-bot-v2-trainer-bridge.service`
7. risk_decision_loop - `python3 -m v2.backend.app.cli.v2_risk_gateway_runtime_worker --once`
8. orchestrator_arbitration - journal tail `ai-bot-v2-orchestrator-arbitration-loop.service`
9. paper_trade_management - journal tail `ai-bot-v2-trade-management-paper-loop.service`
10. paper_ledger_paper_runtime - journal tail `ai-bot-v2-paper-shadow-observation.service`
11. position_history_tracker - journal tail `ai-bot-v2-position-history-persistent-tracker.service`
12. liquidation_wss_paper_shadow - journal tail `ai-bot-v2-liquidation-wss-paper-shadow.service`
13. replay_outcome_miner - journal tail `ai-bot-v2-post-hoc-replay-outcome-miner.service`
14. production_equivalence_comparator - `python3 -m v2.backend.app.cli.v2_production_equivalence_comparator --once`
15. report_center_indexer - journal tail `ai-bot-v2-report-center-indexer.service`
16. executive_command_center - journal tail `ai-bot-v2-executive-command-center.service`
17. no_manual_next_action_policy - journal tail `ai-bot-v2-autonomous-no-manual-next-task-policy.service`
18. spark_worker_pool - journal tail `ai-bot-v2-closed-loop-worker-pool.service`
19. claude_workers - combined journal tail for `ai-bot-v2-closed-loop-claude-worker@1..3.service`
20. codex_workers - combined journal tail for `ai-bot-v2-closed-loop-codex-worker@1..3.service`
21. event_watchers - journal tail `ai-bot-v2-final-operator-decision-event-watcher.service`
22. runtime_cutover_watchdog - journal tail `ai-bot-v2-automation-liveness-watchdog.service`

Every category whose systemd service is already running is shown as a journal tail so the
operator can see live output without double-starting the work. Categories that are timer-driven
(`--once`) are invoked in the terminal and held open via `sleep infinity` so output stays visible.

## Phase 3 - Launcher ([start_v2_rebuild_gnome_terminals.sh](../../tools/start_v2_rebuild_gnome_terminals.sh))

- Reads the manifest (defaults to most recent under `claude_worklog/post_reboot_v2_startup/*/`).
- Warms up `gnome-terminal-server` via D-Bus if needed.
- Per terminal: exports `PYTHONPATH`, plus the safety env documented below.
- Spawns each window with `--window` so each gets its own GNOME terminal window.
- Output of each terminal tees to a per-category log file under the timestamped log dir.
- After the inner command exits, the terminal stays open via `sleep infinity` (Ctrl+C to close).
- Idempotent: a re-run skips categories whose window title is already on screen.
- Pre-flight: aborts if any process under the legacy bot path is detected.

Safety env exported into every terminal:
- `PYTHONPATH=/home/wali/Desktop/AI BOT REBUILD`
- `LIVE_GATE=blocked_human_only`
- `LIVE_SYMBOLS='[]'`
- `V2_PAPER_ONLY=true`
- `DISABLE_LIVE_TRADING=true`

## Phase 4 - Startup ([v2_gnome_terminal_startup_status.json](v2_gnome_terminal_startup_status.json))

- launched_terminal_count: 22
- failed_categories: []
- missing_commands: []
- safety_env_confirmed: true
- All 22 categories visible at validation time (`xwininfo` window count: 22).

## Phase 5 - Runtime ([v2_post_reboot_primary_runtime_status.json](v2_post_reboot_primary_runtime_status.json))

V2 Redis evidence post-startup:

| Pattern | Count |
| --- | --- |
| v2:* | 212 |
| v2:prediction:* | 47 |
| v2:market:ohlcv:* | 37 |
| v2:features:latest:* | 33 |
| v2:technical_analysis:* | 25 |
| v2:paper:shadow_outcome:* | 2 |
| v2:liquidation:* | 0 (stream starts on first opt-in tick) |
| exchange:order:* | 0 |

Real-order safety: `real_order_attempted=false`, `real_order_submitted=false`,
`writes_exchange_orders=false`. LIVE_GATE remains `blocked_human_only` and `live_symbols=[]`.

Public payload freshness (seconds since last write at verification time):
- orchestrator payload: 3 s
- replay miner payload: 30 s
- report center payload: 34 s
- spark worker pool snapshot: ~25 h (timer cadence; not blocking)

## Phase 6 - Legacy Frozen ([legacy_post_reboot_frozen_status.json](legacy_post_reboot_frozen_status.json))

- legacy_root_exists: true (`/home/wali/Desktop/AI BOT`, ~613 GB)
- legacy_api_consuming_processes_count: 0
- legacy_redis_orchestrator_keys: 0 (pre-existing state preserved)
- legacy_redis_prediction_keys: 1 (preserved)
- redis_trim_or_flush_attempted_this_session: false
- The two `ai-bot-v2-*legacy*` services (`continuous-legacy-log-remediation`,
  `legacy-log-intelligence-observer`) are V2-side **read-only** observers of legacy
  logs; they do not start or restart the legacy bot.

## Phase 7 - Automation Resume ([post_reboot_automation_resume_status.json](post_reboot_automation_resume_status.json))

One-shot runs executed for: report center indexer, no-manual next-task policy, replay outcome miner,
production-equivalence comparator. Spark worker pool snapshot read from
`worker_pool_status.json`. All four CLI runs succeeded and emitted JSON output (captured under
`automation_resume/`).

## Phase 8 - Executive Payload ([operator_dashboard_payload.json](operator_dashboard_payload.json))

Public copy at
[v2/frontend/public/v2_post_reboot_gnome_terminal_startup/latest/operator_dashboard_payload.json](../../../v2/frontend/public/v2_post_reboot_gnome_terminal_startup/latest/operator_dashboard_payload.json).
Contains a plain-language `summary` block with the YES/NO answers required by the task,
plus the full preflight / manifest / startup / runtime / legacy_frozen / automation_resume /
safety blocks.

## Phase 9 - Validation

- All 8 JSON artifacts parse OK.
- All touched py3 builders compile clean.
- Launcher bash script lints clean.
- 22 V2 GNOME terminal windows verified visible.
- 23 V2 systemd services active.
- 0 matches for any exchange-mutation token in startup logs.
- 0 matches for any approval-token in startup logs.
- 0 keys under `orchestrator:*`, `live_orders:*`, or `exchange:order:*`.
- `live_symbols=[]`, `LIVE_GATE=blocked_human_only`, `V2_PAPER_ONLY=true`.

## Hard Constraints Verified

- No script under `/home/wali/Desktop/AI BOT` started (probed; 0 procs).
- Legacy not restarted.
- Live trading not enabled.
- Canary not enabled.
- No order placed, cancelled, or modified.
- No test-order endpoint called.
- Leverage unchanged. Margin mode unchanged.
- Old Redis untouched. No trim/flush/delete.
- V2 wrote only to `v2:*` and public V2 payloads.

## Next Action

- Automatic: existing V2 systemd timers continue (report center, replay miner, automation
  liveness, paper-shadow outcome observer, etc.); no operator action required.
- Operator-only: any operator may close any of the 22 GNOME terminals at will. No live
  approval is being requested. All live gates remain `blocked_human_only`.
