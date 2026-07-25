# SIX-HOUR TRAIN-ROW SPRINT — status (2026-07-25)

Mission: (1) remove the 1000-row dependency from paper recovery; (2) attempt 1000
strict admitted rows in 6h via an operator-armed corpus sprint. Live blocked.

## DELIVERED (achievable, rail-safe) — all committed on codex/pipeline-trust-refresh

- **Objective 1 (required-regardless): paper recovery NOT blocked by the strict
  1000-row gate.** Recon proved no 1000-row/strict-champion gate exists on the
  paper-fill path (paper loop + risk gateway + orchestrator + a_plus all clean);
  the recovery policy already defaulted below 1000. Pinned the recovery floor to
  256 and wired the (previously dead-code) train-gate telemetry. Live now:
  `v2:paper:recovery:status` → `paper_recovery_train_gate_satisfied=true`,
  `paper recovery: 272/256 PASS`, `paper_recovery_not_blocked_by_strict_train_row_gate=true`,
  `strict_champion_min_train_rows=1000` (unchanged). Commit 245c5b86b0 / 0878999506.
- **Phase 1+2: continuous train-row telemetry.** Root cause of `train_rows=None`:
  the monitor read a top-level field that never existed (value lived at
  `backtests_processed.train_rows=55`). Fixed both sides — publisher now emits
  TOP-LEVEL `train_rows` + `last_successful_train_rows`, `strict_train_rows_remaining`,
  `current_manifest_candidate/admitted/rejected_rows`, `label_unavailable_rows`,
  `cost_unavailable_rows`, `duplicate_rows` (honest-null), `pit_rejected_rows`,
  `latest_unclosed_rejected_rows`, `admission_yield_ratio`, `estimated_commits_needed`.
  Monitor shows dual `PAPER RECOVERY GATE 272/256 PASS` + `STRICT CHAMPION GATE
  55/1000`. Pure read/derive; safety anchors untouched; the 15-min publisher timer
  republishes with the new fields (no restart). Commit f4e33b456a.
- **Phase 3: TrainerCorpusSprintArmV1** — operator-armed, auto-expiring
  (TTL==6h), fail-closed, paper-only. Hard caps (6h/20GiB/74 symbols) + adaptive
  cadence (180→300 backoff) + disable/pause rules + yield-based commit estimator.
  Commit aec0345536.
- **Arming CLI + STRICT_TRAIN_ROW_SPRINT_ACTIVE.** `v2_trainer_corpus_sprint_arm
  arm|disarm|status` writes `v2:trainer:corpus_sprint:{arm,status}`. The sprint is
  ARMED (state=STRICT_TRAIN_ROW_SPRINT_ACTIVE, operator_authorized, expires in 6h).
  Honest `publisher_acceleration_active=false` with explicit `execution_blockers`
  (no hollow "accelerating" claim). Commit 4e5c2b92fd.

64 focused tests across the new modules; all green. Nothing restarted; strict
1000 gate untouched; no synthetic provenance; no latest-unclosed relaxation.

## NOT DELIVERED (operator-gated / out-of-tree / data-bound) — honest

The strict 1000-row sprint CANNOT be executed to 74-symbol / 180s acceleration by
this agent right now, for three independently-verified reasons:

1. **Publisher restart is credential-gated + exit-78 hazardous.** The 3 operator
   `.cred` files are ABSENT from `~/.config/ai-bot-v2/credentials/profiled-base-
   feature-publisher/`; the running publisher (release 18e2e4b408, PID 425371)
   survives on in-RAM creds. Any restart/daemon-reload → `exit 78` →
   `RestartPreventExitStatus` keeps it DOWN (the 2026-07-24 incident). I did NOT
   restart it (`publisher_restarts=0` is itself an acceptance criterion).
2. **No single release has both the override AND the throughput controller.** HEAD
   carries the disk-horizon override (858ef670e7) but LACKS the throughput
   controller (df1b90113e). Dry-run PROOF (no restart, no creds): at 3d horizon
   HEAD's `config_valid=True`, `disk_cap 0→21`, but `latency_cap` stays the binding
   limiter — deploying HEAD wholesale would select ~2/cycle, FEWER than the
   deployed release's 16. Reaching 74 needs a COMBINED release
   (cherry-pick 858ef670e7 onto the df1b90113e lineage), not HEAD.
3. **The real trainer is out-of-tree + the strict admission is data-bound.** The
   working-tree trainer CLI is a 69-line waiting stub; the manifest builder that
   admits strict rows lives in deployed release 974caa6c26. Strict admission
   currently rejects **59766/60000** snapshots as `latest_unclosed_exclusion_
   unproven` → `admission_yield≈0.0009`, so `estimated_commits_needed` is
   astronomical: the binding constraint is the finality/label-proof admission
   funnel, NOT publisher volume or cycle speed. Relaxing the unclosed exclusion
   would be a PIT-safety/no-latest-unclosed rail violation — not done.

## Operator unlock recipe (to actually run the sprint)

1. Re-provision the 3 publisher `.cred` files (operator-only: Binance API creds).
2. Cut a combined immutable publisher release = deployed throughput lineage +
   cherry-pick 858ef670e7 (override); set `PROFILED_BASE_PUBLISHER_MINIMUM_HORIZON_
   OVERRIDE_SECONDS=259200` AND `PROFILED_BASE_PUBLISHER_RESOURCE_HORIZON_SECONDS=
   259200` together; validate via the one-shot dry-run before restart.
3. Wire arm-consumption (this arm) into that release's per-cycle selection.
4. Address the `latest_unclosed_exclusion_unproven` funnel with GENUINE candle-
   finality/label proof (never by relaxing the unclosed exclusion).

Required-regardless final state ACHIEVED: `PAPER_RECOVERY_NOT_BLOCKED_BY_STRICT_
TRAIN_ROW_GATE`. Preferred `strict_train_rows>=1000` is blocked behind the above.
Live blocked throughout; places_real_order=false; exchange_action_taken=false.
