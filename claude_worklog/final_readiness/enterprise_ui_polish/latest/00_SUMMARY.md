# Enterprise UI Polish — Remove Legacy Chart Duplicate

Date: 2026-05-11
Branch: master
Scope: non-live frontend polish only. No Redis, no exchange, no live mutation.

## Goal

The Mission Control cockpit page rendered two charts in the
`charting-market-data` panel: the TradingView Advanced Chart embed AND a
static SVG proof chart. The static chart was originally a fallback for
environments where the TradingView script could not load. With the
TradingView embed in place by default, showing both surfaces side by side
duplicated the visible chart, cluttered the cockpit, and confused operators
about which surface was authoritative.

This change makes the legacy/static SVG chart fallback-only: it only renders
when the TradingView widget reports a load failure or times out. On a healthy
widget load the legacy SVG is not mounted at all, so there is no duplicate
chart. The `READONLY_MARKET_FEED` / `STATIC_PROOF_FIXTURE` evidence label is
still rendered below the chart in both states so operators can always confirm
which data source is driving the displayed candles.

## Implementation shape

1. `v2/frontend/src/components/charts/TradingViewWidget.tsx`
   - Added optional `fallback?: ReactNode` prop.
   - When `failed === true` and a custom `fallback` is passed, that node is
     rendered in place of the default text-only "Chart unavailable" notice.
   - Default text-only fallback retained for callers that do not pass one.
   - Added `data-failed` data attribute and `aria-hidden` on the empty
     container while failed, for clarity in tests and screen readers.
2. `v2/frontend/src/pages/cockpitComponents.tsx`
   - `ChartPanel` now builds a fallback element that wraps the existing SVG
     proof candles (and decision/risk markers) plus a short status message.
   - That fallback is passed into `<TradingViewWidget fallback={...} />`.
   - The SVG is no longer rendered alongside the widget in the success path.
   - The evidence note paragraph (`READONLY_MARKET_FEED` /
     `STATIC_PROOF_FIXTURE`) remains a sibling of the widget and is always
     visible.
3. `v2/frontend/src/styles.css`
   - Added `.tradingview-widget-fallback--chart` modifier (flex column,
     stretch, left-aligned, scrollable) so the chart fallback fills the
     420px widget shell without inheriting the centred single-line layout
     of the default text fallback.
   - Default `.tradingview-widget-fallback` rule untouched, so any caller
     that uses the original text-only fallback still gets centred text.
4. `v2/frontend/README_LOCAL_UI.md`
   - New "Chart panel behaviour" section documents:
     - widget is read-only,
     - fallback identifier (`data-testid="tradingview-chart-fallback"`),
     - that the evidence label stays visible in both states.
   - No route changes, no run-command changes.

## Preserved

- Safety / admin scaffold (`enterprise-cockpit-hero`, `SafetyTopBar`,
  `cockpit-live-block` with `LIVE TRADING: ${live_gate_status}`).
- RBAC and live-block status surfaces unchanged.
- Route map: `/`, `/admin`, `/admin/mission-control` continue to render the
  same Mission Control cockpit component.
- The visible "AI BOT V2 Modern Dashboard Loaded" loaded marker remains in
  the footer until the operator confirms removal.
- Service-worker stale-cache mitigation in dev (unchanged).
- TradingView widget testid (`tradingview-widget`), `data-symbol`, and
  `data-failed` attributes available for tests.
- Evidence / source labels (`READONLY_MARKET_FEED` /
  `STATIC_PROOF_FIXTURE`) remain visible in the panel.

## Safety scan

- No Redis writes added; no Redis client imported.
- No exchange order placement / cancellation paths added.
- No leverage / margin / position mode changes.
- No live key activation, no live trading gate flips.
- No changes outside `v2/frontend/**` (source/docs) and
  `claude_worklog/final_readiness/enterprise_ui_polish/latest/**`
  (this report).
- No edits to `/home/wali/Desktop/AI BOT` legacy bot.

## Gate

`ENTERPRISE_UI_POLISH_REMOVE_LEGACY_CHART_READY`
