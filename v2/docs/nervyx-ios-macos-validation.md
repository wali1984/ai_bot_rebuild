# NERVYX iOS macOS Validation

- Generated at: `2026-06-22T22:07:36.943474+00:00`
- Updated at: `2026-06-23T19:25:17Z`
- Status: BLOCKED - MACOS/XCODE REQUIRED. macOS validation lane is prepared but not executed on this Linux host.
- Linux Swift Package build/test is not native iOS/watchOS validation.
- Do not alter signing, Apple accounts, or entitlements to force validation.
- Host check: `xcodebuild -version` failed with `/bin/bash: line 1: xcodebuild: command not found`.
- Host Swift toolchain: `Swift version 6.1.2 (swift-6.1.2-RELEASE), Target: x86_64-unknown-linux-gnu`.
- Prepared runnable GitHub Actions workflow: repository-root `.github/workflows/nervyx-ios-macos-validation.yml`.
- Prepared local/source workflow copy for v2 validation tests: `v2/.github/workflows/nervyx-ios-macos-validation.yml`.
- Prepared lane behavior: macOS runner, Xcode toolchain evidence, XcodeGen install, build-number guard, Swift build/test, XcodeGen project generation, iPhone simulator-class builds with `CODE_SIGNING_ALLOWED=NO`, SwiftPM iOS app product build, SwiftPM watchOS product build, XcodeGen watchOS app target build with `CODE_SIGNING_ALLOWED=NO`, blocked-gate status artifact, and artifact upload.
- No signing, Apple account, entitlement, archive upload, or App Store Connect mutation is performed by the prepared workflow.
- Linux validation performed before this refresh: workflow parsed with PyYAML, static workflow/project-structure checks passed, `npm run ios:app-store-build:check` passed (`current=6 previous=4`), and `swift test` passed 12 XCTest.
- Additional source evidence added in this refresh: the repository-root workflow exists and the Swift static guard now verifies both the root workflow and the v2 workflow copy for watchOS target build evidence, `CODE_SIGNING_ALLOWED=NO`, and absence of `DEVELOPMENT_TEAM`, `fastlane pilot`, `altool`, and `notarytool`.

Required native checks remain pending until the workflow runs on macOS/Xcode or an equivalent Mac host: app launch, branding, AppIcon, launch screen, themes, login/logout, Keychain, streams, role gating, reconnect/offline/stale, Dynamic Type, VoiceOver labels, clipping, crash checks, secret logging checks, and simulator screenshots.

Prepared watch target: `mobile/project.yml` declares `AIBotV2Watch` as a watchOS application target with bundle identifier `com.wali1984.aibot-v2.watch`, generated Info.plist, display name `NERVYX ONE`, and `WKWatchOnly`. The prepared workflows build both the SwiftPM `AIBotV2WatchApp` product and the XcodeGen `AIBotV2Watch` target for a watchOS simulator. Install, launch, UI, accessibility, pairing, and screenshot validation remain unproven until macOS/Xcode executes the lane.
