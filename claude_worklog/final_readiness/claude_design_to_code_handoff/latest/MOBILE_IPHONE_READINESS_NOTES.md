# MOBILE_IPHONE_READINESS_NOTES.md

## Claim

The future iPhone / PWA / mobile path is preserved across this handoff.

## What exists today (unchanged)

- **PWA manifest** — `v2/frontend/public/manifest.webmanifest`. `display: standalone`, `scope: /`, dark theme `#0f172a`, icons 192×192 + 512×512 with `purpose: "any maskable"`.
- **Service worker** — `v2/frontend/public/service-worker.js`, registered via `v2/frontend/src/pwa/registerServiceWorker.ts`.
- **Mobile bridge** — `v2/frontend/src/mobile/bridge.ts`, the surface a future native shell would call into.
- **Responsive layout** — `styles.css` `@media (max-width: 760px)` block already collapses `admin-shell__body`, `operator-proof-hero`, `operator-cockpit-layout`, `enterprise-cockpit-hero`, `enterprise-cockpit-grid`, and `cockpit-decision-drawer` to single-column.
- **Admin route** — `/admin/mobile-iphone-readiness` is registered and routed.

## What this handoff added

The design tokens (`@import` IBM Plex, `--accent`, `--hatch`, etc.) are device-agnostic CSS variables; they degrade cleanly on small screens. The hatched live-blocked banner reflows correctly under the existing `@media` rule.

The IBM Plex `@import` is a network request from Google Fonts; the existing service worker caches static assets but does not currently pre-cache the font CDN. On a first mobile visit the user-agent will see a brief font-swap to the system stack (`-apple-system, ui-sans-serif, ...`) before IBM Plex paints. This is acceptable and matches the design package's own load path.

## What is not yet built

The `/admin/mobile-iphone-readiness` page currently renders `PageShell`'s evidence-gap block — the mobile readiness checklist artifact is not yet provisioned. `NEW_PAYLOAD_REQUIREMENTS.md` Section 9 specifies the expected fields (`pwa_manifest_present`, `service_worker_registered`, `responsive_breakpoints`, `mobile_safe_auth`, `mobile_safe_approvals`, `push_notifications_planned`, `future_native_app_track`).

## Future native iPhone app

The plan stays:
- Phase 1 (now): Responsive web + PWA. Status: ✓ shipped.
- Phase 2: Mobile-safe auth and approval surfaces on the existing routes (`/admin/risk-control`, `/admin/config-admin` dangerous controls). Status: gated behind the existing `DangerousControlPanel`.
- Phase 3: React Native / Expo or SwiftUI native shell calling the same V2 API. Status: not started; `mobile/bridge.ts` is the seam.

Nothing in this handoff blocks any phase.

## Verification

```bash
cd v2/frontend
test -f public/manifest.webmanifest && echo manifest:ok
test -f public/service-worker.js && echo sw:ok
test -f src/pwa/registerServiceWorker.ts && echo register:ok
test -f src/mobile/bridge.ts && echo bridge:ok
grep -n "max-width: 760px" src/styles.css | head -1
```

All four files exist; the responsive breakpoint is unchanged.
