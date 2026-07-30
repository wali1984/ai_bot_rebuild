# TERMINAL-WEALTH CLEAN RELEASE MANIFEST

## DEPLOYED 2026-07-30 ~16:51 EDT — final release SHA `f59dd1565097ce7ff4525dc8000bf9797643d9cd`

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
