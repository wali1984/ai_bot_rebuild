# Final visual evidence index

The registry-driven evidence is stored in `../../v2/artifacts/final-product-regression/`.

- 71 concrete route cases × 4 required viewports = 284 expected captures.
- 280 captures recorded.
- 4 signal-explainability captures are explicitly marked blocked by the renderer-heavy proof payload.
- Public clean slice: 16/16 captures, zero console errors, zero failed requests, zero overflow routes.
- Full artifact: `../../v2/artifacts/final-product-regression/final-product-regression-all.json`.

Authenticated family reruns (fresh token, single process) are clean:

- markets/charts: 32/32
- ingestors/providers: 56/56
- trading/portfolio/risk: 56/56
- admin/system: 100/100
- trainer/AI: 20/24; the four omitted captures are the explicitly blocked signal-explainability renderer case.
