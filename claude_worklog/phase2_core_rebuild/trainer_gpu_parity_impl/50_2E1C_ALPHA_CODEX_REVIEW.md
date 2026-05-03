# Phase 2E1.C.alpha - Codex Review (revision 2, post-autofix)

## Rubric 1 - Public surface integrity: PASS

Evidence: `v2/backend/app/domain/trainer_liveness/__init__.py:1-13` imports only the liveness value objects, evaluator, error, and six reason constants for re-export. `__all__` is exactly the revision-2 11-name list at `v2/backend/app/domain/trainer_liveness/__init__.py:16-28`. `LIVENESS_ALERT_CODE`, `errors`, and 2E1.B trainer parity names are not present.

## Rubric 2 - LivenessSignalSnapshot: PASS

Evidence: `v2/backend/app/domain/trainer_liveness/signal_snapshot.py:18-32` defines the required frozen, slotted dataclass field set and ordering. Bool strictness is enforced at `signal_snapshot.py:34-38`; nonnegative and positive invariants are enforced at `signal_snapshot.py:39-53`; RSS-without-PID and worker-alive-without-worker-PID contradictions are enforced at `signal_snapshot.py:55-58`.

## Rubric 3 - LivenessSLAConfig: PASS

Evidence: `v2/backend/app/domain/trainer_liveness/sla_config.py:8-13` defines the required frozen, slotted dataclass field set and ordering. All four thresholds must be at least one via `sla_config.py:15-23`.

## Rubric 4 - LivenessAlert and reason constants: PASS

Evidence: all six post-autofix reason constants are defined at `v2/backend/app/domain/trainer_liveness/alert.py:9-14`; `_ALLOWED_LIVENESS_REASONS` contains exactly those six constants at `alert.py:16-25`; `LIVENESS_ALERT_CODE` is module-local at `alert.py:27`. The alert dataclass field ordering is at `alert.py:30-35`; alert-code, non-empty reasons, duplicate rejection, unknown rejection, and observation timestamp matching are enforced at `alert.py:37-48`.

## Rubric 5 - Evaluator six-rule behavior: PASS

Evidence: `v2/backend/app/domain/trainer_liveness/evaluator.py:23-26` rejects negative `now_ms` and `now_ms < snapshot.observation_ts_ms`. The six rules are evaluated in the required order: prediction age at `evaluator.py:30-34`, GPU batch age at `evaluator.py:36-40`, proposal age at `evaluator.py:42-46`, zero stream growth at `evaluator.py:48-54`, worker dead at `evaluator.py:56-57`, and fatal log signature at `evaluator.py:59-60`. Missing timestamps do not trigger age rules because each age branch guards on `is not None` at `evaluator.py:31`, `evaluator.py:37`, and `evaluator.py:43`. Worker-dead is independent of zero-growth because it is a separate branch at `evaluator.py:56-57`; the targeted regression test proves nonzero stream growth does not suppress it at `v2/backend/tests/unit/domain/trainer_liveness/test_evaluator_prediction_worker_dead.py:13-28`. Empty reasons return `None` at `evaluator.py:62-63`; alerts are returned with tuple ordering from the local reason list at `evaluator.py:65-70`.

## Rubric 6 - Out-of-band requirement compliance: PASS

Evidence: source uses `prediction_stream_id_growth` as an already-measured field at `v2/backend/app/domain/trainer_liveness/signal_snapshot.py:29` and consumes it directly at `v2/backend/app/domain/trainer_liveness/evaluator.py:48-54`; no XLEN-style measurement appears in the domain source. Forbidden-token grep over `v2/backend/app/domain/trainer_liveness` and `v2/backend/tests/unit/domain/trainer_liveness` returned zero hits for Redis, subprocess, network, legacy, environment, clock, GPU, and ML-library tokens. Implementation and autofix reports state no live trainer restart, Redis write/delete, legacy mutation, exchange action, deployment, or live trading enablement at `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/47_2E1C_ALPHA_IMPLEMENTATION_REPORT.md:12-13`, `47_2E1C_ALPHA_IMPLEMENTATION_REPORT.md:31-32`, and `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/71_CODEX_PARALLEL_TRAINER_LIVENESS_AUTOFIX_REPORT.md:24`.

## Rubric 7 - Hard-exclusion compliance: PASS

Evidence: trainer liveness source imports only dataclasses and sibling domain modules at `signal_snapshot.py:1-5`, `sla_config.py:1-5`, `alert.py:1-6`, and `evaluator.py:1-15`. Forbidden-token grep over source and test trees returned zero hits for subprocess, file I/O indicators, network clients, Redis, legacy imports, env reads, adapter reliance, live trainer calls, model/checkpoint/GPU/async/clock/numpy/torch/tensorflow tokens.

## Rubric 8 - END_FILE marker hygiene and py_compile: PASS

Evidence: `rg -n "^END_FILE:" v2/backend/app/domain/trainer_liveness v2/backend/tests/unit/domain/trainer_liveness` returned zero hits. `python3 -m py_compile $(rg --files v2/backend/app/domain/trainer_liveness v2/backend/tests/unit/domain/trainer_liveness -g '*.py')` exited 0 across all 18 Python files. `PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit/domain/trainer_liveness` passed with `24 passed in 0.02s`.

## Rubric 9 - Test coverage: FAIL

Evidence: the post-autofix targeted file exists and covers the critical regression at `v2/backend/tests/unit/domain/trainer_liveness/test_evaluator_prediction_worker_dead.py:13-28`. Multi-reason ordering with worker-dead is covered at `test_evaluator_multi_reason.py:18-44`, and public surface coverage includes the new reason at `test_public_surface.py:6-19`.

However, spec 43 requires many cases that are not present in the current test tree. Examples: all-Optional-int snapshot construction, negative `observation_ts_ms`, negative `proposal_stream_id_growth`, negative `trainer_rss_bytes`, nonpositive `trainer_pid`, nonpositive `prediction_worker_pid`, negative individual timestamp fields, invalid alert code, empty reasons, exact-SLA boundary, never-emitted prediction-age behavior, `now_ms < observation_ts_ms`, zero-growth with RSS zero, nonzero-growth no-alert, fatal-log false no-alert, three-reason subset ordering, and explicit `LIVENESS_ALERT_CODE` / `errors` absence assertions. Required cases are listed in `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/43_PHASE_2E1C_ALPHA_TEST_PLAN.md:31-44`, `43_PHASE_2E1C_ALPHA_TEST_PLAN.md:57-58`, `43_PHASE_2E1C_ALPHA_TEST_PLAN.md:74-89`, `43_PHASE_2E1C_ALPHA_TEST_PLAN.md:97-106`, `43_PHASE_2E1C_ALPHA_TEST_PLAN.md:117-133`; the current tests found by grep cover only a subset at `test_signal_snapshot_invariants.py:10-28`, `test_sla_config_invariants.py:8-34`, `test_alert_invariants.py:14-55`, `test_evaluator_no_alert.py:10-14`, `test_evaluator_age_exceeds.py:15-54`, `test_evaluator_zero_stream_growth.py:13-42`, `test_evaluator_fatal_log_signature.py:13-24`, and `test_evaluator_multi_reason.py:18-44`.

Remediation ask: add the missing spec-43 unit cases without changing the domain behavior unless a new test exposes a real defect.

## Rubric 10 - Cross-symbol isolation: PASS

Evidence: `rg -n "trainer_parity" v2/backend/app/domain/trainer_liveness v2/backend/tests/unit/domain/trainer_liveness` returned zero hits. `rg -n "trainer_liveness|Liveness|LIVENESS|liveness" v2/backend/app/domain/trainer_parity v2/backend/tests/unit/domain/trainer_parity` returned zero hits, so no liveness symbol is imported by or leaked into trainer_parity.

## Rubric 11 - Documentation alignment: FAIL

Evidence: source has no inline rationale documenting why deconflict freshness is captured but not consulted, why `None` timestamps do not trigger age reasons, or why worker-dead is independent of zero-growth; relevant implementation lines are field capture at `v2/backend/app/domain/trainer_liveness/signal_snapshot.py:25-28` and evaluator branches at `v2/backend/app/domain/trainer_liveness/evaluator.py:30-60`. The original implementation report remains pre-autofix stale: it lists reason constants for stale prediction, stale GPU batch, stale proposal, zero prediction stream growth, and fatal log signatures only at `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/47_2E1C_ALPHA_IMPLEMENTATION_REPORT.md:28-29`, and its test summary likewise omits worker-dead at `47_2E1C_ALPHA_IMPLEMENTATION_REPORT.md:47-48`. The autofix report and re-review accurately describe the current worker-dead state at `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/71_CODEX_PARALLEL_TRAINER_LIVENESS_AUTOFIX_REPORT.md:10-13` and `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/73_CODEX_PARALLEL_REREVIEW_TRAINER_LIVENESS_AUTOFIX.md:7-11`.

Remediation ask: update the formal implementation documentation or add a post-autofix addendum under milestone scope, and add concise inline rationale comments/docstrings for the three specified behaviors.

## Rubric 12 - Safety boundaries adherence: PASS

Evidence: safety boundaries forbid Redis, subprocess, legacy trainer, network, exchanges, deployment, and live trading at `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/44_PHASE_2E1C_ALPHA_SAFETY_BOUNDARIES.md:57-66` and `44_PHASE_2E1C_ALPHA_SAFETY_BOUNDARIES.md:103-104`. GO/NO-GO keeps `LIVE TRADING: BLOCKED` at `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/45_PHASE_2E1C_ALPHA_GO_NO_GO_REQUEST.md:41`. The reviewed domain has no external dependency, subprocess, Redis path, deployment path, or live-trading enablement by forbidden-token grep and source import review.

## Adversarial coverage probes

- Public surface, dataclass fields, and allowed reasons were inspected directly via `python3 -c`; observed 11 `__all__` names, the exact 13 snapshot fields, exact 4 SLA fields, and the exact six allowed reasons.
- Snapshot with all freshness timestamps in the future relative to `now_ms` returned `None`, confirming future timestamps do not accidentally trip strict age checks.
- Evaluator with `snapshot.observation_ts_ms == 0` and `now_ms == 0` returned `None`, confirming zero observation time is allowed.
- Worker-dead concurrent with prediction age, GPU age, proposal age, zero growth, and fatal log returned `('prediction_age_exceeds_sla', 'gpu_batch_age_exceeds_sla', 'proposal_age_exceeds_sla', 'prediction_stream_zero_growth', 'prediction_worker_dead', 'fatal_log_signature_observed')`.
- Negative `now_ms` raised `LivenessDomainError` with field `now_ms`; `now_ms < observation_ts_ms` raised `LivenessDomainError` with field `now_before_observation`.

## Autofix continuity check

The post-autofix evaluator and tests preserve the pre-autofix passing behaviors: stale prediction, GPU batch, and proposal alerts remain at `v2/backend/app/domain/trainer_liveness/evaluator.py:30-46`; zero-growth remains gated on parent PID and positive RSS at `evaluator.py:48-54`; fatal-log alert remains at `evaluator.py:59-60`; no-alert behavior remains at `evaluator.py:62-63`; multi-reason deterministic ordering remains covered at `v2/backend/tests/unit/domain/trainer_liveness/test_evaluator_multi_reason.py:18-44`. The autofix adds worker-dead at `evaluator.py:56-57` without nesting it under zero-growth, and the targeted test at `test_evaluator_prediction_worker_dead.py:13-28` confirms nonzero stream growth no longer suppresses it. Static forbidden-token grep, END_FILE grep, py_compile, and the liveness unit suite all passed after the autofix.

PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_FAIL
