# Generation 3 Natural Acceptance Boundary

Generated: 2026-07-26 23:46 UTC  
Classification: `GENERATION_3_ADMISSION_STARVATION`  
Safety: paper only; `live_gate=blocked_human_only`; no exchange action

## Frozen bounded window

The predeclared generation-3 window is the first 50 completed paper matrices in
`.local_data/permanent_system_recovery/generation_acceptance_cycles_v1.jsonl`.
It ran from 2026-07-26 22:11:44.748 UTC through 23:38:26.267 UTC, covering
5,201.575 seconds. This exceeds one complete 1-hour maximum eligible timeframe
window for the active continuous-crypto 5m/15m/1h universe.

| Predicate | Actual | Required |
|---|---:|---:|
| completed cycles | 50 | 50 |
| elapsed seconds | 5,201.575 | 3,600 |
| canonical predictions observed | 6,216 | >0 |
| directional predictions observed | 1,999 | >0 |
| candidates evaluated | 710 | >0 |
| candidates admitted | 0 | >0 for lifecycle |
| paper fills | 0 | >0 for lifecycle |
| open positions | 0 | >0 for restart proof |
| natural closes | 0 | 5 for economics |

Primary rejection attribution is exact over the frozen 710 candidates:

- `BLOCK_MICROSTRUCTURE_UNSAFE`: 687 (96.7606%)
- `BLOCK_GUARDIAN_HALTED`: 21 (2.9577%)
- `BLOCK_FVG_STRUCTURE_INVALID`: 2 (0.2817%)

The dominant supporting constraints were insufficient bucket evidence (710),
insufficient FVG microstructure trust (686), weak exit feasibility (630),
unrealistic MFE relative to stop risk (630), and invalid FVG exit feasibility
(612). Exact microstructure evidence ages ranged from 26.164 to 173.045 seconds
(median 99.663); the feed-quality producer remained active with no sequence-gap
rows. This is unsafe trade-specific market admission, not a stale-feed outage.

Generation 3 is not HOLD-degenerate: 1,999 directional predictions reached the
paper boundary. Of the 710 candidates, 62 satisfied the model-loss probation
bound, 44 satisfied exit feasibility, 238 satisfied the advanced-indicator
predicate, and only 2 had microstructure action `ALLOW`. No candidate satisfied
all unchanged safety predicates, no candidate was otherwise valid except for
the model, and no candidate was otherwise valid except for microstructure.
Retraining or threshold changes are therefore not justified by this window.

The cohort-scoped breaker allowed new entries whenever its exact projection was
present (`ACTIVE_INSUFFICIENT_COHORT_SAMPLE`); the global continuous guardian
remained intentionally repair-held and absent. The adaptive tuner remained
fail-closed because all 92 historical rows failed point-in-time/schema evidence
admission. Historical evidence was not changed.

## Redis capacity repair

Runtime inspection found that each preemptive receipt was approximately 14.25
MB because it duplicated a 13.46 MB adaptive-tuning source payload. With 1,671
per-decision keys and 293 latest keys, Redis reached 34.01 GB allocated under a
32 GiB `allkeys-lru` ceiling; the server had recorded 1,464,112 evictions.

Commit `9f510717ebb05dd7c90a4fc17962096986c81b15` retains the full adaptive source
SHA-256 and all evaluator-consumed fields in a deterministic replayable
projection. It does not change a threshold, action, strategy, or admission
decision. The immutable paper service was deployed at that commit with no open
position. A production latest receipt measured 746,451 bytes, a 94.76% reduction
from the sampled 14,250,494-byte legacy receipt. Historical TTL-bound receipts
were preserved and will age out normally.

## Truthful stop state

The bounded current-market stop condition is satisfied, but permanent recovery
is not complete. The natural paper lifecycle, restart reconstruction, two
additional cycles, five-close economic cohort, G03, G11, G13, and G14 remain
open. G12 remains 17/17 PASS. Do not emit `V2_PERMANENT_RECOVERY_COMPLETE`.

Safe next action: leave the paper-only services and unchanged gates running;
resume lifecycle/restart acceptance only after the fresh, generation-bound
predicate below succeeds. A new model generation is not authorized by this
evidence.

## Fresh generation-bound resume predicate

The observer artifact is a 10-second heartbeat over a roughly one-minute paper
cycle. The resume check therefore requires the status heartbeat to be no more
than 60 seconds old and the latest completed cycle observation to be no more
than 180 seconds old. Invalid JSON, missing timestamps, malformed timestamps,
the wrong generation/checkpoint/cohort, a closed position, or any unsafe
authority flag makes `jq -e` exit nonzero.

```bash
jq -e '
  def epoch:
    if type == "string" then
      (sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601)
    else
      error("timestamp_not_string")
    end;
  . as $s
  | ($s.generated_utc | epoch) as $status_epoch
  | ($s.latest_cycle.observed_utc | epoch) as $cycle_epoch
  | $s.schema_version == "generation_natural_acceptance_observer_v1"
    and (now >= $status_epoch and (now - $status_epoch) <= 60)
    and (now >= $cycle_epoch and (now - $cycle_epoch) <= 180)
    and $s.classification == "NATURAL_ADMISSION_OBSERVED"
    and $s.checkpoint_generation == 3
    and $s.checkpoint_id == "SERVING_ABI_V2_PAPER_f2f6e3b4c67a42b6c13880a4"
    and $s.cohort_id == "paper_serving_abi_v2:541f38b82f5261b5176bbf5f"
    and $s.latest_cycle.checkpoint_generation == $s.checkpoint_generation
    and $s.latest_cycle.checkpoint_id == $s.checkpoint_id
    and $s.latest_cycle.cohort_id == $s.cohort_id
    and (($s.candidates_admitted // 0) > 0)
    and (($s.paper_fills_created // 0) > 0)
    and (($s.generation_open_positions // 0) > 0)
    and $s.paper_only == true
    and $s.live_gate == "blocked_human_only"
    and $s.routes_to_live == false
    and $s.places_real_order == false
    and $s.exchange_action_taken == false
' goal_state/PERMANENT_SYSTEM_RECOVERY/generation_acceptance_status.json
```

Requiring a current open position is intentional: the first resume action is
the restart-reconstruction capture, which cannot be proved after the position
has already closed. Once the predicate succeeds, freeze the admitted lineage
and accounting snapshot before restarting canonical serving and then the paper
loop.

## Post-boundary confirmation

Ongoing observation was kept separate from the frozen acceptance window. Cycles
51 through 60 added 169 candidates and again produced zero admissions, fills,
positions, or closes. Every candidate was rejected primarily as
`BLOCK_MICROSTRUCTURE_UNSAFE`; zero candidates had microstructure action
`ALLOW`, zero passed the advanced-indicator predicate, zero were otherwise
valid except for the model, and zero were otherwise valid except for
microstructure. Ten candidates satisfied the model-loss probation bound.

This confirms the same external market/evidence alignment blocker without
creating a governed basis for retraining or changing an admission threshold.

## Resumed observation through cycle 84

After the operator resumed the same acceptance directive, cycles 61 through 84
were frozen as a second independent confirmation slice. They added 3,431
canonical predictions, including 1,063 directional predictions, and evaluated
389 candidates. The interval produced zero admissions, fills, positions, or
natural closes.

Primary attribution for this slice was:

- `BLOCK_MICROSTRUCTURE_UNSAFE`: 360 (92.545%)
- `BLOCK_GUARDIAN_HALTED`: 25 (6.427%)
- `BLOCK_FVG_STRUCTURE_INVALID`: 4 (1.028%)

Twelve candidates satisfied the model-loss probation bound, 17 satisfied exit
feasibility, 26 passed the advanced-indicator predicate, and 4 had
microstructure action `ALLOW`. These predicates did not align on any candidate.
No candidate was otherwise valid except for the model, and no candidate was
otherwise valid except for microstructure. All 389 candidates carried the
generation-scoped cohort state permitting new entries. Evidence age was 21.070
to 187.902 seconds with a 91.537-second median, so this is not a systematic
stale-source condition.

The resumed evidence again selects remediation condition A:
`action=CONTINUE_OBSERVATION`. It does not authorize generation-4 retraining,
consumer-threshold changes, or weakening the historical global guardian.

## Active deadlock repair and immutable deployment

The later active-repair directive replaced passive observation. The frozen
decision contract and independent production/reference matrix are preserved in:

- `goal_state/PERMANENT_SYSTEM_RECOVERY/generation3_admission_contract_baseline.json`
- `goal_state/PERMANENT_SYSTEM_RECOVERY/generation3_admission_deadlock_report.json`
- `.local_data/permanent_system_recovery/generation3_admission_deadlock_matrix_v1.jsonl`

No threshold, strategy parameter, model generation, checkpoint, cohort, live
authority, or immutable historical outcome was changed.

Three deterministic paper-admission defects were repaired in sequence:

1. Commit `5354ef10c3547fcb74c65d4eefd05294f3c47d0c` made preliminary allocation
   replay use non-recursive point-in-time inputs and retain exact canonical risk
   authority.
2. Commit `91a659ff594af34591c9f0624c8d22cb7e1c1171` rebuilt a candidate reservation
   snapshot from frozen resources when the candidate's governed dynamic
   envelope legitimately differed from the preliminary envelope. It did not
   copy limits across envelopes or turn a blocked receipt into a pass.
3. Commit `556bdb9fc65a7f6e9919e0772de9bb31ae8755b5` removed two duplicated authority
   applications. The strict A+ confidence floor no longer preempts an otherwise
   fill-ready paper risk-controller exploration candidate that already passes
   its unchanged dynamic confidence floor. Final admission now honors the
   preemptive controller's explicit `adaptive_loss_probability_threshold_applied=false`
   only for the exact cohort-scoped, paper-only exploration decision, while the
   unchanged `<0.72` exploration loss bound remains mandatory. Missing risk,
   malformed adaptive authority, live-route flags, any other P0 entry reason,
   or loss probability at/above `0.72` still blocks.

The paper loop alone was deployed immutably at
`556bdb9fc65a7f6e9919e0772de9bb31ae8755b5`. The pre-deployment book was empty;
systemd verification emitted no diagnostics; the service is active with
`NRestarts=0`. Canonical serving and the observer were not restarted.

## Post-repair ten-cycle proof

Cycles 263 through 272 form the required first ten completed paper cycles after
the immutable deployment. They ran from 2026-07-27 04:36:04.776 UTC through
04:50:09.903 UTC.

| Predicate | Actual |
|---|---:|
| completed cycles | 10 |
| canonical predictions | 1,317 |
| directional predictions | 540 |
| candidates evaluated | 195 |
| preemptive exploration authorizations | 9 |
| paper intents | 195 |
| persisted paper fills | 0 |
| open positions | 0 |
| natural closes | 0 |
| generic microstructure blocks | 0 |
| cycles with exact predicate details | 10/10 |
| duplicate fills | 0 |
| duplicate closes | 0 |
| reservation leaks | 0 |
| routes to live | false |
| places real order | false |

The key runtime proof is OPUSDT 1h prediction
`v2h_6e3ae77ba27f2ba70fa2ff376c1e3c53`: it passed canonical risk and
orchestrator, passed the unchanged exploration dynamic confidence policy, and
naturally classified as `PAPER_RISK_CONTROLLER_EXPLORATION`. This proves the
duplicate strict-confidence deadlock is removed. Its normal adaptive notional
was `$69.52135`; the unchanged exploration factor was `0.03177578`, so the
reduced target was below the venue minimum. The allocator correctly returned
`BLOCK_EXCHANGE_MIN_ORDER` instead of rounding upward beyond the frozen risk
budget. Other inspected authorizations retained independent outcome-memory,
risk-record, or exposure-budget failures.

The status artifact's cumulative `classification=NATURAL_ADMISSION_OBSERVED`
means a preemptive exploration authorization exists; it is not accepted as a
natural lifecycle trigger. The fail-closed resume predicate above still exits
nonzero because `paper_fills_created=0` and `generation_open_positions=0`.
Therefore the single-run restart lock was not acquired and restart
reconstruction was not attempted.

Current truthful state remains:

```text
ENGINEERING_RECOVERY_COMPLETE=false
RUNTIME_ACCEPTANCE_PENDING=true
ECONOMIC_ACCEPTANCE_PENDING=true
V2_PERMANENT_RECOVERY_COMPLETE=false
LIVE_NO_GO=true
```

The exact deterministic defect is fixed, immutably deployed, and observed for
the required ten cycles. Leave the governed paper stack running unchanged. At
the first persisted natural fill with an open generation-3 position, use the
fresh generation-bound predicate above, acquire the single-run lock, freeze the
observer's restart capture, and immediately perform canonical-serving followed
by paper-loop restart reconstruction before ordinary close.

## Active-repair verification

```text
targeted paper-loop repair tests: 5 passed
preemptive edge-control suite: 88 passed
full paper-loop module: 552 passed, 13 failed, 31 errors
recorded unmodified baseline: 547 passed, 13 failed, 31 errors
G12 rare-event suite: 17 PASS, 0 WARNING, 0 FAIL
focused Ruff (E902/F821/F822/F823): PASS
Python compilation: PASS
git diff --check: PASS
systemd-analyze --user verify: diagnostics=0
```

The unchanged 13 failures and 31 setup errors are the pre-existing legacy
cycle-reservation/final-admission fixture family. The five additional passing
tests cover the two allocation replay repairs and the exploration authority
repair. An unrestricted Ruff run still reports 42 pre-existing findings in the
51,000-line paper loop and its legacy test module; the focused undefined-name,
syntax, and import-resolution selection is clean. Those unrelated lint findings
were not rewritten during this scoped runtime repair.

Command families used for this active repair, all from the repository root:

```text
git status --short --branch
git log -3 --oneline
git diff --check
git diff -- <changed-files>
git add <scoped-files>
git commit -m <scoped-message>
git rev-parse HEAD
git worktree add --detach <immutable-release-path> <commit-sha>
git -C <immutable-release-path> diff --quiet --exit-code <commit-sha> --
rg -n <admission-and-exploration-patterns> v2/backend scripts goal_state claude_worklog
sed -n <ranges> <paper-loop/policy/test/status/directive-files>
jq <scoped-projections> goal_state/PERMANENT_SYSTEM_RECOVERY/*.json
tail -n 10 .local_data/permanent_system_recovery/generation_acceptance_cycles_v1.jsonl | jq -s <post-deploy-summary>
redis-cli --raw GET <paper-status/intents/fills/positions/closes/restart-keys> | jq <scoped-projection>
.venv/bin/python -m py_compile <changed-python-files>
.venv/bin/pytest -q <targeted-paper-loop-selection>
.venv/bin/pytest -q v2/backend/tests/unit/services/preemptive_edge_control
.venv/bin/pytest -q --tb=no v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py
.venv/bin/python scripts/guardian_phase10_rare_event_tests.py
.venv/bin/ruff check --select E902,F821,F822,F823 <changed-python-files>
.venv/bin/ruff check --ignore E501,UP017,UP038 <changed-python-files>
systemctl --user cat/show/list-units/list-unit-files/daemon-reload/restart <scoped-units>
systemd-analyze --user verify ai-bot-v2-stack.target default.target timers.target ai-bot-v2-trade-management-paper-loop.service
journalctl --user -u ai-bot-v2-trade-management-paper-loop.service <scoped-window>
```

The post-deployment monitor polled the fresh generation-bound `jq -e` predicate
at three-second intervals from cycle 263 through cycle 272. It was configured to
acquire `/run/user/1000/ai-bot-v2-generation3-restart-acceptance.lock` only after
the persisted-fill and open-position conditions succeeded. They did not, so the
lock file was not created.
