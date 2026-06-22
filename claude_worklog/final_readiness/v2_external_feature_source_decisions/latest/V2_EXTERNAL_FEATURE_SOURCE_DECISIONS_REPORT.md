# V2 External Feature Source Decision Packets Report

GO/NO-GO: `V2_EXTERNAL_FEATURE_SOURCE_DECISION_PACKETS_READY`

This report does NOT approve live, canary, leverage/margin, exchange
mutation, legacy shutdown, Redis trim, paper-only shutdown acceptance,
or any external feed adoption. It does NOT create any credentials. It
does NOT load any blob. It does NOT modify legacy. The four packets
captured here are operator-decision inputs only — internal observation
expansion continues in parallel without blocking on them.

## Packets emitted

Each packet has a `.md` operator-readable form and a `.json` machine-
readable form. All four require operator decision before any V2-side
implementation.

| Family | Target dims | Default state | Optional for checkpoint compat? | Packet |
| ------ | ----------: | ------------- | ------------------------------- | ------ |
| `token_metrics` | 18 (within `unified_features`) | `DEFER_TOKEN_METRICS` | `OPERATOR_DECISION_REQUIRED` (`UNKNOWN_METADATA_REQUIRED` until checkpoint sidecar lands) | [token_metrics_source_decision.md](claude_worklog/final_readiness/v2_external_feature_source_decisions/latest/token_metrics_source_decision.md) / [.json](claude_worklog/final_readiness/v2_external_feature_source_decisions/latest/token_metrics_source_decision.json) |
| `onchain_btc` | 15 (standalone optional slice) | `DEFER_ONCHAIN_BTC` | `OPTIONAL_BY_LEGACY_V3_SCHEMA` | [onchain_btc_source_decision.md](claude_worklog/final_readiness/v2_external_feature_source_decisions/latest/onchain_btc_source_decision.md) / [.json](claude_worklog/final_readiness/v2_external_feature_source_decisions/latest/onchain_btc_source_decision.json) |
| `onchain_eth` | 15 (standalone optional slice) | `DEFER_ONCHAIN_ETH` | `OPTIONAL_BY_LEGACY_V3_SCHEMA` | [onchain_eth_source_decision.md](claude_worklog/final_readiness/v2_external_feature_source_decisions/latest/onchain_eth_source_decision.md) / [.json](claude_worklog/final_readiness/v2_external_feature_source_decisions/latest/onchain_eth_source_decision.json) |
| `ccxt_ohlcv` | 10 (within `unified_features`) | `DEFER_CCXT_OHLCV` | `OPTIONAL_FOR_CHECKPOINT_COMPATIBILITY_IF_NATIVE_BINANCE_OHLCV_PRESENT` | [ccxt_ohlcv_source_decision.md](claude_worklog/final_readiness/v2_external_feature_source_decisions/latest/ccxt_ohlcv_source_decision.md) / [.json](claude_worklog/final_readiness/v2_external_feature_source_decisions/latest/ccxt_ohlcv_source_decision.json) |

## Common structure of each packet

- `target_dims` — exact dim count within the legacy V3 observation.
- `why_v2_cannot_produce_today` — concrete pointer to the missing
  V2-native ingestor or upstream source.
- `possible_v2_native_source` — candidate provider(s) + V2
  implementation outline (only if operator approves).
- `required_credentials_or_api` — credential kind, storage location
  (`.local_secrets/`, gitignored), rate-limit decision, and an explicit
  assertion that no raw credentials appear in the packet.
- `optional_for_checkpoint_compatibility` — one of
  `OPERATOR_DECISION_REQUIRED`, `OPTIONAL_BY_LEGACY_V3_SCHEMA`, or
  `OPTIONAL_FOR_CHECKPOINT_COMPATIBILITY_IF_NATIVE_BINANCE_OHLCV_PRESENT`.
- `operator_decision_options` — three choices (Approve / Defer /
  Exclude).
- Hard safety fields: `approves_live=false`, `approves_canary=false`,
  `approves_legacy_shutdown=false`, `approves_redis_trim=false`,
  `live_gate=blocked_human_only`, `live_symbols=[]`,
  `creates_external_feed=false`, `creates_credentials=false`,
  `creates_paper_only_shutdown_acceptance_file=false`,
  `modifies_legacy=false`, `loads_any_blob=false`,
  `exchange_mutation=false`, `writes_old_redis=false`.

## Why this lane does not block internal expansion

Internal V2-native sub-families (`binance_klines`, `binance_orderbook`,
`liquidations`, `technical_analysis`, `coinank`,
`portfolio_state_unified`, `portfolio_state.extended`,
`position_context.extended`) continue to burn down independently. The
external lane is operator-decision-gated and produces zero runtime side
effects until an Approve choice lands with credentials and Codex review.

The full observation builder's current state remains:

```
state                           = FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS
checkpoint_compatibility_claimed = false
policy_architecture_parity_claimed = false
no_zero_fill_for_unknown_fields  = true
external_source_required_families = [token_metrics, onchain_btc, onchain_eth]
operator_decision_required_families = [ccxt_ohlcv]
```

## Default operator path (if the operator does nothing)

All four families remain `DEFER`. The full observation builder keeps
emitting those positions as explicit missing (`ONCHAIN_FEATURE_SOURCE_MISSING`,
`EXTERNAL_SOURCE_REQUIRED_NO_V2_NATIVE_TOKEN_METRICS`,
`OPERATOR_DECISION_REQUIRED_SECONDARY_EXCHANGE_OHLCV`) — never
zero-filled. Checkpoint compatibility is preserved for the two
explicitly optional slices (`onchain_btc`, `onchain_eth`) and remains
UNKNOWN for `token_metrics` until the checkpoint sidecar arrives.

## What this packet does NOT do

- Does not implement any V2 ingestor for external data.
- Does not commit any credentials to Git.
- Does not approve any external feed.
- Does not approve live, canary, legacy shutdown, Redis trim, or paper-
  only shutdown acceptance.
- Does not modify legacy.
- Does not claim checkpoint compatibility or policy architecture parity.

## Safety invariants (raw)

- `live_gate = blocked_human_only`
- `live_symbols = []`
- `approves_live = false`
- `approves_canary = false`
- `approves_legacy_shutdown = false`
- `approves_redis_trim = false`
- No raw credentials/secrets in any decision packet.
- No `.env`, no API keys, no bearer tokens, no operator IDs disclosed.
- No checkpoint blob commit. No legacy mutation.
