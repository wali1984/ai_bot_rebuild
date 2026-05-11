# Stale Dev Server Cache Check

Generated at: 2026-05-11T22:49:45Z

## Vite Process

One Vite dev server was found on port 5173:

- command: `npm run dev --host 127.0.0.1`
- cwd: `/home/wali/Desktop/AI BOT REBUILD/v2/frontend`

No duplicate Vite dev server was identified for port 5173.

## Service Worker

The frontend dev build unregisters service workers in `registerServiceWorker()` when `import.meta.env.DEV` is true. Chromium smoke confirmed service-worker registration count `0`.

## Operator Note

If a browser still shows an old shell, hard refresh with `Ctrl+Shift+R`, unregister any old service worker for `localhost:5173`, clear site data, then open `http://localhost:5173/`.
