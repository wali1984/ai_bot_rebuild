# 04 API Contract Remediation

## Status
- Source blocker: `claude_worklog/v2_architecture_codex_review/04_API_CONTRACT_REVIEW.md` — verdict **FAIL (Critical blocker)**.
- Architecture file under remediation: `claude_worklog/v2_architecture/05_API_CONTRACTS.md`.
- This document supplies the eight missing remediation items required by the Codex adversarial review, plus the endpoint matrices and concrete schema deltas needed to make the architecture **scaffold-ready**.
- This document does **not** ship V2 code. It is an architecture-layer deliverable (contracts + schemas only).

## Scope of remediation
This file produces, in order:
1. Universal contract conventions (envelope, IDs, lineage, schema_version).
2. RBAC scope catalog and route-to-scope binding rules.
3. Standard error envelope and error code catalog (12 classes).
4. Idempotency contract (mutating routes, replay semantics, TTL).
5. Optimistic concurrency contract (versioned resources, preconditions).
6. Pagination, filtering, sorting contract (event feeds and ledgers).
7. Live-block deterministic response envelope (default-deny posture).
8. Endpoint matrix for all 20 API groups (method × path × request × response × errors × idempotency × RBAC × approval × live-block).
9. Schema deltas: concrete JSON shapes for the lineage-bearing and governance-bearing payloads identified in `02_DOMAIN_MODEL_AND_CORE_ENTITIES.md` and `03_DATABASE_SCHEMA.md`.
10. Traceability table mapping each Codex gap to the section that closes it.
11. Gate recommendation.

## Read/write boundary compliance
This document only writes under `./claude_worklog/`. It does not edit `./legacy_reference/**`, does not import legacy modules, does not write Redis, and does not place/cancel orders. Live mutation routes specified below are blocked-by-default per `CLAUDE.md` — the contract encodes the block, it does not enable execution.

---

## 1. Universal contract conventions

### 1.1 Base path and versioning
- Base path: `/api/v1`.
- Schema version is per-payload: every request and response body MUST include `schema_version` (semver string).
- Backward-incompatible changes bump the path (`/api/v2`) and the `schema_version` major.
- All times are millisecond UNIX epoch in field names suffixed `_ts_ms`.
- Currency, leverage, sizing, prices: string-encoded decimals, no float.

### 1.2 Standard request envelope (mutating routes)
Every mutating route (`POST`, `PUT`, `PATCH`, `DELETE`) MUST carry:

```json
{
  "schema_version": "1.0.0",
  "request_id": "uuid-v7",
  "actor": {
    "actor_type": "human|claude|codex|ollama|system",
    "actor_id": "string",
    "session_id": "string|null"
  },
  "reason": "string",
  "evidence_pointers": [
    {"kind": "redis|log|db|file|monitor_snapshot|evidence_packet", "ref": "string"}
  ],
  "client_ts_ms": 1735689600000,
  "payload": { /* route-specific body */ }
}
```

Headers (mutating routes):
- `Authorization: Bearer <session_token>` — required.
- `X-Request-Id: <uuid-v7>` — required, mirrors `request_id`.
- `X-Idempotency-Key: <uuid-v7>` — required (see §4).
- `If-Match: "<resource_version>"` — required for versioned resources (see §5).
- `X-Schema-Version: 1.0.0` — required.
- `X-Approval-Token: <approval_id>` — required for approval-gated routes.

### 1.3 Standard response envelope (success)

```json
{
  "schema_version": "1.0.0",
  "request_id": "uuid-v7",
  "server_ts_ms": 1735689600100,
  "resource_version": "etag-or-int",
  "result": { /* route-specific body */ },
  "audit": {
    "audit_event_id": "uuid-v7",
    "change_id": "uuid-v7|null",
    "approval_state": "not_required|pending|approved|rejected",
    "risk_level": "L0|L1|L2|L3|L4|L5"
  }
}
```

### 1.4 Mandatory lineage fields
Routes that produce, consume, or reference items in the lineage chain MUST surface the chain explicitly. The chain is:

`feature_snapshot_id → prediction_id → signal_id → decision_id → risk_decision_id → execution_intent_id`

Any response that returns a `signal_event`, `orchestrator_decision`, `risk_decision`, `execution_intent`, `paper_trade`, or any explainability payload MUST include the full lineage chain. Missing upstream IDs are represented as explicit `null` with an accompanying `lineage_gap_reason` string — never omitted, never silently zero.

### 1.5 Read vs mutate posture
- Read routes (`GET`) are stateless, cacheable per `Cache-Control`, never require idempotency keys.
- Mutate routes are default-deny: if any of (auth, RBAC, approval, idempotency, version) checks fail, the request is rejected before the handler executes.

---

## 2. RBAC scope catalog

### 2.1 Roles
- `viewer` — read-only across non-secret resources.
- `operator` — paper/replay control, monitoring, evidence packets, non-trading runtime ops.
- `admin` — config/strategy/orchestrator/risk-policy admin (non-live impact).
- `security_admin` — RBAC, users, secrets references, hosting, kill switch.
- `live_admin` — only role permitted to flip live-trading-impacting fields; all such flips still require `approval` workflow and are L5.
- `system` — internal service identity for monitor/adapter callbacks.

### 2.2 Scope tokens (granular, route-attached)
Each route binds to one or more scope tokens. A request is allowed iff `(role.permissions ⊇ route.scopes)` AND any approval requirements are met.

| Scope token | Description |
| --- | --- |
| `read:public` | Health, schema discovery, version. |
| `read:universe` | Read universe + scoring + overrides (no secrets). |
| `read:lineage` | Read feature/prediction/signal/decision/risk/execution events. |
| `read:trader_fleet` | Read trader instances, assignments, status. |
| `read:audit` | Read audit ledger, AI changes, evidence packets. |
| `read:config` | Read config versions and diffs. |
| `read:monitor` | Read monitor snapshots and heartbeat events. |
| `write:paper` | Issue paper-mode operations (replay, sim, paper trade ack). |
| `write:override` | Propose/approve symbol overrides (subject to approval). |
| `write:config` | Propose config changes (non-live). |
| `write:strategy` | Propose strategy/orchestrator/risk policy changes (non-live). |
| `write:trader_fleet` | Reassign symbols, pause traders (paper-mode). |
| `write:approval` | Approve/reject pending changes (within own authority level). |
| `write:rbac` | Manage users, roles, sessions. |
| `write:kill_switch` | Trip/reset kill switch. |
| `write:live_gate` | Toggle live-readiness gate flags (proposal only). |
| `system:monitor` | Internal monitor publish endpoints. |
| `system:adapter` | Internal trainer/orchestrator/exchange adapter ingress. |

### 2.3 Approval levels (mapped to AI governance levels)
Per `13_AUDIT_LEDGER_AND_AI_CHANGE_GOVERNANCE.md`:

| Level | Approval requirement |
| --- | --- |
| L0 (observe) | None. |
| L1 (docs/reports) | None. |
| L2 (V2 non-live config) | Single `admin` approval. |
| L3 (operational non-trading) | Single `admin` approval + `change_id` audit. |
| L4 (trading-impacting, paper or staged) | `admin` proposal + `live_admin` approval. |
| L5 (dangerous live changes) | Human-only origin; never autonomous; `live_admin` approval; secondary out-of-band confirmation; explicit `X-Live-Confirm: I-UNDERSTAND` header. |

L5 is hard-coded as never-autonomous in the route handler — even with a valid approval token, requests with `actor.actor_type != "human"` are rejected.

---

## 3. Error contract

### 3.1 Standard error envelope
All non-2xx responses MUST conform to:

```json
{
  "schema_version": "1.0.0",
  "request_id": "uuid-v7",
  "server_ts_ms": 1735689600100,
  "error": {
    "code": "RISK_GATE_BLOCK",
    "class": "risk_gate_block",
    "http_status": 409,
    "message": "Human-readable message.",
    "field": "payload.size",
    "retriable": false,
    "retry_after_ms": null,
    "evidence_pointers": [{"kind": "log", "ref": "..."}],
    "details": { /* class-specific structured detail */ }
  }
}
```

### 3.2 Error class catalog

| Class | HTTP | When it fires | Retriable |
| --- | --- | --- | --- |
| `validation` | 400 | Schema/field validation failure. | No (fix payload). |
| `auth` | 401 | Missing/invalid session. | No. |
| `forbidden` | 403 | RBAC scope mismatch. | No. |
| `not_found` | 404 | Resource ID unknown or out of tenant. | No. |
| `precondition_failed` | 412 | `If-Match` mismatch (concurrency). | Yes after re-read. |
| `idempotency_conflict` | 409 | Same idempotency key, different payload hash. | No (fix client). |
| `idempotency_replay` | 200/201 | Same key, same hash → replays prior result. | N/A (success path). |
| `approval_required` | 409 | Missing `X-Approval-Token` for L2+ change. | Yes after approval. |
| `approval_state_invalid` | 409 | Token rejected/expired/wrong approver. | No. |
| `risk_gate_block` | 409 | Risk Gateway denied a mutation/intent. | No. |
| `live_blocked` | 423 | Live-trading default-deny posture (see §7). | No. |
| `dependency_timeout` | 504 | Adapter/trainer/exchange call exceeded SLO. | Yes with backoff. |
| `dependency_unavailable` | 503 | Required adapter not ready (e.g. trainer venv). | Yes with backoff. |
| `rate_limited` | 429 | Per-actor rate cap. | Yes after `retry_after_ms`. |
| `internal` | 500 | Unhandled. | Sometimes (with backoff). |

### 3.3 Risk-gate-block detail shape

```json
{
  "policy_check_id": "string",
  "policy_name": "stale_signal|missing_attribution|duplicate|leverage|stop|loss_cap|kill_switch|sizing|reduce_only|live_gate",
  "checked_at_ts_ms": 1735689600200,
  "decision_id": "uuid-v7",
  "risk_decision_id": "uuid-v7|null",
  "blocking_evidence": [{"kind": "redis", "ref": "v2:risk:..."}]
}
```

---

## 4. Idempotency contract

### 4.1 Where it applies
All mutating routes (`POST`, `PUT`, `PATCH`, `DELETE`).

### 4.2 Header
- `X-Idempotency-Key: <uuid-v7>` — required.
- Server stores `(actor_id, route, idempotency_key, payload_sha256, response, created_ts_ms)` for **24 hours minimum**, **7 days for L4/L5**.

### 4.3 Replay semantics
- Same `(actor, route, key, payload_sha256)` within TTL → **replay**: return the stored response with `X-Idempotency-Replay: true`.
- Same key but different payload hash → **conflict**: return `idempotency_conflict` (409) with the original `request_id`.
- Different key → fresh execution.

### 4.4 Sequencing rules
- Idempotency keys are **per-route**; the same key on a different route is a fresh request.
- Keys MUST be UUIDv7 (time-ordered) so server-side eviction is monotonic.

### 4.5 Routes exempt from idempotency
- Pure reads (`GET`).
- Internal `system:monitor` heartbeat publishes (idempotent by `(component_instance, ts)`).

---

## 5. Optimistic concurrency contract

### 5.1 Versioned resources
The following resource families MUST publish `resource_version` (string) in every read response and require `If-Match: "<resource_version>"` on every mutation:

- `universe_versions`, `universe_members`, `symbol_overrides`
- `config_versions`
- `strategy_profile`, `risk_policy_bundle`, `orchestrator_policy`
- `trader_instances`, `trader_assignments`
- `users`, `roles`
- live-readiness gate flags

### 5.2 Mismatch handling
- Mismatch → `precondition_failed` (412) with the current `resource_version` in `error.details.current_version`.
- Client MUST re-read, recompute its proposed change, re-submit with updated `If-Match`.

### 5.3 Universe-version state machine
`proposed → validated → approved → applied → verified` (cf. `03_DATABASE_SCHEMA.md`). Each transition is its own endpoint; transitions are idempotent on `(universe_version_id, target_state)`. Skipping states is `validation` error.

---

## 6. Pagination, filtering, sorting

### 6.1 Cursor-based pagination (mandatory for event feeds)
- Query: `?cursor=<opaque_b64>&limit=<1..500>`.
- Default `limit=100`, hard max `500`.
- Response includes `result.page = { "next_cursor": "...|null", "prev_cursor": "...|null", "approx_total": 12345 }`.
- Cursors are opaque, signed, and tied to the original filter set; mutating the filter invalidates the cursor.

### 6.2 Filtering grammar
- Time window: `?from_ts_ms=<int>&to_ts_ms=<int>` (inclusive/exclusive bounds documented per route).
- Equality: `?field=value` (repeated for OR within a field).
- Range: `?field__gte=`, `?field__lte=`.
- Set: `?field__in=a,b,c`.
- Lineage: `?feature_snapshot_id=`, `?prediction_id=`, `?signal_id=`, `?decision_id=`, `?risk_decision_id=`, `?execution_intent_id=`.

### 6.3 Sorting
- `?sort=<field>:asc|desc` (single field).
- Default sort: `created_ts_ms:desc`.
- Sortable fields are enumerated per route.

### 6.4 Routes that REQUIRE pagination
All event feeds: `prediction_events`, `confidence_events`, `signal_events`, `orchestrator_decisions`, `risk_decisions`, `execution_intents`, `audit_events`, `ai_action_changes`, `monitor_snapshots`, `evidence_packets`, `heartbeat_events`, `paper_trades`, `redis_key_observations`.

---

## 7. Live-block deterministic envelope

### 7.1 Default posture
Per `CLAUDE.md` and `01_ENTERPRISE_SYSTEM_ARCHITECTURE.md`: **LIVE TRADING: BLOCKED** by default. Every live-mutation route returns `live_blocked` (HTTP 423) until **all** readiness gates pass.

### 7.2 Canonical blocked response

```json
{
  "schema_version": "1.0.0",
  "request_id": "uuid-v7",
  "server_ts_ms": 1735689600300,
  "error": {
    "code": "LIVE_TRADING_BLOCKED",
    "class": "live_blocked",
    "http_status": 423,
    "message": "Live mutation blocked by default-deny posture.",
    "retriable": false,
    "retry_after_ms": null,
    "evidence_pointers": [{"kind": "config", "ref": "v2:live_gate:state"}],
    "details": {
      "live_gate_state": "blocked",
      "failing_gates": [
        "monitor_completeness",
        "risk_policy_signoff",
        "approval_workflow_active",
        "kill_switch_armed",
        "human_confirmation_present"
      ],
      "required_approval_level": "L5",
      "required_actor_type": "human",
      "x_live_confirm_required": true
    }
  }
}
```

### 7.3 Routes always under live-block
- `POST /traders/{trader_id}/intents` when `mode=live`.
- `PUT /risk_policy/live_enabled`.
- `PUT /trader_fleet/live_enabled`.
- `PUT /exchange_connectors/{id}/live_enabled`.
- `POST /exchange_accounts/{id}/api_keys` (any mutation).
- `PUT /risk_policy/leverage`, `/margin_mode`, `/kill_switch`, `/stop_policy`, `/loss_cap` when applied to a `live_allowed=true` member.

### 7.4 Lifting the block
The block is lifted only when **all** of:
1. `live_gate.state == "ready"` (computed from monitor completeness, risk-policy signoff, audit ledger health, evidence packet freshness).
2. Request actor is human (`actor.actor_type == "human"`).
3. `X-Live-Confirm: I-UNDERSTAND` present.
4. Valid L5 approval token.
5. Kill switch armed and reachable.

Failure of any → 423 with `failing_gates` populated.

---

## 8. Endpoint matrix — all 20 API groups

Each row defines: `Method · Path · Request body shape · Response shape · Error classes · Idempotency · RBAC scope(s) · Approval level · Live-block applicability`.

Where a body is named (e.g. `UniverseProposal`), the concrete schema delta appears in §9.

### 8.1 Auth/session
| # | Method | Path | Request | Response | Errors | Idem | Scope | Approval | Live-block |
| - | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1.1 | POST | `/auth/login` | `LoginRequest` | `Session` | validation, auth, rate_limited | yes | `read:public` | none | no |
| 1.2 | POST | `/auth/logout` | empty | `OkAck` | auth | yes | (any session) | none | no |
| 1.3 | POST | `/auth/session/refresh` | `RefreshRequest` | `Session` | auth | yes | (any session) | none | no |
| 1.4 | POST | `/auth/mfa/enroll` | `MfaEnroll` | `MfaEnrollChallenge` | validation, auth | yes | `write:rbac` | L2 | no |
| 1.5 | POST | `/auth/mfa/verify` | `MfaVerify` | `OkAck` | validation, auth | yes | (self) | none | no |
| 1.6 | GET | `/auth/whoami` | — | `Identity` | auth | n/a | (any session) | none | no |

### 8.2 Market universe
| # | Method | Path | Request | Response | Errors | Idem | Scope | Approval | Live-block |
| - | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2.1 | GET | `/universe/versions` | filters | `Page<UniverseVersion>` | auth, forbidden | n/a | `read:universe` | none | no |
| 2.2 | GET | `/universe/versions/{id}` | — | `UniverseVersion` | not_found | n/a | `read:universe` | none | no |
| 2.3 | POST | `/universe/versions` | `UniverseProposal` | `UniverseVersion` | validation, forbidden, approval_required | yes | `write:override`+`read:universe` | L2 | no |
| 2.4 | POST | `/universe/versions/{id}:validate` | empty | `UniverseVersion` | precondition_failed, dependency_timeout | yes | `write:override` | L2 | no |
| 2.5 | POST | `/universe/versions/{id}:approve` | `ApprovalDecision` | `UniverseVersion` | approval_state_invalid | yes | `write:approval` | L2 | no |
| 2.6 | POST | `/universe/versions/{id}:apply` | empty | `UniverseVersion` | precondition_failed, risk_gate_block | yes | `write:override`+`live_admin` if any `live_allowed=true` | L4 | conditional |
| 2.7 | POST | `/universe/versions/{id}:verify` | `VerifyEvidence` | `UniverseVersion` | validation | yes | `write:override` | L2 | no |
| 2.8 | GET | `/universe/members` | filters | `Page<UniverseMember>` | — | n/a | `read:universe` | none | no |

### 8.3 Passive discovery
| # | Method | Path | Request | Response | Errors | Idem | Scope | Approval | Live-block |
| - | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 3.1 | GET | `/discovery/observed` | filters | `Page<ObservedSymbol>` | — | n/a | `read:universe` | none | no |
| 3.2 | GET | `/discovery/candidates` | filters | `Page<DiscoveryCandidate>` | — | n/a | `read:universe` | none | no |
| 3.3 | POST | `/discovery/refresh` | `DiscoveryRefreshRequest` | `DiscoveryJob` | rate_limited | yes | `write:strategy` | L2 | no |
| 3.4 | GET | `/discovery/jobs/{id}` | — | `DiscoveryJob` | not_found | n/a | `read:universe` | none | no |

### 8.4 Symbol scoring
| # | Method | Path | Request | Response | Errors | Idem | Scope | Approval | Live-block |
| - | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 4.1 | GET | `/scoring/scores` | filters | `Page<SymbolScore>` | — | n/a | `read:universe` | none | no |
| 4.2 | GET | `/scoring/scores/{id}` | — | `SymbolScore` | not_found | n/a | `read:universe` | none | no |
| 4.3 | POST | `/scoring/recompute` | `RecomputeRequest` | `RecomputeJob` | rate_limited | yes | `write:strategy` | L2 | no |
| 4.4 | GET | `/scoring/components/{exchange_symbol_id}` | — | `ScoreComponents` | not_found | n/a | `read:universe` | none | no |

### 8.5 Symbol override / admin approval
| # | Method | Path | Request | Response | Errors | Idem | Scope | Approval | Live-block |
| - | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 5.1 | GET | `/overrides` | filters | `Page<SymbolOverride>` | — | n/a | `read:universe` | none | no |
| 5.2 | POST | `/overrides` | `OverrideProposal` | `SymbolOverride` | validation, approval_required | yes | `write:override` | L2 | no |
| 5.3 | POST | `/overrides/{id}:approve` | `ApprovalDecision` | `SymbolOverride` | approval_state_invalid | yes | `write:approval` | L2 | no |
| 5.4 | POST | `/overrides/{id}:reject` | `ApprovalDecision` | `SymbolOverride` | approval_state_invalid | yes | `write:approval` | L2 | no |
| 5.5 | POST | `/overrides/{id}:rollback` | `RollbackRequest` | `SymbolOverride` | precondition_failed | yes | `write:override`+`write:approval` | L3 | no |

### 8.6 Exchanges / connectors
| # | Method | Path | Request | Response | Errors | Idem | Scope | Approval | Live-block |
| - | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 6.1 | GET | `/exchanges` | — | `List<Exchange>` | — | n/a | `read:public` | none | no |
| 6.2 | GET | `/exchanges/{id}/connectors` | — | `List<Connector>` | — | n/a | `read:universe` | none | no |
| 6.3 | PUT | `/connectors/{id}/health:probe` | empty | `ConnectorHealth` | dependency_timeout | yes | `system:adapter` or `admin` | L1 | no |
| 6.4 | PUT | `/connectors/{id}/enabled` | `EnabledFlag` | `Connector` | precondition_failed | yes | `write:strategy` | L3 | no |
| 6.5 | PUT | `/connectors/{id}/live_enabled` | `EnabledFlag` | `Connector` | live_blocked, approval_state_invalid | yes | `write:live_gate` | L5 | **yes** |
| 6.6 | GET | `/exchange_accounts` | — | `List<ExchangeAccount>` (no secrets) | — | n/a | `read:universe` | none | no |
| 6.7 | POST | `/exchange_accounts/{id}/api_keys` | `ApiKeyRotation` | `ApiKeyAck` | live_blocked | yes | `write:rbac`+`live_admin` | L5 | **yes** |

### 8.7 Ingestors
| # | Method | Path | Request | Response | Errors | Idem | Scope | Approval | Live-block |
| - | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 7.1 | GET | `/ingestors` | — | `List<Ingestor>` | — | n/a | `read:monitor` | none | no |
| 7.2 | GET | `/ingestors/{id}/status` | — | `IngestorStatus` | not_found | n/a | `read:monitor` | none | no |
| 7.3 | POST | `/ingestors/{id}:pause` | `PauseRequest` | `IngestorStatus` | precondition_failed | yes | `write:strategy` | L3 | no |
| 7.4 | POST | `/ingestors/{id}:resume` | empty | `IngestorStatus` | precondition_failed | yes | `write:strategy` | L3 | no |
| 7.5 | POST | `/ingestors/heartbeat` | `HeartbeatPublish` | `OkAck` | validation | yes | `system:monitor` | none | no |

### 8.8 Feature snapshots
| # | Method | Path | Request | Response | Errors | Idem | Scope | Approval | Live-block |
| - | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 8.1 | GET | `/feature_snapshots` | filters | `Page<FeatureSnapshot>` | — | n/a | `read:lineage` | none | no |
| 8.2 | GET | `/feature_snapshots/{id}` | — | `FeatureSnapshot` (incl. all `feature_values`) | not_found | n/a | `read:lineage` | none | no |
| 8.3 | GET | `/feature_snapshots/{id}/freshness` | — | `FreshnessReport` | not_found | n/a | `read:lineage` | none | no |
| 8.4 | POST | `/feature_snapshots/ingest` | `FeatureSnapshotIngest` | `FeatureSnapshotAck` | validation | yes | `system:adapter` | none | no |

### 8.9 Predictions
| # | Method | Path | Request | Response | Errors | Idem | Scope | Approval | Live-block |
| - | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 9.1 | GET | `/predictions` | filters+lineage | `Page<PredictionEvent>` | — | n/a | `read:lineage` | none | no |
| 9.2 | GET | `/predictions/{id}` | — | `PredictionEvent` | not_found | n/a | `read:lineage` | none | no |
| 9.3 | GET | `/predictions/{id}/explain` | — | `PredictionExplain` | not_found | n/a | `read:lineage` | none | no |
| 9.4 | POST | `/predictions/ingest` | `PredictionIngest` | `PredictionAck` | validation | yes | `system:adapter` | none | no |

### 8.10 Signals
| # | Method | Path | Request | Response | Errors | Idem | Scope | Approval | Live-block |
| - | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10.1 | GET | `/signals` | filters+lineage | `Page<SignalEvent>` | — | n/a | `read:lineage` | none | no |
| 10.2 | GET | `/signals/{id}` | — | `SignalEvent` | not_found | n/a | `read:lineage` | none | no |
| 10.3 | GET | `/signals/{id}/explain` | — | `SignalExplain` | not_found | n/a | `read:lineage` | none | no |
| 10.4 | POST | `/signals/ingest` | `SignalIngest` | `SignalAck` | validation | yes | `system:adapter` | none | no |

### 8.11 Orchestrator decisions
| # | Method | Path | Request | Response | Errors | Idem | Scope | Approval | Live-block |
| - | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 11.1 | GET | `/decisions` | filters+lineage | `Page<OrchestratorDecision>` | — | n/a | `read:lineage` | none | no |
| 11.2 | GET | `/decisions/{id}` | — | `OrchestratorDecision` | not_found | n/a | `read:lineage` | none | no |
| 11.3 | GET | `/decisions/{id}/policy_trace` | — | `PolicyTrace` | not_found | n/a | `read:lineage` | none | no |
| 11.4 | POST | `/decisions/ingest` | `DecisionIngest` | `DecisionAck` | validation, risk_gate_block | yes | `system:adapter` | none | no |

### 8.12 Risk decisions
| # | Method | Path | Request | Response | Errors | Idem | Scope | Approval | Live-block |
| - | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 12.1 | GET | `/risk/decisions` | filters+lineage | `Page<RiskDecision>` | — | n/a | `read:lineage` | none | no |
| 12.2 | GET | `/risk/decisions/{id}` | — | `RiskDecision` | not_found | n/a | `read:lineage` | none | no |
| 12.3 | GET | `/risk/policy` | — | `RiskPolicyBundle` | — | n/a | `read:config` | none | no |
| 12.4 | PUT | `/risk/policy` | `RiskPolicyBundle` | `RiskPolicyBundle` | validation, precondition_failed, approval_required, live_blocked | yes | `write:strategy` | L4 | conditional |
| 12.5 | PUT | `/risk/policy/kill_switch` | `KillSwitch` | `KillSwitchState` | approval_state_invalid | yes | `write:kill_switch` | L4 | conditional |
| 12.6 | POST | `/risk/policy:simulate` | `RiskPolicyBundle` | `RiskSimulationReport` | validation | yes | `write:strategy` | L1 | no |

### 8.13 Execution intents
| # | Method | Path | Request | Response | Errors | Idem | Scope | Approval | Live-block |
| - | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 13.1 | GET | `/execution/intents` | filters+lineage | `Page<ExecutionIntent>` | — | n/a | `read:lineage` | none | no |
| 13.2 | GET | `/execution/intents/{id}` | — | `ExecutionIntent` | not_found | n/a | `read:lineage` | none | no |
| 13.3 | POST | `/execution/intents` (paper) | `IntentRequest` (`mode="paper"`) | `ExecutionIntent` | validation, risk_gate_block | yes | `write:paper` | L2 | no |
| 13.4 | POST | `/execution/intents` (live) | `IntentRequest` (`mode="live"`) | `ExecutionIntent` | live_blocked, risk_gate_block | yes | `write:live_gate` | L5 | **yes** |
| 13.5 | POST | `/execution/intents/{id}:cancel` (paper) | empty | `ExecutionIntent` | precondition_failed | yes | `write:paper` | L2 | no |

### 8.14 Trader fleet
| # | Method | Path | Request | Response | Errors | Idem | Scope | Approval | Live-block |
| - | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 14.1 | GET | `/traders` | filters | `Page<TraderInstance>` | — | n/a | `read:trader_fleet` | none | no |
| 14.2 | GET | `/traders/{id}` | — | `TraderInstance` | not_found | n/a | `read:trader_fleet` | none | no |
| 14.3 | PUT | `/traders/{id}/risk_profile` | `RiskProfile` | `TraderInstance` | precondition_failed | yes | `write:strategy` | L4 | conditional |
| 14.4 | PUT | `/traders/{id}/symbol_scope` | `SymbolScope` | `TraderInstance` | precondition_failed | yes | `write:trader_fleet` | L3 | no |
| 14.5 | POST | `/traders/{id}:pause` | `PauseRequest` | `TraderInstance` | — | yes | `write:trader_fleet` | L2 | no |
| 14.6 | POST | `/traders/{id}:resume` | empty | `TraderInstance` | — | yes | `write:trader_fleet` | L2 | no |
| 14.7 | PUT | `/traders/{id}/mode` | `PaperLiveMode` | `TraderInstance` | live_blocked | yes | `write:live_gate` | L5 | **yes** |
| 14.8 | GET | `/traders/{id}/heartbeat` | — | `Heartbeat` | not_found | n/a | `read:trader_fleet` | none | no |

### 8.15 Monitor / evidence packets
| # | Method | Path | Request | Response | Errors | Idem | Scope | Approval | Live-block |
| - | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 15.1 | GET | `/monitor/snapshots` | filters | `Page<MonitorSnapshot>` | — | n/a | `read:monitor` | none | no |
| 15.2 | GET | `/monitor/snapshots/{id}` | — | `MonitorSnapshot` | not_found | n/a | `read:monitor` | none | no |
| 15.3 | POST | `/monitor/snapshots` | `MonitorSnapshotIngest` | `MonitorSnapshot` | validation | yes | `system:monitor` | none | no |
| 15.4 | GET | `/evidence_packets` | filters | `Page<EvidencePacket>` | — | n/a | `read:audit` | none | no |
| 15.5 | GET | `/evidence_packets/{id}` | — | `EvidencePacket` | not_found | n/a | `read:audit` | none | no |
| 15.6 | POST | `/evidence_packets` | `EvidencePacketIngest` | `EvidencePacket` | validation | yes | `system:monitor` or `write:strategy` | L1 | no |

### 8.16 Audit ledger
| # | Method | Path | Request | Response | Errors | Idem | Scope | Approval | Live-block |
| - | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 16.1 | GET | `/audit/events` | filters | `Page<AuditEvent>` | — | n/a | `read:audit` | none | no |
| 16.2 | GET | `/audit/events/{id}` | — | `AuditEvent` | not_found | n/a | `read:audit` | none | no |
| 16.3 | GET | `/audit/ai_changes` | filters | `Page<AiActionChange>` | — | n/a | `read:audit` | none | no |
| 16.4 | GET | `/audit/ai_changes/{id}` | — | `AiActionChange` | not_found | n/a | `read:audit` | none | no |
| 16.5 | POST | `/audit/ai_changes/{id}:approve` | `ApprovalDecision` | `AiActionChange` | approval_state_invalid | yes | `write:approval` | depends on `risk_level` | conditional |
| 16.6 | POST | `/audit/ai_changes/{id}:reject` | `ApprovalDecision` | `AiActionChange` | approval_state_invalid | yes | `write:approval` | depends | no |
| 16.7 | POST | `/audit/ai_changes/{id}:rollback` | `RollbackRequest` | `AiActionChange` | precondition_failed, risk_gate_block | yes | `write:approval`+`write:strategy` | L3+ | conditional |

### 8.17 Config admin
| # | Method | Path | Request | Response | Errors | Idem | Scope | Approval | Live-block |
| - | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 17.1 | GET | `/config/versions` | filters | `Page<ConfigVersion>` | — | n/a | `read:config` | none | no |
| 17.2 | GET | `/config/versions/{id}` | — | `ConfigVersion` | not_found | n/a | `read:config` | none | no |
| 17.3 | GET | `/config/versions/{id}/diff` | — | `ConfigDiff` | not_found | n/a | `read:config` | none | no |
| 17.4 | POST | `/config/versions` | `ConfigProposal` | `ConfigVersion` | validation, approval_required | yes | `write:config` | L2 (L4 if `scope="risk"`/`"live"`) | conditional |
| 17.5 | POST | `/config/versions/{id}:apply` | empty | `ConfigVersion` | precondition_failed, live_blocked | yes | `write:config` | L2/L4 | conditional |
| 17.6 | POST | `/config/versions/{id}:rollback` | `RollbackRequest` | `ConfigVersion` | precondition_failed | yes | `write:config`+`write:approval` | L3 | conditional |

### 8.18 AI governance
| # | Method | Path | Request | Response | Errors | Idem | Scope | Approval | Live-block |
| - | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 18.1 | GET | `/ai/governance/levels` | — | `GovernanceLevels` | — | n/a | `read:public` | none | no |
| 18.2 | GET | `/ai/governance/policy` | — | `GovernancePolicy` | — | n/a | `read:config` | none | no |
| 18.3 | PUT | `/ai/governance/policy` | `GovernancePolicy` | `GovernancePolicy` | validation, precondition_failed, approval_required | yes | `write:strategy` | L3 | no |
| 18.4 | POST | `/ai/governance/proposals` | `AiActionChange` (proposal) | `AiActionChange` | validation | yes | `write:strategy` (claude/codex/ollama act via system identity that proxies actor) | depends on `risk_level` | conditional |
| 18.5 | GET | `/ai/governance/queue` | filters | `Page<AiActionChange>` | — | n/a | `read:audit` | none | no |
| 18.6 | POST | `/ai/governance/queue/{id}:assign` | `AssignRequest` | `AiActionChange` | precondition_failed | yes | `write:approval` | none | no |

### 8.19 Replay / paper trading
| # | Method | Path | Request | Response | Errors | Idem | Scope | Approval | Live-block |
| - | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 19.1 | GET | `/replay/runs` | filters | `Page<ReplayRun>` | — | n/a | `read:lineage` | none | no |
| 19.2 | POST | `/replay/runs` | `ReplayRunRequest` | `ReplayRun` | validation, dependency_unavailable | yes | `write:paper` | L2 | no |
| 19.3 | POST | `/replay/runs/{id}:cancel` | empty | `ReplayRun` | precondition_failed | yes | `write:paper` | L2 | no |
| 19.4 | GET | `/replay/runs/{id}/result` | — | `ReplayResult` | not_found | n/a | `read:lineage` | none | no |
| 19.5 | GET | `/paper/trades` | filters+lineage | `Page<PaperTrade>` | — | n/a | `read:lineage` | none | no |
| 19.6 | GET | `/paper/positions` | filters | `Page<PaperPosition>` | — | n/a | `read:lineage` | none | no |
| 19.7 | GET | `/paper/pnl` | filters | `PnlReport` | — | n/a | `read:lineage` | none | no |

### 8.20 Live readiness
| # | Method | Path | Request | Response | Errors | Idem | Scope | Approval | Live-block |
| - | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 20.1 | GET | `/live/readiness/state` | — | `LiveReadinessState` | — | n/a | `read:monitor` | none | no |
| 20.2 | GET | `/live/readiness/gates` | — | `List<LiveReadinessGate>` | — | n/a | `read:monitor` | none | no |
| 20.3 | POST | `/live/readiness/gates/{id}:probe` | empty | `LiveReadinessGate` | dependency_timeout | yes | `system:monitor` or `admin` | L1 | no |
| 20.4 | PUT | `/live/readiness/gates/{id}/state` | `GateStatePropose` | `LiveReadinessGate` | precondition_failed, approval_required, live_blocked | yes | `write:live_gate` | L4 (proposal) / L5 (`live_enabled=true`) | **yes** for L5 |
| 20.5 | POST | `/live/readiness:dry_run` | `DryRunRequest` | `LiveReadinessDryRun` | validation | yes | `write:live_gate` | L2 | no |
| 20.6 | POST | `/live/readiness:enable` | `EnableLiveRequest` (requires `X-Live-Confirm`) | `LiveReadinessState` | live_blocked, approval_state_invalid | yes | `write:live_gate` | L5 | **yes** |
| 20.7 | POST | `/live/readiness:disable` | empty | `LiveReadinessState` | — | yes | `write:kill_switch` | L4 | no |

---

## 9. Schema deltas (concrete shapes)

The architecture file `05_API_CONTRACTS.md` only listed group names and three property hints. The deltas below specify the structured payloads required by the matrix above. All field names align with `02_DOMAIN_MODEL_AND_CORE_ENTITIES.md` and `03_DATABASE_SCHEMA.md`.

### 9.1 `Identity` / `Session`

```json
// Identity
{
  "schema_version": "1.0.0",
  "user_id": "uuid-v7",
  "username": "string",
  "roles": ["viewer|operator|admin|security_admin|live_admin|system"],
  "scopes": ["read:public", "..."],
  "mfa_state": "disabled|enrolled|verified",
  "session_id": "uuid-v7",
  "session_expires_ts_ms": 1735689700000
}
```

### 9.2 `UniverseProposal` / `UniverseVersion`

```json
// UniverseProposal (request body inside envelope.payload)
{
  "schema_version": "1.0.0",
  "version_label": "string",
  "change_set": [
    {
      "op": "add|remove|update",
      "layer": "available|observed|training|trading",
      "exchange_symbol_id": "uuid-v7",
      "before": {"train_enabled": false, "trade_enabled": false, "paper_only": true, "live_allowed": false},
      "after":  {"train_enabled": true,  "trade_enabled": true,  "paper_only": true, "live_allowed": false},
      "manual_override_state": "none|proposed|approved",
      "override_reason": "string|null"
    }
  ],
  "rationale": "string",
  "evidence_pointers": [{"kind": "monitor_snapshot", "ref": "..."}]
}
```

```json
// UniverseVersion (response)
{
  "schema_version": "1.0.0",
  "universe_version_id": "uuid-v7",
  "version": "string",
  "state": "proposed|validated|approved|applied|verified",
  "resource_version": "etag-string",
  "change_set_json": [/* as above */],
  "requested_by": "user_id",
  "approved_by": "user_id|null",
  "applied_ts_ms": 1735689600400,
  "created_ts_ms": 1735689600100,
  "audit": { "audit_event_id": "uuid-v7", "change_id": "uuid-v7" }
}
```

### 9.3 `OverrideProposal` / `SymbolOverride`

```json
// OverrideProposal
{
  "schema_version": "1.0.0",
  "exchange_symbol_id": "uuid-v7",
  "override_type": "trade_enable|trade_disable|live_allow|live_block|paper_only|score_freeze",
  "before_value": { "trade_enabled": false },
  "after_value":  { "trade_enabled": true },
  "rollback_value": { "trade_enabled": false },
  "risk_level": "L2|L3|L4|L5",
  "reason": "string",
  "evidence_pointers": [{"kind": "log", "ref": "..."}]
}
```

### 9.4 `FeatureSnapshot` / `FeatureValue` / `FreshnessReport`

```json
// FeatureSnapshot
{
  "schema_version": "1.0.0",
  "feature_snapshot_id": "uuid-v7",
  "symbol": "BTCUSDT",
  "timeframe": "1m|5m|15m|1h|...",
  "model_checkpoint": "string",
  "source_refs": [{"source_key": "string", "ref": "string"}],
  "freshness": {
    "max_age_ms": 60000,
    "stale_count": 0,
    "missing_count": 0
  },
  "feature_values": [
    {
      "feature_value_id": "uuid-v7",
      "feature_name": "string",
      "feature_value": "string-decimal-or-json",
      "source_key": "string",
      "freshness_age_ms": 1234,
      "stale_flag": false,
      "missing_flag": false,
      "unused_flag": false
    }
  ],
  "created_ts_ms": 1735689600200
}
```

### 9.5 `PredictionEvent` + `PredictionExplain`

```json
// PredictionEvent
{
  "schema_version": "1.0.0",
  "prediction_id": "uuid-v7",
  "feature_snapshot_id": "uuid-v7",
  "symbol": "BTCUSDT",
  "timeframe": "1m",
  "model_version": "string",
  "checkpoint": "string",
  "raw_output": { /* model-specific */ },
  "lineage": {
    "feature_snapshot_id": "uuid-v7",
    "prediction_id": "uuid-v7",
    "signal_id": null,
    "decision_id": null,
    "risk_decision_id": null,
    "execution_intent_id": null,
    "lineage_gap_reason": "downstream_not_yet_emitted"
  },
  "created_ts_ms": 1735689600250
}
```

```json
// PredictionExplain
{
  "schema_version": "1.0.0",
  "prediction_id": "uuid-v7",
  "feature_snapshot": { /* full FeatureSnapshot */ },
  "feature_freshness": { /* FreshnessReport */ },
  "raw_model_output": { },
  "confidence_before": "0.6231",
  "confidence_after":  "0.5984",
  "top_positive": [{"feature_name": "x", "contribution": "0.12"}],
  "top_negative": [{"feature_name": "y", "contribution": "-0.07"}],
  "model_version": "string",
  "checkpoint": "string",
  "config_version_id": "uuid-v7",
  "missing_evidence": ["string"]
}
```

### 9.6 `SignalEvent` + `SignalExplain`

```json
// SignalEvent
{
  "schema_version": "1.0.0",
  "signal_id": "uuid-v7",
  "prediction_id": "uuid-v7",
  "symbol": "BTCUSDT",
  "action": "long|short|flat|exit",
  "confidence": "0.5984",
  "reason": { "policy": "string", "components": [/* */] },
  "lineage": { /* full lineage chain */ },
  "created_ts_ms": 1735689600300
}
```

```json
// SignalExplain
{
  "schema_version": "1.0.0",
  "signal_id": "uuid-v7",
  "prediction": { /* PredictionEvent */ },
  "confidence": { /* ConfidenceEvent fields */ },
  "orchestrator_reason": "string|null",
  "risk_gateway_reason": "string|null",
  "config_version_id": "uuid-v7",
  "logs_refs": [{"kind": "log", "ref": "string"}],
  "redis_refs": [{"kind": "redis", "ref": "v2:..."}],
  "missing_evidence": ["string"]
}
```

### 9.7 `OrchestratorDecision` / `PolicyTrace`

```json
{
  "schema_version": "1.0.0",
  "decision_id": "uuid-v7",
  "signal_id": "uuid-v7",
  "decision_action": "propose|skip|hold",
  "decision_reason": "string",
  "policy_trace": [
    { "policy_name": "string", "result": "pass|fail|n/a", "evidence_pointers": [] }
  ],
  "lineage": { /* */ },
  "created_ts_ms": 1735689600350
}
```

### 9.8 `RiskDecision` / `RiskPolicyBundle`

```json
// RiskDecision
{
  "schema_version": "1.0.0",
  "risk_decision_id": "uuid-v7",
  "decision_id": "uuid-v7",
  "allow_block": "allow|block",
  "block_reason": "string|null",
  "policy_checks": [
    {
      "policy_name": "stale_signal|missing_attribution|duplicate|leverage|stop|loss_cap|kill_switch|sizing|reduce_only|live_gate",
      "result": "pass|fail|n/a",
      "details": {}
    }
  ],
  "lineage": { /* */ },
  "created_ts_ms": 1735689600400
}
```

```json
// RiskPolicyBundle
{
  "schema_version": "1.0.0",
  "resource_version": "etag-string",
  "stale_signal_max_age_ms": 5000,
  "duplicate_window_ms": 1000,
  "leverage_cap": "5",
  "margin_mode": "ISOLATED|CROSS",
  "stop_policy": { "mandatory": true, "min_distance_pct": "0.4" },
  "loss_cap": { "daily_pct": "2.0", "weekly_pct": "5.0" },
  "kill_switch": { "armed": true, "trip_thresholds": {} },
  "sizing": { "max_position_pct": "1.0" },
  "reduce_only_required": true,
  "live_enabled": false
}
```

### 9.9 `IntentRequest` / `ExecutionIntent`

```json
// IntentRequest
{
  "schema_version": "1.0.0",
  "trader_id": "uuid-v7",
  "risk_decision_id": "uuid-v7",
  "intent_action": "open_long|open_short|reduce|close|exit",
  "size": "string-decimal",
  "price_hint": "string-decimal|null",
  "reduce_only": true,
  "mode": "paper|live",
  "lineage": { /* must include risk_decision_id */ }
}
```

```json
// ExecutionIntent
{
  "schema_version": "1.0.0",
  "execution_intent_id": "uuid-v7",
  "risk_decision_id": "uuid-v7",
  "trader_id": "uuid-v7",
  "intent_action": "...",
  "mode": "paper|live",
  "status": "queued|sent|filled|partial|rejected|canceled",
  "lineage": { /* full chain */ },
  "created_ts_ms": 1735689600450,
  "executed_ts_ms": 1735689600600
}
```

### 9.10 `TraderInstance`

```json
{
  "schema_version": "1.0.0",
  "trader_id": "uuid-v7",
  "account_id": "uuid-v7",
  "exchange_id": "uuid-v7",
  "strategy_profile": "string",
  "symbol_scope": [{"exchange_symbol_id": "uuid-v7", "weight": "0.25"}],
  "risk_profile": { /* subset of RiskPolicyBundle */ },
  "paper_live_mode": "paper|live",
  "heartbeat_ts_ms": 1735689600500,
  "pnl": { "daily": "0.0", "weekly": "0.0", "lifetime": "0.0" },
  "attribution_completeness": "0.97",
  "status": "running|paused|degraded|stopped",
  "resource_version": "etag-string"
}
```

### 9.11 `AuditEvent` / `AiActionChange`

```json
// AuditEvent
{
  "schema_version": "1.0.0",
  "audit_event_id": "uuid-v7",
  "actor_type": "human|claude|codex|ollama|system",
  "actor_id": "string",
  "action": "string",
  "resource_type": "string",
  "resource_id": "string",
  "before": {},
  "after": {},
  "reason": "string",
  "evidence_pointers": [],
  "approval_state": "not_required|pending|approved|rejected",
  "created_ts_ms": 1735689600550
}
```

```json
// AiActionChange (governance proposal)
{
  "schema_version": "1.0.0",
  "change_id": "uuid-v7",
  "actor": "claude|codex|ollama|human|system",
  "risk_level": "L0|L1|L2|L3|L4|L5",
  "reason": "string",
  "evidence_pointers": [],
  "before_value": {},
  "after_value": {},
  "validation_result": { "passed": true, "checks": [] },
  "rollback_plan": "string",
  "gui_explanation": "string",
  "approval_state": "pending|approved|rejected|withdrawn",
  "created_ts_ms": 1735689600600
}
```

### 9.12 `ConfigProposal` / `ConfigVersion`

```json
// ConfigProposal
{
  "schema_version": "1.0.0",
  "scope": "trainer|orchestrator|risk|strategy|exchange|monitor|live",
  "version_label": "string",
  "diff": [
    { "path": "json.pointer", "op": "add|replace|remove", "before": null, "after": "string" }
  ],
  "rationale": "string",
  "evidence_pointers": []
}
```

### 9.13 `MonitorSnapshot` / `EvidencePacket`

```json
// MonitorSnapshot
{
  "schema_version": "1.0.0",
  "monitor_snapshot_id": "uuid-v7",
  "source": "monitor_center|trainer|orchestrator|risk|adapter",
  "snapshot": {
    "monitors": [
      {
        "monitor_name": "string",
        "owner": "string",
        "script_path": "string",
        "status": "active|broken|unused|duplicate|unknown",
        "last_run_ts_ms": 0,
        "last_success_ts_ms": 0,
        "last_failure_ts_ms": 0,
        "metrics": {},
        "redis_keys_watched": [],
        "logs_watched": [],
        "processes_watched": [],
        "alerts_generated": []
      }
    ],
    "trainer_prediction_stream_health": "ok|degraded|stale",
    "price_prediction_accuracy": "0.0",
    "signal_causality": "ok|broken",
    "feature_freshness": "ok|stale",
    "model_health": "ok|degraded",
    "risk_gate_status": "ok|degraded|tripped",
    "execution_latency_p95_ms": 0,
    "claude_supervision_health": "ok|degraded",
    "ollama_summarization_health": "ok|degraded",
    "codex_review_status": "ok|pending|failed"
  },
  "liveness_status": "ok|degraded|down",
  "created_ts_ms": 1735689600650
}
```

```json
// EvidencePacket
{
  "schema_version": "1.0.0",
  "evidence_packet_id": "uuid-v7",
  "packet_type": "hourly|daily|alert|claude|codex|ollama",
  "packet": {
    "claims": [
      {
        "claim": "string",
        "raw_evidence_pointer": [{"kind": "log|redis|db|file|cmd|config", "ref": "string"}],
        "verification_command": "string",
        "confidence": "low|medium|high",
        "missing_evidence": "string|null"
      }
    ],
    "summary": "string"
  },
  "related_snapshot_id": "uuid-v7|null",
  "created_ts_ms": 1735689600700
}
```

### 9.14 `LiveReadinessState` / `LiveReadinessGate`

```json
{
  "schema_version": "1.0.0",
  "state": "blocked|ready|tripped|disabled",
  "as_of_ts_ms": 1735689600800,
  "gates": [
    {
      "id": "monitor_completeness|risk_policy_signoff|kill_switch_armed|approval_workflow_active|human_confirmation_present|exchange_connector_health|attribution_complete|paper_track_record",
      "state": "pass|fail|unknown",
      "evidence_pointers": [],
      "last_probed_ts_ms": 0,
      "resource_version": "etag-string"
    }
  ],
  "x_live_confirm_required": true,
  "required_actor_type": "human",
  "required_approval_level": "L5"
}
```

### 9.15 Pagination wrapper

```json
{
  "items": [/* T */],
  "page": {
    "next_cursor": "opaque|null",
    "prev_cursor": "opaque|null",
    "approx_total": 12345,
    "limit": 100,
    "applied_filters": { },
    "applied_sort": "created_ts_ms:desc"
  }
}
```

---

## 10. Traceability — Codex gaps closed

| Codex gap (from `04_API_CONTRACT_REVIEW.md`) | Closed by section |
| --- | --- |
| 1. No endpoint inventory (path + method per group) | §8 (matrix for all 20 groups) |
| 2. No request/response schemas per endpoint, including required lineage fields | §1.4 + §9 (concrete shapes, lineage chain mandatory) |
| 3. No error model by status code/class | §3 (envelope + 12-class catalog) |
| 4. No idempotency model for mutable routes | §4 (mandatory `X-Idempotency-Key`, replay/conflict semantics) |
| 5. No concurrency contract (version preconditions / optimistic locking) | §5 (`If-Match` + `resource_version` + state machine) |
| 6. No pagination/filtering/sorting contract for high-volume event feeds | §6 (cursor pagination, filter grammar, sort grammar, mandatory feeds list) |
| 7. No route-level RBAC scope matrix | §2 + §8 (scope tokens + per-route binding) |
| 8. No deterministic live-block response envelope for blocked mutation calls | §7 (canonical 423 envelope, 5-condition lift policy) |

Additional remediation beyond the eight required items:
- AI-governance routes explicitly enforce `actor.actor_type != "human"` rejection at L5 (§2.3).
- All adapter ingress routes are scoped to `system:adapter` / `system:monitor` to prevent confused-deputy with operator scopes (§2.2, §8.7, §8.8, §8.15).
- Default-deny posture is encoded in routing rules (§1.5) so unspecified routes fail closed.

---

## 11. Gate recommendation

This remediation supplies endpoint matrices, request/response schemas, error catalog, idempotency, optimistic concurrency, pagination, route-level RBAC, and live-block envelope. With this document accepted, the API contract layer is **scaffold-ready** at the architecture tier. Final acceptance still requires:

- Codex re-review of this remediation document (next gate).
- Integration into `claude_worklog/v2_architecture/05_API_CONTRACTS.md` as the authoritative replacement / appendix.
- Live-trading routes remain **BLOCKED** by default per `CLAUDE.md`; nothing in this document enables execution.

Recommended provisional decision: **CONDITIONAL PASS pending Codex re-review of this remediation file**.