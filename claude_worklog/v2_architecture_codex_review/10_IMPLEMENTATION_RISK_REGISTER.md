# 10 Implementation Risk Register

| risk_id | description | severity | affected architecture file | affected requirement | mitigation | blocker |
|---|---|---|---|---|---|---|
| R-001 | API groups are defined but endpoint-level contracts are absent; cannot scaffold safely. | critical | 05_API_CONTRACTS.md | 10, 16, 18, 21 | Publish full endpoint catalog with request/response/error schemas and RBAC scope matrix. | yes |
| R-002 | Risk Gateway control list exists but lacks deterministic policy-evaluation contract and precedence rules. | critical | 12_RISK_GATEWAY_ARCHITECTURE.md | 17, 18 | Define policy schema, evaluation order, stale-age defaults, duplicate guard contract, and test vectors. | yes |
| R-003 | Hot-reload ack/retry/quorum/rollback trigger semantics under-specified; restart-free guarantee not operationally enforceable. | high | 08_HOT_RELOAD_PIPELINE_ARCHITECTURE.md | 11, 14, 19 | Define ack timeout matrix, retry limits, partial-failure handling, and rollback trigger thresholds. | yes |
| R-004 | L4 AI changes not explicitly locked to mandatory human approval at architecture contract layer. | high | 13_AUDIT_LEDGER_AND_AI_CHANGE_GOVERNANCE.md | 20 | Add explicit L4 non-autonomous execution-impacting approval rule and approval-state transitions. | yes |
| R-005 | Public-hosting security controls are checklist-level; auth/session and RBAC enforcement details not scaffold-ready. | high | 15_PUBLIC_HOSTING_SECURITY_AND_RBAC_ARCHITECTURE.md | 15, 21 | Define token/session lifecycle, route-level RBAC mapping, and step-up auth for dangerous actions. | yes |
| R-006 | Universe override precedence rules are not deterministic across force-state combinations. | medium | 07_PASSIVE_MARKET_DISCOVERY_AND_ADAPTIVE_SELECTION_ARCHITECTURE.md | 11, 19 | Define explicit precedence table and conflict resolver in policy schema. | no |
| R-007 | Connector interface lacks explicit idempotency and duplicate-order contract for mutation calls. | medium | 09_MULTI_EXCHANGE_CONNECTOR_ARCHITECTURE.md | 12 | Add idempotency key contract and duplicate-action response semantics. | no |
| R-008 | Fleet assignment conflict resolution not formalized for overlapping scopes and failover. | medium | 10_MULTI_TRADER_FLEET_ARCHITECTURE.md | 13 | Define deterministic assignment arbitration and reassignment policy contract. | no |
| R-009 | Explainability minimum contributor-cardinality enforcement not formalized in architecture validation contracts. | medium | 11_FEATURE_ATTRIBUTION_AND_SIGNAL_EXPLAINABILITY_ARCHITECTURE.md | 04 | Add validation rule contract for top +/- contributor minimums and placeholders. | no |
| R-010 | Exit criteria marker exists but per-gate evidence schema and machine-check contract are incomplete. | low | 17_IMPLEMENTATION_SEQUENCE_AND_MILESTONES.md | 08, 18 | Define readiness gate schema with objective pass/fail evidence fields. | no |

## Severity counts
- critical: 2
- high: 3
- medium: 4
- low: 1

## Blocker count
- blocker=yes: 5
