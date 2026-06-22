# V2 Website Rebuild Phase 1 — Structure + Data Contracts Ready

GO/NO-GO: V2_WEBSITE_REBUILD_PHASE_1_STRUCTURE_AND_DATA_CONTRACTS_READY

Phase 1 wires the website navigation structure and the data contracts
that every Phase-2 page rebuild will consume. It explicitly does not
implement new live, order, shutdown, or adopt-symbol controls. It does
not stop or modify any existing service or governor. It does not
remove the report-center route at /admin/report-center.

## Backend modules

- v2/backend/app/services/website/page_contracts.py — 12 page contracts
  across 3 audiences. Each carries required_payloads, optional_payloads,
  redis_bridge_keys, source_type, freshness_window_seconds,
  placeholder_state, and safety_pins. Helpers derive an effective
  placeholder state from runtime evidence (missing -> MISSING_PAYLOAD,
  stale -> STALE).
- v2/backend/app/services/website/redis_bridge_contracts.py — 26 bridge
  contracts plus the allowlisted safe_bridge_read helper and the
  prediction-key resolver. Frontend never reads Redis directly.
- v2/backend/app/cli/v2_website_contracts_status.py — emits the
  page-contracts status JSON.
- v2/backend/app/cli/v2_website_redis_bridge_status.py — emits the
  redis-bridge + prediction-key resolution JSON.

## Pages

12 pages registered across 3 audiences:

| Audience | Route | Page | Source type | Declared placeholder |
|---|---|---|---|---|
| PUBLIC | / | public-landing | V2_NATIVE_PUBLIC_PAYLOAD | OK |
| PUBLIC | /markets | markets | V2_NATIVE_PUBLIC_PAYLOAD | OK |
| PUBLIC | /status | public-status | V2_NATIVE_PUBLIC_PAYLOAD | OK |
| OBSERVER | /ai-brain | ai-brain | V2_BRIDGE_FROM_LEGACY_REDIS | V2_NATIVE_NOT_READY |
| OBSERVER | /trader | trader | V2_NATIVE_PUBLIC_PAYLOAD | DISPLAY_ONLY |
| OBSERVER | /history | history | V2_BRIDGE_FROM_LEGACY_REDIS | LEGACY_BRIDGE_SOURCE |
| OPERATOR | /admin/mission-control | mission-control | V2_NATIVE_PUBLIC_PAYLOAD | OK |
| OPERATOR | /admin/report-center | report-center | V2_NATIVE_PUBLIC_PAYLOAD | OK |
| OPERATOR | /admin/risk-control | risk-control | V2_NATIVE_PUBLIC_PAYLOAD | OPERATOR_DECISION_REQUIRED |
| OPERATOR | /admin/config | config-admin | V2_NATIVE_PUBLIC_PAYLOAD | DISPLAY_ONLY |
| OPERATOR | /admin/paper-trading | paper-trading | V2_NATIVE_PUBLIC_PAYLOAD | DISPLAY_ONLY |
| OPERATOR | /admin/exchange-manager | exchange-manager | PLACEHOLDER_NOT_READY | DISPLAY_ONLY |

## Bridges

26 bridges declared, 13 V2-native plus 13 legacy. Every legacy bridge
is clearly labelled V2_BRIDGE_FROM_LEGACY_REDIS or
LEGACY_REFERENCE_ONLY. The safe_bridge_read helper enforces a regex
allowlist and refuses any key that matches a secret-token pattern
(api_key, secret, token, bearer, password, .local_secrets paths).

## Prediction-key resolver

Candidate order (no silent failover to legacy):

1. v2:prediction:{symbol}:1m (V2_NATIVE_PUBLIC_PAYLOAD)
2. prediction:{symbol}:multi (V2_BRIDGE_FROM_LEGACY_REDIS)
3. prediction:{symbol}:5m (V2_BRIDGE_FROM_LEGACY_REDIS)
4. prediction:{symbol}:1m (V2_BRIDGE_FROM_LEGACY_REDIS)

resolve_prediction_key returns chosen_prediction_key, source_type,
is_v2_native, confidence, direction, freshness_seconds,
missing_reason, and a candidates_tried audit trail. When no candidate
is present, missing_reason = no_prediction_key_present_in_any_candidate.
First smoke run resolved all three symbols to V2-native keys today.

## Phase-2 render contract

Each Phase-2 page implementation must never embed fake data, never
embed static success fixtures, stamp every card with
source / freshness / status, render placeholders that explain why
data is missing, and render even when payloads are missing.

Operator pages must show the five required visible strings:

- Live trading is blocked.
- Legacy shutdown is blocked.
- Recovery requires proof of edge before scaling.
- No fake readiness.
- Candidate symbols are not adopted automatically.

## Tests

Focused suite at v2/backend/tests/unit/services/website/test_website_contracts.py:

- 12-page registration and route coverage
- report-center route still exists
- safety pins on every page
- safety quartet (live_gate, live_symbols, approves_*) on every page dict
- missing required payload yields MISSING_PAYLOAD
- audience counts (PUBLIC>=3, OBSERVER>=3, OPERATOR>=6)
- no dangerous control tokens in declared text
- bridge ids unique
- safe_bridge_read refuses non-allowlisted and secret-like keys
- legacy bridges clearly labelled non-V2-native
- V2-native bridges clearly labelled V2-native
- resolver prefers V2-native, falls back through multi -> 5m -> 1m
- resolver emits explicit missing_reason when no candidate exists
- resolver candidate order matches contract
- prediction-key resolution status carries the safety pins

Result: 22 of 22 passed. Combined sweep with report-center and
edge-proof suites: 44 of 44 passed.

## What Phase 1 did NOT do

- Did not add any new live, order, shutdown, or adopt-symbol button.
- Did not modify any existing page beyond the report-center page that
  was registered in a prior task.
- Did not modify /home/wali/Desktop/AI BOT.
- Did not stop V2 runtime, continuous remediation, Codex governors,
  the report-center indexer timer, the legacy log observer, the
  V2-vs-legacy comparator, the liquidation WSS daemon, or the
  position-history persistent tracker.
- Did not write old Redis keys.
- Did not call the exchange.
- Did not create any approval marker or shutdown-acceptance file.
- Did not enable live or canary.
- Did not adopt any Symbol Universe candidate.
- Did not adopt any external feed.
- Did not expose any raw API key or .local_secrets content.

## Safety scoreboard

- live_gate = blocked_human_only
- live_symbols = []
- approves_live = false
- approves_canary = false
- approves_legacy_shutdown = false
- approves_redis_trim = false
- frontend_must_not_read_redis_directly = true
- no_live_or_order_or_shutdown_or_adopt_symbol_controls_in_phase_1 = true
- did_not_modify_legacy_bot = true
- did_not_stop_v2_runtime = true
