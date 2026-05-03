# Requirement 0009 — Full Decision Explainability and Under-the-Hood UI

The V2 system must expose detailed human-readable explanations for every major system decision.

## Objective

The website must show exactly why the system changes confidence, selects symbols, opens/closes/hedges positions, blocks trades, or changes symbol state.

## Required explanation chains

Show full lineage:

raw source data
→ feature snapshot
→ feature changes
→ trainer prediction
→ confidence change
→ signal
→ orchestrator decision
→ risk gateway decision
→ execution intent
→ paper/shadow/live-blocked trader action
→ result/PnL attribution

## Required UI visibility

Website pages must expose:
- feature_snapshot_id
- prediction_id
- signal_id
- decision_id
- risk_decision_id
- execution_intent_id
- symbol universe state
- confidence delta
- top positive feature contributors
- top negative feature contributors
- stale/missing/unused feature flags
- source freshness by ingestor
- risk checks
- position sizing reason
- open/close/hedge reason
- paper/shadow/legacy comparison
- blocked-trade reason
- audit timeline

## Confidence explanation

When confidence changes, show:
- previous confidence
- new confidence
- delta
- contributing feature deltas
- positive contributors
- negative contributors
- source freshness
- regime context
- model/checkpoint version
- whether data quality affected confidence

## Symbol selection explanation

When a symbol changes state, show:
- source discovery evidence
- Binance USD-M confirmation
- CoinAnk alias evidence
- KuCoin/CoinAPI evidence
- liquidity/volume/volatility/open-interest/freshness scores
- feature completeness
- manual overrides
- reason for observed/training/paper/shadow/live-blocked state

## Trade/risk explanation

For open/close/hedge/block decisions, show:
- signal reason
- risk gateway result
- sizing reason
- stale signal check
- duplicate check
- exposure check
- drawdown check
- live gate status
- execution mode: paper/shadow/live-blocked
- final decision reason

## Website pages

Must be visible in:
- Mission Control
- Trainer Prediction Monitor
- Feature Attribution
- Signal Explainability
- Symbol Universe
- Risk Gateway
- Trader Fleet
- Paper / Shadow Trading
- Audit Ledger
- Live Readiness

## Safety

Do not expose secrets.
Do not show raw private keys/tokens.
Do not imply live trading is enabled.
Live actions remain blocked until final human approval.

REQ_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI_READY
