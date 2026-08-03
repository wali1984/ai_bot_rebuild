# NERVYX iOS Upload Guard

## Issue Prevented

The 2026-06-21 App Store Connect upload failed because `CFBundleVersion` was `4`, and build `4` had already been uploaded for `com.wali1984.aibot-v2`.

## Current Fix

- `v2/mobile/project.yml` now sets `CURRENT_PROJECT_VERSION: "5"`.
- `v2/mobile/app-store-build-guard.json` records the latest known uploaded build floor from the rejection: `previous_uploaded_build_number: 4`.
- `v2/scripts/check_ios_app_store_build_number.py` fails before upload if the configured build number is not greater than the previous uploaded build.
- `v2/package.json` exposes the guard as `npm run ios:app-store-build:check`.

## CI Requirement

Before publishing to App Store Connect, run:

```bash
cd v2
npm run ios:app-store-build:check
```

For the strongest protection, CI should first fetch the latest build number from App Store Connect and export one of:

- `ASC_PREVIOUS_BUILD_NUMBER`
- `APP_STORE_CONNECT_PREVIOUS_BUILD_NUMBER`
- `IOS_PREVIOUS_UPLOADED_BUILD`
- `LATEST_TESTFLIGHT_BUILD_NUMBER`

If any of those env vars are present, the guard uses that live value instead of the local JSON floor.
