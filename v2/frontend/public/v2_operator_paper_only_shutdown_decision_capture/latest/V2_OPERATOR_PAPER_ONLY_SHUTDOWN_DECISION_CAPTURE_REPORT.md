# V2 Operator Paper-Only Shutdown Decision Capture

Generated: 2026-05-25T05:30:00Z
Git HEAD: 10513bbe0517fd81c9c87e4672bb15486a083c02
Lane: `v2_operator_paper_only_shutdown_decision_capture`
GO/NO-GO: `V2_OPERATOR_PAPER_ONLY_SHUTDOWN_DECISION_CAPTURE_READY`

This packet captures the operator decisions required before any paper-only
legacy-shutdown decision can be recorded. It is a decision-capture surface
only.

## What This Packet Does NOT Do

- It does not approve live trading.
- It does not approve canary.
- It does not approve Redis trim.
- It does not approve exchange mutation.
- It does not change leverage or margin.
- It does not stop legacy.
- It does not stop V2 runtime.
- It does not write to old Redis.
- It does not call any exchange-mutation API.
- It does not create any approval token or approval artifact.

`live_gate=blocked_human_only`. `live_symbols=[]`.

## Inputs (raw evidence sources)

- `claude_worklog/final_readiness/v2_final_operator_decision_and_event_watcher_execution/latest/final_operator_decision_center.json`
- `claude_worklog/final_readiness/v2_final_operator_decision_and_event_watcher_execution/latest/final_shutdown_recommendation.json`
- `claude_worklog/final_readiness/v2_final_operator_decision_and_event_watcher_execution/latest/external_source_decision_execution_status.json`
- `claude_worklog/final_readiness/v2_final_operator_decision_and_event_watcher_execution/latest/event_dependent_watcher_runtime_status.json`
- `claude_worklog/final_readiness/v2_final_production_equivalence_blocker_resolution_sprint/latest`

Upstream recommendation:
`BLOCK_LEGACY_SHUTDOWN_PRODUCTION_EQUIVALENCE_INCOMPLETE`.

## Summary

- decision_count: 9
- operator_accepted_count: 0
- operator_selected_count: 0
- paper_only_shutdown_acceptance_artifact_present: false
- shutdown_safe: false
- legacy_shutdown_ready: false
- live_ready: false
- canary_ready: false
- paper_edge_proven: false
- external_source_state: SOURCE_MISSING_KEY_OPERATOR_REQUIRED
- event_watcher_count: 2
- event_watchers_completed: 0
- final_recommendation: OPERATOR_DECISION_CAPTURE_PENDING_LEGACY_SHUTDOWN_BLOCKED

## Items Captured

For each of the nine items, the JSON packet records: current evidence, why it
blocks shutdown/live, option A (`ACCEPT_FOR_PAPER_ONLY_SHUTDOWN`), option B
(`REQUIRE_IMPLEMENTATION_BEFORE_SHUTDOWN`), option C
(`DEFER_KEEP_LEGACY_RUNNING`), the recommended conservative default, risk if
accepted, risk if deferred, and `operator_selected_option=null` /
`operator_accepted=false`.

1. `full_observation_builder.operator_decision_families` — paper-edge
   threshold and unified-feature acceptance. Default: DEFER.
2. `checkpoint_promotion` — checkpoint/model promotion limitation. Default:
   DEFER.
3. `legacy_shutdown.legacy_runtime_owner` — legacy runtime stop acceptance.
   Default: DEFER.
4. `legacy_shutdown.legacy_redis_keys_active` — legacy Redis trim / retention
   decision. Default: DEFER. The capture packet does not trim Redis or write
   to old Redis.
5. `risk_caps_canary_hard_gates_unset` — risk/capital caps and canary hard
   gates. Default: DEFER.
6. `capital_recovery_gate_unset` — capital recovery threshold / risk guard
   acceptance. Default: DEFER.
7. `full_observation_builder.external_sources` — external source adoption
   (onchain_btc, onchain_eth, unified_feature_family.token_metrics). The
   packet checks env-var names only; it does not read or store raw secret
   values. Default: DEFER.
8. `full_observation_builder.event_dependent` — event-dependent liquidation /
   full-observation watcher. Watcher remains active and has not observed
   real per-symbol liquidation evidence. Default: DEFER.
9. `paper_edge_not_proven` — paper-edge proof watcher. After-cost expectancy
   is negative; CI lower bound is negative; minimum sample not satisfied;
   operator thresholds unset. Default:
   REQUIRE_IMPLEMENTATION_BEFORE_SHUTDOWN.

## How Operator Records Decisions

1. Open `operator_decision_form.md` in this directory.
2. For each of the nine items, write `A`, `B`, or `C` under
   `operator_selected_option`.
3. Update `paper_only_shutdown_decision_capture.json` (or sign a follow-up
   acceptance artifact) so that `operator_selected_option`,
   `operator_accepted`, `operator_signed_at_utc`, and
   `operator_signature_artifact_path` reflect operator intent.
4. Sign the acceptance file at
   `claude_worklog/approvals/OPERATOR_ACCEPTS_V2_PAPER_ONLY_SHUTDOWN_LIMITATIONS.md`
   with the required positive language and no forbidden language. The
   downstream `final_paper_only_shutdown_decision` verifier enforces literal
   presence/absence.

Until the acceptance file is present and the verifier passes, the downstream
`final_paper_only_shutdown_decision` packet remains
`OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN` and legacy shutdown
stays blocked.

## Required Safety Text (verbatim)

- This does not approve live.
- This does not approve canary.
- This does not approve Redis trim.
- This does not approve exchange mutation.
- This does not change leverage/margin.
- This is paper-only shutdown decision capture.

## Safety Posture

- live_gate: blocked_human_only
- live_symbols: []
- approves_live: false
- approves_canary: false
- approves_legacy_shutdown: false
- approves_redis_trim: false
- writes_old_redis: false
- calls_exchange_mutation: false
- creates_approval_tokens: false
- creates_approval_artifacts: false
- fabricates_edge: false
- fabricates_missing_observations: false
- modifies_legacy_repo: false
- stops_legacy: false
- stops_v2_runtime: false

## Verification

```text
python3 -c "import json; d=json.load(open('claude_worklog/final_readiness/v2_operator_paper_only_shutdown_decision_capture/latest/paper_only_shutdown_decision_capture.json')); assert d['operator_accepted_count']==0 and d['operator_selected_count']==0 and len(d['decisions'])==9 and all(x['operator_selected_option'] is None and x['operator_accepted'] is False for x in d['decisions']); print('OK')"

python3 -c "import json,glob; [json.load(open(p)) for p in glob.glob('claude_worklog/final_readiness/v2_operator_paper_only_shutdown_decision_capture/latest/*.json')]; print('OK')"

ls claude_worklog/approvals/OPERATOR_ACCEPTS_V2_PAPER_ONLY_SHUTDOWN_LIMITATIONS.md 2>&1 || echo 'acceptance_file_absent_as_expected'

rg -n "truthy live/canary/shutdown/Redis-trim approval marker" claude_worklog/final_readiness/v2_operator_paper_only_shutdown_decision_capture/latest/ || echo 'no_forbidden_approval_tokens'
```

Expected results: JSON validates; acceptance artifact absent; no forbidden
approval token literals in the lane.
