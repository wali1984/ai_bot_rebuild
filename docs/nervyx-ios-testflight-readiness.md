# NERVYX iOS TestFlight Readiness

Status: BLOCKED for upload in this Linux workspace.

Completed in this lane:
- Visible native identity updated to NERVYX ONE.
- Approved app icon and logo assets are present in the asset catalog.
- Bundle identifier, signing, provisioning, App Groups, Keychain groups, capabilities, and associated domains were not changed.
- Mobile safety copy continues to state paper/read-only and live trading blocked.

Required external workflow before upload:
1. Open the existing package/project in Xcode on macOS.
2. Use the existing signing team and provisioning configuration.
3. Run `npm run ios:app-store-build:check` from `v2/` before archive/upload.
4. Run simulator build, unit tests, and UI tests.
5. Validate archive.
6. Upload through the existing App Store Connect workflow.

Latest known upload result:
- 2026-06-21 App Store Connect rejected build `4` for `com.wali1984.aibot-v2` because build `4` had already been uploaded.
- `v2/mobile/project.yml` now uses `CURRENT_PROJECT_VERSION: "5"`.
- `v2/mobile/app-store-build-guard.json` records the known previous uploaded build. CI should set `ASC_PREVIOUS_BUILD_NUMBER`, `APP_STORE_CONNECT_PREVIOUS_BUILD_NUMBER`, `IOS_PREVIOUS_UPLOADED_BUILD`, or `LATEST_TESTFLIGHT_BUILD_NUMBER` from App Store Connect before upload so the guard checks against the live latest value.

Upload remains BLOCKED in this Linux workspace until App Store Connect credentials and signing environment are available.
