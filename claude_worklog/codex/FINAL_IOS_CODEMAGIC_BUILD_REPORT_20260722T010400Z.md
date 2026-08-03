# iOS / Codemagic build report

- `AIBOT_SPM_EXCLUDE_APP_TARGETS=1 swift build`: passed on Linux Swift 6.1.2.
- `AIBOT_SPM_EXCLUDE_APP_TARGETS=1 swift test --filter AIBotV2Tests`: passed, 36 tests, 0 failures.
- `codemagic.yaml`: iOS workflow is manual-only and requires Apple Developer signing plus `ASC_API_KEY`; native Xcode archive was not claimed from Linux.
- Live trading remains disabled in the mobile contract tests.
