# V2 Signal Publisher Legacy Baseline Analysis

Generated: 2026-05-14

## Classification

- Worker: `v2_signal_publisher`
- Lane: P1 runtime migration
- Live gate: `blocked_human_only`
- Legacy mutation: forbidden
- Old Redis writes: forbidden
- Exchange actions: forbidden
- Execution routing: forbidden
- Symbol contract: `SYMBOL_UNIVERSE_CONTRACT_REQUIRED`

## Legacy Source Paths

- `legacy_reference/rl/hybrid_trainer.py`
- `legacy_reference/trading/signal_router.py`
- `legacy_reference/rl/signal_state_manager.py`
- `legacy_reference/rl/orchestrator_worker.py`
- `legacy_reference/monitor_trainer_signals.py`

## Legacy Behavior Preserved As Contract

- The legacy trainer/orchestrator stack publishes signals for downstream consumers.
- The legacy router fans the shared stream to account-specific streams.
- The legacy state manager records signal lifecycle state after publish.
- The legacy monitor reads trainer/signal output for operator visibility.
- The V2 worker preserves fanout semantics only as file-based V2 evidence envelopes for `webhook`, `gui`, and `admin_ai`.

## Intentional V2 Changes

- No legacy stream writes are reproduced.
- No account-specific execution stream is written.
- No exchange route exists.
- No live route exists.
- All consumer envelopes carry `route_to_execution=false`, `execution_route_enabled=false`, and `live_gate=blocked_human_only`.
- Missing, stale, incomplete, or upstream fail-closed lineage fails closed.

## Symbol Universe Contract

The publisher emits:

- `legacy_active_symbols`
- `discovered_symbols`
- `dynamic_discovered_symbols`
- `observed_symbols`
- `training_symbols`
- `paper_symbols`
- `live_symbols`
- `live_blocked_symbols`

The legacy 25 symbols are not the full universe. Training and paper scope remain selected subsets. CoinAnk-only symbols are market-intelligence candidates until Binance USD-M confirmation exists. `live_symbols` remains `[]`.

## V2 Mapping

- CLI: `v2/backend/app/cli/v2_signal_publisher.py`
- Tests: `v2/backend/tests/integration/cli/test_v2_signal_publisher.py`
- Public payload: `v2/frontend/public/operator_runtime/v2_signal_publisher/latest/v2_signal_publisher_status.json`
- Worklog status: `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_signal_publisher_status.json`

Current runtime is allowed to be fail-closed when upstream lineage is not yet publishable.
