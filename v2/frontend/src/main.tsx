import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { registerServiceWorker } from './pwa/registerServiceWorker';
import { isStaleChunkError, reloadForStaleChunkOnce } from './utils/staleChunk';
import './brand/generated/nervyx-tokens.css';
import './styles.css';
import './styles/tokens.css';
import './styles/layout.css';
import './styles/components.css';
import './styles/charts.css';
import './styles/tables.css';
import './styles/admin.css';
import './styles/theme-dark.css';
import './styles/theme-light.css';
import './styles/responsive.css';
import './styles/glass.css';

// Deploy-safe dynamic imports: after a rebuild replaces hashed chunks, a
// long-lived tab's next lazy-route import 404s. This surfaces in several ways:
//   - Vite's own `vite:preloadError` event, and
//   - a plain rejected import() that React Router catches and renders as
//     "Unexpected Application Error! error loading dynamically imported module:
//     .../index-<oldhash>.js" (the vite:preloadError event does NOT fire for
//     these router-lazy failures).
// Reload ONCE (rate-limited via sessionStorage) so the browser fetches the fresh
// index.html + chunk graph instead of stranding the user on the error page.
// (The router-level RouteErrorBoundary handles the same class for React Router
// lazy failures, which React catches before these window handlers fire.)
window.addEventListener('vite:preloadError', (event) => {
  event.preventDefault();
  reloadForStaleChunkOnce();
});
window.addEventListener('unhandledrejection', (event) => {
  const reason = (event as PromiseRejectionEvent).reason;
  if (isStaleChunkError(reason)) reloadForStaleChunkOnce();
});
window.addEventListener('error', (event) => {
  if (isStaleChunkError((event as ErrorEvent).message)) reloadForStaleChunkOnce();
});

const root = document.getElementById('root');
if (!root) throw new Error('root element missing');
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

registerServiceWorker();

// DEV-ONLY visual-editing toolbar (Stagewise). `import.meta.env.DEV` is statically
// replaced with `false` in production builds, so this block and the entire
// ./dev/stagewise chunk (+ the @stagewise/toolbar devDependency) are dead-code-
// eliminated and never ship to prod. Fails silently — never blocks the app.
if (import.meta.env.DEV) {
  void import('./dev/stagewise')
    .then((m) => m.mountStagewiseDevToolbar())
    .catch(() => {});
}
