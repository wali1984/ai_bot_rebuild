# Runtime Truth Bridge Report

Generated at: 2026-05-12T02:59:18.340Z

The hosted dashboard is static unless a current read-only runtime bridge publishes operator truth. The supported bridge for this pass is:

```bash
cd v2/frontend && npm run build:operator-truth
```

Required public output:

- v2/frontend/public/operator_truth/latest/operator_truth_payload.json

Public hosting options:

1. Periodically sync operator_truth_payload.json to the hosted dashboard.
2. Replace the static payload with a secured read-only backend API.
3. Keep the dashboard local/VPN-only until a telemetry bridge exists.

The UI treats stale runtime payloads as STALE_PAYLOAD, static proofs as STATIC_PROOF_FIXTURE, and missing current evidence as MISSING_EVIDENCE.
