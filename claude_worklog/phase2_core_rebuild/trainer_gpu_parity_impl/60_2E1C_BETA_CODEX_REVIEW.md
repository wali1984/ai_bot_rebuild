# Phase 2E1.C.beta - Codex Review

## 1. Public surface integrity - PASS

Evidence: `v2/backend/app/domain/liveness_stream_growth/__init__.py:1-12` re-exports exactly `StreamIdObservation`, `GrowthWindowConfig`, `compute_stream_id_growth_in_window`, and `LivenessStreamGrowthDomainError`. `test_public_surface.py:8-32` verifies exact `__all__`, no `parsed_id`, no internal `_` names, and no alpha import side effect. The `errors` submodule is not in `__all__`.

Remediation ask: none.

## 2. Spec faithfulness - StreamIdObservation - PASS

Evidence: `stream_observation.py:49-64` defines `@dataclass(frozen=True, slots=True)` with fields in the required order: `stream_name`, `stream_id`, `observation_ts_ms`. Validation covers stream-name type/non-empty/whitespace/path/character rules at `stream_observation.py:11-23`, stream-id single-separator and decimal parsing at `stream_observation.py:26-42`, and strict non-bool integer timestamp plus non-negative timestamp at `stream_observation.py:58-61`. `parsed_id()` returns `tuple[int, int]` through the same parser at `stream_observation.py:63-64`. Tests cover these invariants at `test_stream_observation_validation.py:13-83` and `test_stream_observation_parsed_id.py:11-30`.

Remediation ask: none.

## 3. Spec faithfulness - GrowthWindowConfig - PASS

Evidence: `growth_window_config.py:8-19` defines `@dataclass(frozen=True, slots=True)` with `window_ms: int` then `boundary_inclusive: bool = False`. `window_ms` uses exact-type integer validation, rejecting `bool`, and requires `>= 1` at `growth_window_config.py:13-17`. `boundary_inclusive` uses `type(...) is bool` at `growth_window_config.py:18-19`. Tests cover zero, negative, non-int and bool-as-int rejection, boundary int rejection, and default false at `test_growth_window_config_validation.py:11-33`.

Remediation ask: none.

## 4. Spec faithfulness - compute_stream_id_growth_in_window - PASS

Evidence: the signature makes `stream_name` keyword-only at `growth_calculator.py:8-14`. Tuple-only observations validation is at `growth_calculator.py:15-16`; config and `now_ms` validation are at `growth_calculator.py:17-23`. The lower bound and strict/inclusive semantics are at `growth_calculator.py:25` and `growth_calculator.py:35-38`. Future observations are rejected before stream filtering at `growth_calculator.py:31-34`, and iteration continues over the full tuple because the function only returns after the loop at `growth_calculator.py:28-42`. Distinctness is counted on literal `stream_id` strings at `growth_calculator.py:26` and `growth_calculator.py:39-40`. Tests cover input validation at `test_growth_calculator_input_validation.py:17-82`, boundaries at `test_growth_calculator_window_boundary.py:14-73`, distinctness at `test_growth_calculator_distinctness.py:14-58`, stream filtering at `test_growth_calculator_stream_name_filter.py:14-54`, and future rejection at `test_growth_calculator_future_observation.py:17-55`.

Remediation ask: none.

## 5. Out-of-band requirement compliance per 05 spec - PASS

Evidence: spec 05 requires stream-id growth rather than capped-stream `XLEN` counts at `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/05_PREDICTION_WORKER_LIVENESS_FIX_SPEC.md:44-53`. Re-run commands `rg "XLEN" v2/backend/app/domain/liveness_stream_growth; true` and `rg "xlen" v2/backend/app/domain/liveness_stream_growth; true` returned zero hits. The calculator consumes `observations: tuple[StreamIdObservation, ...]` and returns an in-process integer without Redis calls at `growth_calculator.py:8-42`.

Remediation ask: none.

## 6. Hard-exclusion compliance - FAIL

Evidence: forbidden-token grep over source and tests returned zero for `import redis`, `from redis`, `aioredis`, `subprocess`, `os.system`, `os.popen`, `socket`, `requests`, `httpx`, `urllib`, `legacy_reference`, `/home/wali/Desktop/AI BOT/`, `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `time.time(`, `datetime.now(`, `datetime.utcnow(`, `numpy`, `torch`, `tensorflow`, `XLEN`, `xlen`, `asyncio`, `async def`, and `from v2.backend.app.domain.trainer_liveness`.

Failure evidence: safety boundary 54 bans file-system I/O from beta source or beta tests at `54_PHASE_2E1C_BETA_SAFETY_BOUNDARIES.md:46-49`. The beta test tree performs filesystem reads in `test_forbidden_tokens.py:3-8` and `test_forbidden_tokens.py:41-50` via `pathlib.Path` and `path.read_text(...)`. This is read-only and aligned with the test-plan grep intent, but it violates the explicit hard-exclusion wording under review.

Remediation ask: supervisor should resolve the spec conflict under REQ_0007 autofix scope before re-implementation. Either allow this specific read-only token-scan test in safety boundaries, or replace the in-test filesystem scan with an external validation-only grep so beta tests perform no file I/O.

## 7. END_FILE marker hygiene - PASS

Evidence: re-run command `rg "^END_FILE:" v2/backend/app/domain/liveness_stream_growth v2/backend/tests/unit/domain/liveness_stream_growth; true` returned zero hits. Re-run command `python3 -m py_compile $(rg --files v2/backend/app/domain/liveness_stream_growth v2/backend/tests/unit/domain/liveness_stream_growth -g '*.py')` exited 0 for all Python files in both trees. Pytest re-run passed: `53 passed in 0.04s`.

Remediation ask: none.

## 8. Test coverage - PASS

Evidence: each spec 53 rubric maps to at least one beta test. Stream observation validation is covered at `test_stream_observation_validation.py:13-83`; `parsed_id()` at `test_stream_observation_parsed_id.py:11-30`; config validation, including `window_ms=True`, at `test_growth_window_config_validation.py:11-33`; argument validation, including list and generator rejection and positional `stream_name`, at `test_growth_calculator_input_validation.py:17-82`; strict and inclusive lower-bound behavior at `test_growth_calculator_window_boundary.py:14-73`; literal-string distinctness at `test_growth_calculator_distinctness.py:14-58`; mixed-stream filtering at `test_growth_calculator_stream_name_filter.py:14-54`; future-at-end and future non-matching stream at `test_growth_calculator_future_observation.py:28-45`; zero-growth cases at `test_growth_calculator_zero_growth_cases.py:14-59`; public surface at `test_public_surface.py:8-32`; forbidden token scan at `test_forbidden_tokens.py:11-51`.

Remediation ask: none.

## 9. Cross-symbol isolation - PASS

Evidence: beta source imports only beta-local modules and stdlib at `__init__.py:1-4`, `stream_observation.py:1-5`, `growth_window_config.py:1-5`, and `growth_calculator.py:1-5`. Re-run command `rg "trainer_liveness|trainer_parity|adapters/trainer|adapters\\.trainer" v2/backend/app/domain/liveness_stream_growth; true` returned zero hits. `test_public_surface.py:17-23` also verifies beta import does not trigger the alpha package in `sys.modules`.

Remediation ask: none.

## 10. Documentation alignment - WARN

Evidence: implementation report 57 accurately lists authored files, public surface, validation, spec satisfaction, and cross-isolation at `57_2E1C_BETA_IMPLEMENTATION_REPORT.md:3-123`. The source behavior implements future-before-filter and literal-string distinctness at `growth_calculator.py:31-40`.

Warning evidence: source has no inline rationale comments explaining why future rejection precedes stream filtering or why distinctness is on literal strings. The behavior is correct and tested, but the rubric requested inline rationale documentation.

Remediation ask: in a follow-up implementation task, add concise comments near `growth_calculator.py:31-40` if the supervisor treats inline rationale documentation as mandatory rather than advisory.

## 11. Safety boundaries adherence - FAIL

Evidence: safety boundary 54 allows writes only under `v2/backend/app/domain/liveness_stream_growth/`, `v2/backend/tests/unit/domain/liveness_stream_growth/`, and `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/` at `54_PHASE_2E1C_BETA_SAFETY_BOUNDARIES.md:3-13`. It also requires no file-system I/O from beta source or beta tests at `54_PHASE_2E1C_BETA_SAFETY_BOUNDARIES.md:46-49`, and preserves `LIVE TRADING: BLOCKED` at `54_PHASE_2E1C_BETA_SAFETY_BOUNDARIES.md:101-103`.

Failure evidence: implementation report 57 records that recovery "materialized `v2/.venv-control-plane` as a symlink" at `57_2E1C_BETA_IMPLEMENTATION_REPORT.md:91-98`, which is outside the allowed beta write prefixes. Read-only check `ls -ld v2/.venv-control-plane` shows `v2/.venv-control-plane -> ../.venv`. Also, beta test file I/O exists at `test_forbidden_tokens.py:3-8` and `test_forbidden_tokens.py:41-50`, conflicting with safety boundary 54. No live-trading enablement was found; `LIVE TRADING: BLOCKED` remains documented at `54_PHASE_2E1C_BETA_SAFETY_BOUNDARIES.md:101-103` and `55_PHASE_2E1C_BETA_GO_NO_GO_REQUEST.md:49`.

Remediation ask: supervisor should open REQ_0007 remediation. Remove or formally account for the out-of-scope `v2/.venv-control-plane` symlink mutation, and resolve the safety/test-plan conflict around filesystem reads in `test_forbidden_tokens.py`.

## 12. Adversarial probes - PASS

Evidence: explicit `python3` probes against the beta API produced the expected outcomes:

- `StreamIdObservation(stream_name="   ", stream_id="1-0", observation_ts_ms=1)` raised `LivenessStreamGrowthDomainError(reason="must_not_have_edge_whitespace")`.
- `StreamIdObservation(stream_name="prediction", stream_id="abc-0", observation_ts_ms=1)` raised `LivenessStreamGrowthDomainError(reason="must_be_decimal_stream_id")`.
- `GrowthWindowConfig(window_ms=True)` raised `LivenessStreamGrowthDomainError(reason="must_be_int")`.
- `compute_stream_id_growth_in_window([], GrowthWindowConfig(window_ms=1), 1, stream_name="prediction")` raised `LivenessStreamGrowthDomainError(reason="observations_not_tuple")`.
- A future-stamped non-matching stream observation raised `LivenessStreamGrowthDomainError(reason="observation_in_future")`.
- Positional `stream_name` raised `TypeError`.

Remediation ask: none.

## Adversarial coverage probes

All requested additional probes were tried and behaved correctly:

- Whitespace-only `stream_name` raised.
- `stream_id="abc-0"` raised.
- `GrowthWindowConfig(window_ms=True)` raised, proving bool-as-int rejection.
- `observations=[]` raised `observations_not_tuple`.
- Future-stamped observation in a non-matching stream raised before stream filtering.
- Positional `stream_name` raised `TypeError`.

## Final verdict

The domain behavior and test suite pass, but the review is NO-GO because safety-boundary adherence fails on documented out-of-scope symlink materialization and beta test filesystem I/O.

PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_FAIL
