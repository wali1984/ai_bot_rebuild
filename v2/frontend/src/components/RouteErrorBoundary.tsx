import { useEffect } from 'react';
import { useRouteError, useNavigate } from 'react-router-dom';
import { isStaleChunkError, reloadForStaleChunkOnce } from '../utils/staleChunk';

/**
 * Router-level error boundary. React Router renders this (via `errorElement`)
 * when a route — including a lazy `Component` import — throws. Its primary job is
 * to auto-recover from a stale code-split chunk after a redeploy: those surface
 * here as "error loading dynamically imported module: .../index-<oldhash>.js",
 * which React Router catches before any window error handler. On that class we
 * reload once (rate-limited) to pick up the fresh build; otherwise we show a
 * minimal, non-blank error card with a retry.
 */
export function RouteErrorBoundary(): JSX.Element {
  const error = useRouteError();
  const navigate = useNavigate();
  const stale = isStaleChunkError(
    error instanceof Error ? error.message : (error as { message?: unknown })?.message ?? error,
  );

  useEffect(() => {
    if (stale) reloadForStaleChunkOnce();
  }, [stale]);

  if (stale) {
    return (
      <div
        data-testid="route-error-stale-chunk"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '60vh',
          color: 'var(--text-muted, #94a3b8)',
          fontFamily: 'var(--font-mono, ui-monospace, monospace)',
          fontSize: 13,
        }}
      >
        Updating to the latest version…
      </div>
    );
  }

  const message = error instanceof Error ? error.message : String(error ?? 'Unknown error');
  return (
    <div
      data-testid="route-error-boundary"
      role="alert"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '60vh',
        padding: 24,
        textAlign: 'center',
        color: 'var(--text, #e5e7eb)',
        fontFamily: 'var(--font-mono, ui-monospace, monospace)',
      }}
    >
      <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--error, #ef4444)' }}>
        Something went wrong on this page
      </div>
      <div style={{ fontSize: 12, color: 'var(--text-muted, #94a3b8)', maxWidth: 560, wordBreak: 'break-word' }}>
        {message}
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <button
          type="button"
          onClick={() => navigate(0)}
          style={{
            fontSize: 12,
            padding: '6px 14px',
            borderRadius: 8,
            border: '1px solid var(--border, #2a2a2a)',
            background: 'var(--bg-elevated, #1a1a1a)',
            color: 'inherit',
            cursor: 'pointer',
          }}
        >
          Retry
        </button>
        <button
          type="button"
          onClick={() => window.location.reload()}
          style={{
            fontSize: 12,
            padding: '6px 14px',
            borderRadius: 8,
            border: '1px solid var(--border, #2a2a2a)',
            background: 'transparent',
            color: 'inherit',
            cursor: 'pointer',
          }}
        >
          Reload app
        </button>
      </div>
    </div>
  );
}
