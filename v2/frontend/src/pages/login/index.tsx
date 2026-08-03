import { CircleAlert, CircleCheck, Eye, EyeOff, LoaderCircle } from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { fetchAuthHealth, type AuthHealth } from '../../api/auth';
import meta from './meta';
import { useAuth } from '../../hooks/useAuth';

export default function LoginPage(): JSX.Element {
  const { error, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  const returnTo = params.get('returnTo') || '/dashboard';
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [authHealth, setAuthHealth] = useState<AuthHealth | null>(null);
  const [authHealthError, setAuthHealthError] = useState<string | null>(null);
  const [authHealthLoading, setAuthHealthLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setAuthHealthLoading(true);
    fetchAuthHealth()
      .then((health) => {
        if (!active) return;
        setAuthHealth(health);
        setAuthHealthError(null);
      })
      .catch(() => {
        if (!active) return;
        setAuthHealth(null);
        setAuthHealthError('Sign-in service health check failed');
      })
      .finally(() => {
        if (!active) return;
        setAuthHealthLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  const authHealthOnline =
    Boolean(authHealth?.login_endpoint_available) && authHealth?.status?.toLowerCase() === 'ok';
  const authHealthDegraded = Boolean(
    authHealthOnline && authHealth?.data_quality_status && authHealth.data_quality_status !== 'fresh',
  );
  const AuthHealthIcon = authHealthLoading ? LoaderCircle : authHealthOnline ? CircleCheck : CircleAlert;
  const authHealthLabel = authHealthLoading
    ? 'Checking sign-in service'
    : authHealthOnline
      ? 'Sign-in service online'
      : 'Sign-in service issue';
  const authHealthDetail = authHealthError
    ?? (authHealthDegraded ? `Auth store ${authHealth?.data_quality_status}` : authHealth?.freshness_status)
    ?? 'No health detail';

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setSubmitting(true);
    try {
      await login({ email, password });
      navigate(returnTo.startsWith('/') ? returnTo : '/dashboard', { replace: true });
    } catch {
      // useAuth owns the displayed error state; keep the submit event handled.
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      data-testid="page-login"
      data-page-id={meta.id}
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--bg-base)',
        padding: '24px 16px',
        boxSizing: 'border-box',
        overflowX: 'hidden',
      }}
    >
      {/* Background grid pattern */}
      <div
        aria-hidden="true"
        style={{
          position: 'fixed',
          inset: 0,
          backgroundImage:
            'linear-gradient(var(--border) 1px, transparent 1px), linear-gradient(90deg, var(--border) 1px, transparent 1px)',
          backgroundSize: '40px 40px',
          opacity: 0.3,
          pointerEvents: 'none',
        }}
      />
      {/* Ambient glow — gives the frosted glass colour to refract */}
      <div
        aria-hidden="true"
        style={{
          position: 'fixed',
          inset: 0,
          pointerEvents: 'none',
          background:
            'radial-gradient(58% 46% at 50% 40%, rgba(124,92,255,0.20), transparent 70%), radial-gradient(42% 42% at 80% 82%, rgba(45,212,191,0.10), transparent 70%)',
        }}
      />

      <div style={{ position: 'relative', width: '100%', maxWidth: 440, boxSizing: 'border-box' }}>
        {/* Brand header */}
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <img
            src="/brand/nervyx-one-symbol-gradient.svg"
            alt=""
            aria-hidden="true"
            className="glass-pulse"
            style={{
              width: 52,
              height: 52,
              borderRadius: 14,
              border: '1px solid var(--ai-border)',
              objectFit: 'contain',
              marginBottom: 14,
            }}
          />
          <h1
            style={{
              margin: '0 0 6px',
              fontSize: 26,
              fontWeight: 700,
              color: 'var(--text-primary)',
              letterSpacing: 0,
            }}
          >
            NERVYX ONE
          </h1>
          <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>
            Adaptive Market Intelligence
          </p>
        </div>

        {/* Login card — glassmorphism + entrance motion */}
        <div
          className="glass glass-sheen glass-rise"
          style={{
            padding: '28px 32px 32px',
            boxSizing: 'border-box',
          }}
        >
          <h2
            style={{
              margin: '0 0 20px',
              fontSize: 16,
              fontWeight: 600,
              color: 'var(--text-primary)',
            }}
          >
            Sign in to your account
          </h2>

          <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* Email field */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <label
                htmlFor="login-email"
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  color: 'var(--text-secondary)',
                  textTransform: 'uppercase',
                  letterSpacing: 0,
                }}
              >
                Email address
              </label>
              <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                <span
                  aria-hidden="true"
                  style={{
                    position: 'absolute',
                    left: 12,
                    color: 'var(--text-muted)',
                    fontSize: 15,
                    pointerEvents: 'none',
                    lineHeight: 1,
                    top: '50%',
                    transform: 'translateY(-50%)',
                  }}
                >
                  @
                </span>
                <input
                  id="login-email"
                  aria-label="Email"
                  autoComplete="email"
                  name="email"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="you@example.com"
                  required
                  style={{
                    width: '100%',
                    padding: '10px 12px 10px 34px',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border)',
                    background: 'var(--bg-elevated)',
                    color: 'var(--text-primary)',
                    fontSize: 14,
                    fontFamily: 'var(--font-sans)',
                    outline: 'none',
                    boxSizing: 'border-box',
                  }}
                />
              </div>
            </div>

            {/* Password field */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <label
                htmlFor="login-password"
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  color: 'var(--text-secondary)',
                  textTransform: 'uppercase',
                  letterSpacing: 0,
                }}
              >
                Password
              </label>
              <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                <span
                  aria-hidden="true"
                  style={{
                    position: 'absolute',
                    left: 12,
                    color: 'var(--text-muted)',
                    fontSize: 15,
                    pointerEvents: 'none',
                    lineHeight: 1,
                    top: '50%',
                    transform: 'translateY(-50%)',
                  }}
                >
                  *
                </span>
                <input
                  id="login-password"
                  autoComplete="current-password"
                  name="password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Enter password"
                  required
                  style={{
                    width: '100%',
                    padding: '10px 40px 10px 34px',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border)',
                    background: 'var(--bg-elevated)',
                    color: 'var(--text-primary)',
                    fontSize: 14,
                    fontFamily: 'var(--font-sans)',
                    outline: 'none',
                    boxSizing: 'border-box',
                  }}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  style={{
                    position: 'absolute',
                    right: 10,
                    top: '50%',
                    transform: 'translateY(-50%)',
                    padding: '4px 6px',
                    border: 'none',
                    background: 'none',
                    color: 'var(--text-muted)',
                    cursor: 'pointer',
                    fontSize: 11,
                    fontFamily: 'var(--font-mono)',
                    lineHeight: 1,
                  }}
                >
                  {showPassword ? <EyeOff size={15} strokeWidth={1.8} /> : <Eye size={15} strokeWidth={1.8} />}
                </button>
              </div>
            </div>

            {/* Error display */}
            {error ? (
              <div
                role="alert"
                style={{
                  padding: '10px 14px',
                  borderRadius: 'var(--radius-sm)',
                  background: 'color-mix(in oklch, var(--error) 12%, transparent)',
                  border: '1px solid color-mix(in oklch, var(--error) 40%, transparent)',
                  color: 'var(--error)',
                  fontSize: 13,
                  fontWeight: 500,
                }}
              >
                {error}
              </div>
            ) : null}

            {/* Submit button */}
            <button
              type="submit"
              disabled={submitting}
              style={{
                width: '100%',
                padding: '11px 16px',
                borderRadius: 'var(--radius-sm)',
                border: 'none',
                background: submitting ? 'var(--bg-elevated)' : 'var(--accent)',
                color: submitting ? 'var(--text-muted)' : 'var(--text-inverse, #fff)',
                fontSize: 14,
                fontWeight: 600,
                cursor: submitting ? 'not-allowed' : 'pointer',
                fontFamily: 'var(--font-sans)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 8,
                boxSizing: 'border-box',
              }}
            >
              {submitting ? (
                <>
                  <span
                    style={{
                      width: 13,
                      height: 13,
                      borderRadius: '50%',
                      border: '2px solid var(--text-muted)',
                      borderTopColor: 'transparent',
                      display: 'inline-block',
                      animation: 'af-spin 0.7s linear infinite',
                    }}
                  />
                  Signing in…
                </>
              ) : (
                'Sign in'
              )}
            </button>
          </form>

          {/* Access note */}
          <p
            style={{
              margin: '16px 0 0',
              fontSize: 11,
              color: 'var(--text-muted)',
              textAlign: 'center',
            }}
          >
            Backend-authenticated access only. Session permissions are verified server-side.
          </p>
          <div
            data-testid="auth-health-status"
            aria-live="polite"
            style={{
              margin: '12px 0 0',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 8,
              minHeight: 18,
              color: authHealthOnline
                ? authHealthDegraded
                  ? 'var(--warning, #b7791f)'
                  : 'var(--success, #22c55e)'
                : authHealthLoading
                  ? 'var(--text-muted)'
                  : 'var(--error)',
              fontSize: 11,
              textAlign: 'center',
              lineHeight: 1.35,
            }}
          >
            <AuthHealthIcon
              aria-hidden="true"
              size={13}
              strokeWidth={2}
              style={{ flex: '0 0 auto', animation: authHealthLoading ? 'af-spin 0.9s linear infinite' : undefined }}
            />
            <span>
              <strong style={{ fontWeight: 600 }}>{authHealthLabel}</strong>
              <span style={{ color: 'var(--text-muted)' }}> | {authHealthDetail}</span>
            </span>
          </div>
        </div>

      </div>

      {/* Spinner keyframe */}
      <style>{`@keyframes af-spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
