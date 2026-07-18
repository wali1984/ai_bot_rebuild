import meta from './meta';
import rbac from './rbac';
import route from './route';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';

interface CodexLatest {
  open_count: number;
  blocker_count: number;
  last_pass_id: string | null;
  last_fail_id: string | null;
  last_blocker_text: string | null;
}

interface CodexMilestone {
  id: string;
  path: string;
  result: string;
  pass_count: number;
  fail_count: number;
  last_reviewed_at: string | null;
}

interface CodexStatus { generated_at: string; milestones: CodexMilestone[] }

function KV({ label, value, color }: { label: string; value: string; color?: string }): JSX.Element {
  return (
    <div className="glass" style={{ padding: '12px 14px' }}>
      <span style={{ display: 'block', fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{label}</span>
      <span style={{ fontSize: 15, fontWeight: 700, fontFamily: 'var(--font-mono)', color: color ?? 'var(--text-primary)' }}>{value}</span>
    </div>
  );
}

function resultColor(result: string): string {
  const r = result.toLowerCase();
  if (r === 'pass' || r === 'passed') return 'var(--buy)';
  if (r === 'fail' || r === 'failed') return 'var(--sell)';
  return 'var(--text-muted)';
}

export default function CodexReviewCenterPage(): JSX.Element {
  const latest = useRealtimeResource<CodexLatest>({
    url: '/api/v2/codex/reviews/latest', source: '/api/v2/codex/reviews/latest',
    source_type: 'websocket', pollIntervalMs: 30_000, staleThresholdMs: 120_000, mode: 'read_only',
    unwrapEnvelopeData: false,
  });
  const status = useRealtimeResource<CodexStatus>({
    url: '/api/v2/admin/codex/status', source: '/api/v2/admin/codex/status',
    source_type: 'websocket', pollIntervalMs: 60_000, staleThresholdMs: 300_000, mode: 'read_only',
    unwrapEnvelopeData: false,
  });
  const l = latest.envelope.data;
  const milestones = status.envelope.data?.milestones ?? [];

  return (
    <div data-testid="page-codex-review-center" data-page-id={meta.id} data-page-path={route.path} data-page-min-role={rbac.minRole}
      style={{ background: 'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)', paddingBottom: 48 }}>
      <div style={{ padding: '20px 24px 16px', background: 'color-mix(in oklch, var(--bg-panel) 82%, transparent)', borderBottom: '1px solid var(--border)', backdropFilter: 'blur(8px)' }}>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>Codex Review Center</h1>
        <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
          Adversarial review gates · milestone verdicts · blockers
        </p>
      </div>

      <div style={{ padding: '16px 24px 0', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))', gap: 12 }}>
        <KV label="Open reviews" value={String(l?.open_count ?? '—')} color={l?.open_count ? 'var(--warn)' : 'var(--buy)'} />
        <KV label="Blockers" value={String(l?.blocker_count ?? '—')} color={l?.blocker_count ? 'var(--sell)' : 'var(--buy)'} />
        <KV label="Last pass" value={l?.last_pass_id ?? 'none recorded'} />
        <KV label="Last fail" value={l?.last_fail_id ?? 'none recorded'} />
      </div>

      {l?.last_blocker_text && (
        <div style={{ margin: '14px 24px 0', padding: '10px 14px', border: '1px solid var(--sell)', borderRadius: 8, background: 'color-mix(in oklch, var(--sell) 8%, transparent)' }}>
          <span style={{ fontSize: 12, color: 'var(--sell)' }}>{l.last_blocker_text}</span>
        </div>
      )}

      <div style={{ padding: '20px 24px 0' }}>
        <h2 style={{ margin: '0 0 10px', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>
          Milestone Reviews ({milestones.length})
        </h2>
        {status.loading && milestones.length === 0 ? (
          <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>Loading milestone review artifacts…</p>
        ) : milestones.length === 0 ? (
          <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>No milestone review artifacts found on disk.</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
              <thead>
                <tr style={{ background: 'var(--bg-elevated)' }}>
                  {['Milestone', 'Result', 'Pass', 'Fail', 'Last reviewed', 'Artifact'].map((h) => (
                    <th key={h} style={{ padding: '8px 12px', fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {milestones.map((m, i) => (
                  <tr key={m.id} style={{ background: i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-panel)' }}>
                    <td style={{ padding: '8px 12px', fontWeight: 600, color: 'var(--text-primary)' }}>{m.id}</td>
                    <td style={{ padding: '8px 12px', fontWeight: 700, color: resultColor(m.result) }}>{m.result.toUpperCase()}</td>
                    <td style={{ padding: '8px 12px', color: 'var(--buy)' }}>{m.pass_count}</td>
                    <td style={{ padding: '8px 12px', color: m.fail_count ? 'var(--sell)' : 'var(--text-muted)' }}>{m.fail_count}</td>
                    <td style={{ padding: '8px 12px', color: 'var(--text-secondary)' }}>{m.last_reviewed_at?.slice(0, 19).replace('T', ' ') ?? '—'}</td>
                    <td style={{ padding: '8px 12px', color: 'var(--text-muted)', fontSize: 10, overflowWrap: 'anywhere' }}>{m.path}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
