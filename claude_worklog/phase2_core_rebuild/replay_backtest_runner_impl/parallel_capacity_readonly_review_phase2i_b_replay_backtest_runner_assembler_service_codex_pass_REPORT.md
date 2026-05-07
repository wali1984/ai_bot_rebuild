# Parallel Capacity Read-Only Review - Phase 2I.B Replay/Backtest Runner Assembler Service

## Scope
Reviewed the committed Phase 2I.B assembler-service milestone after the Codex pass marker. This was read-only: no source patches, no Redis writes, no live service restarts, no order placement, and no live-trading enablement.

## Verdict
READY. I found no blocker against paper/backtest MVP compatibility for this milestone's declared scope.

## Paper/Backtest MVP Compatibility
PASS. The assembler remains a pure derivation layer. It constructs replay/backtest step and summary value objects only, keeps `live_blocked` hard-coded true, performs no execution, performs no persistence, computes no PnL or sizing fields, and does not introduce scheduler or runner behavior. This matches the MVP split where actual composition/runtime orchestration remains deferred.

## Risk-Gateway Handoff Completeness
PASS for the current milestone boundary. The accepted input is the validated paper-ledger entry, and the replay step preserves the existing handoff identifiers: paper trade, risk decision, orchestrator decision, prediction, feature snapshot, and symbol. That keeps the risk-gateway decision trace reachable through the paper-ledger layer without importing risk-gateway domain objects into this service.

Non-blocking note: the replay step stores paper mirror action/reason rather than duplicating raw risk action/reason. That is consistent with the 2I.B spec, but downstream explainability views must join through the paper-ledger or risk-decision record when they need the original risk reason.

## Lineage And Explainability
PASS with one non-blocking follow-up. The core lineage chain needed for explainability is preserved by ID propagation, and summary aggregation avoids inventing new lineage. The service does not drop the risk decision ID, decision ID, prediction ID, or feature snapshot ID.

Recommended hardening: add an integration-level test in the next composition milestone that assembles a risk decision, paper-ledger entry, replay step, and summary in one flow, then asserts the full lineage chain remains intact and queryable through each handoff.

## Stale Evidence Check
Fresh read-only verification was run with bytecode and pytest cache disabled. Results:
- Service unit suite: 40 passed.
- Cross-isolation suites covering replay domain, paper ledger, risk gateway, orchestrator decision, and trainer prediction domain: 271 passed.
- Source forbidden-token scan: no service-source hits for Redis, HTTP client, FastAPI/server, env access, wall-clock helpers, logging/stdout, persistence, live-disabled false construction, or risk/orchestrator record tokens.
- Protected placeholder/prior-domain diff check: no committed diff observed for the protected prior milestone areas included in the check.

The committed implementation and Codex reports were therefore not relying only on stale historical evidence.

## Test-Hardening Recommendations
1. Add explicit validation-order tests proving the clock is not called when earlier step inputs fail.
2. Add summary validation-order tests proving the clock is not called when step type or replay-run ID checks fail.
3. Add composition-level lineage tests across risk decision to paper ledger to replay step to summary.
4. Add a source-surface test asserting the assembler service imports only the approved modules, not just that forbidden tokens are absent.
5. Add a mutation-resistance test that a tampered paper-ledger entry with mismatched action/reason fails through domain construction or assembler fallback as expected.

## Blocking Findings
None.

CODEX_PARALLEL_READONLY_REVIEW_REPORT_READY
