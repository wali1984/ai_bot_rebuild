# Codex Parallel Review - Risk Gateway Default Deny MVP

Result: CODEX_PARALLEL_REVIEW_BLOCKED

Scope inspected:
- `v2/backend/app/domain/risk_gateway/record.py`
- `v2/backend/app/services/risk_gateway/service.py`
- `v2/backend/app/composition/risk_gateway/runtime.py`
- `v2/backend/app/services/orchestrator_decision/service.py`
- `v2/backend/app/domain/orchestrator_decision/record.py`
- `v2/backend/app/services/external_manual_position_quarantine/service.py`
- `v2/backend/app/proof/*`
- `v2/backend/tests/unit/domain/risk_gateway`
- `v2/backend/tests/unit/services/risk_gateway`
- `v2/backend/tests/unit/composition/risk_gateway`
- `v2/backend/tests/unit/services/orchestrator_decision`
- `v2/backend/tests/unit/proof`
- `v2/backend/tests/unit/replay_case_lab_hedge_unwind`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl`
- `claude_worklog/phase2_core_rebuild/risk_gateway`
- `claude_worklog/legacy_failure_cases`

Findings:

1. BLOCKER - The gateway assembler still allows tradable orchestrator decisions without any gateway-local safety context.
   - `v2/backend/app/services/risk_gateway/service.py:49-54` maps `open_long` and `open_short` directly to `allow`.
   - The function signature at `service.py:25-29` only accepts an `OrchestratorDecisionRecord` and a clock. It has no stale-feature envelope, exposure state, hedge-unwind context, manual-position flag, degraded-source state, account ownership state, or residual-exposure input.
   - This means the gateway cannot independently default-deny when a tradable upstream decision is missing downstream risk context.

2. BLOCKER - `deny_default` is reserved in the risk domain but not emitted by the gateway service for valid orchestrator inputs.
   - `v2/backend/app/domain/risk_gateway/record.py:15` defines `RISK_DECISION_REASON_DENY_DEFAULT`.
   - `record.py:135-140` validates that `deny_default` can be paired with tradable inputs.
   - `v2/backend/app/services/risk_gateway/service.py:49-60` never emits `deny_default`; the only service deny mappings are `hold` and `abstain`.
   - `v2/backend/tests/unit/services/risk_gateway/test_assemble_never_emits_deny_default_for_orchestrator_inputs.py` explicitly locks in that behavior.

3. BLOCKER - Stale data blocks are upstream-dependent, not gateway-enforced.
   - `v2/backend/app/services/orchestrator_decision/service.py:77-84` converts missing/stale prediction freshness into `abstain_freshness_missing` or `abstain_freshness_stale`.
   - `v2/backend/app/services/risk_gateway/service.py:58-60` then denies any abstain.
   - However, risk gateway itself does not accept or inspect freshness age/source data, so a stale-data block only exists if the orchestrator already abstained. A tradable `open_long`/`open_short` input with stale external context cannot be denied at the gateway.

4. BLOCKER - Hedge unwind residual exposure is represented in proof/replay fixtures, not enforced by the gateway.
   - The legacy case requires net exposure checks before closing a protective hedge leg: `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md:27-35`.
   - The risk gateway service has no exposure or hedge-close fields and cannot evaluate residual short exposure.
   - LAB/non-live coverage exists in proof and replay tests, e.g. `v2/backend/tests/unit/replay_case_lab_hedge_unwind/test_lab_hedge_unwind_replay_case.py:142-197`, but those tests mirror prebuilt ledger outcomes rather than proving gateway enforcement.

5. BLOCKER - Manual/external position quarantine is separate from risk gateway admission.
   - `v2/backend/app/services/external_manual_position_quarantine/service.py:12-21` builds an `ExternalPositionQuarantineRecord` from a completed `RiskDecisionRecord` and a `ManualPositionFlag`.
   - The risk gateway runtime at `v2/backend/app/composition/risk_gateway/runtime.py:17-24` only binds a clock and returns the risk assembler evaluator. It does not consult quarantine state before allowing risk-add.
   - The proof artifact policy says to block risk-add on quarantined symbol/account, but that is not wired into the risk gateway decision path.

6. BLOCKER - The non-live proof artifact safety-token test currently fails.
   - Targeted validation result: `1 failed, 159 passed`.
   - Failing test: `v2/backend/tests/unit/proof/test_non_live_operational_proof_artifacts.py::test_harness_does_not_use_live_side_effect_terms`.
   - Offending literals are in `v2/backend/app/proof/readonly_market_exchange_data_plane.py:40-43` and method names at `:95-105`: `create_order`, `cancel_order`, `change_leverage`, `change_margin`.

Positive evidence:
- Risk decision records are frozen and force `live_blocked=True`.
- Risk gateway service and composition imports are pure/no Redis/no FastAPI.
- Stale/missing prediction freshness is denied when upstream orchestrator emits abstain.
- LAB hedge unwind, historical proof, non-live operational proof, and quarantine artifacts exist, but they are not yet gateway admission controls.

Proposed non-live autofix tasks:
1. Add a gateway-local default-deny safety input object for freshness, residual exposure/hedge unwind, degraded source state, and manual/external quarantine. Unknown or missing safety context should return `deny` / `deny_default`.
2. Extend `assemble_risk_decision_record` or add a new non-live evaluator wrapper that checks those safety inputs before allowing `open_long` or `open_short`.
3. Add unit tests proving stale source data, missing freshness context, LAB residual short exposure after protective long close, and quarantined symbol/account all deny tradable actions.
4. Convert LAB replay/proof fixtures into an actual gateway admission test instead of only mirroring prebuilt ledger outcomes.
5. Fix the proof safety-token test by avoiding literal live-action token strings in `readonly_market_exchange_data_plane.py` while keeping the methods inert and non-live.

Verification:
- Command: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider v2/backend/tests/unit/domain/risk_gateway v2/backend/tests/unit/services/risk_gateway v2/backend/tests/unit/composition/risk_gateway v2/backend/tests/unit/services/orchestrator_decision v2/backend/tests/unit/proof/test_external_manual_position_quarantine.py v2/backend/tests/unit/proof/test_historical_30d_replay_and_paper_proof.py v2/backend/tests/unit/proof/test_non_live_operational_proof_artifacts.py v2/backend/tests/unit/replay_case_lab_hedge_unwind/test_lab_hedge_unwind_replay_case.py`
- Result: `1 failed, 159 passed`
