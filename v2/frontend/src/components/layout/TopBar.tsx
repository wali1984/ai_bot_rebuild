import { useState, useRef, useEffect } from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';
import { useRoles, canSee, normalizeRole, type RoleLike } from '../../auth/rbac';
import { NERVYX_BRAND, type NervyxModuleId } from '../../brand/nervyxBrand';
import { ThemeToggle } from './ThemeToggle';

interface TopBarProps {
  surface: 'app' | 'public';
  showSymbolSearch?: boolean;
}

const TRADER_NAV_LINKS: Array<{ label: string; to: string; module: NervyxModuleId; minRole?: RoleLike }> = [
  { label: 'Dashboard', to: '/dashboard', module: 'sense' },
  { label: 'Markets', to: '/markets', module: 'sense' },
  { label: 'Trade', to: '/trade', module: 'execute', minRole: 'trader' },
  { label: 'Derivatives', to: '/derivatives', module: 'sense', minRole: 'trader' },
  { label: 'Signals', to: '/signals', module: 'sense' },
  { label: 'AI', to: '/ai-predictions', module: 'core' },
  { label: 'Portfolio', to: '/portfolio', module: 'execute', minRole: 'trader' },
  { label: 'Backtests', to: '/backtests', module: 'replay', minRole: 'trader' },
  { label: 'Research', to: '/research', module: 'sense' },
  { label: 'Alerts', to: '/alerts', module: 'observe', minRole: 'trader' },
];

const PUBLIC_NAV_LINKS: Array<{ label: string; to: string; module: NervyxModuleId; minRole?: RoleLike }> = [
  { label: 'Home', to: '/', module: 'sense' },
  { label: 'Markets', to: '/markets', module: 'sense' },
  { label: 'Status', to: '/status', module: 'observe' },
];

function SymbolSearch(): JSX.Element {
  const [query, setQuery] = useState('');
  const navigate = useNavigate();

  function handleKey(e: React.KeyboardEvent<HTMLInputElement>): void {
    if (e.key === 'Enter' && query.trim()) {
      navigate(`/market/${query.trim().toUpperCase()}`);
      setQuery('');
    }
  }

  return (
    <div style={{ position: 'relative', flex: '0 1 180px', minWidth: 0, maxWidth: '100%' }}>
      <input
        type="search"
        placeholder="Search symbol…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={handleKey}
        aria-label="Search symbol"
        style={{
          width: 'min(180px, 100%)',
          minHeight: 32,
          padding: '0 10px',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm, 6px)',
          background: 'var(--bg-elevated)',
          color: 'var(--text-primary)',
          fontSize: 13,
          fontFamily: 'var(--font-sans)',
          outline: 'none',
        }}
      />
    </div>
  );
}

function ViewerBadge(): JSX.Element {
  return (
    <span
      title="Viewer access — market visibility. Trade, Portfolio, and Alerts require trader access."
      style={{
        padding: '3px 10px',
        borderRadius: 999,
        border: '1px solid var(--warn, #f59e0b)',
        color: 'var(--warn, #f59e0b)',
        background: 'color-mix(in oklch, var(--warn, #f59e0b) 10%, transparent)',
        fontSize: 11,
        fontWeight: 600,
        fontFamily: 'var(--font-mono)',
        textTransform: 'uppercase',
        letterSpacing: '0.06em',
        whiteSpace: 'nowrap',
      }}
    >
      Viewer Access
    </span>
  );
}

function UserMenu(): JSX.Element {
  const { user, logout } = useAuth();
  const role = useRoles();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handler(e: MouseEvent): void {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  if (!user) {
    return (
      <Link
        to="/login"
        style={{
          padding: '6px 14px',
          borderRadius: 'var(--radius-sm, 6px)',
          border: '1px solid var(--border)',
          background: 'var(--bg-elevated)',
          color: 'var(--text-primary)',
          fontSize: 13,
          textDecoration: 'none',
          fontWeight: 600,
        }}
      >
        Sign in
      </Link>
    );
  }

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 7,
          padding: '5px 10px',
          borderRadius: 'var(--radius-sm, 6px)',
          border: '1px solid var(--border)',
          background: 'var(--bg-elevated)',
          color: 'var(--text-primary)',
          fontSize: 12,
          cursor: 'pointer',
          fontFamily: 'var(--font-sans)',
        }}
        aria-label="User menu"
        aria-expanded={open}
      >
        <span
          style={{
            width: 22,
            height: 22,
            borderRadius: '50%',
            background: 'var(--accent, #3b82f6)',
            color: '#fff',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 11,
            fontWeight: 700,
            flexShrink: 0,
          }}
        >
          {user.username?.[0]?.toUpperCase() ?? user.email?.[0]?.toUpperCase() ?? 'U'}
        </span>
        <span style={{ maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {user.username || user.email}
        </span>
        <span style={{ fontSize: 9, opacity: 0.6 }}>▼</span>
      </button>

      {open && (
        <div
          style={{
            position: 'absolute',
            top: 'calc(100% + 6px)',
            right: 0,
            minWidth: 190,
            borderRadius: 'var(--radius-md, 8px)',
            border: '1px solid var(--border)',
            background: 'var(--bg-elevated)',
            boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
            zIndex: 400,
            overflow: 'hidden',
          }}
          role="menu"
        >
          <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
              {user.username || 'Account'}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginTop: 2 }}>
              {role}
            </div>
          </div>
          <button
            onClick={() => { void logout(); setOpen(false); }}
            style={{
              display: 'block',
              width: '100%',
              textAlign: 'left',
              padding: '9px 14px',
              border: 'none',
              background: 'none',
              fontSize: 13,
              color: 'var(--error, #ef4444)',
              cursor: 'pointer',
              fontFamily: 'var(--font-sans)',
            }}
            role="menuitem"
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

export function TopBar({ surface, showSymbolSearch = true }: TopBarProps): JSX.Element {
  const sessionRole = useRoles();
  const { user, loading: authLoading } = useAuth();
  const topbarRole = user?.role ? normalizeRole(user.role) : sessionRole;
  const isViewer = topbarRole === 'viewer';

  const navLinks = surface === 'app' ? TRADER_NAV_LINKS : PUBLIC_NAV_LINKS;

  // Filter nav links by role
  const visibleLinks = navLinks.filter((link) => {
    if (!link.minRole) return true;
    return canSee(topbarRole, link.minRole);
  });

  return (
    <header
      data-testid="topbar"
      className="topbar-shell"
    >
      <Link
        to={surface === 'app' ? '/dashboard' : '/'}
        aria-label="NERVYX ONE home"
        className="nervyx-brand-lockup"
      >
        <img
          src={NERVYX_BRAND.assets.logoOnMidnight}
          alt="NERVYX ONE"
          className="nervyx-brand-lockup__logo nervyx-brand-lockup__logo--dark"
        />
        <img
          src={NERVYX_BRAND.assets.logoOnLight}
          alt=""
          aria-hidden="true"
          className="nervyx-brand-lockup__logo nervyx-brand-lockup__logo--light"
        />
        <span className="nervyx-brand-lockup__stack">
          <span className="nervyx-brand-lockup__descriptor">{NERVYX_BRAND.descriptor}</span>
        </span>
      </Link>

      <nav
        className="topbar-primary-nav"
        aria-label={surface === 'app' ? 'Trader navigation' : 'Public navigation'}
      >
        {visibleLinks.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            className={({ isActive }) => (
              isActive ? 'topbar-primary-nav__link topbar-primary-nav__link--active' : 'topbar-primary-nav__link'
            )}
            data-nervyx-module={link.module}
          >
            <span className="topbar-primary-nav__link-inner">
              <span className="topbar-primary-nav__label">{link.label}</span>
            </span>
          </NavLink>
        ))}
      </nav>

      <div className="topbar-actions">
        {!authLoading && isViewer && <ViewerBadge />}

        {!authLoading && user?.role && canSee(normalizeRole(user.role), 'admin') ? (
          <nav
            data-testid="admin-nav"
            aria-label="Ops terminal navigation"
            className="topbar-admin-nav"
          >
            <NavLink
              to="/admin"
              className={({ isActive }) => (
                isActive ? 'topbar-admin-nav__link topbar-admin-nav__link--active' : 'topbar-admin-nav__link'
              )}
            >
              NERVYX OBSERVE
            </NavLink>
          </nav>
        ) : null}

        {showSymbolSearch && surface === 'app' && <SymbolSearch />}

        {surface === 'app' || surface === 'public' ? <ThemeToggle /> : null}
        <UserMenu />
      </div>
    </header>
  );
}
