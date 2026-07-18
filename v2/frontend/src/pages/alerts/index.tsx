import { useState, type FormEvent } from 'react';
import meta from './meta';
import rbac from './rbac';
import route from './route';
import { createV2Alert, deleteV2Alert, updateV2Alert } from '../../api/v2Alerts';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import type { AlertsData } from '../../types/apiV2';

export { default as meta } from './meta';
export { default as rbac } from './rbac';
export { default as route } from './route';

const ALERT_TYPES = [
  'Price movement',
  'Funding rate',
  'Open interest',
  'Liquidation activity',
  'Signal change',
  'Risk state',
] as const;

function FormField({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</span>
      {children}
    </label>
  );
}

const inputStyle: React.CSSProperties = {
  padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)',
  background: 'var(--bg-elevated)', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)',
  fontSize: 13, outline: 'none', width: '100%',
};

export default function AlertsPage(): JSX.Element {
  const { envelope: alertsEnvelope, loading, refetch: refetchAlerts } = useRealtimeResource<AlertsData>({
    url: '/api/v2/alerts',
    source: '/api/v2/alerts',
    source_type: 'websocket',
    pollIntervalMs: 15_000,
    staleThresholdMs: 45_000,
    initialFetch: true,
    httpFallback: true,
    mode: 'read_only',
  });
  const [alertsOverride, setAlertsOverride] = useState<AlertsData | null>(null);
  const [alertType, setAlertType] = useState<(typeof ALERT_TYPES)[number]>('Price movement');
  const [symbol, setSymbol] = useState('BTCUSDT');
  const [condition, setCondition] = useState('Last price above');
  const [threshold, setThreshold] = useState('125000');
  const [actionError, setActionError] = useState<string | null>(null);

  const alertData = alertsOverride ?? alertsEnvelope.data;
  const supportedAlertTypes = alertData?.supported_alert_types?.length
    ? alertData.supported_alert_types
    : [...ALERT_TYPES];
  const savedAlerts = alertData?.alerts ?? [];
  const createEnabled = alertData?.create_enabled === true;
  const deliveryStatus = alertData?.delivery_status ?? (loading ? 'connecting' : 'unavailable');
  const repoStatus = alertData?.repository_status ?? 'unknown';

  async function submitAlert(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setActionError(null);
    try {
      const next = await createV2Alert({
        alert_type: alertType,
        symbol,
        condition,
        threshold: threshold.trim() ? Number(threshold) : null,
        enabled: true,
      });
      setAlertsOverride(next.data);
      void refetchAlerts();
    } catch {
      setActionError('Alert action unavailable. Sign in with a scoped trader account.');
    }
  }

  async function toggleMute(alertId: string, muted: boolean): Promise<void> {
    setActionError(null);
    try {
      const next = await updateV2Alert(alertId, { muted: !muted });
      setAlertsOverride(next.data);
      void refetchAlerts();
    }
    catch { setActionError('Alert update unavailable.'); }
  }

  async function removeAlert(alertId: string): Promise<void> {
    setActionError(null);
    try {
      const next = await deleteV2Alert(alertId);
      setAlertsOverride(next.data);
      void refetchAlerts();
    }
    catch { setActionError('Alert delete unavailable.'); }
  }

  return (
    <div
      data-testid="page-alerts"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
      style={{ background: 'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)', paddingBottom: 64, maxWidth: '100%', overflowX: 'hidden' }}
    >
      {/* Header */}
      <div style={{ padding: '20px 24px 16px', background: 'color-mix(in oklch, var(--bg-panel) 82%, transparent)', backdropFilter: 'blur(8px)', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div style={{ minWidth: 0 }}>
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>Alerts</h1>
            <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
              Price · Funding · OI · Liquidation · Signal · Risk · Notification delivery: {deliveryStatus.replaceAll('_', ' ')}
            </p>
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', minWidth: 0 }}>
            <span style={{ padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 600, background: createEnabled ? 'var(--buy-bg)' : 'var(--bg-elevated)', color: createEnabled ? 'var(--buy)' : 'var(--text-muted)', border: `1px solid ${createEnabled ? 'var(--buy-border)' : 'var(--border)'}` }}>
              {createEnabled ? 'Alerts available' : 'Alert actions unavailable'}
            </span>
            <span style={{ padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 600, background: 'var(--buy-bg)', color: 'var(--buy)', border: '1px solid var(--buy-border)' }}>Realtime stream</span>
          </div>
        </div>
      </div>

      {/* Readiness summary */}
      <div style={{ padding: '16px 24px 0' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 12, marginBottom: 20 }}>
          {[
            { label: 'Alert API', value: loading ? 'Checking…' : alertData ? (alertsEnvelope.source_type === 'unavailable' ? 'Unavailable' : 'Connected') : 'Unavailable', color: alertData && alertsEnvelope.source_type !== 'unavailable' ? 'var(--buy)' : 'var(--sell)' },
            { label: 'Repository', value: repoStatus.replaceAll('_', ' ') },
            { label: 'Saved Alerts', value: String(savedAlerts.length) },
            { label: 'Create Enabled', value: createEnabled ? 'Yes' : 'No', color: createEnabled ? 'var(--buy)' : 'var(--sell)' },
            { label: 'Delivery', value: deliveryStatus.replaceAll('_', ' ') },
          ].map((item) => (
            <div key={item.label} className="glass" style={{ minWidth: 0, padding: '12px 14px' }}>
              <span style={{ display: 'block', fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{item.label}</span>
              <span style={{ display: 'block', minWidth: 0, fontSize: 13, fontWeight: 600, fontFamily: 'var(--font-mono)', color: item.color ?? 'var(--text-primary)', overflowWrap: 'anywhere', wordBreak: 'break-word' }}>{item.value}</span>
            </div>
          ))}
        </div>
      </div>

      <div style={{ padding: '0 24px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 280px), 1fr))', gap: 24, alignItems: 'start', maxWidth: '100%', boxSizing: 'border-box' }}>
        {/* Create alert form */}
        <div style={{ minWidth: 0 }}>
          <h2 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Create Alert</h2>
          {!createEnabled ? (
            <div className="glass" style={{ minWidth: 0, padding: '20px', textAlign: 'center' }}>
              <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>
                Alert creation unavailable. The alert API is not connected or requires a scoped trader account.
              </p>
            </div>
          ) : (
            <form
              onSubmit={(e) => void submitAlert(e)}
              className="glass"
              style={{ padding: '18px', display: 'flex', flexDirection: 'column', gap: 14 }}
            >
              <FormField label="Alert type">
                <select value={alertType} onChange={(e) => setAlertType(e.target.value as (typeof ALERT_TYPES)[number])} style={inputStyle}>
                  {supportedAlertTypes.map((label) => (
                    <option value={label} key={label}>{label}</option>
                  ))}
                </select>
              </FormField>
              <FormField label="Symbol">
                <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} style={inputStyle} />
              </FormField>
              <FormField label="Condition">
                <input value={condition} onChange={(e) => setCondition(e.target.value)} style={inputStyle} />
              </FormField>
              <FormField label="Threshold">
                <input inputMode="decimal" value={threshold} onChange={(e) => setThreshold(e.target.value)} style={inputStyle} />
              </FormField>
              <button
                type="submit"
                style={{
                  padding: '10px 16px', borderRadius: 'var(--radius-sm)', border: 'none',
                  background: 'var(--accent)', color: '#fff', fontWeight: 700, fontSize: 13,
                  cursor: 'pointer', fontFamily: 'var(--font-sans)',
                }}
              >
                Save Alert
              </button>
              {actionError && (
                <p style={{ margin: 0, fontSize: 12, color: 'var(--sell)', fontFamily: 'var(--font-mono)' }}>{actionError}</p>
              )}
              <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)' }}>
                Alerts are account-scoped local records. Notification delivery is disabled until a delivery service is connected.
              </p>
            </form>
          )}
        </div>

        {/* Saved alerts */}
        <div style={{ minWidth: 0 }}>
          <h2 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>
            Saved Alerts ({savedAlerts.length})
          </h2>
          {savedAlerts.length === 0 ? (
            <div className="glass" style={{ minWidth: 0, padding: '28px', textAlign: 'center' }}>
              <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>
                No alerts saved yet. {createEnabled ? 'Use the form to create one.' : 'Alert creation unavailable.'}
              </p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {savedAlerts.map((alert) => (
                <div
                  key={alert.id}
                  className="glass"
                  style={{
                    padding: '14px 16px',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8, marginBottom: 8 }}>
                    <div>
                      <span style={{ fontWeight: 700, fontSize: 13, fontFamily: 'var(--font-mono)' }}>{alert.symbol}</span>
                      <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 8 }}>{alert.alert_type}</span>
                    </div>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, background: alert.enabled ? 'var(--buy-bg)' : 'var(--bg-elevated)', color: alert.enabled ? 'var(--buy)' : 'var(--text-muted)', border: `1px solid ${alert.enabled ? 'var(--buy-border)' : 'var(--border)'}` }}>
                        {alert.enabled ? 'Enabled' : 'Disabled'}
                      </span>
                      {alert.muted && (
                        <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, background: 'var(--bg-elevated)', color: 'var(--text-muted)', border: '1px solid var(--border)' }}>Muted</span>
                      )}
                    </div>
                  </div>
                  <p style={{ margin: '0 0 10px', fontSize: 12, color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
                    {alert.condition}{alert.threshold != null ? ` ${alert.threshold}` : ''} · Delivery disabled
                  </p>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button
                      type="button"
                      onClick={() => void toggleMute(alert.id, alert.muted)}
                      style={{ padding: '5px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', fontSize: 12, cursor: 'pointer' }}
                    >
                      {alert.muted ? 'Unmute' : 'Mute'}
                    </button>
                    <button
                      type="button"
                      onClick={() => void removeAlert(alert.id)}
                      style={{ padding: '5px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--sell-border)', background: 'transparent', color: 'var(--sell)', fontSize: 12, cursor: 'pointer' }}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Planned alert types */}
      <div style={{ padding: '24px 24px 0' }}>
        <h2 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Alert Types</h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 10 }}>
          {supportedAlertTypes.map((label) => (
            <div key={label} className="glass" style={{ padding: '12px 14px' }}>
              <p style={{ margin: '0 0 3px', fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)' }}>{label}</p>
              <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)' }}>
                {createEnabled ? 'Alerts can be saved. Notification delivery disabled.' : 'Unavailable until alert repository is wired.'}
              </p>
            </div>
          ))}
        </div>
      </div>

      <div style={{ padding: '20px 24px', marginTop: 8, borderTop: '1px solid var(--border)' }}>
        <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)' }}>
          Alerts are account-scoped local records for the signed-in trader. Notification delivery and production alert audit storage are not wired yet. No fake delivered alerts are shown.
        </p>
      </div>
    </div>
  );
}
