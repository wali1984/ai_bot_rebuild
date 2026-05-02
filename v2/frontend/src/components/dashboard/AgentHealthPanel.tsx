import { useAgentHealth } from '../../hooks/useAgentHealth';

export function AgentHealthPanel(): JSX.Element {
  const { data, error, isLoading } = useAgentHealth();

  if (isLoading) {
    return (
      <section className="dashboard-panel" data-testid="agent-health-panel" data-state="loading">
        <h2>Agent Health</h2>
        <p>Loading…</p>
      </section>
    );
  }

  if (error || !data) {
    return (
      <section className="dashboard-panel" data-testid="agent-health-panel" data-state="error">
        <h2>Agent Health</h2>
        <p role="alert">Unable to load agent health.</p>
      </section>
    );
  }

  const hb = data.heartbeat;
  const ah = data.agent_health;
  const stale = data.heartbeat_stale;

  return (
    <section
      className="dashboard-panel"
      data-testid="agent-health-panel"
      data-state="ok"
      data-heartbeat-stale={String(stale)}
      data-heartbeat-missing={String(data.heartbeat_missing)}
    >
      <h2>Agent Health</h2>
      <dl>
        <dt>Heartbeat pid</dt>
        <dd data-testid="agent-health-pid">{hb ? hb.pid : 'missing'}</dd>
        <dt>Heartbeat age (s)</dt>
        <dd data-testid="agent-health-age">
          {data.heartbeat_age_s == null ? 'unknown' : Math.round(data.heartbeat_age_s)}
        </dd>
        <dt>Loop count</dt>
        <dd>{hb ? hb.loop_count : '—'}</dd>
        <dt>Current task</dt>
        <dd data-testid="agent-health-current-task">{hb?.current_task ?? '—'}</dd>
        <dt>Tmux session</dt>
        <dd>{hb?.tmux_session ?? '—'}</dd>
        <dt>Supervisor version</dt>
        <dd>{ah?.supervisor_version ?? hb?.version ?? '—'}</dd>
        <dt>Active agents</dt>
        <dd>{ah ? ah.active_agents.join(', ') : '—'}</dd>
      </dl>
      {stale ? (
        <p data-testid="agent-health-stale-warning" role="alert">
          Supervisor heartbeat is stale (age ≥ 600s).
        </p>
      ) : null}
    </section>
  );
}
