import { useQueueStatus } from '../../hooks/useQueueStatus';

/**
 * StaleStateAlertsPanel — surfaces every alert category enumerated in
 * `claude_worklog/agent_supervisor_reliability/02_IMPLEMENTATION_REPORT.md`
 * §1.10 / §1.11:
 *
 *   - stale_running              (process dead / no pgrep / output mtime old)
 *   - no_event                   (last_event_ts older than threshold)
 *   - no_output_growth           (stdout/stderr/summary mtimes idle)
 *   - blocked_quota              (Claude/Codex quota exhausted)
 *   - human_attention_required   (retries exhausted; secret_scan blocked)
 */
export function StaleStateAlertsPanel(): JSX.Element {
  const { data, isLoading, error } = useQueueStatus();

  const empty = (
    <p data-testid="stale-state-empty">No stale-state alerts active.</p>
  );

  if (isLoading) {
    return (
      <section className="dashboard-panel" data-testid="stale-state-alerts-panel" data-state="loading">
        <h2>Stale-State Alerts</h2>
        <p>Loading…</p>
      </section>
    );
  }
  if (error || !data || !data.data) {
    return (
      <section className="dashboard-panel" data-testid="stale-state-alerts-panel" data-state="error">
        <h2>Stale-State Alerts</h2>
        <p role="alert">Alert feed unavailable.</p>
      </section>
    );
  }

  const q = data.data;
  const stale = q.stale_running_tasks;
  const noEvent = q.no_event_tasks;
  const noOutput = q.no_output_growth_tasks;
  const quota = q.blocked_quota;
  const human = q.human_attention_required_tasks;
  const total =
    stale.length +
    noEvent.length +
    noOutput.length +
    (quota ? 1 : 0) +
    human.length;

  return (
    <section
      className="dashboard-panel"
      data-testid="stale-state-alerts-panel"
      data-state="ok"
      data-alert-total={total}
    >
      <h2>Stale-State Alerts</h2>

      <div className="alert-group" data-testid="stale-state-stale-running" data-count={stale.length}>
        <h3>stale_running</h3>
        {stale.length === 0 ? (
          empty
        ) : (
          <ul>
            {stale.map((tid) => (
              <li key={tid} data-testid="alert-task-id" data-alert-kind="stale_running" data-task-id={tid}>
                {tid}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="alert-group" data-testid="stale-state-no-event" data-count={noEvent.length}>
        <h3>no_event</h3>
        {noEvent.length === 0 ? (
          empty
        ) : (
          <ul>
            {noEvent.map((tid) => (
              <li key={tid} data-testid="alert-task-id" data-alert-kind="no_event" data-task-id={tid}>
                {tid}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div
        className="alert-group"
        data-testid="stale-state-no-output-growth"
        data-count={noOutput.length}
      >
        <h3>no_output_growth</h3>
        {noOutput.length === 0 ? (
          empty
        ) : (
          <ul>
            {noOutput.map((tid) => (
              <li
                key={tid}
                data-testid="alert-task-id"
                data-alert-kind="no_output_growth"
                data-task-id={tid}
              >
                {tid}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div
        className="alert-group"
        data-testid="stale-state-blocked-quota"
        data-count={quota ? 1 : 0}
      >
        <h3>blocked_quota</h3>
        {!quota ? (
          empty
        ) : (
          <ul>
            <li
              key={quota.task_id}
              data-testid="alert-task-id"
              data-alert-kind="blocked_quota"
              data-task-id={quota.task_id}
              data-resume-after={quota.resume_after_utc ?? ''}
            >
              {quota.task_id}
              {quota.agent ? ` (agent=${quota.agent})` : null}
              {quota.resume_after_utc ? ` resume_after=${quota.resume_after_utc}` : null}
            </li>
          </ul>
        )}
      </div>

      <div
        className="alert-group"
        data-testid="stale-state-human-attention-required"
        data-count={human.length}
      >
        <h3>human_attention_required</h3>
        {human.length === 0 ? (
          empty
        ) : (
          <ul>
            {human.map((t) => (
              <li
                key={t.task_id}
                data-testid="alert-task-id"
                data-alert-kind="human_attention_required"
                data-task-id={t.task_id}
                data-attention-reason={t.attention_reason ?? ''}
              >
                {t.task_id}
                {t.attention_reason ? ` — ${t.attention_reason}` : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
