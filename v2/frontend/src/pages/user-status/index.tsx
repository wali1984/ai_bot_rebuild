import type { ReactElement } from 'react';
import meta from './meta';
import rbac from './rbac';
import route from './route';
import { useFrontendTruthPayload } from '../../data/runtimePayloads';
import { SimpleCard, StatusBadge } from '../../components/status-simple/StatusBadge';
import { publicRuntimeCopy } from '../../lib/tradeCopy';

const EVIDENCE_UNAVAILABLE =
  'Status stream is connecting. We cannot show a status without current evidence.';
const PUBLIC_STATUS_SOURCE = 'Public status summary';

function statusColor(value: string): 'green' | 'yellow' | 'red' {
  const v = (value || '').toUpperCase();
  if (v.includes('PROVEN') || v === 'GREEN' || v === 'OK' || v === 'PASS') return 'green';
  if (v.includes('BLOCK') || v === 'RED' || v === 'FAIL') return 'red';
  return 'yellow';
}

function publicStatusText(value: string | null | undefined): string {
  if (!value?.trim()) return 'Connecting stream';
  return value
    .trim()
    .replace(/operator_runtime/gi, 'status source')
    .replace(/frontend_truth_payload/gi, 'public status summary')
    .replace(/payloads?/gi, 'source')
    .replace(/\/[A-Za-z0-9._/-]+/g, 'status source')
    .replace(/\b[A-Z0-9]+_[A-Z0-9_]+\b/g, (match) => match.replaceAll('_', ' ').toLowerCase());
}

function publicStatusRuntimeText(value: string | null | undefined): string {
  return publicRuntimeCopy(publicStatusText(value), 'Connecting stream');
}

export default function UserStatusPage(): ReactElement {
  const { payload, loading, error } = useFrontendTruthPayload();

  return (
    <article
      data-testid="page-user-status"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
      style={{ padding: 16, maxWidth: 960, margin: '0 auto', background: 'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)' }}
    >
      <header style={{ marginBottom: 12 }}>
        <h1 style={{ margin: 0 }}>{meta.title}</h1>
        <p style={{ margin: '4px 0 0 0', opacity: 0.8 }}>{meta.description}</p>
      </header>

      {loading && !payload && (
        <p data-testid="user-status-loading">Connecting status stream...</p>
      )}
      {error && !payload && (
        <p data-testid="user-status-error">
          <StatusBadge color="red" label="Evidence stream connecting" /> {EVIDENCE_UNAVAILABLE}
        </p>
      )}

      {payload && (
        <>
          <section
            data-testid="user-status-simple-summary"
            className="glass"
            style={{
              padding: 12,
              marginBottom: 12,
            }}
          >
            <p style={{ margin: 0, fontSize: '1.1rem' }}>
              <strong>{publicStatusRuntimeText(payload.plain_english_summary) || EVIDENCE_UNAVAILABLE}</strong>
            </p>
            <p style={{ margin: '4px 0 0 0' }}>
              <em>Today's goal:</em> {publicStatusRuntimeText(payload.current_goal) || EVIDENCE_UNAVAILABLE}
            </p>
            <div
              data-testid="user-status-badges"
              style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}
            >
              <StatusBadge
                color="red"
                label="Operator gate active"
              />
              <StatusBadge
                color={statusColor(payload.paper_edge_status)}
                label={`Execution edge: ${publicRuntimeCopy(payload.paper_edge_status, 'Connecting stream')}`}
              />
              <StatusBadge
                color={statusColor(payload.trainer_parity_status)}
                label={`Trainer parity: ${publicRuntimeCopy(payload.trainer_parity_status, 'Connecting stream')}`}
              />
              <StatusBadge
                color={statusColor(payload.decision_quality_status)}
                label={`Decision quality: ${publicRuntimeCopy(payload.decision_quality_status, 'Connecting stream')}`}
              />
              <StatusBadge
                color={statusColor(payload.shutdown_recommendation)}
                label={`Shutdown: ${publicRuntimeCopy(payload.shutdown_recommendation, 'Connecting stream')}`}
              />
            </div>
          </section>

          <section
            data-testid="user-status-blockers"
            style={{ marginBottom: 16 }}
          >
            <h2 style={{ marginBottom: 4 }}>Why order routing remains gated</h2>
            {payload.blockers_simple.length === 0 ? (
              <p>No blockers in plain English are reported right now.</p>
            ) : (
              <ul>
                {payload.blockers_simple.map((b) => (
                  <li key={b}>{publicStatusRuntimeText(b)}</li>
                ))}
              </ul>
            )}
          </section>

          <section
            data-testid="user-status-page-cards"
            style={{ marginBottom: 16 }}
          >
            <h2 style={{ marginBottom: 4 }}>What each part of the bot is doing</h2>
            {payload.page_cards.length === 0 ? (
              <p>No page cards reported.</p>
            ) : (
              payload.page_cards.map((card) => (
                <SimpleCard
                  key={card.id}
                  title={publicStatusRuntimeText(card.title)}
                  color={card.color}
                  summary={publicStatusRuntimeText(card.summary)}
                  whyItMatters={publicStatusRuntimeText(card.why_it_matters)}
                  whatNeedsToHappenNext={publicStatusRuntimeText(card.what_needs_to_happen_next)}
                  evidencePaths={[]}
                  sourceStatus={publicStatusRuntimeText(card.source_status).toUpperCase()}
                />
              ))
            )}
          </section>

          {(payload.stale_payloads.length > 0 || payload.missing_payloads.length > 0) && (
            <section
              data-testid="user-status-stale-missing"
              style={{
                padding: 12,
                marginBottom: 12,
                backgroundColor: 'rgba(255,200,0,0.05)',
                borderRadius: 8,
              }}
            >
              <h2 style={{ marginBottom: 4 }}>Some evidence is old or missing</h2>
              {payload.stale_payloads.length > 0 && (
                <p>
                  <strong>Old:</strong> {payload.stale_payloads.map(publicStatusRuntimeText).join(', ')}
                </p>
              )}
              {payload.missing_payloads.length > 0 && (
                <p>
                  <strong>Missing:</strong> {payload.missing_payloads.map(publicStatusRuntimeText).join(', ')}
                </p>
              )}
            </section>
          )}
        </>
      )}

      <footer style={{ marginTop: 24, opacity: 0.7, fontSize: '0.8rem' }}>
        <p>
          This page shows live account telemetry. It does not place orders, change leverage, or change live status.
          Order submission remains approval gated.
          Source: {PUBLIC_STATUS_SOURCE}.
        </p>
      </footer>
    </article>
  );
}
