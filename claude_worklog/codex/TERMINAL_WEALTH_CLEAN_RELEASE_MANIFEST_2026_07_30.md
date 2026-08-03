# TERMINAL-WEALTH CLEAN RELEASE MANIFEST

## PAPER EXPLORATION AUTHORITY CORRECTION — DEPLOYED `7b07910eb6` (2026-07-31 ~01:16Z)

Operator directive 2026-07-31 implemented as ONE in-place correction (no new
service/selector): central module `paper_exploration_authority_v2.py` with the
three-class taxonomy (HARD_SAFETY / EXECUTION_INTEGRITY / TRADING_POLICY),
fail-closed on unknown reasons, env lever `PAPER_EXPLORATION_OVERRIDE`
(default true, paper lane only).  Wired mechanically at: final-admission
reject() (telemetry published in the contract), preemptive edge control, P0/
non-relaxable entry gates (replaces bespoke strip lists), performance circuit
(continuous bounded-multiplier for all paper intents absent catastrophic
mandate), router bucket-performance quarantine, standalone-1m gate.
Single-flight removals: open experiment no longer suppresses designation; no
per-cycle authorization cap; shadow hard-check no longer requires zero open
positions for directional actions; authorization bootstrap lane is parallel
(info-gain>0 retained).  Concurrency now governed by the adaptive allocator
envelope + margin/reservation + per-symbol duplicate guard + 32-position
capacity backstop.  All authentication/PIT/venue/accounting/reservation/
duplicate/exposure/liquidation/mandatory-protection/catastrophic/live rails
unchanged (live BLOCKED).

Verification: 3-agent boundary recon (114+wrapped final-admission reasons
classified; every upstream boundary vocabulary mapped; 5 single-flight sites
pinned); 30 legacy-contract tests pinned under override-off; 30 new
override-on tests with probe-verified non-tautology; full battery 2,842
passed; offline calibration acceptance gate 10/10 PASS from the new snapshot;
ordered four-unit cutover (sentinel stopped first per runbook); first cycle
COMPLETED with 1 accepted ADAPTIVE_POLICY_V2 fill, 1 open position, zero
contract errors.  Runtime proof (directive point 9) accumulating in
session-independent `ai-bot-v2-paper-exploration-proof-watch.service`
(P1 concurrent protected positions / P2 policy-negative hard-valid fill /
P3 authorization while positions open / P4 qualified protected closes;
fail-fast on restart/SHA-drift/parity/schema/duplicate/lifecycle defects;
state at terminal_wealth_watch/proof_watch_state.json, events at
proof_events.jsonl).  Cherry-picked to codex/pipeline-trust-refresh as
`8a61f56a49`.  Guardian gates untouched.

## BURN-IN ACCEPTANCE — PASS (2026-07-31 00:04Z / 2026-07-30 20:04 EDT)

The operator-defined event-based burn-in contract on frozen release
`a4cf7ebc9f936fd774789fe9c1fdb32b7d50ef6d` is SATISFIED:

```text
calibration v3 publications:      20 / 3   PASS
completed paper cycles on SHA:    42 / 5   PASS
qualified protected closes:        3 / 3   PASS  (PROTECTED_RECONCILED_LIFECYCLE_V1)
restart deltas:                   0/0/0/0  HELD
production/reference disagreements:     0  HELD
schema mismatches:                      0  HELD
SHA drift:                              0  HELD
failed runtime predicates:              0  HELD
close candidates failing qualification: 0
```

The three qualified lifecycles (each passing all fourteen row-level +
account-level predicates independently):

```text
PENGUUSDT short  TIER_2_ADAPTIVE_POLICY_PROFIT_EXIT  +96.0 bps  +$0.6430  22:38:20Z
FETUSDT   long   TIER_2_ADAPTIVE_POLICY_PROFIT_EXIT  +41.7 bps  +$0.0354  23:36:13Z
NEARUSDT  long   TIER_2_ADAPTIVE_POLICY_PROFIT_EXIT  +47.8 bps  +$0.0366  00:04:18Z
```

Both sides represented, three symbols, all three via configured profit-target
exits with mandatory protection present at entry and full reconciliation.

Status ladder:
- post-deployment execution smoke test: PASS
- continuous post-deployment operation: PROVEN (3 sequential qualified
  lifecycles, no production code changes during observation)
- permanent-recovery designation: operator's call on this evidence.

Honest caveats: three profitable closes do not change the aggregate
economics (99 trades, expectancy still negative; G13/G14 remain honest-red);
the binding constraint remains trainer-lane edge. The frozen line stays
frozen; live authority stays BLOCKED.

### Post-acceptance sentinel (operator caveat: session-independent observation)

Because interactive-session teardown killed the in-session monitor twice
during the burn-in (counters preserved via persisted state both times),
standing observation now runs OUTSIDE any Claude session as a transient
user-systemd unit:

```text
unit:    ai-bot-v2-terminal-wealth-watch.service (systemd-run --user, Restart=no)
script:  /home/wali/ai_bot_local_data/terminal_wealth_watch/terminal_wealth_watch.py
state:   /home/wali/ai_bot_local_data/terminal_wealth_watch/watch_state.json (60s samples)
closes:  /home/wali/ai_bot_local_data/terminal_wealth_watch/qualified_closes.jsonl (append-only)
role:    fail-fast only — no pass condition; HOLDING until a precise predicate
         fails (restart delta, SHA drift, parity disagreement, schema-mismatch
         marker, or any new close failing PROTECTED_RECONCILED_LIFECYCLE_V1
         on two consecutive samples)
stop:    systemctl --user stop ai-bot-v2-terminal-wealth-watch.service
         (stop FIRST before any deliberate redeploy of the four units,
         else the redeploy correctly trips the sentinel)
```

Monitor-only; no production code, no gates, no thresholds touched. First
sample 2026-07-31T00:17Z: verdict HOLDING, all deltas zero.

## SHA-CHANGE RECONCILIATION (operator-required, 2026-07-30 ~17:55 EDT)

Why the accepted SHA changed from `f59dd15650` to `a4cf7ebc9f`:

- Parent: `a4cf7ebc9f936fd774789fe9c1fdb32b7d50ef6d` has exactly one parent,
  `f59dd1565097ce7ff4525dc8000bf9797643d9cd` (verified:
  `git log f59dd15650..a4cf7ebc9f` = one commit).
- Exact diff: 2 files, +53/−6 —
  `candidate_outcome_calibration_v2.py` (correlation attestation logic only:
  `correlation_penalty_learned_online` made conditional on measured rows,
  `correlation_penalty_evidence_available` added,
  `correlation_penalty_derivation_or_initialization` added) and its unit test
  file. No other runtime change of any kind.
- Classification: this IS a production-code change → NEW runtime release per
  operator rule. The burn-in therefore counts from zero on `a4cf7ebc9f`; no
  `f59dd15650` runtime evidence is counted toward `a4cf7ebc9f` acceptance
  (the monitor baseline was captured after the `a4cf7ebc9f` cutover; the
  seeded 2-publication/3-cycle continuity events are all post-`a4cf7ebc9f`
  events whose observation gap was verified clean — absolute NRestarts
  unchanged at 0, closed-trade count unchanged at 96).

Acceptance facts captured live at 17:55 EDT:

```text
all_four_process_cmdlines_sha            = a4cf7ebc9f  (via /proc/<pid>/cmdline)
all_four_loaded_dropins_sha              = a4cf7ebc9f  (DropInPaths grep + NeedDaemonReload=no)
immutable_checkout_clean                 = true        (git diff --quiet vs a4cf7ebc9f)
NRestarts_baseline_recorded_after_cutover = true       (all four = 0 absolute)
```

## BURN-IN MONITOR CORRECTION (operator-required, 2026-07-30 ~18:3x EDT)

Evidence-monitor defect (NOT a production defect): the close counter was a
row-count delta, proving appends rather than valid lifecycles. Corrected —
each close appended after the baseline must now independently pass
`PROTECTED_RECONCILED_LIFECYCLE_V1`:
row-level `close_id` unique, `close_event_time` after the 21:52Z cutover,
`remaining_quantity_after_close == 0`, `reduce_only == true`, mandatory
protection existed at entry (`adaptive_policy_stop_price` /
`stop_distance_bps > 0`), all four paper/live flags correct; account-level
`paper_position_fill_reconciliation_status.status == PASS` with
`phantom_position_count == 0` and `unresolved_position_count == 0`,
`paper_position_close_transition_status.status == PASS`,
`paper_account_margin_status.accounting_complete == true` and
`invariant == true`. Total account margin is deliberately NOT required to be
zero (concurrent positions are legitimate). A close failing qualification on
two consecutive samples (one retry absorbs non-atomic status-block write
skew, per the G08 hardening) is a lifecycle defect → burn-in
FAILED_PREDICATE. Qualifier validated against real data before relaunch: the
last genuine pre-cutover close fails only the cutover-time predicate; the
same row shifted post-cutover fully qualifies; a corrupted variant lists
exactly its broken predicates. Publication/cycle counters (6/12, both past
threshold) were seeded across the monitor swap; the qualified-close counter
started at zero. The frozen production line was NOT touched.

## CURRENT DEPLOYED LINE — `a4cf7ebc9f936fd774789fe9c1fdb32b7d50ef6d` (2026-07-30 ~17:5x EDT)

`a4cf7ebc9f` = `f59dd15650` + the single operator-authorized correction:
**truthful correlation-penalty attestation.** The live artifact had claimed
`correlation_penalty_learned_online=true` against 0 measured / 20,506 missing
correlation rows. Now: the flag is conditional on measured rows, with
`correlation_penalty_evidence_available` and an explicit
`correlation_penalty_derivation_or_initialization`
(`REGULARIZED_LOGISTIC_PRIOR_ONLY_ZERO_FEATURE_NO_MEASURED_EXPOSURE_ROWS`
in the current live state). The penalty remains present as a regularized
prior; only its provenance claim changed. No consumer reads the flag
(verified single producer site). Offline acceptance gate extended with an
attestation-consistency predicate: 10/10 PASS on the real archive.
Corrected artifact verified live (`corr_learned=False|evid=False`), then all
four services cut over to `a4cf7ebc9f` (ordered, calibration first),
verified active on the SHA via /proc. Cherry-picked to
codex/pipeline-trust-refresh as `d41bc08707`.

Per operator verdict, the line is FROZEN: further code changes require an
exact runtime failure predicate. Event-based burn-in running
(scratchpad/burn_in_monitor.py → burn_in_state.json): PASS requires
calibration v3 publications ≥3, paper cycles on the SHA ≥5, post-deploy
closes ≥3, while restarts/parity-disagreements/schema-mismatches stay 0.
Status ladder: post-deployment execution smoke test PASS; continuous
post-deployment operation PARTIAL (pending burn-in); permanent recovery NOT
YET PROVEN. Economic edge remains the binding constraint (trainer lane).

## PRIOR DEPLOY 2026-07-30 ~16:51 EDT — `f59dd1565097ce7ff4525dc8000bf9797643d9cd`

`f59dd15650` = `f21fa6b672` (below) + one incident fix:
**fix(calibration): admit legacy archive rows without correlation exposure.**
The first cutover attempt from `f21fa6b672` crash-looped the calibration
publisher (13 restarts): `extract_calibration_observation` hard-required
`correlation_exposure_after_trade` on every archive record, but ALL 20,506
current fit rows predate the 2026-07-29 correlation contract (offline
write-blocked repro on the real archive died in seconds at 55 MB RSS with
`correlation_exposure_after_trade:finite_number_required`; the 2–3 GB cgroup
climbs were page-cache attribution from the per-cycle archive snapshot copy —
memory was a red herring, though both fit units were also throttle-clipped
and their caps were raised with measured evidence: calibration 1536M/2G →
3G/4G, shadow 1G/2G → 2G/3G). Fix mirrors the four optional source siblings:
`correlation_exposure_source: float | None`, legacy rows admitted with an
honest None (never imputed), zero contribution to the correlation feature,
measured/missing counts published in optimizer evidence. Old stack was rolled
back and verified stable between the two attempts.

Deployment evidence (all four units on `f59dd156`, ordered cutover):
- Offline acceptance gate (write-blocked full cycle on the REAL archive):
  ACCEPTANCE PASS — 9/9 checks (v3 schemas, terminal fields, learned_online
  honesty, selection_authority=false, legacy counts 0 measured / 20,506
  missing), 220 s, 245 MB peak RSS.
- Live v3 artifact in `v2:adaptive_system:candidate_calibration:v2`
  (calibration publisher NRestarts=0).
- All four units active on `f59dd156…` (verified via /proc cmdline), 5-minute
  stability watch: NRestarts=0 across the board.
- Shadow runtime: 123 candidates, coverage 1.0, production/reference parity
  PASS, 0 disagreements, consuming the v3 calibration.
- Paper loop cycle 21:01Z: 261 candidates evaluated,
  `TERMINAL_PROBABILITY_TELEMETRY_ONLY` selection rule live, and ONE
  `ADAPTIVE_POLICY_V2` fill ACCEPTED (continuous paper trading confirmed on
  the new stack); remaining blocks are honest per-candidate adaptive
  thresholds.
- Live authority blocked everywhere (`live_gate=blocked_human_only`,
  `routes_to_live=false`, `places_real_order=false` in every section).

The incident fix is also cherry-picked onto `codex/pipeline-trust-refresh`
as `2d3b61836e`.

---

Base release SHA: `f21fa6b6726899b7a740a0abf5e2f6c596467e36`
Branch: `release/terminal-wealth-f1f4-clean`
Baseline: `dc0638b89a` (reviewed guardian G08 session-scope fix)
Contents: exactly 18 files, 4,065 insertions, 173 deletions. Nothing else.
Provenance: file contents taken verbatim from reviewed commit `e443c1eaaf`
(itself = Codex in-flight F1–F4 fixes + Claude F3/F2 completions + 44
test-drift repairs), plus 15 new continuous-paper regression tests
(+1,016 test lines) written against this tree.

Explicitly EXCLUDED from the release (remain only on
`codex/pipeline-trust-refresh`): raw_evidence/*, trainer run records,
worklogs, FINAL PASS.md, .claude hook change, deploy tooling, gen3/4/5
scripts, watchdogs, unrelated services/tests swept into `83bdd4b50b`.

## Production modules (8)

| File | Reason included | Finding | Test coverage |
|---|---|---|---|
| v2/backend/app/cli/v2_trade_management_paper_loop.py | Designation ranking key `(utility, gain_nats, action_id)`; telemetry-only eligibility stamps; `LookupError` in both catch tuples; `require_complete_terminal_state=True` authoritative path; terminal-state producer; same-cycle ranked-queue fallback | F1, F2, F3, F5–F7 authority | test_v2_trade_management_paper_loop.py 766/766 (incl. 9 new P1/P2/P4/P5 tests) |
| v2/backend/app/services/adaptive_system/adaptive_objective_v2.py | `learned_terminal_equity_objective_weights_v3`; per-opportunity UNIT_CONTRACT; probability contribution hard-zeroed; TerminalEquityProjectionV1 honesty invariants | F1, F2, F3, F5–F7 | test_adaptive_objective_v2.py (incl. magnitude + zero-edge + telemetry-only tests) |
| v2/backend/app/services/adaptive_system/adaptive_objective_reference_v2.py | Reference-twin parity with the production objective | F1 parity | reference replay assertions in adaptive_system suite |
| v2/backend/app/services/adaptive_system/adaptive_policy_shadow_v2.py | Strict finite accessors (incl. `_allocation`); tracked `defaulted_fields`; honest evidence flags; terminal-state digest bound into fingerprints; per-opportunity growth producer | F1, F2, F3 | test_adaptive_policy_shadow_v2.py + bounded-info-gain suite (16 tests incl. 6 new) |
| v2/backend/app/services/adaptive_system/candidate_outcome_calibration_v2.py | `candidate_outcome_calibration_v3`; `learned_online=false` + exact derivation declarations, validator-recomputed; `terminal_target_probability_selection_authority=false` attestation | F2, F4, F5–F7 | test_candidate_outcome_calibration_v2.py |
| v2/backend/app/services/paper_trade_management/outcomes.py | Honesty-contract propagation on close records; legacy fabricated entry snapshots demoted (never trusted); dishonest/partial shapes fail closed | F3 | test_round_trip_close_costs.py (12 tests, 5 new honesty tests) |
| v2/backend/app/services/paper_trade_management/position_state.py | Persists `adaptive_policy_terminal_equity_objective` entry snapshot through position state | F3 consumer compatibility | test_round_trip_close_costs.py persistence assertions |
| v2/backend/app/services/strategy_router/ordinary_paper_interpretation.py | CG-F061: `PAPER_LOSS_BUCKET_QUARANTINE` becomes a bounded Category-E continuous input (REDUCE_SIZE), never a permanent veto; hard router reasons untouched | Continuous-paper P5 | test_ordinary_paper_interpretation.py (incl. quarantine-is-continuous test) |

## Test files (10)

| File | Reason included |
|---|---|
| v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py | Terminal-wealth assertions + 44 drift repairs (all five clusters were fixture drift vs 07-20/07-24/07-26/07-27 hardening) + 9 new continuous-paper regression tests |
| v2/backend/tests/unit/services/adaptive_system/test_adaptive_objective_v2.py | v3 contract, magnitude-parity, zero-edge, telemetry-only-ranking tests |
| v2/backend/tests/unit/services/adaptive_system/test_adaptive_policy_shadow_v2.py | Honest-flag estimator + strict-accessor tests |
| v2/backend/tests/unit/services/adaptive_system/test_candidate_outcome_calibration_v2.py | v3 validator + derivation-attestation tests |
| v2/backend/tests/unit/services/adaptive_system/test_bounded_information_gain_exploration_selection.py | Fixture lockstep + 6 new tests: evidenced-posterior authorization, ranked lower-rank execution, exact venue-minimum lot, aged-calibration non-suppression, queue-head predicate on real shadow results |
| v2/backend/tests/unit/services/adaptive_system/test_candidate_outcome_publisher_v2.py | Fixture lockstep (correlation exposure field) |
| v2/backend/tests/unit/services/microstructure_trust/test_cg_f057_completion_acceptance.py | Fixture lockstep (correlation exposure source) |
| v2/backend/tests/unit/services/paper_trade_management/test_round_trip_close_costs.py | F3 honesty-contract tests (legacy demotion, honest propagation, fail-closed) |
| v2/backend/tests/unit/services/test_ordinary_paper_admission.py | CG-F061 lockstep (parametrized side) |
| v2/backend/tests/unit/services/strategy_router/test_ordinary_paper_interpretation.py | CG-F061 tests (soft quarantine both sides) |

## Continuous-paper regression proof (operator properties P1–P7)

15 new tests, all against real functions, all green:

- P1 no post-close freeze: epoch-scoping (4 directions — previous-epoch open row never freezes a fresh campaign; current-epoch/unstamped opens still suppress), first-negative-close is a bounded multiplier not a next-cycle veto, close bookkeeping composes to no entry freeze.
- P2 maturation never blocks: 50-row unmatured close backlog never suppresses designation; 14-day-aged calibration fit still selects + authorizes bootstrap.
- P3 evidence never disables exploration: evidenced (non-prior-only) posterior authorizes through the standard paper lane; real paper-loop designation with evidence recognized/selected/authorized.
- P4 full traversal + same-cycle fallback: complete ranked-candidate list contract (ranks, strict utility order, queue-match keys); disposition taxonomy pinned (VENUE_MINIMUM_HARD_RISK_REJECTED / CANDIDATE_NOT_IN_CURRENT_CYCLE_UNIVERSE / SELECTED_AND_FILL_ADMITTED); queue-head failure-predicate classification on real shadow results; run_once wiring contract (two `[1:]` pops, single shadow call site, cycle-authorization counter).
- P5 no preference veto on bootstrap: final-admission positivity veto scoped off bootstrap (bootstrap with negative expected pnl passes the ENTIRE real final-admission contract; champion variant rejects; allocator-integrity mismatch still rejects for bootstrap); loss-bucket quarantine reduces size, never blocks.
- P6 executable sizes: sub-minimum target recomputed at the exact smallest executable lot (Decimal ceiling math pinned) and authorized at that exact size.
- P7 flat-account recoverability: flat + hard-valid candidate authorizes a bounded experiment in BOTH lanes (positive-utility exploration; negative-utility venue-minimum bootstrap when no positive-utility action exists); hard-invalid candidates are never resurrected.

## Verification record

- Release battery (this tree): **2,810 passed, 0 failed** — paper-loop file
  766/766; adaptive_system, domain, paper_trade_management, strategy_router,
  admission, microstructure-acceptance, shadow/calibration/outcome publisher,
  bounded exploration, trajectory tracker, tuner, cutover CLI suites.
- G12 rare-event stress matrix: re-run 2026-07-30 — **17/17 PASS, 0 WARN,
  0 FAIL** after re-executing the three stale canaries (S13 max-hold
  transport, S15 stale-feature injection, S16 redis resilience — all pass).
- Systemd state: four drop-ins restored byte-identical to pre-staging
  backups before this release was built (verified, no candidate refs).
- Live authority: BLOCKED throughout (paper_only/live_gate flags asserted at
  every new contract layer; G15 untouched).
