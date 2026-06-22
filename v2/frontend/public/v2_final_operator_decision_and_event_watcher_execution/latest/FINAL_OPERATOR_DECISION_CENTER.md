# Final Operator Decision Center

This surface records required decisions only. It does not approve live, canary, legacy shutdown, or Redis trim.

Pending operator decisions: 6

## full_observation_builder.operator_decision_families

Decision: paper-edge threshold and unified-feature acceptance

Current status: PENDING_OPERATOR_DECISION

Why it blocks shutdown/live: Production equivalence, shutdown, or live gate remains blocked until operator decision is explicit.

Recommended conservative default: option_C_defer_and_keep_legacy_running

operator_accepted=false
operator_selected_option=null

## checkpoint_promotion

Decision: checkpoint/model limitation

Current status: PENDING_OPERATOR_DECISION

Why it blocks shutdown/live: Production equivalence, shutdown, or live gate remains blocked until operator decision is explicit.

Recommended conservative default: option_C_defer_and_keep_legacy_running

operator_accepted=false
operator_selected_option=null

## legacy_shutdown.legacy_runtime_owner

Decision: legacy runtime stop acceptance

Current status: PENDING_OPERATOR_DECISION

Why it blocks shutdown/live: Production equivalence, shutdown, or live gate remains blocked until operator decision is explicit.

Recommended conservative default: option_C_defer_and_keep_legacy_running

operator_accepted=false
operator_selected_option=null

## legacy_shutdown.legacy_redis_keys_active

Decision: legacy Redis trim / retention decision

Current status: PENDING_OPERATOR_DECISION

Why it blocks shutdown/live: Production equivalence, shutdown, or live gate remains blocked until operator decision is explicit.

Recommended conservative default: option_C_defer_and_keep_legacy_running

operator_accepted=false
operator_selected_option=null

## risk_caps_canary_hard_gates_unset

Decision: risk/capital caps

Current status: PENDING_OPERATOR_DECISION

Why it blocks shutdown/live: Production equivalence, shutdown, or live gate remains blocked until operator decision is explicit.

Recommended conservative default: option_C_defer_and_keep_legacy_running

operator_accepted=false
operator_selected_option=null

## capital_recovery_gate_unset

Decision: capital recovery threshold / risk guard acceptance

Current status: PENDING_OPERATOR_DECISION

Why it blocks shutdown/live: Production equivalence, shutdown, or live gate remains blocked until operator decision is explicit.

Recommended conservative default: option_C_defer_and_keep_legacy_running

operator_accepted=false
operator_selected_option=null
