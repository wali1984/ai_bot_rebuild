# 07 AI Governance Remediation

## Status
- Source blocker: actual Codex CLI architecture review, `claude_worklog/v2_architecture_codex_review/12_ACTUAL_CODEX_CLI_ARCHITECTURE_REVIEW_OUTPUT.md`, **Blocker 6** — *"Audit immutability and approval enforcement are not strong enough. Audit is described as append-only, but the schema lacks tamper-evidence/hash chaining, immutable sequence semantics, approval subject integrity, approval state transitions, or enforcement that L4/L5 actions cannot apply without required human approval."*
- Reconciled in `claude_worklog/v2_architecture_codex_review/13_ACTUAL_CODEX_RECONCILIATION.md`, consolidated blocker **#6**.
- Provisional blocker reference: `claude_worklog/v2_architecture_codex_review/08_AI_GOVERNANCE_REVIEW.md` adversarial finding 1 (HIGH) — *"L4 mandatory human approval not explicit enough in architecture text"* — plus findings 2 (approval depth model under-specified), 3 (capability-policy contract incomplete), and 4 (rollback validation criteria not standardized).
- Architecture file under remediation: `claude_worklog/v2_architecture/13_AUDIT_LEDGER_AND_AI_CHANGE_GOVERNANCE.md` (current text is a 32-line stub that names L0–L5 levels, lists twelve mandatory `ai_action_changes` fields, asserts "Level 5 is never autonomous", and asserts append-only DB audit with cross-links to monitor packets — but defines no tamper-evident hash chain, no immutable sequence semantics, no approval subject-integrity binding, no approval state machine, no actor capability matrix, no rollback validation contract, no enforcement that L4/L5 mutations cannot apply without a satisfied approval row).
- Companion remediation files this document references:
  - `04_API_CONTRACT_REMEDIATION.md` — defines the route surface for approval-gated routes (`X-Approval-Token` header, §2.4 approval matrix per risk level, §5 dangerous-change route discipline, §3 standard error envelope including `approval_required`/`approval_state_invalid`), the standard error envelope, and live-block posture this document references.
  - `05_RISK_GATEWAY_REMEDIATION.md` — defines the `policy_bundles` state machine whose transitions are gated by approvals defined here (RG §2.2). Approval levels referenced for bundle transitions (L2 → L4 → L5) are normatively defined in this document (§3, §4).
  - `06_HOT_RELOAD_REMEDIATION.md` — defines the hot-reload rollout state machine whose `live_affecting=true` rollouts require L4/L5 approvals defined here (HR INV-08).
- This document does **not** ship V2 code, does not write Redis, does not place or cancel any exchange instructions, does not modify the legacy runtime tree, and does not restart any service. It is an architecture-layer deliverable producing schemas, state machines, hash-chain semantics, capability matrices, persistence requirements, and test-vector matrices that make AI governance non-bypass enforceable in scaffold tests.

## Read/write boundary compliance
Writes only to `./claude_worklog/v2_architecture_remediation/`. Does not edit `./legacy_reference/**` or the sibling legacy bot tree. No `.env`, no secrets, no Redis writes, no service restarts, no exchange actions. All examples are schema, state-machine, and policy fragments — no executable runtime is created or modified. Live mutation routes referenced here remain blocked-by-default per `CLAUDE.md`; the contract encodes the block, it does not enable autonomous L4/L5 changes against live systems.

## Scope of remediation
This file produces, in order:

1. Non-bypass invariants the architecture must enforce for AI governance (the contract implementations are scored against).
2. Risk-level taxonomy and authoritative meaning of each level (L0–L5) — what actions belong at each level, what approval depth is required, who may originate, who may approve.
3. Approval workflow object model (`approval_request`, `approval_decision`, `approval_chain`, `approval_subject_binding`).
4. Approval state machine (state set, allowed transitions, terminal states, expiry, revocation, supersession).
5. Subject-integrity binding (how an approval ties to *exactly one* mutation payload — closes the "approval-for-anything" exploit).
6. Actor capability matrix (which `actor_type` may originate, propose, approve, apply at each level — closes review finding 3).
7. L4/L5 hard-gate enforcement contract (the architecture-layer guarantee that execution-impacting changes cannot apply without the right approval row).
8. Rollback validation contract (closes review finding 4).
9. Append-only audit ledger schema with tamper-evident hash chain.
10. Sequence-monotonicity guarantees and gap-detection contract.
11. Cross-domain governance binding (how Risk Policy bundles, Hot-Reload rollouts, Symbol Overrides, Connector live-enable, API-key rotation, kill-switch arming, and L5 dangerous flips all bind through the same approval object — closes review finding 1 across the entire control surface).
12. Durable persistence tables (`approval_requests`, `approval_decisions`, `approval_chains`, `audit_ledger`, `audit_chain_heads`, `revocation_lists`).
13. Audit ledger event envelope (`audit_event`) with full lineage and hash-chain trace.
14. Test-vector matrix that any scaffold implementation MUST pass before V2 build clears Blocker 6.
15. Audit / evidence-packet requirements.
16. Traceability table mapping every sub-claim of Codex Blocker 6 to the section that closes it.
17. Gate recommendation.

---

## 1. Non-bypass invariants (the contract AI governance is judged against)

These are the architectural invariants every AI governance implementation MUST satisfy. They are restated as machine-checkable statements so scaffold tests can assert them directly.

| ID | Invariant | Assertion form |
| --- | --- | --- |
| GOV-INV-01 | No mutation row whose `risk_level >= 'L2'` may exist in any governed table without a satisfied `approval_chains.state = 'satisfied'` row whose `subject_binding_hash` matches the canonical hash of the applied payload. | DB CHECK + service-layer guard. Nightly assertion: `SELECT COUNT(*) FROM <table> t LEFT JOIN approval_chains ac ON ac.subject_type=t.kind AND ac.subject_id=t.id WHERE t.risk_level >= 'L2' AND (ac.state IS DISTINCT FROM 'satisfied' OR ac.subject_binding_hash <> t.payload_canonical_hash)` MUST be 0. |
| GOV-INV-02 | No L4 or L5 mutation may be originated by `actor_type IN ('claude','codex','ollama')` without the actor's role being `proposer_only` for that capability AND the approver's role being `live_admin`. L5 additionally requires `actor_type = 'human'` for the originator AND `actor_type = 'human'` for both approvers (dual-control). | Service-layer guard rejects on capability-matrix lookup (§6) before any DB write; route guard rejects at API boundary per `04_API_CONTRACT_REMEDIATION.md §2.4`. |
| GOV-INV-03 | Approval state transitions are deterministic given `(approval_request, approval_decisions[], current_ts_ms, capability_matrix_version, approval_policy_version)`. Re-running the resolver on the same inputs MUST produce the byte-identical terminal state. | Re-evaluation harness produces same `state`, same `failing_check`, same `quorum_satisfied` boolean, same `subject_binding_hash`. |
| GOV-INV-04 | An `approval_chain` is bound to **exactly one** `subject_binding_hash`. If the proposed payload changes between approval-issuance and apply, the chain MUST be invalidated (`state = 'subject_drift'`) before the apply is allowed. The subject-binding hash is computed over the canonicalized payload at proposal time and frozen. | Apply-path service guard recomputes `subject_binding_hash` from the about-to-apply payload and compares to the chain's frozen hash; mismatch = reject. |
| GOV-INV-05 | The audit ledger is append-only at the schema level (no `UPDATE`/`DELETE` privileges granted to application roles) AND tamper-evident at the content level (each row carries `prev_hash` and `row_hash`; `row_hash = sha256(prev_hash || canonicalized_row_excluding_row_hash)`). The first row's `prev_hash` is the genesis constant. | DB role grants exclude `UPDATE`/`DELETE` on `audit_ledger`; nightly chain-walker verifies `row_hash` recomputes for every row in sequence, with zero gaps. |
| GOV-INV-06 | Audit sequence numbers are strictly monotonic per partition (global if unpartitioned), gapless within a partition, and assigned by a single writer (DB serial or coordinator lease). Any detected gap immediately quarantines the partition and emits a `chain_integrity_breach` evidence packet. | Nightly assertion: `SELECT MAX(sequence_id) - MIN(sequence_id) + 1 = COUNT(*)` per partition; mismatch triggers freeze. |
| GOV-INV-07 | Every L4/L5 approved change carries a rollback contract that names (a) a rollback target, (b) a rollback validation set (per §8), and (c) an expected rollback evidence-packet kind. Apply with no rollback contract = reject. | Service-layer guard at apply-path rejects when `approval_chains.rollback_contract_json IS NULL` for `risk_level >= 'L4'`. |
| GOV-INV-08 | Approval decisions are non-repudiable: each decision row stores the approver's `user_id`, `session_id`, `mfa_assertion_id` (for L4/L5), client IP, and the decision row itself participates in the audit hash chain. Decision rows are immutable after write. | DB role grants exclude `UPDATE`/`DELETE` on `approval_decisions`; row participates in `audit_ledger` chain with `event_kind = 'approval_decision'`. |
| GOV-INV-09 | Default state of every newly provisioned governance coordinator is `accepting_approvals=false` until `capability_matrix_version` and `approval_policy_version` are loaded and verified by hash. Until then, every approval request is rejected with `approval_required_policy_unloaded`, and every L2+ apply is blocked with `governance_policy_unloaded`. | Boot test asserts default behavior. |
| GOV-INV-10 | Every audit event carries the lineage tuple `(actor, subject_type, subject_id, approval_chain_id|null, parent_event_id|null, sequence_id, prev_hash, row_hash, capability_matrix_version, approval_policy_version, audit_chain_version)`. Missing upstream IDs are explicit `null` with `lineage_gap_reason`. | Companion of `04_API_CONTRACT_REMEDIATION.md §1.4`. |
| GOV-INV-11 | Governance coordinator never mutates legacy systems, never edits old Redis keys, never restarts the legacy trainer. Every coordinator action targets the V2 namespace only. | Static config: `REDIS_PREFIX = "v2:"`, no write paths to legacy keys; CI grep for legacy key prefixes in coordinator source. |
| GOV-INV-12 | Non-bypass holds across all execution paths: paper, replay, simulator, live. The mode flag (`paper|live`) MUST NOT branch around the approval enforcement; only the *required level* may differ (e.g. an L4 paper change is L5 in live), but every L2+ change still requires a satisfied approval chain. | Static check: the only call-site for governed mutations is the apply-path guard; the apply-path guard reads `approval_chains.state = 'satisfied'` regardless of `mode`. |
| GOV-INV-13 | An approval token (`X-Approval-Token = approval_chain_id`) is single-use against a single `subject_binding_hash`. Token replay against a different subject binding is rejected; token replay against the same binding within idempotency TTL returns the original outcome. | Service-layer guard: `approval_chains.consumed_by_request_id` set on first apply; subsequent uses with different `request_id` rejected unless `subject_binding_hash` matches AND outcome replay is requested. |
| GOV-INV-14 | Revoked approvals propagate within `revocation_propagation_max_ms` (default 5000ms) to every coordinator that may apply against them. A revoked approval that is consumed before propagation MUST emit a `revocation_race_loss` audit event AND auto-arm a rollback evaluation per §8. | Revocation-list TTL contract + audit assertion that every consumption after revocation_ts_ms has a corresponding `revocation_race_loss` row. |
| GOV-INV-15 | L5 dangerous changes (per `04_API_CONTRACT_REMEDIATION.md §2.4` and §2 below) MUST carry the `X-Live-Confirm: I-UNDERSTAND` header at apply time AND a fresh-issued (≤300s old) MFA assertion AND dual approver decisions from two distinct `live_admin` users AND a non-zero `human_origin_attestation` row. | Apply-path service guard rejects on any failure; route guard rejects at API boundary. |

---

## 2. Risk-level taxonomy

The architecture stub names L0–L5. Codex requires concrete meaning, approval depth, originator/approver capability per level, and the explicit set of action types that belong at each level. This section enumerates them.

### 2.1 Authoritative level meanings

| Level | Meaning | Approval depth | Originator allowed | Approver required | MFA required | L5 confirmation header | Rollback contract required |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **L0** | Read/observe only. No mutation. No `ai_action_changes` row. | None | any | none | no | no | no |
| **L1** | Docs, reports, evidence-packet emission, monitor-summary writes. No runtime mutation. | None (recorded; not approved) | any | none | no | no | no |
| **L2** | V2-only non-live config: paper-mode parameters, monitor thresholds, GUI prefs, evidence-packet schedules. | Single `admin` approval | `human|claude|codex|ollama|system` (with `proposer` capability) | one `admin` | no | no | optional |
| **L3** | Operational non-trading: V2 cron schedules, log retention, replay window, RBAC user provisioning (non-`live_admin`), session policy. | Single `admin` approval + `change_id` audit | `human|claude` (`proposer`) | one `admin` | yes (TOTP) | no | optional |
| **L4** | Trading-impacting in *paper or staged*: Risk Policy bundle apply (paper scope), Hot-Reload `live_affecting=true` rollouts at paper, orchestrator strategy weight changes, fleet member admission, leverage-cap policy, daily-loss-cap policy, mandatory-stop policy. | `proposer` proposal + `live_admin` approval (single approver) | `human|claude` (`proposer`); `codex` may propose only via review-center workflow; `ollama` may NOT originate L4 | one `live_admin` (human) | yes (TOTP, ≤300s) | no | required |
| **L5** | Dangerous live changes: enable live trading, add/activate live API keys, raise leverage globally, enable CROSS margin, raise max position size, raise daily-loss-cap, disable kill switch, disable mandatory stop, enable hedge/DCA, enable `ADJUST_LEVERAGE`, switch a connector to `live_enabled=true`, override a connector-side hard block, promote a `risk_policy_bundle` to `applied` with `mode_scope` containing `live`. | `human` proposal + dual `live_admin` approvals (two distinct human users) + `X-Live-Confirm: I-UNDERSTAND` + non-zero `human_origin_attestation` | `human` only (per `CLAUDE.md` "Level 5 is never autonomous") | two distinct `live_admin` (humans) | yes (TOTP fresh ≤300s, both approvers and proposer) | yes | required |

`CLAUDE.md` Hard Constraint Mapping:
- *"Level 5 is never autonomous"* → row L5 in §2.1: originator restricted to `human`, dual-human approver requirement, fresh MFA on all three actors, explicit confirmation header (GOV-INV-02, GOV-INV-15).
- *"Default status: LIVE TRADING: BLOCKED"* → §7.4 below: the L5 capability gate to flip live state requires the satisfied chain AND the API-layer live-block to be unset by a *separate* L5 chain. Both gates are independent (defense in depth).

### 2.2 Action-to-level catalog

The architecture-layer rule: every governed mutation MUST be classified into exactly one level at proposal time. The `change_id` resolver consults this catalog to pick the level. Implementations may add rows under an `x_` namespace for experiment actions, but only at L2 and only when scoped to `mode_scope = 'paper'`.

| Action key | Level | Subject type | Notes |
| --- | --- | --- | --- |
| `monitor.threshold.update` | L2 | `monitor_config` | Paper-only thresholds. |
| `evidence_packet.schedule.update` | L2 | `evidence_packet_schedule` | Cadence and retention only. |
| `gui.layout.update` | L2 | `gui_layout` | Layout only; capability matrix is L3. |
| `replay.window.update` | L3 | `replay_config` | Replay scope only. |
| `rbac.user.create` | L3 | `users` | Non-`live_admin` roles only; granting `live_admin` is L5 (see below). |
| `rbac.session_policy.update` | L3 | `session_policy` | TTL/idle/MFA-window changes. |
| `risk_policy_bundle.apply` (paper scope) | L4 | `risk_policy_bundles` | Bundle whose `applies_to.mode_scopes ⊆ {paper}` only. |
| `risk_policy_bundle.apply` (live scope) | L5 | `risk_policy_bundles` | Bundle whose `applies_to.mode_scopes` contains `live`. |
| `hot_reload.rollout.apply` (live_affecting=true) | L4 (paper) / L5 (live) | `universe_rollouts` | Per `06_HOT_RELOAD_REMEDIATION.md` HR INV-08. |
| `orchestrator.strategy_weight.update` | L4 | `strategy_weights` | Live promotion is L5. |
| `fleet.trader.admit` | L4 | `traders` | Live admission L5. |
| `connector.live_enabled.set_true` | L5 | `connectors` | Per `04_API_CONTRACT_REMEDIATION.md §6.5`. |
| `connector.live_enabled.set_false` | L4 | `connectors` | Disabling is lower risk than enabling. |
| `exchange_account.api_key.rotate` | L5 | `exchange_accounts` | Per `04_API_CONTRACT_REMEDIATION.md §6.7`. |
| `risk.kill_switch.arm` | L4 | `kill_switch_state` | Lower risk to *arm* (more restrictive). |
| `risk.kill_switch.trip` | L4 | `kill_switch_state` | Always allowed manually; logged. |
| `risk.kill_switch.disarm` | L5 | `kill_switch_state` | Per `CLAUDE.md` dangerous-settings list. |
| `risk.leverage_cap.raise` | L5 | `risk_policy_bundles` | Lowering is L4. |
| `risk.daily_loss_cap.raise` | L5 | `risk_policy_bundles` | Lowering is L4. |
| `risk.max_position_size.raise` | L5 | `risk_policy_bundles` | Lowering is L4. |
| `risk.margin_mode.set_cross` | L5 | `risk_policy_bundles` | Per `CLAUDE.md` dangerous-settings list. |
| `risk.mandatory_stop.disable` | L5 | `risk_policy_bundles` | Per `CLAUDE.md` dangerous-settings list. |
| `risk.hedge_or_dca.enable` | L5 | `risk_policy_bundles` | Per `CLAUDE.md` dangerous-settings list. |
| `risk.adjust_leverage.enable` | L5 | `risk_policy_bundles` | Per `CLAUDE.md` dangerous-settings list. |
| `mode.switch.paper_to_live` | L5 | `mode_state` | Per `CLAUDE.md` dangerous-settings list. |
| `rbac.role.grant_live_admin` | L5 | `users` | Granting L5-relevant role is itself L5. |
| `connector_hard_block.override` | L5 | `connector_overrides` | Per `05_RISK_GATEWAY_REMEDIATION.md §10`. |

---

## 3. Approval workflow object model

The governance coordinator never approves "loose" changes. Every governed mutation is bound to an `approval_chain` whose subject-integrity hash freezes the payload at proposal time. The chain is the unit of approval, audit, replay, and revocation.

### 3.1 `approval_request` envelope

Created by the route handler when a non-L0/L1 mutation is proposed.

```json
{
  "schema_version": "1.0.0",
  "approval_chain_id": "uuid-v7",
  "approval_request_id": "uuid-v7",
  "request_id": "uuid-v7",
  "action_key": "risk_policy_bundle.apply",
  "risk_level": "L5",
  "subject_type": "risk_policy_bundles",
  "subject_id": "uuid-v7",
  "subject_binding_hash": "sha256:<hex>",
  "payload_canonical_json": "<canonicalized payload as string>",
  "originator": {
    "actor_type": "human",
    "actor_id": "user_id_or_agent_id",
    "session_id": "string|null",
    "mfa_assertion_id": "string|null",
    "client_ip": "string|null"
  },
  "human_origin_attestation": {
    "present": true,
    "attestation_id": "string|null",
    "issued_ts_ms": 1735689600000
  },
  "required_approvals": [
    { "level": "L5", "role": "live_admin", "count": 2, "must_be_distinct": true, "actor_type_required": "human" }
  ],
  "evidence_pointers": [
    {"kind": "redis|log|db|file|monitor_snapshot|evidence_packet", "ref": "string"}
  ],
  "rollback_contract": {
    "rollback_target_ref": "<table>:<id>:<version>",
    "rollback_validation_set": ["<test_vector_id>", "..."],
    "rollback_evidence_packet_kind": "rollback_validation"
  },
  "expiry_ts_ms": 1735689900000,
  "created_ts_ms": 1735689600000
}
```

Rules:
- `subject_binding_hash = sha256(canonicalized_json(payload_canonical_json))`. Any change to the about-to-apply payload between proposal and apply MUST produce a new hash and invalidate the chain (GOV-INV-04).
- `expiry_ts_ms` defaults to `created_ts_ms + approval_policy.default_expiry_ms` (L2/L3: 24h; L4: 1h; L5: 15min). Expiry is a hard cutoff; expired chains transition to `expired` and cannot be revived.
- `required_approvals[].count` ≥ 2 with `must_be_distinct=true` for L5 implements the dual-control requirement from §2.1.
- `human_origin_attestation.present=true` is mandatory at L5; the attestation row is signed by the originator's MFA-bound session and persists in `audit_ledger` with `event_kind = 'human_origin_attestation'`.
- `rollback_contract` is REQUIRED for L4 and L5 (GOV-INV-07). L2/L3 may omit but defaults are recorded.

### 3.2 `approval_decision` envelope

Recorded when an approver makes a decision against an `approval_chain`.

```json
{
  "schema_version": "1.0.0",
  "approval_decision_id": "uuid-v7",
  "approval_chain_id": "uuid-v7",
  "decision": "approved|rejected|abstained",
  "decision_reason": "string",
  "approver": {
    "actor_type": "human",
    "user_id": "string",
    "role": "live_admin",
    "session_id": "string",
    "mfa_assertion_id": "string",
    "mfa_freshness_ms": 120000,
    "client_ip": "string"
  },
  "subject_binding_hash_seen": "sha256:<hex>",
  "evidence_pointers": [ /* same shape */ ],
  "decision_ts_ms": 1735689660000
}
```

Rules:
- `subject_binding_hash_seen` MUST match the chain's frozen `subject_binding_hash`. Mismatch = decision rejected at write time with `subject_drift_detected` (closes the "approve a different payload than you saw" exploit).
- `mfa_freshness_ms` MUST be ≤ `approval_policy.mfa_freshness_max_ms` for the level (L3: 600000ms, L4: 300000ms, L5: 300000ms). Stale MFA = decision rejected.
- `decision_ts_ms` MUST be ≥ chain `created_ts_ms` and < chain `expiry_ts_ms`. Outside-window = rejected.
- Decision rows are immutable after write (GOV-INV-08); revocation happens by a *separate* `approval_decision` row of `decision = 'revoked'` issued by `live_admin` against an already-approved chain (§4.2).

### 3.3 `approval_chain` (resolver state)

The `approval_chain` is the resolver's projection over the request and all decisions recorded against it. It is materialized in `approval_chains` (§12) and is what the apply-path guard reads.

```json
{
  "approval_chain_id": "uuid-v7",
  "approval_request_id": "uuid-v7",
  "subject_type": "risk_policy_bundles",
  "subject_id": "uuid-v7",
  "subject_binding_hash": "sha256:<hex>",
  "risk_level": "L5",
  "required_approvals_resolved": [
    { "level": "L5", "role": "live_admin", "count": 2, "must_be_distinct": true, "actor_type_required": "human", "satisfied_count": 2 }
  ],
  "decisions": ["approval_decision_id_1", "approval_decision_id_2"],
  "state": "satisfied",
  "consumed_by_request_id": "uuid-v7|null",
  "consumed_ts_ms": 1735689700000,
  "rollback_contract_json": { /* §3.1 rollback_contract */ },
  "rollback_state": "not_triggered|armed|in_progress|verified|failed",
  "expiry_ts_ms": 1735689900000,
  "approval_policy_version": "2026.04.30-001",
  "capability_matrix_version": "2026.04.30-001",
  "audit_chain_version": "1",
  "created_ts_ms": 1735689600000,
  "last_transition_ts_ms": 1735689660000
}
```

---

## 4. Approval state machine

```
draft -> open -> partially_satisfied -> satisfied -> consumed
                                                 \-> revoked
                  \-> rejected
                  \-> expired
                  \-> subject_drift
                  \-> superseded
```

### 4.1 Allowed transitions

| Transition | Trigger | Required scope (RBAC, see `04_API_CONTRACT_REMEDIATION.md §2`) | Side-effect |
| --- | --- | --- | --- |
| `draft → open` | Originator publishes the request | `write:approval` (originator scope per level) | Subject-binding hash frozen; expiry timer starts; capability-matrix and approval-policy versions stamped. |
| `open → partially_satisfied` | A valid `approval_decision.decision='approved'` arrives but `required_approvals.count` not yet met | `write:approval` | Increment `satisfied_count`. |
| `partially_satisfied → satisfied` | The decision that meets `required_approvals.count` arrives, with all `must_be_distinct` and `actor_type_required` constraints met | `write:approval` | Chain becomes apply-eligible. |
| `open|partially_satisfied → rejected` | An `approval_decision.decision='rejected'` arrives from any approver of the required role | `write:approval` | Terminal. New chain required to retry. |
| `open|partially_satisfied|satisfied → expired` | `now_ts_ms >= expiry_ts_ms` | system | Terminal. |
| `open|partially_satisfied|satisfied → subject_drift` | An apply attempt presents a payload whose recomputed `subject_binding_hash` differs from the frozen one | system (apply-path guard) | Terminal. Audit event emitted. |
| `satisfied → consumed` | An apply call presents the chain ID and identical subject hash; chain locked to `consumed_by_request_id` | `write:apply` | Side-effect proceeds. |
| `satisfied → revoked` | A `live_admin` issues a revoke decision on a satisfied-but-unconsumed chain | `write:approval` (must be `live_admin`) | Audit + propagate to revocation list within `revocation_propagation_max_ms` (GOV-INV-14). |
| `consumed → revoked` | Forbidden. A consumed chain cannot be revoked retroactively. The remedy is rollback (§8). | n/a | n/a |
| `*  → superseded` | A new chain for the same `(subject_type, subject_id)` reaches `consumed` | system | Older chains for that subject auto-supersede. |

### 4.2 Revocation contract

- Revocation publishes to `revocation_lists` (§12.5) with TTL `revocation_propagation_max_ms` (default 5000ms).
- Every coordinator (Risk Gateway, Hot-Reload, Connector, Executor) reads `revocation_lists` on every apply-path call. A chain present in the revocation list MUST be treated as `revoked` regardless of `approval_chains.state`.
- Race: if a chain is revoked at `t1` and consumed at `t2` where `t1 < t2 < t1 + revocation_propagation_max_ms`, the consumption is treated as a `revocation_race_loss`. The audit ledger records both events. The downstream effect is *not* automatically reversed at consumption time (the action already happened); instead, the rollback contract is auto-armed (GOV-INV-14) and the operator is paged.
- Race acceptance is bounded: if `revocation_propagation_max_ms` is exceeded by the implementation under measurement, the gate fails closed (apply-path coordinators refuse to consume any chain whose `revocation_list_freshness_ms > revocation_propagation_max_ms`).

### 4.3 Expiry semantics

- Default expiry per level: L2 = 24h, L3 = 24h, L4 = 1h, L5 = 15min.
- Expiry is monotonic-clock-anchored at the coordinator. An expired chain cannot be approved further; new decisions arriving on an expired chain are rejected with `approval_chain_expired`.
- An expired-but-not-rejected chain can be re-proposed by issuing a *new* `approval_request` with the same subject. The new chain has a new `approval_chain_id` and a new `subject_binding_hash` (recomputed at the new proposal time).

### 4.4 Supersession semantics

- When a new chain for the same `(subject_type, subject_id)` reaches `consumed`, all prior chains for that subject in non-terminal states transition to `superseded`. Decisions on superseded chains are rejected with `approval_chain_superseded`.
- Supersession does NOT cancel a `consumed` chain; that is handled by rollback (§8).

---

## 5. Subject-integrity binding

This section closes the "approval-for-anything" exploit class: an approver decides on payload `P`; before apply, an actor swaps to payload `P'` that the approver never saw; the apply succeeds because the chain ID is valid. The defense is **subject-binding hash**.

### 5.1 Canonicalization rule

`subject_binding_hash = sha256(canonical_json(payload))` where `canonical_json` is JCS-style (RFC 8785) sorted-key UTF-8 with no whitespace, no insignificant trailing zeros in numbers, and string-encoded decimals for prices/sizes/leverage (per `04_API_CONTRACT_REMEDIATION.md §1.1`).

### 5.2 Apply-path guard contract

On any apply call presenting `X-Approval-Token: <approval_chain_id>`:
1. Coordinator reads the chain from DB.
2. Coordinator validates `chain.state = 'satisfied'`.
3. Coordinator validates `chain` is not in `revocation_lists`.
4. Coordinator computes `apply_payload_hash = sha256(canonical_json(about_to_apply_payload))`.
5. Coordinator asserts `apply_payload_hash == chain.subject_binding_hash`.
6. On any failure: chain transitions to `subject_drift` (or `revoked`/`expired`); apply rejected; audit event emitted; idempotency replay returns the rejection.
7. On success: chain transitions to `consumed`; apply proceeds; audit event emitted.

### 5.3 Decision-time subject binding

Approvers see `subject_binding_hash` in the GUI and in API responses (per `04_API_CONTRACT_REMEDIATION.md §3.3` evidence-pointer envelope). When an approver POSTs an `approval_decision`, the decision body includes `subject_binding_hash_seen` (§3.2). Mismatch with the chain's frozen hash = decision rejected; the chain is not advanced.

### 5.4 What "subject" means per action type

| `subject_type` | Canonical payload included in hash |
| --- | --- |
| `risk_policy_bundles` | bundle's `bundle_hash` + `applies_to` + `evaluation_order_hash` (per `05_RISK_GATEWAY_REMEDIATION.md §2.1`). |
| `universe_rollouts` | rollout's `change_set_hash` + `component_registry_version` + `live_affecting` (per `06_HOT_RELOAD_REMEDIATION.md`). |
| `connectors.live_enabled` | `(connector_id, target_state, mode)` triple. |
| `exchange_accounts.api_keys` | `(account_id, key_fingerprint_sha256, action='rotate')`. |
| `mode_state` | `(scope, target_mode, enabling_evidence_hash)`. |
| `kill_switch_state` | `(target_state, reason_code)`. |
| `users` | `(user_id, role_after, granted_capabilities_hash)`. |

For any subject type not listed, the apply-path coordinator MUST reject with `subject_type_unrecognized` and the request is logged for capability-matrix update review.

---

## 6. Actor capability matrix

Closes review finding 3 ("Policy-evaluation contract for AI actor capabilities is incomplete (MEDIUM)"). The matrix is a single, version-pinned object loaded at coordinator boot (GOV-INV-09); changes to the matrix are themselves L4 changes against `subject_type = 'capability_matrix'`.

### 6.1 Capability primitives

- `can_observe` — read-only access to the action's domain (always true at L0).
- `can_propose` — may originate an `approval_request` for the action.
- `can_approve` — may issue an `approval_decision.decision='approved'` for the action.
- `can_apply` — may consume a satisfied chain to apply the action (typically the same scope as `can_propose` but separated for audit clarity).
- `can_revoke` — may revoke a satisfied-but-unconsumed chain.
- `can_rollback` — may consume the rollback contract on a `consumed` chain.

### 6.2 Capability matrix (architecture-mandatory rows)

| Action key | actor_type | role | can_propose | can_approve | can_apply | can_revoke | can_rollback |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `monitor.threshold.update` (L2) | `human` | `admin` | yes | yes | yes | yes | yes |
| `monitor.threshold.update` (L2) | `claude` | `proposer` | yes | no | no | no | yes |
| `monitor.threshold.update` (L2) | `codex` | `reviewer` | no | no | no | no | no |
| `monitor.threshold.update` (L2) | `ollama` | `summarizer` | no | no | no | no | no |
| `risk_policy_bundle.apply` (L4 paper) | `human` | `live_admin` | yes | yes | yes | yes | yes |
| `risk_policy_bundle.apply` (L4 paper) | `human` | `admin` | yes | no | no | no | no |
| `risk_policy_bundle.apply` (L4 paper) | `claude` | `proposer` | yes | no | no | no | no |
| `risk_policy_bundle.apply` (L4 paper) | `codex` | `reviewer` | yes (review-center only) | no | no | no | no |
| `risk_policy_bundle.apply` (L4 paper) | `ollama` | `summarizer` | no | no | no | no | no |
| `risk_policy_bundle.apply` (L5 live) | `human` | `live_admin` | yes | yes | yes (post-dual-approval) | yes | yes |
| `risk_policy_bundle.apply` (L5 live) | `claude` | * | no | no | no | no | no |
| `risk_policy_bundle.apply` (L5 live) | `codex` | * | no | no | no | no | no |
| `risk_policy_bundle.apply` (L5 live) | `ollama` | * | no | no | no | no | no |
| `connector.live_enabled.set_true` (L5) | `human` | `live_admin` | yes | yes | yes (post-dual-approval) | yes | yes |
| `connector.live_enabled.set_true` (L5) | non-human | * | no | no | no | no | no |
| `mode.switch.paper_to_live` (L5) | `human` | `live_admin` | yes | yes | yes (post-dual-approval) | yes | yes |
| `mode.switch.paper_to_live` (L5) | non-human | * | no | no | no | no | no |
| `risk.kill_switch.disarm` (L5) | `human` | `live_admin` | yes | yes | yes (post-dual-approval) | yes | yes |
| `risk.kill_switch.disarm` (L5) | non-human | * | no | no | no | no | no |
| `rbac.role.grant_live_admin` (L5) | `human` | `security_admin` | yes | yes | yes (post-dual-approval, second approver `live_admin`) | yes | yes |
| `hot_reload.rollout.apply` (live) (L5) | `human` | `live_admin` | yes | yes | yes (post-dual-approval) | yes | yes |
| `hot_reload.rollout.apply` (paper) (L4) | `human` | `live_admin` | yes | yes | yes | yes | yes |
| `hot_reload.rollout.apply` (paper) (L4) | `claude` | `proposer` | yes | no | no | no | no |

Universal invariants on the matrix:
- For every L5 row, no non-human actor type has any capability set to `yes`. This is GOV-INV-02 manifest.
- For every action with `can_approve = yes`, `actor_type` is `human`. The architecture forbids non-human approval at any level (Codex blocker 6 explicit text: "approval enforcement").
- `can_approve` and `can_propose` are never simultaneously true for the same `user_id` on the same chain (separation of duties at chain-level; enforced by chain resolver, not by capability matrix).

### 6.3 Capability matrix versioning

- The matrix is itself a governed object. Mutations to the matrix are `subject_type = 'capability_matrix'` at L4.
- At apply time, the coordinator pins `capability_matrix_version` into the audit row (GOV-INV-10) so that any future replay can re-evaluate decisions against the matrix that was authoritative at the time.

---

## 7. L4/L5 hard-gate enforcement contract

This is the architecture-layer guarantee Codex Blocker 6 demands: "enforcement that L4/L5 actions cannot apply without required human approval." It is realized by *three* independent gates on every L4/L5 apply call. All three MUST pass; failure of any one rejects.

### 7.1 Gate A: Route-layer guard

Per `04_API_CONTRACT_REMEDIATION.md §2.4`:
- Route handler reads `X-Approval-Token` header. Missing = `approval_required`.
- Route handler reads `X-Live-Confirm: I-UNDERSTAND` for L5. Missing = `live_blocked`.
- Route handler resolves `actor_type` from session. Non-human originator on L5 = `actor_type_disallowed`.
- Route handler resolves the action's risk level via §2.2. If the resolved level exceeds the route's configured max-level = `risk_level_above_route_cap`.

Failure here is recorded but the chain is NOT advanced; the request never reaches the apply-path coordinator.

### 7.2 Gate B: Apply-path coordinator guard (this document, §5.2)

- Resolves the chain by ID; verifies `state = 'satisfied'`, not in `revocation_lists`, not expired.
- Verifies subject-binding hash (GOV-INV-04).
- Verifies capability matrix permits the about-to-apply actor_type+role for `can_apply` (GOV-INV-02).
- For L5: verifies dual `live_admin` decisions exist with distinct `user_id`s and fresh MFA (GOV-INV-15).
- For L5: verifies `human_origin_attestation.present = true` and the attestation is in `audit_ledger`.
- Atomically transitions chain `satisfied → consumed` and reads back to confirm. If the read-back shows `revoked` (revocation race), the apply is aborted before the side-effect; if read-back shows `consumed_by_request_id != current_request_id`, the apply is aborted (concurrent winner) and the loser idempotency-replays the winner's outcome.

### 7.3 Gate C: Domain-coordinator-internal guard (defense in depth)

Each domain coordinator (Risk Gateway, Hot-Reload, Connector, Executor) re-reads the apply contract at its own boundary and refuses any payload whose `approval_chain_id` does not exist locally OR whose chain `state != 'consumed'` OR whose `subject_binding_hash` does not match the recomputed payload hash. This is the connector-side mirror of `05_RISK_GATEWAY_REMEDIATION.md §10` extended to all governed domains.

The proof of non-bypass for Codex Blocker 6: Gate A rejects unauthorized requests at the API surface; Gate B rejects malformed/expired/drifted/replayed approval chains in the coordinator; Gate C independently re-verifies at the domain boundary against DB-resident state. Bypass requires defeating three independent guards and corrupting the audit ledger (GOV-INV-05) at multiple rows simultaneously.

### 7.4 Live-trading-blocked-by-default composition

Per `CLAUDE.md` "Default status: LIVE TRADING: BLOCKED", live trading remains blocked unless and until **two** independent L5 chains have been satisfied and consumed:
1. A `mode.switch.paper_to_live` L5 chain (subject_type = `mode_state`).
2. A `connector.live_enabled.set_true` L5 chain per connector (subject_type = `connectors`).

Both chains are independent: satisfying one without the other leaves live trading blocked. The Risk Gateway `live_gate` policy (per `05_RISK_GATEWAY_REMEDIATION.md §3.1`) reads both states and emits `block` until both are `consumed` and not subsequently rolled back.

---

## 8. Rollback validation contract

Closes review finding 4 ("Rollback validation criteria are not standardized (LOW)"). Every L4/L5 chain MUST carry a rollback contract (GOV-INV-07). This section defines the contract's minimum schema, the rollback state machine, and the criteria under which rollback is marked `verified` vs `failed`.

### 8.1 Rollback contract schema

```json
{
  "rollback_target_ref": "<subject_type>:<subject_id>:<version>",
  "rollback_validation_set": [
    "<test_vector_id>"
  ],
  "rollback_validation_thresholds": {
    "min_pass_rate": 1.0,
    "max_evaluation_window_ms": 600000
  },
  "rollback_evidence_packet_kind": "rollback_validation",
  "rollback_health_window": {
    "duration_ms": 600000,
    "metrics": [
      { "metric": "risk_decisions.allow_block_block_rate", "max": 0.05 },
      { "metric": "executions.error_rate", "max": 0.01 },
      { "metric": "monitor_center.evidence_packet_emit_rate", "min": 0.99 }
    ]
  }
}
```

### 8.2 Rollback state machine

```
not_triggered -> armed -> in_progress -> verified
                                      \-> failed
```

| Transition | Trigger | Required scope | Required approval |
| --- | --- | --- | --- |
| `not_triggered → armed` | Auto-arm condition fired (revocation race, post-apply health failure, or explicit operator request) | system / `write:approval` | none for arming; consumption requires same level as the original change. |
| `armed → in_progress` | Coordinator begins applying `rollback_target_ref` | `write:apply` | A new approval chain at the original action's level (L4 → L4 rollback chain; L5 → L5 rollback chain). |
| `in_progress → verified` | All `rollback_validation_set` test vectors pass at `>= min_pass_rate` AND all `rollback_health_window.metrics` satisfied within `duration_ms` | system | none beyond consumption. |
| `in_progress → failed` | Any test vector below threshold OR any health metric breached within window OR window expired without `verified` | system | none. Failure auto-pages and freezes further mutations to the subject until operator action. |

### 8.3 Rollback re-approval requirement

A rollback that itself requires a new approval chain (at the original level) closes the "rollback as bypass" exploit: an L5 change cannot be rolled back to a state that is itself worse without re-approval. The rollback chain's `subject_type` is the same; the `payload` is the rollback target's canonical form; the chain's `subject_binding_hash` binds the approver to the *target* state, not the change being undone.

### 8.4 Rollback verification evidence

A `rollback_validation` evidence packet (per `CLAUDE.md` evidence-integrity rule) is emitted on every `verified` and `failed` transition. The packet includes raw test-vector results, raw metric series for the health window, and pointers to the original `approval_chain_id`, the rollback `approval_chain_id`, and the audit-ledger sequence range.

---

## 9. Append-only audit ledger with tamper-evident hash chain

### 9.1 Hash-chain contract

- Each `audit_ledger` row carries `prev_hash` and `row_hash`.
- `row_hash = sha256(prev_hash || canonical_json(row_excluding_row_hash))`.
- Genesis row's `prev_hash = sha256("v2-audit-genesis-2026")` (a fixed constant; the actual literal lives in the schema migration).
- The chain is single-headed per `partition_id` (default: single global partition; see §10 for sharding).
- A nightly chain-walker recomputes every row's `row_hash` from the prior row's `prev_hash`; any mismatch is a `chain_integrity_breach` event and the ledger is read-only-quarantined until operator review.

### 9.2 Append-only at schema and runtime

- DB role grants for the application: `INSERT, SELECT` only on `audit_ledger`. No `UPDATE`, `DELETE`, `TRUNCATE` for any application role.
- A separate `audit_admin` role exists only for the chain-walker and operator-initiated forensics; it has `SELECT` only.
- DDL changes to `audit_ledger` itself are L5 against `subject_type = 'audit_ledger_ddl'` and require their own approval chain.

### 9.3 Event kinds (architecture-mandatory)

| `event_kind` | Description |
| --- | --- |
| `approval_request_open` | A new chain entered `open`. |
| `approval_decision` | Approver issued a decision. |
| `approval_chain_state` | Chain transitioned to a new state (any of §4). |
| `approval_chain_consumed` | Chain consumed by an apply. |
| `approval_chain_revoked` | Chain revoked. |
| `revocation_race_loss` | A consumption succeeded after revocation but before propagation. |
| `human_origin_attestation` | An L5 origin attestation was issued. |
| `subject_drift_detected` | An apply or decision was rejected due to subject hash mismatch. |
| `mfa_freshness_failed` | A decision was rejected for stale MFA. |
| `rollback_armed` | A rollback was auto-armed or operator-armed. |
| `rollback_verified` | A rollback completed verification. |
| `rollback_failed` | A rollback failed verification. |
| `capability_matrix_change` | The capability matrix version transitioned. |
| `audit_ddl_change` | DDL on `audit_ledger` was applied (always L5). |
| `chain_integrity_breach` | The nightly chain-walker found a hash mismatch or sequence gap. |
| `governance_policy_load` | Coordinator booted and loaded matrix + policy versions. |
| `governance_policy_unloaded` | Coordinator rejected an apply because matrix or policy was not loaded. |
| `live_block_applied` | A coordinator emitted a live-block due to mode state. |
| `live_block_lifted` | A coordinator detected `mode_state = live` AND all preconditions satisfied. |

### 9.4 Cross-references and lineage

Per GOV-INV-10, every audit row carries the lineage tuple. Where a row references a foreign object (a `risk_policy_bundles` row, a `universe_rollouts` row, a `connectors` row, etc.), the row stores the foreign ID in `subject_id` AND the foreign object's canonical hash at write time in `subject_payload_hash_snapshot`. This makes audit-ledger replay self-contained: the audit can be verified without dereferencing foreign tables (which may have superseded values).

---

## 10. Sequence-monotonicity and gap detection

### 10.1 Sequence assignment

- `sequence_id` is a strictly monotonic `BIGINT` per partition, assigned by a single writer (DB serial column `BIGSERIAL` with `BIGINT IDENTITY ALWAYS` semantics; alternatively a Redis-backed coordinator lease for sharded partitions).
- Each `INSERT` into `audit_ledger` assigns the next sequence value within the active partition.
- `partition_id` is `'global'` in the default deployment; sharding is allowed but every shard MUST have its own gapless chain head.

### 10.2 Gap detection contract

- The nightly chain-walker performs `SELECT MIN(sequence_id), MAX(sequence_id), COUNT(*) FROM audit_ledger WHERE partition_id = ?` per partition.
- Assertion: `MAX - MIN + 1 == COUNT`. If false, a `chain_integrity_breach` is emitted, the partition is set to read-only, and an operator page fires.
- The walker also validates `row_hash` recomputation against `prev_hash`. Any mismatch = same outcome.

### 10.3 Quarantine semantics

- A quarantined partition MUST stop accepting INSERTs (DB-level; revoke `INSERT` on the role for that partition).
- All coordinators reading the quarantined partition's chain head transition to `accepting_approvals=false` (GOV-INV-09 manifest). New approval requests are rejected with `audit_ledger_quarantined`. Existing satisfied chains continue to be apply-eligible until operator intervention.

### 10.4 Out-of-order arrivals

- Out-of-order writes are not permitted: the writer MUST ensure all decisions, state transitions, and consumptions are serialized through the partition writer's lock or DB serial. If the implementation uses Redis-leased coordinator writers, the coordinator MUST hold the lease for the duration of the write.
- Writers that lose the lease MUST drop the write and re-propose the operation against the new lease holder.

---

## 11. Cross-domain governance binding

Closes Codex Blocker 6 across the entire control surface: every L2+ change in V2 binds through the same approval object. This section enumerates the bindings.

### 11.1 Binding to Risk Policy bundles (`05_RISK_GATEWAY_REMEDIATION.md §2.2`)

- Bundle transitions `validated → approved` and `approved → staged` and `staged → applied` and `applied → rolled_back` each require an `approval_chain` whose `subject_type = 'risk_policy_bundles'` and whose `subject_id = policy_bundle_id` and whose `subject_binding_hash` includes `bundle_hash`, `applies_to`, `evaluation_order_hash` per §5.4.
- The Risk Gateway's bundle-apply path is Gate C for these chains (§7.3). It re-reads `approval_chains.state = 'consumed'` and `subject_binding_hash` before activating the bundle.

### 11.2 Binding to Hot-Reload rollouts (`06_HOT_RELOAD_REMEDIATION.md` HR INV-08)

- Rollouts whose `live_affecting=true` require an L4 (paper) or L5 (live) approval chain whose `subject_type = 'universe_rollouts'` and whose `subject_id = universe_rollout_id` and whose `subject_binding_hash` includes `change_set_hash` and `component_registry_version`.
- The Hot-Reload coordinator's apply path is Gate C.

### 11.3 Binding to Connector live-enable (`04_API_CONTRACT_REMEDIATION.md §6.5`)

- `PUT /connectors/{id}/live_enabled` with `target_state=true` requires an L5 chain whose `subject_type = 'connectors'`, `subject_id = connector_id`, and `subject_binding_hash` includes `(connector_id, target_state, mode)`.
- The Connector itself is Gate C; it independently reads `approval_chains` and `revocation_lists` before flipping its local `live_enabled` flag.

### 11.4 Binding to API key rotation (`04_API_CONTRACT_REMEDIATION.md §6.7`)

- `POST /exchange_accounts/{id}/api_keys` requires an L5 chain whose `subject_type = 'exchange_accounts'`, `subject_id = exchange_account_id`, and `subject_binding_hash` includes `(account_id, key_fingerprint_sha256, action='rotate')`.
- The Connector's secret-provider boundary (per future RBAC remediation file) is Gate C.

### 11.5 Binding to mode state and kill-switch

- `mode.switch.paper_to_live` (L5) and `risk.kill_switch.disarm` (L5) bind through `subject_type IN {'mode_state','kill_switch_state'}` per §5.4.
- The Risk Gateway is Gate C for kill-switch state (per `05_RISK_GATEWAY_REMEDIATION.md §8` persistence contract).

### 11.6 Binding to RBAC mutations

- `rbac.role.grant_live_admin` (L5) binds through `subject_type = 'users'` with `subject_binding_hash` including `(user_id, role_after, granted_capabilities_hash)`.
- The route handler for RBAC mutations is Gate A; the user-service is Gate C.

### 11.7 Universal binding rule

For every governed mutation in V2, exactly one row in §2.2 names its action key, exactly one row in §6.2 names its capability per actor_type+role, and exactly one row in §5.4 names its subject canonical form. Adding a new governed mutation requires updating all three at L4 (capability matrix change) before the mutation can be applied. Coordinators that encounter an unrecognized action key reject with `action_key_unrecognized`.

---

## 12. Persistence — DDL-level fragments

The architecture stub names `audit_events`, `ai_action_changes`, and `approvals`. Codex requires structured persistence. This section gives normative DDL fragments. They are not executable migrations but specify shape and constraints; an implementation may translate to its DB dialect.

### 12.1 `approval_requests`

```sql
CREATE TABLE approval_requests (
  approval_request_id      UUID PRIMARY KEY,
  approval_chain_id        UUID NOT NULL,
  request_id               UUID NOT NULL,
  action_key               TEXT NOT NULL,
  risk_level               TEXT NOT NULL CHECK (risk_level IN ('L0','L1','L2','L3','L4','L5')),
  subject_type             TEXT NOT NULL,
  subject_id               UUID NOT NULL,
  subject_binding_hash     TEXT NOT NULL,
  payload_canonical_json   TEXT NOT NULL,
  originator_actor_type    TEXT NOT NULL CHECK (originator_actor_type IN ('human','claude','codex','ollama','system')),
  originator_actor_id      TEXT NOT NULL,
  originator_session_id    TEXT,
  originator_mfa_assertion TEXT,
  originator_client_ip     TEXT,
  human_origin_attestation_id TEXT,
  required_approvals_json  JSONB NOT NULL,
  rollback_contract_json   JSONB,
  evidence_pointers_json   JSONB,
  approval_policy_version  TEXT NOT NULL,
  capability_matrix_version TEXT NOT NULL,
  created_ts_ms            BIGINT NOT NULL,
  expiry_ts_ms             BIGINT NOT NULL,
  CONSTRAINT chk_l5_attestation CHECK (
    risk_level <> 'L5' OR human_origin_attestation_id IS NOT NULL
  ),
  CONSTRAINT chk_l5_human_originator CHECK (
    risk_level <> 'L5' OR originator_actor_type = 'human'
  ),
  CONSTRAINT chk_l4_l5_rollback CHECK (
    risk_level NOT IN ('L4','L5') OR rollback_contract_json IS NOT NULL
  )
);
CREATE UNIQUE INDEX approval_requests_chain_unique ON approval_requests (approval_chain_id);
CREATE INDEX approval_requests_subject_idx ON approval_requests (subject_type, subject_id, created_ts_ms);
```

### 12.2 `approval_decisions`

```sql
CREATE TABLE approval_decisions (
  approval_decision_id     UUID PRIMARY KEY,
  approval_chain_id        UUID NOT NULL REFERENCES approval_requests (approval_chain_id),
  decision                 TEXT NOT NULL CHECK (decision IN ('approved','rejected','abstained','revoked')),
  decision_reason          TEXT NOT NULL,
  approver_actor_type      TEXT NOT NULL CHECK (approver_actor_type = 'human'),
  approver_user_id         TEXT NOT NULL,
  approver_role            TEXT NOT NULL,
  approver_session_id      TEXT NOT NULL,
  approver_mfa_assertion   TEXT NOT NULL,
  approver_mfa_freshness_ms BIGINT NOT NULL,
  approver_client_ip       TEXT NOT NULL,
  subject_binding_hash_seen TEXT NOT NULL,
  evidence_pointers_json   JSONB,
  decision_ts_ms           BIGINT NOT NULL
);
CREATE INDEX approval_decisions_chain_idx ON approval_decisions (approval_chain_id, decision_ts_ms);
-- DB role grants exclude UPDATE and DELETE on this table for application roles.
```

### 12.3 `approval_chains`

```sql
CREATE TABLE approval_chains (
  approval_chain_id        UUID PRIMARY KEY,
  approval_request_id      UUID NOT NULL UNIQUE REFERENCES approval_requests (approval_request_id),
  subject_type             TEXT NOT NULL,
  subject_id               UUID NOT NULL,
  subject_binding_hash     TEXT NOT NULL,
  risk_level               TEXT NOT NULL,
  required_approvals_resolved_json JSONB NOT NULL,
  state                    TEXT NOT NULL CHECK (state IN (
    'draft','open','partially_satisfied','satisfied','rejected',
    'expired','subject_drift','superseded','consumed','revoked'
  )),
  consumed_by_request_id   UUID,
  consumed_ts_ms           BIGINT,
  rollback_contract_json   JSONB,
  rollback_state           TEXT NOT NULL DEFAULT 'not_triggered' CHECK (rollback_state IN (
    'not_triggered','armed','in_progress','verified','failed'
  )),
  expiry_ts_ms             BIGINT NOT NULL,
  approval_policy_version  TEXT NOT NULL,
  capability_matrix_version TEXT NOT NULL,
  audit_chain_version      TEXT NOT NULL,
  created_ts_ms            BIGINT NOT NULL,
  last_transition_ts_ms    BIGINT NOT NULL
);
CREATE INDEX approval_chains_state_idx ON approval_chains (state, last_transition_ts_ms);
CREATE INDEX approval_chains_subject_idx ON approval_chains (subject_type, subject_id, state);
```

### 12.4 `audit_ledger`

```sql
CREATE TABLE audit_ledger (
  sequence_id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  partition_id             TEXT NOT NULL DEFAULT 'global',
  audit_event_id           UUID NOT NULL UNIQUE,
  event_kind               TEXT NOT NULL,
  actor_type               TEXT NOT NULL,
  actor_id                 TEXT NOT NULL,
  subject_type             TEXT,
  subject_id               UUID,
  subject_payload_hash_snapshot TEXT,
  approval_chain_id        UUID,
  parent_event_id          UUID,
  payload_json             JSONB NOT NULL,
  evidence_pointers_json   JSONB,
  capability_matrix_version TEXT NOT NULL,
  approval_policy_version  TEXT NOT NULL,
  audit_chain_version      TEXT NOT NULL,
  prev_hash                TEXT NOT NULL,
  row_hash                 TEXT NOT NULL,
  created_ts_ms            BIGINT NOT NULL
);
CREATE INDEX audit_ledger_subject_idx ON audit_ledger (subject_type, subject_id, sequence_id);
CREATE INDEX audit_ledger_chain_idx ON audit_ledger (approval_chain_id, sequence_id);
CREATE INDEX audit_ledger_partition_seq_idx ON audit_ledger (partition_id, sequence_id);
-- DB role grants: INSERT, SELECT only for application roles.
-- DDL changes to this table are L5 (subject_type='audit_ledger_ddl').
```

### 12.5 `revocation_lists`

```sql
CREATE TABLE revocation_lists (
  approval_chain_id        UUID PRIMARY KEY REFERENCES approval_chains (approval_chain_id),
  revoked_by_user_id       TEXT NOT NULL,
  revoked_reason           TEXT NOT NULL,
  revoked_ts_ms            BIGINT NOT NULL,
  propagation_max_ms       BIGINT NOT NULL DEFAULT 5000,
  expiry_ts_ms             BIGINT NOT NULL
);
CREATE INDEX revocation_lists_expiry_idx ON revocation_lists (expiry_ts_ms);
```

### 12.6 `audit_chain_heads`

```sql
CREATE TABLE audit_chain_heads (
  partition_id             TEXT PRIMARY KEY,
  last_sequence_id         BIGINT NOT NULL,
  last_row_hash            TEXT NOT NULL,
  last_walked_ts_ms        BIGINT NOT NULL,
  walker_state             TEXT NOT NULL CHECK (walker_state IN ('healthy','breach','quarantined'))
);
```

---

## 13. Audit ledger event envelope

```json
{
  "schema_version": "1.0.0",
  "audit_event_id": "uuid-v7",
  "sequence_id": 12345,
  "partition_id": "global",
  "event_kind": "approval_chain_consumed",
  "actor": {
    "actor_type": "human",
    "actor_id": "user_id",
    "session_id": "string",
    "client_ip": "string"
  },
  "subject": {
    "subject_type": "risk_policy_bundles",
    "subject_id": "uuid-v7",
    "subject_payload_hash_snapshot": "sha256:<hex>"
  },
  "approval_chain_id": "uuid-v7",
  "parent_event_id": "uuid-v7|null",
  "payload": { /* event-kind-specific body */ },
  "evidence_pointers": [
    {"kind": "redis|log|db|file|monitor_snapshot|evidence_packet", "ref": "string"}
  ],
  "capability_matrix_version": "2026.04.30-001",
  "approval_policy_version": "2026.04.30-001",
  "audit_chain_version": "1",
  "prev_hash": "sha256:<hex>",
  "row_hash": "sha256:<hex>",
  "created_ts_ms": 1735689700000
}
```

`row_hash = sha256(prev_hash || canonical_json(row_excluding_row_hash))`. The chain-walker (§10.2) recomputes this for every row.

---

## 14. Test-vector matrix

These vectors are normative: any V2 governance scaffold MUST pass every vector before Codex Blocker 6 is closed. Vectors are organized by gate. Each vector specifies (a) input fixture name, (b) expected verdict, (c) expected error/audit code, (d) replay re-determinism check.

For brevity, fixtures are referenced by stable IDs; their canonical JSON forms live alongside the implementation under `v2/governance/test_fixtures/` (created during scaffold, not in this document).

### 14.1 Boot / policy load

| ID | Setup | Expected verdict | Expected code |
| --- | --- | --- | --- |
| TV-GOV-BOOT-01 | Coordinator boot, no `capability_matrix_version` loaded | block | `governance_policy_unloaded` |
| TV-GOV-BOOT-02 | Coordinator boot, matrix loaded but hash mismatch | block | `capability_matrix_hash_mismatch` |
| TV-GOV-BOOT-03 | Two coordinators booted with different `capability_matrix_version` | block (newer takes; older quarantines) | `capability_matrix_version_skew` |
| TV-GOV-BOOT-04 | DB unreachable on boot | block (default deny) | `audit_ledger_unloadable` |

### 14.2 Approval state machine

| ID | Setup | Expected verdict | Expected state |
| --- | --- | --- | --- |
| TV-GOV-SM-01 | Open chain, single L4 decision approved | satisfied (count=1, required=1) | `satisfied` |
| TV-GOV-SM-02 | Open L5 chain, one L5 approval decision | partially_satisfied | `partially_satisfied` |
| TV-GOV-SM-03 | Open L5 chain, two L5 approvals same `user_id` | rejected (must_be_distinct) | `partially_satisfied` (second rejected) |
| TV-GOV-SM-04 | Open L5 chain, two L5 approvals distinct `user_id`s | satisfied | `satisfied` |
| TV-GOV-SM-05 | Open chain, expiry passed, decision arrives | rejected | `expired` |
| TV-GOV-SM-06 | Open chain, originator submits own approval | rejected (separation of duties) | unchanged |
| TV-GOV-SM-07 | Satisfied chain, apply with valid hash | consumed | `consumed` |
| TV-GOV-SM-08 | Consumed chain, second apply with same `request_id` | idempotent replay | `consumed` |
| TV-GOV-SM-09 | Consumed chain, second apply with different `request_id` | rejected | `approval_chain_already_consumed` |
| TV-GOV-SM-10 | Satisfied chain, revoked, apply attempt within propagation window | rejected (race) | `approval_chain_revoked` |
| TV-GOV-SM-11 | Satisfied chain, revoked, apply attempt after propagation window | rejected cleanly | `approval_chain_revoked` |
| TV-GOV-SM-12 | Satisfied chain, new chain for same subject reaches consumed | superseded | `superseded` |

### 14.3 Subject-binding hash

| ID | Setup | Expected verdict | Expected code |
| --- | --- | --- | --- |
| TV-GOV-SUB-01 | Apply payload identical to proposal | allow | — |
| TV-GOV-SUB-02 | Apply payload differs in one field (whitespace re-normalized) | allow | — |
| TV-GOV-SUB-03 | Apply payload differs in one numeric field | block | `subject_drift_detected` |
| TV-GOV-SUB-04 | Apply payload differs in one field (extra unrelated key) | block | `subject_drift_detected` |
| TV-GOV-SUB-05 | Decision body presents wrong `subject_binding_hash_seen` | reject decision | `subject_drift_detected` |
| TV-GOV-SUB-06 | L5 chain, payload changed between two L5 approvals | second decision rejected | `subject_drift_detected` |

### 14.4 Capability matrix

| ID | Setup | Expected verdict | Expected code |
| --- | --- | --- | --- |
| TV-GOV-CAP-01 | `actor_type=claude` proposes L5 | block | `actor_type_disallowed` |
| TV-GOV-CAP-02 | `actor_type=ollama` proposes L4 risk_policy_bundle.apply | block | `actor_type_disallowed` |
| TV-GOV-CAP-03 | `actor_type=codex` proposes L4 hot_reload via review-center | allow proposal | — |
| TV-GOV-CAP-04 | `actor_type=human` role=`admin` approves L5 | block | `role_insufficient` |
| TV-GOV-CAP-05 | `actor_type=human` role=`live_admin` approves L5 | allow | — |
| TV-GOV-CAP-06 | Capability matrix version mismatch between proposal and apply | block | `capability_matrix_version_drift` |

### 14.5 L4 / L5 hard gate

| ID | Setup | Expected verdict | Expected code |
| --- | --- | --- | --- |
| TV-GOV-L4-01 | L4 apply, no chain | block | `approval_required` |
| TV-GOV-L4-02 | L4 apply, chain in `partially_satisfied` | block | `approval_chain_state_invalid` |
| TV-GOV-L4-03 | L4 apply, chain `satisfied`, hash matches | allow | — |
| TV-GOV-L5-01 | L5 apply, no `X-Live-Confirm` header | block | `live_blocked` |
| TV-GOV-L5-02 | L5 apply, single L5 approval | block | `approval_chain_state_invalid` |
| TV-GOV-L5-03 | L5 apply, dual L5 approvals same user | block | `approval_chain_state_invalid` |
| TV-GOV-L5-04 | L5 apply, dual L5 approvals distinct, no MFA freshness | block | `mfa_freshness_failed` |
| TV-GOV-L5-05 | L5 apply, dual approvals, fresh MFA, no `human_origin_attestation` | block | `human_origin_attestation_missing` |
| TV-GOV-L5-06 | L5 apply, dual approvals, fresh MFA, attestation, originator non-human | block | `actor_type_disallowed` |
| TV-GOV-L5-07 | L5 apply, all conditions met | allow | — |
| TV-GOV-L5-08 | L5 apply, all conditions met, but `mode_state.live_block=true` | block (Gate C) | `live_block_active` |

### 14.6 Audit hash chain

| ID | Setup | Expected outcome |
| --- | --- | --- |
| TV-GOV-AUD-01 | Chain-walker on healthy ledger | all rows verify; walker state `healthy` |
| TV-GOV-AUD-02 | Single byte-flipped row | walker emits `chain_integrity_breach`, partition quarantined |
| TV-GOV-AUD-03 | Sequence gap (synthetic delete) | walker emits `chain_integrity_breach`, partition quarantined |
| TV-GOV-AUD-04 | `UPDATE` attempt by application role | DB rejects (privilege); audit row emitted by DB-level deny logger |
| TV-GOV-AUD-05 | `DELETE` attempt by application role | DB rejects |
| TV-GOV-AUD-06 | Two coordinators race-write same `sequence_id` | second write fails on unique constraint; coordinator retries |
| TV-GOV-AUD-07 | Genesis row missing | walker fails to start; partition `quarantined` |
| TV-GOV-AUD-08 | DDL change to `audit_ledger` without L5 chain | rejected by route guard |

### 14.7 Rollback validation

| ID | Setup | Expected outcome |
| --- | --- | --- |
| TV-GOV-RB-01 | L4 chain, no rollback contract | proposal rejected; `rollback_contract_required` |
| TV-GOV-RB-02 | L4 chain, rollback contract present, post-apply health within window | rollback `not_triggered` |
| TV-GOV-RB-03 | L4 chain, post-apply health metric breach | rollback auto-armed; `rollback_armed` |
| TV-GOV-RB-04 | Rollback in_progress, all validation vectors pass | `verified`; `rollback_verified` |
| TV-GOV-RB-05 | Rollback in_progress, one validation vector below threshold | `failed`; `rollback_failed` |
| TV-GOV-RB-06 | Rollback in_progress, health window expires without verification | `failed`; `rollback_failed` |
| TV-GOV-RB-07 | L5 rollback, no new L5 approval chain | rejected; `rollback_approval_required` |

### 14.8 Revocation race

| ID | Setup | Expected outcome |
| --- | --- | --- |
| TV-GOV-REV-01 | Revoke at t1, consume at t2 < t1 + propagation_max_ms | `revocation_race_loss` audit + auto-arm rollback |
| TV-GOV-REV-02 | Revoke at t1, consume at t2 >= t1 + propagation_max_ms | consumption rejected cleanly |
| TV-GOV-REV-03 | Revocation list freshness > propagation_max_ms | apply-path rejects with `revocation_list_stale` (fail closed) |

### 14.9 Cross-domain binding

| ID | Setup | Expected outcome |
| --- | --- | --- |
| TV-GOV-XD-01 | Risk Gateway bundle apply with no chain | rejected by Gate C; `governance_chain_missing` |
| TV-GOV-XD-02 | Hot-Reload live_affecting rollout with L4 paper chain in live mode | rejected; `governance_chain_level_insufficient` |
| TV-GOV-XD-03 | Connector `live_enabled.set_true` with L4 chain | rejected; `governance_chain_level_insufficient` |
| TV-GOV-XD-04 | Mode switch paper→live, only one of two L5 chains satisfied (mode but not connector) | rejected at `live_gate`; `live_block_partial_l5` |
| TV-GOV-XD-05 | API key rotation L5 with valid chain but stale (>15min) | rejected; `approval_chain_expired` |

### 14.10 Determinism (GOV-INV-03)

| ID | Setup | Check |
| --- | --- | --- |
| TV-GOV-DET-01 | Replay each TV-GOV-SM-* with identical inputs and frozen clock | byte-equal `state`, `failing_check`, `quorum_satisfied` |
| TV-GOV-DET-02 | Replay TV-GOV-AUD-* | byte-equal `row_hash` recomputation |
| TV-GOV-DET-03 | Replay TV-GOV-RB-* with frozen metric series | byte-equal `rollback_state` outcome |

### 14.11 Non-bypass invariants (GOV-INV-01..15)

| ID | Setup | Assertion |
| --- | --- | --- |
| TV-GOV-INV-01 | Insert governed mutation row with `risk_level >= 'L2'` and no satisfied chain | rejected by service-layer guard + nightly assertion |
| TV-GOV-INV-02 | Static analysis: enumerate all L5-targeting routes | every route has `actor_type=='human'` route guard |
| TV-GOV-INV-03 | Service-layer guard re-verifies subject hash on every apply | static check: every apply path calls subject-hash recompute |
| TV-GOV-INV-04 | DB role test: application role attempts UPDATE on `audit_ledger` | rejected by privilege |
| TV-GOV-INV-05 | DB role test: application role attempts DELETE on `approval_decisions` | rejected by privilege |
| TV-GOV-INV-06 | Static check: connector code does not call apply path without `approval_chain_id` | static analyzer asserts |
| TV-GOV-INV-07 | Mode flag = `paper`, L5 action proposed | apply path still requires L5 chain (level cannot be downgraded by mode) |

---

## 15. Audit and evidence-packet requirements

### 15.1 Per-decision audit

Every `approval_decision` write:
- One `approval_decisions` row.
- One `audit_ledger` row of `event_kind = 'approval_decision'` referencing the decision row.
- Zero or one `audit_ledger` row of `event_kind = 'approval_chain_state'` if the decision caused a state transition.

### 15.2 Per-apply audit

Every `consumed` transition:
- One `audit_ledger` row of `event_kind = 'approval_chain_consumed'`.
- One `audit_ledger` row of `event_kind = 'approval_chain_state'`.
- One `evidence_packet` of `packet_type = 'governance_apply'` containing the chain ID, the subject payload at apply time (canonical), the approver decisions, and the audit-ledger sequence range.

### 15.3 Hourly evidence packet

A scheduled `evidence_packet` of `packet_type = 'hourly_governance'` emits:
- Counts of chains by terminal state.
- L4/L5 apply counts and rollback rate.
- Subject-drift detections.
- Revocation race losses.
- Chain-walker state per partition.
- MFA freshness failure counts.
- Distribution of `decision_ts_ms - approval_request.created_ts_ms` (approval latency).

This packet is the primary surface for the Monitor Center's "AI Governance" panel.

### 15.4 Chain-integrity-breach packet

Every `chain_integrity_breach` event MUST emit a `chain_integrity_breach` evidence packet within `breach_packet_max_latency_ms` (default 30000ms). The packet contains the breach detection details, the affected sequence range, the recomputed vs stored hashes, and pointers to the operator runbook. The Monitor Center surfaces the packet on a dedicated page (`Audit Ledger → Integrity Status`).

### 15.5 Rollback validation packet

Every `verified` and `failed` rollback transition emits the `rollback_validation` evidence packet defined in §8.4.

---

## 16. Traceability — Codex Blocker 6 sub-claims to closing sections

The actual Codex CLI output (lines 22–23 of `12_ACTUAL_CODEX_CLI_ARCHITECTURE_REVIEW_OUTPUT.md`) enumerates the missing items. Each is closed below. Provisional review (`08_AI_GOVERNANCE_REVIEW.md`) findings are also mapped.

| Codex / review sub-claim | Closed by |
| --- | --- |
| "tamper-evidence/hash chaining" | §1 (GOV-INV-05), §9 (chain contract), §12.4 (`prev_hash`/`row_hash` columns), §14.6 (chain-walker test vectors) |
| "immutable sequence semantics" | §1 (GOV-INV-06), §10 (sequence assignment, gap detection, quarantine), §12.4 (`sequence_id` IDENTITY ALWAYS), §14.6 (TV-GOV-AUD-03) |
| "approval subject integrity" | §1 (GOV-INV-04), §3 (subject_binding_hash in request and decision), §5 (subject-integrity binding), §12.1–12.3 (hash columns), §14.3 (subject-binding test vectors) |
| "approval state transitions" | §3 (object model), §4 (state machine, expiry, revocation, supersession), §12.3 (`approval_chains.state` enum), §14.2 (state-machine vectors) |
| "enforcement that L4/L5 actions cannot apply without required human approval" | §1 (GOV-INV-01, GOV-INV-02, GOV-INV-15), §2 (level taxonomy), §6 (capability matrix), §7 (three-gate hard-gate contract), §11 (cross-domain binding), §14.5 (L4/L5 vectors), §14.9 (cross-domain binding vectors) |
| Provisional finding 1 — "L4 mandatory human approval not explicit enough" | §2.1 (L4 row), §6.2 (capability matrix L4 rows), §7 (three-gate enforcement), §11 (cross-domain binding) |
| Provisional finding 2 — "Approval depth model is under-specified" | §2.1 (depth column per level), §3.1 (`required_approvals` array), §3.3 (`required_approvals_resolved`), §14.2 (TV-GOV-SM-03/04 dual-distinct test vectors) |
| Provisional finding 3 — "Policy-evaluation contract for AI actor capabilities is incomplete" | §6 (capability primitives + matrix), §6.3 (matrix versioning), §14.4 (capability test vectors) |
| Provisional finding 4 — "Rollback validation criteria are not standardized" | §8 (rollback validation contract, state machine, re-approval requirement, evidence packet), §14.7 (rollback test vectors) |

---

## 17. Requirement coverage

This document satisfies the following V2 requirements (per `00_REQUIREMENTS_INDEX_AND_NORMALIZATION.md`):

| Requirement | Coverage |
| --- | --- |
| 01 Observability and attribution | §13 (audit envelope), §15 (evidence packets) |
| 03 Prediction → signal → decision ID chain | §1 (GOV-INV-10 lineage tuple in audit), §13 (lineage in event envelope) |
| 08 / 18 Pre-V2 build exit criteria | §14 (test-vector matrix is the explicit gate for Codex Blocker 6) |
| 10 Enterprise website product | §15.3 (Monitor Center governance panel surface) |
| 13 Multi-trader fleet | §11 (cross-domain binding includes fleet admission) |
| 12 Multi-exchange connectors | §11.3 (connector live-enable binding) |
| 15 Public hosting and security | §1 (GOV-INV-08 non-repudiation), §6 (capability matrix), §7 (three-gate enforcement) |
| 20 AI supervision and autonomous change governance | §2 (level taxonomy), §6 (capability matrix), §7 (L4/L5 hard gate), §9 (audit chain), §11 (cross-domain binding) — this is the central requirement for this document |
| 21 Updated enterprise architecture readiness | §16 traceability table demonstrates remediation closes Codex Blocker 6 |

---

## 18. Out-of-scope (deferred to other remediation files)

- Lineage DDL in `feature_snapshots`/`feature_values` (consolidated Codex blocker #1, #2) — covered in future remediation file; this document references the lineage tuple shape but does not finalize feature-snapshot persistence.
- Confidence explainability schema (consolidated Codex blocker #3) — future file.
- Risk Gateway evaluation invariants (consolidated Codex blocker #4) — closed by `05_RISK_GATEWAY_REMEDIATION.md`; this document binds Risk-Gateway transitions through the approval chain in §11.1.
- Hot-reload per-component ack persistence (consolidated Codex blocker #5) — closed by `06_HOT_RELOAD_REMEDIATION.md`; this document binds Hot-Reload `live_affecting` rollouts through the approval chain in §11.2.
- RBAC user/session/MFA tables (consolidated Codex blocker #7) — partially companion of `04_API_CONTRACT_REMEDIATION.md §2`, finalized in future file. This document uses the RBAC primitives defined there (scope tokens, MFA assertions) but does not redefine them.
- Trainer liveness exit-criterion artifact (consolidated Codex blocker #8) — future file (not AI governance).

This file does not attempt to close those blockers; it ensures its own contracts (§5 subject-integrity binding, §6 capability matrix, §7 three-gate enforcement, §9 hash-chain audit) are written so they compose correctly with those files.

---

## 19. Gate recommendation

Codex Blocker 6 ("Audit immutability and approval enforcement are not strong enough") requires:
- tamper-evident hash chain → §9, §12.4, §14.6
- immutable sequence semantics → §10, §12.4, §14.6
- approval subject integrity → §5, §12.1–12.3, §14.3
- approval state transitions → §3, §4, §12.3, §14.2
- enforcement that L4/L5 cannot apply without required human approval → §1 (GOV-INV-01, -02, -15), §2, §6, §7, §11, §14.5, §14.9

If the V2 scaffold implements §1–§15 verbatim and a re-run of Codex CLI architecture review confirms the test-vector matrix is enforced (e.g. via CI assertions on the `v2/governance/test_fixtures/` scaffold AND the chain-walker is wired into the nightly job AND DB role grants are configured to deny `UPDATE`/`DELETE` on `audit_ledger` and `approval_decisions` for application roles), Codex Blocker 6 is closeable.

Until that re-review returns explicit PASS/GO, **V2 build remains NO-GO** per the consolidated reconciliation. This document is an architecture-layer remediation only; it does not constitute build approval, live-trading approval, autonomous L4/L5 authority, or any mutation of the legacy runtime. Per `CLAUDE.md` defaults, LIVE TRADING remains BLOCKED; the contract here encodes how the block is lifted (two independent L5 chains plus three-gate enforcement), not the lifting itself.