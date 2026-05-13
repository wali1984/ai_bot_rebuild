# Codex Account Permission And Soak Review

Generated at: `2026-05-13T13:19:18Z`

Result: `READONLY_ACCOUNT_TRADE_PERMISSION_AND_SOAK_CODEX_PASS`

| Check | Value |
| --- | --- |
| live_readiness_overstated | False |
| canary_readiness_overstated | False |
| six_h_twenty_four_h_proof_faked | False |
| readonly_account_missing_marked_present | False |
| trade_permission_unknown_blocks_canary | True |
| margin_leverage_missing_explicit | True |
| mutation_endpoint_called | False |
| final_approval_token_created | False |
| old_redis_write_occurred | False |
| exchange_action_occurred | False |
| paper_pnl_linkage_present | True |
| ui_task_superseded_primary | False |

Live remains `blocked_human_only`; canary remains blocked because account/trade/margin evidence is not green and 6h/24h soak is pending.
