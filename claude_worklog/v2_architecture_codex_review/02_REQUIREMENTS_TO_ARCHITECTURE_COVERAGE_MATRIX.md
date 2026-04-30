# 02 Requirements to Architecture Coverage Matrix

Legend:
- **Covered** = mapped and mostly implementable
- **Partial** = mapped but under-specified for scaffold
- **Gap** = missing required enforceable detail

| Req | Requirement | Architecture mapping | Coverage | Adversarial note |
|---|---|---|---|---|
| 01 | Observability + attribution | 02, 03, 11, 14 | Covered | Strong lineage/object model present. |
| 02 | Feature snapshot schema | 03, 11 | Partial | Snapshot fields present, but deterministic ID composition contract is not locked in architecture artifacts. |
| 03 | Prediction-signal-decision chain | 02, 03, 11 | Covered | Parent-child linkage and table-level chain present. |
| 04 | Confidence explainability | 03, 11 | Partial | Payload intent is present; cardinality rules (min top+/- entries + placeholders) not explicitly encoded in architecture contracts. |
| 05 | Redis memory retention policy | 04, 14 | Covered | Thresholds and bounded retention posture are clear. |
| 06 | Heartbeat schema policy | 03, 14 | Partial | Heartbeat events exist; canonical key-type enforcement contract at namespace level is not fully specified. |
| 07 | Monitoring revalidation | 14, 17 | Covered | Evidence packet + monitoring domains represented. |
| 08 | Pre-V2 build exit criteria | 17 | Partial | Sequence is defined; machine-verifiable gate checklist contract is not fully enumerated in architecture files. |
| 09 | Trainer internal worker supervision | 14 | Covered | Corrected liveness domain is represented and tied to packets. |
| 10 | Enterprise website product scope | 01, 06, 17 | Covered | Full control-plane intent and role separation represented. |
| 11 | Dynamic symbol universe | 02, 03, 06, 07, 08 | Partial | Coverage exists; force-state semantics and validation rules need explicit contract detail for implementation. |
| 12 | Multi-exchange connector | 03, 09, 12 | Partial | Connector interface exists; order idempotency/error-class contract is missing. |
| 13 | Multi-trader fleet | 03, 10, 12 | Partial | Fleet schema exists; assignment conflict resolution and risk-checked dispatch protocol are not fully specified. |
| 14 | Hot-reload pipeline | 08 | Partial | State machine and ack envelope are present; timeout/retry/quorum rollback semantics are missing. |
| 15 | Public hosting + security | 05, 15 | Partial | Security checklist present; auth/session/RBAC enforcement contracts are not scaffold-grade. |
| 16 | Enterprise GUI page map | 06 | Covered | Required page inventory and safety-gate framing are present. |
| 17 | 100x–1000x goal alignment | 01, 12, 17 | Covered | Growth-with-safety posture is explicit. |
| 18 | Updated pre-build criteria | 17, 18 | Partial | Marker flow exists; per-gate pass/fail evidence schema not fully normalized. |
| 19 | Passive discovery + adaptive selection | 07, 08, 03, 06 | Partial | Good model; score computation/versioning and tie-break policies require formal contract. |
| 20 | AI supervision governance | 13, 06, 03 | Partial | L5 non-autonomous is explicit; L4 mandatory approval policy needs stricter architecture-level enforcement expression. |
| 21 | Updated architecture readiness | 00, 18 | Partial | Readiness marker exists, but adversarial gate reveals unresolved critical scaffold blockers. |

## Summary
- Covered: 8
- Partial: 13
- Gap: 0 (conceptually mapped)

Adversarial conclusion: conceptual mapping is broad, but implementability and enforceability gaps keep readiness at FAIL.
