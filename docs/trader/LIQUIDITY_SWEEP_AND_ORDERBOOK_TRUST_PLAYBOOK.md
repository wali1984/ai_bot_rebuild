# Liquidity, Sweep, and Orderbook Trust Playbook (Trader)

Last verified: 2026-07-07 00:15 EST | Policy source: docs/master/MICROSTRUCTURE_TRUST_AND_PUBLIC_ORDERBOOK_POLICY.md

## The one rule
The bot never takes a public orderbook at face value. Depth you can see is not
depth you can trade until it has been observed to PERSIST, on more than one venue.

## How to read the trust fields on any candidate/intent
| Field | Meaning | Good |
|---|---|---|
| `microstructure_trust_score` | composite 0-1 | > 0.65 full size; 0.45-0.65 reduced |
| `book_depth_persistence_score` | depth stays >=55% of window max over >=5s | > 0.5 |
| `book_depth_persistence_reason` | STABLE_DEPTH_WINDOW / DEPTH_UNSTABLE / INSUFFICIENT_DEPTH_WINDOW / MISSING_DEPTH_FIELDS | STABLE |
| `cross_venue_confirmation_score` | Binance vs KuCoin agreement | >= 0.5 |
| `microstructure_action` | ALLOW / REDUCE_SIZE / SHADOW_ONLY / NO_TRADE | context |
| `sweep_risk_score` / `liquidation_cascade_risk` | proximity to stop/liq clusters | low |

## Sweep/fakeout handling
- Liquidation-cluster proximity raises `sweep_risk_score`; candidates near dense
  liq zones are blocked or reduced BEFORE cost modeling.
- `book_trade_divergence` (book says one side, tape says the other) is a spoof
  signature: divergence 1.0 suppresses trust.
- Post-sweep reversal probability is modeled; entries against an in-progress
  sweep are NO_TRADE, liquidity_sweep_reversal strategy activates only after
  cluster clearance + tape confirmation.

## What REDUCED_SIZE means for you
Paper-only bootstrap at a fraction of normal budget. Its outcomes never count as
A-grade evidence and can never be promoted to live sizing. If you see full-size
entries while trust <0.65, that is a bug — report immediately.

## Interpreting "why is nothing trading"
Read the intent's `paper_opportunity_tier_reason`:
- BLOCK_INSUFFICIENT_LIQUIDITY on low-trust symbols = fail-closed working as designed
- EXPECTED_EDGE_NOT_FAVORABLE_AFTER_COST / BLOCK_NO_EDGE = model has no edge after
  spread+slippage+funding at this moment (honest rejection)
- MARKET_STATE_INTEGRITY_INVALID = data problem; escalate if persistent (see debug
  commands in the master policy doc)

## Verify commands
```bash
redis-cli GET v2:microstructure:trust_score:ETHUSDT:1m | python3 -m json.tool | grep -E "trust|persistence|cross_venue|action"
redis-cli GET v2:paper:intents | python3 -c "import json,sys,collections; xs=json.load(sys.stdin); print(collections.Counter(x['paper_opportunity_tier_reason'] for x in xs))"
```

## Purpose
Give traders a practical interpretation of liquidity sweeps, depth persistence, public orderbook trust, and why candidates are blocked or reduced.

## Source Files
- `v2/backend/app/services/microstructure_trust/liquidation_sweep_detector.py`
- `v2/backend/app/services/microstructure_trust/orderbook_adversarial_features.py`
- `v2/backend/app/services/a_plus_trade_gate/service.py`

## Runtime Redis Keys/API Routes
- Redis: `v2:microstructure:trust_score:*`
- Redis: `v2:paper:performance_governor_status`
- API: `/api/v2/paper/runtime-status`

## Failure Modes
- Sweep risk ignored and entries allowed into stop/liquidation clusters.
- Public orderbook shown as final trust without persistence and venue confirmation.
- REDUCE_SIZE outcomes counted as final A+.

## Debug Commands
- `redis-cli GET v2:microstructure:trust_score:ETHUSDT:1m | python3 -m json.tool`
- `redis-cli GET v2:paper:new_entry_emergency_halt_status | python3 -m json.tool`

## Validation Commands
- `.venv/bin/pytest -q v2/backend/tests/unit/services/microstructure_trust`
- `.venv/bin/pytest -q v2/backend/tests/unit/services/a_plus_trade_gate`

## Evidence Artifacts
- `goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/PHASE_C_MICROSTRUCTURE_TRUST_DISTRIBUTION.json`

