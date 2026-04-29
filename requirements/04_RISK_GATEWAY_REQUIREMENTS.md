# Risk Gateway Requirements

Risk gateway must block:

- Missing attribution
- Missing signal_id
- Missing confidence
- Stale risk-add signals
- CROSS margin in live mode
- Leverage above configured cap
- Duplicate exchange_order_id
- Missing stop policy
- Disabled kill switch
- ADJUST_LEVERAGE unless explicitly enabled
