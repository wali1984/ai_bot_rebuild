# 14 Continuous Monitoring and Evidence Packet Architecture

## 1 Purpose and scope

This document defines the continuous monitoring contract and evidence packet model for V2. It is an architecture-text deliverable. No V2 code is shipped. No legacy bot is mutated. No Redis writes are performed. `LIVE TRADING: BLOCKED` per `CLAUDE.md` is preserved.

The architecture has five monitoring domains:

- trainer liveness (corrected logic — see §2)
- feature flow monitoring
- signal attribution monitoring
- Redis memory monitoring
- readiness/dashboard monitoring

This revision closes the trainer liveness validation evidence gap by:

- mandating local-timezone interpretation of naive trainer log timestamps (with explicit assumption export);
- mandating stream-ID timestamp progression as the primary growth-evidence signal (with `XLEN` demoted to a secondary signal because of capped-stream bias);
- separating liveness into five orthogonal dimensions and a liveness confidence level;
- requiring a validation evidence run BEFORE any V2 scaffold is allowed to proceed against this monitor;
- defining the canonical evidence packet field set;
- defining the dashboard gate metrics required for the Monitor Center, Trainer Prediction Monitor, and Live Readiness pages.

## 2 Trainer liveness (corrected logic)

### 2.1 Liveness dimensions (separated)

A trainer liveness snapshot MUST publish all five dimensions independently. No dimension is allowed to subsume another. A previous monoblock `trainer_internal_liveness_status` field is retained for backward compatibility ONLY; it MUST NOT be used for V2 gate decisions.

- `trainer_process_liveness` — process is alive (`pid` resolvable, `/proc` entry present, command line matches `rl.hybrid_trainer`).
- `heartbeat_liveness` — trainer heartbeat key/stream is fresh within `heartbeat_sla_ms`. Heartbeat thread proves process liveness, NOT prediction-thread liveness.
- `prediction_loop_liveness` — at least one prediction-cycle log line (`_generate_realtime_predictions exit:` or `GPU_BATCH`) within `prediction_loop_sla_ms`, evaluated under §2.2 corrected timezone handling.
- `publish_surface_liveness` — at least one configured publish surface advanced within `publish_surface_sla_ms`, evaluated under §2.3 stream-ID growth.
- `stream_growth_evidence_quality` — `HIGH` / `MEDIUM` / `LOW`, computed as a function of (a) whether stream-ID timestamps advanced, (b) whether `XLEN` is at cap, (c) whether the `signals:trading` global stream is idle while `wma:proposals` and per-account streams are active.

A composite `liveness_confidence_level` ∈ {`high`, `medium`, `low`} is published. Composite is `high` only when all four primary dimensions are `OK` AND `stream_growth_evidence_quality` is `HIGH`.

### 2.2 Corrected timezone handling

Trainer log lines emit naive timestamps in the host's local timezone (observed: `EDT` on the live host on 2026-04-30). Earlier monitor logic forced `tzinfo=UTC` on parsed log timestamps and compared them against `now_ms` in UTC, producing a multi-hour skew that flipped `prediction_worker_alive` to `false` during normal operation (`TRAINER_PREDICTION_WORKER_ROOT_CAUSE_AUDIT.md` §3 #1).

The corrected contract:

- Naive trainer log timestamps MUST be interpreted as the monitor host's local timezone, exposed as `LOCAL_LOG_TZ` (read from `time.tzname` or an explicit env override).
- The interpretation MUST be exported in every snapshot as `log_timestamp_assumption`, formatted `naive_log_ts_interpreted_as_local_tz:<TZ_ABBREV>` (e.g. `naive_log_ts_interpreted_as_local_tz:EDT`).
- `now_ms` MUST be UTC and unambiguous; conversion to the comparison basis MUST happen on the log-side, not the now-side.
- Snapshots MUST carry `last_prediction_entry_ts_ms` (UTC), `last_prediction_entry_age_ms`, and `prediction_loop_sla_ms` so consumers can audit the freshness math.
- A second observability field `monitor_host_now_local`, `monitor_host_now_utc`, and `monitor_host_tz_offset_seconds` MUST be present in every snapshot.

Any future relocation of the trainer process to a non-EDT host invalidates `log_timestamp_assumption` until re-validated; the §3 validation evidence run MUST be repeated before the dashboard gate metrics are trusted.

### 2.3 Stream-ID growth over XLEN for capped streams

The trainer publishes to streams that are bounded by `MAXLEN ~ N` directives. Observed caps include `wma:proposals ≈ 50001` and `signals:trading:primary = 50000`. At cap, `XLEN` deltas are biased toward zero because every append is matched by a trim, producing false `prediction_stream_growth_rate=0.0` / `proposal_stream_growth_rate=0.0` readings (`TRAINER_PREDICTION_WORKER_ROOT_CAUSE_AUDIT.md` §3 #2).

The corrected contract demotes `XLEN` from primary to secondary growth evidence and elevates stream-ID timestamp progression to primary. Every required stream MUST publish:

- `latest_stream_id` — the millisecond-prefixed stream ID returned by `XREVRANGE <stream> + - COUNT 1` (read-only).
- `latest_stream_id_ts_ms` — the integer prefix of `latest_stream_id` (the embedded server-clock timestamp).
- `latest_stream_id_age_ms` — `now_ms - latest_stream_id_ts_ms`.
- `xlen` — current `XLEN`, recorded but NOT used for primary growth decisions.
- `xlen_at_cap` — boolean computed from `XINFO STREAM <stream>` `max-deleted-entry-id` / `length` vs configured cap; if true, `XLEN` deltas MUST be ignored for liveness.
- `capped_stream_warning` — emitted when stream-ID timestamps advance while `XLEN` is flat at cap.

Required streams (V2 monitor MUST observe all five):

- `wma:proposals`
- `signals:trading:primary`
- `signals:trading:asjad`
- `signals:trading`
- `wma:trainer:predictions`

The global `signals:trading` stream and `wma:trainer:predictions` MAY be idle (`xlen=0`, `latest_stream_id=None`) when orchestrator publish mode routes proposals to `wma:proposals` and account fanout streams (`signals:trading:primary`, `signals:trading:asjad`). This idle MUST be reported as `global_stream_idle_non_fatal=true` and MUST NOT cause a liveness `CRITICAL`. The `publish_surface_used` field MUST enumerate which surfaces actually advanced in the snapshot window.

### 2.4 Liveness confidence level and gating semantics

`liveness_confidence_level` is the only field the V2 GO-gate consumes for trainer liveness. The mapping:

- `high` — all four primary dimensions `OK` AND `stream_growth_evidence_quality=HIGH` AND no `capped_stream_warning` AND `log_timestamp_assumption` matches the validated `LOCAL_LOG_TZ` for the current host.
- `medium` — all four primary dimensions `OK`, but `stream_growth_evidence_quality=MEDIUM` (e.g. capped stream observed with stream-ID advance, or `signals:trading=0` while proposal/account surfaces are active).
- `low` — any primary dimension `DEGRADED`, OR `stream_growth_evidence_quality=LOW`, OR `log_timestamp_assumption` mismatch, OR no validation evidence run in the trailing 24h.

V2 readiness is gated at `medium` or higher. `low` blocks scaffold planning per §3.

### 2.5 Stop signatures (true worker failure)

Liveness MUST still alert when an explicit stop signature is observed in the trainer log within the snapshot window, regardless of timezone math:

- `Prediction worker stopped`
- `Worker exiting after`
- `Broken pipe` on the publish path
- absence of any `_generate_realtime_predictions exit:` or `GPU_BATCH` line for a hard-stale window (`prediction_loop_hard_stale_ms`, default 10× `prediction_loop_sla_ms`) measured under corrected timezone handling.

These are the fail-safe path. The §2.2/§2.3 corrections eliminate false positives but do not relax true-failure detection.

## 3 Validation evidence required before scaffold planning

Before any V2 scaffold task is allowed to plan against this monitor, a validation evidence run MUST be on file. This is a hard precondition; the V2 build supervisor MUST refuse a scaffold task whose `validation_evidence_ref` does not resolve.

### 3.1 Validation run shape

A validation run is a contiguous monitor window that satisfies:

- `window_minutes >= 10` with `snapshots_in_window >= 5`.
- All snapshots in the window carry the §4 evidence packet field set complete (no missing fields).
- All five required streams (§2.3) carry `latest_stream_id`, `latest_stream_id_ts_ms`, `latest_stream_id_age_ms`, `xlen`, and `xlen_at_cap`.
- `log_timestamp_assumption` is identical across all snapshots in the window.
- `liveness_confidence_level >= medium` for every snapshot.
- `process_alive && heartbeat_fresh && trainer_internal_liveness_status=CRITICAL` MUST equal zero. (This is the false-CRITICAL resolution check.)

### 3.2 Reference run

The reference validation run for the current monitor revision is recorded at `claude_worklog/continuous_monitoring_impl/TRAINER_LIVENESS_POST_FIX_10MIN_VALIDATION.md`. Window: `2026-04-30T21:39:44Z` → `2026-04-30T21:49:44Z`, `snapshots_in_window=9`, false-CRITICAL count `0`. This run is the canonical evidence that the corrected timezone handling and stream-ID growth contract are effective on the current host.

### 3.3 Re-validation triggers

A new validation run is REQUIRED when any of the following happens:

- the monitor host timezone changes (`LOCAL_LOG_TZ` changes);
- the trainer is moved to a different host;
- any stream cap is changed;
- a new required stream is added to §2.3;
- the V2 scaffold consumes a new field from the evidence packet;
- the trainer is restarted (process identity change).

The validation evidence record carries `validation_run_id` (deterministic SHA-256 of `(window_start_utc, window_end_utc, snapshots_in_window, monitor_revision_hash)`) and is referenced by V2 scaffold tasks via `validation_evidence_ref`.

### 3.4 Block on stale validation

If the most recent validation run is older than `validation_max_age_hours` (default 24) at the time a scaffold task is dispatched, the supervisor MUST refuse the task and demote `liveness_confidence_level` to `low` for the gate.

## 4 Evidence packet model

Six packet types are defined. All packets share the canonical envelope (§5).

### 4.1 Hourly packets

- domain: trainer liveness, feature flow, signal attribution, Redis memory, readiness.
- aggregation: per-domain rollup over the trailing 60 minutes.
- retention: 30 days raw, 365 days rollup.
- producer: read-only monitor.

### 4.2 Daily packets

- domain: same five plus cross-domain correlation.
- aggregation: per-domain rollup over the trailing 24 hours.
- retention: 365 days raw, indefinite rollup.
- producer: read-only monitor + Ollama summarizer (Ollama produces draft summaries, Claude verifies against raw evidence per `CLAUDE.md` Evidence Integrity Rule).

### 4.3 Alert packets

- emitted on threshold crossing or stop-signature match (§2.5).
- carry the snapshot ID that triggered them, the prior-snapshot ID for diff context, and the `liveness_confidence_level` transition.
- ack workflow lives on the Monitor Center page (see §7).

### 4.4 Claude review packets

- bundled at gate boundaries (V2 scaffold start, GO-gate evaluation).
- include the validation evidence run reference (§3) and the dashboard gate metrics snapshot (§7).
- Claude verifies raw evidence per `CLAUDE.md`; summaries are not evidence.

### 4.5 Codex review packets

- bundled at gate boundaries for adversarial coverage review.
- carry the same envelope as Claude review packets plus a coverage map listing every monitor field consumed.

### 4.6 Ollama summarization packets

- low-risk summarization input only (per `CLAUDE.md` Ollama Rule).
- MUST NOT make final safety claims; output is a draft.
- referenced from daily packets, never substituted for raw evidence.

## 5 Evidence packet fields (canonical)

Every packet carries the canonical envelope:

- `packet_id` — SHA-256 of `(packet_type, window_start_utc, window_end_utc, monitor_revision_hash, host_id)`.
- `packet_type` — `hourly|daily|alert|claude_review|codex_review|ollama_summary`.
- `window_start_utc` / `window_end_utc` — ISO-8601 UTC.
- `monitor_revision_hash` — git rev of the read-only monitor at packet creation.
- `host_id` — opaque host identifier (no secrets).
- `monitor_host_tz` — IANA name plus abbreviation observed at run.
- `log_timestamp_assumption` — the §2.2 export verbatim.
- `liveness_confidence_level` — terminal value at `window_end_utc`.
- `liveness_confidence_transitions[]` — every transition in the window with `from`, `to`, `at_utc`, `cause_field`.
- `dimension_status` — object with the five §2.1 dimensions.
- `streams[]` — one entry per required stream (§2.3) with `latest_stream_id`, `latest_stream_id_ts_ms`, `latest_stream_id_age_ms`, `xlen`, `xlen_at_cap`, `capped_stream_warning`.
- `publish_surface_used[]` — surfaces that advanced in the window.
- `global_stream_idle_non_fatal` — boolean.
- `stop_signatures[]` — observed §2.5 signatures with `match_text`, `at_utc`, `log_offset`.
- `validation_evidence_ref` — `validation_run_id` for the run that authorizes consumption.
- `raw_evidence_pointers[]` — one or more of: source-code line range, raw Redis event reference (read-only), raw log line, raw command output, raw config value, raw verification command (per `CLAUDE.md` Evidence Integrity Rule).
- `confidence` — `high|medium|low` per §2.4.
- `missing_evidence[]` — explicit list of fields that could not be filled, never silently null.
- `monitor_snapshot_id` — primary cross-reference key.
- `change_id` — secondary cross-reference key for §6 storage.
- `produced_by` — `read_only_monitor|claude|codex|ollama`.
- `verified_by[]` — list of `(role, at_utc)` pairs; Ollama drafts MUST be `verified_by` Claude before consumption.

A packet whose envelope has any required field missing MUST be rejected by the storage layer (§6) and recorded as `packet_rejected.envelope_incomplete`. Rejection classes:

- `packet_rejected.envelope_incomplete` — any required field above missing.
- `packet_rejected.timezone_mismatch` — `log_timestamp_assumption` differs from monitor host's current `LOCAL_LOG_TZ`.
- `packet_rejected.validation_evidence_stale` — `validation_evidence_ref` resolves to a run older than `validation_max_age_hours`.
- `packet_rejected.stream_field_missing` — any `streams[]` entry missing a required field from §2.3.
- `packet_rejected.confidence_drift` — `liveness_confidence_level` disagrees with `dimension_status` per §2.4 mapping.
- `packet_rejected.unverified_ollama` — Ollama-produced packet without Claude verification.

## 6 Evidence storage

- packet metadata in DB table `evidence_packets` with NOT NULL on every envelope field listed in §5.
- raw payload retention with lifecycle policy per §4 retention rows.
- cross-reference indexes on `monitor_snapshot_id` and `change_id`.
- a `validation_runs` table referenced by `validation_evidence_ref`. Columns: `validation_run_id PK`, `window_start_utc`, `window_end_utc`, `snapshots_in_window`, `monitor_revision_hash`, `host_id`, `local_log_tz`, `false_critical_count`, `liveness_confidence_floor`, `created_at_utc`. Composite UNIQUE on `(monitor_revision_hash, host_id, window_start_utc)`.
- a foreign key constraint links `evidence_packets.validation_evidence_ref` to `validation_runs.validation_run_id`. NULL is permitted only on `ollama_summary` packet types in `draft` status; once `verified_by` includes Claude, the FK MUST be populated.

## 7 Dashboard gate metrics

The dashboard gate metrics drive the Monitor Center, Trainer Prediction Monitor, Live Readiness, and Build/Validation Status pages. Every metric below MUST be a first-class field on the monitor snapshot, derived from the §5 envelope. Display-side aggregation is permitted; introduction of new metrics is not.

### 7.1 Trainer liveness gate metrics

- `liveness_confidence_level` (terminal and last-15-min mode).
- `dimension_status.trainer_process_liveness`.
- `dimension_status.heartbeat_liveness`.
- `dimension_status.prediction_loop_liveness`.
- `dimension_status.publish_surface_liveness`.
- `dimension_status.stream_growth_evidence_quality`.
- `last_prediction_entry_age_ms` (corrected per §2.2).
- `log_timestamp_assumption`.
- `monitor_host_now_local` / `monitor_host_now_utc` / `monitor_host_tz_offset_seconds`.

### 7.2 Stream gate metrics (per required stream)

- `latest_stream_id_age_ms`.
- `xlen` (informational only).
- `xlen_at_cap` (boolean).
- `capped_stream_warning` (boolean, sticky for the window).
- `publish_surface_used` (multi-select chip on the Trainer Prediction Monitor page).

### 7.3 Validation gate metrics

- `validation_evidence_ref` (resolves to `validation_runs.validation_run_id`).
- `validation_run_age_hours` (clock-driven, refreshed by the dashboard).
- `validation_run_window_minutes`.
- `validation_run_snapshots_in_window`.
- `validation_run_false_critical_count` (MUST be `0` for a passing run).
- `validation_run_liveness_confidence_floor`.

### 7.4 Packet gate metrics

- `packet_ingestion_lag_ms` (latest packet end_utc → now_utc).
- `packet_rejection_rate_15m` per §5 rejection class.
- `unverified_ollama_count` (open drafts awaiting Claude verification).
- `alert_packet_open_count` and `alert_packet_unack_count`.

### 7.5 Page mapping

- Monitor Center — full §7.1 + §7.2 + §7.4 surface, alert ack workflow.
- Trainer Prediction Monitor — §7.1 + §7.2, plus stop-signature feed (§2.5).
- Live Readiness — gates on `liveness_confidence_level >= medium`, `validation_run_age_hours <= validation_max_age_hours`, `validation_run_false_critical_count == 0`, `packet_rejection_rate_15m == 0`. All four MUST be true to expose the GO-gate input; default-deny otherwise.
- Build/Validation Status — exposes `validation_evidence_ref` and the §3.3 re-validation trigger list with current state.

## 8 Out-of-scope and non-mutating constraints

- No V2 code is shipped by this document. Field shapes and rejection classes are architecture-text deliverables; a future build task materializes them as Pydantic / JSON-Schema models, DB constraints, and dashboard widgets.
- No legacy bot mutation. Read-only monitor execution under `claude_worklog/tools/read_only_monitor.py` and `claude_worklog/tools/runtime_monitor_dashboard.py` is the only runtime touchpoint; both are confirmed read-only by the §3.2 reference run.
- No Redis writes. `XREVRANGE` and `XINFO STREAM` are read-only. No `XADD`, no `XTRIM`, no `DEL`.
- No service restarts. The monitor MUST NOT restart trainer, trader, orchestrator, Redis, or VPN, even on `liveness_confidence_level=low`. Recovery decisions remain human-gated per `CLAUDE.md` Protected Runtime Policy.
- `LIVE TRADING: BLOCKED` remains the default. Liveness `high` is a necessary but not sufficient input to the live GO-gate.

## 9 Verification pointers

- `claude_worklog/continuous_monitoring_impl/TRAINER_LIVENESS_MONITOR_FALSE_POSITIVE_FIX_REPORT.md` — fixes implemented, including local-tz interpretation, stream-ID growth elevation, dimension separation, and dashboard updates.
- `claude_worklog/continuous_monitoring_impl/TRAINER_LIVENESS_POST_FIX_10MIN_VALIDATION.md` — reference validation run for §3.2 (window `2026-04-30T21:39:44Z` → `2026-04-30T21:49:44Z`, 9 snapshots, false-CRITICAL count `0`).
- `claude_worklog/continuous_monitoring_impl/TRAINER_PREDICTION_WORKER_ROOT_CAUSE_AUDIT.md` — root cause analysis grounding §2.2 and §2.3 corrections.
- `claude_worklog/tools/read_only_monitor.py` — implementation of the snapshot fields referenced in §5 and §7.
- `claude_worklog/tools/runtime_monitor_dashboard.py` — implementation of the dashboard gate metrics referenced in §7.5.
- `CLAUDE.md` — Evidence Integrity Rule, Ollama Rule, Protected Runtime Policy, Monitor Center Requirements, Signal Explainability Rule.
