# Canary Profile Tightening Implementation Report

Generated at: `2026-05-13T19:39:03Z`

| Field | Value |
| --- | --- |
| generated_at | 2026-05-13T19:39:03Z |
| module_path | v2/backend/app/composition/canary_profile_tightening |
| test_path | v2/backend/tests/unit/composition/canary_profile_tightening |
| behaviors | ["low confidence blocked", "overtrading blocked", "churn blocked", "fee/slippage drag blocked", "stale signal blocked", "symbol not whitelisted blocked", "high-confidence fresh allowed only in paper simulation", "live still blocked without approval token", "existing hard gates are not bypassed"] |
| live_effect | none |
| hard_gates_weakened | False |
