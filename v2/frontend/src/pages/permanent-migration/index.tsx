import type { ReactElement } from 'react';
import meta from './meta';
import rbac from './rbac';
import route from './route';
import { useFrontendTruthPayload } from '../../data/runtimePayloads';
import { SimpleCard, StatusBadge } from '../../components/status-simple/StatusBadge';
import { publicRuntimeCopy } from '../../lib/tradeCopy';

const EVIDENCE_MISSING = 'Evidence missing. The page will not invent values.';

export default function PermanentMigrationPage(): ReactElement {
  const { payload, loading, error } = useFrontendTruthPayload();

  return (
    <article
      data-testid="page-permanent-migration"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
      style={{ padding: 16 }}
    >
      <header style={{ marginBottom: 12 }}>
        <h1 style={{ margin: 0 }}>{meta.title}</h1>
        <p style={{ margin: '4px 0 0 0', opacity: 0.8 }}>{publicRuntimeCopy(meta.description)}</p>
      </header>

      {loading && !payload && <p>Loading frontend truth payload...</p>}
      {error && !payload && (
        <p data-testid="permanent-migration-error">
          <StatusBadge color="red" label="Missing evidence" /> {EVIDENCE_MISSING} ({error})
        </p>
      )}

      {payload && (
        <>
          <section
            data-testid="permanent-migration-simple-summary"
            style={{
              padding: 12,
              marginBottom: 12,
              backgroundColor: 'rgba(255,255,255,0.04)',
              borderRadius: 8,
            }}
          >
            <p style={{ margin: 0, fontSize: '1.1rem' }}>
              <strong>{publicRuntimeCopy(payload.plain_english_summary)}</strong>
            </p>
            <p style={{ margin: '4px 0 0 0' }}>
              <em>Today's goal:</em> {publicRuntimeCopy(payload.current_goal)}
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
              <StatusBadge color="red" label={`Live: ${payload.live_gate}`} />
              <StatusBadge color="yellow" label={`Edge: ${publicRuntimeCopy(payload.paper_edge_status)}`} />
              <StatusBadge color="yellow" label={`Trainer: ${payload.trainer_parity_status}`} />
              <StatusBadge color="yellow" label={`Decision quality: ${payload.decision_quality_status}`} />
              <StatusBadge color="yellow" label={`Shutdown: ${payload.shutdown_recommendation}`} />
            </div>
          </section>

          <section style={{ marginBottom: 16 }}>
            <h2 style={{ marginBottom: 4 }}>What is the bot doing right now?</h2>
            <p>
              <strong>Active Claude task:</strong> <code>{payload.active_claude_task}</code>
            </p>
            <p>
              <strong>Active Codex task:</strong> <code>{payload.active_codex_task}</code>
            </p>
            <p>
              <strong>Last completed fix:</strong> <code>{payload.last_completed_fix}</code>
            </p>
            <p>
              <strong>Next fix:</strong> <code>{payload.next_fix}</code>
            </p>
          </section>

          <section style={{ marginBottom: 16 }}>
            <h2 style={{ marginBottom: 4 }}>Why shutdown is blocked</h2>
            {payload.blockers_simple.length === 0 ? (
              <p>No simple-English blockers reported.</p>
            ) : (
              <ul>
                {payload.blockers_simple.map((b) => (
                  <li key={b}>{publicRuntimeCopy(b)}</li>
                ))}
              </ul>
            )}
          </section>

          <section style={{ marginBottom: 16 }}>
            <h2 style={{ marginBottom: 4 }}>Per-page status</h2>
            {payload.page_cards.map((card) => (
              <SimpleCard
                key={card.id}
                title={publicRuntimeCopy(card.title)}
                color={card.color}
                summary={publicRuntimeCopy(card.summary)}
                whyItMatters={publicRuntimeCopy(card.why_it_matters)}
                whatNeedsToHappenNext={publicRuntimeCopy(card.what_needs_to_happen_next)}
                evidencePaths={card.evidence_paths.map((item) => publicRuntimeCopy(item))}
                sourceStatus={publicRuntimeCopy(card.source_status)}
              />
            ))}
          </section>

          {(payload.stale_payloads.length > 0 || payload.missing_payloads.length > 0) && (
            <section
              style={{
                padding: 12,
                marginBottom: 12,
                backgroundColor: 'rgba(255,200,0,0.05)',
                borderRadius: 8,
              }}
            >
              <h2 style={{ marginBottom: 4 }}>Stale or missing evidence</h2>
              {payload.stale_payloads.length > 0 && (
                <p>
                  <strong>Stale:</strong> {payload.stale_payloads.map((item) => publicRuntimeCopy(item)).join(', ')}
                </p>
              )}
              {payload.missing_payloads.length > 0 && (
                <p>
                  <strong>Missing:</strong> {payload.missing_payloads.map((item) => publicRuntimeCopy(item)).join(', ')}
                </p>
              )}
            </section>
          )}
        </>
      )}

      <footer style={{ marginTop: 24, opacity: 0.7, fontSize: '0.8rem' }}>
        <p>
          This page does not authorize live, canary, legacy shutdown, or Redis trim. Source payload:{' '}
          <code>/operator_runtime/frontend_truth/latest/frontend_truth_payload.json</code>
        </p>
      </footer>
    </article>
  );
}
