# Legacy Root Access Proof Round 2

Generated: `2026-05-16T01:30:30Z`

The stale global `LEGACY_ROOT_READ_ACCESS_DENIED` classification is removed for the files required by this remediation. Codex verified every previously blocked source file exists, is readable, and has been copied into `v2/legacy_owned_runtime` without modifying the legacy tree.

| Source | Destination | SHA256 | Status |
| --- | --- | --- | --- |
| `/home/wali/Desktop/AI BOT/tools/health.py` | `v2/legacy_owned_runtime/tools/health.py` | `5e535062b387a501e9c266d0b45681497bd3bf084e40606594223eb2da445dce` | `SAFE_SOURCE_COPIED_TO_V2_OWNED_RUNTIME` |
| `/home/wali/Desktop/AI BOT/ingest/technical_analysis.py` | `v2/legacy_owned_runtime/ingest/technical_analysis.py` | `909437e7e77bcf6a03371c546b074a20e7a216bcd72b13ba783dcd78154dbee0` | `SAFE_SOURCE_COPIED_TO_V2_OWNED_RUNTIME` |
| `/home/wali/Desktop/AI BOT/monitoring/oom_monitor.py` | `v2/legacy_owned_runtime/monitoring/oom_monitor.py` | `6fdf878ea8cfbfef7b97c8832ca9a34479763eb42936d2c5a770fab8a4041d57` | `SAFE_SOURCE_COPIED_TO_V2_OWNED_RUNTIME` |
| `/home/wali/Desktop/AI BOT/monitoring/deep_troubleshooter.py` | `v2/legacy_owned_runtime/monitoring/deep_troubleshooter.py` | `b293e876155af5af923a9aa2e0c8ece84e0d87e58a37028ee95ebc0f5a364271` | `SAFE_SOURCE_COPIED_TO_V2_OWNED_RUNTIME` |
| `/home/wali/Desktop/AI BOT/monitoring/live_system_auditor.py` | `v2/legacy_owned_runtime/monitoring/live_system_auditor.py` | `1a72674aab6c2cc14d2915f5dea8e975ca03a89adaebfc7fd0542ddf511cadd4` | `SAFE_SOURCE_COPIED_TO_V2_OWNED_RUNTIME` |
| `/home/wali/Desktop/AI BOT/monitoring/regression_alarms.py` | `v2/legacy_owned_runtime/monitoring/regression_alarms.py` | `1bceec7b6756cdda877bf600d0671cdafb008bcfaaf80166c5a457271e8079aa` | `SAFE_SOURCE_COPIED_TO_V2_OWNED_RUNTIME` |

This proof does not approve legacy shutdown or live trading.
