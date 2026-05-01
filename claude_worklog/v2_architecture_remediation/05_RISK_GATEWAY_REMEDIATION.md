# 05 Risk Gateway Remediation

## Status
- Source blocker: actual Codex CLI architecture review, `claude_worklog/v2_architecture_codex_review/12_ACTUAL_CODEX_CLI_ARCHITECTURE_REVIEW_OUTPUT.md`, **Blocker 4** — *"Risk Gateway final authority is asserted, not enforceably designed."*
- Reconciled in `claude_worklog/v2_architecture_codex_review/13_ACTUAL_CODEX_RECONCILIATION.md`, consolidated blocker **#4**.
- Architecture file under remediation: `claude_worklog/v2_architecture/12_RISK_GATEWAY_ARCHITECTURE.md` (current text is a 26-line stub that names ten controls but does not define their schema, ordering, precedence, duplicate strategy, stale defaults, or test vectors).
- Companion contracts: `claude_worklog/v2_architecture_remediation/04_API_CONTRACT_REMEDIATION.md` defines the route surface (`POST /traders/{trader_id}/intents`, `PUT /risk_policy/*`, `PUT /connectors/{id}/live_enabled`, kill-switch routes), error envelope, idempotency rules, and live-block posture this document references. Where that file specifies *how the API speaks*, this file specifies *what the gateway decides and how that decision is structured, ordered, and verifiable*.
- This document does **not** ship V2 code, does not write Redis, does not place or cancel any exchange instructions, does not modify the legacy runtime tree. It is an architecture-layer deliverable producing schema, state machines, ordering invariants, duplicate-guard contracts, and test-vector matrices that make Risk Gateway non-bypass enforceable in scaffold tests.

## Read/write boundary compliance
Writes only to `./claude_worklog/v2_architecture_remediation/`. Does not edit `./legacy_reference/**` or the sibling legacy bot tree. No `.env`, no secrets, no Redis writes, no service restarts. All examples are schema and state-machine fragments — no executable runtime is created or modified.

## Scope of remediation
This file produces, in order:
1. Non-bypass invariants the architecture must enforce (the contract Risk Gateway implementations are scored against).
2. Policy bundle schema and version semantics (the immutable governance object).
3. Per-policy-type schemas (the ten enumerated controls + four added required by Codex).
4. Deterministic evaluation order across phases and within each phase.
5. Failure precedence (which block wins when multiple policies would block).
6. Duplicate-execution guard contract (key derivation, TTL, persistence, replay vs collision).
7. Stale-signal defaults and source-of-truth clock.
8. Kill-switch persistence and state machine.
9. Live-readiness state machine.
10. Connector-side hard-block contract (defense-in-depth at the exchange adapter boundary).
11. Risk decision (`risk_decision` event) envelope with full lineage and policy trace.
12. Test-vector matrix that any scaffold implementation must pass before V2 build clears Blocker 4.
13. Audit / evidence-packet requirements.
14. Traceability table mapping every sub-claim of Codex Blocker 4 to the section that closes it.
15. Gate recommendation.

---

## 1. Non-bypass invariants (the contract the gateway is judged against)

These are the architectural invariants every Risk Gateway implementation MUST satisfy. They are restated as machine-checkable statements so scaffold tests can assert them directly.

| ID | Invariant | Assertion form |
| --- | --- | --- |
| INV-01 | No `execution_intent` row exists in DB without a `risk_decision_id` whose `allow_block = "allow"`. | DB CHECK: `execution_intents.risk_decision_id IS NOT NULL` + FK + nightly assertion `SELECT COUNT(*) FROM execution_intents ei JOIN risk_decisions rd ON ei.risk_decision_id = rd.risk_decision_id WHERE rd.allow_block != 'allow'` MUST be 0. |
| INV-02 | No exchange action exists without a corresponding `execution_intent` whose state is not `rejected`. | Connector-side ledger replay reconciles every accepted exchange action against `execution_intents`. Drift = quarantine + alert. |
| INV-03 | Every `signal_event → orchestrator_decision → risk_decision` triple is evaluated by exactly one Risk Gateway instance, identified by `gateway_instance_id`. | `risk_decisions.gateway_instance_id` is NOT NULL; duplicate `(decision_id)` is unique. |
| INV-04 | Risk Gateway decisions are deterministic given `(orchestrator_decision_payload, policy_bundle_version, runtime_clock_window, kill_switch_state, live_gate_state)`. | Re-evaluation harness produces byte-identical `risk_decision.policy_checks_json` + same `allow_block` + same `block_reason`. |
| INV-05 | Policy evaluation order is fixed by `policy_bundle.evaluation_order_hash`. Reordering the bundle MUST require a new `policy_bundle_version` bumped through L4 approval. | DB CHECK: `policy_bundles.evaluation_order_hash` is NOT NULL and stored alongside `policy_bundle_version`. |
| INV-06 | Approval-gated policy mutations cannot apply without `approvals.decision = 'approved'` AND approver has the required role (`live_admin` for L4/L5). | DB trigger or service-layer guard rejects `policy_bundles INSERT` whose `risk_level >= 'L4'` and missing approval row. |
| INV-07 | Kill-switch `tripped` state survives process restart, Redis flush, and DB primary failover. | Persisted in DB `kill_switch_state` row + replicated; on boot the gateway reads DB state before accepting any orchestrator decision. |
| INV-08 | The default state of every newly provisioned Risk Gateway instance is `live_gate = blocked`, `kill_switch = armed`, `policy_bundle = none_loaded`. Until a bundle is loaded the gateway emits `risk_decision.allow_block = "block"` with `block_reason = "no_policy_bundle_loaded"`. | Boot test asserts default behavior. |
| INV-09 | Every `risk_decision` carries the full lineage tuple `(feature_snapshot_id, prediction_id, signal_id, decision_id, risk_decision_id, execution_intent_id|null)`. Missing upstream IDs are explicit `null` with `lineage_gap_reason`. | Companion of `04_API_CONTRACT_REMEDIATION.md §1.4`. |
| INV-10 | Connector-side hard blocks are independent of the gateway: the connector rejects any exchange action whose `execution_intent_id` does not exist locally, whose lineage hash does not verify, or whose `risk_decision_id` is missing/blocked. | Connector unit tests assert reject on each tampered case. |
| INV-11 | Non-bypass holds across all execution paths: paper, replay, simulator, live. The mode flag (`paper|live`) MUST NOT branch around the gateway; only specific policies (e.g. `live_gate`) condition on mode. | Static check: the only call-site of the connector submit path is the executor, and the executor reads `execution_intents` populated only after `risk_decision.allow_block = "allow"`. |
| INV-12 | Risk Gateway never mutates legacy systems, never edits old Redis keys, never restarts the legacy trainer. Every gateway action targets the V2 namespace only. | Static config: `REDIS_PREFIX = "v2:"`, no write paths to legacy keys; CI grep for legacy key prefixes in gateway source. |

---

## 2. Policy bundle schema (the immutable governance object)

The Risk Gateway never evaluates "loose" policies. It evaluates a single **policy bundle** identified by `policy_bundle_version`. The bundle is the unit of approval, deploy, and replay.

### 2.1 Policy bundle envelope

```json
{
  "schema_version": "1.0.0",
  "policy_bundle_id": "uuid-v7",
  "policy_bundle_version": "2026.04.30-001",
  "evaluation_order_hash": "sha256:<hex>",
  "bundle_hash": "sha256:<hex>",
  "created_by": {
    "actor_type": "human|claude|codex|ollama|system",
    "actor_id": "string"
  },
  "approvals": [
    {
      "approval_id": "uuid-v7",
      "approver_user_id": "string",
      "required_level": "L4",
      "decision": "approved",
      "decision_ts_ms": 1735689600000
    }
  ],
  "applies_to": {
    "trader_scopes": ["trader_id_or_glob"],
    "exchange_scopes": ["exchange_id_or_*"],
    "symbol_scopes": ["exchange_symbol_id_or_*"],
    "mode_scopes": ["paper", "live"]
  },
  "phases": [
    "phase_input",
    "phase_lineage",
    "phase_static",
    "phase_runtime",
    "phase_market",
    "phase_capital",
    "phase_account",
    "phase_duplicate",
    "phase_live_gate"
  ],
  "policies": [
    { "policy_id": "string", "type": "<one of §3>", "phase": "<one of phases>", "order_in_phase": 1, "params": {} }
  ],
  "rollback_target_version": "2026.04.29-007",
  "created_ts_ms": 1735689600000,
  "applied_ts_ms": 1735689660000
}
```

Rules:
- `bundle_hash = sha256(canonicalized_json_excluding(bundle_hash, applied_ts_ms, approvals))`. Any change to ordering, params, or scope produces a new bundle.
- `evaluation_order_hash = sha256(concat(phase || ":" || policy_id || ":" || order_in_phase for each policy))`. INV-05 binds the gateway to this hash; the gateway refuses to evaluate if the runtime-loaded bundle's recomputed hash differs from the stored one.
- `policy_bundle_version` is a monotonic semver-like token (`YYYY.MM.DD-NNN`). Two bundles with the same version string are a **fatal deploy error** and the gateway boots into `block` mode with `block_reason = "policy_bundle_version_collision"`.
- `applies_to` selects which `(trader, exchange, symbol, mode)` tuples this bundle governs. Resolution: most-specific-wins; ties broken by lexicographic `policy_bundle_id`. Unscoped tuples fall back to the **default deny bundle** (a built-in, code-versioned bundle that blocks everything with `block_reason = "no_governing_bundle"`).
- `rollback_target_version` is REQUIRED. Without a rollback target the gateway refuses to accept the bundle (`validation` error at `PUT /risk_policy/bundles/{id}:apply`).

### 2.2 Bundle state machine

```
draft -> validated -> approved -> staged -> applied -> superseded
                                       \-> rolled_back
```

| Transition | Required scope (RBAC, see `04_API_CONTRACT_REMEDIATION.md §2`) | Approval level | Idempotent | Notes |
| --- | --- | --- | --- | --- |
| `draft → validated` | `write:strategy` | L2 | yes | Schema validation, dependency resolution, simulation against last 1000 archived `orchestrator_decisions`. |
| `validated → approved` | `write:approval` (must be `live_admin` if any `mode_scope = "live"`) | L4 | yes | Adds an `approvals` row; bundle hash frozen. |
| `approved → staged` | `write:strategy` | L4 | yes | Bundle is loaded into the gateway in **shadow mode**: real evaluation runs, real `risk_decision` rows written, but `allow_block` is overridden to mirror the previous bundle's verdict. Discrepancies recorded as `shadow_drift` events. |
| `staged → applied` | `write:strategy` | L4 + L5 if `mode=live` | yes | Promotes the bundle to authoritative. Requires `shadow_drift_rate < 1e-4` over a configurable observation window (default 1 hour, persisted in the bundle's `params`). |
| `applied → superseded` | system | n/a | yes | Set automatically when a new bundle for the same scope reaches `applied`. |
| `applied → rolled_back` | `write:strategy` | L4 | yes | Loads `rollback_target_version`. If it does not exist the rollback fails closed: gateway switches to default-deny bundle. |

### 2.3 Bundle persistence

- Stored in DB table `risk_policy_bundles` (companion DDL fragment in §11.1) — NOT only in Redis. Redis carries `v2:risk:active_bundle_pointer` for hot read; DB is source of truth.
- On boot: gateway reads the DB pointer first. If the DB pointer is missing or unreachable, the gateway boots into the **default deny bundle** and emits `block_reason = "policy_bundle_unloadable"`.
- Bundle hash is verified on every load. Hash mismatch → boot fails closed.

---

## 3. Per-policy-type schemas

The architecture stub names ten controls. Codex requires concrete schema for each. This section enumerates the policy types, their `params` schema, the phase they belong to, and their default values.

### 3.1 Policy type catalog

| `type` | Phase | Description |
| --- | --- | --- |
| `lineage_completeness` | `phase_lineage` | All upstream lineage IDs present and resolvable. |
| `attribution_completeness` | `phase_lineage` | `confidence_event` attached, top-N contributors present, calibration version present. |
| `stale_signal` | `phase_input` | Reject signals older than the type-specific stale threshold. |
| `feature_freshness` | `phase_input` | Reject if any required `feature_value.freshness_age_ms` exceeds threshold. |
| `policy_bundle_integrity` | `phase_static` | Verify bundle hash and order hash before any business policy runs. |
| `kill_switch` | `phase_static` | Reject all if kill switch is `tripped`. |
| `live_gate` | `phase_live_gate` | Reject if `mode == "live"` AND live readiness is not `ready`. |
| `mode_consistency` | `phase_static` | Reject if `decision.mode` does not match `applies_to.mode_scopes`. |
| `leverage_cap` | `phase_capital` | Reject if requested leverage exceeds per-symbol/per-account cap. |
| `margin_mode_lock` | `phase_capital` | Reject if requested margin mode (ISOLATED/CROSS) differs from approved policy. |
| `position_sizing` | `phase_capital` | Reject if `qty * mark_price` exceeds per-symbol or per-account size cap. |
| `reduce_only_enforcement` | `phase_runtime` | Reject if a strategy in `reduce_only` posture proposes increase. |
| `stop_policy` | `phase_runtime` | Reject if no mandatory stop attached, or stop violates min/max distance. |
| `daily_loss_cap` | `phase_account` | Reject if today's realized + unrealized loss would exceed cap. |
| `weekly_loss_cap` | `phase_account` | Reject if rolling 7d loss would exceed cap. |
| `drawdown_brake` | `phase_account` | Reject if peak-to-trough drawdown exceeds threshold. |
| `funding_window_block` | `phase_market` | Reject within funding-window blackout. |
| `liquidation_proximity` | `phase_market` | Reject if account `mmr_ratio` is within configured danger band. |
| `duplicate_guard` | `phase_duplicate` | Reject duplicate intents under the duplicate-key contract (§6). |
| `connector_health` | `phase_runtime` | Reject if target connector `health_status != "ok"` or stale heartbeat. |
| `symbol_universe_membership` | `phase_input` | Reject if `(exchange_symbol_id, mode)` is not present in the active `universe_members` row with the appropriate flag (`trade_enabled`, `live_allowed`). |

(Implementations may add types within an `x_` namespace for experiment policies, but only when scoped to `mode_scopes = ["paper"]` and approval level L2.)

### 3.2 Schema fragments (representative; full set normative)

#### 3.2.1 `stale_signal`

```json
{
  "type": "stale_signal",
  "params": {
    "by_signal_type": {
      "scalp_1m": { "max_age_ms": 5000, "clock": "exchange_event_ts" },
      "swing_15m": { "max_age_ms": 60000, "clock": "exchange_event_ts" },
      "default":   { "max_age_ms": 30000, "clock": "exchange_event_ts" }
    },
    "tolerance_ms": 250
  }
}
```

Defaults (used when `params.by_signal_type[type]` and `default` are both absent): `max_age_ms = 10000`, `tolerance_ms = 250`, `clock = "exchange_event_ts"`. Defaults are coded in the gateway and recorded in the policy_bundle resolved-defaults audit field.

Clock source-of-truth (resolved in §7.2): the gateway uses `clock = exchange_event_ts` (the timestamp embedded in the upstream market event), NOT `now()`. Wall-clock skew between gateway host and exchange is bounded by `tolerance_ms`.

#### 3.2.2 `leverage_cap`

```json
{
  "type": "leverage_cap",
  "params": {
    "global_cap": "5.0",
    "per_exchange": {"binance": "5.0", "bybit": "5.0"},
    "per_symbol": {"BTCUSDT": "5.0", "ETHUSDT": "5.0"},
    "default_per_symbol": "3.0"
  }
}
```

All numbers are string-encoded decimals. Resolution: most-specific-wins. Unmatched symbols receive `default_per_symbol`. Increases require L4 approval per `04_API_CONTRACT_REMEDIATION.md §2.3`.

#### 3.2.3 `position_sizing`

```json
{
  "type": "position_sizing",
  "params": {
    "max_notional_usd_per_symbol": {"BTCUSDT": "100000", "default": "10000"},
    "max_notional_usd_per_account": "250000",
    "max_qty_per_symbol": {"BTCUSDT": "10.0", "default": "1.0"},
    "mark_price_source": "v2:price:mark:{symbol}",
    "mark_price_max_age_ms": 1500
  }
}
```

If the mark price source is stale beyond `mark_price_max_age_ms`, the policy resolves to **block** with `block_reason = "position_sizing_mark_stale"` (NOT pass-through).

#### 3.2.4 `daily_loss_cap`

```json
{
  "type": "daily_loss_cap",
  "params": {
    "scope": "account|trader",
    "cap_usd": "1000",
    "loss_basis": "realized_plus_unrealized",
    "reset_clock_utc_hhmm": "00:00",
    "include_paper": false
  }
}
```

Loss accumulator is read from DB views (`v_pnl_today_per_account`, `v_pnl_today_per_trader`). Source of truth is DB, not Redis. If the view is unavailable, policy → block with `block_reason = "daily_loss_cap_basis_unavailable"`.

#### 3.2.5 `kill_switch`

```json
{
  "type": "kill_switch",
  "params": {
    "respect_arming": true,
    "reset_requires_approval_level": "L4"
  }
}
```

The actual tripped/armed state is NOT in `params` — it lives in the persisted state machine (§8). The policy params only encode whether the gateway respects arming and what it takes to reset.

#### 3.2.6 `live_gate`

```json
{
  "type": "live_gate",
  "params": {
    "required_gates": [
      "monitor_completeness",
      "risk_policy_signoff",
      "approval_workflow_active",
      "kill_switch_armed",
      "human_confirmation_present"
    ],
    "ready_window_ms": 600000
  }
}
```

`ready_window_ms` is the freshness window for the `live_gate.state` evaluation. Older than this → block with `live_gate_state_stale`.

#### 3.2.7 `duplicate_guard`

See §6 for the full contract; the policy params are:

```json
{
  "type": "duplicate_guard",
  "params": {
    "key_strategy": "lineage_v1",
    "ttl_ms_paper": 120000,
    "ttl_ms_live": 600000,
    "store": "redis_then_db"
  }
}
```

#### 3.2.8 `attribution_completeness`

```json
{
  "type": "attribution_completeness",
  "params": {
    "min_top_positive": 3,
    "min_top_negative": 3,
    "require_calibration_version": true,
    "require_explainability_method": true,
    "raw_and_calibrated_required": true
  }
}
```

These values are the architecture defaults consistent with consolidated Codex blocker #3 (confidence explainability schema). They are referenced here so `attribution_completeness` blocks any decision missing structured contributors. Lowering any threshold is L4.

#### 3.2.9 `feature_freshness`

```json
{
  "type": "feature_freshness",
  "params": {
    "by_feature_class": {
      "orderbook":  { "max_age_ms": 1500 },
      "trade_tape": { "max_age_ms": 2000 },
      "kline_1m":   { "max_age_ms": 60000 },
      "funding":    { "max_age_ms": 600000 },
      "default":    { "max_age_ms": 5000 }
    },
    "missing_required_count_threshold": 0
  }
}
```

If `feature_value.missing_flag = true` for any required feature, policy → block. If `stale_flag = true` exceeding the per-class `max_age_ms`, policy → block.

#### 3.2.10 All other types

Each remaining type in §3.1 has a `params` schema in this same form, normative for V2 scaffold. They are omitted here only for length; the contract is: every policy type MUST publish (a) JSON schema for `params`, (b) hard defaults applied when params absent, (c) failure mode = always block, never pass-through, on input ambiguity.

### 3.3 Universal policy invariants

- **Closed-on-error.** If a policy raises an unexpected runtime exception or its data dependency is unavailable, the verdict is **block** with `block_reason = "<policy_id>_evaluator_error"` and `evaluator_error_class` populated. There is no pass-through default.
- **Side-effect-free.** A policy evaluation MUST NOT write Redis or DB except through the gateway's outer audit/decision writer. Internal counters used for rate limits MUST be read from authoritative state, not maintained inside the policy module.
- **Deterministic given inputs.** Two evaluations with identical inputs MUST produce identical verdicts. Random sampling/jitter is forbidden inside policies.
- **No legacy mutation.** A policy MUST NOT consult or write any legacy Redis key. Evidence of legacy reads is acceptable only via the read-only adapter, never via direct legacy connection strings.

---

## 4. Deterministic evaluation order

### 4.1 Phases (outer order)

The gateway evaluates phases strictly in this order. Within a phase, policies are evaluated in `order_in_phase` ascending. Phase order is **not configurable** — it is hard-coded into the gateway and asserted at boot.

| # | Phase | Purpose | Stop-on-block? |
| --- | --- | --- | --- |
| 1 | `phase_input` | Cheap input validity: signal stale, feature freshness, universe membership. | yes |
| 2 | `phase_lineage` | Lineage and attribution completeness. | yes |
| 3 | `phase_static` | Bundle integrity, kill switch, mode consistency. | yes |
| 4 | `phase_runtime` | Connector health, reduce-only, stop-policy. | yes |
| 5 | `phase_market` | Funding-window, liquidation proximity. | yes |
| 6 | `phase_capital` | Leverage, margin mode, sizing. | yes |
| 7 | `phase_account` | Daily/weekly loss caps, drawdown brake. | yes |
| 8 | `phase_duplicate` | Duplicate guard (§6). | yes |
| 9 | `phase_live_gate` | Live readiness gate (only if `mode=live`). | yes |

`stop_on_block = yes` everywhere: the first blocking verdict in a phase terminates that phase. Subsequent phases still run iff the **policy bundle declares `evaluate_all_phases = true`** for diagnostic mode (default `false`). Even with `evaluate_all_phases = true`, the **authoritative** verdict is the first block; later phases are run only to populate the diagnostic `policy_checks_json` trace.

### 4.2 Why this order

Cheap, pure checks first; checks that depend on external state (account, market, connectors) later; the `live_gate` last so that a paper-mode decision never even consults the live readiness state. The kill switch is in `phase_static` (early) so a tripped gateway short-circuits before any expensive evaluation. Duplicate guard is the **last** check before live-gate so that the deduplication key is computed against a decision that has otherwise passed all its other policies — preventing the duplicate cache from filling with would-be-blocked entries.

### 4.3 Evaluation invariant

The gateway records the realized evaluation trace as:

```json
{
  "policy_checks_json": [
    {
      "phase": "phase_input",
      "order_in_phase": 1,
      "policy_id": "stale_signal_default",
      "type": "stale_signal",
      "verdict": "allow|block",
      "evaluated_ts_ms": 1735689600200,
      "elapsed_us": 312,
      "params_hash": "sha256:<hex>",
      "inputs_digest": "sha256:<hex>",
      "block_reason": "string|null",
      "block_evidence": [{"kind": "...", "ref": "..."}]
    }
  ]
}
```

INV-04 (determinism) is asserted by hashing `inputs_digest || params_hash || verdict` per policy and comparing across replays.

---

## 5. Failure precedence

When `evaluate_all_phases = false` (production default), there is at most one block — precedence is implicit (first block wins by phase order). When `evaluate_all_phases = true` (diagnostic mode), multiple policies may block; precedence determines which `block_reason` becomes the **authoritative** one surfaced in `risk_decisions.block_reason` and in the API error envelope's `details.policy_name`.

### 5.1 Precedence rules

| Rank | Class | Members |
| --- | --- | --- |
| 1 | **Safety stops** | `kill_switch`, `liquidation_proximity` |
| 2 | **Integrity failures** | `policy_bundle_integrity`, `lineage_completeness`, `attribution_completeness`, `mode_consistency` |
| 3 | **Live-mode controls** | `live_gate` (only relevant in live mode) |
| 4 | **Account hard caps** | `daily_loss_cap`, `weekly_loss_cap`, `drawdown_brake` |
| 5 | **Capital limits** | `leverage_cap`, `margin_mode_lock`, `position_sizing` |
| 6 | **Runtime/market** | `connector_health`, `reduce_only_enforcement`, `stop_policy`, `funding_window_block` |
| 7 | **Input validity** | `stale_signal`, `feature_freshness`, `symbol_universe_membership` |
| 8 | **Duplicate** | `duplicate_guard` |

Lower rank number = higher precedence. Rationale: a `kill_switch` block must always surface as the authoritative reason, even if other policies also blocked. Conversely, `duplicate_guard` blocks only matter in the absence of any "real" reject reason (because they often fire harmlessly during legitimate retries).

### 5.2 Within-class tie break

If two policies in the same precedence rank both block, the tie is broken by `(phase_order_asc, order_in_phase_asc, policy_id_lex_asc)`. This ordering is fully deterministic given the bundle and is recorded in `risk_decisions.precedence_resolution_json`.

### 5.3 Allow precedence

There is no "allow precedence" — any single block is dispositive. `risk_decisions.allow_block = "allow"` requires every executed policy to have returned `allow`. (When `evaluate_all_phases = false` and the trace is shorter than the policy list, that is **not** an `allow` shortcut — it means the trace terminated on a block; the verdict is `block`.)

### 5.4 Manual override

There is no bypass-by-flag. The only way to make a previously-blocking policy stop blocking is to deploy a new `policy_bundle_version` (governed by §2.2). "Emergency override" is implemented as **kill switch trip** (which blocks **everything**, the safe direction) plus an L5 human-only bundle deploy if a configuration unblock is needed. This explicitly removes the foot-gun where a hidden flag could bypass the gateway under operator pressure.

---

## 6. Duplicate-execution guard

### 6.1 Why duplicates happen

The orchestrator may emit the same `decision_id` more than once due to retry loops, connector ack timeouts, hot-reload-induced replay, or operator-level intent re-issue. The gateway must distinguish:
1. **Legitimate retry** (same idempotency intent, replay the prior decision).
2. **Collision** (different content under the same key — never silently accept).
3. **Fresh re-issue** (operator deliberately re-evaluates the same orchestrator decision; new key required).

### 6.2 Key derivation (`key_strategy = "lineage_v1"`)

The duplicate-guard key is:

```
dup_key = sha256(
  policy_bundle_version || "|" ||
  decision_id || "|" ||
  signal_id || "|" ||
  prediction_id || "|" ||
  feature_snapshot_id || "|" ||
  intent_action_canonical || "|" ||
  intent_qty_decimal_canonical || "|" ||
  intent_side || "|" ||
  intent_target_price_canonical_or_market || "|" ||
  trader_id || "|" ||
  exchange_symbol_id || "|" ||
  mode
)
```

`*_canonical` means: numbers stringified with no float, no scientific notation, no trailing zero stripping; "MARKET" used literally for market intents; uppercase symbol IDs.

The key incorporates `policy_bundle_version`: a new bundle version intentionally invalidates dedup so the same orchestrator decision is re-evaluated under the new policies.

### 6.3 Storage

Two-tier:
- **Tier 1 — Redis hot cache.** `v2:risk:dup:<dup_key>` stores `{risk_decision_id, allow_block, decision_payload_hash, created_ts_ms}`. TTL = `ttl_ms_paper` or `ttl_ms_live` (defaults 120s and 600s respectively).
- **Tier 2 — DB authoritative.** `risk_decisions.dup_key` is INDEXED. On Redis miss the gateway falls back to DB lookup of the most recent `risk_decisions` row with this `dup_key` within `(now - tier2_window_ms)`, default `tier2_window_ms = 24h`.

Redis is a cache; DB is source of truth. INV-07 implies the gateway never trusts Redis alone for safety-critical state.

### 6.4 Decision matrix

Inputs: a fresh orchestrator_decision arriving at `phase_duplicate` (i.e. having already passed all earlier phases).

| Cache | DB | `decision_payload_hash` match? | Action |
| --- | --- | --- | --- |
| miss | miss | n/a | Evaluate fresh. Store result in cache and DB. Return new `risk_decision`. |
| hit | n/a | yes | **Replay**: return the cached `risk_decision_id` and verdict. Mark `duplicate_kind = "replay"`. Idempotent. |
| hit | n/a | no | **Collision**: do not evaluate. Block with `block_reason = "duplicate_key_collision"`. Emit `audit_event` with both payload hashes. Do NOT update the cache entry. |
| miss | hit | yes | **Replay** from DB; warm cache. |
| miss | hit | no | **Collision** as above. |

`decision_payload_hash` is `sha256(canonicalized_orchestrator_decision_payload_excluding_request_id)` — i.e. it ignores transient fields like `request_id` so retries with new `request_id` correctly hit replay.

### 6.5 Distinguishing fresh re-issue

If an operator legitimately wants a re-evaluation of the same orchestrator decision under the same bundle, they MUST mint a new `decision_id` (orchestrator side) — there is no API on the gateway to "force re-evaluation." The gateway's duplicate guard is the **only** legitimate path; any operator workflow that needs to bypass it is mis-designed.

### 6.6 TTL and persistence

- Paper `ttl_ms = 120000` (2m) — paper retries are common, false collisions painful, and the safety cost of replay is zero.
- Live `ttl_ms = 600000` (10m) — live retries are rarer; 10 minutes is enough to absorb every realistic ack timeout/network blip.
- `tier2_window_ms = 86400000` (24h) — DB lookup window. Beyond this, the original bundle is likely no longer applied and a fresh evaluation is correct.
- Records older than `tier2_window_ms` remain in the DB ledger forever (audit). They are simply not consulted for dedup decisions.

### 6.7 Failure modes

| Failure | Behavior |
| --- | --- |
| Redis unreachable | Skip Tier 1, query Tier 2. If Tier 2 also unreachable → **block** with `block_reason = "duplicate_guard_storage_unavailable"`. Closed-on-error per §3.3. |
| DB unreachable | If Redis hit returns a record, replay. If Redis misses, **block** as above. |
| Both reachable, hash collision (extreme) | The collision branch above triggers naturally — no special path needed. SHA-256 collision risk is negligible for the volumes in scope. |

---

## 7. Stale-signal handling

### 7.1 Stale-age defaults

Codex Blocker 4 explicitly cites missing "stale-age defaults." The defaults below are normative for the V2 scaffold; bundles may tighten but loosening requires L4 approval.

| Signal class | Default `max_age_ms` | Tolerance | Clock |
| --- | --- | --- | --- |
| `tick_event` | 500 | 100 | `exchange_event_ts` |
| `orderbook_micro` | 1500 | 250 | `exchange_event_ts` |
| `kline_1s` | 1500 | 250 | `exchange_event_ts` |
| `kline_1m` | 60000 | 1000 | `exchange_event_ts` |
| `kline_5m` | 300000 | 5000 | `exchange_event_ts` |
| `kline_15m` | 900000 | 5000 | `exchange_event_ts` |
| `kline_1h` | 3600000 | 30000 | `exchange_event_ts` |
| `funding_event` | 3600000 | 60000 | `exchange_event_ts` |
| `liquidation_event` | 5000 | 1000 | `exchange_event_ts` |
| `default` | 10000 | 250 | `exchange_event_ts` |

`max_age_ms` is measured at the gateway as `(gateway_clock_now - signal.exchange_event_ts)`, where `gateway_clock_now` is monotonic UNIX epoch ms. The `tolerance_ms` is added to `max_age_ms` to absorb clock skew. Total reject threshold = `max_age_ms + tolerance_ms`.

### 7.2 Source-of-truth clock

The gateway uses `signal.exchange_event_ts` as the upstream timestamp. If `exchange_event_ts` is missing or later than `gateway_clock_now + 5000` (impossible-future-tolerance), the policy → **block** with `block_reason = "stale_signal_clock_invalid"`.

A separate `clock_skew_observation` event is emitted whenever `(gateway_clock_now - exchange_event_ts) > 0` AND `< -tolerance_ms`, providing a passive measurement stream for observability without changing the verdict.

### 7.3 Why default-deny on missing clock

If we used `now()` as a fallback when `exchange_event_ts` is missing, every late-arriving event would silently look "fresh." Default-deny eliminates this category of bug.

---

## 8. Kill-switch persistence and state machine

### 8.1 State machine

```
disarmed -> armed -> tripped
   ^            \-> armed (no-op)
   |
   |<-- (only via L4-approved reset, with explicit token)
```

| State | Gateway behavior |
| --- | --- |
| `disarmed` | Gateway refuses to accept any orchestrator decision. `block_reason = "kill_switch_disarmed"`. (Disarmed = "the brake itself is offline" — fail closed.) |
| `armed` | Normal operation. The kill switch is the safety brake, ready to be tripped. |
| `tripped` | Gateway blocks **everything**. `block_reason = "kill_switch_tripped"`. Reset requires L4 approval, an explicit `X-Kill-Switch-Reset-Token`, AND a positive monitor signal that the underlying triggering condition has cleared. |

### 8.2 Persistence (INV-07)

The kill-switch state lives in the DB table `kill_switch_state` (single row per `gateway_instance_id`) with columns: `state`, `transitioned_by_actor`, `transitioned_at_ts_ms`, `transition_reason`, `evidence_pointers_json`, `current_token_id`, `current_token_hash`, `state_lineage_id`. The gateway also caches state in `v2:risk:kill_switch:<instance_id>` for hot reads, but the cache is **read-through** from DB on boot and after every transition.

Process restart, Redis flush, host reboot, or DB primary failover MUST NOT lose the state. On boot, before the gateway accepts any traffic, it reads the DB row. If the DB read fails it boots into `disarmed` (the safest of the three since it blocks everything).

### 8.3 Trip triggers

The kill switch can be tripped by:
- Operator action: `POST /risk_policy/kill_switch:trip` (RBAC: `write:kill_switch`, L3).
- Monitor automatic trip: configured in the bundle as `auto_trip_on = ["liquidation_proximity_breached", "loss_cap_breached", "monitor_completeness_lost"]`. Each trigger produces a `kill_switch_state_lineage_id` linking the trip to the underlying evidence.

Programmatic auto-reset is forbidden. Reset is human-approved (`POST /risk_policy/kill_switch:reset`, RBAC `write:kill_switch`, L4, with `X-Approval-Token`).

### 8.4 Per-instance vs global

The kill switch is **per gateway instance**. Multi-instance deployments (e.g. one gateway per exchange) MUST have their kill switches replicated through a "global trip" service: any instance tripping `globally_propagating = true` causes every other instance to receive a trip event within a configurable propagation window (default `5s`). The propagation contract is:
- Tripped state always wins over armed/disarmed in the propagation merge.
- Reset is per-instance only; there is no global reset.

This asymmetry — fast-spread trip, slow-careful reset — is intentional.

---

## 9. Live-readiness state machine

### 9.1 States

```
blocked  -> ready_pending -> ready -> blocked
   ^                          |
   +--- (any failing gate) <--+
```

| State | Behavior |
| --- | --- |
| `blocked` (default) | `live_gate` policy → block with `block_reason = "live_gate_blocked"`. |
| `ready_pending` | All required gates pass, but the freshness window has not elapsed since the last gate verification. Treated as `blocked` for evaluation; `pending_until_ts_ms` recorded. |
| `ready` | All required gates pass AND verification within `ready_window_ms` AND `kill_switch = armed` AND `policy_bundle.applies_to.mode_scopes contains "live"`. |

### 9.2 Required gates

Mirroring `04_API_CONTRACT_REMEDIATION.md §7.4`:
1. `monitor_completeness` — `monitor_snapshots` show every required monitor reporting within freshness budget.
2. `risk_policy_signoff` — current bundle has L4 approval AND scope includes `live`.
3. `approval_workflow_active` — `approvals` table healthy, no quorum gaps.
4. `kill_switch_armed` — kill switch state = `armed` (not `tripped`, not `disarmed`).
5. `human_confirmation_present` — current request carries `X-Live-Confirm: I-UNDERSTAND` and `actor.actor_type == "human"`.

Gates 1–4 are **system gates** evaluated continuously and cached in `v2:risk:live_gate:state` with TTL `ready_window_ms`. Gate 5 is a **per-request** check, never cached.

### 9.3 Persistence

`live_gate_state` is stored in DB (table `live_gate_state`, single row per `gateway_instance_id`). The Redis cache is read-through. Boot behavior: on any unreadable persistence layer the gateway treats live gate as `blocked`.

### 9.4 State transitions are auditable

Every transition produces an `audit_event` with `actor`, `before_state`, `after_state`, `failing_gates_json`, `evidence_pointers_json`. This is what makes "live gate is blocked" a verifiable claim, not just a runtime assertion.

---

## 10. Connector-side hard blocks (defense in depth)

The Risk Gateway is the **primary** authority. Connector-side hard blocks are an **independent** secondary check that prevents a defective gateway, a leaked credential, or a malicious actor from injecting exchange actions that bypass the gateway.

### 10.1 Connector contract

Every exchange connector MUST refuse to call its underlying exchange SDK unless **all** the following hold:

| # | Check | Failure |
| --- | --- | --- |
| 10.1.1 | The action's `execution_intent_id` exists in DB. | Reject locally. Audit `connector_hard_block`, reason `unknown_execution_intent`. |
| 10.1.2 | `execution_intents.status = 'authorized_for_send'`. | Reject. Reason `execution_intent_not_authorized`. |
| 10.1.3 | `execution_intents.risk_decision_id` resolves to `risk_decisions.allow_block = 'allow'`. | Reject. Reason `risk_decision_not_allow`. |
| 10.1.4 | `risk_decisions.policy_bundle_version` matches the currently applied bundle, OR is within the bundle's grace window (default `0`). | Reject. Reason `stale_policy_bundle`. |
| 10.1.5 | Lineage hash recomputed from DB rows matches `execution_intents.lineage_hash`. | Reject. Reason `lineage_tampered`. |
| 10.1.6 | If `mode = "live"`: `kill_switch_state.state = 'armed'` AND `live_gate_state.state = 'ready'`. | Reject. Reason `live_block_active_at_connector`. |
| 10.1.7 | The connector's local idempotency cache does not show this `execution_intent_id` already submitted. | Replay (return prior result). |
| 10.1.8 | Connector itself is `enabled = true` and `live_enabled = true` (if live). | Reject. Reason `connector_live_disabled`. |

Every hard-block produces an `audit_event` with `actor.actor_type = "system"`, `actor_id = "<connector_id>"` and includes the offending payload hash. Hard blocks at the connector are critical-severity alerts: they should not happen in a healthy system, because they imply the upstream gateway logic disagrees with the connector logic.

### 10.2 Why the redundancy

- The gateway and the connector run in different processes (often different hosts).
- A bug in the gateway that wrongly issues `allow` is partially caught by the connector's revalidation.
- A future attacker with API access but without DB write access cannot synthesize a fake `execution_intent` row.
- This is the architectural answer to "no bypass can be formally verified": even if the gateway is bypassed, the connector still refuses.

### 10.3 Shared truth surface

Both gateway and connector read from the same DB tables (`execution_intents`, `risk_decisions`, `policy_bundles`, `kill_switch_state`, `live_gate_state`). Neither computes its own version; this avoids the class of bugs where two services hold diverging "current" state.

---

## 11. Risk decision envelope

### 11.1 DDL fragments (companion to `03_DATABASE_SCHEMA.md`)

```sql
-- new table: policy bundles
CREATE TABLE risk_policy_bundles (
  policy_bundle_id            UUID PRIMARY KEY,
  policy_bundle_version       TEXT NOT NULL UNIQUE,
  evaluation_order_hash       TEXT NOT NULL,
  bundle_hash                 TEXT NOT NULL,
  state                       TEXT NOT NULL CHECK (state IN ('draft','validated','approved','staged','applied','superseded','rolled_back')),
  applies_to_json             JSONB NOT NULL,
  policies_json               JSONB NOT NULL,
  rollback_target_version     TEXT NOT NULL,
  created_by_actor_type       TEXT NOT NULL,
  created_by_actor_id         TEXT NOT NULL,
  created_ts_ms               BIGINT NOT NULL,
  applied_ts_ms               BIGINT
);

-- new table: kill switch persisted state
CREATE TABLE kill_switch_state (
  gateway_instance_id         TEXT PRIMARY KEY,
  state                       TEXT NOT NULL CHECK (state IN ('disarmed','armed','tripped')),
  transitioned_by_actor_type  TEXT NOT NULL,
  transitioned_by_actor_id    TEXT NOT NULL,
  transitioned_at_ts_ms       BIGINT NOT NULL,
  transition_reason           TEXT NOT NULL,
  evidence_pointers_json      JSONB NOT NULL,
  state_lineage_id            UUID
);

-- new table: live gate persisted state
CREATE TABLE live_gate_state (
  gateway_instance_id         TEXT PRIMARY KEY,
  state                       TEXT NOT NULL CHECK (state IN ('blocked','ready_pending','ready')),
  failing_gates_json          JSONB NOT NULL,
  last_evaluated_ts_ms        BIGINT NOT NULL,
  ready_until_ts_ms           BIGINT
);

-- amend existing table: risk_decisions (additions)
ALTER TABLE risk_decisions
  ADD COLUMN gateway_instance_id  TEXT NOT NULL,
  ADD COLUMN policy_bundle_version TEXT NOT NULL,
  ADD COLUMN evaluation_order_hash TEXT NOT NULL,
  ADD COLUMN dup_key               TEXT NOT NULL,
  ADD COLUMN duplicate_kind        TEXT CHECK (duplicate_kind IN ('fresh','replay','collision')) NOT NULL,
  ADD COLUMN precedence_resolution_json JSONB,
  ADD COLUMN feature_snapshot_id   UUID NOT NULL,
  ADD COLUMN prediction_id         UUID NOT NULL,
  ADD COLUMN signal_id             UUID NOT NULL,
  ADD COLUMN lineage_hash          TEXT NOT NULL;
CREATE INDEX risk_decisions_dup_key_idx       ON risk_decisions (dup_key, created_ts_ms);
CREATE INDEX risk_decisions_lineage_idx       ON risk_decisions (signal_id, decision_id);
CREATE UNIQUE INDEX risk_decisions_decision_unique ON risk_decisions (decision_id);

-- amend existing table: execution_intents (additions)
ALTER TABLE execution_intents
  ADD COLUMN lineage_hash         TEXT NOT NULL,
  ADD COLUMN status               TEXT NOT NULL CHECK (
    status IN ('authorized_for_send','sent','acked','filled','rejected','superseded')
  );
```

### 11.2 `risk_decision` event payload

```json
{
  "schema_version": "1.0.0",
  "risk_decision_id": "uuid-v7",
  "gateway_instance_id": "string",
  "policy_bundle_version": "2026.04.30-001",
  "evaluation_order_hash": "sha256:<hex>",
  "lineage": {
    "feature_snapshot_id": "uuid-v7",
    "prediction_id": "uuid-v7",
    "signal_id": "uuid-v7",
    "decision_id": "uuid-v7",
    "lineage_hash": "sha256:<hex>",
    "lineage_gap_reason": null
  },
  "decision_id": "uuid-v7",
  "trader_id": "string",
  "exchange_symbol_id": "string",
  "mode": "paper-or-live",
  "allow_block": "allow-or-block",
  "block_reason": "string|null",
  "block_policy_id": "string|null",
  "duplicate_kind": "fresh|replay|collision",
  "dup_key": "sha256:<hex>",
  "precedence_resolution_json": [
    { "policy_id": "...", "rank": 1, "verdict": "block" }
  ],
  "policy_checks_json": [ /* per-policy entries from §4.3 */ ],
  "evaluated_ts_ms": 1735689600400,
  "kill_switch_snapshot": { "state": "armed", "snapshot_ts_ms": 1735689600350 },
  "live_gate_snapshot": { "state": "blocked", "failing_gates": [ "human_confirmation_present" ], "snapshot_ts_ms": 1735689600350 }
}
```

`lineage_hash = sha256(feature_snapshot_id || prediction_id || signal_id || decision_id || risk_decision_id)`.

### 11.3 Lineage stamping

The gateway is the canonical writer of the `risk_decision_id` part of the lineage tuple (consolidated Codex blocker #1). Downstream `execution_intents` MUST copy `lineage_hash` from `risk_decisions` and add `execution_intent_id` to it via:
`execution_intents.lineage_hash = sha256(risk_decisions.lineage_hash || execution_intent_id)`.

This makes connector-side `lineage_tampered` detection (§10.1.5) a single hash recomputation against the DB rows — cheap and unambiguous.

---

## 12. Test-vector matrix

These vectors are normative: any V2 Risk Gateway scaffold MUST pass every vector before Codex Blocker 4 is closed. Vectors are organized by phase, then by intended verdict. Each vector specifies (a) input fixture name, (b) expected verdict, (c) expected `block_policy_id`, (d) expected `block_reason` substring, (e) expected `duplicate_kind`, (f) replay re-determinism check.

For brevity, fixtures are referenced by stable IDs; their canonical JSON forms live alongside the implementation under `v2/risk_gateway/test_fixtures/` (created during scaffold, not in this document). All fixtures share a common base (`fixture.base.json`) that defines a healthy decision; each vector specifies the deltas applied to the base.

### 12.1 Boot / bundle integrity

| ID | Setup | Expected verdict | Expected `block_reason` |
| --- | --- | --- | --- |
| TV-BOOT-01 | No bundle loaded | block | `no_policy_bundle_loaded` |
| TV-BOOT-02 | Bundle loaded but `bundle_hash` mismatch | block | `policy_bundle_integrity_hash_mismatch` |
| TV-BOOT-03 | Bundle `evaluation_order_hash` mismatch | block | `policy_bundle_integrity_order_mismatch` |
| TV-BOOT-04 | Two bundles with same `policy_bundle_version` present in DB | block (boot fail) | `policy_bundle_version_collision` |
| TV-BOOT-05 | DB unreachable on boot | block (default deny) | `policy_bundle_unloadable` |

### 12.2 Stale-signal

| ID | Setup | Expected verdict | Expected `block_reason` |
| --- | --- | --- | --- |
| TV-STALE-01 | `kline_1m` signal `age_ms = 60000` exactly | allow | — |
| TV-STALE-02 | `kline_1m` signal `age_ms = 61001` (over `max_age + tolerance`) | block | `stale_signal_kline_1m` |
| TV-STALE-03 | Signal missing `exchange_event_ts` | block | `stale_signal_clock_invalid` |
| TV-STALE-04 | `exchange_event_ts` 6000ms in the future | block | `stale_signal_clock_invalid` |
| TV-STALE-05 | Custom `by_signal_type` override `max_age_ms = 100`; signal `age_ms = 200` | block | `stale_signal_<type>` |

### 12.3 Lineage / attribution completeness

| ID | Setup | Expected verdict | Expected `block_reason` |
| --- | --- | --- | --- |
| TV-LIN-01 | Missing `prediction_id` | block | `lineage_completeness_missing_prediction_id` |
| TV-LIN-02 | All IDs present, lineage_hash computes correctly | allow | — |
| TV-LIN-03 | `confidence_event` missing | block | `attribution_completeness_missing_confidence` |
| TV-LIN-04 | `top_positive` cardinality `2` (under `min_top_positive=3`) | block | `attribution_completeness_top_positive_cardinality` |
| TV-LIN-05 | `calibration_version` missing | block | `attribution_completeness_calibration_version` |

### 12.4 Kill switch

| ID | Setup | Expected verdict | Expected `block_reason` |
| --- | --- | --- | --- |
| TV-KS-01 | `kill_switch_state = tripped` | block | `kill_switch_tripped` |
| TV-KS-02 | `kill_switch_state = disarmed` | block | `kill_switch_disarmed` |
| TV-KS-03 | `kill_switch_state = armed` | allow (subject to other policies) | — |
| TV-KS-04 | Trip then process restart, DB intact | still tripped | `kill_switch_tripped` |
| TV-KS-05 | Trip then Redis flush, DB intact | still tripped (Redis re-warmed from DB) | `kill_switch_tripped` |
| TV-KS-06 | Trip without `state_lineage_id` (synthetic) | reject the trip itself; state remains armed | n/a (the trip API rejects) |

### 12.5 Capital / sizing / leverage

| ID | Setup | Expected verdict | Expected `block_reason` |
| --- | --- | --- | --- |
| TV-CAP-01 | Leverage requested = `5.0`, cap `5.0` | allow | — |
| TV-CAP-02 | Leverage requested = `5.001`, cap `5.0` | block | `leverage_cap_exceeded` |
| TV-CAP-03 | Margin mode `CROSS` proposed, lock `ISOLATED` | block | `margin_mode_lock_violation` |
| TV-CAP-04 | Notional `9999.99` USD, cap `10000` (default) | allow | — |
| TV-CAP-05 | Notional `10001` USD | block | `position_sizing_per_symbol` |
| TV-CAP-06 | Mark price source stale beyond `mark_price_max_age_ms` | block | `position_sizing_mark_stale` |

### 12.6 Account caps

| ID | Setup | Expected verdict | Expected `block_reason` |
| --- | --- | --- | --- |
| TV-ACC-01 | Today's loss = `$999`, cap `$1000`, intent loss potential `$2` | block | `daily_loss_cap_breach_predicted` |
| TV-ACC-02 | DB view `v_pnl_today_per_account` unavailable | block | `daily_loss_cap_basis_unavailable` |
| TV-ACC-03 | Drawdown `12%`, brake `10%` | block | `drawdown_brake_exceeded` |

### 12.7 Duplicate guard

| ID | Setup | Expected verdict | `duplicate_kind` |
| --- | --- | --- | --- |
| TV-DUP-01 | First arrival of `decision_id=A` | allow (assuming other passes) | `fresh` |
| TV-DUP-02 | Second arrival of identical `decision_id=A` payload | replay (same `risk_decision_id`) | `replay` |
| TV-DUP-03 | Second arrival of `decision_id=A` with different `intent_qty` | block | `collision` |
| TV-DUP-04 | New `policy_bundle_version` deployed; same `decision_id=A` arrives again | allow (re-evaluated) | `fresh` |
| TV-DUP-05 | Redis unavailable, DB has prior record matching | replay | `replay` |
| TV-DUP-06 | Redis and DB both unavailable | block | `duplicate_guard_storage_unavailable` |
| TV-DUP-07 | Replay arrives after `tier2_window_ms` (24h) | allow (fresh re-evaluation) | `fresh` |

### 12.8 Live gate

| ID | Setup | Expected verdict | `failing_gates` includes |
| --- | --- | --- | --- |
| TV-LIVE-01 | `mode = paper` always | allow | n/a |
| TV-LIVE-02 | `mode = live`, all gates pass, human confirm absent | block | `human_confirmation_present` |
| TV-LIVE-03 | `mode = live`, all gates pass, header present, actor `claude` | block | `human_confirmation_present` |
| TV-LIVE-04 | `mode = live`, all gates pass, header present, actor `human`, kill switch `tripped` | block | `kill_switch_armed` |
| TV-LIVE-05 | `mode = live`, all gates pass, `live_gate_state` last evaluated `> ready_window_ms` ago | block | `live_gate_state_stale` |
| TV-LIVE-06 | `mode = live`, all gates pass, fresh, kill switch armed, human + token | allow | — |

### 12.9 Precedence

Run with `evaluate_all_phases = true`.

| ID | Concurrent blockers | Expected authoritative `block_reason` |
| --- | --- | --- |
| TV-PREC-01 | `kill_switch` + `daily_loss_cap` + `stale_signal` | `kill_switch_tripped` |
| TV-PREC-02 | `daily_loss_cap` + `leverage_cap` | `daily_loss_cap_*` |
| TV-PREC-03 | `leverage_cap` + `position_sizing` (same rank) | tie-broken by `(phase_order, order_in_phase, policy_id_lex)` |
| TV-PREC-04 | `duplicate_guard` + `stale_signal` | `stale_signal_*` (rank 7 < rank 8) |
| TV-PREC-05 | `live_gate` + `daily_loss_cap` (live mode) | `live_gate_*` (rank 3 < rank 4) |

### 12.10 Connector hard blocks

| ID | Setup | Expected outcome |
| --- | --- | --- |
| TV-CONN-01 | Synthesized exchange action whose `execution_intent_id` not in DB | reject; audit `unknown_execution_intent` |
| TV-CONN-02 | `execution_intents.status = sent` already, retry submitted | replay (idempotent) |
| TV-CONN-03 | Tampered `lineage_hash` | reject; audit `lineage_tampered` |
| TV-CONN-04 | `risk_decisions.allow_block = block` but `execution_intents.status = authorized_for_send` (corrupt) | reject; audit `risk_decision_not_allow` |
| TV-CONN-05 | `policy_bundle_version` in `risk_decisions` superseded | reject; audit `stale_policy_bundle` |
| TV-CONN-06 | Live mode but `live_gate_state.state != ready` at connector | reject; audit `live_block_active_at_connector` |

### 12.11 Determinism (INV-04)

| ID | Setup | Check |
| --- | --- | --- |
| TV-DET-01 | Replay each of the above vectors twice with identical inputs | byte-equal `policy_checks_json`, equal `allow_block`, equal `block_reason` |
| TV-DET-02 | Replay TV-DUP-01..03 using a frozen wall-clock fixture | byte-equal results |
| TV-DET-03 | Re-run TV-LIVE-* with identical `live_gate_snapshot` and `kill_switch_snapshot` | byte-equal results |

### 12.12 Closed-on-error

| ID | Setup | Expected verdict |
| --- | --- | --- |
| TV-ERR-01 | `position_sizing` policy raises an unhandled runtime exception | block, `evaluator_error_class = "<...>"` |
| TV-ERR-02 | DB unreachable mid-evaluation | block, `<policy>_evaluator_error` |
| TV-ERR-03 | Mark price feed returns `null` | block, `position_sizing_mark_stale` (handled, not crashed) |

### 12.13 Non-bypass invariants (INV-01..12)

| ID | Setup | Assertion |
| --- | --- | --- |
| TV-INV-01 | Attempt to insert `execution_intents` row whose `risk_decision_id` is `null` | rejected by FK + CHECK |
| TV-INV-02 | Attempt to insert `execution_intents` row whose `risk_decisions.allow_block != allow` | rejected by service-layer guard + nightly assertion |
| TV-INV-03 | Static analysis: enumerate all call-sites of the connector submit path | exactly one site, in the executor; reads `execution_intents` only |
| TV-INV-04 | Static analysis: enumerate all writes to `risk_policy_bundles` of state ≥ `applied` | every transition has a matching `approvals` row at the right level |
| TV-INV-05 | Bundle deploy attempted by `actor_type=claude` for L5 change | rejected by route guard (per `04_API_CONTRACT_REMEDIATION.md §2.3`) |
| TV-INV-06 | `paper` and `live` mode evaluations run identical policies (excluding `live_gate`) | identical `policy_checks_json` ordering |

---

## 13. Audit and evidence-packet requirements

### 13.1 Per-decision audit

Every `risk_decision` produces:
- One `risk_decisions` row (canonical record).
- Zero or more `audit_events` rows for any state-changing side-effect (kill-switch-trip-on-loss-cap, bundle-shadow-drift, etc.).
- Zero or one `evidence_packet` row of `packet_type = "alert"` if the decision's `block_reason` matches the bundle's `alert_on` glob list.

### 13.2 Hourly evidence packet

A scheduled `evidence_packet` of `packet_type = "hourly"` emits aggregated counters: decisions per `block_policy_id`, `duplicate_kind` distribution, kill-switch transitions, live-gate transitions, shadow-mode drift rate, average policy elapsed time per type. This packet is the primary surface for the Monitor Center's "risk gate status" panel (per `CLAUDE.md` Monitor Center Requirements).

### 13.3 Evidence pointers in API errors

Per `04_API_CONTRACT_REMEDIATION.md §3.3`, every `risk_gate_block` API response carries `evidence_pointers` to (a) the `risk_decisions.risk_decision_id`, (b) the `policy_bundle_version` bundle row, (c) the `policy_id` that blocked, (d) the upstream `signal_id`/`decision_id`. This makes operator debugging deterministic.

### 13.4 Bundle deploy audit

Every transition in §2.2 produces a `risk_policy_bundles` state-change row plus an `audit_events` row referencing the diff against the prior version. L4/L5 transitions additionally produce an `ai_action_changes` row when the proposing actor is non-human.

---

## 14. Traceability — Codex Blocker 4 sub-claims to closing sections

The actual Codex CLI output (line 17 of `12_ACTUAL_CODEX_CLI_ARCHITECTURE_REVIEW_OUTPUT.md`) enumerates the missing items. Each is closed below.

| Codex sub-claim | Closed by |
| --- | --- |
| "no concrete execution-order invariants" | §1 (INV-04, INV-05), §4 (phases + within-phase order), §11.1 (`evaluation_order_hash` column), §12.11 (determinism vectors) |
| "live readiness state" | §9 (state machine, persistence, gates), §11.1 (`live_gate_state` table), §12.8 (live-gate vectors) |
| "kill-switch persistence" | §1 (INV-07), §8 (state machine + persistence + boot behavior + propagation), §11.1 (`kill_switch_state` table), §12.4 (kill-switch vectors incl. restart/flush) |
| "policy bundle versioning" | §2 (envelope, state machine, persistence, hashes), §3 (per-type schemas), §11.1 (`risk_policy_bundles` table), §12.1 (boot vectors) |
| "connector-side hard blocks" | §10 (connector contract, redundancy rationale, shared truth), §12.10 (connector vectors) |
| "stale-age defaults" | §7 (defaults table, source-of-truth clock, default-deny on missing clock), §12.2 (stale vectors) |
| "duplicate-key strategy" | §6 (key derivation, two-tier storage, decision matrix, fresh-re-issue policy, failure modes), §12.7 (duplicate vectors) |
| "policy schema contract" | §2 (envelope), §3 (catalog + per-type fragments + universal invariants), §11 (DDL + decision payload) |
| "sufficient to prove live exchange action cannot bypass Risk Gateway" | §1 invariants (INV-01, INV-02, INV-10, INV-11) + §10 connector hard blocks + §12.13 non-bypass vectors. The proof structure: the only path to the connector submit step requires (a) an `execution_intents` row, which (b) requires `risk_decisions.allow_block = "allow"` (FK+CHECK), and (c) the connector independently re-verifies via §10. Bypass requires defeating two independent guards and corrupting the DB. |

---

## 15. Requirement coverage

This document satisfies the following V2 requirements (per `00_REQUIREMENTS_INDEX_AND_NORMALIZATION.md`):

| Requirement | Coverage |
| --- | --- |
| 01 Observability and attribution | §3 (`attribution_completeness`), §11.2 (`policy_checks_json`), §13 (audit/evidence packets) |
| 03 Prediction → signal → decision ID chain | §1 (INV-09), §11.2 (`lineage` in decision), §11.3 (lineage stamping) |
| 04 Confidence explainability schema | §3.2.8 (`attribution_completeness` defaults match consolidated blocker #3) |
| 08 / 18 Pre-V2 build exit criteria | §12 (test-vector matrix is the explicit gate for Codex Blocker 4) |
| 10 Enterprise website product | §13.2 (Monitor Center risk gate panel surface) |
| 11 / 14 / 19 Universe / hot reload / discovery | §3 (`symbol_universe_membership`), §10.1.4 (bundle-version freshness at connector) |
| 13 Multi-trader fleet | §2.1 (`applies_to.trader_scopes`), §11.2 (`trader_id` in decision) |
| 12 Multi-exchange connectors | §10 (connector contract is per-connector), §11.2 (`exchange_symbol_id` in decision) |
| 15 Public hosting and security | §1 (INV-06 approval enforcement), §2.2 (RBAC scopes per transition) |
| 20 AI supervision and autonomous change governance | §2.2 (L4/L5 transitions), §1 (INV-06), §13.4 (bundle deploy audit) |
| 21 Updated enterprise architecture readiness | §14 traceability table demonstrates remediation closes Codex Blocker 4 |

---

## 16. Out-of-scope (deferred to other remediation files)

- Lineage DDL in `feature_snapshots`/`feature_values` (consolidated Codex blocker #1, #2) — covered in `claude_worklog/v2_architecture_remediation/` future files (not yet created at time of writing).
- Audit hash-chain / tamper-evidence (consolidated Codex blocker #6) — future file.
- Hot-reload per-component ack persistence (consolidated Codex blocker #5) — future file.
- RBAC user/session/MFA tables (consolidated Codex blocker #7) — partially companion of `04_API_CONTRACT_REMEDIATION.md §2`, finalized in future file.
- Trainer liveness exit-criterion artifact (consolidated Codex blocker #8) — future file (not Risk Gateway).

This file does not attempt to close those blockers; it only ensures its own contracts (§2.2 approval levels, §11.2 lineage tuple, §10 connector revalidation) are written so they compose correctly with those forthcoming files.

---

## 17. Gate recommendation

Codex Blocker 4 ("Risk Gateway final authority is asserted, not enforceably designed") requires:
- enforceable schema → §2, §3, §11
- API contracts → already in `04_API_CONTRACT_REMEDIATION.md` and re-bound here
- validation gates → §12 test-vector matrix
- evidence artifacts → §13

If the V2 scaffold implements §1–§13 verbatim and a re-run of Codex CLI architecture review confirms the test-vector matrix is enforced (e.g. via CI assertions on the `v2/risk_gateway/test_fixtures/` scaffold), Codex Blocker 4 is closeable.

Until that re-review returns explicit PASS/GO, **V2 build remains NO-GO** per the consolidated reconciliation. This document is an architecture-layer remediation only; it does not constitute build approval, live-trading approval, or any mutation of the legacy runtime.

`LIVE TRADING: BLOCKED` (default-deny posture preserved.)