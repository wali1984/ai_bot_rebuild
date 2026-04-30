# 05 API Contracts

## API groups
1. Auth/session
2. Market universe
3. Passive discovery
4. Symbol scoring
5. Symbol override/admin approval
6. Exchanges/connectors
7. Ingestors
8. Feature snapshots
9. Predictions
10. Signals
11. Orchestrator decisions
12. Risk decisions
13. Execution intents
14. Trader fleet
15. Monitor/evidence packets
16. Audit ledger
17. Config admin
18. AI governance
19. Replay/paper trading
20. Live readiness

## Contract conventions
- Versioned REST/JSON APIs with explicit schema version field.
- Mutation endpoints require auth + RBAC + audit envelope.
- Risk-level tagged operations require approval workflow.
- All lineage-bearing endpoints include relevant IDs.

## Required payload properties (selected)
- `request_id`, `actor`, `timestamp_ms`, `schema_version`
- For governed mutations: `change_id`, `risk_level`, `reason`, `evidence_pointers`, `approval_state`
- For model flow: lineage chain IDs where applicable

## Safety behavior
- Live mutation routes return blocked status by default until readiness gates pass.
- No unauthenticated trading-control endpoints.
