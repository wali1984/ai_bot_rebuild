# 12D Trainer Liveness Validation Evidence Closure

## Gap statement

Prior to this update, `claude_worklog/v2_architecture/14_CONTINUOUS_MONITORING_AND_EVIDENCE_PACKET_ARCHITECTURE.md` was a 27-line skeleton. It listed packet types, monitoring domains, and a one-line note "trainer liveness (corrected logic)" without defining what "corrected" meant or how V2 was supposed to gate on the correction. Specifically it did not define:

- the corrected timezone handling contract (naive trainer log timestamps interpreted as monitor-host local timezone, with `log_timestamp_assumption` exported on every snapshot);
- the corrected stream-growth contract (stream-ID timestamp progression as primary signal, `XLEN` demoted to secondary because of capped-stream bias on `wma:proposals` and `signals:trading:primary`);
- the five separated liveness dimensions (`trainer_process_liveness`, `heartbeat_liveness`, `prediction_loop_liveness`, `publish_surface_liveness`, `stream_growth_evidence_quality`) and the composite `liveness_confidence_level`;
- the validation-evidence precondition that MUST be satisfied before any V2 scaffold task is allowed to plan against the monitor;
- the canonical evidence packet field set (`packet_id`, `monitor_revision_hash`, `validation_evidence_ref`, `streams[]`, `dimension_status`, `liveness_confidence_transitions[]`, `raw_evidence_pointers[]`, etc.);
- the dashboard gate metrics list that drives Monitor Center, Trainer Prediction Monitor, Live Readiness, and Build/Validation Status;
- the rejection classes for malformed packets (envelope incomplete, timezone mismatch, validation evidence stale, stream field missing, confidence drift, unverified Ollama).

The post-fix evidence in `TRAINER_LIVENESS_MONITOR_FALSE_POSITIVE_FIX_REPORT.md`, `TRAINER_LIVENESS_POST_FIX_10MIN_VALIDATION.md`, and `TRAINER_PREDICTION_WORKER_ROOT_CAUSE_AUDIT.md` had identified the false-positive root causes (timezone misinterpretation, capped-stream `XLEN` bias) and produced a 10-minute validation window with `false-CRITICAL=0`, but the architecture document had not translated those findings into a normative monitor contract that V2 could gate on.

## What was added

1. **Five-dimension liveness contract (§2.1).** `trainer_process_liveness`, `heartbeat_liveness`, `prediction_loop_liveness`, `publish_surface_liveness`, `stream_growth_evidence_quality` are independent and MUST all publish. Composite `liveness_confidence_level` ∈ {`high`, `medium`, `low`} is the only field the V2 GO-gate consumes; the legacy monoblock `trainer_internal_liveness_status` is retained for backward compatibility ONLY.
2. **Corrected timezone handling (§2.2).** Naive trainer log timestamps MUST be interpreted as monitor-host local timezone (`LOCAL_LOG_TZ`). Every snapshot MUST export `log_timestamp_assumption` (e.g. `naive_log_ts_interpreted_as_local_tz:EDT`), `monitor_host_now_local`, `monitor_host_now_utc`, and `monitor_host_tz_offset_seconds`. Conversion happens on the log-side, not the now-side. Consumers can audit the freshness math via `last_prediction_entry_ts_ms`, `last_prediction_entry_age_ms`, and `prediction_loop_sla_ms`. Host relocation invalidates the assumption until §3 re-validation.
3. **Stream-ID growth over XLEN for capped streams (§2.3).** `XLEN` is demoted to secondary; primary growth evidence is stream-ID timestamp progression. Every required stream MUST publish `latest_stream_id`, `latest_stream_id_ts_ms`, `latest_stream_id_age_ms`, `xlen`, `xlen_at_cap`, and `capped_stream_warning`. Five required streams: `wma:proposals`, `signals:trading:primary`, `signals:trading:asjad`, `signals:trading`, `wma:trainer:predictions`. `signals:trading=0` and `wma:trainer:predictions=0` are non-fatal when `wma:proposals` and per-account streams are advancing (`global_stream_idle_non_fatal=true`); `publish_surface_used[]` MUST enumerate the surfaces that actually advanced.
4. **Liveness confidence level mapping (§2.4).** `high` requires all four primary dimensions `OK` AND `stream_growth_evidence_quality=HIGH` AND no `capped_stream_warning` AND `log_timestamp_assumption` matches validated `LOCAL_LOG_TZ`. `medium` permits capped-stream advance under `MEDIUM` evidence quality. `low` blocks scaffold planning. V2 readiness is gated at `medium` or higher.
5. **Stop-signature fail-safe (§2.5).** Liveness still alerts on `Prediction worker stopped`, `Worker exiting after`, `Broken pipe` on the publish path, or hard-stale prediction-cycle absence under corrected timezone math. Corrections eliminate false positives but do not relax true-failure detection.
6. **Validation evidence required before scaffold planning (§3).** A scaffold task whose `validation_evidence_ref` does not resolve MUST be refused by the V2 build supervisor. A run is valid iff `window_minutes >= 10`, `snapshots_in_window >= 5`, all envelope fields complete, all five required streams populated, `log_timestamp_assumption` constant across the window, `liveness_confidence_level >= medium` for every snapshot, and the `process_alive && heartbeat_fresh && status=CRITICAL` count is `0`. Reference run on file: `2026-04-30T21:39:44Z` → `2026-04-30T21:49:44Z`, 9 snapshots, false-CRITICAL count `0`.
7. **Re-validation triggers (§3.3).** Host timezone change, trainer host move, stream cap change, new required stream, scaffold consumption of a new field, trainer process identity change. Default `validation_max_age_hours=24`; older runs demote `liveness_confidence_level` to `low` for the gate.
8. **Six-packet model (§4).** `hourly`, `daily`, `alert`, `claude_review`, `codex_review`, `ollama_summary`. Retention policy per packet type. Ollama summarization is draft-only per `CLAUDE.md` Ollama Rule; verification by Claude against raw evidence is mandatory before consumption.
9. **Canonical evidence packet field set (§5).** Twenty-plus envelope fields including `packet_id`, `packet_type`, `window_start_utc`/`window_end_utc`, `monitor_revision_hash`, `host_id`, `monitor_host_tz`, `log_timestamp_assumption`, `liveness_confidence_level`, `liveness_confidence_transitions[]`, `dimension_status`, `streams[]`, `publish_surface_used[]`, `global_stream_idle_non_fatal`, `stop_signatures[]`, `validation_evidence_ref`, `raw_evidence_pointers[]`, `confidence`, `missing_evidence[]`, `monitor_snapshot_id`, `change_id`, `produced_by`, `verified_by[]`. Six rejection classes: `envelope_incomplete`, `timezone_mismatch`, `validation_evidence_stale`, `stream_field_missing`, `confidence_drift`, `unverified_ollama`.
10. **Storage contract (§6).** `evidence_packets` table with NOT NULL on every envelope field; `validation_runs` table with composite UNIQUE on `(monitor_revision_hash, host_id, window_start_utc)`; foreign key from `evidence_packets.validation_evidence_ref` to `validation_runs.validation_run_id` (NULL only on `ollama_summary` drafts).
11. **Dashboard gate metrics (§7).** Four metric groups (trainer liveness, stream, validation, packet) feeding Monitor Center, Trainer Prediction Monitor, Live Readiness, and Build/Validation Status. Live Readiness exposes the GO-gate input only when `liveness_confidence_level >= medium` AND `validation_run_age_hours <= validation_max_age_hours` AND `validation_run_false_critical_count == 0` AND `packet_rejection_rate_15m == 0`; default-deny otherwise.
12. **Out-of-scope carve-outs (§8).** No V2 code shipped; no legacy bot mutation; no Redis writes (`XREVRANGE` and `XINFO STREAM` are read-only); no service restarts even on `liveness_confidence_level=low`; `LIVE TRADING: BLOCKED` remains the default and liveness `high` is necessary but not sufficient for the live GO-gate.

## Why this closes the gap

- **The false-CRITICAL pattern is rejectable, not advisory.** The §2.2 timezone contract and §2.3 stream-ID growth contract together eliminate both observed false-positive paths (4-hour skew, capped-stream `XLEN=flat`). The §3 validation evidence run is the on-file proof that the corrections work on the current host; the architecture demands one before scaffold can plan.
- **Dimension separation prevents lumped failure.** Earlier monitor logic could flip `trainer_internal_liveness_status` to `CRITICAL` on any one of timezone skew, capped streams, or per-account routing. The five §2.1 dimensions are now orthogonal, and the composite `liveness_confidence_level` is computed from a documented mapping (§2.4), not from a single flag.
- **Capped-stream behavior is a first-class signal.** `xlen_at_cap` and `capped_stream_warning` are required fields, and `publish_surface_used[]` enumerates what actually advanced. A monitor that observes `signals:trading=0` while `wma:proposals` is at cap and advancing reports `global_stream_idle_non_fatal=true` instead of triggering a false stop.
- **V2 cannot scaffold against an unverified monitor.** The §3 precondition is hard: `validation_evidence_ref` MUST resolve to a passing run, and a stale run demotes `liveness_confidence_level` to `low`. The supervisor refuses scaffold tasks whose evidence is missing or stale, satisfying the `CLAUDE.md` Completeness Override.
- **Evidence integrity is preserved.** Every packet carries `raw_evidence_pointers[]` per `CLAUDE.md` Evidence Integrity Rule. Ollama-produced packets MUST be `verified_by` Claude before they can be consumed; the `unverified_ollama` rejection class enforces this at the storage boundary.
- **Default-deny live trading is preserved.** `liveness_confidence_level=high` is a necessary input to the live GO-gate, not a sufficient one. The Live Readiness page surfaces the gate inputs but never auto-promotes to live execution.
- **The architecture text is fully testable.** Every rule maps to a published field, a rejection class, or a packet retention policy. A future V2 build task that fails any of §2.1, §2.2, §2.3, §3, §5, or §7 cannot claim the gap is closed.

## Verification pointers

- File updated: `claude_worklog/v2_architecture/14_CONTINUOUS_MONITORING_AND_EVIDENCE_PACKET_ARCHITECTURE.md` — see §2 (trainer liveness contract: dimensions, timezone, stream-ID growth, confidence level, stop signatures), §3 (validation evidence precondition, reference run, re-validation triggers, stale-block), §4 (six-packet model), §5 (canonical envelope fields, six rejection classes), §6 (storage tables and FK), §7 (dashboard gate metrics and page mapping), §8 (non-mutating constraints), §9 (verification pointers).
- File created: `claude_worklog/v2_architecture_remediation/12D_TRAINER_LIVENESS_EVIDENCE_CLOSURE.md` (this file).
- Inputs incorporated:
  - `claude_worklog/continuous_monitoring_impl/TRAINER_LIVENESS_MONITOR_FALSE_POSITIVE_FIX_REPORT.md` — fixes implemented (local-tz interpretation; stream-ID growth elevation; dimension separation; dashboard updates; py_compile, `--validate-continuous-dry`, and one-shot dashboard validations passing).
  - `claude_worklog/continuous_monitoring_impl/TRAINER_LIVENESS_POST_FIX_10MIN_VALIDATION.md` — reference validation run (window `2026-04-30T21:39:44Z` → `2026-04-30T21:49:44Z`, 9 snapshots, `OK=9`, `DEGRADED=0`, `CRITICAL=0`, `process_alive && heartbeat_fresh && status=CRITICAL` count `0`, `log_timestamp_assumption=naive_log_ts_interpreted_as_local_tz:EDT`).
  - `claude_worklog/continuous_monitoring_impl/TRAINER_PREDICTION_WORKER_ROOT_CAUSE_AUDIT.md` — root causes #1 (timezone misinterpretation) and #2 (`XLEN` delta at cap) grounding §2.2 and §2.3.
  - `claude_worklog/agent_supervisor/ollama_context/012d_trainer_liveness_context.md` — Ollama draft context (treated as navigation aid only; final claims grounded in raw evidence per `CLAUDE.md` Ollama Rule).
- Paired structural enforcement (already closed, retained for cross-domain coherence):
  - `claude_worklog/v2_architecture_remediation/12A_DATABASE_LINEAGE_CLOSURE.md` — DB lineage chain that `evidence_packets` and `validation_runs` extend.
  - `claude_worklog/v2_architecture_remediation/12B_API_LINEAGE_ENFORCEMENT_CLOSURE.md` — API lineage block consumed by Claude/Codex review packets.
  - `claude_worklog/v2_architecture_remediation/12C_FEATURE_EXPLAINABILITY_CLOSURE.md` — explainability completeness predicate that the feature-flow monitoring domain (§1) consumes.
- Task spec: `claude_worklog/agent_supervisor/tasks/012d_trainer_liveness_validation_evidence.json`.
- Required outputs declared by the task spec are both produced via `BEGIN_FILE:` blocks under the allowed prefixes (`claude_worklog/v2_architecture/`, `claude_worklog/v2_architecture_remediation/`); the supervisor's `materialize_emit_files()` (`claude_worklog/tools/agent_supervisor.py:184`) materializes them.

## Out of scope

- No V2 code is shipped. Pydantic / JSON-Schema models, DB constraints, dashboard widgets, and packet-rejection exception types are deferred to a later build task.
- No legacy bot mutation. `/home/wali/Desktop/AI BOT` is read-only. The read-only monitor and dashboard tools were the only runtime touchpoints during the §3.2 reference run.
- No Redis writes. `XREVRANGE` and `XINFO STREAM` are read-only. No `XADD`, `XTRIM`, or `DEL`.
- No service restarts. The monitor MUST NOT restart trainer, trader, orchestrator, Redis, or VPN, even on `liveness_confidence_level=low`. Recovery decisions remain human-gated per `CLAUDE.md` Protected Runtime Policy.
- `LIVE TRADING: BLOCKED` remains the default per `CLAUDE.md`. Liveness `high` is necessary but not sufficient for the live GO-gate.

## Status

Trainer liveness validation evidence architecture gap: CLOSED at the architecture-text level. A future V2 build task must materialize:

- the `TrainerLivenessSnapshot` and `EvidencePacket` schemas (Pydantic / JSON-Schema) per §5;
- the `evidence_packets` and `validation_runs` DB tables with the §6 NOT NULL columns, composite UNIQUE, and FK;
- the six packet rejection classes per §5 as exception types mapping to documented HTTP statuses on the packet ingestion endpoint;
- the §3 validation-evidence precondition as a supervisor pre-dispatch check;
- the §7 dashboard gate metrics on Monitor Center, Trainer Prediction Monitor, Live Readiness, and Build/Validation Status;
- the §2.5 stop-signature feed on the Trainer Prediction Monitor page.

Any deviation from §2.2, §2.3, §3, §5, or §7 reopens this gap.
