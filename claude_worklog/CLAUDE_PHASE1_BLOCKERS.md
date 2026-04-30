# Claude Phase 1 Blockers (Rerun)

Date: 2026-04-30
Status: **0 blocking, 0 unresolved-suppressed, 7 conditions-on-GO carried into Phase 2**

## Prior blockers (from first Claude Phase 1 run)

| ID | Blocker | Prior status | Current status | Evidence of fix |
|---|---|---|---|---|
| B-1 | Taxonomy mismatch (canonical unknown class undefined; `quarantine_unknown` vs `unsafe_unknown` divergence) | BLOCKING | RESOLVED | `COVERAGE_SUMMARY.md:Taxonomy` declares canonical class = `unsafe_unknown`; `UNKNOWN_GAPS.md` line 3 "Canonical class: unsafe_unknown"; `COVERAGE_SUMMARY.json:unsafe_unknown_canonical_label="unsafe_unknown"`; grep for `quarantine_unknown` across `claude_worklog/coverage/` returns zero matches; `PHASE1_BLOCKER_FIX_REPORT.md` confirms "no generated report uses `quarantine_unknown` as canonical output class". |
| B-2 | unknown_exchange_use unresolved at scale (3,996 → 0 reclassification path unverified) | BLOCKING | RESOLVED via routed-to-Tier-A | `EXCHANGE_UNKNOWN_RESOLUTION.md`: `unknown_exchange_use_before=12439`, `unknown_exchange_use_after=0`, `blocking_unknown_exchange_use=0`, `exchange_unresolved_tier_a_review=1361`; `COVERAGE_SUMMARY.json` confirms zero unknown and zero blocking. The 1,361 unresolved items are not silently dropped — they are reclassified into the explicit `exchange_unresolved_tier_a_review` class, counted in the coverage summary, and queued in the Tier A plan with verification commands. `exchange_unresolved_missing_tier_a_plan_count=0`. |
| B-3 | Tier A raw review plan was boilerplate (entries lacked actionable file/start/end/verification command) | BLOCKING | RESOLVED | `TIER_A_RAW_REVIEW_PLAN.json` total=11,700 with `"file"`, `"start_line"`, `"end_line"`, `"verification_command"` present on each (raw counts confirmed: 11700/11700 for each field). Sample verification command: `python3 tools/show_trainer_section.py --trainer-file ./legacy_reference/rl/hybrid_trainer.py --start 1360 --end 1370`. Both helper scripts (`tools/show_file_range.py`, `tools/show_trainer_section.py`) exist on disk. Priority breakdown P0=5,186, P1=1,265, P2=5,249 matches header. |
| B-4 | Trainer size discrepancy (>250k claim vs actual measurement) | BLOCKING | RESOLVED | `TRAINER_SIZE_RECONCILIATION.md` is the canonical artifact (per CLAUDE.md "Trainer Size Reconciliation Rule"). Measured: `legacy_reference/rl/hybrid_trainer.py` = 57,250 lines, 3,165,342 bytes, sha256 `b7dad66b63b57c0d5c29e0fbaf67466d9c2aab81baf7a4f67b6e681e38c5b102`. Stated subsystem caveat preserved: broader trainer subsystem may include additional files; `TRAINER_SUBSYSTEM_LINECOUNT.txt` is referenced for the broader count. `HYBRID_TRAINER_COVERAGE_REPORT.md`: unclassified_chunks=0, unknown_signal_paths=0, unknown_reward_paths=0, unknown_confidence_paths=0, unknown_redis_writes=0. |

## New blockers identified in this rerun

None.

## New risks identified (non-blocking, carried into Phase 2)

| ID | Risk | Why non-blocking at Phase 1 | Required Phase 2 action |
|---|---|---|---|
| R-1 | 1,361 `exchange_unresolved_tier_a_review` items have not been raw-reviewed yet — they are queued | Phase 1 verifies coverage completeness (the gap is found, named, counted, and routed). Raw review is Phase 2's job. | Each entry's `verification_command` must be executed against `./legacy_reference/...`; resulting code range must be reclassified into a concrete exchange class (order_create, leverage_change, margin_change, stop_loss, take_profit, reduce_only, account_query, exchange_state_accounting, etc.) or explicitly cleared. |
| R-2 | Markdown copy of Tier A plan (`TIER_A_RAW_REVIEW_PLAN.md`, `CLAUDE_PHASE1_TIER_A_RAW_REVIEW_PLAN.md`) does not surface verification_command in the human-readable table | The canonical artifact is `TIER_A_RAW_REVIEW_PLAN.json` (verified 11700/11700). The .md is a navigational aid per CLAUDE.md "Evidence Integrity Rule" — summaries are not evidence. JSON is the source of truth. | Phase 2 reviewers must consume the JSON, not the .md table, when executing verification commands. Optionally, a future regeneration can include the verification_command column in the .md. |
| R-3 | The 11,700-entry Tier A plan is heavily weighted toward `.backups/fix_signals_*` paths (duplicated trainer/trader/paper_trader copies) | These are evidence-backed historical snapshots and must remain in scope to detect divergence between active and backup trainer files. They are not noise. | Phase 2 raw review can deduplicate by content hash if active and backup files are byte-identical, but only after explicitly proving identity. Do not silently skip. |
| R-4 | Top concentration of unresolved exchange items is in `rl/hybrid_trainer.py` (75) and `trading/trader.py` (63) | These are the primary trainer + primary live trader paths. High concentration is expected, not surprising. | Phase 2 P0 raw review must cover these files end-to-end before any V2 trader/trainer adapter is written. |
| R-5 | `tier_a_count` (script-level) = 701 but `tier_a_review_plan_entries` = 11,700 | The 701 is script-level; 11,700 is line-range-level inside scripts. They are not the same metric. | No action — confirm the metric distinction is documented. |
| R-6 | CLAUDE.md asserts ">250k lines" for trainer; reconciliation states 57,250 for primary file | CLAUDE.md prose is overridden by `TRAINER_SIZE_RECONCILIATION.md` per the explicit "Trainer Size Reconciliation Rule" in CLAUDE.md itself, which names that artifact as canonical. | None at Phase 1. Optional cleanup: refresh the CLAUDE.md prose with the canonical numbers when the rule is next edited. |
| R-7 | Phase 1 GO does not approve V2 build | This is a coverage-completeness gate, not a build gate. | Phase 2 (Tier A raw review) + Codex adversarial coverage review remain prerequisites for V2 build. Live trading remains BLOCKED by default. |

## Suppressed risks check

Suppressed-risk audit performed for the following classes:

- Hidden unknowns: `grep` of `unsafe_unknown` and `quarantine_unknown` across `claude_worklog/coverage/` confirms canonical-class normalization, no quarantine alias still in use as canonical output, and no count mismatches between `COVERAGE_SUMMARY.json` and `COVERAGE_SUMMARY.md`.
- Hidden unresolved exchange: 1,361 items are explicitly counted and explicitly named `exchange_unresolved_tier_a_review` (not a euphemism). They are not labeled "resolved", "ok", "low_risk", or similar.
- Hidden Tier A items: `exchange_unresolved_missing_tier_a_plan_count=0` and JSON count of 11,700 matches header. All entries carry verification commands.
- Hidden trainer size: reconciliation artifact present; broader-subsystem caveat preserved.
- Hidden V2 work: `v2/` enumerated to 5 files, all docs/config; no shadow code.
- Hidden legacy mutation: `git status` and `git log` against `legacy_reference/` show clean state, no edits.

No suppressed risks identified.

## Final blocker disposition

- B-1 → **resolved**
- B-2 → **resolved (routed)**
- B-3 → **resolved**
- B-4 → **resolved**
- New blockers → **none**
- New risks → **7 non-blocking, all carried into Phase 2 with explicit conditions**

Phase 1 verification can transition to GO.
