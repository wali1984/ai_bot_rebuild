# V2 Alt-Data Symbol Candidate Publisher — Frontend Wiring

**Generated:** 2026-05-21 (UTC)
**GO_NO_GO:** `V2_ALT_DATA_SYMBOL_CANDIDATE_PUBLISHER_FRONTEND_WIRING_READY`

## Why this packet exists

The prior packet
[`V2_ALT_DATA_SYMBOL_UNIVERSE_CANDIDATE_PUBLISHER_READY`](../../v2_alt_data_symbol_candidate_publisher/latest/V2_ALT_DATA_SYMBOL_CANDIDATE_PUBLISHER_REPORT.md)
shipped the backend candidate publisher service + CLI and was
Codex-PASSed for backend scope. Codex flagged one fail blocker:

```
FRONTEND_CANDIDATE_PUBLISHER_AUTO_ADOPTION_MESSAGE_NOT_WIRED
```

The blocker: nothing on the operator dashboard explicitly tells the
operator that alt-data candidates are recommendations only and are
**not** auto-promoted into `training_symbols`, `paper_symbols`, or
`live_symbols`. The truth was in the payload; it was not on the
screen.

This packet remediates that — display layer only. No backend scope
change. No Symbol Universe adoption. No live/canary enablement.

## What shipped

Three frontend files were touched. No backend file was touched
beyond what was already shipped in the prior packet.

### Files modified

- [v2/frontend/src/data/realtimeUserWebsitePayloads.ts](../../../../v2/frontend/src/data/realtimeUserWebsitePayloads.ts)
  - Added `PAYLOAD_PATHS.alt_data_candidate_publisher` pointing at
    `/v2_alt_data_symbol_candidate_publisher/latest/operator_dashboard_payload.json`.
  - Added types `AltDataCandidateState`,
    `AltDataCandidateSummaryRow`,
    `AltDataCandidatePublisherDashboard` (extends `SafetyEnvelope`).
  - Added `useAltDataCandidatePublisher(pollMs = 60_000)` hook.

- [v2/frontend/src/components/realtimeWebsite/index.tsx](../../../../v2/frontend/src/components/realtimeWebsite/index.tsx)
  - Added local row type `CandidatePublisherRowLite`.
  - Added per-state colour map `CANDIDATE_STATE_TONE`.
  - Added exported component `CandidatePublisherPanel` —
    display-only, no `<button>`, no `<form>`, no `<input>`, no
    event handlers, no network call.
  - Renders the six Codex-required adoption labels as
    `BlockerChip` rows inside a strip tagged
    `data-testid="candidate-publisher-adoption-labels"`.
  - Renders the safety pins (`candidate_only_not_adopted`,
    `live_symbols_expanded`, `paper_symbols_expanded`,
    `training_symbols_expanded`, `raw_credential_in_payload`,
    `writes_exchange_orders`,
    `may_not_override_strict_paper_fill_gate`, plus the three
    threshold values) as `MetricCard` chips.
  - Renders the candidate state-count `BlockerChip` summary.
  - Renders the candidate-row table (data-testid
    `candidate-publisher-table`) with columns
    `#`, `Symbol`, `candidate_state`, `altdata_symbol_score`,
    `proposed_use`, `missing_provider_flags`,
    `stale_provider_flags`, `live_symbol_candidate`.
  - When the payload is absent or stale, renders the standard
    `PayloadMissingCard` referencing the public payload path —
    no fabricated candidate is ever shown.

- [v2/frontend/src/pages/market/index.tsx](../../../../v2/frontend/src/pages/market/index.tsx)
  - Imports `CandidatePublisherPanel` and
    `useAltDataCandidatePublisher`.
  - Calls the hook in the page body.
  - Renders the panel in a new section tagged
    `data-testid="alt-data-candidate-publisher-section"`,
    inserted between the Top-10 alt-data grid (section 3) and the
    legacy Binance-feed cross-reference (section 3b).

### Files NOT modified

- `v2/backend/app/services/alternative_data/symbol_candidate_publisher.py`
- `v2/backend/app/cli/v2_alt_data_symbol_candidate_publisher.py`
- Any legacy bot file under `../AI BOT/`.
- Any V2 runtime systemd unit.
- Any leverage/margin/mode setting.

## Six required adoption labels — rendered verbatim

These six strings are required by the Codex blocker remediation and
are rendered in the order shown, as `BlockerChip` rows inside the
adoption-strip element. They are NOT buttons; they are static
operator-facing chips that are always visible whenever the panel
mounts, even when the payload is loading or errored.

1. `Candidate only — not adopted`
2. `Does not change training_symbols`
3. `Does not change paper_symbols`
4. `Does not change live_symbols`
5. `Cannot override strict paper-fill gate`
6. `Live trading remains blocked`

## Safety envelope on the panel

Every render pins the following safety envelope and surfaces it on
the dashboard via `MetricCard` chips that turn red if violated:

- `candidate_only_not_adopted=true`
- `live_symbols_expanded=false`
- `paper_symbols_expanded=false`
- `training_symbols_expanded=false`
- `raw_credential_in_payload="NEVER"`
- `writes_exchange_orders=false`
- `may_not_override_strict_paper_fill_gate=true`
- `live_gate=blocked_human_only`
- `live_symbols=[]`

If a future payload tick flips any of these, the chip turns red
and the operator can see the regression immediately. The chips
intentionally do NOT trust the underlying boolean blindly — the
`tone` is bound to the actual rendered value.

## Display-only safety boundary (enforced by static-source test)

The CandidatePublisherPanel JSX body is asserted to contain none of
the following tokens:

```
<button   <Button   <form   <Form   <input   <Input   <select   <Select
<textarea <Textarea onClick= onSubmit= onChange= onMouseDown=
onKeyDown= onMouseUp= useMutation fetch( axios. XMLHttpRequest
```

This is a stronger boundary than verb-matching on text. The panel
*must* contain text like `"Candidate only — not adopted"` and
`"candidate_only_not_adopted"` (those are the Codex requirement),
but it cannot do anything when an operator interacts with it
because it has no action-capable JSX at all.

The same boundary is enforced on the `/market` page region inside
the `alt-data-candidate-publisher-section`.

## Honest rendering of MISSING_PROVIDER_DATA

The current live-Redis snapshot has 3 candidates, all classified
`MISSING_PROVIDER_DATA` because the upstream Nansen/LunarCrush
per-symbol payloads are not yet written. The frontend renders this
honestly:

- The state-count chip strip shows `MISSING_PROVIDER_DATA · 3`.
- Each candidate row's `candidate_state` column shows the warn-tone
  `MISSING_PROVIDER_DATA` chip.
- `altdata_symbol_score` for missing-data candidates renders as
  `—` (no fabricated score).
- `proposed_use` for missing-data candidates renders as `—`
  (publisher returns `[]`).
- `live_symbol_candidate` is the `ok`-tone string `"false"` —
  the publisher never proposes live, by design.
- A trailing explainer paragraph reminds operators that
  adoption into paper/training requires the existing Symbol
  Universe governance gate, not this publisher.

A regression test
(`test_public_payload_missing_provider_data_rendered_honestly`)
asserts that a candidate with `altdata_symbol_score=null` MUST be
classified `MISSING_PROVIDER_DATA` and MUST have empty
`proposed_use` plus `live_symbol_candidate=false`.

## Tests

A new static-source regression test file was added:

[v2/backend/tests/integration/cli/test_v2_alt_data_symbol_candidate_publisher_frontend_wiring.py](../../../../v2/backend/tests/integration/cli/test_v2_alt_data_symbol_candidate_publisher_frontend_wiring.py)
— **11 / 11 pass**.

| # | test | what it proves |
|---|------|---------------|
| 1 | `test_payload_hook_and_path_declared_in_payloads_ts` | The hook exists, the public payload path is registered, and the hook does not read v2:paper/v2:risk |
| 2 | `test_candidate_publisher_panel_component_defined` | `CandidatePublisherPanel` is exported and tags itself with the three required `data-testid` markers |
| 3 | `test_all_six_required_adoption_labels_rendered` | All six Codex-required adoption labels appear verbatim in the panel source |
| 4 | `test_safety_pins_referenced_in_panel_source` | Every required safety pin field is referenced in the panel implementation (so it is rendered on the dashboard) |
| 5 | `test_panel_does_not_render_any_action_button` | The panel contains zero `<button>` / `<form>` / `<input>` / `<select>` / `<textarea>` JSX, zero event handlers, zero network calls — the display-only boundary |
| 6 | `test_panel_does_not_embed_raw_api_keys` | No `BINANCE_*` / `NANSEN_*` / `LUNARCRUSH_*` variable references and no credential-shaped 32+ char literal next to "api_key" or "secret" |
| 7 | `test_market_page_imports_panel_and_uses_hook` | /market page imports + calls the hook and renders the panel inside the tagged section |
| 8 | `test_market_page_does_not_render_adopt_button_for_publisher` | The candidate publisher section on /market contains no `<button>` JSX |
| 9 | `test_public_dashboard_payload_pins_safety_envelope` | The on-disk public payload pins every member of the safety envelope |
| 10 | `test_public_dashboard_payload_candidate_safety_pins` | Every candidate in the payload pins live_symbol_candidate=false, may_not_*=true, live_symbols=[], live_gate=blocked_human_only, raw_credential_in_payload="NEVER" |
| 11 | `test_public_payload_missing_provider_data_rendered_honestly` | Candidates with null altdata_symbol_score are MISSING_PROVIDER_DATA with empty proposed_use — no silent promotion |

The prior packet's backend suite still passes unchanged:

`v2/backend/tests/integration/cli/test_v2_alt_data_symbol_candidate_publisher.py` — **18 / 18 pass**, no regression.

## Frontend build status

- `npm run typecheck` (`tsc -b --noEmit`) — **PASS**
- `npm run build` (Vite production build) — **PASS**.
  215 modules transformed, 539 kB JS (140.7 kB gzipped),
  68.55 kB CSS (11.75 kB gzipped), built in 1.31 s.

## Validation sweep

`tools/v2_live_canary_validation_sweep.py` — **PASS**.
22 files scanned. 0 secret hits, 0 approval_true hits,
0 legacy_redis_hits, 0 exchange_mutation_hits, 0 JSON parse
failures, 0 missing files.

## Public payload mirror

The publisher's own truth packet at
[v2/frontend/public/v2_alt_data_symbol_candidate_publisher/latest/operator_dashboard_payload.json](../../../../v2/frontend/public/v2_alt_data_symbol_candidate_publisher/latest/operator_dashboard_payload.json)
remains the source of truth read by the new hook (generated by the
prior packet's CLI run at 2026-05-21T21:29:56Z).

A frontend-wiring-scoped truth payload is also published at
`v2/frontend/public/v2_alt_data_symbol_candidate_publisher_frontend_wiring/latest/operator_dashboard_payload.json`
for the Codex review marker.

## What this packet did NOT do

- Did NOT mutate `live_symbols`, `paper_symbols`, or
  `training_symbols` (nor anything else in Symbol Universe).
- Did NOT change backend candidate-publisher scoring rules, state
  classifier, or Redis allowlists.
- Did NOT add any `<button>`, `<form>`, `<input>`, `<select>`,
  `<textarea>`, `onClick`, `onSubmit`, `onChange`, or network
  call to the candidate publisher panel.
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

## Safety pins (every payload, every tick, every render)

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `live_symbols_expanded=false`
- `paper_symbols_expanded=false`
- `training_symbols_expanded=false`
- `candidate_only_not_adopted=true`
- `dry_run=true` (the panel is read-only display)
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
- `raw_credential_in_payload="NEVER"`
- `provider_network_calls_attempted=false`
- `may_not_override_strict_paper_fill_gate=true`
- `may_not_authorize_live_or_canary=true`
- `may_not_place_orders=true`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`
