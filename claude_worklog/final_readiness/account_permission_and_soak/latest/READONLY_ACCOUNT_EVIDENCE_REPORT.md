# Readonly Account Evidence Report

Generated at: `2026-05-13T13:19:18Z`

| Field | Value |
| --- | --- |
| generated_at | 2026-05-13T13:19:18Z |
| account_evidence_status | READONLY_ACCOUNT_EVIDENCE_STALE |
| classifications | ["READONLY_ACCOUNT_EVIDENCE_STALE", "READONLY_ADAPTER_NOT_CONFIGURED", "READONLY_KEY_STATUS_UNKNOWN", "EVIDENCE_PROVIDER_REQUIRED"] |
| exchange | Binance USD-M |
| account_mode | MISSING_EVIDENCE |
| can_read_balance | False |
| can_read_positions | False |
| can_read_open_orders_readonly | False |
| key_present_redacted | False |
| key_permissions_known | False |
| generated_at_source | 2026-05-10T00:00:00Z |
| source_path | claude_worklog/final_readiness/readonly_market_exchange_data_plane/latest/operator_dashboard_payload.json |
| age_seconds | 307158 |
| missing_fields | ["fresh_current_payload", "balance_read", "position_read", "open_orders_read", "key_status_known"] |
| safety_notes | No secrets printed. No account endpoint was called by this task. Existing payload is treated as evidence only if current. |
| canary_blocker | True |
