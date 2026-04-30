# Claude Phase 1 Tier A Raw Review Plan

## Goal
Convert existing trainer-atlas and coverage artifacts into deterministic, command-driven raw review steps.

## Preconditions
- Use read-only verification tools only:
  - `tools/show_file_range.py`
  - `tools/show_trainer_section.py`
- Do not modify `legacy_reference`.
- Do not run live bot/runtime commands.

## Track A — Trainer chunk raw review
Use `HYBRID_TRAINER_CHUNKS.json` / `HYBRID_TRAINER_CHUNK_CLASSIFICATION.md` as source of truth.

### A1. Boundary integrity
- Verify first and last ranges:
  - `python3 tools/show_trainer_section.py --trainer-file ./legacy_reference/rl/hybrid_trainer.py --start 1 --end 120`
  - `python3 tools/show_trainer_section.py --trainer-file ./legacy_reference/rl/hybrid_trainer.py --start 57180 --end 57250`

### A2. Reward/confidence/signal/checkpoint slices
- Cross-reference extractor outputs and sample high-density line regions:
  - `python3 tools/show_file_range.py --file ./claude_worklog/trainer_atlas/HYBRID_TRAINER_REWARD_PATHS.json --start 1 --end 220`
  - `python3 tools/show_file_range.py --file ./claude_worklog/trainer_atlas/HYBRID_TRAINER_CONFIDENCE_PATHS.json --start 1 --end 220`
  - `python3 tools/show_file_range.py --file ./claude_worklog/trainer_atlas/HYBRID_TRAINER_SIGNAL_PATHS.json --start 1 --end 220`
  - `python3 tools/show_file_range.py --file ./claude_worklog/trainer_atlas/HYBRID_TRAINER_CHECKPOINT_PATHS.json --start 1 --end 220`

### A3. Redis write validation
- Validate redis write classifications and sample referenced lines:
  - `python3 tools/show_file_range.py --file ./claude_worklog/trainer_atlas/HYBRID_TRAINER_REDIS_WRITE_CLASSIFICATION.md --start 1 --end 260`

## Track B — Coverage unknown-risk closure

### B1. Unknown class mismatch closure
- Compare detector vs registry labels:
  - `python3 tools/show_file_range.py --file ./tools/detect_coverage_gaps.py --start 1 --end 180`
  - `python3 tools/show_file_range.py --file ./tools/collect_script_registry.py --start 1 --end 260`

### B2. Unknown exchange-action closure
- Review unresolved entries from exchange map:
  - `python3 tools/show_file_range.py --file ./claude_worklog/coverage/EXCHANGE_ACTION_MAP.md --start 1 --end 260`

### B3. Tier A unknown scripts sample
- Review unknown entries and prioritize Tier A impact:
  - `python3 tools/show_file_range.py --file ./claude_worklog/coverage/SCRIPT_REGISTRY.md --start 1 --end 260`
  - `python3 tools/show_file_range.py --file ./claude_worklog/coverage/UNKNOWN_GAPS.md --start 1 --end 260`

## Exit criteria for GO reconsideration
- Unknown class metric aligned (`unsafe_unknown` vs `quarantine_unknown`) and reflected in summary.
- `unknown_exchange_use` resolved or explicitly gated with deterministic unresolved report.
- Tier A plan regenerated with concrete chunk-by-chunk line ranges + verification commands.
- Re-run Phase 1 and regenerate GO/NO-GO.
