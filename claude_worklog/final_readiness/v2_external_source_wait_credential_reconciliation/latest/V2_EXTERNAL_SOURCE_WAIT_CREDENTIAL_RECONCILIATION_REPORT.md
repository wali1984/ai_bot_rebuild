# V2 External Source Wait Credential Reconciliation

Generated: 2026-05-25T19:15:42Z
GO/NO-GO: `V2_EXTERNAL_SOURCE_WAIT_CREDENTIAL_RECONCILIATION_READY`

This packet checks external-source credential presence by env var name and alias only.
It does not read or print raw credential values and does not activate paid feeds.

## Summary

- alias_mappings_checked: `True`
- providers_with_key_present_client_missing: `['tokenmetrics']`
- seeded_or_referenced_count: `1`
- external_source_marked_complete_without_payload_count: `0`

## Safety

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- no live/canary/shutdown approval
- no old Redis writes
- no exchange mutation
- no raw credential values

## full_observation_builder.external_sources

- onchain_btc: SOURCE_MISSING_KEY_OPERATOR_REQUIRED (key_present_by_name=False)
- onchain_eth: SOURCE_MISSING_KEY_OPERATOR_REQUIRED (key_present_by_name=False)
- unified_feature_family.token_metrics: SOURCE_KEY_PRESENT_CLIENT_MISSING_TASK_SEEDED_OR_REFERENCED (key_present_by_name=True)
