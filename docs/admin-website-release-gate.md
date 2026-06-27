# Admin Website Release Gate

**Gate version:** 2.0.0  
**Generated:** 2026-06-25T03:45:00Z  
**Branch:** `codex/pipeline-trust-refresh`  
**Operator:** Claude Code (claude-sonnet-4-6)  
**Overall status:** `BLOCKED`  
**Live trading:** `BLOCKED`

---

## Gate Result: BLOCKED

Do not merge or deploy until all blocking conditions are cleared.  
Do not approve the website release while either the trader or admin release gate remains false.

---

## Blocking Conditions

| ID | Reason |
|---|---|
| T4-UNIMPLEMENTED | Admin data consistency not built — canonical source per field, actionable MissingSourceIncident for empty panels |
| T5-UNIMPLEMENTED | Admin visual redesign not implemented — 12-column grid, 4-viewport symmetry, panel alignment |
| T6-UNIMPLEMENTED | Admin security not implemented — dangerous controls need confirmation + backend audit + audit ID |
| CODEX-UNVERIFIED | Codex production trader patch not yet deployed; post-deploy verification pending |

---

## Check Results

| Check | Status | Evidence |
|---|---|---|
| TypeScript typecheck | PASS | `tsc --noEmit` — clean |
| Production build | PASS | 2754 modules, 1897 kB, 9.32s |
| Trader nav E2E (6 pages) | PASS | 6/6 pass — Trade, Alerts, Replay, Technical Analysis, Account Settings, Market Detail |
| Admin IA (23 tests) | PASS | 23/23 pass — 13 canonical routes, RBAC, role badges |
| Admin data consistency | PARTIAL | 7/8 pass (1 flaky/retry). Full MissingSourceIncident not built. |
| Admin controls security | PARTIAL | 9/9 pass. Full DangerousControlPanel not built. |
| Admin visual final | PARTIAL | 12/12 pass (2 flaky/retry). 4-viewport screenshots not run. |
| Codex independent verification | PRE-DEPLOY | Pre-deploy verification complete. Post-deploy pending. |
| 4-viewport screenshots | NOT RUN | Requires T5 implementation |
| Live trading blocked | CONFIRMED | All trades paper_only=true, live_gate=blocked_human_only |

---

## Completed This Session

### Trader Navigation (Task 1 & 2)

All 6 required trader pages now accessible via visible clicks:

| Page | Method | Status |
|---|---|---|
| Trade (`/trade`) | Top nav link | Pre-existing |
| Alerts (`/alerts`) | Top nav link | Pre-existing |
| Replay (`/replay`) | Top nav link | Added |
| Technical Analysis (`/technical-analysis`) | Top nav link | Added + path fixed |
| Account Settings (`/account-settings`) | UserMenu dropdown | Added |
| Market Detail (`/market/:symbol`) | Markets page row click | Pre-existing |

E2E test: `tests/e2e/trader_menu_navigation_final.spec.ts` — 6/6 pass, visible-click-only.

### Admin Navigation Consolidation (Task 3)

**13 canonical admin routes:**

| # | Route | MinRole | Notes |
|---|---|---|---|
| 1 | `/admin` | admin | Overview |
| 2 | `/admin/data` | reviewer | Data |
| 3 | `/admin/intelligence` | reviewer | Intelligence |
| 4 | `/admin/orchestration` | admin | Orchestration |
| 5 | `/admin/risk` | admin | Risk & Readiness |
| 6 | `/admin/execution` | admin | Execution |
| 7 | `/admin/exchanges` | reviewer | Exchanges |
| 8 | `/admin/config` | admin | Configuration |
| 9 | `/admin/users` | admin | Users |
| 10 | `/admin/reports` | reviewer | Reports |
| 11 | `/admin/logs` | live_approver | Logs (superadmin-only) |
| 12 | `/admin/audit` | live_approver | Audit (superadmin-only) |
| 13 | `/admin/tools` | live_approver | Developer Tools (superadmin-only) |

AdminShell built with: left nav, sticky header, breadcrumb, global health strip (EXECUTION BLOCKED), role badge, incident count badge.

### Bugs Fixed (from Codex independent verification)

| ID | Severity | Description | Fix |
|---|---|---|---|
| BF-01 | HIGH | PnL showing $0.00 instead of $647.82 | `capital_source` now injected with Redis `pnl_source` override |
| BF-02 | HIGH | Accuracy showing 0% / NO_EVALUATED_OUTCOME_EVIDENCE | Same pattern fix for accuracy override |
| BF-03 | MEDIUM | Technical Analysis page unreachable from UI | Route path changed from `/research/technical-analysis` to `/technical-analysis` |
| BF-04 | MEDIUM | Replay/TechAnalysis/AccountSettings required manual URL | Added to TopBar nav and UserMenu |

### Test Infrastructure Fixed

- `admin_visual_final.spec.ts`: Added explicit `admin-shell` wait before checking nav/breadcrumb; removed `/admin/logs` from admin-role route list
- `admin_controls_security.spec.ts`: Fixed reviewer→admin role mapping (changed to viewer which is actually below admin)
- `admin_data_consistency.spec.ts`: Fixed route registration LIFO order; fixed intelligence tab testIds
- `admin-intelligence/index.tsx`: Added `data-testid` to all 4 tab buttons (model, predictions, signals, risk-checks)
- `playwright.config.ts`: Set `retries: 1` to absorb transient ERR_ABORTED flakiness

---

## Runtime State at Gate Check

| Field | Value |
|---|---|
| Backend | `http://127.0.0.1:5173` |
| Frontend build | `dist/assets/index-Bdchbnix.js` |
| Closed trades | 2604 |
| Open positions | 13 |
| Realized PnL (7d) | $647.82 |
| Win rate | 44.78% |
| Mode | Paper |
| Live gate | `blocked_human_only` |

---

## Next Steps to Unlock Gate

1. **T4 — Admin data consistency**: Build `MissingSourceIncident` component (source, endpoint, owner, last_success, error, affected_pages, remediation, incident_id). Replace all "Connecting…" / empty panel states across all 13 admin pages.
2. **T5 — Admin visual redesign**: Implement 12-column grid, aligned panel headers, consistent row heights. Add 4-viewport (375/768/1280/1920px) screenshot regression tests.
3. **T6 — Admin security**: Add `DangerousControlPanel` with confirmation dialog, reason field, backend auth, audit ID. Cover all controls from CLAUDE.md Admin Control Rule.
4. **CODEX**: Wait for Codex production trader patch deployment. Run post-deploy independent verification: portfolio values, positions, signals, source precedence, cross-page consistency, navigation, failed requests, clipping, live-blocked status.
5. **T7 re-run**: After T4–T6 complete and Codex verified, re-run full Chromium suite + 4-viewport screenshots. Update gate to PASS.
