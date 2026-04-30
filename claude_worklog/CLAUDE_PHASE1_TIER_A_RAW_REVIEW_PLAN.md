# Claude Phase 1 Tier A Raw Review Plan (Verification View)

Date: 2026-04-30
Source of truth: `claude_worklog/coverage/TIER_A_RAW_REVIEW_PLAN.json` (canonical, machine-readable)
Companion table: `claude_worklog/coverage/TIER_A_RAW_REVIEW_PLAN.md` (full 11,700-row table without verification_command column)
This file: Phase 1 verifier's structural confirmation, priority/category breakdown, and representative samples with verification commands.

## Structural verification (canonical JSON)

| Field | Coverage |
|---|---|
| `review_id` | 11,700 / 11,700 |
| `file` | 11,700 / 11,700 |
| `start_line` | 11,700 / 11,700 |
| `end_line` | 11,700 / 11,700 |
| `reason` | 11,700 / 11,700 |
| `category` | 11,700 / 11,700 |
| `priority` | 11,700 / 11,700 |
| `evidence_source_artifact` | 11,700 / 11,700 |
| `verification_command` | 11,700 / 11,700 |
| `expected_review_question` | 11,700 / 11,700 |

Every entry has file/start/end/verification command. Confirmed via raw count of field occurrences in JSON.

## Priority breakdown

- P0: 5,186 (44.3%)
- P1: 1,265 (10.8%)
- P2: 5,249 (44.9%)
- Total: 11,700

P0 is reserved for: redis writes from production paths, leverage_margin changes, stops/take_profit/reduce_only operations, order_create paths, and exchange_unresolved items in primary live trader/trainer files.

## Category coverage (verified categories observed in JSON)

- `redis_write` (P0 dominant — production-path Redis writers)
- `leverage_margin` (P0 — leverage_change clusters)
- `stops_take_profit` (P0 — stop_loss / take_profit / reduce_only clusters)
- `exchange_execution` (P0 — order_create clusters)
- `exchange_unresolved_tier_a_review` (1,361 entries — unresolved production exchange logic queued for raw review)
- (additional P1/P2 categories exist for trainer reward paths, confidence paths, signal paths, feature freshness, runtime entrypoints — see canonical JSON)

The 1,361 `exchange_unresolved_tier_a_review` entries account for 11.6% of the plan and represent the deterministic conversion of the prior `unknown_exchange_use=3,996` into a named, queued, evidence-backed class.

## Verification command schema

Two helper tools are referenced. Both exist on disk:

- `tools/show_file_range.py`  — usage: `python3 tools/show_file_range.py --file ./legacy_reference/<path> --start <N> --end <M>`
- `tools/show_trainer_section.py` — usage: `python3 tools/show_trainer_section.py --trainer-file ./legacy_reference/rl/hybrid_trainer.py --start <N> --end <M>`

Both tools must be invoked against `./legacy_reference/...` paths only (read-only per CLAUDE.md Read/Write Boundaries).

## Representative samples (with verification commands from canonical JSON)

### P0 — redis_write cluster, primary trainer

```
review_id: tier_a_00001
file: .backups/fix_signals_20251012_191010/hybrid_trainer.py
range: 661-666
category: redis_write
priority: P0
verification_command: python3 tools/show_file_range.py --file ./legacy_reference/.backups/fix_signals_20251012_191010/hybrid_trainer.py --start 661 --end 666
expected_review_question: Does this range write trading/position/execution state to Redis?
evidence_source_artifact: claude_worklog/coverage/REDIS_USAGE_MAP.json
```

### P0 — leverage_margin cluster, primary trainer

```
review_id: tier_a_00008
file: .backups/fix_signals_20251012_191010/hybrid_trainer.py
range: 2177-2183
category: leverage_margin
priority: P0
verification_command: python3 tools/show_file_range.py --file ./legacy_reference/.backups/fix_signals_20251012_191010/hybrid_trainer.py --start 2177 --end 2183
```

### P0 — exchange_execution (order_create) cluster, primary trader

```
review_id: tier_a_00037
file: .backups/fix_signals_20251012_191010/trader.py
range: 712-720
category: exchange_execution
priority: P0
verification_command: python3 tools/show_file_range.py --file ./legacy_reference/.backups/fix_signals_20251012_191010/trader.py --start 712 --end 720
```

### P0 — stops_take_profit (stop_loss) cluster, primary trader

```
review_id: tier_a_00038
file: .backups/fix_signals_20251012_191010/trader.py
range: 733-739
category: stops_take_profit
priority: P0
verification_command: python3 tools/show_file_range.py --file ./legacy_reference/.backups/fix_signals_20251012_191010/trader.py --start 733 --end 739
```

### P0 — exchange_unresolved_tier_a_review, active trainer

```
review_id: tier_a_00654
file: rl/hybrid_trainer.py
range: 1360-1370
category: exchange_unresolved_tier_a_review
priority: P0
verification_command: python3 tools/show_trainer_section.py --trainer-file ./legacy_reference/rl/hybrid_trainer.py --start 1360 --end 1370
expected_review_question: Determine whether this unresolved exchange-related production logic can mutate orders, leverage, margin, stops, positions, balances, or execution accounting.
evidence_source_artifact: claude_worklog/coverage/EXCHANGE_ACTION_MAP.json
```

### P0 — exchange_unresolved_tier_a_review, active trainer (second sample)

```
review_id: tier_a_00882
file: rl/hybrid_trainer.py
range: 4631-4641
category: exchange_unresolved_tier_a_review
priority: P0
verification_command: python3 tools/show_trainer_section.py --trainer-file ./legacy_reference/rl/hybrid_trainer.py --start 4631 --end 4641
```

### P0 — exchange_unresolved_tier_a_review, active trainer (third sample)

```
review_id: tier_a_01091
file: rl/hybrid_trainer.py
range: 7209-7219
category: exchange_unresolved_tier_a_review
priority: P0
verification_command: python3 tools/show_trainer_section.py --trainer-file ./legacy_reference/rl/hybrid_trainer.py --start 7209 --end 7219
```

## Top file concentrations (unresolved exchange queue)

From `claude_worklog/coverage/EXCHANGE_UNKNOWN_RESOLUTION.md`:

- `rl/hybrid_trainer.py`: 75 unresolved
- `trading/trader.py`: 63 unresolved
- `ingest/realtime_price_provider.py`: 63 unresolved
- `ingest/ccxt_historical.py`: 55 unresolved
- `ingest/live_binance.py`: 47 unresolved
- `ingest/cdd_historical.py`: 33 unresolved
- `ingest/live_coinank.py`: 30 unresolved
- `trading/base_executor.py`: 28 unresolved
- `ingest/live_ccxt.py`: 25 unresolved
- `trading/stealth_stops.py`: 24 unresolved
- (full list in `EXCHANGE_UNKNOWN_RESOLUTION.md`)

These files are the priority targets for Phase 2 P0 raw review.

## Execution policy for Phase 2

1. Process P0 entries before P1, P1 before P2.
2. For each entry: run the `verification_command` to print the line range, classify into a concrete exchange class per `EXCHANGE_UNKNOWN_RESOLUTION_POLICY.md`, and record the result in the audit ledger.
3. Active-path files (`rl/hybrid_trainer.py`, `trading/trader.py`, `trading/base_executor.py`, `trading/stealth_stops.py`, `trading/execution_engine.py`, `trading/maker_execution.py`, `trading/dynamic_*`, `trading/adaptive_edge_gate.py`) are blocking for the V2 trader/trainer adapter.
4. `.backups/fix_signals_*` paths must be reviewed but may be deduplicated against active paths after byte-identity is proven.
5. No raw review may invoke any command that writes Redis, places orders, changes leverage, changes margin mode, or mutates the live bot. Reviewers may only call `tools/show_file_range.py` and `tools/show_trainer_section.py` against `./legacy_reference/...`.
6. Codex adversarial coverage review must follow Tier A raw review and must precede V2 build.

## Canonical references

- Plan source: `claude_worklog/coverage/TIER_A_RAW_REVIEW_PLAN.json`
- Plan flat table: `claude_worklog/coverage/TIER_A_RAW_REVIEW_PLAN.md`
- Coverage summary: `claude_worklog/coverage/COVERAGE_SUMMARY.{md,json}`
- Exchange resolution: `claude_worklog/coverage/EXCHANGE_UNKNOWN_RESOLUTION.md`
- Resolution policy: `claude_worklog/coverage/EXCHANGE_UNKNOWN_RESOLUTION_POLICY.md`
- Exchange map: `claude_worklog/coverage/EXCHANGE_ACTION_MAP.{md,json}`
- Redis usage: `claude_worklog/coverage/REDIS_USAGE_MAP.json`
- Trainer reconciliation: `claude_worklog/trainer_atlas/TRAINER_SIZE_RECONCILIATION.md`
- Trainer hybrid coverage: `claude_worklog/trainer_atlas/HYBRID_TRAINER_COVERAGE_REPORT.md`
- Phase 1 fix report: `claude_worklog/phase1_fixes/PHASE1_BLOCKER_FIX_REPORT.md`

This Tier A plan is verified at Phase 1 GO. It governs Phase 2 raw review.
