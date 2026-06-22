# V2 Real-Exchange Read-Only Shadow + Paper Blocker Diagnosis

Generated: 2026-05-25T20:30:00Z
Git HEAD: 10513bbe0517fd81c9c87e4672bb15486a083c02
Lane: `v2_real_exchange_read_only_shadow_and_paper_blocker_diagnosis`
GO/NO-GO: `V2_REAL_EXCHANGE_READ_ONLY_SHADOW_AND_PAPER_BLOCKER_DIAGNOSIS_READY`
Upstream Codex gate: `V2_FASTEST_SAFE_CANARY_READINESS_EXECUTION_CODEX_PASS`

This packet stages V2 to observe the real exchange in a strictly read-only
shadow mode while every mutation path stays disabled, and diagnoses why
paper edge is currently negative.

## Plain English

- **TokenMetrics remains deferred and is not a blocker.**
- **Live order execution is blocked.** Every mutation endpoint is disabled
  and a read-only adapter throws on any mutation method.
- **Real-exchange read-only shadow path is contract-defined.** Activation
  requires a separate operator-signed read-only permission probe approval.
- **Why paper is negative:** after-cost expectancy is -8.98 bps with CI
  lower -13.09 bps. Diagnosis is observed in 13 categories — trainer
  wrapper bridge/contract path (24 events), v2 native baseline not yet
  profitable, paper-fill gate block, fee/slippage drag (7 bps total),
  risk gate block, checkpoint missing, insufficient labeled evidence
  (4336/4453), false-negative rate 0.198, no labeled positives, partial
  feature families, and small symbol universe.
- **Next operator decision:** sign a separate read-only permission probe
  approval to enable read-only shadow (no orders), OR progress paper-edge
  thresholds, risk caps, or checkpoint promotion.
- **Next automatic action:** closed-loop Spark continues replay-miner
  cycles, report-center indexer, comparator refresh, dry-run canary,
  full-observation internal-family burndown. No TokenMetrics work is
  auto-seeded.

`live_gate=blocked_human_only`. `live_symbols=[]`.

## Phase 1 — Live-Shadow Safety Contract

All order, test-order, cancel, modify, batch, leverage, margin,
position-side, transfer, withdraw, and deposit endpoints are disabled.
14 forbidden endpoints enumerated. Read-only adapter required;
`must_throw_on_mutation=true`; 12 mutation method names listed for
the adapter to refuse.

## Phase 2 — Read-Only Exchange Probe Plan

Plan only. Operator approval required before execution. Credentials
checked by env-var NAME only (`BINANCE_API_KEY`, `BINANCE_API_SECRET`);
values never read, never exposed, never persisted; container path not
exposed in payload. 8 allowed read-only GET endpoints listed; 14 forbidden
mutation endpoints listed. Dry-execution guard active.

## Phase 3 — V2 Live-Shadow Status

`shadow_mode=READ_ONLY_NO_ORDERS`, `shadow_mode_active=false`. Adapter
contract `ReadOnlyExchangeAdapter` defined with 12 mutation methods that
must throw and 8 allowed read methods. V2 namespaces declared but no
writes occur until operator signs the probe approval. The loop would emit
8 telemetry fields (server time, exchange-info symbol count, capability
flags, range-bucketed balance, position count, open-order count, trades
last 24h count, income last 24h count) — all currently null because the
loop is not active.

## Phase 4 — Paper-Trading Blocker Diagnosis (13 categories)

| # | Category | Observed |
| - | --- | --- |
| 1 | TRAINER_WRAPPER_LIMITATION | true (24 bridge/contract predictions) |
| 2 | CONTRACT_ONLY_PREDICTION | true (24 events) |
| 3 | BASELINE_MODEL_NOT_PROFITABLE | true (after-cost -8.98 bps) |
| 4 | PAPER_FILL_GATE_BLOCK | true (1 event) |
| 5 | EXPECTED_EDGE_AFTER_COST_NEGATIVE | true (-8.98 bps) |
| 6 | RISK_GATE_BLOCK | true (24 events `live_gate_blocked_human_only`) |
| 7 | FEATURE_STALE_OR_MISSING | partial (3 partial families + 1 event-dependent) |
| 8 | CHECKPOINT_MISSING | true (`.local_models/` ABSENT; 24 hold-on-checkpoint events) |
| 9 | INSUFFICIENT_EVIDENCE | true (4336 of 4453 sample) |
| 10 | FALSE_NEGATIVE | true (rate 0.198; 21 events) |
| 11 | FALSE_POSITIVE | insufficient labeled positives (rate null) |
| 12 | FEE_SLIPPAGE_DRAG | true (5 bps fee + 2 bps slippage = 7 bps) |
| 13 | SYMBOL_SELECTION_WEAKNESS | partial (only BTCUSDT, ETHUSDT, SOLUSDT) |

Primary diagnosis: paper edge is negative because of mixed trainer path
(bridge/contract still contaminating aggregate), fee/slippage drag,
insufficient labeled evidence, missing checkpoint promotion, and no
profitable native baseline yet under the current sample.

## Phase 5 — Trainer Wrapper Exit Diagnosis

Prediction source distribution out of 4453 events:
- bridge/contract predictions: 24
- v2_native_baseline_evaluator predictions: present but not claimed
  profitable in current sample
- checkpoint-promoted V2 native inference: 0
- insufficient_evidence: 4336

Three selected recommendations:
1. `DO_NOT_COPY_LEGACY_TRAINER_AS_PRODUCTION_NATIVE` — copying preserves
   negative-edge behavior and adds pickle/torch deserialization surface
   (operator-required).
2. `KEEP_AS_REFERENCE_OR_BRIDGE_ONLY` — `v2/legacy_owned_runtime/*`
   remains read-only reference; bridge predictions stay
   `contract_only_not_tradeable` for canary/live.
3. `CONTINUE_V2_NATIVE_BASELINE_AND_DATASET_PATH` — keep iterating the
   native baseline + dataset extension; operator-signed checkpoint
   promotion required before claiming native edge.

Combined primary: `DO_NOT_COPY_LEGACY_TRAINER_AS_PRODUCTION_NATIVE_AND_CONTINUE_V2_NATIVE_BASELINE_AND_DATASET_PATH`.

## Phase 6 — Fastest Safe Path Recommendation

Primary: `READ_ONLY_LIVE_SHADOW_OPERATOR_DECISION_REQUIRED`

Secondary: `BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN`,
`BLOCK_LIVE_RISK_CAPS_OPERATOR_REQUIRED`,
`BLOCK_LIVE_CHECKPOINT_MODEL_NOT_READY`

`canary_ready=false`, `live_ready=false`, `shutdown_safe=false`,
`read_only_live_shadow_ready_no_orders=false` (pending operator probe
approval). `CANARY_READY`, `LIVE_READY`, and `SAFE_TO_SHUTDOWN` emits
explicitly disallowed.

## Phase 7 — Report Center

`operator_dashboard_payload.json` consolidates all phase summaries with
plain-English explanation and outputs list. Report Center indexer ingests
this lane on next cycle.

## Required Safety Text

- This is live-shadow / read-only execution diagnostics.
- This is not live trading.
- This is not canary approval.
- This is not legacy shutdown.
- This is not Redis trim.

## Verification

```text
python3 -c "import json,glob; [json.load(open(p)) for p in glob.glob('claude_worklog/final_readiness/v2_real_exchange_read_only_shadow_and_paper_blocker_diagnosis/latest/*.json')]; print('OK')"

python3 -c "import pathlib; assert not any(pathlib.Path('claude_worklog/approvals').glob('*PERMISSION_PROBE*.md')); print('probe_approval_absent_as_expected')"
```
