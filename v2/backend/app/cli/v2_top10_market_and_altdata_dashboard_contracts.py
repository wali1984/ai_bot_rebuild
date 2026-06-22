"""Emit top-10 market and altdata dashboard contracts.

Contract-only. No provider clients, no provider API calls, no Redis
writes, no exchange mutation.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from v2.backend.app.services.alternative_data.top10_dashboard_contracts import (
    build_public_payload,
    build_top10_dashboard_contracts,
)

WORKLOG_CONTRACTS = Path(
    "claude_worklog/final_readiness/v2_top10_market_and_altdata_dashboard_contracts/latest/top10_dashboard_contracts.json"
)
WORKLOG_REPORT = Path(
    "claude_worklog/final_readiness/v2_top10_market_and_altdata_dashboard_contracts/latest/TOP10_MARKET_AND_ALTDATA_DASHBOARD_CONTRACTS.md"
)
WORKLOG_GO_NO_GO = Path(
    "claude_worklog/final_readiness/v2_top10_market_and_altdata_dashboard_contracts/latest/GO_NO_GO.md"
)
PUBLIC_PAYLOAD = Path(
    "v2/frontend/public/v2_top10_market_and_altdata_dashboard_contracts/latest/operator_dashboard_payload.json"
)


def _write_report(path: Path, contracts: dict) -> None:
    ids = "\n".join(
        f"{row['rank']}. `{row['id']}` - {row['title']}"
        for row in contracts["dashboards"]
    )
    alt_rows = [
        row for row in contracts["dashboards"]
        if row.get("category") == "alternative_data"
    ]
    alt_summary = "\n".join(
        f"- `{row['id']}`: enabled=`{str(row['enabled']).lower()}`, disabled_reason=`{row['disabled_reason']}`"
        for row in alt_rows
    )
    body = f"""# Top-10 Market And Alternative-Data Dashboard Contracts

Generated: `{contracts['generated_utc']}`

GO/NO-GO: `{contracts['go_no_go']}`

## Decision

The top-10 website dashboard contracts are defined using V2 data only. This is contract/data-shape work only; it does not implement provider clients, does not call provider APIs, does not write Redis, and does not affect trading gates.

## Dashboards

{ids}

## Data Rules

- Binance 12h dashboards use Binance rolling-window stats when present, or locally computed 12h windows from V2 market data.
- Liquidation tape uses V2 liquidation WSS aggregate keys only and never synthesizes liquidation events.
- Funding/OI movers use existing V2 CoinAnk/funding/open-interest payloads.
- Nansen and LunarCrush dashboards remain disabled/empty until provider clients pass Codex.
- Missing provider keys produce `MISSING_SOURCE`; present keys without Codex-passed clients produce `KEY_PRESENT_NO_CLIENT_YET`.

## Alternative-Data Panels

{alt_summary}

## Safety

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`
- `writes_old_redis`: `false`
- `exchange_mutation`: `false`
- raw values exposed: `false`
- provider network calls attempted: `false`

## Final Decision

`{contracts['go_no_go']}`
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def run_once() -> dict:
    contracts = build_top10_dashboard_contracts()
    public_payload = build_public_payload()
    body = json.dumps(contracts, indent=2, sort_keys=True) + "\n"
    WORKLOG_CONTRACTS.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_PAYLOAD.parent.mkdir(parents=True, exist_ok=True)
    WORKLOG_CONTRACTS.write_text(body, encoding="utf-8")
    WORKLOG_GO_NO_GO.write_text(contracts["go_no_go"] + "\n", encoding="utf-8")
    PUBLIC_PAYLOAD.write_text(
        json.dumps(public_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_report(WORKLOG_REPORT, contracts)
    return contracts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="v2_top10_market_and_altdata_dashboard_contracts"
    )
    parser.add_argument("--once", action="store_true")
    parser.parse_args(argv)
    payload = run_once()
    print(
        json.dumps(
            {
                "go_no_go": payload["go_no_go"],
                "dashboard_count": payload["dashboard_count"],
                "provider_network_calls_attempted": payload[
                    "provider_network_calls_attempted"
                ],
                "raw_values_exposed": payload["raw_values_exposed"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
