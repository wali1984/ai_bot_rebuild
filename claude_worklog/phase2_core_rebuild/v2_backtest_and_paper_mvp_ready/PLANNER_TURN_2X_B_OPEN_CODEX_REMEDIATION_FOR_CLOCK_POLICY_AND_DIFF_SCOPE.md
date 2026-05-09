# Planner Turn — Phase 2X.B Open Codex Remediation for Clock Policy and Diff Scope

## Trigger

Phase 2X external manual position quarantine domain Codex review marker at `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/09_2X_EXTERNAL_MANUAL_POSITION_QUARANTINE_DOMAIN_CODEX_GO_NO_GO.md` is `PHASE2X_EXTERNAL_MANUAL_POSITION_QUARANTINE_DOMAIN_CODEX_FAIL`. Phase 2X local validation marker at `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/07_GO_NO_GO.md` is `PHASE2X_EXTERNAL_MANUAL_POSITION_QUARANTINE_DOMAIN_IMPL_AND_VALIDATION_PASSED`. Phase 2X composition layer source `v2/backend/app/composition/external_manual_position_quarantine/runtime.py` invokes the supplied clock once per runtime call inside `_external_manual_position_quarantine_now`, and the test `v2/backend/tests/unit/composition/external_manual_position_quarantine/test_runtime_invokes_clock_exactly_once_per_call.py` asserts `calls == 1`. The implementation report at `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/06_IMPLEMENTATION_REPORT.md` already states the runtime "does not invoke the supplied clock at build time or per runtime call because `risk_decision_ts_ms` remains authoritative in Phase 2X". The code and test contradict the report and the Codex review gate.

## Codex review blockers cited

Two blockers are recorded in `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/08_2X_EXTERNAL_MANUAL_POSITION_QUARANTINE_DOMAIN_CODEX_REVIEW.md`:

- Step 6 runtime-clock policy: the implementation invokes `_now_ms_clock()` per runtime call and the test asserts `calls == 1`; the Phase 2X.B Codex policy requires zero per-call invocation because `risk_decision_ts_ms` remains authoritative and the clock is reserved for a future timestamping extension.
- Step 10 no-prior-milestone-byte-mutation diff: the exact `git diff --stat HEAD~1..HEAD ...` command is non-empty; it reports `claude_worklog/agent_supervisor/tasks/190_phase2x_external_manual_position_quarantine_domain_codex_review.json` and `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/PLANNER_TURN_2X_DOMAIN_READY_AND_CODEX_REVIEW_QUEUED.md` inside the Phase 2X commit window outside the exclusion set.

## Chosen remediation milestone

Phase 2X.B is the chosen consolidated non-live remediation milestone. It is a single Codex-led concrete blocker fix in the `codex_watchdog` lane, followed by a single Codex re-review task with a tightened `HEAD~1..HEAD` exclusion set. Phase 2X.B does not introduce any execution-side surface, any new lineage ID, any FastAPI lifespan, any Redis adapter, any GPU runner, any model-loading subsystem, any strategy library, or any live-gate flip. Phase 2X.B keeps the `live_blocked == True` invariant at the `ManualPositionFlag` and `ExternalPositionQuarantineRecord` layer.

## Lane and MVP relevance

Lane: `codex_watchdog`. Mvp relevance: Phase 2X is a post-MVP-ready REQ_0013 prerequisite milestone gating SMC liquidity shadow features behind an external/manual position quarantine typed flag; the `RISK_GATEWAY_DEFAULT_DENY_MVP` baseline at `claude_worklog/phase2_core_rebuild/risk_gateway_impl/25_2G_C_RISK_GATEWAY_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` and the LAB hedge-unwind regression scenario at `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/01_LEGACY_FAILURE_EVIDENCE.md` cannot consume the Phase 2X typed flag downstream until the Phase 2X Codex pass marker is recorded. Phase 2X.B unblocks the Phase 2X Codex pass and therefore the post-`V2_BACKTEST_AND_PAPER_MVP_READY` REQ_0013 phase-1 quarantine prerequisite. No new MVP path is opened; Phase 2X.B is strictly a Codex blocker remediation.

## Legacy evidence consulted

- `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md` lines 7-27: LAB hedge-unwind / short-squeeze residual exposure failure case anchoring the typed quarantine flag's regression input.
- `claude_worklog/phase2_core_rebuild/legacy_evidence/02_CURRENT_LEGACY_FAILURE_SIGNALS.md` line 25: classifies "External / manual position quarantine missing" as the RISK_GATEWAY_DEFAULT_DENY_MVP follow-up plus REQ_0013 phase-1 quarantine.
- `claude_worklog/requirements_inbox/REQ_0013_SMC_LIQUIDITY_SHADOW_FEATURES.md` line 31: prohibition on using SMC features to justify DCA/hedging/rescue/risk-add on manual or external positions, which the typed `ManualPositionFlag` enforces downstream.
- `claude_worklog/requirements_inbox/REQ_0022_LEGACY_FAILURE_HEDGE_UNWIND_AND_SQUEEZE_RISK.md` lines 26-47: required risk-gateway rules before closing a hedge or protective leg, which the typed quarantine record carries as a downstream-consumable pattern-matchable field.

## Legacy failure addressed

LAB hedge-unwind / short-squeeze residual exposure plus REQ_0013 manual-position SMC misuse safety rule, gated downstream on a typed `ManualPositionFlag` / `ExternalPositionQuarantineRecord` value object that downstream services can pattern-match on once the Phase 2X Codex pass marker is achieved through Phase 2X.B remediation.

## V2 proof gate

Phase 2X.B will produce the marker `PHASE2X_B_EXTERNAL_MANUAL_POSITION_QUARANTINE_REMEDIATION_IMPL_AND_VALIDATION_PASSED` at `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/11_PHASE_2X_B_REMEDIATION_GO_NO_GO.md`, followed by Codex re-review marker `PHASE2X_B_EXTERNAL_MANUAL_POSITION_QUARANTINE_DOMAIN_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/13_2X_B_EXTERNAL_MANUAL_POSITION_QUARANTINE_DOMAIN_CODEX_GO_NO_GO.md`. Phase 2X composition source `v2/backend/app/composition/external_manual_position_quarantine/runtime.py` and Phase 2X composition test `v2/backend/tests/unit/composition/external_manual_position_quarantine/test_runtime_does_not_invoke_clock_per_call.py` will encode the zero-per-call invariant and replace the misnamed `test_runtime_invokes_clock_exactly_once_per_call.py`. Phase 2X.B preserves all other Phase 2X invariants verified PASS in steps 1-5, 7-9, and 11 of the Phase 2X Codex review.

## Tasks emitted this turn

- `claude_worklog/agent_supervisor/tasks/191_phase2x_b_external_manual_position_quarantine_codex_remediation.json` — Codex L1 remediation task patching the per-call clock invariant and emitting Phase 2X.B remediation evidence. `agent: codex`. `lane: codex_watchdog`. `risk_level: L1`. `requires_clean_worktree: true`. Allowed prefixes are scoped to `v2/backend/app/composition/external_manual_position_quarantine/`, `v2/backend/tests/unit/composition/external_manual_position_quarantine/`, and `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/`. Forbidden output paths cover all other v2 source/test directories, all other Phase 2 sibling directories, the legacy bot path, and live/Redis/exchange/deployment surfaces. The prompt instructs Codex CLI to perform a single self-contained commit via `git mv` for the test rename plus content-only edits to `runtime.py`, the new test file, the new `10_PHASE_2X_B_REMEDIATION_REPORT.md`, and the new `11_PHASE_2X_B_REMEDIATION_GO_NO_GO.md` so that the Phase 2X.B `HEAD~1..HEAD` diff is self-contained.
- `claude_worklog/agent_supervisor/tasks/192_phase2x_b_external_manual_position_quarantine_codex_rereview.json` — Codex L1 re-review task that re-runs the Step 1-11 Phase 2X Codex review checklist plus the tightened Step 10 no-prior-milestone-byte-mutation diff with an exclusion set covering `v2/backend/app/composition/external_manual_position_quarantine/`, `v2/backend/tests/unit/composition/external_manual_position_quarantine/`, `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/`, `claude_worklog/agent_supervisor/tasks/191_*.json`, `claude_worklog/agent_supervisor/tasks/192_*.json`, and `claude_worklog/agent_supervisor/tasks/codex_recover_189_*.json`. `agent: codex`. `lane: codex_watchdog`. `risk_level: L1`. Required outputs are `12_2X_B_EXTERNAL_MANUAL_POSITION_QUARANTINE_DOMAIN_CODEX_RE_REVIEW.md` and `13_2X_B_EXTERNAL_MANUAL_POSITION_QUARANTINE_DOMAIN_CODEX_GO_NO_GO.md`.

## Hard safety boundaries reasserted

- Do not modify `/home/wali/Desktop/AI BOT`.
- Do not write or delete any Redis key.
- Do not restart any live service.
- Do not place or cancel exchange orders.
- Do not change leverage or margin.
- Do not enable live trading.
- Do not deploy.
- Do not run a production migration.
- Do not expose or commit any secret value.
- Do not approve the live gate.
- Do not introduce any execution-side surface in Phase 2X.B.
- Do not introduce any new lineage ID in Phase 2X.B.
- Do not modify any Phase 2X documentation file already certified PASS in steps 11 of the Phase 2X Codex review (`00_PHASE_2X_SCOPE.md` through `09_2X_EXTERNAL_MANUAL_POSITION_QUARANTINE_DOMAIN_CODEX_GO_NO_GO.md`).
- Keep `live_blocked == True` invariant at the `ManualPositionFlag` and `ExternalPositionQuarantineRecord` layer.
- `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` remains blocked and human-only.

PLANNER_TURN_2X_B_OPEN_CODEX_REMEDIATION_FOR_CLOCK_POLICY_AND_DIFF_SCOPE_READY
