# NEW_PAYLOAD_REQUIREMENTS.md

**Handoff date:** 2026-05-11

For every panel concept introduced by Claude Design that is not already backed by a V2 payload, this file records a **payload requirement** rather than fabricating data. Each spec has: payload name, route/page, fields, source, freshness requirement, source type, backend owner, missing-evidence behavior.

---

## 1. `topbar_telemetry`

- **Route / page:** Mission Control top bar (`/admin/mission-control`)
- **Fields:**
  - `orchestrator_latency_ms_p50: number`
  - `orchestrator_latency_ms_p99: number`
  - `risk_gate_latency_ms_p50: number`
  - `risk_gate_latency_ms_p99: number`
  - `redis_ops_per_sec: number`
  - `generated_at: ISO8601`
  - `freshness_state: 'fresh' | 'warn' | 'stale' | 'missing'`
- **Source:** runtime monitor process, derived from `aibotv2:metrics:*` streams (read-only, no writes).
- **Source type:** `RUNTIME_MONITOR_PAYLOAD`
- **Freshness requirement:** 5 s (warn if older than 30 s, stale if older than 2 min)
- **Backend owner:** runtime monitor team (V2 ops-plane)
- **Missing-evidence behavior:** Top bar telemetry chips render `MISSING_EVIDENCE` placeholder text (`"telemetry payload pending"`) with no fabricated numbers. Existing TopBar chips (`MODE`, `LIVE BLOCKED`) continue to render from `/api/v1/risk/live-readiness`.

---

## 2. `subsystems_strip`

- **Route / page:** Mission Control body strip (`/admin/mission-control`)
- **Fields:** array of subsystem rows, each with
  - `id: 'trainer' | 'orchestrator' | 'risk_gateway' | 'execution' | 'redis' | 'postgres'`
  - `status: 'ok' | 'warn' | 'block' | 'paper'`
  - `metric: string` (e.g. `"queue 0"`)
  - `detail: string` (e.g. `"0 stuck"`)
  - `last_event_age_seconds: number`
  - `evidence_link: string` (path to source artifact)
  - `freshness_state: 'fresh' | 'warn' | 'stale' | 'missing'`
- **Source:** aggregated from runtime monitor (`phase3c_runtime_monitor_verification/latest/*.json`) + read-only checks on Redis/Postgres health.
- **Source type:** `RUNTIME_MONITOR_PAYLOAD`
- **Freshness requirement:** 15 s (warn if > 1 min, stale if > 5 min)
- **Backend owner:** runtime monitor + script-registry teams
- **Missing-evidence behavior:** Each row that lacks runtime data renders `cockpit-evidence-gap` with the exact source it expects; the strip never invents `loss 0.0382` / `step 184,201` / `keys 12,481` style numbers from `data.jsx`.

---

## 3. `recent_executions_strip`

- **Route / page:** Mission Control bottom strip (`/admin/mission-control`)
- **Fields:** array of execution rows, each with
  - `decision_id: string`
  - `t: ISO8601`
  - `symbol: string`
  - `side: 'LONG' | 'SHORT'`
  - `verdict: 'ALLOW' | 'BLOCK'`
  - `block_reason?: string`
  - `mode: 'PAPER' | 'REPLAY' | 'BLOCKED'` (live never appears)
  - `lineage_pointer: string`
- **Source:** `historical_30d_replay_and_paper_proof/latest/legacy_vs_v2_decision_comparison.json` (existing) — wire-only, no new artifact.
- **Source type:** `V2_PROOF_ARTIFACT`
- **Freshness requirement:** dataset is non-live by design; show `STATIC_PROOF_FIXTURE` badge.
- **Backend owner:** historical replay team
- **Missing-evidence behavior:** if artifact is absent, render `cockpit-evidence-gap`.

---

## 4. `audit_ledger_chain`

- **Route / page:** `/admin/audit-ledger`
- **Fields:**
  - `chain_length: number`
  - `chain_breaks: number`
  - `last_verified_at: ISO8601`
  - `recent_links: Array<{ link_id, t, kind, summary, prev_hash, this_hash }>`
- **Source:** dedicated audit ledger writer (V2 ops-plane).
- **Source type:** `V2_PROOF_ARTIFACT`
- **Freshness requirement:** 60 s for `last_verified_at`.
- **Backend owner:** audit ledger team
- **Missing-evidence behavior:** page already renders `cockpit-evidence-gap`; banner string `"audit chain · 1,204,481 links · 0 breaks"` from `app.jsx` is **never** lifted.

---

## 5. `strategy_admin_registry`

- **Route / page:** `/admin/strategy-admin`
- **Fields:**
  - `strategies: Array<{ id, name, status, paper_only, live_blocked_reason, params }>`
- **Source:** strategy-registry artifact (pending).
- **Source type:** `V2_PROOF_ARTIFACT`
- **Freshness requirement:** static (config-driven, regenerated on config change)
- **Backend owner:** strategy team
- **Missing-evidence behavior:** evidence-gap until artifact exists. **No dangerous-setting toggle may be shown without `dangerousControls.ts` classification.**

---

## 6. `trainer_admin_overview`

- **Route / page:** `/admin/trainer-admin`
- **Fields:**
  - `current_checkpoint: { id, step, ts }`
  - `recent_checkpoints: Array<{ id, step, ts, promoted }>`
  - `loss_curve: Array<{ step, value }>`
  - `reward_breakdown: Array<{ component, value }>`
  - `freshness: { source_pointer, generated_at, freshness_state }`
- **Source:** trainer lineage artifact (extension of `trainer_lineage_and_readiness/latest/*.json`).
- **Source type:** `V2_PROOF_ARTIFACT`
- **Freshness requirement:** 30 s during training; static otherwise.
- **Backend owner:** trainer team
- **Missing-evidence behavior:** evidence-gap until artifact exists.

---

## 7. `execution_admin_overview`

- **Route / page:** `/admin/execution-admin`
- **Fields:**
  - `adapter: 'paper' | 'replay'` (never `live` while gate blocked)
  - `recent_orders: Array<{ order_id, signal_id, ts, side, qty, status, lifecycle }>`
  - `latency_breakdown: { mean_ms, p99_ms }`
  - `freshness: { source_pointer, generated_at, freshness_state }`
- **Source:** execution adapter telemetry (pending).
- **Source type:** `RUNTIME_MONITOR_PAYLOAD`
- **Freshness requirement:** 5 s
- **Backend owner:** execution team
- **Missing-evidence behavior:** evidence-gap until artifact exists. **No "place order" action; this page is observe-only.**

---

## 8. `build_validation_status`

- **Route / page:** `/admin/build-validation-status`
- **Fields:**
  - `last_typecheck: { ts, status, errors }`
  - `last_build: { ts, status, warnings, size }`
  - `last_smoke: { ts, status, routes }`
  - `last_codex_review: { ts, verdict, link }`
  - `freshness: { source_pointer, generated_at, freshness_state }`
- **Source:** local CI artifact (`claude_worklog/build_validation/latest/*.json` — pending).
- **Source type:** `V2_PROOF_ARTIFACT`
- **Freshness requirement:** updated per CI run.
- **Backend owner:** harness team
- **Missing-evidence behavior:** evidence-gap until artifact exists.

---

## 9. `mobile_iphone_readiness`

- **Route / page:** `/admin/mobile-iphone-readiness`
- **Fields:**
  - `pwa_manifest_present: boolean`
  - `service_worker_registered: boolean`
  - `responsive_breakpoints: Array<{ name, min_width_px, status }>`
  - `mobile_safe_auth: boolean`
  - `mobile_safe_approvals: boolean`
  - `push_notifications_planned: boolean`
  - `future_native_app_track: 'react-native-expo' | 'swiftui' | 'undecided'`
  - `freshness: { source_pointer, generated_at, freshness_state }`
- **Source:** mobile readiness checklist artifact (pending).
- **Source type:** `V2_PROOF_ARTIFACT`
- **Freshness requirement:** updated per release.
- **Backend owner:** mobile/PWA team
- **Missing-evidence behavior:** evidence-gap until artifact exists. PWA manifest + service worker already exist at `public/manifest.webmanifest` and `public/service-worker.js` — readiness checklist can derive partial fields from them.

---

## 10. `symbol_universe`

- **Route / page:** `/admin/symbols`
- **Fields:**
  - `symbols: Array<{ symbol, exchange, market_data_freshness, paper_allowed, live_allowed }>`
  - `freshness: { source_pointer, generated_at, freshness_state }`
- **Source:** curated symbol-universe artifact (pending).
- **Source type:** `V2_PROOF_ARTIFACT`
- **Freshness requirement:** daily.
- **Backend owner:** market-data team
- **Missing-evidence behavior:** evidence-gap until artifact exists.

---

## 11. `claude_admin_session_metadata`

- **Route / page:** `/admin/claude-admin-ai`
- **Fields:**
  - `recent_sessions: Array<{ session_id, ts, tokens_in, tokens_out, status, summary_pointer }>`
  - `current_quota: { plan, remaining, resets_at }`
  - `freshness: { source_pointer, generated_at, freshness_state }`
- **Source:** local Claude session log artifact (pending — must be safe to publish; no raw transcripts).
- **Source type:** `V2_PROOF_ARTIFACT`
- **Freshness requirement:** per session boundary.
- **Backend owner:** Claude admin team
- **Missing-evidence behavior:** evidence-gap until artifact exists.

---

## 12. `monitor_center_aggregate`

- **Route / page:** `/admin/monitor-center`
- **Fields:** aggregated subset of the existing `automation_liveness/*` artifacts plus
  - `trainer_prediction_stream: Array<{ ts, symbol, model_id, ckpt, confidence }>` (subset)
  - `price_prediction_accuracy: { window, accuracy, sample_size, freshness }`
  - `signal_causality: Array<{ signal_id, cause_chain }>`
  - `feature_freshness: Array<{ feature, age_seconds, state }>`
  - `model_health: { ts, status, drift, calibration }`
  - `execution_latency: { mean_ms, p99_ms, n }`
  - `claude_supervision_health: { ts, status, last_check }`
  - `ollama_summarization_health: { ts, status, last_check }`
- **Source:** various existing artifacts (`trainer_lineage_and_readiness`, `decision_explainability_lineage`, `phase3c_runtime_monitor_verification`, `automation_liveness`).
- **Source type:** mostly `V2_PROOF_ARTIFACT` with `RUNTIME_MONITOR_PAYLOAD` overlays.
- **Freshness requirement:** sub-minute for runtime overlays.
- **Backend owner:** runtime monitor + trainer + automation teams
- **Missing-evidence behavior:** every absent field renders a row-level `cockpit-evidence-gap`; the page **must not** synthesize numbers.

---

## Out-of-scope but reserved

- **Theme switcher payload** (`theme: 'dark'|'light'|'terminal'`) — design ships token namespace for all three themes; V2 currently ships dark-only. A future controlled switcher is a separate piece of work and not part of this handoff.
- **`tweaks-panel.jsx`** is design-tool-only and explicitly excluded from V2 ship.
