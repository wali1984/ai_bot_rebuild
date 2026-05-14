# v2_config_admin_manager Legacy Baseline Analysis

generated_at: 2026-05-14
live_gate: blocked_human_only

## Legacy Source Paths

- `v2/legacy_preserved/startup_baseline/config.py`
- `v2/legacy_preserved/startup_baseline/scripts/start_all_services_production.sh`
- `v2/legacy_preserved/startup_baseline/scripts/stop_all_services_production.sh`
- `v2/legacy_preserved/startup_baseline/trading/trader.py`
- `v2/legacy_preserved/startup_baseline/rl/hybrid_trainer.py`
- `claude_worklog/final_readiness/legacy_startup_baseline_v2_migration/latest/legacy_startup_baseline_matrix.json`

## Legacy Responsibilities Preserved

| Legacy behavior | V2 mapping |
|---|---|
| config values are spread across `config.py`, env, startup flags, and scripts | `ConfigSetting` records expose effective value, staged value, source, validation, rollback, and approval requirement |
| startup flags influence trainer/trader/runtime behavior | V2 config/admin status publishes safe and dangerous runtime records without executing startup scripts |
| risky settings can enable live, change leverage, change margin, disable stops, or alter limits | dangerous setting keys are always pending human approval and never self-approved |
| secrets may exist in env/private config in legacy | public payload redacts sensitive setting values |

## Legacy Inputs

- config module values
- startup command flags
- env-provided secrets and runtime toggles
- trader and trainer safety settings

## V2 Inputs

- optional staged-change JSON
- V2 Symbol Universe service or public payload
- fail-closed default config records

## V2 Outputs

- `v2/frontend/public/operator_runtime/v2_config_admin_manager/latest/v2_config_admin_manager_status.json`
- `v2/runtime/v2_config_admin_manager/latest/v2_config_admin_manager_status.json`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_config_admin_manager_status.json`
- API module `v2/backend/app/api/v1/config_admin.py`

## Legacy Redis Keys

No old Redis keys are read or written by the V2 config/admin manager.

## Config Dependencies

- live gate must remain `blocked_human_only`
- final approval token must remain absent
- dangerous settings require explicit human approval
- secrets are never written to public payloads
- Symbol Universe scope must preserve canonical legacy 25 separately from discovered/training/paper/live sets

## Edge Cases

- dangerous setting staged without approval: stays staged, effective value unchanged
- margin mode set to anything except isolated-only: rejected
- paper-to-live switch set away from blocked state: rejected
- leverage/limit numeric value invalid: rejected
- sensitive setting appears in public payload: redacted
- public Symbol Universe payload mismatch: ignored for canonical legacy 25 and surfaced as evidence

## Intentional Changes

- no approval token creation
- no live gate unlock
- no exchange action
- no leverage or margin mutation
- no old Redis dependency
- no secret emission

## Tests

- `test_non_dangerous_settings_crud_works`
- `test_dangerous_settings_require_human_approval_token`
- `test_approval_token_for_gate_leverage_or_margin_is_never_self_creatable`
- `test_staged_value_distinct_from_effective_value_and_rollback_recorded`
- `test_secrets_not_written_to_payload_invariant`
- `test_no_old_redis_write_contract`
- `test_symbol_universe_contract_required`
- `test_public_symbol_payload_cannot_override_canonical_legacy_25`

Result: config/admin manager implemented as paper/shadow support infrastructure only.
