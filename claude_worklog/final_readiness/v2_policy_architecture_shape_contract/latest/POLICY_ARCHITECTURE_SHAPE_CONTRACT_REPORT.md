# V2 Policy Architecture Shape Contract Prep Report

GO/NO-GO: `V2_POLICY_ARCHITECTURE_SHAPE_CONTRACT_PREP_READY`

This packet is **prep only**. It does NOT implement the policy port.
It does NOT claim port complete, checkpoint compatibility, model parity,
or production equivalence. It does NOT load any torch/pickle blob.
It does NOT modify legacy. It does NOT approve live, canary,
leverage/margin, exchange mutation, legacy shutdown, Redis trim, or
paper-only shutdown acceptance.

## Purpose

Capture the exact legacy policy-architecture contract from the V2-owned
legacy mirror (`v2/legacy_owned_runtime/rl/`) so the future port lane
has a stable, auditable target. The port itself stays operator-decision-
gated and is conditioned on the full observation builder being Codex-
reviewed first.

## Live extracted contract

### Input observation

- `target_dim = 1911` (V3 schema)
- Slices: `unified_features=1430`, `portfolio_state=401`,
  `onchain_btc=15`, `onchain_eth=15`, `position_context=50`

### Action space

- `joint_action_count = 59049` (legacy `3 ** len(SYMBOLS) = 3^10`)
- `per_symbol_actions = 3`
- `per_symbol_action_labels_hint = ["hold", "long", "short"]`
- `joint_action_decomposition = "joint_action_id = sum(action_for_symbol[i] * (3 ** i) for i in range(N))"`
- `n_symbols_expr = "len(SYMBOLS)"` (resolved to 10 in legacy environment)

### Architecture components present (in legacy mirror)

- LSTM: **True** (`enhanced_architectures.py` — `RecurrentFeatureExtractor`)
- Multi-head attention: **True**
- Feed-forward network + LayerNorm: **True**
- Regime head: **True** (4-class softmax over market regimes)
- Value head: **True**
- Policy head: **True** (`ActorCriticPolicy` discriminator)
- Expected-move head: **False** (legacy uses regime-driven heads; V2's
  separate `expected_move_head` is a V2-native paper-only addition that
  the future port must keep distinct).
- MoE router: **True** (`moe_router.py`)
- CNN: **True** (`gpu_cnn_policy.py` — Conv1d/Conv2d paths)

### Architecture defaults observed

- `lstm_hidden_size_default = 512`
- `lstm_num_layers_default` and `features_dim_default` carried verbatim
  from the legacy module defaults (see `policy_architecture_shape_contract.json`).
- `regime_head_class_count = 4`
- `uses_ActorCriticPolicy = True`

### V2 trainer-output contract (must be preserved by the future port)

The V2-native trainer output module emits the following P0.2F-relevant
fields. Any future V2 policy port must continue to emit them so the
strict paper-fill gate and downstream comparator passthrough remain
intact:

`paper_fill_allowed`, `paper_fill_gate_status`,
`paper_fill_gate_block_reasons`, `selected_action`,
`selected_action_index`, `policy_action_probabilities`,
`expected_move_bps`, `expected_move_after_cost_bps`,
`confidence_raw`, `confidence_calibrated`,
`hedge_action_classification`, `feature_freshness_state`,
`trainer_source`, `prediction_id`, `feature_snapshot_id`,
`checkpoint_id`, `checkpoint_blocker`, `generated_utc`,
`live_gate`, `live_symbols`.

## Safety invariants (raw)

- `live_gate = blocked_human_only`
- `live_symbols = []`
- `approves_live = false`
- `approves_canary = false`
- `approves_legacy_shutdown = false`
- `approves_redis_trim = false`
- `policy_port_implementation_claimed = false`
- `checkpoint_compatibility_claimed = false`
- `operator_decision_required_to_implement_port = true`
- no torch import; no pickle load; no legacy filesystem modification

## Next required step

> Codex review of the full observation builder must pass first; only
> then is the policy architecture port a parity candidate.

Until the full observation builder is `COMPLETE` (all 1911 dims sourced
without zero-fill), the policy port lane stays in prep state. This
report is the **stable target contract** the port will be measured
against, not a port implementation.

## What this packet does NOT do

- Does not implement the LSTM / attention / MoE / CNN policy port.
- Does not modify the current V2 deterministic-init compact 26-dim policy.
- Does not load any legacy `.pt` / `.pkl` / `.ckpt`.
- Does not approve any operator-required artifact adoption.
- Does not claim parity, equivalence, or readiness for shutdown.
- Does not approve live, canary, legacy shutdown, Redis trim, or paper-
  only shutdown acceptance.
- Does not modify legacy at `/home/wali/Desktop/AI BOT`.

## Outputs

- [GO_NO_GO.md](claude_worklog/final_readiness/v2_policy_architecture_shape_contract/latest/GO_NO_GO.md)
- [policy_architecture_shape_contract.json](claude_worklog/final_readiness/v2_policy_architecture_shape_contract/latest/policy_architecture_shape_contract.json)
- [operator_dashboard_payload.json](v2/frontend/public/v2_policy_architecture_shape_contract/latest/operator_dashboard_payload.json)
