# Codex Review: V2 Top-10 Market And Alternative-Data Dashboard Contracts

Generated: `2026-05-21T03:55:14Z`

GO/NO-GO: `V2_TOP10_MARKET_AND_ALTDATA_DASHBOARD_CONTRACTS_CODEX_PASS`

## Decision

Codex passes the top-10 market and alternative-data dashboard contracts. This is contract/data-shape work only: it does not call provider APIs, does not expose raw keys, does not write Redis, and does not affect trading gates.

This review does not approve provider-client implementation, external feed adoption, paid endpoints, live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, production equivalence, or legacy shutdown.

## Evidence Reviewed

- `v2/backend/app/services/alternative_data/top10_dashboard_contracts.py`
- `v2/backend/app/cli/v2_top10_market_and_altdata_dashboard_contracts.py`
- `v2/backend/tests/integration/cli/test_v2_top10_market_and_altdata_dashboard_contracts.py`
- `claude_worklog/final_readiness/v2_top10_market_and_altdata_dashboard_contracts/latest/top10_dashboard_contracts.json`
- `claude_worklog/final_readiness/v2_top10_market_and_altdata_dashboard_contracts/latest/TOP10_MARKET_AND_ALTDATA_DASHBOARD_CONTRACTS.md`
- `v2/frontend/public/v2_top10_market_and_altdata_dashboard_contracts/latest/operator_dashboard_payload.json`

## Exact Dashboard Set

The generated contract contains exactly 10 dashboards in the requested order:

1. `binance_spot_12h_volume_leaders` - Binance Spot 12h Volume Leaders
2. `binance_futures_12h_volume_leaders` - Binance Futures 12h Volume Leaders
3. `binance_spot_12h_most_traded` - Binance Spot 12h Most Traded
4. `binance_futures_12h_most_traded` - Binance Futures 12h Most Traded
5. `binance_spot_12h_volatility_leaders` - Binance Spot 12h Volatility Leaders
6. `binance_futures_12h_volatility_leaders` - Binance Futures 12h Volatility Leaders
7. `liquidation_tape_top_symbols` - Liquidation Tape Top Symbols
8. `funding_oi_movers` - Funding/OI Movers
9. `nansen_smart_money_top_symbols` - Nansen Smart Money Top Symbols
10. `lunarcrush_social_momentum_top_symbols` - LunarCrush Social Momentum Top Symbols

## Contract Checks

Binance spot/futures panels use V2/Binance market-data contract sources only:

- `v2:market:binance:{spot|futures}:rolling_12h:{symbol}`
- `v2:market:prices:{symbol}`
- `v2:features:latest:{symbol}:1m`

All 10 dashboards explicitly require `missing_source` and `stale_flag`. The liquidation panel uses only V2 liquidation WSS heartbeat/latest/aggregate keys and states `no_synthetic_liquidation_events=true`. The Funding/OI panel uses V2-native funding/open-interest keys plus the CoinAnk public status payload path.

Nansen and LunarCrush panels are disabled until provider clients pass Codex:

- `enabled=false`
- `empty_until_provider_client_codex_pass=true`
- `provider_client_codex_pass_required=true`
- current state with keys present: `KEY_PRESENT_NO_CLIENT_YET`
- `credential_value=NEVER`
- `raw_credentials_allowed=false`

Both alt-data panels preserve the safety pins: they may not override the strict paper-fill gate, authorize live/canary, or place orders.

## Network And Redis Boundary

The reviewed contract path does not import or load:

- `urllib.request`, `requests`, `httpx`, `aiohttp`, `websockets`, or `ccxt`
- `nansen_client`
- `lunarcrush_client`
- `binance_top10_dashboards`

The source scan found no provider API call, Binance order endpoint, test-order endpoint, cancel/modify endpoint, leverage/margin endpoint, Redis import, or Redis write call in this contract packet.

## Safety

Codex verified:

- raw local secret-value hits in reviewed source/worklog/public payloads: `0`
- `provider_network_calls_attempted=false`
- `provider_clients_implemented=false`
- `alternative_data_dashboards_enabled=false`
- `raw_values_exposed=false`
- `paid_tier_enabled=false`
- `writes_old_redis=false`
- `exchange_mutation=false`
- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`

No checkpoint compatibility or policy architecture parity is claimed.

## Governors

Standing governors remain ready:

- `CODEX_8H_WAR_ROOM_REVIEW_GOVERNOR_READY`
- runtime GO/NO-GO: `READY`
- website GO/NO-GO: `PASS`
- overall GO/NO-GO: `READY`
- `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY`
- fail blockers: none

## Validation

- Focused tests: `7 passed`.
- `py_compile`: PASS.
- Exact dashboard-order validation: PASS.
- JSON payload validation: PASS.
- Raw secret-value scan: PASS, `0` hits outside `.local_secrets`.
- Network/provider-client import check: PASS.
- Exchange mutation scan: PASS.
- Redis write scan: PASS, no Redis writes in this contract path.
- Approval drift scan: PASS.

## Final Decision

`V2_TOP10_MARKET_AND_ALTDATA_DASHBOARD_CONTRACTS_CODEX_PASS`
