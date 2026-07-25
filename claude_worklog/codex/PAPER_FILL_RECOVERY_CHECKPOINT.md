# PAPER FILL RECOVERY CHECKPOINT — Phase 0 frozen identities

Emergency Paper Recovery Pass 2. Goal: `PAPER_RECOVERY_CANARY_LIFECYCLE_COMPLETE`.
Live remains mechanically blocked.

## Runtime identities (captured 2026-07-25T00:5xZ)

- Branch: `codex/pipeline-trust-refresh`  HEAD: `565bdcec3d`  dirty: 0
- Orchestrator + risk gateway: run from **repo** (carry the Pass-1 recovery waivers).
- **Paper loop: runs from IMMUTABLE RELEASE `6f5dd649b1a962c2f16b08b3beb7caa3bb375ba0`** (NOT repo).
  PID 759182, active. Single canonical writer (`v2_trade_management_paper_loop`, canonical_paper_writer_count=1).
- Paper session: `PAPER_SIM_ACCOUNT`, initial_capital 3000.0, paper_only, live_gate blocked.
- Account: equity 2985.59, wallet 2985.59, used_margin 0.0, free_margin 2985.59 (ample).
- entry_freeze: **absent**.  kill switch: not active.  live_gate:state: blocked_human_only.
- Prior recovery prediction/intent expired (TTL 240s); a fresh canary is required to trace.

## Implication

The fill block is NOT margin, NOT entry-freeze, NOT duplicate-writer. Candidates:
minimum-notional vs the $5 canary ceiling, recovery-intent eligibility/schema, or
risk-ALLOW identity propagation into the paper loop. Phase 1 will expose the exact
first failed predicate before any classification.

## Fix-deployment note

Because the paper loop runs from an immutable release, a paper-loop code fix will
NOT take effect on the running process without either (a) a redeploy of the new
SHA, or (b) a drop-in ExecStart repin to the repo. Category-A fixes (canary input
/ sizing) need NO paper-loop edit and are preferred.

## Phase 1 result — EXACT first-rejection predicates (recovery canary, BTCUSDT)

Recovery intent reached `v2:paper:intents` with `risk_controller_decision=PASS`
(risk ALLOW *is* recognized) but `paper_fill_gate_status=RISK_PENDING`.
Full block set (all evaluated; predicates + values):

| Block reason | Predicate / value | Category |
|---|---|---|
| PAPER_PERFORMANCE_CIRCUIT_BREAKER_BLOCKED | `v2:paper:performance_circuit_breaker_status.state=HALTED_PERFORMANCE` (enabled, paper_only). **Global halt — no paper open since 2026-07-17.** Triggering condition (poor perf: PF 0.658, edge −18bps) is CURRENT, not stale. | **A (legitimate, current)** |
| PAPER_BUCKET_QUARANTINE_BLOCKED_REENTRY | per-bucket reentry quarantine active | A (perf-protective) |
| PAPER_HIGH_CONFIDENCE_LOSS_CLUSTER_BLOCKED_REENTRY | high-confidence loss cluster active | A (perf-protective) |
| STALE_FEATURE_STATE / MARKET_STATE_INTEGRITY_SCORE_BELOW_PAPER_MIN | BTCUSDT latest snapshot = 2026-07-23 (1.4d old); coverage not yet crossed post-recovery | **A (legitimate stale-data guard)** |
| MISSING_ENTRY_FEATURE_AVAILABLE_AT / _GENERATED_AT / _CUTOFF, ENTRY_FEATURE_CANDLE_NOT_CONFIRMED_CLOSED | paper-loop entry gate (line ~39338) reads `entry_feature_*` prefixed fields; recovery signal does not populate them and prediction-side fields do NOT propagate through orchestrator→signal→intent | **B (field-derivation gap for recovery signals)** |
| MISSING_EXPLICIT_FUNDING_BPS_AT_DECISION_TIME, source_event_time_missing, candle_open_or_close_time_missing | entry-quality microstructure the paper loop computes at allocation; not derived for the recovery signal | B (derivation gap) |
| VALID_FOR_PAPER_NOT_TRUE | prediction sets valid_for_paper=True but paper loop re-derives it False | B (interpretation) |

## Classification + honest stop point

The **binding** blocker is the **performance circuit breaker (HALTED_PERFORMANCE)**,
a *global* paper-entry halt whose triggering condition (genuinely poor current
performance) is still TRUE — a legitimate Category-A protection of the simulated
account, NOT a stale freeze. Bucket-quarantine + loss-cluster are the same class.
STALE_FEATURE_STATE on BTCUSDT is also legitimate (07-23 snapshot).

The Category-B gaps (entry-feature derivation, valid_for_paper interpretation)
live in the paper loop, which runs from **immutable release 6f5dd649b1** — a fix
needs deploy/repin.

**Completing the canary fill requires a paper-loop recovery exception to the
performance circuit breaker + quarantine + loss-cluster + a recovery entry-feature
derivation path.** That is a substantial, careful change to a 50k-line,
release-pinned, co-agent-owned file, and it is a genuine judgment call: relaxing a
*current* performance halt (even paper-only, live-blocked) is in tension with the
spec's "must not bypass legitimate controls". Not bypassed here. Live stayed
blocked; places_real_order=false; exchange_action_taken=false throughout.
