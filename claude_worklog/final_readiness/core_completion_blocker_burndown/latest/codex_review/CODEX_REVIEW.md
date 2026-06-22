# Codex Review: V2 Core Completion Blocker Burndown

Generated: `2026-05-16T22:55:54Z`

GO/NO-GO: `V2_CORE_COMPLETION_BLOCKER_BURNDOWN_CODEX_FAIL`

## Decision

Codex fails the blocker burndown review. The packet makes real progress and the active code-level safety checks are clean, but the burndown cannot be accepted as complete because the report/matrix truth and active runtime truth disagree for CoinAPI/CoinAnk ingestors.

This review does not approve live trading, canary trading, legacy shutdown, exchange mutation, leverage changes, margin changes, or Redis trim.

## Blocking Findings

1. `COINAPI_AND_COINANK_SECRET_OR_OPERATOR_DECISIONS_NOT_ACCEPTED` is reported as resolved, but active runtime truth still says blocked.
   - `core_completion_blocker_matrix.json` says `COINAPI_API_KEY` and `COINANK_API_KEY` are present in the local secret vault and marks the blocker `RESOLVED_FOR_READ_ONLY_DATA_AND_OPERATOR_DECISION_FOR_PAID_OR_AGGREGATOR`.
   - `coinapi_coinank_secret_decision_status.json` also reports both key names present, with raw values not recorded.
   - However `v2/frontend/public/operator_runtime/v2_native_ingestors/latest/v2_native_ingestors_status.json` still classifies:
     - `live_coinank`: `BLOCKED_BY_SECRET_OR_API`
     - `live_coinapi_v1`: `BLOCKED_BY_SECRET_OR_API`
     - `live_coinapi_wsds`: `BLOCKED_BY_SECRET_OR_API`
   - The active classifier in `v2/backend/app/services/native_ingestors/registry.py` only checks process environment via `os.environ`, while the burndown decision is based on the local secret vault. Until the runtime classifier safely consumes the redacted vault decision or the matrix is downgraded to match runtime truth, this blocker is not closed.

2. The burndown matrix overstates final blocker status.
   - `every_blocker_implemented_or_explicitly_accepted=true` is not accurate for the current packet.
   - The checkpoint packet explicitly says an operator must provide weights or accept the limitation.
   - The paper-edge packet explicitly says `operator_accepts_no_trade_paper_only_for_legacy_shutdown=false`.
   - These may be valid `OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN` states, but they are not accepted states. The matrix should distinguish `implemented`, `converted_to_operator_decision_required`, and `operator_accepted`.

3. Ingestor closure still needs one more truth cleanup.
   - The registry has no current ingestor entry classified `READONLY_BRIDGED`, which is good.
   - The active payload still contains secret-blocked CoinAPI/CoinAnk entries while the dashboard says those blockers are resolved for read-only data.
   - This is a frontend/runtime truth mismatch and must stay visible as NO-GO.

## Verified Positive Findings

- `LIVE_KUCOIN_MISSING_IN_V2`: KuCoin is implemented as V2 public-data config/worker and the active payload classifies `live_kucoin` as `NATIVE_V2`.
- `CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED_NOT_ACCEPTED_FOR_PAPER_ONLY_SHUTDOWN`: checkpoint parity is not falsely claimed; candidate count is `0` and the packet keeps the blocker operator-required.
- `ADAPTIVE_HEDGE_FAIL_CLOSED_LIMITATION_NOT_ACCEPTED_FOR_PAPER_ONLY_SHUTDOWN`: hedge behavior is not silently enabled. `hedge_engine.py` fail-closes by default unless operator approval is passed.
- `FULL_LEGACY_ORCHESTRATOR_WORKER_LOGIC_NOT_PORTED_OR_ACCEPTED`: V2 has real paper-only orchestration code with a proposal bus, arbitration, stale/duplicate handling, protection scoring, and hedge overlay. Full legacy 10k-line live parity is not claimed.
- `LIVE_REDIS_PROPOSAL_BUS_NOT_PORTED_OR_ACCEPTED`: `V2NativeProposalBus` is in-process and reports `writes_legacy_redis=false`.
- `PAPER_EDGE_CURRENT_SAMPLE_NEGATIVE_AND_NOT_OPERATOR_ACCEPTED_AS_NO_TRADE_ONLY`: the current negative after-cost edge remains blocked; `paper_fill_allowed=false`; no positive edge is claimed and the gate was not loosened.

## Validation Run

- Focused tests:
  - `test_v2_kucoin_ingestor_worker.py`: `8 passed`
  - `test_v2_native_ingestors_worker.py`
  - `test_v2_trade_management_paper_hedge_engine.py`
  - `test_v2_orchestrator_arbitration_worker.py`
  - `test_v2_rl_core_p0_2f_trainer_output.py`
  - Combined non-KuCoin focused run: `55 passed`
- `py_compile` for active burndown modules: PASS.
- Active-source old Redis write scan: PASS, no matches.
- Active-source exchange mutation scan: PASS, no matches.
- High-confidence secret scan over burndown worklog/public payloads: PASS, no raw secret values found.
- Approval-token/live-approval scan: PASS, no active approval found.

## Safety State

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`

## Required Remediation

Before Codex can pass this burndown:

1. Reconcile CoinAPI/CoinAnk secret truth with the active ingestor payload:
   - either wire `v2_native_ingestors` to a redacted local-secret decision source without printing or publishing raw secrets,
   - or downgrade the burndown matrix/dashboard to show CoinAPI/CoinAnk still blocked/operator-decision-required.
2. Replace `every_blocker_implemented_or_explicitly_accepted` with an accurate state model that separates:
   - implemented,
   - converted to operator decision required,
   - explicitly operator accepted.
3. Keep frontend truth as NO-GO until the runtime payload and burndown matrix agree.

## Final Decision

`V2_CORE_COMPLETION_BLOCKER_BURNDOWN_CODEX_FAIL`
