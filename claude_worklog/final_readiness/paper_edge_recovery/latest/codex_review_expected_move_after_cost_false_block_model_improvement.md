# Codex Review - Expected Move After Cost False-Block Model Improvement

Result: PASS_WITH_EDGE_PENDING

Generated: `2026-05-15T10:00:33Z`

## Findings

- Shadow outcome evidence shows `15` blocked intents later beat estimated costs, with `43` completed observations and `90` candidate observations.
- `2` completed outcomes were preserved after the rolling candle window moved on; this prevents evidence regression.
- These are model-review signals only. They do not permit fills from hindsight and do not prove positive paper edge.
- Current paper PnL remains `-49.197409` and post-filter edge remains unproven.
- The current V2 paper status keeps top-level `live_gate=blocked_human_only` and `live_symbols=[]`.

## Required Next Work

Improve native expected-move-after-cost coverage and calibration using trainer/feature evidence available at decision time. Do not lower thresholds, do not loosen the strict gate, and do not authorize fills from future outcome labels.

## Safety

No live approval, legacy shutdown approval, old Redis write, exchange mutation, leverage change, margin-mode change, final approval token, or Redis trim approval token was introduced.
