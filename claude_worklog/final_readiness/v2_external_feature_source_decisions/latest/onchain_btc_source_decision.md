# External Feature Source Decision: onchain_btc

Target dims: **15** (legacy V3 `onchain_btc` slice, `optional=True`)

## Why current V2 cannot produce onchain_btc

- No V2-native Bitcoin on-chain feed ingestor exists.
- Legacy V3 schema declares this slice **`optional=True`** in
  `v2/legacy_owned_runtime/rl/obs_schema.py _build_schema_v3`. It is
  therefore optional for legacy inference and not required for V2
  paper inference today.
- V2 has no on-chain data source in `v2:*` Redis.

## Possible V2-native source

External feed required. Candidate providers (operator selects):

- Operator-provided on-chain aggregator
  (Glassnode-equivalent, mempool-style metrics)
- Operator-provided exchange-netflow / hash-rate feed
- Operator-internal on-chain ETL

V2 implementation outline, **only if approved**:

1. New CLI `v2/backend/app/cli/v2_onchain_btc_ingestor_loop.py`.
2. Vault-aware `secret_decision.py` classification.
3. Writes only `v2:market:onchain_btc` keys.
4. Extend `full_observation_builder.onchain_btc` to project from new
   `v2:market` keys.
5. Add focused tests + Codex review pair.

## Required credentials / API

- `OPERATOR_PROVIDED_KEY_REQUIRED` — API key or bearer token.
- Credential storage: `.local_secrets/` (gitignored; **never** in
  payloads or commits).
- Rate-limit decision required.
- **No raw credentials in this packet.**

## Optional for checkpoint compatibility

`OPTIONAL_BY_LEGACY_V3_SCHEMA`. The legacy V3 obs_schema marks
`onchain_btc.optional = True`, so checkpoint compatibility does NOT
require this slice to be filled. V2 can keep the 15 dims explicit-
missing without breaking the V3 shape contract.

## Operator decision required

Options:

- **APPROVE_EXTERNAL_BTC_ONCHAIN_FEED**: provide credentials and V2
  ingestor scope.
- **DEFER_ONCHAIN_BTC**: keep 15 dims explicit-missing (current
  default; safe under `optional=True`).
- **EXCLUDE_ONCHAIN_BTC**: skip permanently and record the limitation
  in the operator-provided checkpoint metadata.

Current default state: **DEFER_ONCHAIN_BTC**.

## Safety

- `live_gate = blocked_human_only`
- `live_symbols = []`
- `approves_live = false`
- `approves_canary = false`
- `approves_legacy_shutdown = false`
- `approves_redis_trim = false`
- This packet does NOT modify legacy, write old Redis, call exchange
  mutation, enable live, create approvals, or commit credentials.
