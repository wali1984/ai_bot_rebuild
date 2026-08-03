# NERVYX ONE — Admin Portal Rebuild Release Gate

**Branch:** `claude/website-admin-final`  
**Gate date:** 2026-06-23  
**Result: PASS**

---

## Live Trading Status

> **REAL LIVE EXECUTION REMAINS BLOCKED.**  
> No exchange orders, no leverage changes, no live-gate transitions were made.  
> Dangerous controls require explicit human approval through ControlActionDialog  
> (dry_run → reason → confirm → execute). The `EXECUTION BLOCKED` banner is  
> always visible in the admin global health strip.

---

## What Changed

The NERVYX ONE admin portal was consolidated from ~28 sprawling admin routes into
**13 canonical routes** (10 primary + 3 secondary). Legacy paths are preserved as
redirects. AdminShell was rebuilt with a compact 220px left nav.

### Canonical Admin Routes

| # | Route | Page |
|---|-------|------|
| 1 | `/admin` | Overview (services, pipeline, incidents) |
| 2 | `/admin/data` | Data sources, coverage, freshness |
| 3 | `/admin/intelligence` | Trainer status, predictions, model health |
| 4 | `/admin/orchestration` | Orchestrator, job queues, task graph |
| 5 | `/admin/risk` | Risk gate, kill switch, readiness |
| 6 | `/admin/execution` | Execution engine, order flow, latency |
| 7 | `/admin/exchanges` | Exchange connectors, API health |
| 8 | `/admin/config` | Versioned config, diff, rollback |
| 9 | `/admin/users` | Users, roles, sessions |
| 10 | `/admin/reports` | Operational reports, evidence, exports |
| — | — | *Secondary (below divider)* |
| 11 | `/admin/logs` | Structured event logs, error aggregation |
| 12 | `/admin/audit` | Append-only governance audit chain |
| 13 | `/admin/tools` | Developer tools (superadmin only) |

**86 legacy paths** redirect to canonical routes via `MERGED_LEGACY_PATHS`.

---

## Gate Criteria

### Information Architecture

| ID | Criterion | Result |
|----|-----------|--------|
| IA-001 | 13 canonical admin routes in SYSTEM_NAV_ORDER | **PASS** |
| IA-002 | 86 legacy paths covered by MERGED_LEGACY_PATHS | **PASS** |
| IA-003 | No duplicate route registrations | **PASS** |

### AdminShell

| ID | Criterion | Result |
|----|-----------|--------|
| SHELL-001 | 220px left nav, divider, superadmin gating | **PASS** |
| SHELL-002 | Global health strip, 30s poll, EXECUTION BLOCKED banner | **PASS** |
| SHELL-003 | Breadcrumb from PAGES registry, role badge | **PASS** |

### Admin Pages

| ID | Criterion | Result |
|----|-----------|--------|
| PAGES-001 | 14 admin page modules with correct data contracts | **PASS** |
| PAGES-002 | No "Connecting…" strings — MissingSourceIncident used everywhere | **PASS** |
| PAGES-003 | FreshnessBadge called with `{status, lagMs}` (not legacy props) | **PASS** |

### Component Library

| ID | Criterion | Result |
|----|-----------|--------|
| COMP-001 | 7 new admin components, correct type unions | **PASS** |
| COMP-002 | ControlActionDialog requires dry_run → reason → confirm | **PASS** |

### Build Quality

| ID | Criterion | Result |
|----|-----------|--------|
| TYPES-001 | `npx tsc --noEmit` → exit 0, zero errors | **PASS** |
| BUILD-001 | `npm run build` → 2744 modules, no errors | **PASS** |
| BUILD-002 | `npm run lint --if-present` → clean | **PASS** |

### Playwright E2E Tests

| ID | Criterion | Result |
|----|-----------|--------|
| E2E-001 | 5 new spec files (IA, redirects, security, data, visual) | **PASS** |

### Security

| ID | Criterion | Result |
|----|-----------|--------|
| SEC-001 | Live trading blocked; no exchange connector calls from UI | **PASS** |
| SEC-002 | Audit + Tools hidden from non-live_approver roles | **PASS** |
| SEC-003 | No ?role= bypass, no auth mocks in final code | **PASS** |
| THEME-001 | ops-terminal theme token on admin shell | **PASS** |

---

## Key Fixes Applied

**Route conflicts removed from registry.ts:**
- `config` alias page at `/admin/config` — conflicted with canonical `admin-config`
- `market-root` at `/market` — redundant with MERGED_LEGACY_PATHS
- `trader-legacy` at `/trader` — redundant with MERGED_LEGACY_PATHS

**Hook API fixed across all 11 pages using `useRealtimeResource`:**
```typescript
// Before (wrong — 2 positional args):
const { data, loading, error, lastUpdated } = useRealtimeResource<T>(URL, INTERVAL);

// After (correct — 1 options object):
const { envelope, loading, error } = useRealtimeResource<T>({ url: URL, source: 'name', pollIntervalMs: INTERVAL });
const data = envelope.data;
```

**FreshnessBadge props fixed across all pages:**
```tsx
// Before (wrong — legacy props):
<FreshnessBadge sourceId="..." dataset="..." lastRecordAt={...} />

// After (correct):
<FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
```

**Admin component type errors fixed:**
- `ServiceHealthGrid`: removed `offline` from STATUS_COLOR (valid: `ok|warn|error|unknown`)
- `PipelineMap`: removed `live|delayed|stale|offline` (valid: `ok|warn|error|gap|unknown`); fixed field names (`src.dataset` not `src.name`, `src.throughput` not `src.throughput_per_sec`)
- `SourceCoverageTable`: same fixes as PipelineMap

---

## Warnings (non-blocking)

1. **Chunk size advisory:** Main JS bundle is 1,850 kB (gzip: 490 kB). Consider dynamic `import()` code-splitting in a follow-up task.
2. `admin-war-room` page exists under `src/pages/admin-war-room/` but is not registered in `SYSTEM_NAV_ORDER`. This is correct — it is a special secondary page, not part of the primary 13.

---

## New Files

**Pages:**
- `src/pages/admin-overview/index.tsx`
- `src/pages/admin-data/index.tsx`
- `src/pages/admin-intelligence/index.tsx`
- `src/pages/admin-orchestration/index.tsx`
- `src/pages/admin-risk/index.tsx`
- `src/pages/admin-execution/index.tsx`
- `src/pages/admin-exchanges/index.tsx`
- `src/pages/admin-config/index.tsx`
- `src/pages/admin-users/index.tsx`
- `src/pages/admin-reports/index.tsx`
- `src/pages/admin-logs/index.tsx`
- `src/pages/admin-audit/index.tsx`
- `src/pages/admin-tools/index.tsx`

**Components:**
- `src/components/admin/AdminIncidentCard.tsx`
- `src/components/admin/ServiceHealthGrid.tsx`
- `src/components/admin/PipelineMap.tsx`
- `src/components/admin/ControlActionDialog.tsx`
- `src/components/admin/SourceCoverageTable.tsx`
- `src/components/admin/RealtimeStreamTable.tsx`
- `src/components/admin/DataContractViolationPanel.tsx`
- `src/components/admin/index.ts`

**Layout:**
- `src/components/layout/AdminShell.tsx` (rebuilt)
- `src/styles/admin.css` (rebuilt)

**E2E Tests:**
- `tests/e2e/admin_information_architecture.spec.ts`
- `tests/e2e/legacy_admin_redirects.spec.ts`
- `tests/e2e/admin_controls_security.spec.ts`
- `tests/e2e/admin_data_consistency.spec.ts`
- `tests/e2e/admin_visual_final.spec.ts`

**Release gate:**
- `artifacts/admin-website-release-gate.json`
- `docs/admin-website-release-gate.md`
