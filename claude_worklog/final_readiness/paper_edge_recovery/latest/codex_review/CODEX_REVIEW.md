# Codex Review - Paper Edge Recovery And Cost-Aware Trade Selection

Result: FAIL

Scope reviewed read-only: Claude paper-edge outputs, V2 paper execution source/tests, paper loss attribution, post-filter observation, paper runtime/shadow payloads, and current shutdown controller state. No source files were modified. No live trading, exchange, leverage, margin, legacy, or old Redis mutation was performed.

## Failing Findings

1. V2 paper execution can still record a fill while required edge fields are missing.

Evidence: a temp-path dry run of `v2.backend.app.cli.v2_paper_execution_worker.run_once` with an allow decision produced:
- `ledger_action=record_allow`
- `fills_recorded_total=1`
- `paper_filter_denied=false`
- `paper_filter_blockers=[]`
- `paper_symbols=[]`
- `live_gate=blocked_human_only`
- `live_symbols=[]`

The input intentionally omitted `trainer_source`, `feature_freshness_state`, and singular `expected_move_after_cost_bps`. It also ran with no symbol-universe payload, leaving `paper_symbols=[]`. This directly fails the review conditions: missing expected move after cost can allow a fill, missing trainer source can allow a fill, missing feature freshness state can allow a fill, and symbol not in `paper_symbols` can allow a fill.

2. Existing tests encode the unsafe admission path.

`v2/backend/tests/integration/cli/test_v2_paper_execution_worker.py` happy-fill fixtures use `expected_move_bps`, timestamps, confidence, fees, and slippage, but do not require `expected_move_after_cost_bps`, `trainer_source`, or `feature_freshness_state`. The happy-fill tests still assert `fills_recorded_total == 1`. The tests therefore do not protect the required hard-fail conditions.

3. Phase A-E are not implemented.

Claude’s own packet is honest about this: schema extension, cost-aware scoring module, shadow outcome observer, threshold replay, and paper-only legacy protective equivalents are specified or mapped but not merged/run. That means the current runtime cannot pass the requested paper-edge recovery readiness review.

4. Positive edge is not proven.

Paper post-filter evidence still has zero fills. Current raw `v2/runtime/paper_online/latest/paper_events.jsonl` parse after `2026-05-14T22:40:46Z` shows 694 post-filter events, 694 blocks, 0 fills, 0 fees, and PnL unchanged at `-49.12`. Zero post-filter fills cannot prove positive net-after-cost edge.

## Passing Checks Within Failed Review

- Main `claude_worklog/final_readiness/paper_edge_recovery/latest/GO_NO_GO.md` contains allowed token `V2_PAPER_EDGE_RECOVERY_BLOCKED`.
- Claude did not mark paper edge proven, did not approve live/canary/legacy shutdown, and did not hide the old pre-filter loss.
- Paper loss attribution preserves the caveats: prior baseline `-26.37`, observed pre-filter loss `-22.75`, post-filter delta `0.0`, post-filter fills `0`, trainer/source/freshness/edge-after-cost gaps present.
- Legacy protective behaviors are mapped with pending equivalents/blockers, not silently claimed complete.
- Current runtime/shadow/controller safety state remains `live_gate=blocked_human_only`, `live_symbols=[]`, approval token absent, Redis trim approval absent.
- Parsed current paper events showed no `legacy_redis_write=true`, no exchange/live order true, and no leverage or margin-mode mutation.
- Shutdown controller remains blocked with paper-edge and parity blockers, including `PAPER_EDGE_UNPROVEN` and `OBSERVATORY_PAPER_EDGE_RECOVERY_REQUIRED`.

## Decision

CODEX_FAIL. The Claude packet is appropriately blocked and honest, but the underlying V2 paper fill boundary still admits fills without the required cost-aware provenance gates. This review does not approve live, canary, or legacy shutdown.
