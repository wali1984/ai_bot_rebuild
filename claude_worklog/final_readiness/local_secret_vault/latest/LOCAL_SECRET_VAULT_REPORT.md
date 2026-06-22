# Local-Only Legacy Secret And Config Vault Report

Generated: `2026-05-16T03:10:42+00:00`

GO/NO-GO: `LOCAL_ONLY_LEGACY_SECRET_AND_CONFIG_VAULT_READY`

## Result

Legacy env/config/credential files were copied into the local gitignored vault at `.local_secrets/legacy_runtime/raw/`. Raw values were not written to frontend public payloads or worklog reports.

## Counts

- Files considered: `31`
- Files copied: `31`
- Missing or unreadable files: `0`
- Total key names discovered: `3292`
- Unique key names discovered: `761`
- Values redacted: `true`

## Git And Permission Safety

- `.local_secrets/` gitignored: `True`
- `.env` gitignored: `True`
- `.env.*` gitignored: `True`
- Secret/credential/apikey patterns gitignored: `True`
- `git status --short .local_secrets .env .env.* config_accounts.py` empty: `True`
- Staged secret hits: `0`
- Vault directory mode: `0o700`
- Raw directory mode: `0o700`
- Redacted manifest mode: `0o600`

## Redacted Key Names

The status payload includes redacted key-name metadata only. First sample entries:

- `ACCOUNTS`
- `ACCOUNT_ASJAD_ALLOW_PUBLISH`
- `ACCOUNT_ASJAD_ENABLED`
- `ACCOUNT_ID`
- `ACCOUNT_PREFLIGHT_MAX_AGE_S`
- `ACCOUNT_PREFLIGHT_REQUIRED`
- `ACCOUNT_PRIMARY_ENABLED`
- `ACTION_CATEGORIES`
- `ACTIVE_TRADING_ACCOUNTS`
- `ADAPTIVE_BASE_SL_PCT`
- `ADAPTIVE_BASE_SL_PCT_WITH_HEDGE`
- `ADAPTIVE_BASE_TP_PCT`
- `ADAPTIVE_GATE_EDGE_FEES_ENABLED`
- `ADAPTIVE_GATE_ENABLED`
- `ADAPTIVE_GATE_FAST_MOVE_ENABLED`
- `ADAPTIVE_GATE_FUNDING_ENABLED`
- `ADAPTIVE_GATE_IMBALANCE_ENABLED`
- `ADAPTIVE_GATE_LIQUIDITY_ENABLED`
- `ADAPTIVE_GATE_MANIPULATION_ENABLED`
- `ADAPTIVE_GATE_SPREAD_ENABLED`
- `ADAPTIVE_GATE_TREND_ENABLED`
- `ADAPTIVE_GATE_VOLATILITY_ENABLED`
- `ADAPTIVE_HEDGE_BASE_TRIGGER_ROE`
- `ADAPTIVE_HEDGE_COOLDOWN_SEC`
- `ADAPTIVE_HEDGE_ENABLED`

No values are included in this report or the public payload.

## Loader

Created `v2/backend/app/services/local_secret_loader/service.py` and unit tests. The loader reads only from `.local_secrets/legacy_runtime`, redacts values in repr/logging helpers, denies frontend/public usage, and keeps live/exchange mutation usage blocked without separate approval and account-permission evidence.

## Safety State

- live_gate: `blocked_human_only`
- live_symbols: `[]`
- live_use_allowed: `false`
- approves_live: `false`
- approves_canary: `false`
- approves_legacy_shutdown: `false`
- approves_redis_trim: `false`
- old Redis written: `false`
- exchange mutation called: `false`

## Non-Approval

This vault does not approve live trading, canary trading, legacy shutdown, Redis trim, exchange mutation, leverage changes, or margin changes. Exchange keys remain read-only/unknown until the account permission monitor verifies permissions.
