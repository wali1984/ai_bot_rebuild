# Binance USD-M commission-evidence broker operator contract

This service is an isolated read-only evidence producer. It executes at most
one signed `GET /fapi/v1/commissionRate` per scheduling turn and has no order,
cancel, leverage, margin-mode, transfer, withdrawal, trainer, prediction,
paper, or live authority.

## Credentials and public identity

The unit reuses the three protected files already provisioned for the approved
Binance USD-M leverage-bracket evidence surface:

| Runtime credential name | Protected source |
| --- | --- |
| `trader-wajidali1984--ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY--api_key` | `%h/.config/ai-bot-v2/credentials/binance-bracket-evidence/api-key.cred` |
| `trader-wajidali1984--ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY--api_secret` | `%h/.config/ai-bot-v2/credentials/binance-bracket-evidence/api-secret.cred` |
| `binance_bracket_evidence_hmac_key` | `%h/.config/ai-bot-v2/credentials/binance-bracket-evidence/evidence-hmac.cred` |

Secret values are never accepted in arguments, environment values, Redis,
journal output, repository files, or the publisher. The producer uses the
fixed mainnet origin and the public account binding documented by the unit.

## Adaptive rotation and rate limit

The scheduling universe is read atomically from
`v2:symbol_universe:dynamic_discovered_symbols`. Invalid symbol metadata is
rejected individually; valid canonical symbols continue. This key selects the
rotation only and grants no trainer or trading authority.

Each successful turn reserves the endpoint's published request weight 20 in
the host-shared Redis budget. With the deployed 120-weight-per-minute service
budget, minimum pacing is derived as 10 seconds. The broker samples observed
capture latency, prioritizes missing/invalid/expired evidence, derives each
refresh interval from the projected universe revisit, and refuses evidence
lifetimes beyond the immutable one-hour integrity horizon. These are resource
and provenance bounds, not market or performance thresholds.

## Storage and publication

The producer has read-write access only to:

`/home/wali/ai_bot_local_data/v2_authenticated_evidence/binance_usdm_commission_broker_v1`

Raw response, request identity, fee artifact, fee receipt, adaptive refresh
artifact/receipt, and rotation artifact/receipt are immutable CAS objects.
Redis receives a canonical HMAC-sealed envelope, never raw response or secret
material. Publication is monotonic compare-and-set and a pacing claim prevents
restart or duplicate-worker bursts.

The publisher receives this root read-only and only the HMAC credential. Do
not switch the publisher until the full current canonical trainer universe is
warm and sampled reader results are `READY`.
