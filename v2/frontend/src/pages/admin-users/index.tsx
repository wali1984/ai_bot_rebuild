import { useState } from 'react';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { relativeAge } from '../../data/adminFieldRegistry';

const USERS_ENDPOINT = '/api/v2/admin/users';
const TABS = ['Users', 'Roles'] as const;
type Tab = typeof TABS[number];
const SC = { ok: '#22c55e', warn: '#f59e0b', error: '#ef4444', unknown: '#6b7280', info: '#60a5fa' };

// Backend sends session_count: null honestly — auth is stateless JWT, so
// per-user live sessions are not tracked (session_tracking flag below).
interface User { id: string; email: string; role: string; status: string; created_at: string | null; last_login_at: string | null; session_count: number | null; }
interface UsersPayload { users?: User[]; total?: number; active_sessions?: number | null; active_users?: number; session_tracking?: string; }

const ROLE_LEVELS = ['guest', 'viewer', 'trader', 'admin', 'superadmin'] as const;
function roleColor(role: string) {
  if (role === 'superadmin') return SC.error;
  if (role === 'admin') return SC.warn;
  if (role === 'trader') return SC.info;
  return SC.unknown;
}

export default function AdminUsersPage(): JSX.Element {
  const [tab, setTab] = useState<Tab>('Users');
  const { envelope, loading } = useRealtimeResource<UsersPayload>({ url: USERS_ENDPOINT, source: 'admin-users', pollIntervalMs: 30_000 });
  const data = envelope.data;
  const users = data?.users || [];

  return (
    <div data-testid="admin-users-page" style={{ display: 'flex', flexDirection: 'column', gap: 18, background: 'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)' }}>

      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>Users</h1>
          <p style={{ margin: '3px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>User list, roles, and account state</p>
        </div>
        <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
      </div>

      {/* Stat tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 10 }}>
        {/* When the endpoint has not returned data (error/403), render '—' —
            a zero here would falsely assert a zero-user system. */}
        {[
          { label: 'TOTAL USERS', value: data ? String(data.total ?? users.length) : '—' },
          { label: 'ACTIVE SESSIONS', value: data?.active_sessions != null ? String(data.active_sessions) : data?.session_tracking === 'not_tracked_stateless_jwt' ? 'NOT TRACKED' : '—' },
          { label: 'ADMINS', value: data ? String(users.filter(u => u.role === 'admin' || u.role === 'superadmin').length) : '—' },
          { label: 'ACTIVE', value: data ? String(data.active_users ?? users.filter(u => u.status === 'active').length) : '—' },
        ].map(({ label, value }) => (
          <div key={label} style={{ padding: '10px 14px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', display: 'flex', flexDirection: 'column', gap: 3 }}>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>{label}</span>
            <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{value}</span>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 2, borderBottom: '1px solid var(--line-soft)' }}>
        {TABS.map(t => (
          <button key={t} type="button" onClick={() => setTab(t)} style={{
            padding: '7px 16px', border: 'none', background: 'none', cursor: 'pointer', fontSize: 12,
            fontWeight: tab === t ? 700 : 400, color: tab === t ? 'var(--text-primary)' : 'var(--text-muted)',
            borderBottom: tab === t ? '2px solid var(--admin-accent)' : '2px solid transparent',
          }}>{t}</button>
        ))}
      </div>

      {tab === 'Users' && (
        loading && !data ? <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: '12px 0' }}>Loading users…</div> :
        users.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            {users.map(u => (
              <div key={u.id} data-testid={`user-row-${u.id}`} style={{ display: 'grid', gridTemplateColumns: '1fr auto auto auto auto', gap: 12, alignItems: 'center', padding: '10px 14px', borderRadius: 6, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
                <div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>{u.email}</div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginTop: 2 }}>id: {u.id}</div>
                </div>
                <span style={{ padding: '2px 8px', borderRadius: 4, background: `${roleColor(u.role)}20`, border: `1px solid ${roleColor(u.role)}44`, color: roleColor(u.role), fontSize: 10, fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
                  {u.role.toUpperCase()}
                </span>
                <span style={{ padding: '2px 8px', borderRadius: 4, background: u.status === 'active' ? `${SC.ok}18` : `${SC.unknown}18`, border: `1px solid ${u.status === 'active' ? SC.ok : SC.unknown}33`, color: u.status === 'active' ? SC.ok : SC.unknown, fontSize: 10, fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
                  {u.status.toUpperCase()}
                </span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap' }} title={u.session_count == null ? (data?.session_tracking ?? 'sessions not tracked (stateless JWT)') : undefined}>
                  {u.session_count == null ? 'sessions not tracked' : u.session_count > 0 ? `${u.session_count} sessions` : 'no sessions'}
                </span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                  {u.last_login_at ? relativeAge(u.last_login_at) : 'never'}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ padding: '12px 14px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', color: 'var(--text-muted)', fontSize: 12 }}>
            No users returned from <span style={{ fontFamily: 'var(--font-mono)', color: SC.info }}>{USERS_ENDPOINT}</span>
          </div>
        )
      )}

      {tab === 'Roles' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {ROLE_LEVELS.map((role, i) => {
            const count = users.filter(u => u.role === role).length;
            return (
              <div key={role} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px', borderRadius: 6, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
                <span style={{ width: 20, height: 20, borderRadius: '50%', background: `${roleColor(role)}22`, border: `1px solid ${roleColor(role)}55`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, color: roleColor(role), fontWeight: 700, flexShrink: 0 }}>{i}</span>
                <span style={{ flex: 1, fontSize: 13, fontWeight: 600, fontFamily: 'var(--font-mono)', color: roleColor(role) }}>{role}</span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{count > 0 ? `${count} user${count !== 1 ? 's' : ''}` : 'no users'}</span>
                {users.filter(u => u.role === role).slice(0, 3).map(u => (
                  <span key={u.id} style={{ fontSize: 10, padding: '2px 6px', borderRadius: 3, background: 'var(--bg-panel)', border: '1px solid var(--line-soft)', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{u.email.split('@')[0]}</span>
                ))}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
