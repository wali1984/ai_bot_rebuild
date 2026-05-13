# Admin AI Evidence Query Contract

Generated: 2026-05-13T21:18:35Z

Admin AI may answer these support-lane questions only when it cites concrete payload or evidence paths:
- Which V2 workers are missing?
- Which paper-shadow metrics block canary?
- Why is canary not ready?
- What is current account permission evidence?
- What is trade permission evidence?
- Which payloads are stale?
- Which worker failed Codex?
- Which scripts are still legacy-only?
- Which worker should Claude port next?

Rules:
- Admin AI must cite payload/evidence paths.
- Admin AI must not guess.
- Admin AI must say evidence missing when evidence is missing.
- Admin AI cannot enable live.
- Admin AI cannot change leverage or margin.
- Admin AI cannot write old Redis.
- Admin AI cannot create approval tokens.

Canonical support payloads:
- `v2_worker_inventory.json`
- `public_payload_freshness_guard.json`
- `paper_shadow_metrics_analysis.json`
- `account_permission_contract_status.json`
- `operator_dashboard_payload.json`
