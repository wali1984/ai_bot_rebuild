# V2 Executive Recovery and Production-Readiness Command Center — Ready Report

GO/NO-GO: `V2_EXECUTIVE_RECOVERY_AND_PRODUCTION_READINESS_COMMAND_CENTER_READY`

Generated: see [executive_automation_status.json](executive_automation_status.json) `generated_utc`.

## Mission

Build V2 into a production-equivalent, risk-controlled trading system
capable of systematic capital recovery through measured edge, **not**
aggressive or unproven live risk.

The operator has indicated prior capital loss. Every executive action
in this command center defaults to capital preservation. When in doubt
the cautious option is chosen, not the aggressive one.

## What this command center is

A permanent operator-facing layer that aggregates every existing
governor / controller / observer into one honest readiness picture.
The command center never trades, never approves, never starts the
legacy shutdown, and never raises caps. It only:

- aggregates the latest status from all upstream artifacts;
- maintains the mission lock, blocker matrix, capital recovery gate
  model, and production readiness scorecard;
- emits the daily executive briefing;
- exposes a frontend operator-dashboard payload that is honest about
  blocked state.

## Artifacts (Phases 1–9)

| Phase | Artifact | Path |
|---|---|---|
| 1 | Mission lock | [mission_lock.json](mission_lock.json) |
| 2 | Blocker matrix (14 blockers / 13 categories) | [executive_blocker_matrix.json](executive_blocker_matrix.json) |
| 3 | Capital recovery gate model (placeholder caps) | [capital_recovery_gate_model.json](capital_recovery_gate_model.json) |
| 4 | Executive automation status (aggregator) | [executive_automation_status.json](executive_automation_status.json) |
| 5 | Production readiness scorecard (11 categories, honest low) | [production_readiness_scorecard.json](production_readiness_scorecard.json) |
| 6 | Daily executive briefing | [DAILY_EXECUTIVE_BRIEFING.md](DAILY_EXECUTIVE_BRIEFING.md) |
| 7 | Frontend operator dashboard payload | [v2/frontend/public/v2_executive_command_center/latest/operator_dashboard_payload.json](../../../../../v2/frontend/public/v2_executive_command_center/latest/operator_dashboard_payload.json) |
| 8 | systemd .service + .timer (not enabled) | [claude_worklog/tools/systemd/](../../../../tools/systemd/) |
| 9 | This GO/NO-GO + report | [GO_NO_GO.md](GO_NO_GO.md), this file |

## Phase 4 — Integrated upstream controllers / governors

The command center reads (does **not** drive) the latest status of:

- autonomous full-rebuild self-healing controller
  (`claude_worklog/final_readiness/v2_autonomous_full_rebuild_self_healing/latest/`)
- autonomous production-equivalence burndown controller
  (`claude_worklog/final_readiness/v2_autonomous_production_equivalence_burndown/latest/`)
- pending-task watchdog
  (`pending_task_watchdog_status.json`)
- continuous remediation governor and Codex autonomous governor
  (latest payloads under `claude_worklog/final_readiness/…`)
- legacy log observer + V2-vs-legacy comparator
  (frontend public payloads)
- full-observation builder status
  (`v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json`)
- remaining-dim execution queue
  (`v2_full_observation_remaining_dim_execution_queue/latest/`)
- alt-data candidate publisher
  (lane registry pointer)
- liquidation WSS daemon heartbeat
  (`v2:market:liquidations:heartbeat`)
- position-history tracker heartbeat
  (`v2:paper:position_history:heartbeat`)
- live/canary safety markers (`live_gate=blocked_human_only`, `live_symbols=[]`).

Stale controllers and stalled tasks are reported in
`executive_automation_status.json`.

## Phase 5 — Scorecard honesty

Scores are intentionally low when evidence is unknown or unproven.
First-cycle overall_score = `18.2 / 100`. The individual category
scores stay capped until prior gates pass:

- `observation_completeness` capped at 30 until 1911 dims are genuinely sourced;
- `model_policy_readiness` = 0 (policy architecture not started, operator gate);
- `checkpoint_readiness` = 0 (blob deserialization forbidden);
- `paper_edge_readiness` = 0 (after-cost positive edge not certified);
- `risk_readiness` = 10 (caps unset);
- `decision_match_readiness` = 10 (not yet certified);
- `live_canary_readiness` = 0 (blocked human-only).

These are deliberately conservative numbers chosen to prevent
fabricated readiness.

## Phase 6 — Daily executive briefing

[DAILY_EXECUTIVE_BRIEFING.md](DAILY_EXECUTIVE_BRIEFING.md) answers
the 8 required questions, including "What must not be done?". The
briefing is regenerated every cycle.

## Phase 3 — Capital recovery gate model

[capital_recovery_gate_model.json](capital_recovery_gate_model.json)
lists the absolute rules (`no live recovery trading until paper edge
is statistically positive after costs`, etc.) and the placeholder caps
that REQUIRE operator decision before any live or canary action:

- `max_daily_loss_pct`
- `max_weekly_loss_pct`
- `max_position_notional_pct`
- `max_consecutive_losses`
- `canary_order_size`
- `min_expected_edge_after_cost_bps`
- `min_confidence_calibrated`
- `max_feature_freshness_seconds`
- `max_concurrent_positions`
- `kill_switch_consecutive_losses_window_hours`

Each cap defaults to `OPERATOR_DECISION_REQUIRED`. No autonomous
process is permitted to set, raise, or lower these caps.

## Phase 7 — Frontend operator command center

[operator_dashboard_payload.json](../../../../../v2/frontend/public/v2_executive_command_center/latest/operator_dashboard_payload.json)
exposes:

- current objective (mission text);
- readiness scorecard (all 11 categories with scores, evidence,
  blockers, next action);
- full blocker matrix (14 blockers);
- active automation + stale automation lists;
- stalled and pending Claude/Codex task counts;
- next automatable task / next operator decision /
  no_automatable_work_remaining reason;
- `live_blocked=true`, `shutdown_blocked=true`;
- `paper_edge_state=unproven`, `model_parity_state=not_started`,
  `recovery_gate_state=placeholders_pending_operator_decision`;
- `capital_protection_decisions_required` list;
- honesty invariants (`no fabricated readiness`,
  `every blocked state surfaced explicitly`,
  `capital protection precedes recovery`,
  `live and shutdown remain blocked human-only`).

## Phase 8 — systemd (not enabled)

Under [claude_worklog/tools/systemd/](../../../../tools/systemd/):

- `ai-bot-v2-executive-command-center.service` (oneshot)
- `ai-bot-v2-executive-command-center.timer` (every 15 min)
- (plus the previously-added self-healing controller + watchdog units)

`install_user_units.sh` copies units to `~/.config/systemd/user/` and
runs `systemctl --user daemon-reload`. It does **NOT** enable or start
any timer. The operator must explicitly run
`systemctl --user enable --now ai-bot-v2-executive-command-center.timer`
to switch on the cadence. Existing services / governors / observers
are not touched.

## Safety scoreboard (this command center, this cycle)

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
- did_not_modify_leverage_or_margin
- did_not_enable_live
- did_not_create_approval_marker
- did_not_create_shutdown_acceptance_file
- did_not_expose_raw_api_keys
- did_not_deserialize_checkpoint_blobs
- did_not_set_risk_caps_autonomously
- did_not_raise_or_lower_caps
- live_gate=blocked_human_only
- live_symbols=[]

## Manual entry points

```
python3 claude_worklog/tools/v2_executive_command_center.py        # one cycle
python3 claude_worklog/tools/v2_executive_command_center.py --json # full JSON
bash claude_worklog/tools/systemd/install_user_units.sh             # install systemd units (not enabled)

# Then operator opt-in for cadence:
systemctl --user enable --now ai-bot-v2-executive-command-center.timer
systemctl --user enable --now ai-bot-v2-autonomous-full-rebuild-self-healing-controller.timer
systemctl --user enable --now ai-bot-v2-pending-task-watchdog.timer
```

## Operator decisions pending (top of the queue)

1. Set numeric capital protection caps in `capital_recovery_gate_model.json`
   (or via a separate operator decision artifact). No live/canary can
   proceed until these are set.
2. Decide each external feed individually (token metrics, onchain BTC,
   onchain ETH, CCXT OHLCV, paid CoinAnk aggregator).
3. Decide whether to add a V2-owned liquidation WSS publisher.
4. Approve the policy architecture gate (only after observation gate).
5. Approve the checkpoint artifact gate (only after policy gate).
6. Approve V2-vs-legacy decision-match certification threshold.
7. Approve paper-edge certification threshold (minimum trade count,
   minimum after-cost expectancy, drawdown bounds).
8. Approve Symbol Universe adoption scope when ready.
9. Approve canary parameters and the canary order activation.
10. Approve live ramp parameters only after canary pass.
