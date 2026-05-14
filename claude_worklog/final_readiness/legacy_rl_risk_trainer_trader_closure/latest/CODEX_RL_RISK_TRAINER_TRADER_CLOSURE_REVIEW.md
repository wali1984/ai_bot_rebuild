# Codex Review - RL/Risk/Trainer/Trader Closure

Generated: 2026-05-14T18:33:02Z

Result: `LEGACY_RL_RISK_TRAINER_TRADER_CLOSURE_CODEX_FAIL`

## Scope

Codex independently checked whether the expanded legacy `rl/`, `risk/`,
`services/`, `utils/`, and `trading/` closure is sufficient to recommend
legacy trainer/trader shutdown.

This review is non-live. Codex did not modify `/home/wali/Desktop/AI BOT`, did
not write old Redis, did not call exchange APIs, did not change leverage or
margin, did not enable live, and did not create approval tokens. Live remains
`blocked_human_only`.

## Verdict

`FAIL / BLOCK`

The V2 P0/P1/P2 worker list being complete is not the same as full legacy
trainer/risk/trader closure. Worker-level reviews show several V2 surfaces are
safe and fail-closed, but the full shutdown standard is not met.

## Inventory Check

Codex scan results:

| Area | Present | Python files scanned |
|---|---:|---:|
| `legacy_reference/rl` | yes | 121 |
| `legacy_reference/risk` | yes | 22 |
| `legacy_reference/risks` | no | 0 |
| `legacy_reference/services` | yes | 8 |
| `legacy_reference/utils` | yes | 21 |
| `legacy_reference/trading` | yes | 35 |
| `legacy_reference/config_accounts.py` | yes | 1 |

Required files exist in legacy reference:

- `legacy_reference/config_accounts.py`
- `legacy_reference/trading/base_executor.py`
- `legacy_reference/risk/assertions.py`
- `legacy_reference/risk/halt_manager.py`

Closure problem: the startup baseline SHA manifest is under-scoped for this
review. `copied_baseline_manifest.json` contains copied records for only:

- `rl/hybrid_trainer.py`
- `rl/orchestrator_worker.py`
- `trading/trader.py`
- `trading/trader-asjad.py`

It does not contain copied SHA256 records for the required closure files
`config_accounts.py`, `trading/base_executor.py`, `risk/assertions.py`, or
`risk/halt_manager.py`, and it does not cover the full `risk/`, `services/`,
`utils/`, or `trading/` dependency surface.

## Dependency Closure

Existing baseline matrix:

- `legacy_dependency_closure_matrix.json` analyzed 32 files.
- It reports 21 files with unresolved imports.
- `trading/trader.py` unresolved/unknown imports include
  `config_accounts`, `risk`, `services`, and `utils`.
- `rl/hybrid_trainer.py` unresolved/unknown imports include `risk`, `services`,
  and `utils`.
- `rl/orchestrator_worker.py` unresolved/unknown imports include `risk` and
  `utils`.

Independent Codex AST scan over 208 relevant Python files found:

- Parse errors in:
  - `legacy_reference/rl/microstructure_aggregator.py`
  - `legacy_reference/rl/microstructure_features.py`
- External dependency names not mapped by the closure proof:
  - `schedule`
  - `nvidia_ml_py`
  - `nvidia_ml_py3`
  - `tqdm`

This fails the requirement that no unexplained unresolved local imports remain
and that external dependencies are mapped.

## Trainer Parity

Evidence reviewed:

- `v2_trainer_bridge_LEGACY_BASELINE_ANALYSIS.md`
- `v2_trainer_bridge_legacy_behavior_mapping.json`
- `codex_v2_trainer_bridge_review.md`
- `v2/frontend/public/operator_runtime/v2_trainer_bridge/latest/v2_trainer_bridge_status.json`

Positive evidence:

- Hybrid trainer classes/functions are documented.
- Feature snapshot dependency, checkpoint/model metadata, GPU evidence,
  prediction IDs, confidence fields, missing/stale feature flags, and Symbol
  Universe scope are represented in the V2 bridge contract.
- The Codex worker-level review passed because the bridge is safe and
  fail-closed.

Blocking evidence:

- Runtime status remains `trainer_readiness = BLOCKED`.
- `runtime_evidence_status = WRAPPER_NOT_LEGACY_HYBRID_PARITY`.
- `prediction_evidence_status = WRAPPER_NOT_LEGACY_HYBRID_PARITY`.
- `accepted_as_legacy_hybrid_prediction = false`.
- Current accepted predictions emitted: `0`.

Therefore the wrapper is correctly not accepted as full parity, but full trainer
parity is not proven.

## Risk/Trader Action Parity

Positive evidence:

- The risk gateway worker maps a bounded risk-stamp contract and remains
  fail-closed.
- The default blocked execution adapter maps the canonical mutation operations
  and refuses them:
  - order placement
  - cancel
  - leverage change
  - margin mode change
- Worker-level reviews for risk gateway, paper execution, execution ledger,
  signal lineage, account monitor, trainer bridge, and blocked execution adapter
  are present.

Blocking evidence:

- Full trader behavior is not closure-proven. Existing analyses explicitly
  defer or remove important legacy behavior:
  - paper position bookkeeping is deferred outside `v2_paper_execution_worker`.
  - per-symbol slippage modelling is deferred.
  - Telegram/alerting behavior is deferred.
  - reduce-only flag enforcement, hedge-mode position-side tagging, leverage
    tier caps, cross/isolated margin switching, exchange retry behavior, IP-ban
    handling, and cancel/fill races are not re-implemented in the blocked
    adapter; they are collapsed into refusal.
- Legacy `risk/hedge_cage_manager.py`, `risk/halt_manager.py`,
  `risk/assertions.py`, `trading/stealth_stops.py`,
  `trading/dynamic_adaptive_stops.py`, `trading/dynamic_tp_engine.py`,
  `trading/adaptive_hedge_builder.py`, `trading/base_executor.py`,
  `services/portfolio_state.py`, and `utils/unified_position_loader.py` contain
  hedge, reduce, margin, leverage, stop-loss, take-profit, stale/duplicate, and
  execution-state behavior that is not proven as V2 parity-complete.
- DCA, stealth-profit/take-profit, stop-loss, hedge ordering, and execution
  attribution are partially documented across worker files, but there is no
  single complete closure matrix that maps every legacy behavior to a V2 status,
  missing-test status, and shutdown decision.

This is acceptable for paper/shadow safety, but not sufficient for legacy
shutdown.

## V2 Parity Status

Current V2 state from worker artifacts:

- P0/P1/P2 worker list: complete.
- V2 mode: paper/shadow only.
- Live gate: `blocked_human_only`.
- Final live approval token: absent.
- Redis trim approval token: absent.
- Trainer bridge: blocked on legacy hybrid parity.
- Account/trade permission: read-only/unknown blocks canary in the latest
  account permission contract.
- Paper metrics remain canary-blocked by negative PnL, unproven edge, and high
  historical fill rate in current monitoring evidence.

The worker list completion cannot be used as shutdown proof.

## Safety Review

Codex did not observe a new V2 live execution path during this review.

- Old Redis writes by Codex: none.
- Legacy mutation by Codex: none.
- Exchange actions by Codex: none.
- Leverage/margin changes by Codex: none.
- Live enablement by Codex: none.
- Final live approval token created by Codex: no.

The reviewed V2 worker artifacts continue to state `live_gate =
blocked_human_only`.

## Shutdown Recommendation

`BLOCK`

Do not shut down the legacy trainer/trader solely because P0/P1/P2 worker
descriptors are complete. Shutdown requires a full closure package that:

1. Scans and SHA-manifests the full `rl/`, `risk/`, `services/`, `utils/`,
   `trading/`, and `config_accounts.py` dependency set.
2. Resolves or explicitly classifies every local import and external dependency.
3. Maps every trainer, risk, execution, hedge, DCA, stop, take-profit,
   reduce-only, leverage/margin, stale-signal, duplicate-signal, and attribution
   behavior to a V2 status.
4. Lists every missing V2 behavior and its required tests.
5. Proves trainer parity without accepting a wrapper as full parity.
6. Keeps live blocked until separate human approval exists.

## Final Decision

`LEGACY_RL_RISK_TRAINER_TRADER_CLOSURE_CODEX_FAIL`
