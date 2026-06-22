# V2 Shadow Observation Outcome Metrics Report

GO/NO-GO: V2_SHADOW_OBSERVATION_OUTCOME_METRICS_READY

This packet does NOT approve real trading, canary trading, exchange
mutation, leverage/margin changes, legacy shutdown, Redis trim, or
paper-only shutdown acceptance. It does NOT modify legacy. It does
NOT pause the V2 runtime. It does NOT write old Redis keys. It does
NOT loosen the strict paper-fill gate. It does NOT create accepted
fills. It does NOT compute accepted-position MFE/MAE/ROE from shadow
rows. It does NOT claim checkpoint compatibility or policy
architecture parity.

## Scope

After acceptance-state normalization, `v2:paper:positions` carries
only accepted paper fills, and shadow / held rows live in their own
keys. This packet wires a dedicated outcome-metrics path so the
system can learn from blocked intents (was the block correct? did
we miss a profitable move?) WITHOUT counting them as fills, WITHOUT
opening the gate, and WITHOUT touching the PnL ledger.

## Files added

### v2/backend/app/services/paper_shadow_outcome_metrics/service.py

- `SHADOW_OUTCOME_KEY_TEMPLATE = "v2:paper:shadow_outcome:{symbol}"`
- `SHADOW_OUTCOME_HEARTBEAT_KEY = "v2:paper:shadow_outcome:heartbeat"`
- Source-rule constants: `SOURCE_V2_MARKET_LAST`,
  `SOURCE_V2_FEATURES_FRESH_CLOSE`,
  `MISSING_CURRENT_PRICE_BLOCKER = "MISSING_V2_MARKET_PRICE_FOR_SHADOW_OUTCOME"`.
- Decision labels: `LABEL_SHADOW = "SHADOW_OUTCOME_ONLY"`,
  `LABEL_HELD = "HELD_OUTCOME_ONLY"`.
- `_safe_redis_set` refuses every key except
  `v2:paper:shadow_outcome:*` and the heartbeat. The service cannot
  leak writes into accepted-position keys, the ledger, the paper
  heartbeat, or anything legacy.
- `read_v2_current_price` strict source order:
  1. `v2:market:prices:{symbol}.ticker_24hr.lastPrice`
  2. `v2:features:latest:{symbol}:1m.features.close_price` ONLY when
     `feature_freshness_state="CURRENT"`
  3. otherwise emit `MISSING_V2_MARKET_PRICE_FOR_SHADOW_OUTCOME`
- `build_shadow_outcome` computes per-row metrics from V2-only inputs;
  the `ShadowOutcome` dataclass pins safety invariants on every
  emitted payload.
- `_classify(...)` produces `(no_trade_correct, false_block_candidate)`:
  - direction consistent + move-after-cost > threshold →
    `(False, True)` ← a missed-opportunity / false-block candidate
  - direction inconsistent + move-after-cost < -threshold →
    `(True, False)` ← block correctly avoided a loss
  - otherwise `(None, None)` (honestly uncertain; never classified)

### v2/backend/app/cli/v2_paper_shadow_outcome_metrics.py

- `--once` (default) and `--loop --interval-seconds`.
- Reads:
  - `v2:paper:shadow_observations` (only rows with
    `decision == "SHADOW_OBSERVATION_ONLY"`)
  - `v2:paper:intents_held_by_paper_fill_gate`
  - `v2:market:prices:{symbol}`
  - `v2:features:latest:{symbol}:1m`
  - `v2:prediction:{symbol}:1m`
- Writes:
  - `v2:paper:shadow_outcome:{symbol}` per outcome row
  - `v2:paper:shadow_outcome:heartbeat`
  - `claude_worklog/final_readiness/v2_shadow_observation_outcome_metrics/latest/shadow_outcome_metrics_status.json`
  - `v2/frontend/public/v2_shadow_observation_outcome_metrics/latest/operator_dashboard_payload.json`

The CLI does NOT write `v2:paper:positions`, `v2:paper:ledger`,
`v2:paper:heartbeat`, or any non-shadow-outcome key. Tests verify
this directly.

## Per-row payload schema

Every `v2:paper:shadow_outcome:{symbol}` row carries:

- `symbol`, `decision_label`, `block_reason`, `side`
- `shadow_entry_price`, `shadow_entry_price_source`, `shadow_entry_price_utc`
- `current_price`, `current_price_source`, `current_price_source_utc`
- `missed_move_bps`, `missed_move_after_cost_bps`, `fee_round_trip_bps`
- `time_since_shadow_seconds`
- `direction_consistent_with_prediction`
- `no_trade_correct`, `false_block_candidate`
- `missing_flags`, `stale_flags`
- `generated_utc`

Plus the persistent safety pins:

- `counted_as_accepted_position=false`
- `counted_as_fill=false`
- `affects_pnl_ledger=false`
- `opens_paper_fill_gate=false`
- `approves_live / approves_canary / approves_legacy_shutdown / approves_redis_trim=false`
- `places_real_order=false`
- `writes_legacy_redis / writes_exchange_orders=false`
- `live_gate="blocked_human_only"`, `live_symbols=[]`

## Live state (raw, after CLI --once)

```
v2:paper:shadow_outcome:BTCUSDT  label=SHADOW_OUTCOME_ONLY  side=long
  entry=76962.95  cur=76962.95  missed_bps=0.0  after_cost=-10.0
  dir_consistent=False  no_trade_correct=True  false_block=False
  block_reason=UPSTREAM_PAPER_FILL_GATE_DENIED
  counted_as_accepted_position=False  affects_pnl_ledger=False

v2:paper:shadow_outcome:ETHUSDT  label=SHADOW_OUTCOME_ONLY  side=long
  entry=2116.66  cur=2116.66  missed_bps=0.0  after_cost=-10.0
  dir_consistent=False  no_trade_correct=True  false_block=False
  block_reason=UPSTREAM_PAPER_FILL_GATE_DENIED

v2:paper:shadow_outcome:SOLUSDT  label=HELD_OUTCOME_ONLY  side=hold
  entry=None  cur=84.94  missed_bps=None  after_cost=None
  dir_consistent=None  no_trade_correct=None  false_block=None
  block_reason=NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK

v2:paper:shadow_outcome:heartbeat
  label_counts={SHADOW_OUTCOME_ONLY: 2, HELD_OUTCOME_ONLY: 1}
  outcome_count=3
  symbols=[BTCUSDT, ETHUSDT, SOLUSDT]
```

## Tests

`v2/backend/tests/integration/cli/test_v2_paper_shadow_outcome_metrics.py` — **17 / 17 pass**.

Coverage:

- `read_v2_current_price` picks `v2:market:prices` first
- Falls back to `v2:features:latest` ONLY when `feature_freshness_state="CURRENT"`
- Refuses STALE feature snapshot → emits `MISSING_V2_MARKET_PRICE_FOR_SHADOW_OUTCOME`
- Returns explicit blocker when no source is available
- `_safe_redis_set` refuses any key outside `v2:paper:shadow_outcome:*` (positive: `:{symbol}` + `:heartbeat`; negative: `v2:paper:positions`, `v2:paper:ledger`, `v2:paper:heartbeat`, legacy keys)
- Long shadow with +166 bps favourable move → `no_trade_correct=False`, `false_block_candidate=True`
- Long shadow with -166 bps adverse move → `no_trade_correct=True`, `false_block_candidate=False`
- Missing current price → outcome carries `MISSING_V2_MARKET_PRICE_FOR_SHADOW_OUTCOME` and metrics stay None (no fabricated price)
- Missing shadow entry price → `MISSING_SHADOW_ENTRY_PRICE` + `MISSING_SHADOW_ENTRY_UTC` flags
- Held outcome carries the orchestrator's `paper_fill_gate_block_reasons` joined into `block_reason`
- CLI writes only `v2:paper:shadow_outcome:*` and the heartbeat — never `v2:paper:positions`, never `v2:paper:ledger`, never `v2:paper:heartbeat`
- CLI does NOT modify `v2:paper:positions` even when shadow rows exist
- Position price tracking recorder source does NOT import or read `paper_shadow_outcome_metrics` — accepted-position MFE/MAE/ROE remain isolated from shadow outcomes
- Status payload pins every safety invariant
- No exchange-mutation verbs in either module source
- No torch / no pickle deserialization in either module

## Strict invariants

- `counted_as_accepted_position = false`
- `counted_as_fill = false`
- `affects_pnl_ledger = false`
- `opens_paper_fill_gate = false`
- `places_real_order = false`
- `approves_live / approves_real / approves_canary / approves_legacy_shutdown / approves_redis_trim = false`
- `writes_legacy_redis / writes_exchange_orders = false`
- `no_synthetic_price = true`
- `no_legacy_redis_read = true`
- `live_gate = blocked_human_only`, `live_symbols = []`
- `checkpoint_compatibility_claimed = false`, `policy_architecture_parity_claimed = false`

## What this packet does NOT do

- Does not approve real trading.
- Does not approve canary, legacy shutdown, Redis trim, or paper-only
  shutdown acceptance.
- Does not modify legacy.
- Does not pause V2 runtime.
- Does not change leverage or margin.
- Does not loosen the strict paper-fill gate.
- Does not create accepted paper fills.
- Does not compute accepted-position MFE/MAE/ROE from shadow rows.
- Does not affect the PnL ledger.
- Does not place, modify, or cancel exchange entries.
- Does not synthesize prices.
- Does not claim checkpoint compatibility.
- Does not claim policy architecture parity.

## Outputs

- `claude_worklog/final_readiness/v2_shadow_observation_outcome_metrics/latest/GO_NO_GO.md`
- `claude_worklog/final_readiness/v2_shadow_observation_outcome_metrics/latest/V2_SHADOW_OBSERVATION_OUTCOME_METRICS_REPORT.md`
- `claude_worklog/final_readiness/v2_shadow_observation_outcome_metrics/latest/shadow_outcome_metrics_status.json`
- `v2/frontend/public/v2_shadow_observation_outcome_metrics/latest/operator_dashboard_payload.json`
- `v2/backend/app/services/paper_shadow_outcome_metrics/__init__.py` (new)
- `v2/backend/app/services/paper_shadow_outcome_metrics/service.py` (new)
- `v2/backend/app/cli/v2_paper_shadow_outcome_metrics.py` (new)
- `v2/backend/tests/integration/cli/test_v2_paper_shadow_outcome_metrics.py` (new; 17 tests)
- `v2:paper:shadow_outcome:{BTCUSDT|ETHUSDT|SOLUSDT}` (Redis; written by CLI)
- `v2:paper:shadow_outcome:heartbeat` (Redis; written by CLI)
