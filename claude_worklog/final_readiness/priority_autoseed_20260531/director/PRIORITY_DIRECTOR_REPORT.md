# Priority Director Report — Legacy Audit Omission Closure (2026-05-31)

## Scope
Director task: `claude_priority_director_legacy_audit_omission_closure_20260531`.
Operates only inside `AI BOT REBUILD`. Live remains `blocked_human_only`.
No legacy mutation, no old-Redis writes, no exchange action.

## Inputs
- Dispatch packet: `claude_worklog/final_readiness/priority_autoseed_20260531/latest/PRIORITY_AUTONOMOUS_DISPATCH_PACKET.json` (11 autoseeded omissions).
- Runtime evidence baseline: `V2_VS_LEGACY_AUDIT_2026-05-31.md` (legacy stopped 2026-05-26; V2 partial coverage).
- Task descriptors: `claude_worklog/agent_supervisor/tasks/claude_priority_*_20260531.json` (11 omission tasks + 1 director task).

## Coverage Result
- Omissions represented: 11/11 (each has a task descriptor, allowed output prefixes, required output files, and prompt explicitly demanding exact blocker + evidence pointer).
- Legacy audit items covered: 15/15 (mapped against the V2-vs-Legacy audit Shutdown Readiness scorecard).
- Data sources validated: 23/23 (each tagged PASS / BLOCKED / MISSING_EVIDENCE).
- Omission blocker ledger entries: 11/11 (each has an exact blocker, an evidence pointer, and an owner).

## Gate Determination
Acceptance criteria status:
- every_legacy_audit_item_represented: **true**
- every_data_source_validated: **true**
- every_omission_has_exact_blocker: **true**
- website_displays_true_state: **false** (depends on still-pending `claude_priority_website_stale_incorrect_page_20260531`)

Gate: **PRIORITY_OMISSION_CLOSURE_BLOCKED**.

The director cannot emit READY because:
1. The website truth payload alignment task is still pending. Until that task emits READY, V2 dashboards may continue to render stale or incorrect cards against runtime evidence.
2. 8 of 11 omissions are pending dispatch (only `feature_ta_missing_fields`, `backtest_not_run`, and the director itself are running). Until each pending task either resolves to READY or stamps a final BLOCKED, omission closure is incomplete by definition.
3. Two root-cause omissions (`feature_ta_missing_fields` and `trainer_data_feed_gaps`) depend on capabilities that runtime evidence proves missing (V2 unified features 14/562 fields; V2 RL core 0/6 components; signals:trading:primary frozen since 2026-05-13). These cannot be closed in this conversation without rebuilding the trainer and feature pipeline — which is itself bounded by the protected-runtime policy in `CLAUDE.md`.

## Constraints Respected
- No writes to legacy paths.
- No old-Redis writes from V2 director output.
- All emitted artifacts confined to `claude_worklog/final_readiness/priority_autoseed_20260531/director/`.
- All emitted files via BEGIN_FILE / END_FILE only (harness materializes).

## Next Recommended Action
Keep the supervisor dispatching the 8 pending omission tasks. After each emits its REPORT/STATUS/GO_NO_GO, re-run the director so the coverage matrix and blocker ledger reflect the new state. The director should be re-fired automatically once any sub-task's `status` transitions out of `pending`.
