# Codex adversarial coverage review

## Scope
- Post-Claude Phase-1 GO adversarial review
- Audit-only checks in AI BOT REBUILD
- No V2 build actions

## Preconditions
- Claude Phase-1 decision: `COVERAGE_VERIFICATION_GO`
- Coverage gate decision: `GO`
- Working tree was clean before Codex review steps

## Machine checks summary
Source: `claude_worklog/codex/CODEX_MACHINE_CHECKS.txt`

- `unknown_exchange_use`: 0
- `unsafe_unknown`: 0
- `exchange_unresolved_tier_a_review`: 1361
- `unresolved_missing_tier_a_review`: 0
- `tier_a_items`: 11700
- `tier_a_items_missing_fields`: 0

Interpretation:
- Blocking unknown classes are zero.
- Unresolved exchange items are preserved and routed to Tier A (not hidden).

## Targeted grep evidence
- `claude_worklog/codex/CODEX_TARGETED_EXCHANGE_GREP.txt`
- `claude_worklog/codex/CODEX_TARGETED_REDIS_GREP.txt`
- `claude_worklog/codex/CODEX_TARGETED_TRAINER_GREP.txt`

## Cross-check against Tier A plan
Source: `claude_worklog/codex/CODEX_GREP_VS_TIER_A_COVERAGE.md`

- Tier A entries: 11700
- Tier A unique files: 655
- Grep unique files: 550
- Intersection files: 437
- Tier A files missing in grep set: 218
- High-risk Tier A files missing from grep evidence: 217

Adversarial finding:
- Targeted grep evidence does **not** sufficiently cover Tier A high-risk file space.
- This is a review-evidence gap (not a production-runtime verdict), but it blocks a strict adversarial PASS.

## Required remediation before PASS
1. Expand targeted grep coverage to include remaining high-risk Tier A files.
2. Re-run grep-vs-tier-a cross-check and reduce high-risk missing set to acceptable threshold (ideally zero for core exchange/redis/trainer paths).
3. Re-issue Codex adversarial review decision.

CODEX_COVERAGE_REVIEW_FAIL
