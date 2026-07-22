# CoinAnk Plan3 runtime projection checkpoint — 2026-07-21

## Identity

- Source branch: `codex/liquidation-levels-bridge-remediation-20260721`
- Projected source commit: `a177e142bc1cbceb45f3bad2b5244ed409d94f0b`
- Active service: `ai-bot-v2-coinank-live-direct.service`
- Projection scope: three files only; no order, margin, leverage, or execution
  path was changed.

## Exact projected files

| Path | Active and committed SHA-256 |
|---|---|
| `v2/backend/app/services/altdata/coinank_scheduler.py` | `f87ffd8f0b10492fff7cbd135417d0f9712f96dbcfd934e29afd45b93e2a56d4` |
| `v2/backend/app/services/altdata/coinank_receipts.py` | `dc32f1c1c066401a9fbdb74fc570043a955aa37d83dfd2d5eca8afac1daf6f97` |
| `v2/legacy_owned_runtime/ingest/live_coinank.py` | `ec626727b6d6bd0316bbf334e295b06254a283197ad22785920423061715fff1` |

The service was stopped before projection because its unit uses
`Restart=always`. Dependencies were projected in scheduler, receipt, producer
order, then byte-compared with the pushed branch and compiled using the exact
service interpreter before restart.

## Provider-free dry plan

The dry plan used the service working directory, interpreter, and Python path.
It did not call CoinAnk.

- active supported endpoint families: 53;
- total parameter sets: 3,232;
- `openInterest_kline` parameter sets: 960;
- current adaptive runtime symbols: 160;
- distinct 5-minute OI lanes: 160;
- 5-minute venue values: exactly `Binance`;
- 5-minute product type values: exactly `SWAP`;
- 5-minute requested row sizes: exactly `3`;
- validator warnings: 0;
- `/api/liqMap` or liquidation-heatmap references: 0.

The universe changed from the earlier 159-symbol snapshot to 160. No code or
configuration threshold was edited to accommodate the new symbol. The
canonical resolver and lane scheduler adapted automatically.

## Deployment-discovered validator repair

The first dry plan revealed that the old diagnostic validator retained a
static symbol allowlist even though the OI plan used the adaptive universe.
The validator was log-only and would not have dropped requests, but it would
have emitted one warning per dynamic symbol and mirrored that noise to Redis.

Commit `a177e142bc` binds the `openInterest_kline` validator membership to the
exact symbol set emitted by its current plan. Other endpoint families retain
their existing allowlists. Focused tests prove that a planned dynamic symbol
is accepted, an unplanned symbol is warned, and the same symbol remains warned
for an unrelated endpoint.

Validation:

- CoinAnk receipt/scheduler focused suite: 38 passed;
- changed test lint: passed;
- producer compilation: passed;
- diff whitespace validation: passed;
- the legacy runtime's existing repository-wide Ruff debt was not reformatted
  or broadened as part of this repair.

## First live scheduler slice

After restart, systemd reported active/running, PID `3061007`, and
`NRestarts=0`. The first `openInterest_kline` scheduler status reported:

- classification: `WARMING_CADENCE`;
- lane count: 160;
- requested this tick: 27;
- successful this tick: 27;
- causally fresh successes: 27;
- fresh coverage: 0.16875;
- cursor: 0 to 27;
- derived calls required for the freshness SLA: 27;
- derived call budget: 27;
- estimated revisit: 540 seconds;
- remaining non-surface OI budget: 18 calls.

`WARMING_CADENCE` is the truthful state after the first rotation. It must not
be relabeled green until successful causal receipts cover the complete current
lane set within the measured freshness window.

## Strict adapter proof

An exact Redis GET plus Redis server `TIME` reopened
`latest:coinank:open_interest:AAVEUSDT:5m`. The committed strict Plan3 adapter
accepted the bytes and produced:

- endpoint: `openInterest_kline`;
- exchange: `Binance`;
- product type: `SWAP`;
- request start: `1784686684235` ms;
- response observed: `1784686684500` ms;
- consumer observed: `1784686747940` ms;
- finalized rows admitted: 2;
- latest feature cutoff: `1784686500000` ms;
- unit: `base_asset`;
- raw SHA-256:
  `38d8e9d70d472bd63094ae725621a38771c0efed962bb2deb00a95ec712cc6af`.

The strict adapter excludes a bar whose close is not strictly before request
start. It never treats observed forced-liquidation events as prospective open
position levels.

## Remaining boundary

This checkpoint proves the Plan3 OI producer is live and causally usable. It
does not claim that a prospective liquidation surface is published or trainer
authorized. The next family must atomically bind candles, mark price, Plan3
OI, authenticated exchange bracket evidence, model output, and a postcommit
consumer reopen receipt. Missing or stale optional liquidation evidence must
remain masked rather than fabricated or allowed to stop core training.
