# UI Defect Log (Pre-redesign)
Generated: 2026-06-12T22:22:41.000Z

## High-priority Codex 5.5 blockers (trader-facing)
| area | blocker | evidence |
|---|---|---|
| Brand | `AI BOT V2` and `Control Plane` still rendered in public/trader components | `v2/frontend/src/components/layout/Nav.tsx`, `v2/frontend/src/components/layout/AdminShell.tsx`, `v2/frontend/src/components/layout/PublicShell.tsx` |
| Auth | Browser role override still possible through URL/session storage in session path | `v2/frontend/src/auth/session.ts`, `v2/frontend/src/components/layout/AdminShell.tsx` |
| Shell | No separate trader shell; public/admin boundary is not cleanly enforced in nav model | `v2/frontend/src/components/layout/AdminShell.tsx`, `v2/frontend/src/pages/productNavigation.ts` |
| Market analytics | `/markets` still lacks CoinAnk-style filters and risk of dense operator-style table layouts | `v2/frontend/src/pages/markets/index.tsx`, `v2/frontend/src/styles.css` |
| Trade terminal | missing clear order-form/order-book/recent-trades architecture for `/trade` | `v2/frontend/src/pages/trader/index.tsx` (legacy terminal entry points), `/admin` route aliasing |
| Trader/Signals separation | operator/developer pages and terminology still accessible or labeled in trader surfaces | route metadata and nav sources in `v2/frontend/src/router.tsx` and page metadata |
| Data honesty | static payloads used as primary data source without explicit stale/fallback state in many pages | many entries in `docs/data-source-inventory.md` and page-level payload hooks |
| Missing API endpoints | `/api/v2/market`, `/api/v2/positions`, `/api/v2/signals`, `/api/v2/portfolio`, `/api/v1/alerts` | no direct implemented route consumers for public trading surfaces |
| Live-readiness clarity | role/state-dependent labels still mix production-oriented copy with trader wording | `v2/frontend/src/components/banners/*`, `v2/frontend/src/pages/public-landing-v2/*` |

## Notes
- Keep this log as a pre-redesign baseline only; this file should be reworked during implementation phases with completed findings cleared.

## Defect findings
| file | line | category | evidence |
|---|---|---|---|
| v2/frontend/src/auth/session.ts | 23 | branding/auth/nav | const queryRole = url.searchParams.get('role') as Role | null; |
| v2/frontend/src/auth/session.ts | 24 | branding/auth/nav | if (queryRole) { |
| v2/frontend/src/auth/session.ts | 25 | branding/auth/nav | window.sessionStorage.setItem(STORAGE_KEY, queryRole); |
| v2/frontend/src/auth/session.ts | 26 | branding/auth/nav | return { ...DEFAULT_SESSION, role: queryRole }; |
| v2/frontend/src/auth/session.ts | 28 | branding/auth/nav | const stored = window.sessionStorage.getItem(STORAGE_KEY) as Role | null; |
| v2/frontend/src/auth/session.ts | 31 | branding/auth/nav | // sessionStorage unavailable; fall through |
| v2/frontend/src/auth/session.ts | 54 | branding/auth/nav | window.sessionStorage.setItem(STORAGE_KEY, role); |
| v2/frontend/src/auth/session.ts | 66 | branding/auth/nav | window.sessionStorage.removeItem(STORAGE_KEY); |
| v2/frontend/src/components/banners/MissionControlReadinessBanner.tsx | 33 | branding/auth/nav | .replace(/^CLAUDE_PRIMARY_ONLINE_READINESS_BUILD_WITH_CODEX_PARALLEL_AUDIT_AND_UI_POLISH_/, 'Archive readiness ') |
| v2/frontend/src/components/dashboard/StaleStateAlertsPanel.tsx | 11 | branding/auth/nav | *   - blocked_quota              (Claude/Codex quota exhausted) |
| v2/frontend/src/components/layout/AdminShell.tsx | 93 | branding/auth/nav | function roleFromSearch(search: string): Role | null { |
| v2/frontend/src/components/layout/AdminShell.tsx | 98 | branding/auth/nav | export function AdminShell(): JSX.Element { |
| v2/frontend/src/components/layout/AdminShell.tsx | 107 | branding/auth/nav | const queryRole = roleFromSearch(location.search); |
| v2/frontend/src/components/layout/AdminShell.tsx | 108 | branding/auth/nav | const role = queryRole ?? sessionRole; |
| v2/frontend/src/components/layout/AdminShell.tsx | 113 | branding/auth/nav | if (queryRole && queryRole !== sessionRole) { |
| v2/frontend/src/components/layout/AdminShell.tsx | 114 | branding/auth/nav | sessionStore.setRole(queryRole); |
| v2/frontend/src/components/layout/AdminShell.tsx | 116 | branding/auth/nav | }, [queryRole, sessionRole]); |
| v2/frontend/src/components/layout/AdminShell.tsx | 134 | branding/auth/nav | <h1>AI BOT V2 Trading Desk</h1> |
| v2/frontend/src/components/layout/Nav.tsx | 55 | branding/auth/nav | <span className="nav__brand-name">AI BOT V2</span> |
| v2/frontend/src/components/layout/PageShell.tsx | 136 | branding/auth/nav | source: 'operator truth payload / monitor center', |
| v2/frontend/src/components/layout/PageShell.tsx | 141 | branding/auth/nav | 'codex-review-center': { |
| v2/frontend/src/components/layout/PageShell.tsx | 142 | branding/auth/nav | source: 'Codex review artifacts', |
| v2/frontend/src/components/layout/PageShell.tsx | 144 | branding/auth/nav | next: 'Wire latest Codex PASS/FAIL matrix and remediation links.', |
| v2/frontend/src/components/layout/PageShell.tsx | 151 | branding/auth/nav | data: ['model', 'task', 'draft packet', 'Claude/Codex verification state'], |
| v2/frontend/src/components/layout/PageShell.tsx | 177 | branding/auth/nav | next: `Keep ${meta.title} backed by current V2 paper/shadow, operator truth, and route-specific payloads.`, |
| v2/frontend/src/components/layout/PageShell.tsx | 291 | branding/auth/nav | <p className="cockpit-evidence-gap" role="alert">Operator truth payload source pending: {truthError}</p> |
| v2/frontend/src/components/layout/PublicShell.tsx | 29 | branding/auth/nav | export function PublicShell(): JSX.Element { |
| v2/frontend/src/components/layout/PublicShell.tsx | 35 | branding/auth/nav | <Link className="public-shell__brand" to="/landing">AI BOT V2</Link> |
| v2/frontend/src/components/realtimeWebsite/index.tsx | 487 | branding/auth/nav | // the explicit adoption-blocked labels Codex required. Renders NO |
| v2/frontend/src/components/realtimeWebsite/index.tsx | 563 | branding/auth/nav | // The adoption-blocked label set is Codex-required and must always |
| v2/frontend/src/components/realtimeWebsite/index.tsx | 605 | branding/auth/nav | {/* Codex-required adoption-blocked label strip — always visible. */} |
| v2/frontend/src/data/realtimeUserWebsitePayloads.ts | 99 | branding/auth/nav | war_room_codex_5m: '/v2_8h_war_room/latest/codex_5m_review_payload.json', |
| v2/frontend/src/data/realtimeUserWebsitePayloads.ts | 114 | branding/auth/nav | war_room_codex_queue: '/v2_8h_war_room/latest/codex_review_queue.json', |
| v2/frontend/src/data/realtimeUserWebsitePayloads.ts | 181 | branding/auth/nav | state?: { cycle_count?: number; started_at?: string; no_action_streak?: number; codex_reviews_queued_total?: number }; |
| v2/frontend/src/data/realtimeUserWebsitePayloads.ts | 197 | branding/auth/nav | codex_review_queue?: { pending_codex_reviews?: unknown[]; pre_existing_blockers_not_eligible_for_new_task_creation?: unknown[] }; |
| v2/frontend/src/data/realtimeUserWebsitePayloads.ts | 466 | branding/auth/nav | export const useWarRoomCodexQueue = (pollMs = 30_000) => |
| v2/frontend/src/data/realtimeUserWebsitePayloads.ts | 467 | branding/auth/nav | useJsonPayload<{ pending_codex_reviews?: unknown[]; pre_existing_blockers_not_eligible_for_new_task_creation?: unknown[] }>( |
| v2/frontend/src/data/realtimeUserWebsitePayloads.ts | 468 | branding/auth/nav | PAYLOAD_PATHS.war_room_codex_queue, |
| v2/frontend/src/data/realtimeUserWebsitePayloads.ts | 532 | branding/auth/nav | export const useWarRoomCodex5m = (pollMs = 30_000) => |
| v2/frontend/src/data/realtimeUserWebsitePayloads.ts | 533 | branding/auth/nav | useJsonPayload<Record<string, unknown>>(PAYLOAD_PATHS.war_room_codex_5m, pollMs); |
| v2/frontend/src/data/realtimeUserWebsitePayloads.ts | 551 | branding/auth/nav | codex_live_canary_pass_marker_present?: boolean; |
| v2/frontend/src/data/realtimeUserWebsitePayloads.ts | 592 | branding/auth/nav | codex_pass_marker_present?: boolean; |
| v2/frontend/src/data/runtimePayloads.ts | 38 | branding/auth/nav | active_codex_task: string; |
| v2/frontend/src/hooks/useAgentHealth.ts | 20 | branding/auth/nav | codex?: Record<string, unknown> | null; |
| v2/frontend/src/hooks/useQueueStatus.ts | 73 | branding/auth/nav | pending_codex?: number; |
| v2/frontend/src/hooks/useQueueStatus.ts | 75 | branding/auth/nav | stale_codex?: number; |
| v2/frontend/src/hooks/useQueueStatus.ts | 79 | branding/auth/nav | stale_codex?: string[]; |
| v2/frontend/src/hooks/useQueueStatus.ts | 85 | branding/auth/nav | const stale = [...(raw.stale_claude ?? []), ...(raw.stale_codex ?? [])]; |
| v2/frontend/src/hooks/useQueueStatus.ts | 105 | branding/auth/nav | pending: (counts.pending_claude ?? 0) + (counts.pending_codex ?? 0), |
| v2/frontend/src/hooks/useQueueStatus.ts | 115 | branding/auth/nav | pending_codex: counts.pending_codex ?? 0, |
| v2/frontend/src/hooks/useQueueStatus.ts | 117 | branding/auth/nav | stale_codex: counts.stale_codex ?? 0, |
| v2/frontend/src/pages/admin-war-room/index.tsx | 20 | branding/auth/nav | useWarRoomCodexQueue, |
| v2/frontend/src/pages/admin-war-room/index.tsx | 38 | branding/auth/nav | const codexQueue = useWarRoomCodexQueue(); |
| v2/frontend/src/pages/admin-war-room/index.tsx | 65 | branding/auth/nav | // Raw payload explorer: every source path we read, plus current |
| v2/frontend/src/pages/admin-war-room/index.tsx | 72 | branding/auth/nav | { key: 'war_room_codex_queue', path: PAYLOAD_PATHS.war_room_codex_queue, status: codexQueue.error ?? (codexQueue.payload ? 'OK' : 'loading'), freshness: '' }, |
| v2/frontend/src/pages/admin-war-room/index.tsx | 105 | branding/auth/nav | <MetricCard label="codex_reviews_queued_total" value={state?.codex_reviews_queued_total ?? 0} /> |
| v2/frontend/src/pages/admin-war-room/index.tsx | 180 | branding/auth/nav | {/* ---- 5. Codex review status ---- */} |
| v2/frontend/src/pages/admin-war-room/index.tsx | 181 | branding/auth/nav | <section className="panel" style={{ padding: 14, marginTop: 18 }} data-testid="war-room-codex-review"> |
| v2/frontend/src/pages/admin-war-room/index.tsx | 182 | branding/auth/nav | <PanelHeader title="Codex review queue" source={PAYLOAD_PATHS.war_room_codex_queue} rightExtras={<FreshnessBadge generatedAt={(codexQueue.payload as any)?.generated_utc} maxAgeSeconds={3600} />} /> |
| v2/frontend/src/pages/admin-war-room/index.tsx | 183 | branding/auth/nav | {!codexQueue.payload ? ( |
| v2/frontend/src/pages/admin-war-room/index.tsx | 184 | branding/auth/nav | <PayloadMissingCard path={PAYLOAD_PATHS.war_room_codex_queue} error={codexQueue.error} loading={codexQueue.loading} /> |
| v2/frontend/src/pages/admin-war-room/index.tsx | 187 | branding/auth/nav | <p style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--fg-3)' }}>pending_codex_reviews: {(codexQueue.payload.pending_codex_reviews ?? []).length}</p> |
| v2/frontend/src/pages/admin-war-room/index.tsx | 189 | branding/auth/nav | {(codexQueue.payload.pending_codex_reviews ?? []).slice(0, 10).map((r: any, i) => ( |
| v2/frontend/src/pages/admin-war-room/index.tsx | 197 | branding/auth/nav | {(codexQueue.payload.pre_existing_blockers_not_eligible_for_new_task_creation ?? []).slice(0, 10).map((b: any, i) => ( |
| v2/frontend/src/pages/admin-war-room/index.tsx | 256 | branding/auth/nav | <MetricCard label="codex_pass_marker" value={String(canaryDash.payload?.codex_live_canary_pass_marker_present ?? false)} /> |
| v2/frontend/src/pages/admin-war-room/index.tsx | 370 | branding/auth/nav | {/* ---- 8. Raw payload explorer ---- */} |
| v2/frontend/src/pages/admin-war-room/index.tsx | 372 | branding/auth/nav | <PanelHeader title="Raw payload explorer" source="public/" rightExtras={<BlockerChip text="paths only · no raw secrets" tone="info" />} /> |
| v2/frontend/src/pages/admin-war-room/meta.ts | 7 | branding/auth/nav | 'Admin-only view of the V2 8h war-room daemon. Wires real cycle history, gap matrix, blocker matrix, Codex queue, legacy log observer, safety scan, raw payload explorer.', |
| v2/frontend/src/pages/build-validation-status/index.tsx | 16 | branding/auth/nav | <SourceRibbon labels={['proof freshness', 'go/no-go markers', 'Codex review status', 'pending-source checks']} /> |
| v2/frontend/src/pages/claude-admin-ai/index.tsx | 31 | branding/auth/nav | 'Answers must cite operator truth, paper runtime, risk decisions, audit ledger, or build status.', |
| v2/frontend/src/pages/cockpitComponents.tsx | 366 | branding/auth/nav | <Metric label="Codex" value={payload.codex_go_no_go} /> |
| v2/frontend/src/pages/cockpitComponents.tsx | 396 | branding/auth/nav | <Metric label="Codex" value={payload.codex_go_no_go} /> |
| v2/frontend/src/pages/cockpitComponents.tsx | 439 | branding/auth/nav | <Metric label="Codex" value={payload.codex_go_no_go} /> |
| v2/frontend/src/pages/cockpitComponents.tsx | 481 | branding/auth/nav | <Metric label="Codex" value={payload.codex_go_no_go} /> |
| v2/frontend/src/pages/cockpitComponents.tsx | 528 | branding/auth/nav | <Metric label="Codex" value={payload.codex_go_no_go} /> |
| v2/frontend/src/pages/cockpitComponents.tsx | 569 | branding/auth/nav | <Metric label="Codex" value={payload.codex_go_no_go} /> |
| v2/frontend/src/pages/cockpitComponents.tsx | 673 | branding/auth/nav | <p>Codex reviews and challenges each safe milestone.</p> |
| v2/frontend/src/pages/cockpitComponents.tsx | 674 | branding/auth/nav | <p>Ollama drafts evidence only; Claude/Codex verify raw facts.</p> |
| v2/frontend/src/pages/cockpitData.ts | 170 | branding/auth/nav | codex_go_no_go: string; |
| v2/frontend/src/pages/cockpitData.ts | 196 | branding/auth/nav | codex_go_no_go: string; |
| v2/frontend/src/pages/cockpitData.ts | 229 | branding/auth/nav | codex_go_no_go: string; |
| v2/frontend/src/pages/cockpitData.ts | 260 | branding/auth/nav | codex_go_no_go: string; |
| v2/frontend/src/pages/cockpitData.ts | 304 | branding/auth/nav | codex_go_no_go: string; |
| v2/frontend/src/pages/cockpitData.ts | 331 | branding/auth/nav | codex_go_no_go: string; |
| v2/frontend/src/pages/cockpitData.ts | 382 | branding/auth/nav | codex_auto_governor_working: boolean; |
| v2/frontend/src/pages/codex-review-center/index.tsx | 86 | branding/auth/nav | export default function CodexReviewCenterPage(): JSX.Element { |
| v2/frontend/src/pages/codex-review-center/index.tsx | 102 | branding/auth/nav | data-testid="page-codex-review-center" |
| v2/frontend/src/pages/codex-review-center/meta.ts | 3 | branding/auth/nav | id: 'codex-review-center', |
| v2/frontend/src/pages/codex-review-center/meta.ts | 6 | branding/auth/nav | description: 'Codex review status across milestones.', |
| v2/frontend/src/pages/codex-review-center/route.ts | 2 | branding/auth/nav | const route: PageRoute = { path: '/admin/codex-review-center' }; |
| v2/frontend/src/pages/live-readiness/index.tsx | 68 | branding/auth/nav | codex_final_live_canary_pass_marker_present?: boolean; |
| v2/frontend/src/pages/live-readiness/index.tsx | 69 | branding/auth/nav | codex_live_canary_pass_marker_present?: boolean; |
| v2/frontend/src/pages/live-readiness/index.tsx | 533 | branding/auth/nav | const canaryPassMarkerPresent = canary?.codex_final_live_canary_pass_marker_present ?? canary?.codex_live_canary_pass_marker_present ?? false; |
| v2/frontend/src/pages/live-readiness/index.tsx | 821 | branding/auth/nav | <div><span>codex_final_canary_pass</span><strong className={canaryPassMarkerPresent ? 'status-ok' : 'status-block'}>{String(canaryPassMarkerPresent)}</strong></div> |
| v2/frontend/src/pages/live-readiness/index.tsx | 964 | branding/auth/nav | ['codex_canary_pass_marker', canaryPassMarkerPresent ? 'PRESENT' : 'ABSENT — Codex final canary review not passed'], |
| v2/frontend/src/pages/market-intelligence/index.tsx | 62 | branding/auth/nav | exchange_actions_by_codex?: boolean; |
| v2/frontend/src/pages/market-intelligence/index.tsx | 63 | branding/auth/nav | destructive_redis_mutation_by_codex?: boolean; |
| v2/frontend/src/pages/market-intelligence/index.tsx | 64 | branding/auth/nav | manual_redis_mutation_by_codex?: boolean; |
| v2/frontend/src/pages/market-intelligence/index.tsx | 758 | branding/auth/nav | <SafetyCell label="exchange_actions_by_codex" value={String(c?.exchange_actions_by_codex ?? false)} expected="false" /> |
| v2/frontend/src/pages/market-intelligence/index.tsx | 759 | branding/auth/nav | <SafetyCell label="destructive_redis_mutation_by_codex" value={String(c?.destructive_redis_mutation_by_codex ?? false)} expected="false" /> |
| v2/frontend/src/pages/markets/index.tsx | 335 | branding/auth/nav | <span>Dense rows</span> |
| v2/frontend/src/pages/mission-control/index.tsx | 547 | branding/auth/nav | AI BOT V2 Modern Dashboard Loaded |
| v2/frontend/src/pages/mission-control/index.tsx | 1335 | branding/auth/nav | <div><span>Next task</span><strong>{truthPayload.current_next_task ?? 'Current runtime pending from operator truth payload'}</strong></div> |
| v2/frontend/src/pages/mission-control/index.tsx | 1367 | branding/auth/nav | <p>Current lineage is not ready in this payload. Historical proof rows stay in Signal Explainability and Operator Proof Dashboard, not as the current stream.</p> |
| v2/frontend/src/pages/mission-control/index.tsx | 1394 | branding/auth/nav | <p className="cockpit-evidence-note">Rows are V2 proof artifacts unless the operator truth payload marks current runtime lineage as realtime.</p> |
| v2/frontend/src/pages/mission-control/index.tsx | 1407 | branding/auth/nav | <p className="eyebrow">AI BOT V2 verified market context</p> |
| v2/frontend/src/pages/mission-control/index.tsx | 1440 | branding/auth/nav | const codexStatus = autonomousGovernor?.codex_auto_governor_working |
| v2/frontend/src/pages/mission-control/index.tsx | 1441 | branding/auth/nav | ? 'CODEX_AUTO_GOVERNOR_WORKING' |
| v2/frontend/src/pages/mission-control/index.tsx | 1475 | branding/auth/nav | label: 'Codex review', |
| v2/frontend/src/pages/mission-control/index.tsx | 1476 | branding/auth/nav | value: codexStatus, |
| v2/frontend/src/pages/mission-control/meta.ts | 7 | branding/auth/nav | description: 'Global health, alerts, and readiness across the V2 control plane.', |
| v2/frontend/src/pages/monitor-center/index.tsx | 53 | branding/auth/nav | .replaceAll('CODEX_PRODUCTION_REPLACEMENT_RUNTIME_GOVERNOR_BLOCKED', 'production replacement is not certified yet') |
| v2/frontend/src/pages/monitor-center/index.tsx | 169 | branding/auth/nav | claude_codex_task_pairs_written_or_existing?: Array<{ |
| v2/frontend/src/pages/monitor-center/index.tsx | 174 | branding/auth/nav | codex_task_path?: string; |
| v2/frontend/src/pages/monitor-center/index.tsx | 332 | branding/auth/nav | paired_codex_review_task_ids_required?: string[]; |
| v2/frontend/src/pages/monitor-center/index.tsx | 729 | branding/auth/nav | <small>Read-only (Codex-paired)</small> |
| v2/frontend/src/pages/monitor-center/index.tsx | 753 | branding/auth/nav | <strong>{remediationData?.claude_codex_task_pairs_written_or_existing?.length ?? 'Current monitor source pending'}</strong> |
| v2/frontend/src/pages/monitor-center/index.tsx | 754 | branding/auth/nav | <small>Claude remediation + Codex review descriptors</small> |
| v2/frontend/src/pages/monitor-center/index.tsx | 779 | branding/auth/nav | <small>Codex PASS; production-equivalence remains blocked.</small> |
| v2/frontend/src/pages/operator-proof-dashboard/index.tsx | 98 | branding/auth/nav | codex_governor_status?: string; |
| v2/frontend/src/pages/operator-proof-dashboard/index.tsx | 132 | branding/auth/nav | active_claude_codex_child_process?: boolean; |
| v2/frontend/src/pages/operator-proof-dashboard/index.tsx | 146 | branding/auth/nav | codex_watchdog_running: boolean; |
| v2/frontend/src/pages/operator-proof-dashboard/index.tsx | 162 | branding/auth/nav | claude_codex_child_present: boolean; |
| v2/frontend/src/pages/operator-proof-dashboard/index.tsx | 360 | branding/auth/nav | .replaceAll('CLAUDE_PRIMARY_ONLINE_READINESS_BUILD_WITH_CODEX_PARALLEL_AUDIT_AND_UI_POLISH_', 'Archive readiness ') |
| v2/frontend/src/pages/operator-proof-dashboard/index.tsx | 737 | branding/auth/nav | <Section id="automation-status" title="Claude/Codex/Ollama Automation Status"> |
| v2/frontend/src/pages/operator-proof-dashboard/index.tsx | 740 | branding/auth/nav | title="Autonomous planner and Codex governor" |
| v2/frontend/src/pages/operator-proof-dashboard/index.tsx | 747 | branding/auth/nav | codex_governor: payload.autonomous_live_readiness_builder.codex_governor_status ?? 'evidence_missing', |
| v2/frontend/src/pages/operator-proof-dashboard/index.tsx | 759 | branding/auth/nav | <Metric label="Codex Watchdog" value={String(payload.automation_status.liveness.dashboard_summary.codex_watchdog_running)} /> |
| v2/frontend/src/pages/operator-proof-dashboard/index.tsx | 790 | branding/auth/nav | child_process: String(payload.automation_status.task_069_liveness.progress_signals?.active_claude_codex_child_process ?? false), |
| v2/frontend/src/pages/operator-proof-dashboard/index.tsx | 856 | branding/auth/nav | The old operator proof cockpit is archived and no longer presented as current website truth. |
| v2/frontend/src/pages/operator-proof-dashboard/meta.ts | 5 | branding/auth/nav | title: 'Operator Proof Dashboard', |
| v2/frontend/src/pages/operatorTruthComponents.tsx | 6 | branding/auth/nav | const MISSING = 'Current operator truth source pending.'; |
| v2/frontend/src/pages/operatorTruthComponents.tsx | 87 | branding/auth/nav | <Panel id="operator-truth-loading" title="Operator Truth Payload"> |
| v2/frontend/src/pages/operatorTruthComponents.tsx | 89 | branding/auth/nav | {error ? `Operator truth payload source pending: ${error}` : 'Loading operator truth payload...'} |
| v2/frontend/src/pages/operatorTruthComponents.tsx | 124 | branding/auth/nav | <p className="eyebrow">Realtime operator truth / no guessing</p> |
| v2/frontend/src/pages/operatorTruthComponents.tsx | 222 | branding/auth/nav | ['Control plane', controlPlaneValue(payload), payload.supervisor_status.canonical_snapshot_fresh ? 'fresh process/runtime bridge snapshot' : 'agent_supervisor/status/current_status.json'], |
| v2/frontend/src/pages/operatorTruthComponents.tsx | 476 | branding/auth/nav | label: 'Control plane', |
| v2/frontend/src/pages/operatorTruthComponents.tsx | 537 | branding/auth/nav | <TruthStateCard label="Control plane" value={controlPlaneValue(payload)} detail="Dashboard must disclose missing control-plane daemons and stale historical status files separately." source={payload.canonical_truth_bridge ? 'PAPER_ONLINE_CANONICAL_TRUTH_BRIDGE' : 'RUNTIME_MONITOR_PAYLOAD'} /> |
| v2/frontend/src/pages/operatorTruthComponents.tsx | 550 | branding/auth/nav | <section className="truth-status-strip" data-testid="operator-truth-status-strip" aria-label="Current operator truth status"> |
| v2/frontend/src/pages/operatorTruthComponents.tsx | 552 | branding/auth/nav | <Metric label="Control plane" value={controlPlaneValue(payload)} /> |
| v2/frontend/src/pages/operatorTruthData.ts | 293 | branding/auth/nav | const persistentControlPlaneObserved = oldSupervisor?.supervisor_processes.some((line) => /--daemon|claude_master_rebuild_planner|autonomous_governor|parallel_scheduler|codex_watchdog/.test(line)) ?? false; |
| v2/frontend/src/pages/operatorTruthData.ts | 319 | branding/auth/nav | : 'The operator truth payload is stale, so browser-side paper runtime truth cannot prove current supervisor process state. Refresh operator truth from the local control plane.', |
| v2/frontend/src/pages/operatorTruthData.ts | 395 | branding/auth/nav | evidence_source: 'read-only process snapshot from last operator truth payload', |
| v2/frontend/src/pages/permanent-migration/index.tsx | 65 | branding/auth/nav | <strong>Active Codex task:</strong> <code>{payload.active_codex_task}</code> |
| v2/frontend/src/pages/productNavigation.ts | 458 | branding/auth/nav | 'codex-review-center': { |
| v2/frontend/src/pages/productNavigation.ts | 505 | branding/auth/nav | '/admin/codex-review-center': '/system/build-code-review', |
| v2/frontend/src/pages/public-landing/meta.ts | 4 | branding/auth/nav | title: 'AI BOT V2', |
| v2/frontend/src/pages/public-landing-v2/meta.ts | 5 | branding/auth/nav | title: 'AI BOT V2 · Control plane', |
| v2/frontend/src/pages/public-landing-v2/meta.ts | 8 | branding/auth/nav | 'Redesigned public landing. Evidence-cited, risk-gated overview of the paper-shadow control plane. No internal IDs or operator controls.', |
| v2/frontend/src/pages/public-landing-v2/styles.css | 1 | branding/auth/nav | /* AI BOT V2 — public landing v2 (warm-dark institutional palette) |
| v2/frontend/src/pages/registry.ts | 179 | branding/auth/nav | import CodexReviewCenterPage from './codex-review-center'; |
| v2/frontend/src/pages/registry.ts | 180 | branding/auth/nav | import codexReviewCenterMeta from './codex-review-center/meta'; |
| v2/frontend/src/pages/registry.ts | 181 | branding/auth/nav | import codexReviewCenterRbac from './codex-review-center/rbac'; |
| v2/frontend/src/pages/registry.ts | 182 | branding/auth/nav | import codexReviewCenterRoute from './codex-review-center/route'; |
| v2/frontend/src/pages/registry.ts | 297 | branding/auth/nav | { meta: codexReviewCenterMeta, rbac: codexReviewCenterRbac, route: codexReviewCenterRoute, Component: CodexReviewCenterPage }, |
| v2/frontend/src/pages/report-center/index.tsx | 10 | branding/auth/nav | const REPORT_CODEX_FAILS_PATH = '/v2_report_center/latest/latest_codex_failures.json'; |
| v2/frontend/src/pages/report-center/index.tsx | 28 | branding/auth/nav | codex_passed: boolean | null; |
| v2/frontend/src/pages/report-center/index.tsx | 54 | branding/auth/nav | codex_pass_count?: number; |
| v2/frontend/src/pages/report-center/index.tsx | 55 | branding/auth/nav | codex_fail_count?: number; |
| v2/frontend/src/pages/report-center/index.tsx | 84 | branding/auth/nav | codex_pass_count?: number; |
| v2/frontend/src/pages/report-center/index.tsx | 85 | branding/auth/nav | codex_fail_count?: number; |
| v2/frontend/src/pages/report-center/index.tsx | 122 | branding/auth/nav | current_pending_tasks?: { claude?: number; codex?: number }; |
| v2/frontend/src/pages/report-center/index.tsx | 123 | branding/auth/nav | current_stalled_tasks?: { claude?: number; codex?: number }; |
| v2/frontend/src/pages/report-center/index.tsx | 124 | branding/auth/nav | current_codex_failures?: number; |
| v2/frontend/src/pages/report-center/index.tsx | 135 | branding/auth/nav | interface CodexFailuresPayload { |
| v2/frontend/src/pages/report-center/index.tsx | 136 | branding/auth/nav | codex_failures?: Array<{ |
| v2/frontend/src/pages/report-center/index.tsx | 359 | branding/auth/nav | const codexFails = dashboard?.codex_fail_count ?? index?.codex_fail_count ?? 0; |
| v2/frontend/src/pages/report-center/index.tsx | 360 | branding/auth/nav | const codexPass = dashboard?.codex_pass_count ?? index?.codex_pass_count ?? 0; |
| v2/frontend/src/pages/report-center/index.tsx | 366 | branding/auth/nav | <MetricCard label="Codex Failures" value={codexFails} detail={`${codexPass} Codex passes in index`} tone={codexFails ? 'block' : 'ok'} /> |
| v2/frontend/src/pages/report-center/index.tsx | 369 | branding/auth/nav | value={(dashboard?.current_pending_tasks?.claude ?? 0) + (dashboard?.current_pending_tasks?.codex ?? 0)} |
| v2/frontend/src/pages/report-center/index.tsx | 370 | branding/auth/nav | detail="Claude + Codex pending descriptors" |
| v2/frontend/src/pages/report-center/index.tsx | 474 | branding/auth/nav | const codexFails = dashboard?.current_codex_failures ?? 0; |
| v2/frontend/src/pages/report-center/index.tsx | 482 | branding/auth/nav | <span className={codexFails ? 'chip solid-block' : 'chip solid-ok'}>Codex fails {codexFails}</span> |
| v2/frontend/src/pages/report-center/index.tsx | 486 | branding/auth/nav | <div><span>Pending Codex</span><strong>{pending.codex ?? 0}</strong></div> |
| v2/frontend/src/pages/report-center/index.tsx | 488 | branding/auth/nav | <div><span>Stalled Codex</span><strong>{stalled.codex ?? 0}</strong></div> |
| v2/frontend/src/pages/report-center/index.tsx | 567 | branding/auth/nav | function LatestCodexFailuresPanel(): JSX.Element { |
| v2/frontend/src/pages/report-center/index.tsx | 568 | branding/auth/nav | const codexFails = usePollingQuery<CodexFailuresPayload>( |
| v2/frontend/src/pages/report-center/index.tsx | 569 | branding/auth/nav | REPORT_CODEX_FAILS_PATH, |
| v2/frontend/src/pages/report-center/index.tsx | 570 | branding/auth/nav | (signal) => fetchJson(REPORT_CODEX_FAILS_PATH, signal), |
| v2/frontend/src/pages/report-center/index.tsx | 573 | branding/auth/nav | const fails = codexFails.data?.codex_failures ?? []; |
| v2/frontend/src/pages/report-center/index.tsx | 575 | branding/auth/nav | <section className="report-panel" aria-label="Latest Codex failures"> |
| v2/frontend/src/pages/report-center/index.tsx | 578 | branding/auth/nav | <p className="eyebrow">Codex Review</p> |
| v2/frontend/src/pages/report-center/index.tsx | 581 | branding/auth/nav | <span className={fails.length ? 'chip solid-block' : 'chip solid-ok'}>{codexFails.data?.count ?? 0}</span> |
| v2/frontend/src/pages/report-center/index.tsx | 584 | branding/auth/nav | <p className="report-empty">No active Codex failures in the latest payload.</p> |
| v2/frontend/src/pages/report-center/index.tsx | 725 | branding/auth/nav | <LatestCodexFailuresPanel /> |
| v2/frontend/src/pages/report-center/meta.ts | 8 | branding/auth/nav | 'Realtime view of every Claude/Codex/governor/runtime report lane with freshness, GO/NO-GO, blockers, owners, and safety state. Live, shutdown, and symbol adoption stay blocked.', |
| v2/frontend/src/router.tsx | 2 | branding/auth/nav | import { AdminShell } from './components/layout/AdminShell'; |
| v2/frontend/src/router.tsx | 3 | branding/auth/nav | import { PublicShell } from './components/layout/PublicShell'; |
| v2/frontend/src/router.tsx | 30 | branding/auth/nav | { element: <PublicShell />, children: publicChildren }, |
| v2/frontend/src/router.tsx | 31 | branding/auth/nav | { element: <AdminShell />, children: protectedChildren }, |
| v2/frontend/src/styles.css | 1 | branding/auth/nav | @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&family=IBM+Plex+Sans:wght@300;400;500;600;700&family=IBM+Plex+Sans+Condensed:wght@500;600&display=swap'); |
| v2/frontend/src/styles.css | 89 | branding/auth/nav | grid-template-columns: 260px minmax(0, 1fr); |
| v2/frontend/src/styles.css | 300 | branding/auth/nav | grid-template-columns: minmax(260px, 0.9fr) minmax(280px, 1.1fr); |
| v2/frontend/src/styles.css | 406 | branding/auth/nav | min-width: 260px; |
| v2/frontend/src/styles.css | 557 | branding/auth/nav | grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); |
| v2/frontend/src/styles.css | 1770 | branding/auth/nav | grid-template-columns: minmax(190px, 1.2fr) minmax(110px, 0.8fr) minmax(170px, 1fr) minmax(260px, 1.5fr); |
| v2/frontend/src/styles.css | 1844 | branding/auth/nav | min-height: 260px; |
| v2/frontend/src/styles.css | 1994 | branding/auth/nav | min-height: 260px; |
| v2/frontend/src/styles.css | 2483 | branding/auth/nav | grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); |
| v2/frontend/src/styles.css | 2837 | branding/auth/nav | grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); |
| v2/frontend/src/styles.css | 3008 | branding/auth/nav | .cond   { font-family: "IBM Plex Sans Condensed", "IBM Plex Sans", sans-serif; } |
| v2/frontend/src/styles.css | 3356 | branding/auth/nav | grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); |
| v2/frontend/src/styles.css | 3693 | branding/auth/nav | /* ── Admin shell refresh: denser sidebar + clearer live polling surfaces ── */ |
| v2/frontend/src/styles.css | 4337 | branding/auth/nav | grid-template-columns: minmax(420px, 2fr) minmax(260px, 0.8fr) minmax(280px, 0.9fr); |
| v2/frontend/src/styles.css | 4343 | branding/auth/nav | grid-template-columns: minmax(360px, 1fr) minmax(260px, 0.7fr); |
| v2/frontend/src/styles.css | 5923 | branding/auth/nav | grid-template-columns: repeat(3, minmax(260px, 1fr)); |
| v2/frontend/src/styles.css | 5989 | branding/auth/nav | grid-template-columns: minmax(0, 1fr) minmax(180px, 260px); |

## Required manual checks
- Capture screenshot matrix before work starts: `/`, `/dashboard`, `/markets`, `/trade`, `/status`, `/login` at 1920x1080 / 1440x900 / 390x844.
- Confirm no raw enum keys in trader-facing labels.
- Confirm all admin routes are excluded from trader nav.
