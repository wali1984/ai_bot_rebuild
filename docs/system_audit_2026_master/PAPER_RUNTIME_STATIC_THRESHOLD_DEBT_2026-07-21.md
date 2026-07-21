# Paper runtime static-threshold debt — 2026-07-21

## Decision

The repository cannot truthfully claim that every market-sensitive decision is
adaptive. This remediation does not change threshold semantics: replacing a
gate while repairing the final-fill boundary could create unmeasured candidate
flow and invalidate the safety evidence. The correct target is adaptive market
policy inside explicit protocol, exchange, and immutable safety bounds.

## Classification

| Class | Current examples | Required treatment |
|---|---|---|
| Protocol and arithmetic invariants | finite probabilities in `[0, 1]`; positive price/quantity/notional; aware UTC clocks; `available_at <= decision_time`; closed-candle and latest-unclosed exclusion proof; `notional = quantity * price`; `margin = notional / leverage` | Keep fixed and fail closed. These are definitions, not market-entry policy. |
| Exchange/account constraints | symbol `minQty`, `stepSize`, `maxQty`, minimum notional, signed maintenance bracket and exchange leverage ceiling | Read from authenticated, current account/environment evidence. Never replace them with learned values or defaults. |
| Immutable risk ceilings | operator-authorized paper-only symbol leverage ceilings, liquidation-distance safety, no live routing, no order/margin/leverage mutation, and mandatory final/revocable/write receipts | Keep as upper bounds. Adaptation may contract below them but may not exceed or bypass them. |
| Evidence/certification policy | minimum causal sample coverage, purged holdout requirements, confidence-calibration non-regression, freshness authority TTLs, and final receipt schemas | Version and justify separately. These may control whether evidence is admissible, but must not be described as learned market thresholds. |
| Market-sensitive operating debt | the constants and fallback branches listed below | Replace only through a versioned, PIT-safe policy with shadow replay and bounded rollout evidence. |

## Executable operating debt in the paper path

The following source controls affect ranking, admission, sizing, recovery, or
market interpretation and remain fixed or partly fixed:

- `DIRECTIONAL_COLLAPSE_MAJOR_SIDE_SHARE`,
  `DIRECTIONAL_COLLAPSE_ADAPTIVE_MAX_SHARE_TIGHTENING`, and
  `STRATEGY_MODE_COLLAPSE_MAJOR_MODE_SHARE`.
- `PAPER_DRAWDOWN_RECOVERY_MIN_CONFIDENCE`,
  `PAPER_DRAWDOWN_RECOVERY_MAX_CONFIDENCE`, the 300/1,000-bps drawdown
  tightening interval, `PAPER_DRAWDOWN_RECOVERY_WEAK_EDGE_BPS`, and the 0.25
  recovery size multiplier.
- `PAPER_STRICT_A_CONFIDENCE_THRESHOLD`, the B-grade 0.50–0.74 confidence
  interval, its 0.25 risk cap and 500-bps drawdown stop.
- Positive-edge probation's 0.10 risk cap, 0.65 loss-probability bound and 0.55
  exit-feasibility floor.
- Risk-controller exploration's 0.05 risk cap, 0.72 loss-probability bound and
  0.50 exit-feasibility floor.
- B-grade promotion's fixed win-rate, lower-confidence-bound, expectancy and
  profit-factor requirements.
- Fixed depth-to-liquidity breakpoints, spread/slippage weights, the five-second
  cadence fallback, and other fallback market-shape mappings.
- Halted-book probe ages, confidence bands, size fraction, attempt count and
  slot cap.
- Cross-margin diagnostic shock and beta tables. These are scenario debt, not
  authority to select account margin mode.

The paper-only 75/50/20 leverage ceilings and five-ATR liquidation rule are
operator-authorized immutable ceilings in this audit. They remain static by
design; actual leverage must be the conservative minimum of authenticated
bracket, symbol ceiling, edge uncertainty, liquidity/slippage, volatility,
correlation/cascade, drawdown, margin, concentration and liquidation evidence.

## Safe replacement contract

A market-sensitive constant is eligible for replacement only when the new
policy:

1. consumes only finalized data with explicit `event_time`, `available_at`,
   `feature_cutoff` and `decision_time` ordering;
2. is computed per relevant symbol/timeframe/regime from a bounded historical
   window that excludes the decision's future and untouched holdout;
3. publishes a versioned input material, canonical hash, output, confidence or
   uncertainty, fallback reason and validity interval;
4. contracts to the existing fail-closed safety envelope when evidence is
   missing, stale, invalid, sparse or contradictory;
5. runs in shadow/replay against the fixed policy before affecting sizing or
   admission, with after-cost expectancy and drawdown compared on identical
   rows; and
6. is released slice-by-slice without changing live exchange behavior.

No throughput increase, A+ grade, profitability claim, or 1000x claim follows
from removing a constant. Positive causal after-cost evidence is still
required. Until these replacements are implemented and validated, static
operating debt remains a paper-readiness blocker; protocol and immutable safety
bounds do not.
