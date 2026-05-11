# Data Truth And Safety Review

The full visual implementation uses current V2 payloads and explicit evidence-gap behavior.

Data rules preserved:

- `DESIGN_MOCK_DATA_TO_REMOVE` is not imported.
- `READONLY_MARKET_FEED` is surfaced when the payload marks market feed data as read-only.
- `STATIC_PROOF_FIXTURE` remains visible only on the TradingView fallback path.
- Missing decision evidence renders evidence-gap copy instead of invented explanations.
- Signal, orchestrator, risk, and execution identifiers are read from `CockpitPayload.decisions`.
- Monitor, config, exchange, quarantine, Redis, and system atlas panels continue reading V2 proof/runtime payloads.

Safety rules preserved:

- Live trading remains `blocked_human_only`.
- The global live-block banner remains sticky and non-dismissable.
- Mission Control also renders `MissionControlReadinessBanner`.
- Admin/RBAC route structure is unchanged.
- Risk Gateway remains final authority; the orchestrator boundary panel explicitly states this.
- No order placement, cancel, leverage, margin, API key, Redis mutation, or live execution control was added.
- Redis trim approval file was not created.

Operator Proof Dashboard remains evidence/proof-only and was not converted into the main product cockpit.
