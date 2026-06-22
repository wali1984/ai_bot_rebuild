# Hosting And Telemetry Bridge Plan

Generated at: 2026-06-17T15:13:35-04:00

Current local hosting path: Vite serves V2 frontend at `http://127.0.0.1:5173`.

Public dashboard path: `https://dashboard.wajidali.us` must receive fresh `operator_truth` and `operator_runtime/paper_online` payloads through one of:

1. periodic static payload sync from this machine,
2. secured read-only backend telemetry API,
3. VPN/local-only hosting until telemetry bridge is deployed.

Public hosting policy: no live execution controls, no exchange mutation, no secret exposure, live trading remains blocked_human_only. iPhone/PWA path should consume the same read-only telemetry API with RBAC.
