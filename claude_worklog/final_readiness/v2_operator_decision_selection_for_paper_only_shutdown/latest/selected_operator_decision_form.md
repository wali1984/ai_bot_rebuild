# Selected Operator Decisions — Paper-Only Legacy Shutdown

Generated: 2026-05-25T05:45:00Z
Git HEAD: 10513bbe0517fd81c9c87e4672bb15486a083c02
Lane: `v2_operator_decision_selection_for_paper_only_shutdown`
GO/NO-GO: `V2_OPERATOR_DECISION_SELECTION_FOR_PAPER_ONLY_SHUTDOWN_READY`
Upstream Codex gate: `V2_OPERATOR_PAPER_ONLY_SHUTDOWN_DECISION_CAPTURE_CODEX_PASS`

This file records the operator's selection of one option per blocker. It is
selection recording only.

## Required Safety Text (verbatim)

- This is not shutdown approval.
- This is not live approval.
- This is not Redis trim approval.
- This does not change leverage/margin.
- Legacy keeps running.
- `live_gate=blocked_human_only`
- `live_symbols=[]`

## Acceptance File Status

- Path: `claude_worklog/approvals/OPERATOR_ACCEPTS_V2_PAPER_ONLY_SHUTDOWN_LIMITATIONS.md`
- Present: false
- Created by this lane: false (this lane does not, and may not, create it)

## Selection Summary

- decision_count: 9
- operator_selected_count: 9
- operator_accepted_count: 0  (none chose ACCEPT_FOR_PAPER_ONLY_SHUTDOWN)
- REQUIRE_IMPLEMENTATION_BEFORE_SHUTDOWN: 5
- DEFER_KEEP_LEGACY_RUNNING: 4
- ACCEPT_FOR_PAPER_ONLY_SHUTDOWN: 0
- final_recommendation: `BLOCK_LEGACY_SHUTDOWN_PRODUCTION_EQUIVALENCE_INCOMPLETE`

## Selections

| # | Blocker | Selected option | operator_accepted |
| - | --- | --- | --- |
| 1 | `full_observation_builder.operator_decision_families` | REQUIRE_IMPLEMENTATION_BEFORE_SHUTDOWN | false |
| 2 | `checkpoint_promotion` | REQUIRE_IMPLEMENTATION_BEFORE_SHUTDOWN | false |
| 3 | `legacy_shutdown.legacy_runtime_owner` | DEFER_KEEP_LEGACY_RUNNING | false |
| 4 | `legacy_shutdown.legacy_redis_keys_active` | DEFER_KEEP_LEGACY_RUNNING | false |
| 5 | `risk_caps_canary_hard_gates_unset` | REQUIRE_IMPLEMENTATION_BEFORE_SHUTDOWN | false |
| 6 | `capital_recovery_gate_unset` | REQUIRE_IMPLEMENTATION_BEFORE_SHUTDOWN | false |
| 7 | `full_observation_builder.external_sources` | DEFER_KEEP_LEGACY_RUNNING (promotes to REQUIRE_IMPLEMENTATION_BEFORE_SHUTDOWN if paper-edge proof requires it) | false |
| 8 | `full_observation_builder.event_dependent` | DEFER_KEEP_LEGACY_RUNNING (watchers active) | false |
| 9 | `paper_edge_not_proven` | REQUIRE_IMPLEMENTATION_BEFORE_SHUTDOWN | false |

## Per-Item Selection Detail

### 1. `full_observation_builder.operator_decision_families`

- Selected: `REQUIRE_IMPLEMENTATION_BEFORE_SHUTDOWN`
- Reason: Paper-edge thresholds and unified-feature acceptance must be
  implemented with raw evidence before any paper-only shutdown is captured.
- Effect: Implementation/evidence work required; legacy continues to run.

### 2. `checkpoint_promotion`

- Selected: `REQUIRE_IMPLEMENTATION_BEFORE_SHUTDOWN`
- Reason: Checkpoint weight blob promotion must be signed with raw weight
  lineage before paper-only shutdown is captured.
- Effect: Checkpoint promotion runbook must complete with operator
  signature; legacy continues to run.

### 3. `legacy_shutdown.legacy_runtime_owner`

- Selected: `DEFER_KEEP_LEGACY_RUNNING`
- Reason: No stop intent is captured. Legacy runtime owner continues to
  operate. This lane never stops legacy.
- Effect: Legacy keeps running. Dual-system overhead continues.

### 4. `legacy_shutdown.legacy_redis_keys_active`

- Selected: `DEFER_KEEP_LEGACY_RUNNING`
- Reason: No Redis trim intent is captured. Legacy Redis remains active.
  This lane never writes to old Redis or trims keys.
- Effect: Legacy Redis keeps its keys. No trim. No write.

### 5. `risk_caps_canary_hard_gates_unset`

- Selected: `REQUIRE_IMPLEMENTATION_BEFORE_SHUTDOWN`
- Reason: Operator-signed numeric risk caps and canary hard gates must
  exist before paper-only shutdown is captured, even though live remains
  blocked.
- Effect: Numeric caps and gates must be set with operator signature before
  any future canary attempt.

### 6. `capital_recovery_gate_unset`

- Selected: `REQUIRE_IMPLEMENTATION_BEFORE_SHUTDOWN`
- Reason: Operator-signed numeric capital recovery threshold and risk
  guard must exist before paper-only shutdown is captured.
- Effect: Capital recovery threshold and risk guard implementation
  required; live remains blocked.

### 7. `full_observation_builder.external_sources`

- Selected: `DEFER_KEEP_LEGACY_RUNNING`
- Conditional promotion: promotes to `REQUIRE_IMPLEMENTATION_BEFORE_SHUTDOWN`
  if operator paper-edge proof requires `onchain_btc`, `onchain_eth`, or
  `unified_feature_family.token_metrics` to satisfy `paper_edge_not_proven`.
- Reason: Default-defer external sources. If paper-edge proof depends on
  them, the selection auto-promotes.
- Effect: External-source adoption deferred by default. Full-observation
  builder continues with documented external-source gap. No env-var values
  are read.

### 8. `full_observation_builder.event_dependent`

- Selected: `DEFER_KEEP_LEGACY_RUNNING`
- Watcher state: ACTIVE (`event_watcher_1_liquidation_source` continues)
- Reason: Defer with watchers active. No synthetic completion is permitted.
- Effect: Liquidation-event watcher continues to wait for real per-symbol
  evidence. Legacy keeps running.

### 9. `paper_edge_not_proven`

- Selected: `REQUIRE_IMPLEMENTATION_BEFORE_SHUTDOWN`
- Reason: After-cost expectancy is negative; CI lower bound is negative;
  minimum sample not satisfied; operator thresholds unset. Paper-only
  shutdown cannot be captured until operator numeric thresholds exist AND
  statistically defensible positive after-cost paper/shadow expectancy is
  observed.
- Effect: Paper-edge proof work must complete with operator thresholds
  before paper-only shutdown is captured.

## Downstream Consistency

- `final_paper_only_shutdown_decision` remains
  `OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN` (no acceptance
  file).
- `final_shutdown_recommendation` remains
  `BLOCK_LEGACY_SHUTDOWN_PRODUCTION_EQUIVALENCE_INCOMPLETE`.
- `live_gate` remains `blocked_human_only`. `live_symbols` remains `[]`.
- No `OPERATOR_ACCEPTS_V2_PAPER_ONLY_SHUTDOWN_LIMITATIONS.md` is created
  by this lane.
- No live/canary/shutdown/Redis-trim approval artifact is created.

## Verification

```text
python3 -c "import json; d=json.load(open('claude_worklog/final_readiness/v2_operator_decision_selection_for_paper_only_shutdown/latest/operator_decision_selection_status.json')); assert d['operator_selected_count']==9 and d['operator_accepted_count']==0 and d['decision_count']==9 and d['operator_acceptance_file_present'] is False and d['final_recommendation']=='BLOCK_LEGACY_SHUTDOWN_PRODUCTION_EQUIVALENCE_INCOMPLETE' and d['live_gate']=='blocked_human_only' and d['live_symbols']==[]; print('OK')"

ls claude_worklog/approvals/OPERATOR_ACCEPTS_V2_PAPER_ONLY_SHUTDOWN_LIMITATIONS.md 2>&1 || echo 'acceptance_file_absent_as_expected'

jq empty \
  claude_worklog/final_readiness/v2_operator_decision_selection_for_paper_only_shutdown/latest/*.json \
  v2/frontend/public/v2_operator_decision_selection_for_paper_only_shutdown/latest/*.json
```
