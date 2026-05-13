# V2 Production Truth Reconciliation and Migration Execution Gate Report

Generated: 2026-05-13T04:43:38.228869Z

Final status: `V2_PRODUCTION_TRUTH_RECONCILIATION_AND_MIGRATION_EXECUTION_GATE_BLOCKED`
Codex result: `V2_PRODUCTION_TRUTH_RECONCILIATION_CODEX_FAIL`
Live gate: `blocked_human_only`

## Actual Live Readiness Status

Full live is **not ready**. The final approval packet exists, but it is not approval and the approval token file is absent.

## Migration Status

- Migrated-to-V2 rows: `1592`
- Backlog/not-migrated rows: `2603`
- Unsafe unknown rows: `2093`
- Exchange-action references: `344`
- Redis-writer references: `445`

## Paper / Shadow Result Status

Paper runtime is `PAPER_RUNTIME_ONLINE_ACTIVE` with latest prediction `pred_paper_tick_1778647390310`, signal `sig_paper_tick_1778647390310`, risk decision `risk_paper_tick_1778647390310`, and execution intent `pei_paper_tick_1778647390310`.

This is current non-live runtime evidence, not full strategy proof. Full 6h/24h durable paper-shadow performance is still required.

## Website Current Data Status

Website data truth is `WEBSITE_DATA_TRUTH_INCOMPLETE`. Route crawl checked `20` local/public route loads and found `12` blocked data-truth routes. Static fixture visibility was found on: local /admin/signals?role=admin, local /admin/executions?role=admin, public /admin/signals?role=admin, public /admin/executions?role=admin.

## Claude / Codex Improvements

Meaningful improvements are recorded in `CLAUDE_CODEX_IMPROVEMENT_LEDGER.md`. They include CoinAnk remediation, always-on runtime guardrails, non-drift lock, canonical paper runtime truth bridge, active dispatch proof, risk gateway expansion, script migration backlog, hosting telemetry support, and final approval packet. These are mixed runtime/control-plane/documentation/backlog improvements, not proof of full live readiness.

## Legacy vs V2

V2 blocks or exposes several legacy failure modes, but several remain only visible or test-covered rather than fully fixed in migrated live runtime. See `LEGACY_VS_V2_COMPARISON.md`.

## Final Canary Status

Tiny canary packet exists but remains human-gated. Missing evidence remains in the final canary checklist. No approval token was created.

## Next 6h Sprint

See `NEXT_6H_RECOVERY_SPRINT_PLAN.md`. Highest priority: repair website current signal/prediction/execution display, then convert P0/P1 script backlog into real V2 wrappers/ports.
