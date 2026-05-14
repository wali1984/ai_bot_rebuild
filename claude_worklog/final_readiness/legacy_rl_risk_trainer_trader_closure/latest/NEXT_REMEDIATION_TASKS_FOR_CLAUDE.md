# NEXT_REMEDIATION_TASKS_FOR_CLAUDE — Phase H

Concrete remediation list emerging from Phases A–G. Ordered by priority.

## P0 — must close before any legacy-shutdown discussion

### P0.1 Close remaining unresolved local imports

- **Title:** `claude_resolve_remaining_unresolved_local_imports`
- **Owner:** Claude
- **Files to inspect:** legacy root for `binance_websocket.py`, `hybrid_rule_based_signals.py`; closure JSON
- **Expected outputs:**
  - Either (a) extend `claude_worklog/tools/copy_legacy_full_runtime_closure.py` `TOP_LEVEL_FILES` to include the missing helpers and re-run, or (b) write a brief note classifying each as `LEGACY_ONLY_DEP_REPLACED_BY_V2_WITH_REASON`.
  - Re-run closure; the unresolved set must reduce to stdlib-only.
- **Acceptance:** `full_trainer_trader_dependency_closure.json` "files_with_unresolved_imports" drops to ≤ 5 (stdlib-only false positives).
- **Codex fail conditions:** any local helper silently dropped without classification.

### P0.2 Trainer-bridge port

- **Title:** `claude_port_v2_trainer_bridge` (descriptor already exists; needs LEGACY-FIRST execution against the expanded preserved tree)
- **Owner:** Claude
- **Files to inspect:** every `rl/*.py` in `v2/legacy_preserved/full_runtime_closure/rl/`
- **Expected outputs:**
  - `v2_trainer_bridge_LEGACY_BASELINE_ANALYSIS.md` citing SHA256 from `full_runtime_copied_source_manifest.json` for every rl/ helper consumed
  - Either (a) subprocess wrapper around `python3 -m rl.hybrid_trainer` from the preserved tree, OR (b) V2-native re-implementation enumerating each removed/changed legacy behavior with reason
  - `v2/backend/app/cli/v2_trainer_bridge.py` + tests + public payload
- **Acceptance:** Codex passes `V2_TRAINER_BRIDGE_CODEX_PASS`.
- **Codex fail conditions:** WRAPPER_NOT_LEGACY_HYBRID_PARITY persists; any rl/ helper silently dropped; torch/stable_baselines3 used without operator-approved install.

### P0.3 Risk-gateway test expansion

- **Title:** `claude_expand_v2_risk_gateway_test_suite_from_legacy_action_map`
- **Owner:** Claude
- **Files to inspect:** `risk/*.py` (22 files), `trading/depth_execution_gate.py`, `trading/fee_ratio_gate.py`, `trading/adaptive_edge_gate.py`, `trading/dynamic_margin_manager.py`
- **Expected outputs:**
  - 9+ new tests in `v2/backend/tests/integration/cli/test_v2_risk_gateway_runtime_worker.py`:
    - `kill_switch_active_denies_everything`
    - `halt_manager_active_denies_everything`
    - `reduce_only_latch_denies_increase_position`
    - `intelligent_close_guard_overrides_close_only_if_safety_holds`
    - `auto_deleverager_triggered_position_reduce_only`
    - `shared_risk_gate_denies_when_budget_exhausted`
    - `margin_governor_denies_leverage_increase`
    - `phase_controller_blocks_in_warmup_phase`
    - `adaptive_gate_blocks_on_microstructure_toxicity`
- **Acceptance:** all 9 tests pass on the V2 risk gateway library.
- **Codex fail conditions:** tests skip; test bodies do not actually invoke real gate functions.

### P0.4 Account/position read-only monitor port

- **Title:** `claude_port_v2_account_position_monitor` (descriptor exists)
- **Owner:** Claude
- **Files to inspect:** `services/portfolio_state.py`, `services/portfolio_publisher.py`, `monitor_portfolio_primary.py`, `monitor_portfolio_asjad.py`, `utils/unified_position_loader.py`
- **Expected outputs:** V2 CLI worker that reads exchange account/positions read-only or classifies `MISSING_CREDENTIALS`; never mutates.
- **Codex fail conditions:** any mutating endpoint reachable; paper-mode positions presented as real.

### P0.5 Three baseline-anchored ingestor/feature ports

- Same descriptors as prior turn (`claude_port_v2_market_ingestor_from_legacy_baseline`, `claude_port_v2_coinank_and_liquidation_bridge_from_legacy_baseline`, `claude_port_v2_feature_pipeline_and_ta_worker_from_legacy_baseline`)
- Now must also cite SHA256 from `full_runtime_copied_source_manifest.json` for any rl/utils helper they import.

## P1

### P1.1 UI explainability built from mapped action paths

- **Title:** `claude_realign_ui_explainability_to_mapped_action_paths`
- **Files to inspect:** `trader_risk_action_path_map.json`, `orchestrator_proposal_signal_flow_map.json`, current V2 frontend
- **Expected outputs:** UI panel that for any current decision can show:
  - which legacy risk-gate would have triggered (or did)
  - which proposal stage produced it
  - which exchange-action class it maps to (place/cancel/leverage/margin)
- **Codex fail conditions:** UI shows hardcoded action labels not tied to the mapped action paths.

### P1.2 Additional paper/replay comparisons

- **Title:** `claude_add_legacy_vs_v2_replay_comparison_for_p0_workers`
- **Files to inspect:** `rl/replay_store.py`, `rl/walk_forward_validation.py`, V2 `replay_backtest_runner` library
- **Expected outputs:** Replay test that runs the same window through legacy and V2 and reports field-level deltas.

### P1.3 Stale public artifact cleanup

- **Title:** `claude_audit_stale_public_payloads`
- **Files to inspect:** every `v2/frontend/public/operator_runtime/*/latest/` payload + freshness threshold
- **Expected outputs:** stale-payload report; cleanup or `MISSING_EVIDENCE` labels.

## P2 — explicit BLOCK until P0 closure

### P2.1 Live / canary proof

- **Title:** `claude_propose_live_canary_proof_protocol`
- **Status:** **BLOCKED** until P0.1–P0.5 close and Codex aggregate passes.
- **Codex fail conditions:** any live action recommended before P0 closure.

## Codex fail conditions across remediation tasks

- worker is greenfield without justification
- copied baseline source SHA256 not cited
- dependency closure missing
- legacy features silently dropped
- tests do not cover legacy-equivalent behavior
- worker claims migration from backlog only
- old Redis writes appear
- exchange mutation appears
- live approval token exists
