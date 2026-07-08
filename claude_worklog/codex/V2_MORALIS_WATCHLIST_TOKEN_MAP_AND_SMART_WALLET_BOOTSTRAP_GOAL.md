# CODEX_GOAL_ID: V2_MORALIS_WATCHLIST_TOKEN_MAP_AND_SMART_WALLET_BOOTSTRAP_READY

Add-on to the current same-day goal
(V2_SAME_DAY_PRODUCTION_CUTOVER_PROVIDER_RATE_LIMITED_DATA_FEATURE_TRAINER_PREEMPTIVE_AND_LIVE_CANARY_READY).

REPOSITORY: /home/wali/Desktop/AI BOT REBUILD

## CURRENT STATE RECONCILIATION (verified by Claude 2026-07-08, raw evidence)

Do NOT rebuild what already exists. Verified against the working tree and live Redis:

ALREADY EXISTS AND RUNNING — extend, do not recreate:
- `v2/backend/app/cli/v2_moralis_provider_loop.py` (Phase 5 loop exists)
- `v2/backend/app/services/smart_money_wallets/`: client.py, poller.py, rate_limit.py,
  cu_budget.py, endpoint_registry.py, normalizer.py, publisher.py, health.py,
  streams.py, models.py
- CU ledger live: `v2:provider:moralis:cu_budget_status` (2026-07-08: monthly_limit_cu=2000000,
  daily_allowance_cu=66656, safety_factor=0.8, day_spent_cu=300, tokens_polled=6,
  raw_key_exposed=false)
- Payloads live TODAY: 12 `v2:market:moralis:*` keys (whale_flow / token_transfers for
  LINKUSDT, CRVUSDT, AAVEUSDT, ...), `meta:moralis:last_update` fresh
- `goal_state/V2_SAME_DAY_PRODUCTION_CUTOVER_PROVIDER_RATE_LIMITED_.../phase1_moralis_compute_budget_status.json`

MISSING — this goal's actual scope (all verified absent):
- `v2/config/moralis/` (entire dir): token_contract_map.yaml, excluded_addresses.yaml,
  exchange_wallets.yaml, wallet_watchlist_seed.yaml
- `smart_money_wallets/token_contract_mapper.py`
- `smart_money_wallets/address_classifier.py`
- `smart_money_wallets/wallet_watchlist.py`
- `smart_money_wallets/smart_wallet_scorer.py`
- `smart_money_wallets/streams_registry.py` (streams.py exists; registry + setup check do not)
- `smart_money_wallets/moralis_feature_bridge.py` — NOTE:
  `v2/backend/app/services/provider_features/provider_feature_bridge.py` exists but emits
  ZERO moralis_ features (verified by grep) — Moralis data is not consumed anywhere yet
- `v2/backend/app/cli/v2_moralis_token_map_bootstrap.py`
- `v2/backend/app/cli/v2_moralis_streams_setup_check.py`
- No `v2:moralis:*` Redis keys (token_map / watchlist / smart_wallet_candidates absent)
- Token/wallet selection is currently env-driven (MORALIS_TOKENS / MORALIS_WALLETS) —
  replace with the config/Redis-backed lists below; keep env as emergency override only.

Phase 0 expected-state correction: `actual_payload_count` is NOT 0 (payloads active today);
`token_map_count=0`, `wallet_watchlist_count=0`, `smart_wallet_candidate_count=0`,
`stream_configured=false`. Correct dashboard state is `PAYLOADS_ACTIVE` +
`WATCHLIST_MISSING`, not `CONFIGURED_NO_WATCHLIST`. Never GREEN from key presence alone.

## MISSION

Moralis keys and a rate-limited provider loop exist, but there is no token contract map,
no wallet watchlist, no smart-wallet candidate list, no exclusion lists, no stream
subscription registry, and no feature-bridge consumption. Build the missing Moralis
watchlist bootstrap layer. Moralis must not be shown GREEN until real lists AND payloads
AND feature consumption exist.

DO NOT:
- use Moralis as standalone trade approval
- poll every symbol every minute
- exceed Starter CU/RPS limits (respect the EXISTING cu_budget.py ledger; do not fork a second ledger)
- expose API keys
- call unknown wallets "smart money"
- block core trading because Moralis lists are empty

## Phase 0 — Freeze current Moralis state

Create `goal_state/<GOAL_ID>/phase0_moralis_current_state.json` with:
moralis_api_key_present, moralis_subscription_status, moralis_health_key_exists,
moralis_token_map_count, moralis_wallet_watchlist_count,
moralis_smart_wallet_candidate_count, moralis_stream_configured,
moralis_actual_payload_count_1h, dashboard_color, core_system_blocked.
Use the reconciliation above as the expected baseline.

## Phase 1 — Token contract map bootstrap

Create:
- `v2/config/moralis/token_contract_map.yaml`
- `v2/backend/app/services/smart_money_wallets/token_contract_mapper.py`
- `v2/backend/app/cli/v2_moralis_token_map_bootstrap.py`

Inputs: V2 paper symbol universe, active probation/open positions, top candidate symbols,
majors (BTC, ETH, SOL, BNB, XRP), Moralis token metadata/search/price endpoints,
manual override file. Symbol selection must remain adaptive/market-driven — no hardcoded
static symbol lists beyond the majors seed (see symbol universe policy).

Redis: `v2:moralis:token_map:{symbol}`, `v2:moralis:token_map_status`.

Row fields: symbol, base_asset, chain, contract_address, token_name, token_symbol,
decimals, moralis_supported, mapping_confidence, mapping_source, manual_review_required,
tradeable_mapping_status.

Hard fail: wrong-chain contract silently accepted; conflicting contracts without
confidence; mapping without metadata validation.

## Phase 2 — Exclusion list

Create:
- `v2/config/moralis/excluded_addresses.yaml`
- `v2/config/moralis/exchange_wallets.yaml`
- `v2/backend/app/services/smart_money_wallets/address_classifier.py`

Categories: exchange_hot_wallet, exchange_cold_wallet, bridge, router, lp_contract,
token_contract, vesting_contract, burn_address, deployer, unknown_contract.

Redis: `v2:moralis:excluded_addresses`, `v2:moralis:address_classification:{chain}:{address}`.

Hard fail: exchange wallet counted as smart money; contract counted as smart wallet.

## Phase 3 — Initial wallet watchlist

Create:
- `v2/config/moralis/wallet_watchlist_seed.yaml`
- `v2/backend/app/services/smart_money_wallets/wallet_watchlist.py`

Sources: manual seed, top non-contract token holders (Token API), large transfer
participants, active DEX swap participants. Tiers: T0 max 50, T1 max 250, T2 background.

Redis: `v2:moralis:wallet_watchlist`, `v2:moralis:wallet_watchlist_status`.

Hard fail: empty list marked green; wallets without source; sizes beyond Starter budget.

## Phase 4 — Smart-wallet candidate scoring

Create `v2/backend/app/services/smart_money_wallets/smart_wallet_scorer.py`.

Features: realized_profit_proxy, win_rate_proxy, entry_timing_score, exit_timing_score,
wallet_networth_usd, token_diversity, recent_activity, whale_size_score,
exchange_flow_score, contract_penalty, exchange_wallet_penalty.

Labels: UNKNOWN, WHALE_ONLY, CANDIDATE_SMART_WALLET, VERIFIED_SMART_WALLET,
EXCHANGE_LIKE, CONTRACT_LIKE.

Redis: `v2:moralis:smart_wallet_candidates`, `v2:moralis:smart_wallet_score:{chain}:{address}`.

Hard fail: candidate promoted to VERIFIED without sufficient history; score used as
standalone trade approval.

## Phase 5 — Scheduler integration (EXTEND existing loop)

`v2_moralis_provider_loop.py` already implements polling + rate limiting + CU ledger.
Required changes only:
- consume token_contract_map + wallet_watchlist instead of MORALIS_TOKENS/MORALIS_WALLETS envs
- tiered cadence: T0 wallets history/transfers/swaps 15m, balances/networth 30m;
  T1 1h/2h; token transfers/swaps for active symbols 10m–30m; token holders 6h–24h;
  full universe rotating background only
- keep rps guards (normal<=5, catchup<=10, hard<=30) and the existing daily CU allowance
  (ledger says 66,656/day with 0.8 safety; do not raise)
- publish `v2:provider:moralis:endpoint_status` alongside existing health/usage keys

Hard fail: second/duplicate rate limiter or CU ledger; API key logged; 403 marked green.

## Phase 6 — Feature bridge

Create `v2/backend/app/services/smart_money_wallets/moralis_feature_bridge.py`
(or extend provider_feature_bridge.py — currently has zero moralis features).

Output features: moralis_exchange_inflow_usd, moralis_exchange_outflow_usd,
moralis_net_exchange_flow_usd, moralis_whale_buy_usd, moralis_whale_sell_usd,
moralis_whale_net_flow_usd, moralis_smart_wallet_accumulation_score,
moralis_smart_wallet_distribution_score, moralis_holder_concentration_change,
moralis_token_holder_delta, moralis_dex_buy_pressure_usd, moralis_dex_sell_pressure_usd,
moralis_dex_flow_imbalance_usd, moralis_onchain_risk_score.

Write: `v2:features:moralis:{symbol}:{timeframe}`, `v2:smart_money:signals:{symbol}`.

Rules: missing data => missing_mask=true (never zero-fill); Moralis can block /
reduce-size / require hedge / boost confluence; Moralis can NEVER approve a trade alone
and can NEVER override CoinAnk/CoinGlass/Binance/KuCoin.

## Phase 7 — Streams readiness

Create `smart_money_wallets/streams_registry.py` +
`v2/backend/app/cli/v2_moralis_streams_setup_check.py` (streams.py exists — build on it).

Status fields: webhook_url_configured, webhook_signature_validation, stream_count,
watched_wallets, watched_contracts, last_stream_event.
Do not enable streams until webhook endpoint exists, signature validation is tested,
and no raw secrets are exposed. `streams_configured=false` / `streams_ready=false` until then.

## Phase 8 — Dashboard/iOS

Patch web + iOS provider panels to show: key present, subscription/auth status, dashboard
color, CU used today / remaining estimate, current RPS, token map count, wallet watchlist
count, smart-wallet candidate count, actual payload count, last success/error, feature
contribution.

State machine: CONFIGURED_NO_WATCHLIST -> TOKEN_MAP_BUILDING -> WATCHLIST_BUILDING ->
PAYLOADS_ACTIVE -> FEATURE_CONSUMED. GREEN only at PAYLOADS_ACTIVE with non-empty lists;
FEATURE_CONSUMED once trainer/risk actually read the features.

## Phase 9 — Validation

```bash
python -m py_compile v2/backend/app/services/smart_money_wallets/*.py \
  v2/backend/app/cli/v2_moralis_token_map_bootstrap.py \
  v2/backend/app/cli/v2_moralis_provider_loop.py \
  v2/backend/app/cli/v2_moralis_streams_setup_check.py
.venv/bin/pytest -q v2/backend/tests/unit/services/smart_money_wallets \
  v2/backend/tests/unit/cli/test_v2_moralis_provider_loop.py
npm --prefix v2/frontend run typecheck && npm --prefix v2/frontend run build
swift test --package-path v2/mobile
rg -n "MORALIS_API_KEY|x-api-key|api[_-]?key" v2/frontend/src v2/mobile \
  goal_state/V2_MORALIS_WATCHLIST_TOKEN_MAP_AND_SMART_WALLET_BOOTSTRAP_READY \
  --glob '!*.example' --glob '!*.md'
```

## Final marker

`V2_MORALIS_WATCHLIST_TOKEN_MAP_AND_SMART_WALLET_BOOTSTRAP_READY` requires:
token map exists; watchlist exists or honest WATCHLIST_MISSING blocker; single rate/CU
limiter (the existing one); endpoint registry wired to lists; feature bridge emitting with
missing_mask semantics; dashboard/iOS show actual counts; no API key exposure; Moralis not
green without payloads+lists. Otherwise emit
`V2_MORALIS_WATCHLIST_TOKEN_MAP_AND_SMART_WALLET_BOOTSTRAP_BLOCKED` with blocker list.

## Practical first T0 seed (bootstrap day)

Majors BTC, ETH, SOL, BNB, XRP; PYTH, FLOKI/1000FLOKI, JST, AUCTION; all open probation
symbols; top-20 positive-edge candidates; top-20 CoinAnk/CoinGlass pressure symbols.
Per mapped token: metadata -> price -> holders -> transfers -> swaps -> extract top
non-contract holders + large transfer participants + active swap wallets -> classify
exclusions -> score candidates -> promote only after history.
