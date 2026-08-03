# Base publisher 0-publish — root cause + WSS/PIT-safe fix (2026-07-24)

**Owner:** Claude (full trainer + supply + provenance ownership).
**Bar:** correct enough that Codex need not intervene. No gate change, no REST backfill, no manufactured claims.

## Symptom
`profiled_base_feature_publisher_v1` publishes `published_symbol_count=0` every cycle
(discovered 163 / eligible 76 / selected 16 / all 16 FAIL). Newest durable feature-snapshot
archive record content stuck at 2026-07-22T12:38Z. Downstream: champion/challenger
`train_rows=55` (needs 1000), `v2:signals:paper=[]`, RTX 5080 idle, paper drought.

## Root cause (8-agent workflow, all claims raw-verified)
A single **universe-wide missing WSS 5m candle at open 2026-07-24T01:05:00Z** split the
163-symbol universe:
- **61 symbols** kept the gap → fail **reason A** `feature_window_core_ta_minimum_coverage_unavailable`
  (contiguous suffix ~32 < 71; feature_window_dependency_contract.py:629-641,702). Self-heals
  ~07:05Z as WSS accumulates 71 post-gap candles.
- **98 symbols** had the 01:05 candle **REST-patched by `v2_universe_coverage_sync`** → fail
  **reason B** `canonical_ohlcv_multitimeframe_required_window_rest_provenance_unavailable`.
- 0 clean. The current all-majors cycle selects the REST-patched cohort → 15/16 reason B.

**Injector:** `v2/backend/app/cli/v2_universe_coverage_sync.py` heals `ohlcv_closed` gaps
via `heal_ohlcv_gaps` (L1475) → `_backfill_symbol_tf` (Binance REST) →
`market_state_integrity/canonical_candles.py:204,220` stamps `source="binance_rest",
is_backfilled=True` into the WSS-only ring `v2:market:ohlcv_closed:binance:*:{5m,1h}`.
The 2026-07-21 migration (commit **9fc6c55ebd** "enforce causal WSS policy migration") made
the MTF capture-set require the ENTIRE 71×5m+34×1h window to be `source_transport=="binance_wss"
and is_backfilled is False` (canonical_ohlcv_multitimeframe_capture_set_v1.py:778-782 + twin
:1338-1342; identical twins also at authenticated_ohlcv_profile_transform_v1.py and
profiled_training_ledger_loader_v1.py). One embedded REST gap-fill row fails the entire symbol.
**Half-migration twin of the trainer_consumable bug: the gate was tightened but the REST
healer that feeds the channel was never stopped.** This is the operator's own "REST makes
eligibility strictly worse" hazard, automated on a 15-min timer.

## Fix decision (Codex-aligned; adversarial-verifier confirmed PIT-safe)
Both `violates_wss_or_pit=False` verifiers + Lens D + Codex agree: **the gate is correct; fix
upstream; do NOT loosen the gate** (Lens B's "restore V1 / allow provably-final REST" is
technically PIT-safe but is the exact loosening Codex forbade). Fix = stop the REST injection.

**Applied — reason B (primary, durable):** drop-in
`~/.config/systemd/user/ai-bot-v2-universe-coverage-sync.service.d/95-no-rest-backfill.conf`
appends `--no-backfill` (the CLI's designed dry_run/census-only mode; heal_ohlcv_gaps returns
before any write at L1516). **Verified:** run reports `backfill: {attempted:0, dry_run:true,
completion_status:"dry_run", gap_pairs_found:148}` — 148 gaps it would have REST-patched,
injected 0. Census preserved for monitoring. Reversible (delete drop-in + daemon-reload).

**Reason A (WSS 5m drops): NO fix.** Raw-verified rare/one-off: NEARUSDT/SUIUSDT show exactly
1 gap in 8.3h; kline WSS loop `NRestarts=0`, 0 reconnect events in 6h. Modifying the healthy,
critical WSS loop to prevent a rare self-healing 1-candle drop risks the whole candle feed for
little gain. The reason-B fix already makes rare gaps self-heal cleanly (WSS accumulation)
instead of being REST-poisoned into 34h blocks.

## Recovery (time-bound, PIT-safe; cannot accelerate without violating WSS-only)
- No new REST contamination (injector stopped). Existing REST rows scroll out: 5m ~07:05Z,
  the embedded 01:00-02:00 1h REST row over ~+34h (majors), but the 61 pure-WSS cohort
  (clean 5m+1h) publish once their 5m window reaches 71 at ~07:05Z — trainer only needs SOME.
- Expected chain: published_symbol_count>0 (~07:05Z) → new records carry a GENUINE
  `trainer_consumable` via the feature-pipeline lineage decision + Codex's propagate-only
  archive path (NOT archive-derived) → champion/challenger train_rows climbs past 55 → GPU +
  paper. Monitoring signals: status `published_symbol_count>0` and reasons drop
  `..._rest_provenance_unavailable`; non-WSS rows in windows trend to 0 and STAY 0.

## Do NOT
- Do not REST-backfill the 5m/1h canonical archive (operator directive, re-confirmed).
- Do not loosen capture_set_v1.py:778-782 / twins (gate is correct).
- Do not rewrite immutable archive records; do not re-enable coverage-sync backfill.
- Keep the offline GPU trainer held until a genuine consumable corpus exists.
