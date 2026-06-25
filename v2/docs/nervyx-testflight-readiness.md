# NERVYX TestFlight Readiness

- Generated at: `2026-06-22T22:07:36.943474+00:00`
- Updated at: `2026-06-23T19:25:17Z`
- Status: BLOCKED.
- App Store Connect upload/processing was not attempted and must not be claimed.
- Host check: `xcodebuild -version` failed with `/bin/bash: line 1: xcodebuild: command not found`.
- No signing, Apple account, entitlement, archive, upload, or App Store Connect processing action was attempted.
- Current `mobile/project.yml` declares `PRODUCT_BUNDLE_IDENTIFIER: com.wali1984.aibot-v2`, `MARKETING_VERSION: 1.0.0`, and `CURRENT_PROJECT_VERSION: 6`; macOS/Xcode must verify these against the existing approved App Store Connect app before any upload.
- Static guard passed on Linux: `python3 scripts/check_ios_app_store_build_number.py` reported `iOS App Store build number preflight passed: current=6 previous=4`.
- Prepared runnable workflow `.github/workflows/nervyx-ios-macos-validation.yml` and v2 source copy `v2/.github/workflows/nervyx-ios-macos-validation.yml` do not upload to App Store Connect and do not change signing. They build iOS simulator targets, the SwiftPM watchOS product, and the XcodeGen watchOS app target with signing disabled, then upload validation logs.
- Current iOS app source default uses HTTPS via `AppConfiguration.baseURL = https://dashboard.wajidali.us`; the cross-platform CLI/core fallback still contains a localhost development default and is not TestFlight proof until native archive/release configuration is validated on macOS/Xcode.

Pending checks: bundle identifier against App Store Connect, signing team unchanged, entitlements unchanged, version/build convention under Xcode archive, AppIcon validation, archive validation, privacy strings, HTTPS-only release API, no localhost in release, beta description, What to Test, release notes, crash diagnostics, TestFlight upload, and App Store Connect processed-build confirmation.
