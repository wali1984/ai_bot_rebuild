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

## Pass 3 — implemented + precise remaining plan (reviewer map verified)

IMPLEMENTED + committed (deploy-ready, guarded, tested logic; NOT yet deployed):
- `PaperRecoveryCanaryArmV1` (single-use, ID-bound, <=900s, atomic consume, fail-closed) + 11 tests.
- Driver creates the arm for engineering_canary + carries paper_eligible + tagged neutral funding.
- Paper loop economic exception (2 edits): run_once validates the arm at PL:44827 call site and
  stamps `intent["paper_recovery_canary_arm_valid"]`; `_paper_block_new_entry_by_performance_circuit`
  (PL:27560) removes ONLY the three economic reasons for the armed canary. Ordinary intents untouched;
  global breaker state unchanged; every hard control preserved.

REMAINING to reach PAPER_RECOVERY_CANARY_LIFECYCLE_COMPLETE (exact sites from reviewer map):
1. Risk recognition (Phase 5): PL:45144 `canonical_risk_allowed` — for the armed canary, accept the
   persisted `v2:decision:risk:rd_dec_<pid>` record when its `risk_action=="allow"` even if the strict
   identity dereference (PL:26347 else-branch) left `risk_decision_record_resolved=False`. Add exact
   mismatch reason codes. Root cause: `_lineage_ids` PL:40535 synthesizes `paper_risk_<pid>` when the
   signal lacks the id; the real record is `rd_dec_<pid>`.
2. Entry-feature propagation (Phase 4): the SIGNAL (orchestrator `v2:signals:paper` row builder,
   v2_orchestrator_arbitration_loop.py ~:1348-1417) must copy entry_feature_available_at/generated_at/
   cutoff/candle_closed_confirmed + source_event_time + candle_open/close_time + expected_funding_bps
   from the prediction; paper loop already copies signal->intent at PL:44087 and re-derives from the
   feature snapshot at PL:44232 (only when entry_features truthy). For engineering_replay honor the
   sealed-snapshot finality (PL:39348) only with real candle-finality evidence.
3. Staleness exception (Phase 3): armed engineering_replay canary — apply `feature_staleness_exception_
   applied` for STALE_FEATURE_STATE + MARKET_STATE_INTEGRITY_SCORE_BELOW_PAPER_MIN, or use a fresh
   symbol (BTCUSDT snapshot is 07-23). Sealed replay must carry exact snapshot/vector/abi hashes + no
   future leakage vs its historical decision time.
4. valid_for_paper (Phase 6): PL:42586 — recompute True for the armed canary from arm+risk-allow+
   identities, not inherited-False from strict promotion/economic failure.
5. Sizing (Phase 7): min-notional at PL:38618/38622; use smallest qty satisfying LOT_SIZE.minQty +
   MIN_NOTIONAL (BTCUSDT mark ~64006 -> $5 is below min; use up to $10 or a lower-min symbol).
6. DEPLOY: new immutable worktree at deployments/ai_bot_rebuild/<newSHA>, update paper-loop
   90-immutable-release.conf drop-in, preserve all live-block/no-exchange flags, restart ONLY the paper
   loop, verify NRestarts=0 + single writer. Then run the canary driver (creates arm) -> fill/open/
   reduce-only close/reconcile; restart-reconstruct; 2 subsequent cycles.

NOT bypassed: any hard control. Live blocked; places_real_order=false; exchange_action_taken=false.
Global paper_performance_circuit_breaker stays HALTED_PERFORMANCE for ordinary intents.

## Pass 3 — DEPLOYED + PROVEN chain; exact terminal blocker (2026-07-25T05:3xZ)

Final SHA `d30c6e07b1` deployed as immutable release
`deployments/ai_bot_rebuild/d30c6e07b168...` (git worktree + shared venv symlink +
untracked co-agent runtime deps copied verbatim; drop-in repinned SHA-only; ONLY
the paper loop restarted; ActiveState=active, ExecMainStatus=0, NRestarts=0,
single writer holds the flock; lock now in the writable runtime dir).

### Regression fixed to make ANY immutable-release deploy of this branch start
`PAPER_LOOP_LOCK_PATH` had been hardcoded to `Path(__file__).parents[4]/logs`,
which is inside the read-only release mount → `OSError Errno 30` at startup.
Restored the env-configurable resolver (commit 3d8c9ed7e8). Also: 24 co-agent
files (cycle_reservation.py, exact_on_policy_entry_outbox.py, adaptive_symbol_
selection*, coinank_scheduler.py, tests) are present-on-disk but UNTRACKED on this
branch though imported at runtime; a fresh `git worktree` checkout omits them.
Copied verbatim into the release (matches the running stable release). **Branch
hygiene: these need committing for reproducible deploys.**

### PROVEN end-to-end (engineering_canary recovery_pred_200a2e...):
recovery prediction -> orchestrator ALLOW (`dec_...`, proceed_long) -> **persisted
risk ALLOW** (`rd_dec_...`, allow_proceed_long) -> per-tf paper signal -> paper
intent. On the intent, EVERY Pass-3 control fired correctly:
`paper_recovery_canary_arm_valid=True`, `economic_control_exception_applied=True`
(the 3 economic strings stripped at the SOLE producer), `risk_decision_record_
resolved=True`/`risk_controller_decision=allow`/`paper_fill_risk_state=ALLOW`,
`feature_staleness_exception_applied=True`, `valid_for_paper=True`,
`certification_bypass=True`, `paper_recovery_canary_local_gate_override=True`
(bypassed A_PLUS/ENTRY_GATE/INTEGRITY_VALID_FOR_PAPER/STRATEGY_TRADE_ALLOWED).
Marker propagation solved self-contained: paper loop recovers engineering_canary
markers via the arm + a single targeted GET of the canonical prediction (the loop
indexes predictions FROM signals, so upstream markers are otherwise lost).

### TERMINAL blocker = allocation sized to ZERO (NOT a fill, honestly):
`target_notional_usdt=0.0`. Root cause = the ordinary paper ALLOCATION runs at
PL:44847, BEFORE the arm is validated at PL:44934, and a CASCADE of allocation
vetos sets `risk_veto=True` (zero size) on incomplete OHLCV-replay evidence:
- PL:44838 `PAPER_ALLOCATION_POINT_IN_TIME_CONTRACT_BLOCKED` — allocation_pit
  status != PASS (ALLOCATION_INPUT_TIME_MISSING entry_feature/microstructure/
  portfolio_state clocks; ORDER_INVALID entry_atr_available_at>generated_at ~531ms;
  MICROSTRUCTURE_SOURCE_HASH_INVALID). Temporal/certification gate.
- PL:44787 `PAPER_CANDIDATE_DYNAMIC_ENVELOPE_RESERVATION_BLOCKED` +
  `paper_cycle_reservation_build_rejection_reasons` = RESERVATION_LIMIT_CHANGED on
  max_single_symbol_exposure_pct / max_total_portfolio_risk_pct / min_available_
  margin_buffer_pct — these are tied to **EXPOSURE hard controls**.
- allocator `BLOCK_LIQUIDATION_RISK`=no_safe_leverage_margin_configuration +
  `MICROSTRUCTURE_TRUST_SCORE_MISSING` (trust=0.0; OHLCV-only recovery lane has NO
  microstructure evidence).

### Why not force it — the two shortcuts are both barred by the operator's rails
1. Provide microstructure trust score / valid source hash -> FABRICATING evidence
   that never existed for the OHLCV recovery lane. Barred ("no fabricated feature
   freshness / genuine attestation").
2. Blanket-clear `risk_veto` before PL:44847 -> waives the reservation vetos that
   guard EXPOSURE/risk-limit HARD controls. Barred (exposure non-bypassable).

### Legitimate path to the FILL (Phase 7, substantial, NOT rushed under budget)
Establish the arm state BEFORE PL:44631 (marker recovery + validate_canary_arm),
then a dedicated recovery-allocation that (a) waives ONLY the temporal/certification
PIT + reservation-consistency vetos for the validated single-use arm, while (b) the
allocator still computes a REAL conservative size and enforces the HARD
liquidation/margin/stop/EXPOSURE/duplicate controls on that size — and supplies a
complete, PIT-ordered, genuinely-derivable allocation-input bundle (OHLCV ATR with
corrected ~531ms ordering; entry_feature/portfolio_state clocks). Microstructure
trust must be honestly ABSENT (not fabricated); either the recovery-allocation
tolerates its absence as a scoped certification waiver, or the fill legitimately
requires a symbol/timeframe with a genuine fresh microstructure-complete snapshot —
which is the system-wide feature/microstructure staleness that is the real root
blocker the whole recovery effort exists to fix.

Terminal state this pass: `PAPER_RECOVERY_CANARY_CHAIN_AND_CERTIFICATION_PROVEN;
FILL_HELD_AT_HARD_ALLOCATION_EXPOSURE_BOUNDARY`. Live blocked throughout;
places_real_order=false; exchange_action_taken=false; no order artifacts; no
position opened; global breaker still HALTED for ordinary intents; paper loop
healthy (NRestarts=0, single writer).

## Guardian gate root-cause — raw-evidence chain (2026-07-25T05:4xZ)

Guardian FAIL 11/16; the 5 failing gates (G03/G11/G12/G13/G14) all trace to ONE
systemic deadlock, verified against raw runtime (not summaries):

- **G13** notional-wtd expectancy = -18.13 bps, **G14** PF = 0.658 — computed over
  the SAME 92-trade sample; `v2:paper:closed_trades` latest close =
  `2026-07-17T22:48:28Z` (raw: redis GET). **No paper close in 8 days.**
- **Why no closes:** `v2:paper:performance_circuit_breaker_status.state =
  HALTED_PERFORMANCE` (global halt, triggered by the genuinely poor PF 0.658) +
  the allocation hard boundary the Pass-3 canary hit. Ordinary entries halted.
- **Why edge can't improve (CG-F053):** no new samples -> model edge frozen.
- **Why no fresh routable predictions (CG-F054):** native-cuda-trainer-persistent
  status.json `status_generated_at=2026-07-25T05:25:28Z` (LIVE) but
  `prediction_authorized=False`, `serving_authorized=False` — it runs by design as
  `locally-authenticated-profiled-research-publisher` (non-promotable OBSERVER),
  NOT a serving predictor. All 1284 `v2:prediction:*` keys are stale
  `generated_utc=2026-07-18T05:19Z` relics. Serving path stopped 7 days ago.
- CG-F049/F050/F051/F052 fixes are in code (CG-F051 liquidation exit verified: the
  `getattr(position,'liquidation_distance_bps')` bug is already replaced by
  `_current_liquidation_distance_bps()` computing side-aware distance to
  `position.liquidation_price_estimate`, fail-closed) but all four are
  SAMPLE-STARVED for runtime proof — blocked on the same no-new-closes deadlock.

**Deadlock:** poor PF -> circuit HALTED + no serving predictions -> no new paper
trades -> no new samples -> edge frozen -> poor PF persists. Breaking it needs
either (a) the dedicated recovery-allocation Phase-7 build (waive ONLY temporal/
certification vetos for the validated single-use arm while the allocator still
enforces hard liquidation/margin/stop/EXPOSURE on a real conservative size) plus a
genuinely microstructure-complete snapshot, or (b) offline/backtest edge training
to build the brain without live samples (memory: "offline+H2L drives improvement").
Both are multi-hour/multi-day. Neither G13 nor G14 can be made to PASS this turn
without fabricating edge/performance or forcing trades past hard controls — both
barred by the rails. Live blocked throughout; no order artifacts; no position.
