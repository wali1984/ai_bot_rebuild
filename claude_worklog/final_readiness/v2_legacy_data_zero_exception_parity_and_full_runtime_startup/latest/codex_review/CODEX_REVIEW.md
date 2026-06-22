# Codex Review: V2 Legacy-Data Zero-Exception Parity and Full Runtime Startup

GO/NO-GO: `V2_LEGACY_DATA_ZERO_EXCEPTION_PARITY_CODEX_FAIL`

## Required safety checks

- `LIVE_GATE=blocked_human_only` and `live_symbols=[]` are present in the startup report, operator dashboard payload, and per-phase status files.
- Old-Redis writes are not active in V2 runtime now (`active_v2_processes_writing_old_redis=false`), though static legacy keys remain in Redis.
- No live/canary/shutdown/trim approvals are reported.
- No exchange mutation is reported in V2 status payloads (`exchange_actions_by_codex=false`, `manual_redis_mutation_by_codex=false`, `destructive_redis_mutation_by_codex=false`).
- Liquidation WSS parsing and bridge services assert **no event synthesis** and only write to `v2:*` keys.

## Fail findings

1. `legacy_to_v2_zero_exception_data_matrix.json` has 36 rows but is not fully ready:
   - `V2_MISSING_IMPLEMENTATION`: 6
   - `V2_CREDENTIAL_BLOCKED`: 3
   - `V2_OPERATOR_REQUIRED`: 5
   - `V2_ADAPTER_REQUIRED`: 4
   - `V2_RUNNING_PARTIAL`: 7
2. Feature/TA parity is incomplete:
   - `v2_active_feature_field_count_per_symbol_tf=23` vs `v2_unified_feature_count_per_symbol_tf=562`
   - Hardcoded TA fields are still being emitted.
3. Trainer parity remains blocked:
   - `v2_native_trainer_ready=false`
   - Trainer role is `COPIED_LEGACY_TRAINER_NOT_RUNNING_IN_V2`
   - Current feed coverage is partial and includes `v2:liquidations:events_XLEN=0`.
4. Paper decision and edge logic are not green:
   - Current paper PnL is negative (`-49.345535`) with zero fills.
   - `edge_claimed=false` with threshold failures/inconclusive status.
   - War-room only has 12 validation rows against 9 strategy axes (8 missing).
5. Trading platform readiness is partial:
   - 5 required pages missing, 5 partial pages.
   - Report-center pages are not complete.
6. `1000BONK` dominates the current paper-window symbol distribution; concentration handling is not demonstrated as addressed.

## Verification against requested audit coverage

- Legacy inventory and matrix are present for the expected scope (`audit_canonical_counts` and row coverage present in `legacy_to_v2_zero_exception_data_matrix.json`).
- `matrix_rows` rows all include an explicit `status` and non-empty blocker/target contract metadata where applicable.
- Redis namespace observer is present and explicit about stale static keys plus zero active old-write processes.
- Website/front-end control checks remain in-progress (multiple missing pages) and do not yet satisfy full trading-platform completeness.

No safe V2-side code edits were applied because the remaining blockers are architectural/completion gaps (missing ingestors, missing features, trainer readiness, and evidence insufficiency), not defects with a narrow safe fix in this turn.
