# Command ledger — adaptive end-to-end audit and repair

**Date:** 2026-07-17

**Repository root:** `/home/wali/Desktop/AI BOT REBUILD`

**Observed base/current HEAD during the coordinated turn:** `6997e4d99e` (the worktree remained intentionally dirty and changed concurrently)

**Boundary:** source, paper/shadow control, isolated tests, read-only Redis/systemd observation, and documentation. No live exchange order, cancel, modification, leverage-setting, margin-setting, credential test, live-gate enablement, destructive retention, Git reset/checkout/commit/push, or provider-side mutation was run.

This is the reproducibility ledger for the dated worktree, not a claim that every command passed. Result labels are retained so a failed diagnostic cannot be mistaken for a green gate. Commands were run from the repository root unless stated otherwise.

## 1. Credential-redaction exception

One early read-only service diagnostic exposed a cloudflared bearer credential in tool output. That command and its output are deliberately not reproduced here. This is the only intentional omission from the safe command record. Repeating it would expand the credential leak and would conflict with the required rotate/revoke response. Avoid raw process, `ExecStart`, environment, or full service-status inspection until tunnel authentication uses protected credential handling.

Required security action: rotate/revoke the exposed cloudflared credential at the provider, audit where the diagnostic output propagated, and move the credential out of command-line visibility. No credential value was copied into repository documentation.

## 2. Mutation mechanism and scope

Repository edits in this coordinated turn were made with structured `apply_patch` calls. The exact unified patches remain in the agent tool transcript; shell redirection, `cat >`, broad formatter rewrites, and destructive Git commands were not used. Because multiple agents shared one worktree, each workstream scoped its patch and diff checks to its owned files.

### 2.1 Control and certification

- `scripts/guardian_phase10_rare_event_tests.py`
- `scripts/verify_claude_guardian_completion.py`

### 2.2 Orchestrator, risk, and trainer publication

- `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py`
- `v2/backend/app/cli/v2_risk_gateway_live_loop.py`
- `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/publisher.py`
- `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/runtime.py`
- `v2/backend/tests/integration/cli/test_v2_paper_fill_gate_block_reason_passthrough.py`
- `v2/backend/tests/integration/cli/test_v2_risk_gateway_live_loop.py`
- `v2/backend/tests/unit/cli/test_v2_orchestrator_arbitration_loop.py`
- `v2/backend/tests/unit/test_pipeline_trust_runtime_enforcement.py`

### 2.3 Trainer point-in-time, replay, and PPO identity

- `v2/backend/app/services/market_state_integrity/replay_snapshot.py`
- `v2/backend/app/services/market_state_integrity/sample_rejection.py`
- `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py`
- `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/leverage_margin_exploration.py`
- `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/ppo_trainer.py`
- `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/temporal_windowing.py`
- `v2/backend/app/services/native_trainer/trusted_replay/dataset.py`
- `v2/backend/tests/unit/services/native_trainer/test_hybrid_ppo_action_balance.py`
- `v2/backend/tests/unit/services/native_trainer/test_hybrid_trainer_feedback_labels.py`
- `v2/backend/tests/unit/services/native_trainer/test_historical_missing_mask_admission.py`
- `v2/backend/tests/unit/services/native_trainer/test_hybrid_cuda_trainer_runtime.py`
- `v2/backend/tests/unit/services/native_trainer/test_hybrid_trainer_regularization_and_validation.py`
- `v2/backend/tests/unit/services/native_trainer/test_leverage_margin_exploration.py`
- `v2/backend/tests/unit/services/native_trainer/test_temporal_windowing.py`
- `v2/backend/tests/unit/services/native_trainer/test_trust_feedback_weight_update_repair.py`
- `v2/backend/tests/unit/services/native_trainer/test_trusted_replay_bootstrap.py`

### 2.4 Allocator and paper accounting/lifecycle

- `v2/backend/app/cli/v2_portfolio_state_publisher.py`
- `v2/backend/app/cli/v2_trade_management_paper_loop.py`
- `v2/backend/app/cli/v2_binance_usdm_leverage_bracket_evidence.py`
- `v2/backend/app/services/adaptive_capital_allocator/allocator.py`
- `v2/backend/app/services/adaptive_capital_allocator/contracts.py`
- `v2/backend/app/services/adaptive_capital_allocator/counterfactual.py`
- `v2/backend/app/services/adaptive_capital_allocator/dynamic_envelope.py`
- `v2/backend/app/services/binance_usdm_leverage_bracket_evidence.py`
- `v2/backend/app/services/paper_accounting/mark_to_market.py`
- `v2/backend/app/services/paper_trade_management/generation_identity.py`
- `v2/backend/app/services/paper_trade_management/lifecycle.py`
- `v2/backend/app/services/paper_trade_management/margin_accounting.py`
- `v2/backend/app/services/paper_trade_management/outcomes.py`
- `v2/backend/app/services/paper_trade_management/position_state.py`
- `v2/backend/tests/unit/cli/test_v2_portfolio_state_publisher_equity.py`
- `v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py`
- `v2/backend/tests/unit/services/adaptive_capital_allocator/test_allocator.py`
- `v2/backend/tests/unit/services/adaptive_capital_allocator/test_adaptive_leverage_margin_ramp.py`
- `v2/backend/tests/unit/services/adaptive_capital_allocator/test_counterfactual.py`
- `v2/backend/tests/unit/services/adaptive_capital_allocator/test_dynamic_envelope.py`
- `v2/backend/tests/unit/services/adaptive_capital_allocator/test_go_live_fixture_matrix.py`
- `v2/backend/tests/unit/services/adaptive_capital_allocator/test_phase6_status.py`
- `v2/backend/tests/unit/services/allocator/test_allocator_simulation.py`
- `v2/backend/tests/unit/services/test_binance_usdm_leverage_bracket_evidence.py`
- `v2/backend/tests/unit/cli/test_v2_binance_usdm_leverage_bracket_evidence.py`
- `v2/backend/tests/unit/services/paper_trade_management/test_lifecycle.py`
- `v2/backend/tests/unit/services/paper_trade_management/test_margin_accounting.py`

### 2.5 Documentation

- `docs/MASTER_SYSTEM_DOC.md`
- `v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md`
- `docs/system_audit_2026_master/ADAPTIVE_END_TO_END_CONTROL_AND_ACCOUNTING_2026-07-17.md`
- `docs/system_audit_2026_master/AI_BOT_V2_FULL_REBUILD_MASTER_AUDIT_REPORT.md`
- `docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md`
- `docs/system_audit_2026_master/COMMAND_LEDGER_2026-07-17.md`
- `docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md`
- `docs/system_audit_2026_master/OPERATOR_VALIDATION_AND_MONITORING_RUNBOOK_2026-07-17.md`
- `docs/system_audit_2026_master/REBUILD_BLUEPRINT.md`
- `docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md`
- `docs/system_audit_2026_master/components/DATA_TEMPORAL_LINEAGE_AND_FEATURES.md`
- `docs/system_audit_2026_master/components/DECISION_RISK_PAPER_AND_LIVE_EXECUTION.md`
- `docs/system_audit_2026_master/components/TRAINER_PPO_MASA_REPLAY_AND_CHECKPOINTS.md`

Files created or updated by unrelated pre-existing/concurrent work are not claimed by this ledger.

## 3. Baseline diagnostics retained as failures

These were useful pre-repair observations, not final gates:

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py -k 'policy_intent_decision_dereference or preemptive_admission or margin_leverage or economic_fill_fields'
```

Result: no selected test matched; 423 were deselected. This did not validate the behavior.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/integration/cli/test_v2_paper_fill_gate_block_reason_passthrough.py
```

Baseline result: 11 passed, one failed because the paper loop read zero per-symbol signal rows where the test expected one. Later scoped reruns are recorded below.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/paper_trade_management/test_position_state.py v2/backend/tests/unit/services/paper_trade_management/test_position_validity.py
```

Result: collection error because those paths do not exist. The actual lifecycle tests are under `test_lifecycle.py`.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/adaptive_capital_allocator/test_allocator.py v2/backend/tests/unit/services/adaptive_capital_allocator/test_adaptive_leverage_margin_ramp.py
```

Result: 47 passed.

## 4. Independent audit command sets

### 4.1 Trainer/edge audit

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q -p no:cacheprovider \
  v2/backend/tests/unit/services/native_trainer/test_temporal_windowing.py \
  v2/backend/tests/unit/services/native_trainer/test_temporal_encoder_integration.py \
  v2/backend/tests/unit/services/native_trainer/test_hybrid_ppo_action_balance.py \
  v2/backend/tests/unit/services/native_trainer/test_leverage_margin_exploration.py \
  v2/backend/tests/unit/services/native_trainer/test_confidence_calibration.py \
  v2/backend/tests/unit/services/native_trainer/test_trusted_replay_bootstrap.py \
  v2/backend/tests/unit/services/native_trainer/test_hybrid_runtime_training_selection.py
```

Result: 46 passed in 24.24 seconds.

### 4.2 Control-plane/adaptivity audit

```bash
.venv/bin/python -m pytest -q \
  v2/backend/tests/integration/cli/test_v2_orchestrator_arbitration_worker.py \
  v2/backend/tests/integration/cli/test_v2_risk_gateway_live_loop.py \
  v2/backend/tests/unit/services/adaptive_capital_allocator/test_allocator.py \
  v2/backend/tests/unit/services/paper_trade_management/test_phase8_leverage_recommendation.py
```

Result: 84 passed in 0.27 seconds.

### 4.3 Paper leverage/margin audit

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q -p no:cacheprovider v2/backend/tests/unit/services/adaptive_capital_allocator v2/backend/tests/unit/services/hedge_engine v2/backend/tests/unit/services/paper_trade_management/test_phase8_leverage_recommendation.py v2/backend/tests/unit/services/paper_trade_management/test_adaptive_hedging.py
```

Result: 151 passed.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q -p no:cacheprovider v2/backend/tests/unit/services/paper_trade_management/test_lifecycle.py v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py
```

Result: 497 passed.

## 5. Orchestrator-lineage repair commands

```bash
python -m py_compile v2/backend/app/cli/v2_orchestrator_arbitration_loop.py
```

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/cli/test_v2_orchestrator_arbitration_loop.py
```

```bash
.venv/bin/python -m pytest -q v2/backend/tests/integration/cli/test_v2_paper_fill_gate_block_reason_passthrough.py -k 'orchestrator_'
```

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/cli/test_v2_orchestrator_arbitration_loop.py v2/backend/tests/integration/cli/test_v2_paper_fill_gate_block_reason_passthrough.py -k 'test_non_routeable_actions_are_held_without_direction_synthesis or test_published_signal_uses_canonical_risk_decision_id or test_published_signal_cannot_claim_fill_permission_before_risk or test_signed_short_and_long_edges_are_symmetric_for_arbitration or orchestrator_'
```

```bash
.venv/bin/python -m pytest -q v2/backend/tests/integration/cli/test_v2_paper_fill_gate_block_reason_passthrough.py
```

```bash
git diff --check -- v2/backend/app/cli/v2_orchestrator_arbitration_loop.py v2/backend/tests/unit/cli/test_v2_orchestrator_arbitration_loop.py
```

```bash
sha256sum v2/backend/app/cli/v2_orchestrator_arbitration_loop.py v2/backend/tests/unit/cli/test_v2_orchestrator_arbitration_loop.py
git diff --check -- v2/backend/app/cli/v2_orchestrator_arbitration_loop.py
.venv/bin/python -m py_compile v2/backend/app/cli/v2_orchestrator_arbitration_loop.py v2/backend/tests/unit/cli/test_v2_orchestrator_arbitration_loop.py
```

The final isolated orchestrator unit rerun passed; the integrated result is recorded in §9.

## 6. Trainer PIT/replay/PPO repair commands

The following are the exact final focused validation invocations; earlier baseline/rerun variants are retained where their result changed.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_temporal_windowing.py v2/backend/tests/unit/services/native_trainer/test_trusted_replay_bootstrap.py
```

Observed focused results during iteration included 21 passed and then 25 passed as tests were added.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_temporal_windowing.py v2/backend/tests/unit/services/native_trainer/test_trusted_replay_bootstrap.py v2/backend/tests/unit/services/native_trainer/test_model_edge_recovery_challenger.py v2/backend/tests/unit/services/native_trainer/test_temporal_encoder_integration.py
```

Result: 31 passed.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_temporal_windowing.py v2/backend/tests/unit/services/native_trainer/test_trusted_replay_bootstrap.py v2/backend/tests/unit/services/native_trainer/test_train_input_cache.py
.venv/bin/python -m compileall -q v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py v2/backend/app/services/native_trainer/hybrid_cuda_trainer/temporal_windowing.py v2/backend/app/services/native_trainer/hybrid_cuda_trainer/ppo_trainer.py v2/backend/app/services/native_trainer/trusted_replay/dataset.py
git diff --check -- v2/backend/app/services/native_trainer v2/backend/tests/unit/services/native_trainer
```

Result: 27 passed; compilation and diff check passed.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_hybrid_ppo_action_balance.py v2/backend/tests/unit/services/native_trainer/test_hybrid_trainer_feedback_labels.py v2/backend/tests/unit/services/native_trainer/test_trust_feedback_weight_update_repair.py
```

Baseline result before behavior-identity mutation: 47 passed. Final result: 52 passed with one inherited `pynvml` deprecation warning.

```bash
.venv/bin/python -m compileall -q v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py v2/backend/app/services/native_trainer/hybrid_cuda_trainer/ppo_trainer.py
git diff --check
awk 'length($0)>119 { print FNR ":" length($0) ":" $0 }' v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py v2/backend/app/services/native_trainer/hybrid_cuda_trainer/ppo_trainer.py
```

Compilation and diff check passed. The line-length inspection reported pre-existing long lines.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer
```

Interim result before the final trainer additions: 297 passed, three failed. The failures were the same feature-spec contract drift retained in the final full run below.

Final focused PIT/promotion/PPO/authority suite:

```bash
.venv/bin/python -m pytest -q --disable-warnings v2/backend/tests/unit/services/native_trainer/test_hybrid_cuda_trainer_runtime.py v2/backend/tests/unit/services/native_trainer/test_hybrid_trainer_regularization_and_validation.py v2/backend/tests/unit/services/native_trainer/test_hybrid_ppo_action_balance.py v2/backend/tests/unit/services/native_trainer/test_historical_missing_mask_admission.py v2/backend/tests/unit/test_pipeline_trust_runtime_enforcement.py
```

Result: 100 passed, one warning, 40.89 seconds.

Final rejected-candidate/publication authority targets and compilation:

```bash
.venv/bin/python -m pytest -q --disable-warnings v2/backend/tests/unit/test_pipeline_trust_runtime_enforcement.py::test_prediction_publish_commits_replay_write_before_lineage_risk v2/backend/tests/unit/services/native_trainer/test_hybrid_cuda_trainer_runtime.py::test_runtime_suppresses_rejected_candidate_forward_and_backtest && .venv/bin/python -m compileall -q v2/backend/app/services/native_trainer/hybrid_cuda_trainer v2/backend/app/services/market_state_integrity/replay_snapshot.py v2/backend/app/services/market_state_integrity/sample_rejection.py
```

Result: two passed; compileall clean.

Intermediate full native-trainer plus pipeline-trust command before the feature-ABI fixture reconciliation:

```bash
.venv/bin/python -m pytest -q --disable-warnings v2/backend/tests/unit/services/native_trainer v2/backend/tests/unit/test_pipeline_trust_runtime_enforcement.py
```

Result: 371 passed and three failed in 96.11 seconds. The failures were:

- `test_ta_full_feature_expansion.py::test_feature_spec_grew_and_has_no_duplicates`;
- `test_ta_full_feature_expansion.py::test_taf_features_resolve_from_ta_full_indicators`;
- `test_ta_full_feature_expansion.py::test_no_ta_full_payload_leaves_taf_missing_not_crashing`.

All three expected 477 features/1,908 model values while unchanged current `FEATURE_SPEC` imported as 446/1,784. This was a failed intermediate full-trainer gate and was recorded as RE-044, not attributed to the PIT repair. Scoped `git diff --check` was clean.

After investigation confirmed the 31-feature removal was intentional, the three stale test expectations were reconciled to the intended 446/1,784 source generation and the literal complete command was rerun:

```bash
.venv/bin/python -m pytest -q --disable-warnings v2/backend/tests/unit/services/native_trainer v2/backend/tests/unit/test_pipeline_trust_runtime_enforcement.py
```

Result: **374 passed in 98.82 seconds**. This supersedes the 371/3 local test result, but it does not migrate deployed/history 477/1,908 checkpoints, replay, caches or temporal buffers; that cross-generation ABI debt remains RE-044.

Canonical-decision prefix absence in the trainer publisher was checked with:

```bash
if rg -n 'v2:decision:(risk|orchestrator|index):' v2/backend/app/services/native_trainer/hybrid_cuda_trainer/publisher.py; then exit 1; else echo trainer_canonical_decision_prefix_absent; fi
```

Result: `trainer_canonical_decision_prefix_absent`.

### 6.1 Trainer leverage/margin study v2

The focused study validation progressed from a six-test baseline through intermediate 19-pass/one-fail and 20-pass states. The final exact focused invocation was:

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_leverage_margin_exploration.py
```

Final result: 25 passed.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer -k 'policy_backtest or leverage_margin_exploration'
```

Result: 25 passed, 296 deselected.

Final static/source checks:

```bash
.venv/bin/ruff check v2/backend/app/services/native_trainer/hybrid_cuda_trainer/leverage_margin_exploration.py v2/backend/tests/unit/services/native_trainer/test_leverage_margin_exploration.py
.venv/bin/python -m py_compile v2/backend/app/services/native_trainer/hybrid_cuda_trainer/leverage_margin_exploration.py v2/backend/tests/unit/services/native_trainer/test_leverage_margin_exploration.py
git diff --check -- v2/backend/app/services/native_trainer/hybrid_cuda_trainer/leverage_margin_exploration.py v2/backend/tests/unit/services/native_trainer/test_leverage_margin_exploration.py
```

Result: all passed.

A read-only direct invocation of the unchanged legacy-style four-field payload was:

```bash
.venv/bin/python - <<'PY'
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.leverage_margin_exploration import evaluate_leverage_margin_grid
result = evaluate_leverage_margin_grid({
    "expected_move_after_cost_bps": 12.0,
    "stop_distance_bps": 25.0,
    "equity_usd": 200.0,
    "notional_usd": 60.0,
})
print({
    "study_admission_allowed": result["study_admission_allowed"],
    "best_leverage": result["best_leverage"],
    "best_margin_mode": result["best_margin_mode"],
    "input_evidence_complete": result["input_evidence_complete"],
    "missing_reason_count": len(result["input_rejection_reasons"]),
})
PY
```

Result: `study_admission_allowed=false`, `best_leverage=null`, no margin mode, `input_evidence_complete=false`, and 16 missing reasons. No service restart, network command, live route, leverage setting, or margin setting was performed by this workstream.

## 7. Read-only runtime evidence commands

These commands do not mutate Redis:

```bash
redis-cli --raw GET 'v2:goal:trajectory_1000x' | jq '{generated_utc,equity_usd,initial_equity_usd,multiple_now,realized_pnl_usd,unrealized_pnl_usd,closed_trade_count,on_track,required_daily_return_pct,actual_daily_return_pct,growth_stage,binding_constraint,paper_only,places_real_order,routes_to_live,live_gate}'
```

```bash
redis-cli --raw GET 'v2:paper:performance_circuit_breaker_status' | jq '{generated_utc,state,new_entries_allowed,governed_outcome_count,aggregate,rolling_25,block_reasons,paper_only,places_real_order,routes_to_live}'
```

```bash
redis-cli --raw GET 'v2:prediction:BTCUSDT:1m' | jq '{prediction_id, generated_utc, candle_closed_confirmed, candle_close_time, masa_feature_cutoff, ppo_feature_cutoff, ppo_decision_time, routes_to_orchestrator, routes_to_orchestrator_reason, paper_fill_allowed, trust_result}'
```

```bash
date -u +'%Y-%m-%dT%H:%M:%SZ'
systemctl --user is-active ai-bot-v2-trade-management-paper-loop.service ai-bot-v2-orchestrator-arbitration-loop.service ai-bot-v2-risk-gateway-live-loop.service ai-bot-v2-native-cuda-trainer-persistent.service
redis-cli --raw GET 'v2:prediction:BTCUSDT:1m' | jq '{prediction_id,generated_utc,candle_closed_confirmed,candle_close_time,masa_feature_cutoff,ppo_feature_cutoff,ppo_decision_time,replay_snapshot_write_success,routes_to_orchestrator,routes_to_orchestrator_reason,paper_fill_allowed}'
redis-cli --raw GET 'v2:paper:ledger' | jq '{generated_utc,open_position_count,has_margin:(.paper_account_margin_status!=null),has_reservation:(.paper_margin_reservation_status!=null),generation_complete:([.open_positions[]? | select(.position_generation_id!=null and .position_id_version=="PAPER_POSITION_GENERATION_V1")]|length),positions:([.open_positions[]?]|length)}'
```

At 18:45 UTC all four units reported active. The prediction showed the repaired fields and successful replay write; the paper ledger still showed the old/mixed shape.

The first observation found a pre-reload prediction with the new fields absent and both route/fill permission false. A repeat at 18:45 UTC found a new BTCUSDT row generated at 18:44:20 UTC with confirmed candle finality, exact MASA/PPO cutoff and decision fields, and `replay_snapshot_write_success=true`; it remained safely blocked for explicit paper-gate reasons. This is prediction-stage deployment evidence, not routeable cross-surface proof.

```bash
redis-cli --raw TYPE 'v2:paper:account_margin_status'
redis-cli --raw TTL 'v2:paper:account_margin_status'
redis-cli --raw GET 'v2:paper:account_margin_status' | jq '{schema_version,status,generated_utc,used_margin_usd,newly_reserved_margin_usd,free_margin_usd,free_margin_after_buffer_usd,invariant_holds,source,cycle_reserved_candidate_count,cycle_margin_blocked_candidate_count,paper_only,routes_to_live,places_real_order}'
```

```bash
redis-cli --raw GET 'v2:paper:ledger' | jq '{generated_utc,open_position_count,margin:.paper_account_margin_status,reservation:.paper_margin_reservation_status,positions:[.open_positions[]? | {symbol,position_generation_id,position_id_version,gross_notional_usd,allocated_margin_usd,effective_leverage,net_quantity,avg_entry_price}]}'
```

At 18:33 UTC the standalone key existed and passed its arithmetic invariant, but it lacked `generated_utc`; the simultaneous ledger lacked both embedded receipts and its six open positions were legacy identity rows. The commands were read-only and the result remains deployment reconciliation FAIL.

Pre-reload safety and deployment-shape recheck:

```bash
date -u +'%Y-%m-%dT%H:%M:%SZ'
systemctl --user is-active ai-bot-v2-trade-management-paper-loop.service ai-bot-v2-orchestrator-arbitration-loop.service ai-bot-v2-risk-gateway-live-loop.service ai-bot-v2-native-cuda-trainer-persistent.service
redis-cli --raw GET v2:live_gate:state | jq '{live_gate,trader_execution_enabled,live_symbols,execution_live_symbols,operator_approved,order_transport_submit_enabled,places_real_order}'
redis-cli --raw GET v2:trader:execution_state | jq '{live_gate,trader_execution_enabled,live_symbols,execution_live_symbols,operator_approved,order_transport_submit_enabled,places_real_order}'
redis-cli --raw GET v2:prediction:BTCUSDT:1m | jq '{prediction_id,generated_utc,behavior_policy_sampling_mode,behavior_policy_distribution_contract,ppo_on_policy_entry_fields_present,ppo_on_policy_ineligible_reason,candle_closed_confirmed,masa_feature_cutoff,ppo_feature_cutoff,ppo_decision_time,replay_snapshot_write_success,routes_to_orchestrator,paper_fill_allowed}'
redis-cli --raw GET v2:paper:ledger | jq '{generated_utc,open_position_count,margin_generated_utc:.paper_account_margin_status.generated_utc,reservation_generated_utc:.paper_margin_reservation_status.generated_utc,margin_status:.paper_account_margin_status.status,reservation_status:.paper_margin_reservation_status.status,generation_complete:([.open_positions[]? | select(.position_generation_id!=null and .position_id_version=="PAPER_POSITION_GENERATION_V1")]|length),positions:([.open_positions[]?]|length)}'
```

At 19:17:18 UTC all four units were active and both gate keys were fully disabled (`blocked_human_only`, execution false, both symbol arrays empty, operator approval false, transport false, real-order false). The fresh 19:15:59 prediction had finality/cutoff/replay proof but no behavior-policy fields. The 19:16:27 ledger had five open positions, no embedded margin/reservation receipt, and zero generation-aware positions. This remained pre-reload/mixed deployment evidence.

```bash
redis-cli --raw GET v2:trainer:hybrid_cuda:status | jq '{generated_utc,online_learning_status,checkpoint_id,checkpoint_promotion_allowed,checkpoint_promotion_rejected,checkpoint_promotion_reason,validation_split_pit_safe,validation_split_reason,validation_policy_edge_status,validation_policy_edge_after_cost_bps,validation_policy_edge_lower_confidence_bound_bps,validation_policy_edge_rows_evaluated,learning_metrics:(.learning_metrics|{learning_update_lane,ppo_objective_used,validation_rows_evaluated,checkpoint_promoted_this_cycle,checkpoint_restore_after_rejection_verified})}'
```

The 19:16:17 resident status had `checkpoint_promotion_allowed=true`, reason `VALIDATION_GUARD_DISABLED`, 403 validation rows, and `checkpoint_promoted_this_cycle=true`, but every new PIT-split/edge field was absent. Its update lane was outcome-supervised and `ppo_objective_used=false`. This proves that cycle ran old code; it is negative evidence and cannot certify the promoted checkpoint.

## 8. Paper position/account-margin repair commands

Initial position-generation/capital validation:

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/paper_trade_management/test_lifecycle.py -k 'position_from_fill_reconciles_notional_margin_and_leverage or same_side_netting_recomputes_aggregate_capital_state or reopen_same_symbol_after_close_uses_new_position_generation or same_symbol_repeated_long_nets_into_one_position'
.venv/bin/python -m pytest -q v2/backend/tests/unit/cli/test_v2_portfolio_state_publisher_equity.py -k 'closed_generation_filter_keeps_later_reopen_with_reused_ids or closed_trade_source_ids_remove_accepted_fill_from_open_inventory'
```

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/paper_trade_management/test_lifecycle.py v2/backend/tests/unit/cli/test_v2_portfolio_state_publisher_equity.py
```

Result: 94 passed.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/paper_trade_management
```

Initial result: 369 passed. After the account-margin additions: 372 passed.

```bash
git diff --check -- v2/backend/app/services/paper_accounting/mark_to_market.py v2/backend/app/services/paper_trade_management/lifecycle.py v2/backend/app/services/paper_trade_management/outcomes.py v2/backend/app/services/paper_trade_management/position_state.py v2/backend/tests/unit/services/paper_trade_management/test_lifecycle.py v2/backend/tests/unit/cli/test_v2_portfolio_state_publisher_equity.py
.venv/bin/python -m py_compile v2/backend/app/services/paper_trade_management/generation_identity.py v2/backend/app/services/paper_trade_management/position_state.py v2/backend/app/services/paper_trade_management/lifecycle.py v2/backend/app/services/paper_trade_management/outcomes.py v2/backend/app/services/paper_accounting/mark_to_market.py
```

Result: passed.

Account-margin follow-up diagnostics and validation:

```bash
python -m py_compile v2/backend/app/services/paper_trade_management/margin_accounting.py
sed -n '1,80p' v2/backend/app/services/paper_trade_management/margin_accounting.py
git status --short --untracked-files=all -- v2/backend/app/services/paper_trade_management/margin_accounting.py
```

```bash
python -m py_compile v2/backend/app/services/paper_trade_management/margin_accounting.py v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/app/cli/v2_portfolio_state_publisher.py v2/backend/app/services/adaptive_capital_allocator/allocator.py v2/backend/tests/unit/services/paper_trade_management/test_margin_accounting.py v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py v2/backend/tests/unit/cli/test_v2_portfolio_state_publisher_equity.py v2/backend/tests/unit/services/adaptive_capital_allocator/test_allocator.py
```

Result: passed.

```bash
pytest -q v2/backend/tests/unit/services/paper_trade_management/test_margin_accounting.py v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py::test_margin_normalization_uses_executed_notional_and_preserves_upstream v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py::test_higher_paper_leverage_reduces_margin_and_recomputes_liquidation v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py::test_portfolio_context_subtracts_canonical_open_position_margin v2/backend/tests/unit/services/adaptive_capital_allocator/test_allocator.py::test_paper_allocator_fails_closed_when_account_wide_free_margin_is_zero v2/backend/tests/unit/services/adaptive_capital_allocator/test_allocator.py::test_leverage_is_lowest_safe_value_that_supports_margin_budget v2/backend/tests/unit/cli/test_v2_portfolio_state_publisher_equity.py::test_accepted_fill_recomputes_equity_from_current_market_price
```

Expected environment diagnostic: failed because bare `pytest` was not on `PATH`; no tests ran. The exact rerun was:

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/paper_trade_management/test_margin_accounting.py v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py::test_margin_normalization_uses_executed_notional_and_preserves_upstream v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py::test_higher_paper_leverage_reduces_margin_and_recomputes_liquidation v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py::test_portfolio_context_subtracts_canonical_open_position_margin v2/backend/tests/unit/services/adaptive_capital_allocator/test_allocator.py::test_paper_allocator_fails_closed_when_account_wide_free_margin_is_zero v2/backend/tests/unit/services/adaptive_capital_allocator/test_allocator.py::test_leverage_is_lowest_safe_value_that_supports_margin_budget v2/backend/tests/unit/cli/test_v2_portfolio_state_publisher_equity.py::test_accepted_fill_recomputes_equity_from_current_market_price
```

Result: 9 passed.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/paper_trade_management/test_margin_accounting.py v2/backend/tests/integration/cli/test_v2_paper_fill_gate_block_reason_passthrough.py::test_paper_loop_reads_per_symbol_paper_signal_keys
```

Result: 4 passed. This covers account-margin timestamps/non-atomicity telemetry and aggregate-empty per-symbol discovery with fail-closed admission semantics.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/cli/test_v2_portfolio_state_publisher_equity.py::test_accepted_fill_recomputes_equity_from_current_market_price
```

Result: 1 passed. The portfolio publisher's reconstructed nested margin status uses its payload generation timestamp.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/adaptive_capital_allocator/test_allocator.py v2/backend/tests/unit/services/paper_trade_management/test_margin_accounting.py v2/backend/tests/unit/cli/test_v2_portfolio_state_publisher_equity.py
```

Result: 55 passed.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/adaptive_capital_allocator
```

Final result in this workstream: 101 passed.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py
```

Final result in this workstream: 429 passed.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/cli/test_v2_portfolio_state_publisher_equity.py v2/backend/tests/unit/cli/test_v2_adaptive_allocation_trade_lifecycle_24h_paper_soak.py
```

Result: 32 passed.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/paper_trade_management v2/backend/tests/unit/services/adaptive_capital_allocator v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py v2/backend/tests/unit/cli/test_v2_portfolio_state_publisher_equity.py v2/backend/tests/unit/cli/test_v2_adaptive_allocation_trade_lifecycle_24h_paper_soak.py
```

Result: 934 passed on two consecutive runs.

```bash
.venv/bin/ruff check v2/backend/app/services/paper_trade_management/margin_accounting.py v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/app/cli/v2_portfolio_state_publisher.py v2/backend/app/services/adaptive_capital_allocator/allocator.py v2/backend/tests/unit/services/paper_trade_management/test_margin_accounting.py v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py v2/backend/tests/unit/cli/test_v2_portfolio_state_publisher_equity.py v2/backend/tests/unit/services/adaptive_capital_allocator/test_allocator.py
```

Result: 717 inherited errors across legacy large files; this was not a green whole-file lint gate. Focused new-file checks followed:

```bash
.venv/bin/ruff check --fix v2/backend/app/services/paper_trade_management/margin_accounting.py
.venv/bin/ruff check --fix v2/backend/app/services/paper_trade_management/generation_identity.py
.venv/bin/ruff check --output-format concise v2/backend/app/services/paper_trade_management/generation_identity.py v2/backend/app/services/paper_trade_management/margin_accounting.py v2/backend/tests/unit/services/paper_trade_management/test_margin_accounting.py
```

Result: two mechanical import-format fixes; final focused check passed.

Final combined validation:

```bash
python -m py_compile v2/backend/app/services/paper_trade_management/generation_identity.py v2/backend/app/services/paper_trade_management/margin_accounting.py v2/backend/app/services/paper_trade_management/position_state.py v2/backend/app/services/paper_trade_management/lifecycle.py v2/backend/app/services/paper_trade_management/outcomes.py v2/backend/app/services/paper_accounting/mark_to_market.py v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/app/cli/v2_portfolio_state_publisher.py v2/backend/app/services/adaptive_capital_allocator/allocator.py
.venv/bin/ruff check --output-format concise v2/backend/app/services/paper_trade_management/generation_identity.py v2/backend/app/services/paper_trade_management/margin_accounting.py v2/backend/tests/unit/services/paper_trade_management/test_margin_accounting.py
git diff --check -- v2/backend/app/services/paper_trade_management/generation_identity.py v2/backend/app/services/paper_trade_management/margin_accounting.py v2/backend/app/services/paper_trade_management/position_state.py v2/backend/app/services/paper_trade_management/lifecycle.py v2/backend/app/services/paper_trade_management/outcomes.py v2/backend/app/services/paper_accounting/mark_to_market.py v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/app/cli/v2_portfolio_state_publisher.py v2/backend/app/services/adaptive_capital_allocator/allocator.py v2/backend/tests/unit/services/paper_trade_management/test_margin_accounting.py v2/backend/tests/unit/services/paper_trade_management/test_lifecycle.py v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py v2/backend/tests/unit/cli/test_v2_portfolio_state_publisher_equity.py v2/backend/tests/unit/services/adaptive_capital_allocator/test_allocator.py
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/paper_trade_management v2/backend/tests/unit/services/adaptive_capital_allocator v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py v2/backend/tests/unit/cli/test_v2_portfolio_state_publisher_equity.py v2/backend/tests/unit/cli/test_v2_adaptive_allocation_trade_lifecycle_24h_paper_soak.py
```

Result: compilation passed, focused lint passed, diff check passed, 934 tests passed.

### 8.1 Later executed-notional/cap/maintenance hardening

These commands were run after the earlier 934-pass cut. They validate the later fail-closed distinction between candidate estimates and executed open-position truth. The historical 934-pass result above must not be treated as a whole-suite result for this later moving worktree.

Initial compilation followed by a wrong-environment diagnostic:

```bash
python -m py_compile v2/backend/app/services/paper_trade_management/margin_accounting.py v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/tests/unit/services/paper_trade_management/test_margin_accounting.py v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py && cd v2/backend && pytest -q tests/unit/services/paper_trade_management/test_margin_accounting.py tests/unit/cli/test_v2_trade_management_paper_loop.py -k 'margin_accounting or margin_normalization or higher_paper_leverage or portfolio_context_subtracts or recommendation_only or target_only_open or above_decision_time_envelope or missing_maintenance'
```

Result: `py_compile` passed; bare `pytest` then failed with exit 127 because it was not on `PATH`. No tests ran in that invocation.

Environment discovery:

```bash
rg --files -g 'pytest' -g '!node_modules' -g '!frontend/node_modules' . | head -n 40
find . -maxdepth 4 -type f -path '*/bin/pytest' -print | head -n 40
command -v python
python -m pytest --version
```

Result: `./.venv-pytsst/bin/pytest` and `./.venv/bin/pytest` were found; system Python was `/usr/bin/python`; system Python had no pytest module.

Focused repository-venv selection:

```bash
.venv/bin/pytest -q v2/backend/tests/unit/services/paper_trade_management/test_margin_accounting.py v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py -k 'margin_accounting or margin_normalization or higher_paper_leverage or portfolio_context_subtracts or recommendation_only or target_only_open or above_decision_time_envelope or missing_maintenance'
```

Result: 12 passed, 427 deselected in 1.42 seconds; one inherited pytest-asyncio loop-scope deprecation warning.

```bash
.venv/bin/pytest -q v2/backend/tests/unit/services/paper_trade_management/test_margin_accounting.py
```

Interim result before the final uncapped-extreme regression was added: 8 passed in 0.12 seconds; same warning.

Whole touched-file lint diagnostic:

```bash
.venv/bin/ruff check v2/backend/app/services/paper_trade_management/margin_accounting.py v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/tests/unit/services/paper_trade_management/test_margin_accounting.py v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py
```

Result: exit 1 with 605 errors across the legacy monolithic loop/test files. This is baseline lint debt, not a passing lint gate.

Focused new module/test lint:

```bash
.venv/bin/ruff check v2/backend/app/services/paper_trade_management/margin_accounting.py v2/backend/tests/unit/services/paper_trade_management/test_margin_accounting.py
```

Result: all checks passed.

Tracked diff and untracked-file diagnostics:

```bash
git diff --check -- v2/backend/app/services/paper_trade_management/margin_accounting.py v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/tests/unit/services/paper_trade_management/test_margin_accounting.py v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py
git diff --stat -- v2/backend/app/services/paper_trade_management/margin_accounting.py v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/tests/unit/services/paper_trade_management/test_margin_accounting.py v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py
```

Result: diff check passed. Normal `git diff` showed only the tracked loop/test files because the margin module/test were untracked.

```bash
git status --short -- v2/backend/app/services/paper_trade_management/margin_accounting.py v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/tests/unit/services/paper_trade_management/test_margin_accounting.py v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py
rg -n "margin_accounting" .gitignore
```

Result: the tracked loop files appeared modified; no ignore rule matched, so the combined command returned 1 on the no-match `rg`.

```bash
git ls-files --stage v2/backend/app/services/paper_trade_management/margin_accounting.py v2/backend/tests/unit/services/paper_trade_management/test_margin_accounting.py
ls -l v2/backend/app/services/paper_trade_management/margin_accounting.py v2/backend/tests/unit/services/paper_trade_management/test_margin_accounting.py
git check-ignore -v v2/backend/app/services/paper_trade_management/margin_accounting.py v2/backend/tests/unit/services/paper_trade_management/test_margin_accounting.py || true
```

Result: neither file had a tracked index entry or ignore match; both existed on disk.

```bash
git config --get status.showUntrackedFiles || true
git status --short --untracked-files=all | rg 'margin_accounting' || true
git rev-parse --show-toplevel
git check-ignore -q v2/backend/app/services/paper_trade_management/margin_accounting.py; echo $?
```

Result: `status.showUntrackedFiles=no`; explicit untracked status showed both files with `??`; repository root matched this ledger; check-ignore returned 1.

Full paper-loop unit file during concurrent canonical-decision hardening:

```bash
.venv/bin/pytest -q v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py
```

Result: 418 passed and 13 failed in 1.93 seconds. All failures were concurrent decision-dereference/per-ID tests concerning preview acceptance, inline PASS and consumer-built records; none was a margin assertion. This is a failed full-file gate.

Cross-component lifecycle/portfolio checks:

```bash
.venv/bin/pytest -q v2/backend/tests/unit/cli/test_v2_portfolio_state_publisher_equity.py v2/backend/tests/unit/services/paper_trade_management/test_lifecycle.py -k 'margin or leverage or capital_accounting or liquidation'
```

Result: one passed, 93 deselected in 0.15 seconds.

```bash
.venv/bin/pytest -q v2/backend/tests/unit/cli/test_v2_portfolio_state_publisher_equity.py v2/backend/tests/unit/services/paper_trade_management/test_lifecycle.py
```

First result: 93 passed and one failed. `test_accepted_fill_recomputes_equity_from_current_market_price` used a fixture without the now-required canonical effective-leverage and maintenance evidence, so accounting correctly failed closed.

The exact same command after making the fixture explicit returned 94 passed in 0.23 seconds.

Final focused accounting/lifecycle validation, including the uncapped-extreme regression:

```bash
.venv/bin/ruff check v2/backend/app/services/paper_trade_management/margin_accounting.py v2/backend/tests/unit/services/paper_trade_management/test_margin_accounting.py && .venv/bin/pytest -q v2/backend/tests/unit/services/paper_trade_management/test_margin_accounting.py v2/backend/tests/unit/cli/test_v2_portfolio_state_publisher_equity.py v2/backend/tests/unit/services/paper_trade_management/test_lifecycle.py
```

Result: Ruff passed; 103 tests passed in 0.26 seconds.

```bash
.venv/bin/pytest -q v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py -k 'margin_accounting or margin_normalization or higher_paper_leverage or portfolio_context_subtracts or recommendation_only or target_only_open or above_decision_time_envelope or missing_maintenance'
```

Result: four passed, 427 deselected in 0.26 seconds. The standalone regressions are covered by the 103-pass command above.

```bash
python -m py_compile v2/backend/app/services/paper_trade_management/margin_accounting.py v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/tests/unit/services/paper_trade_management/test_margin_accounting.py v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py v2/backend/tests/unit/cli/test_v2_portfolio_state_publisher_equity.py
git diff --check -- v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py v2/backend/tests/unit/cli/test_v2_portfolio_state_publisher_equity.py
```

Result: both commands passed. The normal Git diff check cannot cover the two untracked margin files; compilation, focused Ruff and pytest covered their content.

Final maintenance null/restart regression after removing estimate-derived fallback:

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/paper_trade_management/test_lifecycle.py -k 'maintenance or reconciles_notional_margin_and_leverage'
```

Result: three passed, 77 deselected.

### 8.2 Dynamic paper-envelope hardening

```bash
.venv/bin/ruff check --fix v2/backend/app/services/adaptive_capital_allocator/dynamic_envelope.py
```

Result: one mechanical import issue fixed.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/adaptive_capital_allocator/test_dynamic_envelope.py
```

Result: 12 passed in 0.11 seconds; only the inherited pytest-asyncio loop-scope deprecation warning.

```bash
.venv/bin/ruff check v2/backend/app/services/adaptive_capital_allocator/dynamic_envelope.py v2/backend/tests/unit/services/adaptive_capital_allocator/test_dynamic_envelope.py
```

Result: all checks passed.

```bash
.venv/bin/python -m py_compile v2/backend/app/services/adaptive_capital_allocator/dynamic_envelope.py v2/backend/tests/unit/services/adaptive_capital_allocator/test_dynamic_envelope.py
```

Result: passed with no output.

```bash
git diff --check -- v2/backend/app/services/adaptive_capital_allocator/dynamic_envelope.py v2/backend/tests/unit/services/adaptive_capital_allocator/test_dynamic_envelope.py
```

Result: passed with no output.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/adaptive_capital_allocator
```

Result: 107 passed and one failed in 0.46 seconds. The failure was `test_go_live_fixture_matrix.py::test_ppo_on_policy_row_created_from_policy_sampled_close`: the old fixture expected `ppo_on_policy_entry_fields_present=true`, while concurrent deterministic-policy lineage hardening correctly made it false. This is a failed whole-directory gate even though the 12 focused envelope tests passed.

The strict actionable-signal context reducer, halted-probe crash/slot/economic scaling, and hedge runtime interlock were then checked together:

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py -k 'halted_probe or adaptive_hedge_runtime_interlock or dynamic_envelope_context'
```

Result: seven passed, 437 deselected in 1.81 seconds. The halted-probe fix replaces the previously undefined `confidence` reference with explicitly parsed finite calibrated confidence; missing/raw-only confidence fails closed. The fixtures also cover one provisional slot across three candidates, quarter-size notional/margin/risk consistency and the runtime hedge interlock. They do not close downstream reservation release, gate ownership, timestamp, exact-generation/bucket or outcome-stratification defects.

### 8.3 Final allocator leverage, maintenance and cross-mode hardening

The final allocator workstream validation combined the continuous leverage target, discrete envelope-bounded rung selection, paper maintenance fail-closed contract, counterfactual pruning, candidate-level cross-mode selection and disabled hedge-size amplification:

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/adaptive_capital_allocator/test_allocator.py v2/backend/tests/unit/services/adaptive_capital_allocator/test_adaptive_leverage_margin_ramp.py v2/backend/tests/unit/services/adaptive_capital_allocator/test_counterfactual.py v2/backend/tests/unit/services/adaptive_capital_allocator/test_phase6_status.py v2/backend/tests/unit/services/allocator/test_allocator_simulation.py && .venv/bin/python -m py_compile v2/backend/app/services/adaptive_capital_allocator/allocator.py v2/backend/app/services/adaptive_capital_allocator/contracts.py v2/backend/app/services/adaptive_capital_allocator/counterfactual.py && .venv/bin/ruff check --select F,E9,I v2/backend/app/services/adaptive_capital_allocator/allocator.py v2/backend/app/services/adaptive_capital_allocator/contracts.py v2/backend/app/services/adaptive_capital_allocator/counterfactual.py && git diff --check -- v2/backend/app/services/adaptive_capital_allocator v2/backend/tests/unit/services/adaptive_capital_allocator v2/backend/tests/unit/services/allocator/test_allocator_simulation.py
```

Result: 102 tests passed; compilation passed; focused Ruff passed; scoped diff check passed.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/adaptive_capital_allocator
```

Result: 116 passed and one unrelated stale behavior-policy fixture failed: `test_go_live_fixture_matrix.py::test_ppo_on_policy_row_created_from_policy_sampled_close`. The fixture expected an on-policy categorical row while the repaired publisher truthfully marks deterministic selection as PPO-ineligible. This invocation remains a failed whole-directory gate.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/adaptive_capital_allocator -k 'not test_ppo_on_policy_row_created_from_policy_sampled_close'
```

Result: 116 passed, one deselected. This isolates the allocator assertions but does not erase the stale-fixture failure above.

### 8.4 Adversarial outcome-memory, halted-probe and hedge audit

The existing outcome-memory aggregate tests passed, but the focused source audit found that they did not cover outcome-event freshness, impossible PIT lineage or lifetime-loss recovery:

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/paper_trade_management/test_phase2_3_4_gates.py -k 'aggregate or outcome_memory'
```

Result: 11 passed, 39 deselected.

The exact read-only forged-lineage/lifetime-drawdown reproduction was:

```bash
.venv/bin/python - <<'PY'
from v2.backend.app.services.paper_trade_management.outcome_memory_updater import build_outcome_memory_buckets_from_closed_trades
from v2.backend.app.services.paper_trade_management.outcome_memory import OutcomeMemoryBucket, evaluate_outcome_memory_bucket
rows=[]
for i in range(20):
    win=i%2==0
    rows.append({'symbol':'BTCUSDT','timeframe':'1m','realized_pnl_usd':100.0 if win else -2.0,'realized_pnl_bps':100.0 if win else -2.0,'generated_at':f'2026-07-17T00:{i:02d}:00Z','prediction_id':f'p{i}','signal_id':f's{i}','decision_id':f'd{i}','feature_snapshot_id':f'f{i}','mtf_snapshot_id':f'm{i}','feature_cutoff':'2099-01-01T00:00:00Z','decision_time':'2026-01-01T00:00:00Z','available_at':'2099-01-01T00:00:00Z','selected_action':'long','model_version':'fake','checkpoint_id':'fake','source_hashes':{'fake':'fake'}})
b=build_outcome_memory_buckets_from_closed_trades(rows)['v2:paper:outcome_memory:BTCUSDT:1m']
print({k:b[k] for k in ('trade_count','rolling_win_rate','rolling_ev_bps','drawdown_contribution_usd','degraded','block_reason','outcome_memory_can_block_entries','trusted_trade_count')})
print(evaluate_outcome_memory_bucket(OutcomeMemoryBucket.from_dict(b)))
PY
```

Result: 20 rows with net +$980, 50% win rate and +49 bps rolling EV were counted as 20 trusted trades despite impossible future cutoff/availability and fake IDs/hashes. The bucket hard-blocked on lifetime loss-only `DRAWDOWN_EXCEEDED:-20.00usd<-10.00usd`. This proves both presence-only trust/PIT admission and the non-recovering lifetime-loss latch.

The original hedge-amplification test passed because it asserted larger notional rather than a bounded max-loss invariant:

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/adaptive_capital_allocator/test_allocator.py -k 'hedge_aware_sizing'
```

Pre-containment result: one passed, 41 deselected. A direct source probe measured unhedged notional/risk budget/max loss of 399.88550647/83.49609375/83.73602505 and hedge-flag values of 619.26021827/83.49609375/129.67308971. The flag therefore raised max loss to about 1.553 times the same risk budget. The full inline probe body was not retained as a stable command artifact, so those values are recorded as an audit observation rather than reproducible command provenance.

The first halted-probe selector was wrong and selected no tests:

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py -k 'halted_empty_book_probe'
```

Result: 442 deselected; zero selected, so it was not validation.

After the confidence fix, then after slot/scaling tests were added, the same correct selector evolved from two passes to the final result:

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py -k 'halted_probe'
```

Initial result: two passed, 440 deselected. Final result: three passed, 441 deselected in 0.35 seconds.

Final allocator hedge containment:

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/adaptive_capital_allocator/test_allocator.py -k 'hedge_flag or hedge_aware_sizing'
```

Result: two passed, 40 deselected in 0.15 seconds. Current sizing is identical with/without the requested flag and stamps the disabled reason.

Historical Claude commits traced in this audit were:

- `b872bdf1714ff477f05fe952129fe17045a4e7c6` — degraded-timeframe staleness valve;
- `20adc4840b116e186a96ef9656056d064feb4f8d` — incremental probe-slot count;
- `8ccb3629f83f07e70b5d1a03ad68ede460951838` — actionable-signal probe floor;
- `9da77df836b2049e1186727e77b575df4bec83b7` — probe skip/context telemetry;
- `ce3062a47feafc2d3a2ffea3121f06ffe031090a` — three-attempt budget/admitted-symbol telemetry;
- `ca99a3f8822c1906ab63d18c52ee153da2d943c6` — unsafe hedge-aware sizing amplification;
- `35705d8d12b39a887e71373a96b47e07e91214b6` — explicit stale marker/tests;
- `5be59f5b042bc9a42f64df02dcbd20d89361e619` — admitted probes clear blocking stamps;
- `20449b545559171b1b737bec1fe382ba4d1bad9d` — aggregate P0 becomes advisory for probes.

The first six application changes did not add dedicated tests for the new behavior; the hedge test reinforced amplification rather than checking the risk budget. This violates the repository requirement that every behavioral change include tests or an explicit impossibility reason.

### 8.5 Supplied prior G11/G12 revalidation provenance

The user-supplied Claude transcript records this earlier verification command; it was not rerun merely to recreate history:

```bash
.venv/bin/python scripts/run_counterfactual_sweep.py && .venv/bin/python scripts/guardian_phase10_rare_event_tests.py
```

It records `CG-F047` appended to `goal_state/V2_CLAUDE_CONTINUOUS_ADVERSARIAL_VALIDATION_AND_CAPITAL_PRODUCTIVITY_GUARDIAN/FINDINGS.jsonl`, pointing to a counterfactual artifact generated at 2026-07-17 14:05:50 UTC and a rare-event artifact generated at 14:06:10 UTC. G11 was fresh FAIL. The rare-event artifact had zero explicit FAIL and eight WARNING; although the historical finding called that PASS under its then-current interpretation, the corrected zero-warning G12 contract classifies it FAIL. This ledger retains both the provenance and the later semantic correction.

### 8.6 Isolated read-only Binance USD-M bracket evidence

The connector workstream created only four files and made no network call, systemd installation/restart, paper-loop integration, live edit or exchange mutation. Focused service/CLI tests:

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/test_binance_usdm_leverage_bracket_evidence.py v2/backend/tests/unit/cli/test_v2_binance_usdm_leverage_bracket_evidence.py
```

Result: 25 passed.

Existing signed-adapter contract plus connector tests:

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/execution/test_stealth_and_intent.py v2/backend/tests/unit/services/test_binance_usdm_leverage_bracket_evidence.py v2/backend/tests/unit/cli/test_v2_binance_usdm_leverage_bracket_evidence.py
```

Result: 35 passed.

Final static validation run by the documentation reconciler:

```bash
.venv/bin/python -m ruff check v2/backend/app/services/binance_usdm_leverage_bracket_evidence.py v2/backend/app/cli/v2_binance_usdm_leverage_bracket_evidence.py v2/backend/tests/unit/services/test_binance_usdm_leverage_bracket_evidence.py v2/backend/tests/unit/cli/test_v2_binance_usdm_leverage_bracket_evidence.py && .venv/bin/python -m mypy --config-file v2/pyproject.toml v2/backend/app/services/binance_usdm_leverage_bracket_evidence.py v2/backend/app/cli/v2_binance_usdm_leverage_bracket_evidence.py && .venv/bin/python -m py_compile v2/backend/app/services/binance_usdm_leverage_bracket_evidence.py v2/backend/app/cli/v2_binance_usdm_leverage_bracket_evidence.py v2/backend/tests/unit/services/test_binance_usdm_leverage_bracket_evidence.py v2/backend/tests/unit/cli/test_v2_binance_usdm_leverage_bracket_evidence.py
```

Result: Ruff all checks passed; mypy reported no issues in two source files; compilation passed.

These results validate normalization, credential-free status, read-only mutation stamps, hash/time/TTL checks and fail-closed bracket selection on fixtures. They do not prove credentials, REST transport permission, current account brackets, Redis deployment or paper allocation integration.

### 8.7 Independent glue/PIT audit and post-audit source checks

The independent bracket-glue audit made no source edit and no network/exchange call. Its adversarial harness exposed high-water overshoot, incomplete lifecycle provenance, a dead Tier-0 liquidation-distance read, cross-versus-isolated math, early allocation time, alias drift, and missing full-run/deployment proof. Its recorded focused results were 5 helper/compaction, 8 lifecycle-bracket, and 60 combined-selection tests passed. A second read-only PIT/alias audit ran no tests and edited no files; it traced missing dynamic-envelope, fee, TA/ATR, correlation, strategy/cascade, advanced-indicator, microstructure, capital-state and persistence-schema provenance.

At an intermediate source-hardening cut, the documentation reconciler ran these exact narrow checks:

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py -k 'paper_allocation_point_in_time_contract or maintenance_bracket or bracket_evidence'
```

Result: 2 passed, 448 deselected in 0.27 seconds.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/paper_trade_management/test_lifecycle.py v2/backend/tests/unit/services/paper_trade_management/test_phase7_hedge_and_exits.py -k 'maintenance_bracket or flattened_bracket or selector_shaped or liquidation_distance or cross_margin'
```

Result: 3 passed, 126 deselected in 0.19 seconds.

The complete affected modules were then rerun:

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py
```

Result: 450 passed in 0.49 seconds.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/paper_trade_management/test_lifecycle.py v2/backend/tests/unit/services/paper_trade_management/test_phase7_hedge_and_exits.py
```

Result: 129 passed in 0.30 seconds.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/test_binance_usdm_leverage_bracket_evidence.py v2/backend/tests/unit/cli/test_v2_binance_usdm_leverage_bracket_evidence.py v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py
```

Result: 499 passed in 0.53 seconds.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/paper_trade_management/test_lifecycle.py
```

Result: 93 passed in 0.21 seconds.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/paper_trade_management
```

Result: 411 passed in 0.98 seconds.

Every command emitted only the already-known `pytest-asyncio` default-loop-scope deprecation warning. These source checks prove the selected/module contracts at that intermediate cut only. A later audit found materialization-boundary TOCTOU and post-allocator sizing mutations, and source changed again; therefore 93/411/450/499 are historical checkpoints, not final counts. They do not supply the missing full `run_once`, lifecycle-side cryptographic HMAC verification, approved poller, network response, deployed restart, fresh allocation/outcome receipt, positive expectancy, or A+ evidence. The earlier coordinated 929-test result is likewise not relabeled as current without a final rerun.

### 8.8 Scoped A+ derived-context clock hardening

An independent scoped workstream hardened `a_plus_trade_gate.service._parse_utc` and `_fresh`, then ran:

```bash
python -m py_compile v2/backend/app/services/a_plus_trade_gate/service.py v2/backend/tests/unit/services/a_plus_trade_gate/test_context_loader.py
.venv/bin/ruff check --select F821 v2/backend/app/services/a_plus_trade_gate/service.py v2/backend/tests/unit/services/a_plus_trade_gate/test_context_loader.py
.venv/bin/pytest -q v2/backend/tests/unit/services/a_plus_trade_gate v2/backend/tests/unit/services/adaptive_regime_gate/test_phase3_regime_gate.py v2/backend/tests/unit/services/native_trainer/test_a_plus_phase8_trade_gate.py
git diff --check -- v2/backend/app/services/a_plus_trade_gate/service.py v2/backend/tests/unit/services/a_plus_trade_gate/test_context_loader.py
```

Result: compilation passed; focused Ruff passed; 30 tests passed in 0.16 seconds; scoped diff check passed. The adversarial matrix covers naive/future generation and availability for regime, HTF, and tape, plus generation/availability ordering, required generation, legacy generation-only compatibility, and alias semantics. An earlier broad Ruff invocation stopped on 19 pre-existing style violations in the service; no unrelated style cleanup was performed. These checks are source evidence only. They do not make `available_at` mandatory on legacy context rows, prove every A+ input's temporal contract, prove deployment, or change the FAIL-for-A+ decision.

### 8.9 Preloaded paper entry-gate evidence boundary

The first literal invocation used a non-environment `pytest` command and failed before collection because `pytest` was not on `PATH`. It was rerun through the repository environment:

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/paper_trade_management/test_entry_gate_preloaded_evidence.py
```

Result: 13 passed.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/paper_trade_management/test_phase2_3_4_gates.py v2/backend/tests/unit/services/paper_trade_management/test_side_performance_gate.py v2/backend/tests/unit/services/microstructure_trust/test_cascade_context.py
```

Result: 64 passed.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py -k 'cg_f038 or r29_d2 or r30_d1'
```

Result: 13 passed, 437 deselected.

```bash
.venv/bin/python -m py_compile v2/backend/app/services/paper_trade_management/entry_gate.py v2/backend/tests/unit/services/paper_trade_management/test_entry_gate_preloaded_evidence.py
.venv/bin/python -m ruff check --select F821 v2/backend/app/services/paper_trade_management/entry_gate.py v2/backend/tests/unit/services/paper_trade_management/test_entry_gate_preloaded_evidence.py
git diff --check -- v2/backend/app/services/paper_trade_management/entry_gate.py v2/backend/tests/unit/services/paper_trade_management/test_entry_gate_preloaded_evidence.py
```

Result: all passed. These 90 tests establish the service-level no-late-Redis-read contract and legacy compatibility. At this command cut, the paper-loop caller had not yet bound/hash-stamped all inputs and invoked `runtime_evidence_preloaded=true`; the legacy read-through path therefore remained reachable. Do not call the end-to-end TOCTOU boundary closed from these counts alone.

### 8.10 Allocator post-step notional/margin identity

```bash
.venv/bin/python -m pytest -q 'v2/backend/tests/unit/services/adaptive_capital_allocator/test_allocator.py::test_paper_coarse_step_fails_closed_when_final_size_is_below_exchange_minimum' 'v2/backend/tests/unit/services/adaptive_capital_allocator/test_allocator.py::test_paper_post_quantization_notional_drives_margin_and_liquidation_stress' 'v2/backend/tests/unit/services/adaptive_capital_allocator/test_allocator.py::test_paper_probe_fraction_is_applied_before_filters_and_all_derivations' 'v2/backend/tests/unit/services/adaptive_capital_allocator/test_allocator.py::test_paper_probe_fraction_never_rounds_up_to_exchange_minimum' v2/backend/tests/unit/services/adaptive_capital_allocator/test_adaptive_leverage_margin_ramp.py
```

Result: 18 passed in 0.16 seconds, plus the existing pytest-asyncio deprecation warning.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/adaptive_capital_allocator
```

Result: **1 failed, 126 passed in 0.49 seconds**. The sole failure was `test_paper_margin_mode_keeps_isolated_until_account_wide_cross_model_exists`: its current expectation requires `cross_margin_safe=true`, while the isolated-only/no-account-wide-cross implementation returns false. The post-step code does not control that value, but the full-directory command is still a failed gate and is not reported green.

```bash
.venv/bin/python -m py_compile v2/backend/app/services/adaptive_capital_allocator/allocator.py v2/backend/tests/unit/services/adaptive_capital_allocator/test_allocator.py
.venv/bin/ruff check --select F821 v2/backend/app/services/adaptive_capital_allocator/allocator.py v2/backend/tests/unit/services/adaptive_capital_allocator/test_allocator.py
git diff --check -- v2/backend/app/services/adaptive_capital_allocator/allocator.py v2/backend/tests/unit/services/adaptive_capital_allocator/test_allocator.py
```

Result: compilation and scoped diff check exited zero with no output; focused Ruff reported `All checks passed!`. The focused tests prove the source identity for coarse step sizes and both exchange minima. They do not prove the final paper-loop integration/deployment or close the full-directory failure.

The otherwise-isolated allocator package was also run as:

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/adaptive_capital_allocator -k 'not test_paper_margin_mode_keeps_isolated_until_account_wide_cross_model_exists'
```

Result: 126 passed, one deselected in 0.61 seconds, with the same pytest-asyncio warning. This isolates the independently inconsistent cross-margin expectation; it does not erase the failed complete-directory invocation above.

### 8.11 Preemptive decision tuning/time/input snapshot

```bash
.venv/bin/pytest -q v2/backend/tests/unit/services/preemptive_edge_control
```

Initial focused result was 69 passed in 0.36 seconds; the post-hash-alignment rerun was 69 passed in 0.22 seconds; after adding the failed-deep-materialization adversarial case, the final focused result was 70 passed in 0.26 seconds. The new case proves a candidate whose deep copy/materialization raises becomes `CANDIDATE_PAYLOAD_MISSING`/`NO_TRADE`, never a partial snapshot. These invocations emitted only the existing pytest-asyncio deprecation warning.

```bash
.venv/bin/pytest -q v2/backend/tests/unit/services/live_gate/test_phase7_readiness.py v2/backend/tests/unit/services/market_structure/test_advanced_indicator_replay.py v2/backend/tests/unit/services/altdata/test_provider_consumption_status.py
```

Result: 22 passed in 0.23 seconds.

```bash
.venv/bin/pytest -q v2/backend/tests/unit/cli/test_v2_a_plus_candidate_inventory.py
```

Result: 38 passed in 0.31 seconds.

```bash
.venv/bin/pytest -q v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py -k preemptive
```

Initial result: five passed, 445 deselected in 0.40 seconds. Final caller-selection rerun: five passed, 445 deselected in 0.25 seconds.

```bash
.venv/bin/ruff format --check v2/backend/app/services/preemptive_edge_control/decision.py v2/backend/app/services/preemptive_edge_control/candidate_loss_risk.py v2/backend/tests/unit/services/preemptive_edge_control/test_decision_snapshot_contract.py
.venv/bin/ruff check v2/backend/app/services/preemptive_edge_control/decision.py v2/backend/app/services/preemptive_edge_control/candidate_loss_risk.py v2/backend/tests/unit/services/preemptive_edge_control/test_decision_snapshot_contract.py
python -m py_compile v2/backend/app/services/preemptive_edge_control/decision.py v2/backend/app/services/preemptive_edge_control/candidate_loss_risk.py v2/backend/tests/unit/services/preemptive_edge_control/test_decision_snapshot_contract.py
git diff --check
```

Result: three files were already formatted/left unchanged; Ruff passed; compilation and diff check exited zero. The final deterministic test proves `adaptive_tuning_state_hash` equals the paper entry snapshot's full-canonical-payload SHA-256 for the same nonempty tuning mapping. `preemptive_input_hash` remains a separate wider digest over the complete decision input receipt.

The complete paper-loop module was then run while adjacent boundary repairs were still landing:

```bash
.venv/bin/pytest -q v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py
```

Result at that cut: **441 passed, nine failed in 1.60 seconds**. The failures were outside the focused preemptive snapshot lane: advanced-indicator/tape fixture; three references to the removed field-scaling budget helper; stricter orderbook status; stricter mark `available_at`; two long/short clock-semantics fixtures; and stricter cost-contract fields. This is a failed intermediate module gate and must be superseded by a later literal full-module result, not ignored.

## 9. Earlier root integration checkpoint and certification commands

These coordinated invocations occurred before later entry-snapshot, final-materialization and post-quantization hardening. They are retained as an earlier checkpoint and must not be called the final regression. Later literal reruns supersede them only where explicitly recorded.

```bash
.venv/bin/python -m py_compile v2/backend/app/cli/v2_trade_management_paper_loop.py
```

Result: passed.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py
```

Result at the recorded integration cut: 426 passed.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/adaptive_capital_allocator
```

Result at the recorded integration cut: 100 passed.

```bash
.venv/bin/python scripts/guardian_phase10_rare_event_tests.py
```

Result: 9 PASS, 8 WARNING, exit 1. Under corrected semantics any warning means FAIL.

```bash
.venv/bin/python scripts/verify_claude_guardian_completion.py
```

Result: 10 of 16 gates passed and process exit 1. G10 found 45 capital-invariant violations; G11, G12, G13, and G14 were not passing. This is an end-to-end **FAIL**, not A+.

```bash
systemctl --user is-active ai-bot-v2-trade-management-paper-loop.service ai-bot-v2-risk-gateway-live-loop.service ai-bot-v2-native-cuda-trainer-persistent.service
```

Result: all three reported `active`. This proves process state only; it does not prove correct deployed source, current lineage, positive expectancy, or certification.

The unsafe paper hedge path required immediate paper-only containment. The intended paper unit alone was restarted; no live/exchange submitter or gate was changed:

```bash
systemctl --user restart ai-bot-v2-trade-management-paper-loop.service
systemctl --user is-active ai-bot-v2-trade-management-paper-loop.service
systemctl --user show ai-bot-v2-trade-management-paper-loop.service -p MainPID -p ActiveEnterTimestamp --no-pager
```

Result: `active`, `MainPID=2215061`, `ActiveEnterTimestamp=Fri 2026-07-17 16:00:27 EDT`.

The first selected-field runtime verification was equivalent to:

```bash
redis-cli --raw GET v2:paper:adaptive_hedge_status | jq '{
  generated_utc,resolved_enabled,env_flag_at_import,
  runtime_safety_interlock,runtime_safety_block_reason,enable_source,
  fill_synthesis
}'
```

Result: `generated_utc=2026-07-17T20:00:29.746Z`, `resolved_enabled=false`, `env_flag_at_import=true`, `runtime_safety_interlock=true`, reason `HEDGE_DISABLED_NO_ATOMIC_FUNDED_EXACT_LINEAGE_EXECUTION_PROOF`, `enable_source=runtime_safety_interlock`; fill synthesis was disabled with zero synthesized rows and reason `DISABLED`. This proves deployed hedge containment, not safety of the dormant hedge implementation or deployment of every other moving source change.

## 10. Safe repository inspection commands used for final reconciliation

The coordinated root/docs reconciliation used these command families exactly to prevent stale-file assumptions:

```bash
git status --short --untracked-files=all
git rev-parse HEAD
git log -1 --date=iso-strict --format='%H %ad %s'
git diff --stat
git diff --check
git diff --name-only
```

```bash
rg -n "TrainingExample|decision_time|trusted_replay|raw_return|long_net|short_net|counterfactual" v2/backend -g '*.py'
rg -n "risk_decision_id|paper_fill_allowed|RISK_PENDING|HALTED_PERFORMANCE|gross_notional_usd|allocated_margin_usd|effective_leverage" v2/backend docs -g '*.py' -g '*.md'
rg -n "reserved_margin|available_margin|margin_account|generation_identity|position_generation_id" v2/backend -g '*.py'
```

```bash
sed -n '1,220p' docs/MASTER_SYSTEM_DOC.md
sed -n '1,260p' docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md
sed -n '1,260p' docs/system_audit_2026_master/OPERATOR_VALIDATION_AND_MONITORING_RUNBOOK_2026-07-17.md
```

Some inspections used narrower `nl -ba ... | sed -n ...` ranges and `jq` projections to avoid dumping large tensors, ledgers, or secrets. They were read-only. No live exchange command was run.

The current source feature-width reconciliation used:

```bash
.venv/bin/python -c 'from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import FEATURE_SPEC; print(len(FEATURE_SPEC), len(FEATURE_SPEC) * 4)'
```

Result: `446 1784`; the component document preserves the older 477/1,908 deployment measurement as historical and marks the mismatch unresolved.

The current ordered source digest was computed without importing trainer runtime code:

```bash
.venv/bin/python - <<'PY'
import ast, hashlib, json
from pathlib import Path
path = Path('v2/backend/app/services/native_trainer/hybrid_cuda_trainer/tensor_builder.py')
tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
node = next(item for item in tree.body if isinstance(item, ast.AnnAssign) and getattr(item.target, 'id', None) == 'FEATURE_SPEC')
spec = ast.literal_eval(node.value)
actual = hashlib.sha256(json.dumps(spec, separators=(',', ':')).encode()).hexdigest()
print(len(spec), len(spec) * 4, actual)
PY
```

Result: `446 1784 f7ab7245c0919f0be4a2831d193dca5263b643c0d875f992a68ba8fe01e3c34c`. This is the intended current source ABI digest, not proof that a deployed checkpoint or historical replay row matches it.

Final documentation whitespace/fence validation used:

```bash
git diff --check -- docs/MASTER_SYSTEM_DOC.md docs/system_audit_2026_master
for file in docs/MASTER_SYSTEM_DOC.md docs/system_audit_2026_master/ADAPTIVE_END_TO_END_CONTROL_AND_ACCOUNTING_2026-07-17.md docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md docs/system_audit_2026_master/COMMAND_LEDGER_2026-07-17.md docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md docs/system_audit_2026_master/OPERATOR_VALIDATION_AND_MONITORING_RUNBOOK_2026-07-17.md docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md docs/system_audit_2026_master/components/DECISION_RISK_PAPER_AND_LIVE_EXECUTION.md docs/system_audit_2026_master/components/TRAINER_PPO_MASA_REPLAY_AND_CHECKPOINTS.md; do count=$(awk '/^```/{n++} END{print n+0}' "$file"); if [ $((count % 2)) -ne 0 ]; then echo "unbalanced_fence $file $count"; exit 1; fi; done
printf '%s\n' doc_diff_and_fences_pass
```

Result: `doc_diff_and_fences_pass`.

## 11. Result interpretation

- Passing unit/integration tests establish only the tested source contracts.
- `systemctl is-active` establishes only a running process.
- A source change is not deployed evidence until a controlled reload and a new attributable record are observed.
- Historical margin inconsistencies remain failed historical evidence; they were not rewritten.
- G11 negative expectancy and warning-bearing G12 force certification FAIL.
- The 1000x-in-90-days value is an objective, not a guarantee. Current after-cost evidence does not support it.

## 12. 2026-07-18 trainer/resource truth and controlled probes

This section is later than sections 1–11 and supersedes their service-liveness/resource descriptions where they conflict. It records source, deployment and state separately. No live order, cancellation, margin-mode or exchange-leverage command was run.

### 12.1 Git provenance and pushed repair commits

The following scoped commits were present on `codex/pipeline-trust-refresh` and pushed before this documentation reconciliation:

```text
f4e1676e74  Bound trainer runtime logs and repair service environments
4cf7b948af  Make offline edge challenger strictly point-in-time
a2de1bb18b  Require validation guard for trainer promotion
9236bba4c9  Surface offline trainer failures to systemd
1db7a9fee1  Exclude control files from checkpoint retention
aae14956e4  Preserve trainer runtime schema identity
097fc01b46  Stop supervisor poll-event log amplification
1be4e78cdd  Separate trainer probe and service liveness
dd275e5e4c  Require evidence for trainer process and CUDA status
da8b6a44e3  Recover checkpoint identity during status probes
```

The root later pushed the already-existing dashboard HEAD without folding the dirty trainer/docs work into that commit:

```bash
git rev-parse HEAD
git status --branch --short | head -1
git log -1 --oneline --decorate
git branch -vv | rg '^\*'
```

Result at this documentation reconciliation: HEAD/local/origin branch were all `d03a98b1270fe8985edbbbe6238b80960d87eba4`, `Dashboard KPI cards: uniform fixed height + internal scroll (no blank space)`. This is branch provenance only; the dirty trainer/docs source was not thereby committed or deployed.

### 12.2 Controlled paper one-shot

```bash
/usr/bin/time -v timeout 300 .venv/bin/python -m v2.backend.app.cli.v2_trade_management_paper_loop --once --out /tmp/ai_bot_paper_status_probe_20260718_0125.json
```

Result: process exit 0, elapsed 69.85 seconds, peak RSS 4,925,812 KB (~4.70 GiB), zero swap. The cycle built 597 intents, accepted 0, blocked 597 and wrote 551 Redis keys. Process/resource classification `PRODUCTION_OK` described bounded process execution only. The temp/canonical artifacts were 5,017,701/4,160,870 bytes with no `Infinity`/`NaN`. Current/adaptive sources were hashable; persistent 132-row legacy history remained FAIL_CLOSED. Account margin accounted for 2/2 positions with equity/wallet 2,985.59472051, used 55.80754736, free 2,929.78717315, adaptive buffer 499.52893144 and post-buffer free 2,430.25824171. Bracket selection remained `BLOCKED:CREDENTIAL_BINDING_NOT_ACCOUNT_SPECIFIC`; no leverage binding/mutation/order occurred.

### 12.3 Controlled Guardian one-shot

The worker command recorded by `/usr/bin/time` was:

```bash
timeout 300 .venv/bin/python -m v2.backend.app.cli.v2_continuous_edge_guardian --once --no-redis
```

The shell captured JSON in `/tmp/codex_guardian_once_20260718.json` and timing in `/tmp/codex_guardian_once_20260718.time`.

Result: exit 2 was the expected semantic BLOCKED result; elapsed 3.57 seconds, peak RSS 35,896 KB, zero swap. `guardian_status=A_GRADE_HALTED_PERFORMANCE`; anti-metric-gaming was PASSED; canonical allocation aggregate validation had no errors. New A-grade entries were blocked while reduce/close/emergency de-risk remained allowed. All 26 recommendations were 1x and status `BLOCKED_UNTIL_A_GRADE_EDGE_PROVEN`. Phase-3 coverage contained 99,644 PIT-valid predictions across 135 symbols/five timeframes, but holdout `accepted_row_count=0` because there were no countable pre-outcome A-grade rows/passed reverify manifest. Redis publication was `SKIPPED_BY_CALLER`.

### 12.4 Strict Ridge real-archive probe

The exact timed worker command was:

```bash
.venv/bin/python -c 'from pathlib import Path; import json; from v2.backend.app.services.native_trainer.model_edge_recovery_challenger import run_champion_challenger; r=run_champion_challenger(repo_root=Path.cwd(), scan_limit=200, replay_limit=200); print(json.dumps({"status":r["status"],"blocker_reasons":r["blocker_reasons"],"row_counts":r["row_counts"],"dataset_freeze":{k:r["dataset_freeze"].get(k) for k in ("snapshots_scanned","accepted_rows","action_specific_cost_coverage_complete","explicit_action_specific_cost_rows","missing_action_specific_cost_rows")},"rejections_by_reason":r["rejections_by_reason"],"edge_claim":r["edge_claim"]},sort_keys=True))'
```

Result: worker exit 0, elapsed 0.19 seconds, peak RSS 29,208 KB, zero swap. Semantic status was `BLOCKED_INSUFFICIENT_TRUSTED_REPLAY_ROWS`; train/validation/untouched-holdout were 0/0/0. Rejections were fee evidence missing/invalid 145, slippage evidence missing/invalid 145 and latest-unclosed exclusion unproven 55. Blockers included incomplete action-specific cost coverage, insufficient distinct decision groups and empty train/validation partitions after the four-hour purge. `edge_claim.allowed=false`; no model, paper signal, checkpoint, A+ or live result was produced.

### 12.5 Redis evidence-size snapshot

```bash
date --iso-8601=seconds
redis-cli INFO memory | rg '^(used_memory_human|maxmemory_human|maxmemory_policy):'
redis-cli CONFIG GET appendonly
redis-cli TYPE v2:guardian:pit_prediction_observations
redis-cli TTL v2:guardian:pit_prediction_observations
redis-cli MEMORY USAGE v2:guardian:pit_prediction_observations
redis-cli LLEN v2:guardian:pit_prediction_observations
redis-cli TYPE v2:trainer:feedback:counterfactuals
redis-cli TTL v2:trainer:feedback:counterfactuals
redis-cli STRLEN v2:trainer:feedback:counterfactuals
stat -c '%n %s %y' claude_worklog/autonomous_control_plane/events.jsonl claude_worklog/agent_supervisor/events.jsonl 2>/dev/null || true
```

Result at `2026-07-18T02:15:13-04:00`: Redis reported 25.10G used, 32.00G maximum, `allkeys-lru`, `appendonly=no`. The Guardian key was a TTL −1 list using 6,230,529,272 bytes with 6,054,941 rows. The counterfactual key was a TTL −1 string of 536,827,021 bytes. `claude_worklog/agent_supervisor/events.jsonl` was 10,904,034,037 bytes. An earlier reconciliation sample reported total Redis use around 25.49 GiB; the changing aggregate does not alter the unbounded-object finding. No key/file was deleted or trimmed.

The supervisor source repair in `097fc01b46` filters two stable non-drift poll observations from the append-only transition log and retains bounded counts/sample in current queue status. The active producer was not restarted/deployed; sampled file growth remained about 112 KB/10 seconds (~0.9 GiB/day).

### 12.6 Exact service/timer repair-hold state

```bash
systemctl --user list-unit-files --no-pager | rg 'edge-replay|adaptive-capital-productivity|continuous-edge-guardian|native-cuda-trainer-persistent|continuous-offline-gpu-trainer|trainer-scheduled-pretrain|native-ppo-masa-continuous-training-guard' || true
systemctl --user show ai-bot-v2-edge-replay-factory.service ai-bot-v2-adaptive-capital-productivity.service ai-bot-v2-continuous-edge-guardian.service ai-bot-v2-native-cuda-trainer-persistent.service ai-bot-v2-continuous-offline-gpu-trainer.service ai-bot-v2-trainer-scheduled-pretrain.service ai-bot-v2-native-ppo-masa-continuous-training-guard.service -p Id -p ActiveState -p SubState -p RefuseManualStart -p NRestarts --no-pager || true
systemctl --user show ai-bot-v2-trainer-scheduled-pretrain.timer ai-bot-v2-native-ppo-masa-continuous-training-guard.timer -p Id -p ActiveState -p SubState --no-pager || true
```

Result: all seven services were `inactive/dead`, `RefuseManualStart=yes`, `NRestarts=0`. The scheduled-pretrain and native PPO/MASA continuous-guard timers were `inactive/dead`. This is temporary workstation deployment state and is not reproduced by Git alone. No live service was changed.

### 12.7 Retention candidate regression and adversarial rejection

The root literally reran the candidate retention suite:

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/tools/test_edge_replay_factory_loop.py v2/backend/tests/unit/services/test_all_timeframe_prediction_signal_price_target_publisher.py v2/backend/tests/unit/services/continuous_edge_guardian/test_pit_prediction_counter.py v2/backend/tests/integration/cli/test_v2_all_timeframe_prediction_signal_price_target_publisher.py
```

Result: 62 passed in 2.43 seconds.

This suite did **not** accept the implementation. Root adversarial reproductions release-blocked two contracts: archive-before-Guardian-`RPUSH` can cause a Redis-failed retry to be skipped/lost from the hot list, and counterfactual archival can preserve cost-blind labels. The draft was not deployed; no Redis migration/trim/delete occurred. A corrected retry/commit protocol and explicit after-cost label contract require new negative tests before migration review.

### 12.8 Source-validation handoffs still awaiting controlled runtime proof

The confidence handoff reported a final adversarial group of 35 passes (including strict outcome exit after decision and missing-fingerprint calibration loading unfitted), 66 adjacent trainer passes, one explicit external-fitter refusal pass, plus compile/lint success.

The final exact on-policy source commands were:

```bash
CUDA_VISIBLE_DEVICES='' .venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_hybrid_ppo_action_balance.py v2/backend/tests/unit/services/native_trainer/test_trust_feedback_weight_update_repair.py v2/backend/tests/unit/services/native_trainer/test_hybrid_confidence_profitability_semantics.py v2/backend/tests/unit/services/native_trainer/test_hybrid_trainer_regularization_and_validation.py
```

Result: 73 passed, one `pynvml` warning, 96.98 seconds.

```bash
CUDA_VISIBLE_DEVICES='' .venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_on_policy_behavior_receipt.py
```

Result: 16 passed, one `pynvml` warning, 1.85 seconds. This suite includes exact served-artifact/gate receipt failures, deterministic-action rejection, a real clipped optimizer delta and entry→position→close→feedback propagation.

The tested source contract is distinct from the historical runtime predicate: current source uses plan schema `v2_adaptive_on_policy_paper_lane_plan_v1` and receipt schema `v2_positive_edge_on_policy_behavior_receipt_v1`, with `CATEGORICAL_SAMPLE`, `POSITIVE_EDGE_MASKED_RAW_LOGITS_SOFTMAX_V1`, `NATIVE_CUDA_POLICY_CATEGORICAL_SAMPLE` and `PIT_AFTER_COST_POSITIVE_ENTRY_ACTION_MASK_V1`. Its evidence-derived credit/carry budget reserves ordinary paper supply, samples the positive-after-cost masked distribution with a cryptographic 53-bit draw, binds exact served-weight/PIT/feature/plan/action/probability/value/cost identity, and requires immutable seven-day receipt durability before paper/orchestrator eligibility. Inspection also found that carry/ordinary credit is process-local and unfenced, while the numeric cost may use a fixed 600-second/flat fallback without source/key/clock/fallback fields in the receipt; configured publisher coverage/confidence/edge minima still gate durability after the threshold-free plan selection. These are inspected source/test facts only; the observed old generation remains PPO 0/0.

```bash
CUDA_VISIBLE_DEVICES='' .venv/bin/python -m pytest -q v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py -k 'read_paper_signals_enriches_matched_native_policy_fields or read_paper_signals_rejects_future_native_policy_fields or read_paper_signals_never_leaks_exact_policy_proof_into_strategy_supply or trainer_feedback_keeps_deterministic_native_entry_outcome_supervised or trainer_feedback_keeps_legacy_self_contained_native_row_outcome_supervised'
```

Result: five passed, 533 deselected, 0.26 seconds.

```bash
CUDA_VISIBLE_DEVICES='' .venv/bin/python -m pytest -q v2/backend/tests/integration/cli/test_v2_trade_management_paper_strategy_router.py -k 'strategy_mode_collapse'
CUDA_VISIBLE_DEVICES='' .venv/bin/python -m pytest -q v2/backend/tests/integration/cli/test_v2_trade_management_paper_strategy_router.py
```

Results: mode-collapse selection eight passed/46 deselected in 1.00 second; the complete file passed 54 in 4.38 seconds.

```bash
CUDA_VISIBLE_DEVICES='' .venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_model_edge_recovery_challenger.py
```

Result: 16 passed in 0.24 seconds.

```bash
.venv/bin/python -m py_compile v2/backend/app/services/native_trainer/hybrid_cuda_trainer/on_policy_behavior.py v2/backend/app/services/native_trainer/hybrid_cuda_trainer/safety.py v2/backend/app/services/native_trainer/hybrid_cuda_trainer/publisher.py v2/backend/app/services/native_trainer/hybrid_cuda_trainer/runtime.py v2/backend/app/services/native_trainer/hybrid_cuda_trainer/ppo_trainer.py v2/backend/app/cli/v2_orchestrator_arbitration_loop.py v2/backend/app/cli/v2_risk_gateway_live_loop.py v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/app/services/paper_trade_management/position_state.py v2/backend/app/services/paper_trade_management/outcomes.py v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py v2/backend/tests/unit/services/native_trainer/test_on_policy_behavior_receipt.py v2/backend/tests/unit/services/native_trainer/test_hybrid_ppo_action_balance.py v2/backend/tests/unit/services/native_trainer/test_trust_feedback_weight_update_repair.py v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py
.venv/bin/python -m ruff format --check v2/backend/app/services/native_trainer/hybrid_cuda_trainer/on_policy_behavior.py v2/backend/tests/unit/services/native_trainer/test_on_policy_behavior_receipt.py
.venv/bin/python -m ruff check v2/backend/app/services/native_trainer/hybrid_cuda_trainer/on_policy_behavior.py v2/backend/tests/unit/services/native_trainer/test_on_policy_behavior_receipt.py
```

Result: compilation exited zero; two files were already formatted; focused Ruff passed. The handoff also reports the scoped undefined-name Ruff check and tracked production/test `git diff --check` exited zero; their full literal path lists were not reconstructed here.

The literal pytest command lines for the separate 35/66/1 confidence handoff were not present in the root command transcript at this documentation cut, so they are not reconstructed here. Confidence/on-policy source repairs were not deployed, no held trainer completed burn-in, runtime PPO remains 0/0, the TTL −1 Redis objects remain unchanged, and no A+/1000x/release claim follows.

### 12.9 Old-generation runtime handoff after source repair

The adaptive-mode-collapse workstream reported a final read-only runtime snapshot from the still-running old code generation:

```text
prediction rows / publication failures: 745 / 0
outcome-supervised rows:                 2,014
PPO admitted / consumed / clipped:       0 / 0 / 0
PPO objective used:                      false
serving-policy validation edge bps:      -1.39286013
serving-policy validation LCB bps:       -2.25532918
composed gate:                           HALTED
paper margin:                            PASS
MANA / ARB leverage:                     2x / 2x
```

The root did not receive the literal Redis read commands and did not independently reproduce this snapshot, so it is labeled handoff-reported read-only evidence. It is negative deployment evidence: the source repair is not active in that generation, PPO remains 0/0, validation edge is adverse, and two 2x positions do not prove profitable adaptive leverage. Fresh literal controlled/read-only probes are required after source acceptance.

### 12.10 Corrected Guardian archive consumer and retention source validation

After the rejected 62-test draft, the corrected publisher/consumer/counterfactual source was validated with these exact commands:

```bash
.venv/bin/pytest -q v2/backend/tests/unit/services/continuous_edge_guardian/test_pit_prediction_counter.py
```

Result: 18 passed in 2.24 seconds. The only diagnostic was the existing pytest-asyncio unset-loop-scope deprecation warning.

```bash
.venv/bin/pytest -q v2/backend/tests/unit/services/test_all_timeframe_prediction_signal_price_target_publisher.py v2/backend/tests/unit/services/continuous_edge_guardian/test_pit_prediction_counter.py v2/backend/tests/unit/tools/test_edge_replay_factory_loop.py v2/backend/tests/integration/cli/test_v2_all_timeframe_prediction_signal_price_target_publisher.py
```

Result: 87 passed in 5.33 seconds, with the same pytest-asyncio warning.

```bash
python -m py_compile v2/backend/app/services/continuous_edge_guardian/pit_prediction_counter.py tools/guardian_pit_prediction_counter.py v2/backend/tests/unit/services/continuous_edge_guardian/test_pit_prediction_counter.py
```

Result: exit 0.

```bash
.venv/bin/ruff check --ignore E501 v2/backend/app/services/continuous_edge_guardian/pit_prediction_counter.py tools/guardian_pit_prediction_counter.py v2/backend/tests/unit/services/continuous_edge_guardian/test_pit_prediction_counter.py
```

Result: all checks passed. E501 was deliberately ignored because these files retain pre-existing long-line formatting debt.

```bash
git diff --check -- v2/backend/app/services/continuous_edge_guardian/pit_prediction_counter.py tools/guardian_pit_prediction_counter.py v2/backend/tests/unit/services/continuous_edge_guardian/test_pit_prediction_counter.py
```

Result: exit 0.

The accepted source contract uses authoritative SQLite stream `v2_guardian_pit_prediction_observations_unique_v1`, consumer ID `guardian_pit_prediction_counter_v1`, cursor/status metadata `consumer_cursor:guardian_pit_prediction_counter_v1` and `consumer_status:guardian_pit_prediction_counter_v1`, and a 10,000-row default batch. It matches the publisher's `prediction_id + source key` record identity; validates content, semantic, sequence, sort and archive-chain hashes plus explicit UTC PIT/finality; quarantines and advances hash-authentic legacy/semantically dirty rows without counting them; hard-blocks malformed non-wrapper/corrupt evidence; and makes the fsynced JSONL sink path/count/chain-bound and crash-replay idempotent. Redis trim safety additionally requires consumer catch-up, publisher legacy migration completion/cursor coverage, empty delivery outbox and sink revalidation. No real Redis migration, trim, delete, service reload or resident burn-in ran.

### 12.11 Final trainer adversarial audit and negative probes

The final trainer audit was read-only. First, the exact receipt group was rerun:

```bash
PYTHONDONTWRITEBYTECODE=1 CUDA_VISIBLE_DEVICES='' .venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_on_policy_behavior_receipt.py
```

Result: 16 passed, one warning, 1.73 seconds.

```bash
PYTHONDONTWRITEBYTECODE=1 CUDA_VISIBLE_DEVICES='' .venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_confidence_calibration.py v2/backend/tests/unit/services/native_trainer/test_confidence_proportional_calibration.py v2/backend/tests/unit/services/native_trainer/test_hybrid_confidence_profitability_semantics.py
```

Result: 25 passed, one warning, 10.24 seconds. The warnings were the existing pytest-asyncio configuration and Torch `pynvml` warning families; both processes exited 0.

The PIT-safe scarce-PPO split probe was:

```bash
PYTHONDONTWRITEBYTECODE=1 CUDA_VISIBLE_DEVICES='' .venv/bin/python - <<'PY'
from types import SimpleNamespace
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import V2HybridPPOTrainer
rows = [
    SimpleNamespace(name='replay_early', decision_time='2026-01-01T00:00:00Z', label_available_at='2026-01-01T00:01:00Z', label_timing_valid=True, label_timing_error=None),
    SimpleNamespace(name='replay_mid', decision_time='2026-01-01T00:10:00Z', label_available_at='2026-01-01T00:11:00Z', label_timing_valid=True, label_timing_error=None),
    SimpleNamespace(name='sole_ppo_latest', decision_time='2026-01-01T00:20:00Z', label_available_at='2026-01-01T00:21:00Z', label_timing_valid=True, label_timing_error=None),
]
train, validation, metrics = V2HybridPPOTrainer._chronological_purged_split(rows, validation_fraction=0.34)
print('train=', [r.name for r in train])
print('validation=', [r.name for r in validation])
print('pit_safe=', metrics['validation_split_pit_safe'], 'reason=', metrics['validation_split_reason'])
PY
```

Result, exit 0:

```text
train= ['replay_early', 'replay_mid']
validation= ['sole_ppo_latest']
pit_safe= True reason= PIT_SAFE_CHRONOLOGICAL_PURGED_SPLIT
```

This preserves PIT safety but proves that PPO-first row ordering does not guarantee optimizer PPO supply: a sole/latest exact PPO row may be validation-only.

The consolidated receipt/economics/terminal/promotion probe was:

```bash
PYTHONDONTWRITEBYTECODE=1 CUDA_VISIBLE_DEVICES='' .venv/bin/python - <<'PY'
import math
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.confidence import profitability_target_from_trust_row
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import V2HybridPolicyModel
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.on_policy_behavior import U53_DENOMINATOR, build_positive_edge_behavior_receipt, model_parameter_fingerprint
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import V2HybridPPOTrainer
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.runtime import _checkpoint_promotion_decision
from v2.backend.tests.unit.services.native_trainer.test_hybrid_confidence_profitability_semantics import _trust
from v2.backend.tests.unit.services.native_trainer.test_on_policy_behavior_receipt import _exact_ppo_example, _model_output, _tensor

receipt = build_positive_edge_behavior_receipt(
    prediction_id='probe_equal_time', model_output=_model_output(selected_action='long'),
    checkpoint_id='probe_checkpoint', checkpoint_weight_sha256=None,
    served_policy_fingerprint='d' * 64, feature_tensor_id='probe_tensor',
    feature_vector_hash='probe_hash', feature_cutoff='2026-07-18T00:01:00Z',
    available_at='2026-07-18T00:01:00Z', candle_close_time='2026-07-18T00:01:00Z',
    decision_time='2026-07-18T00:01:00Z', candle_closed_confirmed=True,
    round_trip_cost_bps=2.0, draw_u53=U53_DENOMINATOR - 1,
    sampling_plan_hash='a' * 64, sampling_plan_input_hash='b' * 64,
)
print('equal_close_decision_receipt_accepted=', bool(receipt), 'checkpoint_hash=', receipt['checkpoint_weight_sha256'])

contradictory = _trust(91, profitable=True)
contradictory.update({'realized_net_pnl_bps': 10.0, 'gross_realized_pnl_usd': -100.0, 'realized_net_pnl_usd': 1.0, 'fees': 1000.0, 'slippage': 1000.0, 'funding': 0.0})
contradictory['outcome_targets'].update({'realized_net_pnl_bps': 10.0, 'gross_realized_pnl_usd': -100.0, 'realized_net_pnl_usd': 1.0, 'fees': 1000.0, 'slippage': 1000.0, 'funding': 0.0})
profit = profitability_target_from_trust_row(contradictory)
print('contradictory_cost_target=', {'eligible': profit['eligible'], 'target': profit['target'], 'reason': profit['reason']})

model = V2HybridPolicyModel(input_dim=len(_tensor().model_vector), seed=37)
assert model.torch_available and model.torch is not None and model.net is not None
with model.torch.no_grad():
    model.net.expected_move_head.weight.zero_()
    model.net.expected_move_head.bias.fill_(math.atanh(12.0 / 120.0))
exact = _exact_ppo_example(index=1, model=model, policy_fingerprint=model_parameter_fingerprint(model))
exact.trust_row['done'] = False
exact.trust_row['trajectory_index'] = -0.5
exact.trust_row['reward'] = 999.0
print('corrupt_terminal_reward_ppo_ineligibility=', V2HybridPPOTrainer._ppo_ineligibility_reason(exact))

metrics = {
    'validation_split_pit_safe': True,
    'validation_split_actual_validation_rows': 2,
    'validation_policy_edge_evidence_valid': True,
    'validation_policy_edge_rows_evaluated': 2,
    'validation_policy_edge_after_cost_bps': 1.0,
    'validation_policy_edge_lower_confidence_bound_bps': 0.1,
    'validation_rows_evaluated': 2,
    'validation_supervised_loss_before': 1.0,
    'validation_supervised_loss_after': 0.9,
    'confidence_calibration_fitted': False,
    'validation_confidence_status': 'CHECKPOINT_CALIBRATION_UNFITTED',
    'validation_confidence_brier': None,
    'validation_confidence_ece': None,
}
print('unfitted_confidence_promotion_reason=', _checkpoint_promotion_decision(training_metrics=metrics, checkpoint_load={})['checkpoint_promotion_reason'])
negative = dict(metrics, validation_policy_edge_after_cost_bps=-1.0, validation_policy_edge_lower_confidence_bound_bps=-2.0)
print('cold_start_negative_edge_reason=', _checkpoint_promotion_decision(training_metrics=negative, checkpoint_load={})['checkpoint_promotion_reason'])
PY
```

Result: exit 0 in 1.0618 seconds, with only the Torch `pynvml` warning. Standard output was:

```text
equal_close_decision_receipt_accepted= True checkpoint_hash= None
contradictory_cost_target= {'eligible': True, 'target': 1, 'reason': None}
corrupt_terminal_reward_ppo_ineligibility= None
unfitted_confidence_promotion_reason= PIT_EDGE_BOOTSTRAP_PASS
cold_start_negative_edge_reason= VALIDATION_POLICY_EDGE_NONPOSITIVE
```

The contradictory-economics line above records the source state at the instant of that probe. It is superseded by the Confidence V2 hardening in section 12.12; the other reproduced results remained open at that instant. Source inspection additionally proved the P0 cold-start candidate-discard cycle, absent durable unique-consumption ledger, four-boundary-token tensor-cache identity, pooled LONG/SHORT temperature, process-local lane state, incomplete cost provenance, optional checkpoint hash/nonreloadable behavior generation and fixed downstream coverage/confidence/edge gates. No runtime state was mutated. The resulting verdict is **TRAINER NOT READY**; the services and timers remain held.

### 12.12 Confidence V2 recomputed-economics supersession

Current source changed the calibration schema to `v2_profitability_confidence_calibration_v2` and the target semantics to `P_SELECTED_DIRECTIONAL_ACTION_RECOMPUTED_NET_PNL_AFTER_EXPLICIT_COSTS_GT_ZERO_V2`. It derives target truth only from `realized_gross_pnl_usd - fees_usd - slippage_usd + signed_funding_pnl_usd`, derives bps from positive close-specific entry notional, and treats claimed net/profit/outcome fields as consistency checks. V1 calibration states intentionally invalidate.

Exact focused commands and results were:

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_confidence_calibration.py v2/backend/tests/unit/services/native_trainer/test_confidence_proportional_calibration.py
```

Result: 12 passed in 0.19 seconds.

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_hybrid_confidence_profitability_semantics.py -k 'profitability_target or forged or notional or gross_pnl or cost_provenance or claimed_net_bps or signed_funding or ambiguous_cost'
```

Result: 15 passed, 13 deselected in 0.22 seconds.

```bash
.venv/bin/python -m py_compile v2/backend/app/services/native_trainer/hybrid_cuda_trainer/confidence.py v2/backend/tests/unit/services/native_trainer/test_confidence_calibration.py v2/backend/tests/unit/services/native_trainer/test_hybrid_confidence_profitability_semantics.py && .venv/bin/python -m ruff check v2/backend/app/services/native_trainer/hybrid_cuda_trainer/confidence.py v2/backend/tests/unit/services/native_trainer/test_confidence_calibration.py v2/backend/tests/unit/services/native_trainer/test_hybrid_confidence_profitability_semantics.py
```

Result: all checks passed.

The concurrent aggregate command was:

```bash
.venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_confidence_calibration.py v2/backend/tests/unit/services/native_trainer/test_confidence_proportional_calibration.py v2/backend/tests/unit/services/native_trainer/test_hybrid_confidence_profitability_semantics.py
```

Result: 3 failed, 36 passed, one warning in 11.23 seconds. The failures were:

```text
test_legacy_scalar_confidence_checkpoint_refuses_load_without_mutation
  KeyError: checkpoint_confidence_head_compatible
test_calibration_fingerprint_mismatch_restores_weights_but_stays_unfitted
  latest_checkpoint_loadable is False
test_calibration_missing_fingerprint_restores_weights_but_stays_unfitted
  latest_checkpoint_loadable is False
```

All three tests intentionally mutated an NPZ after its manifest was written. Concurrent checkpoint SHA enforcement rejected that mutation before the older confidence-specific assertion was reached. This is a cross-workstream integration result, not evidence that SHA rejection should be weakened; the tests/expectations require reconciliation after checkpoint source stabilizes.

After that initial handoff, source was extended so close outcomes, feedback enrichment and trainer loading preserve unit-explicit `realized_gross_pnl_usd`, `closed_entry_notional_usd`, `fees_usd`, `slippage_usd` and signed `funding_pnl_usd`; focused lifecycle proof passed. No held runtime has yet demonstrated nonzero eligible V2 rows or both-direction fit. This source hardening did not add a promotion hard gate. The trainer verdict and repair holds therefore remain unchanged.

### 12.13 Trainer handoff source supersession and effective-cycle blocker

Sections 12.11 and 12.12 are immutable chronology: their negative outputs describe the source at the instant of those probes. Later helper/source work now rejects or binds the former equal-clock, optional-checkpoint-hash, corrupt terminal/trajectory/reward, contradictory economics, four-token cache, external checkpoint path and unfitted point-metric promotion paths. The current low-level schemas are:

```text
v2_exact_adaptive_cost_provenance_v1
v2_exact_ppo_finalized_outcome_v1
v2_trainer_full_ordered_tensor_cache_digest_v1
v2_non_serving_candidate_progress_gate_v1
v2_checkpoint_bound_confidence_promotion_gate_v1
v2_exact_ppo_consumption_update_key_v1
v2_exact_ppo_training_partition_v1
v2_exact_ppo_consumption_ledger_v3
v2_hybrid_checkpoint_evidence_v1
```

The finalized outcome recomputes side/entry/exit/quantity gross and every entry/exit fee/slippage/funding component under exact paper versions, formula, rate scope, allocation and no-fallback provenance. Reward is exactly `realized_net_pnl_bps/100`. PPO requires terminal true and a nonnegative integer trajectory. The cache hashes every ordered row feature/mask/target/clock/trust material.

The SQLite ledger uses WAL/FULL, process ownership `boot-id:pid:start-ticks`, semantic update/partition hashes, atomic claims and an optimizer write-ahead fence. A fully verified checkpoint can reconcile the artifact→ledger crash window. A dead post-fence attempt with no provable child is consumed under `CRASH_AMBIGUOUS_OPTIMIZER_ATTEMPT_CONSUMED_FAIL_CLOSED`, not replayed. Checkpoint paths are confined to exact manager-owned `{checkpoint_id}.weights.npz`; manifests bind NPZ/parameter/evidence/calibration/lineage/parent/consumed-key state. These are tamper-evident source contracts, not authenticated runtime storage.

Confidence promotion now rederives global/LONG/SHORT same-row raw-versus-calibrated Brier/ECE plus paired Brier mean/standard error/one-SE upper bound and ECE leave-one-out/jackknife standard error/upper bound. Each uncertainty upper bound must be nonpositive. It uses no configured market row threshold; two rows per scope are the mathematical identifiability minimum. The gate is necessary and explicitly non-serving.

After that inspection, source integration moved again. `run_hybrid_trainer_cycle` now opens separate serving/candidate/rejected stores; reconciles every fully verified artifact before dead-claim recovery; removes consumed exact rows; selects a verified serving, non-serving candidate or fresh training parent; reaches a fixed-point exact claim plan; writes the optimizer fence; evaluates candidate, confidence and serving decisions; persists candidate/rejected/serving artifacts; records ledger disposition; and serves only a fully reverified prior or promoted serving checkpoint. Receipt decision time now uses microseconds. Exact receipts are immutable with `ex=None`, and `test_behavior_receipt_is_persisted_without_fixed_expiry` covers removal of the former seven-day expiry. No held service or timer was started, so this is source integration rather than trainer-health evidence.

Read-only cost-state inspection at approximately 08:32Z found the deployed BTCUSDT publication still on the pre-repair shape: `freshness_status=FRESH_ORDERBOOK` and round-trip cost `10.01953227`, but `available_at`, `expires_at`, adaptive freshness fields, order-book provenance and publication TTL were null; Redis TTL was 537 seconds. The publisher service had been running since 2026-07-17 22:40:05 EDT, before the source repair. Exact sampling must reject that row. A controlled cost-producer restart plus four distinct source clocks (three intervals) is required before exact-lane burn-in; no service restart occurred in this audit.

Source subsequently added and exact admission rederives `paper_cost_fee_schedule_evidence_v1` with `CONFIGURED_TAKER_FEE_BPS_PER_SIDE`, value/source and SHA-256 plus `paper_cost_notional_configuration_evidence_v1` with reference-notional value/source and SHA-256. This closes configured paper/shadow fee and notional identity. It does not prove the actual exchange account's fee tier, discounts or maker-versus-taker applicability; that is a live-transfer boundary, not a blocker to the configured paper exact lane.

Open paper/trainer release blockers after source integration are scarce/latest PPO validation-only supply, process-local lane carry, deployed cost-producer burn-in, static downstream publisher gates and a controlled cold-start/candidate/reject/crash/promote/restore run. The former 0.25-bps paper exit-slippage minimum is removed: observed half-spread is used exactly, while missing spread invokes the configured reserve, marks fallback and remains ineligible for exact PPO. Actual exchange-account fee authority remains separately required before any live transfer. Runtime remains PPO 0/0, held and non-A+.

### 12.14 Partial-close/restart reconstruction and persistence validation

The final source contract uses `PAPER_OPEN_POSITION_RECONSTRUCTION_V1` plus canonical SHA-256 over exact position/generation/version, aware ordered entry/open/reconstruction clocks, symbol/side, remaining quantity, average entry, ordered source fill IDs, realized PnL, incurred/remaining/allocated entry fee and slippage ledgers, materialized fallback rates/sources/status and OPEN_POSITION/paper-only safety. Valid snapshots seed state before fill replay and must reserialize to the same hash. Legacy partial, tampered, future-clock, incomplete-ledger, non-round-tripping or mixed complete/incomplete same-side basis fails closed.

A generation is suppressed only when explicit final-close plus pre-close=closed or remaining=0 proves full quantity consumption. Every historical netting fill requires a versioned hash receipt bound to close ID, generation ID, fill ID, side and `input=consumed+residual`. Accepted-fill disk compaction retains both evidence contracts; fallback entry costs materialize once and conserve their original rate across restarts.

Exact final commands were:

```bash
PYTHONDONTWRITEBYTECODE=1 CUDA_VISIBLE_DEVICES='' .venv/bin/python -m pytest -q v2/backend/tests/unit/services/paper_trade_management v2/backend/tests/unit/cli/test_v2_paper_partial_restart_state_persistence.py
```

Result: 509 passed in 1.51 seconds, exit 0. Pytest emitted the existing `asyncio_default_fixture_loop_scope` deprecation warning.

```bash
PYTHONDONTWRITEBYTECODE=1 CUDA_VISIBLE_DEVICES='' .venv/bin/python -m pytest -q v2/backend/tests/unit/services/paper_trade_management/test_partial_close_restart_reconstruction.py v2/backend/tests/unit/cli/test_v2_paper_partial_restart_state_persistence.py
```

Result: 16 passed in 0.28 seconds, exit 0, with the same warning.

```bash
PYTHONDONTWRITEBYTECODE=1 CUDA_VISIBLE_DEVICES='' .venv/bin/python -m pytest -q v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py -k 'compact_accepted_fill_state or accepted_fill_from_open_position'
```

Result: 4 passed, 534 deselected in 0.26 seconds, exit 0, with the same warning.

```bash
.venv/bin/python -m ruff check --ignore E501,UP017,UP038 v2/backend/app/services/paper_trade_management/position_state.py v2/backend/app/services/paper_trade_management/lifecycle.py v2/backend/tests/unit/services/paper_trade_management/test_partial_close_restart_reconstruction.py v2/backend/tests/unit/cli/test_v2_paper_partial_restart_state_persistence.py
```

Result: `All checks passed!`, exit 0.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m py_compile v2/backend/app/services/paper_trade_management/position_state.py v2/backend/app/services/paper_trade_management/lifecycle.py v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/tests/unit/services/paper_trade_management/test_partial_close_restart_reconstruction.py v2/backend/tests/unit/cli/test_v2_paper_partial_restart_state_persistence.py
```

Result: no output, exit 0.

The full CLI-inclusive Ruff inventory was also attempted:

```bash
.venv/bin/python -m ruff check --ignore E501,UP017,UP038 v2/backend/app/services/paper_trade_management/position_state.py v2/backend/app/services/paper_trade_management/lifecycle.py v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/tests/unit/services/paper_trade_management/test_partial_close_restart_reconstruction.py v2/backend/tests/unit/cli/test_v2_paper_partial_restart_state_persistence.py
```

Result: exit 1, `Found 112 errors.` The findings are the pre-existing CLI-wide I001/UP035/F401/S110/E722/F601 and related inventory; the scoped changed service/test files pass. No paper restart, migration or release was performed.

### 12.15 Durable behavior-receipt lifecycle, checkpoint retention and adaptive exit-cost supersession

Source now treats Redis as a receipt lookup/cache plane rather than the only retention authority. `durable_behavior_receipt_archive.py` defines blob schema `v2_durable_behavior_receipt_archive_v1`, lifecycle-event schema `v2_behavior_receipt_lifecycle_event_v1` and default root `.local_data/v2_native_trainer/durable_behavior_receipt_archive`. Receipt blobs and events are canonical-SHA content-addressed, create-or-identical, file/directory-fsynced and read back. A per-receipt `fcntl.flock` spans event read/check/write/readback; multiple stored events of the same type are corrupt/fail closed. The required lifecycle is `PUBLISHED → ENTRY_ACCEPTED → OUTCOME_FINALIZED → TRAINER_CONSUMED`.

Publisher archive+`PUBLISHED` success precedes the immutable no-expiry Redis receipt and exact route eligibility. Paper entry re-verifies the archive/published event, matches the actual configured fee-schedule SHA to the receipt and appends `ENTRY_ACCEPTED`. Feedback re-verifies archive/entry/fee identity, appends `OUTCOME_FINALIZED` and marks retention required. The final `TRAINER_CONSUMED` type exists and requires the exact PPO update key, but no trainer call appends it after the durable SQLite ledger disposition. Lifecycle retention therefore remains required. There is no behavior-archive garbage collector; physical blobs are never deleted at this source cut, avoiding premature deletion but leaving unbounded local-disk growth. The hashes are tamper-evident/self-authenticating, not keyed authentication or off-host backup proof.

Checkpoint retention separately emits `native_cuda_trainer_checkpoint_retention_manifest_v2`. It scans serving, non-serving-candidate and rejected-attempt stores; pins active serving, latest candidate, artifacts intersecting pending SQLite claims and SQLite/WAL/SHM; deletes only complete unpinned JSON/NPZ pairs; and pins every rejected artifact when claim state is unreadable. This protects reconciliation artifacts but does not bound the receipt archive.

Two other source supersessions are included in the same focused lane. `build_close_event` uses the observed exit half-spread exactly; the former 0.25-bps minimum is removed. Missing spread uses the configured reserve, marks fallback and remains ineligible for exact PPO economics. `parse_runtime_time` now rejects naive timestamps rather than assuming UTC.

The final five-file focused command was:

```bash
PYTHONDONTWRITEBYTECODE=1 CUDA_VISIBLE_DEVICES='' .venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_durable_behavior_receipt_archive.py v2/backend/tests/unit/services/native_trainer/test_on_policy_behavior_receipt.py v2/backend/tests/unit/services/native_trainer/test_persistent_cuda_trainer_runtime.py v2/backend/tests/unit/services/paper_trade_management/test_adaptive_cost_model.py v2/backend/tests/unit/services/paper_trade_management/test_round_trip_close_costs.py
```

Result after all retention/entry-validity and concurrent-event hardening: 98 passed, one `pynvml` deprecation warning in 3.13 seconds; measured wall time was about 4.1 seconds.

The archive race-focused command was:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_durable_behavior_receipt_archive.py
```

Result: 4 passed in 0.28 seconds.

Scoped quality command:

```bash
.venv/bin/python -m ruff check v2/backend/app/services/native_trainer/durable_behavior_receipt_archive.py v2/backend/tests/unit/services/native_trainer/test_durable_behavior_receipt_archive.py
```

Result: `All checks passed!`. `git diff --check` also returned no output/errors at that source cut. No service/timer was started, no Redis key was changed, and no archive migration, deletion or runtime burn-in occurred.

Six-file syntax validation was:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m py_compile v2/backend/app/services/native_trainer/durable_behavior_receipt_archive.py v2/backend/app/services/native_trainer/hybrid_cuda_trainer/publisher.py v2/backend/app/services/native_trainer/persistent_cuda_trainer_runtime.py v2/backend/app/services/paper_trade_management/adaptive_cost_model.py v2/backend/app/services/paper_trade_management/outcomes.py v2/backend/app/cli/v2_trade_management_paper_loop.py
```

Result: no output, exit 0.
