# V2 Alternative-Data Integration Plan (Clean, Plan-Only)

GO/NO-GO: V2_ALTERNATIVE_DATA_INTEGRATION_PLAN_READY

This packet is PLAN-ONLY. No provider clients are implemented. No
external network calls are issued. No raw API keys are read, written,
logged, exposed in payloads, exposed in stdout, exposed in task
descriptors, or surfaced in the frontend. No legacy is modified. The
existing V2 paper/shadow runtime (full observation builder, continuous
remediation governor, liquidation WSS persistent daemon, legacy log
observer, account permission soak) is not paused, throttled, or
reconfigured. live_gate remains blocked_human_only. live_symbols
remains [].

## Approved providers in this lane

The integration lane covers exactly the following six providers:

1. nansen — on-chain smart-money / entity flow (free + paid tiers)
2. lunarcrush — off-chain social sentiment / momentum (free + paid tiers)
3. arkham_future — entity forensics, future-only, no integration today
4. binance_existing — already-integrated native V2 market baseline
5. coinank_existing — already-integrated native V2 funding / OI / aggregate
6. liquidation_wss_existing — already-integrated public Binance Futures
   forceOrder stream, paper/shadow daemon active under systemd

No other provider is included in this lane. Provider docs referenced
for plan purposes only:

- Nansen API docs: https://docs.nansen.ai/
- LunarCrush developer API: https://lunarcrush.com/developers/api

These URLs are documented for the plan reviewer. No client calls them
in this packet.

## Three-layer architecture

Layer 1 — Predictive baseline (already native V2)

- Sources: Binance / KuCoin / CoinAPI / CoinAnk / TA composite /
  liquidation WSS persistent daemon.
- Already integrated into the V2 native runtime. No new client added.
- Provides: 12h volume leaders, 12h most traded, 12h volatility
  leaders, futures liquidation tape, funding / open interest
  intelligence.

Layer 2 — On-chain alternative signals

- nansen (free / paid)
- arkham_future (future-only placeholder, no integration today)
- Produces per-symbol smart-money flow scores and (future-only)
  entity-flow forensics scores.

Layer 3 — Off-chain alternative signals

- lunarcrush (free / paid)
- Produces per-symbol social-volume / sentiment / momentum scores.

The three layers are isolated. A failure or rate-limit in Layer 2 or
Layer 3 cannot interrupt Layer 1, the V2 paper/shadow runtime, the
full observation builder, the continuous remediation governor, the
account permission soak, or the legacy log observer.

## V2 Redis namespace contract

All alternative-data writes target only the V2 namespace. No old
Redis key is written.

- v2:altdata:nansen:status — global Nansen heartbeat / budget /
  availability
- v2:altdata:nansen:symbol:{symbol} — per-symbol Nansen feature
  dict + missing/stale flags
- v2:altdata:lunarcrush:status — global LunarCrush heartbeat /
  budget / availability
- v2:altdata:lunarcrush:symbol:{symbol} — per-symbol LunarCrush
  feature dict + missing/stale flags
- v2:altdata:arkham:status — Arkham future-state placeholder;
  remains absent until operator approves implementation
- v2:altdata:symbol_score:{symbol} — aggregated alt-data score per
  symbol
- v2:symbol_universe:altdata_candidates — candidate symbol set from
  alt-data ranking

## Rate-limit policy

Default tier is `free`. Paid endpoints stay disabled until both env
vars flip and Codex validates the paid endpoint contract.

Free-tier defaults per provider:

- nansen: cache TTL 600s, per-symbol cooldown 300s, daily budget
  1000 requests
- lunarcrush: cache TTL 600s, per-symbol cooldown 300s, daily budget
  1000 requests
- arkham_future: no rate-limit defined; future-only placeholder

Paid-tier defaults per provider (only after operator + Codex enable):

- nansen: cache TTL 60s, per-symbol cooldown 30s, daily budget
  50000 requests
- lunarcrush: cache TTL 60s, per-symbol cooldown 30s, daily budget
  50000 requests
- arkham_future: undefined until operator-approved

Cross-cutting rate-limit rules:

- Stale-but-safe fallback: if cache hit is older than TTL but still
  fresh enough to mark stale, the consumer uses it with stale_flag
  set rather than blocking.
- Per-symbol cooldown is enforced before any provider call.
- Daily request budget decrements on every successful call; on
  exhaustion the lane falls back to cached signals only.
- Provider failure isolation: no provider failure may break V2
  runtime. The orchestrator never blocks on alt-data provider
  health.
- Batch prioritization: requests are issued in order of paper
  position size first, then symbol-universe rank.

## Paid-upgrade single-switch design

Paid tier flips with exactly two env changes:

- ALT_DATA_TIER=paid
- ALT_DATA_ENABLE_PAID=true

When both are set, paid endpoints remain disabled at runtime until
Codex validates the provider's paid endpoint contract and config.
No code rewrite is required. Free and paid capabilities are
documented separately per provider in the provider registry.

## Credential handling

Credentials are read at runtime only from the operator-managed
`.local_secrets/` directory (gitignored), using the secret-decision
pattern that probes the env-var name and never the value. The plan
imposes these invariants:

- No raw credentials in this packet.
- No raw credentials in any V2 payload.
- No raw credentials in any log line, stdout, or stderr.
- No raw credentials in any task descriptor.
- No raw credentials in any frontend payload.
- No raw credentials in any worklog file.
- Credential redaction is required in every status payload that is
  emitted to the operator dashboard.
- Credential env-var name documented only:
  - NANSEN_API_KEY (documented, value not present in packet)
  - LUNARCRUSH_API_KEY (documented, value not present in packet)
  - ARKHAM_API_KEY (documented, value absent until operator provides
    it)

## Five integration points

1. Provider clients (NOT IMPLEMENTED in this packet)
   - Future: paper/shadow-only client modules under
     v2/backend/app/services/altdata_clients/ that emit signals to
     v2:altdata:* and never to old Redis.
2. Symbol universe automation (NOT MODIFIED in this packet)
   - Future: v2 symbol universe consumes
     v2:symbol_universe:altdata_candidates as one input among
     dynamic-discovered / training / paper buckets. live_symbols
     remains [].
3. Feature family integration (NOT WIRED in this packet)
   - The `altdata` feature family is kept separate from the
     1911-dimension legacy observation parity. checkpoint
     compatibility is not claimed. policy architecture parity is
     not claimed. The slot allocation is an operator decision
     pending Codex dimension-contract review.
4. Trainer / Risk / Orchestrator overlay (NOT MODIFIED in this
   packet)
   - Paper/shadow-only consumption. The alt-data score may filter
     or annotate decisions, but it cannot override the strict
     P0.2F paper-fill gate, cannot authorize live or canary,
     cannot place / cancel / modify exchange orders, and cannot
     modify legacy.
5. Operator dashboard (CONTRACT-ONLY in this packet)
   - 10 top panels are contracted in
     alternative_data_dashboard_contract.json. No frontend panel
     rendering changes ship here.

## Top-10 dashboard panels (contracted only)

1. Binance 12h Volume Leaders
2. Binance 12h Most Traded
3. Binance 12h Volatility Leaders
4. Futures Liquidation Tape
5. Funding / Open Interest Intelligence
6. Nansen Smart Money Flow
7. LunarCrush Social Momentum
8. Arkham Entity Watchlist Future
9. V2 Symbol Universe Alt-Data Ranking
10. V2 Trainer / Risk Decision Overlay

Each contracted panel requires missing / stale flags, must never
include raw credentials in the payload, and must surface the source
v2:* keys. Panel 10 explicitly affirms that alt-data cannot override
the strict paper-fill gate, cannot authorize live or canary, and
cannot place orders.

## Codex review checklist

The Codex reviewer is asked to verify:

- The lane lists exactly the six approved providers and nothing
  else.
- No provider outside the approved list appears in any artifact
  (registry, feature contract, symbol universe contract, dashboard
  contract, plan, GO_NO_GO, public dashboard payload).
- The lane never writes old Redis keys.
- The lane never instructs exchange order placement / cancellation /
  modification.
- The lane never authorizes live, canary, legacy shutdown, or Redis
  trim.
- The lane never creates approval tokens.
- No raw credentials exist anywhere in the packet.
- Free vs paid tier capabilities are defined separately per provider.
- Single-switch paid upgrade gates paid endpoints behind both env
  changes plus a Codex validation step.
- Feature family integration is explicitly separated from the 1911
  legacy observation parity, with checkpoint_compatibility_claimed =
  false and policy_architecture_parity_claimed = false.
- The trainer / trader / risk / orchestrator constraints reject any
  paper-fill-gate override, live or canary authorization, or order
  placement.
- The dashboard contract requires missing / stale flags on every
  panel and forbids credentials in any panel payload.

## Safety invariants

- live_gate = blocked_human_only
- live_symbols = []
- approves_live = false
- approves_canary = false
- approves_legacy_shutdown = false
- approves_redis_trim = false
- approves_paper_only_shutdown_acceptance = false
- creates_external_feed_today = false
- creates_credentials_today = false
- writes_old_redis = false
- exchange_mutation = false
- modifies_legacy = false
- loads_any_blob = false
- pauses_v2_runtime = false
- interrupts_soak = false
- claims_checkpoint_compatibility = false
- claims_policy_architecture_parity = false
- no_fake_compatibility_claim = true

## Implementation state

This packet is plan-only. No provider clients are implemented. No
symbol universe automation changes are wired. No full observation
builder changes are wired. No frontend panel rendering ships in
this packet. No task is dispatched to start provider client
implementation in this packet.

## Outputs

- claude_worklog/final_readiness/v2_alternative_data_integration/latest/GO_NO_GO.md
- claude_worklog/final_readiness/v2_alternative_data_integration/latest/V2_ALTERNATIVE_DATA_INTEGRATION_PLAN.md
- claude_worklog/final_readiness/v2_alternative_data_integration/latest/alternative_data_provider_registry.json
- claude_worklog/final_readiness/v2_alternative_data_integration/latest/alternative_data_feature_contract.json
- claude_worklog/final_readiness/v2_alternative_data_integration/latest/alternative_data_symbol_universe_contract.json
- claude_worklog/final_readiness/v2_alternative_data_integration/latest/alternative_data_dashboard_contract.json
- v2/frontend/public/v2_alternative_data_integration/latest/operator_dashboard_payload.json
