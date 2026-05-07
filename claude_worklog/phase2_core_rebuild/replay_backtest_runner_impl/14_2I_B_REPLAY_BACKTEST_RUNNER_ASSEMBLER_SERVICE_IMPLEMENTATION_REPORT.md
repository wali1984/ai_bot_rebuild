# Phase 2I.B Replay/Backtest Runner Assembler Service Implementation Report

## Files authored
- v2/backend/app/services/replay_backtest_runner/__init__.py — 270 bytes
- v2/backend/app/services/replay_backtest_runner/errors.py — 409 bytes
- v2/backend/app/services/replay_backtest_runner/service.py — 8859 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/__init__.py — 0 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_calls_clock_exactly_once.py — 1115 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_exhaustive_over_paper_ledger_reasons.py — 2807 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_keyword_only_params.py — 1050 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_propagates_input_lineage_fields.py — 1587 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_record_allow_for_mirror_allow_proceed_long.py — 1332 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_record_allow_for_mirror_allow_proceed_short.py — 1168 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_record_deny_for_mirror_deny_default.py — 1275 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_record_deny_for_mirror_deny_orchestrator_abstained.py — 1317 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_record_deny_for_mirror_deny_orchestrator_held.py — 1262 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_records_clock_into_step_ts_ms.py — 974 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_rejects_clock_returning_before_run_started_ts_ms.py — 1280 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_rejects_clock_returning_negative.py — 1221 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_rejects_clock_returning_non_int.py — 1301 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_rejects_non_callable_clock.py — 1228 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_rejects_paper_ledger_entry_not_record.py — 841 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_rejects_paper_ledger_entry_symbol_mismatch.py — 1296 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_rejects_paper_trade_id_too_long_for_replay_step_id_derivation.py — 1882 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_rejects_replay_run_not_record.py — 1069 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_replay_step_id_derived_from_paper_trade_id.py — 1035 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_returned_record_is_live_blocked_true.py — 1074 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_returns_frozen_record.py — 1080 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_returns_replay_backtest_step.py — 1001 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_summary_aggregates_counts_for_mixed_steps.py — 2713 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_summary_calls_clock_exactly_once.py — 661 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_summary_keyword_only_params.py — 606 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_summary_records_clock_into_summary_emitted_ts_ms.py — 520 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_summary_rejects_clock_invalid.py — 1187 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_summary_rejects_replay_run_id_too_long_for_replay_summary_id_derivation.py — 1130 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_summary_rejects_replay_run_not_record.py — 578 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_summary_rejects_step_element_not_record.py — 768 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_summary_rejects_step_replay_run_id_mismatch.py — 1277 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_summary_rejects_steps_not_tuple.py — 786 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_summary_replay_summary_id_derived_from_replay_run_id.py — 525 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_summary_zero_steps_zero_counts.py — 1181 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assembler_service_does_not_import_redis.py — 760 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assembler_service_does_not_import_url_env.py — 388 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assembler_service_does_not_register_fastapi_lifespan.py — 552 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_assembler_service_forbidden_tokens.py — 1205 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_errors_invariants.py — 525 bytes
- v2/backend/tests/unit/services/replay_backtest_runner/test_public_surface.py — 461 bytes
- claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/14_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md — 19435 bytes
- claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/15_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_GO_NO_GO.md — 78 bytes

## Public surface
`("assemble_replay_backtest_step", "assemble_replay_backtest_summary", "ReplayBacktestRunnerServiceError")`

## Behavior contract steps satisfied
1. `assemble_replay_backtest_step` validates paper entry, run, and callable before invoking the clock: `service.py:36-52`.
2. `assemble_replay_backtest_step` invokes the clock once and validates exact int type, nonnegative value, and run-start guard before use: `service.py:52-67`.
3. `assemble_replay_backtest_step` enforces symbol equality before deriving the step id: `service.py:68-72` before `service.py:112`.
4. `assemble_replay_backtest_step` enforces the 122-character paper-trade-id cap before deriving the step id: `service.py:73-77` before `service.py:112`.
5. `assemble_replay_backtest_step` implements the five-row mirror table in order with defensive fallback: `service.py:79-110`.
6. `assemble_replay_backtest_step` constructs the step with literal `live_blocked=True` and unmodified lineage/input propagation: `service.py:112-128`.
7. `assemble_replay_backtest_summary` validates run, tuple, element type, and run-id match before invoking the clock: `service.py:137-164`.
8. `assemble_replay_backtest_summary` invokes the clock once and validates exact int type, nonnegative value, and run-start guard before use: `service.py:164-179`.
9. `assemble_replay_backtest_summary` enforces the 123-character run-id cap before deriving the summary id: `service.py:180-184` before `service.py:212`.
10. `assemble_replay_backtest_summary` computes all count fields in one linear pass and returns a frozen summary with literal `live_blocked=True`: `service.py:186-226`.
11. Summary partition equalities hold by construction because counts are partitioned by 2I.A step action/reason constants in the single pass: `service.py:195-210`.
12. Neither function contains caches, global mutation, logging/stdout, process/thread spawning, or I/O; both perform validation and value-object construction only: `service.py:30-226`.

## Validation commands run
- `.venv/bin/python -m py_compile v2/backend/app/services/replay_backtest_runner/__init__.py v2/backend/app/services/replay_backtest_runner/errors.py v2/backend/app/services/replay_backtest_runner/service.py` — exit 0; compile succeeded.
- `.venv/bin/python -m pytest v2/backend/tests/unit/services/replay_backtest_runner/ -q` — exit 0; 40 passed.
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/replay_backtest_runner/ -q` — exit 0; 51 passed.
- `.venv/bin/python -m pytest v2/backend/tests/unit/services/paper_execution_ledger/ -q` — exit 0; 28 passed.
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/paper_execution_ledger/ -q` — exit 0; 30 passed.
- `.venv/bin/python -m pytest v2/backend/tests/unit/services/risk_gateway/ -q` — exit 0; 29 passed.
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/risk_gateway/ -q` — exit 0; 32 passed.
- `.venv/bin/python -m pytest v2/backend/tests/unit/services/orchestrator_decision/ -q` — exit 0; 36 passed.
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/orchestrator_decision/ -q` — exit 0; 34 passed.
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_prediction_output/ -q` — exit 0; 31 passed.
- `git ls-files v2/backend/app/services/replay_backtest_runner.py` — exit 0; 0 output lines.
- `git ls-files v2/backend/app/services/replay_runner.py` — exit 0; 1 output line.
- `git diff --stat HEAD -- v2/backend/app/services/replay_runner.py` — exit 0; 0 output lines.
- `git ls-files v2/backend/app/services/paper_loop.py` — exit 0; 1 output line.
- `git diff --stat HEAD -- v2/backend/app/services/paper_loop.py` — exit 0; 0 output lines.
- `git diff --stat HEAD -- v2/backend/app/domain/replay_backtest_runner/` — exit 0; 0 output lines.
- `git diff --stat HEAD -- v2/backend/app/domain/paper_execution_ledger/` — exit 0; 0 output lines.
- `git status -s` over cross-isolation paths in safety boundary file — exit 0; two additive directory lines, zero lines outside additive 2I.B scope.
- Forbidden-token `rg --fixed-strings --case-sensitive <token> v2/backend/app/services/replay_backtest_runner/` scans — each scan returned zero output lines; no authored source match.

## Forbidden token scan
Each source-scan command used the required `rg --fixed-strings --case-sensitive <token> v2/backend/app/services/replay_backtest_runner/` form. `rg` exit code was 1 with zero output lines for every no-match token:

- `"re" + "dis"` — zero matches
- `"Re" + "dis"` — zero matches
- `"RE" + "DIS"` — zero matches
- `"aio" + "re" + "dis"` — zero matches
- `"hi" + "re" + "dis"` — zero matches
- `"ht" + "tpx"` — zero matches
- `"req" + "uests"` — zero matches
- `"fast" + "api"` — zero matches
- `"Fast" + "API"` — zero matches
- `"uvi" + "corn"` — zero matches
- `"star" + "lette"` — zero matches
- `"url" + "lib"` — zero matches
- `"sub" + "process"` — zero matches
- `"sock" + "et"` — zero matches
- `"os." + "environ"` — zero matches
- `"os." + "getenv"` — zero matches
- `"time." + "time"` — zero matches
- `"time." + "monotonic"` — zero matches
- `"time." + "sleep"` — zero matches
- `"date" + "time.now"` — zero matches
- `"date" + "time.utcnow"` — zero matches
- `"date" + "time"` — zero matches
- `"log" + "ging"` — zero matches
- `"pri" + "nt("` — zero matches
- `"url_" + "env"` — zero matches
- `"URL_" + "ENV"` — zero matches
- `"gamma." + "real"` — zero matches
- `"Risk" + "DecisionRecord"` — zero matches
- `"Orchestrator" + "DecisionRecord"` — zero matches
- `"sql" + "ite"` — zero matches
- `"sql" + "alchemy"` — zero matches
- `"par" + "quet"` — zero matches
- `"BEGIN" + "_FILE"` — zero matches
- `"END" + "_FILE"` — zero matches

## Cross-isolation diff
`git status -s` over the safety-boundary cross-isolation paths returned 2 lines:

```text
?? v2/backend/app/services/replay_backtest_runner/
?? v2/backend/tests/unit/services/replay_backtest_runner/
```

Filtered listing outside additive 2I.B scope: none.

## Placeholder integrity verification
- `git ls-files v2/backend/app/services/replay_backtest_runner.py` — 0 output lines; PASS.
- `git ls-files v2/backend/app/services/replay_runner.py` — 1 output line; PASS.
- `git diff --stat HEAD -- v2/backend/app/services/replay_runner.py` — 0 output lines; PASS.
- `git ls-files v2/backend/app/services/paper_loop.py` — 1 output line; PASS.
- `git diff --stat HEAD -- v2/backend/app/services/paper_loop.py` — 0 output lines; PASS.
- `git diff --stat HEAD -- v2/backend/app/domain/replay_backtest_runner/` — 0 output lines; PASS.
- `git diff --stat HEAD -- v2/backend/app/domain/paper_execution_ledger/` — 0 output lines; PASS.

## Final 44 file names
1. v2/backend/app/services/replay_backtest_runner/__init__.py
2. v2/backend/app/services/replay_backtest_runner/errors.py
3. v2/backend/app/services/replay_backtest_runner/service.py
4. v2/backend/tests/unit/services/replay_backtest_runner/__init__.py
5. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_calls_clock_exactly_once.py
6. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_exhaustive_over_paper_ledger_reasons.py
7. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_keyword_only_params.py
8. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_propagates_input_lineage_fields.py
9. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_record_allow_for_mirror_allow_proceed_long.py
10. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_record_allow_for_mirror_allow_proceed_short.py
11. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_record_deny_for_mirror_deny_default.py
12. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_record_deny_for_mirror_deny_orchestrator_abstained.py
13. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_record_deny_for_mirror_deny_orchestrator_held.py
14. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_records_clock_into_step_ts_ms.py
15. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_rejects_clock_returning_before_run_started_ts_ms.py
16. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_rejects_clock_returning_negative.py
17. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_rejects_clock_returning_non_int.py
18. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_rejects_non_callable_clock.py
19. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_rejects_paper_ledger_entry_not_record.py
20. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_rejects_paper_ledger_entry_symbol_mismatch.py
21. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_rejects_paper_trade_id_too_long_for_replay_step_id_derivation.py
22. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_rejects_replay_run_not_record.py
23. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_replay_step_id_derived_from_paper_trade_id.py
24. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_returned_record_is_live_blocked_true.py
25. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_returns_frozen_record.py
26. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_step_returns_replay_backtest_step.py
27. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_summary_aggregates_counts_for_mixed_steps.py
28. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_summary_calls_clock_exactly_once.py
29. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_summary_keyword_only_params.py
30. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_summary_records_clock_into_summary_emitted_ts_ms.py
31. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_summary_rejects_clock_invalid.py
32. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_summary_rejects_replay_run_id_too_long_for_replay_summary_id_derivation.py
33. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_summary_rejects_replay_run_not_record.py
34. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_summary_rejects_step_element_not_record.py
35. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_summary_rejects_step_replay_run_id_mismatch.py
36. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_summary_rejects_steps_not_tuple.py
37. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_summary_replay_summary_id_derived_from_replay_run_id.py
38. v2/backend/tests/unit/services/replay_backtest_runner/test_assemble_summary_zero_steps_zero_counts.py
39. v2/backend/tests/unit/services/replay_backtest_runner/test_assembler_service_does_not_import_redis.py
40. v2/backend/tests/unit/services/replay_backtest_runner/test_assembler_service_does_not_import_url_env.py
41. v2/backend/tests/unit/services/replay_backtest_runner/test_assembler_service_does_not_register_fastapi_lifespan.py
42. v2/backend/tests/unit/services/replay_backtest_runner/test_assembler_service_forbidden_tokens.py
43. v2/backend/tests/unit/services/replay_backtest_runner/test_errors_invariants.py
44. v2/backend/tests/unit/services/replay_backtest_runner/test_public_surface.py

## Safety review
- `re` + `dis` import — none observed.
- `aio` + `re` + `dis` / `hi` + `re` + `dis` / `re` + `dis.asyncio` import — none observed.
- `ht` + `tpx` / `req` + `uests` / `url` + `lib` import — none observed.
- `fast` + `api` / `uvi` + `corn` / `star` + `lette` import — none observed.
- `sub` + `process` invocation outside permitted import-isolation test files — none observed.
- `sock` + `et` import — none observed.
- `os.` + `environ` / `os.` + `getenv` read — none observed.
- wall-clock helper invocation in authored 2I.B source — none observed.
- module-level singleton, cache, or lock — none observed.
- `log` + `ging` or stdout emission — none observed.
- URL, token, key, or credential-shaped string emission — none observed.
- construction of `ReplayBacktestStep` or `ReplayBacktestSummary` with `live_blocked == False` — none observed.
- import of `v2.backend.app.domain.risk_gateway` — none observed.
- import of `v2.backend.app.domain.orchestrator_decision` — none observed.
- import of `v2.backend.app.domain.trainer_prediction_output` — none observed.
- emission of token `Risk` + `DecisionRecord` or `Orchestrator` + `DecisionRecord` in authored 2I.B source — none observed.
- modification of `v2/backend/app/services/replay_runner.py` or `v2/backend/app/services/paper_loop.py` — none observed.
- modification of `v2/backend/app/domain/replay/` or `v2/backend/app/domain/execution/` — none observed.
- modification of `v2/backend/app/domain/paper_execution_ledger/` or `v2/backend/app/domain/replay_backtest_runner/` — none observed.
- modification of any pre-existing prior-milestone artifact — none observed.
- ledger-persistence introduction — none observed.
- PnL / position sizing / quantity / price / fees / slippage introduction — none observed.
- replay engine / scheduler / background loop / paper trader / paper executor / shadow executor / strategy library introduction — none observed.
- composition-root binder introduction — none observed.

PHASE2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT_READY
