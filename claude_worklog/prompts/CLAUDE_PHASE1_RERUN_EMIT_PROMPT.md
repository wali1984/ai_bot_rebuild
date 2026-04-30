You are in /home/wali/Desktop/AI BOT REBUILD.

This is a rerun of Claude Phase 1 coverage verification.

Read these inputs:
- PROJECT_STATE.md
- CLAUDE.md
- claude_worklog/CLAUDE_PHASE1_RERUN_CONTEXT.md
- claude_worklog/phase1_fixes/PHASE1_BLOCKER_FIX_REPORT.md
- claude_worklog/coverage/GO_NO_GO_COVERAGE.md
- claude_worklog/coverage/COVERAGE_SUMMARY.md
- claude_worklog/coverage/UNKNOWN_GAPS.md
- claude_worklog/coverage/EXCHANGE_ACTION_MAP.md
- claude_worklog/coverage/EXCHANGE_UNKNOWN_RESOLUTION.md
- claude_worklog/coverage/EXCHANGE_UNKNOWN_RESOLUTION_POLICY.md
- claude_worklog/coverage/TIER_A_RAW_REVIEW_PLAN.md
- claude_worklog/trainer_atlas/TRAINER_SIZE_RECONCILIATION.md
- claude_worklog/trainer_atlas/HYBRID_TRAINER_COVERAGE_REPORT.md
- claude_worklog/CLAUDE_PHASE1_TIER_A_RAW_REVIEW_PLAN.md

Task:
Verify whether previous Phase 1 blockers are fixed.

Check specifically:
1. unsafe_unknown is 0.
2. unknown_exchange_use is 0.
3. blocking_unknown_exchange_use is 0.
4. exchange_unresolved_tier_a_review is preserved and routed to Tier A raw review, not hidden.
5. Tier A raw review entries have file/start/end/verification command.
6. Trainer size discrepancy is reconciled.
7. Coverage GO/NO-GO is GO.
8. No V2 build has started.
9. legacy_reference remains read-only/evidence-only.
10. Remaining risks are documented as Tier A review items, not suppressed.

You are running in headless/non-interactive mode. Do NOT try to write files with tools. Instead, PRINT the full content for required files in this exact envelope format so an external wrapper can write them:

BEGIN_FILE: claude_worklog/CLAUDE_PHASE1_COVERAGE_VERIFICATION.md
<full file content>
END_FILE

BEGIN_FILE: claude_worklog/CLAUDE_PHASE1_BLOCKERS.md
<full file content>
END_FILE

BEGIN_FILE: claude_worklog/CLAUDE_PHASE1_TIER_A_RAW_REVIEW_PLAN.md
<full file content>
END_FILE

BEGIN_FILE: claude_worklog/CLAUDE_PHASE1_GO_NO_GO.md
<full file content must be exactly one line: COVERAGE_VERIFICATION_GO or COVERAGE_VERIFICATION_NO_GO>
END_FILE

Do not include any other text outside these BEGIN_FILE/END_FILE blocks.

Do not build V2.
Do not modify ./legacy_reference.
Do not modify ../AI BOT.
Do not read .env files.
Do not write Redis.
Do not start/stop/restart trainer, trader, Redis, or any live process.
Do not place orders.
Do not change leverage or margin mode.
Do not install packages.
Stop after printing the four blocks.
