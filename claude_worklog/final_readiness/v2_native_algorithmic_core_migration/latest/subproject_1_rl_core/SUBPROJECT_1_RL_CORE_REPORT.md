# Subproject 1 (RL Core) — Report

Generated: `2026-05-15`
Subproject: `v2_native_algorithmic_core_migration/subproject_1_rl_core`
Scope: `PAPER_ONLY`
Live gate: `blocked_human_only`
Live symbols: `[]`
Migration contract: `claude_worklog/final_readiness/permanent_migration_runtime/latest/MIGRATION_COMPLETION_CONTRACT.md`

## Outcome summary

This subproject delivers V2-native, paper-only re-implementations of the small
subset of the legacy RL core that can be ported faithfully:

1. A declarative V2 observation field descriptor (`observation_schema.py`)
   with ~30 named fields, dtypes, ranges, freshness flags, and a legacy slice
   pointer. The legacy `rl/obs_schema.py` SHA256 is cited inline.
2. A pure CPU constrained reward (`reward.py`) implementing realized PnL
   credit, fee penalty (bps of notional), slippage penalty, fee-ratio step
   penalty, drawdown Lagrangian-style penalty, no-trade-correct credit, and a
   hard reward clamp. The three legacy reward files' SHA256 values are cited
   in the module docstring.
3. A legacy checkpoint filename parser (`checkpoint_metadata.py`) that
   converts known patterns (e.g. `legacy_live_checkpoint_<unix_ts>[_<version>]`)
   into a `CheckpointMetadata` dataclass without loading PyTorch state.
4. A pure temperature-scaling adapter (`service.RLCoreService.calibrate_confidence`
   and module-level `calibrate_confidence`) that applies `logit / T` then a
   numerically-stable sigmoid, with explicit identity fallback when the
   calibration flag is off or temperature is invalid.

The CLI worker `v2/backend/app/cli/v2_rl_core_worker.py` emits the canonical
status payload to
`v2/frontend/public/operator_runtime/v2_rl_core/latest/v2_rl_core_status.json`.

## Test result

Pytest invocation against `v2/backend/tests/integration/cli/test_v2_rl_core_worker.py`
under the V2 venv reports 15 passed in 0.11s, 0 failed.

Tests included:

- `test_observation_schema_has_expected_fields`
- `test_reward_components_drawdown_penalty_negative`
- `test_reward_fee_ratio_shaping_reduces_score_when_fee_high`
- `test_reward_no_trade_correct_credit_positive`
- `test_reward_total_is_clamped_to_safe_range`
- `test_checkpoint_filename_legacy_pattern_parses`
- `test_checkpoint_filename_invalid_returns_none`
- `test_calibrated_confidence_temperature_one_is_identity`
- `test_calibrated_confidence_temperature_higher_is_softer`
- `test_status_payload_carries_safety_invariants`
- `test_status_payload_lists_components_missing`
- `test_cli_dry_run_prints_payload`
- `test_cli_write_evidence_emits_file`
- `test_cli_rejects_mutually_exclusive_flags`
- `test_cli_observation_status_via_service`

No network IO, no Redis import, no torch import, no exchange SDK import.

## Honest migration classification

Under the migration completion contract, this subproject is classified
`PARTIALLY_MIGRATED`. The emitted `go_no_go` label is:

```
SUBPROJECT_1_RL_CORE_PARTIALLY_MIGRATED_PAPER_ONLY
```

- The policy network (PPO+MASA) is `MISSING_IN_V2`.
- The Gymnasium env step/reset/reward loop is `MISSING_IN_V2`.
- The GPU training loop is `MISSING_IN_V2`.
- The unified feature builder tensor assembly is owned by Subproject 2 and is
  not part of this delivery.

## What is NOT done in this subproject

- No PyTorch model is imported, loaded, or evaluated. Weight loading is
  intentionally absent. `checkpoint_metadata.py` is filename-only.
- No training loop is implemented. The reward functions score paper outcomes
  but do not feed any optimizer.
- No Redis keys are read or written. Legacy keys
  (`rl:config:features`, `rl:calibration:temperature`,
  `rl:calibration:comparisons`) are documented as informational only.
- No exchange SDK is imported. No exchange-mutation paths
  (order placement, order cancellation, order modification, leverage change,
  margin-mode change) exist in this code.
- No live symbols are added. No live gate is flipped. The status payload
  hard-codes `live_gate=blocked_human_only`, `live_symbols=[]`,
  `approves_live=False`, `approves_canary=False`,
  `approves_legacy_shutdown=False`. The CLI offers
  `--require-paper-only` defense-in-depth assertions that exit non-zero if
  invariants drift.

## Files owned by this subproject

- `v2/backend/app/services/rl_core/__init__.py`
- `v2/backend/app/services/rl_core/service.py`
- `v2/backend/app/services/rl_core/observation_schema.py`
- `v2/backend/app/services/rl_core/reward.py`
- `v2/backend/app/services/rl_core/checkpoint_metadata.py`
- `v2/backend/app/cli/v2_rl_core_worker.py`
- `v2/backend/tests/integration/cli/test_v2_rl_core_worker.py`
- `v2/frontend/public/operator_runtime/v2_rl_core/latest/v2_rl_core_status.json`
- `claude_worklog/final_readiness/v2_native_algorithmic_core_migration/latest/subproject_1_rl_core/LEGACY_BASELINE_ANALYSIS.md`
- `claude_worklog/final_readiness/v2_native_algorithmic_core_migration/latest/subproject_1_rl_core/legacy_behavior_mapping.json`
- `claude_worklog/final_readiness/v2_native_algorithmic_core_migration/latest/subproject_1_rl_core/SUBPROJECT_1_RL_CORE_REPORT.md`
- `claude_worklog/final_readiness/v2_native_algorithmic_core_migration/latest/subproject_1_rl_core/subproject_1_rl_core_status.json`

## Live readiness

Live trading remains `blocked_human_only`. This subproject is paper-only and
does not approve any live transition. The next gates required before
classification can advance toward `MIGRATED_CODEX_PASS` are:

- A closed dependency graph for the V2 RL core modules.
- A Codex PASS review pinned in
  `claude_worklog/final_readiness/v2_native_algorithmic_core_migration/latest/codex_review/`.
- Reconciliation of `MISSING_IN_V2` items with the parallel subprojects
  (Subproject 2 feature intelligence, etc.) and the operator-decision-gated
  question of whether V2 will ever host PPO/MASA policy execution natively.
