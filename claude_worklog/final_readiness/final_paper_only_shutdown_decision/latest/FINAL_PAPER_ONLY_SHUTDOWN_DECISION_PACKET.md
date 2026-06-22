# Final Paper-Only Legacy Shutdown Decision Packet

Last refreshed: 2026-05-17T00:30:00Z
Git HEAD: 31a7fd70319f0d586c454b5ea2ea530ba9cb1541
Verification scope: FINAL_PAPER_ONLY_SHUTDOWN_ACCEPTANCE_VERIFICATION_READY

## Decision

`OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN`

The expected operator acceptance file is NOT present on disk:

  claude_worklog/approvals/OPERATOR_ACCEPTS_V2_PAPER_ONLY_SHUTDOWN_LIMITATIONS.md

The verifier searched the approvals directory and the file is
absent. Therefore the packet cannot mark
`SAFE_TO_SHUTDOWN_LEGACY_RUNTIME_FOR_V2_PAPER_ONLY` and must keep
all six remaining limitations operator-decision-required.

## Acceptance file verification

- file_present: false
- verdict: MISSING
- missing_required_literals: every required positive and negative
  literal (file absent => all missing)
- forbidden_literals_found: []

The verifier rejects acceptance if the file is missing, contains
forbidden language, or lacks required paper-only language. The
exact algorithm is in
v2/backend/scripts/run_final_shutdown_acceptance_verification.py.

## Runtime health check (passes)

- P0.2F strict paper-fill gate: blocks negative after-cost edge
  - paper_fill_allowed: false
  - paper_fill_gate_status: BLOCKED_BY_TRAINER_OUTPUT_MALFORMED
  - paper_fill_gate_block_reasons: [NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK]
  - expected_move_after_cost_bps: -68.46
- P0.2G trainer-algo status:
  - migration_classification: PAPER_ONLY_TRAINER_ALGO_READY_P0_2G
  - PPO clip / GAE / AdamW ready paper-only
  - checkpoint_weight_status: CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED
  - hedge_status: HEDGE_FAIL_CLOSED_PAPER_HEDGE_ENGINE_PENDING_CODEX_PASS
- V2-owned non-live startup: V2_OWNED_NON_LIVE_STARTUP_READY
  - any_unsafe_live_field: false
- Native ingestor classifications (matrix and runtime agree):
  - live_coinank: NATIVE_V2_READONLY_PUBLIC_DATA
  - live_coinapi_v1: NATIVE_V2_READONLY_PUBLIC_DATA
  - live_coinapi_wsds: OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN
  - live_coinank_global_aggregator: OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN
  - live_kucoin: NATIVE_V2
- Burndown matrix:
  - burndown_go_no_go: V2_CORE_COMPLETION_BLOCKER_BURNDOWN_TRUTH_REMEDIATION_READY
  - matrix_agrees_with_runtime: true
  - all_required_operator_decisions_accepted: false

## Remaining operator decisions still required

| Item | State | Operator accepted |
| --- | --- | --- |
| checkpoint weights limitation | CONVERTED_TO_OPERATOR_DECISION_REQUIRED | false |
| adaptive hedge operator enablement | CONVERTED_TO_OPERATOR_DECISION_REQUIRED | false |
| paper-edge no-trade mode | CONVERTED_TO_OPERATOR_DECISION_REQUIRED | false |
| CoinAPI WSDS paid tier | OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN | false |
| CoinAnk global aggregator scope | OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN | false |
| ccxt_historical vs replay store | OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN | false |

## Acceptance file requirements

The verifier requires (case-insensitive):

Required positive language: `paper-only`, `live_gate = blocked_human_only`, `live_symbols = []`.

Required negative language: `does not approve live`, `does not approve canary`, `does not approve exchange mutation`, `does not approve leverage`, `does not approve margin`, `does not approve Redis trim`.

Forbidden language (any occurrence rejects the file): `APPROVE_LIVE_TRADING`, `ENABLE_LIVE`, `APPROVE_CANARY`, `APPROVE_REDIS_TRIM`, `APPROVE_EXCHANGE_MUTATION`, `APPROVE_LEVERAGE_CHANGE`, `APPROVE_MARGIN_CHANGE`.

When all requirements pass and runtime health is OK, the packet upgrades to `SAFE_TO_SHUTDOWN_LEGACY_RUNTIME_FOR_V2_PAPER_ONLY`. Until then the decision stays `OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN`.

## Safety scans

- Old Redis write scan over final decision + active runtime: clean.
- Exchange mutation scan: clean.
- Approval-token scan over claude_worklog/approvals/: no
  APPROVE_LIVE_*, FINAL_LIVE*, or redis_trim approval files.
- High-confidence secret scan: no raw values found.

## Safety posture

- live_gate: blocked_human_only
- live_symbols: []
- approves_live: false
- approves_canary: false
- approves_legacy_shutdown: false
- approves_redis_trim: false
- final_live_approval_token_created: false

## Decision (restated)

OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN. Legacy shutdown
remains blocked until the operator acceptance file is present,
contains the required paper-only language, and contains no forbidden
language.
