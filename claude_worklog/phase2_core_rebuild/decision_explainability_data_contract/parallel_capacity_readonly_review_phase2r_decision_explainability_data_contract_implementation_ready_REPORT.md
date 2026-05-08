# Parallel Capacity Read-Only Review - Phase 2R Decision Explainability Data Contract

Decision: BLOCKED.

Scope was reviewed read-only against the committed implementation-ready marker. No source patch was made, no dirty work was intentionally changed, no Redis or live service action was taken, and no live trading action was taken.

## Blocking Findings

1. The committed Phase 2R test package is not collectable in the dependency-complete test environment. Collection fails before any test runs because the package initializer contains a leaked materialization marker line that evaluates an undefined `v2` name at import time. This directly contradicts the implementation report claim that the validation command passes with 16 tests.

2. The same leaked materialization marker pattern remains in the authored fixture, harness, and test modules as trailing annotated-expression lines. Even where these compile, they violate the Phase 2R forbidden standalone marker rule and would be caught by the authored forbidden-token scan if collection reached the tests.

3. Validation evidence is stale. The reported expected result of 16 passing tests is not current for the committed tree. The system Python also lacks pytest, so the only meaningful local pytest check was the dependency-complete environment, and that produced a collection error.

## Compatibility Review

Paper and backtest MVP compatibility is conceptually aligned but not ready. The intended design is non-live, deterministic, test-only, in-memory, and does not invoke ledger recording, replay execution, exchange clients, Redis, schedulers, or background services. However, the leaked marker issue blocks the test package and therefore blocks using the milestone as reliable MVP evidence.

Risk-gateway handoff is partially complete. The fixture rows use the existing risk decision typed surface and mirror the four expected lineage identifiers plus action, reason, timestamp, symbol, and live-blocked state into an explainability envelope. The gap is that the harness constructs risk records directly rather than exercising the risk gateway evaluator handoff path, so it proves mirror-shape compatibility more than end-to-end handoff compatibility.

Lineage and explainability coverage is intentionally narrow. The envelope covers feature snapshot, prediction, decision, risk decision, risk action, input decision, timestamp, symbol, paper-mode state, scenario slug, step index, and legacy evidence pointer. It does not include paper trade lineage, execution intent lineage, feature contributors, freshness flags, confidence deltas, model or checkpoint version, risk checklist, blocked-trade reason, or audit timeline. That is acceptable only if downstream Lane B milestones explicitly add those surfaces before UI readiness.

## Test-Hardening Recommendations

Remove all leaked materialization marker lines from the committed Python package, then rerun the exact Phase 2R pytest command in a dependency-complete environment.

Add a lightweight collection/import smoke check for the package initializer, fixture module, harness module, and test module so marker leakage fails before behavioral assertions.

Add a direct source scan for standalone materialization markers across all authored Phase 2R files, including the package initializer, not only imported modules that are reachable after collection.

Add a handoff-oriented test that constructs at least one row through the risk gateway evaluator service or composition root, while keeping the existing direct-constructor fixtures for deterministic mirror checks.

Add an explicit downstream readiness note that Phase 2R is a mirror contract only, not a complete explainability UI contract, until paper trade, replay, confidence, freshness, risk-check, and audit-timeline lineage are wired.
