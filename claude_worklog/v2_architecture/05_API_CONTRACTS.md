# 05 — API Contracts

> Canonical API contract surface for V2. Replaces the prior 39-line stub.
> Source remediation: `claude_worklog/v2_architecture_remediation/04_API_CONTRACT_REMEDIATION.md`.
> Lineage-enforcement closure: `claude_worklog/v2_architecture_remediation/12B_API_LINEAGE_ENFORCEMENT_CLOSURE.md`.
> All routes are HTTP/1.1+JSON over TLS. RBAC, approval, idempotency,
> concurrency, error envelope, lineage validation, and live-block enforcement
> are non-bypassable.

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

### 1.3 Lineage carriage (canonical)
Every request and response that touches the lineage chain MUST carry the chain explicitly. The canonical chain, exactly as enforced in `03_DATABASE_SCHEMA.md`:

`feature_snapshot_id → prediction_id → signal_id → decision_id → risk_decision_id → execution_intent_id`

#### 1.3.1 Lineage block shape
A `lineage` object MUST appear on every prediction/signal/decision/risk/execution payload, both on the wire and inside event-bearing responses:

```
"lineage": {
  "feature_snapshot_id": "<uuid7|null>",
  "prediction_id":       "<uuid7|null>",
  "signal_id":           "<uuid7|null>",
  "decision_id":         "<uuid7|null>",
  "risk_decision_id":    "<uuid7|null>",
  "execution_intent_id": "<uuid7|null>",
  "lineage_gap_reason":  "<string|null>"
}
```

Rules:
- Upstream IDs (those that already exist for the stage being emitted) MUST be present and non-null.
- Downstream IDs (not yet produced) MUST be explicit `null`. Omission is a `lineage.malformed` validation error.
- Whenever any chain field is `null` on a stage where it should be present, `lineage_gap_reason` MUST hold a non-empty enum value: `"upstream_missing" | "downstream_not_yet_emitted" | "ingest_pre_attribution" | "replay_partial"`.
- Cross-symbol/cross-timeframe linkage is invalid. Server MUST reject with `lineage.cross_symbol` (see §3.2) when `symbol`/`timeframe` on a child does not match the resolved parent's `symbol`/`timeframe`.

#### 1.3.2 Required upstream IDs by stage
The minimum set of non-null lineage IDs in a request/response payload, by stage:

| Stage | Stage shape | Required non-null IDs |
| --- | --- | --- |
| Feature snapshot ingest | `FeatureSnapshotIngest` / `FeatureSnapshot` | `feature_snapshot_id` |
| Prediction ingest / read | `PredictionIngest` / `PredictionEvent` | `feature_snapshot_id`, `prediction_id` |
| Signal ingest / read | `SignalIngest` / `SignalEvent` | `feature_snapshot_id`, `prediction_id`, `signal_id` |
| Orchestrator decision ingest / read | `DecisionIngest` / `OrchestratorDecision` | `feature_snapshot_id`, `prediction_id`, `signal_id`, `decision_id` |
| Risk decision read | `RiskDecision` | full chain through `risk_decision_id` |
| Execution intent (paper or live) | `IntentRequest` / `ExecutionIntent` | full chain through `execution_intent_id` (the latter is server-issued; request must carry the rest) |
| Paper trade ack | `PaperTrade` | full chain through `execution_intent_id` |

#### 1.3.3 Other lineage carriers
Every event-emitting route also attaches:
- `policy_version` (selection / risk / governance bundle versions effective at request time)
- `feature_snapshot_id` (when feature data informs the call — already a member of the lineage block)
- `model_version`, `checkpoint_id` (when model output is referenced)
- `config_version` (active config bundle hash)

These are alongside the lineage block, never as a substitute for it.

### 1.4 Determinism guarantees
- Same `(idempotency_key, actor_subject, body_hash)` MUST yield byte-identical response within retention window.
- Server response time MUST NOT depend on tenant-private data leaks (constant-time comparisons for token/secret paths).

### 1.5 Read vs mutate posture
- Read routes (`GET`) are stateless, cacheable per `Cache-Control`, never require idempotency keys, but MUST still emit lineage blocks on every event payload they return.
- Mutate routes are default-deny: if any of (auth, RBAC, approval, idempotency, version, lineage validation, live-block) checks fail, the request is rejected before the handler executes.

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
5. Schema validation (`validation.schema`, `schema.unknown_field`).
6. **Lineage validation (§9)** — chain shape + parent existence + cross-symbol consistency (`lineage.*` error classes).
7. Live-block envelope (§7 below) for any live-mutation route.
8. Idempotency replay check (§4).
9. Optimistic concurrency (§5).
10. Handler.

The order is deterministic so that the server response class is reproducible from the request alone.

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
| `lineage.malformed` | 400 | no |
| `lineage.missing_attribution` | 422 | no |
| `lineage.parent_not_found` | 422 | no |
| `lineage.cross_symbol` | 422 | no |
| `lineage.chain_break` | 422 | no |
| `lineage.immutable_violation` | 409 | no |
| `lineage.duplicate_child` | 409 | no |
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

### 3.3 Lineage error class semantics

| Class | Trigger | `details` fields |
| --- | --- | --- |
| `lineage.malformed` | `lineage` block missing, has unknown fields, has wrong types, or omits a downstream ID slot (must be explicit `null`). | `missing_fields[]`, `unknown_fields[]`, `wrong_type_fields[]` |
| `lineage.missing_attribution` | A required upstream ID is `null` for the stage being emitted (per §1.3.2) and `lineage_gap_reason` is absent or invalid. | `stage`, `required_ids[]`, `missing_ids[]`, `gap_reason_supplied` |
| `lineage.parent_not_found` | A non-null upstream ID does not resolve to an existing record (FK miss). | `parent_kind`, `parent_id`, `lookup_table` |
| `lineage.cross_symbol` | Child `symbol`/`timeframe`/`exchange_symbol_id` disagrees with resolved parent. | `child_symbol`, `parent_symbol`, `child_timeframe`, `parent_timeframe` |
| `lineage.chain_break` | Two non-null IDs in the chain are inconsistent (e.g. `signal.prediction_id` ≠ `prediction_events[prediction_id].prediction_id`). | `expected`, `observed`, `break_at` |
| `lineage.immutable_violation` | Mutation attempted on a chain ID that is declared immutable (any `feature_snapshot_id`, `prediction_id`, `signal_id`, `decision_id`, `risk_decision_id`, `execution_intent_id`). | `field`, `before`, `proposed` |
| `lineage.duplicate_child` | Two children claim the same single-parent slot when single-parent linkage is required (e.g. two `signal_events` for the same `prediction_id` in the same publish window). | `parent_id`, `existing_child_id`, `proposed_child_id`, `window_ms` |

All `lineage.*` errors are non-retryable: the client must fix the payload, not retry.

### 3.4 Mapping to database integrity errors
Application-layer `lineage.parent_not_found` and `lineage.missing_attribution` MUST be raised before the DB call, but the schema (`03_DATABASE_SCHEMA.md` §"Missing-attribution rejection") is the authoritative gate. If application validation is bypassed, the DB returns an integrity error which the API translates to:
- DB FK NOT NULL violation → `lineage.missing_attribution` (HTTP 422).
- DB FK RESTRICT violation → `lineage.parent_not_found` (HTTP 422).
- DB CHECK violation on `risk_decisions.allow_block` / `block_reason` alignment → `validation.policy` (HTTP 422).
- DB trigger blocking `execution_intents` from a `block`-class `risk_decisions` → `risk.gateway_block` (HTTP 409).

The mapping is part of the contract and stable across implementations.

## 4. Idempotency contract

- Server stores `(idempotency_key, actor_subject, route, body_hash) → response_envelope` with TTL ≥ 7 days.
- Replay with same key + subject + body_hash → cached response, status `200`/original status.
- Replay with same key but different `body_hash` → `idempotency.conflict`.
- Idempotency table is a partitioned, append-only store; deletions are forbidden.
- Lineage IDs received on ingest routes are part of `body_hash`, so a replayed prediction/signal/decision/risk/intent ingest cannot smuggle in a different lineage block under the same idempotency key.

## 5. Optimistic concurrency contract

- Every versioned resource exposes `etag` (sha256 of canonical serialization including `version` integer).
- Mutation requires `If-Match: <etag>`; mismatch → `concurrency.etag_mismatch` with current `etag` and `version` in `details`.
- Server increments `version` and re-emits `etag` atomically with handler commit.
- Lineage chain rows (`feature_snapshots`, `prediction_events`, `signal_events`, `orchestrator_decisions`, `risk_decisions`, `execution_intents`) are not versioned resources because their PKs are immutable. Any PUT/PATCH that would mutate a chain ID returns `lineage.immutable_violation`.

## 6. Pagination, filtering, sorting

- `?cursor=<opaque>&limit=<1..200>` (default 50). `next_cursor` returned in `data.page`.
- `?filter[<field>]=<expr>` with whitelisted fields per route.
- `?sort=<field>:asc|desc` with whitelisted fields. Default sort is documented per route.
- Lineage filters are first-class on every event feed: `?filter[feature_snapshot_id]=`, `?filter[prediction_id]=`, `?filter[signal_id]=`, `?filter[decision_id]=`, `?filter[risk_decision_id]=`, `?filter[execution_intent_id]=`. These short-circuit table scans by hitting the indexes in `03_DATABASE_SCHEMA.md` §"Indexes for explainability and audit".

## 7. Live-block deterministic envelope

Routes flagged `live_mutation=true` short-circuit with `423 live_blocked` unless ALL five conditions hold:
1. `kill_switch_state.state = 'armed'` (§12 RG §8).
2. `live_gate_state.state = 'ready'` (§12 RG §9).
3. Active L5 chain `mode.switch.paper_to_live` consumed and not rolled back (§13 §7).
4. Active L5 chain `connector.live_enabled.set_true` consumed and not rolled back (§13 §7).
5. Connector hard-block re-verification at call-site (§12 RG §10.6).

`live_blocked` envelope `details` MUST enumerate which of (1)–(5) failed without leaking secrets. A `lineage.*` failure that occurred on the same request MUST also surface via a separate prior response — `lineage.*` is checked before `live_blocked` per §2.3.

## 8. Endpoint matrix (canonical groups)

| Group | Prefix | Min level | Live-mutation? | Lineage-bearing? |
| --- | --- | --- | --- | --- |
| Auth | `/v1/auth/*` | L0–L3 | no | no |
| Sessions | `/v1/sessions/*` | L0–L1 | no | no |
| Users / RBAC | `/v1/iam/*` | L2–L4 | no | no |
| Approvals | `/v1/governance/approvals/*` | L1–L5 | no | no |
| Audit Ledger | `/v1/audit/*` | L0 | no | references chain |
| Symbols / Markets | `/v1/markets/*` | L0 | no | no |
| Feature Snapshots | `/v1/feature_snapshots/*` | L0–L1 | no | **yes (chain root)** |
| Predictions / Explain | `/v1/predictions/*` | L0–L1 | no | **yes** |
| Signals | `/v1/signals/*` | L0–L1 | no | **yes** |
| Orchestrator Decisions | `/v1/orchestrator/decisions/*` | L0–L1 | no | **yes** |
| Strategies | `/v1/strategies/*` | L1–L4 | conditional | no |
| Risk Policies | `/v1/risk/policies/*` | L2–L4 | no | no |
| Risk Decisions | `/v1/risk/decisions/*` | L0 | no | **yes** |
| Kill Switch | `/v1/risk/kill_switch/*` | L3–L4 | no | no |
| Live Gate | `/v1/risk/live_gate/*` | L4–L5 | yes | no |
| Mode | `/v1/mode/*` | L4–L5 | yes | no |
| Connectors | `/v1/connectors/*` | L2–L5 | yes | no |
| Orders / Executions | `/v1/executions/*` | L1–L5 | yes | **yes** |
| Positions | `/v1/positions/*` | L0–L4 | conditional | references chain |
| Trainer | `/v1/trainer/*` | L0–L3 | no | no |
| Hot-Reload | `/v1/hot_reload/*` | L2–L4 | no | no |
| Config | `/v1/config/*` | L1–L4 | no | no |
| Monitors | `/v1/monitors/*` | L0–L2 | no | no |
| Secrets (lease only) | `/v1/secrets/leases/*` | L3–L4 | no | no |
| System / Health | `/v1/system/*` | L0–L2 | no | no |

Per-route rows live in §A1 of the source remediation; the canonical surface is the matrix above plus the rules in §1–§9.

## 9. Endpoint-level lineage enforcement

This section is the authoritative specification for how each lineage-bearing endpoint validates request and response payloads against the chain. Every rule below is a **MUST**. Violations map to the error classes in §3.2/§3.3.

### 9.1 Common pre-handler validators
Applied in order to any lineage-bearing route after schema validation:

1. **Shape validator.** `lineage` block exists, has the seven canonical keys (six IDs + `lineage_gap_reason`), no extras.
2. **Type validator.** Each ID is either a UUIDv7 string or `null`; `lineage_gap_reason` is `null` or an enum string.
3. **Stage-required validator.** Per §1.3.2, the IDs required for the stage are non-null.
4. **Gap-reason validator.** Any `null` in a slot that the stage allows to be downstream-empty MUST be paired with a non-empty `lineage_gap_reason`. Any `null` in a slot the stage requires non-null is `lineage.missing_attribution` (no gap reason can excuse it).
5. **Parent-existence validator.** Every non-null upstream ID resolves to a row in the corresponding parent table. If any does not, `lineage.parent_not_found`.
6. **Cross-symbol validator.** `symbol`/`timeframe`/`exchange_symbol_id` on the child equals the resolved parent's value.
7. **Chain-coherence validator.** Where the request supplies more than one upstream ID, the child's claimed parent ID for each level matches the parent's actual parent ID at the previous level (e.g. a `SignalIngest` claiming both `prediction_id=P` and `feature_snapshot_id=F` MUST satisfy `prediction_events[P].feature_snapshot_id = F`). Mismatch → `lineage.chain_break`.
8. **Immutability validator.** No mutation request (PUT/PATCH/DELETE) targets a chain ID. Any such request → `lineage.immutable_violation`.
9. **Single-parent uniqueness validator.** For ingest routes, a `(parent_id, window_ms)` duplicate produces `lineage.duplicate_child` per §3.3.

### 9.2 `/v1/feature_snapshots/*` (chain root)
- `POST /v1/feature_snapshots/ingest` (`FeatureSnapshotIngest`):
  - `feature_snapshot_id` is the *only* lineage ID; downstream slots MUST be `null` with `lineage_gap_reason="downstream_not_yet_emitted"`.
  - `source_refs` and `freshness` non-empty (mirrors DB `source_refs_json` / `freshness_json` NOT NULL).
  - Response `FeatureSnapshot` echoes the same lineage block.
- `GET /v1/feature_snapshots/{id}`: response `FeatureSnapshot` carries `feature_snapshot_id` non-null, all downstream `null`. `lineage_gap_reason="downstream_not_yet_emitted"` is acceptable; clients walk via `?filter[feature_snapshot_id]=` on `/v1/predictions` to enumerate descendants.

### 9.3 `/v1/predictions/*` (REQUIRES `feature_snapshot_id`)
- `POST /v1/predictions/ingest` (`PredictionIngest`):
  - REQUIRES non-null `feature_snapshot_id` and `prediction_id`. Missing either → `lineage.missing_attribution`.
  - Resolved `feature_snapshots` row MUST exist and `(symbol, timeframe)` must match.
  - `model_version` and `checkpoint` non-empty (mirrors `prediction_events.model_version`/`checkpoint` NOT NULL).
  - `raw_output_json` non-empty.
  - Server-side: an attempt to insert a `prediction_events` row whose `feature_snapshot_id` is unresolved is rejected first by the validator (§9.1) and ultimately by the DB FK (`03_DATABASE_SCHEMA.md` §"Missing-attribution rejection").
- `GET /v1/predictions` / `GET /v1/predictions/{id}`: every item carries `lineage` with `feature_snapshot_id` and `prediction_id` non-null; downstream slots `null` if not yet emitted.
- `GET /v1/predictions/{id}/explain`: response `PredictionExplain` MUST embed the resolved `feature_snapshot` (full, with all `feature_values`) — never a dangling `feature_snapshot_id`.

### 9.4 `/v1/signals/*` (REQUIRES `prediction_id`)
- `POST /v1/signals/ingest` (`SignalIngest`):
  - REQUIRES non-null `feature_snapshot_id`, `prediction_id`, `signal_id`.
  - Chain coherence: `prediction_events[prediction_id].feature_snapshot_id` MUST equal the request's `feature_snapshot_id`. Mismatch → `lineage.chain_break`.
  - `action` ∈ {`long`, `short`, `flat`, `close`} (mirrors DB CHECK).
  - `confidence` ∈ [0, 1] (mirrors DB CHECK).
  - `reason_json` non-empty (mirrors DB NOT NULL on `reason_json`).
  - Single-parent uniqueness: at most one `signal_events` row per `(prediction_id, publish_window_ms)`. Window default 1000 ms; configurable per `RiskPolicyBundle.duplicate_window_ms`. Duplicate → `lineage.duplicate_child`.
- `GET /v1/signals` / `GET /v1/signals/{id}`: lineage carries non-null IDs through `signal_id`.
- `GET /v1/signals/{id}/explain`: `SignalExplain` MUST include the prediction, the confidence event(s), and the active `config_version_id`. Missing any → `validation.policy`.

### 9.5 `/v1/orchestrator/decisions/*` (REQUIRES `signal_id`)
- `POST /v1/orchestrator/decisions/ingest` (`DecisionIngest`):
  - REQUIRES non-null `feature_snapshot_id`, `prediction_id`, `signal_id`, `decision_id`.
  - Chain coherence: `signal_events[signal_id].prediction_id` MUST equal request's `prediction_id`; `prediction_events[prediction_id].feature_snapshot_id` MUST equal request's `feature_snapshot_id`. Any mismatch → `lineage.chain_break`.
  - `decision_action` ∈ {`forward`, `reject`, `defer`, `split`} (mirrors DB CHECK).
  - `policy_trace_json` non-empty (mirrors DB NOT NULL).
- `GET /v1/orchestrator/decisions` / `GET /v1/orchestrator/decisions/{id}` / `GET .../policy_trace`: lineage carries non-null IDs through `decision_id`.

### 9.6 `/v1/risk/decisions/*` (REQUIRES `decision_id`)
- Risk decisions are produced by the Risk Gateway service (not external clients) but the read surface is exposed via this group. The contract is enforceable as if the gateway were a client:
  - `POST /v1/risk/decisions/ingest` (internal, `system:risk_gateway`): REQUIRES full chain through `decision_id`; `risk_decision_id` is the new ID.
  - Chain coherence: full walk from `risk_decision_id → decision_id → signal_id → prediction_id → feature_snapshot_id` must be internally consistent.
  - `allow_block` ∈ {`allow`, `block`} (mirrors DB CHECK).
  - `block_reason` constraint: `(allow_block='allow' ⇒ block_reason IS NULL) ∧ (allow_block='block' ⇒ block_reason IS NOT NULL)`. Violation → `validation.policy`.
  - `policy_checks_json` non-empty (mirrors DB NOT NULL).
- `GET /v1/risk/decisions` / `GET /v1/risk/decisions/{id}`: response carries lineage through `risk_decision_id`.

### 9.7 `/v1/executions/*` (REQUIRES `risk_decision_id`)
- `POST /v1/executions/intents` (paper, `IntentRequest` with `mode="paper"`):
  - REQUIRES non-null `feature_snapshot_id`, `prediction_id`, `signal_id`, `decision_id`, `risk_decision_id` in the request lineage block. Missing any → `lineage.missing_attribution`.
  - Resolved `risk_decisions[risk_decision_id].allow_block` MUST equal `'allow'`. Otherwise → `risk.gateway_block` (mirrors DB trigger from `03_DATABASE_SCHEMA.md` §"execution_intents").
  - Chain coherence walked end-to-end. Any mismatch → `lineage.chain_break`.
  - `mode = "paper"` accepted; `mode = "live"` triggers §7 live-block envelope and is also subject to all lineage checks first (per §2.3).
- `POST /v1/executions/intents` (live, `IntentRequest` with `mode="live"`):
  - All lineage checks identical to paper. Then live-block envelope (§7). Then handler.
- `POST /v1/executions/intents/{id}:cancel`: lineage in response is preserved; cancel request body carries no lineage block (target is identified by URL). Mutation of `execution_intent_id` itself is `lineage.immutable_violation`.
- `GET /v1/executions/intents` / `GET /v1/executions/intents/{id}`: full chain in response, all six IDs non-null.

### 9.8 `/v1/positions/*` and `/v1/audit/*` (chain references)
Positions and audit events both reference chain IDs but are not chain members themselves:
- Position rows MUST surface the originating `execution_intent_id` (and through it the full chain by lookup). A position without `execution_intent_id` → `lineage.missing_attribution` (can occur for legacy-imported positions; ingest is rejected by default).
- Audit events MUST carry whichever chain IDs are relevant to the action; no audit event referring to a chain row may omit the corresponding ID. Filters on `?filter[<chain_id>]=` MUST work on `/v1/audit/events`.

### 9.9 Pre-attribution allowance
The only legitimate stage at which a downstream slot may be `null` is when the stage has not yet emitted that ID. The only legitimate stage at which an upstream slot may be `null` is `feature_snapshot ingest` (where there is no upstream). All other configurations are rejected by §9.1.

If a route legitimately operates pre-attribution (e.g. a connector ingest pre-feature), it MUST live outside the lineage-bearing groups in §8 and MUST NOT include a `lineage` block. Adding a half-populated `lineage` block to a non-lineage route → `lineage.malformed`.

## 10. Schema deltas (referenced shapes)

`SignalEnvelope`, `PredictionExplain`, `RiskDecision`, `OrderIntent`, `ExecutionEvent`, `PolicyBundle`, `ApprovalChain`, `ApprovalAssertion`, `LiveGateState`, `KillSwitchState`, `HotReloadEnvelope`, `HotReloadAck`, `UniverseRollout`, `AuditEvent`, `SessionToken`. Each shape carries lineage fields per §1.3 and is validated per §9.

The concrete JSON shapes for the lineage-bearing payloads (`FeatureSnapshot`, `PredictionEvent`, `PredictionExplain`, `SignalEvent`, `SignalExplain`, `OrchestratorDecision`, `PolicyTrace`, `RiskDecision`, `IntentRequest`, `ExecutionIntent`) are in `04_API_CONTRACT_REMEDIATION.md` §9.4–§9.9 and are normative.

## 11. Cross-references

- Risk evaluation precedence: §12 §4–§5.
- Approval enforcement: §13 §4–§7.
- Identity / session / MFA: §15 §3 / §5.
- Hot-reload route surface: §08 §3 / §13.
- Database lineage enforcement: `03_DATABASE_SCHEMA.md` §"Lineage chain (canonical, enforceable)" and §"Lineage enforcement".
- Observability/attribution requirements: `claude_worklog/v2_requirements/01_OBSERVABILITY_AND_ATTRIBUTION_SPEC.md` and `03_PREDICTION_SIGNAL_DECISION_ID_CHAIN.md`.

## 12. Traceability

Every successful mutating response includes `trace.audit_event_id` pointing into `audit_ledger` (§13 §13). Every error response with `auth/rbac/approval/risk/lineage/live_blocked` class also emits an audit row. The audit row records the lineage block as received (after redaction of secrets), so a forensic walk can reconstruct any rejected ingest from the ledger alone.

## 13. Scaffoldable test vectors (lineage enforcement)

The test vectors below are language-agnostic specifications. Each vector has `name`, `route`, `request`, `expected_status`, and `expected_class` fields. Implementations of the V2 API MUST pass each `accept` vector and reject each `reject` vector with the specified class. Vectors are grouped by stage.

UUIDv7 placeholders below use `F1`, `P1`, `S1`, `D1`, `R1`, `E1` as short names; treat each as a distinct, valid UUIDv7. `<F2>` etc. denote a *different* UUIDv7 than `<F1>`.

### 13.1 Feature snapshot vectors

```yaml
- name: feature_snapshot_ingest_accept_minimal
  route: POST /v1/feature_snapshots/ingest
  request:
    payload:
      feature_snapshot_id: <F1>
      symbol: BTCUSDT
      timeframe: 1m
      source_refs: [{source_key: "redis:btc:1m", ref: "..."}]
      freshness: {max_age_ms: 60000, stale_count: 0, missing_count: 0}
      feature_values: [{feature_name: "rsi_14", feature_value: "55.2", source_key: "redis:btc:1m", freshness_age_ms: 1000, stale_flag: false, missing_flag: false, unused_flag: false}]
      lineage: {feature_snapshot_id: <F1>, prediction_id: null, signal_id: null, decision_id: null, risk_decision_id: null, execution_intent_id: null, lineage_gap_reason: "downstream_not_yet_emitted"}
  expected_status: 201
  expected_class: null

- name: feature_snapshot_ingest_reject_missing_lineage_block
  route: POST /v1/feature_snapshots/ingest
  request:
    payload: {feature_snapshot_id: <F1>, symbol: BTCUSDT, timeframe: 1m, source_refs: [...], freshness: {...}}
  expected_status: 400
  expected_class: lineage.malformed

- name: feature_snapshot_ingest_reject_empty_source_refs
  route: POST /v1/feature_snapshots/ingest
  request:
    payload: {feature_snapshot_id: <F1>, symbol: BTCUSDT, timeframe: 1m, source_refs: [], freshness: {...}, lineage: {...}}
  expected_status: 422
  expected_class: validation.policy
```

### 13.2 Prediction vectors

```yaml
- name: prediction_ingest_accept
  route: POST /v1/predictions/ingest
  preconditions: [feature_snapshot_ingest_accept_minimal]
  request:
    payload:
      prediction_id: <P1>
      feature_snapshot_id: <F1>
      symbol: BTCUSDT
      timeframe: 1m
      model_version: "trainer-2026.04.01"
      checkpoint: "ckpt-9821"
      raw_output: {...}
      lineage: {feature_snapshot_id: <F1>, prediction_id: <P1>, signal_id: null, decision_id: null, risk_decision_id: null, execution_intent_id: null, lineage_gap_reason: "downstream_not_yet_emitted"}
  expected_status: 201
  expected_class: null

- name: prediction_ingest_reject_missing_feature_snapshot_id
  route: POST /v1/predictions/ingest
  request:
    payload: {prediction_id: <P1>, feature_snapshot_id: null, ..., lineage: {feature_snapshot_id: null, prediction_id: <P1>, signal_id: null, decision_id: null, risk_decision_id: null, execution_intent_id: null, lineage_gap_reason: null}}
  expected_status: 422
  expected_class: lineage.missing_attribution

- name: prediction_ingest_reject_unresolved_feature_snapshot
  route: POST /v1/predictions/ingest
  request:
    payload: {prediction_id: <P1>, feature_snapshot_id: <F2-not-ingested>, ..., lineage: {feature_snapshot_id: <F2>, prediction_id: <P1>, ...}}
  expected_status: 422
  expected_class: lineage.parent_not_found

- name: prediction_ingest_reject_cross_symbol
  route: POST /v1/predictions/ingest
  preconditions: [feature_snapshot_ingest_accept_minimal]   # F1 was BTCUSDT/1m
  request:
    payload: {prediction_id: <P1>, feature_snapshot_id: <F1>, symbol: ETHUSDT, timeframe: 1m, ..., lineage: {...}}
  expected_status: 422
  expected_class: lineage.cross_symbol

- name: prediction_ingest_reject_lineage_block_downstream_omitted
  route: POST /v1/predictions/ingest
  request:
    payload: {prediction_id: <P1>, feature_snapshot_id: <F1>, ..., lineage: {feature_snapshot_id: <F1>, prediction_id: <P1>}}
  expected_status: 400
  expected_class: lineage.malformed
```

### 13.3 Signal vectors

```yaml
- name: signal_ingest_accept
  route: POST /v1/signals/ingest
  preconditions: [prediction_ingest_accept]
  request:
    payload:
      signal_id: <S1>
      prediction_id: <P1>
      feature_snapshot_id: <F1>
      symbol: BTCUSDT
      action: long
      confidence: "0.62"
      reason: {policy: "trend_follow_v3", components: [...]}
      lineage: {feature_snapshot_id: <F1>, prediction_id: <P1>, signal_id: <S1>, decision_id: null, risk_decision_id: null, execution_intent_id: null, lineage_gap_reason: "downstream_not_yet_emitted"}
  expected_status: 201

- name: signal_ingest_reject_chain_break
  route: POST /v1/signals/ingest
  preconditions: [prediction_ingest_accept]   # F1→P1 truth
  request:
    payload: {signal_id: <S1>, prediction_id: <P1>, feature_snapshot_id: <F2>, ..., lineage: {...}}
  expected_status: 422
  expected_class: lineage.chain_break

- name: signal_ingest_reject_invalid_action
  route: POST /v1/signals/ingest
  request:
    payload: {signal_id: <S1>, prediction_id: <P1>, feature_snapshot_id: <F1>, symbol: BTCUSDT, action: yolo, confidence: "0.62", reason: {...}, lineage: {...}}
  expected_status: 422
  expected_class: validation.policy

- name: signal_ingest_reject_confidence_out_of_range
  route: POST /v1/signals/ingest
  request:
    payload: {..., confidence: "1.4", ...}
  expected_status: 422
  expected_class: validation.policy

- name: signal_ingest_reject_duplicate_within_window
  route: POST /v1/signals/ingest
  preconditions: [signal_ingest_accept]
  request:
    payload: {signal_id: <S2>, prediction_id: <P1>, feature_snapshot_id: <F1>, ..., lineage: {...}}
  expected_status: 409
  expected_class: lineage.duplicate_child

- name: signal_ingest_reject_missing_reason
  route: POST /v1/signals/ingest
  request:
    payload: {..., reason: {}, lineage: {...}}
  expected_status: 422
  expected_class: validation.policy
```

### 13.4 Orchestrator decision vectors

```yaml
- name: decision_ingest_accept
  route: POST /v1/orchestrator/decisions/ingest
  preconditions: [signal_ingest_accept]
  request:
    payload:
      decision_id: <D1>
      signal_id: <S1>
      prediction_id: <P1>
      feature_snapshot_id: <F1>
      decision_action: forward
      decision_reason: "policy_pass_v2"
      policy_trace: [{policy_name: "freshness_check", result: "pass", evidence_pointers: [...]}]
      lineage: {feature_snapshot_id: <F1>, prediction_id: <P1>, signal_id: <S1>, decision_id: <D1>, risk_decision_id: null, execution_intent_id: null, lineage_gap_reason: "downstream_not_yet_emitted"}
  expected_status: 201

- name: decision_ingest_reject_unknown_signal
  route: POST /v1/orchestrator/decisions/ingest
  request:
    payload: {decision_id: <D1>, signal_id: <S-not-ingested>, prediction_id: <P1>, feature_snapshot_id: <F1>, ...}
  expected_status: 422
  expected_class: lineage.parent_not_found

- name: decision_ingest_reject_invalid_action
  route: POST /v1/orchestrator/decisions/ingest
  request:
    payload: {decision_id: <D1>, signal_id: <S1>, ..., decision_action: maybe, ...}
  expected_status: 422
  expected_class: validation.policy

- name: decision_ingest_reject_empty_policy_trace
  route: POST /v1/orchestrator/decisions/ingest
  request:
    payload: {..., policy_trace: [], ...}
  expected_status: 422
  expected_class: validation.policy
```

### 13.5 Risk decision vectors

```yaml
- name: risk_decision_ingest_accept_allow
  route: POST /v1/risk/decisions/ingest      # internal scope: system:risk_gateway
  preconditions: [decision_ingest_accept]
  request:
    payload:
      risk_decision_id: <R1>
      decision_id: <D1>
      signal_id: <S1>
      prediction_id: <P1>
      feature_snapshot_id: <F1>
      allow_block: allow
      block_reason: null
      policy_checks: [{policy_name: "stale_signal", result: "pass", details: {}}, {policy_name: "leverage", result: "pass", details: {}}]
      lineage: {feature_snapshot_id: <F1>, prediction_id: <P1>, signal_id: <S1>, decision_id: <D1>, risk_decision_id: <R1>, execution_intent_id: null, lineage_gap_reason: "downstream_not_yet_emitted"}
  expected_status: 201

- name: risk_decision_ingest_accept_block
  route: POST /v1/risk/decisions/ingest
  request:
    payload: {risk_decision_id: <R2>, decision_id: <D1>, ..., allow_block: block, block_reason: "stale_signal", policy_checks: [...], lineage: {...}}
  expected_status: 201

- name: risk_decision_ingest_reject_block_without_reason
  route: POST /v1/risk/decisions/ingest
  request:
    payload: {risk_decision_id: <R3>, decision_id: <D1>, ..., allow_block: block, block_reason: null, ...}
  expected_status: 422
  expected_class: validation.policy

- name: risk_decision_ingest_reject_allow_with_reason
  route: POST /v1/risk/decisions/ingest
  request:
    payload: {..., allow_block: allow, block_reason: "should_be_null", ...}
  expected_status: 422
  expected_class: validation.policy

- name: risk_decision_ingest_reject_unknown_decision
  route: POST /v1/risk/decisions/ingest
  request:
    payload: {risk_decision_id: <R4>, decision_id: <D-not-ingested>, ...}
  expected_status: 422
  expected_class: lineage.parent_not_found
```

### 13.6 Execution intent vectors

```yaml
- name: execution_intent_paper_accept
  route: POST /v1/executions/intents
  preconditions: [risk_decision_ingest_accept_allow]    # R1 = allow
  request:
    payload:
      trader_id: <T1>
      risk_decision_id: <R1>
      intent_action: open_long
      size: "0.10"
      price_hint: null
      reduce_only: false
      mode: paper
      lineage: {feature_snapshot_id: <F1>, prediction_id: <P1>, signal_id: <S1>, decision_id: <D1>, risk_decision_id: <R1>, execution_intent_id: null, lineage_gap_reason: "downstream_not_yet_emitted"}
  expected_status: 201

- name: execution_intent_reject_when_risk_block
  route: POST /v1/executions/intents
  preconditions: [risk_decision_ingest_accept_block]    # R2 = block
  request:
    payload: {risk_decision_id: <R2>, intent_action: open_long, mode: paper, lineage: {feature_snapshot_id: <F1>, prediction_id: <P1>, signal_id: <S1>, decision_id: <D1>, risk_decision_id: <R2>, execution_intent_id: null, lineage_gap_reason: "downstream_not_yet_emitted"}}
  expected_status: 409
  expected_class: risk.gateway_block

- name: execution_intent_reject_missing_lineage_id
  route: POST /v1/executions/intents
  request:
    payload: {risk_decision_id: <R1>, mode: paper, lineage: {feature_snapshot_id: <F1>, prediction_id: <P1>, signal_id: null, decision_id: <D1>, risk_decision_id: <R1>, execution_intent_id: null, lineage_gap_reason: null}}
  expected_status: 422
  expected_class: lineage.missing_attribution

- name: execution_intent_reject_chain_break
  route: POST /v1/executions/intents
  preconditions: [risk_decision_ingest_accept_allow]    # R1 came from D1, S1, P1, F1
  request:
    payload: {risk_decision_id: <R1>, mode: paper, lineage: {feature_snapshot_id: <F2>, prediction_id: <P1>, signal_id: <S1>, decision_id: <D1>, risk_decision_id: <R1>, execution_intent_id: null, lineage_gap_reason: "downstream_not_yet_emitted"}}
  expected_status: 422
  expected_class: lineage.chain_break

- name: execution_intent_live_blocked_by_default
  route: POST /v1/executions/intents
  preconditions: [risk_decision_ingest_accept_allow]
  request:
    payload: {trader_id: <T1>, risk_decision_id: <R1>, intent_action: open_long, size: "0.10", mode: live, lineage: {...full chain...}}
  expected_status: 423
  expected_class: live_blocked

- name: execution_intent_immutable_violation_on_patch
  route: PATCH /v1/executions/intents/<E1>
  request:
    payload: {execution_intent_id: <E2>}
  expected_status: 409
  expected_class: lineage.immutable_violation
```

### 13.7 Read-side vectors (every event GET surfaces lineage)

```yaml
- name: predictions_get_response_carries_lineage
  route: GET /v1/predictions/<P1>
  preconditions: [prediction_ingest_accept]
  expected_status: 200
  response_assert:
    data.lineage.feature_snapshot_id == <F1>
    data.lineage.prediction_id == <P1>
    data.lineage.signal_id == null
    data.lineage.decision_id == null
    data.lineage.risk_decision_id == null
    data.lineage.execution_intent_id == null
    data.lineage.lineage_gap_reason == "downstream_not_yet_emitted"

- name: signal_explain_includes_full_chain
  route: GET /v1/signals/<S1>/explain
  preconditions: [signal_ingest_accept]
  expected_status: 200
  response_assert:
    data.lineage.feature_snapshot_id == <F1>
    data.lineage.prediction_id == <P1>
    data.lineage.signal_id == <S1>
    data.prediction.lineage.prediction_id == <P1>
    data.prediction.feature_snapshot.feature_snapshot_id == <F1>
    data.config_version_id != null
    data.missing_evidence is array

- name: execution_intent_get_full_chain
  route: GET /v1/executions/intents/<E1>
  preconditions: [execution_intent_paper_accept]
  expected_status: 200
  response_assert:
    data.lineage.feature_snapshot_id == <F1>
    data.lineage.prediction_id == <P1>
    data.lineage.signal_id == <S1>
    data.lineage.decision_id == <D1>
    data.lineage.risk_decision_id == <R1>
    data.lineage.execution_intent_id == <E1>
    data.lineage.lineage_gap_reason == null

- name: filter_predictions_by_feature_snapshot
  route: GET /v1/predictions?filter[feature_snapshot_id]=<F1>
  preconditions: [prediction_ingest_accept]
  expected_status: 200
  response_assert:
    every item: data.items[].lineage.feature_snapshot_id == <F1>
```

### 13.8 Negative vector index (`reject` class coverage)
The vectors above collectively exercise every lineage error class:
- `lineage.malformed` — feature_snapshot_ingest_reject_missing_lineage_block, prediction_ingest_reject_lineage_block_downstream_omitted
- `lineage.missing_attribution` — prediction_ingest_reject_missing_feature_snapshot_id, execution_intent_reject_missing_lineage_id
- `lineage.parent_not_found` — prediction_ingest_reject_unresolved_feature_snapshot, decision_ingest_reject_unknown_signal, risk_decision_ingest_reject_unknown_decision
- `lineage.cross_symbol` — prediction_ingest_reject_cross_symbol
- `lineage.chain_break` — signal_ingest_reject_chain_break, execution_intent_reject_chain_break
- `lineage.duplicate_child` — signal_ingest_reject_duplicate_within_window
- `lineage.immutable_violation` — execution_intent_immutable_violation_on_patch
- `risk.gateway_block` — execution_intent_reject_when_risk_block
- `live_blocked` — execution_intent_live_blocked_by_default
- `validation.policy` — feature_snapshot_ingest_reject_empty_source_refs, signal_ingest_reject_invalid_action, signal_ingest_reject_confidence_out_of_range, signal_ingest_reject_missing_reason, decision_ingest_reject_invalid_action, decision_ingest_reject_empty_policy_trace, risk_decision_ingest_reject_block_without_reason, risk_decision_ingest_reject_allow_with_reason

### 13.9 Vector usage
- The vectors are scaffold inputs: a future V2 build task will materialize them as concrete fixtures (e.g. JSON files under `v2/tests/fixtures/api_lineage/`) and a runner that drives `httpx` against the FastAPI app or a mock in-process client.
- Each vector is independently runnable given its `preconditions` list. The runner MUST seed preconditions in dependency order before issuing the vector under test.
- Any deviation from the `expected_class` (including a 200 where a `reject` was expected, or a different class than specified) reopens this gap.
- Vectors MUST be re-validated against the integrated DB schema (`03_DATABASE_SCHEMA.md`) — the application-layer rejection class must match the §3.4 mapping when the DB constraint is the actual gate.