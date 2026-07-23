# Binance USD-M Leverage-Bracket Evidence Producer

By default this user service performs only the signed Binance USD-M
`GET /fapi/v1/leverageBracket` read and publishes authenticated paper-sizing
evidence. An explicitly configured, currently undeployed extension can additionally
interleave one `GET /fapi/v1/commissionRate` read at a time. Neither path can place,
cancel, or modify orders or change leverage or margin mode. Bracket evidence is an
exchange ceiling and maintenance-margin input, never a leverage recommendation or
trade authorization. The authenticated bracket evidence and status contracts are
version 3; version 2 readers must fail closed rather than silently accept the added
binding assertions.

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

Current negative permission evidence (2026-07-20 UTC): a signed, non-mutating
`account.status` diagnostic using the legacy generic resolved credential succeeded
and reported `canTrade=true`, `canDeposit=true`, and `canWithdraw=true`. Balances,
positions, API-key bytes, and secret bytes were not retained in the operator record.
That credential is therefore explicitly disqualified from this service: do not copy,
rename, encrypt, or provision it into any credential slot listed above. This negative
result does not set `exchange_key_permissions_proven_by_connector=true`; activation
still requires a distinct account-scoped key whose Binance-side permissions are
independently proven both non-trading and non-withdrawing.

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

## Optional commission-evidence broker (implemented, not deployed)

Supplying the CLI's `--commission-broker-data-root <absolute-path>` opt-in keeps the
normal bracket refresh cadence and uses the in-process, authenticated
`symbols_published` result as the maximum commission rotation universe. The optional
`--commission-priority-symbol` can reorder a symbol already in that universe; it
cannot add a symbol that the bracket response did not authenticate and publish.
The checked-in systemd unit does not currently supply either option, and no service
activation or restart is part of this code checkpoint.

Every broker turn is restricted to exactly one signed
`GET /fapi/v1/commissionRate?symbol=...` request. The existing capture factory:

- reserves the endpoint's exact weight of 20 in the host-shared Redis Binance budget;
- allows only the official USD-M mainnet/testnet HTTPS origins and disables proxy and
  redirect forwarding of the signed request;
- snapshots a bounded response and durably writes its exact bytes to immutable CAS
  before the first JSON decode; and
- persists only a domain-separated credential-binding fingerprint, sanitized request
  identity, exact response hash/address, fee artifact, and receipts. API-key, secret,
  signature, and raw response bytes are not placed in Redis.

Rotation pacing is an operational rate-limit calculation, not a market threshold.
It divides the configured shared per-minute budget by the route's weight, spaces
single-symbol claims uniformly, and continuously reorders the universe by missing,
invalid, expired, then earliest-expiring authenticated evidence. At the current
default safety budget of 120 weight/minute, that is six calls/minute, one claim per
10 seconds, and a 159-symbol baseline revisit of 1,590 seconds. The policy then adds
the maximum authenticated observed capture duration and one projected turn. It does
not assert continuous coverage until every symbol is current and the measured revisit
fits inside the capture factory's immutable one-hour evidence safety horizon.

Two Redis controls prevent a burst or stale replacement:

- `v2:binance_usdm:commission_rotation_claim:<environment>:<trader>:<credential-ref>`
  is an atomic pacing claim shared by duplicate workers and restarts; and
- per-symbol evidence/version keys use one Lua compare-and-set. An older publication
  is rejected, an exact same-clock retry is idempotent, and a same-clock byte conflict
  fails closed. Both evidence and version TTLs are bounded by the evidence's exclusive
  `expires_at`.

The Redis envelope uses an HMAC domain distinct from the credential fingerprint and
binds exact route, symbol, origin, account identifiers, clocks, CAS addresses, request
weight, adaptive rotation receipt, and refresh-policy receipt. The credential label
is still only an operator assertion; every envelope explicitly records
`exchange_key_permissions_proven_by_connector=false`.

`read_authenticated_commission_evidence(...)` is the intended profiled-publisher
boundary. It needs only the independent evidence HMAC context and read access to the
broker CAS; it never accepts or loads either Binance credential. It reopens and hashes
the raw response, sanitized request identity, fee artifact/receipt, adaptive rotation
artifact/receipt, and refresh-policy artifact/receipt. Admission requires the exact
causal order
`source_available_at <= broker_available_at <= consumer_observed_at <= available_at <= decision_time < expires_at`.
The returned object contains the exact three inputs already accepted by the causal
cost builder, but grants no trainer, prediction, paper, or live authority by itself.

Two integration steps intentionally remain operator/release work: choose a durable
absolute CAS path writable under the hardened unit's `ProtectSystem=strict` sandbox,
and wire the credentialless reader into the profiled publisher's prospective decision
path. Until both are released and a symbol has current evidence, the publisher must
retain its masked-cost behavior; it must not synthesize a fee or fall back to a static
value.

Focused verification for this extension is:

```bash
.venv/bin/python -m pytest -q \
  v2/backend/tests/unit/services/test_binance_usdm_commission_evidence_broker.py \
  v2/backend/tests/unit/services/native_trainer/test_binance_usdm_commission_capture_v1.py \
  v2/backend/tests/unit/services/native_trainer/test_causal_cost_evidence_v1.py \
  v2/backend/tests/unit/cli/test_v2_binance_usdm_leverage_bracket_evidence.py
```
