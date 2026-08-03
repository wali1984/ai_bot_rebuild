import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { MissingSourceIncident } from '../../components/data/MissingSourceIncident';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { useState } from 'react';

const TABS = ['Scripts', 'Build', 'Coverage', 'Migrations', 'AI Tools', 'Codex'] as const;
type Tab = typeof TABS[number];

const ENDPOINTS: Record<Tab, string> = {
  Scripts: '/api/v2/admin/scripts',
  Build: '/api/v2/admin/build/status',
  Coverage: '/api/v2/admin/coverage',
  Migrations: '/api/v2/admin/migrations',
  'AI Tools': '/api/v2/admin/ai/status',
  Codex: '/api/v2/admin/codex/status',
};

const SC = { ok: '#22c55e', warn: '#f59e0b', error: '#ef4444', unknown: '#6b7280', info: '#60a5fa', block: '#ef4444' };

function StatusDot({ status }: { status: string }) {
  const c = status === 'ok' || status === 'ready' || status === 'active' || status === 'applied' || status === 'available' ? SC.ok
    : status === 'warn' || status === 'partial' || status === 'idle' ? SC.warn
    : status === 'error' || status === 'block' || status === 'blocked' || status === 'failed' || status === 'unavailable' ? SC.error
    : SC.unknown;
  return <span style={{ width: 7, height: 7, borderRadius: '50%', background: c, display: 'inline-block', flexShrink: 0 }} />;
}

function Row({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 0', borderBottom: '1px solid var(--line-soft)', gap: 8 }}>
      <span style={{ fontSize: 11, color: 'var(--text-muted)', flexShrink: 0 }}>{label}</span>
      <span style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)', textAlign: 'right' }}>{value ?? '—'}</span>
    </div>
  );
}

function Panel({ children }: { children: React.ReactNode }) {
  return (
    <div className="glass" style={{ padding: 16 }}>
      {children}
    </div>
  );
}

function SectionLabel({ label }: { label: string }) {
  return (
    <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10 }}>
      {label}
    </div>
  );
}

function ScriptsTab({ data }: { data: Record<string, unknown> | null }) {
  if (!data) return null;
  const scripts = (data.scripts as Record<string, unknown>[] | undefined) ?? [];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Panel>
        <SectionLabel label={`Script Registry — ${data.total ?? 0} scripts`} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 400, overflowY: 'auto' }}>
          {scripts.map((s, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 8px', borderRadius: 5, background: 'var(--bg-base)', border: '1px solid var(--line-soft)' }}>
              <StatusDot status={String(s.status ?? 'unknown')} />
              <span style={{ flex: 1, fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>{String(s.name ?? '')}</span>
              <span style={{ fontSize: 10, color: 'var(--text-muted)', flexShrink: 0 }}>{String(s.owner ?? '')}</span>
              <span style={{ fontSize: 10, color: 'var(--text-muted)', flexShrink: 0, fontFamily: 'var(--font-mono)' }}>{String(s.classification ?? '')}</span>
            </div>
          ))}
          {scripts.length === 0 && <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No scripts found</div>}
        </div>
      </Panel>
    </div>
  );
}

function BuildTab({ data }: { data: Record<string, unknown> | null }) {
  if (!data) return null;
  const overall = String(data.overall ?? 'pending');
  const artifacts = (data.artifacts as Record<string, unknown>[] | undefined) ?? [];
  const trust = data.pipeline_trust as Record<string, unknown> | null | undefined;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <StatusDot status={overall} />
        <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>Build: {overall.toUpperCase()}</span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{artifacts.length} artifacts</span>
      </div>
      {trust && (
        <Panel>
          <SectionLabel label="Pipeline Trust Report" />
          <Row label="Overall" value={String(trust.overall_result ?? '—')} />
          <Row label="Warnings" value={Number(trust.warnings ?? 0)} />
          <Row label="Failures" value={Number(trust.failures ?? 0)} />
          <Row label="Generated" value={String(trust.generated_at ?? '—')} />
        </Panel>
      )}
      <Panel>
        <SectionLabel label="Artifacts" />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 360, overflowY: 'auto' }}>
          {artifacts.map((a, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '5px 8px', borderRadius: 5, background: 'var(--bg-base)', border: '1px solid var(--line-soft)' }}>
              <StatusDot status={String(a.status ?? 'unknown')} />
              <span style={{ flex: 1, fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>{String(a.name ?? '')}</span>
              <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{a.size_bytes ? `${Math.round(Number(a.size_bytes) / 1024)}KB` : ''}</span>
            </div>
          ))}
          {artifacts.length === 0 && <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No artifacts found</div>}
        </div>
      </Panel>
    </div>
  );
}

function CoverageTab({ data }: { data: Record<string, unknown> | null }) {
  if (!data) return null;
  const pct = Number(data.coverage_pct ?? 0);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Panel>
        <SectionLabel label="File Coverage" />
        <Row label="Files Total" value={Number(data.files_total ?? 0)} />
        <Row label="Files Classified" value={Number(data.files_classified ?? 0)} />
        <Row label="Coverage %" value={`${pct}%`} />
        <Row label="Source" value={String(data.source_file ?? '—')} />
      </Panel>
      {!!data.classification_summary && (
        <Panel>
          <SectionLabel label="By Classification" />
          {Object.entries(data.classification_summary as Record<string, unknown>).map(([k, v]) => (
            <Row key={k} label={k} value={String(v)} />
          ))}
        </Panel>
      )}
      {!!data.data_surface_summary && (
        <Panel>
          <SectionLabel label="Data Surfaces" />
          <Row label="Total" value={String(data.data_surfaces ?? '—')} />
        </Panel>
      )}
    </div>
  );
}

function MigrationsTab({ data }: { data: Record<string, unknown> | null }) {
  if (!data) return null;
  const migrations = (data.migrations as Record<string, unknown>[] | undefined) ?? [];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Panel>
        <SectionLabel label={`Migration History — ${data.total ?? 0} total (${data.applied ?? 0} applied)`} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 400, overflowY: 'auto' }}>
          {migrations.map((m, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 8px', borderRadius: 5, background: 'var(--bg-base)', border: '1px solid var(--line-soft)' }}>
              <StatusDot status={String(m.status ?? 'unknown')} />
              <span style={{ flex: 1, fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>{String(m.name ?? '')}</span>
              {!!m.description && <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{String(m.description)}</span>}
              <span style={{ fontSize: 10, color: 'var(--text-muted)', flexShrink: 0 }}>{String(m.applied_at ?? '').slice(0, 10)}</span>
            </div>
          ))}
          {migrations.length === 0 && <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No migration files found</div>}
        </div>
      </Panel>
    </div>
  );
}

function AIToolsTab({ data }: { data: Record<string, unknown> | null }) {
  if (!data) return null;
  const claude = data.claude as Record<string, unknown> | undefined;
  const ollama = data.ollama as Record<string, unknown> | undefined;
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12 }}>
      <Panel>
        <SectionLabel label="Claude Supervision" />
        {claude && (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <StatusDot status={String(claude.status ?? 'unknown')} />
              <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
                {String(claude.status ?? 'unknown').toUpperCase()}
              </span>
            </div>
            <Row label="Model" value={String(claude.model ?? '—')} />
            <Row label="Session Active" value={claude.session_active ? 'YES' : 'NO'} />
            <Row label="Last Activity" value={String(claude.last_activity_at ?? '—').replace('T', ' ').slice(0, 19)} />
            <Row label="Redis Key" value={String(claude.supervision_redis_key ?? '—')} />
          </>
        )}
      </Panel>
      <Panel>
        <SectionLabel label="Ollama Local Assistant" />
        {ollama && (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <StatusDot status={String(ollama.status ?? 'unknown')} />
              <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
                {String(ollama.status ?? 'unknown').toUpperCase()}
              </span>
            </div>
            <Row label="Available" value={ollama.available ? 'YES' : 'NO'} />
            <Row label="Model" value={String(ollama.model ?? '—')} />
            <Row label="Endpoint" value={String(ollama.endpoint ?? '—')} />
          </>
        )}
      </Panel>
      <Panel>
        <SectionLabel label="Safety Locks" />
        <Row label="Live Mutation" value="BLOCKED" />
        <Row label="Supervision" value={data.supervision_enabled ? 'ENABLED' : 'DISABLED'} />
        <Row label="Live Trading" value={data.live_mutation_allowed ? 'ALLOWED' : 'BLOCKED'} />
      </Panel>
    </div>
  );
}

function CodexTab({ data }: { data: Record<string, unknown> | null }) {
  if (!data) return null;
  const milestones = (data.milestones as Record<string, unknown>[] | undefined) ?? [];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Panel>
        <SectionLabel label="Codex Review Summary" />
        <Row label="Open Reviews" value={Number(data.open_count ?? 0)} />
        <Row label="Blockers" value={Number(data.blocker_count ?? 0)} />
        <Row label="Last Pass ID" value={String(data.last_pass_id ?? '—')} />
        <Row label="Last Fail ID" value={String(data.last_fail_id ?? '—')} />
        {!!data.last_blocker_text && <Row label="Last Blocker" value={String(data.last_blocker_text)} />}
      </Panel>
      {milestones.length > 0 && (
        <Panel>
          <SectionLabel label={`Review Files — ${data.total ?? 0} found`} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 360, overflowY: 'auto' }}>
            {milestones.map((m, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 8px', borderRadius: 5, background: 'var(--bg-base)', border: '1px solid var(--line-soft)' }}>
                <StatusDot status={String(m.result ?? 'unknown') === 'PASS' ? 'ok' : String(m.result ?? '') === 'FAIL' ? 'error' : 'unknown'} />
                <span style={{ flex: 1, fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)', wordBreak: 'break-all' }}>{String(m.id ?? '')}</span>
                <span style={{ fontSize: 10, color: 'var(--text-muted)', flexShrink: 0 }}>{String(m.last_reviewed_at ?? '').slice(0, 10)}</span>
              </div>
            ))}
          </div>
        </Panel>
      )}
    </div>
  );
}

function TabContent({ tab, data, loading, error }: {
  tab: Tab;
  data: Record<string, unknown> | null;
  loading: boolean;
  error: string | null;
}) {
  const endpoint = ENDPOINTS[tab];
  if (loading && !data) {
    return <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: '12px 0' }}>Loading…</div>;
  }
  if (!data) {
    return (
      <MissingSourceIncident
        page="Developer Tools"
        component={tab}
        source={endpoint}
        owner={`v2-${tab.toLowerCase().replace(/\s/g, '-')}`}
        remediation={`Wire ${endpoint} endpoint.`}
        adminOnly
      />
    );
  }
  if (tab === 'Scripts') return <ScriptsTab data={data} />;
  if (tab === 'Build') return <BuildTab data={data} />;
  if (tab === 'Coverage') return <CoverageTab data={data} />;
  if (tab === 'Migrations') return <MigrationsTab data={data} />;
  if (tab === 'AI Tools') return <AIToolsTab data={data} />;
  if (tab === 'Codex') return <CodexTab data={data} />;
  return null;
}

export default function AdminToolsPage(): JSX.Element {
  const [tab, setTab] = useState<Tab>('Scripts');

  const scripts = useRealtimeResource<Record<string, unknown>>({ url: ENDPOINTS.Scripts, source: ENDPOINTS.Scripts, pollIntervalMs: 60_000 });
  const build = useRealtimeResource<Record<string, unknown>>({ url: ENDPOINTS.Build, source: ENDPOINTS.Build, pollIntervalMs: 60_000 });
  const coverage = useRealtimeResource<Record<string, unknown>>({ url: ENDPOINTS.Coverage, source: ENDPOINTS.Coverage, pollIntervalMs: 120_000 });
  const migrations = useRealtimeResource<Record<string, unknown>>({ url: ENDPOINTS.Migrations, source: ENDPOINTS.Migrations, pollIntervalMs: 120_000 });
  const aiTools = useRealtimeResource<Record<string, unknown>>({ url: ENDPOINTS['AI Tools'], source: ENDPOINTS['AI Tools'], pollIntervalMs: 30_000 });
  const codex = useRealtimeResource<Record<string, unknown>>({ url: ENDPOINTS.Codex, source: ENDPOINTS.Codex, pollIntervalMs: 60_000 });

  const resourceMap: Record<Tab, typeof scripts> = {
    Scripts: scripts,
    Build: build,
    Coverage: coverage,
    Migrations: migrations,
    'AI Tools': aiTools,
    Codex: codex,
  };

  const current = resourceMap[tab];

  return (
    <div data-testid="admin-tools-page" style={{ display: 'flex', flexDirection: 'column', gap: 20, background: 'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>Developer Tools</h1>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-secondary)' }}>
            Scripts, build validation, coverage, migrations, AI tools, and Codex review. Superadmin only.
          </p>
        </div>
        <FreshnessBadge status={current.envelope.freshness_status} lagMs={current.envelope.lag_ms} />
      </div>

      <div
        data-testid="tools-superadmin-notice"
        style={{ padding: '10px 16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', fontSize: 13, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}
      >
        SUPERADMIN ONLY — Developer tools expose internal system state. Collapsed by default in admin navigation.
      </div>

      <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid var(--line-soft)', flexWrap: 'wrap' }}>
        {TABS.map((t) => (
          <button key={t} type="button" onClick={() => setTab(t)} data-testid={`tab-${t.toLowerCase().replace(/\s/g, '-')}`}
            style={{ padding: '8px 14px', border: 'none', borderBottom: tab === t ? '2px solid var(--admin-accent)' : '2px solid transparent', background: 'none', color: tab === t ? 'var(--text-primary)' : 'var(--text-secondary)', cursor: 'pointer', fontWeight: tab === t ? 700 : 400, fontSize: 13, whiteSpace: 'nowrap' }}>
            {t}
          </button>
        ))}
      </div>

      <section>
        <TabContent
          tab={tab}
          data={current.envelope.data ?? null}
          loading={current.loading}
          error={current.error}
        />
      </section>
    </div>
  );
}
