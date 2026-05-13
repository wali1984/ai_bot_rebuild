# Website Current Data Proof

Generated: 2026-05-13T04:43:38.228869Z

Local and public route screenshots are stored under `screenshots/local/` and `screenshots/public/`.

Summary:
- Routes checked: 20
- Blocked routes: 12
- Dangerous controls enabled: 0
- Static fixture routes: local /admin/signals?role=admin, local /admin/executions?role=admin, public /admin/signals?role=admin, public /admin/executions?role=admin
- Hist-pattern visible routes: local /admin/signals?role=admin, local /admin/executions?role=admin, local /admin/risk-control?role=admin, public /admin/signals?role=admin, public /admin/executions?role=admin, public /admin/risk-control?role=admin
- Current-lineage missing routes: local /admin/mission-control?role=admin, local /admin/trainer-prediction-monitor?role=admin, local /admin/signal-explainability?role=admin, local /admin/script-registry?role=admin, public /admin/mission-control?role=admin, public /admin/trainer-prediction-monitor?role=admin, public /admin/signal-explainability?role=admin, public /admin/signals?role=admin, public /admin/executions?role=admin, public /admin/paper-trading?role=admin, public /admin/risk-control?role=admin, public /admin/live-readiness?role=admin, public /admin/script-registry?role=admin, public /admin/claude-admin-ai?role=admin
- Truth status: `WEBSITE_DATA_TRUTH_INCOMPLETE`

This is the key finding: route availability is not enough. Several routes load but do not show the current prediction/signal/risk IDs, and Signals/Executions still expose static/historical proof material.

| Scope | Route | HTTP | Current IDs | Hist | Fixture | Live blocked | Status | Blockers |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| local | /admin/mission-control?role=admin | 200 | False | False | False | False | BLOCKED | current_lineage_id_not_visible, live_blocked_banner_not_visible_in_scraped_text |
| local | /admin/trainer-prediction-monitor?role=admin | 200 | False | False | False | False | BLOCKED | current_lineage_id_not_visible, live_blocked_banner_not_visible_in_scraped_text |
| local | /admin/signal-explainability?role=admin | 200 | False | False | False | False | BLOCKED | current_lineage_id_not_visible, live_blocked_banner_not_visible_in_scraped_text |
| local | /admin/signals?role=admin | 200 | True | True | True | True | BLOCKED | STATIC_PROOF_FIXTURE_visible, hist_pattern_visible_anywhere_requires_context_review |
| local | /admin/executions?role=admin | 200 | True | True | True | True | BLOCKED | STATIC_PROOF_FIXTURE_visible, hist_pattern_visible_anywhere_requires_context_review |
| local | /admin/paper-trading?role=admin | 200 | True | False | False | True | PASS |  |
| local | /admin/risk-control?role=admin | 200 | True | True | False | True | PASS | hist_pattern_visible_anywhere_requires_context_review |
| local | /admin/live-readiness?role=admin | 200 | True | False | False | True | PASS |  |
| local | /admin/script-registry?role=admin | 200 | False | False | False | False | BLOCKED | current_lineage_id_not_visible, live_blocked_banner_not_visible_in_scraped_text |
| local | /admin/claude-admin-ai?role=admin | 200 | True | False | False | True | PASS |  |
| public | /admin/mission-control?role=admin | 200 | False | False | False | False | BLOCKED | current_lineage_id_not_visible, live_blocked_banner_not_visible_in_scraped_text |
| public | /admin/trainer-prediction-monitor?role=admin | 200 | False | False | False | False | BLOCKED | current_lineage_id_not_visible, live_blocked_banner_not_visible_in_scraped_text |
| public | /admin/signal-explainability?role=admin | 200 | False | False | False | False | BLOCKED | current_lineage_id_not_visible, live_blocked_banner_not_visible_in_scraped_text |
| public | /admin/signals?role=admin | 200 | False | True | True | True | BLOCKED | STATIC_PROOF_FIXTURE_visible, hist_pattern_visible_anywhere_requires_context_review, current_lineage_id_not_visible |
| public | /admin/executions?role=admin | 200 | False | True | True | True | BLOCKED | STATIC_PROOF_FIXTURE_visible, hist_pattern_visible_anywhere_requires_context_review, current_lineage_id_not_visible |
| public | /admin/paper-trading?role=admin | 200 | False | False | False | True | PASS | current_lineage_id_not_visible |
| public | /admin/risk-control?role=admin | 200 | False | True | False | True | PASS | hist_pattern_visible_anywhere_requires_context_review, current_lineage_id_not_visible |
| public | /admin/live-readiness?role=admin | 200 | False | False | False | True | PASS | current_lineage_id_not_visible |
| public | /admin/script-registry?role=admin | 200 | False | False | False | False | BLOCKED | current_lineage_id_not_visible, live_blocked_banner_not_visible_in_scraped_text |
| public | /admin/claude-admin-ai?role=admin | 200 | False | False | False | True | PASS | current_lineage_id_not_visible |
