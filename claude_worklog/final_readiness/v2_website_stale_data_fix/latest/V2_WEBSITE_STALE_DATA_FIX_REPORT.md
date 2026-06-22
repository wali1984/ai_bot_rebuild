# V2 Website Stale Data — Root Cause + Fix Report

GO/NO-GO: V2_WEBSITE_STALE_DATA_FIXED

## Symptom

Operator reported the landing page cards showed:

- Data Ingestors ? feeds . 8m ago
- AI Trainer bridge active . 8m ago
- Predictions CURRENT . 7m ago

The publishers on disk were updating every 15-30 seconds, but the
browser was seeing 7-8 minute old data.

## Diagnosis (read-only)

The FastAPI SPA catch-all in v2/backend/app/main.py was serving every
JSON payload from v2/frontend/dist/, which is the Vite build snapshot.
Vite's build copies v2/frontend/public/ into v2/frontend/dist/ once.
After the build finishes, the operator runtime publishers continue to
write fresh JSON into public/, but dist/ stays frozen at build time.

Evidence collected:

- dist/operator_runtime/v2_native_ingestors/latest/v2_native_ingestors_status.json
  mtime 00:13:14 (build time).
- public/operator_runtime/v2_native_ingestors/latest/v2_native_ingestors_status.json
  mtime 00:22:40 (fresh, refreshing every ~30 seconds).
- Backend HTTP GET on the same path returned the dist (frozen) copy
  with internal generated_at age of 626 seconds.

Result: every payload the SPA consumed was as old as the last vite
build.

## Fix applied

Edited the catch-all in v2/backend/app/main.py to prefer the live
public/ directory before falling back to the dist/ snapshot. For
every URL that does not start with api/ or public/:

1. try public/full_path first; if it is a file, serve it with
   Cache-Control: no-store, max-age=0.
2. otherwise try dist/full_path (for genuine build artifacts like
   index.html, favicon.ico, robots.txt).
3. otherwise hand over the SPA index for client-side routing.

The no-store header guarantees no intermediate proxy or browser cache
freezes a payload between polls. Both directories remain read-only;
no Redis write, no exchange call, no live action.

After restarting the backend:

- operator_runtime/v2_native_ingestors/latest/v2_native_ingestors_status.json -> 30s old (was 626s)
- operator_runtime/v2_trainer_bridge/latest/v2_trainer_bridge_status.json -> 46s old (was 634s)
- operator_runtime/paper_online/latest/trainer_prediction_current_record.json -> 5s old (was 592s)
- operator_runtime/paper_online/latest/risk_runtime_payload.json -> 2s old
- operator_runtime/paper_online/latest/current_signal_lineage.json -> 2s old

Cache-Control header on a payload request:

  HTTP/1.1 200 OK
  cache-control: no-store, max-age=0
  content-type: application/json

## What about the other stale payloads on disk

The disk scan also found ~50 payloads under public/operator_runtime/
that are hours-to-days old. These belong to workers that are not
currently running:

- legacy_live_bridge, live_observer (legacy bridge writers; not active)
- v2_orchestrator_adapter, v2_signal_publisher, v2_replay_worker,
  v2_script_monitor, v2_config_admin_manager,
  v2_default_blocked_execution_adapter, v2_binance_usdm_adapter,
  v2_paper_execution_worker, v2_feature_pipeline_and_ta_worker,
  v2_market_ingestor, coinank_market_intelligence,
  v2_account_position_monitor, v2_feature_intelligence,
  v2_signal_lineage_worker, v2_risk_gateway_runtime_worker,
  v2_execution_ledger_worker, v2_owned_ingestors,
  v2_owned_feature_pipeline, v2_owned_trainer (etc.)

These are not consumed by the landing page cards the operator
referenced. Each one is a separate worker the operator can start
later. The backend fix ensures that whenever a worker IS running, its
fresh payload is what the SPA sees.

Pages that already render explicit MISSING_PAYLOAD / STALE badges
(report center, executive command center, website rebuild phase 1)
will surface those states honestly via the v2_report_center indexer.

## Validation

- py_compile of v2/backend/app/main.py: PASS.
- pytest v2/backend/tests/unit/services/website/
  + v2/backend/tests/unit/services/report_center/ -> 40 of 40 passed.
- Backend restarted via systemctl --user restart
  ai-bot-v2-public-website-backend.service; is-active = active.
- HTTP probes of the three landing-page payloads returned 2-46s ages.
- Cache-Control: no-store, max-age=0 set on every live payload.

## What this cycle did NOT do

- Did not modify /home/wali/Desktop/AI BOT.
- Did not stop legacy.
- Did not stop V2 runtime, continuous remediation, Codex governors,
  the report-center indexer timer, the legacy log observer, the
  V2-vs-legacy comparator, the liquidation WSS daemon, or the
  position-history persistent tracker.
- Did not change any port from the prior change to 5173.
- Did not write any old Redis key.
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

## Operator next step

Hard refresh the browser (Ctrl+Shift+R) on http://127.0.0.1:5173/.
The Data Ingestors, AI Trainer, and Predictions cards should now show
seconds-ago ages and update every 15-30 seconds via the existing
usePayloadFile polling. No further action needed.
