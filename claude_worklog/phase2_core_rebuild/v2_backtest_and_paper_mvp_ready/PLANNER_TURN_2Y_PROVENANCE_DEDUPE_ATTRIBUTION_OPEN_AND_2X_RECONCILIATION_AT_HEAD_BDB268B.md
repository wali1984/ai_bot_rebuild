# Planner Turn 2Y — Open Provenance / Dedupe / Attribution Domain and Phase 2X Reconciliation Acknowledged at HEAD bdb268b

## Date
2026-05-09

## HEAD
`bdb268b Build enterprise trading cockpit for V2 operator UI`

## Worktree state at planner turn open
- One untracked task definition file:
  `claude_worklog/agent_supervisor/tasks/parallel_capacity_readonly_review_phase2x_b_external_manual_position_quarantine_remediation_impl_and_valid.json`.
  This is a Codex parallel read-only review task targeting the reconciled Phase 2X.B state. It is an authored queue entry only and contains no source-file mutation. It belongs in `worktree_excluded_paths` for the next implementation task per the standing parallel-capacity convention.
- No active Claude/Codex/Ollama child running.
- No live, legacy, Redis, exchange, deploy, or secret action present.
- All other tracked files clean.

## On-disk gate evidence read at planner turn open
- `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/07_GO_NO_GO.md` — `PHASE2X_EXTERNAL_MANUAL_POSITION_QUARANTINE_DOMAIN_IMPL_AND_VALIDATION_PASSED`.
- `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/11_PHASE_2X_B_REMEDIATION_GO_NO_GO.md` — `PHASE2X_B_EXTERNAL_MANUAL_POSITION_QUARANTINE_REMEDIATION_IMPL_AND_VALIDATION_PASSED`.
- `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/13_2X_B_EXTERNAL_MANUAL_POSITION_QUARANTINE_DOMAIN_CODEX_GO_NO_GO.md` — `PHASE2X_B_EXTERNAL_MANUAL_POSITION_QUARANTINE_DOMAIN_CODEX_FAIL` (caused by re-review command comparing against commit `879063e` where a Codex watchdog refresh of `claude_worklog/historical_pnl_audit/01_DATA_SOURCE_STATUS.md` was bundled into the diff scope).
- `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/14_2X_B_FAIL_RECONCILIATION_CURRENT_HEAD.md` — at `HEAD = 34305f4` the tightened no-prior-milestone byte-mutation command was rerun against `HEAD~1..HEAD` with the 2X.B exclusion set and produced empty stdout; the focused 30-test pytest suite (`v2/backend/tests/unit/{domain,services,composition}/external_manual_position_quarantine/`) passed `30 passed in 0.04s`. Marker line: `PHASE2X_B_EXTERNAL_MANUAL_POSITION_QUARANTINE_CURRENT_HEAD_RECONCILED`.
- `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/15_2X_B_FAIL_RECONCILIATION_GO_NO_GO.md` — `PHASE2X_B_EXTERNAL_MANUAL_POSITION_QUARANTINE_CODEX_FAIL_RECONCILED`.
- `claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/06_PHASE_2W_GO_NO_GO.md` — `PHASE2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT_READY`.
- `claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/08_PHASE_2W_CODEX_GO_NO_GO.md` — `PHASE2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT_CODEX_PASS`.
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/06_GO_NO_GO.md` — `V2_BACKTEST_AND_PAPER_MVP_READY`.
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/10_GO_NO_GO_CODEX.md` — `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS`.
- `claude_worklog/final_readiness/04_GO_NO_GO.md` — `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` (final live gate remains human-only).
- `claude_worklog/final_readiness/enterprise_trading_cockpit/latest/GO_NO_GO.md` — `PHASE2Y_ENTERPRISE_COINANK_STYLE_TRADING_COCKPIT_AND_REALTIME_DATA_READY` (committed as part of `bdb268b`; explainability_ui-lane frontend/operator-cockpit work; not authored by this planner; the marker name overlaps the Phase 2W-recommended `2Y_PROVENANCE_DEDUPE_ATTRIBUTION` typed-contract milestone label, requiring marker-name disambiguation below).

## Phase 2X reconciliation classification
The Codex re-review FAIL recorded in `13_…` is on-disk superseded-by-evidence per the planner profile rule: "GO/NO-GO PASS markers override stale queue/current_status noise; stale tasks become superseded_by_evidence." The 14/15 reconciliation files demonstrate that the FAIL was caused by the re-review's diff-scope comparison reaching into a Codex-watchdog historical-audit refresh outside the Phase 2X typed-contract surface, not by any defect in the Phase 2X.B remediation. The reconciled 30-test pytest suite passes at current HEAD, and the no-prior-milestone byte-mutation diff is empty under the 2X.B exclusion set. The Phase 2X typed-contract surface is therefore evidence-first accepted for the purposes of opening the next consolidated typed-contract milestone.

The untracked Codex parallel read-only review task (`parallel_capacity_readonly_review_phase2x_b_external_manual_position_quarantine_remediation_impl_and_valid.json`) provides supplementary independent verification and may run in parallel under the `codex_watchdog` lane while the next consolidated typed-contract milestone proceeds. It is not a gate on opening the next milestone — it is an additional review the parallel-capacity scheduler may consume when no Claude child is active and worktree is clean.

## Phase 2W recommendation order
Phase 2W explicitly ordered the post-MVP-ready non-live build chain as:
1. **2X_EXTERNAL_MANUAL_POSITION_QUARANTINE** (REQ_0013 prerequisite 1) — DONE per `07_GO_NO_GO.md` PASS, `11_…` remediation PASS, and `15_…` Codex-FAIL reconciliation. Phase 2X.B Codex FAIL is reconciled.
2. **2Y_PROVENANCE_DEDUPE_ATTRIBUTION** (REQ_0013 prerequisite 2) — typed contract + non-live unit tests only. This is the next consolidated milestone authorized by this planner turn.
3. **2Z_DEGRADED_STATE_FAIL_CLOSED_GATES** (REQ_0013 prerequisite 3) — typed contract + non-live unit tests only. Deferred to third position; depends on 2Y carrying provenance pointers per Phase 2W rationale.

## Marker-name disambiguation note (no rename this turn)
The cockpit commit at HEAD `bdb268b` introduced marker `PHASE2Y_ENTERPRISE_COINANK_STYLE_TRADING_COCKPIT_AND_REALTIME_DATA_READY` under `claude_worklog/final_readiness/enterprise_trading_cockpit/latest/GO_NO_GO.md`. That marker uses the `PHASE2Y_` prefix from the explainability_ui lane (cockpit/frontend operator surface). The next typed-contract milestone is named **Phase 2Y_PROVENANCE_DEDUPE_ATTRIBUTION** in Phase 2W and uses a distinct marker-string family `PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_*`, so the two markers are lexically disjoint. To eliminate any ambiguity the new directory under `claude_worklog/phase2_core_rebuild/` is named `provenance_dedupe_attribution_impl/`, mirroring `external_manual_position_quarantine_impl/`. The new V2 source/test directories are named `provenance_dedupe_attribution/`. No prior cockpit byte content is touched.

## Next safe consolidated non-live milestone — Phase 2Y_PROVENANCE_DEDUPE_ATTRIBUTION

### Scope (typed contract + non-live unit tests only)
- **Typed value object 1**: `ProvenanceRecord` (`@dataclass(frozen=True, slots=True)`), fields:
  - `provenance_id: str` (non-empty, no-whitespace, ≤128 chars; namespaced literal of the upstream record id; not a new lineage ID — derived deterministically from the upstream lineage IDs already at `claude_worklog/v2_requirements/03_PREDICTION_SIGNAL_DECISION_ID_CHAIN.md`).
  - `source_id: str` (non-empty, no-whitespace, ≤64 chars).
  - `ingestor_id: str` (non-empty, no-whitespace, ≤64 chars).
  - `source_ts_ms: int` (nonnegative non-bool; the upstream source timestamp).
  - `ingest_ts_ms: int` (nonnegative non-bool; ≥ `source_ts_ms`).
  - `freshness_ms: int` (nonnegative non-bool; equals `ingest_ts_ms - source_ts_ms`).
  - `decision_id: str`, `prediction_id: str`, `feature_snapshot_id: str` (mirrored lineage IDs).
  - `model_version: str`, `checkpoint_id: str`, `confidence_raw: float`, `confidence_calibrated: float`, `trainer_worker_liveness: str` (the five Phase 2V trainer-parity fields, mirrored).
  - `live_blocked: bool` (must be `True`).
- **Typed value object 2**: `DedupeDecisionRecord` (`@dataclass(frozen=True, slots=True)`), fields:
  - `dedupe_decision_id: str` (non-empty, no-whitespace, ≤128 chars; deterministically derived from `decision_id` + `dedupe_state`; not a new lineage ID).
  - `dedupe_state: str` in `{DEDUPE_NEW, DEDUPE_DUPLICATE_OF_PRIOR, DEDUPE_STALE_OUT_OF_ORDER}` exposed as module constants.
  - `duplicate_of_decision_id: Optional[str]` (must be set iff `dedupe_state == DEDUPE_DUPLICATE_OF_PRIOR`; else `None`).
  - `dedupe_reason: str` (non-empty short reason code, ≤64 chars).
  - `decision_id: str`, `prediction_id: str`, `feature_snapshot_id: str` (mirrored lineage IDs).
  - `model_version: str`, `checkpoint_id: str`, `confidence_raw: float`, `confidence_calibrated: float`, `trainer_worker_liveness: str` (the five Phase 2V trainer-parity fields, mirrored).
  - `live_blocked: bool` (must be `True`).
- **Pure-function service 1**: `assemble_provenance_record(*, upstream_record, source_id, ingestor_id, source_ts_ms, ingest_ts_ms, trainer_model_version, trainer_checkpoint_id, trainer_confidence_raw, trainer_confidence_calibrated, trainer_worker_liveness) -> ProvenanceRecord`. Validates types of each input, mirrors the four lineage IDs and the five trainer-parity fields, computes `freshness_ms = ingest_ts_ms - source_ts_ms`, derives `provenance_id` deterministically from the upstream record's `decision_id` + `source_id` + `ingestor_id`. Raises `ProvenanceServiceError` on invalid input. The service module imports neither `redis`/`aioredis`/`redis.asyncio` nor `fastapi`/`starlette`.
- **Pure-function service 2**: `assemble_dedupe_decision_record(*, upstream_record, dedupe_state, duplicate_of_decision_id, dedupe_reason, trainer_model_version, trainer_checkpoint_id, trainer_confidence_raw, trainer_confidence_calibrated, trainer_worker_liveness) -> DedupeDecisionRecord`. Validates types of each input, mirrors the four lineage IDs and the five trainer-parity fields, derives `dedupe_decision_id` deterministically from `decision_id` + `dedupe_state`, enforces the `duplicate_of_decision_id` invariant against `dedupe_state`. Raises `DedupeServiceError` on invalid input. No `redis` or `fastapi` imports.
- **Composition root**: `build_provenance_dedupe_attribution_runtime(*, now_ms_clock: Callable[[], int]) -> ProvenanceDedupeAttributionRuntime`. Validates `now_ms_clock` is callable. Does not invoke the clock at build time. The returned runtime exposes `provenance_now(...)` and `dedupe_decision_now(...)` callables that delegate to the two assemblers. Following the Phase 2X precedent, the clock is captured by closure and reserved for a future timestamping extension; the typed records carry their own `source_ts_ms` / `ingest_ts_ms` (provenance) and inherit `decision_id`-derived timestamps (dedupe). Raises `ProvenanceDedupeAttributionRuntimeCompositionError` on invalid input.
- **Non-live unit tests**: domain construction PASS/FAIL for each invariant on both records; service assembly PASS/FAIL with deterministic fixtures; composition root validation; clock invocation count = 0 per call; keyword-only param enforcement; no `redis`/`fastapi` import; no FastAPI lifespan registration in `__init__.py`; public-surface stability tests; one regression fixture row reusing the LAB hedge-unwind scenario from `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/01_LEGACY_FAILURE_EVIDENCE.md` and the `duplicate_signal_blocked` row at `claude_worklog/phase2_core_rebuild/trainer_lineage_parity_fields_extension/02_PHASE_2V_TRAINER_LINEAGE_PARITY_FIELDS_SPEC.md` line 19 (model_version=`hybrid_trainer_v2026_05`, checkpoint_id=`ckpt_duplicate_signal_blocked_2026_05`, confidence_raw=0.71, confidence_calibrated=0.68, trainer_worker_liveness=`alive`).

### Out of scope (explicit non-actions)
- No execution-side surface (no paper trader process, no shadow trader process, no live trader process, no replay engine, no scheduler, no background loop, no FastAPI surface, no Redis adapter, no GPU runner, no model-loading subsystem, no strategy library).
- No new lineage ID beyond those already at `claude_worklog/v2_requirements/03_PREDICTION_SIGNAL_DECISION_ID_CHAIN.md` and the five Phase 2V trainer-parity fields. `provenance_id` and `dedupe_decision_id` are deterministic derivations of existing IDs, not new IDs.
- No live-gate flip; `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` remains human-only.
- No byte mutation outside the three new V2 source directories, the three new V2 test directories, and `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/`.
- No frontend/cockpit byte mutation; the cockpit work at `bdb268b` is left untouched.
- No mutation of any prior-milestone artifact under `claude_worklog/phase2_core_rebuild/` outside the new `provenance_dedupe_attribution_impl/` directory.
- No mutation of `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`.
- No SMC/liquidity feature shadow-mode work (REQ_0013 prerequisite 4-onwards remains gated until 2Y and 2Z PASS).
- No Redis import, no FastAPI import, no FastAPI lifespan registration, no environment-variable read, no network call, no heavyweight ML import in any new module.

### Lane / MVP / gate fields for the Phase 2Y implementation task (to be authored next planner turn as task `193_phase2y_provenance_dedupe_attribution_domain_implementation`)
- `lane`: `legacy_parity` (read-only consultation of legacy evidence; typed-contract authoring with no live or shadow surface).
- `secondary_lane`: `paper_backtest_mvp` (residual hardening — provenance pointers and dedupe decision records are the typed inputs a future risk-gateway extension consumes to refuse stale-data trades and duplicate signals).
- `mvp_relevance`: Closes the second of three REQ_0013 phase-order prerequisites that gate SMC/liquidity feature shadow mode. Authors typed `ProvenanceRecord` and `DedupeDecisionRecord` value objects, two pure-function assemblers, one composition-root factory, and non-live unit tests so that downstream extensions of the risk gateway and the orchestrator decision projection can pattern-match on (a) per-source provenance and freshness, and (b) deterministic dedupe state, before allowing any open/close/hedge/reduce action. Closes the orchestrator stale/duplicate-signal handling typed-contract gap noted at `claude_worklog/phase2_core_rebuild/legacy_evidence/01_BUILD_IMPACT_MAP.md` line 31. Closes the trainer-parity duplicate-signal-blocked typed-contract gap noted at `claude_worklog/phase2_core_rebuild/trainer_lineage_parity_fields_extension/02_PHASE_2V_TRAINER_LINEAGE_PARITY_FIELDS_SPEC.md` line 19. No execution-side surface, no new lineage ID, no live-gate flip.
- `next_gate`: `PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_IMPL_AND_VALIDATION_PASSED` (Claude validation) → `PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_PASS` (Codex review, task 194 next turn).
- `predecessor_required_marker`: `PHASE2X_B_EXTERNAL_MANUAL_POSITION_QUARANTINE_CODEX_FAIL_RECONCILED` at `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/15_2X_B_FAIL_RECONCILIATION_GO_NO_GO.md`. Evidence-first acceptance per planner profile.
- `blocked_by`: nothing on disk. The untracked Codex parallel read-only review task is supplementary parallel-lane work and does not block this implementation task.
- `legacy_evidence_consulted`:
  - `claude_worklog/requirements_inbox/REQ_0013_SMC_LIQUIDITY_SHADOW_FEATURES.md` (prerequisite 2 ordering).
  - `claude_worklog/requirements_inbox/REQ_0017_FORCE_PAPER_BACKTEST_MVP_TRACK.md`.
  - `claude_worklog/requirements_inbox/REQ_0018_PLANNER_LANE_LOCK_AND_PARALLEL_BUILD_POLICY.md`.
  - `claude_worklog/requirements_inbox/REQ_0019_LEGACY_MONITOR_AUDIT_EVIDENCE_IN_BUILD.md`.
  - `claude_worklog/requirements_inbox/REQ_0020_FULL_AUTONOMOUS_LEGACY_MAPPED_PAPER_BACKTEST_PERFORMANCE_TARGET.md`.
  - `claude_worklog/requirements_inbox/REQ_0023_FULL_LEGACY_READONLY_AUDIT_SENTINEL.md`.
  - `claude_worklog/requirements_inbox/REQ_0024_HISTORICAL_PNL_TRADE_TRAINER_AUDIT.md`.
  - `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md` (LAB hedge-unwind row).
  - `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/01_LEGACY_FAILURE_EVIDENCE.md`.
  - `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/01_PHASE_2F_LEGACY_EVIDENCE_REVIEW.md` (orchestrator stale/duplicate signal taxonomy).
  - `claude_worklog/phase2_core_rebuild/risk_gateway_impl/01_PHASE_2G_LEGACY_EVIDENCE_REVIEW.md`.
  - `claude_worklog/phase2_core_rebuild/risk_gateway_impl/25_2G_C_RISK_GATEWAY_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`.
  - `claude_worklog/phase2_core_rebuild/legacy_evidence/01_BUILD_IMPACT_MAP.md` line 31 (orchestrator stale/duplicate signal handling row).
  - `claude_worklog/phase2_core_rebuild/legacy_evidence/02_CURRENT_LEGACY_FAILURE_SIGNALS.md`.
  - `claude_worklog/phase2_core_rebuild/trainer_lineage_parity_fields_extension/02_PHASE_2V_TRAINER_LINEAGE_PARITY_FIELDS_SPEC.md` line 19 (`duplicate_signal_blocked`).
  - `claude_worklog/phase2_core_rebuild/trainer_lineage_parity_fields_extension/11_CODEX_REREVIEW_AFTER_VENV_PYTEST_GO_NO_GO.md`.
  - `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/02_PHASE_2X_EXTERNAL_MANUAL_POSITION_QUARANTINE_SPEC.md` (typed-contract precedent).
  - `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/15_2X_B_FAIL_RECONCILIATION_GO_NO_GO.md`.
  - `claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/03_PHASE_2W_NEXT_CONSOLIDATED_MILESTONE_RECOMMENDATION.md`.
  - `claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/06_PHASE_2W_GO_NO_GO.md`.
  - `claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/08_PHASE_2W_CODEX_GO_NO_GO.md`.
  - `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/06_GO_NO_GO.md`.
  - `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/10_GO_NO_GO_CODEX.md`.
  - `claude_worklog/v2_requirements/03_PREDICTION_SIGNAL_DECISION_ID_CHAIN.md`.
  - `claude_worklog/final_readiness/04_GO_NO_GO.md` (live-gate posture).
  - `v2/backend/app/domain/risk_gateway/record.py` (RiskDecisionRecord shape to mirror lineage IDs from).
  - `v2/backend/app/domain/external_manual_position_quarantine/flag.py` (Phase 2X typed-flag pattern to mirror).
  - `v2/backend/app/services/external_manual_position_quarantine/service.py` (Phase 2X assembler-service pattern to mirror).
  - `v2/backend/app/composition/external_manual_position_quarantine/runtime.py` (Phase 2X composition-root pattern to mirror).
- `legacy_failure_addressed`: Closes the orchestrator stale/duplicate-signal handling typed-contract gap (per `01_BUILD_IMPACT_MAP.md` line 31) and the trainer-parity duplicate-signal-blocked typed-contract gap (per `02_PHASE_2V_TRAINER_LINEAGE_PARITY_FIELDS_SPEC.md` line 19) by authoring `ProvenanceRecord` and `DedupeDecisionRecord` typed value objects that downstream extensions of the risk gateway and orchestrator decision projection can pattern-match on. Together with the Phase 2X `ManualPositionFlag` / `ExternalPositionQuarantineRecord` typed surface, the Phase 2Y typed surface is the second of three REQ_0013 prerequisites the SMC/liquidity feature shadow-mode milestones must consume before any execution authority is granted. Phase 2Y authors only the typed-contract surface plus non-live unit tests; the downstream risk-gateway extension that consumes provenance freshness and dedupe state to emit typed `deny_stale_provenance` and `deny_duplicate_decision` reason codes is a future Phase 2Y-follow-up milestone outside this turn's scope.

### Required output files for task 193 (next planner turn will render this set into the task definition)
V2 source:
- `v2/backend/app/domain/provenance_dedupe_attribution/__init__.py`
- `v2/backend/app/domain/provenance_dedupe_attribution/errors.py`
- `v2/backend/app/domain/provenance_dedupe_attribution/provenance_record.py`
- `v2/backend/app/domain/provenance_dedupe_attribution/dedupe_decision_record.py`
- `v2/backend/app/services/provenance_dedupe_attribution/__init__.py`
- `v2/backend/app/services/provenance_dedupe_attribution/errors.py`
- `v2/backend/app/services/provenance_dedupe_attribution/provenance_service.py`
- `v2/backend/app/services/provenance_dedupe_attribution/dedupe_service.py`
- `v2/backend/app/composition/provenance_dedupe_attribution/__init__.py`
- `v2/backend/app/composition/provenance_dedupe_attribution/errors.py`
- `v2/backend/app/composition/provenance_dedupe_attribution/runtime.py`

V2 tests (one assertion per file, mirroring the Phase 2X granularity):
- `v2/backend/tests/unit/domain/provenance_dedupe_attribution/__init__.py`
- `v2/backend/tests/unit/domain/provenance_dedupe_attribution/test_provenance_record_constructs_with_valid_inputs.py`
- `v2/backend/tests/unit/domain/provenance_dedupe_attribution/test_provenance_record_rejects_negative_source_ts_ms.py`
- `v2/backend/tests/unit/domain/provenance_dedupe_attribution/test_provenance_record_rejects_ingest_ts_before_source_ts.py`
- `v2/backend/tests/unit/domain/provenance_dedupe_attribution/test_provenance_record_rejects_freshness_mismatch.py`
- `v2/backend/tests/unit/domain/provenance_dedupe_attribution/test_provenance_record_rejects_live_blocked_false.py`
- `v2/backend/tests/unit/domain/provenance_dedupe_attribution/test_provenance_record_carries_phase_2v_trainer_parity_fields.py`
- `v2/backend/tests/unit/domain/provenance_dedupe_attribution/test_provenance_record_module_does_not_load_redis_when_imported.py`
- `v2/backend/tests/unit/domain/provenance_dedupe_attribution/test_dedupe_decision_record_constructs_with_dedupe_new.py`
- `v2/backend/tests/unit/domain/provenance_dedupe_attribution/test_dedupe_decision_record_constructs_with_dedupe_duplicate_of_prior.py`
- `v2/backend/tests/unit/domain/provenance_dedupe_attribution/test_dedupe_decision_record_constructs_with_dedupe_stale_out_of_order.py`
- `v2/backend/tests/unit/domain/provenance_dedupe_attribution/test_dedupe_decision_record_rejects_unknown_dedupe_state.py`
- `v2/backend/tests/unit/domain/provenance_dedupe_attribution/test_dedupe_decision_record_rejects_duplicate_of_decision_id_when_state_is_new.py`
- `v2/backend/tests/unit/domain/provenance_dedupe_attribution/test_dedupe_decision_record_requires_duplicate_of_decision_id_when_state_is_duplicate_of_prior.py`
- `v2/backend/tests/unit/domain/provenance_dedupe_attribution/test_dedupe_decision_record_rejects_live_blocked_false.py`
- `v2/backend/tests/unit/domain/provenance_dedupe_attribution/test_dedupe_decision_record_carries_phase_2v_trainer_parity_fields.py`
- `v2/backend/tests/unit/domain/provenance_dedupe_attribution/test_dedupe_decision_record_module_does_not_load_redis_when_imported.py`
- `v2/backend/tests/unit/domain/provenance_dedupe_attribution/test_init_module_does_not_register_fastapi_lifespan.py`
- `v2/backend/tests/unit/domain/provenance_dedupe_attribution/test_public_surface.py`
- `v2/backend/tests/unit/services/provenance_dedupe_attribution/__init__.py`
- `v2/backend/tests/unit/services/provenance_dedupe_attribution/test_provenance_service_assembles_record_for_valid_inputs.py`
- `v2/backend/tests/unit/services/provenance_dedupe_attribution/test_provenance_service_rejects_non_record_upstream_input.py`
- `v2/backend/tests/unit/services/provenance_dedupe_attribution/test_provenance_service_keyword_only_params.py`
- `v2/backend/tests/unit/services/provenance_dedupe_attribution/test_provenance_service_propagates_phase_2v_trainer_parity_fields.py`
- `v2/backend/tests/unit/services/provenance_dedupe_attribution/test_provenance_service_derives_freshness_ms_deterministically.py`
- `v2/backend/tests/unit/services/provenance_dedupe_attribution/test_provenance_service_does_not_import_redis.py`
- `v2/backend/tests/unit/services/provenance_dedupe_attribution/test_provenance_service_does_not_register_fastapi_lifespan.py`
- `v2/backend/tests/unit/services/provenance_dedupe_attribution/test_dedupe_service_assembles_record_for_valid_inputs.py`
- `v2/backend/tests/unit/services/provenance_dedupe_attribution/test_dedupe_service_rejects_non_record_upstream_input.py`
- `v2/backend/tests/unit/services/provenance_dedupe_attribution/test_dedupe_service_keyword_only_params.py`
- `v2/backend/tests/unit/services/provenance_dedupe_attribution/test_dedupe_service_propagates_phase_2v_trainer_parity_fields.py`
- `v2/backend/tests/unit/services/provenance_dedupe_attribution/test_dedupe_service_derives_dedupe_decision_id_deterministically.py`
- `v2/backend/tests/unit/services/provenance_dedupe_attribution/test_dedupe_service_does_not_import_redis.py`
- `v2/backend/tests/unit/services/provenance_dedupe_attribution/test_dedupe_service_does_not_register_fastapi_lifespan.py`
- `v2/backend/tests/unit/services/provenance_dedupe_attribution/test_public_surface.py`
- `v2/backend/tests/unit/composition/provenance_dedupe_attribution/__init__.py`
- `v2/backend/tests/unit/composition/provenance_dedupe_attribution/test_returns_runtime_instance.py`
- `v2/backend/tests/unit/composition/provenance_dedupe_attribution/test_runtime_provenance_now_invokes_clock_zero_times_per_call.py`
- `v2/backend/tests/unit/composition/provenance_dedupe_attribution/test_runtime_dedupe_decision_now_invokes_clock_zero_times_per_call.py`
- `v2/backend/tests/unit/composition/provenance_dedupe_attribution/test_runtime_provenance_now_keyword_only_params.py`
- `v2/backend/tests/unit/composition/provenance_dedupe_attribution/test_runtime_dedupe_decision_now_keyword_only_params.py`
- `v2/backend/tests/unit/composition/provenance_dedupe_attribution/test_runtime_does_not_invoke_clock_at_build_time.py`
- `v2/backend/tests/unit/composition/provenance_dedupe_attribution/test_runtime_validates_now_ms_clock.py`
- `v2/backend/tests/unit/composition/provenance_dedupe_attribution/test_runtime_module_does_not_load_redis_when_imported.py`
- `v2/backend/tests/unit/composition/provenance_dedupe_attribution/test_init_module_does_not_register_fastapi_lifespan.py`
- `v2/backend/tests/unit/composition/provenance_dedupe_attribution/test_public_surface.py`

Phase 2Y docs:
- `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/00_PHASE_2Y_SCOPE.md`
- `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/01_PHASE_2Y_LEGACY_EVIDENCE_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/02_PHASE_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_SPEC.md`
- `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/03_PHASE_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/04_PHASE_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/05_PHASE_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_GO_NO_GO_REQUEST.md`
- `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/06_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/07_GO_NO_GO.md`

### worktree_excluded_paths for task 193
- `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`.
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/PLANNER_TURN_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_OPEN_AND_2X_RECONCILIATION_AT_HEAD_BDB268B.md` (this planner-turn note).
- `claude_worklog/agent_supervisor/tasks/parallel_capacity_readonly_review_phase2x_b_external_manual_position_quarantine_remediation_impl_and_valid.json` (untracked Codex parallel read-only review task).
- The seven standing `parallel_capacity_readonly_review_codex_*` task JSONs already in the Phase 2X exclusion set.

### Forbidden output paths and forbidden actions (high-level summary; full enumeration in task 193)
- All Phase 2X forbidden_output_paths plus `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/` (now itself a prior-milestone dir).
- All Phase 2X forbidden_actions plus the explicit prohibition on opening 2Z degraded-state fail-closed gate work before Phase 2Y reaches `PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_PASS`.

## This turn's authored output
This planner turn authors **one** planning note inside `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/`. It does **not** author task `193`, `194`, any V2 source, any V2 test, any task definition under `claude_worklog/agent_supervisor/tasks/`, any prior-milestone artifact byte content, any planner-prompt edit, or any cockpit/frontend byte. The dirty untracked `parallel_capacity_readonly_review_phase2x_b_external_manual_position_quarantine_remediation_impl_and_valid.json` task remains untouched and stays in the parallel-capacity scheduler's queue for Codex `codex_watchdog`-lane dispatch.

The planner-prompt tracker line `Current MVP milestone: REPLAY_BACKTEST_RUNNER_MVP` remains stale (V2_BACKTEST_AND_PAPER_MVP_READY achieved). Operator action remains as recommended in `PLANNER_TURN_2L_…`: replace the three tracker lines with `Current MVP milestone: V2_BACKTEST_AND_PAPER_MVP_READY (achieved)`, `Next paper/backtest milestone: none — sequence closed; Lane A residual hardening only`, `Distance to V2_BACKTEST_AND_PAPER_MVP_READY: 0 milestones remaining`. This planner turn does not author that change.

## Hard non-live boundaries reaffirmed
- Do not modify `/home/wali/Desktop/AI BOT`.
- Do not read or write any Redis key.
- Do not invoke any Redis command.
- Do not restart any live service.
- Do not place or cancel exchange orders.
- Do not change leverage or margin.
- Do not enable live trading.
- Do not deploy.
- Do not run a production migration.
- Do not expose or commit secrets.
- Do not flip `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` or any other live-gate marker.
- Final live approval remains human-only.

## Why this is the next safe non-live planner turn
- Phase 2W's recommendation order is anchored to on-disk legacy evidence (REQ_0013 phase order, REQ_0022 LAB hedge-unwind tie-in, REQ_0023 read-only sentinel, REQ_0024 historical PnL audit) and explicitly defers 2Y as the next typed-contract milestone after 2X.
- The Phase 2X.B Codex re-review FAIL is reconciled at current HEAD per `15_…`; the focused 30-test suite passes; the no-prior-milestone byte-mutation diff under the 2X.B exclusion set is empty. Evidence-first acceptance applies.
- The untracked Codex parallel read-only review task is supplementary parallel-lane work, not a gate, and remains queued for `codex_watchdog`-lane dispatch when worktree clears.
- The cockpit `bdb268b` commit's `PHASE2Y_ENTERPRISE_…` marker is lexically disjoint from the Phase 2W-recommended `PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_*` typed-contract markers; the new typed-contract directory `provenance_dedupe_attribution_impl/` and source/test directories `provenance_dedupe_attribution/` are namespace-distinct from `enterprise_trading_cockpit/`.
- No active Claude/Codex/Ollama child is running. No live, legacy, Redis, exchange, deploy, or secret action is present. No L4/L5 action is required.
- The opening of Phase 2Y_PROVENANCE_DEDUPE_ATTRIBUTION as a typed-contract + non-live-unit-tests milestone matches the consolidated_default planner profile and the legacy_parity / paper_backtest_mvp lane combination authorized by REQ_0018 and REQ_0020.

PHASE_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_OPEN_AND_2X_RECONCILIATION_ACKNOWLEDGED
