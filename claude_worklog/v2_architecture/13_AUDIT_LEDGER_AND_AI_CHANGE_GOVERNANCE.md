# 13 — Audit Ledger and AI Change Governance

> Canonical governance and audit-ledger contract for V2. Replaces the
> prior 32-line stub. Source remediation:
> `claude_worklog/v2_architecture_remediation/07_AI_GOVERNANCE_REMEDIATION.md`.
> Defines L0–L5 risk taxonomy, approval state machine, subject-binding,
> tamper-evident audit chain, and three-gate L4/L5 enforcement.

## 1. Non-bypass invariants (GOV-INV-01..15)

1. GOV-INV-01 — Every L1+ action requires an approval chain referenced in the request envelope.
2. GOV-INV-02 — Approval chains bind to `(action_class, subject_canonical_form, body_hash, actor_subject)`.
3. GOV-INV-03 — Chain consumption is single-use; replay rejected (`approval.not_consumed` on second use).
4. GOV-INV-04 — L4 requires one approver from the action-specific approver pool ≠ requester.
5. GOV-INV-05 — L5 requires two distinct approvers ≠ requester ≠ each other, both step-up authenticated within window.
6. GOV-INV-06 — Subject canonical form is computed server-side; client-supplied subjects are rejected.
7. GOV-INV-07 — Audit ledger rows are append-only; UPDATE/DELETE forbidden by DB role.
8. GOV-INV-08 — Hash chain is per-stream and globally anchored; gap detection runs continuously.
9. GOV-INV-09 — Approver actions emit their own audit rows bound to the same chain id.
10. GOV-INV-10 — Rollback of a consumed L5 chain emits a new chain (rollback chain) at L5; silent rollback forbidden.
11. GOV-INV-11 — Subject mismatch at consumption → `approval.subject_mismatch`, never silent allow.
12. GOV-INV-12 — Time-bounded chain validity; expired chains require fresh approval.
13. GOV-INV-13 — Cross-domain governance bindings (§11) verified at consumption.
14. GOV-INV-14 — Capability matrix evaluated at request and at consumption (defense-in-depth).
15. GOV-INV-15 — Hash chain integrity is verified at startup and on each write; failure trips kill-switch.

## 2. Risk-level taxonomy and action-to-level catalog

| Level | Definition | Examples |
| --- | --- | --- |
| L0 | Read-only | view audit, list signals |
| L1 | Self-mutating, paper-only | personal pref, scratch strategy in paper |
| L2 | Mutating, cross-tenant, paper-only | shared strategy edit, monitor add/remove |
| L3 | Sensitive admin without live impact | role grant within tenant, RBAC scope, hot-reload T2/T3 |
| L4 | Pre-live mutation | risk policy bundle activation, hot-reload T0/T1, kill-switch maintenance entry |
| L5 | Live-trading-affecting | live API key add/activate, mode switch paper→live, leverage cap raise above policy ceiling, kill-switch re-arm after trip, connector live_enabled=true, daily loss limit raise, mandatory_stop disable, hedge/DCA enable, ADJUST_LEVERAGE enable |

Action-to-level catalog (≥20 actions) lives in §A1 of source remediation; canonical mapping above.

## 3. Approval workflow object model

```
ApprovalChain {
  chain_id, action_class, subject_canonical_form, body_hash,
  required_level, requester_subject, requester_attestation,
  required_approvers: int, approver_pool_id,
  state: 'pending'|'partially_approved'|'approved'|'consumed'|'rejected'|'expired'|'rolled_back',
  expires_at, created_at, consumed_at,
  audit_chain_anchor
}
ApprovalAssertion {
  assertion_id, chain_id, approver_subject, approver_step_up_ref,
  decision: 'approve'|'reject', comment, asserted_at
}
```

## 4. Approval state machine

`pending → partially_approved → approved → consumed → (rolled_back)?`
Terminal alts: `rejected`, `expired`.
Transitions:
- approver assertion (per §5/§6) → moves toward `approved`.
- Mutation handler invokes `consume(chain_id, body_hash, subject_canonical_form, actor_subject)` atomically with handler commit.
- Rollback workflow: a consumed L5 chain may produce a `rolled_back` annotation only via a NEW L5 rollback chain.

## 5. Subject-integrity binding

`subject_canonical_form` is computed server-side via the type-specific canonicalizer (e.g., for `connector.live_enabled.set_true`: `connector_id || target_state || environment_id`).
Body hash binds the entire request body. Consumption is atomic with state mutation.

## 6. Actor capability matrix

| Subject role | L0 | L1 | L2 | L3 | L4 (request) | L4 (approve) | L5 (request) | L5 (approve) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| viewer | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| operator | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| admin | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ |
| risk_officer | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓* |
| live_owner | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓* |

*L5 always requires two distinct approvers; one role assignment never satisfies both seats.

## 7. L4/L5 hard-gate enforcement (three-gate)

For any L4/L5 action:
1. **Request gate** — capability + step-up + chain in `pending`.
2. **Assertion gate** — each approver: capability + fresh step-up + non-self + non-duplicate.
3. **Consumption gate** — at handler commit: chain `approved`, subject_canonical_form match, body_hash match, actor_subject match, expiry not passed, no rollback in flight.

All three are evaluated server-side; bypass of any is INV breach and trips kill-switch.

## 8. Rollback validation contract

Rollback workflow re-runs the original action's policy in reverse and re-emits decisions through Risk Gateway. A rollback chain MUST reference the original `chain_id`, the rollback target state, and a `verification_evidence_pointer` (e.g., universe rollout `verified` row).

## 9. Tamper-evident hash chain

Per-stream chain (`audit_ledger`):
```
prev_hash = audit_ledger[seq-1].hash
hash = sha256(prev_hash || canonical_event_bytes || ts || seq)
```
Plus daily Merkle anchor written into `audit_anchors` and optionally signed externally.
Verification:
- on each write, recompute and compare.
- continuous background verifier scans windows; mismatch → kill-switch trip + page.

## 10. Sequence monotonicity and gap detection

`seq` is a per-stream monotonically increasing integer assigned in the same transaction as the row insert. A separate continuous scanner checks `MAX(seq) - MIN(seq) + 1 == COUNT(*)` per stream per window; gap → INV-15 trip.

## 11. Cross-domain governance binding

- Hot-reload (`08`): `universe_rollouts.approval_chain_id` MUST resolve to a `consumed` chain at emit.
- Risk Gateway (`12`): `risk_policy_bundles.approval_chain_id` for activation.
- Mode switch and live-gate: L5 chains referenced by Risk Gateway live-gate state machine.
- Secrets boundary (`15`): L4/L5 leases require chain consumption.
- IAM role grants: L3+ chain.

## 12. Persistence DDL (sketch)

```
approval_chains(chain_id PK, action_class, subject_canonical_form, body_hash,
  required_level, requester_subject, required_approvers, approver_pool_id,
  state, expires_at, created_at, consumed_at)
approval_assertions(assertion_id PK, chain_id FK, approver_subject, approver_step_up_ref,
  decision, comment, asserted_at)
approval_pools(pool_id PK, name, criteria_jsonb)
audit_ledger(event_id PK, stream_id, seq, kind, payload jsonb, prev_hash, hash, ts)
audit_anchors(anchor_id PK, stream_id, range_lo, range_hi, merkle_root, signed_by, signed_ts)
revocation_lists(token_id PK, kind, revoked_at, reason)
```
DB role grants: app role has INSERT only on `audit_ledger`; UPDATE/DELETE revoked.

## 13. Audit ledger event envelope

```
{ event_id, stream_id, seq, ts, kind, actor_subject, subject_canonical_form, body_hash,
  approval_chain_id|null, payload, prev_hash, hash }
```

## 14. Mandatory event kinds (≥18)

`auth.login`, `auth.logout`, `auth.step_up`, `iam.role_grant`, `iam.role_revoke`,
`approval.created`, `approval.assert`, `approval.consumed`, `approval.expired`, `approval.rolled_back`,
`risk.bundle_activated`, `risk.decision_blocked`, `risk.kill_switch_transition`, `risk.live_gate_transition`,
`hot_reload.dispatched`, `hot_reload.terminal`, `hot_reload.rolled_back`,
`secrets.lease_issued`, `secrets.lease_revoked`,
`mode.transition`, `connector.live_enabled_change`, `audit.chain_breach_detected`.

## 15. Test-vector matrix (TV-GOV-* categories)

INV breach attempts (15), state machine traversal (10), three-gate enforcement (8),
subject binding (6), hash-chain tamper (6), sequence gap detection (4), cross-domain binding (5).
~50 vectors across 11 categories.

## 16. Audit / evidence packets

Per chain: chain envelope + assertions + consumption record + linked domain artifacts.
Per audit anchor: signed Merkle root + verification log. Stored under `raw_evidence/governance/`.