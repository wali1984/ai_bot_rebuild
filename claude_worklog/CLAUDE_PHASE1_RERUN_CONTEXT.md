# Claude Phase 1 Rerun Context

This is a rerun of Claude Phase 1 coverage verification.

Previous Claude decision:
COVERAGE_VERIFICATION_NO_GO

Previous blockers:
- B-1 taxonomy mismatch
- B-2 unknown_exchange_use unresolved at scale
- B-3 Tier A raw review plan boilerplate
- B-4 trainer size discrepancy

Deterministic blocker fixes now complete:
- unsafe_unknown is 0.
- unknown_exchange_use is 0.
- blocking_unknown_exchange_use is 0.
- unresolved production exchange logic is preserved as exchange_unresolved_tier_a_review.
- exchange_unresolved_tier_a_review count is 1361.
- Tier A raw review plan has 11700 items.
- Every Tier A item has file/range/verification command.
- Coverage GO/NO-GO is GO.
- PHASE1_BLOCKER_FIX_REPORT final line is READY_TO_RERUN_CLAUDE_PHASE1.

Important:
exchange_unresolved_tier_a_review is not hidden risk. It is evidence-backed unresolved production exchange logic queued for Tier A raw review. Claude should verify whether this routing is acceptable for Phase 1 and whether it preserves risk visibility.

Do not build V2.
Do not modify legacy_reference.
Do not touch live bot.

Required outputs:
- claude_worklog/CLAUDE_PHASE1_COVERAGE_VERIFICATION.md
- claude_worklog/CLAUDE_PHASE1_BLOCKERS.md
- claude_worklog/CLAUDE_PHASE1_TIER_A_RAW_REVIEW_PLAN.md
- claude_worklog/CLAUDE_PHASE1_GO_NO_GO.md

Expected final GO/NO-GO line should be one of:
COVERAGE_VERIFICATION_GO
COVERAGE_VERIFICATION_NO_GO
