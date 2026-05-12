# TradingView Production Repair Report

Generated at: 2026-05-12T03:04:31.442Z

- Mission Control uses TradingViewWidget as the primary chart component.
- The chart container has data-testid="tradingview-widget".
- If the external widget fails, the fallback is explicitly labeled FALLBACK_STATIC_CHART.
- The old SVG/static chart appears only inside that fallback state.
- Source/freshness text remains visible below the chart.
