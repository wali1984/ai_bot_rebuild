# Actual Codex Architecture Rerun After Remediation

## Files reviewed
- `claude_worklog/v2_architecture/*.md`
- `claude_worklog/v2_requirements/*.md`
- `claude_worklog/v2_architecture_review/*.md`
- `claude_worklog/v2_architecture_codex_review/*.md`
- `claude_worklog/v2_architecture_remediation/*.md`

## Previous blockers
1. API endpoint contracts.
2. Risk Gateway enforceability.
3. Hot-reload failure semantics.
4. L4 human approval governance.
5. Security/auth/session/RBAC contracts.

## Resolution assessment
1. API endpoint contracts: **Resolved at architecture tier.** `05_API_CONTRACTS.md` and `04_API_CONTRACT_REMEDIATION.md` now define envelopes, errors, idempotency, concurrency, pagination, RBAC/approval levels, live-block behavior, schema deltas, and endpoint-group coverage. Residual risk: canonical file summarizes route groups while full route detail is in remediation.
2. Risk Gateway enforceability: **Resolved at architecture tier.** `12_RISK_GATEWAY_ARCHITECTURE.md` now specifies non-bypass invariants, deterministic phase order, failure precedence, duplicate guard, stale defaults, policy bundle states, kill-switch persistence, live-readiness state, connector-side hard blocks, DDL sketches, evidence, and test vectors.
3. Hot-reload failure semantics: **Resolved at architecture tier.** `08_HOT_RELOAD_PIPELINE_ARCHITECTURE.md` now includes persisted rollout/target/event models, ack binding, timeout escalation, retry/dead-letter behavior, quorum rules, partial-failure policy, rollback triggers, rollback state machine, post-apply health checks, evidence packets, and test vectors.
4. L4 human approval governance: **Resolved at architecture tier.** `13_AUDIT_LEDGER_AND_AI_CHANGE_GOVERNANCE.md` now defines L0-L5 taxonomy, approval chains/assertions, subject/body binding, capability matrix, L4/L5 three-gate enforcement, single-use consumption, rollback rules, tamper-evident audit chain, monotonic sequence semantics, DDL sketches, and test vectors.
5. Security/auth/session/RBAC contracts: **Resolved at architecture tier.** `15_PUBLIC_HOSTING_SECURITY_AND_RBAC_ARCHITECTURE.md` now defines identity/account tables, sessions/tokens/revocation, MFA and step-up assertions, RBAC route examples and middleware order, service identity limits, secrets lease boundary, IP allowlist/rate limits, auth audit hash chain, evidence packets, and security test vectors.

## Remaining risks
The five targeted blockers are materially remediated, but the architecture is still not cleanly ready for V2 scaffold planning because prior actual Codex blockers outside this five-item remediation set remain open or only partially addressed:
- Full lineage DB/API enforcement is still not closed end-to-end across database schema and all downstream records.
- Feature snapshot/value schema completeness remains under-specified relative to requirements.
- Confidence/explainability still needs a fully structured contributor/calibration/method contract, not only broad shape references.
- Trainer internal liveness exit criterion remains unresolved: no read-only validation artifact proving detection of `TRAINER_PREDICTION_WORKER_DEAD_PROCESS_ALIVE` with evidence packet output.
- Minor integration drift remains between canonical summaries and remediation detail, including `/v1` vs `/api/v1` path convention and scope-token grammar differences.

## Scaffold-readiness assessment
The five named architecture blockers are resolved at the architecture-remediation level. However, the whole architecture package is **not yet V2 scaffold-planning ready** under the requested go/no-go rule because critical/high gaps remain from the actual Codex review set.

Decision: **ACTUAL_CODEX_ARCHITECTURE_RERUN_FAIL**

## Recommended next step
Do not begin V2 scaffold planning yet. Remediate the remaining actual-Codex blockers for lineage DB/API closure, feature snapshot schema, confidence explainability schema, and trainer liveness validation, then reconcile path/scope conventions across canonical and remediation files and rerun the architecture review.