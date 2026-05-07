# Phase 2I.A Replay/Backtest Runner Domain Codex Review

## Worktree precondition check

- PASS: `git status --porcelain` returned zero output lines before review artifact emission.

## Predecessor marker check

- PASS: `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/07_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_GO_NO_GO.md` contained exactly `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_IMPL_AND_VALIDATION_PASSED`.
- PASS: `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/26_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` contained exactly `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_PASS`.

## Files reviewed

- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/00_PHASE_2I_SUB_PHASE_BREAKDOWN.md` lines 1-50.
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/01_PHASE_2I_LEGACY_EVIDENCE_REVIEW.md` lines 1-52.
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/02_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_SPEC.md` lines 1-303.
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/03_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_TEST_PLAN.md` lines 1-92.
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/04_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_SAFETY_BOUNDARIES.md` lines 1-92.
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/05_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_GO_NO_GO_REQUEST.md` lines 1-49.
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/06_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_IMPLEMENTATION_REPORT.md` lines 1-247.
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/07_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_GO_NO_GO.md` line 1.
- `v2/backend/app/domain/replay_backtest_runner/__init__.py` lines 1-29.
- `v2/backend/app/domain/replay_backtest_runner/errors.py` lines 1-9.
- `v2/backend/app/domain/replay_backtest_runner/run.py` lines 1-82.
- `v2/backend/app/domain/replay_backtest_runner/step.py` lines 1-200.
- `v2/backend/app/domain/replay_backtest_runner/summary.py` lines 1-116.
- `v2/backend/tests/unit/domain/replay_backtest_runner/__init__.py` zero bytes.
- 51 test files under `v2/backend/tests/unit/domain/replay_backtest_runner/` enumerated by 03 lines 11-73; local `wc -l` confirmed each file exists, one test function per file, and 915 total test-source lines.

## Placeholder verification

- PASS: `git ls-files v2/backend/app/domain/replay_backtest_runner.py` returned zero output lines.
- PASS: `git ls-files v2/backend/app/services/replay_runner.py` returned `v2/backend/app/services/replay_runner.py`.
- PASS: `git diff --stat HEAD -- v2/backend/app/services/replay_runner.py` returned zero output lines.
- PASS: `git ls-files v2/backend/app/domain/replay/` returned exactly `v2/backend/app/domain/replay/__init__.py` and `v2/backend/app/domain/replay/deterministic.py`.
- PASS: `git diff --stat HEAD -- v2/backend/app/domain/replay/` returned zero output lines.
- PASS: `git ls-files v2/backend/app/domain/execution/` returned exactly `v2/backend/app/domain/execution/__init__.py`, `v2/backend/app/domain/execution/intent.py`, and `v2/backend/app/domain/execution/paper.py`.
- PASS: `git diff --stat HEAD -- v2/backend/app/domain/execution/` returned zero output lines.
- PASS: `git diff --stat HEAD -- v2/backend/app/domain/paper_execution_ledger/` returned zero output lines.

## Rubric findings

1. PASS: Public surface order matches 02; evidence `02_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_SPEC.md` lines 35-51 and `__init__.py` lines 15-29.
2. PASS: `__all__` tuple length is 13; evidence `__init__.py` lines 15-29.
3. PASS: `errors.py` imports limited to future annotations; evidence `errors.py` line 1.
4. PASS: `run.py` imports limited to future annotations, dataclass, and local error; evidence `run.py` lines 1-5.
5. PASS: `step.py` imports identical pattern; evidence `step.py` lines 1-5.
6. PASS: `summary.py` imports identical pattern; evidence `summary.py` lines 1-5.
7. PASS: `__init__.py` imports limited to relative re-exports per 02; evidence `__init__.py` lines 1-13 and 02 lines 269-274.
8. PASS: `ReplayBacktestRun` is frozen and slotted; evidence `run.py` line 31.
9. PASS: `ReplayBacktestStep` is frozen and slotted; evidence `step.py` line 70.
10. PASS: `ReplayBacktestSummary` is frozen and slotted; evidence `summary.py` line 32.
11. PASS: `RUN_MODE_REPLAY` equals literal lowercase replay; evidence `run.py` line 8.
12. PASS: `RUN_MODE_BACKTEST` equals literal lowercase backtest; evidence `run.py` line 9.
13. PASS: `STEP_ACTION_RECORD_ALLOW` equals documented literal; evidence `step.py` line 8.
14. PASS: `STEP_ACTION_RECORD_DENY` equals documented literal; evidence `step.py` line 9.
15. PASS: Five `STEP_REASON_MIRROR_*` constants equal documented literals; evidence `step.py` lines 11-17 and 02 lines 123-127.
16. PASS: Every allow mirror reason starts with the required allow prefix; evidence `step.py` lines 11-12.
17. PASS: Every deny mirror reason starts with the required deny prefix; evidence `step.py` lines 13-17.
18. PASS: Run ID charset and length are enforced; evidence `run.py` lines 18-28 and 40-42.
19. PASS: Run mode frozenset membership is enforced; evidence `run.py` lines 11 and 43-46.
20. PASS: Symbol uppercase invariant is enforced; evidence `run.py` lines 48-57.
21. PASS: `run_started_ts_ms` int-not-bool and non-negative invariant is enforced; evidence `run.py` lines 59-64.
22. PASS: `run_ended_ts_ms >= run_started_ts_ms` is enforced; evidence `run.py` lines 66-74.
23. PASS: `ReplayBacktestRun.live_blocked` must be true; evidence `run.py` lines 76-82.
24. PASS: Seven step ID fields use per-field identifier validation; evidence `step.py` lines 50-60 and 87-94.
25. PASS: `step_action` frozenset membership is enforced; evidence `step.py` lines 19-24 and 112.
26. PASS: `step_reason_code` frozenset membership is enforced; evidence `step.py` lines 25-33 and 113-117.
27. PASS: `input_paper_action` frozenset membership is enforced; evidence `step.py` lines 34 and 118-122.
28. PASS: `input_paper_reason_code` frozenset membership is enforced; evidence `step.py` lines 35-43 and 123-127.
29. PASS: Allow action requires allow-prefixed step reason; evidence `step.py` lines 137-142.
30. PASS: Deny action requires deny-prefixed step reason; evidence `step.py` lines 149-154.
31. PASS: Allow action requires record-allow input action; evidence `step.py` lines 143-147.
32. PASS: Deny action requires record-deny input action; evidence `step.py` lines 155-159.
33. PASS: Five one-to-one step/input reason mappings are enforced; evidence `step.py` lines 161-200.
34. PASS: `ReplayBacktestStep.live_blocked` must be true; evidence `step.py` lines 129-135.
35. PASS: Summary ID charset and length are enforced; evidence `summary.py` lines 12-22 and 47-49.
36. PASS: Summary emitted timestamp int-not-bool and non-negative invariant is enforced; evidence `summary.py` lines 51-56.
37. PASS: Every count field is int-not-bool and non-negative; evidence `summary.py` lines 25-29 and 58-80.
38. PASS: Action partition-sum equality is enforced; evidence `summary.py` lines 90-97.
39. PASS: Allow-subreason partition-sum equality is enforced; evidence `summary.py` lines 98-106.
40. PASS: Deny-subreason partition-sum equality is enforced; evidence `summary.py` lines 107-116.
41. PASS: `ReplayBacktestSummary.live_blocked` must be true; evidence `summary.py` lines 82-88.
42. PASS: `.venv/bin/python -m pytest v2/backend/tests/unit/domain/replay_backtest_runner/ -q` exited 0; output `51 passed in 0.36s`.
43. PASS: `.venv/bin/python -m pytest v2/backend/tests/unit/domain/paper_execution_ledger/ -q` exited 0; output `30 passed in 0.19s`.
44. PASS: `.venv/bin/python -m pytest v2/backend/tests/unit/domain/risk_gateway/ -q` exited 0; output `32 passed in 0.06s`.
45. PASS: `.venv/bin/python -m pytest v2/backend/tests/unit/domain/orchestrator_decision/ -q` exited 0; output `34 passed in 0.05s`.
46. PASS: `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_prediction_output/ -q` exited 0; output `31 passed in 0.06s`.
47. PASS: py_compile of all five authored source files exited 0 with zero stderr/stdout.
48. PASS: Forbidden-token rg sweep over authored source returned zero matches for every 02 token; command output reported `rc=1 lines=0` for each no-match scan.
49. PASS: `git diff --stat HEAD -- v2/backend/app/domain/paper_execution_ledger/` returned zero output lines.
50. PASS: `git ls-files v2/backend/app/domain/replay_backtest_runner.py` returned zero output lines.
51. PASS: `git ls-files v2/backend/app/services/replay_runner.py` returned exactly one output line and service diff stat returned zero output lines.
52. PASS: `git ls-files v2/backend/app/domain/replay/` returned exactly two output lines and replay diff stat returned zero output lines.
53. PASS: `git ls-files v2/backend/app/domain/execution/` returned exactly three output lines and execution diff stat returned zero output lines.
54. PASS: Cross-isolation `git status -s` over the 04 path list returned zero lines outside additive 2I.A scope.
55. PASS: Paper-ledger, risk, and orchestrator record class tokens are absent from authored source; fixed-string scans returned zero output lines.
56. PASS: FastAPI/server-framework tokens are absent from authored source; fixed-string scan returned zero output lines.
57. PASS: No module-level singleton, cache, lock primitive, or wall-clock helper invocation observed; fixed-string scan for `threading`, `Lock`, `RLock`, `lru_cache`, `cache`, and `singleton` returned zero output lines.
58. PASS: No environment reads observed; fixed-string scan for `os.environ` and `os.getenv` returned zero output lines.
59. PASS: No subprocess invocation outside permitted import-isolation tests; source scan returned zero lines and test scan found only import-isolation test files from 03 lines 11-23.
60. PASS: Safety-boundary scan in 06 reports none observed for every forbidden runtime behavior; evidence `06_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_IMPLEMENTATION_REPORT.md` lines 221-245.

## Validation commands run

- `git status --porcelain` - exit 0; zero output lines.
- `.venv/bin/python -m py_compile v2/backend/app/domain/replay_backtest_runner/__init__.py v2/backend/app/domain/replay_backtest_runner/errors.py v2/backend/app/domain/replay_backtest_runner/run.py v2/backend/app/domain/replay_backtest_runner/step.py v2/backend/app/domain/replay_backtest_runner/summary.py` - exit 0; zero stderr/stdout.
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/replay_backtest_runner/ -q` - exit 0; 51 passed.
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/paper_execution_ledger/ -q` - exit 0; 30 passed.
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/risk_gateway/ -q` - exit 0; 32 passed.
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/orchestrator_decision/ -q` - exit 0; 34 passed.
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_prediction_output/ -q` - exit 0; 31 passed.
- `git ls-files v2/backend/app/domain/replay_backtest_runner.py` - exit 0; zero output lines.
- `git ls-files v2/backend/app/services/replay_runner.py` - exit 0; one output line.
- `git diff --stat HEAD -- v2/backend/app/services/replay_runner.py` - exit 0; zero output lines.
- `git ls-files v2/backend/app/domain/replay/` - exit 0; two output lines.
- `git diff --stat HEAD -- v2/backend/app/domain/replay/` - exit 0; zero output lines.
- `git ls-files v2/backend/app/domain/execution/` - exit 0; three output lines.
- `git diff --stat HEAD -- v2/backend/app/domain/execution/` - exit 0; zero output lines.
- `git diff --stat HEAD -- v2/backend/app/domain/paper_execution_ledger/` - exit 0; zero output lines.
- `git status -s -- <04 cross-isolation path list>` - exit 0; zero output lines.

## Forbidden token scan

- `red` + `is`: zero matches.
- `aio` + `red` + `is`: zero matches.
- `hire` + `dis`: zero matches.
- `fast` + `api`: zero matches.
- `uvi` + `corn`: zero matches.
- `star` + `lette`: zero matches.
- `htt` + `px`: zero matches.
- `requ` + `ests`: zero matches.
- `get` + `env`: zero matches.
- `en` + `viron`: zero matches.
- `sub` + `process`: zero matches in authored source.
- `sock` + `et`: zero matches.
- `log` + `ging`: zero matches.
- `time` + `.` + `time`: zero matches.
- `time` + `.` + `monotonic`: zero matches.
- `datetime` + `.` + `now`: zero matches.
- `datetime` + `.` + `utcnow`: zero matches.
- `PaperExecution` + `LedgerEntry`: zero matches.
- `RiskDecision` + `Record`: zero matches.
- `OrchestratorDecision` + `Record`: zero matches.
- `sql` + `ite`: zero matches.
- `sql` + `alchemy`: zero matches.
- `par` + `quet`: zero matches.

## Cross-isolation diff

- PASS: `git status -s` over the 04 path list returned zero output lines outside the additive 2I.A scope.

## Concrete blockers

- Zero rows.

## Safety review

- Redis import: none observed.
- aio/hire/async Redis import: none observed.
- HTTP client import: none observed.
- FastAPI / uvicorn / starlette import: none observed.
- subprocess invocation outside permitted import-isolation test files: none observed.
- socket import: none observed.
- os.environ / os.getenv read: none observed.
- wall-clock helper invocation in authored 2I.A source: none observed.
- module-level singleton, cache, or lock: none observed.
- logging or stdout emission: none observed.
- URL, token, key, or credential-shaped string emission: none observed.
- construction of `ReplayBacktestRun` / `ReplayBacktestStep` / `ReplayBacktestSummary` with `live_blocked == False`: none observed.
- flat-file placeholder forbidden-introduction row: none observed.
- replay_runner.py forbidden-modification row: none observed.
- v2/backend/app/domain/replay/ forbidden-population row: none observed.
- v2/backend/app/domain/execution/ forbidden-population row: none observed.
- v2/backend/app/domain/paper_execution_ledger/ forbidden-modification row: none observed.
- ledger-persistence forbidden-introduction row: none observed.
- PnL / position sizing / quantity / price / fees / slippage forbidden-introduction row: none observed.
- import of paper-execution-ledger value-object domain: none observed.
- emission of paper-ledger entry token in authored 2I.A source: none observed.
- emission of risk/orchestrator record tokens in authored 2I.A source: none observed.
- modification of any pre-existing prior-milestone artifact: none observed.
- replay engine / scheduler / background loop / paper trader process / paper executor / shadow executor / strategy library introduction: none observed.

## Recommendation

PASS

PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_REVIEW_READY
