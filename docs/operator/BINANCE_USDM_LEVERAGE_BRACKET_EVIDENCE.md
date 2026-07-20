# Binance USD-M Leverage-Bracket Evidence Producer

This user service performs only the signed Binance USD-M `GET /fapi/v1/leverageBracket`
read and publishes authenticated paper-sizing evidence. It cannot place, cancel, or
modify orders and cannot change leverage or margin mode. Its evidence is an exchange
ceiling and maintenance-margin input, never a leverage recommendation or trade
authorization. The authenticated evidence and status contracts are version 3; version
2 readers must fail closed rather than silently accept the added binding assertions.

## Fail-closed identity and secret contract

The supervised unit is bound to:

- trader ID `trader-wajidali1984`;
- credential reference `ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY`;
- Binance USD-M mainnet origin `https://fapi.binance.com`;
- evidence key ID `binance-bracket-evidence-v1`.

The exchange key must be independently verified in Binance as read-only. Code also
requires the public credential reference to match the case-sensitive structural
grammar `<namespace>_BINANCE[_<opaque-account-token>...]_READONLY`. The final token
is an explicit operator usage/binding label, not proof of the API key's permissions
at Binance; public status says so directly. A reference of `BINANCE` or
`BINANCE_READONLY` is forbidden: the legacy resolver would treat the generic
`BINANCE_API_KEY` pair as account-specific when that reference is selected, even
though it does not prove a trader-scoped, read-only binding.

Three separately named systemd encrypted credentials are mandatory:

| Credential name | Encrypted blob expected by the unit |
| --- | --- |
| `trader-wajidali1984--ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY--api_key` | `%h/.config/ai-bot-v2/credentials/binance-usdm-leverage-bracket/api-key.cred` |
| `trader-wajidali1984--ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY--api_secret` | `%h/.config/ai-bot-v2/credentials/binance-usdm-leverage-bracket/api-secret.cred` |
| `binance_bracket_evidence_hmac_key` | `%h/.config/ai-bot-v2/credentials/binance-usdm-leverage-bracket/evidence-hmac-key.cred` |

The HMAC credential must contain at least 32 bytes of entropy encoded as one
UTF-8-safe, single-line base64 or hexadecimal value. It must differ from both the
exchange API key and exchange API secret. Do not reuse an exchange credential, put plaintext values in
the unit or repository, pass values on a command line, or print decrypted values.
The paper consumer must be provisioned with the same HMAC key and key ID through
its own protected credential path before bracket evidence can authorize paper
accounting.

## Operator provisioning boundary

Do not install, enable, or start the unit until the operator has verified the exact
Binance account and read-only API-key permissions. Create the destination directory
with mode `0700`, then create each blob with `systemd-creds encrypt` using TPM-backed
encryption. Feed secrets through a non-echoing stdin prompt; never use a plaintext
temporary file or a command-line argument. Generate the evidence HMAC independently
with at least 32 bytes of entropy, encode it as single-line base64 or hexadecimal,
and label the encrypted input with the exact case-sensitive credential name in the
table.

The checked-in unit intentionally has no optional secret fallback. A missing blob,
wrong credential name, changed trader/reference, unrecognized HTTP origin, short or
reused HMAC, unavailable Redis, disabled/budget-blocked REST fallback, invalid Binance
response, or failed Redis publication remains `BLOCKED` and cannot produce usable
evidence. Existing good evidence is still governed by its embedded account binding,
authentication tag, observation time, and expiry.

## Paper consumer credential boundary

The checked-in candidate drop-in
`tools/systemd_units/ai-bot-v2-trade-management-paper-loop.service.d/60-binance-usdm-leverage-bracket-consumer.conf`
gives the paper loop only `binance_bracket_evidence_hmac_key` and the four public
binding values listed above. It does not load the Binance API key or API secret. The
paper loop never falls back to an HMAC environment variable or repository env file;
an absent, empty, symlinked, non-regular, oversized, multiline, or invalid protected
credential leaves maintenance-bracket verification `BLOCKED`.

The producer and paper consumer must load the same encrypted HMAC blob and key ID.
The consumer reconstructs the exact public trader, credential-reference, and Binance
environment binding, then verifies both those fields and the HMAC on every cached
payload. A mismatched key, key ID, or binding cannot authorize leverage or margin.
This authentication does not prove the exchange key's Binance-side permissions;
`exchange_key_permissions_proven_by_connector` remains `false` until a separate
read-only permission proof is implemented and validated.

The drop-in is a version-controlled candidate only. Installing it, reloading the
user manager, and restarting the paper loop remain operator-controlled actions. Do
not activate it before the producer credential and Binance permission checks above
are complete.

Before any operator-controlled start, validate the unit syntax and run focused tests:

```bash
systemd-analyze --user verify tools/systemd_units/ai-bot-v2-binance-usdm-leverage-bracket-evidence.service
.venv/bin/python -m pytest -q \
  v2/backend/tests/unit/services/test_binance_usdm_leverage_bracket_evidence.py \
  v2/backend/tests/unit/cli/test_v2_binance_usdm_leverage_bracket_evidence.py \
  v2/backend/tests/unit/cli/test_v2_binance_usdm_leverage_bracket_supervision.py \
  v2/backend/tests/unit/cli/test_v2_trade_management_paper_bracket_credentials.py
```

Installation, credential creation, service start/restart, and the first signed read
are explicit operator actions and are not performed by repository tests.
