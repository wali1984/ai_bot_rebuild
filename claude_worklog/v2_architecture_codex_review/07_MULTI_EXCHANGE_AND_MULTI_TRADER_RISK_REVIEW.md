# 07 Multi-Exchange and Multi-Trader Risk Review

## Scope
Adversarial review of connector architecture, fleet model, and risk authority boundaries.

## What passes
- Binance Futures first + pluggable futures connectors are clearly stated.
- Connector interface includes required methods.
- Mutation methods are blocked until live readiness gates pass.
- Fleet schema includes required trader fields.
- Risk Gateway final authority and non-bypass intent are explicit.

## Adversarial findings
1. **Connector mutation safety is policy-only (HIGH)**
   - No explicit idempotency key and duplicate-submit prevention contract for `create_order`/`cancel_order`.

2. **Precision/lot-size normalization contract missing (MEDIUM)**
   - Architecture does not define standardized validation for exchange-specific quantity/price filters before order intent acceptance.

3. **Risk Gateway coupling contract needs hardening (HIGH blocker)**
   - Non-bypass is declared, but architecture does not define required technical enforcement point (e.g., only `execution_intent` created from `risk_decision_id` via constrained service path).

4. **Fleet assignment conflict policy under-specified (MEDIUM)**
   - Overlap/sharding intent exists, but tie-break and contention-resolution semantics are not formalized.

## Verdict
Design intent is correct; enforceability details are still insufficient for safe scaffolding.
