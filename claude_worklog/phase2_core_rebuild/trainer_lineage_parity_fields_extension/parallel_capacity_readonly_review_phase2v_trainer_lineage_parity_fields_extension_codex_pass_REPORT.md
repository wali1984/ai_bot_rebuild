# Codex Parallel Read-Only Review

Status: BLOCKED

Blocking findings:

1. The committed proof source builds the five trainer parity fields correctly in memory, but the committed runtime proof artifacts and frontend public proof mirror are stale. Every checked projection is missing the five fields:
- replay/backtest scenarios: 25 missing values
- paper ledger events: 35 missing values
- risk-gateway decisions: 25 missing values
- decision explainability rows: 25 missing values
- shadow comparison rows: 25 missing values

This blocks paper/backtest MVP compatibility because the artifacts a dashboard or downstream proof consumer reads do not match the source-level parity contract.

2. The trainer readiness gate can report READY while reading stale proof evidence. Its fallback rebuilds decision explanations in memory when the persisted proof artifact lacks the parity fields, then writes READY trainer readiness artifacts. That masks the stale persisted proof instead of forcing the non-live proof artifacts and public proof mirror to be regenerated first.

3. Risk-gateway handoff is incomplete in committed evidence. Source-generated risk decisions carry risk decision and execution intent lineage plus the five trainer fields, but the persisted risk-gateway proof rows do not. Any downstream handoff that consumes the committed evidence loses model/checkpoint identity, raw/calibrated confidence, and trainer worker liveness.

4. The operator cockpit evidence remains stale. The direct trainer readiness mirror is READY, but the operator cockpit payload still embeds the old BLOCKED trainer marker and old gaps. The active dashboard reads that cockpit payload, so the UI evidence path can disagree with the direct trainer readiness evidence.

5. The frontend e2e expectation still asserts the old BLOCKED trainer marker. That is a test-hardening gap and also confirms the stale cockpit contract has not been updated for the Phase 2V marker flip.

Non-blocking observations:

- The deterministic proof builder currently emits the five parity fields across replay/backtest, paper ledger, risk-gateway, decision explainability, and shadow comparison rows when called directly.
- The venv proof unit suite passed: 18 passed.
- The live gate remains blocked_human_only and live_ready remains false in the trainer readiness evidence.
- No source files were patched, dirty work was not modified, Redis was not touched, live services were not restarted, and no live/exchange action was taken.

Recommended hardening before pass:

- Regenerate and commit the non-live proof runtime artifacts and frontend public proof mirror after the Phase 2V source change.
- Regenerate and commit the operator cockpit payload so the dashboard consumes the READY trainer marker and empty trainer gaps.
- Update the frontend e2e expectation to assert READY while still asserting live trading remains blocked and no dangerous controls exist.
- Add a test that reads committed or fixture-equivalent persisted proof artifacts and verifies all five parity fields exist across all five projections.
- Add a test that prevents the trainer readiness builder from silently flipping READY from an in-memory fallback while persisted proof artifacts remain stale.
- Strengthen trainer gate coverage for baseline lineage fields from any-row coverage to all-row coverage where the field is required per explanation row.

CODEX_PARALLEL_READONLY_REVIEW_BLOCKED
