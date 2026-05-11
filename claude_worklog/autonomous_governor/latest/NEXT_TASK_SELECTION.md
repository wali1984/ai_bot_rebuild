# Next Task Selection

Selected primary task: `v2_online_readiness_acceleration`

Parallel Codex tasks: `codex_parallel_audit_plan`, `targeted_online_readiness_reviews`, `enterprise_ui_polish_codex_review`

UI polish lane: `parallel`, not primary.

Reason: The latest objective is to bring V2 online safely, not to polish UI in isolation. The 069D2 chain is READY, Claude quota is ready, git is clean, and Codex has passed targeted aggregator/frontend reviews while broad online-readiness audit still carries real runtime blockers.

Why live is still blocked: Phase 3C runtime evidence remains blocked with Redis memory pressure, trainer liveness degradation, duplicate exchange-order-id observations, and lineage gaps. Final live/capital approval is not selected.

Why Redis trim is non-blocking: the exact Phase 3H trim approval file is absent. No XTRIM may run. V2 data-plane independence and GUI/product work continue without Redis mutation.

How this advances online readiness: prioritize V2-owned read-only rollups, banner API/UI integration, bounded V2 Redis policy, durable DB history/audit ownership, monitor continuity, and risk/degraded-state fail-closed work.

How legacy intelligence is preserved: legacy trainer/models/features remain read-only evidence and can be wrapped into V2 contracts; ownership moves into V2 data contracts, audit ledgers, and durable stores.

How old failure modes are avoided: no legacy writes, no unbounded Redis history as permanent truth, no live order/leverage/margin path, no stale/missing attribution bypass, no UI-only fake-ready markers.
