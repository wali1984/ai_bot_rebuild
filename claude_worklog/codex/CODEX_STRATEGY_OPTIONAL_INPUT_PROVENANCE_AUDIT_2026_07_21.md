# Codex Strategy Optional-Input Provenance Audit — 2026-07-21

## Executive result

This slice audited the strategy/canonical hypothesis publisher's remaining
direct optional Redis inputs: fair-value gaps (FVG), liquidity zones, sweep
risk, liquidation context, order-book context, trade-tape context, and the
derived microstructure trust envelope.

**Release decision: NO-GO for every directly read optional input.** None of
the audited compatibility projections has an independent consumer resolver
that can prove the exact retained bytes read by the strategy, the unique
writer/revision that produced those bytes, and a successful post-commit
readback receipt. Several projections also have incomplete or ambiguous
clocks. Self-declared booleans, timestamps, hashes, and quality scores inside
the same mutable payload do not authenticate that payload.

The code change in this slice therefore masks these inputs at the strategy
boundary and does not read their raw keys. Missing optional data remains
missing; it is not zero-filled. It cannot create a strategy family, raise a
trust score, satisfy a liquidation gate, improve economics, or appear in the
provider-feature hash set. Every resulting hypothesis remains paper-only,
consumer-ineligible, trainer-ineligible, and unavailable until a real
post-commit output receipt exists.

This is not a guarantee of a 1000x result. It is an evidence-integrity control
needed to ensure the system makes the best defensible use of available data
without training or scoring on mutable, unauthenticated projections.

No service was deployed, restarted, unmasked, or permitted to touch a live
exchange in this slice.

## Scope and immutable baseline

- Repository baseline: `f0ce93da8e16638274255bc59bd2dec1e73f8b33`
- Audit branch: `codex/strategy-optional-input-audit-20260721`
- Strategy consumer:
  `v2/backend/app/services/strategy_supply/edge_hypothesis_generator.py`
- Scope is limited to the strategy publisher's optional input boundary and
  its unit/CLI contract tests.
- The native-TA resolver from the baseline was retained unchanged.
- CoinGlass, Moralis, current-price, trainer, allocator, risk, orchestration,
  service units, and exchange execution implementations were not modified.

## Required point-in-time and retained-artifact contract

An input is eligible for canonical strategy or trainer admission only when a
consumer can verify all of the following from an independent boundary:

1. `event_time` is the economic observation time.
2. `ingested_at` is when the producer actually received/persisted it.
3. `available_at` is when the exact retained artifact was committed and
   observable to the consumer. It is not an alias for event time.
4. `feature_cutoff` is the latest economic input included in the feature.
5. `decision_time` is captured after all input reads and satisfies
   `available_at <= decision_time` and `feature_cutoff <= decision_time`.
6. `generated_at` is captured after the feature/output computation; it does
   not substitute for any earlier clock.
7. Candle-backed inputs use only final candles whose close time has passed.
8. The consumer performs one exact binary read, verifies strict decoding and
   schema, identifies the immutable revision/window, hashes the exact bytes,
   and validates an independent post-commit readback receipt for those bytes.
9. Writer identity is unambiguous. A compatibility key with multiple writers
   is not a canonical evidence source.
10. Missing, stale, invalid, future-dated, partially formed, or unreceipted
    data is masked rather than converted to a neutral numeric value.

The required temporal order is:

```text
candle_close_time <= event_time <= ingested_at <= available_at <= decision_time <= generated_at
feature_cutoff <= decision_time
output generated_at <= output post-commit available_at
```

Not every non-candle source needs a candle clock, but every admitted source
needs the applicable clocks with their actual meanings.

## Low-level input matrix

| Input | Candidate Redis projections formerly read | Producer/path evidence | Clock/finality finding | Retained-artifact finding | Verdict and fallback |
|---|---|---|---|---|---|
| FVG | `v2:market:fvg:{symbol}:{timeframe}` | Native feature loop calls `compute_fvg` and writes the projection (`v2_feature_pipeline_native_loop.py:1830-1844`). The paper loop also contains a writer (`v2_trade_management_paper_loop.py:6597`). | Upstream selection is based on closed candles, but this output has no independently verified exact source window. `row_available_at` may fall back to event time. Optional order-book/tape/trust/HTF inputs are mutable. | Direct Redis `SET`; no exact-byte receipt, immutable revision, or consumer CAS. Writer ambiguity exists. | **NO-GO.** Masked as absent; cannot create `fvg_retest` or confluence fields. |
| Liquidity zones | `v2:market:liquidity_zones:{symbol}` | Native loop calls `compute_liquidity_zones` and writes at `v2_feature_pipeline_native_loop.py:1759-1776`; paper loop has another writer at `v2_trade_management_paper_loop.py:6588`. | Closed-candle ancestry exists, but no exact window identity is authenticated at consumption. The common market-structure clock helper permits aliases that collapse economic and availability clocks. | Mutable `SET`, no post-commit receipt; multiple writers. | **NO-GO.** Masked; cannot alter zone-distance or structure context. |
| Sweep risk | `v2:market:sweep_risk:{symbol}:{timeframe}` | Native loop republishes the liquidity-zone payload under the sweep key (`v2_feature_pipeline_native_loop.py:1891-1896`). Feed-quality monitor also publishes a separately derived sweep envelope. | The alias does not prove which underlying candle/book/liquidation/tape snapshot was observed together. | Mutable raw projection with no receipt; semantic collision between different producer meanings. | **NO-GO.** Masked; cannot create `liquidity_sweep_reversal` or relax aged-liquidation handling. |
| Liquidation context | `v2:liquidations:levels:{symbol}:{timeframe}` plus five compatibility aliases enumerated in code | WSS ingestion has exchange event times and local ingestion timestamps; the levels engine emits `liquidation_updated_ts`, `liquidation_last_event_ts`, stale/no-event markers, JSON `SET`, and hash mirrors (`v2_liquidation_levels_engine.py:420-424,615-636`). | No-event rows can refresh producer update time with no economic event. The prior consumer accepted any apparently fresh mapping, fresh self-declared no-event payload, or some aged levels when a separate mutable sweep flag passed. Standard `event_time`, `ingested_at`, `available_at`, `feature_cutoff`, and `decision_time` are not all present and verified. | JSON and HSET projections are mutable; no independent exact-byte/hash-field receipt or atomic multi-input identity. Several compatibility aliases have no trustworthy current producer. | **NO-GO.** All aliases masked. Fresh-looking, no-event, and aged payloads cannot satisfy the context gate. |
| Order-book features | `v2:orderbook:features:binance:{symbol}`, `v2:orderbook:top:binance:{symbol}`, `v2:market:orderbook:binance:{symbol}` | Feature publisher reads a decoded book and writes `v2:orderbook:features:*` (`v2_orderbook_features_publisher.py:97-100,285-286`). Top/rest aliases have WSS, REST fallback, public-metadata, and native-ingestor surfaces. | Feature output carries some combination of event/received/available/generated clocks, but lacks a complete verified `ingested_at`, `feature_cutoff`, and `decision_time` chain. Its event selector can use availability/receipt aliases, and naive timestamps are accepted. Top/rest writer and fallback ambiguity prevents one canonical lineage. | Direct mutable `SET`, no exact source/output byte receipt or atomic book revision binding. | **NO-GO.** Masked; cannot create `orderbook_absorption`, synthesize trust, or claim exit-depth evidence. |
| Trade tape | `v2:market:trade_tape_features:{symbol}` | `v2_trade_tape_ingestor_loop.py` writes the projection and stamps one cycle-level `generated_utc` captured before per-symbol fetch/computation (`:249,269`). It exposes computed and oldest/newest trade timestamps but no full envelope. | `generated_utc` can predate the feature's actual computation. There is no authoritative `ingested_at`, `available_at`, `feature_cutoff`, `decision_time`, or exact admitted trade-batch identity. | Direct mutable `SET`; no receipt or immutable trade range/revision binding. | **NO-GO.** Masked; cannot synthesize tape confirmation or `microstructure_momentum`. |
| Trade-tape confirmation | `v2:microstructure:trade_tape_confirmation:{symbol}` | Feed-quality monitor derives it after reading mutable books/trades and writes it at `v2_microstructure_feed_quality_monitor.py:748`. | The monitor captures a decision time after reads, but its independently read sources are not an atomic snapshot; source availability is inherited/combined rather than exact-artifact verified. | Mutable `SET`, no exact input set or post-commit output receipt. | **NO-GO.** Masked; cannot satisfy the strategy tape gate. |
| Microstructure trust | `v2:microstructure:trust_score:{symbol}:{timeframe}` with timeframe fallbacks | Feed-quality monitor constructs feed, trade, cross-venue, sweep, and trust records, captures decision time at `v2_microstructure_feed_quality_monitor.py:536-546`, and publishes trust at `:751`. It mirrors some results across decision timeframes. | Decision-time capture is the strongest part, but inputs are separate mutable reads. Mirroring changes timeframe identity while retaining source clocks. The legacy `v2:market:microstructure:{symbol}` alias has no uniquely identified current producer. | Direct `SET` with short TTL; no atomic input digest, exact-output receipt, or immutable source batch. Self-declared execution-grade booleans remain unauthenticated. | **NO-GO.** Masked; strategy remains rejected with the explicit resolver-unwired reason. |

## Shared market-structure defects affecting FVG/zones/sweep

`v2/backend/app/services/market_structure/common.py` exposes two important
semantic hazards:

- `row_available_at` can fall back through generated, ingested, received, and
  finally event time (`:81`). An economic event clock can therefore masquerade
  as availability.
- `payload_base` publishes broad consumption flags (`:135-169`) even though
  these raw projections have no durable consumer receipt. A producer's claim
  that a payload is trainer/risk/orchestrator/allocator-eligible does not grant
  authority at the consumer boundary.

These producer defects are documented but intentionally not refactored in
this strategy-only slice.

## Strategy behavior before this slice

The generator directly decoded the optional Redis keys and used any mapping
it found. Consequences included:

- FVG, sweep, order-book, microstructure, or tape mappings could create their
  corresponding strategy families.
- Trust/tape mappings could satisfy minimum-context gates.
- A liquidation mapping could satisfy the mandatory liquidation-context gate;
  a self-declared no-event row or sweep-accepted aged row could also pass.
- Order-book aliases could change exit feasibility and loss probability.
- Re-serialized semantic hashes were emitted in `provider_feature_hashes`, but
  such hashes identify normalized content only. They do not prove the exact
  bytes that were read, the writer, or the retained revision.
- The hypothesis copied an input's `available_at` into the output's own
  `available_at`, even though the hypothesis did not yet exist then.
- `signal_context` was mixed into `provider_features_used` even though it is a
  strategy label rather than a provider input.

## Strategy behavior after this slice

The patched boundary:

- Enumerates every compatibility key for operator/debug provenance without
  reading it as strategy evidence.
- Sets each direct optional field to `None` and emits an explicit
  `strategy_supply_optional_input_status_v1` MASKED record.
- Records the common reason
  `EXACT_RETAINED_ARTIFACT_CONSUMER_RESOLVER_UNWIRED` per input.
- Declares no admitted clocks, no exact source read, no artifact
  authentication, no receipt verification, no zero fill, no trainer
  admission, and no live authority.
- Excludes the masked fields from `provider_features_used` and
  `provider_feature_hashes`.
- Keeps `signal_context` in its own field.
- Captures `decision_time` only after the input context read and captures each
  hypothesis `generated_at` later during output construction.
- Preserves latest admitted input availability as `input_available_at`.
- Leaves output `available_at=None` and explicitly states that no output
  post-commit readback receipt has been emitted.
- Emits `consumer_eligible=false`, `trainer_consumable=false`, and
  `trainer_admission_granted=false` on every row.

The expected operational state is therefore gray/held supply, not fake green
or A+ flow. This slice does not reduce information available to operators; it
removes unauthenticated information from strategy authority.

## Adjacent boundary decisions (documented, not changed)

### Native closed-OHLCV TA

**Limited GO for same-process shadow hypothesis calculation only.** The native
TA resolver performs one exact binary closed-window read and validates source
ABI, symbol/timeframe identity, final candle close, continuity, cutoff, and
clock order. It deliberately declares that its deterministic hashes are
identity aids rather than authentication and that it has no durable Redis
read receipt, trainer admission, or live authority. It must remain held until
the receipt boundary exists.

### CoinGlass

**Schema/PIT GO; retained-artifact authenticity NO-GO.** The provider bridge
strictly checks schema, exact provider/symbol/timeframe identity, exact boolean
types, finite numeric features, strict UTC timestamps, and
`feature_cutoff <= available_at <= generated_at <= observed_at`. That is
materially stronger than the direct optional projections. However, it still
decodes a mutable JSON value and has no independent exact-byte receipt, byte
count/digest binding, writer identity, or immutable revision/CAS. The
canonical confluence consumer explicitly identifies its hashes as
non-authoritative content identity, not authentication.

CoinGlass was not newly masked here because it belongs to the separately owned
provider boundary and was outside this direct-optional-input patch. Before
canonical trainer/live admission, it requires the same exact-artifact receipt
work described below.

### Moralis

**NO-GO and already masked.** Its loader deliberately returns absent until an
authenticated post-commit receipt verifier is wired. No raw Moralis fallback
is introduced here.

### Canonical confluence reconstruction

**Conditional only.** Rebuilding in-process is safer than consuming a cached
confluence envelope, and the consumer revalidates provider identities and
clocks. Its authority cannot exceed its inputs: a strict but unauthenticated
CoinGlass artifact remains unauthenticated after reconstruction.

### Current-price resolver

**NO-GO for canonical admission; acceptable only inside the currently held
shadow lane.** It reads multiple mutable aliases. Its timestamp selector
prioritizes `event_time` before `available_at` and then labels the selected
timestamp as availability (`current_price_resolver.py:107-178`). Future source
timestamps can receive zero age, and successful resolution declares
`decision_time_safe=true` without an exact retained-artifact receipt
(`:392-457`). A dedicated price-boundary slice is required before release.

### Live-gate notional cap

**GO only as a monotonic safety cap, not as evidence or admission.** The
strategy reads `v2:live_gate:state`, but it can only reduce the existing
reference notional by taking a minimum; it cannot enlarge exposure. This
classification does not make that mutable payload canonical strategy data.

## Per-input release prerequisites

No audited direct optional input should be unmasked until it has all of these:

1. One registered canonical writer and one versioned canonical key or
   immutable artifact family; compatibility mirrors cannot be evidence.
2. Strict binary read with explicit UTF-8/JSON rules, duplicate-key rejection,
   non-finite-number rejection, exact byte count, exact SHA-256, and schema
   version.
3. An immutable source revision/batch identity. For book and tape data this
   must bind exchange sequence/trade-range identity; for candle features it
   must bind the exact closed-window identity.
4. Correct, separately named `event_time`, `ingested_at`, `available_at`,
   `generated_at`, `feature_cutoff`, and consumer `decision_time`.
5. Producer commit followed by readback of the committed bytes and an
   independent receipt that binds key, revision, byte count, exact-byte hash,
   clocks, and writer implementation/version.
6. Consumer verification that receipt and bytes match, clocks are ordered, the
   artifact existed by decision time, and no candle is unfinished.
7. Missing/stale/invalid policy that masks the field and records why; it must
   never zero-fill, reuse a stale value as fresh, or trust an alias clock.
8. Adversarial tests for forged self-declarations, mutation after receipt,
   alias/writer collision, future timestamps, clock inversion, stale no-event
   refresh, unfinished candle inclusion, duplicate JSON keys, non-finite
   values, partial/multi-key updates, and mismatched source/output hashes.

Input-specific requirements:

- FVG/zones/sweep: bind exact closed-candle rows and every optional enrichment
  into one deterministic source manifest; remove producer consumption claims
  until the independent receipt verifies them.
- Liquidations: distinguish economic-event time from empty-window observation
  time; an authenticated empty window may be usable, but a refreshed producer
  timestamp must never pretend that a liquidation event occurred.
- Order book: require exchange sequence/update IDs and atomic snapshot
  identity; REST fallback and WSS data must be explicit, never silently
  interchangeable.
- Trade tape: capture generated time after computation and bind the exact
  oldest/newest trade IDs/timestamps plus venue and range digest.
- Trust/confirmation: bind every contributing book, tape, liquidation, and
  cross-venue receipt into one decision manifest before scoring.

## Adversarial validation

The tests prove that:

- Self-declared execution-grade trust and quality flags remain masked.
- Fresh, no-event, and aged liquidation payloads cannot satisfy the context
  gate.
- FVG, sweep, order-book, microstructure, tape, and confirmation payloads
  cannot create a strategy family.
- The consumer does not call `GET` for any enumerated optional raw key, even
  when the payload self-declares receipt/authentication/eligibility fields.
- Masked fields do not enter provider-feature labels or hashes.
- Hypothesis output availability is not backdated to input availability.
- Published rows remain consumer/trainer-ineligible and the positive/gate-clean
  artifact sets are empty for the held test fixture.

Validation commands and results:

```bash
'/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python' -m pytest -q \
  v2/backend/tests/unit/services/strategy_supply/test_edge_hypothesis_generator.py \
  v2/backend/tests/unit/cli/test_v2_strategy_supply_publish_hypotheses.py
# 43 passed

'/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python' -m pytest -q \
  v2/backend/tests/unit/cli/test_v2_a_plus_candidate_inventory.py
# 49 passed

'/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python' -m pytest -q \
  v2/backend/tests/unit/services/strategy_supply/test_edge_hypothesis_generator.py \
  v2/backend/tests/unit/cli/test_v2_strategy_supply_publish_hypotheses.py \
  v2/backend/tests/unit/cli/test_v2_a_plus_candidate_inventory.py
# 92 passed

'/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python' -m pytest -q \
  v2/backend/tests/unit/services/strategy_supply/test_edge_hypothesis_generator.py \
  v2/backend/tests/unit/services/strategy_supply/test_feedback_maturation.py \
  v2/backend/tests/unit/cli/test_v2_strategy_supply_publish_hypotheses.py \
  v2/backend/tests/unit/cli/test_v2_a_plus_candidate_inventory.py
# 103 passed, 2 failed in feedback_maturation

# Exact f0ce93d baseline, isolated detached worktree:
'/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python' -m pytest -q \
  v2/backend/tests/unit/services/strategy_supply/test_feedback_maturation.py
# 11 passed, same 2 failed
```

The pre-change two-file baseline was 41 passing tests. The two broader-suite
failures are pre-existing at the exact branch baseline: both expect matured
rows to be trainer-ready, while the current fail-closed maturation contract
returns zero. They do not import or execute the changed hypothesis generator.
They are reported rather than altered in this bounded strategy-input slice.
`py_compile` and `git diff --check` also passed before documentation
finalization and are rerun as final commit gates.

## Files changed in this slice

- `v2/backend/app/services/strategy_supply/edge_hypothesis_generator.py`
- `v2/backend/tests/unit/services/strategy_supply/test_edge_hypothesis_generator.py`
- `v2/backend/tests/unit/cli/test_v2_strategy_supply_publish_hypotheses.py`
- `claude_worklog/codex/CODEX_STRATEGY_OPTIONAL_INPUT_PROVENANCE_AUDIT_2026_07_21.md`

## Final release statement

**NO-GO for unmasking the audited direct optional inputs.** The scoped code is
**GO to merge as a fail-closed strategy-boundary hardening change** because it
removes unsupported authority, adds explicit observability, preserves missing
data as missing, and is covered by adversarial tests. It does not authorize
trainer publishing, A+ claims, service rollout, leverage changes, margin
changes, or live exchange execution.
