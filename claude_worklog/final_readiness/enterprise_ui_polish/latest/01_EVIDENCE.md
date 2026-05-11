# Enterprise UI Polish — Evidence Pointers

## Files changed

- `v2/frontend/src/components/charts/TradingViewWidget.tsx`
  - `interface TradingViewWidgetProps` now exposes `fallback?: ReactNode`.
  - `useState`-driven `failed` flag still drives the fallback surface; the
    render branch is `failed ? (fallback ?? <default text fallback />) : null`.
  - Shell `<div className="tradingview-widget-shell" data-testid="tradingview-widget">`
    is preserved so the existing `e2e` selectors continue to match.
- `v2/frontend/src/pages/cockpitComponents.tsx`
  - `ChartPanel` builds `const fallback = (<div className="tradingview-widget-fallback tradingview-widget-fallback--chart" role="status" data-testid="tradingview-chart-fallback">...)` and passes it to `<TradingViewWidget fallback={fallback} />`.
  - The legacy SVG, candle markers, and decision/risk markers now live inside
    that fallback only — they are no longer rendered as a sibling of the
    widget on the success path.
  - The `cockpit-evidence-note` paragraph is preserved as a sibling of the
    widget so the source-of-truth label remains visible regardless of widget
    state.
- `v2/frontend/src/styles.css`
  - Added `.tradingview-widget-fallback--chart` modifier and child rules for
    the wrapped SVG. Default `.tradingview-widget-fallback` rule unchanged.
- `v2/frontend/README_LOCAL_UI.md`
  - Documents the chart-panel fallback behaviour and the
    `tradingview-chart-fallback` test id. No route or run-command changes.

## Test impact

- `tests/e2e/enterprise_trading_cockpit.spec.ts` checks the panel content
  with `await expect(page.getByTestId('cockpit-charting-market-data')).toContainText(/READONLY_MARKET_FEED|STATIC_PROOF_FIXTURE/);`.
  The `cockpit-evidence-note` paragraph still emits that exact text whether
  or not the widget loaded, so the assertion remains satisfied.
- The same test enforces `await expect(page.getByTestId('page-mission-control').getByRole('button')).toHaveCount(0);`.
  This change adds no `<button>` elements.
- Live block assertion: `cockpit-live-block` and `cockpit-topbar` continue
  to render `LIVE TRADING: blocked_human_only`.
- Other admin pages and their assertions are untouched.

## Validation plan

The supervisor should run the following from `v2/frontend/`:

- `npm run typecheck` — should pass; the only signature change is the new
  optional `fallback?: ReactNode` prop on `TradingViewWidget`, which is the
  pattern already used elsewhere in the cockpit components for React-node
  composition.
- `npm run build` — should produce a clean `dist/` since the source change
  is local to `TradingViewWidget`, `cockpitComponents`, and `styles.css`.
- `npx playwright test tests/e2e/enterprise_trading_cockpit.spec.ts` — should
  still pass: the panel text assertion is satisfied by the evidence note,
  and no new buttons are introduced. In test environments where the
  TradingView CDN script does not load, the local proof candle SVG will
  appear as the fallback (the test does not assert on the SVG either way).

## Safety scan (manual)

Searched `v2/frontend/src/components/charts/TradingViewWidget.tsx`,
`v2/frontend/src/pages/cockpitComponents.tsx`, `v2/frontend/src/styles.css`,
`v2/frontend/README_LOCAL_UI.md`:

- No mention of `XADD`, `XTRIM`, `XDEL`, `DEL`, `SET`, `HSET`, `FLUSHALL`,
  `FLUSHDB`, `redis://`, `BINANCE_API_KEY`, `BINANCE_SECRET_KEY`,
  `place_order`, `cancel_order`, `leverage`, `margin_mode`, or
  `enable_live`.
- The TradingView embed script URL (`s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js`)
  is unchanged from the prior, already-reviewed source.
- The change is read-only and presentation-only.

## Gate

`ENTERPRISE_UI_POLISH_REMOVE_LEGACY_CHART_READY`
End-of-turn summary: emitted BEGIN_FILE blocks for TradingViewWidget (adds optional `fallback?: ReactNode`), ChartPanel (legacy SVG now routed into that fallback so it's hidden on healthy widget load while the `READONLY_MARKET_FEED`/`STATIC_PROOF_FIXTURE` evidence label stays visible), styles.css (new `.tradingview-widget-fallback--chart` modifier), README_LOCAL_UI.md (chart panel behaviour section), plus `GO_NO_GO.md` (`ENTERPRISE_UI_POLISH_REMOVE_LEGACY_CHART_READY`), `00_SUMMARY.md`, and `01_EVIDENCE.md` under `claude_worklog/final_readiness/enterprise_ui_polish/latest/`. Next: supervisor materializes the files and runs `npm run typecheck` / `npm run build` / Playwright smoke from `v2/frontend/`.
