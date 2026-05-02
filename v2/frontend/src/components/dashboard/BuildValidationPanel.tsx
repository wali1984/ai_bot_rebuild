import { useBuildStatus } from '../../hooks/useBuildStatus';
import { useAuditChain } from '../../hooks/useAuditChain';

export function BuildValidationPanel(): JSX.Element {
  const builds = useBuildStatus(10);
  const audit = useAuditChain(50);

  if (builds.isLoading || audit.isLoading) {
    return (
      <section className="dashboard-panel" data-testid="build-validation-panel" data-state="loading">
        <h2>Build / Validation Status</h2>
        <p>Loading…</p>
      </section>
    );
  }
  if (builds.error || !builds.data) {
    return (
      <section className="dashboard-panel" data-testid="build-validation-panel" data-state="error">
        <h2>Build / Validation Status</h2>
        <p role="alert">Build status unavailable.</p>
      </section>
    );
  }

  const runs = builds.data.runs;
  const chainIntact = audit.data?.chain_intact ?? null;
  const chainBreaks = audit.data?.chain_breaks ?? [];

  return (
    <section
      className="dashboard-panel"
      data-testid="build-validation-panel"
      data-state="ok"
      data-chain-intact={String(chainIntact)}
      data-runs-returned={builds.data._meta.returned}
    >
      <h2>Build / Validation Status</h2>

      <div className="audit-chain">
        <h3>Audit chain</h3>
        <p data-testid="audit-chain-state">
          {chainIntact == null
            ? 'unknown'
            : chainIntact
              ? 'intact'
              : `BROKEN (${chainBreaks.length} break(s))`}
        </p>
        {chainBreaks.length > 0 ? (
          <ul data-testid="audit-chain-breaks">
            {chainBreaks.map((b) => (
              <li key={`${b.index}`}>
                idx={b.index} task={b.task_id ?? '—'} prev={b.previous_ts} cur={b.current_ts}
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      <div className="recent-runs">
        <h3>Recent runs</h3>
        <ul data-testid="recent-runs">
          {runs.map((r) => (
            <li
              key={r.task_id}
              data-testid="recent-run"
              data-task-id={r.task_id}
              data-status={r.status}
              data-timed-out={String(r.timed_out)}
            >
              <strong>{r.task_id}</strong> — {r.status}
              {r.agent ? ` (agent=${r.agent})` : null}
              {r.start_time ? ` at ${r.start_time}` : null}
              {r.attention_reason ? ` [attention: ${r.attention_reason}]` : null}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
