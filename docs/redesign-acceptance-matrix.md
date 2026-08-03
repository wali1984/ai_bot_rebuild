# Redesign Acceptance Matrix (Pre-redesign)
Generated: 2026-06-12T22:22:41.000Z

## Baseline state
| check | status | evidence |
|---|---|---|
| Inventory docs | PASS | route, source, ui-defect docs generated |
| Brand cleanup | BLOCKED | `AI BOT V2`, "Control Plane", and related operator labels are still present in trader-facing files |
| Route separation | BLOCKED | operator/admin pages remain discoverable in trader surfaces |
| Auth integrity | BLOCKED | role override via URL/session path still implemented |
| Paper-mode communication | BLOCKED | banner exists but is not standardized across all trading surfaces |
| Data source readiness | BLOCKED | missing high-priority market/symbol/portfolio/signals/positions endpoints |
| Design system baseline | NOT STARTED | no shared tokenized component system for redesign yet |
| Test evidence | NOT STARTED | no automated acceptance suite for Codex 5.5 gates yet |

## Route gate checklist
| page id | route status | blocker |
|---|---|---|
| admin-war-room | ADMIN | developer wording in route metadata |
| ai-brain | ADMIN | requires visual/data verification |
| alerts | TRADER | requires visual/data verification |
| audit-ledger | ADMIN | requires visual/data verification |
| build-validation-status | ADMIN | requires visual/data verification |
| claude-admin-ai | ADMIN | developer wording in route metadata |
| codex-review-center | ADMIN | developer wording in route metadata |
| config | ADMIN | requires visual/data verification |
| config-admin | ADMIN | requires visual/data verification |
| coverage-system-atlas | ADMIN | requires visual/data verification |
| exchange-manager | ADMIN | requires visual/data verification |
| execution-admin | ADMIN | requires visual/data verification |
| executions | ADMIN | requires visual/data verification |
| executive-status | ADMIN | requires visual/data verification |
| external-manual-position-quarantine | ADMIN | requires visual/data verification |
| history | ADMIN | requires visual/data verification |
| ingestors | ADMIN | requires visual/data verification |
| liquidation-bridge | ADMIN | requires visual/data verification |
| live-readiness | ADMIN | requires visual/data verification |
| login | PUBLIC | requires visual/data verification |
| logs-errors | ADMIN | requires visual/data verification |
| market | PUBLIC | requires visual/data verification |
| market-intelligence | ADMIN | requires visual/data verification |
| markets | PUBLIC | requires visual/data verification |
| mission-control | ADMIN | developer wording in route metadata |
| mobile-iphone-readiness | ADMIN | requires visual/data verification |
| monitor-center | ADMIN | requires visual/data verification |
| ollama-local-assistant | ADMIN | requires visual/data verification |
| operator-proof-dashboard | ADMIN | developer wording in route metadata |
| orchestrator-admin | ADMIN | requires visual/data verification |
| paper-trading | ADMIN | requires visual/data verification |
| permanent-migration | ADMIN | requires visual/data verification |
| positions | ADMIN | requires visual/data verification |
| public-landing | PUBLIC | developer wording in route metadata |
| public-landing-v2 | PUBLIC | developer wording in route metadata |
| public-status | PUBLIC | requires visual/data verification |
| replay | ADMIN | requires visual/data verification |
| report-center | ADMIN | developer wording in route metadata |
| risk-control | ADMIN | requires visual/data verification |
| script-registry | ADMIN | requires visual/data verification |
| signal-explainability | ADMIN | requires visual/data verification |
| signals | ADMIN | requires visual/data verification |
| strategy-admin | ADMIN | requires visual/data verification |
| strategy-backtesting | ADMIN | requires visual/data verification |
| symbols | ADMIN | requires visual/data verification |
| system-health | ADMIN | requires visual/data verification |
| technical-analysis | ADMIN | requires visual/data verification |
| trader | ADMIN | requires visual/data verification |
| trainer-admin | ADMIN | requires visual/data verification |
| trainer-prediction-monitor | ADMIN | requires visual/data verification |
| user-status | PUBLIC | requires visual/data verification |

## Phase 0 deliverables status
| deliverable | status | notes |
|---|---|---|
| Route inventory | PASS | `docs/route-inventory-before-redesign.md` present and updated from current router/registry/navigation files |
| Data source inventory | PASS | `docs/data-source-inventory.md` present, includes API gap list |
| UI defect log | PASS | `docs/ui-defect-log-before.md` present with baseline findings |
| Redesign acceptance matrix baseline | PASS | this file updated with current blockers |
| API gap register | NOT STARTED | now required by phase 0; added in this pass as part of this action |
| Launch readiness | NOT STARTED | now required by phase 0; added in this pass as part of this action |
| Screenshot matrix (before) | BLOCKED | required captures are not yet present in repo for `/`, `/dashboard`, `/markets`, `/trade`, `/status`, `/login` |
