# Phase 2M — Replay-Case Outcome Matrix (REQ_0022 § "Required replay/backtest case")

## Outcome variants

REQ_0022 requires the following five outcome variants for the LAB hedge-unwind / squeeze case:

1. legacy action — close-long-hedge allowed; squeeze loss occurred.
2. keep hedge — do not close the protective long.
3. close short — close the residual short instead of the hedge.
4. reduce short — partial residual-short close.
5. block hedge close — risk-gateway default-deny on the close.

## Type-level mapping at consolidation HEAD

The typed surfaces at HEAD 7b46dbf model `record_allow` / `record_deny` × directional mirror reasons (`mirror_allow_proceed_long`, `mirror_allow_proceed_short`, `mirror_deny_orchestrator_held`, `mirror_deny_orchestrator_abstained`, `mirror_deny_default`). They do not model hedge state, residual exposure, position size, PnL, slippage, fees, funding, OI, liquidation map, orderbook depth, or squeeze risk. Each REQ_0022 outcome therefore maps to a sequence of typed mirror records only, not to hedge-aware fields.

The five outcome variants are encoded as five distinct `ReplayBacktestRun` instances, each with its own `replay_run_id`, its own ordered tuple of `PaperExecutionLedgerEntry` mirror rows, and its own resulting tuple of `ReplayBacktestStep` mirror rows. The richer hedge-unwind / residual-exposure / squeeze-risk modelling is explicitly out of scope at Phase 2M and belongs to a separate, later milestone.

## Per-outcome typed mirror sequence (each row is one `PaperExecutionLedgerEntry` → one `ReplayBacktestStep`)

The "step #" column is the one-based ordinal within the outcome's ordered step tuple. The "ledger_action" / "ledger_reason_code" / "input_risk_action" / "input_risk_reason_code" columns are the typed values carried by the fixture `PaperExecutionLedgerEntry`. The supervisor implementation must follow the pairing rules enforced by `PaperExecutionLedgerEntry.__post_init__` (allow ↔ mirror_allow_* prefix ↔ allow input_risk_action ↔ allow_proceed_* input_risk_reason_code; deny ↔ mirror_deny_* prefix ↔ deny input_risk_action ↔ deny_* input_risk_reason_code).

### Outcome 1 — legacy action

Symbol: `LABUSDT`. `replay_run_id`: `replay_run_lab_hedge_unwind_legacy`. Three steps:

- step 1: `record_allow` × `mirror_allow_proceed_short` (open of the directional short under legacy untyped routing).
- step 2: `record_allow` × `mirror_allow_proceed_long` (open of the protective long hedge under legacy untyped routing).
- step 3: `record_allow` × `mirror_allow_proceed_long` (close of the protective long hedge — the close is an allow-long mirror because the close exits a short-leg-against-long position; today's typed surfaces use the directional reason code, not an open/close differentiator).

Expected `ReplayBacktestSummary` step counts: `record_allow` = 3, `record_deny` = 0.

### Outcome 2 — keep hedge

Symbol: `LABUSDT`. `replay_run_id`: `replay_run_lab_hedge_unwind_keep_hedge`. Three steps:

- step 1: `record_allow` × `mirror_allow_proceed_short` (open of the directional short).
- step 2: `record_allow` × `mirror_allow_proceed_long` (open of the protective long hedge).
- step 3: `record_deny` × `mirror_deny_orchestrator_held` (close of the protective long hedge denied because orchestrator held; the hedge is kept).

Expected step counts: `record_allow` = 2, `record_deny` = 1.

### Outcome 3 — close short

Symbol: `LABUSDT`. `replay_run_id`: `replay_run_lab_hedge_unwind_close_short`. Three steps:

- step 1: `record_allow` × `mirror_allow_proceed_short` (open of the directional short).
- step 2: `record_allow` × `mirror_allow_proceed_long` (open of the protective long hedge).
- step 3: `record_allow` × `mirror_allow_proceed_short` (close of the residual short — the close is an allow-short mirror by today's directional reason code convention).

Expected step counts: `record_allow` = 3, `record_deny` = 0.

### Outcome 4 — reduce short

Symbol: `LABUSDT`. `replay_run_id`: `replay_run_lab_hedge_unwind_reduce_short`. Three steps:

- step 1: `record_allow` × `mirror_allow_proceed_short` (open of the directional short).
- step 2: `record_allow` × `mirror_allow_proceed_long` (open of the protective long hedge).
- step 3: `record_allow` × `mirror_allow_proceed_short` (partial close of the residual short — at this typing layer "reduce" and "close" project to the same typed mirror record; the differentiation is documentation-only at Phase 2M and becomes typed in a later milestone).

Expected step counts: `record_allow` = 3, `record_deny` = 0.

### Outcome 5 — block hedge close

Symbol: `LABUSDT`. `replay_run_id`: `replay_run_lab_hedge_unwind_block_hedge_close`. Three steps:

- step 1: `record_allow` × `mirror_allow_proceed_short` (open of the directional short).
- step 2: `record_allow` × `mirror_allow_proceed_long` (open of the protective long hedge).
- step 3: `record_deny` × `mirror_deny_default` (close of the protective long hedge denied by default-deny; the hedge close is blocked).

Expected step counts: `record_allow` = 2, `record_deny` = 1.

## Acknowledged typing limitation

Outcomes 3 and 4 produce identical typed mirror sequences at consolidation HEAD because the typed surfaces do not differentiate full close from partial close at the type level. The differentiation is preserved in the documentation under `01_LEGACY_FAILURE_EVIDENCE.md` and `06_IMPLEMENTATION_REPORT.md` for traceability and is intentionally deferred to a later milestone that introduces typed quantity / size / partial-close fields. The Phase 2M test plan asserts that outcomes 3 and 4 produce the same typed mirror counts and that the differentiation lives in the `replay_run_id` namespacing only.

PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_OUTCOME_MATRIX_READY
