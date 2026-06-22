# V2 Final Operator Decision Packet for Paper-Only Shutdown

This packet does not approve live, canary, legacy shutdown, or Redis trim.

Operator-required blocker count: 6

## full_observation_builder.operator_decision_families

Decision required: Operator must decide unified-feature inclusion for: unified_feature_family.ccxt_ohlcv

Conservative default: defer and keep legacy running.

operator_accepted=false

## checkpoint_promotion

Decision required: Operator must provide or approve a checkpoint blob under the protected runtime policy. Claude/Codex must not deserialize, mutate, or promote checkpoints autonomously.

Conservative default: defer and keep legacy running.

operator_accepted=false

## legacy_shutdown.legacy_runtime_owner

Decision required: Operator must explicitly approve legacy production runtime stop. CLAUDE.md forbids Claude/Codex from stopping legacy.

Conservative default: defer and keep legacy running.

operator_accepted=false

## legacy_shutdown.legacy_redis_keys_active

Decision required: Operator must approve Redis trim (operator Redis-trim approval) before legacy production Redis keys can be removed. CLAUDE.md forbids Claude/Codex from writing old Redis.

Conservative default: defer and keep legacy running.

operator_accepted=false

## risk_caps_canary_hard_gates_unset

Decision required: Operator must set/confirm risk caps and canary hard gates before live can be considered. Does not block paper-only V2.

Conservative default: defer and keep legacy running.

operator_accepted=false

## capital_recovery_gate_unset

Decision required: Operator must set/confirm capital recovery thresholds before live capital deployment. Does not block paper-only V2.

Conservative default: defer and keep legacy running.

operator_accepted=false
