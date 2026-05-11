# Orchestrator / Risk Gateway Boundary

The orchestrator is not redundant: it proposes, coordinates, ranks, enriches, and deconflicts candidates. The Risk Gateway is final authority. Trader executes only approved execution intents. Orchestrator cannot bypass risk gateway. Risk blocks stale/missing/confidence/margin/leverage/duplicate/kill-switch issues, and every decision must emit an audit event.
