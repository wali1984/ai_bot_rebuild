# Phase 1 Blocker Fix Start

## B-1 taxonomy mismatch
- Blocker: `unsafe_unknown` metric is checked, but registry emitted `quarantine_unknown`.
- Likely source files:
  - `tools/collect_script_registry.py`
  - `tools/detect_coverage_gaps.py`
- Intended fix:
  - Canonicalize unknown classification to `unsafe_unknown` in registry output.
  - Keep defensive backward-compat handling for legacy `quarantine_unknown` in gap detector.
  - Add taxonomy note in coverage summary markdown.

## B-2 unknown_exchange_use unresolved at scale
- Blocker: exchange classifier overuses `unknown_exchange_use`, reducing audit precision.
- Likely source files:
  - `tools/collect_exchange_actions.py`
  - `claude_worklog/coverage/EXCHANGE_ACTION_MAP.*` (regenerated)
- Intended fix:
  - Implement richer context-aware exchange action taxonomy.
  - Add confidence/reason/context/evidence fields.
  - Generate `EXCHANGE_UNKNOWN_RESOLUTION.md` with before/after and unresolved breakdown.

## B-3 Tier A raw review plan boilerplate
- Blocker: plan is static and not line-range actionable.
- Likely source files:
  - `tools/build_hybrid_trainer_atlas.py` (existing static tier plan output)
  - new `tools/build_tier_a_raw_review_plan.py`
- Intended fix:
  - Build deterministic `TIER_A_RAW_REVIEW_PLAN.json/.md` from coverage + trainer atlas artifacts.
  - Require each entry to include file/range/category/priority/evidence/verification command.
  - Sync `claude_worklog/CLAUDE_PHASE1_TIER_A_RAW_REVIEW_PLAN.md` from generated plan.

## B-4 trainer size discrepancy
- Blocker: docs state >250k line trainer while primary file is ~57k lines.
- Likely source files:
  - `CLAUDE.md`
  - `claude_worklog/trainer_atlas/*`
- Intended fix:
  - Compute exact file metrics and hash.
  - Create `claude_worklog/trainer_atlas/TRAINER_SIZE_RECONCILIATION.md`.
  - Update doc wording to use canonical measured statement.
