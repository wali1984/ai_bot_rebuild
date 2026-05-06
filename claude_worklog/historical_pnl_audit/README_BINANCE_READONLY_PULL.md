# Optional Binance Read-Only Pull

The historical audit can pull 30-day USD-M account-history evidence if read-only Binance API credentials are available in environment variables.

Accepted environment variable names:

- `BINANCE_API_KEY` / `BINANCE_API_SECRET`
- `BINANCE_FUTURES_API_KEY` / `BINANCE_FUTURES_API_SECRET`
- `BINANCE_USDM_API_KEY` / `BINANCE_USDM_API_SECRET`

Command:

```bash
cd "$HOME/Desktop/AI BOT REBUILD"
DAYS=30 SYMBOLS="BTCUSDT,ETHUSDT,SOLUSDT" BINANCE_FLAG=1 ./claude_worklog/tools/run_historical_pnl_trade_audit_once.sh
```

Rules:

- GET-only account/history endpoints.
- No orders.
- No cancels.
- No leverage or margin changes.
- No transfers.
- No secret values printed or committed.
