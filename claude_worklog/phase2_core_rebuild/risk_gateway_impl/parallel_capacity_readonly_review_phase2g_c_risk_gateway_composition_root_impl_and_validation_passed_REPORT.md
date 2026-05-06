# Codex Parallel Read-Only Review: Phase 2G.C Risk Gateway Composition Root

Verdict: READY. No source-level blocker found for the committed Phase 2G.C composition-root milestone.

## Review scope

Read-only review of the committed milestone marker `PHASE2G_C_RISK_GATEWAY_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`.

No source patching, no Redis write, no live service restart, no order placement/cancelation, no live-trading enablement, and no legacy-bot workspace access were performed.

The pre-existing dirty worktree entries remained limited to the already-dirty planner prompt and the untracked supervisor task visible at review start.

## Paper/backtest MVP compatibility

PASS. The composition root is a pure binder around the existing risk-gateway assembler service. It does not add paper execution, exchange execution, adapters, FastAPI, background tasks, wall-clock calls, Redis access, strategy logic, or live-trading controls.

The evaluator keeps the MVP live-safety posture intact: the downstream risk record is still emitted through the service/domain path that requires `live_blocked is True`.

This is compatible with the paper/backtest MVP as a handoff boundary, not as a paper ledger implementation. The next paper-ledger milestone still needs to persist and consume the risk decision explicitly before any simulated execution decision.

## Risk-gateway handoff completeness

PASS. The public composition surface exposes the expected evaluator builder and error class. The builder validates only callable clock injection at build time, captures the clock, returns a keyword-only evaluator, and delegates each call to the assembler service with the original decision object.

The assembler remains the single place that maps orchestrator action to risk action/reason and constructs the risk decision. Service and domain errors propagate without wrapping, which keeps caller handling specific and predictable.

## Lineage and explainability

PASS with follow-up recommendation. The produced risk decision preserves the required joinable lineage: derived risk decision id, orchestrator decision id, prediction id, feature snapshot id, symbol, risk timestamp, risk action/reason, and input decision action/reason.

No extra composition-layer lineage id is introduced, which matches scope. The practical explainability dependency is that paper/backtest consumers must join risk decisions back to the orchestrator decision when they need confidence, freshness, worker-health, or decision timestamp context. Add paper-ledger integration tests that assert this join remains available.

## Stale evidence check

No stale implementation evidence was found for the narrow 2G.C claims. Current read-only validation confirmed:

- 2G.C composition suite: 24 passed.
- Risk-gateway service plus domain suites: 61 passed.
- Forbidden reserved risk-reason token scan over the 2G.C composition source and tests: zero matches.
- No tracked dirty change appeared in the reviewed 2G.C source, tests, or milestone report/marker after validation.

## Test-hardening recommendation

One non-blocking test-hardening gap was observed outside the 2G.C source: an older trainer-worker-health import-clean test is order-dependent when run in the same process after the new 2G.C URL-env import-clean test module has been loaded. The older suite passes alone, while an aggregate predecessor sweep failed because the older assertion scans all loaded module names and sees another test module name containing the reconstructed marker.

Recommendation: convert that older import-clean assertion to the subprocess isolation pattern used by 2G.C, or restrict its scan to runtime application modules rather than all loaded pytest modules. This is not a 2G.C source handoff defect, but it should be hardened before broad aggregate CI gates rely on mixed-suite execution.

## Go/no-go

CODEX_PARALLEL_READONLY_REVIEW_READY
