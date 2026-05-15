# Paper Edge Post-Filter Observation Window

Generated at: `2026-05-15T02:00:11Z`
Task: `paper_edge_post_filter_observation_window`
Lane: `shutdown_readiness_remediation`
Live gate: `blocked_human_only`
Live symbols: `[]`
Final approval token: `absent`
Redis trim approval: `absent`
Classification: **POST_FILTER_EDGE_PENDING**

## Purpose

Separate the legacy / pre-filter paper-fill behavior (which produced the
cumulative `-49.12 USDT` paper PnL) from behavior after the
`paper_canary_aligned_filter_v1` predicate started gating paper fills via
`v2_paper_execution_worker`. Prove whether the post-filter window is
preventing fee bleed and churn, without conflating it with old
pre-filter losses and without prematurely declaring paper edge proven.

## Filter activation evidence (raw)

| Field | Value | Source |
| --- | --- | --- |
| direct_fix_id | `codex_wire_paper_canary_aligned_filter_v1` | `claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/codex_direct_fixes/codex_wire_paper_canary_aligned_filter_v1/codex_wire_paper_canary_aligned_filter_v1_STATUS.json:3` |
| status | `CODEX_DIRECT_FIX_COMPLETE` | same file:4 |
| as_of_utc | `2026-05-14T22:40:46Z` | same file:2 |
| fixed_defect | `paper_execution_worker_missing_canary_profile_tightening_before_fill` | same file:7 |
| changed_files | `v2/backend/app/cli/v2_paper_execution_worker.py`, `v2/backend/tests/integration/cli/test_v2_paper_execution_worker.py` | same file:15-18 |
| paper_filter_profile | `paper_canary_aligned_filter_v1` | `v2/runtime/v2_paper_execution_worker/latest/v2_paper_execution_worker_status.json:112` |
| paper_filter_source | `V2_CANARY_PROFILE_TIGHTENING` | same file:116 |
| live_gate (post-fix) | `blocked_human_only` | `codex_wire_paper_canary_aligned_filter_v1_STATUS.json:33` |

## Post-filter observation window definition

- `post_filter_window_start_utc = 2026-05-14T22:40:46Z` (matches the
  Codex direct-fix completion timestamp).
- `post_filter_window_end_utc = 2026-05-15T02:00:11Z` (latest
  `paper_shadow_observation_status.json` `generated_at`).
- `post_filter_window_seconds ≈ 11 965` (≈ 3h 19m).
- `pre_filter_window_start_utc = 2026-05-13T07:21:34Z`
  (`paper_shadow_observation_started_at`).
- `pre_filter_window_seconds ≈ 141 552` (≈ 39h 19m before activation).

The 1h shadow rollup (latest 1h ending 2026-05-15T02:00:11Z) is
fully inside the post-filter window. The 6h rollup straddles the
filter activation (~3h pre + ~3h post) but its allow/deny/fill
distribution shows fills already at zero — consistent with the
filter being live and effective end-to-end.

## Post-filter fill / denial / churn / fee evidence (raw)

Source: `v2/runtime/paper_shadow_observation/latest/paper_shadow_observation_status.json`
(generated_at `2026-05-15T02:00:11Z`).

### 1h window (fully post-filter)

| Field | Value | Line |
| --- | --- | --- |
| event_count | 109 | 47 |
| simulated_fills | 0 | 56 |
| allowed_intents | 0 | 39 |
| blocked_intents | 109 | 40 |
| reason_distribution.deny_canary_profile_tightening | 102 | 53 |
| reason_distribution.deny_low_confidence | 3 | 54 |
| reason_distribution.deny_orchestrator_held | 4 | 55 |
| paper_pnl_delta_usdt | 0.0 | 50 |
| paper_pnl_delta_status | `CURRENT_WINDOW_PNL_AVAILABLE` | 49 |
| symbol_distribution | `{"BTCUSDT": 109}` | 58 |
| window_complete | true | 60 |

### 6h window (mixed pre/post-filter)

| Field | Value | Line |
| --- | --- | --- |
| event_count | 654 | 96 |
| simulated_fills | 0 | 110 |
| allowed_intents | 0 | 92 |
| blocked_intents | 654 | 93 |
| reason_distribution.deny_canary_profile_tightening | 596 | 105 |
| reason_distribution.deny_low_confidence | 37 | 106 |
| reason_distribution.deny_orchestrator_held | 19 | 107 |
| reason_distribution.deny_stale_market_feed | 2 | 108 |
| paper_pnl_delta_usdt | 0.0 | 102 |
| symbol_distribution | `{"BTCUSDT": 654}` | 112 |

### 24h window (predominantly pre-filter)

| Field | Value | Line |
| --- | --- | --- |
| event_count | 2 618 | 73 |
| simulated_fills | 775 | 84 |
| allowed_intents | 775 | 64 |
| blocked_intents | 1 843 | 65 |
| reason_distribution.allow_proceed_long | 402 | 78 |
| reason_distribution.allow_proceed_short | 373 | 79 |
| reason_distribution.deny_canary_profile_tightening | 1 616 | 80 |
| reason_distribution.deny_low_confidence | 142 | 81 |
| reason_distribution.deny_orchestrator_held | 82 | 82 |
| reason_distribution.deny_stale_market_feed | 3 | 83 |
| paper_pnl_delta_usdt | -7.74 | 75 |

The 24h `paper_pnl_delta_usdt = -7.74` is dominated by the pre-filter
fills counted into the rollup; it does not represent post-filter
behavior.

### v2_paper_execution_worker post-filter snapshot

Source: `v2/runtime/v2_paper_execution_worker/latest/v2_paper_execution_worker_status.json`
(`last_run_ts = 2026-05-14T22:42:09Z`, ~83 s after filter wire).

| Field | Value | Line |
| --- | --- | --- |
| live_gate | `blocked_human_only` | 98 |
| live_symbols | `[]` | 100 |
| current_paper_equity | 10000.0 | 11 |
| current_paper_pnl | 0.0 | 12 |
| decisions_processed_total | 0 | 12 |
| fills_processed_total | 0 | 41 |
| fills_recorded_total | 0 | 42 |
| denials_recorded_total | 0 | 16 |
| denials_breakdown | `{"deny_default": 1}` | 13-15 |
| paper_filter_profile | `paper_canary_aligned_filter_v1` | 112 |
| paper_filter_source | `V2_CANARY_PROFILE_TIGHTENING` | 116 |
| paper_filter_safe_for_live | false | 115 |
| missing_runtime_evidence | true | 101 |
| runtime_evidence_status | `MISSING_RUNTIME_EVIDENCE` | 121 |

## PnL split: pre-filter vs post-filter

| Bucket | PnL (USDT) | Window | Source |
| --- | --- | --- | --- |
| Cumulative paper PnL (pre + post) | -49.12 | 2026-05-13T07:21:34Z → 2026-05-15T02:00:11Z | `paper_shadow_observation_status.json:19` |
| 24h delta (mostly pre-filter, plus ~3h post) | -7.74 | last 24h | `paper_shadow_observation_status.json:75` |
| 6h delta (≈3h pre + ≈3h post around activation) | 0.0 | last 6h | `paper_shadow_observation_status.json:102` |
| 1h delta (fully post-filter) | 0.0 | last 1h | `paper_shadow_observation_status.json:50` |
| Post-filter realized fills | 0 USDT (no fills) | 2026-05-14T22:40:46Z → 2026-05-15T02:00:11Z | derived from 1h+6h windows showing 0 simulated_fills |
| Post-filter fees / slippage / funding bleed | 0.0 USDT (no fills, no fees) | same | derived; `simulated_fills=0` ⇒ no fee accrual |
| Post-filter churn (flip / same-symbol-same-direction) | 0 events | same | derived; `simulated_fills=0` ⇒ no churn |

The `-49.12 USDT` figure is **pre-filter cumulative paper PnL** and
must NOT be presented as post-filter PnL. Post-filter PnL delta to
date is `0.0 USDT` because no new fills have been allowed.

## Blocker impact summary

- `paper_canary_aligned_filter_v1` is correctly attached to the
  paper-fill boundary inside `v2_paper_execution_worker.py` per the
  Codex direct-fix report (lines 5–17 of
  `CODEX_DIRECT_FIX_REPORT.md`).
- It blocks fills with reason
  `denied_by_paper_filter` / `deny_canary_profile_tightening` and the
  worker emits `paper_filter_profile`, `paper_filter_applied`,
  `paper_filter_denied`, `paper_filter_classification`, blocker, cost,
  confidence, and recent-fill evidence fields.
- Within the post-filter observation window, every BTCUSDT paper
  intent has been blocked (102/109 by canary tightening in the last
  1h, 596/654 in the last 6h). No new simulated fill was recorded
  by either the paper shadow observation rollup or the paper
  execution worker since `2026-05-14T22:40:46Z`.
- Therefore: the post-filter window has prevented fee bleed
  (`fees_post_filter = 0`) and churn (`churn_events_post_filter = 0`)
  by the strongest possible mechanism — disallowing fills entirely.
- However, **edge has not been proven positive**, because there are
  zero post-filter realized PnL outcomes to evaluate against. Edge
  remains pending and depends on further evidence:
  - the canary profile tightening over-blocking issue
    (`tightened_allowed_fills=0` in
    `claude_worklog/final_readiness/paper_strategy_edge_tightening/latest/tightened_profile_evaluation.json`)
    being resolved so a small, safe number of high-quality fills can
    occur in paper, and
  - sufficient post-filter fill volume + positive 6h/24h PnL to
    satisfy
    `minimum_confidence_bucket_performance_requirement` and
    `require_positive_6h_or_24h_paper_result_before_canary` from
    `canary_profile_tightening_proposal.options`.

## Current shutdown blockers still in force

From
`claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/codex_shutdown_takeover_status.json`
as of `2026-05-15T02:00:05Z`:

- `LEGACY_LOG_CONFIDENCE_CALIBRATION_DERIVED`
- `LEGACY_LOG_FEATURE_ATTRIBUTION_INCOMPLETE`
- `LEGACY_LOG_FEATURE_SNAPSHOT_ID_DERIVED`
- `PAPER_PNL_NEGATIVE_BLOCKS_CANARY`
- `PAPER_EDGE_UNPROVEN`
- `TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY`

The older `WRAPPER_NOT_LEGACY_HYBRID_PARITY` and stale public artifact
blockers are not part of the current controller blocker set. They are
not reintroduced by this packet.

## Classification rationale

Available classifications:

- `POST_FILTER_EDGE_PENDING` — filter active, observation window
  too short / too sparse to either confirm or refute edge yet.
- `POST_FILTER_NO_UNSAFE_FILLS` — filter active, all unsafe-looking
  fills blocked, no fills permitted.
- `POST_FILTER_POSITIVE_EDGE_PROVEN` — sufficient post-filter fills
  exist with positive realized PnL after fees.
- `POST_FILTER_EDGE_STILL_UNPROVEN` — post-filter window has
  enough fills but they are not positive-edge.

The post-filter window is only ~3h 16m long. The 1h fully
post-filter rollup shows 0 fills and 0 PnL delta. The 6h rollup
spanning activation also shows 0 fills. The worker has 0 fills
recorded. There is therefore not enough post-filter realized
outcome to either prove positive edge or to refute it. The filter
is also currently over-blocking (allowed_fills_in_post_filter_1h=0,
6h=0), which prevents collecting positive-edge evidence.

Resulting classification: **POST_FILTER_EDGE_PENDING**.

This task does NOT:

- declare paper edge proven,
- treat the cumulative `-49.12 USDT` as post-filter PnL,
- approve canary, live, or legacy shutdown,
- create a final approval token,
- create a Redis trim approval token,
- mutate the legacy bot, old Redis, exchange state, leverage, or
  margin mode.

## Safety attestations

- live_gate: `blocked_human_only`
- live_symbols: `[]`
- final_approval_token: absent
- redis_trim_approval: absent
- legacy_mutation: none
- old_redis_write: none
- exchange_action: none
- leverage_change: none
- margin_mode_change: none
- old_negative_pnl_mislabeled_post_filter: false (cumulative
  `-49.12` is reported as pre-filter cumulative; post-filter delta
  is reported as `0.0`)
- paper_edge_proven_without_post_filter_evidence: false

## Verification commands

- `cat v2/runtime/v2_paper_execution_worker/latest/v2_paper_execution_worker_status.json`
- `cat v2/runtime/paper_shadow_observation/latest/paper_shadow_observation_status.json`
- `cat claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/codex_direct_fixes/codex_wire_paper_canary_aligned_filter_v1/codex_wire_paper_canary_aligned_filter_v1_STATUS.json`
- `cat claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/codex_direct_fixes/codex_wire_paper_canary_aligned_filter_v1/CODEX_DIRECT_FIX_REPORT.md`
- `cat claude_worklog/final_readiness/paper_strategy_edge_tightening/latest/operator_dashboard_payload.json`
