# External Feature Source Decision: token_metrics

Target dims (within `unified_features` 1430-dim slice): **18**

## Why current V2 cannot produce token_metrics

- No V2-native token-metrics ingestor exists in
  `v2.backend.app.cli` or `v2.backend.app.services`.
- Legacy `unified_feature_builder.py` defines `token_metrics` as a
  separate `DataSource.TOKEN_METRICS` family expecting off-exchange
  inputs (on-chain metrics, sentiment, holder distribution) that
  are NOT in any `v2:*` Redis namespace today.
- V2 ingestor registry currently exposes only Binance, KuCoin,
  CoinAPI, and CoinAnk; none of those provide the legacy
  token_metrics 18 dims.

## Possible V2-native source

External feed required. Candidate providers (operator selects):

- Operator-provided token-metrics REST/WebSocket feed
- Operator-provided sentiment aggregator
  (Glassnode-style, IntoTheBlock-style, or operator-internal)
- Operator-provided holder-distribution dataset

V2 implementation outline, **only if approved**:

1. New CLI `v2/backend/app/cli/v2_token_metrics_ingestor_loop.py`
   reading operator-approved REST/WebSocket feeds.
2. Vault-aware `secret_decision.py` classification for feed credentials.
3. Writes only `v2:market:token_metrics:{symbol}` keys.
4. Extend `full_observation_builder` to project the 18-dim slice from
   new `v2:market` keys.
5. Add focused tests + Codex review pair.

## Required credentials / API

- `OPERATOR_PROVIDED_KEY_REQUIRED` — API key or bearer token.
- Credential storage: `.local_secrets/` (gitignored; **never** embedded
  in payloads or commits).
- Rate-limit decision required.
- **No raw credentials appear anywhere in this decision packet.**

## Optional for checkpoint compatibility

`OPERATOR_DECISION_REQUIRED` (currently `UNKNOWN_METADATA_REQUIRED`).
Legacy V3 obs_schema declares `token_metrics=18` without an `optional=True`
flag, but whether the operator-provided checkpoint requires this slice
filled depends on its sidecar metadata. That metadata does not yet exist
(see `V2_CHECKPOINT_PROMOTION_OPERATOR_REQUIRED`), so the question is
open.

## Operator decision required

Options:

- **APPROVE_EXTERNAL_TOKEN_METRICS_FEED**: provide credentials and V2
  ingestor scope; new V2 ingestor + Codex review needed before
  integration.
- **DEFER_TOKEN_METRICS**: keep the 18 dims explicit-missing in
  `full_observation_builder` until a checkpoint is shown to need them.
- **EXCLUDE_TOKEN_METRICS**: skip permanently and record the
  corresponding compatibility limitation in the operator-provided
  checkpoint metadata.

Current default state: **DEFER_TOKEN_METRICS**.

## Safety

- `live_gate = blocked_human_only`
- `live_symbols = []`
- `approves_live = false`
- `approves_canary = false`
- `approves_legacy_shutdown = false`
- `approves_redis_trim = false`
- This packet does NOT modify legacy, write old Redis, call exchange
  mutation, enable live, create approvals, or commit credentials.
