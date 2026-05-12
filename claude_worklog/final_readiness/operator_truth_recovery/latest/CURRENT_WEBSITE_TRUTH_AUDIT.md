# Current Website Truth Audit

Generated at: 2026-05-12T00:29:57.739Z

| Route | Panel | Current data source | Source file/API | Source generated_at | Age seconds | Real-time? | Static fixture? | Stale? | Missing evidence? | Operator risk |
|---|---|---|---|---:|---:|---|---|---|---|---|
| Mission Control | Truth status strip | REALTIME_RUNTIME_EVIDENCE | operator_truth/latest/operator_truth_payload.json | 2026-05-12T00:29:57.739Z | n/a | yes | no | no | no | Current snapshot or labeled proof. |
| Mission Control | Legacy runtime monitor | REALTIME_RUNTIME_EVIDENCE / MISSING_EVIDENCE | operator_truth/latest/operator_truth_payload.json | 2026-05-12T00:29:57.739Z | n/a | yes | no | yes | yes | Do not treat as live truth. |
| Mission Control | Trainer prediction preview | STATIC_PROOF_FIXTURE / MISSING_EVIDENCE | operator_truth/latest/operator_truth_payload.json | 2026-05-12T00:29:57.739Z | n/a | no | yes | yes | yes | Do not treat as live truth. |
| Mission Control | Signal explainability preview | STATIC_PROOF_FIXTURE | operator_truth/latest/operator_truth_payload.json | 2026-05-12T00:29:57.739Z | n/a | no | yes | no | no | Current snapshot or labeled proof. |
| Mission Control | TradingView chart | READONLY_MARKET_FEED / STATIC_PROOF_FIXTURE fallback | TradingViewWidget + enterprise cockpit payload | 2026-05-12T00:29:57.739Z | n/a | no | yes | no | no | Current snapshot or labeled proof. |
| Monitor Center | Monitor scripts | RUNTIME_MONITOR_PAYLOAD | enterprise cockpit payload + operator_truth payload | 2026-05-12T00:29:57.739Z | n/a | no | no | no | no | Current snapshot or labeled proof. |
| Trainer Prediction Monitor | Prediction stream | TRAINER_RUNTIME_EVIDENCE_MISSING | operator_truth/latest/operator_truth_payload.json | 2026-05-12T00:29:57.739Z | n/a | no | no | no | no | Current snapshot or labeled proof. |
| Signal Explainability | Lineage details | STATIC_PROOF_FIXTURE | operator_truth/latest/operator_truth_payload.json | 2026-05-12T00:29:57.739Z | n/a | no | yes | no | no | Current snapshot or labeled proof. |
| Build Validation Status | Proof freshness | V2_PROOF_ARTIFACT / STALE_PAYLOAD | operator_truth/latest/operator_truth_payload.json | 2026-05-12T00:29:57.739Z | n/a | no | no | no | no | Current snapshot or labeled proof. |
| Operator Proof Dashboard | Proof/evidence route | V2_PROOF_ARTIFACT / STATIC_PROOF_FIXTURE | existing proof artifacts | 2026-05-12T00:29:57.739Z | n/a | no | yes | no | no | Current snapshot or labeled proof. |

Direct conclusion: the old cockpit payload is a static proof fixture. The new operator truth strip is the only current snapshot source for supervisor/process truth in this pass.
