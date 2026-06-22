# Codex Review: V2 Paper Ledger Fill-Price Provenance

Generated: `2026-05-18T19:27:59Z`

GO/NO-GO: `V2_PAPER_LEDGER_FILL_PRICE_PROVENANCE_CODEX_FAIL`

## Decision

Codex fails this packet. The price provenance itself is V2-owned and the systemd/orphan-writer fixes are in place, but live `v2:paper:positions` and `v2:paper:ledger.accepted` are currently treating rows with `paper_fill_allowed=false` as accepted/open paper positions. The position recorder then computes MFE/MAE/ROE from those rows, and the full-observation builder lifts BTCUSDT/ETHUSDT dimensions from that evidence.

This is an acceptance-state failure, not an old-Redis, exchange, or live-trading finding. This review does not approve live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, or legacy shutdown.

## Fail Blocker

`PAPER_FILL_ALLOWED_FALSE_ROWS_COUNTED_AS_ACCEPTED_OPEN_POSITIONS`

Live Redis currently shows:

- `v2:paper:positions`: `2` rows
- `v2:paper:ledger.accepted_count=2`
- both BTCUSDT and ETHUSDT accepted/open rows have `paper_fill_allowed=false`
- both rows carry `entry_price`, `fill_price`, and `latest_price`
- both rows have `entry_price_provenance_present=true`

Observed live rows:

| Symbol | Surface | paper_fill_allowed | Entry Source | Treated As |
| --- | --- | --- | --- | --- |
| `BTCUSDT` | `v2:paper:positions` + `ledger.accepted` | `false` | `V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE` | accepted/open |
| `ETHUSDT` | `v2:paper:positions` + `ledger.accepted` | `false` | `V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE` | accepted/open |

The writer acceptance condition is currently:

`pre_trade_allowed AND fee_gate_allowed AND not churn_blocked`

It does not require the upstream `paper_fill_allowed` flag to be true, and it does not clearly relabel false-gate rows as shadow-only non-positions. That fails the critical acceptance-state check.

## Downstream Impact

After the provenance patch, the recorder consumes the false-gate position rows:

- recorder state: `OPEN_TRACKING` for BTCUSDT and ETHUSDT
- `symbols_with_entry_recovered=["BTCUSDT", "ETHUSDT"]`
- MFE/MAE/ROE are computed for BTCUSDT and ETHUSDT

The refreshed full-observation builder then reports:

- `BTCUSDT=159`
- `ETHUSDT=159`
- `SOLUSDT=147`

The builder still remains partial and does not claim checkpoint or policy parity, but the +3 BTC/ETH lift is not acceptable until the writer proves those rows are genuine paper-fill accepted positions or marks them clearly as shadow-only and excludes them from recorder/open-position computation.

## Positive Findings

Codex verified the price source discipline:

- primary source: `v2:market:prices:{symbol}.ticker_24hr.lastPrice`
- fallback source: `v2:features:latest:{symbol}:1m.features.close_price` only when `feature_freshness_state="CURRENT"`
- no legacy Redis current-truth price source found
- no static sample price source found
- missing entry price emits `MISSING_V2_MARKET_PRICE_FOR_FILL`
- close schema exposes `closes`, `close_event_count`, `realized_exit_blocker`, and `exit_price_field_contract`

Held-by-gate SOLUSDT stayed held in `v2:paper:intents_held_by_paper_fill_gate` and was not converted to a position.

The systemd unit is now quoted correctly for the workspace path with spaces, and the active process is the systemd-managed paper loop:

- `ai-bot-v2-trade-management-paper-loop.service`: active/running
- `PYTHONPATH=/home/wali/Desktop/AI BOT REBUILD`
- `LIVE_GATE=blocked_human_only`
- only one live `v2_trade_management_paper_loop` process observed

## Redis And Safety

Reviewed writer outputs are V2-prefixed:

- `v2:paper:intents`
- `v2:paper:intents_held_by_paper_fill_gate`
- `v2:risk:decisions`
- `v2:paper:ledger`
- `v2:paper:positions`
- `v2:paper:heartbeat`

Codex found no old Redis write path, exchange mutation surface, raw key exposure, live approval, canary approval, shutdown approval, or Redis-trim approval in the reviewed artifacts.

Safety state remains:

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`
- `writes_legacy_redis`: `false`
- `writes_exchange_orders`: `false`

## Runtime Governor

The Codex 8h war-room review governor remains healthy and running:

- `CODEX_8H_WAR_ROOM_REVIEW_GOVERNOR_READY`
- runtime GO/NO-GO: `READY`
- website GO/NO-GO: `PASS`
- core migration GO/NO-GO: `READY`
- overall GO/NO-GO: `READY`
- fail blockers: none

The governor does not currently detect this paper-fill acceptance-state issue; this review is the blocking packet-level finding.

## Validation

- Focused provenance tests: `13 passed`.
- Recorder tests: `19 passed`.
- TA/position-history tests: `22 passed`.
- Combined focused sweep: `54 passed`.
- `py_compile`: PASS.
- JSON validation: PASS.
- Raw secret scan: PASS, `0` hits outside `.local_secrets`.
- Old Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.
- `git diff --check`: PASS for reviewed artifacts.

The tests are insufficient because they do not cover `paper_fill_allowed=false` signals entering `v2:paper:positions` / `ledger.accepted`.

## Required Remediation

Patch the writer so false-gate rows cannot be counted as accepted/open positions:

- require `paper_fill_allowed is True` before adding a row to `accepted`, `v2:paper:positions`, or `ledger.accepted`; or
- if false-gate rows must remain visible for provenance, publish them under a clearly named shadow-only/non-position surface and ensure the recorder/full-observation builder ignores them for MFE/MAE/ROE.

Add tests proving:

- `paper_fill_allowed=false` never enters `v2:paper:positions`;
- `paper_fill_allowed=false` never increments `accepted_count`;
- recorder does not compute MFE/MAE/ROE from false-gate rows;
- full-observation dims do not increase from false-gate rows.

Then rerun this Codex review.

## Final Decision

`V2_PAPER_LEDGER_FILL_PRICE_PROVENANCE_CODEX_FAIL`
