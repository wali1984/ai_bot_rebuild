# V2 Data Plane Independence Plan

Generated: 2026-05-11T07:45:58.228145+00:00

Status: `V2_DATA_PLANE_INDEPENDENCE_ACCELERATION_READY`

V2 becomes the source of truth by owning bounded Redis transport/cache, durable DB history/audit/features/predictions/signals/executions, read-only legacy importers, and clean cutover packets. Legacy remains passive evidence/facade only until V2 proves independent market-data ingress and storage contracts.

Priority: if clean V2 cutover is closer than legacy Redis surgery, prioritize V2 bounded data plane and durable storage. Do not add net-new legacy logic.
