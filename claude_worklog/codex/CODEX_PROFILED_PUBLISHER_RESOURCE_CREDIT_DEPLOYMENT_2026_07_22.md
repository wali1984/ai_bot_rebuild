# Profiled Publisher Resource-Credit Deployment — 2026-07-22

## Scope

This checkpoint covers only the profiled base-feature publisher's resource
scheduler and its immutable deployment. It does not grant trainer, prediction,
paper-trading, or live-trading authority.

## Defect and correction

The resource controller derived a sustainable five-minute write budget smaller
than one observed indivisible evidence unit. It therefore selected zero symbols
on every cycle even though absolute disk capacity remained positive. The fix
accrues a bounded byte credit across cycles, subtracts materialized bytes, and
caps the bucket at the larger of one observed evidence unit and one cycle's
sustainable budget. The existing 90-day horizon and filesystem reserve remain
unchanged.

Code commit: `df1b90113e0a3b006a83640b37643a439a5a4218`

Immutable release root:
`/home/wali/ai_bot_local_data/deployments/ai_bot_rebuild/df1b90113e0a3b006a83640b37643a439a5a4218`

## Verification counts

- Targeted resource/backpressure tests passed: 9
- Full profiled publisher tests passed: 54 of 54
- Ruff failures: 0
- Python compile failures: 0
- Live eligible symbols discovered: 75
- Live symbols selected after restart: 1 (`1000SHIBUSDT`)
- Live masked-cost observations materialized: 1
- Live materialization failures: 0
- Service restarts: 0
- State cycle count after acceptance cycle: 15
- Cumulative materialized observations: 4
- Cumulative materialized bytes: 43,573,288

## Live acceptance evidence

The service restarted at `2026-07-22T05:53:56Z` and completed the acceptance
cycle at `2026-07-22T05:54:32.593216Z` with classification
`CYCLE_COMPLETE_MASKED_COST_OBSERVATIONS`. The running process exported the
exact release SHA in `AI_BOT_CODE_SHA`, and its `PYTHONPATH`, working directory,
and bytecode cache all resolve to the immutable release.

The resource decision reported:

- safe disk headroom: 237,807,012,249 bytes
- immutable reserve: 393,347,335,783 bytes
- one-unit write-credit capacity: 11,348,664 bytes
- available write credit: 11,348,664 bytes
- sustainable per-cycle budget: 9,174,653 bytes
- absolute capacity: 20,954 evidence units
- selected count: 1

The old `RESOURCE_HEADROOM_HOLD` is therefore resolved. Cost fields remain
truthfully masked because no authenticated commission evidence was available
to this credentialless publisher during the acceptance cycle. Those masked
parents are not trainer-admissible and are not retroactively relabelled.

## Remaining gate

The next independent gate is the read-only Binance USD-M commission evidence
broker and its credentialless publisher reader. A strict 39-field child may be
created only for a new decision after authenticated fee evidence satisfies
`available_at <= decision_time < expires_at`.
