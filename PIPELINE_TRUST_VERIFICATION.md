# Pipeline Trust Verification Tool

`verify_pipeline_trust` is a read-only audit command for the existing V2 pipeline. It inspects stored JSON/JSONL snapshots and optional Redis data, then writes:

- `pipeline_trust_report.json`
- `pipeline_trust_report.md`

The command does not submit orders, cancel orders, mutate Redis, trim streams, restart services, change strategy logic, change PPO, change MASA, or change execution behavior.

## Usage

Run against exported JSON/JSONL evidence:

```bash
./verify_pipeline_trust --input raw_evidence --input replay_data --output-dir .
```

Run against Redis with read-only commands:

```bash
./verify_pipeline_trust --redis-url "$REDIS_URL" --output-dir .
```

Run against both stored files and Redis:

```bash
./verify_pipeline_trust --input raw_evidence --redis-url "$REDIS_URL" --output-dir .
```

## Exit behavior

The command exits `0` when no critical failures are found.

The command exits non-zero when it detects critical failures such as:

- look-ahead leakage
- future feature use
- unfinished higher-timeframe candle use
- dirty training sample acceptance
- invalid position transition

Use `--strict-unknown` if missing evidence should also fail as critical.

## Checks

The report includes PASS/FAIL/WARN findings for:

- candle integrity
- multi-timeframe alignment
- feature integrity
- MASA/PPO consistency
- training samples
- position and execution records
- config/admin safety state
- live vs paper/backtest parity

Each finding includes severity, affected files/modules, affected symbols/timeframes when known, example records, and a recommended fix.

## Redis behavior

When `--redis-url` is supplied, the verifier only uses read commands such as `SCAN`, `GET`, `HGETALL`, `LRANGE`, `XREVRANGE`, `ZRANGE`, and `SMEMBERS`.

Default scan patterns target V2 pipeline keys and current CoinAnk evidence keys. You can override or narrow scans with repeated `--redis-pattern` values.

## Notes

This verifier is intentionally conservative. A PASS means the loaded records did not contain the checked violation. It does not prove the entire production pipeline is safe unless the supplied data covers the relevant runtime windows and all required metadata is present.
