# IMPLEMENTATION_MAP.md

Targeted, additive file-by-file change summary.

## v2/frontend/src/styles.css

**Top of file (line 1):** added `@import` for Google Fonts IBM Plex Sans (300-700), IBM Plex Mono (300-600), IBM Plex Sans Condensed (500-600). The `@import` precedes any CSS rule per the CSS spec — failing this ordering produces a Vite warning and a missing-font fallback.

**Bottom of file (appended after the existing `@media (max-width: 760px)` block):** a single guarded "Claude Design handoff 2026-05-11" section. All rules below are net new and additive — every existing rule retains precedence, including all `.live-block-banner--{red,amber,green}` rules and all `.cockpit-evidence-gap` rules.

Added blocks:

- Theme-token blocks:
  - `:root, [data-theme="dark"]` — adds `--surface`, `--panel`, `--panel-2`, `--border-strong`, `--text-mid`, `--text-dim`, `--text-faint`, `--accent`, `--accent-2`, `--ok`, `--block`, `--warn`, `--paper`, `--grid-line`, `--hatch`, `--hatch-strong`. Does **not** override `--color-bg`, `--color-fg`, `--color-muted`, `--color-red`, `--color-amber`, `--color-green`, `--color-border` declared at the top of the file.
  - `[data-theme="light"]` — same set in warm-paper palette.
  - `[data-theme="terminal"]` — same set in phosphor-amber palette.
  - No runtime `data-theme` switcher is shipped; these are inert until a controlled switcher is added in a future change.

- Typography utility classes: `.mono`, `.num`, `.cond`, `.eyebrow`, `.label-mono`.

- Surface utilities: `.hatch`, `.hatch-strong` (repeating 135° amber stripes); `.grid-bg` (32px × 32px faint grid).

- Panel primitives: `.panel`, `.panel-head`, `.panel-title`, `.panel-body`. These can be opted into by any page that wants the design's panel aesthetic; existing pages are unaffected.

- Corner-bracket modifier: `.bracketed` + `.br-bl` / `.br-br` (uses `::before`, `::after`, and the two child spans to draw amber corner brackets on cockpit-critical panels).

- Status dots: `.dot`, `.dot.ok`, `.dot.warn`, `.dot.block`, `.dot.paper`, `.pulse` (the `pulse` keyframes name is namespaced as `design-pulse` to avoid colliding with any existing animation).

- Tick-flash animation: `.tick-flash` (0.5s amber fade for updated numbers; existing `keyframes tick-flash` is namespaced inside the appended block).

- Chip primitives: `.chip` + `.chip.solid-block`, `.chip.solid-warn`, `.chip.solid-ok`, `.chip.solid-paper`.

- Live-blocked banner modifier: `.live-block-banner--hatched` — adds repeating 135° amber stripes over the red banner. Used only when banner state is `blocked` (see `LiveBlockBanner.tsx`).

## v2/frontend/src/components/banners/LiveBlockBanner.tsx

One-line change inside the `TONES` map:
- `blocked: 'live-block-banner--red'` → `blocked: 'live-block-banner--red live-block-banner--hatched'`.

Banner behavior:
- Still sticky, undismissable, role=`status`, `aria-live="polite"`.
- Still derives state from `GET /api/v1/risk/live-readiness`; on fetch failure or unexpected state it falls back to `DEFAULT_LIVE_READINESS` (blocked).
- States: `blocked` → red + hatched amber surface, `pending` → solid amber, `active` → solid green (unchanged).

## No other source file modified

The 28 admin page components, the routing layer, the dangerous-control gating, the TradingView chart layer, the PWA scaffolding, the proof artifacts under `public/`, the `cockpitComponents.tsx` primitives, the `FreshnessBadge`, and every backend payload remain bit-for-bit unchanged.

## Build output diff

Before: `dist/assets/index-*.css` 19.47 kB / 4.29 kB gzip.
After:  `dist/assets/index-*.css` 19.66 kB / 4.38 kB gzip.

JS bundle size unchanged: `dist/assets/index-*.js` 290.57 kB / 86.65 kB gzip.

CSS bundle grew by ~190 bytes — the Google Fonts `@import` adds a directive but the actual fonts are loaded over the network at runtime, not embedded.
