# TERMINAL-WEALTH COMPLETION — F1–F4 ACCEPTANCE RECORD + REMAINING WORK (2026-07-30)

Authority: operator NO-GO verdict 2026-07-30 on the in-flight terminal-wealth
implementation; operator instruction to Claude (03:05 EDT) to fix F1–F4 alongside
verification. Source review: `claude_worklog/TERMINAL_WEALTH_OBJECTIVE_REVIEW_2026_07_29.md`.

Verification basis: 12-agent adversarial verify+refute sweep (read-only) against
the UNCOMMITTED working tree on `codex/pipeline-trust-refresh`, run 03:05–03:18 EDT
2026-07-30. IMPORTANT: Codex was actively editing the subject files DURING the
sweep (mtimes advanced 03:05 → 03:17); statuses below are pinned to the last
snapshot each agent read. Line anchors will drift.

## Standing constraints (unchanged)

- Do NOT deploy the in-flight implementation until every item below is closed.
- `terminal_target_probability` is TELEMETRY ONLY (no selection/sizing authority)
  until the persistent-uncertainty + liquidation model is hardened (F5–F7).
- `target_guaranteed` stays false. Live authority stays BLOCKED.
- Do not modify ingestion, trainer topology, the working paper lifecycle,
  accounting, continuous exploration, or outcome maturation.

## Verified per-finding status (as of 03:15–03:17 EDT snapshots)

### F1 — units mismatch — CODE FIXED, TESTS MISSING
FIXED in tree: `_derive_score_values` now multiplies the per-trade-scale weight by
`expected_log_equity_growth_per_opportunity` (no n multiplier); the n-compounded
value survives only as a published projection field; probability contribution
hard-zeroed as telemetry-only; UNIT_CONTRACT declares
`EXPECTED_LOG_EQUITY_GROWTH_PER_OPPORTUNITY_NATS` +
`TERMINAL_TARGET_PROBABILITY_AND_COMPOUNDED_GROWTH_TELEMETRY_ONLY`
(adaptive_objective_v2.py ~:49-56, ~:829-853; adaptive_policy_shadow_v2.py
~:1719-1726; reference twin in lockstep).
REMAINING (blocking acceptance):
- [ ] Magnitude regression test: at representative operating points the
      growth-term contribution must stay within the same order of magnitude as
      return / cost / drawdown / tail contributions. Does not exist anywhere in
      v2/backend/tests as of the sweep.
- [ ] Zero-edge, zero-cost action ⇒ zero terminal deltas test. Absent.

### F2-CODE — contract/crash safety — ADDRESSED (refuter-confirmed)
- Schema bumps: `candidate_outcome_calibration_v3` (calibration_v2.py:25) +
  `learned_terminal_equity_objective_weights_v3` (adaptive_objective_v2.py:26);
  old live v2 artifact now fails validation with
  CandidateOutcomeCalibrationError (ValueError subclass) → graceful
  BLOCKED_ADAPTIVE_POLICY_AUTHORITY, not a crash-loop.
- Strict accessors: all 13 weight fields via `_strict_finite_field` →
  AdaptivePolicyShadowError (shadow ~:292-296); no bare raw[] on terminal keys.
- Both paper-loop catch tuples now include LookupError (~:55462-55471 eval
  boundary, ~:52011-52018 designation guard).
Residual hygiene (non-blocking but close it):
- [ ] Validator still does not ENUMERATE the required terminal weight keys inside
      `learned_objective_weights` (protection rests on the schema string alone).
      Add explicit required-key enumeration (calibration_v2.py ~:1693-1699 region).
- [ ] `_allocation` (shadow) retains bare `raw[...]` indexing — convert to strict
      accessor for uniformity.

### F2-DEPLOY — SHA skew + old artifact — STILL PRESENT (refuted at three layers)
Live state verified via drop-ins + loaded systemd config (NeedDaemonReload=no) +
/proc/<pid>/cmdline:
- paper loop: `6bcada5039` (up since 07-29 18:16 EDT)
- calibration publisher + candidate outcome publisher: `d4569be033` (20:33)
- adaptive policy shadow: `6f49487175` (20:33)
Three distinct SHAs. `FINAL PASS.md`'s claim of deployment at `81d2a014e7` is
CONTRADICTED by live state — .conf.bak files show 81d2a014 was deployed earlier
on 07-29 and then re-pinned away (81d2a014 → 19cc80c8 → e701fde9 → current).
Live artifact `v2:adaptive_system:candidate_calibration:v2` is schema
`learned_objective_weights_v2`, NO terminal fields, actively republished.
NRestarts=0 everywhere only because no service runs the new code yet.
Required choreography (in order, after all code items are closed and committed):
1. One commit set on the branch → one immutable release checkout for ALL FOUR
   services at the SAME SHA.
2. Check each unit's credential/EnvironmentFile posture BEFORE restart
   (standing rule from the 2026-07-24 profiled-base-feature-publisher incident).
3. Repoint the 90-immutable-*.conf drop-ins for all four units → daemon-reload.
4. Restart calibration publisher FIRST → verify a v3 artifact with both terminal
   weight fields lands in `v2:adaptive_system:candidate_calibration:v2`.
5. Then restart paper loop + shadow + outcome publisher.
6. Rollback = repoint drop-ins to previous SHA (old artifact stays valid for old code).

### F3 — evidence honesty — PARTIALLY ADDRESSED (one real gap left)
FIXED in tree: defaults tracked in `defaulted_fields` (12 sites);
`evidence_supported_probability` honest-conditional with schema invariant
forbidding True while unsupported/prior_only; paper loop passes
`require_complete_terminal_state=True` (fail-closed authoritative path, :55456);
diagnostic CLI explicitly passes False (permissive-but-flagged); terminal-state
digest bound into state_sha + receipts + fingerprinted projection; both test
files rewritten (81/81 passing at the 03:14 snapshot).
REMAINING (blocking acceptance):
- [ ] `outcomes.py` (untouched since 21:30, old contract): will mark every NEW
      realized-outcome projection UNAVAILABLE, and can still stamp
      `evidence_supported_probability=True` on records derived from legacy
      fabricated entry snapshots persisted in open-position state. Reconcile it
      to the new contract (honest flags on legacy-derived records; accept the
      new projection shape).

### F4 — attestation honesty — STILL PRESENT (as of 03:14; calibration touched
03:17, possibly mid-fix)
`expected_log_equity_growth_reward` = ratio-of-means (post-optimizer statistic,
calibration_v2.py ~:1261-1264); `terminal_target_probability_reward` = that
× ln(1000) (~:1265-1268); yet flags stamp both `*_learned_online: True` and
`all_economic_tradeoff_weights_learned_online: True` (~:1317-1321). Note: the
same false-attestation pattern also covers `information_gain_reward` and
`concentration_penalty` (post-hoc statistics, ~:1245-1252). No `derivation`
declaration anywhere in the file.
REQUIRED (either arm):
- [ ] (a) fit these coefficients inside the logistic optimizer on matured rows; or
- [ ] (b) declare `learned_online: false` + exact `derivation` (e.g.
      `RETURN_SCALE_RATIO_TIMES_LN_TARGET_MULTIPLE`) + source parameters for
      EVERY non-fitted coefficient (terminal pair + information_gain_reward +
      concentration_penalty), and make the aggregate flag truthful (drop or
      compute it honestly).

### F5–F7 — telemetry-only demotion — ADDRESSED (refuter-confirmed)
Ranking key is now `(utility, gain_nats, stable_id)`; selection rule string
declares `TERMINAL_PROBABILITY_TELEMETRY_ONLY`; eligibility hard-requires the
telemetry-only stamps (excluding pre-refactor persisted rows); objective
contribution hard-zeroed; calibration acceptance hard-fails unless
`terminal_target_probability_selection_authority is False`; unit test asserts
probability confers no ranking authority. Estimator hardening (persistent
parameter uncertainty, declared liquidation mixture) remains OPEN as follow-up —
acceptable only while telemetry-only holds.

## Division of labor (to avoid concurrent-edit clobbering)

Codex was actively editing at 03:17 EDT. Claude (interactive session) will take,
once the tree goes idle: F1 regression tests, F2 validator enumeration +
`_allocation` hygiene, F3 `outcomes.py` reconciliation, F4 (if still open),
full-suite run, checkpoint commit, and the F2-DEPLOY single-SHA choreography.
If Codex resumes on any of these files first, Codex owns that item; the
acceptance checklist above is the contract either way.

## Acceptance = every [ ] above checked + full suite green + four services on
one SHA + live v3 artifact verified + this file updated with the evidence.

---

## COMPLETION STATUS — 2026-07-30 ~04:05 EDT

All code items CLOSED and committed:

- Commit `83bdd4b50b` — F1–F4 completion (Codex in-flight fixes + Claude's
  F3 outcomes.py honesty reconciliation + F2 `_allocation` strict accessors +
  new honesty-contract tests). F4 was finished by Codex at 03:23 (learned_
  online=false + full derivation declarations, validator-enforced). F1
  magnitude + zero-edge regression tests exist (Codex, 03:12/03:22).
- Commit `e443c1eaaf` — repaired all 44 pre-existing paper-loop test failures
  (all five clusters verified TEST_DRIFT against deliberate 07-20/07-24/07-26/
  07-27 hardening; test-only edits; three assertions strengthened).
- Verification: paper-loop file 757/757; adjacent battery (adaptive_system,
  domain, paper_trade_management, shadow/calibration/outcome/trajectory/
  exploration/tuner/cascade/cutover CLI) 1593/1593.

F2-DEPLOY: STAGED, AWAITING OPERATOR (auto-mode classifier requires operator
review for production restarts — correct call):

- Immutable snapshot created + attested:
  `/home/wali/ai_bot_local_data/deployments/ai_bot_rebuild/e443c1eaaf365530a1b7f7a285c97b788c40759b`
- All four 90-immutable drop-ins repointed on disk to `e443c1eaaf…`
  (backups: `*.bak-20260730T0757Z`).
- NO daemon-reload has run since the edits: systemd's LOADED config still
  runs the old SHAs, so the staging is inert — no restart path (including the
  self-healing supervisor) can pick up the new SHA until reload.
- Both LoadCredential files verified present on disk (07-24 rule satisfied).

OPERATOR GO (one command; ordered restarts + v3-artifact verification built in):

    bash "claude_worklog/tools/deploy_terminal_wealth_four_service_single_sha.sh" \
      e443c1eaaf365530a1b7f7a285c97b788c40759b

OPERATOR ROLLBACK (decline the staged deploy):

    for f in ~/.config/systemd/user/ai-bot-v2-{candidate-outcome-calibration,candidate-outcome-publisher}.service.d/90-immutable-release.conf \
             ~/.config/systemd/user/ai-bot-v2-adaptive-policy-shadow.service.d/90-immutable-final-pass.conf \
             ~/.config/systemd/user/ai-bot-v2-trade-management-paper-loop.service.d/90-immutable-release.conf; do
      cp "$f.bak-20260730T0757Z" "$f"
    done
    # (no daemon-reload needed either way until you choose to deploy)

Expected post-deploy behavior: calibration publisher emits the v3 artifact
(terminal fields + learned_online=false derivations) into
`v2:adaptive_system:candidate_calibration:v2`; consumers accept it; the paper
loop still REMAIN_FLATs on the serving trust gate keystone (trust.py:511,
Codex v4 feature-lineage, repair-hold to 2026-08-09) — this deploy aligns the
honest objective, it does not by itself produce fills.
