# Codex Alternative Data Secret Custody

GO/NO-GO: `CODEX_ALT_DATA_SECRET_CUSTODY_READY`

This packet stores alternative-data key custody in a local gitignored vault and publishes only redacted presence status. It does not approve live, canary, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy parity, or legacy shutdown.

## Redacted Presence

- `nansen_key_present`: `true`
- `lunarcrush_key_present`: `true`
- `arkham_key_present`: `false`
- `raw_values_exposed`: `false`
- `paid_tier_enabled`: `false`
- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`

## Custody

- Vault path: `.local_secrets/alternative_data.env`
- `.local_secrets/` is gitignored.
- `ARKHAM_API_KEY` is an empty placeholder until the operator provides it.
- Raw key values are not written to worklog reports, public payloads, task descriptors, or stdout.

## Decision

`CODEX_ALT_DATA_SECRET_CUSTODY_READY`
