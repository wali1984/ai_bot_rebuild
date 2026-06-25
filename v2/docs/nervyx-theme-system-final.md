# NERVYX Shared Theme System Evidence

- Generated at: `2026-06-23T19:42:56Z`
- Status: IN PROGRESS. Shared source/generator/drift evidence, public theme persistence, legacy storage migration, and public Ops Terminal escalation rejection are proven on Linux. Full route visual validation, native iOS/watchOS UI validation, Dynamic Type, VoiceOver, simulator accessibility, and TestFlight validation remain pending or blocked.

## Source And Outputs

| Item | Path | Status |
|---|---|---|
| Authoritative token source | `/home/wali/Desktop/AI BOT REBUILD/rebranding/nervyx-one-brand-tokens.json` | READ-ONLY SOURCE, checksum `36bf9013c0a13604cadc6ffa3429a875249359f36755bb1b9bf13f6baf49f2d7` |
| Token generator | `scripts/generate-nervyx-brand-tokens.mjs` | Generates web CSS/TS/manifest and Swift token/manifest outputs from the same source checksum |
| Drift checker | `scripts/check-nervyx-brand-token-drift.mjs` | Passed, proving source checksum, theme values, semantic colors, module text, CSS selectors, and Swift access maps match |
| Web CSS tokens | `frontend/src/brand/generated/nervyx-tokens.css` | Generated output present |
| Web TS tokens | `frontend/src/brand/generated/nervyx-tokens.ts` | Generated output refreshed; execute module description is `Execution order lifecycle` |
| Web theme manifest | `frontend/src/brand/generated/nervyx-theme-manifest.json` | Generated output refreshed; source checksum matches `/rebranding` |
| Swift tokens | `mobile/Sources/AIBotV2/Brand/Generated/NervyxTokens.swift` | Generated output present; source checksum matches `/rebranding` |
| Swift theme manifest | `mobile/Sources/AIBotV2/Brand/Generated/NervyxThemeManifest.swift` | Generated output refreshed with theme/module/access maps |

## Theme Access

| Theme | Intended use | Evidence | Status |
|---|---|---|---|
| Midnight Neural | Default public/trader dark theme | CSS selector `:root, [data-nervyx-theme="midnight-neural"]`; manifest `defaultFor: ["public", "trader"]`; Playwright confirms web toggle returns to dark mode | PROVEN IN SOURCE AND FOCUSED WEB TEST |
| Polar Signal | Selectable public/trader light theme | CSS selector `[data-nervyx-theme="polar-signal"]`; manifest `selectableFor: ["public", "trader"]`; Playwright confirms `data-theme="light"` and reload persistence through `nervyx_theme=polar-signal` | PROVEN IN SOURCE AND FOCUSED WEB TEST |
| Ops Terminal | Admin/superadmin operations theme only | CSS selector `[data-nervyx-theme="ops-terminal"]`; manifest `restrictedTo: ["admin", "superadmin"]`; `AdminShell` sets `data-nervyx-theme="ops-terminal"` only after authenticated admin session; public `ThemeToggle` exposes only Midnight/Polar; Playwright verifies a public `nervyx_theme=ops-terminal` localStorage attempt is sanitized back to Midnight; Swift manager rejects Ops Terminal without `backendConfirmedAdmin` | SOURCE AND FOCUSED WEB/SWIFT GUARDS PASSED; FULL AUTHENTICATED ROLE AUDIT STILL PENDING |

## Validation Run

| Command | Result |
|---|---|
| `npm run brand:tokens` | Passed; regenerated deterministic NERVYX token outputs from checksum `36bf9013c0a13604cadc6ffa3429a875249359f36755bb1b9bf13f6baf49f2d7` |
| `npm run brand:tokens:check` | Passed; source checksum, generated web tokens, generated Swift tokens, theme access maps, module text, CSS selectors, and Swift access maps match |
| `npm run --prefix frontend test:e2e -- nervyx_theme_token_drift.spec.ts --project=chromium --reporter=line` | Passed: 1 Chromium test |
| `npm run --prefix frontend test:e2e -- nervyx_branding.spec.ts --project=chromium --reporter=line` | Initial run failed because the test reseeded localStorage on every reload; after fixing the one-time seed guard, passed: 4 Chromium tests |
| `npm run --prefix frontend typecheck` | Passed |
| `swift test` from `mobile/` | Passed: 18 XCTest tests |

## Remaining Theme-Gate Gaps

- Charts under every theme: not fully route-rendered across all chart pages yet.
- Tables under every theme: not fully route-rendered across all table pages yet.
- Positive/negative/warning states: semantic tokens exist and are covered by source/drift checks, but full rendered visual coverage is pending.
- Contrast/focus/increased contrast/Reduce Motion: source CSS selectors and focus tokens exist, but complete automated accessibility proof is pending.
- Theme persistence: focused Playwright coverage verifies Polar Signal reload persistence, migration/removal of legacy keys, and invalid public Ops Terminal storage sanitization. Route-wide persistence across every canonical and legacy route remains part of the broader role-route audit.
- Dynamic Type and VoiceOver: blocked on native macOS/iOS simulator validation.
- Role escalation through theme selection: web Ops Terminal is not exposed in `ThemeToggle`; Swift rejects Ops Terminal without backend-confirmed admin. Full authenticated role-route audit remains pending.
