# 04 API Contract Review

## Scope
Adversarial check of API scaffold readiness across required API groups.

## Required API groups coverage
All required groups are named in architecture:
- auth/session
- market universe
- passive discovery
- symbol scoring
- symbol override/admin approval
- exchange connectors
- ingestors
- feature snapshots
- predictions
- signals
- orchestrator decisions
- risk decisions
- execution intents
- trader fleet
- monitor/evidence packets
- audit ledger
- config admin
- AI governance
- replay/paper trading
- live readiness

## Adversarial verdict
**FAIL (Critical blocker)**

## Why this fails
The contract is group-level only. For scaffold planning, missing details are material:
1. **No endpoint inventory** (path + method per group).
2. **No request/response schemas** per endpoint, including required lineage fields.
3. **No error model** by status code/class (`validation`, `auth`, `approval`, `risk_gate_block`, `dependency_timeout`, etc.).
4. **No idempotency model** for mutable routes (required for safe retries).
5. **No concurrency contract** (version preconditions / optimistic locking for config/universe updates).
6. **No pagination/filtering/sorting contract** for high-volume event feeds.
7. **No route-level RBAC scope matrix** (operator/admin/security-admin by endpoint).
8. **No deterministic live-block response envelope** for blocked mutation calls.

## Required remediation (minimum)
- Produce endpoint matrix for all 20 API groups.
- Define JSON schema for every mutable and lineage-bearing payload.
- Define standard error envelope and error-code catalog.
- Define idempotency headers/keys and replay behavior.
- Define RBAC scope map + approval requirements per route.
- Define canonical blocked-by-default live mutation responses.

## Gate decision
Until remediated, architecture is **not scaffold-ready**.
