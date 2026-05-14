# Live Readiness Preflight Report

Generated: 2026-05-14T10:10:00Z

Status: `LIVE_READINESS_PREFLIGHT_BLOCKED`

## Current Truth

The V2 worker migration sequence is complete, but the system is not ready for live canary. This report replaces the stale 2026-05-13 preflight-ready marker with current blocker truth.

## Preserved Safety

- Live gate: `blocked_human_only`
- Final live approval token: absent
- Redis trim approval: absent
- V2 exchange orders: none
- V2 leverage changes: none
- V2 margin mode changes: none
- Codex legacy mutation: none
- Codex old Redis writes: none

## Runtime State

- Last completed worker: `v2_p2_deployment_helpers`
- Next orchestrator action: `all_workers_complete`
- Follow-up: `proceed_to_v2_local_online_bootstrap_paper_shadow_only`
- P0 progress: `9 / 9`
- P1 progress: `6 / 6`
- P2 progress: `3 / 3`
- V2 state: paper/shadow only

## Live Blockers

| Blocker | Current evidence | Required resolution |
|---|---|---|
| Paper PnL negative | `pnl=-49.12`, `PAPER_PNL_NEGATIVE_BLOCKS_CANARY` | sustained positive paper-shadow evidence without faking profitability |
| Historical paper churn too high | `fill_rate=0.89233792`, `PAPER_FILL_RATE_TOO_HIGH`; new paper fills are now gated by `deny_canary_profile_tightening` | complete a fresh post-tightening soak window with safe fill cadence |
| Paper edge unproven | `win_rate=0.0`, `profit_factor=0.0`, `PAPER_EDGE_UNPROVEN` | prove positive edge over the required window |
| Trainer parity not live-ready | `v2_trainer_bridge` rejects `V2_PAPER_TRAINER_WRAPPER` with `WRAPPER_NOT_LEGACY_HYBRID_PARITY` | current accepted legacy-hybrid or V2-native trainer prediction evidence |
| Trade permission evidence not canary-ready | account evidence is read-only; trade permission is `TRADE_PERMISSION_EVIDENCE_PRESENT_READONLY`; canary blockers include `TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY` | read-only proof of account/trade permission sufficient for canary, without secrets or mutation |
| Legacy runtime still observed | legacy `rl.hybrid_trainer`, `rl.orchestrator_worker`, `ingest/live_coinank.py`, and trainer monitors are running outside V2 | containment decision or shutdown must be handled by an explicit legacy containment task |
| Public freshness guard blocked | stale public artifacts still report stale or overbroad ready/profitability claims | update or quarantine stale public truth artifacts |

## Decision

No live approval was created. No live trading was enabled. The Symbol Universe public payload is now present with `live_symbols=[]`, but the correct operating state remains `blocked_human_only` until every blocker above is cleared with fresh evidence.
