# Codex Review: V2 External Feature Source Decision Packets

Generated: `2026-05-17T20:09:15Z`

GO/NO-GO: `V2_EXTERNAL_FEATURE_SOURCE_DECISION_PACKETS_CODEX_PASS`

## Decision

Codex passes the external feature source decision packets at the operator-decision-input scope. The packets make the external gaps explicit, defer all four families by default, and do not claim implementation, checkpoint compatibility, policy parity, live readiness, or shutdown readiness.

This review does not approve any external feed adoption, credential creation, live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, or legacy shutdown.

## Packet Coverage

Reviewed packets:

- `token_metrics_source_decision.md` / `.json`
- `onchain_btc_source_decision.md` / `.json`
- `onchain_eth_source_decision.md` / `.json`
- `ccxt_ohlcv_source_decision.md` / `.json`
- public payload: `v2/frontend/public/v2_external_feature_source_decisions/latest/operator_dashboard_payload.json`

Current packet states:

| Family | Target dims | Default state | Operator decision |
| --- | ---: | --- | --- |
| `unified_feature_family.token_metrics` | `18` | `DEFER_TOKEN_METRICS` | required |
| `onchain_btc` | `15` | `DEFER_ONCHAIN_BTC` | required |
| `onchain_eth` | `15` | `DEFER_ONCHAIN_ETH` | required |
| `unified_feature_family.ccxt_ohlcv` | `10` | `DEFER_CCXT_OHLCV` | required |

All four JSON packets report `v2_native_can_produce_today=false` and `operator_decision_required=true`.

## External Gaps

The gaps are not hidden:

- `token_metrics` remains external/operator-required because no V2-native token-metrics ingestor exists.
- `onchain_btc` and `onchain_eth` remain external-source-required and optional by legacy V3 schema.
- `ccxt_ohlcv` remains operator-decision-required for secondary-exchange OHLCV.

The active full-observation payload still shows:

- `external_source_required_families = ["unified_feature_family.token_metrics", "onchain_btc", "onchain_eth"]`
- `operator_decision_required_families = ["unified_feature_family.ccxt_ohlcv"]`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`
- `no_zero_fill_for_unknown_fields=true`

## Frontend Visibility

The frontend/public payload exists and is machine-readable:

`v2/frontend/public/v2_external_feature_source_decisions/latest/operator_dashboard_payload.json`

It contains `packet_count=4`, family IDs, target dims, defer states, operator-decision-required flags, no-raw-credential flags, and safety booleans. This is sufficient for frontend/operator display as decision data. I did not find dedicated Monitor Center cards for this payload in this review, so this PASS is for public payload availability and honesty, not a claim of a rendered Monitor Center section.

## Safety And Secret Review

Codex verified:

- No raw secret/API key/bearer token/private key patterns in the decision packets or public payload.
- `creates_external_feed=false` for every packet.
- `creates_credentials=false` for every packet.
- `creates_paper_only_shutdown_acceptance_file=false`.
- `modifies_legacy=false`.
- `loads_any_blob=false`.
- `exchange_mutation=false`.
- `writes_old_redis=false`.
- No approval drift in packet artifacts or public payload.

Safety state remains:

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`

## Runtime Governor

The standing continuous remediation governor was refreshed:

- `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY`
- V2/remediation processes: `12/12`
- 6h soak remains true.
- V2 Redis namespaces remain non-empty.
- No fail blockers.
- No unsafe Redis write, exchange mutation, approval drift, or raw secret exposure reported.

The Codex governor loop remains running.

## Validation

- JSON validation for all four decision packets and the public payload: PASS.
- Structured packet field validation: PASS.
- Raw secret scan: PASS.
- Approval/live/shutdown drift scan: PASS.
- Exchange mutation and old Redis write scan over packet artifacts/public payload: PASS.
- `git diff --check`: PASS for reviewed packet artifacts.

## Final Decision

`V2_EXTERNAL_FEATURE_SOURCE_DECISION_PACKETS_CODEX_PASS`
