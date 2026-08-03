# NERVYX ONE Local UI

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

- `/` opens the NERVYX ONE public landing route.
- `/dashboard?role=admin` opens the NERVYX EXECUTE paper/read-only trader dashboard.
- `/admin/monitor-center?role=admin` opens the NERVYX OBSERVE admin shell.
- `/landing` keeps the public shell route available for compatibility.

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
`/index.html` shells do not hide new React source changes. If the browser still
lands on an old shell, clear the service worker and site data, then open
`http://localhost:5173/` again.

## Chart panel behaviour

The NERVYX EXECUTE chart panel (`cockpit-charting-market-data`) embeds the
external TradingView Advanced Chart widget for `BINANCE:BTCUSDT` by default.
The widget is read-only: it never places, cancels, or modifies orders.

If the TradingView script fails to load or does not finish loading within
the timeout, the panel renders a local read-only proof candle SVG as a
fallback. The fallback is identified by `data-testid="tradingview-chart-fallback"`
and is only visible when the embed has failed; on a healthy widget load the
legacy SVG chart is hidden entirely so it does not duplicate the live widget.

The `READONLY_MARKET_FEED` / `STATIC_PROOF_FIXTURE` evidence label is always
visible below the chart regardless of which surface is rendered, so operators
can confirm which data source drove the displayed candles.
