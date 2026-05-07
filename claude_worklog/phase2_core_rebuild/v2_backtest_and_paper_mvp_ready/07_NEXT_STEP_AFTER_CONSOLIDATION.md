# Next Steps After V2_BACKTEST_AND_PAPER_MVP_READY

The `V2_BACKTEST_AND_PAPER_MVP_READY` consolidation gate closes REQ_0017 milestone 8 of 8 and frees the planner to open evidence-collection and explainability lanes that depend on the seven typed surfaces. The live-readiness gate remains a separate downstream artifact requiring explicit human approval; the lanes below are non-live by construction.

## Next planner-eligible lanes (post-consolidation)

Per REQ_0018 / REQ_0020 lane policy, until the live-readiness gate review (`FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`) is requested, the planner remains restricted to the four approved lanes (`paper_backtest_mvp`, `explainability_ui`, `codex_watchdog`, `legacy_parity`). The consolidation gate does NOT add a new approved lane and does NOT remove any existing restriction. Within the existing lanes the following next-step categories become eligible:

### Lane A — paper_backtest_mvp (post-consolidation evidence collection per REQ_0020 § "Required proof before live")

Each next-step task must continue to declare `lane`, `mvp_relevance`, `blocked_by`, `next_gate`, `legacy_evidence_consulted`, and `legacy_failure_addressed` per the standing planner-lane lock.

- Replay-case authoring: instantiate the LAB hedge-unwind / squeeze replay case (REQ_0022 § "Required replay/backtest case") through the typed `ReplayBacktestRunner` composition root binder. The case is authored as test fixtures / replay inputs that drive the existing typed surfaces; no new code surface beyond fixtures and per-case typed input records.
- Paper-mode evidence-collection harness: a non-live, non-FastAPI, non-scheduler harness that replays a sequence of typed prediction inputs through the existing typed surfaces and records the resulting `PaperExecutionLedgerEntry` mirror sequence and `ReplayBacktestSummary` for offline inspection. The harness must remain a pure-function pipeline; it must NOT introduce a scheduler, a background loop, a FastAPI surface, persistence, or a Redis adapter at this stage.
- Shadow-mode evidence-collection harness: a non-live, non-FastAPI, non-scheduler harness that, gated on `SHADOW_MODE_READY`, replays a sequence of typed prediction inputs through the existing typed surfaces and produces a per-step comparison record alongside the legacy action evidence pulled from read-only legacy logs. No `shadow_decision_id` lineage row is introduced at this stage; the comparison record is per-step typed pairs of `(legacy_action_evidence_pointer, V2_RiskDecisionRecord)`. Adding a `shadow_decision_id` lineage row is a separate, later milestone explicitly out of scope at this stage.
- 30-day historical PnL audit (REQ_0024) wiring: read-only collection of legacy realized PnL / fees / funding / commission / trade history per REQ_0024 scope, with the typed `RiskDecisionRecord` / `PaperExecutionLedgerEntry` typed surfaces driving the per-trade replay comparison.

### Lane B — explainability_ui (post-consolidation; backed only by real lineage)

Per REQ_0018 lane B and REQ_0009 § "Required UI visibility", explainability UI work becomes eligible only when backed by real lineage IDs. At consolidation HEAD the eligible lineage is exactly:

- `feature_snapshot_id`, `prediction_id` (milestone 1 lineage IDs).
- The implicit per-record identity of `OrchestratorDecisionRecord`, `RiskDecisionRecord`, `PaperExecutionLedgerEntry`, `ReplayBacktestStep`, `ReplayBacktestSummary` (mirror-row identity).

Frontend / website pages may be authored that surface these typed records and pattern-match on the typed action / reason constants. Per REQ_0008 enterprise website design and REQ_0009 explainability, polished animation work remains forbidden until real backend contracts back the data; the typed surfaces certified by this consolidation are the real backend contracts.

`shadow_decision_id`, `execution_intent_id`, and standalone `paper_trade_id` lineage rows do NOT exist at consolidation HEAD; UI panels keyed on those lineage rows must wait for downstream lineage milestones explicitly out of scope at this consolidation.

### Lane C — codex_watchdog (continuous)

Codex watchdog continues per REQ_0011 / REQ_0014 / REQ_0016 / REQ_0021 to:
- Diagnose and recover non-live `human_attention_required` blockers.
- Recover dirty-tree dispatch holds within the allowed autofix scope.
- Reconcile stale queue / current_status / dashboard noise against PASS evidence.
- Run Codex re-review and harden tests for committed milestones.

### Lane D — legacy_parity (read-only continuation per REQ_0019 / REQ_0020 / REQ_0023)

Read-only legacy audit / preservation / parity mapping continues per REQ_0019 and REQ_0023, including the legacy_readonly_audit sentinel artifacts and the historical PnL audit per REQ_0024 (read-only Binance USD-M Futures account-history endpoints; no live action; no order; no leverage / margin change; no Redis writes).

## Sequencing rule for the next planner turn

The next planner turn opens after the V2_BACKTEST_AND_PAPER_MVP_READY consolidation packet is committed and supervisor task 162 has produced its Codex review marker (`V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS` or `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_FAIL` with autofix-eligible blockers). On Codex PASS, the planner selects the next eligible lane A task per the categories above (highest priority: replay-case authoring for the LAB hedge-unwind / squeeze case per REQ_0022). On Codex FAIL with concrete documentation blockers, the planner queues a REQ_0007 / REQ_0014 autofix scoped to this consolidation packet only.

## Live-gate posture (restated)

Live trading remains blocked. The consolidation marker does not advance the live-readiness gate. `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` remains a separate downstream artifact requiring explicit human approval, and is NOT requested by this consolidation.

V2_BACKTEST_AND_PAPER_MVP_READY_NEXT_STEP_READY
END_FILE: claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/07_NEXT_STEP_AFTER_CONSOLIDATION.md
