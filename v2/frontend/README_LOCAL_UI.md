# AI BOT V2 Local UI

Run the React/Vite frontend from this directory:

```bash
cd v2/frontend
npm install
npm run dev
```

Vite is configured for port `5173`, so the local URL is:

```text
http://localhost:5173/
```

Routes to check:

- `/` shows the modern Mission Control cockpit and the marker `AI BOT V2 Modern Dashboard Loaded`.
- `/admin/mission-control?role=admin` shows the same cockpit inside the admin shell.
- `/admin` redirects to `/admin/mission-control`.

If the browser still shows an older UI:

1. Hard refresh with `Ctrl+Shift+R`.
2. In DevTools, unregister the old service worker for `localhost:5173`.
3. Clear site data for `localhost:5173`.
4. Remove stale build output if you are serving production files:

```bash
rm -rf dist
npm run build
```

The dev build unregisters local service workers automatically so cached `/` or
`/index.html` shells do not hide new React source changes.
