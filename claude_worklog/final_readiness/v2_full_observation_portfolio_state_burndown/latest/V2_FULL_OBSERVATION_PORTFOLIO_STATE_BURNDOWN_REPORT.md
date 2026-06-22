# V2 Full-Observation Portfolio-State Burndown

Generated: `2026-05-22T02:07:15Z`

GO/NO-GO: `V2_FULL_OBSERVATION_PORTFOLIO_STATE_BURNDOWN_READY_PARTIAL_PROGRESS`

This packet does not approve live trading, canary trading, exchange
mutation, leverage/margin changes, Redis trim, approval creation,
checkpoint compatibility, policy architecture parity, production
equivalence, or legacy shutdown.

## Scope

Post-tracker position feature expansion has Codex PASS. This packet
continues full-observation builder burndown by expanding the 401-dim
`portfolio_state` slice using V2-owned paper, risk, prediction,
trainer, orchestrator, tracker-context, and alt-data candidate evidence.

The builder remains partial. No policy architecture work was started
and no checkpoint compatibility is claimed.

## Files Changed

- `v2/backend/app/services/rl_core/full_observation_builder.py`
- `v2/backend/tests/integration/cli/test_v2_full_observation_portfolio_state_burndown.py`

## Source Boundary

Allowed inputs for this packet:

- `v2:paper:positions`
- `v2:paper:ledger`
- `v2:paper:intents`
- `v2:paper:intents_held_by_paper_fill_gate`
- `v2:paper:position_history:{symbol}`
- `v2:risk:decisions`
- `v2:prediction:{symbol}:1m`
- `v2:trainer:heartbeat`
- `v2:orchestrator:decisions`
- `v2:altdata:symbol_score:{symbol}`
- `v2:symbol_universe:altdata_candidates`

The portfolio-state path is generic portfolio context. It does not
change or weaken the tracker-derived position-history field boundary.
Tracker-derived position-history fields remain in their existing
tracker-only extractors and continue to consume only tracker-owned
payloads.

## Added Portfolio-State Context

The expansion adds V2-owned context across:

- portfolio exposure summary;
- paper ledger summary;
- risk-gate summary;
- blocked-vs-accepted paper intent summary;
- held-by-paper-fill-gate summary;
- alt-data candidate context;
- per-symbol portfolio rollups;
- payload freshness and missing/stale flag counts.

Accepted fill counts now use a safe accepted-fill filter. Held,
shadow, blocked, and rejected rows are counted separately and are not
counted as accepted fills. Duplicate held rows across
`v2:paper:ledger` and `v2:paper:intents_held_by_paper_fill_gate` are
deduped by intent/prediction identity before per-symbol held rollups.

## No Fabrication

The builder does not fabricate portfolio PnL:

- realized PnL fields stay `None` unless V2 ledger close rows carry
  realized PnL;
- unrealized PnL fields stay `None` unless V2 paper position rows carry
  unrealized PnL.

The builder does not fabricate MFE, MAE, or ROE:

- tracker MFE / MAE / ROE fields stay `None` while the current tracker
  reports `NO_OPEN_POSITION`.

Alt-data candidate fields are context only:

- `candidate_only_not_adopted=true`
- `live_symbols_expanded=false`
- `paper_symbols_expanded=false`
- `training_symbols_expanded=false`
- `live_symbol_candidate=false`

Those fields do not authorize trading or mutate symbol sets.

## Runtime Status

Refreshed `full_observation_builder_status.json`:

| Symbol | Before | After | Missing After |
| --- | ---: | ---: | ---: |
| `BTCUSDT` | `160` | `217` | `1694` |
| `ETHUSDT` | `160` | `217` | `1694` |
| `SOLUSDT` | `154` | `207` | `1704` |

The builder still reports:

- `state=FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`
- `target_full_observation_dim=1911`
- `zero_filled_field_count=0`
- `no_zero_fill_for_unknown_fields=true`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`
- `live_gate=blocked_human_only`
- `live_symbols=[]`

## Current Evidence Samples

Current live V2 paper evidence:

- accepted fill count: `0`
- ledger held-by-gate count: `1`
- ledger shadow observation count: `2`
- SOLUSDT per-symbol held-by-gate count after dedupe: `1`
- BTCUSDT / ETHUSDT per-symbol shadow observation count: `1`
- SOLUSDT prediction paper-fill allowed: `0`
- BTCUSDT / ETHUSDT prediction paper-fill allowed: `1`
- tracker MFE / MAE / ROE: `None`, because tracker state is
  `NO_OPEN_POSITION`
- alt-data candidate state: `MISSING_PROVIDER_DATA`
- candidate rows remain not adopted automatically

## Outputs

- `claude_worklog/final_readiness/v2_full_observation_portfolio_state_burndown/latest/GO_NO_GO.md`
- `claude_worklog/final_readiness/v2_full_observation_portfolio_state_burndown/latest/V2_FULL_OBSERVATION_PORTFOLIO_STATE_BURNDOWN_REPORT.md`
- `claude_worklog/final_readiness/v2_full_observation_portfolio_state_burndown/latest/portfolio_state_burndown_status.json`
- `claude_worklog/final_readiness/v2_full_observation_portfolio_state_burndown/latest/full_observation_builder_status.json`
- `v2/frontend/public/v2_full_observation_portfolio_state_burndown/latest/full_observation_builder_status.json`
- `v2/frontend/public/v2_full_observation_portfolio_state_burndown/latest/operator_dashboard_payload.json`
- `v2/frontend/public/v2_model_parity_sprint/latest/full_observation_builder_status.json`
- `claude_worklog/final_readiness/v2_model_parity_sprint/latest/full_observation_builder_status.json`

## Validation

- Focused portfolio-state tests: `5 passed`.
- Combined full-observation tests: `57 passed`.
- `py_compile`: PASS.
- Full-observation status refresh: PASS.
- Live status remains partial: PASS.
- `zero_filled_field_count=0`: PASS.
- Raw credential scan: PASS, `0` hits outside `.local_secrets`.
- Old Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.
- Validation sweep: PASS, `22` files scanned, `0` secret hits,
  `0` approval-true hits, `0` legacy Redis hits, `0` exchange mutation
  hits.

## Safety Posture

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `live_enabled=false`
- `writes_legacy_redis=false`
- `writes_exchange_orders=false`
- `places_real_order=false`
- `leverage_changed=false`
- `margin_mode_changed=false`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- `raw_credential_in_payload=NEVER`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`
- `no_zero_fill_for_unknown_fields=true`
- `zero_filled_field_count=0`
- legacy code: unmodified
- legacy runtime: not stopped, not touched
- old Redis namespaces: not written
- exchange mutation surface: none introduced
- approvals: none created

## Final Decision

`V2_FULL_OBSERVATION_PORTFOLIO_STATE_BURNDOWN_READY_PARTIAL_PROGRESS`
