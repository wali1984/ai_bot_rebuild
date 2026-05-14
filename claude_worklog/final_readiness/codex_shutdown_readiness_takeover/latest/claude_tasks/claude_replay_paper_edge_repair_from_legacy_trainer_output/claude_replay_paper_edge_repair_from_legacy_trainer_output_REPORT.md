# Claude Replay/Paper Edge Repair From Legacy Trainer Output — REPORT

Task: `claude_replay_paper_edge_repair_from_legacy_trainer_output`
Generated (UTC): 2026-05-14
Live gate: `blocked_human_only` (unchanged)
Live symbols: `[]` (unchanged)
Final approval token: `absent` (NOT created)
Redis trim approval token: `absent` (NOT created)
Scope: V2 paper/shadow + canary tightening only. No legacy mutation, no exchange action, no live enablement.

## 1. Problem statement (from operator runtime evidence)

Operator-reported symptoms during the 6h paper/shadow soak:
- paper_pnl_current_usdt = `-49.12` (delta `-22.75` in the window)
- fee_slippage_bleed = `true`; gross_pnl_if_fees_added_back_usdt = `-0.06` (≈ all loss is fees/slippage drag)
- win_rate = `0.0`; profit_factor = `0.0`
- fills_per_hour = `84.99`, fills_per_minute = `1.42` → overtrading
- churn_flip_count = `193`; repeated same-direction fills long=1156 / short=1113
- blocked_intents = `1597`; `deny_canary_profile_tightening` = `1244`, `deny_low_confidence` = `223`
- trainer_edge_status = `UNPROVEN_OR_WEAK_UNTIL_6H_24H_AND_GROSS_PNL_MODEL_COMPLETE`
- paper_engine_assumption = "Current paper engine realizes fee-only PnL per fill and does not model exit edge; negative PnL is not profitability proof."

Raw evidence pointers:
- `claude_worklog/final_readiness/paper_shadow_soak_negative_pnl/latest/negative_paper_pnl_diagnosis.json`
- `claude_worklog/final_readiness/paper_shadow_soak_negative_pnl/latest/paper_fill_quality_and_overtrading_audit.json`

## 2. Diagnosis (root causes, ranked)

R1 — `PAPER_ENGINE_LACKS_POSITION_LIFECYCLE` (single-tick fee-only PnL).
  - Evidence: `paper_engine_assumption` + `average_hold_time_seconds = MISSING_EVIDENCE_CURRENT_PAPER_ENGINE_HAS_NO_POSITION_LIFECYCLE`.
  - Effect: every fill bleeds avg_fee_usdt=0.01 + slippage_bps=2.0; PnL = pure cost drag → negative PnL is not edge evidence.

R2 — `OVERTRADING` (84.99 fills/hr, 1.42 fills/min, top-symbol concentration BTCUSDT=2269).
  - Effect: cost drag compounds; signal selection has no cooldown.

R3 — `LOW_CONFIDENCE_FILL_RISK` (454 fills in 0.58–0.65 bucket; 996 intents `stricter_canary_profile_would_block_count`).
  - Effect: weak edge ⊕ unbounded fill rate → unrecoverable cost drag.

R4 — `CHURN/FLIP_RISK` (193 flips, no reduce-only enforcement).
  - Effect: flips realize fees on both sides while feature regime unchanged.

R5 — `RISK_GATEWAY_ALLOWED_TOO_MANY_UNSAFE_PAPER_INTENTS = true`.
  - Effect: gateway permitted >2269 fills before tightened profile arrived; rising `blocked_intents` is the tightened profile working — not a regression.

## 3. Legacy parity (does the legacy bot behave differently?)

See `claude_replay_paper_edge_repair_from_legacy_trainer_output_LEGACY_BASELINE_ANALYSIS.md`. Summary: legacy `rl/hybrid_trainer.py` (3,165,342 bytes, sha256=b7dad66b63b57c0d5c29e0fbaf67466d9c2aab81baf7a4f67b6e681e38c5b102) couples prediction → `rl/signal_state_manager.py` (sha256=62c7d46ade7d03cd378e46cba2d06d2ee63bd218b27d9a853ee221a9899e6459) → `rl/increase_signal_validator.py` (sha256=6b1dbcb61bac934038d7be3ca16721453e4eda7263c6f7527c5583f23c7d12a0) → `rl/advanced_risk_management.py` (sha256=db2fc5c91f270f69790c4d3e25e9b6007384b6c788a2c6dc00cf3305cf829697). Legacy enforces per-symbol confidence/cooldown/stop-risk validation prior to action emission; V2 paper engine currently emits fills without the equivalent inline validator. Tightened canary runtime (already present at `v2/backend/app/composition/canary_profile_tightening/runtime.py`) is the V2 equivalent and must be wired in *front of paper fills*, not only at canary eligibility evaluation.

## 4. Remediation proposal (paper/shadow only — live remains BLOCKED)

Profile name: `paper_canary_aligned_filter_v1` (paper-only filter, does NOT mutate the live gate).

Knobs (matches existing `build_canary_profile_tightening_runtime` defaults — no code addition required, only wiring):
- `min_confidence` = `0.75` (rejects 454+ low-confidence fills already observed).
- `max_fills_per_hour` = `12` (caps overtrading at ≤7× current; ≥85% reduction).
- `cooldown_seconds` = `300` after any fill (same-symbol-same-direction).
- `loss_cooldown_seconds` = `600` after a loss outcome.
- `max_signal_age_seconds` = `10`; `max_feature_age_seconds` = `60`.
- `symbol_whitelist` = `("BTCUSDT",)` for paper soak; do not widen until 6h/24h non-negative gross.
- `expected_move_bps > fee_bps + slippage_bps + funding_bps` → blocker `expected_edge_below_costs`.
- Flip churn requires `REDUCE_ONLY`/`PARTIAL_CLOSE_*` action class; otherwise `flip_churn_cooldown` denies.

Wiring change (paper-side only, no live effect):
- `v2/backend/app/cli/v2_paper_execution_worker.py` calls `CanaryProfileTighteningRuntime.evaluate_now(...)` BEFORE recording a paper fill. If classification != `TIGHTENED_PROFILE_PAPER_SIMULATION_ELIGIBLE`, the intent is logged as `denied_by_paper_filter` with reason set to `blockers[0]` and is NOT materialized into the paper ledger.
- `risk_gateway/runtime.py` already returns `deny_canary_profile_tightening`; that is the *report* path. The proposed change adds the *enforcement* path for paper fills (same predicate, applied at the paper execution boundary).
- Live execution path unchanged. `live_gate = blocked_human_only`; `live_symbols = []`; approval token absent.

Edge-modeling tracking item (NOT a code change in this task, recorded for the next task):
- Replace fee-only single-tick paper PnL with a position-lifecycle paper engine that:
  - holds the position until `stop`/`take`/`exit_signal`/`cooldown_close`,
  - models slippage at entry AND exit (2.0 bps each side baseline; configurable),
  - models funding when `funding_assumption != "zero_until_funding_feed_adapter_current"`.
- Until then, paper PnL is COST-OF-FRICTION and `trainer_edge_status` cannot be promoted past `UNPROVEN_OR_WEAK_*`.

## 5. Public payload impact (runtime-facing)

Only V2 paper/shadow surfaces change. No live payload mutation.

Surfaces affected (paper-only):
- `v2/frontend/public/paper_strategy_edge_tightening/latest/canary_profile_tightening_proposal.json` — proposal stays as-is (already published).
- New paper-filter outcomes will surface in the existing `risk_decision_distribution` view as additional `deny_paper_canary_aligned_filter_v1` counts.
- `canary_readiness_after_*` payloads continue to assert `LIVE_REMAINS_BLOCKED`.

No change to:
- `live_gate` (stays `blocked_human_only`)
- `live_symbols` (stays `[]`)
- `final_approval_token` (stays `absent`; this task does NOT create one)
- `redis_trim_approval_token` (stays `absent`; this task does NOT create one)

## 6. Dependency closure

- `composition/canary_profile_tightening/runtime.py` — present, has unit tests `tests/unit/composition/canary_profile_tightening/test_runtime.py` and `test_public_surface.py`.
- `composition/paper_mode/runtime.py`, `composition/paper_execution_ledger/runtime.py` — present.
- `cli/paper_strategy_edge_tightening.py`, `cli/v2_paper_execution_worker.py`, `cli/paper_shadow_negative_pnl.py` — present.
- No new imports; no new third-party dependency; no legacy import required.
- Status: `DEPENDENCY_CLOSURE_OK`.

## 7. Tests

- Existing tightening unit tests cover blocker fan-out and probability/positive-int guards.
- Required additional paper-filter wiring test (planned, NOT in this report's diff):
  `tests/unit/cli/test_v2_paper_execution_worker_paper_canary_aligned_filter_v1.py` asserting:
  - low-confidence intent → `denied_by_paper_filter` (reason `confidence_below_canary_threshold`).
  - same-symbol same-direction inside cooldown → denied.
  - flip without REDUCE_ONLY → denied.
  - expected_move_bps ≤ cost_bps → denied.
  - approval_token_present has no effect on live path; live remains BLOCKED.
- Classification for this report: `V2_ENV_BLOCKED` for *running* a fresh 6h paper soak with the new filter (operator-gated start); evidence for the filter spec itself is present and verified.

## 8. GO / NO-GO

NO-GO for live (unchanged). GO for paper-side enforcement wiring of `paper_canary_aligned_filter_v1` (same predicate as existing tightened canary; paper-only) and for opening the follow-up task to add a position-lifecycle paper engine. Final approval token NOT created. Redis trim approval token NOT created.
