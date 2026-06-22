# Codex Review: V2 Full-Observation Portfolio-State Burndown

Generated: `2026-05-22T02:26:17Z`

GO/NO-GO: `V2_FULL_OBSERVATION_PORTFOLIO_STATE_BURNDOWN_CODEX_PASS_PARTIAL_PROGRESS`

## Decision

Codex passes the V2 full-observation portfolio-state burndown as partial progress. The dimension increase is backed by V2-owned evidence, the builder remains partial, unknown fields are not zero-filled, and the packet does not claim checkpoint compatibility, policy architecture parity, live trading, canary trading, exchange mutation, Redis trim, approvals, or legacy shutdown.

## Scope Reviewed

Reviewed:

- `v2/backend/app/services/rl_core/full_observation_builder.py`
- `v2/backend/tests/integration/cli/test_v2_full_observation_portfolio_state_burndown.py`
- `claude_worklog/final_readiness/v2_full_observation_portfolio_state_burndown/latest/portfolio_state_burndown_status.json`
- `claude_worklog/final_readiness/v2_full_observation_portfolio_state_burndown/latest/full_observation_builder_status.json`
- `v2/frontend/public/v2_full_observation_portfolio_state_burndown/latest/operator_dashboard_payload.json`
- `v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json`

## Generated Dimensions

After refreshing `v2_full_observation_builder_status --once`, the live operator-runtime payload reports:

| Symbol | Generated Dim | Missing Dim | State |
| --- | ---: | ---: | --- |
| `BTCUSDT` | `217` | `1694` | `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS` |
| `ETHUSDT` | `217` | `1694` | `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS` |
| `SOLUSDT` | `207` | `1704` | `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS` |

The packet status mirrors report the same target dimension of `1911`, `zero_filled_field_count=0`, `no_zero_fill_for_unknown_fields=true`, and partial status. `FULL_OBSERVATION_BUILDER_COMPLETE` is not claimed.

## V2 Source Boundary

The status builder reads V2-owned keys only for this expansion:

- `v2:paper:positions`
- `v2:paper:ledger`
- `v2:paper:intents`
- `v2:paper:intents_held_by_paper_fill_gate`
- `v2:risk:decisions`
- `v2:orchestrator:decisions`
- `v2:trainer:heartbeat`
- `v2:symbol_universe:altdata_candidates`
- `v2:features:latest:{symbol}:{timeframe}`
- `v2:prediction:{symbol}:{timeframe}`
- `v2:market:prices:{symbol}`
- `v2:market:funding:{symbol}`
- `v2:market:open_interest:{symbol}`
- `v2:paper:position_price_track:{symbol}`
- `v2:paper:position_history:{symbol}`
- `v2:altdata:symbol_score:{symbol}`

Codex found no legacy Redis `features:*` or old production key read used as current truth. Source matches for legacy terms are schema metadata, comments, and safety fields such as `no_legacy_features_consumed_as_current_truth=true`.

## Portfolio Honesty

Direct builder proof from current Redis showed the new portfolio-state fields are evidence-backed:

- accepted fill count: `0.0` from `V2_PAPER_LEDGER_ACCEPTED_FILLS_SAFE`;
- held-by-gate count: `1.0` from held V2 paper context;
- shadow observation count: `2.0` globally, with BTCUSDT/ETHUSDT at `1.0` and SOLUSDT at `0.0`;
- held/shadow rows do not count as accepted fills;
- realized PnL fields remain `None` with `MISSING_V2_REALIZED_PNL`;
- unrealized PnL fields remain `None` with `MISSING_V2_UNREALIZED_PNL`;
- tracker MFE/MAE/ROE remain `None` with explicit missing tracker sources.

Alt-data candidate fields are context only:

- `portfolio_altdata_candidate_only_not_adopted=1.0`;
- `portfolio_altdata_live_symbols_expanded=0.0`;
- `portfolio_altdata_paper_symbols_expanded=0.0`;
- `portfolio_altdata_training_symbols_expanded=0.0`;
- per-symbol live, paper, and training candidate flags are `0.0`;
- sources are labeled `V2_ALTDATA_CANDIDATE_CONTEXT_NO_ADOPTION_AUTHORITY` where adoption authority would otherwise be ambiguous.

## Safety

Codex verified:

- no Redis write call in the reviewed builder/status path;
- no old Redis write path in reviewed source;
- no exchange order, cancel, modify, leverage, margin, `/fapi/`, or test-order mutation path in reviewed source;
- no live/canary/shutdown/Redis-trim approval drift;
- raw credential-value scan over reviewed source, tests, worklog/public payloads: `0` hits outside `.local_secrets`;
- `live_gate=blocked_human_only`;
- `live_symbols=[]`;
- `checkpoint_compatibility_claimed=false`;
- `policy_architecture_parity_claimed=false`;
- `approves_live=false`;
- `approves_canary=false`;
- `approves_legacy_shutdown=false`;
- `approves_redis_trim=false`.

Frontend/public payloads show the partial state honestly: generated dimensions, missing dimensions, partial status, zero-fill count, and blocked live state are visible in the refreshed public/operator-runtime mirrors.

## Validation

- Full-observation status refresh: PASS.
- Focused portfolio/full-observation test sweep: `57 passed`.
- `py_compile`: PASS.
- Direct current-Redis portfolio field proof: PASS.
- V2-only read inspection: PASS.
- Zero-fill invariant: PASS.
- Partial-status payload inspection: PASS.
- Redis write scan: PASS, no writes in reviewed builder path.
- Old Redis/current-truth scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.
- Raw credential scan: PASS, `0` hits.
- Validation sweep: PASS, `22` files scanned, `0` secret hits, `0` approval-true hits, `0` legacy Redis hits, `0` exchange mutation hits.

## Final Decision

`V2_FULL_OBSERVATION_PORTFOLIO_STATE_BURNDOWN_CODEX_PASS_PARTIAL_PROGRESS`
