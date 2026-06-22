# Operator Decision Form — Paper-Only Legacy Shutdown Decision Capture

Generated: 2026-05-25T05:30:00Z
Git HEAD: 10513bbe0517fd81c9c87e4672bb15486a083c02
Lane: `v2_operator_paper_only_shutdown_decision_capture`
GO/NO-GO: `V2_OPERATOR_PAPER_ONLY_SHUTDOWN_DECISION_CAPTURE_READY`

## Required Safety Text (do not edit)

- This does not approve live.
- This does not approve canary.
- This does not approve Redis trim.
- This does not approve exchange mutation.
- This does not change leverage/margin.
- This is paper-only shutdown decision capture.

## How To Use This Form

1. This form is a decision-capture surface. Filling it out does NOT execute any
   shutdown, trim, or exchange action.
2. For each of the nine items, select exactly one option (A, B, or C). The
   recommended conservative default is shown.
3. After selecting, sign the acceptance file at
   `claude_worklog/approvals/OPERATOR_ACCEPTS_V2_PAPER_ONLY_SHUTDOWN_LIMITATIONS.md`
   with the required positive language (`paper-only`,
   `live_gate = blocked_human_only`, `live_symbols = []`,
   `does not approve live`, `does not approve canary`,
   `does not approve exchange mutation`, `does not approve leverage`,
   `does not approve margin`, `does not approve Redis trim`).
4. No approval token is created by this packet. Live and canary remain
   `blocked_human_only` regardless of which options are selected here.
5. If any item selects `REQUIRE_IMPLEMENTATION_BEFORE_SHUTDOWN` or
   `DEFER_KEEP_LEGACY_RUNNING`, the final shutdown recommendation remains
   `BLOCK_LEGACY_SHUTDOWN_PRODUCTION_EQUIVALENCE_INCOMPLETE`.

## Options Legend

- **A — ACCEPT_FOR_PAPER_ONLY_SHUTDOWN**: Operator explicitly accepts the
  documented limitation for paper-only shutdown evaluation only. Live and
  canary stay blocked. No approval token is created.
- **B — REQUIRE_IMPLEMENTATION_BEFORE_SHUTDOWN**: Operator requires the
  implementation/evidence to be complete before any paper-only shutdown
  decision is captured.
- **C — DEFER_KEEP_LEGACY_RUNNING**: Operator defers. Legacy continues to
  run. V2 remains paper-only.

---

## 1. `full_observation_builder.operator_decision_families`

Decision label: paper-edge threshold and unified-feature acceptance.

- Current evidence: source packet `final_operator_decision_center.json`;
  current_status `PENDING_OPERATOR_DECISION`; operator decision families for
  paper-edge thresholds and unified-feature acceptance are explicit and
  unaccepted.
- Why it blocks shutdown/live: Production equivalence cannot mark resolved
  while operator-controlled paper-edge thresholds and unified-feature
  acceptance remain unselected.
- Recommended conservative default: **C — DEFER_KEEP_LEGACY_RUNNING**.
- Risk if accepted: Paper-only shutdown could proceed without strict
  operator-numeric thresholds; live/canary still blocked.
- Risk if deferred: Legacy keeps running; V2 production-equivalence stays
  incomplete.

Operator selection (write one of A, B, C; leave blank if not yet decided):

```text
operator_selected_option: <blank>
operator_accepted: false
operator_signed_at_utc: <blank>
```

---

## 2. `checkpoint_promotion`

Decision label: checkpoint/model promotion limitation.

- Current evidence: `p0_2g_checkpoint_weight_status =
  CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED`. Promotion path is not signed.
- Why it blocks shutdown/live: Without a signed checkpoint promotion, V2
  inference parity with legacy cannot be claimed; paper-only continuity is at
  risk.
- Recommended conservative default: **C — DEFER_KEEP_LEGACY_RUNNING**.
- Risk if accepted: V2 may run paper without a fully-signed checkpoint;
  audit lineage gaps may appear.
- Risk if deferred: Migration delay; no exchange-side risk.

```text
operator_selected_option: <blank>
operator_accepted: false
operator_signed_at_utc: <blank>
```

---

## 3. `legacy_shutdown.legacy_runtime_owner`

Decision label: legacy runtime stop acceptance.

- Current evidence: No operator-signed acceptance to stop legacy runtime
  owner. Legacy processes remain active.
- Why it blocks shutdown/live: Stopping legacy requires explicit operator
  authority. Without it, no shutdown action is permitted.
- Recommended conservative default: **C — DEFER_KEEP_LEGACY_RUNNING**.
- Risk if accepted: Operator commits to a stop intent (the actual stop is a
  separate runbook). Misexecution outside the runbook could disrupt
  observability.
- Risk if deferred: Dual-system overhead continues; no exchange-side risk.

```text
operator_selected_option: <blank>
operator_accepted: false
operator_signed_at_utc: <blank>
```

---

## 4. `legacy_shutdown.legacy_redis_keys_active`

Decision label: legacy Redis trim / retention decision.

- Current evidence: Legacy Redis keys still hold live data lineage. No
  operator decision to trim or retain.
- Why it blocks shutdown/live: Without an explicit operator decision on
  trim/retention, V2 cannot safely assume legacy Redis is decommissioned.
  Trimming without authority risks lineage loss.
- Recommended conservative default: **C — DEFER_KEEP_LEGACY_RUNNING**.
- Risk if accepted: Operator captures intent to retain legacy Redis
  read-only as frozen lineage. The capture itself does not trim Redis.
- Risk if deferred: Storage growth and audit ambiguity continue; no
  exchange-side risk.

```text
operator_selected_option: <blank>
operator_accepted: false
operator_signed_at_utc: <blank>
```

---

## 5. `risk_caps_canary_hard_gates_unset`

Decision label: risk/capital caps and canary hard gates.

- Current evidence: Hard risk caps and canary gates are unset; no
  operator-signed numeric caps exist.
- Why it blocks shutdown/live: Paper-only shutdown evaluation requires the
  documented live/canary risk frame, even though live remains blocked.
- Recommended conservative default: **C — DEFER_KEEP_LEGACY_RUNNING**.
- Risk if accepted: Caps remain unset; any future canary attempt must trip a
  fresh operator gate.
- Risk if deferred: Continued dual-system; no exchange-side risk.

```text
operator_selected_option: <blank>
operator_accepted: false
operator_signed_at_utc: <blank>
```

---

## 6. `capital_recovery_gate_unset`

Decision label: capital recovery threshold / risk guard acceptance.

- Current evidence: Capital recovery threshold and risk guard are unset and
  operator-required.
- Why it blocks shutdown/live: Paper-edge proof statistics and any future
  canary capital frame rely on this threshold.
- Recommended conservative default: **C — DEFER_KEEP_LEGACY_RUNNING**.
- Risk if accepted: No numeric recovery target captured; paper-only metrics
  may lack a defensible boundary. Live remains blocked.
- Risk if deferred: Continued dual-system overhead; no exchange-side risk.

```text
operator_selected_option: <blank>
operator_accepted: false
operator_signed_at_utc: <blank>
```

---

## 7. `full_observation_builder.external_sources`

Decision label: external source adoption (onchain_btc, onchain_eth,
unified_feature_family.token_metrics).

- Current evidence: classification `SOURCE_MISSING_KEY_OPERATOR_REQUIRED`;
  `raw_values_read=false`; `raw_key_values_exposed=false`;
  `free_tier_codex_safe_confirmed_by_env_name_presence=false`. The capture
  checks env-var names only and never reads raw secret values. Missing env
  names by family: onchain_btc, onchain_eth, unified_feature_family.token_metrics.
- Why it blocks shutdown/live: Full observation builder cannot satisfy
  external-source families without operator-approved adoption (free-tier
  confirmation OR paid-tier secret name presence).
- Recommended conservative default: **C — DEFER_KEEP_LEGACY_RUNNING**.
- Risk if accepted: Full observation operates with documented external
  gaps; live remains blocked so no exchange risk.
- Risk if deferred: Continued dual-system; no exchange-side risk.

```text
operator_selected_option: <blank>
operator_accepted: false
operator_signed_at_utc: <blank>
```

---

## 8. `full_observation_builder.event_dependent`

Decision label: event-dependent liquidation / full-observation watcher.

- Current evidence: watcher_id `event_watcher_1_liquidation_source`;
  `current_observed_state=WAITING_FOR_REAL_LIQUIDATION_EVENT_OR_SOURCE`;
  `pass_condition_satisfied=false`;
  `symbols_with_any_v2_liquidation_key_populated_count=0`;
  `v2_liquidation_aggregator_per_symbol_source_available=false`;
  `no_synthetic_liquidation_events=true`.
- Why it blocks shutdown/live: Full observation requires real per-symbol
  liquidation events. Watcher must stay open until real evidence is seen.
- Recommended conservative default: **C — DEFER_KEEP_LEGACY_RUNNING**.
- Risk if accepted: Full observation continues with documented liquidation
  gap; live remains blocked.
- Risk if deferred: Continued dual-system; no exchange-side risk.

```text
operator_selected_option: <blank>
operator_accepted: false
operator_signed_at_utc: <blank>
```

---

## 9. `paper_edge_not_proven`

Decision label: paper-edge proof watcher.

- Current evidence: watcher_id `event_watcher_2_paper_edge_evidence`;
  `current_observed_state=WAITING_FOR_EDGE_PROOF_AND_OPERATOR_THRESHOLDS`;
  `pass_condition_satisfied=false`;
  `miner_verdict=EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED`;
  `expected_move_after_cost_bps=-8.981832584893514`;
  `after_cost_ci_lower_bps=-13.090729934534577`;
  `edge_claimed=false`; `minimum_sample_satisfied=false`;
  `no_fabricated_outcomes=true`.
- Why it blocks shutdown/live: Paper-edge is the foundation of any
  post-legacy decision. Negative after-cost edge with unset operator
  thresholds means paper-only shutdown cannot claim a defensible edge frame.
- Recommended conservative default: **B —
  REQUIRE_IMPLEMENTATION_BEFORE_SHUTDOWN**.
- Risk if accepted: V2 operates paper-only with an explicitly unproven
  edge; misinterpretation risk if anyone treats this as a green light.
- Risk if deferred: Continued dual-system; no exchange-side risk.

```text
operator_selected_option: <blank>
operator_accepted: false
operator_signed_at_utc: <blank>
```

---

## After Form Submission

- This file is not parsed by any auto-acceptance worker. Selections in this
  form do not, by themselves, change `paper_only_shutdown_decision_capture.json`.
- To record acceptances, operator updates the JSON capture explicitly AND
  signs `claude_worklog/approvals/OPERATOR_ACCEPTS_V2_PAPER_ONLY_SHUTDOWN_LIMITATIONS.md`
  with all required literals.
- No live approval token, Redis-trim approval marker, or
  exchange-mutation artifact is created by this lane under any circumstances.
- Live gate remains `blocked_human_only`. `live_symbols=[]`.
