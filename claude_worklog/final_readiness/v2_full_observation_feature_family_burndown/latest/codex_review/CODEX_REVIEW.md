# Codex Review: V2 Full Observation Internal Feature-Family Burndown

Generated: `2026-05-17T20:04:29Z`

GO/NO-GO: `V2_FULL_OBSERVATION_FEATURE_FAMILY_BURNDOWN_CODEX_PASS_PARTIAL_PROGRESS`

## Decision

Codex passes the feature-family burndown at the partial-progress scope. Claude materially expanded the V2-native full observation builder using existing V2 runtime sources, while keeping the 1911-dim contract partial and keeping missing dimensions explicit.

This review does not approve full observation parity, policy architecture port implementation, checkpoint compatibility, production equivalence, live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, or legacy shutdown.

## Runtime Continuity

- 6h soak remains passed: `soak_6h_ready=true`.
- Current soak evidence: `1081.37` observed minutes, `all_v2_processes_uninterrupted=true`, `v2_namespaces_never_empty=true`.
- Continuous remediation governor: `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY`.
- V2/remediation processes: `12/12` running in the refreshed Codex 5m cycle.
- V2 Redis namespaces are non-empty: `v2:* = 36`, including market, features, prediction, trainer, orchestrator, paper, and risk namespaces.
- Comparator, legacy log observer, continuous remediation, frontend truth, and full-observation payloads are fresh.
- `live_gate=blocked_human_only`; `live_symbols=[]`.

## Builder Delta

Reviewed artifacts:

- `v2/backend/app/services/rl_core/full_observation_builder.py`
- `v2/backend/tests/integration/cli/test_v2_full_observation_feature_family_burndown.py`
- `claude_worklog/final_readiness/v2_full_observation_feature_family_burndown/latest/feature_family_burndown_status.json`
- `v2/frontend/public/v2_full_observation_feature_family_burndown/latest/operator_dashboard_payload.json`
- `v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json`

Generated full-observation dimensions increased from the Codex-reviewed baseline:

| Symbol | Baseline | Current | Delta |
| --- | ---: | ---: | ---: |
| `BTCUSDT` | `44` | `109` | `+65` |
| `ETHUSDT` | `44` | `109` | `+65` |
| `SOLUSDT` | `39` | `104` | `+65` |

The state remains `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`, with target dim `1911` and missing counts still visible.

## Source Scope

The builder consumes V2-native runtime sources only:

- `v2:features:latest:{symbol}:{timeframe}`
- `v2:market:prices:{symbol}`
- `v2:market:funding:{symbol}`
- `v2:market:open_interest:{symbol}`
- `v2:paper:*`
- `v2:risk:*`
- `v2:orchestrator:*`
- `v2:trainer:*`
- `v2:prediction:{symbol}:{timeframe}`

No legacy `features:*` keys are consumed as current truth. The builder adds no Redis writes.

## Feature Families

The subfamily layout now matches the legacy unified-feature family shape surface for the 137 named subfamily slots inside the 1430-dim unified slice. Current aggregate present counts:

- `binance_klines`: `60` present across 3 symbols, fully sourced from V2 market/features.
- `portfolio_state_unified`: `45` present across 3 symbols, fully sourced for the current 15-slot subfamily.
- `binance_orderbook`: `30` present across 3 symbols, partial.
- `technical_analysis`: `54` present across 3 symbols, partial.
- `coinank`: `30` present across 3 symbols, partial.
- `liquidations`: `3` present across 3 symbols, partial.
- `ccxt_ohlcv`: `0`, operator-decision-required.
- `token_metrics`: `0`, external-source-required.

The frontend displays aggregate present counts against per-symbol targets multiplied by symbol count, so the visible present/target counters are not overstated.

## No Fabrication

Codex verified:

- Missing fields remain `null`/`None` with explicit source labels.
- `zero_filled_field_count=0`.
- Unknown/trailing legacy V3 dimensions remain `MISSING_LEGACY_V3_EXTRA_NO_V2_SOURCE`.
- `token_metrics` remains `EXTERNAL_SOURCE_REQUIRED_NO_V2_NATIVE_TOKEN_METRICS`.
- `onchain_btc` and `onchain_eth` remain `ONCHAIN_FEATURE_SOURCE_MISSING`.
- `ccxt_ohlcv` remains `OPERATOR_DECISION_REQUIRED_SECONDARY_EXCHANGE_OHLCV`.
- `checkpoint_compatibility_claimed=false`.
- `policy_architecture_parity_claimed=false`.

No generated dimension is padded to fake 1911-dim completion.

## Policy And Checkpoint Scope

The policy architecture work remains a shape-contract packet only:

- `policy_port_implementation_claimed=false`
- `operator_decision_required_to_implement_port=true`

Checkpoint compatibility remains false. No checkpoint blob is tracked or staged, and no torch/pickle load path was introduced.

## Validation

- Focused tests: `36 passed` across feature-family burndown, full observation builder, missing-feature source map, and policy architecture shape contract tests.
- `py_compile`: PASS for active full-observation, missing-source, policy-shape, and CLI modules.
- Frontend `npm run typecheck`: PASS.
- Torch/pickle load scan: PASS, no active load/import matches.
- Exchange mutation scan: PASS, no matches.
- Old Redis write scan over builder/source-map/policy-shape path: PASS, no write calls.
- Approval scan over burndown artifacts/public payloads: PASS.
- Raw secret scan over burndown artifacts/public payloads: PASS.
- Git-tracked checkpoint blob scan: PASS, no tracked model blobs.
- `git diff --check`: PASS for reviewed files/artifacts.

## Safety State

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`

## Remaining Blockers

- Full 1911-dim observation parity is not complete.
- `binance_orderbook`, `technical_analysis`, `coinank`, `liquidations`, `portfolio_state`, and `position_context` remain partial.
- `token_metrics`, `onchain_btc`, and `onchain_eth` require external/operator decisions.
- `ccxt_ohlcv` remains operator-decision-required.
- Policy architecture port must not proceed as a parity claim until the observation contract is complete or the operator explicitly changes the scope.
- Checkpoint compatibility remains blocked.
- Legacy still owns production; shutdown remains blocked.

## Final Decision

`V2_FULL_OBSERVATION_FEATURE_FAMILY_BURNDOWN_CODEX_PASS_PARTIAL_PROGRESS`
