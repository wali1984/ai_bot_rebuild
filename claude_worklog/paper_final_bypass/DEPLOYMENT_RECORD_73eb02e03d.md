# FINAL PAPER POLICY-GATE BYPASS — deployment record

- Directive: operator 2026-07-31 "FINAL PAPER POLICY-GATE BYPASS — NO MORE
  EXCEPTIONS OR MONITOR-ONLY COMPLETION" (items 1-11).
- **Frozen acceptance SHA: `1811ec94689448234d6af82f51645c263c67657c`**
  (deployed 05:50Z; = 84ff48c1e7 + persisted allocator zero-diagnostics
  (Signal Explainability) + TRADING_POLICY classification for
  calibration-unfitted and after-cost-edge-zero/direction families.)
- Superseded during same-pass hardening: `84ff48c1e7df5a6d5680ba0258f6d5862a0badfb`
  (branch `release/paper-final-bypass`; `73eb02e03d` + the exposure-validator
  fixes + the at-source router-leak fix below; parent line `53dec2e343`).
- Deployed: 2026-07-31T05:34:37Z, unit
  `ai-bot-v2-trade-management-paper-loop.service`, PID 606399, immutable
  snapshot `/home/wali/ai_bot_local_data/deployments/ai_bot_rebuild/84ff48c1e7…`.
- `84ff48c1e7` completions over `ae3b8bcce8`: (a) the runtime ledger
  projection has no 'accepted' key, so the admission-row fallback now sources
  persisted fills from the bounded v2:paper:accepted_fills read (replayed
  READY against the TRUE runtime ledger construction); (b) at-source item-4
  leak fixed — the legacy router comparator diverted TRADING_POLICY reasons
  (strategy_router:PAPER_LOSS_BUCKET_QUARANTINE) to
  strategy_router_trading_policy_telemetry_reasons instead of
  local_block_reasons.
- Intermediate SHA `a3e71eb464` (05:18:44Z) fixed only the max-loss-alias
  half; the same validator also demanded the v3 final-admission CONTRACT on
  compact proof-rail rows (`PERSISTED_ADMISSION_FINAL_CONTRACT_MISSING`).
  `ae3b8bcce8` selects the admission/economics row explicitly (legacy
  full-row proof sources as before; durable-rail rows validate the
  hash-verified persisted accepted-fill row proved by the same
  source_fill_id+symbol) — verified by replaying the exact function against
  the live ledger with EGLDUSDT open: READY, zero rejects.
- First deploy attempt `73eb02e03d` (05:01:50Z, PID 562332) ran clean and
  surfaced a LATENT pre-existing defect on its first cycles (zero fills on
  that SHA): the durable proof rail stores compact lineage WITHOUT the sealed
  allocator payload, while the precycle exposure validator read
  `adaptive_allocation.max_loss_*` from proof rows — so ANY open position
  (EGLDUSDT, opened 04:48Z by the 53dec line) failed
  `OPEN_POSITION_SOURCE_FILL_MAX_LOSS_ALIASES_INVALID` and blocked ALL new
  entries (`PAPER_CANDIDATE_DYNAMIC_ENVELOPE_RESERVATION_BLOCKED`).  Masked
  historically by the single-flight rail; structurally fatal to concurrency
  criteria B/C.  Fixed in `a3e71eb464`: max-loss aliases fall back to the
  hash-verified persisted accepted-fill row proved by the same
  source_fill_id (own admission validation applies; fail-closed unchanged).
- Proof watch: transient unit `ai-bot-v2-paper-final-bypass-proof-watch`
  running `tools/paper_final_bypass_proof_watch.sh` → collector
  `tools/paper_final_bypass_acceptance_proof.py` → verdict JSON at
  `raw_evidence/paper_final_bypass_acceptance_latest.json`; transitions in
  `claude_worklog/paper_final_bypass_proof_watch.log`.

## Line reconciliation

A parallel session had already deployed a cutover (`53dec2e343`, running since
2026-07-31T02:44Z) implementing much of the directive.  This session's first
implementation on the pre-cutover line is preserved as WIP `70c7f33185` on
`codex/pipeline-trust-refresh` (NOT deployed).  The final release re-derives
the missing deltas onto the deployed line:

1. **Allocator economics keystone** — live runtime at 03:32Z still produced
   `allocator_decision=BLOCK_NO_EDGE`, reason
   `expected_move_after_cost_not_positive` → `REMAIN_FLAT`.  Fixed: paper mode
   never blocks on nonpositive after-cost edge; TRADING_POLICY sizing factors
   (confidence/edge/cost-preference/regime) floored at
   `PAPER_POLICY_SIZING_FLOOR = 0.05` (scale, never zero); zero paper budget
   only from hard capacity factors (`BLOCK_EXPOSURE_BUDGET`); sub-venue-minimum
   still hard-blocks (never rounds up).
2. **Structural authority (item 1)** — `paper_exploration_override_enabled()`
   returns True unconditionally; the `PAPER_EXPLORATION_LEGACY_AUTHORITY_FOR_TESTS`
   test seam is inert (an env var is an env var); every seam-guarded legacy
   branch is structurally dead.  `PAPER_EXPLORATION_OVERRIDE` env dropped from
   the unit (telemetry-only via `paper_exploration_override_env_status`).
3. **Classifier runtime strings (items 2-3)** — lowercase allocator family
   (`expected_move_after_cost_not_positive`, `BLOCK_NO_EDGE`,
   `ALLOCATOR_HARD_BLOCK:*`, `confidence_below_adaptive_minimum`),
   `CONFIDENCE_EXECUTABLE_TRADE_*`, `LOSS_CLUSTER_OR_QUARANTINE_ACTIVE`, raw
   `NEGATIVE_BUCKET_PERFORMANCE`, lowercase `bootstrap_*`,
   `NOT_A_PLUS_CANDIDATE`, `expected_move_` prefix.
4. **Router** — `NEGATIVE_BUCKET_PERFORMANCE(_QUARANTINE)` soft, softening
   unconditional.
5. **Item 4 invariant** — publish-time mechanical filter over
   `rejection_reasons` / `paper_fill_block_reason` /
   `paper_fill_gate_block_reasons` / `entry_gate_block_reasons` /
   `local_block_reasons`; writes `authoritative_hard_blockers`; any moved
   reason sets `paper_authority_field_policy_leak` (release-blocking signal).
6. **Item 7 event-driven loop** — immediate re-evaluation on new paper
   signal / fill / close / position update / policy_state_version bump (O(1)
   STRLEN+HGET probes, 5s min spacing); 60s timer is fallback heartbeat only.
   Trigger telemetry: `v2:paper:evaluation_trigger:last`.
7. **Item 8 receipts** — accepted intents: enriched `risk_capacity_receipt`
   (authorization_id + allocator capacity envelope) +
   `mandatory_protection_receipt`; positions & closes re-join
   `authorization_id`/receipts by position_id and carry
   `policy_gate_authority=false`; compaction whitelists retain the chain (the
   prior stripping caused the runtime `policy_gate_authority=None`).
8. **I08 monitor** — net-basis fix: per-close `realized_net_pnl_usd` sum
   reconciles to the net ledger within 1e-9; the prior FAIL was gross-vs-net
   units, not an accounting break.

## Tests

Battery on the frozen SHA: **2,208 passed** (adaptive_system 360+,
adaptive_capital_allocator, strategy_router interpretation, CLI paper loop
778, paper_trade_management 702 incl. fast-path receipts).  44 drifted tests
repaired to the structural contracts; every test guarding a genuine hard rail
(accounting, margin, stop, duplicate, catastrophic mandate, live-blocked)
kept its hard expectations via still-hard fixture variants.
Pre-existing failure NOT from this work:
`services/allocator/test_allocator_simulation.py::test_allocated_margin_derives_from_final_notional_and_leverage`
(fails identically on pristine 53dec2e343).

## Acceptance (item 10) — A-G

Collector: `tools/paper_final_bypass_acceptance_proof.py` (READ-ONLY;
frozen-SHA discrimination via `mandatory_protection_receipt` on fills and
`policy_gate_authority` on closes).  Verdict at deploy time: ACCRUING (all
criteria PENDING pre-deployment, G zero-defects PASS).

## Hard rails unchanged

Authentication, PIT/causality, venue feasibility, accounting, reservation,
duplicate protection, exposure/leverage/liquidation envelopes, mandatory
protection, catastrophic mandates, operator symbol exclusions, LIVE BLOCKED
(`blocked_human_only`, routes_to_live/places_real_order false everywhere).

## Not redeployed (noted)

`ai-bot-v2-adaptive-policy-shadow.service` still runs pinned snapshot
`7700414a4b` (independent shadow evidence stream, no authority).  Repo-run
services pick up the final line on their next natural restart.
