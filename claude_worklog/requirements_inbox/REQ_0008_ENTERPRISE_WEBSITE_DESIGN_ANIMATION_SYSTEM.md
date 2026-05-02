# Requirement 0008 — Enterprise Website Design and Animation System

Improve the V2 enterprise website into a polished animated mission-control interface.

Objective:
The website must become the operating center for AI BOT REBUILD, not a basic dashboard.

Design goals:
- modern dark-mode-first enterprise UI
- animated but not distracting
- live safety state always visible
- lineage from data → features → trainer → signal → risk → trader
- system health at a glance
- mobile/iPhone-ready layout
- public/admin separation
- approval center
- live-blocked state
- Claude/Codex/Ollama activity
- symbol universe heatmap/ranking
- trainer GPU and prediction worker health
- ingestor freshness map
- risk gateway decisions
- paper/shadow/live-readiness progression

Allowed scope:
- v2/frontend/
- v2/backend API stubs needed for frontend contracts
- frontend tests
- docs under claude_worklog/phase2_core_rebuild/frontend_design/
- non-live mock data
- local-only animation/UI state

Forbidden:
- live trading
- Redis writes
- legacy mutation
- deployment
- production secrets

Required pages/components:
- Mission Control
- Live Readiness
- Symbol Universe
- Ingestor Health
- Feature Attribution
- Trainer GPU Health
- Prediction Worker Health
- Signal Explainability
- Risk Gateway
- Trader Fleet
- Paper/Shadow Trading
- Audit Ledger
- Agent Supervisor
- Claude/Codex/Ollama Activity
- Approval Center
- Public Landing
- Public Status
- Login / step-up auth flow

Animation requirements:
- page transitions
- status pulse indicators
- data-flow graph animations
- risk-gate block animations
- streaming activity timeline
- symbol heatmap hover/focus states
- mobile-friendly slide panels

Animations must not block usability or hide critical risk warnings.

Validation:
- frontend static/compile checks
- component smoke tests
- route smoke tests
- accessibility basics
- no secrets
- no live API dependency
- no deployment

Codex must verify:
- no live behavior
- public/admin separation
- safety banners
- live-blocked state
- mobile readiness
- critical operational pages represented
- animations are non-blocking

REQ_ENTERPRISE_WEBSITE_DESIGN_ANIMATION_SYSTEM_READY
