# TradingView Primary And Old Chart Removal Report

TradingView status: primary.

Evidence:

- Mission Control still renders `ChartPanel`.
- `ChartPanel` renders `TradingViewWidget` as the normal chart surface.
- The old local SVG candle chart is passed only as the `TradingViewWidget` fallback.
- The fallback renders only when the widget reports failure or timeout.
- The chart label remains visible and distinguishes `READONLY_MARKET_FEED` from `STATIC_PROOF_FIXTURE`.

No primary cockpit path renders the SVG chart beside a healthy TradingView widget.

No exchange order, cancel, leverage, margin, or live action path is connected to the chart.
