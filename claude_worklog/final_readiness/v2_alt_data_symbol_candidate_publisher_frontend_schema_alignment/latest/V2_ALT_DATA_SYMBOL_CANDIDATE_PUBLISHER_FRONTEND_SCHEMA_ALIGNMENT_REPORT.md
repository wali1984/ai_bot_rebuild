# V2 Alt-Data Symbol Candidate Publisher — Frontend Schema Alignment

**Generated:** 2026-05-21 (UTC)
**GO_NO_GO:** `V2_ALT_DATA_SYMBOL_CANDIDATE_PUBLISHER_FRONTEND_SCHEMA_ALIGNMENT_READY`

## Why this packet exists

The prior wiring packet
[`V2_ALT_DATA_SYMBOL_CANDIDATE_PUBLISHER_FRONTEND_WIRING_READY`](../../v2_alt_data_symbol_candidate_publisher_frontend_wiring/latest/V2_ALT_DATA_SYMBOL_CANDIDATE_PUBLISHER_FRONTEND_WIRING_REPORT.md)
mounted the panel and the six adoption labels, but Codex flagged a
re-review blocker:

```
FRONTEND_PUBLIC_PAYLOAD_SCHEMA_MISMATCH_HIDES_CANDIDATE_ROWS
```

The served public payload at
`v2/frontend/public/v2_alt_data_symbol_candidate_publisher/latest/operator_dashboard_payload.json`
emits rows under the key `candidates`, while the panel was reading
`dashboard?.candidate_summary`. Result: `candidate_count=3` in the
payload, but the panel rendered its "no candidates" fallback because
the row array it read was undefined.

This packet remediates that with the smallest possible change:
**rename the canonical row key in the frontend to `candidates`**,
keep `candidate_summary` as a backward-compatible alias, and add a
regression test that fails if anyone ever reverses the preference.

No backend scope was touched. No Symbol Universe adoption.

## What shipped

### Files modified

- [v2/frontend/src/data/realtimeUserWebsitePayloads.ts](../../../../v2/frontend/src/data/realtimeUserWebsitePayloads.ts)
  - `AltDataCandidatePublisherDashboard` now declares
    `candidates?: AltDataCandidateSummaryRow[]` as the canonical row
    field, with `candidate_summary` kept as a deprecated alias.
  - `AltDataCandidateSummaryRow` gained `altdata_symbol_rank`,
    `candidate_reason`, `candidate_only_not_adopted`,
    `paper_symbol_candidate`, `training_symbol_candidate`, and
    `watchlist_candidate`.

- [v2/frontend/src/components/realtimeWebsite/index.tsx](../../../../v2/frontend/src/components/realtimeWebsite/index.tsx)
  - `CandidatePublisherRowLite` mirrors the extended row fields.
  - Panel prop type now accepts `candidates?: CandidatePublisherRowLite[]`.
  - The candidate-row resolver block prefers `dashboard?.candidates`
    over the legacy `candidate_summary` alias:
    ```ts
    const candidateRows: CandidatePublisherRowLite[] =
      (dashboard?.candidates && dashboard.candidates.length > 0
        ? dashboard.candidates
        : dashboard?.candidate_summary ?? []) as CandidatePublisherRowLite[];
    ```
  - The table renders three new columns: `altdata_symbol_rank`,
    `candidate_only_not_adopted`, `candidate_reason`.
  - Empty state is tagged
    `data-testid="candidate-publisher-empty-state"` so future
    operator-side tests can distinguish "renders empty" from
    "fails to render" without ambiguity.

### Files NOT modified

- `v2/backend/app/services/alternative_data/symbol_candidate_publisher.py`
- `v2/backend/app/cli/v2_alt_data_symbol_candidate_publisher.py`
- Any legacy bot file under `../AI BOT/`.
- Any Redis schema, allowlist, or write boundary.
- Any leverage/margin/mode/runtime setting.

## Schema-mismatch regression coverage

[test_v2_alt_data_symbol_candidate_publisher_frontend_wiring.py](../../../../v2/backend/tests/integration/cli/test_v2_alt_data_symbol_candidate_publisher_frontend_wiring.py)
gained four new tests:

| # | test | what it proves |
|---|------|---------------|
| 1 | `test_panel_reads_candidates_as_canonical_row_field` | The panel body references `dashboard?.candidates` and declares `candidates?: CandidatePublisherRowLite[]` in its prop type |
| 2 | `test_payloads_ts_declares_candidates_field` | The shared dashboard interface declares `candidates?: AltDataCandidateSummaryRow[]` |
| 3 | `test_panel_renders_candidates_with_no_candidate_summary_alias` | The candidateRows resolver prefers `candidates` ahead of `candidate_summary` (positional check on the ?? chain) |
| 4 | `test_public_payload_uses_canonical_candidates_key` | The served public payload exposes `candidates` with every required row field (`symbol`, `candidate_state`, `candidate_reason`, `live_symbol_candidate`, `candidate_only_not_adopted`, `missing_provider_flags`, `stale_provider_flags`, `proposed_use`) |

If anyone later reverts the panel to read `candidate_summary` only,
or if the publisher emits rows under a non-canonical key, the
regression tests fire before reaching Codex.

## Tests

**33 / 33 pass** across both suites:

- Backend publisher suite —
  [test_v2_alt_data_symbol_candidate_publisher.py](../../../../v2/backend/tests/integration/cli/test_v2_alt_data_symbol_candidate_publisher.py) — 18 / 18 pass (no regression).
- Frontend wiring + schema-alignment suite —
  [test_v2_alt_data_symbol_candidate_publisher_frontend_wiring.py](../../../../v2/backend/tests/integration/cli/test_v2_alt_data_symbol_candidate_publisher_frontend_wiring.py) — 15 / 15 pass (11 wiring + 4 new schema-alignment).

## Frontend build status

- `npm run typecheck` (`tsc -b --noEmit`) — **PASS**
- `npm run build` (Vite production build) — **PASS**.
  215 modules, 539.56 kB JS (140.78 kB gzipped), 68.55 kB CSS (11.75 kB gzipped), built in 1.38 s.

## Validation sweep

`tools/v2_live_canary_validation_sweep.py` — **PASS**.
22 files scanned. 0 secret hits, 0 approval_true hits,
0 legacy_redis_hits, 0 exchange_mutation_hits, 0 JSON parse
failures, 0 missing files.

## Public payload mirror

The served publisher payload at
[v2/frontend/public/v2_alt_data_symbol_candidate_publisher/latest/operator_dashboard_payload.json](../../../../v2/frontend/public/v2_alt_data_symbol_candidate_publisher/latest/operator_dashboard_payload.json)
already uses the canonical `candidates` key (it has not changed and
was generated by the prior packet's publisher CLI). The frontend now
reads it correctly.

A frontend-schema-alignment-scoped truth payload mirror is also
published at
`v2/frontend/public/v2_alt_data_symbol_candidate_publisher_frontend_schema_alignment/latest/operator_dashboard_payload.json`.

## What the operator now sees

Each candidate row visibly surfaces:

- `#` (candidate_publisher_rank)
- `altdata_symbol_rank`
- `Symbol`
- `candidate_state` chip (colour-coded per state)
- `altdata_symbol_score`
- `proposed_use`
- `missing_provider_flags`
- `stale_provider_flags`
- `candidate_only_not_adopted` chip (green when true; red if ever false)
- `live_symbol_candidate` chip (green when false; red if ever true)
- `candidate_reason` (publisher-provided operator-readable string)

For the current snapshot (BTCUSDT / ETHUSDT / SOLUSDT all in
`MISSING_PROVIDER_DATA`), the operator now sees three rows with the
warn-tone MISSING_PROVIDER_DATA chip, an empty `proposed_use`, the
reason string `v2:altdata:symbol_score:{symbol} absent.`, and the
green `candidate_only_not_adopted=true` chip. No row is hidden;
nothing is fabricated.

## What this packet did NOT do

- Did NOT change the backend candidate-publisher scoring rules.
- Did NOT change the backend publisher's Redis reads or writes.
- Did NOT mutate `live_symbols`, `paper_symbols`, or
  `training_symbols`.
- Did NOT add any `<button>`, `<form>`, `<input>`, `<select>`,
  `<textarea>`, `onClick`, `onSubmit`, `onChange`, or network call
  to the candidate publisher panel.
- Did NOT call any exchange endpoint.
- Did NOT call any provider endpoint.
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
  probe, dry-run service, website backend, or any other
  Codex-passed lane.

## Safety pins

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `live_symbols_expanded=false`
- `paper_symbols_expanded=false`
- `training_symbols_expanded=false`
- `candidate_only_not_adopted=true`
- `writes_exchange_orders=false`
- `writes_legacy_redis=false`
- `writes_old_redis=false`
- `leverage_changed=false`
- `margin_mode_changed=false`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- `raw_credential_in_payload="NEVER"`
- `provider_network_calls_attempted=false`
- `may_not_override_strict_paper_fill_gate=true`
- `may_not_authorize_live_or_canary=true`
- `may_not_place_orders=true`
- `places_real_order=false`
- `real_order_attempted=false`
- `real_order_submitted=false`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`
