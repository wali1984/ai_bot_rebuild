import meta from './meta';
import rbac from './rbac';
import route from './route';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';

interface OllamaHealth {
  model: string;
  ready: boolean;
  last_draft_at: string | null;
}

function KV({ label, value, color }: { label: string; value: string; color?: string }): JSX.Element {
  return (
    <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius-md, 10px)', padding: '12px 14px' }}>
      <span style={{ display: 'block', fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{label}</span>
      <span style={{ fontSize: 15, fontWeight: 700, fontFamily: 'var(--font-mono)', color: color ?? 'var(--text-primary)' }}>{value}</span>
    </div>
  );
}

const RULES: Array<{ text: string; allowed: boolean }> = [
  { text: 'Summarize low-risk files and compress logs', allowed: true },
  { text: 'Draft script inventories and evidence packet descriptions', allowed: true },
  { text: 'Group anomalies for Claude review', allowed: true },
  { text: 'Make final safety claims or decide risk', allowed: false },
  { text: 'Approve strategy or live trading', allowed: false },
  { text: 'Mutate the legacy bot', allowed: false },
];

export default function OllamaLocalAssistantPage(): JSX.Element {
  const health = useRealtimeResource<OllamaHealth>({
    url: '/api/v2/ollama/health', source: '/api/v2/ollama/health',
    source_type: 'websocket', pollIntervalMs: 30_000, staleThresholdMs: 120_000, mode: 'read_only',
    unwrapEnvelopeData: false,
  });
  const d = health.envelope.data;

  return (
    <div data-testid="page-ollama-local-assistant" data-page-id={meta.id} data-page-path={route.path} data-page-min-role={rbac.minRole}
      style={{ background: 'var(--bg-base)', paddingBottom: 48 }}>
      <div style={{ padding: '20px 24px 16px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>Ollama Local Assistant</h1>
        <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
          Local support model for summaries and drafts · outputs verified against raw evidence before acceptance
        </p>
      </div>

      <div style={{ padding: '16px 24px 0', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(190px, 1fr))', gap: 12 }}>
        <KV label="Status" value={health.loading && !d ? '…' : d?.ready ? 'READY' : 'OFFLINE'} color={d?.ready ? 'var(--buy)' : 'var(--sell)'} />
        <KV label="Model" value={d?.model ?? '—'} />
        <KV label="Last draft" value={d?.last_draft_at ? d.last_draft_at.slice(0, 19).replace('T', ' ') : 'no drafts recorded'} />
      </div>

      <div style={{ padding: '20px 24px 0' }}>
        <h2 style={{ margin: '0 0 10px', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Operating Boundaries</h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 10 }}>
          {RULES.map((rule) => (
            <div key={rule.text} style={{ display: 'flex', alignItems: 'center', gap: 10, background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px' }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: rule.allowed ? 'var(--buy)' : 'var(--sell)' }}>
                {rule.allowed ? '✓' : '✗'}
              </span>
              <span style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>{rule.text}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
