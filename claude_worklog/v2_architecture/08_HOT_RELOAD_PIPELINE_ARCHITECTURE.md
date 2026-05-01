# 08 — Hot-Reload Pipeline Architecture

> Canonical hot-reload contract for V2. Replaces the prior 45-line stub.
> Source remediation: `claude_worklog/v2_architecture_remediation/06_HOT_RELOAD_REMEDIATION.md`.
> All hot-reload mutations are non-bypassable, persisted, ack-tracked,
> quorum-gated, and rollback-instrumented.

## 1. Non-bypass invariants (HR-INV-01..12)

1. HR-INV-01 — No component may load a new policy version without an envelope signed by the orchestrator and recorded in `universe_rollouts`.
2. HR-INV-02 — No envelope is dispatched without an associated `approval_chain_id` of level ≥ the component tier's minimum.
3. HR-INV-03 — Every dispatched envelope produces exactly one terminal row (`succeeded`, `partial`, `failed`, `rolled_back`).
4. HR-INV-04 — Acks bind to `(rollout_id, component_id, attempt)`; replays MUST be idempotent.
5. HR-INV-05 — Quorum check is evaluated against the registry snapshot pinned at envelope-emit time, not live membership.
6. HR-INV-06 — Partial-failure handling never silently downgrades; either rollback or explicit operator override (L4) chooses the path.
7. HR-INV-07 — Rollback path uses the previously-recorded envelope as truth; no derived "diff" rollback.
8. HR-INV-08 — Selection-policy version is pinned to the rollout; ad-hoc selection drift is rejected at ack time.
9. HR-INV-09 — Post-apply health check executes within tier-specific window or auto-rollback fires.
10. HR-INV-10 — All state transitions emit `universe_rollout_event` rows into the audit ledger.
11. HR-INV-11 — `kill_switch_state.state != 'armed'` blocks every new envelope dispatch.
12. HR-INV-12 — Live-gate-affecting reloads require L5 approval chain consumption (per §13 §7).

## 2. Component registry tiers

| Tier | Examples | Quorum required | Max ack window |
| --- | --- | --- | --- |
| T0 | Risk Gateway, Connectors | 100% | 5 s |
| T1 | Orchestrator, Execution Engine | 100% | 10 s |
| T2 | Trainer prediction publisher, Feature pipelines | ≥ ⌈2N/3⌉ | 30 s |
| T3 | Monitors, Explainability cache | ≥ ⌈N/2⌉ | 60 s |
| T4 | GUI surfaces, dashboards | best-effort, no block | 120 s |

## 3. Universe update envelope

```
UniverseRolloutEnvelope {
  rollout_id: uuidv7,
  emitted_at: ts,
  emitter: actor_subject,
  approval_chain_id: id,
  selection_policy_version: semver+hash,
  risk_policy_version: semver+hash,
  config_version: hash,
  components: [ component_id ],   // pinned snapshot
  payload_hash: sha256,
  payload: <opaque, schema-versioned>,
  prior_rollout_id: uuidv7|null,  // for rollback truth
  tier: T0|T1|T2|T3|T4,
  expected_quorum: fraction,
  ack_deadline_ms: int,
  rollback_policy: { triggers: [...], default: 'auto'|'manual' }
}
```

## 4. Per-component ack envelope

```
HotReloadAck {
  rollout_id, component_id, attempt,
  outcome: 'applied'|'rejected'|'deferred'|'noop',
  observed_policy_version,
  observed_payload_hash,
  health_at_ack: { ... },
  reason_class: enum,
  reason_detail: string,
  ack_ts
}
```

## 5. Ack timeout policy

- Per-tier `ack_deadline_ms` from §2.
- After deadline: missing acks become `timeout`; tier-specific quorum recomputed.
- Component-level escalation:
  - 1st miss: warning audit event.
  - 2nd consecutive miss: component marked `degraded` in registry; subsequent rollouts skip until recovery probe.
  - 3rd miss: component marked `quarantined`; requires L3 admin to clear.

## 6. Retry policy

- Idempotency key = `(rollout_id, component_id, attempt)`.
- Schedule: 250 ms, 1 s, 4 s (exponential, jittered ±20%).
- Retry budget: tier-dependent (T0: 1, T1: 2, T2/T3: 3, T4: 5).
- Dead-letter: exhausted retries land in `universe_rollout_dead_letter` for L3 inspection.

## 7. Quorum semantics

- Required fraction set at envelope emit (§3) and frozen.
- Computed against pinned `components` list.
- `applied` and `noop` count toward quorum; `deferred` does not.
- T0/T1: failure to meet quorum → immediate rollback trigger RBT-01.

## 8. Partial-failure handling

- If quorum met but some `rejected`/`timeout`:
  - T0: rollback (RBT-02).
  - T1: rollback unless L4 operator override `partial_apply_acceptable` consumed.
  - T2/T3: continue, schedule recovery probe; emit `partial` terminal row.
  - T4: continue silently, log only.
- Override-conflict precedence: invariants > kill-switch > tier policy > operator override.

## 9. Rollback trigger thresholds (RBT-01..06)

| ID | Trigger |
| --- | --- |
| RBT-01 | Quorum not met within deadline |
| RBT-02 | Any T0 component `rejected` |
| RBT-03 | Post-apply health check fails (§11) |
| RBT-04 | Risk-decision error rate > 2× pre-rollout 5-min EWMA within first 5 min post-apply |
| RBT-05 | Connector reject rate > tier threshold within first 5 min |
| RBT-06 | L3+ operator manual `rollback` request |

## 10. Rollback state machine

States: `none → triggered → dispatching → acked_partial → acked_full → verified | failed_to_rollback`.
- `verified`: prior envelope's payload_hash observed across pinned components.
- `failed_to_rollback`: kill-switch auto-trips; oncall page emitted.

## 11. Post-apply health-check contract

- Per-tier window (T0: 30 s, T1: 60 s, T2: 180 s, T3: 300 s).
- Probe set declared per component class in registry.
- Failure → RBT-03.
- Success → emit `rollout_verified` audit row.

## 12. Persistence DDL (sketch)

```
universe_rollouts(
  rollout_id PK, emitted_at, emitter, approval_chain_id,
  selection_policy_version, risk_policy_version, config_version,
  payload_hash, tier, expected_quorum, ack_deadline_ms,
  prior_rollout_id, status, terminal_reason, terminal_ts
)
universe_rollout_targets(rollout_id, component_id, status, attempts, last_ack_ts, PK(rollout_id, component_id))
universe_rollout_events(event_id PK, rollout_id, component_id, kind, payload_jsonb, prev_hash, hash, ts)
universe_rollout_dead_letter(...)
```

All three primary tables are append-only except for the bounded `status` column on `universe_rollouts` and `universe_rollout_targets`, which is monotonic.

## 13. `universe_rollout_event` envelope

```
{ event_id, rollout_id, component_id|null, kind: 'dispatched'|'ack'|'timeout'|'partial'|'verified'|'rollback_triggered'|'rollback_verified'|'failed_to_rollback'|'dead_lettered',
  payload, prev_hash, hash, ts, audit_chain_anchor }
```
`audit_chain_anchor` cross-binds into `audit_ledger` per §13 §11.

## 14. Selection-policy version pinning

Components MUST reject envelopes whose `selection_policy_version` differs from the version they currently hold without an explicit `policy_upgrade=true` field. Drift between envelope's pin and component's view → `rejected/policy_drift`.

## 15. Test-vector matrix (categories)

- TV-HR-INV: invariant breach attempts (12).
- TV-HR-ACK: ack timing edges per tier (8).
- TV-HR-QUORUM: T0/T1 quorum boundary (6).
- TV-HR-PARTIAL: partial-apply precedence (6).
- TV-HR-RBT: each RBT trigger fires correctly (6).
- TV-HR-ROLLBACK: state machine traversal (8).
- TV-HR-DRIFT: policy-version drift rejection (4).
- TV-HR-AUDIT: audit chain continuity across rollouts (4).

## 16. Audit / evidence packets

Each terminal rollout produces an evidence packet under `raw_evidence/hot_reload/<rollout_id>/`: envelope, ack matrix, health-check raw outputs, audit chain segment, kill-switch / live-gate snapshot at emit and at terminal.