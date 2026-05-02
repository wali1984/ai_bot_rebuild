import { useQueueStatus } from '../../hooks/useQueueStatus';

export function QueueStatusPanel(): JSX.Element {
  const { data, error, isLoading } = useQueueStatus();

  if (isLoading) {
    return (
      <section className="dashboard-panel" data-testid="queue-status-panel" data-state="loading">
        <h2>Queue Status</h2>
        <p>Loading…</p>
      </section>
    );
  }
  if (error || !data || !data.data) {
    return (
      <section className="dashboard-panel" data-testid="queue-status-panel" data-state="error">
        <h2>Queue Status</h2>
        <p role="alert">Queue status unavailable ({data?._meta?.error ?? 'request failed'}).</p>
      </section>
    );
  }

  const q = data.data;
  return (
    <section
      className="dashboard-panel"
      data-testid="queue-status-panel"
      data-state="ok"
      data-gate={q.gate}
    >
      <h2>Queue Status</h2>
      <dl>
        <dt>Generated at</dt>
        <dd>{q.generated_at}</dd>
        <dt>Gate</dt>
        <dd data-testid="queue-status-gate">{q.gate}</dd>
        <dt>Current running</dt>
        <dd data-testid="queue-status-current-running">{q.current_running_task ?? '—'}</dd>
        <dt>Next pending</dt>
        <dd data-testid="queue-status-next-pending">{q.next_pending_task ?? '—'}</dd>
      </dl>
      <h3>Counts</h3>
      <ul data-testid="queue-status-counts">
        {Object.entries(q.counts).map(([k, v]) => (
          <li key={k} data-testid={`queue-count-${k}`}>
            {k}: {v}
          </li>
        ))}
      </ul>
    </section>
  );
}
