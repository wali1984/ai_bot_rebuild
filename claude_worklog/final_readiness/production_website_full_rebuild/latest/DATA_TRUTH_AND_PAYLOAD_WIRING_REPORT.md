# Data Truth And Payload Wiring Report

Canonical source order:

1. `v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json`
2. `v2/frontend/public/operator_truth/latest/operator_truth_bridge_payload.json`
3. `v2/frontend/public/operator_runtime/legacy_live_bridge/latest/legacy_live_bridge_status.json`
4. Read-only market/live_coinank payloads
5. Proof/static archives only in archive pages

Runtime status: `PAPER_RUNTIME_ONLINE_ACTIVE`
Truth bridge status: `PAPER_ONLINE_CANONICAL_TRUTH_ACTIVE`
Legacy bridge status: `CURRENT`

Rules enforced: `hist_*` is not current truth, `STATIC_PROOF_FIXTURE` cannot dominate Mission Control, stale payloads are warning data, and missing data names the missing source.
