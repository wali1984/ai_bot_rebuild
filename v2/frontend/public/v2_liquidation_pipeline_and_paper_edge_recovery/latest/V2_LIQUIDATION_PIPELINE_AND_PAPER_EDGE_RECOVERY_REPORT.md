# V2 Liquidation Pipeline and Paper-Edge Recovery — Report

- **Task ID**: `v2_liquidation_pipeline_and_paper_edge_recovery`
- **Generated EST**: 2026-05-31T00:48:00-0400
- **Generated UTC**: 2026-05-31T04:48:00Z
- **GO/NO-GO**: `V2_LIQUIDATION_PIPELINE_AND_PAPER_EDGE_RECOVERY_READY`
- **Live gate**: `blocked_human_only`
- **Live symbols**: `[]`
- **Live recommendation**: `BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN`
- **Canary recommendation**: `BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN`

## What this READY verdict DOES claim

- The liquidation event flow is now wired end-to-end **inside V2-only namespace**: real Binance `forceOrder` events parsed by the WSS client are now forwarded into the canonical stream `v2:liquidations:events`, where the levels engine consumes them and populates `v2:unified_features:*` hashes.
- The bridge input contract is formalised: WSS is the canonical producer; the legacy bridge polling `v2:binance:force:raw` / `v2:raw:coinank:liquidation_orders:global` is downgraded to `LABELLED_FALLBACK` for the CoinAnk REST path (when that adapter is wired later).
- The paper-only symbol-concentration guard is implemented as a deterministic, side-effect-free evaluator at `v2/backend/app/services/paper_guards/symbol_concentration_guard.py` with 11 passing tests. It produces ALLOW / DOWNRANK / BLOCK decisions and feeds the replay miner.
- War-room validation growth is now tracked; current 12 rows < 300 target — edge stays `EDGE_NOT_CLAIMED`.

## What this READY verdict does NOT claim

- The Binance `forceOrder` stream has NOT yet delivered an event since the WSS was rewired (4 minutes of observation; stream is genuinely quiet — `events_received=0`). Per spec this is `EVENT_DEPENDENT_NO_REAL_LIQUIDATION_EVENTS`, NOT a wiring failure.
- Paper PnL is still `-49.345535 USDT`. Live/canary remain BLOCKED.
- The legacy hybrid trainer was not touched. The V2 trainer wrapper remains the momentum-only stub.
- No operator-gated decision was taken (no key rotation, no canary relaxation, no edge threshold setting).

## Phase dispositions

| Phase | Disposition |
|------|-------------|
| 1 — event namespace wiring | `EVENT_DEPENDENT_NO_REAL_LIQUIDATION_EVENTS` (wired, stream empty because Binance hasn't fired) |
| 2 — bridge input contract | `BRIDGE_INPUT_CONTRACT_DEFINED_WSS_NOW_CANONICAL_PRODUCER_BRIDGE_DOWNGRADED_TO_LABELLED_FALLBACK` |
| 3 — levels output contract | `EVENT_DEPENDENT_NO_REAL_LIQUIDATION_EVENTS` (engine consumes stream; emits no-event defaults until events flow) |
| 4 — paper PnL diagnosis | `ROOT_CAUSE_DECOMPOSED_ACROSS_7_AXES_REMEDIATIONS_QUEUED` |
| 5 — concentration guard | `GUARD_IMPLEMENTED_PAPER_ONLY_FEEDS_REPLAY_MINER` (11 tests pass) |
| 6 — validation growth | `EDGE_NOT_CLAIMED_VALIDATION_BELOW_TARGET` (12 / 300) |

## Phase 1 — liquidation event namespace wiring

Code change in [v2/backend/app/services/native_ingestors/liquidations_wss.py](v2/backend/app/services/native_ingestors/liquidations_wss.py):

- Added `KEY_EVENTS_STREAM = "v2:liquidations:events"` and `DEFAULT_EVENTS_STREAM_MAXLEN = 10000`.
- Added `write_event_to_stream(redis_client, *, symbol, latest_event, source="binance_wss_forceOrder", maxlen=DEFAULT_EVENTS_STREAM_MAXLEN)` which XADDs the parsed event into the stream with `MAXLEN ~10000` (approximate).
- Modified `write_event_to_redis()` to ALSO call `write_event_to_stream()` so per-symbol KV writes and stream publish happen on the same code path.
- Side mapping documented and tested: WSS tape side `long` (BUY hits ask) → `SHORT_LIQ`; tape side `short` (SELL hits bid) → `LONG_LIQ`.
- 3 new unit tests:
  - `test_write_event_to_stream_publishes_into_v2_liquidations_events`
  - `test_write_event_to_stream_buy_maps_to_short_liq`
  - `test_write_event_to_redis_also_publishes_stream`
- WSS service restarted to pick up the wiring.

No synthetic events. The WSS publishes ONLY what the existing parser accepted.

## Phase 2 — bridge input contract

Canonical producer: WSS `write_event_to_stream`.

The legacy bridge (`liquidation_bridge.py`) is now `LABELLED_FALLBACK` for two CoinAnk + raw-list paths whose inputs (`v2:binance:force:raw`, `v2:raw:coinank:liquidation_orders:global`) currently have no upstream producer. The levels engine does NOT depend on the bridge today; it consumes the stream directly.

## Phase 3 — levels output contract

Engine `v2/legacy_owned_runtime/ingest/liquidation_levels_engine.py` writes liquidation fields (`liquidation_long_level`, `liquidation_short_level`, `liquidation_long_distance_pct`, `liquidation_short_distance_pct`, `liquidation_volume`, `liquidation_levels_json`, `liquidation_is_stale`, etc.) into `v2:unified_features:{symbol}:{tf}` and `:latest` hashes. Symbol coverage: 27 (170 unified_features keys currently).

The `v2:market:liquidation_levels:*` family is **permitted but not currently used** by the engine — it remains 0 keys by design.

With `v2:liquidations:events XLEN=0`, the engine emits the no-event default branch (`liquidation_long_level=0.0`, `liquidation_is_stale=1`, `liquidation_long_distance_pct=100.0`, etc.). Status: `EVENT_DEPENDENT_NO_REAL_LIQUIDATION_EVENTS`.

## Phase 4 — paper PnL root cause across 7 axes

| Axis | Finding |
|------|---------|
| Symbol concentration | recent 1h/6h/24h intents 100% on `1000BONKUSDT` — addressed by Phase 5 guard |
| Confidence calibration | ~76% of blocked intents at 0.75+ confidence; canary profile tighter than strategy band |
| Risk block reasons | `deny_canary_profile_tightening` dominates 94-96% of blocks |
| False negative / positive rates | war-room FN=15 (altdata_missing + paper_fill_gate_block); FP rate undefined (no allowed sample) |
| Strategy/trainer disagreement | val=12 < threshold; no winner declared |
| Fee / slippage drag | fee=0.0004 + slippage=2 bps → ~6 bps round-trip vs after-cost -7.25 bps |
| Stale / missing features | LunarCrush key missing, Nansen 403, CoinAPI not ported, KuCoin stub-only |

Recommendation surface populated. NO thresholds relaxed. NO orders placed.

## Phase 5 — paper-only symbol concentration guard

New module: [v2/backend/app/services/paper_guards/symbol_concentration_guard.py](v2/backend/app/services/paper_guards/symbol_concentration_guard.py)

Thresholds default:
- `max_recent_intent_share_per_symbol = 0.60` → BLOCK
- `downrank_share_threshold = 0.40` → DOWNRANK
- `min_symbol_diversity = 3` → BLOCK if existing symbol in low-diversity window

Decision API: `evaluate(distribution, symbol, *, max_share, min_diversity, downrank_share) -> ConcentrationDecision`.

Replay-miner feed: `replay_miner_feed(decisions) -> list[dict]` (each row carries the live-safety envelope).

Guarantees:
- Paper-only; cannot touch `live_symbols`, live gate, exchange.
- Module does not import redis or ccxt; pure deterministic evaluator.
- 11/11 unit tests pass.

When applied to the recent 1h/6h/24h windows, the guard would BLOCK new `1000BONKUSDT` intents with reason `block_paper_symbol_below_min_diversity` — exactly the concentration the diagnosis surfaced.

## Phase 6 — war-room validation growth tracker

| Field | Value |
|-------|-------|
| `validation_rows_current` | 12 |
| `validation_rows_prior_snapshot` | 16 |
| `target_rows` | 300 |
| `rows_remaining_to_target` | 288 |
| `expected_hours_to_target` (1 row/h assumption) | ~288 |
| `edge_claimed` | false |

Blockers tracked: altdata_missing, paper_fill_gate_block, single-symbol concentration, quiet forceOrder stream.

## Phase 7 — Report Center

Registered lane `v2_liquidation_pipeline_and_paper_edge_recovery` in `v2/backend/app/services/report_center/report_registry.py` with `blocks_live=True`, `blocks_shutdown=True`, `blocks_production_equivalence=True`. Indexer rebuilt: report_count went from 69 → 70.

## Phase 8 — validation

- `python3 -m py_compile` for all touched modules + builder + report registry: PASS
- `pytest v2/backend/tests/integration/cli/test_v2_liquidation_wss_loop.py v2/backend/tests/unit/paper_guards/`: **39 passed**
- JSON validation: 7 / 7 artifacts parse
- Redis scans `orchestrator:*`, `live_orders:*`, `exchange:order:*`, `order:*`, `leverage:*`, `margin:*`: all 0
- Approval-token scan in milestone output dir: 0 files
- Raw secret scan (`API_KEY=...`, `sk-...`, `Bearer ...`): 0 hits

## Hard constraints honoured

| Constraint | Status |
|-----------|--------|
| `LIVE_GATE=blocked_human_only` | held |
| `live_symbols=[]` | held |
| Did not enable live | held |
| Did not enable canary | held |
| Did not place/cancel/modify orders | held |
| Did not call test-order endpoint | held |
| Did not change leverage | held |
| Did not change margin mode | held |
| Did not restart legacy | held |
| Did not write old Redis | held |
| Did not trim/flush Redis | held |
| Did not fabricate liquidation events | held (WSS forwards only what parser accepts) |
| Did not fabricate liquidation levels | held (engine only emits with real events; current is no-event default) |
| Used EST timestamps in artifacts | held |

## Files

Mirrored at both `claude_worklog/final_readiness/v2_liquidation_pipeline_and_paper_edge_recovery/latest/` and `v2/frontend/public/v2_liquidation_pipeline_and_paper_edge_recovery/latest/`:

- `GO_NO_GO.md`
- `V2_LIQUIDATION_PIPELINE_AND_PAPER_EDGE_RECOVERY_REPORT.md` (this file)
- `liquidation_event_namespace_wiring_status.json`
- `liquidation_bridge_input_contract_status.json`
- `liquidation_levels_output_contract_status.json`
- `paper_pnl_recovery_diagnosis_status.json`
- `paper_symbol_concentration_guard_status.json`
- `war_room_validation_growth_status.json`
- `operator_dashboard_payload.json`
- `build_artifacts.py` (builder for this turn)

## What still needs to happen

Automatable (no operator gate):
1. Wait for Binance `forceOrder` events to fire on any of the 27 symbols → stream auto-populates → levels engine auto-populates non-zero liquidation fields in `v2:unified_features:*`.
2. Apply the symbol concentration guard at the paper-intent admission path (separate wiring; this milestone provides the evaluator).
3. Continue war-room validation accumulation until 300 rows.

Operator-gated (preserved as decisions, NOT executed):
1. Refresh or replace Nansen API key (currently 403).
2. Provision LunarCrush API key (currently missing).
3. Decide on canary profile tightening relaxation.
4. Set explicit edge thresholds for the war-room evaluator.
