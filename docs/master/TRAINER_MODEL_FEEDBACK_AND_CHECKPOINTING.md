# Trainer Model Feedback And Checkpointing

Last verified timestamp: 2026-07-23T03:25:14Z for the local profiled candidate lane; legacy feedback sections retain their dated evidence

## Purpose
Explain trainer feedback ingestion, trusted replay rows, checkpoint evidence, online learning state, and how paper outcomes become safe trainer evidence.

## Source Files
- `v2/backend/app/main.py`
- `v2/backend/app/api/v1/paper.py`
- `v2/backend/app/api/v1/derivatives.py`
- `v2/backend/app/api/v2/market_contracts.py`
- `v2/backend/app/api/v2/live_readiness.py`
- `v2/backend/app/api/v2/mobile.py`
- `v2/backend/app/cli/v2_trade_management_paper_loop.py`
- `v2/backend/app/cli/v2_runtime_drift_monitor.py`
- `v2/frontend/src/components/layout/RuntimeTruthStrip.tsx`
- `v2/mobile/Sources/AIBotV2/Views/Components/RuntimeTruthCard.swift`

## Runtime Redis Keys/API Routes
- Redis: v2:paper:performance_governor_status
- Redis: v2:paper:new_entry_emergency_halt_status
- Redis: v2:trainer:hybrid_cuda:status
- Redis: v2:monitor:runtime_drift
- Redis: v2:altdata:santiment:symbol:*
- API: /api/v2/paper/runtime-status
- API: /api/v2/live-readiness
- API: /api/v2/mobile/paper-summary
- Artifact: v2/frontend/public/operator_runtime/v2_runtime_drift/latest/status.json

## Operator/Trader/Developer Meaning
- Operator: use this document to decide whether the current runtime is safe, current, and fail-closed.
- Trader: use this document to interpret paper performance, A+ readiness, REDUCE_SIZE bootstrap rows, live gate state, and why trades are blocked.
- Developer: use this document to find the source files, route contracts, Redis keys, tests, and evidence artifacts that must stay in sync.
- Primary audience for this page: operator, trader, and developer.

## 2026-07-22/23 local profiled candidate lane

The currently commissioned trainer path is a locally authenticated,
non-promotable research publisher. Feature producer and trainer consumer are
pinned to the same detached, read-only source release
`974caa6c263eeadf09fad5028d0883d304a14075`. It is intentionally separate from
the independently witnessed promotion path and from all serving/trading paths.

### Exact data flow and clocks

```text
finalized canonical 5m + 1h OHLCV
  -> atomic source captures and immutable CAS
  -> verified source-provenance shard append/readback
  -> profiled parent feature record
  -> authenticated cost-enrichment child
  -> durable feature-snapshot ledger
  -> fixed publisher cycle status SHA/completion time
  -> profiled observation manifest at that exact observation time
  -> finalized 5m label lookup bounded by manifest observation high water
  -> causal train/validation/PIT-purge partition
  -> CUDA optimizer
  -> local candidate JSON + NPZ weight artifact
```

The ordering contract distinguishes `event_time`, `ingested_at`,
`available_at`, `generated_at`, `feature_cutoff`, `decision_time` and any later
execution time. Finalized candle close and every contributing availability must
be no later than the feature decision. The publisher assigns no execution
time. The trainer fixes the publisher cycle's `cycle_completed_at` as its
manifest observation boundary; later rows cannot be smuggled into that run.

The label archive is append-only, so its physical tail can legitimately grow
while a manifest is being built. Reusing a whole-archive proof for a bounded
row after such an append incorrectly treated safe suffix growth as corruption.
The repaired builder now:

1. fixes the exact observation-time label high water;
2. verifies full archive integrity before the build;
3. opens each bounded range in one read transaction;
4. independently checks SQLite quick integrity, schema/retention identity,
   canonical payloads, row hash chain, append receipts and post-commit
   receipts for that range;
5. rejects any movement of the fixed observation high water or mutation of a
   bounded prefix; and
6. verifies full archive integrity again after the build.

An append strictly after the observation high water is therefore tolerated.
A label unavailable at the observation time is counted and excluded; it is
not NaN-filled, guessed, shifted to a later target or allowed to kill the whole
trainer. This is adaptive use of available clean data, not relaxed PIT safety.

### Current candidate evidence

The first end-to-end candidate on the joint release completed at
`2026-07-23T03:25:14.063038Z`:

- candidate generation: 15;
- candidate ID:
  `v2_hybrid_ckpt_17cbe15f_90658e05e7debce4_5512088ec352`;
- base generation/ID: 14 / `v2_hybrid_ckpt_17cbe15f_09c6fe71fb50c903_87ece1a87ce0`;
- source manifest:
  `b919c4282b32ce4d382499b1f35bf40bc05d1cab69a6cefd361b44ee924d833d`;
- publisher status SHA:
  `ef498003ef2747a624d5f635bee7a98e1ca50af66711652f461c8eaf1a810e3d`;
- 23 total profiled samples = 22 admitted + one unavailable label;
- 22 admitted = 18 optimizer rows + four validation rows + zero PIT-purged
  rows;
- complete corpus reopened after optimizer: true;
- full entry inventory and manifest authentication verified: true;
- CUDA active on `cuda:0`, model input dimension 1,784;
- weight file size: 29,815,274 bytes; and
- independently recomputed weight SHA-256:
  `c07a0daba71d43287372b3643f49eb00748f95074c59aba27ffc4d36908a4755`.

Zero PIT-purged rows in this particular partition means no admitted training
row overlapped the validation embargo boundary; it is not a disabled purge.
Earlier 18-row evidence produced 14 training, three validation and one purged
row, proving that the purge activates when the observed clocks require it.

### Authority and change impact

The candidate directory is limited to
`.local_models/v2_native_rl_masa_ppo/local_profiled_research_candidates`.
Checkpoint evidence declares `local_research_non_promotable=true`. Deployment,
serving activation/promotion, prediction, paper trading, live execution, order
submission, exchange access, execution and runtime wiring are all false. The
trainer has no network or exchange credential authority.

Changes to any of the following require producer/consumer contract tests and a
new immutable joint deployment: publisher status fields/hash, source shard
preflight, feature ledger schema, cost CAS root, observation high-water rules,
label row/receipt chain, manifest entry identity, split/purge semantics, model
input ABI, optimizer input serialization, checkpoint evidence or candidate
write scope. A new local checkpoint alone must never activate prediction or
trading.

Scoped verification counts for this commissioning slice were 73 publisher
cases, 35 strict cycle-reader cases, 24 observation-manifest cases and 15 local
research service cases. All passed; Ruff and diff whitespace checks were clean.

## Failure Modes
- Stale runtime payload labelled as current.
- `new_entries_allowed=true` while PF is below 1 or expectancy is non-positive.
- A+ shown when final A+ rows are zero, or REDUCE_SIZE rows shown as final A+.
- Live readiness shown without signed-read and pre-submit dry-run proof.
- Santiment or another paid data source expected for symbol selection but unused.
- Feature freshness or lineage missing around `available_at`, `feature_cutoff`, `decision_time`, or `execution_time`.

## Debug Commands
- `systemctl --user list-units --type=service --all | rg "ai-bot-v2|paper|trainer"`
- `redis-cli GET v2:paper:performance_governor_status | python3 -m json.tool`
- `redis-cli GET v2:paper:new_entry_emergency_halt_status | python3 -m json.tool`
- `redis-cli GET v2:monitor:runtime_drift | python3 -m json.tool`
- `redis-cli --scan --pattern "v2:altdata:santiment:symbol:*" | wc -l`

## Validation Commands
- `python -m py_compile v2/backend/app/cli/v2_runtime_drift_monitor.py`
- `.venv/bin/pytest -q v2/backend/tests/unit/cli/test_v2_runtime_drift_monitor.py`
- `npm --prefix v2/frontend run typecheck`
- `npm --prefix v2/frontend run build`
- `swift test --package-path v2/mobile`

## Evidence Artifacts
- `goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/PHASE_H_BACKEND_API_CONTRACT_STATUS.json`
- `goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/PHASE_I_FRONTEND_ROUTE_TRUTH_STATUS.json`
- `goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/PHASE_J_IOS_RUNTIME_TRUTH_STATUS.json`
- `goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/PHASE_K_RUNTIME_ALERT_MATRIX.json`
- `goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/RUNTIME_SNAPSHOTS/PHASE_K_RUNTIME_DRIFT_STATUS.json`

## Current Runtime Truth
- Paper state: `HALTED_PERFORMANCE`, PF about `0.4613`, expectancy about `-5.2575 bps`, and `new_entries_allowed=false`.
- Trainer state: `WEIGHTS_UPDATING` with feedback rows present.
- Live state: `blocked_human_only`; dry-run packets must not submit or mutate exchange state.
- Runtime drift: Phase K monitor reports `services_stale=0` after V2 restarts and the legacy comparator stop.
- Santiment: `v2:altdata:santiment:symbol:*` has runtime symbol-selection evidence and the paid-ingestor-unused alert is passing.
