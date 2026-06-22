# Codex Review: V2 Full Observation Vector Builder P0

Generated: `2026-05-17T19:41:06Z`

GO/NO-GO: `V2_FULL_OBSERVATION_BUILDER_CODEX_PASS_PARTIAL_MISSING_FEATURE_BURNDOWN`

## Decision

Codex passes the full observation-vector builder at the partial missing-feature burndown scope. The builder honestly preserves the current 26-dim compact runtime observation and builds a separate 1911-slot legacy V3 target surface with explicit missing/source accounting.

This is not full observation parity. It does not approve policy architecture parity, checkpoint compatibility, production equivalence, live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, or legacy shutdown.

## Runtime Continuity

- 6h soak remains passed: `soak_6h_ready=true`.
- Current soak evidence: `1056.3` observed minutes, `all_v2_processes_uninterrupted=true`, `v2_namespaces_never_empty=true`.
- Continuous remediation governor: `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY`.
- V2/remediation processes: `12/12` running in the refreshed Codex 5m cycle.
- V2 Redis namespaces are non-empty: `v2:* = 36`, including market, features, prediction, trainer, orchestrator, paper, and risk namespaces.
- Comparator and frontend truth payloads are fresh.
- Legacy log observer is fresh and read-only.
- `live_gate=blocked_human_only`; `live_symbols=[]`.

## Observation Contract

Verified artifacts:

- `v2/backend/app/services/rl_core/full_observation_builder.py`
- `v2/backend/app/cli/v2_full_observation_builder_status.py`
- `claude_worklog/final_readiness/v2_full_observation_builder/latest/full_observation_builder_status.json`
- `v2/frontend/public/v2_full_observation_builder/latest/operator_dashboard_payload.json`

The current contract is:

- `compact_observation_v1.dim=26`, preserved as the current runtime policy input.
- `full_observation_v1.target_dim=1911`, target schema `V3`.
- `checkpoint_compatibility_claimed=false`.
- `policy_architecture_parity_claimed=false`.
- Missing categories: `onchain_btc`, `onchain_eth`.
- Partial categories: `unified_features`, `portfolio_state`, `position_context`.

Current generated dimensions:

- `BTCUSDT`: generated `44`, missing `1867`, zero-filled `0`.
- `ETHUSDT`: generated `44`, missing `1867`, zero-filled `0`.
- `SOLUSDT`: generated `39`, missing `1872`, zero-filled `0`.

The builder result object carries full 1911-length `field_names`, `field_values`, and `field_sources`; the public/status payload emits compact samples plus counts/categories to avoid bloating frontend payloads. Missing evidence is visible through missing counts, missing-field samples, explicit categories, and `MISSING_NO_V2_NATIVE_SOURCE` / `ONCHAIN_FEATURE_SOURCE_MISSING` source labels. Source freshness is emitted per symbol as `CURRENT`.

## No Fabrication

Codex verified the builder does not pad the vector to fake completion:

- Missing slots remain `null`/`None`.
- Unknown fields are not silently zero-filled.
- On-chain BTC/ETH slices are explicit source-missing slices, not fake values.
- `FULL_OBSERVATION_BUILDER_COMPLETE` is not claimed.
- Checkpoint compatibility is not claimed.
- Policy architecture parity is not claimed.

The status is correctly `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`.

## V2-Only Runtime

The builder consumes V2-native runtime state only:

- `v2:features:latest:{symbol}:{timeframe}`
- `v2:paper:positions`
- `v2:paper:ledger`
- `v2:risk:decisions`
- `v2:orchestrator:decisions`
- `v2:trainer:heartbeat`
- `v2:prediction:{symbol}:{timeframe}`

No legacy `features:*` keys are consumed as current truth. No legacy filesystem read is used by the builder for live current features. No Redis writes are added by this builder path.

## Validation

- Focused tests: `9 passed` in `test_v2_full_observation_builder_status.py`.
- `py_compile`: PASS for the builder, CLI, and legacy observation contract helper.
- Torch/pickle load scan: PASS, no matches.
- Exchange mutation scan: PASS, no matches.
- Old Redis write scan over builder/CLI: PASS, no write calls.
- Approval scan over builder artifacts/public payloads: PASS.
- Raw secret scan over builder artifacts/public payloads: PASS.
- Git-tracked checkpoint blob scan: PASS, no tracked `.pt`, `.pth`, `.ckpt`, `.pkl`, `.pickle`, `.safetensors`, or `.zip` model blobs.
- `git diff --check`: PASS for reviewed builder files and artifacts.

## Frontend Truth

Monitor Center is wired to `/v2_full_observation_builder/latest/operator_dashboard_payload.json` and shows:

- builder state,
- compact vs target dimensions,
- generated vs target dimensions per symbol,
- missing and partial categories,
- zero-fill discipline,
- checkpoint compatibility false,
- policy architecture parity false,
- live/shutdown blocked state.

The frontend does not hide the missing-feature blocker.

## Safety State

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`

## Required Next Work

Proceed with missing-feature burndown, not policy-port parity yet:

- extend V2-native `unified_features` beyond the current 23 of 1430 fields,
- implement V2-native on-chain BTC/ETH sources or keep them explicitly missing,
- extend `portfolio_state` and `position_context` from V2 paper/risk/runtime state,
- keep missing/stale/source labels visible,
- rerun Codex before any `FULL_OBSERVATION_BUILDER_COMPLETE` or checkpoint compatibility claim.

## Final Decision

`V2_FULL_OBSERVATION_BUILDER_CODEX_PASS_PARTIAL_MISSING_FEATURE_BURNDOWN`
