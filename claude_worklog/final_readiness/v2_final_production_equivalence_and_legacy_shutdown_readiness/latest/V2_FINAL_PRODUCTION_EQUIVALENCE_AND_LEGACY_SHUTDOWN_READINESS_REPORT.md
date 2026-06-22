# Final V2 Production-Equivalence and Legacy Shutdown Readiness Packet

GO/NO-GO: `V2_FINAL_PRODUCTION_EQUIVALENCE_AND_LEGACY_SHUTDOWN_READINESS_BLOCKED`

This is the current final-state packet after autonomous burndown. It does not
approve edge, canary, live trading, legacy shutdown, Redis trim, symbol
adoption, checkpoint promotion, or external-feed adoption.

## Bottom Line

- Non-operator P0 implementation blockers visible in the mission blocker
  inventory: `0`
- Production equivalence: `NOT_READY`
- Legacy shutdown: `NOT_READY`
- Live/canary: `NOT_READY`
- Paper edge: `NOT_PROVEN`
- Automation: workers remain active, but active leases are not counted as
  production readiness.

## What Was Burned Down

- War-room governor stale/blocker state was refreshed to READY.
- Runtime soak and production-equivalence governor was refreshed to READY.
- Replay bundles now carry explicit paper-fill gate lineage and altdata
  missing-source states instead of silently missing evidence.
- False-negative war-room causes no longer emit fake automatable work when
  missing data is explicitly `MISSING_SOURCE`.
- Full-observation status no longer presents event-dependent liquidation fields
  or math-undefined TA ratios as buildable implementation work.
- Report center and autonomous mission backlog now classify the remaining top
  blockers as non-automatable.

## Remaining Blockers

### 1. `full_observation_builder`

Classification: `OPERATOR_REQUIRED_EXTERNAL_EVENT_DEPENDENT`

Exact remaining requirements:

- `unified_feature_family.token_metrics` requires operator-approved external
  source adoption.
- `onchain_btc` requires operator-approved external source adoption.
- `onchain_eth` requires operator-approved external source adoption.
- `unified_feature_family.ccxt_ohlcv` requires an operator decision before it
  can be included.
- `liquidations` is event-dependent; current V2 WSS can publish the source, but
  absent per-symbol liquidation events must not be fabricated.
- `technical_analysis` has a conditional undefined field
  `macd_signal_strength` when the denominator is zero; this must not be
  zero-filled or invented.

Current payload says:

```text
state=FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS
next_required_family=null
no_buildable_internal_family_remaining=true
event_dependent_families=["liquidations"]
conditionally_undefined_families=["technical_analysis"]
operator_required=true
```

### 2. `checkpoint_promotion`

Classification: `OPERATOR_DECISION_REQUIRED`

Exact remaining requirement:

- Operator must provide or approve a checkpoint under the protected runtime
  policy before any checkpoint promotion or compatibility claim can be made.
- Claude/Codex must not deserialize, mutate, fabricate, or promote checkpoint
  blobs autonomously.

Current marker:

```text
V2_CHECKPOINT_PROMOTION_OPERATOR_REQUIRED
```

### 3. `paper_edge_not_proven`

Classification: `EVIDENCE_AND_OPERATOR_THRESHOLD_REQUIRED`

Exact remaining requirement:

- Paper/shadow evidence must show statistically defensible positive after-cost
  expectancy using operator-approved thresholds.
- One-off correct-no-trade outcomes or descriptor completions do not prove
  edge.
- No live/canary/shutdown decision can depend on unproven edge.

### 4. `legacy_shutdown`

Classification: `OPERATOR_ONLY`

Exact remaining requirements:

- `LEGACY_STILL_OWNS_PRODUCTION_RUNTIME`: operator must explicitly decide when
  legacy can stop.
- `LEGACY_PRODUCTION_REDIS_KEYS_STILL_ACTIVE`: operator must explicitly approve
  Redis trim before any legacy production keys are removed.

## Automation State

Persistent workers are active and continue to process residual descriptors:

```text
active_claude_workers=3
active_codex_workers=3
active_lane_count=6
```

This is execution capacity, not readiness proof. Current residual leases are
not treated as migration completion, paper-edge proof, checkpoint readiness, or
shutdown approval.

## Safety

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- Did not modify legacy.
- Did not stop legacy or V2 runtime.
- Did not write old Redis.
- Did not call exchange mutation.
- Did not create approval tokens.
- Did not fabricate missing observations, liquidation events, TA ratios, paper
  outcomes, edge, checkpoint parity, or policy parity.

## Verification

```text
python -m py_compile \
  v2/backend/app/services/rl_core/full_observation_builder.py \
  v2/backend/app/cli/v2_full_observation_builder_status.py

PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/integration/cli/test_v2_full_observation_builder_status.py \
  v2/backend/tests/integration/cli/test_v2_liquidation_observation_aggregator.py -q

PYTHONPATH=$PWD .venv/bin/python \
  -m v2.backend.app.cli.v2_full_observation_builder_status --once \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT

PYTHONPATH=$PWD .venv/bin/python \
  -m v2.backend.app.cli.v2_report_center_indexer --once --json

PYTHONPATH=$PWD/claude_worklog/tools .venv/bin/python \
  claude_worklog/tools/v2_autonomous_mission_backlog_autoseed.py --json
```

Results: py_compile passed, focused tests passed `19/19`, full-observation
payload refreshed, report center re-indexed, autonomous backlog reports
`automatable_blocker_count=0` and `operator_required_blocker_count=2`.
