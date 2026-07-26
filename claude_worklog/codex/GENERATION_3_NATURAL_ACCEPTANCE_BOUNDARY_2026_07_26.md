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
resume lifecycle/restart acceptance only after a natural governed admission is
observed. A new model generation is not authorized by this evidence.

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
