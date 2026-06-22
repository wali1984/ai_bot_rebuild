# External Feature Source Decision: onchain_eth

Target dims: **15** (legacy V3 `onchain_eth` slice, `optional=True`)

## Why current V2 cannot produce onchain_eth

- No V2-native Ethereum on-chain feed ingestor exists.
- Legacy V3 schema declares this slice **`optional=True`**; same
  rationale as `onchain_btc`.
- V2 has no on-chain data source in `v2:*` Redis.

## Possible V2-native source

External feed required. Candidate providers (operator selects):

- Operator-provided ETH on-chain aggregator
- Operator-provided Etherscan-style netflow / active-address feed
- Operator-internal Ethereum ETL

V2 implementation outline, **only if approved**:

1. New CLI `v2/backend/app/cli/v2_onchain_eth_ingestor_loop.py`.
2. Vault-aware `secret_decision.py` classification.
3. Writes only `v2:market:onchain_eth` keys.
4. Extend `full_observation_builder.onchain_eth`.
5. Tests + Codex review pair.

## Required credentials / API

- `OPERATOR_PROVIDED_KEY_REQUIRED` — API key or bearer token.
- Credential storage: `.local_secrets/` (gitignored).
- Rate-limit decision required.
- **No raw credentials in this packet.**

## Optional for checkpoint compatibility

`OPTIONAL_BY_LEGACY_V3_SCHEMA`. Checkpoint compatibility does NOT
require this slice.

## Operator decision required

Options:

- **APPROVE_EXTERNAL_ETH_ONCHAIN_FEED**: provide credentials and V2
  ingestor scope.
- **DEFER_ONCHAIN_ETH**: keep 15 dims explicit-missing (current
  default).
- **EXCLUDE_ONCHAIN_ETH**: skip permanently and record the limitation
  in the operator-provided checkpoint metadata.

Current default state: **DEFER_ONCHAIN_ETH**.

## Safety

- `live_gate = blocked_human_only`
- `live_symbols = []`
- `approves_live = false`
- `approves_canary = false`
- `approves_legacy_shutdown = false`
- `approves_redis_trim = false`
- This packet does NOT modify legacy, write old Redis, call exchange
  mutation, enable live, create approvals, or commit credentials.
