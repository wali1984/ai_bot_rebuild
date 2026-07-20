# Ingestor Runtime Truth and Trainer-Admission Audit

Audit date: 2026-07-20

Evidence cutoff: 2026-07-20T22:29:03Z

Scope: Binance-native market data, direct order book, trade tape, KuCoin,
CoinGlass, CoinAnk, liquidation, cross-exchange, microstructure, whale-wall,
public-intelligence, dynamic-universe, scoring, and alt-confluence paths.

This is a dated runtime audit, not a claim that a running service is safe for
training. It supersedes the liveness and trainer-feed conclusions in the
historical `INGESTOR_MASTER_AUDIT.md` wherever they conflict. CoinAPI and
Moralis have separate active hardening reviews and are intentionally not
re-adjudicated here.

## Decision vocabulary

| Decision | Exact meaning |
|---|---|
| `GO_PHYSICAL` | The observed producer has useful physical data. This does not grant trainer, prediction, paper, or live authority. |
| `HELD` | Some source evidence is useful, but a named contract, receipt, coverage, clock, deployment, or cross-source proof is missing. |
| `STOP_TRAINER` | The data must not populate the model ABI or make a snapshot trainer-consumable. |

The immutable temporal rules are independent of market adaptivity:

1. A source value may be used only when its exact bytes and producer identity
   are bound to a receipt.
2. `event_time`, `ingested_at`, `available_at`, `generated_at`,
   `feature_cutoff`, `decision_time`, and `execution_time` retain distinct
   meanings.
3. `available_at <= decision_time` and
   `MASA feature_cutoff <= PPO decision_time` are mandatory.
4. An interval feature must be final before admission. Rewriting a cache,
   aggregate, bundle, TTL, status, or heartbeat cannot make its source event
   newer.
5. Missing, stale, future-clocked, schema-conflicted, or lineage-invalid data
   is typed unavailable. It is never converted to zero or a neutral signal.

## Keystone trainer finding

The physical producer layer is not the current trainer authorization layer.
`feature_source_registry_v4.py` and `feature_resolution_plan_v4.py` are
audit-only, unwired contracts. They perform no runtime provider read, Redis
read, tensor publication, or trainer admission and keep every downstream
authority false. Therefore a green service, heartbeat, Redis key, or feature
candidate cannot release the trainer.

The trainer remains `STOP_TRAINER` until the runtime path produces all of the
following for one coherent decision snapshot:

- exact source-record identities and immutable CAS bytes;
- authenticated producer/source receipts;
- source-specific temporal and finality validation;
- an exact resolver branch and transform identity per model slot;
- authenticated optional typed-negative evidence instead of synthetic zero;
- an ordered 446-slot value/mask/receipt binding;
- atomic durable publication plus independent postcommit readback; and
- a checkpoint feature-ABI match before training or inference.

## Runtime matrix

| Source family | Physical observation | Trainer decision | Low-level reason |
|---|---|---|---|
| Binance canonical closed OHLCV | `GO_PHYSICAL` | `HELD` | 157/157 symbols were present for 1m, 5m, 15m, 1h, and 4h. Closed-candle finality is enforced in `canonical_candles.py`, and current candles remain separate. The durable label archive and full per-slot publication receipt are not authorized. |
| Binance mark/funding | `GO_PHYSICAL` | `HELD` | Mark normalization can replace an absent provider event clock with a local observation clock; the writer lacks a monotonic source-version fence. The service had a high restart count consistent with its one-shot/restart pattern, so process churn cannot be interpreted as data freshness. |
| Binance native open-interest history | Partial | `STOP_TRAINER` for missing rows | Only 141/157 symbols had history; 23 sampled rows were older than 900 seconds. Coverage and each field's source clock must be admitted independently. |
| Binance native long/short ratio | Present but stale | `STOP_TRAINER` | All 157 keys exceeded 900 seconds; 155 exceeded 3600 seconds; the maximum observed age was about 21.9 hours. The cache reader did not age-check the retained source, while bundle rewrites refreshed TTL and could preserve stale values indefinitely. |
| Direct order-book features | Partial | `STOP_TRAINER` | Raw Binance coverage was 149/157. Two writers publish incompatible semantics to the same feature surface: one computes impact at a USD 1,000 reference and another at USD 10,000. There is no canonical schema owner or monotonic write fence; one parser also treats an unparseable event clock as an unknown age and can admit it. |
| Trade tape | `HELD` | `STOP_TRAINER` for model slots 128-130 | Rotational acquisition produced roughly 78-416 second sample age. Batch `generated_at` can precede later constituent events. Old events are filtered, but future event clocks are not rejected. A fixed large-trade multiplier is also embedded in the feature path. |
| KuCoin public REST | `GO_PHYSICAL` observationally | `HELD` cross-venue; `STOP_TRAINER` direct | Temporal parsing is materially stronger than several other sources, but each cycle covered only a budgeted subset: 153 authorized, 79 fetched, 74 deferred, 4 unsupported in the sampled heartbeat; only 92 symbols had a closed 1m kline. Running process bytes predated relevant worktree changes. |
| CoinGlass | API health `GO_PHYSICAL` | `STOP_TRAINER` | The deployed aggregate supplied a BTC cutoff around 22:00 while included constituents extended to about 22:23, which is a concrete point-in-time aggregation violation. Current worktree code moves the aggregate cutoff toward the maximum constituent cutoff, but had not been reviewed, committed, or deployed at the audit cutoff. Provider support was limited to BTC/ETH/SOL and 1m and has no direct registry label. |
| CoinAnk | Provider API `GO_PHYSICAL` | `STOP_TRAINER` | The running bridge lacked complete event/ingest/availability/cutoff clocks and emitted at least one malformed symbol (`1000FLOKIUSDTUSDT`). Its global aggregate could represent unsupported data as zero. Current worktree repairs were newer than the running process and require coordinated review/deployment. CoinAnk enters scoring/confluence rather than a direct registry slot. |
| Binance liquidation WSS | Observed stream `GO_PHYSICAL` | `STOP_TRAINER` for future-surface slots | The stream is observational and lossy. Worktree changes add clock validation and atomic dedupe but were not deployed. Required ABI slots 68-77, 136-141, and 165 describe future liquidation-surface semantics; retrospective observed clusters cannot truthfully populate them. |
| Liquidation levels/enhanced | `HELD` shadow evidence | `STOP_TRAINER` | Worktree code improves ordering, future-clock rejection, typed missingness, and ACK-after-publish. The enhanced runtime still represented retrospective material as eligible. The corrected enhanced path must remain shadowed until a forward open-position surface exists or the ABI/model is explicitly versioned. |
| Cross-exchange analyzer | 1/157 successful | `STOP_TRAINER` | Top-book notional is mislabeled as 24h volume; KuCoin and Binance funding branches read the same generic Binance key; source clocks/freshness are absent; thresholds are fixed; outputs are forcibly labeled synthetic. |
| Microstructure | Raw partial `GO_PHYSICAL` | `STOP_TRAINER` and A+ | Coverage was 149/157 with zero final A+ outputs. The required `v2:market:microstructure:{symbol}` producer was absent, and KuCoin cross-venue evidence was absent. Missing symbols included ACE, ATOM, HEMI, JASMY, NIGHT, PROM, SPELL, and TOSHI. |
| Whale-wall intelligence | Source mismatch | `STOP_TRAINER` | All 157 outputs reported `MISSING_ORDERBOOK_SIDE`. The consumer reads a top-of-book alias but expects depth arrays, then emits neutral numeric values despite missing source depth. Clocks are incomplete and wall rules are fixed. |
| Public intelligence | `GO_PHYSICAL` observationally | `HELD` optional | 157 outputs were present, but constituent providers were partial, only a generation clock was carried, and the composite used fixed weights. |
| Dynamic discovery/scoring/candidate publication | Governance `HELD` | `STOP_TRAINER` | Discovery included a non-ASCII malformed symbol, while validation checked little more than a quote suffix. Some public snapshots stored `provider_freshness_seconds=0`, and scoring trusted it, allowing old data to appear immortal. CoinGlass namespaces do not align. Candidate cutoffs were fixed at 0.10/0.30/0.50 instead of using causal adaptive ranking. Zero-ready supply is a deliberate gate result and must not be bypassed. |
| Alt-data confluence | `HELD` | `STOP_TRAINER` | The running process predated stricter worktree clock checks, covered base pairs at 1m but not the required 5m view, and inherited unsafe provider clocks. Providers must be repaired and deployed before confluence can be revalidated. |

## Critical source-level defects and change impact

### Native long/short TTL resurrection

Observed path:

```text
provider payload with old event_time
  -> cached long/short object
  -> native bundle reconstruction
  -> new bundle write / TTL refresh
  -> heartbeat sees a cache-primary field
  -> physically present value appears live although its source event is old
```

A change to cache or bundle TTL alone affects key visibility, not source
freshness. The repair must preserve the original clocks, compute adaptive
cadence from authenticated observations, reject future/invalid ordering, mark
only the affected field unavailable, and prevent it from satisfying the live
heartbeat. This repair must not create trainer authority.

### Order-book schema collision

Two independent writers use one logical feature surface while calculating
different quantities. Any downstream change to impact, imbalance, liquidity,
whale-wall, microstructure, slippage, sizing, or execution-cost features can
therefore change meaning depending on which writer won the last race.

The fix requires one canonical owner and versioned schema, an exact source
event/version monotonic fence, authenticated depth rather than a top-only
alias for depth consumers, and typed nulls for unavailable sides. Merely
choosing the most recent Redis value is insufficient.

### CoinGlass aggregate clock laundering

An aggregate containing constituent families with different cutoffs cannot
assign an earlier common cutoff to later constituent bytes. Conversely, a
single maximum cutoff must not be used to imply that older individual fields
were generated at that maximum. The aggregate needs both a conservative
envelope cutoff and per-family/per-field clocks and receipts. A consumer must
resolve its selected field against the matching constituent evidence.

### Liquidation ABI semantic mismatch

Observed force-order events and retrospective clusters answer what was
liquidated. The unresolved model slots purport to answer where open positions
will liquidate. These are different random variables. Aliasing one to the
other would silently change the checkpoint feature ABI even if shapes and
types still match.

Safe options are limited to:

1. construct and validate a causal forward open-position/liquidation surface;
2. version the ABI, reclassify/remove those slots, and retrain a compatible
   model; or
3. keep the slots unavailable and the trainer held.

## Coordinated deployment boundary

At the evidence cutoff, KuCoin, CoinGlass, CoinAnk live/global/bridge,
liquidation WSS/levels/enhanced, alt-confluence, and cascade-context processes
were older than relevant current or dirty source bytes. A green unit therefore
proved that an older binary was running, not that the worktree fix was active.

Do not restart those units independently across an incompatible contract.
Review, test, commit, and push a coherent slice first, then restart source and
consumer units in dependency order and verify exact runtime code identity,
clocks, keys, and postcommit readback. The enhanced liquidation path remains
shadow-only.

## Minimal safe repair order

1. Wire authenticated source receipts, exact resolver observations, transform
   identities, and atomic feature publication while keeping trainer authority
   false.
2. Fix native long/short source-age enforcement and TTL resurrection; make
   open-interest coverage and each field's availability truthful.
3. Select one canonical order-book schema/writer, add a monotonic fence, and
   correct whale-wall depth/missingness semantics.
4. Review and deploy coherent source slices: liquidation WSS plus levels;
   CoinAnk live plus global plus bridge; CoinGlass then confluence; KuCoin;
   cascade context. Keep enhanced liquidation shadowed.
5. Repair clocks/freshness in public intelligence, discovery, and scoring;
   enforce canonical symbol grammar; replace fixed candidate thresholds with
   causal, cross-sectional adaptive ranks.
6. Resolve the liquidation ABI semantically rather than by alias.
7. Build the canonical microstructure producer and real KuCoin cross-venue
   path; remove forcibly synthetic cross-exchange output.
8. Generate fresh authenticated receipts, validate the fixed checkpoint ABI,
   release trainer/prediction services one slice at a time, and observe real
   post-release evidence before considering paper candidate gates.

## Operator interpretation

- A heartbeat is evidence that a loop ran; it is not evidence that each field
  is current or admissible.
- A Redis TTL is a storage lifetime; it is not source freshness.
- `active (running)` identifies process state; it does not identify the code
  revision unless runtime code identity is separately attested.
- Zero candidates is currently expected from the fail-closed provenance and
  universe gates. Do not inject candidates, neutral-fill features, or relax
  risk gates to make dashboards green.
- The authorized adaptive paper leverage envelope remains unchanged. Missing
  authenticated growth evidence correctly resolves to its fail-safe branch;
  source repair must not bypass that evidence contract.
- No performance target, including 1000x, can be guaranteed. The engineering
  objective is adaptive opportunity selection under immutable temporal,
  accounting, margin, and loss-containment invariants.

## Audit actions

The audit used read-only unit/service inspection, bounded Redis key reads and
stream metadata reads, source searches, line-level code inspection, file
timestamps, Git status/diffs, and bounded registry queries. Broad wildcard
scans were stopped when they became load-sensitive. No service was restarted;
no external API was called; no Redis key, file, order, position, or trainer
authority was mutated by the audit.
