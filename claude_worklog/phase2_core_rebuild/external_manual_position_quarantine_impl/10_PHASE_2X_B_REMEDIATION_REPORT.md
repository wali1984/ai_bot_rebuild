Phase 2X.B remediation patch:

- Removed the per-call `_now_ms_clock()` invocation from the external manual position quarantine runtime.
- Removed the per-call integer and nonnegative validation for the runtime clock return value.
- Preserved the build-time `callable(now_ms_clock)` validation, the `now_ms_clock` parameter, and the `_now_ms_clock` closure capture.
- Added the runtime comment that the clock is reserved for a future Phase 2X timestamping extension and must not be invoked per call because `risk_decision_ts_ms` remains authoritative.
- Replaced the clock invocation assertion test with `test_runtime_does_not_invoke_clock_per_call`, preserving the `RiskDecisionRecord` helper, quarantined manual position flag, and trainer-parity fixture row.

Targeted pytest result:

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. ./.venv/bin/python -m pytest -p no:cacheprovider v2/backend/tests/unit/domain/external_manual_position_quarantine/ v2/backend/tests/unit/services/external_manual_position_quarantine/ v2/backend/tests/unit/composition/external_manual_position_quarantine/ -x -q`

Result: `30 passed in 0.04s`.

Smoke import result:

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 -c "from v2.backend.app.domain.external_manual_position_quarantine import ManualPositionFlag, MANUAL_POSITION_QUARANTINED, MANUAL_POSITION_NOT_PRESENT, ExternalPositionQuarantineRecord, ExternalManualPositionQuarantineDomainError; from v2.backend.app.services.external_manual_position_quarantine import assemble_external_position_quarantine_record, ExternalManualPositionQuarantineServiceError; from v2.backend.app.composition.external_manual_position_quarantine import ExternalManualPositionQuarantineRuntime, build_external_position_quarantine_runtime, ExternalManualPositionQuarantineRuntimeCompositionError; print('ok')"`

Result: `ok`.

No Phase 2X 00-09 doc was modified. No Phase 2X domain or services source was modified. No Phase 2X domain or services test was modified. No execution-side surface or new lineage ID was introduced.

PHASE_2X_B_REMEDIATION_REPORT_READY
