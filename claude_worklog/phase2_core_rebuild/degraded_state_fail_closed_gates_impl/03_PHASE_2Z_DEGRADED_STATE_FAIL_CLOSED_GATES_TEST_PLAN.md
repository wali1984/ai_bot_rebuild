```
# Phase 2Z — Test Plan

All deterministic-input rows use the duplicate_signal_blocked
trainer-parity row from
`claude_worklog/phase2_core_rebuild/trainer_lineage_parity_fields_extension/02_PHASE_2V_TRAINER_LINEAGE_PARITY_FIELDS_SPEC.md`
(line 19): `model_version=hybrid_trainer_v2026_05`,
`checkpoint_id=ckpt_duplicate_signal_blocked_2026_05`,
`confidence_raw=0.71`, `confidence_calibrated=0.68`,
`trainer_worker_liveness=alive`.

The LAB hedge-unwind regression-fixture row (from
`claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/01_LEGACY_FAILURE_EVIDENCE.md`)
seeds the
`test_service_derives_degraded_state_id_deterministically` test (decision-id
`decision-LAB-2026-05-10`).

## Domain layer tests

| Test | Layer | Assertion | Fixture inputs |
| --- | --- | --- | --- |
| `test_degraded_state_record_constructs_with_valid_inputs` | domain | All four sources OK; `fail_closed=False`; `live_blocked=True`; `degraded_state_id="degraded_state:decision-1"`. | All sources `DEGRADED_SOURCE_OK`, ages 50/60/70/80, lineage `decision-1`/`prediction-1`/`feature-1`/`risk-1`, trainer parity row, `live_blocked=True`. |
| `test_degraded_state_record_rejects_negative_age_ms` | domain | Negative `smc_age_ms`, `liq_age_ms`, `oi_age_ms`, or `orderbook_age_ms` raises `DegradedStateFailClosedGatesDomainError` (4 sub-tests). | Base row, age `-1` per source. |
| `test_degraded_state_record_rejects_unknown_source_state` | domain | Unknown `smc_state`, `liq_state`, `oi_state`, or `orderbook_state` raises domain error (4 sub-tests). | Base row, state `"UNKNOWN"` per source. |
| `test_degraded_state_record_rejects_live_blocked_false` | domain | `live_blocked=False` raises domain error. | Base row, `live_blocked=False`. |
| `test_degraded_state_record_derives_fail_closed_from_per_source_states` | domain | Six matrix rows derive `fail_closed` correctly. | (1) all OK / `False`; (2) smc=STALE, others OK / `True`; (3) liq=MISSING / `True`; (4) oi=UNUSED / `False`; (5) orderbook=MISSING / `True`; (6) all STALE / `True`. |
| `test_degraded_state_record_rejects_fail_closed_inconsistent_with_per_source_states` | domain | `fail_closed=False` with `smc_state=DEGRADED_SOURCE_STALE` raises domain error; `fail_closed=True` with all sources OK raises domain error. | Two sub-tests covering both inconsistent shapes. |
| `test_degraded_state_record_carries_phase_2v_trainer_parity_fields` | domain | The five Phase 2V fields round-trip onto the record. | Base row. |
| `test_degraded_state_record_module_does_not_load_redis_when_imported` | domain | `redis` is not in `sys.modules` after importing `degraded_state_record`. | n/a. |
| `test_init_module_does_not_register_fastapi_lifespan` | domain | `__init__.py` exposes no `lifespan`. | n/a. |
| `test_public_surface` | domain | `__all__` equals the six expected names. | n/a. |

## Service layer tests

| Test | Layer | Assertion | Fixture inputs |
| --- | --- | --- | --- |
| `test_service_assembles_record_for_valid_inputs` | services | Record has expected `degraded_state_id`, `decision_id`, `fail_closed=False`, `live_blocked=True`. | Risk record `decision-1`, all sources OK. |
| `test_service_rejects_non_record_upstream_input` | services | Non-`RiskDecisionRecord` raises `DegradedStateFailClosedGatesServiceError`. | `object()` upstream. |
| `test_service_keyword_only_params` | services | Positional call raises `TypeError`. | Single positional `object()`. |
| `test_service_propagates_phase_2v_trainer_parity_fields` | services | All five Phase 2V fields round-trip. | Base row, trainer parity values. |
| `test_service_derives_degraded_state_id_deterministically` | services | `degraded_state_id == "degraded_state:decision-LAB-2026-05-10"` from upstream `decision_id`. | LAB regression decision-id. |
| `test_service_derives_fail_closed_from_per_source_states` | services | Six matrix rows match the domain derivation rule. | Six combinations of per-source states. |
| `test_service_does_not_import_redis` | services | `redis` is not in `sys.modules` after importing `service`. | n/a. |
| `test_service_does_not_register_fastapi_lifespan` | services | `service` module exposes no `lifespan`. | n/a. |
| `test_public_surface` | services | `__all__` equals the two expected names. | n/a. |

## Composition layer tests

| Test | Layer | Assertion | Fixture inputs |
| --- | --- | --- | --- |
| `test_returns_runtime_instance` | composition | Build returns a `DegradedStateFailClosedGatesRuntime`. | `now_ms_clock=lambda: 1`. |
| `test_runtime_degraded_state_now_invokes_clock_zero_times_per_call` | composition | Counter increments 0 times after one closure call. | Counter clock; one closure call with all sources OK. |
| `test_runtime_degraded_state_now_keyword_only_params` | composition | Positional call raises `TypeError`. | Single positional `object()`. |
| `test_runtime_does_not_invoke_clock_at_build_time` | composition | Counter increments 0 times after build. | Counter clock; no closure call. |
| `test_runtime_validates_now_ms_clock` | composition | Non-callable raises `DegradedStateFailClosedGatesRuntimeCompositionError`. | `now_ms_clock=1`. |
| `test_runtime_module_does_not_load_redis_when_imported` | composition | `redis` is not in `sys.modules` after importing `runtime`. | n/a. |
| `test_init_module_does_not_register_fastapi_lifespan` | composition | `__init__.py` exposes no `lifespan`. | n/a. |
| `test_public_surface` | composition | `__all__` equals the three expected names. | n/a. |

PHASE_2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_TEST_PLAN_READY
```
