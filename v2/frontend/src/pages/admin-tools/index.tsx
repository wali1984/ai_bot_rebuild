import { useState } from 'react';
import { MissingSourceIncident } from '../../components/data/MissingSourceIncident';

const TABS = ['Scripts', 'Build', 'Coverage', 'Migrations', 'AI Tools', 'Codex'] as const;
type Tab = typeof TABS[number];

const TOOL_SOURCES: Record<Tab, { source: string; owner: string; remediation: string; description: string }> = {
  Scripts: { source: '/api/v2/admin/scripts', owner: 'v2-script-registry', remediation: 'Wire /api/v2/admin/scripts endpoint from script-registry.', description: 'Script registry: usage evidence, owner, schedule, last-run, and classification.' },
  Build: { source: '/api/v2/admin/build/status', owner: 'v2-build', remediation: 'Wire /api/v2/admin/build/status endpoint.', description: 'Build artifact states, READY/BLOCKED markers, and CI validation results.' },
  Coverage: { source: '/api/v2/admin/coverage', owner: 'v2-coverage', remediation: 'Wire /api/v2/admin/coverage endpoint with file inventory and classifier state.', description: 'File inventory, coverage atlas, and classification for legacy + V2 surfaces.' },
  Migrations: { source: '/api/v2/admin/migrations', owner: 'v2-migration', remediation: 'Wire /api/v2/admin/migrations endpoint with migration history.', description: 'Schema/data migration history and status.' },
  'AI Tools': { source: '/api/v2/admin/ai/status', owner: 'v2-ai', remediation: 'Wire /api/v2/admin/ai/status endpoint for Claude/Ollama supervision health.', description: 'Claude supervision dashboard and Ollama local assistant integration. No live mutation.' },
  Codex: { source: '/api/v2/admin/codex/status', owner: 'v2-codex', remediation: 'Wire /api/v2/admin/codex/status endpoint with review status across milestones.', description: 'Codex review status, milestone gates, and GO/NO-GO evidence across milestones.' },
};

export default function AdminToolsPage(): JSX.Element {
  const [tab, setTab] = useState<Tab>('Scripts');
  const tool = TOOL_SOURCES[tab];

  return (
    <div data-testid="admin-tools-page" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>Developer Tools</h1>
        <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-secondary)' }}>
          Scripts, build validation, coverage, migrations, AI tools, and Codex review. Superadmin only.
        </p>
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
        <p style={{ color: 'var(--text-secondary)', fontSize: 13, marginBottom: 12 }}>{tool.description}</p>
        <MissingSourceIncident
          page="Developer Tools"
          component={tab}
          source={tool.source}
          owner={tool.owner}
          remediation={tool.remediation}
          adminOnly
        />
      </section>
    </div>
  );
}
