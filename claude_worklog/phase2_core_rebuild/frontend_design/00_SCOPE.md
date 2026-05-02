# Phase 2F — Enterprise Frontend Design and Animation System — Scope

This phase covers REQ_0008 (Enterprise Website Design and Animation System).
It runs in parallel with REQ_0006 Phase 2E1.C.α (trainer liveness domain layer)
because the two work-streams touch disjoint paths:

- REQ_0006 Phase 2E1.C.α writes only under
  `v2/backend/app/domain/trainer_liveness/` and
  `v2/backend/tests/unit/domain/trainer_liveness/`.
- REQ_0008 Phase 2F writes only under `v2/frontend/` and
  `claude_worklog/phase2_core_rebuild/frontend_design/` (and supervisor
  task definitions). Phase 2F.A.0 — the milestone authored by this
  planner turn — restricts itself further to documentation under
  `claude_worklog/phase2_core_rebuild/frontend_design/` only and does
  not modify `v2/frontend/`.

## Active requirement source

`claude_worklog/requirements_inbox/REQ_0008_ENTERPRISE_WEBSITE_DESIGN_ANIMATION_SYSTEM.md`.

## Phase 2F objective

Take the existing `v2/frontend/` scaffold (React 18 + TypeScript + Vite +
React Router + Playwright; ~30 page directories already present) and
upgrade it into the enterprise mission-control UI mandated by REQ_0008
without enabling live behavior, without writing Redis, without modifying
legacy, and without deploying.

## In scope

- design-system tokens (dark-mode-first, accessible color/contrast)
- typography scale and spacing scale
- animation primitives (page transitions, status pulses, data-flow
  graphs, risk-gate block animations, streaming activity timelines,
  symbol heatmap focus states, mobile slide panels) implemented as
  composable React components or CSS-only primitives
- live safety state always visible (LIVE TRADING: BLOCKED banner,
  approval-required indicator, kill-switch state)
- public/admin separation of routes and chrome
- mobile/iPhone-ready responsive layout (PWA-friendly)
- approval center, agent activity stream, audit ledger surfaces
- lineage visualization (data → features → trainer → signal → risk →
  trader)
- non-live mock data fixtures for development and Playwright tests

## Out of scope (Phase 2F)

- Trainer parity service implementation (REQ_0006 / Phase 2E)
- Redis read/write
- Live exchange API integration
- Production deployment artifacts
- Production secrets handling beyond manifest references
- Modifications to `/home/wali/Desktop/AI BOT/`
- Any change to `legacy_reference/`
- Any subprocess invocation from frontend code
- Any direct import of legacy modules

## Hard exclusions for every Phase 2F sub-phase

- No live trading enable.
- No Redis client construction in frontend code.
- No exchange API call in frontend code.
- No legacy module import.
- No production secret in any frontend or doc artifact.
- No deployment script invocation.
- No production migration.
- No removal of the existing `LIVE TRADING: BLOCKED` semantics.

## Predecessor markers

This phase has no upstream Codex/impl gate; it is independent of the
2E trainer parity track. The only required predecessor is the existence
of REQ_0008 in the requirements inbox, which the planner has confirmed.

## Phase-wide marker emitted by this scope file

PHASE2F_FRONTEND_DESIGN_SCOPE_READY
