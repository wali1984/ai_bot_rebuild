# Design Vs Current UI Gap Report

Before this pass, the design handoff had been ingested mostly as additive CSS tokens and banner styling. Mission Control still used the old component composition, and several secondary admin pages still used either the older `enterprise-cockpit-hero` pattern or the generic `PageShell` placeholder.

Implemented gaps:

- Mission Control now uses the Claude Design visual hierarchy: command hero, hatch/bracket treatment, subsystem strip, risk-boundary flow, dense panels, and source/safety ribbons.
- Shared panels now render through the bracketed `panel` structure instead of plain card sections.
- Monitor Center, Trainer Prediction Monitor, Signal Explainability, Risk Control, Config Admin, Build Validation Status, Claude Admin AI, and Mobile/iPhone Readiness now use a shared design shell.
- Risk Control, Build Validation Status, Claude Admin AI, and Mobile/iPhone Readiness no longer render as generic placeholder-only `PageShell` pages.

Unsafe/mock-only design elements not copied:

- `data.jsx` mock telemetry.
- `window.AIBOT` prototype globals.
- prototype-only subsystem counts and fake policy revision strings.
- design SVG chart as a primary chart.
- `module-placeholder.jsx` placeholder behavior as product content.
- `tweaks-panel.jsx` user style mutation panel.

Payloads preserved:

- `useCockpitPayload()` remains the Mission Control data source.
- `TradingViewWidget` remains the primary chart surface.
- existing proof/runtime payloads remain source of truth.
- explicit evidence gaps remain visible when runtime data is absent.
- live-block and readiness banners remain visible.

Remaining visual gaps:

- Some non-requested admin pages still use older route shells and should be migrated in later polish passes.
- Several pages still depend on proof artifacts rather than live runtime payloads; this is represented as evidence-gap status, not fabricated data.
