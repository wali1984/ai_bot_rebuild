# Codex Review: V2 Post-6H Model Parity And Decision Equivalence Sprint

Generated: `2026-05-17T17:59:13Z`

GO/NO-GO: `V2_MODEL_PARITY_SPRINT_CODEX_PASS_OBSERVATION_BUILDER_NEXT`

## Decision

Codex passes the model-parity sprint as an honest production-equivalence blocker packet. It does not pass model parity, checkpoint parity, production equivalence, live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, or legacy shutdown.

Operator chose Option B, so deterministic-init / no-trained-checkpoint limitation is not accepted. The next actionable implementation gate is the full observation-vector builder: V2 must close the 26-dim to 1911-dim observation gap before any legacy-compatible policy architecture or checkpoint shape parity can be meaningfully reviewed.

## Runtime Continuity

- Continuous remediation governor: `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY`.
- Runtime soak remains passed: `soak_6h_ready=true`.
- Current soak evidence: `956.0` observed minutes.
- V2/remediation processes: `12/12` running in the latest Codex governor cycle.
- V2 Redis namespaces remain non-empty.
- Legacy log observer is fresh.
- Comparator is fresh.
- Frontend truth is fresh.
- `live_gate=blocked_human_only`.
- `live_symbols=[]`.

Existing monitors/runtimes were not stopped or paused by this review.

## Checkpoint Safety

Checkpoint lane remains blocked/operator-required, not parity:

- approved local candidates: `0`
- `.local_models/`: absent
- approved local checkpoint extensions: all `0`
- legacy reference inventory: `.pt=15275`, `.pkl=62`
- unsafe pickle references are classified `UNSAFE_PICKLE_NO_LOAD`
- no raw checkpoint blob is staged or tracked in Git
- no checkpoint blob was deserialized
- no pickle was loaded
- no torch import was performed by the model-parity modules
- no checkpoint parity is claimed

This satisfies the checkpoint safety review because the state is honest: `CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED` remains visible.

## Observation Shape

Legacy observation contract is extracted from V2-owned legacy mirrors, not from the live legacy root:

- `v2/legacy_owned_runtime/rl/obs_schema.py`
- `v2/legacy_owned_runtime/rl/environment.py`
- `v2/legacy_owned_runtime/rl/enhanced_architectures.py`
- `v2/legacy_owned_runtime/rl/moe_router.py`
- `v2/legacy_owned_runtime/rl/gpu_cnn_policy.py`

Observed legacy dimensions:

- V1: `1053`
- V2: `1061`
- V3: `1911`
- legacy action space: `59049` (`3 ** 10`)

Current V2 runtime observation:

- compact observation dim: `26`
- action count: `5`
- compatibility: `INCOMPATIBLE_OBSERVATION_VECTOR_SHAPE_REQUIRES_PORT`
- observation dim gap: `1885`
- action compatibility: `INCOMPATIBLE_ACTION_SPACE_REQUIRES_PORT`

Full observation builder status is honest:

- state: `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`
- target schema: `V3`
- target dim: `1911`
- missing categories: `unified_features`, `onchain_btc`, `onchain_eth`
- partial categories: `portfolio_state`, `position_context`
- `checkpoint_compatibility_claimed=false`

No fake full observation parity is claimed.

## Policy Architecture

Legacy architecture facts are mapped:

- LSTM: present
- multi-head attention: present
- MoE: present
- CNN: present
- regime head: present
- observation dim: up to `1911`
- action space: `59049`

Current V2 policy facts are mapped:

- compact MLP
- obs dim: `26`
- hidden dim: `16`
- action count: `5`
- deterministic-init: `true`
- LSTM/attention/MoE/CNN/regime head: absent

Policy classification is honest:

- `REQUIRES_OBSERVATION_VECTOR_EXPANSION`
- `REQUIRES_V2_POLICY_ARCHITECTURE_PORT`
- overall: `REQUIRES_V2_POLICY_ARCHITECTURE_PORT`

No fake architecture compatibility is claimed.

## Decision Match

Current comparator state:

- schema: `v2_production_equivalence_comparison_v3`
- `no_invented_outcomes=true`
- `primary_mismatch_source_when_unmatched=CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED`
- `all_mismatches_attributable_to_checkpoint_blocker=true`
- `deterministic_init_policy_active=true`
- `strict_paper_gate_active=true`
- `positive_edge_claimed=false`

Decision-match shadow metrics:

- symbols: `3`
- action match count: `0`
- action match rate: `0.0`
- V2 hold due checkpoint count: `3`
- V2 hold due strict gate count: `1`
- no-action safe block count: `4`

Mismatches remain visible. The deterministic-init/checkpoint-missing cause remains visible. The SOLUSDT strict paper-fill gate block remains visible. No positive paper edge is claimed.

## Continuous Remediation And Task Scope

No duplicate checkpoint task was created in this sprint. Existing checkpoint task pair remains:

- `claude_fix_v2_gap_trainer_missing_checkpoint_weight_shape_contract.json`
- `codex_review_fix_v2_gap_trainer_missing_checkpoint_weight_shape_contract.json`

New tasks are narrow and operator-decision-gated:

- `claude_fix_v2_gap_full_observation_vector_builder.json`
- `codex_review_fix_v2_gap_full_observation_vector_builder.json`
- `claude_fix_v2_gap_policy_architecture_shape_contract.json`
- `codex_review_fix_v2_gap_policy_architecture_shape_contract.json`

The task files prohibit legacy mutation, legacy stop/restart, old Redis writes, exchange mutation, live enablement, approval-token creation, legacy monitor execution, and checkpoint blob commits. `auto_apply_allowed_by_this_loop=false` for the new implementation tasks.

No broad audit loop was created.

## Frontend Truth

Public model-parity payload exists at:

- `v2/frontend/public/v2_model_parity_sprint/latest/operator_dashboard_payload.json`

It shows:

- 6h soak preserved
- checkpoint candidates `0`
- checkpoint remains operator-required
- observation gap `26 -> 1911`
- full observation builder partial state
- policy architecture mismatch
- action match rate `0.0`
- live/shutdown approvals false

Monitor Center is wired to the model-parity payload and surfaces the checkpoint, observation, policy, decision-match, and safety cards.

## Validation

- JSON validation for model-parity artifacts: PASS.
- Focused tests: `8 passed` in `test_v2_full_observation_builder.py`.
- `py_compile` for model-parity modules and CLI: PASS.
- Torch/pickle load scan over model-parity modules: PASS.
- Exchange mutation scan over model-parity/runtime reviewed files: PASS.
- Old Redis write scan: model-parity modules add none; active V2 runtime writes remain guarded to `v2:` namespaces.
- Approval scan: PASS, no live/canary/shutdown/Redis-trim approval drift.
- Raw secret scan over model-parity artifacts: PASS.

## Safety State

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`

## Required Next Work

Proceed with the narrow full observation-vector builder lane first:

1. Implement V2-native sources for `unified_features`, `onchain_btc`, and `onchain_eth`.
2. Extend `portfolio_state` and `position_context` from V2 paper/runtime state.
3. Preserve missing/stale flags and do not fabricate dimensions.
4. Only after the 1911-dim contract is buildable should the policy architecture port be reviewed as a parity candidate.

Checkpoint artifact review remains a separate operator-required path.

## Final Decision

`V2_MODEL_PARITY_SPRINT_CODEX_PASS_OBSERVATION_BUILDER_NEXT`
