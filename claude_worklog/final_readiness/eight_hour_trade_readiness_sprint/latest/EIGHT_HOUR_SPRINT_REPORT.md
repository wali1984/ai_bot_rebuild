# 8-Hour Trade Readiness Sprint Report

Generated: 2026-05-15
Live gate: `blocked_human_only`. Live symbols: `[]`.
Final approval token: `absent`. Redis trim approval token: `absent`.

This sprint advanced V2 toward trade readiness on every dimension that
evidence permits, without faking any readiness. Live, canary, legacy
shutdown, and Redis trim remain blocked.

## Per-lane outcomes

### Lane A — Paper edge model repair
GO/NO-GO: `LANE_A_PAPER_EDGE_RECOVERY_READY_KEEP_GATE_STRICT`

- Reviewed expected-move review payload, threshold replay results, false-block
  audit.
- 347 completed observations, false-block rate 0.363, no-trade-correct rate
  0.637.
- 72 threshold replay rows tested across `expected_move_after_cost_bps ∈
  {4,6,8,10,12,15}`, `min_confidence_calibrated ∈ {0.60,0.65,0.70,0.75}`,
  cooldown modes `60m_observed_strict`/`30m_source_limited_no_change`/
  `10m_source_limited_no_change`.
- **0 safe threshold candidates.** Best rows show 71-75% precision but only
  5-8 allow events.
- Decision: keep the strict paper gate. No global or selective threshold
  change is authorized.

Outputs:
- [LANE_A_PAPER_EDGE_REPORT.md](LANE_A_PAPER_EDGE_REPORT.md)
- [lane_a_paper_edge_status.json](lane_a_paper_edge_status.json)

### Lane B — Trainer evidence
GO/NO-GO: `LANE_B_TRAINER_EVIDENCE_DERIVED_PAPER_ONLY_HONEST_CLASSIFICATION`

- Inspected `v2/legacy_preserved/full_runtime_closure/rl/hybrid_trainer.py`
  (57,250 lines) and calibration modules.
- Native fields present: `expected_move_pct` (raw, ATR-derived),
  `calibrated_confidence` (temperature-scaled, behind Redis feature flag),
  `model_version`, `checkpoint_id`.
- Native fields missing under V2 contract: `expected_move_after_cost_bps`,
  V2-form `feature_snapshot_id`, structured `feature_attribution`.
- Bridge correctly classified `READONLY_BRIDGED` / `PAPER_ONLY` /
  `DERIVED_FROM_LEGACY_LOG`. NOT `MIGRATED_CODEX_PASS`.

Outputs:
- [LANE_B_TRAINER_EVIDENCE_REPORT.md](LANE_B_TRAINER_EVIDENCE_REPORT.md)
- [lane_b_trainer_evidence_status.json](lane_b_trainer_evidence_status.json)

### Lane C — Risk/trader action parity deny tests
GO/NO-GO: `LANE_C_RISK_TRADER_PARITY_DENY_TESTS_PASS`

- New test file: `v2/backend/tests/integration/cli/test_v2_risk_trader_action_parity_deny_paths.py` (567 lines).
- 11 action paths covered with positive deny assertions on actual exported
  risk_gateway evaluators: `kill_switch`, `halt_manager`, `reduce_only_latch`,
  `intelligent_close_guard`, `auto_deleverager`, `shared_risk_gate`,
  `margin_governor`, `phase_controller`, `adaptive_gate` (microstructure
  toxicity), `orchestrator_hold`, `orchestrator_abstain`.
- 3 parity gaps documented with `pytest.skip(PARITY_GAP_NOT_FOUND)` rather
  than fabricated: `fee_ratio_gate`, `churn_veto`, `minimum_hold_time`.
- pytest: **22 passed, 3 skipped, 0 failed**.
- No exchange clients imported; no mutation paths reachable.

Outputs:
- [LANE_C_RISK_TRADER_PARITY_REPORT.md](LANE_C_RISK_TRADER_PARITY_REPORT.md)
- [lane_c_risk_trader_parity_status.json](lane_c_risk_trader_parity_status.json)

### Lane D — Signal/orchestrator freshness
GO/NO-GO: `LANE_D_SIGNAL_FRESHNESS_READ_ONLY_REPORT_READY_TWO_STALE_PAYLOADS`

- Decision comparator, legacy runtime observer, legacy signal outcome observer:
  **FRESH**.
- v2_signal_lineage_worker: near 24h boundary.
- v2_orchestrator_adapter: **STALE** (~37.7h).
- v2_signal_publisher: **STALE** (~37.5h).
- Comparator invariants verified: `legacy_mutation_performed: false`,
  `old_redis_write_performed: false`, `exchange_action_taken: false`,
  `live_blocked: true`, `live_gate: blocked_human_only`.
- No invented outcomes; `MISSING_EVIDENCE_CANNOT_COMPARE` honored.

Outputs:
- [LANE_D_SIGNAL_FRESHNESS_REPORT.md](LANE_D_SIGNAL_FRESHNESS_REPORT.md)
- [lane_d_signal_freshness_status.json](lane_d_signal_freshness_status.json)

### Lane E — Account permission
GO/NO-GO: `LANE_E_ACCOUNT_PERMISSION_HONESTLY_CLASSIFIED_BLOCKED_BY_PERMISSION`

- Account position monitor payload age: ~22 minutes — FRESH.
- `trade_permission_status`: `TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY`.
- `credentials_status`: `MISSING`.
- `fail_closed`: true. `fail_closed_reason`: `MISSING_CREDENTIALS`.
- `exchange_call_invariant`: `READONLY_ACCOUNT_AND_POSITION_ENDPOINTS_ONLY`.
- `exchange_mutation_performed`: false.
- Migration contract classification: `READONLY_BRIDGED`, `FAIL_CLOSED_STUB`,
  `BLOCKED_BY_PERMISSION`.

Outputs:
- [LANE_E_ACCOUNT_PERMISSION_REPORT.md](LANE_E_ACCOUNT_PERMISSION_REPORT.md)
- [lane_e_account_permission_status.json](lane_e_account_permission_status.json)

### Lane F — Frontend truth
GO/NO-GO: `LANE_F_FRONTEND_TRUTH_PAGE_READY`

- New public page at `/status-simple` (page id `user-status`, surface `public`,
  min role `viewer`, testid `page-user-status`).
- Consumes only `useFrontendTruthPayload` from `runtimePayloads.ts`.
- Reuses `StatusBadge` and `SimpleCard` from `status-simple/StatusBadge.tsx`.
- Renders plain-English summary, today's goal, status badges, simple-English
  blockers, per-page `SimpleCard`s, stale/missing evidence section.
- On missing payload: shows `MISSING_EVIDENCE` and a red badge — no mocks.
- Wired into `pages/registry.ts` and `tests/e2e/_shared.ts` (append-only).
- Frontend typecheck: clean.

Outputs:
- [LANE_F_FRONTEND_TRUTH_REPORT.md](LANE_F_FRONTEND_TRUTH_REPORT.md)
- [lane_f_frontend_truth_status.json](lane_f_frontend_truth_status.json)

## Validation results

- py_compile: clean across new Python.
- JSON validation: 6/6 lane status JSONs hold all required safety invariants.
- pytest combined (lanes A reuse + C + Phase-3 expected_move_review tests):
  **31 passed, 3 skipped, 0 failed**.
- Frontend typecheck (`tsc -b --noEmit`): clean.
- Forbidden-mutation scan: clean. No exchange-mutation symbols, no leverage
  changes, no margin-mode changes, and no old-Redis writes appear in the new
  code paths.
- Final approval token: absent. Redis trim approval token: absent.

## What this sprint does NOT do

- Does not authorize live trading.
- Does not authorize canary trading.
- Does not authorize legacy shutdown.
- Does not authorize Redis trim.
- Does not loosen the paper gate.
- Does not start legacy trainer or trader.
- Does not write to legacy Redis.
- Does not add or change credentials.

## Net advancement

The sprint:
1. Confirmed the paper edge gate must remain strict (Lane A).
2. Honestly classified trainer evidence as derived/paper-only (Lane B).
3. Added 22 new passing legacy-equivalent risk action deny tests + 3
   documented parity gaps (Lane C).
4. Identified two stale V2 payloads needing republish (Lane D).
5. Confirmed account permission is correctly fail-closed (Lane E).
6. Added a simple-English public status page consuming only V2 payloads
   (Lane F).

Live remains `blocked_human_only`.
