# V2 Alt-Data Symbol-Universe Scoring — Input-Boundary Remediation

**Generated:** 2026-05-21 (UTC)
**GO_NO_GO:** `V2_ALT_DATA_SYMBOL_UNIVERSE_SCORING_INPUT_BOUNDARY_REMEDIATION_READY`
**Codex prior fail:** `SCORING_INPUT_BOUNDARY_INCLUDES_V2_PAPER_AND_RISK_CONTEXT`

## What Codex flagged

The previous scoring CLI's `_load_inputs_for_symbol` read three
Redis keys outside the alt-data input boundary:

- `v2:paper:positions`
- `v2:paper:ledger`
- `v2:risk:decisions`

And the worklog/public status payloads' `allowed_inputs` list
advertised `v2:paper:*` and `v2:risk:*` as legitimate inputs. The
review contract for this lane requires inputs to be strictly
limited to `v2:altdata:*`, `v2:market:*`, and V2 feature inputs.

## What changed

### 1. CLI input loader

[`_load_inputs_for_symbol`](v2/backend/app/cli/v2_alt_data_symbol_universe_scoring.py)
now reads ONLY:

- `v2:altdata:nansen:symbol:{symbol}`
- `v2:altdata:lunarcrush:symbol:{symbol}`
- `v2:market:prices:{symbol}` / `v2:market:funding:{symbol}` / `v2:market:open_interest:{symbol}`
- `v2:features:latest:{symbol}:{timeframe}`

The function's docstring documents the boundary explicitly and
names the Codex regression ID so future readers see the rule.

### 2. Contract signature

[`build_symbol_score_payload`](v2/backend/app/services/alternative_data/symbol_scoring_contract.py)
no longer accepts `paper_payloads` or `risk_payloads` keyword
arguments — passing them now raises `TypeError`. The
`input_presence` dict written into every per-symbol score payload
no longer contains `paper` or `risk` keys.

### 3. Advertised inputs / forbidden namespaces

The status payload's `allowed_inputs` list is now:

```
v2:altdata:nansen:status
v2:altdata:nansen:symbol:{symbol}
v2:altdata:lunarcrush:status
v2:altdata:lunarcrush:symbol:{symbol}
v2:market:prices:{symbol}
v2:market:funding:{symbol}
v2:market:open_interest:{symbol}
v2:features:latest:{symbol}:{timeframe}
```

A new explicit `forbidden_input_namespaces_for_alt_data_scoring`
field is `["v2:paper:*", "v2:risk:*"]` so an auditor can grep for
the explicit refusal. The new `scoring_input_boundary_remediated:
true` field documents the closure of the Codex regression.

### 4. Report body

The report's Scope paragraph now states the boundary explicitly
and notes that any paper/risk overlay belongs to a separately
reviewed lane (`V2_SYMBOL_UNIVERSE_PAPER_RISK_CONTEXT_OVERLAY`,
not in this packet).

## Tests

`test_v2_alt_data_symbol_universe_scoring.py` — **22 / 22 pass**
(14 original + 8 new regression tests):

- `test_cli_load_inputs_for_symbol_does_not_read_v2_paper_or_v2_risk_keys`
  — records every Redis `.get()` call from the loader; asserts no
  key starts with `v2:paper:` or `v2:risk:`.
- `test_cli_load_inputs_keys_returned_dict_has_no_paper_or_risk_fields`
  — confirms the returned dict has no `paper_payloads` /
  `risk_payloads` fields.
- `test_run_once_status_payload_does_not_advertise_v2_paper_or_v2_risk_inputs`
  — scans `allowed_inputs` for any `v2:paper`/`v2:risk` substring;
  asserts `forbidden_input_namespaces_for_alt_data_scoring`
  contains both prefixes; asserts
  `scoring_input_boundary_remediated=true`.
- `test_run_once_reads_no_v2_paper_or_v2_risk_keys_during_full_pipeline`
  — full 3-symbol pipeline; records every Redis read; asserts none
  start with the forbidden prefixes.
- `test_build_symbol_score_payload_input_presence_excludes_paper_and_risk`
  — asserts `paper` / `risk` are not keys of `input_presence`.
- `test_build_symbol_score_payload_rejects_paper_or_risk_kwargs`
  — passing `paper_payloads=` or `risk_payloads=` to the contract
  raises `TypeError`.
- `test_run_once_keeps_safety_pins_after_remediation` — `live_gate`,
  `live_symbols`, `paper_symbols_expanded`, and the per-symbol
  `may_not_override_strict_paper_fill_gate` /
  `may_not_authorize_live_or_canary` pins remain correct.
- `test_run_once_only_writes_to_allowlisted_keys` — every Redis
  write is `v2:altdata:symbol_score:{symbol}` or
  `v2:symbol_universe:altdata_candidates`; nothing leaks to
  `v2:paper:*` or `v2:risk:*` or any legacy namespace.

## Scoring output unchanged

The per-symbol score still produces:

- `smart_money_score`
- `social_momentum_score`
- `social_volume_velocity`
- `entity_flow_score`
- `altdata_freshness_score`
- `provider_availability_score`
- `altdata_symbol_rank`
- `missing_provider_flags`
- `stale_provider_flags`

plus the explicit per-provider degradation booleans (`*_key_present`,
`*_key_missing_no_network`, `*_budget_limited`). Missing /
key-missing / no-client-yet / budget-limited / stale provider
states all remain explicit.

## Redis write boundary (unchanged)

Allowed writes for this lane:

- `v2:altdata:symbol_score:{symbol}`
- `v2:symbol_universe:altdata_candidates`

A test in this suite proves these are the only keys ever written
during a full pipeline run.

## Safety pins (unchanged)

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `paper_symbols_expanded=false`
- `may_not_override_strict_paper_fill_gate=true` (per-symbol score)
- `may_not_authorize_live_or_canary=true` (per-symbol score)
- `may_not_place_orders=true` (per-symbol score)
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- `raw_credential_in_payload=NEVER` (provider client invariant)
- `provider_network_calls_attempted=false` (scorer never imports
  the provider client into the scoring path)
- `writes_old_redis=false`
- `writes_exchange_orders=false`
- `leverage_changed=false`
- `margin_mode_changed=false`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`

## What this packet did NOT do

- Did NOT start another audit.
- Did NOT change live or shutdown state.
- Did NOT modify the legacy bot tree.
- Did NOT touch `/home/wali/Desktop/AI BOT`.
- Did NOT write any legacy Redis key.
- Did NOT place / cancel / modify exchange orders.
- Did NOT change leverage or margin.
- Did NOT enable live trading.
- Did NOT create any new approval token.
- Did NOT expose any raw API key (the scorer never imports the
  provider clients into the scoring path).
- Did NOT add any paper or risk overlay to this scorer; that work
  is deliberately deferred to
  `V2_SYMBOL_UNIVERSE_PAPER_RISK_CONTEXT_OVERLAY`, a separately
  reviewed packet.
- Did NOT silently update `paper_symbols`, `training_symbols`, or
  `live_symbols`; the universe candidate list is a proposal, never
  a runtime override.

## Cross-references

- Source: [v2_alt_data_symbol_universe_scoring.py](v2/backend/app/cli/v2_alt_data_symbol_universe_scoring.py)
- Contract: [symbol_scoring_contract.py](v2/backend/app/services/alternative_data/symbol_scoring_contract.py)
- Tests: [test_v2_alt_data_symbol_universe_scoring.py](v2/backend/tests/integration/cli/test_v2_alt_data_symbol_universe_scoring.py)
