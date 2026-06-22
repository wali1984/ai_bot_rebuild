# V2 Full-Observation Builder — Remaining-Dim Execution Queue

**Generated:** 2026-05-21 (UTC)
**GO_NO_GO:** `V2_FULL_OBSERVATION_REMAINING_DIM_EXECUTION_QUEUE_READY`

## Mandate

The full-observation builder is now at **223 / 1911** (BTC, ETH) and
**213 / 1911** (SOL). Random tiny burndown patches stop here. This
packet emits a deterministic **execution queue** that classifies
every remaining missing dimension into exactly one of 12 canonical
categories so the next packet can attack only the genuinely
V2-buildable work.

**Read-only.** No code change to the builder, no Redis write, no
provider call, no exchange call, no checkpoint touch, no policy
architecture, no live enablement, no Symbol Universe mutation, no
shutdown acceptance.

## The 12 canonical categories

1. `V2_BUILDABLE_NOW`
2. `V2_EVENT_DEPENDENT_LIQUIDATION_WSS`
3. `V2_POSITION_DEPENDENT_OPEN_POSITION_REQUIRED`
4. `EXTERNAL_SOURCE_REQUIRED_TOKEN_METRICS`
5. `EXTERNAL_SOURCE_REQUIRED_ONCHAIN_BTC`
6. `EXTERNAL_SOURCE_REQUIRED_ONCHAIN_ETH`
7. `OPERATOR_DECISION_REQUIRED_CCXT_OHLCV`
8. `OPERATOR_DECISION_REQUIRED_COINANK_PAID_AGGREGATOR`
9. `LEGACY_V3_EXTRA_NO_V2_SOURCE`
10. `POLICY_ARCHITECTURE_BLOCKED`
11. `CHECKPOINT_ARTIFACT_BLOCKED`
12. `NOT_REQUIRED_FOR_CURRENT_V2_MODEL_PATH`

## Aggregate distribution (3 symbols × 1911 = 5733 dims)

| Category | Dims | Share of 5733 |
|----------|------:|---------------:|
| Sourced today (BTC=223, ETH=223, SOL=213) | **659** | 11.5 % |
| `LEGACY_V3_EXTRA_NO_V2_SOURCE` | 3879 | 67.7 % |
| **`V2_BUILDABLE_NOW`** | **940** | **16.4 %** |
| `EXTERNAL_SOURCE_REQUIRED_TOKEN_METRICS` | 54 | 0.9 % |
| `V2_POSITION_DEPENDENT_OPEN_POSITION_REQUIRED` | 51 | 0.9 % |
| `EXTERNAL_SOURCE_REQUIRED_ONCHAIN_BTC` | 45 | 0.8 % |
| `EXTERNAL_SOURCE_REQUIRED_ONCHAIN_ETH` | 45 | 0.8 % |
| `OPERATOR_DECISION_REQUIRED_CCXT_OHLCV` | 30 | 0.5 % |
| `NOT_REQUIRED_FOR_CURRENT_V2_MODEL_PATH` | 18 | 0.3 % |
| `V2_EVENT_DEPENDENT_LIQUIDATION_WSS` | 12 | 0.2 % |
| `OPERATOR_DECISION_REQUIRED_COINANK_PAID_AGGREGATOR` | 0 | 0 % |
| `POLICY_ARCHITECTURE_BLOCKED` | 0 | 0 % |
| `CHECKPOINT_ARTIFACT_BLOCKED` | 0 | 0 % |

Math: `659 + 3879 + 940 + 54 + 51 + 45 + 45 + 30 + 18 + 12 = 5733`. ✓

## Per-symbol distribution

| Symbol | Sourced | V2_BUILDABLE_NOW | LEGACY_V3 | Position-dep | Ext-required | Op-decision | Event-dep | Not-required |
|--------|--------:|------------------:|----------:|-------------:|--------------:|------------:|----------:|-------------:|
| BTCUSDT | 223 | 311 | 1293 | 17 | 48 | 10 | 4 | 5 |
| ETHUSDT | 223 | 311 | 1293 | 17 | 48 | 10 | 4 | 5 |
| SOLUSDT | 213 | 318 | 1293 | 17 | 48 | 10 | 4 | 8 |

Ext-required = `TOKEN_METRICS (18)` + `ONCHAIN_BTC (15)` +
`ONCHAIN_ETH (15)`. Per-symbol counts checksum to the aggregate.

## Category-by-category: what it means and what unblocks it

### V2_BUILDABLE_NOW — 940 dims (the actual implementation queue)

Field groups, ranked by dim count:

| Dims | Field group | V2 source keys |
|-----:|-------------|----------------|
| 912 | `portfolio_state[*]` (slice padding/reserved budget) | `v2:paper:*` + `v2:risk:decisions` + `v2:orchestrator:decisions` + `v2:trainer:heartbeat` + `v2:prediction:{sym}:{tf}` + `v2:altdata:symbol_score:{sym}` + `v2:symbol_universe:altdata_candidates` |
| 3 | `portfolio_state.portfolio_trainer_heartbeat_age_seconds` | `v2:trainer:heartbeat` |
| 3 | `portfolio_state.portfolio_altdata_score_payload_present` | `v2:altdata:symbol_score:{sym}` |
| 3 | `portfolio_state.portfolio_symbol_altdata_score` | `v2:altdata:symbol_score:{sym}` |
| 3 | `portfolio_state.portfolio_symbol_altdata_rank` | `v2:altdata:symbol_score:{sym}` |
| 3 | `portfolio_state.portfolio_symbol_provider_availability_score` | `v2:altdata:symbol_score:{sym}` |
| 3 | `portfolio_state.portfolio_symbol_altdata_freshness_score` | `v2:altdata:symbol_score:{sym}` |
| 3 | `portfolio_state.portfolio_altdata_score_age_seconds` | `v2:altdata:symbol_score:{sym}` |
| 1 each | `portfolio_state.portfolio_symbol_risk_decision_present`, `*_pre_trade_allowed`, `*_fee_gate_allowed`, `*_churn_blocked`, `position_context.pre_trade_allowed`, `position_context.fee_gate_allowed`, `position_context.churn_blocked` | `v2:risk:decisions` per symbol (currently absent for SOL) |

The 912-dim portfolio_state group dominates. These are slice slots
that the projector currently labels
`MISSING_FROM_V2_PORTFOLIO_STATE_EXTENDED` — no V2 source is missing,
but no specific projector field is wired to each slot yet. The next
implementation packet should expand `_build_portfolio_state_slice` to
project additional V2-native fields from the keys already read.

**No external source required. No paid aggregator. No operator
decision. No policy architecture. No checkpoint artifact.**

### V2_EVENT_DEPENDENT_LIQUIDATION_WSS — 12 dims

Unblocks when: a V2-owned Binance USDM WSS publisher writes
`v2:market:liquidations:latest:{sym}` and
`v2:market:liquidations:aggregate:{sym}`. Today both keys are
verified ABSENT in live Redis.

| Dims | Field group |
|-----:|-------------|
| 12 | `liquidations[*]` (the 4 per-symbol slots that depend on the per-symbol aggregator) |

### V2_POSITION_DEPENDENT_OPEN_POSITION_REQUIRED — 51 dims

These fields source automatically when a real V2 paper position is
open. No code change required; just real position state.

Sourced from: `v2:paper:position_history:{sym}`,
`v2:paper:position_price_track:{sym}`, `v2:paper:positions`,
`v2:paper:ledger`.

Per-symbol breakdown: 17 dims. Today all three symbols are in
`NO_OPEN_POSITION`, so these fields surface as `None` with the
position-dependent sources
(`V2_POSITION_HISTORY_TRACKER_NO_OPEN_POSITION`,
`V2_POSITION_HISTORY_TRACKER_PAYLOAD_FIELD_MISSING`,
`MISSING_V2_REALIZED_PNL`, `MISSING_V2_UNREALIZED_PNL`,
`MISSING_FROM_V2_PAPER_POSITIONS`).

### EXTERNAL_SOURCE_REQUIRED_TOKEN_METRICS — 54 dims (18 × 3)

Unblocks when: operator approves a Glassnode / CryptoQuant /
IntoTheBlock ingestor packet and Codex passes it. Until then the
slot stays `EXTERNAL_SOURCE_REQUIRED_NO_V2_NATIVE_TOKEN_METRICS`.

### EXTERNAL_SOURCE_REQUIRED_ONCHAIN_BTC — 45 dims (15 × 3)

Unblocks when: operator approves an on-chain BTC ingestor packet
(Glassnode / Coin Metrics / public node) and Codex passes it.

### EXTERNAL_SOURCE_REQUIRED_ONCHAIN_ETH — 45 dims (15 × 3)

Same as above, for the ETH on-chain slice.

### OPERATOR_DECISION_REQUIRED_CCXT_OHLCV — 30 dims (10 × 3)

Unblocks when: operator decides whether V2 should consume a
secondary-exchange OHLCV feed via CCXT (e.g. Bybit, OKX, Kraken).
Current label: `OPERATOR_DECISION_REQUIRED_SECONDARY_EXCHANGE_OHLCV`.

### OPERATOR_DECISION_REQUIRED_COINANK_PAID_AGGREGATOR — 0 dims

The free-tier CoinAnk-derivable fields are already sourced by the
prior unified-features burndown packet. No paid-tier expansion has
been authorised, and the open slots no longer carry a
"coinank_paid_aggregator_required" label — they were closed under
free-tier derivations. This category is reserved for any future
paid-CoinAnk expansion the operator may authorise.

### LEGACY_V3_EXTRA_NO_V2_SOURCE — 3879 dims (1293 × 3)

The trailing dims of the 1430-dim `unified_features` slice beyond
the 137-dim `SUBFAMILY_LAYOUT`. These were legacy V3 fields with no
known V2-native equivalent. **Out of scope** for incremental
burndown unless a future V2 source surfaces a specific subset. Not
buildable today by definition.

### POLICY_ARCHITECTURE_BLOCKED — 0 dims

**No field is currently classified here.** Policy architecture is
intentionally NOT started in this packet. The category remains
defined so a future policy-related packet can claim slots before
work begins.

### CHECKPOINT_ARTIFACT_BLOCKED — 0 dims

**No field is currently classified here.**
`checkpoint_compatibility_claimed=false` remains the canonical
position. The category is reserved for the eventual checkpoint
artifact mining packet, which has not been authorised.

### NOT_REQUIRED_FOR_CURRENT_V2_MODEL_PATH — 18 dims

Today: 3 dims per symbol from
`technical_analysis.macd_signal_strength` (None when `macd == 0` —
mathematically degenerate; not a missing source), plus 2 dims per
symbol from `position_context.*` slots whose projected value is None
on degenerate state. SOL has an extra 3 dims due to SOL not having a
risk decision today (those will reclassify to `V2_BUILDABLE_NOW`
once a risk decision lands).

## Next-10 buildable tasks (the actionable queue)

Ranked by aggregate dim count. **Each task is `V2_BUILDABLE_NOW` —
no external source, no operator decision, no policy/checkpoint
unblocking required.**

| # | Field group | Aggregate dim gap | V2 source keys to consume |
|--:|-------------|------------------:|----------------------------|
| 1 | `portfolio_state` (slice expansion) | 912 | `v2:paper:positions`, `v2:paper:ledger`, `v2:paper:intents`, `v2:paper:intents_held_by_paper_fill_gate`, `v2:risk:decisions`, `v2:orchestrator:decisions`, `v2:trainer:heartbeat`, `v2:prediction:{symbol}:{timeframe}`, `v2:paper:position_history:{symbol}`, `v2:altdata:symbol_score:{symbol}`, `v2:symbol_universe:altdata_candidates` |
| 2 | `portfolio_state.portfolio_trainer_heartbeat_age_seconds` | 3 | `v2:trainer:heartbeat` |
| 3 | `portfolio_state.portfolio_altdata_score_payload_present` | 3 | `v2:altdata:symbol_score:{symbol}` |
| 4 | `portfolio_state.portfolio_symbol_altdata_score` | 3 | `v2:altdata:symbol_score:{symbol}` |
| 5 | `portfolio_state.portfolio_symbol_altdata_rank` | 3 | `v2:altdata:symbol_score:{symbol}` |
| 6 | `portfolio_state.portfolio_symbol_provider_availability_score` | 3 | `v2:altdata:symbol_score:{symbol}` |
| 7 | `portfolio_state.portfolio_symbol_altdata_freshness_score` | 3 | `v2:altdata:symbol_score:{symbol}` |
| 8 | `portfolio_state.portfolio_altdata_score_age_seconds` | 3 | `v2:altdata:symbol_score:{symbol}` |
| 9 | `portfolio_state.portfolio_symbol_risk_decision_present` | 1 | `v2:risk:decisions` |
| 10 | `portfolio_state.portfolio_symbol_pre_trade_allowed` | 1 | `v2:risk:decisions` |

Task #1 alone is **934 dims** — by far the largest single
implementation surface. The smaller ranked groups are already
projected today; they're listed because their *value* is None when
the upstream payload field is absent or for a symbol that lacks a
risk decision. They will source naturally as the projector grows.

## Output artifacts emitted

All under
`claude_worklog/final_readiness/v2_full_observation_remaining_dim_execution_queue/latest/`:

- `GO_NO_GO.md` — `V2_FULL_OBSERVATION_REMAINING_DIM_EXECUTION_QUEUE_READY`
- `REMAINING_DIM_EXECUTION_QUEUE_REPORT.md` (this file)
- `remaining_dim_execution_queue.json` — aggregate + per-symbol classification with full source-label distribution
- `next_10_feature_tasks.json` — the actionable queue
- `v2_buildable_now_fields.json` — every field group classified V2_BUILDABLE_NOW
- `event_dependent_fields.json` — liquidation WSS blocked group
- `operator_decision_required_fields.json` — CCXT + paid CoinAnk
- `external_source_required_fields.json` — token_metrics + onchain_btc + onchain_eth
- `position_dependent_fields.json` — open-position-state-dependent fields
- `legacy_v3_extra_fields.json` — legacy V3 trailing dims
- `policy_architecture_blocked_fields.json` — 0 entries today
- `checkpoint_artifact_blocked_fields.json` — 0 entries today
- `not_required_for_current_v2_model_path_fields.json` — degenerate state slots

Public frontend mirrors under
`v2/frontend/public/v2_full_observation_remaining_dim_execution_queue/latest/`:

- `operator_dashboard_payload.json`
- `remaining_dim_execution_queue.json`
- `next_10_feature_tasks.json`

## Classifier source

[tools/v2_full_observation_remaining_dim_classifier.py](../../../../tools/v2_full_observation_remaining_dim_classifier.py)

The classifier is read-only and reproducible. It loads the V2
builder, runs `build_full_observation_for_symbol` for each of
BTCUSDT / ETHUSDT / SOLUSDT against current Redis state, and
deterministically partitions every (field_name, value, source)
triple into one of the 12 categories. The source-label → category
mapping table is the authoritative classification rulebook; future
packets must update both the table and the test coverage if they
introduce new source labels.

Per-symbol generated/missing match the live builder exactly:
- BTCUSDT: 223 / 1688 (classifier matches `build_full_observation_status`)
- ETHUSDT: 223 / 1688 (matches)
- SOLUSDT: 213 / 1698 (matches)

## Validation

- `tools/v2_live_canary_validation_sweep.py` — **PASS** (22 files
  scanned, 0 secret / approval_true / legacy_redis /
  exchange_mutation hits, 0 JSON parse failures).
- All 11 JSON output artifacts are valid JSON.
- No new test failures across the prior 49-test full-observation
  suite (no builder code changed).

## What this packet did NOT do

- Did NOT modify the full-observation builder.
- Did NOT add any new feature projector or V2 source consumer.
- Did NOT call any exchange, provider, or WSS endpoint.
- Did NOT modify any Redis key.
- Did NOT mutate Symbol Universe (paper_symbols, training_symbols,
  live_symbols).
- Did NOT start policy architecture.
- Did NOT claim checkpoint compatibility.
- Did NOT claim policy architecture parity.
- Did NOT create any approval, Codex marker, live-enablement, or
  shutdown-acceptance artifact.
- Did NOT modify `/home/wali/Desktop/AI BOT`.
- Did NOT stop or modify the legacy or V2 runtime.
- Did NOT expose any raw API key value.
- Did NOT mark any field `V2_BUILDABLE_NOW` without verifying the
  exact V2 source key exists at runtime today (V2 keys read live
  during the classifier run).

## Safety pins

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `zero_filled_field_count=0`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- `writes_exchange_orders=false`
- `writes_legacy_redis=false`
- `writes_old_redis=false`
- `leverage_changed=false`
- `margin_mode_changed=false`
- `provider_network_calls_attempted=false`
- `raw_credential_in_payload=NEVER`
- `did_not_start_policy_architecture=true`
- `did_not_claim_checkpoint_compatibility=true`
- `did_not_mutate_symbol_universe=true`
- `did_not_create_approval_marker=true`
