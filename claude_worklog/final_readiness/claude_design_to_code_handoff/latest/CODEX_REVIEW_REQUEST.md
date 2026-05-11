# CODEX_REVIEW_REQUEST.md

**Target:** INGEST_CLAUDE_DESIGN_HANDOFF_AND_UPDATE_V2_WEBSITE_READY
**Branch:** master
**Pre-Codex commit hashes:** see `git log --oneline 737b6f4..HEAD` in `CLAUDE_DESIGN_TO_CODE_HANDOFF_REPORT.md` appendix
**Changed files (V2 src):** `v2/frontend/src/styles.css` (additive), `v2/frontend/src/components/banners/LiveBlockBanner.tsx` (one-line modifier).
**Worklog files produced:** see `CLAUDE_DESIGN_TO_CODE_HANDOFF_REPORT.md` "Reports" section.

## What to challenge (adversarial)

Codex must adversarially review whether:

1. **Mock leak:** Any string, number, or import from the Claude Design `data.jsx` or `app.jsx` `BlockedStrip` mock strings is presented in V2 as live data.
2. **Chart regression:** Any SVG candle / synthetic-tick chart from the design package is rendered as a primary chart anywhere in V2 (Mission Control, Operator Proof Dashboard, or elsewhere). TradingView must remain primary.
3. **Signal Explainability guessing:** Any panel under `/admin/signal-explainability` shows a fabricated or interpolated feature contribution where the real artifact lacks a value. The contract is: missing feature → `cockpit-evidence-gap`, never invented filler.
4. **Monitor Center field coverage:** Whether `/admin/monitor-center` design intent is correctly translated. The route must surface (or evidence-gap) the required script registry, monitor owner, last-run, last-success, last-failure, metrics emitted, Redis keys watched, processes watched, alerts generated, plus the runtime overlays (trainer prediction stream, price prediction accuracy, signal causality, feature freshness, model health, risk gate status, execution latency, Claude supervision health, Ollama summarization health, Codex review status).
5. **Config Admin dangerous-setting approval classification:** Whether the dangerous-setting list documented in CLAUDE.md and `dangerousControls.ts` is correctly gated, including: enable live trading, add/activate live API keys, increase leverage, enable CROSS margin, increase max position size, increase daily loss limit, disable kill switch, disable mandatory stop, enable hedge/DCA, enable ADJUST_LEVERAGE, paper→live switch.
6. **Placeholder-only ships:** Whether any V2 route renders a bare placeholder without a labelled `cockpit-evidence-gap` block and without a `DangerousControlPanel` wired.
7. **Safety violation:** Whether any code, payload, or doc change in this pass enables (a) writing to legacy Redis keys, (b) creating the Redis trim approval file, (c) placing/cancelling exchange orders, (d) changing leverage / margin / position mode, (e) activating live API keys, or (f) enabling live trading.
8. **Mobile / iPhone future path:** Whether the existing PWA manifest, service worker, mobile bridge, or responsive breakpoints regressed in any way. The `MOBILE_IPHONE_READINESS_NOTES.md` rationale must hold.

## What to confirm

- The 28 required admin pages plus the V2-specific `operator-proof-dashboard`, `exchange-manager`, and `external-manual-position-quarantine` are routed.
- Build (`npm run build`) is clean.
- Typecheck (`npm run typecheck`) is clean.
- Playwright `live_block_banner.spec.ts` + `nav_smoke.spec.ts` both pass (64/64 reported by Claude Code).
- Live-blocked banner is sticky and undismissable on every admin route.
- The hatched amber modifier is applied only when banner state is `blocked`; solid amber/green for `pending`/`active`.
- `data.jsx`, `TweaksPanel`, and the design's mock-marquee strings are absent from `v2/frontend/src/`.

## Where to write the verdict

- `claude_worklog/final_readiness/claude_design_to_code_handoff/latest/CODEX_DESIGN_HANDOFF_REVIEW.md` — full review writeup.
- `claude_worklog/final_readiness/claude_design_to_code_handoff/latest/CODEX_GO_NO_GO.md` — exactly one line:
  - `CLAUDE_DESIGN_TO_CODE_HANDOFF_CODEX_PASS`
  - or `CLAUDE_DESIGN_TO_CODE_HANDOFF_CODEX_FAIL`
