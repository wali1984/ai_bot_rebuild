# Phase 2O — Harness Pipeline Spec

## Pure-function harness module

The Phase 2O harness module `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py` exposes one pure function:

```
replay_shadow_mode_evidence_pack(
    *,
    evidence_pack: tuple[tuple[str, tuple[ShadowModeComparisonInput, ...]], ...],
    requested_state: str,
    shadow_mode_clock: Callable[[], int],
    risk_decision_clock: Callable[[], int],
) -> tuple[ShadowModeReadinessFlag, tuple[ShadowModeEvidenceTrio, ...]]
```

Where `ShadowModeEvidenceTrio` is a test-only frozen value class:

```
@dataclass(frozen=True, slots=True)
class ShadowModeEvidenceTrio:
    scenario_slug: str
    inputs: tuple[ShadowModeComparisonInput, ...]
    comparisons: tuple[ShadowModeComparisonRecord, ...]
```

And `ShadowModeComparisonInput` and `ShadowModeComparisonRecord` are test-only frozen value classes under the unit-test package:

```
@dataclass(frozen=True, slots=True)
class ShadowModeComparisonInput:
    orchestrator_decision: OrchestratorDecisionRecord
    legacy_action_evidence_pointer: str

@dataclass(frozen=True, slots=True)
class ShadowModeComparisonRecord:
    legacy_action_evidence_pointer: str
    v2_risk_decision_record: RiskDecisionRecord
```

Neither `ShadowModeEvidenceTrio` nor `ShadowModeComparisonInput` nor `ShadowModeComparisonRecord` is a V2 `app/domain` type, service, adapter, persistence model, API surface, scheduler, shadow-trader process, or live-readiness gate. They are test-only typed value classes authored entirely inside the unit-test package.

## Pipeline behavior

The harness function:

1. Calls `build_shadow_mode_readiness_runtime(now_ms_clock=shadow_mode_clock)` and asserts the returned `ShadowModeReadinessRuntime` is bound.
2. Calls `runtime.shadow_mode_readiness_now(requested_state=requested_state)` and captures the typed `ShadowModeReadinessFlag`.
3. Asserts `shadow_mode_readiness_flag.live_blocked is True` and `shadow_mode_readiness_flag.state in {SHADOW_MODE_NOT_READY, SHADOW_MODE_READY}`.
4. Calls `build_risk_decision_evaluator(now_ms_clock=risk_decision_clock)` and asserts the returned evaluator is bound.
5. For each `(scenario_slug, inputs)` in `evidence_pack`:
   - For each `ShadowModeComparisonInput` in `inputs`, calls `evaluator(decision=input.orchestrator_decision)` to obtain a typed `RiskDecisionRecord` and constructs a typed `ShadowModeComparisonRecord(legacy_action_evidence_pointer=input.legacy_action_evidence_pointer, v2_risk_decision_record=...)`.
   - Constructs a typed `ShadowModeEvidenceTrio(scenario_slug=scenario_slug, inputs=inputs, comparisons=...)` and appends to the trio tuple.
6. Returns `(shadow_mode_readiness_flag, tuple_of_trios)`.

The harness does NOT:

- introduce any I/O, persistence, network call, FastAPI surface, scheduler, background loop, Redis adapter, GPU runner, or model-loading subsystem;
- mock, patch, or monkeypatch `build_shadow_mode_readiness_runtime`, `assemble_shadow_mode_readiness_flag`, `build_risk_decision_evaluator`, `assemble_risk_decision_record`, or any of their dependencies;
- introduce a `shadow_decision_id`, `execution_intent_id`, or new standalone `paper_trade_id` lineage row;
- introduce a new V2 typed surface, service, composition root, adapter, persistence model, API surface, or live-readiness gate;
- open, read, or write the `legacy_action_evidence_pointer` string as a filesystem path; the pointer is a deterministic typed string convention only.

## Shadow-readiness gate behavior

The harness exposes the readiness flag back to the caller; the harness does NOT abort, raise, or short-circuit when the readiness state is `not_ready`. The pytest module asserts that for `requested_state=ready` the returned flag has `state == SHADOW_MODE_READY`, and that for `requested_state=not_ready` the returned flag has `state == SHADOW_MODE_NOT_READY`. In both cases the harness produces the typed comparison trios over the same evidence pack; the readiness gate is captured as evidence, not enforced as a runtime kill. Enforcing the gate as a runtime kill belongs to a separate, later milestone explicitly out of scope at Phase 2O.

## Hard safety posture

No `/home/wali/Desktop/AI BOT` access. No Redis access. No live service restart. No exchange action. No leverage / margin change. No live-trading enablement. No deployment. No production migration. No secret exposure. No flip of `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`.

PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_HARNESS_PIPELINE_SPEC_READY
