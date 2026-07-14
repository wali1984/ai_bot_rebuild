import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { registerServiceWorker } from './pwa/registerServiceWorker';
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

// Deploy-safe dynamic imports: after a rebuild replaces hashed chunks, a
// long-lived tab's next lazy-route import 404s ("error loading dynamically
// imported module"). Vite surfaces that as `vite:preloadError` — reload once
// (rate-limited) to pick up the fresh index.html + chunk graph instead of
// stranding the user on the application error page.
window.addEventListener('vite:preloadError', (event) => {
  event.preventDefault();
  const key = 'nervyx-chunk-reload-at';
  const last = Number(sessionStorage.getItem(key) || 0);
  if (Date.now() - last > 15_000) {
    sessionStorage.setItem(key, String(Date.now()));
    window.location.reload();
  }
});

const root = document.getElementById('root');
if (!root) throw new Error('root element missing');
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

registerServiceWorker();
