# Codex Review: V2 Alt-Data Symbol Universe Candidate Publisher

Generated: `2026-05-22T02:11:31Z`

GO/NO-GO: `V2_ALT_DATA_SYMBOL_UNIVERSE_CANDIDATE_PUBLISHER_CODEX_PASS`

## Decision

Codex passes the candidate-publisher re-review after frontend schema alignment. The frontend reads and renders rows from the canonical `candidates` field, displays the candidate-only / not-adopted boundary, and renders no adopt, live, order, or shutdown controls. The backend remains V2-scoped and does not read paper/risk namespaces or mutate symbol sets.

This review does not approve candidate adoption, provider-client expansion, paid endpoints, live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, production equivalence, or legacy shutdown.

## Frontend Rendering

Reviewed:

- `v2/frontend/src/data/realtimeUserWebsitePayloads.ts`
- `v2/frontend/src/components/realtimeWebsite/index.tsx`
- `v2/frontend/src/pages/market/index.tsx`
- `v2/frontend/public/v2_alt_data_symbol_candidate_publisher/latest/operator_dashboard_payload.json`

Codex verified:

- `useAltDataCandidatePublisher()` reads `/v2_alt_data_symbol_candidate_publisher/latest/operator_dashboard_payload.json`.
- `CandidatePublisherPanel` resolves row data from `dashboard?.candidates` first.
- `candidate_summary` remains only a fallback alias.
- The public payload contains `candidates`, not just `candidate_summary`.

Browser render probe against `/market` on a local Vite server:

- candidate panel visible: `true`
- rendered candidate rows: `3`
- symbols visible: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`
- `MISSING_PROVIDER_DATA` visible
- `candidate_only_not_adopted=true` visible
- `live_symbol_candidate=false` visible
- `live_symbols_expanded=false` visible
- `paper_symbols_expanded=false` visible
- `training_symbols_expanded=false` visible
- recommendations-only / not-adopted copy visible
- strict paper-fill gate copy visible
- controls inside panel: `0`

No `<button>`, `<input>`, `<select>`, `<textarea>`, or `<form>` controls were rendered inside the candidate-publisher panel.

## Runtime Payload

After refreshing the publisher CLI, the public payload reports:

- `go_no_go=V2_ALT_DATA_SYMBOL_UNIVERSE_CANDIDATE_PUBLISHER_READY`
- `candidate_count=3`
- row key: `candidates`
- state counts: `MISSING_PROVIDER_DATA=3`
- `candidate_only_not_adopted=true`
- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `live_symbols_expanded=false`
- `paper_symbols_expanded=false`
- `training_symbols_expanded=false`
- `may_not_override_strict_paper_fill_gate=true`
- `may_not_authorize_live_or_canary=true`
- `may_not_place_orders=true`

Each current row has:

- `candidate_state=MISSING_PROVIDER_DATA`
- `proposed_use=[]`
- `candidate_only_not_adopted=true`
- `live_symbol_candidate=false`
- `paper_symbol_candidate=false`
- `training_symbol_candidate=false`
- `missing_provider_flags=[]`
- `stale_provider_flags=[]`

The empty provider flags are honest for the current missing-score state; the row columns remain visible.

## Backend Boundary

Reviewed:

- `v2/backend/app/services/alternative_data/symbol_candidate_publisher.py`
- `v2/backend/app/cli/v2_alt_data_symbol_candidate_publisher.py`
- `v2/backend/tests/integration/cli/test_v2_alt_data_symbol_candidate_publisher.py`
- `v2/backend/tests/integration/cli/test_v2_alt_data_symbol_candidate_publisher_frontend_wiring.py`

The publisher reads only:

- `v2:altdata:symbol_score:{symbol}`
- `v2:altdata:nansen:status`
- `v2:altdata:lunarcrush:status`
- `v2:market:prices:{symbol}`
- `v2:features:latest:{symbol}:{timeframe}`

Forbidden backend reads remain absent:

- `v2:paper:*`: `0`
- `v2:risk:*`: `0`
- legacy Redis current-truth prefixes: `0`

Allowed writes remain exactly:

- `v2:symbol_universe:altdata_candidates`
- `v2:altdata:candidate_publisher:status`

Current Redis scan found only those candidate-publisher output keys. No `paper_symbols`, `training_symbols`, or `live_symbols` mutation key is written by this lane.

## Safety

Codex verified:

- no raw credential values in reviewed source, tests, worklog/public payloads, or current publisher Redis values;
- no old Redis write path in the reviewed publisher/frontend path;
- no provider network-call import in the publisher path;
- no exchange order, cancel, modify, leverage, margin, `/fapi/`, or test-order mutation path in the reviewed publisher path;
- no live/canary/shutdown/Redis-trim approval drift.

Safety state remains:

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- `writes_old_redis=false`
- `writes_legacy_redis=false`
- `writes_exchange_orders=false`

Source-scan hits for `v2:paper:*`, `v2:risk:*`, symbol-set names, and order/shutdown terms are forbidden-namespace documentation, regression assertions, safety labels, or unrelated page text. They are not executable candidate-publisher reads, writes, or mutation controls.

## Validation

- Publisher CLI refresh: PASS.
- Backend candidate publisher tests plus frontend wiring regression tests: `33 passed`.
- Frontend typecheck: PASS.
- Frontend build: PASS.
- Browser render probe for `/market`: PASS, `3` rows visible and `0` controls in panel.
- Redis write allowlist check: PASS.
- Current Redis key scan: PASS, only the two candidate-publisher outputs.
- Raw credential scan: PASS, `0` file hits and `0` Redis hits outside `.local_secrets`.
- Old Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.

## Final Decision

`V2_ALT_DATA_SYMBOL_UNIVERSE_CANDIDATE_PUBLISHER_CODEX_PASS`
