# Claude Phase 1 Blockers

## B-1 — `unsafe_unknown` metric mismatch (blocking)
- `tools/detect_coverage_gaps.py` checks for `classification_candidate == "unsafe_unknown"`.
- `tools/collect_script_registry.py` emits `quarantine_unknown` for unknown classes, not `unsafe_unknown`.
- Result: summary metric `unsafe_unknown_count: 0` is not a valid proof that unknown-risk scripts are zero.

Required fix:
- Either emit `unsafe_unknown` from registry builder, OR
- Update gap detector to count `quarantine_unknown`, and explicitly surface Tier A unknowns in `UNKNOWN_GAPS.md`.

## B-2 — `unknown_exchange_use` unresolved at scale (blocking)
- `EXCHANGE_ACTION_MAP.md` includes a large set of `unknown_exchange_use` matches.
- Current headline (`exchange_script_files_unclassified: 0`) only means files are registered; it does not mean exchange behavior is semantically resolved.

Required fix:
- Refine `collect_exchange_actions.py` to classify current `unknown_exchange_use` rows into concrete action classes, OR
- Produce a deterministic per-file unresolved exchange-action gap report and gate GO on its closure.

## B-3 — Tier A raw review plan is boilerplate (blocking)
- `HYBRID_TRAINER_TIER_A_REVIEW_PLAN.md` is static text and does not enumerate concrete line ranges/chunks.
- Data already exists in chunk outputs but is not converted into executable review steps.

Required fix:
- Build plan from `HYBRID_TRAINER_CHUNKS.json` + per-path extractor outputs (reward/confidence/signal/feature/checkpoint/redis).
- Include chunk IDs, line ranges, priority groups, and verification commands.

## B-4 — Trainer size documentation discrepancy (non-runtime blocker)
- `CLAUDE.md` references a 250k-line trainer rule while atlas primary target is ~57,250 lines.
- Coverage of the actual target file is complete, but documentation should be reconciled for audit trust.

Required fix:
- Update docs to reflect current primary file size, or document aggregate subsystem line count and atlas boundaries.

## Final blocker state
Because B-1/B-2/B-3 remain unresolved, Phase 1 result is:

`COVERAGE_VERIFICATION_NO_GO`
