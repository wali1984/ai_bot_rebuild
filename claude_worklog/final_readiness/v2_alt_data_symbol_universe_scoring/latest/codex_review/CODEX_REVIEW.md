# Codex Review: V2 Alternative-Data Symbol-Universe Scoring

Generated: `2026-05-21T21:13:26Z`

GO/NO-GO: `V2_ALT_DATA_SYMBOL_UNIVERSE_SCORING_CODEX_PASS`

## Decision

Codex passes the V2 alternative-data symbol-universe scoring packet after the input-boundary remediation. The scorer now consumes only V2 alternative-data provider payloads plus V2 market/feature inputs, exposes missing and stale provider data explicitly, keeps all live/canary/shutdown authority blocked, and writes only the approved scoring outputs.

This review does not approve the future candidate publisher, provider-client expansion, paid endpoints, live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, production equivalence, or legacy shutdown.

## Prior Blocker Cleared

Prior fail blocker:

`SCORING_INPUT_BOUNDARY_INCLUDES_V2_PAPER_AND_RISK_CONTEXT`

Codex verified the scorer no longer reads or declares `v2:paper:*` or `v2:risk:*` as scoring inputs.

Allowed inputs are now exactly:

- `v2:altdata:nansen:status`
- `v2:altdata:nansen:symbol:{symbol}`
- `v2:altdata:lunarcrush:status`
- `v2:altdata:lunarcrush:symbol:{symbol}`
- `v2:market:prices:{symbol}`
- `v2:market:funding:{symbol}`
- `v2:market:open_interest:{symbol}`
- `v2:features:latest:{symbol}:{timeframe}`

The payload explicitly marks these namespaces as forbidden for this lane:

- `v2:paper:*`
- `v2:risk:*`

Direct read-log proof over `BTCUSDT`, `ETHUSDT`, and `SOLUSDT` showed only alt-data, market, and feature reads. Forbidden `v2:paper:*` / `v2:risk:*` reads: `0`.

## Prerequisite Markers

Provider client Codex markers exist:

- `V2_NANSEN_FREE_TIER_CLIENT_CODEX_PASS_PAPER_SHADOW`
- `V2_LUNARCRUSH_FREE_TIER_CLIENT_CODEX_PASS_PAPER_SHADOW`

Those provider reviews remain paper/shadow only and do not grant live authority.

## Runtime Payload

Refreshed scoring payload:

- `go_no_go=V2_ALT_DATA_SYMBOL_UNIVERSE_SCORING_READY`
- symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`
- `scoring_input_boundary_remediated=true`
- `provider_network_calls_attempted=false`
- `paper_symbols_expanded=false`
- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`

Current provider state remains explicit:

- missing Nansen/LunarCrush fields are surfaced in `missing_provider_flags`;
- `stale_provider_flags=[]`;
- provider availability is explicit per symbol;
- `providers_consulted=[]` where provider payloads are unavailable;
- `altdata_symbol_rank_per_candidate` is populated for the three reviewed symbols.

## Redis And Frontend

Allowed writes are only:

- `v2:altdata:symbol_score:{symbol}`
- `v2:symbol_universe:altdata_candidates`

Current Redis evidence:

- `v2:altdata:symbol_score:BTCUSDT`
- `v2:altdata:symbol_score:ETHUSDT`
- `v2:altdata:symbol_score:SOLUSDT`
- `v2:symbol_universe:altdata_candidates`

The worklog and public operator payloads match the refreshed three-symbol status. The frontend exposes score, freshness, missing/stale provider flags, provider availability, rank, and live-blocked state honestly.

## Safety

Codex verified:

- raw credential-value scan over reviewed source, tests, worklog/public payloads, and current scoring Redis values: `0` hits outside `.local_secrets`;
- no old Redis write path in the reviewed scoring path;
- no provider network-call import in the scoring path;
- no exchange order, cancel, modify, leverage, margin, `/fapi/`, or test-order mutation path in the reviewed scoring path;
- no live/canary/shutdown/Redis-trim approval drift;
- alt-data payloads keep `may_not_override_strict_paper_fill_gate=true`;
- alt-data payloads keep `may_not_authorize_live_or_canary=true`;
- alt-data payloads keep `may_not_place_orders=true`.

Matches for `v2:paper:*` and `v2:risk:*` are now restricted to forbidden-namespace documentation, forbidden-namespace payload fields, and regression-test assertions.

## Candidate Publisher Boundary

Codex did not start or approve `V2_ALT_DATA_SYMBOL_UNIVERSE_CANDIDATE_PUBLISHER`.

Future candidate-publisher work may propose:

- `altdata_candidates`
- `training_symbol_candidates`
- `paper_symbol_candidates`

but this scoring PASS does not allow silent mutation of:

- `live_symbols`
- `paper_symbols`
- `training_symbols`

unless existing Symbol Universe governance explicitly permits it in a separate reviewed packet.

## Validation

- Scoring CLI refresh: PASS.
- Focused alt-data scoring tests: `22 passed`.
- Direct read-log proof: PASS, `0` paper/risk reads.
- `py_compile`: PASS.
- Redis write allowlist check: PASS.
- Raw credential scan: PASS, `0` file hits and `0` Redis hits outside `.local_secrets`.
- Old Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.
- Worklog/public mirror inspection: PASS.

## Final Decision

`V2_ALT_DATA_SYMBOL_UNIVERSE_SCORING_CODEX_PASS`
