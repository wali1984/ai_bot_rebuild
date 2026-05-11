# TRADINGVIEW_REPLACEMENT_REPORT.md

## Claim

TradingView remains the primary chart in V2's Mission Control. The Claude Design package's SVG fallback chart was not lifted.

## Evidence

### Design package

`mission-control.jsx` in the design ships an inline SVG fallback chart driven by `useTicker` (animated synthetic candles). The README explicitly says:

> Chart: prototype uses an SVG fallback. Per the prompt, the real implementation must use TradingView / lightweight-charts as primary and only keep the SVG as a clearly-labeled fallback.

### V2 today

V2 has TradingView already wired:

- Component: `v2/frontend/src/components/charts/TradingViewWidget.tsx` — loads the official TradingView advanced-chart embed script (`https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js`), with a 7-second timeout falling back to a clear "TradingView did not load" message.
- Embed config: `theme: 'dark'`, `timezone: 'Etc/UTC'`, default interval `'15'`, and a symbol prop.
- Consumer: `cockpitComponents.tsx` `ChartPanel` — used by `mission-control/index.tsx`.

The Mission Control page does **not** render any SVG candle fallback. If TradingView fails to load, the user sees a labelled error block, not synthetic candles. That preserves the contract that V2 never presents fabricated price action as a primary surface.

### What did not change

No edits to `TradingViewWidget.tsx`. No edits to `cockpitComponents.tsx`. No edits to `mission-control/index.tsx`. The SVG path from `mission-control.jsx` in the design package was not ported.

### Verification

```bash
cd v2/frontend
grep -n "tradingview\.com/external-embedding" src/components/charts/TradingViewWidget.tsx     # expect 1 hit
grep -rn "useTicker\|synth.*candle\|<path.*spark" src/                                         # expect 0 hits
```

Result: TradingView is the only primary chart path; no synthetic / SVG primary chart was introduced.
