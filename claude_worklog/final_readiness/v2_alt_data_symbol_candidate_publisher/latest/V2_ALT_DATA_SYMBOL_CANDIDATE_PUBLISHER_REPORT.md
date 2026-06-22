# V2 Alt-Data Symbol Universe Candidate Publisher

**Generated:** 2026-05-21 (UTC)
**GO_NO_GO:** `V2_ALT_DATA_SYMBOL_UNIVERSE_CANDIDATE_PUBLISHER_READY`

## What shipped

A read-only candidate publisher that consumes the
Codex-approved alt-data scoring outputs plus V2 market and feature
inputs, classifies every symbol into one of seven explicit
candidate states, and writes two Redis keys + a public dashboard
payload. It NEVER mutates `live_symbols`, `paper_symbols`, or
`training_symbols`.

### Files

- [v2/backend/app/services/alternative_data/symbol_candidate_publisher.py](v2/backend/app/services/alternative_data/symbol_candidate_publisher.py)
  — pure service. `classify_candidate_state`, `build_candidate`,
  `build_candidate_list`, `safe_redis_set` (allowlist of exactly
  2 keys), `derive_proposed_uses`, `build_candidate_reason`.
- [v2/backend/app/cli/v2_alt_data_symbol_candidate_publisher.py](v2/backend/app/cli/v2_alt_data_symbol_candidate_publisher.py)
  — CLI. Reads ONLY:
  - `v2:altdata:symbol_score:{symbol}`
  - `v2:altdata:nansen:status`
  - `v2:altdata:lunarcrush:status`
  - `v2:market:prices:{symbol}`
  - `v2:features:latest:{symbol}:{timeframe}`
- [v2/backend/tests/integration/cli/test_v2_alt_data_symbol_candidate_publisher.py](v2/backend/tests/integration/cli/test_v2_alt_data_symbol_candidate_publisher.py)
  — 18 tests, all pass.

## Input boundary

The publisher reads ONLY the keys listed above. It NEVER reads:

- `v2:paper:*`
- `v2:risk:*`
- legacy Redis keys
- raw API key values

A regression test
(`test_cli_does_not_read_v2_paper_or_v2_risk_during_full_pipeline`)
records every Redis read on a fake-redis driver and asserts no
read starts with any of those forbidden prefixes. The published
payload explicitly lists
`forbidden_input_namespaces=["v2:paper:*", "v2:risk:*"]` so an
auditor can grep for the explicit refusal.

## Redis write boundary

Allowed writes (enforced by `safe_redis_set`):

- `v2:symbol_universe:altdata_candidates`
- `v2:altdata:candidate_publisher:status`

A regression test
(`test_safe_redis_set_refuses_keys_outside_publisher_allowlist`)
proves writes to `v2:paper:positions`, `v2:risk:decisions`,
`order_intent:BTCUSDT`, `trader:positions`,
`v2:symbol_universe:paper_symbols`,
`v2:symbol_universe:live_symbols`, and
`v2:symbol_universe:training_symbols` are all refused.

## Candidate-state classifier

Each candidate is classified into exactly one of seven states.
Priority order (highest first):

1. `SYMBOL_NOT_TRADABLE_ON_BINANCE` — no `v2:market:prices:{symbol}.ticker_24hr.lastPrice`.
2. `BUDGET_LIMITED` — Nansen or LunarCrush provider status reports
   `DAILY_BUDGET_EXHAUSTED` / `BUDGET_EXHAUSTED` / `BUDGET_LIMITED`
   / `RATE_LIMITED` / `HTTP_429` / `TOO_MANY_REQUESTS`.
3. `MISSING_PROVIDER_DATA` — `v2:altdata:symbol_score:{symbol}`
   absent OR `altdata_symbol_score` is null OR `providers_consulted`
   is empty OR `missing_provider_flags` non-empty.
4. `STALE_PROVIDER_DATA` — `stale_provider_flags` non-empty OR
   `stale_signal=true`.
5. `BELOW_THRESHOLD` — score < `watchlist_threshold` (default 0.10).
6. `SYMBOL_UNIVERSE_GATE_REQUIRED` — score ≥ `paper_threshold`
   (default 0.30); adoption to paper/training requires the
   existing Symbol Universe governance gate, NOT this publisher.
7. `CANDIDATE_READY` — score is in the watchlist-only band
   `[watchlist_threshold, paper_threshold)`; watchlist proposal
   needs no extra gate.

## Proposed-use tiering

For `CANDIDATE_READY` and `SYMBOL_UNIVERSE_GATE_REQUIRED`:

- `watchlist_candidate` when score ≥ watchlist_threshold (0.10)
- `paper_symbol_candidate` when score ≥ paper_threshold (0.30)
- `training_symbol_candidate` when score ≥ training_threshold (0.50)
- `live_symbol_candidate=false` ALWAYS — the publisher never
  proposes a live order. A regression test
  (`test_build_candidate_pins_safety_invariants_and_never_proposes_live_use`)
  asserts this on every code path.

## Required output fields

Each candidate carries exactly the fields the user spec required:

- `symbol`
- `altdata_symbol_rank` (from upstream scorer)
- `candidate_publisher_rank` (assigned by publisher sort)
- `altdata_symbol_score`
- `smart_money_score`
- `social_momentum_score`
- `social_volume_velocity`
- `entity_flow_score`
- `provider_availability_score`
- `altdata_freshness_score`
- `missing_provider_flags`
- `stale_provider_flags`
- `candidate_reason` (deterministic operator-readable string)
- `candidate_state` (one of the 7 states above)
- `proposed_use` (list)
- `live_symbol_candidate=false`

Plus immutable safety pins on every candidate:
`may_not_override_strict_paper_fill_gate`,
`may_not_authorize_live_or_canary`, `may_not_place_orders`,
`live_gate=blocked_human_only`, `live_symbols=[]`,
`raw_credential_in_payload=NEVER`, `writes_old_redis=false`,
`writes_exchange_orders=false`, `leverage_changed=false`,
`margin_mode_changed=false`, `candidate_only_not_adopted=true`.

## Runtime payload snapshot

Current live-Redis snapshot:

```
candidate_count=3
candidate_state_counts={
  "BELOW_THRESHOLD": 0,
  "BUDGET_LIMITED": 0,
  "CANDIDATE_READY": 0,
  "MISSING_PROVIDER_DATA": 3,
  "STALE_PROVIDER_DATA": 0,
  "SYMBOL_NOT_TRADABLE_ON_BINANCE": 0,
  "SYMBOL_UNIVERSE_GATE_REQUIRED": 0
}
```

All 3 candidates (BTCUSDT, ETHUSDT, SOLUSDT) classify as
`MISSING_PROVIDER_DATA` because the upstream Nansen and LunarCrush
per-symbol payloads are not yet present (the scoring lane's
provider clients only have status entries; per-symbol payloads
land when the future Nansen/LunarCrush daemons run). The
publisher honestly surfaces this state; no candidate is silently
promoted.

## Tests

`test_v2_alt_data_symbol_candidate_publisher.py` — **18 / 18 pass**.

State-classifier tests (one per state):

- `test_classify_symbol_not_tradable_when_market_prices_absent`
- `test_classify_budget_limited_when_lunarcrush_status_marks_budget`
- `test_classify_budget_limited_when_nansen_status_marks_rate_limit`
- `test_classify_missing_provider_data_when_symbol_score_absent`
- `test_classify_missing_provider_data_when_altdata_score_is_null`
- `test_classify_stale_provider_data_when_stale_flags_present`
- `test_classify_below_threshold_when_score_too_low`
- `test_classify_candidate_ready_for_watchlist_band`
- `test_classify_symbol_universe_gate_required_when_score_above_paper_threshold`

Candidate-construction tests:

- `test_build_candidate_pins_safety_invariants_and_never_proposes_live_use`
- `test_build_candidate_below_threshold_has_no_proposed_uses`
- `test_build_candidate_reason_strings_are_state_specific` (all 7
  states produce non-empty reason strings)

CLI / Redis-boundary tests:

- `test_cli_pipeline_reads_only_allowlisted_keys_no_paper_no_risk`
- `test_safe_redis_set_refuses_keys_outside_publisher_allowlist`
- `test_payload_does_not_serialize_synthetic_credential`
- `test_cli_does_not_read_v2_paper_or_v2_risk_during_full_pipeline`
- `test_cli_pipeline_does_not_mutate_symbol_universe_sets`
- `test_cli_legend_and_state_counts_match_candidates`

## Validation sweep

`tools/v2_live_canary_validation_sweep.py` PASS at 22 files; 0
secret hits, 0 approval_true hits, 0 legacy Redis writes, 0
exchange-mutation verbs, 0 JSON parse failures.

## What this packet did NOT do

- Did NOT mutate `live_symbols`, `paper_symbols`, or
  `training_symbols`.
- Did NOT call any provider endpoint.
- Did NOT call any exchange endpoint.
- Did NOT read `v2:paper:*` or `v2:risk:*`.
- Did NOT write any legacy Redis namespace.
- Did NOT change leverage or margin.
- Did NOT enable live trading.
- Did NOT create any approval token, Codex marker, or live
  enablement.
- Did NOT modify `/home/wali/Desktop/AI BOT`.
- Did NOT stop or modify the legacy or V2 runtime.
- Did NOT expose any raw API key value.
- Did NOT touch the live-canary execution adapter, permission
  probe, dry-run service, website backend, or any other Codex-passed
  lane.

## Safety pins (every payload, every tick)

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `live_symbols_expanded=false`
- `paper_symbols_expanded=false`
- `training_symbols_expanded=false`
- `dry_run=true` (publisher is read-only display)
- `live_enabled=false`
- `real_order_attempted=false`
- `real_order_submitted=false`
- `places_real_order=false`
- `writes_exchange_orders=false`
- `writes_legacy_redis=false`
- `writes_old_redis=false`
- `leverage_changed=false`
- `margin_mode_changed=false`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- `raw_credential_in_payload=NEVER`
- `provider_network_calls_attempted=false`
- `may_not_override_strict_paper_fill_gate=true`
- `may_not_authorize_live_or_canary=true`
- `may_not_place_orders=true`
- `candidate_only_not_adopted=true`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`

## Frontend rendering

The Top-10 dashboards renderer + `Top10Panel` component already
in place will pick up `v2:altdata:nansen:status` /
`v2:altdata:lunarcrush:status` + per-symbol scoring data through
its existing pipeline. The publisher's own
`v2:altdata:candidate_publisher:status` + the candidate list
payload are also available at the public mirror path
`v2/frontend/public/v2_alt_data_symbol_candidate_publisher/latest/operator_dashboard_payload.json`
for a future "Candidate Watchlist" panel. (This packet ships the
payload; a frontend panel is a separate display-only follow-up.)
