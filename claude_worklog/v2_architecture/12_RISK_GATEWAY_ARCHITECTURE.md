# 12 — Risk Gateway Architecture

> Canonical risk-gateway contract for V2. Replaces the prior 26-line stub.
> Source remediation: `claude_worklog/v2_architecture_remediation/05_RISK_GATEWAY_REMEDIATION.md`.
> The Risk Gateway is the only authority that may emit `allow` for an order
> intent. The orchestrator proposes; the gateway decides; the connector
> re-verifies (§10).

## 1. Non-bypass invariants (INV-01..12)

1. INV-01 — Every order intent passes through `evaluate(intent, bundle, context)` exactly once before any connector call.
2. INV-02 — A `block` decision can NEVER be downgraded to `allow` by any other component.
3. INV-03 — A `degraded` policy bundle MUST default to `block` for every live-affecting policy.
4. INV-04 — `kill_switch_state.state != 'armed'` forces `allow=false` regardless of evaluation.
5. INV-05 — `live_gate_state.state != 'ready'` forces `allow=false` for live-mutation intents.
6. INV-06 — Risk decision rows are append-only and bind to `(intent_id, bundle_version)`.
7. INV-07 — Duplicate-guard is evaluated before policy phases (§4).
8. INV-08 — Stale signal/feature inputs use the documented stale defaults (§7), never silent passthrough.
9. INV-09 — Phase order (§4) is fixed; runtime reordering is rejected.
10. INV-10 — Failure precedence (§5) is deterministic; ties never produce `allow`.
11. INV-11 — Connector boundary re-verifies kill-switch and live-gate independently.
12. INV-12 — Every decision emits a `risk_decision` envelope (§11) into the audit ledger.

## 2. Policy bundle envelope and state machine

```
RiskPolicyBundle {
  bundle_version: semver+hash,
  emitted_at, emitter, approval_chain_id,
  policies: [ Policy ],
  defaults: { stale_signal, stale_feature, missing_attribution, ... },
  fingerprint: sha256 (canonical),
  prior_bundle_version
}
```

States: `draft → proposed → approved → active → superseded | revoked | degraded`.
- `degraded`: structurally loaded but failed startup self-check; INV-03 defaults apply until cleared.

## 3. Per-policy-type schemas (21 types)

Categories and representative shapes:

1. `notional_cap` — `{ ccy, max_notional, scope }`.
2. `position_cap` — `{ symbol_pattern, max_qty, side }`.
3. `leverage_cap` — `{ market_pattern, max_leverage, margin_mode }`.
4. `daily_loss_limit` — `{ scope, currency, max_loss }`.
5. `drawdown_limit` — `{ scope, lookback, max_dd_pct }`.
6. `concentration_limit` — `{ axis, max_share }`.
7. `correlation_cap` — `{ basket, max_corr }`.
8. `min_confidence` — `{ strategy_class, threshold }`.
9. `attribution_completeness` — `{ required_features: [...], min_present_fraction, min_explained_fraction }`.
10. `stale_signal_guard` — `{ max_age_ms, default: 'block' }`.
11. `stale_feature_guard` — `{ feature_id, max_age_ms, default: 'block' }`.
12. `duplicate_guard` — `{ key_derivation, window_ms }` (see §6).
13. `kill_switch_gate` — `{ states_allowed: ['armed'] }`.
14. `live_gate` — `{ requires: ['mode.paper_to_live.consumed', 'connector.live_enabled.consumed'] }`.
15. `connector_health_gate` — `{ required: ['heartbeat_fresh','clock_skew_ok'] }`.
16. `notional_per_intent_cap`.
17. `rate_limit_per_strategy`.
18. `cooldown_after_loss`.
19. `slippage_band_guard`.
20. `mandatory_stop_loss`.
21. `hedge_dca_disabled_default`.

Each policy declares `phase` (§4), `precedence_rank` (§5), `policy_id`, `version`.

## 4. Deterministic evaluation order (phases)

| Phase | Name | Policy classes |
| --- | --- | --- |
| P0 | Pre-evaluation gates | `kill_switch_gate`, `live_gate`, `duplicate_guard`, `connector_health_gate` |
| P1 | Input validity | `stale_signal_guard`, `stale_feature_guard`, `attribution_completeness`, `min_confidence` |
| P2 | Per-intent bounds | `notional_per_intent_cap`, `slippage_band_guard`, `mandatory_stop_loss` |
| P3 | Aggregate bounds | `notional_cap`, `position_cap`, `leverage_cap`, `concentration_limit`, `correlation_cap`, `rate_limit_per_strategy` |
| P4 | Loss / cooldown | `daily_loss_limit`, `drawdown_limit`, `cooldown_after_loss` |
| P5 | Behavioral | `hedge_dca_disabled_default` |

Phases evaluate in order; first phase that emits any `block` short-circuits remaining phases (with full reason set captured for audit).

## 5. Failure precedence

Within a phase, ties resolve by `precedence_rank` (lower wins). Across phases, lower-numbered phase wins. Any `block` always beats any `allow`. `degraded_default_block` (INV-03) always beats `allow`.

## 6. Duplicate-execution guard contract

- Key derivation: `sha256(strategy_id || symbol || side || qty_bucket || price_bucket || policy_window_id)`.
- Window: bundle-configurable, default 2 s for live, 250 ms for paper.
- Hits within window → `block / risk.duplicate_guard`.
- Audited under `risk_decision` with `duplicate_key`.

## 7. Stale-signal defaults

| Input | Default `max_age_ms` | Default action when stale |
| --- | --- | --- |
| Mark price | 1500 | block |
| Order book L1 | 750 | block |
| Funding rate | 60000 | warn (paper) / block (live) |
| Feature snapshot | per-feature | block |
| Trainer prediction | 5000 | block |
| Confidence calibration | 30000 | block |

Clock authority: server NTP-synced; `clock_skew > 250ms` → `block / connector_health_gate`.

## 8. Kill-switch persistence and state machine

States: `armed → tripped → maintenance → armed`.
- `tripped`: any P0..P5 emits forced block (`kill_switch.tripped`).
- Transitions persisted in `kill_switch_events` with `prev_hash`/`hash` chained to `audit_ledger`.
- L3 required to enter `maintenance`; L4 required to re-arm after `tripped`.

## 9. Live-readiness state machine

States: `not_ready → preparing → ready → degraded`.
- `ready` requires both consumed L5 chains (`mode.switch.paper_to_live`, `connector.live_enabled.set_true`) and successful self-check.
- Any rollback of either L5 chain forces `not_ready`.

## 10. Connector-side hard blocks

Connector independently re-verifies, before any exchange call:
1. `kill_switch_state.state == 'armed'`.
2. `live_gate_state.state == 'ready'`.
3. Risk-decision exists for `intent_id` with `allow=true` and `bundle_version` matching active.
4. `clock_skew_ok` and connector heartbeat fresh.
5. Order parameters re-validated against `notional_per_intent_cap` and `mandatory_stop_loss`.
6. Idempotency-key uniqueness at connector layer.
7. Symbol whitelisted in active universe rollout (§08).
8. No outstanding rollback in flight for the policy bundle.

Any failure → `connector.hard_block` emitted; intent never reaches the exchange.

## 11. Risk decision envelope and DDL

```
RiskDecision {
  decision_id, intent_id, bundle_version,
  allow: bool, phase_results: [...],
  blocking_reasons: [...], non_blocking_warnings: [...],
  duplicate_key|null,
  inputs: { signal_id, prediction_id, feature_snapshot_id, calibration_id, kill_switch_state, live_gate_state, connector_health_snapshot },
  decided_at, decided_by: 'risk_gateway',
  audit_chain_anchor
}

risk_decisions(decision_id PK, intent_id, bundle_version, allow, blocking_reasons jsonb, payload jsonb, decided_at)
risk_decision_inputs(...)  // 1:1 input snapshots
ALTER orders ADD COLUMN risk_decision_id;
ALTER executions ADD COLUMN risk_decision_id;
```

## 12. Test-vector matrix (TV-* categories)

- TV-INV (12), TV-PHASE-ORDER (6), TV-PRECEDENCE (6), TV-DUP (5),
- TV-STALE (8), TV-KILL (6), TV-LIVE (6), TV-CONN-HARD (8),
- TV-DEGRADED (4), TV-DDL (3), TV-CHAIN (3), TV-EDGE-NOTIONAL (6), TV-EDGE-CORR (3).
~50 vectors across 13 categories.

## 13. Audit / evidence packets

Per decision: serialized `RiskDecision`, input snapshots, bundle fingerprint, kill-switch and live-gate snapshots. Per bundle activation: bundle envelope + approval chain + self-check output. Stored under `raw_evidence/risk_gateway/`.