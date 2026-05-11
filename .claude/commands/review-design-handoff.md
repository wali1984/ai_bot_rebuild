# Review Claude Design Handoff

Use this command to review the latest Claude Design -> Claude Code handoff without treating design output as runtime truth.

## Required Flow

1. Inspect the latest folder under `claude_worklog/frontend_design/handoffs/`.
2. Verify `DESIGN_HANDOFF.md` exists for new handoffs, or record a legacy-handoff gap for older folders.
3. Verify these maps exist or are explicitly marked missing:
   - `ROUTE_MAP.json`
   - `COMPONENT_MAP.json`
   - `DATA_CONTRACT_MAP.json`
   - `SAFETY_STATE_MAP.json`
   - `MISSING_EVIDENCE_MAP.md`
4. Inspect current V2 frontend routes:
   - `v2/frontend/src/router.tsx`
   - `v2/frontend/src/pages/registry.ts`
   - `v2/frontend/src/pages/**`
   - `v2/frontend/src/components/**`
5. Map design components to real V2 payloads or explicit evidence gaps.
6. Identify mock data to remove.
7. Identify placeholder-only modules.
8. Identify backend/payload gaps.
9. Generate a Claude Code implementation task only for safe non-live UI changes.
10. Generate a Codex review checklist.
11. Keep live trading blocked.
12. Forbid mock data as truth.
13. Require Codex review before any READY marker.

## Source Of Truth

Do not treat Claude Design output as source of truth. V2 artifacts, runtime monitor payloads, read-only market/account payloads, audit ledger, risk decisions, trainer lineage, script registry, and GO/NO-GO markers remain source of truth.

## Safety Boundary

Do not modify `/home/wali/Desktop/AI BOT`. Do not mutate Redis. Do not create Redis trim approval files. Do not place/cancel/modify exchange orders. Do not change leverage, margin, or position mode. Do not enable live trading. Do not expose secrets.
