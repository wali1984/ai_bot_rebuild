# V2 Realtime Report Center — Website Ready Report

GO/NO-GO: `V2_REALTIME_REPORT_CENTER_WEBSITE_READY`

Generated: see [report_center_status.json](report_center_status.json) `generated_at`.

A website truth layer that aggregates every Claude / Codex / governor /
runtime report into one frontend page. Stale lanes show `MISSING_PAYLOAD`
and are never hidden. Live, canary, and legacy shutdown remain blocked.

## Artifacts (Phases 1–9)

| Phase | Artifact | Path |
|---|---|---|
| 1 | Report registry | [v2/backend/app/services/report_center/report_registry.py](../../../../../v2/backend/app/services/report_center/report_registry.py) |
| 1 | Indexer CLI | [v2/backend/app/cli/v2_report_center_indexer.py](../../../../../v2/backend/app/cli/v2_report_center_indexer.py) |
| 2 | 30 required lanes — all registered, missing lanes surface as `MISSING_PAYLOAD` | (LANES tuple in report_registry.py) |
| 3 | Safe-summary extractor + secret redaction | [v2/backend/app/services/report_center/safe_summary.py](../../../../../v2/backend/app/services/report_center/safe_summary.py) |
| 4 | Public payloads (6 files + per-lane safe summaries) | [v2/frontend/public/v2_report_center/latest/](../../../../../v2/frontend/public/v2_report_center/latest/) |
| 5 | Website page + components | [v2/frontend/src/pages/report-center/](../../../../../v2/frontend/src/pages/report-center/), [registry.ts](../../../../../v2/frontend/src/pages/registry.ts) |
| 6 | Polling refresh (15 s dashboard / 30 s index) via `usePollingQuery` | (in `index.tsx`) |
| 7 | systemd .service + .timer (every 60 s, not enabled) | [claude_worklog/systemd/user/](../../../../systemd/user/) + [install_report_center.sh](../../../../systemd/user/install_report_center.sh) |
| 8 | Focused pytest (13/13 passing) | [v2/backend/tests/unit/services/report_center/](../../../../../v2/backend/tests/unit/services/report_center/) |
| 9 | This GO_NO_GO + report | [GO_NO_GO.md](GO_NO_GO.md), this file |

## Lane registry (Phase 2)

All 30 required lanes are registered. Lanes whose worklog directory or
public payload does not yet exist still appear in the registry with
status `MISSING_PAYLOAD` and `stale=true`; they are never hidden.

Registered lanes: `executive_command_center`, `codex_executive_governor`,
`self_healing_controller`, `codex_self_healing_governor`,
`autonomous_production_equivalence_burndown`, `codex_autonomous_governor`,
`continuous_remediation_governor`, `runtime_soak_and_production_equivalence`,
`full_observation_builder`, `remaining_dim_execution_queue`,
`full_observation_latest_burndown`, `policy_architecture_shape_contract`,
`checkpoint_promotion`, `model_parity_sprint`, `liquidation_wss_daemon`,
`position_history_tracker`, `alt_data_provider_registry`, `nansen_client`,
`lunarcrush_client`, `alt_data_symbol_scoring`,
`alt_data_candidate_publisher`, `top10_dashboards`, `symbol_universe`,
`legacy_log_intelligence`, `v2_vs_legacy_comparator`, `live_canary_safety`,
`capital_recovery_gate`, `production_readiness_scorecard`,
`pending_task_watchdog`, `latest_codex_failures`.

Each entry carries: `report_id`, `title`, `lane`, `owner`, `source_type`,
`go_no_go`, `status`, `generated_at`, `freshness_seconds`, `stale`,
`codex_passed`, `blocks_live`, `blocks_shutdown`,
`blocks_production_equivalence`, `blocks_recovery`, `current_blockers`,
`next_action`, `public_payload_path`, `safe_report_path`,
`frontend_visible`, and the safety quartet
`live_gate / live_symbols / approves_live / approves_canary / approves_legacy_shutdown / approves_redis_trim`.

## Safe summaries (Phase 3)

`safe_summary.py` extracts:

- GO/NO-GO line (`V2_…_READY / _BLOCKED / _CODEX_PASS / _CODEX_FAIL / _REMEDIATED_READY / _PARTIAL_PROGRESS`),
- Known markdown sections only (`Decision`, `Current Blockers`,
  `Next Action`, `Safety`, `Validation`, `Summary`, `Non-Approval Items`)
  truncated to 1200 characters per section,
- Pruned JSON keys from a fixed allowlist;

and **redacts**:

- API keys / bearer tokens / passwords (case-insensitive),
- AWS access-key IDs (`AKIA…`, `ASIA…`),
- PEM private-key headers,
- 40+ char hex or base64 opaque blobs (likely credentials/hashes),
- `.local_secrets` path mentions,
- exchange credential phrasing (`binance_api_key=…`, etc.).

Verified at smoke time: 30 per-lane safe summaries written, **zero**
forbidden tokens (`AKIA`, `BEGIN RSA PRIVATE KEY`, `.local_secrets/`)
present in any frontend-public file.

## Public payloads (Phase 4)

Written each cycle under `v2/frontend/public/v2_report_center/latest/`:

- `report_index.json` — full lane entries.
- `report_summary.json` — slim per-lane summary view.
- `latest_blockers.json` — top-blockers excerpt.
- `latest_codex_failures.json` — entries with `codex_passed=false`.
- `latest_next_actions.json` — automatable + operator-required.
- `operator_dashboard_payload.json` — aggregator for the website page;
  includes `report_count`, `stale_report_count`, `fail_count`,
  `blocked_count`, `codex_pass_count`, `codex_fail_count`,
  `operator_decision_required_count`, `live_gate=blocked_human_only`,
  `live_symbols=[]`, `shutdown_blocked=true`, `live_blocked=true`,
  `production_equivalence_blocked=true`, `top_blockers`,
  `next_automatable_actions`, `next_operator_decisions`,
  `current_scorecard`, `current_autonomous_controller_state`,
  `current_pending_tasks`, `current_stalled_tasks`,
  `current_codex_failures`, plus `required_visible_text` and
  `honesty_invariants`.
- `safe_summaries/<lane>.json` — sanitized per-lane summary.

A worklog snapshot mirror is written to
[report_center_status.json](report_center_status.json).

## Website page (Phase 5)

[v2/frontend/src/pages/report-center/](../../../../../v2/frontend/src/pages/report-center/)
implements:

- `ReportCenterPage` (default export, registered in
  [registry.ts](../../../../../v2/frontend/src/pages/registry.ts) at
  route `/admin/report-center`).
- `SafetyStateBanner` — always visible, repeats the five required
  visible strings:
  - "Live trading is blocked."
  - "Legacy shutdown is blocked."
  - "Candidate symbols are not adopted automatically."
  - "Recovery requires proof of edge before scaling."
  - "No fake readiness."
- `ExecutiveScorecardPanel`.
- `ControllerStatePanel`.
- `PendingAndStalledTasksPanel`.
- `BlockerMatrixPanel`.
- `NextActionsPanel`.
- `LatestCodexFailuresPanel`.
- `StaleReportsPanel`.
- `ReportStatusTable` (all 30 lanes with status pill, freshness, owner,
  GO/NO-GO, next action; stale rows visually distinguished).

The page exposes **no** live / order / shutdown / adopt-symbol button.
When a payload fails to load, the page shows
`REPORT_CENTER_STALE_OR_UNAVAILABLE` and keeps the blockers visible.

## Polling (Phase 6)

- Operator dashboard payload polled every **15 s** via `usePollingQuery`.
- Report index polled every **30 s**.
- Latest Codex failures polled every **30 s** in its own panel.
- No WebSocket added.

## systemd (Phase 7)

[ai-bot-v2-report-center-indexer.service](../../../../systemd/user/ai-bot-v2-report-center-indexer.service)
(oneshot, runs from `/home/wali/Desktop/AI BOT REBUILD` using
`.venv/bin/python3`) + matching
[ai-bot-v2-report-center-indexer.timer](../../../../systemd/user/ai-bot-v2-report-center-indexer.timer)
(every 60 s).

[install_report_center.sh](../../../../systemd/user/install_report_center.sh)
copies the unit files into `~/.config/systemd/user/` and runs
`daemon-reload`; it does **NOT** enable or start the timer. The
operator must explicitly run
`systemctl --user enable --now ai-bot-v2-report-center-indexer.timer`
to switch on the cadence. Existing services are not touched.

## Tests (Phase 8)

Focused pytest under
[v2/backend/tests/unit/services/report_center/](../../../../../v2/backend/tests/unit/services/report_center/)
with **13 / 13 passing**:

- `test_registry_includes_all_required_lanes` — 30/30 lanes registered.
- `test_registry_has_no_duplicate_lane_ids`.
- `test_extract_go_no_go_from_marker_only_file`.
- `test_status_from_marker_codex_pass_and_fail`.
- `test_sanitize_text_redacts_api_keys_and_bearer`.
- `test_sanitize_text_redacts_pem_private_key_block`.
- `test_extract_markdown_sections_only_known_headings`.
- `test_safe_summary_from_markdown_captures_marker_and_redacts`.
- `test_safe_summary_from_json_prunes_unknown_keys_and_keeps_safety`.
- `test_index_lanes_emits_missing_payload_for_absent_lanes`.
- `test_index_lanes_marks_blocked_status_when_marker_blocked`.
- `test_no_lane_publishes_raw_secret`.
- `test_stale_threshold_marks_old_files`.

Run:

```
PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/unit/services/report_center/ -q
```

Frontend typecheck (`npx tsc --noEmit -p tsconfig.json` in
`v2/frontend/`) produced **no errors** for the new report-center
module after registering it in `registry.ts`.

Safety validation run on the live payloads:

- `safe_summary count: 30`
- `bad tokens found: []` (checked `AKIA`, `BEGIN RSA PRIVATE KEY`,
  `.local_secrets/`)
- `live_blocked=True`, `shutdown_blocked=True`,
  `production_equivalence_blocked=True`,
- `approves_live=False`, `approves_canary=False`,
  `approves_legacy_shutdown=False`, `approves_redis_trim=False`,
- `live_gate=blocked_human_only`, `live_symbols=[]`,
- All 5 `required_visible_text` strings present.

## Safety scoreboard (this cycle)

- did_not_modify_legacy_bot
- did_not_stop_v2_runtime
- did_not_stop_continuous_remediation
- did_not_stop_codex_governors
- did_not_stop_legacy_log_observer
- did_not_stop_v2_vs_legacy_comparator
- did_not_stop_liquidation_wss_daemon
- did_not_stop_position_history_daemon
- did_not_write_old_redis
- did_not_call_exchange
- did_not_create_approval_marker
- did_not_create_shutdown_acceptance_file
- did_not_expose_raw_api_keys
- did_not_expose_local_secrets
- did_not_expose_raw_logs
- live_gate=blocked_human_only
- live_symbols=[]

## Manual entry points

```
# One-off index refresh:
PYTHONPATH=$PWD .venv/bin/python v2/backend/app/cli/v2_report_center_indexer.py

# Continuous loop (every 60 s) without systemd:
PYTHONPATH=$PWD .venv/bin/python v2/backend/app/cli/v2_report_center_indexer.py --loop --interval-seconds 60

# Install systemd units (operator opt-in to enable):
bash claude_worklog/systemd/user/install_report_center.sh
systemctl --user enable --now ai-bot-v2-report-center-indexer.timer

# Tests:
PYTHONPATH=$PWD .venv/bin/pytest v2/backend/tests/unit/services/report_center/ -q
```

## Website route

`/admin/report-center` (RBAC: `viewer`).
