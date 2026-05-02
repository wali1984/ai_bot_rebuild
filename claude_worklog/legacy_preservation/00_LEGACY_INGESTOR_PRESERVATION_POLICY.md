# Legacy Ingestor Preservation Policy

## Objective
Preserve existing ingestors as production-learned components. Do not rewrite or refactor them casually.

## Rules
- Do not modify live legacy ingestors in /home/wali/Desktop/AI BOT.
- Do not rewrite legacy ingestor logic in V2 unless explicitly required and reviewed.
- V2 should wrap/adapt existing ingestor behavior.
- Only symbol universe inputs may change, and those changes must happen through controlled symbol configuration/adapters.
- Existing parsing, API request behavior, timing, error handling, source-specific assumptions, and field mapping must be preserved unless Codex/Claude review approves a targeted fix.
- Any ingestor modification must include:
  - before/after hash
  - reason
  - risk assessment
  - replay/smoke test
  - Codex review
  - rollback plan

## Required V2 approach
- Build `legacy_compatible` ingestor adapters.
- Feed symbols dynamically through the V2 Symbol Universe service.
- Preserve source-specific settings from legacy config.
- Add contract tests around outputs.
- Add freshness and health monitoring.
- Never assume ingestors are interchangeable.

## Data sources to preserve
- Binance Futures
- CoinAnk
- CoinAPI
- KuCoin
- liquidation feeds
- technical/realtime price feeds
- future ingestors discovered in legacy inventory

LEGACY_INGESTOR_PRESERVATION_READY
