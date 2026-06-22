# REAL_RUNTIME_TRUST_FINDINGS.md

Status: Code Green, Runtime Evidence Pending

## Summary

As of the latest workspace state:

- Backend test suite is green.
- Trust-boundary trading-path tests are green.
- Strict verifier is green in the current workspace state.
- Recorded-state / runtime replay verification is not fully green yet.
- The system is not market-ready.
- No new model-performance work, new providers, strategy expansion, or live enablement should begin until runtime replay evidence is clean.

## Important separation

This project currently has three different trust layers:

| Layer | Status | Meaning |
|---|---:|---|
| Backend code/tests | Green | Code contracts and regression tests pass |
| Strict verifier/export checks | Green in current workspace | Exported evidence format and current strict checks pass |
| Recorded-state/runtime replay verification | Pending / red | Real runtime replay evidence still requires cleanup, quarantine, refresh, and re-verification |

Backend green does not mean market-ready.

Strict verifier green does not mean the bot should trade live.

Recorded runtime replay must also prove that approved decisions, blocked decisions, MTF snapshots, replay snapshots, feature timestamps, and risk records are complete and reconstructable.

## Market-readiness gate

Do not consider the system market-ready until all of the following are true on the live runtime evidence set:

- Backend tests: green
- Strict verifier exit code: 0
- Recorded-state/runtime replay verifier exit code: 0
- Critical failures: 0
- Replay snapshots exported: > 0 when approvals exist
- Missing replay snapshots: 0
- Missing MTF snapshots: 0
- Missing feature `available_at`: 0
- Missing feature `feature_cutoff`: 0
- Abnormal OHLC: 0
- Missing required MTF evidence for approved decisions: 0
- Approved risk records have replay and MTF linkage
- No stale pre-enforcement prediction, feature, candle, or risk records are model-consumable or approval-consumable
- Dirty states cannot reach trainer, PPO, MASA, paper execution, or risk approval
- Live order submission remains disabled
- Replay missing count: 0
- Replay reconstruction failure count: 0
- Approved decision without replay reconstruction: 0
- Approved decision without MTF reconstruction: 0

## Current operational decision

Freeze these activities:

- no model-performance work
- no new providers
- no Cielo / Moralis / Chainbase / Dune / GMGN integration
- no strategy expansion
- no PPO/MASA optimization
- no live trading enablement

Next phase:

1. Refresh affected runtime workers.
2. Quarantine or expire stale unsafe runtime keys.
3. Re-export runtime evidence.
4. Run strict verification.
5. Run recorded-state/runtime replay verification.
6. Confirm zero critical runtime evidence failures.
