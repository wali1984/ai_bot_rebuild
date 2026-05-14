# v2_risk_gateway_runtime_worker — worker report

## Status

**MIGRATED_AND_RUNNABLE** as of 2026-05-13. Standalone CLI worker shipped;
public payload seeded; 21 integration tests pass covering happy path,
low-confidence denial, stale-feature denial, fail-closed on missing fields,
gate-always-blocked invariant across every decision action, no-old-Redis
contract, no-exchange-mutation contract, symbol-universe contract,
audit-only kill-switch reference list, required-public-payload-fields
contract, and `MISSING_RUNTIME_EVIDENCE` classification when the legacy bot
is shut down.

## What this worker does

Standalone CLI worker that lifts the V2 risk gateway library
(`v2/backend/app/services/risk_gateway/service.py` +
`v2/backend/app/composition/risk_gateway/runtime.py`) out of any embedded
runtime and runs it as an independent process. It:

1. Consumes `OrchestratorDecisionRecord` events from a V2-namespaced source
   — `--decision-file PATH` or, as fallback, a V2 public payload under
   `v2/frontend/public/operator_runtime/orchestrator_decision/latest/`.
2. Emits `RiskDecisionRecord` via
   `build_risk_decision_evaluator(...)(decision=...)` and reports
   `risk_action` + `risk_reason_code` collapsed into the V2 set
   (`allow_proceed_long`, `allow_proceed_short`, `deny_orchestrator_held`,
   `deny_orchestrator_abstained`, `deny_default`).
3. Sets the **fail-closed gate** to `blocked_human_only` on every run —
   regardless of whether the underlying `risk_action` is `allow` or `deny`.
4. Writes the public payload to:
   - `v2/frontend/public/operator_runtime/v2_risk_gateway_runtime_worker/latest/v2_risk_gateway_runtime_worker_status.json`
   - `v2/runtime/v2_risk_gateway_runtime_worker/latest/v2_risk_gateway_runtime_worker_status.json`
   - `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_risk_gateway_runtime_worker_status.json`
5. On missing input (legacy bot shut down or no public payload yet) the
   worker classifies trainer-parity inputs as `MISSING_RUNTIME_EVIDENCE`,
   fail-closes (`risk_action=deny`, `risk_reason_code=deny_default`), and
   exits code 2 in single-shot mode. No data is synthesized. The public
   payload also labels this explicitly as
   `runtime_evidence_status = "MISSING_RUNTIME_EVIDENCE"`.

## Runnable commands

```text
python3 -m v2.backend.app.cli.v2_risk_gateway_runtime_worker --once --decision-file ./decision.json
python3 -m v2.backend.app.cli.v2_risk_gateway_runtime_worker --once
python3 -m v2.backend.app.cli.v2_risk_gateway_runtime_worker --loop --interval 30
```

Flags:
- `--decision-file PATH` — JSON containing one `OrchestratorDecisionRecord`
  (or a list under `decisions`).
- `--once` / `--loop` (default `--once`).
- `--interval N` (loop interval, default 30s).
- `--no-write` (dry run; useful for diagnostics).

## Public payload fields (required + present)

`worker_id`, `last_run_ts`, `last_decision_id`, `last_risk_decision_id`,
`last_risk_decision_ts`, `risk_action`, `risk_reason_code`,
`input_decision_action`, `input_decision_reason_code`, `symbol`, `live_gate`,
`current_gate_state`, `gate_always_blocked_invariant`, `fail_closed`,
`missing_runtime_evidence`, `runtime_evidence_status`,
`symbol_universe_contract`,
`symbol_universe_source_path`, `symbol_universe_public_payload_status`,
`legacy_active_symbols`, `dynamic_discovered_symbols`, `observed_symbols`,
`training_symbols`, `paper_symbols`, `live_symbols`, `live_blocked_symbols`,
`legacy_kill_switch_key_references`, `legacy_risk_gate_source_paths`,
`source_payload_path`. The `REQUIRED_PUBLIC_PAYLOAD_FIELDS` constant enumerates
the contract and is asserted by `test_required_public_payload_fields_present`.

## Risk-action / reason-code mapping

| orchestrator `decision_action` + `decision_reason_code` | `risk_action` | `risk_reason_code` |
|---|---|---|
| `open_long` + `proceed_long` | `allow` | `allow_proceed_long` |
| `open_short` + `proceed_short` | `allow` | `allow_proceed_short` |
| `hold` + `hold_flat_direction` | `deny` | `deny_orchestrator_held` |
| `abstain` + `abstain_low_confidence` | `deny` | `deny_orchestrator_abstained` |
| `abstain` + `abstain_freshness_stale` | `deny` | `deny_orchestrator_abstained` |
| `abstain` + `abstain_freshness_missing` | `deny` | `deny_orchestrator_abstained` |
| `abstain` + `abstain_worker_*` | `deny` | `deny_orchestrator_abstained` |
| **(missing input / unreadable / invalid)** | `deny` | `deny_default` (+ `missing_runtime_evidence=true`, `fail_closed=true`) |

In every case the public payload reports `live_gate = current_gate_state = "blocked_human_only"`.

## Symbol Universe Contract

- `symbol_universe_contract = "SYMBOL_UNIVERSE_CONTRACT_REQUIRED"`.
- `symbol_universe_source_path = "v2/backend/app/services/symbol_universe/service.py"` when no V2 public symbol-universe payload is present; otherwise the relative path to that payload.
- `symbol_universe_public_payload_status` is `"PRESENT"` when a V2 payload is found at one of the candidate paths; otherwise `"MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD"`.
- `legacy_active_symbols` is the 25-symbol legacy subset from `LEGACY_ACTIVE_SYMBOLS_25` (sourced through `SymbolUniverseService`). This is not the full universe.
- `dynamic_discovered_symbols`, `discovered_symbols`, `observed_symbols`, `training_symbols`, `paper_symbols`, `live_symbols`, `live_blocked_symbols` are each emitted as distinct scopes.
- `live_symbols == []` while live is `blocked_human_only`. `train_all_discovered_symbols` and `trade_all_discovered_symbols` are both `false`.
- CoinAnk symbols carry the policy tag `coinank_symbols_tradability = "market_intelligence_only_until_binance_usdm_confirmed"`.

## Test coverage

| # | test | what it proves |
|---|---|---|
| 1 | `test_happy_path_open_long_stamps_allow_proceed_long_but_gate_stays_blocked_human_only` | `open_long` → `allow_proceed_long` AND `current_gate_state == "blocked_human_only"` |
| 2 | `test_low_confidence_abstain_stamps_deny_orchestrator_abstained` | `abstain_low_confidence` → `deny_orchestrator_abstained` |
| 3 | `test_stale_feature_abstain_stamps_deny_orchestrator_abstained` | `abstain_freshness_stale` → `deny_orchestrator_abstained` |
| 4 | `test_missing_input_payload_fails_closed_with_missing_runtime_evidence` | missing input → fail-closed + `missing_runtime_evidence=true` + CLI rc 2 |
| 4b | `test_fail_closed_when_required_record_field_missing` | invalid record fields → fail-closed + `missing_runtime_evidence=true` |
| 5 | `test_gate_always_blocked_invariant_holds_for_every_decision_action` | parameterized over all 9 decision-action/reason combos; gate stays blocked every time |
| 6 | `test_worker_has_no_old_redis_writer_codepath` | source has no `import redis`, no `from redis`, no `.set(`/`.hset(`/`.xadd(`/`.publish(` |
| 7 | `test_worker_has_no_real_exchange_codepath` | source contains no exchange-mutation method names |
| 8 | `test_symbol_universe_contract_required_in_public_payload` | scope contract + distinct symbol scopes present |
| 9 | `test_legacy_kill_switch_key_references_listed_for_audit_only` | audit-only kill-switch reference list is the documented set |
| 10 | `test_required_public_payload_fields_present` | every field in `REQUIRED_PUBLIC_PAYLOAD_FIELDS` is present in status and on disk |
| 11 | `test_legacy_bot_shutdown_classifies_missing_runtime_evidence` | no input → `MISSING_RUNTIME_EVIDENCE`, no synthesized data |
| 12 | `test_no_codepath_unblocks_live_gate` | single `LIVE_GATE_STATUS = "blocked_human_only"` declaration; no `unblock`/`approval_token`/`enable_live` |

Run via `.venv/bin/pytest v2/backend/tests/integration/cli/test_v2_risk_gateway_runtime_worker.py`.

## Hard-constraint compliance

- No legacy Redis writes: yes — worker contains no `redis` import; verified by `test_worker_has_no_old_redis_writer_codepath`.
- No exchange order / leverage / margin codepath: yes — verified by `test_worker_has_no_real_exchange_codepath`.
- No approval-token creation: yes — source contains no `approval_token`.
- No "unblock" path: yes — source contains no `unblock` or `enable_live`.
- Fail-closed on missing input: yes — `missing_runtime_evidence=true`, `risk_action=deny`, `risk_reason_code=deny_default`, CLI rc 2.
- Gate always `blocked_human_only`: yes — single constant + `gate_always_blocked_invariant=true` on every payload.
- Symbol Universe Contract: yes — scope read through `SymbolUniverseService`; 25 legacy symbols not treated as the full universe; CoinAnk-only symbols flagged as market-intelligence-only.
- Legacy bot shutdown → MISSING_RUNTIME_EVIDENCE: yes — no data synthesized; CLI rc 2.

## Legacy baseline

See `v2_risk_gateway_runtime_worker_LEGACY_BASELINE_ANALYSIS.md` and
`v2_risk_gateway_runtime_worker_legacy_behavior_mapping.json` (siblings in
this directory) for the SHA-anchored legacy-source mapping, edge-case
table, intentional-divergence rationale, and removed-behavior list.

## Codex review trigger

Paired Codex review task `codex_review_v2_risk_gateway_runtime_worker` is
the trigger emitted on this artifact set. Codex must produce
`V2_RISK_GATEWAY_RUNTIME_WORKER_CODEX_PASS` or `_FAIL` after reviewing this
report and the artifacts listed above.

## Files emitted by this worker port

- `v2/backend/app/cli/v2_risk_gateway_runtime_worker.py`
- `v2/backend/tests/integration/cli/test_v2_risk_gateway_runtime_worker.py`
- `v2/frontend/public/operator_runtime/v2_risk_gateway_runtime_worker/latest/v2_risk_gateway_runtime_worker_status.json`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_risk_gateway_runtime_worker_report.md` (this file)
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_risk_gateway_runtime_worker_status.json` (mirror)
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_risk_gateway_runtime_worker_LEGACY_BASELINE_ANALYSIS.md`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_risk_gateway_runtime_worker_legacy_behavior_mapping.json`

## Outcome for the aggregate

This port advances the V2 runtime independence score (per the
`V2_RUNTIME_WORKER_GAP_MATRIX.md` row for `risk_gateway_runtime`) from
`MIGRATED_LIBRARY_ONLY` to `MIGRATED_AND_RUNNABLE`. Aggregate emergency
migration GO/NO-GO remains
`EMERGENCY_V2_RUNTIME_MIGRATION_AND_ONLINE_BOOTSTRAP_BLOCKED` until the
remaining P0 workers (paper_execution, execution_ledger, signal_lineage,
account/position monitor) ship.
