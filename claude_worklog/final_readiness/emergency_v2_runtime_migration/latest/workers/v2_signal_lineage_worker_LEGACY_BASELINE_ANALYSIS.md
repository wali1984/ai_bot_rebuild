# v2_signal_lineage_worker — Legacy Baseline Analysis

## Purpose

This file is the legacy-first baseline mandated by the
**LEGACY-FIRST MANDATE** for every V2 emergency-runtime-migration
worker. It documents *what the legacy bot already does today* for
signal generation, lineage reconstruction, and explainability so the
V2 worker can be reviewed as a behaviour-preserving lift, not a
greenfield reinvention. Each claim is backed by a `legacy_reference`
path + line range that can be re-verified with `grep` / `wc -l` /
direct read.

The V2 worker
(`v2/backend/app/cli/v2_signal_lineage_worker.py`) lifts the previously
in-process `paper_online_runtime.build_signal_lineage()` function into
a standalone CLI subscriber. The worker is a downstream reader: it
subscribes to the seven per-stage records the V2 paper runtime already
publishes, reassembles a unified `signal_lineage_record`, and exposes
an explainability block whose claims are always either evidence-cited
or explicitly labelled as missing-evidence.

## Legacy source paths

| Path | Role |
|---|---|
| `legacy_reference/rl/hybrid_trainer.py` (57,250 lines) | Legacy primary hybrid trainer; produces predictions and proposes signals. Publishes signal proposals onto the Redis pub-sub fabric for the trader to consume. |
| `legacy_reference/rl/orchestrator_worker.py` (10,523 lines) | Legacy orchestrator worker; consumes trainer proposals (`proposal["_stream_id"] = str(msg_id)` at line 2002) and emits orchestrator decisions referenced downstream as `stream_id` (e.g. line 10183 `f"plan_id={plan_id} stream_id={msg_id}"`). |
| `legacy_reference/rl/signal_state_manager.py` (554 lines) | Legacy signal state machine. Tracks `SignalState.IDLE/PENDING/EXECUTED` per symbol, `SignalRecord(signal_id, action_name, confidence, price_at_signal, position_snapshot, timestamp_ms, state)` (`record_signal_sent` at line 288, `mark_signal_executed` at line 329). Closest legacy analog to the V2 signal record. |
| `legacy_reference/trading/signal_router.py` (349 lines) | Legacy signal router. Trainer publishes to Redis stream `wma:signals:all` (line 8, 244), the router copies to `wma:signals:{ACCOUNT_ID}` (line 199, 206), and the trader consumes from the account stream. |
| `legacy_reference/monitor_trainer_signals.py` (1,058 lines) | Operator-facing signal stream monitor; the closest legacy analog to surfacing current lineage state. |
| `legacy_reference/scripts/trace_symbol_e2e.py` (170 lines) | Legacy end-to-end lineage *reconstruction* script — given a symbol, it walks Redis to stitch trainer → router → trader events back into a single chain. Closest legacy analog to the V2 `signal_lineage_record`. |
| `legacy_reference/scripts/signal_accuracy_v2.py` (382 lines) | Legacy signal accuracy auditor; walks trainer signal stream + paper trade log to compute per-signal accuracy. |
| `legacy_reference/scripts/signal_accuracy_48h.py` | 48-hour rolling variant of the same auditor. |
| `legacy_reference/scripts/why_hedged_timeline.py` | Lineage-aware "why did the bot hedge" timeline reconstruction; uses trainer/router/trader Redis streams to explain a hedge decision. |
| `legacy_reference/rl/microstructure_overlay.py`, `legacy_reference/rl/target_exposure_controller.py`, `legacy_reference/rl/dynamic_runner_hedge.py`, `legacy_reference/risk/auto_deleverager.py`, `legacy_reference/risk/hedge_cage_manager.py`, `legacy_reference/trading/adaptive_hedge_builder.py`, `legacy_reference/trading/lifecycle_controller.py` | Legacy decision overlays that consult intermediate signal/prediction/confidence fields. They confirm that *every* downstream legacy module relies on a per-stage view of lineage that legacy reconstructs ad-hoc from Redis streams. |

There was **no** single legacy module that wrote a unified, durable
`signal_lineage_record`. The chain was reconstructed post-hoc from
Redis streams (`wma:signals:all`, `wma:signals:{ACCOUNT_ID}`,
`wma:paper:trade_log`) by audit scripts such as `trace_symbol_e2e.py`
and `signal_accuracy_v2.py`. The V2 worker therefore *implements* the
durable, evidence-cited unified lineage record that legacy lacked, on
top of the per-stage records the V2 paper runtime already produces.

## legacy_functions_preserved

| Legacy function / responsibility | Legacy file | Preserved in V2 as |
|---|---|---|
| Trainer publishes signal proposal with `stream_id` | `legacy_reference/rl/hybrid_trainer.py` + `legacy_reference/rl/orchestrator_worker.py:2002` | `signal_publisher.build_signal_record(...)` returns a deterministic `signal_id` derived from `prediction_id`. |
| Orchestrator decision references the trainer-published `stream_id` | `legacy_reference/rl/orchestrator_worker.py:10183` | `current_signal_lineage.orchestrator_decision.signal_id` is captured as the V2 `orchestrator_decision` stage record. |
| Signal state machine (IDLE/PENDING/EXECUTED) per symbol | `legacy_reference/rl/signal_state_manager.py:288, 329` | The V2 lineage worker tracks chain state implicitly via per-stage presence + lineage ID consistency (`chain_complete`, `chain_consistent`, `chain_inconsistencies`). The IDLE/PENDING/EXECUTED tri-state is not re-implemented because the V2 paper runtime already emits each stage's terminal record; the lineage worker only re-assembles, never executes. |
| Trainer → router → account-stream → trader signal routing | `legacy_reference/trading/signal_router.py:8, 199, 206, 244` | Not re-implemented as Redis routing. In V2 the routing is replaced by file-based per-stage payloads written by the V2 paper runtime. Multi-account routing is out of scope for the lineage worker (the lineage worker is read-only). |
| Operator stream monitor view of signals | `legacy_reference/monitor_trainer_signals.py` | Public payload `stages.*` and `signal_lineage_record` expose the same operator-facing view via JSON instead of Redis tail commands. |
| Lineage reconstruction (trace_symbol_e2e.py) | `legacy_reference/scripts/trace_symbol_e2e.py` | `signal_lineage_record` produced on every run; `lineage_ids` cross-stage map; `chain_consistent` flag. |
| Per-signal accuracy auditing | `legacy_reference/scripts/signal_accuracy_v2.py`, `legacy_reference/scripts/signal_accuracy_48h.py` | Out of scope for this worker. The lineage worker is the *foundation* this auditor will read in V2; accuracy auditing remains a separate worker. |
| "Why hedged" timeline reconstruction | `legacy_reference/scripts/why_hedged_timeline.py` | Captured via per-stage `explanation` field plus `risk_gateway_decision.risk_reason_code` / `orchestrator_decision.decision_reason`. |
| Signal explainability (legacy: ad-hoc fields in trader logs) | `legacy_reference/rl/orchestrator_worker.py`, `legacy_reference/trading/trader.py` | Explicit `evidence_citations[]` per stage with `{field_name, source, value, present}`; missing-evidence collapses to `EVIDENCE_MISSING_LABEL` instead of being silently filled. |

## legacy_inputs

The legacy chain consumed:

1. Trainer hidden-state outputs (in-process, hybrid_trainer.py).
2. Feature freshness / market data from feature pipeline.
3. Redis pub/sub topics (`wma:signals:all` → router → `wma:signals:{ACCOUNT_ID}`).
4. Trader Redis-streams (`wma:paper:trade_log`, account streams).
5. Operator console queries (`monitor_trainer_signals.py`).

In V2 the equivalent input is the **public paper runtime bundle**
emitted by `v2/backend/app/cli/paper_online_runtime.py`, located at
`v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json`.
That bundle already contains every per-stage record. The lineage
worker takes:

1. `--source-file PATH` to a paper runtime bundle JSON, or
2. fallback to the public payload above.

No legacy Redis is read; no legacy module is imported; no exchange
client is instantiated.

## legacy_outputs

The legacy chain wrote:

1. Trainer signal stream: Redis `wma:signals:all`
   (`legacy_reference/trading/signal_router.py:244`).
2. Router account streams: Redis `wma:signals:{ACCOUNT_ID}`
   (`legacy_reference/trading/signal_router.py:199, 206`).
3. Trader paper log: Redis `wma:paper:trade_log`
   (audit-only reference; never re-used by V2).
4. Trader logs to disk under `legacy_reference/*.log`.
5. Telegram alerts via `legacy_reference/utils/telegram_alerts.py`.

V2 outputs:

1. `v2/frontend/public/operator_runtime/v2_signal_lineage_worker/latest/v2_signal_lineage_worker_status.json`
2. `v2/runtime/v2_signal_lineage_worker/latest/v2_signal_lineage_worker_status.json`
3. `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_signal_lineage_worker_status.json`
4. CLI exit code `0` on `chain_complete=true and fail_closed=false`,
   `2` on any fail-closed condition.

## legacy_redis_keys (audit-only references; never writers)

The legacy chain used the following Redis namespaces. The V2 worker
references them only in audit documentation and never reads or writes
them.

- `wma:signals:all` — trainer signal publish topic
- `wma:signals:{ACCOUNT_ID}` — router output streams
- `wma:paper:trade_log` — trader paper event stream
- `wma:risk_state` — risk evaluator state (read by audit scripts)
- `wma:signal:*` — pre-router signal namespace used by some legacy modules

## legacy_config_dependencies

| Key | Legacy file | V2 note |
|---|---|---|
| `SIGNAL_TTL_SECONDS` | `legacy_reference/config.py` | V2 lineage worker uses `stale_threshold_seconds=600` (configurable via CLI); equivalence verified against legacy default. |
| `ROUTE_ACCOUNTS` | `legacy_reference/trading/signal_router.py:13` | Not re-implemented; lineage worker is account-agnostic and never routes. |
| `paralysis detectors` | `legacy_reference/scripts/paralysis_detectors.py` | Not in scope; lineage worker only observes. |
| `BASE_NOTIONAL`, fee anchors | `legacy_reference/config.py`, `legacy_reference/trading/trader.py` | Not redefined here; surfaced via `paper_execution_result` stage citations only. |

## legacy_edge_cases

1. *Signal expired before execution*. Legacy: signal state machine
   transitions to `EXPIRED` (`signal_state_manager.py`). V2: the
   `paper_execution_result` stage is missing for that tick →
   `chain_complete=false`, `fail_closed=true`,
   `runtime_evidence_status=MISSING_CHAIN_RECORDS`.
2. *Trainer pause / no signal*. Legacy: `wma:signals:all` simply has
   no new entry. V2: the bundle's `trainer_prediction` block is
   present but `raw_output.side="hold"` → `signal_record.actionable=false,
   actionable_reason_code="non_directional_side"`. The chain is still
   complete; the worker does not fail-close on a hold signal.
3. *Stale feature snapshot*. Legacy: trainer skip / fail-open. V2: the
   `feature_snapshot.freshness_state` is cited; `signal_record.actionable=false,
   actionable_reason_code="non_actionable_market_freshness"` when the
   market feed is `STALE`/`MISSING`.
4. *Risk-gateway denied with missing required field*. Legacy: trader
   logs and skips. V2: `risk_gateway_decision` stage retains all
   present-field citations; the missing field collapses the stage
   `explanation` to `EVIDENCE_MISSING_LABEL`.
5. *Signal id collision*. Legacy: rare; signal state manager
   deduplicates per-symbol per cooldown. V2: `signal_id` is the
   deterministic SHA-256 prefix of `prediction_id|run_ts`; collisions
   require both inputs identical.
6. *Bundle clock skew*. Legacy: not detected. V2: `generated_at_ms`
   is preferred over ISO `generated_at`; if both are absent, age is
   `None` → fail-close `STALE_RUNTIME_EVIDENCE`.

## legacy_failure_modes

1. Trainer not running → no signal in `wma:signals:all`. V2:
   `MISSING_RUNTIME_EVIDENCE`.
2. Router not running → trader sees no signals. V2: chain incomplete
   at `paper_execution_result` if downstream paper worker did not
   record a fill.
3. Trader logs but does not publish → operator confusion. V2: paper
   ledger tail is empty → `MISSING_CHAIN_RECORDS:paper_execution_result`.
4. Redis stream truncated under load → audit scripts return partial
   chains. V2: the file-based bundle is atomic; partial bundles
   trigger `INVALID_PAYLOAD`.
5. Operator unable to attribute risk denial reason. V2: explicit
   `risk_gateway_decision.evidence_citations[].risk_reason_code`
   citation.

## legacy_tests_or_expected_behavior

Legacy did not ship pytest coverage for lineage reconstruction. The
closest legacy assurance was manual replay via
`legacy_reference/scripts/trace_symbol_e2e.py` and the periodic
`signal_accuracy_v2.py` audit. V2 adds explicit integration tests at
`v2/backend/tests/integration/cli/test_v2_signal_lineage_worker.py`
covering full-chain capture, explainability invariant, fail-closed on
missing/stale chain, no-placeholder remnants, symbol universe
contract, gate invariant, and exchange/Redis import hygiene.

## V2_mapping

| V2 component | Purpose |
|---|---|
| `v2/backend/app/cli/v2_signal_lineage_worker.py` | Standalone CLI subscriber + lineage assembler. |
| `v2/backend/app/services/signal_publisher.py` | Real signal publisher service (replaces 1-line scaffold). Produces the signal record consumed by the orchestrator stage. |
| `v2/backend/tests/integration/cli/test_v2_signal_lineage_worker.py` | Integration tests for the worker. |
| `v2/frontend/public/operator_runtime/v2_signal_lineage_worker/latest/v2_signal_lineage_worker_status.json` | Public operator payload. |
| `v2/runtime/v2_signal_lineage_worker/latest/v2_signal_lineage_worker_status.json` | Local runtime payload. |
| `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_signal_lineage_worker_status.json` | Final readiness payload. |

## intentional_changes

1. **Replaces ad-hoc lineage reconstruction with a durable unified
   record.** Legacy required `trace_symbol_e2e.py` to be re-run by an
   operator; V2 emits `signal_lineage_record` on every tick.
2. **Replaces silent inference with evidence citations.** Legacy
   trader/orchestrator logs occasionally inferred missing fields; V2
   collapses missing-field explanations to
   `EVIDENCE_MISSING_LABEL = "Evidence missing — cannot explain
   without guessing"`.
3. **Replaces Redis routing with file-based per-stage records.**
   Legacy used Redis pub/sub (`wma:signals:all` → account streams);
   V2 reads the V2 paper runtime bundle (file). This eliminates a
   live-Redis write surface from the audit path.
4. **Enforces fail-closed at the chain level.** Any missing/stale
   per-stage record fail-closes the worker (CLI exit code `2`).
5. **Wires the V2 signal publisher service**. `signal_publisher.py`
   is invoked on every chain-complete run; the worker fail-closes if
   the publisher module still ships scaffold remnants.

## removed_or_deprecated_behavior

| Removed | Reason |
|---|---|
| Redis publishing of signals (`wma:signals:all`) | V2 evidence-integrity rule prohibits legacy-Redis writes. |
| Account routing (`wma:signals:{ACCOUNT_ID}`) | The lineage worker is account-agnostic; multi-account routing is a separate, future V2 worker. |
| In-memory `signal_state_manager` cooldown deduplication | Cooldown is enforced upstream (orchestrator + risk gateway). The lineage worker only assembles records; it does not gate generation. |
| Telegram signal alerts | Not in scope for lineage assembly; reserved for the operator alerting worker. |

## Conclusion

The V2 worker preserves every observable legacy lineage field while
upgrading the legacy ad-hoc reconstruction to a durable, evidence-cited
unified record. Live trading remains `blocked_human_only`. The worker
contains no exchange-mutation method names, no Binance/ccxt/Redis
imports, no Redis writer calls, and the signal publisher module
contains no scaffold remnant.
