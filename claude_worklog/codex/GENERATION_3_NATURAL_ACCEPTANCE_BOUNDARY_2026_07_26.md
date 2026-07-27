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
