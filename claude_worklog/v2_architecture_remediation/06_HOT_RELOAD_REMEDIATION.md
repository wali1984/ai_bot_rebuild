```markdown
# 06 Hot-Reload Remediation

## Status
- Source blocker: actual Codex CLI architecture review, `claude_worklog/v2_architecture_codex_review/12_ACTUAL_CODEX_CLI_ARCHITECTURE_REVIEW_OUTPUT.md`, **Blocker 5** — *"Hot-reload persistence is missing. Requirements require component-wise ack status, missing-ack escalation, validation results, post-apply health checks, and rollback evidence per universe update. DB architecture only has `universe_versions` and `universe_members`; no durable per-component rollout/ack/evidence model is specified."*
- Reconciled in `claude_worklog/v2_architecture_codex_review/13_ACTUAL_CODEX_RECONCILIATION.md`, consolidated blocker **#5**.
- Provisional blocker reference: `claude_worklog/v2_architecture_codex_review/06_DYNAMIC_UNIVERSE_HOT_RELOAD_REVIEW.md` adversarial findings 1 (ack reliability contract incomplete) and 2 (partial-apply behavior not formally constrained).
- Architecture file under remediation: `claude_worklog/v2_architecture/08_HOT_RELOAD_PIPELINE_ARCHITECTURE.md` (current text is a 45-line stub that names the state flow `proposed→validated→approved→applied→verified`, lists eight propagation targets, and names ack envelope fields, but does not define ack timeouts, retry policy, dead-letter escalation, quorum rules, partial-apply semantics, rollback trigger thresholds, post-apply health-check contract, or per-component durable rollout persistence).
- Companion remediation files this document references:
  - `04_API_CONTRACT_REMEDIATION.md` — defines the route surface for `POST /universe/proposals`, `POST /universe/proposals/{id}/approve`, `POST /universe/versions/{ver}/apply`, `POST /universe/versions/{ver}/rollback`, the standard error envelope, idempotency contract, optimistic concurrency, evidence-pointer envelope, and live-block posture this document references.
  - `05_RISK_GATEWAY_REMEDIATION.md` — defines policy bundle versioning and the kill-switch persistence/state machine that this document parallels for hot-reload rollout state.
- This document does **not** ship V2 code, does not write Redis, does not place or cancel any exchange instructions, does not modify the legacy runtime tree, and does not restart any service. It is an architecture-layer deliverable producing schemas, state machines, timeout/retry/quorum/rollback semantics, persistence requirements, and test-vector matrices that make hot-reload non-bypass and recoverable in scaffold tests.

## Read/write boundary compliance
Writes only to `./claude_worklog/v2_architecture_remediation/`. Does not edit `./legacy_reference/**` or the sibling legacy bot tree. No `.env`, no secrets, no Redis writes, no service restarts, no exchange actions. All examples are schema, state-machine, and timing-policy fragments — no executable runtime is created or modified. Live mutation routes referenced here remain blocked-by-default per `CLAUDE.md`; the contract encodes the block, it does not enable propagation against live systems.

## Scope of remediation
This file produces, in order:

1. Non-bypass invariants the architecture must enforce for hot-reload (the contract implementations are scored against).
2. Component registry contract (which components MUST ack, classified by criticality).
3. Universe update envelope (the immutable rollout object).
4. Per-component ack envelope (extending the architecture stub).
5. Ack timeout policy (tier-based deadlines with deterministic clock source).
6. Retry policy (exponential backoff, idempotency keys, ceiling, dead-letter).
7. Quorum semantics (per-component-class minimum-applied requirement).
8. Partial-failure handling (mixed-state resolution rules).
9. Rollback trigger thresholds (six explicit triggers, all auto-arming).
10. Rollback state machine (rollback-target selection, rollback ack contract, terminal states).
11. Post-apply health-check contract (windows, metrics, failure semantics).
12. Durable persistence tables (`universe_rollouts`, `universe_rollout_components`, `universe_rollout_health`, `universe_rollouts_audit`).
13. Hot-reload event envelope (`universe_rollout_event`) with full lineage and rollout trace.
14. Override-conflict deterministic precedence (closes review finding 4).
15. Selection-policy version pinning requirement (closes review finding 3).
16. Test-vector matrix that any scaffold implementation MUST pass before V2 build clears Blocker 5.
17. Audit / evidence-packet requirements.
18. Traceability table mapping every sub-claim of Codex Blocker 5 to the section that closes it.
19. Gate recommendation.

---

## 1. Non-bypass invariants (the contract hot-reload is judged against)

These are the architectural invariants every hot-reload implementation MUST satisfy. They are restated as machine-checkable statements so scaffold tests can assert them directly.

| ID | Invariant | Assertion form |
| --- | --- | --- |
| HR-INV-01 | No `universe_version` may transition from `approved` to `applied` without a `universe_rollouts` row whose `quorum_status = 'satisfied'` and whose per-component `ack_status` set satisfies the quorum rule of §7. | DB CHECK + service-layer guard. Nightly assertion `SELECT COUNT(*) FROM universe_versions uv JOIN universe_rollouts ur ON ur.universe_version=uv.universe_version WHERE uv.state='applied' AND ur.quorum_status<>'satisfied'` MUST be 0. |
| HR-INV-02 | Every component listed in the component registry (§2) MUST emit an ack of one of `{applied, validation_failed, health_failed, timeout, refused}` for every `universe_rollout_id` it is targeted by. No silent drop is permitted. | `universe_rollout_components.ack_status IS NOT NULL OR escalation_state='dead_letter'` for every (rollout, component) pair after `escalation_deadline_ts_ms`. |
| HR-INV-03 | Hot-reload state is deterministic given `(universe_version, rollout_id, component_registry_version, ack_timeout_policy_version, retry_policy_version, quorum_policy_version, rollback_policy_version)`. Re-evaluation of the same recorded acks MUST produce the byte-identical rollout terminal state. | Re-evaluation harness produces same `quorum_status`, same `partial_state_resolution`, same `rollback_triggered` boolean, same `rollback_reason_code`. |
| HR-INV-04 | Every rollout MUST persist a rollback target (the prior `verified` `universe_version`) at rollout-start time. The rollback target cannot be recomputed at rollback-trigger time. | `universe_rollouts.rollback_target_version IS NOT NULL` at row creation. DB trigger rejects NULL. |
| HR-INV-05 | A rollout in `rolling_back` state cannot accept new component ack messages for the original target version; it only accepts acks for the rollback target version. | Service-layer guard rejects acks whose `applied_version` does not match the active rollback target. |
| HR-INV-06 | Rollback is versioned: the rollback itself produces a new `universe_rollout_id` and a new audit chain entry, never an in-place mutation of the original rollout row. | DB CHECK: `universe_rollouts.rollout_kind IN ('forward','rollback')`; rollback rows reference `parent_rollout_id`. |
| HR-INV-07 | Critical-tier components (§2) failing to ack within the timeout (§5) MUST auto-arm a rollback evaluation; non-critical components failing to ack MUST escalate to dead-letter and surface to operators but MUST NOT alone trigger rollback. | State-machine assertion in §10. |
| HR-INV-08 | Hot-reload events MUST never bypass the Risk Gateway live-block contract: any rollout that would change live-trading-affecting parameters (per §6 `live_affecting=true`) requires the same approval level (L4/L5) as a Risk Policy bundle change (companion `05_RISK_GATEWAY_REMEDIATION.md`). | Service-layer guard rejects `apply` on a rollout whose `live_affecting=true` and missing required approval row. |
| HR-INV-09 | The default state of every newly provisioned hot-reload coordinator instance is `accepting_proposals=false`, `accepting_applies=false` until the component registry version (§2) and policy versions (§5–§9) are loaded. Until then, the coordinator emits `universe_rollout_event.state='blocked_no_policy'` for any rollout request. | Boot test asserts default behavior. |
| HR-INV-10 | Every `universe_rollout_event` carries the lineage tuple `(universe_version, parent_universe_version, rollout_id, parent_rollout_id|null, change_set_hash, proposal_id, approval_chain_ids, component_registry_version, ack_timeout_policy_version, retry_policy_version, quorum_policy_version, rollback_policy_version)`. Missing upstream IDs are explicit `null` with `lineage_gap_reason`. | Companion of `04_API_CONTRACT_REMEDIATION.md §1.4`. |
| HR-INV-11 | Hot-reload coordinator never mutates legacy systems, never edits old Redis keys, never restarts the legacy trainer. Every coordinator action targets the V2 namespace only. | Static config: `REDIS_PREFIX = "v2:"`, no write paths to legacy keys; CI grep for legacy key prefixes in coordinator source. |
| HR-INV-12 | Non-bypass holds across all execution paths: paper, replay, simulator, live. The mode flag (`paper|live`) MUST NOT branch around the rollout coordinator; only specific approvals (e.g., live-affecting L4) condition on mode. | Static check: the only call-site for component reconfiguration is the rollout coordinator's apply path; components reject reconfiguration messages whose `universe_rollout_id` is missing or whose `rollout_state` is not `applying`. |

---

## 2. Component registry contract (who MUST ack, and how critical)

The hot-reload coordinator never broadcasts to "loose" subscribers. It applies a rollout to a single **component registry** identified by `component_registry_version`. The registry is the unit of approval, deploy, and replay.

### 2.1 Registry envelope

```json
{
  "schema_version": "1.0.0",
  "component_registry_id": "uuid-v7",
  "component_registry_version": "2026.04.30-001",
  "registry_hash": "sha256:<hex>",
  "created_by": {
    "actor_type": "human|claude|codex|ollama|system",
    "actor_id": "string"
  },
  "approvals": [
    {
      "approval_id": "uuid-v7",
      "approver_user_id": "string",
      "required_level": "L3",
      "decision": "approved",
      "decision_ts_ms": 1735689600000
    }
  ],
  "components": [ /* see §2.2 */ ]
}
```

A registry-version bump is required to add, remove, or reclassify any component. Reclassification (e.g., changing a `tier` or `live_affecting` value) bumps the registry-version and re-runs the L3 approval pass. The current active registry-version is single-valued globally (no two registries are concurrently active).

### 2.2 Component classification

Every component is classified by **tier**, **liveness affinity**, and **ack channel**. The tier governs ack timeout (§5), retry ceiling (§6), and quorum requirement (§7); the liveness affinity governs rollback trigger eligibility (§9); the ack channel governs the transport contract.

| component_id | role | tier | liveness affinity | live_affecting | ack channel |
| --- | --- | --- | --- | --- | --- |
| `ingestor` | passive market discovery / candle ingest | T1-CRITICAL | hot-path | true | `ack.universe.ingestor` |
| `feature_pipeline` | feature build + freshness publication | T1-CRITICAL | hot-path | true | `ack.universe.feature_pipeline` |
| `trainer_adapter` | subprocess boundary to legacy trainer | T1-CRITICAL | hot-path | true | `ack.universe.trainer_adapter` |
| `orchestrator` | proposes/coordinates per `12_RISK_GATEWAY_ARCHITECTURE.md` | T1-CRITICAL | hot-path | true | `ack.universe.orchestrator` |
| `risk_gateway` | final-authority validator | T1-CRITICAL | hot-path | true | `ack.universe.risk_gateway` |
| `executor` | post-allow execution dispatcher | T1-CRITICAL | hot-path | true | `ack.universe.executor` |
| `connector_<exchange>` | exchange adapter (per exchange) | T1-CRITICAL | hot-path | true | `ack.universe.connector.<exchange>` |
| `trader_<id>` | per-trader fleet member | T2-IMPORTANT | warm-path | true | `ack.universe.trader.<id>` |
| `monitor_center` | live monitoring + evidence packets | T2-IMPORTANT | warm-path | false | `ack.universe.monitor_center` |
| `audit_ledger` | append-only audit consumer | T2-IMPORTANT | warm-path | false | `ack.universe.audit_ledger` |
| `gui_backend` | FastAPI control plane | T3-INFORMATIONAL | cold-path | false | `ack.universe.gui_backend` |
| `gui_frontend` | web/PWA client (SSE/websocket) | T3-INFORMATIONAL | cold-path | false | `ack.universe.gui_frontend` |
| `claude_admin_ai` | local Claude assistant | T3-INFORMATIONAL | cold-path | false | `ack.universe.claude_admin_ai` |
| `ollama_assistant` | Ollama summarizer | T3-INFORMATIONAL | cold-path | false | `ack.universe.ollama_assistant` |
| `codex_review_center` | Codex review surface | T3-INFORMATIONAL | cold-path | false | `ack.universe.codex_review_center` |

Tier definitions:
- **T1-CRITICAL** — ack failure or health failure on this component is an absolute rollback trigger when the rollout is `live_affecting=true` and the component is on the live path. Rollback cannot be skipped by operator override below L4.
- **T2-IMPORTANT** — ack failure escalates to operator and counts against the `applied`-fraction quorum (§7). Rollback may be triggered if the cumulative T2 failure ratio crosses the §9 threshold.
- **T3-INFORMATIONAL** — ack failure is recorded as `degraded` but does not by itself trigger rollback. Operators may force rollback manually.

The registry MUST list every consumer of universe state. Adding a new consumer without a registry-version bump is an HR-INV-02 violation; CI MUST grep coordinator and consumer source to enforce parity (every code path that subscribes to a universe topic MUST resolve to a `component_id` present in the active registry).

---

## 3. Universe update envelope (the immutable rollout object)

A rollout is uniquely identified by `universe_rollout_id` and pins every policy version it depends on, so it is replayable byte-identically.

```json
{
  "schema_version": "1.0.0",
  "universe_rollout_id": "uuid-v7",
  "rollout_kind": "forward|rollback",
  "parent_rollout_id": "uuid-v7|null",
  "universe_version": "2026.04.30-009",
  "parent_universe_version": "2026.04.30-008",
  "rollback_target_version": "2026.04.30-008",
  "change_set_hash": "sha256:<hex>",
  "live_affecting": true,
  "selection_policy_version": "2026.04.20-003",
  "capacity_policy_version": "2026.04.18-001",
  "score_policy_version": "2026.04.20-002",
  "component_registry_version": "2026.04.30-001",
  "ack_timeout_policy_version": "2026.04.30-001",
  "retry_policy_version": "2026.04.30-001",
  "quorum_policy_version": "2026.04.30-001",
  "rollback_policy_version": "2026.04.30-001",
  "approval_chain": [
    {"approval_id": "uuid-v7", "level": "L4", "approver_user_id": "string", "decision_ts_ms": 1735689600000}
  ],
  "proposal_id": "uuid-v7",
  "evidence_pointers": [
    {"kind": "redis|log|db|file|monitor_snapshot|evidence_packet", "ref": "string"}
  ],
  "rollout_started_ts_ms": 1735689600000,
  "rollout_deadline_ts_ms": 1735689660000,
  "lineage": { /* see HR-INV-10 */ }
}
```

Required fields:
- `live_affecting=true` triggers L4 approval per HR-INV-08; `live_affecting=false` requires L3.
- `rollback_target_version` is captured at row insert (HR-INV-04). It MAY NOT be recomputed; if no prior `verified` version exists, the rollout is rejected with `error_code=NO_ROLLBACK_TARGET` and the system stays at proposal stage.
- `selection_policy_version`, `capacity_policy_version`, and `score_policy_version` close review finding 3 (selection-policy version pinning).

---

## 4. Per-component ack envelope (extending the architecture stub)

The `08_HOT_RELOAD_PIPELINE_ARCHITECTURE.md` stub names five ack fields. The full enforceable envelope is below.

```json
{
  "schema_version": "1.0.0",
  "ack_id": "uuid-v7",
  "universe_rollout_id": "uuid-v7",
  "component_id": "string",
  "component_instance_id": "string",
  "applied_version": "2026.04.30-009",
  "ack_status": "applied|validation_failed|health_failed|timeout|refused|partial",
  "ack_reason_code": "string|null",
  "ack_reason_detail": "string|null",
  "ack_ts_ms": 1735689601000,
  "component_clock_skew_ms": 12,
  "validation_results": [
    {"check_id": "string", "status": "pass|fail", "detail": "string"}
  ],
  "post_apply_health": {
    "window_start_ts_ms": 1735689601000,
    "window_end_ts_ms": 1735689631000,
    "metrics": [
      {"metric_id": "string", "value": "string-decimal", "threshold": "string-decimal", "status": "pass|fail|stale"}
    ]
  },
  "rollback_ready": true,
  "rollback_target_version": "2026.04.30-008",
  "lineage": { /* see HR-INV-10 */ }
}
```

Rules:
- `ack_status='partial'` is permitted only for components that wrap multiple instances (e.g., `trader_<id>` rolled across N traders). It MUST also include a `partial` breakdown listing which sub-instances are `applied` and which are not. `partial` is treated as a failure for quorum (§7) unless the component's own sub-instance quorum passes its registry-declared sub-quorum.
- `applied_version` MUST equal `universe_rollout.universe_version` for forward rollouts and `universe_rollout.rollback_target_version` for rollback rollouts. Mismatch = automatic `ack_status='refused'` regardless of what the component claimed.
- `component_clock_skew_ms` is reported by the component vs the coordinator's authoritative clock; |skew| > 5_000 ms forces a re-handshake (the coordinator rejects acks with excessive skew because timeouts (§5) are computed against the coordinator clock, not the component clock).
- `rollback_ready=false` from a T1-CRITICAL component is itself an absolute rollback trigger (§9), because a critical component without rollback capability cannot satisfy HR-INV-04 going forward.

---

## 5. Ack timeout policy

### 5.1 Authoritative clock
All deadlines are computed against the coordinator's monotonic clock, captured at `rollout_started_ts_ms` on the row. Component clocks are advisory and used only for skew reporting (§4). NTP drift is irrelevant to deadline math.

### 5.2 Timeout matrix

| tier | first-ack deadline (after `apply_dispatched_ts_ms`) | full-applied deadline | post-apply health window |
| --- | --- | --- | --- |
| T1-CRITICAL | 5_000 ms | 30_000 ms | 60_000 ms |
| T2-IMPORTANT | 15_000 ms | 90_000 ms | 180_000 ms |
| T3-INFORMATIONAL | 30_000 ms | 300_000 ms | n/a (no rollback contribution) |

Definitions:
- **first-ack deadline** — interval within which the coordinator MUST receive any ack (`applied`, `validation_failed`, `health_failed`, or `refused`). Silence past this deadline = treated as `ack_status='timeout'` virtual ack and triggers retry (§6).
- **full-applied deadline** — interval within which the component MUST reach `ack_status='applied'` with `post_apply_health` populated. Failure to reach `applied` by this deadline = terminal `timeout` for that (rollout, component) pair after the retry ceiling (§6) is exhausted.
- **post-apply health window** — additional window during which `post_apply_health` metrics are required to remain `pass`. A flip from `pass` to `fail` inside this window is a §9 rollback trigger.

### 5.3 Deadlines persist across coordinator restart
Deadlines are stored on the `universe_rollout_components` row (§12). Coordinator restart does NOT extend deadlines — on boot, the coordinator re-evaluates every active rollout and any deadline already passed in coordinator-clock terms is treated as expired. This prevents using restart as a way to silently extend timeouts.

### 5.4 Policy version pinning
The timeout matrix is captured by `ack_timeout_policy_version`. Modifying any cell requires a new policy version through L3 approval. The rollout row pins the policy version it was started against, so re-evaluation of historical rollouts uses the matrix that was in force at start time.

---

## 6. Retry policy

### 6.1 Idempotency contract
Every `apply` dispatch carries `(universe_rollout_id, component_id, attempt_number, idempotency_key)`. Components MUST treat repeat dispatches with the same `idempotency_key` as duplicates; they re-emit the prior ack rather than re-applying. The coordinator persists the canonical `idempotency_key = sha256(universe_rollout_id || component_id || attempt_number)`.

### 6.2 Retry schedule

| tier | base delay | growth | max attempts | total wallclock ceiling |
| --- | --- | --- | --- | --- |
| T1-CRITICAL | 1_000 ms | exponential ×2, jitter ±20% | 3 | bounded by full-applied deadline (30_000 ms) |
| T2-IMPORTANT | 5_000 ms | exponential ×2, jitter ±20% | 4 | bounded by full-applied deadline (90_000 ms) |
| T3-INFORMATIONAL | 15_000 ms | exponential ×2, jitter ±20% | 5 | bounded by full-applied deadline (300_000 ms) |

Whichever bound (max attempts OR wallclock ceiling) is hit first is terminal. A retry is issued ONLY when the current ack is `timeout`, `validation_failed`, or `health_failed` AND the component's stated `ack_reason_code` is on the retryable allow-list (`transient_*`, `validation_input_stale`, `health_metric_stale`). `refused` is never retried (the component declined; coordinator escalates instead).

### 6.3 Dead-letter and escalation
On exhaustion (max attempts or wallclock ceiling), the (rollout, component) pair transitions to `escalation_state='dead_letter'`. This:
- writes a `universe_rollouts_audit` row with the full retry trace;
- emits a `universe_rollout_event.state='component_dead_letter'` event;
- pages the operator surface in `monitor_center` (which is itself a registry component, so its own dead-letter is detected separately and surfaces via the secondary alarm path);
- is evaluated by §9 to decide whether to auto-arm rollback.

The dead-letter state is durable and survives coordinator restart. Resuming a dead-lettered (rollout, component) pair requires explicit operator action through `POST /universe/rollouts/{id}/components/{component_id}/resume` which itself re-runs L3 approval.

### 6.4 Retry policy version pinning
The retry schedule is captured by `retry_policy_version`. Modifying any cell requires a new policy version through L3 approval. The rollout pins the policy version at start time (§3).

---

## 7. Quorum semantics

A rollout's `quorum_status` is one of `pending|satisfied|violated` and is recomputed every time a component ack is received OR a deadline expires.

### 7.1 Per-tier quorum requirements

| tier | required `applied` fraction | minimum absolute count |
| --- | --- | --- |
| T1-CRITICAL | 100% (every T1 component MUST be `applied`) | n/a (1.0 ratio) |
| T2-IMPORTANT | ≥ 80% | ≥ 1 |
| T3-INFORMATIONAL | ≥ 50% | n/a |

Rules:
- `quorum_status='satisfied'` iff all three tier rules are satisfied simultaneously AND no T1 component is in `dead_letter` AND no T1 component reports `rollback_ready=false`.
- `quorum_status='violated'` iff any T1 component is terminally `timeout`/`validation_failed`/`health_failed`/`refused`/`dead_letter`, OR T2 `applied` fraction falls below 80% with no further pending acks, OR T3 fraction falls below 50% with no further pending acks AND the rollout is `live_affecting=true` (T3 violations on `live_affecting=false` rollouts only mark the rollout `degraded`, not `violated`).
- `quorum_status='pending'` while any tier is still awaiting acks within its timeout windows.

### 7.2 Quorum is gated on `verified` transition
The state-machine transition `applied → verified` requires `quorum_status='satisfied'` AND the post-apply health window of every T1+T2 component to have closed `pass` (§11). Re-entering `verified` from `applying` is prohibited; once a rollout has been marked `verified` it is terminal-success and any new universe change requires a new `universe_version`.

### 7.3 Quorum policy version pinning
Quorum cells are captured by `quorum_policy_version`. Modifying any cell requires a new policy version through L4 approval (because tightening or loosening quorum directly changes live-trading-effect blast radius). The rollout pins the policy version at start time.

---

## 8. Partial-failure handling (mixed-state resolution)

Closes review finding 2 (partial-apply behavior not formally constrained).

### 8.1 Mixed-state rules

A rollout can produce a mixed state where some components are `applied` and others are not. The deterministic resolution rule is:

1. Evaluate quorum (§7). If `satisfied` and post-apply health is `pass`, the rollout is `verified` even if some T3 components are not yet `applied` — they continue to be retried within their full-applied deadline; on exhaustion they go to dead-letter without affecting the verified state.
2. If quorum is `violated` because of a T1 failure, **immediate rollback** is auto-armed (§9 trigger RBT-01).
3. If quorum is `violated` because of a T2 fraction below 80%, the rollout transitions to `partial_apply_quarantine`:
   - components currently `applied` are NOT instructed to roll back;
   - the universe state is functionally split: the coordinator marks `universe_versions.state='partial'`;
   - any execution path that depends on a non-`applied` T2 component is gated as if the component were in maintenance mode (read-through to prior `verified` configuration);
   - `partial_apply_quarantine` is a terminal-non-success state — it does not auto-recover. Operators MUST either:
     (a) approve a `forward-recovery` rollout that targets the same `universe_version` with a refreshed component subset (re-running approvals), OR
     (b) approve a `rollback` rollout to `rollback_target_version` (which itself runs as a new rollout under §10).
4. If quorum is `pending` past the rollout deadline (`rollout_deadline_ts_ms`), the rollout transitions to `stalled` and is treated as a §9 RBT-04 trigger.
5. T3 violations on `live_affecting=false` rollouts produce `degraded` not `partial_apply_quarantine`. `degraded` does not gate execution paths; it only marks the rollout's terminal evidence packet for operator review.

### 8.2 No silent overlap of universe versions on the live path
At any instant, every T1-CRITICAL component on the live path MUST be running the same `universe_version`. The coordinator enforces this by refusing to mark a rollout `verified` (§7.2) until every T1 component has acked the same `applied_version`. This rules out the dangerous mixed state where, for example, the orchestrator believes a symbol is in-universe but the executor still rejects it.

### 8.3 Explicit override conflict precedence (closes review finding 4)
Universe member states resolve in this fixed order, highest-priority first:
1. `force_disabled` (operator hard-exclude) — wins over everything below.
2. `manual_exclude` — wins over selection auto-include.
3. `force_train_only` (operator forces include but blocks live trading on this symbol) — wins over selection auto-trade.
4. `manual_include` — wins over selection auto-exclude.
5. `selection_auto` (selection-policy output).
6. `capacity_constraint` (lowest-priority — used as a tiebreak).

The rule "force_disabled wins over force_train_only" closes the explicit ambiguity called out in `06_DYNAMIC_UNIVERSE_HOT_RELOAD_REVIEW.md` finding 4. The precedence is captured by a `selection_policy_version` value and may not be reordered without a new policy version.

---

## 9. Rollback trigger thresholds

There are exactly six auto-arming rollback triggers. Each MUST be evaluated on every coordinator tick AND on every ack/health update. Triggers are not OR-merged silently — each fires its own `rollback_reason_code` so post-mortem is unambiguous.

| ID | Trigger | Threshold | Tier scope | Reason code |
| --- | --- | --- | --- | --- |
| RBT-01 | T1-CRITICAL component reaches terminal failure (`timeout`/`validation_failed`/`health_failed`/`refused`/`dead_letter` after retry exhaustion) on a `live_affecting=true` rollout. | any 1 occurrence | T1 only | `T1_CRITICAL_FAILURE` |
| RBT-02 | T2-IMPORTANT cumulative failure fraction ≥ 30% on a `live_affecting=true` rollout, OR ≥ 50% on `live_affecting=false`. | per-fraction | T2 only | `T2_FAILURE_FRACTION_EXCEEDED` |
| RBT-03 | Post-apply health metric for any T1+T2 component flips `pass→fail` inside the post-apply health window (§5.2). | any 1 occurrence | T1+T2 | `POST_APPLY_HEALTH_REGRESSION` |
| RBT-04 | Rollout exceeds `rollout_deadline_ts_ms` with `quorum_status='pending'`. | wallclock | global | `ROLLOUT_STALLED` |
| RBT-05 | T1-CRITICAL component reports `rollback_ready=false` at any time during `applying`. | any 1 occurrence | T1 only | `ROLLBACK_CAPABILITY_LOST` |
| RBT-06 | Risk Gateway emits a `risk_decision.allow_block='block'` whose `block_reason='hot_reload_state_inconsistent'` against a trader that the rollout is supposed to have already configured. | any 1 occurrence | global | `RISK_GATEWAY_BLOCKED_DUE_TO_INCONSISTENCY` |

### 9.1 Manual rollback
Operators may invoke rollback manually at any state via `POST /universe/rollouts/{id}/rollback` with reason `MANUAL_OPERATOR`. Manual rollback follows the same state machine (§10) and runs as a new rollout (HR-INV-06). Manual rollback on a `live_affecting=true` rollout requires L4; on `live_affecting=false` requires L3.

### 9.2 Rollback de-duplication
If multiple triggers fire within the same coordinator tick, the highest-priority one wins (RBT-01 > RBT-05 > RBT-03 > RBT-02 > RBT-06 > RBT-04 > MANUAL_OPERATOR). The losing triggers are still recorded on the audit row's `additional_triggers[]` so post-mortem sees the full picture, but only one rollback rollout is started.

### 9.3 Rollback policy version pinning
Trigger thresholds are captured by `rollback_policy_version`. Modifying any threshold requires a new policy version through L4 approval (because loosening rollback triggers directly affects live-trading blast radius).

---

## 10. Rollback state machine

```
forward_rollout_states:
  proposed -> validated -> approved -> applying -> verified
                                          |
                                          +-> partial_apply_quarantine (terminal-non-success)
                                          |
                                          +-> stalled (terminal-non-success, RBT-04)
                                          |
                                          +-> rolling_back -> rolled_back (terminal-success-of-rollback)
                                                            -> rollback_failed (terminal-failure, surfaces RBT-* + RB-FAIL)
```

### 10.1 Entering `rolling_back`
Triggered by any of RBT-01..RBT-06 or `MANUAL_OPERATOR`. On entry, the coordinator:
1. atomically transitions the original rollout row to `state='rolling_back'`;
2. inserts a NEW `universe_rollouts` row with `rollout_kind='rollback'`, `parent_rollout_id` pointing to the original, `universe_version=<rollback_target_version>`, `rollback_target_version=<rollback target's own prior version>`;
3. the new rollback rollout pins the SAME `component_registry_version`, `ack_timeout_policy_version`, `retry_policy_version`, `quorum_policy_version`, `rollback_policy_version` as the parent (so the rollback runs under the same rules);
4. dispatches the rollback `apply` to every component that previously acked `applied` on the parent. Components that never reached `applied` MUST NOT be sent rollback dispatch (they are already on the prior version);
5. emits `universe_rollout_event.state='rollback_started'` carrying the `rollback_reason_code` and `additional_triggers[]`.

### 10.2 Rollback acks
Components ack the rollback under the same envelope (§4) but `applied_version` MUST equal the rollback target. The coordinator validates this strictly (HR-INV-05).

### 10.3 Rollback quorum
Rollback uses the SAME quorum rules (§7) but the success target is "every T1+T2 component that previously acked `applied` on the parent has now acked `applied` on the rollback target." T3 components do not block rollback completion.

### 10.4 Terminal states
- `rolled_back` — every required component reverted, post-rollback health window closed `pass`. Universe state on the live path is the rollback target version. The original `universe_version` is marked `state='abandoned'` and is never retried in place; remediation requires a new `universe_version`.
- `rollback_failed` — at least one T1 component failed to revert within its retry ceiling. The system enters a hard-blocked posture: `accepting_applies=false`, `accepting_proposals=false`. Risk Gateway is signalled to flip `live_gate=blocked` (companion `05_RISK_GATEWAY_REMEDIATION.md`). Recovery requires explicit L5 operator action through a separate incident-recovery flow (out of scope of this document; produces a `rollback_failed` evidence packet that is the input to that flow).

### 10.5 No nested rollback
A rollback rollout that itself fails does NOT auto-arm a "rollback of the rollback." The state-machine terminates at `rollback_failed`; further action is manual L5 incident recovery.

---

## 11. Post-apply health-check contract

### 11.1 Required metrics per tier

| tier | required metrics | sample frequency | window | failure rule |
| --- | --- | --- | --- | --- |
| T1-CRITICAL | error_rate, latency_p99, freshness_age_ms, throughput, log_error_rate | ≥ 1 sample / 5_000 ms | 60_000 ms | any single sample `fail` flips status `fail`; 3 consecutive `stale` samples = `fail` |
| T2-IMPORTANT | error_rate, latency_p99, freshness_age_ms | ≥ 1 sample / 15_000 ms | 180_000 ms | 2 consecutive `fail` samples flip status `fail`; 4 consecutive `stale` = `fail` |
| T3-INFORMATIONAL | n/a | n/a | n/a | does not contribute to RBT-03 |

Metric thresholds are component-registry-pinned (per `component_registry_version`), so changing thresholds requires a registry-version bump and L3 approval.

### 11.2 Health window MUST close `pass` for `verified`
A rollout cannot transition `applying → verified` until every T1+T2 component's health window has closed `pass`. A flip to `fail` mid-window fires RBT-03 immediately.

### 11.3 Health regression after `verified`
Health is monitored continuously by `monitor_center` after the post-apply window closes, but a regression after `verified` is NOT in scope of the rollout state machine — it is handled by `monitor_center`'s alert path. This document only specifies rollback during the rollout window. Out-of-window regressions are an independent operational alert flow.

---

## 12. Durable persistence (closes Codex Blocker 5 directly)

### 12.1 `universe_rollouts`

| column | type | constraint | note |
| --- | --- | --- | --- |
| universe_rollout_id | UUID v7 | PK | |
| rollout_kind | TEXT | CHECK IN ('forward','rollback') NOT NULL | |
| parent_rollout_id | UUID v7 | FK universe_rollouts(universe_rollout_id) NULL | NULL for first forward rollout |
| universe_version | TEXT | NOT NULL | |
| parent_universe_version | TEXT | NULL | |
| rollback_target_version | TEXT | NOT NULL | HR-INV-04 |
| change_set_hash | TEXT | NOT NULL | |
| live_affecting | BOOLEAN | NOT NULL | |
| selection_policy_version | TEXT | NOT NULL | |
| capacity_policy_version | TEXT | NOT NULL | |
| score_policy_version | TEXT | NOT NULL | |
| component_registry_version | TEXT | NOT NULL | |
| ack_timeout_policy_version | TEXT | NOT NULL | |
| retry_policy_version | TEXT | NOT NULL | |
| quorum_policy_version | TEXT | NOT NULL | |
| rollback_policy_version | TEXT | NOT NULL | |
| approval_chain_ids | UUID[] | NOT NULL | matches §3 |
| proposal_id | UUID v7 | NOT NULL | |
| state | TEXT | CHECK IN ('proposed','validated','approved','applying','verified','partial_apply_quarantine','stalled','rolling_back','rolled_back','rollback_failed','abandoned') | |
| quorum_status | TEXT | CHECK IN ('pending','satisfied','violated') | |
| rollback_reason_code | TEXT | NULL | populated on rolling_back |
| additional_triggers | JSONB | NULL | array of (trigger_id, reason_code, ts_ms) |
| rollout_started_ts_ms | BIGINT | NOT NULL | |
| rollout_deadline_ts_ms | BIGINT | NOT NULL | |
| rollout_terminal_ts_ms | BIGINT | NULL | populated on terminal state |
| evidence_packet_id | UUID v7 | NULL | populated on terminal state |
| lineage_json | JSONB | NOT NULL | HR-INV-10 |

Indexes: `(universe_version, rollout_kind)`, `(state)`, `(rollout_started_ts_ms)`, `(parent_rollout_id)`.

### 12.2 `universe_rollout_components`

| column | type | constraint | note |
| --- | --- | --- | --- |
| universe_rollout_component_id | UUID v7 | PK | |
| universe_rollout_id | UUID v7 | FK universe_rollouts NOT NULL | |
| component_id | TEXT | NOT NULL | |
| component_instance_id | TEXT | NOT NULL | |
| tier | TEXT | CHECK IN ('T1-CRITICAL','T2-IMPORTANT','T3-INFORMATIONAL') NOT NULL | |
| live_affecting | BOOLEAN | NOT NULL | mirrors registry |
| apply_dispatched_ts_ms | BIGINT | NOT NULL | |
| first_ack_deadline_ts_ms | BIGINT | NOT NULL | §5.2 |
| full_applied_deadline_ts_ms | BIGINT | NOT NULL | §5.2 |
| post_apply_health_deadline_ts_ms | BIGINT | NULL | populated on first `applied` |
| ack_status | TEXT | CHECK IN ('pending','applied','validation_failed','health_failed','timeout','refused','partial') | |
| ack_reason_code | TEXT | NULL | |
| ack_reason_detail | TEXT | NULL | |
| latest_ack_id | UUID v7 | NULL | |
| latest_ack_ts_ms | BIGINT | NULL | |
| attempt_number | INT | NOT NULL DEFAULT 1 | |
| max_attempts | INT | NOT NULL | from retry policy |
| escalation_state | TEXT | CHECK IN ('none','retrying','dead_letter','recovered') NOT NULL DEFAULT 'none' | |
| escalation_deadline_ts_ms | BIGINT | NOT NULL | |
| rollback_ready | BOOLEAN | NULL | from latest ack |
| sub_instance_breakdown | JSONB | NULL | for `partial` |
| validation_results_json | JSONB | NULL | from latest ack |
| lineage_json | JSONB | NOT NULL | |

Indexes: `(universe_rollout_id, component_id)` UNIQUE, `(ack_status)`, `(escalation_state)`, `(first_ack_deadline_ts_ms)`, `(full_applied_deadline_ts_ms)`.

### 12.3 `universe_rollout_health`

| column | type | constraint | note |
| --- | --- | --- | --- |
| universe_rollout_health_id | UUID v7 | PK | |
| universe_rollout_id | UUID v7 | FK universe_rollouts NOT NULL | |
| component_id | TEXT | NOT NULL | |
| metric_id | TEXT | NOT NULL | |
| sample_ts_ms | BIGINT | NOT NULL | |
| value_decimal | TEXT | NOT NULL | string-encoded decimal |
| threshold_decimal | TEXT | NOT NULL | string-encoded decimal |
| status | TEXT | CHECK IN ('pass','fail','stale') NOT NULL | |
| window_start_ts_ms | BIGINT | NOT NULL | |
| window_end_ts_ms | BIGINT | NOT NULL | |

Indexes: `(universe_rollout_id, component_id, metric_id, sample_ts_ms)`, `(status, sample_ts_ms)`.

### 12.4 `universe_rollouts_audit`

Tamper-evident hash chain (consistent with `13_AUDIT_LEDGER_AND_AI_CHANGE_GOVERNANCE.md` requirements).

| column | type | constraint | note |
| --- | --- | --- | --- |
| audit_seq | BIGSERIAL | PK | immutable monotonic sequence |
| audit_event_id | UUID v7 | NOT NULL UNIQUE | |
| universe_rollout_id | UUID v7 | NOT NULL | |
| event_kind | TEXT | NOT NULL | dispatch, ack, retry, escalation_to_dead_letter, quorum_recompute, rollback_armed, rollback_started, terminal_state |
| event_ts_ms | BIGINT | NOT NULL | |
| payload_json | JSONB | NOT NULL | snapshot of changed fields |
| actor_json | JSONB | NOT NULL | actor envelope (system or human) |
| prev_audit_hash | TEXT | NOT NULL | sha256 of prior row's `row_hash` |
| row_hash | TEXT | NOT NULL | sha256(prev_audit_hash || canonicalize(payload_json) || actor_json || event_ts_ms) |

Inserts only. Updates and deletes are rejected by DB trigger. Nightly assertion verifies hash-chain continuity.

---

## 13. `universe_rollout_event` envelope

Carried on the V2 event bus (Redis stream `v2:events:universe_rollout`).

```json
{
  "schema_version": "1.0.0",
  "event_id": "uuid-v7",
  "event_kind": "rollout_proposed|rollout_approved|apply_dispatched|component_acked|component_retry|component_dead_letter|quorum_recomputed|rollback_armed|rollback_started|rolled_back|rollback_failed|partial_apply_quarantine|stalled|verified",
  "event_ts_ms": 1735689601000,
  "universe_rollout_id": "uuid-v7",
  "parent_rollout_id": "uuid-v7|null",
  "universe_version": "string",
  "parent_universe_version": "string|null",
  "rollback_target_version": "string|null",
  "rollout_state": "string",
  "quorum_status": "pending|satisfied|violated",
  "rollback_reason_code": "string|null",
  "additional_triggers": [{"trigger_id": "RBT-01", "reason_code": "T1_CRITICAL_FAILURE", "ts_ms": 1735689601000}],
  "components_summary": {
    "total": 14,
    "by_status": {"pending": 2, "applied": 11, "validation_failed": 1, "timeout": 0, "refused": 0, "dead_letter": 0}
  },
  "lineage": {
    "universe_version": "string",
    "parent_universe_version": "string|null",
    "rollout_id": "uuid-v7",
    "parent_rollout_id": "uuid-v7|null",
    "change_set_hash": "string",
    "proposal_id": "uuid-v7",
    "approval_chain_ids": ["uuid-v7"],
    "component_registry_version": "string",
    "ack_timeout_policy_version": "string",
    "retry_policy_version": "string",
    "quorum_policy_version": "string",
    "rollback_policy_version": "string",
    "lineage_gap_reason": "string|null"
  }
}
```

Events are append-only on the Redis stream and replicated into `universe_rollouts_audit`. The Redis stream is a navigation aid; the DB audit table is the authoritative record.

---

## 14. Override-conflict deterministic precedence

Already captured in §8.3 to keep partial-failure resolution self-contained, but explicitly surfaced here so it is one of the enumerated remediation deliverables. Closes review finding 4.

---

## 15. Selection-policy version pinning requirement

Already captured in §3 (`selection_policy_version`, `capacity_policy_version`, `score_policy_version` are all required fields on `universe_rollouts`). Closes review finding 3. Every selection output that flows into a rollout MUST carry these IDs; rollouts whose payload is missing any of the three are rejected with `error_code=MISSING_POLICY_VERSION_PIN`.

---

## 16. Test-vector matrix

A scaffold implementation MUST pass every vector below before V2 build clears Blocker 5.

### 16.1 Ack timeout vectors

| vector | setup | expected outcome |
| --- | --- | --- |
| TV-AT-01 | T1 component silent past first-ack deadline | virtual `ack_status='timeout'`, retry attempt 2 dispatched |
| TV-AT-02 | T1 component silent past full-applied deadline after max retries | terminal `timeout`, RBT-01 fires, rollback armed |
| TV-AT-03 | Coordinator restart mid-rollout with deadline already expired | post-restart re-evaluation marks expired components `timeout` without grace extension |
| TV-AT-04 | Component clock skew > 5_000 ms | ack rejected, re-handshake required |

### 16.2 Retry vectors

| vector | setup | expected outcome |
| --- | --- | --- |
| TV-RT-01 | T1 component returns `validation_failed` with `transient_*` reason | retry up to max_attempts=3 |
| TV-RT-02 | T1 component returns `refused` | NO retry; immediate escalation; RBT-01 evaluation |
| TV-RT-03 | Duplicate dispatch with same idempotency_key | component re-emits prior ack, no double-apply |
| TV-RT-04 | Retry exhaustion on T2 component | dead_letter; RBT-02 fraction recompute |

### 16.3 Quorum vectors

| vector | setup | expected outcome |
| --- | --- | --- |
| TV-QM-01 | All T1 applied, T2 fraction 80%, T3 fraction 60% | `quorum_status='satisfied'` |
| TV-QM-02 | All T1 applied except 1 timeout | `quorum_status='violated'`, RBT-01 |
| TV-QM-03 | T2 fraction 79% on `live_affecting=true` | `quorum_status='violated'`, partial_apply_quarantine |
| TV-QM-04 | T3 fraction 40% on `live_affecting=false` | rollout `degraded`, NOT violated |
| TV-QM-05 | T1 component reports rollback_ready=false | RBT-05 fires regardless of ack_status |

### 16.4 Partial-failure vectors

| vector | setup | expected outcome |
| --- | --- | --- |
| TV-PF-01 | Half T2 components applied, half timed out | partial_apply_quarantine, no auto-recover |
| TV-PF-02 | Operator submits forward-recovery rollout from quarantine | new rollout, fresh approvals required |
| TV-PF-03 | Operator submits rollback from quarantine | new rollout, kind=rollback, runs §10 |
| TV-PF-04 | Override conflict force_disabled vs force_train_only | force_disabled wins, deterministic |
| TV-PF-05 | T1 components on differing universe_versions during apply | execution path read-through to prior verified blocked until uniform |

### 16.5 Rollback trigger vectors

| vector | setup | expected outcome |
| --- | --- | --- |
| TV-RB-01 | RBT-01 fires (T1 critical failure) | rollback rollout created, parent_rollout_id set, components that acked applied receive rollback dispatch |
| TV-RB-02 | RBT-03 fires (post-apply health regression) | rollback rollout created with reason POST_APPLY_HEALTH_REGRESSION |
| TV-RB-03 | RBT-04 fires (rollout deadline exceeded with quorum pending) | rollback rollout created with reason ROLLOUT_STALLED |
| TV-RB-04 | RBT-01 + RBT-03 fire same tick | rollback created with reason=T1_CRITICAL_FAILURE, additional_triggers[] includes RBT-03 |
| TV-RB-05 | Rollback itself fails on T1 component | terminal `rollback_failed`, Risk Gateway live_gate flipped to blocked |
| TV-RB-06 | Manual operator rollback on live_affecting=true without L4 | rejected at API layer per §9.1 |
| TV-RB-07 | rollback_target_version was never NOT NULL at row creation | rollout rejected at proposal stage with NO_ROLLBACK_TARGET |

### 16.6 Persistence vectors

| vector | setup | expected outcome |
| --- | --- | --- |
| TV-DB-01 | `universe_rollouts.rollback_target_version` NULL | DB trigger rejects insert |
| TV-DB-02 | UPDATE on `universe_rollouts_audit` | DB trigger rejects |
| TV-DB-03 | Hash-chain break in audit | nightly assertion alarms |
| TV-DB-04 | Coordinator restart, in-flight rollouts re-loaded | active rollouts re-evaluated, expired deadlines transition correctly |

### 16.7 Determinism vector

| vector | setup | expected outcome |
| --- | --- | --- |
| TV-DT-01 | Replay rollout from recorded acks against pinned policy versions | byte-identical terminal state, byte-identical audit chain |

---

## 17. Audit / evidence-packet requirements

Every rollout terminal state (`verified`, `rolled_back`, `rollback_failed`, `partial_apply_quarantine`, `stalled`, `abandoned`) MUST emit an evidence packet at `ollama/evidence_packets/universe_rollout/<universe_rollout_id>.json` containing:

- the full `universe_rollouts` row;
- the full `universe_rollout_components` row set;
- every `universe_rollout_health` sample for every (component, metric) pair;
- the contiguous slice of `universe_rollouts_audit` rows for this rollout, with `row_hash` chain verified;
- the active component registry, all five policy bundles (selection/capacity/score/component_registry/ack_timeout/retry/quorum/rollback) at the pinned versions;
- approval chain rows from the audit ledger with their hash-chain neighbors;
- raw evidence pointers (Redis stream offsets, log file offsets, monitor snapshots);
- a Claude-verifiable summary (per CLAUDE.md Evidence Integrity Rule, summary is navigation aid only).

Evidence packets are append-only and named by rollout id so replay is trivial.

---

## 18. Traceability — Codex Blocker 5 sub-claims to remediation sections

| Codex sub-claim | Closed by |
| --- | --- |
| component-wise ack status | §2 (registry), §4 (ack envelope), §12.2 (`universe_rollout_components`) |
| missing-ack escalation | §5 (timeouts), §6 (retry + dead-letter), §12.2 (`escalation_state`) |
| validation results | §4 (`validation_results[]`), §12.2 (`validation_results_json`) |
| post-apply health checks | §11 (health contract), §12.3 (`universe_rollout_health`) |
| rollback evidence per universe update | §10 (state machine), §12.4 (audit chain), §17 (evidence packets) |
| durable per-component rollout/ack/evidence model | §12.1–§12.4 (four tables) |
| ack timeout policy | §5 |
| retry policy | §6 |
| dead-letter / escalation model | §6.3 |
| rollback trigger thresholds | §9 |
| partial-apply behavior | §8 |
| selection-policy version pinning | §3, §15 |
| override conflict resolution deterministic ordering | §8.3, §14 |
| non-bypass | §1 (HR-INV-01..12) |
| determinism | §1 HR-INV-03, §16.7 |

Every sub-claim has at least one section. No sub-claim is left to "asserted" status.

---

## 19. Gate recommendation

Blocker 5 is closed by this remediation file together with the persistence schema deltas folded into `claude_worklog/v2_architecture/03_DATABASE_SCHEMA.md` and the route surface defined in `claude_worklog/v2_architecture_remediation/04_API_CONTRACT_REMEDIATION.md`. To clear the gate, the next pass MUST:

1. Fold §12 tables into `03_DATABASE_SCHEMA.md`.
2. Fold §13 envelope into `04_REDIS_NAMESPACE_AND_RETENTION_PLAN.md`.
3. Fold §3 / §4 into `08_HOT_RELOAD_PIPELINE_ARCHITECTURE.md`, replacing the 45-line stub.
4. Confirm `04_API_CONTRACT_REMEDIATION.md` route entries match §3 / §9.1 / §10.1 dispatch surface.
5. Re-run actual Codex CLI architecture review with the updated package.

Until those four edits land, the architecture remains NO-GO on Blocker 5 even though the operational semantics are now specified. This file IS the spec, but the spec MUST be linked into the canonical architecture set before the gate flips. V2 build remains blocked.

No files outside `./claude_worklog/v2_architecture_remediation/` were modified by producing this document. No Redis writes were made. No service state was altered. No exchange actions were taken.
```