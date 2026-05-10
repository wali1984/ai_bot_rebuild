# Exchange Linking Read-Only Design

Exchange Manager supports read-only-first connector cards for:

- Binance USD-M
- KuCoin
- MEXC

The UI exposes:

- status
- read-only key status
- trade permission state
- IP restriction state
- market-data availability
- account-read availability
- order capability

Trade permissions are always shown as blocked before the final live gate. No API
key values are stored, printed, or committed.

EXCHANGE_LINKING_READONLY_DESIGN_READY
