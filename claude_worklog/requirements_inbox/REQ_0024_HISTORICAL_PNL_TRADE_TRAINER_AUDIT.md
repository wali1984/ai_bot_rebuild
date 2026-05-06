# Requirement 0024 - Historical PnL, Trade, Trainer, and Decision Audit

## Objective

Claude and Codex must use at least 30 days of historical trading, PnL, trainer, orchestrator, and risk evidence to build V2.

The rebuild must learn from actual legacy outcomes, not assumptions.

## Scope

The audit must collect and summarize, read-only:

- realized PnL by day
- realized PnL by symbol
- realized PnL by side if derivable
- funding fees
- commissions
- trade count
- win/loss distribution
- drawdowns
- large losers
- large winners
- open/close/hedge/reduce behavior if inferable
- symbols that repeatedly lost
- symbols that made money
- time-of-day patterns
- position hold duration if inferable
- trainer prediction availability
- trainer confidence if logged
- orchestrator decision evidence if logged
- trader action evidence if logged
- risk/failure cases such as LAB hedge unwind

## Data Sources

Prefer local/legacy evidence first:

- legacy logs
- legacy audit files
- read-only Redis metadata
- trainer monitor logs
- trader/orchestrator logs
- order/trade history logs if already present
- local CSV/JSON exports if present

If local logs are missing or incomplete, use direct read-only Binance USD-M Futures account-history API calls.

## Binance Read-Only Policy

Allowed Binance endpoints are read-only account/history endpoints only, such as:

- account trade history
- order history
- income history / realized PnL / funding / commission
- account/balance snapshots if needed for audit context

Forbidden:

- new order
- cancel order
- leverage change
- margin change
- position mode change
- transfer
- any POST/DELETE/PUT request
- any live execution action

## Secret Handling

Claude/Codex must not receive raw API secret values.

Allowed:
- environment variable names
- local key presence checks
- local read-only script using env/config secrets without printing them

Forbidden:
- printing API key/secret
- committing secrets
- sending secret values to Claude/Codex/Ollama
- dumping account credentials

## Minimum Audit Period

At least 30 days.

If Binance endpoint time windows are limited, split requests into safe chunks.

## Required Artifacts

Create and maintain:

- `claude_worklog/historical_pnl_audit/00_AUDIT_INDEX.md`
- `claude_worklog/historical_pnl_audit/01_DATA_SOURCE_STATUS.md`
- `claude_worklog/historical_pnl_audit/02_BINANCE_READONLY_PULL_SUMMARY.md`
- `claude_worklog/historical_pnl_audit/03_30D_REALIZED_PNL_BY_DAY.md`
- `claude_worklog/historical_pnl_audit/04_30D_PNL_BY_SYMBOL.md`
- `claude_worklog/historical_pnl_audit/05_30D_FEES_FUNDING_COMMISSION.md`
- `claude_worklog/historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md`
- `claude_worklog/historical_pnl_audit/07_LEGACY_TRAINER_DECISION_EVIDENCE.md`
- `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md`
- `claude_worklog/historical_pnl_audit/09_V2_BUILD_IMPACT_MAP.md`
- `claude_worklog/historical_pnl_audit/10_GO_NO_GO.md`

GO/NO-GO marker:
`HISTORICAL_PNL_TRADE_TRAINER_AUDIT_READY`

Partial marker when only local metadata is available:
`HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`

## Required V2 Build Impact

Claude/Codex must use this audit to inform:

- trainer prediction output
- orchestrator decision MVP
- risk gateway default-deny MVP
- paper execution ledger MVP
- replay/backtest runner MVP
- paper mode MVP
- shadow readiness
- explainability UI

## Risk-Gateway Implications

V2 must learn from historical losses:

- block stale-data trades
- block repeated loser patterns
- identify shorting bottoms / longing tops
- identify bad hedge unwind behavior
- identify unsafe residual exposure
- identify liquidation/squeeze risk
- avoid leaving naked exposure after hedge close

## Codex Role

Codex must review the audit and verify:

- at least 30 days were attempted
- data source gaps are stated
- no secrets are exposed
- no live action occurred
- no Redis write occurred
- V2 requirements are derived from actual PnL/trade evidence

REQ_HISTORICAL_PNL_TRADE_TRAINER_AUDIT_READY
