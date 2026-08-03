# Same-Day Cutover CEO Packet

Status: LIVE_CANARY_NOT_READY
Generated UTC: 2026-07-08T19:55:00Z
Headline: Live canary is not ready; provider actual-data evidence is incomplete.

## Provider Actual Data
- CoinGlass: GREEN actual=True heartbeat_only=False
- Moralis: GRAY actual=False heartbeat_only=True

## Live Control
- Live gate: blocked_human_only
- Live ready: False
- Live-ready from probation: False
- Operator approval required for live: True
- Final marker: V2_SAME_DAY_PRODUCTION_CUTOVER_DATA_FEATURE_TRAINER_PREEMPTIVE_AND_LIVE_CANARY_BLOCKED

## Hard Blocks
- none

## Provider Readiness Blockers
- moralis_actual_payload_absent:CONFIGURED_NO_WATCHLIST

## Next Patch
- configure Moralis wallet/token watchlist or subscription access, rerun provider loop, and confirm actual on-chain payloads

## Safety Assertions
- API keys are not exposed.
- Optional provider failures are not core-blocking.
- Heartbeat-only payloads are not green.
- Moralis is not polled on every symbol every minute.
- CoinGlass public limit is not exceeded.