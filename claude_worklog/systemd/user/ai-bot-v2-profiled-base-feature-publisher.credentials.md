# Profiled base-feature publisher broker credential contract

This is the deployment and trust-boundary contract for the publisher. The
publisher is an authenticated consumer of locally brokered commission
evidence. It does not load Binance API credentials and cannot execute the
signed exchange request itself.

## Exact protected input

The unit mounts exactly one systemd credential:

| Runtime credential name | Protected source | Purpose |
| --- | --- | --- |
| `binance_bracket_evidence_hmac_key` | `%h/.config/ai-bot-v2/credentials/binance-bracket-evidence/evidence-hmac.cred` | Verify the broker envelope and seal the consumer-read receipt |

The HMAC value must be at least 32 UTF-8 bytes and must match the independent
key used by the commission-evidence producer. The publisher unit contains zero
API-key, API-secret, commission-fingerprint-key, `ImportCredential=`, `.env`,
or `EnvironmentFile=` inputs. The public binding remains:

- trader ID: `trader-wajidali1984`
- credential reference: `ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY`
- exchange origin identity: `https://fapi.binance.com`
- evidence key ID: `binance-bracket-evidence-v1`

`READONLY` in the public reference is an operator label, not proof of the
Binance-side permission set. The stronger process boundary is that the
publisher has neither exchange credential and its code path only reads Redis
and the broker CAS.

## Broker evidence boundary

The producer is the only service in this path that can execute signed
`GET /fapi/v1/commissionRate`. It persists the exact response plus refresh and
rotation artifacts in immutable CAS and publishes only a canonical HMAC-sealed
envelope in Redis. Its request weight is reserved through the host-shared Redis budget.
The route is read-only; no order, cancellation, leverage, margin-mode,
transfer, or withdrawal endpoint is present in the producer CLI.

The publisher receives read-only filesystem access to:

`/home/wali/ai_bot_local_data/v2_authenticated_evidence/binance_usdm_commission_broker_v1`

For each prospective decision it verifies the envelope HMAC, all eight CAS
objects, content hashes, symbol, rotation receipt, refresh receipt, and the
ordering of `source_available_at`, `broker_available_at`,
`consumer_observed_at`, `consumer_checked_at`, `decision_time`, and
`expires_at`. The exact envelope and HMAC-sealed consumer-read receipt are then
copied into the publisher's enrichment CAS and bound to the fee derivation.
This adds lineage only; the physical ABI remains 35+4.

## Fail-closed behavior

Missing, stale, malformed, future, expired, or unauthenticated broker evidence
produces a durable 35-field parent with cost masks `[1,1,1,1]`, no four cost
values, and no trainer admission. Such a parent is never retro-enriched. A
later authenticated broker observation can affect only a new finalized,
prospective decision window.

The producer must be warmed before the publisher is switched to broker mode.
Required activation evidence is:

- broker current count equals the canonical trainer-universe count;
- missing, invalid, and expired counts are all zero;
- `continuous_coverage_feasible=true`;
- producer `NRestarts=0`;
- authenticated reader samples return `READY`.

The publisher writes only under
`/home/wali/ai_bot_local_data/v2_native_trainer` and reads the separate broker
root. It does not start a trainer, optimizer, predictor, allocator, paper loop,
risk controller, or live process. Its unit has no automatic downstream
transition authority.
