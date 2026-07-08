# V2 Repo Cleanup Report
Goal: V2_REPO_CLEANUP_RUNTIME_SAFE_SOURCE_TREE_AND_ARTIFACT_ARCHIVE_READY
Date: 2026-07-01
Status: READY

---

## FINAL NUMBERS

Files archived: 480
Bytes archived: 775 MB
Cache dirs deleted: 620 (__pycache__)
Pyc files deleted: 6,245
Other caches deleted: pytest_cache, htmlcov, coverage, playwright-report, test-results, tsbuildinfo, DS_Store
Files requiring operator review: 9 dirs/items
Active runtime disruption: None
Archive location: /home/wali/AI_BOT_REBUILD_REPO_CLEANUP_ARCHIVE/20260701_184046/files/
Backend compile: PASS
Tests: 138 passed
Validation: PASS

---

## PHASE 0 — Runtime Lock (PASS)

- 46 active wali-owned processes detected, none stopped
- 8 active goal_state dirs excluded from cleanup
- 14 active operator_runtime payload dirs excluded
- DB files (leases.db, v2_paper_trading.db) untouched
- Redis service untouched

---

## PHASE 2 — Cache Deletion (PASS)

Deleted without archive (all regeneratable by build tools):
- 620 __pycache__/ directories
- 6,245 *.pyc files
- 2 .pytest_cache/ directories
- .coverage, htmlcov/, playwright-report/, test-results/ artifacts
- *.tsbuildinfo, .DS_Store files

Excluded from cache cleanup: legacy_reference/, .venv/, venv/, .claude/worktrees/

---

## PHASE 4 — Archive + Delete (PASS)

All 17 items below were archived then deleted from repo:

1. goal_state/V2_ACTIVE_PAPER_RUNTIME_OWNER_CUTOVER_CUDA_SIGNAL_CHAIN_AND_COMPOUNDING_REPAIR (572K)
   - Inactive goal, no backend or frontend code references
2. goal_state/V2_ADAPTIVE_CAPITAL_OUT_OF_SAMPLE_EVIDENCE_PRODUCER_AND_LIVE_GRADE_REVERIFY (539M)
   - Inactive goal, no backend or frontend code references
3. goal_state/V2_CHALLENGER_BLIND_LOCKBOX_CURRENT_MARKET_SUPPLY_RUNTIME_BINDING_AND_PAPER_CANARY (1.9M)
   - Inactive goal, no backend or frontend code references
4. goal_state/V2_CLAUDE_CONTINUOUS_ADVERSARIAL_VALIDATION_AND_CAPITAL_PRODUCTIVITY_GUARDIAN.premature-complete.20260620T195354Z (204K)
   - Premature marker dir from 2026-06-20
5. goal_state/V2_CLAUDE_PERFORMANCE_REGRESSION_RECOVERY_VERIFIER (32K)
   - Inactive goal, no backend or frontend code references
6. recorded_state_verification_pass2a/ (13M)
7. recorded_state_verification_pass2b/ (2.2M)
8. recorded_state_verification_pass3a/ (2.2M)
9. recorded_state_verification_pass3b/ (2.2M)
10. recorded_state_verification_pass3c/ (2.2M)
11. recorded_state_verification_pass4a/ (18M)
    - All pass2-pass4 dirs: completed audit snapshots, no code references
12. pipeline_trust_quarantine/ (17M)
    - Listed in .gitignore, no backend/frontend references
13. screenshots/ — 136 files cleared (177M)
    - Auto-generated Playwright/crawl screenshots, regeneratable
14. v2/frontend/public/v2_zero_exception_parity_codex_review_burndown_20260531/ (740K)
15. v2/frontend/public/historical_30d_replay_and_paper_proof/ (156K)
16. v2/frontend/public/8h_trade_readiness/ (84K)
17. v2/frontend/public/api/ (24K)
    - Items 14-17: Old public proof dirs from May/June 2026, no code references

TOTAL ARCHIVED: ~775 MB across 480 files

---

## PHASE 5 — Source Review (PASS, no deletions)

Scanned for DEPRECATED, DO_NOT_USE, paper_online_runtime, bridge, wrapper markers.
All found instances are legitimate field names or docstrings in active code.
No source files deleted. All marked REVIEW_REQUIRED requiring operator approval.

---

## PHASE 6 — Frontend Public Cleanup (PASS)

Old non-latest public proof dirs (older than 14 days, not under operator_runtime/) archived and deleted.
v2/frontend/public/operator_runtime/* fully preserved.
v2/frontend/dist/ preserved — actively served as the dashboard frontend.

---

## PHASE 7 — Backend Validation (PASS)

compile: OK (main.py, paper_loop, risk_gateway, orchestrator_loop)
paper loop tests: 138 passed, 0 failed

---

## PHASE 9 — Git Hygiene (PASS)

Added to .gitignore (were missing, patterns now prevent future tracking):
  .pytest_cache/
  .mypy_cache/
  .ruff_cache/
  .coverage
  htmlcov/
  *.tsbuildinfo
  playwright-report/
  test-results/
  .DS_Store
  Thumbs.db

---

## WHAT WAS NOT CLEANED

legacy_reference/ (290G) — read-only audit source per CLAUDE.md constraint
v2/legacy_owned_runtime/data/ (113G) — ingestor JSONL data feeds being actively written
claude_worklog/agent_supervisor/events.jsonl (5.4G) — active agent supervisor event log
v2/backend/market_stream_alert_history.jsonl (12G) — market stream telemetry
v2/frontend/dist/ (7.8G) — dashboard served in production, must not delete
.local_data/v2_native_trainer/ (9.2G) — trainer snapshot archive
.claude/worktrees/ (4.1G) — agent worktrees with uncommitted changes
claude_worklog/final_readiness/ (21G) — modified in last 72h, excluded per lock policy
7 goal_state dirs with backend code references — kept per safety rule
.venv/, venv/ (8.2G) — hard constraint, do not touch

---

## OPERATOR REVIEW REQUIRED

See repo_cleanup_review_required_files.txt

Top priority items:
1. goal_state/V2_P0_DIRECTIONAL_EXIT_EXECUTION_RISK_AND_ADAPTIVE_CAPITAL_REMEDIATION
   Actively read by v2_adaptive_capital_productivity_status.py:9698. NEVER ARCHIVE.
2. goal_state/V2_CHALLENGER_V2_REPRODUCIBLE_COST_PARITY_* (1.8G)
   Active GOAL_ID in challenger pipeline. Do not archive.
3. .claude/worktrees/ (4.1G) — 4 worktrees with uncommitted changes. Investigate per-worktree.
4. v2/frontend/dist/ (7.8G) — production frontend. Never delete.

---

## RESTORE

Archive: /home/wali/AI_BOT_REBUILD_REPO_CLEANUP_ARCHIVE/20260701_184046/files/
Instructions: repo_cleanup_restore_instructions.md

