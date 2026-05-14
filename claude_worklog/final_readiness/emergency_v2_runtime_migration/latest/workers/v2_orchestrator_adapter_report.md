# v2_orchestrator_adapter — Worker Report

## Status

- **Worker ID:** `v2_orchestrator_adapter`
- **Live gate:** `blocked_human_only`
- **Exchange action taken:** `false`
- **Exchange call invariant:** `NO_REAL_EXCHANGE_CALL_FROM_ORCHESTRATOR_ADAPTER`
- **Orchestrator overrides risk gateway:** `false`
- **Cannot bypass risk gateway:** `true`
- **Risk gateway binding:** `true`
- **Codex review trigger:** `codex_review_v2_orchestrator_adapter`
- **Initial payload state:** `fail_closed=true` with
  `runtime_evidence_status=MISSING_RUNTIME_EVIDENCE` (no source bundle
  has been emitted under the test path yet). First production run
  reads the paper-online bundle and flips this to `PRESENT`.

## What was emitted

| Path | Purpose |
|---|---|
| `v2/backend/app/cli/v2_orchestrator_adapter.py` | Standalone CLI worker that lifts `v2/backend/app/composition/orchestrator_decision/runtime.py` into a downstream subscriber. Consumes `trainer_prediction` records, emits `OrchestratorDecisionRecord` instances. |
| `v2/backend/tests/integration/cli/test_v2_orchestrator_adapter.py` | Integration tests covering happy-path, all abstain branches, the orchestrator-never-overrides-risk-gateway invariant, fail-closed paths, Symbol Universe contract, gate invariant, no exchange/Redis surface, and required payload fields. |
| `v2/frontend/public/operator_runtime/v2_orchestrator_adapter/latest/v2_orchestrator_adapter_status.json` | Initial public operator payload (pre-first-emit). |
| `claude_worklog/.../workers/v2_orchestrator_adapter_status.json` | Final-readiness mirror of the public payload. |
| `claude_worklog/.../workers/v2_orchestrator_adapter_LEGACY_BASELINE_ANALYSIS.md` | LEGACY-FIRST baseline analysis (mandated). |
| `claude_worklog/.../workers/v2_orchestrator_adapter_legacy_behavior_mapping.json` | Structured legacy → V2 mapping (mandated). |
| `claude_worklog/.../workers/v2_orchestrator_adapter_report.md` | This file. |

## Critical invariant: orchestrator never overrides the risk gateway

The adapter delegates to the existing
`v2/backend/app/services/orchestrator_decision/service.py` policy.
The set of decision actions is closed at the domain layer
(`v2/backend/app/domain/orchestrator_decision/record.py` —
`{open_long, open_short, hold, abstain}`). The adapter cannot
synthesize an `execute` or `force_open` action even by accident:
attempting to do so raises `OrchestratorDecisionDomainError`.

The public payload exposes three explicit invariant flags so Codex
can re-verify the constraint at review time:

- `orchestrator_overrides_risk: false`
- `cannot_bypass_risk_gateway: true`
- `risk_gateway_binding: true`

The integration test
`test_orchestrator_never_overrides_risk_gateway_when_upstream_denies`
constructs a bundle in which the upstream `risk_decision.risk_action`
is `"deny"`, and asserts that:

1. the adapter still emits only an `open_long`/`open_short`/`hold`/
   `abstain` proposal, never an execute;
2. all three invariant flags are surfaced on both the payload and the
   embedded `decision_record`;
3. `allowed_decision_actions` excludes every token that could imply a
   direct execution (`execute`, `force_open*`, `live_open`,
   `place_position`).

## Inputs consumed

1. `--source-file PATH` (explicit override)
2. `v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json` (primary)
3. `v2/frontend/public/operator_runtime/v2_trainer_bridge/latest/v2_trainer_bridge_status.json` (fallback)

No legacy Redis is read; no legacy module is imported; no exchange
client is instantiated.

## Outputs

- Public payload + local runtime payload + final-readiness mirror.
- CLI exit code `0` on `fail_closed=false`, `2` on any fail-closed
  condition.

## Symbol Universe contract

- `symbol_universe_contract = SYMBOL_UNIVERSE_CONTRACT_REQUIRED`
- `legacy_active_symbols` = the 25-symbol legacy active subset
  (`legacy_config.py SYMBOLS`) — **not** the universe.
- `dynamic_discovered_symbols` is the broader passive-discovery
  universe (Binance Futures, CoinAnk, CoinAPI, KuCoin, future
  ingestors).
- `training_symbols`, `paper_symbols`: evidence-selected subsets.
- `live_symbols = []`, `live_symbol_policy = none_live_blocked_human_only`.
- CoinAnk-only symbols remain market-intelligence candidates until
  Binance USD-M tradability is confirmed.
- `train_all_discovered_symbols = false`, `trade_all_discovered_symbols = false`,
  `passive_monitor_all_discovered_symbols = true`.

## Codex review trigger

Every emit sets `codex_review_trigger = "codex_review_v2_orchestrator_adapter"`
and `codex_review_emitted_at` to the run timestamp. The operator-facing
Codex Review Center can pick this up after every run.

## Safety posture

- Live trading remains `blocked_human_only` (unchanged).
- No exchange-mutation method names in the worker source.
- No Binance/ccxt/Redis imports or writer calls in the worker source.
- No mutation of the legacy bot, legacy Redis, or any `.env` file.
- The adapter never writes to legacy paths; all outputs are under
  `v2/` and `claude_worklog/`.

## Follow-ups

- Codex review of this worker via `codex_review_v2_orchestrator_adapter`
  on the next dispatch tick.
- Once Codex returns PASS, downstream V2 workers (`v2_risk_gateway_runtime_worker`,
  `v2_paper_execution_worker`, `v2_signal_lineage_worker`) can be
  re-validated against the new orchestrator decision record without
  schema drift.
End-of-turn summary: Emitted all 7 required files for `v2_orchestrator_adapter` — the LEGACY-FIRST baseline analysis + mapping JSON, the standalone CLI worker that lifts `composition/orchestrator_decision/runtime.py` and consumes `trainer_prediction` records to emit `OrchestratorDecisionRecord`, integration tests asserting the orchestrator-never-overrides-risk-gateway invariant (closed enum + explicit `cannot_bypass_risk_gateway`/`orchestrator_overrides_risk`/`risk_gateway_binding` flags), the initial public + worker status payloads with `codex_review_v2_orchestrator_adapter` trigger, and the worker report. Live remains `blocked_human_only`; no exchange/Redis writers; Symbol Universe contract surfaced with legacy-25 vs. dynamic-discovered distinction preserved.
