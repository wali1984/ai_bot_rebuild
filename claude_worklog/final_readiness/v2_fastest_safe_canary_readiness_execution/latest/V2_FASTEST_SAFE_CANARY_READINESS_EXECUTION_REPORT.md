# V2 Fastest-Safe Canary-Readiness Execution

Generated: 2026-05-25T19:55:00Z
Git HEAD: 10513bbe0517fd81c9c87e4672bb15486a083c02
Lane: `v2_fastest_safe_canary_readiness_execution`
GO/NO-GO: `V2_FASTEST_SAFE_CANARY_READINESS_EXECUTION_READY`
Upstream Codex gate: `V2_LIVE_READINESS_BLOCKER_BURNDOWN_EXCLUDING_TOKENMETRICS_CODEX_PASS`

This packet executes the fastest safe canary-readiness path. It does not
approve canary, live trading, legacy shutdown, Redis trim, exchange
mutation, leverage/margin changes, or any approval workflow.

## Plain English

- **TokenMetrics remains deferred and is not a canary blocker.**
- **Canary is blocked because** paper-edge is not proven under any candidate
  threshold set, risk/capital caps are operator-required, and the read-only
  permission probe approval has not been signed.
- **Next operator decision:** sign a paper-edge threshold set
  (conservative or aggressive), sign 14 risk/capital cap fields, and sign
  a separate read-only permission-probe approval artifact.
- **Next automatic action:** closed-loop Spark continues replay-miner
  cycles, report-center indexer, comparator refresh, dry-run canary
  service. No new TokenMetrics work is auto-seeded.

`live_gate=blocked_human_only`. `live_symbols=[]`.

## Phase 1 — TokenMetrics deferral frozen

TokenMetrics is `DEFERRED_NOT_REQUIRED_FOR_CURRENT_NATIVE_PATH`. No API
call, no live-blocker classification, no autoseed.

## Phase 2 — Threshold selection packet

7 operator paper-edge thresholds surfaced with conservative AND aggressive
candidate sets. `operator_selected_count=0`, `operator_accepted_count=0`,
`is_proposal_only=true`. No value persisted to engine config.

| Threshold | Conservative | Aggressive | Current Observed |
| --- | --- | --- | --- |
| `min_sample_count` | 5000 | 2000 | 3347 |
| `min_after_cost_expectancy_bps` | 5.0 | 0.0 | -8.98 |
| `min_after_cost_lower_ci_bps` | 0.0 | -5.0 | -13.09 |
| `max_drawdown_bps_rolling` | 200.0 | 500.0 | 309.83 |
| `min_downside_pre_cascade_recall` | 0.60 | 0.40 | null |
| `max_false_positive_rate` | 0.10 | 0.25 | null |
| `max_false_negative_rate` | 0.15 | 0.30 | 0.198 |

## Phase 3 — Risk/capital cap selection packet

14 canary risk/capital cap fields surfaced with conservative AND aggressive
candidate sets. `operator_selected_count=0`, `operator_accepted_count=0`.
No value persisted to engine config.

| Field | Conservative | Aggressive |
| --- | --- | --- |
| `max_daily_loss_pct` | 1.0% | 2.0% |
| `max_weekly_loss_pct` | 3.0% | 5.0% |
| `max_position_notional_pct` | 5.0% | 10.0% |
| `max_consecutive_losses` | 3 | 5 |
| `canary_order_size` (USDT) | 25 | 50 |
| `min_expected_edge_after_cost_bps` | 5.0 | 0.0 |
| `min_confidence_calibrated` | 0.65 | 0.55 |
| `max_feature_freshness_seconds` | 60 | 180 |
| `max_concurrent_positions` | 1 | 3 |
| `kill_switch_consecutive_losses_window_hours` | 6 | 24 |
| `max_total_exposure` (USDT) | 100 | 200 |
| `max_symbol_exposure` (USDT) | 50 | 100 |
| `cooldown_after_loss_minutes` | 30 | 10 |
| `kill_switch_drawdown_pct` | 3.0% | 5.0% |

## Phase 4 — Paper-edge re-evaluation

Both conservative and aggressive candidate sets fail. `edge_proven=false`,
`canary_ready=false`, `live_ready=false`, `fabricates_edge=false`.

| Set | Thresholds Passed | Verdict |
| --- | --- | --- |
| conservative | 0/7 | `EDGE_NOT_CLAIMED_UNDER_CONSERVATIVE_SET` |
| aggressive | 3/7 | `EDGE_NOT_CLAIMED_UNDER_AGGRESSIVE_SET_AFTER_COST_NEGATIVE_AND_LABELS_INSUFFICIENT` |

Recommendation from this phase: `BLOCK_CANARY_PAPER_EDGE_NOT_PROVEN`.

## Phase 5 — Read-only exchange permission probe approval packet

Draft only. `operator_approval_artifact_present=false`,
`probe_executed_at_this_packet=false`. Allowed surface when operator signs:
read-only GET account/balance (bucketed in payload), read-only
permission introspection (capability flags only). Forbidden: all
POST/PUT/DELETE order/leverage/margin/positionSide/batchOrders endpoints.
Credentials never printed, never persisted, referenced by env-var NAME
only. Operator must sign a separate read-only permission-probe approval
artifact before any probe can run.

## Phase 6 — Canary dry-run safety refresh

- `exchange_adapter_kind`: FakeExchangeAdapter
- `fake_exchange_adapter_only`: true
- `real_order_attempted`: false
- `real_order_submitted`: false
- `writes_exchange_orders`: false
- `leverage_changed`: false
- `margin_mode_changed`: false
- `live_gate`: blocked_human_only
- `live_symbols`: []
- Ledger: 42 entries, 0 real orders attempted/submitted
- Boundary safety: final post revalidates all gates; bypasses remediated
- Kill switch tested in dry run against fake adapter only

## Phase 7 — Final recommendation

Primary: `BLOCK_CANARY_PAPER_EDGE_NOT_PROVEN`

Secondary: `BLOCK_CANARY_RISK_CAPS_OPERATOR_REQUIRED`,
`BLOCK_CANARY_EXCHANGE_PERMISSION_PROBE_REQUIRED`

`canary_ready=false`. `live_ready=false`. Positive canary/live readiness
emits are explicitly disallowed.

## Verification

```text
python3 -c "import json,glob; [json.load(open(p)) for p in glob.glob('claude_worklog/final_readiness/v2_fastest_safe_canary_readiness_execution/latest/*.json')]; print('OK')"

python3 -c "import pathlib; assert not any(pathlib.Path('claude_worklog/approvals').glob('*PERMISSION_PROBE*.md')); print('probe_approval_absent_as_expected')"

python3 -c "import pathlib; assert not any(pathlib.Path('claude_worklog/approvals').glob('*PAPER_ONLY_SHUTDOWN*.md')); print('shutdown_acceptance_absent_as_expected')"
```
