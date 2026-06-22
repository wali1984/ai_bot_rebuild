# V2 Model Path Decision and Native Edge-Proof Gate

GO/NO-GO: `V2_MODEL_PATH_DECISION_NATIVE_EDGE_PROOF_RECOMMENDED`

The recommendation is **V2-native compact-to-expanded model** as the
primary path. **Legacy parity** is preserved as a secondary path for
operator-approved comparator work only. **Live trading remains
blocked. Legacy shutdown remains blocked.** Capital recovery requires
proof of edge before any size increase.

## 1. Current V2 observation state

Source artifacts (read-only):

- [v2_full_observation_remaining_dim_execution_queue/latest/remaining_dim_execution_queue.json](../../v2_full_observation_remaining_dim_execution_queue/latest/remaining_dim_execution_queue.json)
- [v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json](../../../../../v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json)

Per-symbol generated dims (out of 1911 target):

| Symbol | Generated | Missing | Status |
|---|---:|---:|---|
| BTCUSDT | 224 | 1687 | FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS |
| ETHUSDT | 224 | 1687 | FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS |
| SOLUSDT | 224 | 1687 | FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS |

Aggregate (3 symbols × 1911 = 5733) breakdown of the 5061 missing
dims:

| Category | Dims | Share | Reachability |
|---|---:|---:|---|
| `LEGACY_V3_EXTRA_NO_V2_SOURCE` | 3879 | 76.6% | **NOT reachable through V2 lanes** — legacy V3 trailing dims with no V2-native source by classification |
| `NOT_REQUIRED_FOR_CURRENT_V2_MODEL_PATH` | 915 | 18.1% | Reserved-bucket slots out of scope for current V2 model |
| `V2_POSITION_DEPENDENT_OPEN_POSITION_REQUIRED` | 60 | 1.19% | Sources automatically when a paper position opens |
| `EXTERNAL_SOURCE_REQUIRED_TOKEN_METRICS` | 54 | 1.07% | Operator decision on paid feed |
| `EXTERNAL_SOURCE_REQUIRED_ONCHAIN_BTC` | 45 | 0.89% | Operator decision on external feed |
| `EXTERNAL_SOURCE_REQUIRED_ONCHAIN_ETH` | 45 | 0.89% | Operator decision on external feed |
| `OPERATOR_DECISION_REQUIRED_CCXT_OHLCV` | 30 | 0.59% | Operator decision on secondary exchange OHLCV |
| `V2_LANE_EXISTS_PAYLOAD_ABSENT` | 21 | 0.41% | Lane exists; publisher must republish |
| `V2_EVENT_DEPENDENT_LIQUIDATION_WSS` | 12 | 0.24% | Event-dependent (V2 WSS publisher emission) |
| `V2_BUILDABLE_NOW` | 0 | 0.0% | Exhausted after exact-source risk-decision burndown |

Verified queue invariants this cycle:

- `queue_go_no_go = V2_FULL_OBSERVATION_REMAINING_DIM_EXECUTION_QUEUE_REMEDIATED_READY`
- `aggregate_total_observed = 5733`
- `strict_source_contract_pass = True`
- `generic_source_hint_hits = 0`
- `checkpoint_compatibility_claimed = false`
- `policy_architecture_parity_claimed = false`

**Conclusion on 1911 parity:** 76.6% of current missing dims
(67.7% of the 5733 aggregate target) are
`LEGACY_V3_EXTRA_NO_V2_SOURCE` — legacy V3 trailing dims that have no
V2-native source by classification. Reaching 1911 parity would require
building parallel V2 publishers that recreate the legacy V3 schema
field-for-field, for fields whose predictive value is unknown. Adding
the operator/external/event/position categories, the
remaining-dim queue now has **no exact-source `V2_BUILDABLE_NOW` code
tasks left**. **1911 parity is not realistically reachable soon.**

## 2. Legacy-parity path (cost honesty)

Required remaining work to reach 1911 parity:

- **Observation builder:** stand up V2 publishers for ~1293
  legacy-V3-extra dims per symbol. Many of these are derived /
  aggregated fields with no clear semantic mapping in the V2 surface.
  Cost: multiple sprints, with most lanes blocked on either
  (a) an operator decision on external feeds (token metrics, onchain,
  CCXT OHLCV), or (b) construction of V2-owned publishers that mimic
  legacy V3 internals.
- **Policy architecture:** start the legacy policy architecture port
  to V2 (currently `policy_architecture_parity_claimed=false`,
  operator-gated). Cost: large; requires reverse-engineering the
  legacy policy head, action space, and reward shaping. **No
  autonomous progress is permitted before operator approval.**
- **Checkpoint / model artifact:** load and validate the legacy
  checkpoint blob into the V2 policy head with shape parity. Cost:
  bounded by operator approval (currently
  `checkpoint_compatibility_claimed=false`, blob deserialization
  forbidden without operator approval). The legacy checkpoint is also
  the artifact that may carry whatever edge the legacy model has —
  but the V2 rebuild's first-principles audit ([CLAUDE.md](../../../../../CLAUDE.md)) prohibits
  loading it without proof.

Estimated blockers (severity-ordered):

- `POLICY_ARCHITECTURE_GATE_REQUIRED` (operator approval)
- `CHECKPOINT_ARTIFACT_REQUIRED` (operator approval, blob safety)
- `EXTERNAL_SOURCE_REQUIRED_TOKEN_METRICS / ONCHAIN_BTC / ONCHAIN_ETH`
  (operator decisions per feed)
- `OPERATOR_DECISION_REQUIRED_CCXT_OHLCV` (operator decision)
- `V2_EVENT_DEPENDENT_LIQUIDATION_WSS` (publisher work; event-dependent)
- `V2_POSITION_DEPENDENT_OPEN_POSITION_REQUIRED` (only sources when a
  position is open; not a code task)

What cannot be automated:

- No autonomous policy architecture port (operator gate).
- No autonomous checkpoint blob deserialization (operator gate, safety
  rule).
- No autonomous external feed adoption (operator gates per feed).
- No autonomous Symbol Universe adoption.
- No live or canary trading.
- No legacy shutdown.

## 3. V2-native model path (recommended)

The recommended path trains a compact V2-native model on the surface
that V2 actually sources today, then expands its input set as
operator-approved lanes light up.

Inputs available today (per symbol):

- **Generated observation dims:** 224 per symbol — sourced
  exclusively from `v2:*` keys (no legacy current truth).
- **Risk decisions:** `v2:risk:decisions` (per-symbol gates — pre-trade
  / fee-gate / churn-blocked, plus rolling rates), with explicit
  per-state MISSING labels.
- **Orchestrator decisions:** `v2:orchestrator:decisions` (held by
  paper fill gate, bucket winners, deconflict).
- **Trainer heartbeat:** `v2:trainer:heartbeat` (predictions count,
  open-gate predictions, blocked predictions, age via finished_at /
  started_at).
- **Paper / shadow runtime:** `v2:paper:positions`,
  `v2:paper:ledger`, `v2:paper:intents`,
  `v2:paper:intents_held_by_paper_fill_gate`,
  `v2:paper:position_history:{symbol}`,
  `v2:paper:position_price_track:{symbol}`,
  `v2:paper:position_history:heartbeat`.
- **Prediction:** `v2:prediction:{symbol}:1m` (expected move, expected
  move after cost, calibrated confidence, paper-fill-gate block reasons).
- **Market:** `v2:market:prices:{symbol}`, `v2:market:funding:{symbol}`,
  `v2:market:open_interest:{symbol}`.
- **Features (technical):** `v2:features:latest:{symbol}:1m`.
- **Alt-data candidate publisher:** `v2:symbol_universe:altdata_candidates`
  (candidate-only; not used for live adoption).
- **Liquidation WSS heartbeat:** `v2:market:liquidations:heartbeat`
  (when emitting; field is event-dependent for per-symbol latest /
  aggregate).

Training and evaluation plan:

1. **Compact-to-expanded architecture:** start with a model that
   consumes only the V2 observation dims today (224 per symbol). The
   model head has slots reserved for the expanded
   feature set, so that when an operator-approved lane lights up
   (token metrics, onchain BTC/ETH, CCXT OHLCV, etc.), the model can
   be re-trained without an architectural rewrite.
2. **Targets (compounded objectives):**
   - **Edge-after-cost:** signed P&L per trade after fee + slippage
     model, in basis points. Optimization target: strictly positive
     expectation across rolling windows.
   - **Downside pre-cascade recall:** detect liquidation-class
     drawdowns before they become unrecoverable. Optimization target:
     high recall on `pre-cascade-shock` events, even at the cost of
     precision.
   - **Block-by-risk-gate compliance:** model output must never
     override the risk gateway. The training signal must penalize
     trades the risk gateway would have blocked.
3. **Evaluation in paper / shadow only:**
   - Minimum trade count before any edge claim (operator-set).
   - Bootstrap confidence intervals on after-cost expectancy.
   - Drawdown bound per rolling window (operator-set).
   - V2-vs-legacy comparator runs alongside, **for evidence only**;
     decision-match is reported but is not a gate.
4. **No live, no canary, no scaling** until the paper-edge gate emits
   `V2_NATIVE_PAPER_EDGE_CERTIFIED_PASS` with a separate Codex review.

Why this path:

- **Time-to-evidence is short.** The V2 observation surface is
  already wired, tested, and emitting honest source labels.
- **No checkpoint blob deserialization.** The new model is trained
  from scratch in the V2 environment, so the
  `checkpoint_compatibility_claimed=false` invariant stays true.
- **No policy architecture port required upfront.** A compact V2
  model can be designed for the current V2 action / observation
  surface. The legacy policy head is preserved for later comparison
  only.
- **Aligns with capital-protection-first doctrine.** The operator has
  lost capital. A measured, evidence-based small model that can be
  validated in paper is the cautious option compared with a
  multi-month parity port that still depends on operator approvals to
  proceed.
- **Operator gates remain explicit.** Training-spec and evaluator
  authoring can start without live/canary approval. Treating a
  paper-soak result as formal edge certification, approving any canary,
  or approving any live ramp remains operator-gated.

Limitations to acknowledge:

- The compact V2 model will not match the legacy model's decision
  surface initially. The V2-vs-legacy comparator's decision-match
  rate will be low at first. That is honest, not a failure.
- The compact model will not predict outcomes that depend on
  external feeds (token metrics, onchain) until those feeds are
  operator-approved.

## 4. Recovery safety

Absolute rules (carried over from
[capital_recovery_gate_model.json](../../v2_executive_command_center/latest/capital_recovery_gate_model.json)):

- No live recovery trading until paper edge is statistically positive
  after costs.
- No scaling of size until canary pass.
- No daily loss beyond operator-set cap.
- No weekly loss beyond operator-set cap.
- No trade if expected edge after cost is below operator-set threshold.
- No trade if calibrated confidence is missing.
- No trade if feature freshness is stale.
- No trade if the risk gateway blocks.
- No trade if `live_gate` is not approved (currently `blocked_human_only`).

Operator-required caps still pending decision before any live /
canary ramp:

- `max_daily_loss_pct`
- `max_weekly_loss_pct`
- `max_position_notional_pct`
- `max_consecutive_losses`
- `canary_order_size`
- `min_expected_edge_after_cost_bps`
- `min_confidence_calibrated`
- `max_feature_freshness_seconds`
- `max_concurrent_positions`
- `kill_switch_consecutive_losses_window_hours`

## 5. Recommendation

**Primary path: V2-native compact-to-expanded model.**

GO/NO-GO marker: `V2_MODEL_PATH_DECISION_NATIVE_EDGE_PROOF_RECOMMENDED`.

**Secondary path: legacy-parity comparator preservation only.**

The legacy parity work is preserved as a slow, operator-gated
comparator track. It does not block recovery progress and it does not
require autonomous code work for the legacy V3 trailing dims.

### Next automatable tasks

1. Author the V2-native compact-to-expanded training spec under
   `claude_worklog/final_readiness/v2_native_edge_proof/` (no
   checkpoint loading, no policy architecture port).
2. Wire a paper-soak evaluator that consumes
   `v2:paper:ledger` + `v2:paper:position_history:{symbol}` + risk /
   orchestrator decisions and emits the rolling after-cost expectancy
   plus drawdown bounds.
3. Route every training and evaluation artifact through Codex review
   on the existing self-healing controller + executive command center
   surface.
4. Continue the read-only V2-vs-legacy comparator — its decision-match
   rate is informational, not a gate.
5. Keep the executive command center, self-healing controller, report
   center, and remaining-dim queue current.

### Operator decisions required

1. Approve the V2-native edge-proof gate (paper-only soak; no canary
   yet).
2. Set the 10 numeric capital protection caps in
   [capital_recovery_gate_model.json](../../v2_executive_command_center/latest/capital_recovery_gate_model.json).
3. Decide whether to start the legacy policy architecture port in
   parallel (operator-gated, optional, not required for V2-native
   path).
4. Decide each external feed individually (token metrics, onchain
   BTC, onchain ETH, CCXT OHLCV, paid CoinAnk aggregator).
5. Approve the paper-edge certification threshold (minimum trade
   count, minimum after-cost expectancy, drawdown bounds).
6. Approve the V2-vs-legacy decision-match certification threshold —
   informational only, not a gate.

### What this decision does NOT approve

- No live trading.
- No canary trading.
- No legacy shutdown.
- No checkpoint blob loading.
- No policy architecture port start.
- No Symbol Universe adoption.
- No external feed adoption.
- No exchange order.
- No leverage / margin change.
- No old-Redis write.

## Safety scoreboard

- did_not_modify_legacy_bot
- did_not_stop_v2_runtime
- did_not_stop_continuous_remediation
- did_not_stop_codex_governors
- did_not_write_old_redis
- did_not_call_exchange
- did_not_create_approval_marker
- did_not_create_shutdown_acceptance_file
- did_not_deserialize_checkpoint_blobs
- did_not_start_policy_architecture
- did_not_claim_checkpoint_compatibility
- did_not_claim_policy_architecture_parity
- did_not_adopt_symbol_universe_automatically
- did_not_adopt_external_feeds_automatically
- live_gate = blocked_human_only
- live_symbols = []
- approves_live = false
- approves_canary = false
- approves_legacy_shutdown = false
- approves_redis_trim = false
