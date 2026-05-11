# Legacy To V2 Contract Map

- Legacy market/trainer/signal streams -> V2 read-only importers with source freshness and evidence pointer.
- Legacy feature/model logic -> V2 wrappers/adapters with versioned contracts and tests.
- Legacy executions -> V2 execution ledger/audit events with provenance/dedupe attribution.
- Legacy Redis liquidation history -> V2 durable history store/archive; Redis remains transport/cache only.
- Legacy runtime monitors -> V2 monitor center records and dashboard payloads.
