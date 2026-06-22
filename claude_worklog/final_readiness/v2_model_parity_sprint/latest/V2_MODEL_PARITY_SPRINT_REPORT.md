# V2 Post-6H Model Parity and Decision Equivalence Sprint Report

GO/NO-GO: `V2_MODEL_PARITY_SPRINT_READY_FOR_POLICY_ARCHITECTURE_PORT`

This packet does NOT approve live, canary, leverage/margin changes,
exchange mutation, legacy shutdown, Redis trim, paper-only shutdown
acceptance, or loading legacy pickle into the V2 process.

## LANE 0 — runtime preserved

- 15 V2/remediation processes running.
- `v2:*` keys = 36; soak `minutes_observed = 940.35`, `soak_6h_ready = true`,
  `all_v2_processes_uninterrupted = true`.
- `continuous_remediation: V2_CONTINUOUS_LEGACY_LOG_TO_REBUILD_REMEDIATION_READY`.
- `legacy_log_observer_running = true`.
- `live_gate = blocked_human_only`, `live_symbols = []`.

## LANE 1 — checkpoint candidate inventory (read-only, no deserialization)

[checkpoint_candidate_inventory.json](claude_worklog/final_readiness/v2_model_parity_sprint/latest/checkpoint_candidate_inventory.json)

- approved_local candidates: `0` (`.local_models/` absent).
- legacy reference candidates (cap=200/root): listed with sha256 of first
  64KiB, size, mtime, family hint, source classification.
- `UNSAFE_PICKLE_NO_LOAD` count: ≥12 (legacy `.pkl` files marked do-not-load).
- `no_blob_deserialized = true`, `no_torch_imported = true`,
  `no_legacy_filesystem_modified = true`, `no_pickle_loaded = true`.

## LANE 2 — legacy observation shape contract (static extraction)

[legacy_observation_shape_contract.json](claude_worklog/final_readiness/v2_model_parity_sprint/latest/legacy_observation_shape_contract.json) and
[v2_vs_legacy_observation_gap_matrix.json](claude_worklog/final_readiness/v2_model_parity_sprint/latest/v2_vs_legacy_observation_gap_matrix.json)

Legacy observation schemas (from
`v2/legacy_owned_runtime/rl/obs_schema.py`):

| Version | total_dim | Notes |
| ------- | --------: | ----- |
| V1      | 1053      | technical_indicators=50, ohlcv_multi_tf=600, orderbook_depth=100, volatility=50, momentum=50, volume_profile=50, portfolio_state=153 |
| V2      | 1061      | V1 + onchain_btc=4, onchain_eth=4 |
| V3      | 1911      | unified_features=1430, portfolio_state=401, onchain_btc=15, onchain_eth=15, position_context=50 |

Legacy action space:
- `action_space_size_expr = 3 ** len(SYMBOLS)`
- `action_space_size_resolved = 59049` (3^10 joint action)
- `per_symbol_actions = 3` (hold / long / short)

Legacy architecture (from `enhanced_architectures.py`,
`gpu_cnn_policy.py`, `moe_router.py`):
- LSTM ✓, Multi-head attention ✓, FFN ✓, Regime head ✓, MoE ✓, CNN ✓
- LSTM hidden default ≈ 512 (informational, default kwarg observed).

V2 vs legacy gap:
- `v2_native_compact_observation_dim = 26`
- `legacy_largest_observation_dim = 1911`
- `observation_dim_gap_legacy_minus_v2 = 1885`
- `observation_compatibility = INCOMPATIBLE_OBSERVATION_VECTOR_SHAPE_REQUIRES_PORT`
- `action_space_compatibility = INCOMPATIBLE_ACTION_SPACE_REQUIRES_PORT`

## LANE 3 — full observation builder scaffold

[full_observation_builder_status.json](claude_worklog/final_readiness/v2_model_parity_sprint/latest/full_observation_builder_status.json) (mirrored at
[v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json](v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json))

State: `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`.

- `compact_observation_v1`: kept as runtime input, `dim = 26`.
- `full_observation_v1.target_dim = 1911 (V3)`.
- Missing observation categories (no V2 native source today):
  `unified_features` (1430 dims), `onchain_btc` (15), `onchain_eth` (15).
- Partial categories (V2 native data exists but not yet shaped):
  `portfolio_state`, `position_context`.
- `checkpoint_compatibility_claimed = false`.
- `operator_artifact_or_new_builder_required = true`.

Source: [v2/backend/app/services/rl_core/full_observation_builder.py](v2/backend/app/services/rl_core/full_observation_builder.py)

## LANE 4 — policy architecture compatibility

[policy_architecture_compatibility.json](claude_worklog/final_readiness/v2_model_parity_sprint/latest/policy_architecture_compatibility.json)

- `classifications`: `["REQUIRES_OBSERVATION_VECTOR_EXPANSION", "REQUIRES_V2_POLICY_ARCHITECTURE_PORT"]`
- `overall_classification`: `REQUIRES_V2_POLICY_ARCHITECTURE_PORT`
- V2 facts: obs_dim=26, hidden_dim=16, action_count=5, MLP only, no LSTM/
  attention/MoE/CNN, deterministic-init.
- Legacy facts: LSTM + attention + MoE + CNN over 1911-dim obs, 59049-action
  joint action space.

Narrow remediation tasks created (pending operator decision):
- [claude_fix_v2_gap_policy_architecture_shape_contract.json](claude_worklog/agent_supervisor/tasks/claude_fix_v2_gap_policy_architecture_shape_contract.json) ⇄ [codex_review_fix_v2_gap_policy_architecture_shape_contract.json](claude_worklog/agent_supervisor/tasks/codex_review_fix_v2_gap_policy_architecture_shape_contract.json)
- [claude_fix_v2_gap_full_observation_vector_builder.json](claude_worklog/agent_supervisor/tasks/claude_fix_v2_gap_full_observation_vector_builder.json) ⇄ [codex_review_fix_v2_gap_full_observation_vector_builder.json](claude_worklog/agent_supervisor/tasks/codex_review_fix_v2_gap_full_observation_vector_builder.json)

Both tasks are `OPERATOR_DECISION_REQUIRED` / `auto_apply_allowed_by_this_loop = false`.

## LANE 5 — decision-match shadow metrics

[model_decision_match_shadow_metrics.json](claude_worklog/final_readiness/v2_model_parity_sprint/latest/model_decision_match_shadow_metrics.json)

Latest cycle (against fresh comparator v3 schema):
- `symbols_total = 3`
- `action_match_count = 0`, `action_match_rate = 0.0`
- `v2_hold_due_checkpoint_count = 3`
- `v2_hold_due_strict_gate_count = 1` (SOLUSDT)
- `no_action_safe_block_count = 4`
- `no_invented_outcomes = true`, `paper_edge_claimed = false`

`next_required_by_symbol` (all): `CHECKPOINT_ARTIFACT_REQUIRED_OR_FULL_OBSERVATION_BUILDER_OR_POLICY_PORT`.

## LANE 6 — continuous remediation integration

New high-level model-parity states are surfaced via the narrow task pair
files (LANE 4). The continuous-remediation gap-matrix loop continues to
preserve the checkpoint-weight blocker as
`BLOCKS_PRODUCTION_EQUIVALENCE` / `OPERATOR_DECISION_REQUIRED` and the
paper-fill passthrough as `NO_ACTION_REQUIRED_SAFE_BLOCK`. No duplicate
checkpoint tasks created (`remediation_tasks_created_count = 0`,
`duplicate_task_suppression_count = 3` last cycle).

States now visible to operator review:
- `CHECKPOINT_ARTIFACT_ABSENT` (already represented by existing checkpoint blocker)
- `LEGACY_OBSERVATION_VECTOR_MISMATCH` (this packet)
- `V2_POLICY_ARCHITECTURE_MISMATCH` (this packet)
- `FULL_OBSERVATION_BUILDER_PARTIAL` (this packet)
- `MODEL_PARITY_OPERATOR_ARTIFACT_REQUIRED` (this packet)
- `NO_ACTION_REQUIRED_SAFE_BLOCK` (already supported)

## LANE 7 — frontend truth (Monitor Center)

8 new cards added to Monitor Center reading
`/v2_model_parity_sprint/latest/operator_dashboard_payload.json`:
- Sprint GO/NO-GO
- Legacy obs shape per version + action-space size
- Observation gap (26 → 1911, gap=1885)
- Full observation builder state + missing categories
- Policy architecture compatibility
- Action match shadow (with v2_hold_due_checkpoint / strict_gate)
- Approved checkpoint candidates count
- Sprint safety (live_gate + approves_*)

Mismatches are surfaced, not hidden. Deterministic-init policy is NOT
labeled "equivalent" anywhere.

## LANE 8 — final state

```
go_no_go             = V2_MODEL_PARITY_SPRINT_READY_FOR_POLICY_ARCHITECTURE_PORT
obs_compat           = INCOMPATIBLE_OBSERVATION_VECTOR_SHAPE_REQUIRES_PORT
action_compat        = INCOMPATIBLE_ACTION_SPACE_REQUIRES_PORT
full_obs_state       = FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS
policy_overall       = REQUIRES_V2_POLICY_ARCHITECTURE_PORT
action_match_rate    = 0.0
checkpoint candidates= 0 approved local / many legacy reference
next gate            = operator must choose between:
                       OPTION_A: train V2-native compact (26-dim, 5-action) checkpoint
                       OPTION_B: implement full observation expansion + policy port (multi-month port)
```

## Safety invariants (raw)

- `live_gate = blocked_human_only`
- `live_symbols = []`
- `approves_live = false`
- `approves_canary = false`
- `approves_legacy_shutdown = false`
- `approves_redis_trim = false`
- no torch import in any new module
- no pickle deserialization
- no legacy filesystem modification
- no checkpoint blob committed to Git (`.local_models/` is gitignored)
- soak runtime continues uninterrupted (only the comparator daemon was
  refreshed; it is NOT in the soak observer's V2_PROCESSES list)
- legacy still running and untouched

## What this packet does NOT claim or do

- Does not claim production equivalence.
- Does not approve operator-required artifact loading.
- Does not load any pickle or safetensors into V2.
- Does not implement the full observation builder beyond the partial
  scaffold and gap manifest.
- Does not implement the policy architecture port; it documents the
  contract and creates the operator-decision tasks only.
- Does not approve live, canary, legacy shutdown, Redis trim, or paper-
  only shutdown acceptance.
- Does not create approval tokens.
- Does not modify legacy.
