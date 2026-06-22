# Codex Review: V2 Alt-Data Provider One-Shot Population

Generated: `2026-05-18T05:36:00Z`

GO/NO-GO: `V2_ALT_DATA_PROVIDER_ONE_SHOT_POPULATION_CODEX_PASS`

## Decision

Codex passes the provider one-shot population control run. Nansen and LunarCrush keys were present in the local Codex-only env, neither raw key was printed or persisted outside `.local_secrets`, both bounded one-shot clients ran without daemonizing, and the follow-up Symbol Universe scoring run preserved explicit provider failure states.

The providers returned `API_FORBIDDEN_403` for all three symbols. This is an acceptable PASS for this gate because the failure was explicit, no synthetic provider values were created, runtime continued, and scoring left provider-derived values `null`.

This review does not approve provider daemon enrollment, live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, or legacy shutdown.

## Commands Run

The local env was loaded without echoing values:

```bash
set -a
. .local_secrets/alternative_data.env
set +a
```

Then Codex ran bounded one-shots:

```bash
.venv/bin/python -m v2.backend.app.cli.v2_nansen_altdata_ingestor --symbols BTCUSDT,ETHUSDT,SOLUSDT
.venv/bin/python -m v2.backend.app.cli.v2_lunarcrush_altdata_ingestor --symbols BTCUSDT,ETHUSDT,SOLUSDT
.venv/bin/python -m v2.backend.app.cli.v2_alt_data_symbol_universe_scoring
```

Stdout/stderr were captured first and scanned against the loaded key values before any summaries were displayed. The captured-output secret scan passed.

## Provider Results

Nansen:

- `key_present=true`
- `network_call_attempted=true`
- `source_status_counts={"API_FORBIDDEN_403": 3}`
- `successful_symbol_count=0`
- `credential_in_payload=NEVER`
- `writes_legacy_redis=false`
- `writes_exchange_orders=false`

LunarCrush:

- `key_present=true`
- `network_call_attempted=true`
- `source_status_counts={"API_FORBIDDEN_403": 3}`
- `successful_symbol_count=0`
- `credential_in_payload=NEVER`
- `writes_legacy_redis=false`
- `writes_exchange_orders=false`

Both status payloads keep `gate=blocked_human_only` and `symbols_real=[]`.

## Redis Write Boundary

Observed provider keys:

- `v2:altdata:nansen:status`
- `v2:altdata:nansen:symbol:BTCUSDT`
- `v2:altdata:nansen:symbol:ETHUSDT`
- `v2:altdata:nansen:symbol:SOLUSDT`
- `v2:altdata:lunarcrush:status`
- `v2:altdata:lunarcrush:symbol:BTCUSDT`
- `v2:altdata:lunarcrush:symbol:ETHUSDT`
- `v2:altdata:lunarcrush:symbol:SOLUSDT`

Follow-up scoring wrote only:

- `v2:altdata:symbol_score:BTCUSDT`
- `v2:altdata:symbol_score:ETHUSDT`
- `v2:altdata:symbol_score:SOLUSDT`
- `v2:symbol_universe:altdata_candidates`

No old Redis key write was observed.

## Scoring After Provider Run

The scoring run consumed the provider payloads and kept failure explicit:

- `provider_source_status.nansen=API_FORBIDDEN_403`
- `provider_source_status.lunarcrush=API_FORBIDDEN_403`
- `altdata_symbol_score=null`
- `smart_money_score=null`
- `social_momentum_score=null`
- `providers_consulted=[]`
- missing reasons include `nansen_source_status_API_FORBIDDEN_403` and `lunarcrush_source_status_API_FORBIDDEN_403`

No missing or forbidden provider data was converted into numeric scores.

## Secret Hygiene

Codex scanned:

- captured stdout/stderr from the three one-shots;
- worklog artifacts under the provider/scoring lanes;
- public/frontend payloads;
- relevant V2 app and test source;
- live Redis values under the provider/scoring keys.

Result:

- raw Nansen key hits outside `.local_secrets`: `0`
- raw LunarCrush key hits outside `.local_secrets`: `0`
- raw Arkham key hits outside `.local_secrets`: `0`
- raw key hits in Redis provider/scoring payloads: `0`

## Safety

Codex verified:

- no old Redis writes;
- no exchange order placement/cancel/modify, leverage, or margin surface;
- no live/canary/shutdown/Redis-trim approval drift;
- provider failures did not stop runtime or scoring;
- scoring kept `live_symbols=[]`;
- scoring kept `paper_symbols_expanded=false`;
- scoring kept `may_not_override_strict_paper_fill_gate=true`.

Safety state remains:

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`

## Final Decision

`V2_ALT_DATA_PROVIDER_ONE_SHOT_POPULATION_CODEX_PASS`
