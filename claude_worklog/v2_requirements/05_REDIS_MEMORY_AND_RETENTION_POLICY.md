# 05 Redis Memory and Retention Policy

## Purpose
Define memory safety, retention, and audit offload requirements without deleting legacy namespaces.

## Thresholds
- Memory warning threshold: 85%
- Memory elevated threshold: 90%
- Memory critical threshold: 95%

Given runtime evidence (~96.8%), current posture is critical until remediated.

## Hot stream retention strategy
- Keep hot execution/signaling streams bounded by explicit TTL/length budgets per stream category.
- Use rolling caps sized by operational horizon, not unbounded growth.
- Prefer append-only short horizon for operational streams; preserve lineage IDs in compact form.

## Audit ledger offload strategy
- Offload full-fidelity attribution and decision logs to durable audit storage on short intervals.
- Keep Redis as low-latency operational cache/queue, not long-term ledger.
- Offload payload must preserve full lineage tuple and confidence explainability block.

## Safety policies
- On warning/elevated/critical bands, emit observability alerts and stricter sampling diagnostics.
- At critical band, block non-essential telemetry expansion until headroom restored.

## Legacy compatibility
- No deletion or mutation of legacy V1 key contracts as part of V2 rollout.
- V2 retention controls must apply to V2 additive namespaces only.
