# V2 Alt-Data Symbol Universe Frontend And Candidate Display Report

Generated: `2026-05-18T05:41:00Z`

GO/NO-GO: `V2_ALT_DATA_SYMBOL_UNIVERSE_FRONTEND_AND_CANDIDATE_DISPLAY_READY`

This packet does NOT approve live trading, canary trading, exchange mutation, leverage/margin changes, legacy shutdown, Redis trim, checkpoint compatibility, policy architecture parity, provider daemon enrollment, or trainer/risk/orchestrator wiring.

## Scope

Monitor Center now displays the paper/shadow alt-data Symbol Universe scoring payload and provider status payloads:

- `/operator_runtime/v2_alt_data_symbol_universe_scoring/latest/alt_data_symbol_universe_scoring_status.json`
- `/operator_runtime/v2_nansen_altdata_client/latest/v2_nansen_altdata_status.json`
- `/operator_runtime/v2_lunarcrush_altdata_client/latest/v2_lunarcrush_altdata_status.json`

## Displayed Fields

- Nansen source-status counts, key-present state, redaction marker, and rate-limit state.
- LunarCrush source-status counts, key-present state, redaction marker, and rate-limit state.
- Candidate rows with combined `altdata_symbol_score`, provider availability, provider freshness, Nansen status/score, LunarCrush status/score, and missing flags.
- `live_symbols=[]`.
- `paper_symbols_expanded=false`.
- strict paper-fill gate override remains forbidden.
- checkpoint and policy parity claims remain false.

## Current Provider State

The latest Codex-controlled one-shots returned `API_FORBIDDEN_403` for both providers, so candidate rows show explicit provider failure/missing flags and `null` scores. No synthetic scores are displayed.

## Validation

- `npm run -s typecheck`: PASS.
- No trading action code added.
- No provider API call code added.
- No old Redis write code added.
- No exchange mutation code added.
- No live/canary/shutdown approval added.

## Safety

- `live_gate = blocked_human_only`
- `live_symbols = []`
- `paper_symbols_expanded = false`
- `may_not_override_strict_paper_fill_gate = true`
- `approves_live = false`
- `approves_canary = false`
- `approves_legacy_shutdown = false`
- `approves_redis_trim = false`

## Final Decision

`V2_ALT_DATA_SYMBOL_UNIVERSE_FRONTEND_AND_CANDIDATE_DISPLAY_READY`
