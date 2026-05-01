# 05 — API Contracts

> Canonical API contract surface for V2. Replaces the prior 39-line stub.
> Source remediation: `claude_worklog/v2_architecture_remediation/04_API_CONTRACT_REMEDIATION.md`.
> All routes are HTTP/1.1+JSON over TLS. RBAC, approval, idempotency,
> concurrency, error envelope, and live-block enforcement are non-bypassable.

## 1. Universal contract conventions

### 1.1 Request envelope
- Header `X-Request-Id` (UUIDv7) — caller-supplied, audit-bound.
- Header `X-Idempotency-Key` (required on all `POST`/`PUT`/`PATCH`/`DELETE` that mutate state).
- Header `X-Actor-Subject` derived server-side from session; clients MUST NOT supply.
- Header `If-Match: <etag>` required on every mutation of a versioned resource (see §5).
- Body MUST validate against the route's published JSON Schema; unknown fields rejected (`schema.unknown_field`).

### 1.2 Response envelope
```
{
  "request_id": "<uuidv7>",
  "ok": true|false,
  "data": <object|null>,
  "error": <error_envelope|null>,
  "trace": { "span_id": "...", "audit_event_id": "..." }
}
```

### 1.3 Lineage carriage
Every event-emitting route attaches:
- `policy_version` (selection / risk / governance bundle versions effective at request time)
- `feature_snapshot_id` (when feature data informs the call)
- `model_version`, `checkpoint_id` (when model output is referenced)
- `config_version` (active config bundle hash)

### 1.4 Determinism guarantees
- Same `(idempotency_key, actor_subject, body_hash)` MUST yield byte-identical response within retention window.
- Server response time MUST NOT depend on tenant-private data leaks (constant-time comparisons for token/secret paths).

## 2. RBAC scope catalog and approval levels

### 2.1 Scope grammar
`<domain>:<resource>:<action>` — domains: `signals`, `executions`, `positions`, `risk`, `config`, `strategy`, `trainer`, `orchestrator`, `audit`, `system`, `mode`, `connector`, `governance`, `secrets`, `monitor`.

### 2.2 Approval levels
| Level | Meaning | Required actor evidence |
| --- | --- | --- |
| L0 | Read | session + scope |
| L1 | Self-mutating, paper-only | session + scope |
| L2 | Mutating, paper-only, cross-tenant | session + scope |
| L3 | Sensitive admin, no live impact | session + scope + recent step-up |
| L4 | Pre-live mutation (lift partial gate) | session + scope + step-up + 1 approver chain consumed |
| L5 | Live-trading-affecting | session + scope + step-up + dual-approver chain consumed + subject-binding verified |

### 2.3 Enforcement order
1. TLS / edge controls (§7 SEC).
2. Auth: session valid, not revoked, MFA freshness within window (§5 SEC).
3. RBAC: route scopes ⊆ effective subject scopes.
4. Approval-gate: level ≥ route's declared minimum (L4/L5 require consumed chain bound to this exact subject + body hash).
5. Live-block envelope (§7 below) for any live-mutation route.
6. Idempotency replay check (§4).
7. Optimistic concurrency (§5).
8. Handler.

## 3. Error envelope and class catalog

### 3.1 Envelope
```
{
  "class": "<class>",
  "code": "<machine_code>",
  "message": "<human, no PII>",
  "retryable": true|false,
  "retry_after_ms": <int|null>,
  "details": { ... },
  "audit_event_id": "<id|null>"
}
```

### 3.2 Class catalog (minimum)
| Class | HTTP | Retryable |
| --- | --- | --- |
| `auth.unauthenticated` | 401 | no |
| `auth.session_expired` | 401 | no |
| `auth.mfa_required` | 401 | no |
| `auth.step_up_required` | 401 | no |
| `rbac.forbidden` | 403 | no |
| `approval.required` | 409 | no |
| `approval.not_consumed` | 409 | no |
| `approval.subject_mismatch` | 409 | no |
| `idempotency.conflict` | 409 | no |
| `concurrency.etag_mismatch` | 412 | no |
| `validation.schema` | 400 | no |
| `validation.policy` | 422 | no |
| `live_blocked` | 423 | no |
| `risk.gateway_block` | 409 | no |
| `risk.duplicate_guard` | 409 | no |
| `state.not_found` | 404 | no |
| `state.conflict` | 409 | no |
| `rate.limited` | 429 | yes |
| `dependency.unavailable` | 503 | yes |
| `internal` | 500 | conditional |
| `timeout` | 504 | yes |
| `schema.unknown_field` | 400 | no |

## 4. Idempotency contract

- Server stores `(idempotency_key, actor_subject, route, body_hash) → response_envelope` with TTL ≥ 7 days.
- Replay with same key + subject + body_hash → cached response, status `200`/original status.
- Replay with same key but different `body_hash` → `idempotency.conflict`.
- Idempotency table is a partitioned, append-only store; deletions are forbidden.

## 5. Optimistic concurrency contract

- Every versioned resource exposes `etag` (sha256 of canonical serialization including `version` integer).
- Mutation requires `If-Match: <etag>`; mismatch → `concurrency.etag_mismatch` with current `etag` and `version` in `details`.
- Server increments `version` and re-emits `etag` atomically with handler commit.

## 6. Pagination, filtering, sorting

- `?cursor=<opaque>&limit=<1..200>` (default 50). `next_cursor` returned in `data.page`.
- `?filter[<field>]=<expr>` with whitelisted fields per route.
- `?sort=<field>:asc|desc` with whitelisted fields. Default sort is documented per route.

## 7. Live-block deterministic envelope

Routes flagged `live_mutation=true` short-circuit with `423 live_blocked` unless ALL five conditions hold:
1. `kill_switch_state.state = 'armed'` (§12 RG §8).
2. `live_gate_state.state = 'ready'` (§12 RG §9).
3. Active L5 chain `mode.switch.paper_to_live` consumed and not rolled back (§13 §7).
4. Active L5 chain `connector.live_enabled.set_true` consumed and not rolled back (§13 §7).
5. Connector hard-block re-verification at call-site (§12 RG §10.6).

`live_blocked` envelope `details` MUST enumerate which of (1)–(5) failed without leaking secrets.

## 8. Endpoint matrix (canonical groups)

| Group | Prefix | Min level | Live-mutation? |
| --- | --- | --- | --- |
| Auth | `/v1/auth/*` | L0–L3 | no |
| Sessions | `/v1/sessions/*` | L0–L1 | no |
| Users / RBAC | `/v1/iam/*` | L2–L4 | no |
| Approvals | `/v1/governance/approvals/*` | L1–L5 | no |
| Audit Ledger | `/v1/audit/*` | L0 | no |
| Symbols / Markets | `/v1/markets/*` | L0 | no |
| Signals | `/v1/signals/*` | L0–L1 | no |
| Predictions / Explain | `/v1/predictions/*` | L0 | no |
| Strategies | `/v1/strategies/*` | L1–L4 | conditional |
| Risk Policies | `/v1/risk/policies/*` | L2–L4 | no |
| Risk Decisions | `/v1/risk/decisions/*` | L0 | no |
| Kill Switch | `/v1/risk/kill_switch/*` | L3–L4 | no |
| Live Gate | `/v1/risk/live_gate/*` | L4–L5 | yes |
| Mode | `/v1/mode/*` | L4–L5 | yes |
| Connectors | `/v1/connectors/*` | L2–L5 | yes |
| Orders / Executions | `/v1/executions/*` | L1–L5 | yes |
| Positions | `/v1/positions/*` | L0–L4 | conditional |
| Trainer | `/v1/trainer/*` | L0–L3 | no |
| Hot-Reload | `/v1/hot_reload/*` | L2–L4 | no |
| Config | `/v1/config/*` | L1–L4 | no |
| Monitors | `/v1/monitors/*` | L0–L2 | no |
| Secrets (lease only) | `/v1/secrets/leases/*` | L3–L4 | no |
| System / Health | `/v1/system/*` | L0–L2 | no |

Per-route rows live in §A1 of the source remediation; the canonical surface is the matrix above plus the rules in §1–§7.

## 9. Schema deltas (referenced shapes)

`SignalEnvelope`, `PredictionExplain`, `RiskDecision`, `OrderIntent`, `ExecutionEvent`, `PolicyBundle`, `ApprovalChain`, `ApprovalAssertion`, `LiveGateState`, `KillSwitchState`, `HotReloadEnvelope`, `HotReloadAck`, `UniverseRollout`, `AuditEvent`, `SessionToken`. Each shape carries lineage fields per §1.3.

## 10. Cross-references

- Risk evaluation precedence: §12 §4–§5.
- Approval enforcement: §13 §4–§7.
- Identity / session / MFA: §15 §3 / §5.
- Hot-reload route surface: §08 §3 / §13.

## 11. Traceability

Every successful mutating response includes `trace.audit_event_id` pointing into `audit_ledger` (§13 §13). Every error response with `auth/rbac/approval/risk/live_blocked` class also emits an audit row.