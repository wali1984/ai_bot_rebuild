# V2 Live-Readiness Blocker Burndown (TokenMetrics Excluded)

Generated: 2026-05-25T19:30:00Z
Git HEAD: 10513bbe0517fd81c9c87e4672bb15486a083c02
Lane: `v2_live_readiness_blocker_burndown_excluding_tokenmetrics`
GO/NO-GO: `V2_LIVE_READINESS_BLOCKER_BURNDOWN_EXCLUDING_TOKENMETRICS_READY`

## Plain English

- **TokenMetrics is deferred and is not the live blocker.**
- **Live is blocked because** paper-edge is not proven (after-cost expectancy
  -8.98 bps, operator thresholds OPERATOR_DECISION_REQUIRED), and risk caps +
  capital recovery + checkpoint promotion + exchange-adapter real-endpoint
  safety also remain unresolved.
- **Next operator decision is** sign paper-edge thresholds AND sign 14
  risk-cap fields AND decide checkpoint promotion path AND sign a separate
  read-only permission probe approval. Each step is a separate operator gate.
- **Next automatic action is** closed-loop Spark worker pool continues
  replay-miner cycles, report-center indexer, comparator refresh,
  pending-task watchdog, full-observation internal-family burndown, and
  dry-run canary service. No new tasks are auto-seeded for TokenMetrics.

`live_gate=blocked_human_only`. `live_symbols=[]`.

## Phase 1 — TokenMetrics Deferral

TokenMetrics is recorded as `DEFERRED_NOT_REQUIRED_FOR_CURRENT_NATIVE_PATH`.
It is removed from live-readiness blockers. The autoseed candidate
`tokenmetrics_native_v2_client_and_ingestor_scaffold` transitions to
`DEFERRED_BY_OPERATOR_NOT_AUTOSEED_ELIGIBLE`. No TokenMetrics API call,
no raw key read, no client scaffold continues from here.

## Phase 2 — Live-Readiness Blocker Matrix (14 categories)

| # | Category | Blocks Canary | Blocks Live | Automatable | Operator-Required |
| - | --- | :-: | :-: | :-: | :-: |
| 1 | `paper_edge` | ✓ | ✓ | ✓ | ✓ |
| 2 | `risk_caps` | ✓ | ✓ |   | ✓ |
| 3 | `capital_recovery_gates` | ✓ | ✓ |   | ✓ |
| 4 | `checkpoint_or_native_model_path` | ✓ | ✓ |   | ✓ |
| 5 | `canary_dry_run_safety` |   | ✓ | ✓ |   |
| 6 | `exchange_adapter_safety` | ✓ | ✓ |   | ✓ |
| 7 | `permission_probe` | ✓ | ✓ |   | ✓ |
| 8 | `kill_switch` |   | ✓ | ✓ | ✓ |
| 9 | `symbol_allowlist` | ✓ | ✓ |   | ✓ |
| 10 | `position_sizing` | ✓ | ✓ |   | ✓ |
| 11 | `margin_leverage_guard` | ✓ | ✓ |   | ✓ |
| 12 | `order_retry_cancel_safety` | ✓ | ✓ | ✓ | ✓ |
| 13 | `paper_to_live_consistency` | ✓ | ✓ | ✓ | ✓ |
| 14 | `report_center_operator_truth` |   |   | ✓ |   |

Totals: 11 block_canary · 14 block_live · 7 automatable · 12 operator_required.

## Phase 3 — Paper-Edge Live-Readiness

| Field | Value |
| --- | --- |
| `sample_count` | 3347 |
| `after_cost_expectancy_bps` | -8.981832584893514 |
| `after_cost_ci_lower_bps` | -13.090729934534577 |
| `after_cost_ci_upper_bps` | -5.115957570291047 |
| `false_positive_rate` | null (insufficient labels) |
| `false_negative_rate` | 0.198 |
| `downside_pre_cascade_recall` | null (insufficient labels) |
| `max_drawdown_bps_observed` | 309.83 |
| `no_trade_correct_count` | 65 |
| `fee_drag_bps` | 5.0 |
| `slippage_estimate_bps` | 2.0 |
| `minimum_sample_satisfied` | false |
| `threshold_status` | OPERATOR_THRESHOLDS_REQUIRED_AND_AFTER_COST_EVIDENCE_NEGATIVE |
| `edge_proven` | **false** |
| `canary_ready` | **false** |
| `live_ready` | **false** |

No fabricated edge. Replay miner verdict mirrored: `EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED`.

## Phase 4 — Risk/Capital Threshold Proposal (proposal-only)

14 fields proposed with conservative numeric values for operator review.
Every field has `operator_selected=false` and `operator_accepted=false`.
No value is persisted to engine config. Engine continues to fail closed
when fields are `OPERATOR_DECISION_REQUIRED`.

Examples (all proposal-only, awaiting operator signature):
- `max_daily_loss_usd`: 100 USDT
- `max_daily_loss_pct`: 1.0%
- `max_trade_notional_usd`: 25 USDT
- `max_drawdown_pct`: 2.0%
- `kill_switch_drawdown_pct`: 3.0%
- `paper_edge_min_expectancy_bps`: 5.0 (current observed -8.98 bps — floor not met)

## Phase 5 — Canary Dry-Run Safety

Upstream `v2_live_canary_dry_run_service` is READY. Key invariants
re-verified for this lane:

- `exchange_adapter_kind`: FakeExchangeAdapter
- `fake_exchange_adapter_only`: true
- `real_order_attempted`: false
- `real_order_submitted`: false
- `places_real_order`: false
- `exchange_mutation`: false
- `leverage_changed`: false
- `margin_mode_changed`: false
- `live_enabled`: false
- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- Ledger: 42 entries, 0 real orders attempted, 0 real orders submitted, 0 exchange writes
- Boundary safety: final post revalidates all gates; direct/private bypasses remediated
- Kill switch tested in dry run against fake adapter only (not validated under real endpoint)

## Phase 6 — Exchange Permission / No-Order Probe Plan (plan-only)

Plan is DRAFT. Not executed. Operator approval required before any execution.
Allowed surface when operator signs: read-only GET account/balance with
range-bucketed balances (never raw); read-only GET permission introspection
returning capability flags only. Forbidden endpoints: all POST/PUT/DELETE
order/leverage/margin/positionSide/batchOrders paths. Test orders not
permitted in this lane.

Credential safety invariants:
- Credentials never printed to console
- Credentials never persisted in worklog
- Credentials never persisted in public payload
- Credentials referenced in payloads by env-var NAME only

## Phase 7 — Final Recommendation

Primary: `BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN`

Secondary:
- `BLOCK_LIVE_RISK_CAPS_OPERATOR_REQUIRED`
- `BLOCK_LIVE_MODEL_CHECKPOINT_NOT_READY`
- `BLOCK_LIVE_EXCHANGE_SAFETY_NOT_PROVEN`

`canary_ready=false`. `live_ready=false`. `CANARY_READY` and `LIVE_READY`
are explicitly disallowed.

## Phase 8 — Operator Dashboard

See `operator_dashboard_payload.json` for the consolidated view. Report
Center indexer will pick this lane up on the next cycle.

## Required Safety Text

- This is live-readiness blocker burndown.
- This is not live approval.
- This is not canary approval.
- This is not legacy shutdown approval.
- This is not Redis trim approval.

## Verification

```text
python3 -c "import json,glob; [json.load(open(p)) for p in glob.glob('claude_worklog/final_readiness/v2_live_readiness_blocker_burndown_excluding_tokenmetrics/latest/*.json')]; print('OK')"

ls claude_worklog/approvals/OPERATOR_ACCEPTS_V2_PAPER_ONLY_SHUTDOWN_LIMITATIONS.md 2>&1 || echo 'acceptance_file_absent_as_expected'
```
