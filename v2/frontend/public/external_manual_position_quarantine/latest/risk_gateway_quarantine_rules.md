# Risk Gateway Quarantine Rules

- `deny_external_manual_position_quarantined`: block risk-add on quarantined symbol/account
- `deny_manual_external_hedge_or_dca`: block hedge/DCA/increase on manual_external positions
- `exclude_quarantined_reward_attribution`: block trainer reward/PnL attribution from quarantined executions
- `allow_monitor_only_quarantine_state`: allow read-only dashboard monitoring without auto-close

The rules are non-live stubs. They add no exchange action path and do not
auto-close or mutate any position.
