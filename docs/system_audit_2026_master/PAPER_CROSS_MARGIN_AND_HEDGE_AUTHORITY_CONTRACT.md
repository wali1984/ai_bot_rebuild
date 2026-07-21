# Paper Cross-Margin and Adaptive-Hedge Authority Contract

Status: implementation contract for the paper-only path. Nothing in this
document authorizes a live order, exchange leverage change, margin-mode change,
transfer, or withdrawal.

## Scope and hard boundaries

- Runtime owner: `v2_trade_management_paper_loop`.
- Lifecycle/account owner: `paper_trade_management.lifecycle`,
  `position_state`, and `margin_accounting`.
- Portfolio stress owner: `risk.cross_margin_liquidation`.
- Hedge-first risk owner: `risk.hedge_first_controller`.
- Cascade owner: `v2_portfolio_cascade_guard_loop` plus
  `risk.portfolio_cascade_directive`.
- Every output in this path must carry `paper_only=true` and
  `places_real_order=false`. Queue envelopes additionally carry
  `routes_to_live=false`.

## Time semantics

These clocks are intentionally distinct:

| Field | Meaning | Ordering requirement |
|---|---|---|
| `event_time` | Exchange event time from Binance `E` | First source clock |
| `generated_at` | Local normalization completion | `event_time <= generated_at` |
| `available_at` | Redis publication/release time | `generated_at <= available_at` |
| `decision_time` | Consumer decision boundary | `available_at <= decision_time` |
| `consumer_observed_at` | Completion of the Redis read/validation | `decision_time <= consumer_observed_at` |
| lifecycle `generated_utc` | Lifecycle reconciliation decision | Must not precede source availability |
| directive `valid_until` | Derived handoff expiry | Recomputed; never inferred from Redis TTL |

A missing, naive, future, reversed, or stale authority clock fails closed. A
receipt-time substitution is not permitted for missing exchange event time.

## Mark-price authority

Producer:
`v2/backend/app/cli/v2_binance_mark_price_wss_seeder.py`.

Redis key: `v2:market:mark_price:{SYMBOL}`.

Required exact contract:

- schema: `binance_usdm_mark_price_wss_v1`;
- source: `binance_usdm_wss_mark_price_all_symbols`;
- transport: `websocket_primary`;
- stream: `!markPrice@arr@1s`;
- authentication boundary:
  `BINANCE_USDM_TLS_WSS_MARK_PRICE_PUBLIC_STREAM_V1`;
- cadence policy: `BINANCE_USDM_MARK_PRICE_STREAM_1S_CADENCE_V1`;
- canonical SHA-256 over every payload field except `evidence_sha256`;
- positive finite mark and complete ordered clocks;
- source freshness budget equal to the declared source update interval.

Ticker and candle values may support non-authoritative paper telemetry. They
cannot authorize maintenance margin, liquidation, cascade force-close, or
hedge-fill pricing. A hedge fill is priced from a newly authenticated mark at
the synthesis decision boundary; the directive's trigger-time mark is not
relabelled as a current execution mark.

## Maintenance bracket and reconstruction binding

Maintenance arithmetic requires authenticated Binance USD-M leverage-bracket
evidence selected for the exact marked position notional. The persisted row
binds the bracket, source/account environment, authentication evidence, source
availability/expiry, current check, decision time, notional range, current
mark receipt, position ID, and position generation.

The open-position reconstruction hash includes all current mark/bracket fields
and all hedge-pair linkage fields. For a hedge child, the following must be
present and reconstruction-bound:

- `hedge_parent_id`;
- `hedge_parent_generation_id`;
- `hedge_child_id`;
- `hedge_pair_session_id`;
- `hedge_ratio`.

For a `HEDGE_PENDING` parent, the complete adaptive directive-validity envelope
is also reconstruction-bound. Restart restoration therefore cannot silently
replace a parent generation, session, pair link, or pending expiry.

## Cross-margin account and stress contract

Cross positions are partitioned from isolated positions. Cross wallet balance
is same-ledger starting equity plus realized net PnL. Cross equity is that
wallet balance plus current cross-position unrealized PnL. Used/free margin,
maintenance, and PnL must reconcile to the exact ledger rows before portfolio
stress can become authority.

Stress authority is a versioned, content-hashed adaptive envelope from
`adaptive_portfolio_stress_controller`. It binds source observation hash,
policy/cadence versions, freshness and guard lifetime, recovery reserve,
scenario symbol moves, and hedge-candidate maintenance brackets. Missing,
stale, malformed, future, mode-mismatched, or arithmetically unreconciled
stress evidence blocks authority.

Per-position close relief is side-aware and scenario-aware:

`marginal_stress_buffer_relief_if_closed_usd = shocked_maintenance_margin_usd - shocked_position_pnl_delta_usd`

The cascade guard chooses only positive relief in the worst authenticated
scenario, ranks relief descending, and selects the smallest prefix needed
toward the adaptive recovery reserve. Isolated positions are never selected by
the cross guard.

## Adaptive hedge directive lifetime

The former fixed 300-second directive age check and fixed 600-second pending
deferral are not authority. The validity producer now requires both:

1. an observed lifecycle-to-lifecycle cadence (`previous generated_utc` to the
   current lifecycle decision); and
2. the current authenticated mark receipt's freshness budget.

Effective authority lifetime:

`min(immutable maximum safety lifetime, observed lifecycle update cadence + authenticated mark freshness budget)`

The immutable maximum is 600 seconds. It is a fail-safe ceiling only: it can
shorten a poisoned/stalled cadence observation but cannot make an otherwise
invalid directive valid. The consumer re-derives the observed cadence, source
cadence identity, effective budget, and `valid_until`; it also requires the
content hash and exact paper session/parent generation.

Redis TTL is derived from the remaining valid lifetime and is labelled
`OPERATIONAL_GARBAGE_COLLECTION_ONLY_NOT_VALIDITY_AUTHORITY`. Retrying a
transiently unavailable parent fill or mark uses Redis `KEEPTTL`, so a retry
cannot extend authority. Expired or invalid directives are removed. Successful
directives are removed while unrelated retryable directives remain in the same
queue update.

## Pair admission and close atomicity

A synthesized hedge can open only when all of the following match the current
state exactly:

- base symbol and opposite side;
- current parent position ID;
- current parent generation ID;
- parent quantity times directive hedge ratio;
- active paper session and hedge-pair session;
- child fill identity;
- fresh authenticated synthesis mark.

There is no symbol-only fallback to an older parent fill.

Pair HOLD/UNWIND/CLOSE evaluation may observe telemetry from fallback prices,
but no pair mutation is allowed unless both legs were updated from the current
authenticated mark at the lifecycle decision time. Missing or fallback mark
authority holds the pair and keeps the parent hedge-protected.

`CLOSE_BOTH` is copy-on-write. Both legs run their close preflight against a
deep-copied position map. The real map, close events, and outcome labels are
updated only when both staged legs return complete clean close/outcome pairs.
If either leg fails, both real positions remain open and an atomic dirty-close
block is emitted. An orphan hedge is marked unwound only after its hedge close
actually succeeds.

## Change-impact map

| Change | Direct consumers | Required regression focus |
|---|---|---|
| Mark receipt schema/hash/clocks | lifecycle, liquidation, cascade, hedge synthesis | future/stale/tamper/fallback rejection |
| Bracket selection/binding | position state, margin accounting, liquidation | exact notional/mark/generation and HMAC evidence |
| Margin mode canonicalization | ledger, cross partition, allocator status | isolated exclusion and cross reconciliation |
| Stress scenario or recovery reserve | liquidation and cascade directive selection | worst-scenario relief ordering and smallest prefix |
| Hedge linkage fields | reconstruction, admission, pair manager | wrong ID/generation/session and restart symmetry |
| Directive cadence/freshness | lifecycle pending state, Redis handoff, synthesis | fast/slow adaptation, hard ceiling, expiry, `KEEPTTL` |
| Close-event construction | pair close, ledger totals, trainer outcomes | injected one-leg failure and no partial commit |

## Verification evidence

Focused tests cover:

- fast and slow observed cadence producing different validity budgets;
- expiry immediately after the derived boundary;
- missing cadence and unauthenticated mark failing closed;
- the immutable ceiling constraining a stalled observation;
- Redis TTL tracking remaining lifetime without granting or extending authority;
- successful queue consumption plus atomic retention of an unrelated retry;
- expired queue work being deleted without a fill;
- `HEDGE_PENDING` validity surviving reconstruction and releasing the ATR stop
  after adaptive expiry;
- injected second-leg `CLOSE_BOTH` failure preserving both positions and
  emitting no pair close.
