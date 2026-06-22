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

const root = document.getElementById('root');
if (!root) throw new Error('root element missing');
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

registerServiceWorker();
