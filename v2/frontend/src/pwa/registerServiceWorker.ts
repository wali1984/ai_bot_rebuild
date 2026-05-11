export function registerServiceWorker(): void {
  if (typeof window === 'undefined') return;
  if (!('serviceWorker' in navigator)) return;
  if (import.meta.env.DEV) {
    navigator.serviceWorker.getRegistrations()
      .then((registrations) => Promise.all(registrations.map((registration) => registration.unregister())))
      .catch(() => undefined);
    return;
  }
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
