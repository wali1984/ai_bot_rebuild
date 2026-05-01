# 10 — Canonical Integration Summary (Remediation View)

> Companion to `claude_worklog/v2_architecture/10_CANONICAL_INTEGRATION_SUMMARY.md`.
> This file lives in the remediation tree and maps each remediation file's
> sections to the canonical architecture sections that integrated them,
> and to the prior Codex blockers each closure addresses.
> No code was built, no Redis was written, no service was restarted, no
> legacy file was modified.

## 1. Source remediation files

| File | Pages | Purpose |
| --- | --- | --- |
| `04_API_CONTRACT_REMEDIATION.md` | scaffold-ready API surface | rebuilds `05_API_CONTRACTS.md` |
| `05_RISK_GATEWAY_REMEDIATION.md` | scaffold-ready risk gateway | rebuilds `12_RISK_GATEWAY_ARCHITECTURE.md` |
| `06_HOT_RELOAD_REMEDIATION.md` | scaffold-ready hot-reload pipeline | rebuilds `08_HOT_RELOAD_PIPELINE_ARCHITECTURE.md` |
| `07_AI_GOVERNANCE_REMEDIATION.md` | scaffold-ready audit + governance | rebuilds `13_AUDIT_LEDGER_AND_AI_CHANGE_GOVERNANCE.md` |
| `08_SECURITY_RBAC_REMEDIATION.md` | scaffold-ready hosting security | rebuilds `15_PUBLIC_HOSTING_SECURITY_AND_RBAC_ARCHITECTURE.md` |

## 2. Section-level integration map

### 2.1 `04_API_CONTRACT_REMEDIATION.md` → `05_API_CONTRACTS.md`
| Remediation § | Canonical § |
| --- | --- |
| §1 Universal contract conventions | §1 |
| §2 RBAC scope catalog + approval levels | §2 |
| §3 Error envelope + class catalog | §3 |
| §4 Idempotency contract | §4 |
| §5 Optimistic concurrency contract | §5 |
| §6 Pagination, filtering, sorting | §6 |
| §7 Live-block deterministic envelope | §7 |
| §8 Endpoint matrix (groups + per-route rows) | §8 |
| §9 Schema deltas | §9 |
| §10 Traceability | §11 |

### 2.2 `06_HOT_RELOAD_REMEDIATION.md` → `08_HOT_RELOAD_PIPELINE_ARCHITECTURE.md`
| Remediation § | Canonical § |
| --- | --- |
| §1 HR-INV-01..12 | §1 |
| §2 Component registry tiers | §2 |
| §3 Universe envelope + policy pin | §3 |
| §4 Per-component ack envelope | §4 |
| §5 Ack timeout policy | §5 |
| §6 Retry policy | §6 |
| §7 Quorum semantics | §7 |
| §8 Partial-failure handling + override precedence | §8 |
| §9 Rollback triggers RBT-01..06 | §9 |
| §10 Rollback state machine | §10 |
| §11 Post-apply health-check | §11 |
| §12 DDL `universe_rollouts*` | §12 |
| §13 `universe_rollout_event` envelope | §13 |
| §15 Selection-policy version pinning | §14 |
| §16 Test-vector matrix | §15 |
| §17 Audit / evidence packets | §16 |

### 2.3 `05_RISK_GATEWAY_REMEDIATION.md` → `12_RISK_GATEWAY_ARCHITECTURE.md`
| Remediation § | Canonical § |
| --- | --- |
| §1 INV-01..12 | §1 |
| §2 Bundle envelope + state machine | §2 |
| §3 Per-policy schemas | §3 |
| §4 Phase order | §4 |
| §5 Failure precedence | §5 |
| §6 Duplicate-execution guard | §6 |
| §7 Stale defaults + clock | §7 |
| §8 Kill-switch persistence | §8 |
| §9 Live-readiness state machine | §9 |
| §10 Connector hard blocks | §10 |
| §11 Decision envelope + DDL | §11 |
| §12 TV-* matrix | §12 |
| §13 Audit / evidence packets | §13 |

### 2.4 `07_AI_GOVERNANCE_REMEDIATION.md` → `13_AUDIT_LEDGER_AND_AI_CHANGE_GOVERNANCE.md`
| Remediation § | Canonical § |
| --- | --- |
| §1 GOV-INV-01..15 | §1 |
| §2 Taxonomy + action catalog | §2 |
| §3 Approval object model | §3 |
| §4 Approval state machine | §4 |
| §5 Subject-integrity binding | §5 |
| §6 Actor capability matrix | §6 |
| §7 L4/L5 three-gate enforcement | §7 |
| §8 Rollback validation | §8 |
| §9 Tamper-evident hash chain | §9 |
| §10 Sequence monotonicity + gap detection | §10 |
| §11 Cross-domain governance binding | §11 |
| §12 DDL | §12 |
| §13 Event envelope | §13 |
| §14 Mandatory event kinds | §14 |
| §14 TV-GOV-* matrix | §15 |
| §15 Audit / evidence packets | §16 |

### 2.5 `08_SECURITY_RBAC_REMEDIATION.md` → `15_PUBLIC_HOSTING_SECURITY_AND_RBAC_ARCHITECTURE.md`
| Remediation § | Canonical § |
| --- | --- |
| §1 SEC-INV-01..18 | §1 |
| §2 Identity + account model | §2 |
| §3 Session + token lifecycle | §3 |
| §4 RBAC matrix + middleware chain | §4 |
| §5 Step-up auth (MFA + dual-assertion) | §5 |
| §6 Secrets provider boundary | §6 |
| §7 Edge controls + hardening | §7 |
| §8 Cross-domain bindings | §8 |
| §9 `auth_audit_events` hash chain | §9 |
| §10 SEC-T-001..040 | §10 |
| §11 Audit / evidence packets | §11 |

## 3. Codex blocker closure status

| Blocker | Title | Closure | Canonical anchor |
| --- | --- | --- | --- |
| #1 | Lineage chain end-to-end at DB+API tier | partial (API surface only; DDL closure pending future remediation) | `05` §1.4 + §9; `12` §11; `13` §13 |
| #2 | Confidence/explainability missing | partial (attribution_completeness defaults; PredictionExplain shape) | `05` §9; `12` §3.2.9 |
| #3 | Confidence explainability schema | partial | `12` §3.2.9 |
| #4 | Risk Gateway final authority asserted, not enforceably designed | CLOSED at architecture tier | `12` §1–§13 |
| #5 | Hot-reload persistence missing | CLOSED at architecture tier | `08` §1–§16 |
| #6 | Audit immutability + approval enforcement weak | CLOSED at architecture tier | `13` §1–§16 |
| #7 | Public-hosting security/RBAC scaffold | CLOSED at architecture tier | `15` §1–§11 |
| #8 | Trainer liveness exit-criterion artifact | NOT in scope of this integration | pending future remediation |

Score: **5 of 8 blockers** addressed at architecture-tier scaffold-ready level (#4, #5, #6, #7 closed; #2/#3 partially closed). #1 (DDL closure) and #8 (trainer liveness) require dedicated remediation files outside this integration pass.

## 4. Live-trading-blocked-by-default composition

The architecture preserves `CLAUDE.md`'s `LIVE TRADING: BLOCKED` default through three independent gates:
1. **API surface** — `05` §7 returns `live_blocked` (423) until five lift conditions hold.
2. **Risk Gateway** — `12` §9 `live_gate` policy emits `block` until both L5 chains (`mode.switch.paper_to_live`, `connector.live_enabled.set_true`) are `consumed` AND not subsequently rolled back.
3. **Connector boundary** — `12` §10.6 re-verifies kill-switch and live-gate independently before any exchange action.

Defeating the block requires defeating all three gates AND the audit hash chain (`13` §9) at multiple rows simultaneously.

## 5. Cross-file dependency graph

```
04_API_REM ───→ 05_API_CONTRACTS (envelope, error, idempotency, concurrency, RBAC, live-block, endpoint matrix)
05_RG_REM  ───→ 12_RISK_GATEWAY  (INV, bundle, eval order, precedence, dup, stale, kill-switch, live-gate, connector hard-block, DDL, vectors)
06_HR_REM  ───→ 08_HOT_RELOAD    (HR-INV, registry, ack, timeout/retry/quorum, RBT, rollback FSM, persistence)
07_GOV_REM ───→ 13_AUDIT_LEDGER  (GOV-INV, taxonomy, FSM, subject binding, capability matrix, three-gate, hash chain)
08_SEC_REM ───→ 15_SECURITY_RBAC (SEC-INV, identity, session/token, RBAC, MFA, secrets boundary, IP, rate, hardening)
```

`05` is the substrate for every other file's route surface. `13` is the audit substrate that `08`, `12`, and `15` write into. `15` provides identity / session / MFA that `13` consumes for approver decisions and `05` consumes for route-layer enforcement.

## 6. Scaffold-readiness summary

| Canonical file | Concrete artifacts |
| --- | --- |
| `05` | endpoint groups + rules; 22+ error classes; idempotency/concurrency/pagination; live-block envelope |
| `08` | 4 DDL tables; HR-INV 1..12; per-tier matrices; RBT-01..06; rollback FSM |
| `12` | 4 tables + 2 ALTERs; INV 1..12; bundle envelope + 5-state machine; 21 policy types; phase order; precedence; dup-key; stale defaults; kill-switch + live-gate FSMs; 8 connector hard-block checks; ~50 test vectors |
| `13` | 6 tables; GOV-INV 1..15; L0–L5 taxonomy; action catalog; FSM; subject canonical form; capability matrix; three-gate; rollback validation; hash chain; 18+ event kinds; ~50 test vectors |
| `15` | ~15 tables; SEC-INV 1..18; route-scope table; role-scope table; 12-stage middleware; MFA factor + assertion lifecycle; L5 dual-assertion; lease-only secrets; edge controls; SEC-T-001..040 |

## 7. Gate recommendation

This integration is **architecture-tier scaffold-ready** for blockers #4, #5, #6, #7. Re-running Codex CLI architecture review against the canonical set should validate closure. `V2 build remains NO-GO` until:
1. Codex re-review confirms scaffold readiness for #4–#7.
2. Remediation files for blockers #1 (lineage DDL closure) and #8 (trainer liveness exit-criterion) land.
3. Any additional blockers surfaced by re-review are closed.

Per `CLAUDE.md` defaults, **LIVE TRADING remains BLOCKED**; this integration encodes how the block is structured and how it would be lifted, not the lifting itself.