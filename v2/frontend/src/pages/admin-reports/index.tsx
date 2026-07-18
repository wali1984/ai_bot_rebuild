import { useState } from 'react';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { MissingSourceIncident } from '../../components/data/MissingSourceIncident';
import { relativeAge, statusColor, statusBg } from '../../data/adminFieldRegistry';

const REPORTS_ENDPOINT = '/v2_report_center/latest/report_index.json';
const TABS = ['Reports', 'Executive', 'Evidence', 'Exports'] as const;
type Tab = typeof TABS[number];

interface LaneEntry {
  report_id: string;
  title: string;
  owner: string;
  status: string;
  go_no_go: string | null;
  generated_at: string | null;
  stale: boolean;
  codex_passed: boolean | null;
  blocks_live: boolean;
  current_blockers: string[];
  next_action: string | null;
}

interface ReportIndexPayload {
  generated_at?: string;
  lanes?: LaneEntry[];
  report_count?: number;
}

export default function AdminReportsPage(): JSX.Element {
  const [tab, setTab] = useState<Tab>('Reports');
  const { envelope, loading, error } = useRealtimeResource<ReportIndexPayload>({ url: REPORTS_ENDPOINT, source: 'admin-reports', pollIntervalMs: 30_000 });
  const data = envelope.data;

  return (
    <div data-testid="admin-reports-page" style={{ background: 'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)', display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>Reports</h1>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-secondary)' }}>
            Operational reports, executive summary, evidence records, and export history.
          </p>
        </div>
        <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
      </div>

      <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid var(--line-soft)' }}>
        {TABS.map((t) => (
          <button key={t} type="button" onClick={() => setTab(t)} data-testid={`tab-${t.toLowerCase()}`}
            style={{ padding: '8px 16px', border: 'none', borderBottom: tab === t ? '2px solid var(--admin-accent)' : '2px solid transparent', background: 'none', color: tab === t ? 'var(--text-primary)' : 'var(--text-secondary)', cursor: 'pointer', fontWeight: tab === t ? 700 : 400, fontSize: 13 }}>
            {t}
          </button>
        ))}
      </div>

      {error && <MissingSourceIncident page="Reports" component="ReportIndex" source={REPORTS_ENDPOINT} owner="v2-report-center" remediation={`Check ${REPORTS_ENDPOINT}. Verify report center service is generating index.`} adminOnly />}

      {!error && tab === 'Reports' && (
        loading && !data ? <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>Loading reports…</div> :
        !data?.lanes?.length ? (
          <MissingSourceIncident page="Reports" component="LaneTable" source={REPORTS_ENDPOINT} owner="v2-report-center" remediation="No report lanes returned." adminOnly />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {data.lanes.filter(l => l.report_id).map((lane) => (
              <div key={lane.report_id} data-testid={`report-lane-${lane.report_id}`} style={{ padding: '12px 16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', display: 'grid', gridTemplateColumns: '1fr auto', gap: 12, alignItems: 'start' }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <span style={{ fontWeight: 600, fontSize: 14, color: 'var(--text-primary)' }}>{lane.title}</span>
                    {lane.go_no_go && (
                      <span style={{ padding: '2px 8px', borderRadius: 4, background: lane.go_no_go === 'GO' ? 'var(--buy-bg)' : 'var(--sell-bg)', color: lane.go_no_go === 'GO' ? 'var(--ok)' : 'var(--error)', fontSize: 11, fontWeight: 700, fontFamily: 'var(--font-mono)' }}>{lane.go_no_go}</span>
                    )}
                    {lane.stale && <span style={{ padding: '2px 8px', borderRadius: 4, background: 'color-mix(in oklch, var(--warn) 15%, transparent)', color: 'var(--warn)', fontSize: 11, fontFamily: 'var(--font-mono)' }}>STALE</span>}
                    {lane.blocks_live && <span style={{ padding: '2px 8px', borderRadius: 4, background: 'var(--sell-bg)', color: 'var(--error)', fontSize: 11, fontFamily: 'var(--font-mono)' }}>BLOCKS LIVE</span>}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>Owner: {lane.owner} &nbsp;|&nbsp; Generated: {relativeAge(lane.generated_at)}</div>
                  {lane.current_blockers?.length ? (
                    <div style={{ marginTop: 6, fontSize: 12, color: 'var(--error)' }}>Blockers: {lane.current_blockers.join(', ')}</div>
                  ) : null}
                  {lane.next_action && <div style={{ marginTop: 4, fontSize: 12, color: 'var(--warn)' }}>Next: {lane.next_action}</div>}
                </div>
                <span style={{ padding: '2px 8px', borderRadius: 4, background: statusBg(lane.status), color: statusColor(lane.status), fontSize: 11, fontWeight: 700, fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap' }}>{lane.status.toUpperCase()}</span>
              </div>
            ))}
          </div>
        )
      )}
      {!error && tab === 'Executive' && <MissingSourceIncident page="Reports" component="ExecutiveSummary" source="/api/v2/reports/executive" owner="v2-report-center" remediation="Wire /api/v2/reports/executive endpoint with plain-English migration/live readiness summary." adminOnly />}
      {!error && tab === 'Evidence' && <MissingSourceIncident page="Reports" component="EvidenceRecords" source="/api/v2/reports/evidence" owner="v2-report-center" remediation="Wire /api/v2/reports/evidence endpoint for operator proof records." adminOnly />}
      {!error && tab === 'Exports' && <MissingSourceIncident page="Reports" component="ExportHistory" source="/api/v2/reports/exports" owner="v2-report-center" remediation="Wire /api/v2/reports/exports endpoint." adminOnly />}
    </div>
  );
}
