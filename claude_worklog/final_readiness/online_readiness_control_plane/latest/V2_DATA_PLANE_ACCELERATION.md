# V2 Data Plane Acceleration

V2 must own bounded Redis transport/cache plus durable DB history/audit/features/predictions/signals/executions. Legacy is read-only source/facade until clean cutover with freeze, backup, final sync, rollback point, and explicit cutover packet.
