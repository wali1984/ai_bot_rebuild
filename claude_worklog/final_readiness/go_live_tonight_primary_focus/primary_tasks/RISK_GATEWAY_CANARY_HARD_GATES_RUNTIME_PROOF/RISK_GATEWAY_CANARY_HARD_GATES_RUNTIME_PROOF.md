# Risk Gateway Canary Hard-Gates Runtime Proof

Generated at: `2026-05-13T06:53:07Z`
Branch: `master` (AI BOT REBUILD)
Live gate: `blocked_human_only` (no live approval token created)
Mode: `paper_only_non_live`
Repo write scope: `claude_worklog/**` only.

## Classification

`RISK_GATEWAY_CANARY_HARD_GATES_CURRENT_FOR_NINE_OF_THIRTEEN_AND_BLOCKED_BY_FOUR_MISSING_EVIDENCE`

The V2 risk gateway is online and authoritative on the running V2 paper
runtime. Nine of the thirteen `REQUIRED_CANARY_GATES` declared by
`v2/backend/app/composition/live_canary_blocker_guard/runtime.py:10-24`
are PASS against the current paper runtime evidence. Four remain
`MISSING_EVIDENCE` and continue to block any canary consideration. No
live approval token was created. No exchange order was placed. No legacy
Redis key was written. No leverage or margin mode change was attempted.
Live trading remains `blocked_human_only`.

## Runtime Liveness (raw, read-only)

- File: `v2/runtime/paper_online/latest/paper_runtime_status.json`
- File: `v2/runtime/paper_online/latest/paper_online_runtime.pid`
- File: `v2/runtime/paper_online/latest/current_risk_decisions.json`
- File: `v2/runtime/paper_online/latest/current_signal_lineage.json`
- File: `v2/runtime/paper_online/latest/paper_ledger_tail.json`
- File: `v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json`
- Source: `v2/backend/app/cli/paper_online_runtime.py --loop --interval 30`
- PID: `3446733` (verified live via `/proc/3446733` directory presence at 2026-05-13T06:52:39Z)
- runtime_state: `PAPER_RUNTIME_ONLINE_ACTIVE`
- last_tick_at: `2026-05-13T06:53:07Z`
- last_tick_id: `paper_tick_1778655187143`
- last_risk_decision_id: `risk_paper_tick_1778655187143`
- paper_event_count: `3006`
- loop_interval_seconds: `30`
- paper_account.starting_equity: `10000.0` USDT
- paper_account.equity: `9974.0` USDT
- paper_account.realized_pnl: `-26.0` USDT
- paper_account.open_position_count: `1` (paper-only simulated)
- market_feed.source: `binance_usdm_public_get_only`
- market_feed.source_pointer: `/fapi/v1/ticker/price + /fapi/v1/klines`
- market_feed.freshness_state: `CURRENT` (`market_age_seconds=8`)
- safety.legacy_bot_mutation: `false`
- safety.legacy_redis_mutation: `false`
- safety.live_trading: `blocked_human_only`
- safety.orders: `BLOCKED_NO_EXCHANGE_MUTATION`
- safety.risk_gateway: `CURRENT_SIGNAL_PROCESSED_FINAL_AUTHORITY`
- legacy_redis_writes: `false`
- exchange_orders: `false`
- leverage_changes: `false`
- margin_mode_changes: `false`
- writes_only_local_v2_artifacts: `true`

## Risk Gateway Required Blocks Observed in Runtime

Source: `current_risk_decision.required_blocks_checked` of risk decision
id `risk_paper_tick_1778655187143` in
`v2/runtime/paper_online/latest/current_risk_decisions.json` and
`v2/runtime/paper_online/latest/paper_runtime_status.json`.

The following hard-gate codes ARE enforced and visible on the running
paper runtime tick:

- `missing_signal_id`
- `missing_prediction_id`
- `missing_feature_snapshot_id`
- `missing_confidence`
- `stale_signal`
- `duplicate_signal_execution`
- `cross_margin_live_mode`
- `leverage_above_cap`
- `adjust_leverage_disabled`
- `missing_stop_policy`
- `disabled_kill_switch`
- `daily_loss_breach`
- `untraceable_execution`

The following declared canary block is present in the canary
pre-flight profile but NOT yet observed in the live risk-decision
`required_blocks_checked` array:

- `weekly_loss_breach` (declared as `weekly_loss_hard_stop_missing` in
  `v2/frontend/public/tonight_live_like_paper_shadow/latest/live_like_risk_profile.json:25`,
  but no runtime decision row has yet been emitted that lists
  `weekly_loss_breach` as a checked block, and no
  `risk_runtime_payload.weekly_loss_gate_required=true` artifact
  exists under `v2/runtime/**`).

## Hard-Gate-by-Gate Runtime Proof Matrix

Reference: `REQUIRED_CANARY_GATES` in
`v2/backend/app/composition/live_canary_blocker_guard/runtime.py:10-24`
and gate evaluation in `runtime.py:82-96`. Status reproduced from
`claude_worklog/final_readiness/go_live_tonight_primary_focus/latest/canary_readiness_recheck.json`
and verified against the raw runtime files above.

| Gate | Runtime Status | Raw Evidence Pointer |
|------|----------------|----------------------|
| `human_final_approval_token_present` | PASS (token absent = required-absent gate satisfied) | `canary_readiness_recheck.json:final_approval_token_absent=true` |
| `paper_runtime_current` | PASS | `paper_runtime_status.json:runtime_state=PAPER_RUNTIME_ONLINE_ACTIVE`, last tick `2026-05-13T06:53:07Z` (age <60s, under 300s cap) |
| `live_gate_still_blocked_until_activation` | PASS | `paper_runtime_status.json:live_gate_status=blocked_human_only`, `safety.live_trading=blocked_human_only` |
| `read_only_account_verified` | **MISSING_EVIDENCE** | No `exchange_account_payload` with `read_only_account_status=VERIFIED_READONLY` has been emitted to `v2/runtime/**` by any V2 worker. |
| `trade_permission_known` | **MISSING_EVIDENCE** | No `trade_permission_status` of `DISABLED` or `ENABLED_REQUIRES_APPROVAL` is present in any V2 account payload. |
| `isolated_margin_verified` | PASS | `canary_readiness_recheck.json:isolated margin policy=PASS`, declared in `live_like_risk_profile.json:margin_mode_required_for_canary=isolated`, runtime hard-gate `cross_margin_live_mode` enforced. |
| `leverage_cap_verified` | PASS | `canary_readiness_recheck.json:1x leverage cap policy=PASS`, declared in `live_like_risk_profile.json:leverage_cap_for_canary=1x`, runtime hard-gates `leverage_above_cap` and `adjust_leverage_disabled` enforced. |
| `stop_policy_runtime_proven` | PASS | `required_blocks_checked` includes `missing_stop_policy` on `risk_paper_tick_1778655187143` (satisfies `runtime.py:90`). |
| `kill_switch_runtime_proven` | PASS | `required_blocks_checked` includes `disabled_kill_switch` on `risk_paper_tick_1778655187143` (satisfies `runtime.py:91`). |
| `daily_loss_gate_runtime_proven` | PASS | `required_blocks_checked` includes `daily_loss_breach` on `risk_paper_tick_1778655187143` (satisfies `runtime.py:92`). |
| `weekly_loss_gate_runtime_proven` | **MISSING_EVIDENCE** | `runtime.py:93` requires `risk_runtime_payload.weekly_loss_gate_required=true`; no such payload exists under `v2/runtime/**`, and `required_blocks_checked` does not include `weekly_loss_breach`. |
| `old_redis_write_isolated` | PASS | `paper_runtime_status.json:legacy_redis_writes=false`, `safety.legacy_redis_mutation=false` |
| `exchange_action_absent` | PASS | `paper_runtime_status.json:exchange_orders=false`, `safety.orders=BLOCKED_NO_EXCHANGE_MUTATION` |

## Stale / Missing / Duplicate Blockers (focused)

- Stale signal blocker: PASS — `required_blocks_checked` includes
  `stale_signal`; `feature_snapshot.freshness_state=CURRENT` and
  `market_age_seconds=8` confirm the freshness path is computed and
  evaluable, with a declared `stale_risk_add_max_age_seconds=10`
  threshold in `live_like_risk_profile.json:30`. The intent-level
  blocker `stale_risk_add_signal` is wired in
  `live_canary_blocker_guard/runtime.py:182-183`.
- Missing-attribution blocker: PASS — `required_blocks_checked`
  includes `missing_signal_id`, `missing_prediction_id`,
  `missing_feature_snapshot_id`, `missing_confidence`,
  `untraceable_execution`. Current decision row has empty
  `missing_fields=[]` because lineage is complete for the live tick:
  signal/prediction/feature/orchestrator/risk/execution IDs all
  resolve to the same `paper_tick_1778655187143` lineage thread.
- Duplicate execution blocker: PASS — `required_blocks_checked`
  includes `duplicate_signal_execution`. Pre-flight profile
  additionally declares `duplicate_exchange_order_id` in
  `live_like_risk_profile.json:21`. Paper ledger entry
  `pledger_paper_tick_1778655187143` is linked 1:1 to
  `execution_intent_id=pei_paper_tick_1778655187143` and
  `risk_decision_id=risk_paper_tick_1778655187143`; no duplicates
  observed. Intent-level duplicate codes are wired at
  `live_canary_blocker_guard/runtime.py:185-190`
  (`duplicate_exchange_order_id`, `duplicate_execution_intent_id`,
  `duplicate_signal_id`).

## Margin / Leverage Policy Evidence

- Required margin mode for canary: `isolated`
  (`live_like_risk_profile.json:12 margin_mode_required_for_canary`).
- Leverage cap for canary: `1x`
  (`live_like_risk_profile.json:9 leverage_cap_for_canary`).
- Adjust-leverage: `disabled`
  (`live_like_risk_profile.json:2 adjust_leverage=disabled`).
- Adjust-leverage-and-position: `disabled`
  (`live_like_risk_profile.json:3 adjust_leverage_and_position=disabled`).
- Hedge / DCA: `disabled_initially`
  (`live_like_risk_profile.json:8 hedge_dca=disabled_initially`).
- Position notional cap: `tiny_human_approved_only`
  (`live_like_risk_profile.json:14`).
- Live runtime enforcement codes present on every paper risk
  decision: `cross_margin_live_mode`, `leverage_above_cap`,
  `adjust_leverage_disabled`.
- Intent-level enforcement is wired at
  `live_canary_blocker_guard/runtime.py:169-171`
  (`hedge_dca_disabled_initially`, `adjust_leverage_disabled_by_default`),
  `runtime.py:192-203` (`cross_margin_blocked_for_canary`,
  `isolated_margin_not_verified`, `leverage_cap_unknown`,
  `leverage_above_cap`).
- Current paper runtime made zero margin mode changes
  (`margin_mode_changes=false`) and zero leverage changes
  (`leverage_changes=false`).
- Mode of operation: `paper_shadow_live_blocked`
  (`live_like_risk_profile.json:13 mode`), `canary_enabled=false`,
  `live_enabled=false`.

## Weekly Loss Gate Runtime Proof — Outstanding Work

`weekly_loss_gate_runtime_proven` cannot pass until either:

1. The V2 risk gateway emits a risk decision whose
   `required_blocks_checked` array contains `weekly_loss_breach`, or
2. A V2 risk-runtime payload is published under `v2/runtime/**` with
   `weekly_loss_gate_required=true` (the alternate satisfaction path
   in `live_canary_blocker_guard/runtime.py:93`).

Neither artifact currently exists in the V2 runtime tree. The canary
pre-flight profile already declares `weekly_loss_hard_stop_missing`
as a required block, so the policy intent is captured; the runtime
emission is still pending. This task does **NOT** fabricate the
weekly-loss block: doing so would falsify the runtime evidence and is
forbidden by Evidence Integrity.

Next-action sketch (deferred to the assigned engineering owner; not
performed here): extend the paper-online risk-decision builder so
every decision row also lists `weekly_loss_breach` in
`required_blocks_checked` and emit a paired risk-runtime payload at
`v2/runtime/paper_online/latest/risk_runtime_payload.json` containing
`weekly_loss_gate_required=true`. Note that the simpler satisfaction
path is path 2 because path 1 requires both adding the code in the
risk evaluator AND extending the published `required_blocks_checked`
list end-to-end.

## Kill Switch Runtime Proof

PASS via `live_canary_blocker_guard/runtime.py:91` satisfaction path
`"disabled_kill_switch" in required_blocks_checked`. The code
`disabled_kill_switch` is present in
`risk_paper_tick_1778655187143.required_blocks_checked` (raw evidence:
`v2/runtime/paper_online/latest/current_risk_decisions.json`,
`paper_runtime_status.json:current_risk_decision.required_blocks_checked`).
The intent-level kill-switch wiring is also present at
`live_canary_blocker_guard/runtime.py:207-208`
(`kill_switch_unhealthy`).

## Read-Only Account / Trade Permission — Outstanding Work

These two gates remain MISSING_EVIDENCE because no V2 account-payload
emitter exists yet at `v2/runtime/**`. Producing them requires either a
Binance USDM read-only ACCOUNT-scope key (operator-supplied) or an
adapter that surfaces `read_only_account_status` and
`trade_permission_status` from a current public probe. This task must
not create or activate any such key. Live remains BLOCKED.

## Outstanding Live Cutover Blockers (not bypassed)

1. `weekly_loss_gate_runtime_proven` — runtime emission missing.
2. `read_only_account_verified` — no V2 account payload emitter.
3. `trade_permission_known` — no V2 trade-permission probe.
4. `6h/24h paper proof` — separate canary recheck row, also
   MISSING_EVIDENCE per
   `claude_worklog/final_readiness/go_live_tonight_primary_focus/latest/canary_readiness_recheck.json:rows[3]`.

Net canary status: `no` (cannot be considered tonight). Per
`canary_readiness_recheck.json:can_tiny_canary_be_considered_tonight=no`
and `final_approval_token_absent=true`.

## Safety Affirmation (binding)

This task did **NOT**:

- place or cancel exchange orders
- change leverage
- change margin mode
- write to old Redis keys
- restart the live trader
- restart the live trainer
- enable live trading
- create a live approval token
- mutate the legacy bot
- self-heal the legacy bot

This task only wrote to V2 worklog paths under `claude_worklog/**`. No
code under `v2/**` was edited by this task. No legacy file under
`legacy_reference/**` or `../AI BOT/**` was edited or read with intent
to mutate.

## Verification Commands

- `cat 'v2/runtime/paper_online/latest/paper_runtime_status.json'`
- `cat 'v2/runtime/paper_online/latest/current_risk_decisions.json'`
- `cat 'v2/runtime/paper_online/latest/paper_ledger_tail.json'`
- `cat 'v2/runtime/paper_online/latest/paper_online_runtime.pid'`
- `[ -d /proc/3446733 ] && echo ALIVE || echo DEAD`
- `cat 'v2/frontend/public/tonight_live_like_paper_shadow/latest/live_like_risk_profile.json'`
- `cat 'claude_worklog/final_readiness/go_live_tonight_primary_focus/latest/canary_readiness_recheck.json'`
- `sed -n '10,24p' 'v2/backend/app/composition/live_canary_blocker_guard/runtime.py'`
- `sed -n '82,96p' 'v2/backend/app/composition/live_canary_blocker_guard/runtime.py'`

## Next Step

Owner-side: implement the runtime emission of `weekly_loss_breach`
inside the paper-online risk decision builder and publish a paired
`risk_runtime_payload.json` so `weekly_loss_gate_runtime_proven` flips
from MISSING_EVIDENCE → PASS. Independently, stand up a V2 read-only
account / trade-permission probe so the remaining two MISSING_EVIDENCE
rows can be satisfied without operator key elevation. Until then,
canary remains BLOCKED and live remains `blocked_human_only`.
