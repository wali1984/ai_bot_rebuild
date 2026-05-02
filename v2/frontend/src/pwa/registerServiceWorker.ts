export function registerServiceWorker(): void {
  if (typeof window === 'undefined') return;
  if (!('serviceWorker' in navigator)) return;
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/service-worker.js', { scope: '/' })
      .catch((err) => {
        // Registration failure is non-fatal; the app must keep working.
        // eslint-disable-next-line no-console
        console.warn('[pwa] service worker registration failed:', err);
      });
  });
}
