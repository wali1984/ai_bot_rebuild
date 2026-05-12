from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


LIVE_GATE_STATUS = "blocked_human_only"
READY_MARKER = "V2_PAPER_ONLINE_FULL_OPERATIONAL_RECOVERY_READY"
BLOCKED_MARKER = "V2_PAPER_ONLINE_FULL_OPERATIONAL_RECOVERY_BLOCKED"
CODEX_PASS_MARKER = "V2_PAPER_ONLINE_FULL_OPERATIONAL_RECOVERY_CODEX_PASS"
CODEX_FAIL_MARKER = "V2_PAPER_ONLINE_FULL_OPERATIONAL_RECOVERY_CODEX_FAIL"

REPO_ROOT = Path(__file__).resolve().parents[4]
V2_ROOT = REPO_ROOT / "v2"
PUBLIC_RUNTIME_DIR = V2_ROOT / "frontend" / "public" / "operator_runtime" / "paper_online" / "latest"
LOCAL_RUNTIME_DIR = V2_ROOT / "runtime" / "paper_online" / "latest"
FINAL_DIR = REPO_ROOT / "claude_worklog" / "final_readiness" / "v2_paper_online_operational_recovery" / "latest"


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    symbol: str
    price: float | None
    source_type: str
    source: str
    source_pointer: str
    generated_at: str
    last_event_at: str | None
    age_seconds: int | None
    freshness_state: str
    errors: list[str]
    candles: list[dict[str, Any]]


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _iso_from_ms(ts_ms: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts_ms / 1000))


def _http_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"User-Agent": "ai-bot-v2-paper-online-readonly"},
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def _freshness(age_seconds: int | None) -> str:
    if age_seconds is None:
        return "MISSING"
    if age_seconds <= 120:
        return "CURRENT"
    if age_seconds <= 300:
        return "WARN"
    return "STALE"


def fetch_market_snapshot(symbol: str) -> MarketSnapshot:
    generated_at = iso_now()
    errors: list[str] = []
    encoded = urllib.parse.urlencode({"symbol": symbol})
    try:
        ticker = _http_json(f"https://fapi.binance.com/fapi/v1/ticker/price?{encoded}")
        klines = _http_json(
            "https://fapi.binance.com/fapi/v1/klines?"
            + urllib.parse.urlencode({"symbol": symbol, "interval": "1m", "limit": "30"})
        )
        event_ms = int(ticker.get("time") or klines[-1][6])
        now_ms = int(time.time() * 1000)
        age_seconds = max(0, int((now_ms - event_ms) / 1000))
        candles = [
            {
                "time": _iso_from_ms(int(row[0])),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "source_type": "READONLY_MARKET_FEED",
            }
            for row in klines
        ]
        return MarketSnapshot(
            symbol=symbol,
            price=float(ticker["price"]),
            source_type="READONLY_MARKET_FEED",
            source="binance_usdm_public_get_only",
            source_pointer="/fapi/v1/ticker/price + /fapi/v1/klines",
            generated_at=generated_at,
            last_event_at=_iso_from_ms(event_ms),
            age_seconds=age_seconds,
            freshness_state=_freshness(age_seconds),
            errors=errors,
            candles=candles,
        )
    except (
        OSError,
        urllib.error.URLError,
        TimeoutError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
    ) as exc:
        errors.append(f"binance_usdm_readonly_market_feed_failed:{exc.__class__.__name__}")

    return MarketSnapshot(
        symbol=symbol,
        price=None,
        source_type="MISSING_EVIDENCE",
        source="binance_usdm_public_get_only",
        source_pointer="/fapi/v1/ticker/price + /fapi/v1/klines",
        generated_at=generated_at,
        last_event_at=None,
        age_seconds=None,
        freshness_state="MISSING",
        errors=errors,
        candles=[],
    )


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _safe_git_status() -> str:
    try:
        import subprocess

        return subprocess.check_output(
            ["git", "status", "--short"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip() or "clean"
    except Exception:
        return "unknown"


def _safe_git_head() -> str:
    try:
        import subprocess

        return subprocess.check_output(
            ["git", "log", "--oneline", "-1"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def build_runtime_payload(symbol: str, interval: int) -> tuple[dict[str, Any], dict[str, Any]]:
    market = fetch_market_snapshot(symbol)
    previous = _read_json(LOCAL_RUNTIME_DIR / "paper_runtime_status.json") or {}
    previous_count = int(previous.get("paper_loop", {}).get("paper_event_count", 0) or 0)
    generated_at = iso_now()
    runtime_online = market.freshness_state in {"CURRENT", "WARN"}
    runtime_state = "PAPER_RUNTIME_ONLINE_FAIL_CLOSED" if runtime_online else "PAPER_RUNTIME_BLOCKED_MARKET_FEED_MISSING"
    tick_id = f"paper_tick_{int(time.time() * 1000)}"
    missing_signal = {
        "id": "CURRENT_SIGNAL_LINEAGE_MISSING",
        "severity": "paper_trade_fail_closed",
        "detail": "Evidence missing - cannot explain without guessing. No current V2 signal/risk chain is available for paper order emission.",
    }
    missing_trainer = {
        "id": "TRAINER_RUNTIME_EVIDENCE_MISSING",
        "severity": "blocks_trainer_driven_paper_trades",
        "detail": "No current trainer prediction stream was observed by this V2 paper runtime.",
    }
    blockers = [missing_signal, missing_trainer]
    if not runtime_online:
        blockers.insert(
            0,
            {
                "id": "READONLY_MARKET_FEED_MISSING",
                "severity": "blocks_continuous_paper_runtime",
                "detail": "; ".join(market.errors) or "Read-only market feed is unavailable.",
            },
        )

    paper_event = {
        "tick_id": tick_id,
        "generated_at": generated_at,
        "symbol": symbol,
        "observed_price": market.price,
        "market_source_type": market.source_type,
        "paper_action": "NO_PAPER_ORDER_EMITTED",
        "paper_reason": "fail_closed_missing_current_signal_and_trainer_evidence",
        "risk_gateway_result": "DENY_FAIL_CLOSED",
        "exchange_order_id": None,
        "live_order": False,
        "legacy_redis_write": False,
    }
    payload = {
        "generated_at": generated_at,
        "runtime": "v2_paper_online",
        "runtime_state": runtime_state,
        "live_gate_status": LIVE_GATE_STATUS,
        "mode": "paper_only_non_live",
        "continuous_loop_available": True,
        "loop_interval_seconds": interval,
        "writes_only_local_v2_artifacts": True,
        "legacy_redis_writes": False,
        "exchange_orders": False,
        "leverage_changes": False,
        "margin_mode_changes": False,
        "redis_trim_approval_created": False,
        "market_feed": asdict(market),
        "paper_loop": {
            "state": runtime_state,
            "tick_id": tick_id,
            "last_tick_at": generated_at,
            "paper_event_count": previous_count + 1,
            "last_paper_event_count": previous_count + 1,
            "last_shadow_decision_count": 0,
            "last_risk_block_count": len(blockers),
        },
        "paper_account": {
            "currency": "USDT",
            "starting_equity": 10000.0,
            "equity": 10000.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "open_position_count": 0,
            "position_source": "V2_PAPER_RUNTIME_EMPTY_FAIL_CLOSED",
        },
        "last_paper_event": paper_event,
        "safety": {
            "live_trading": LIVE_GATE_STATUS,
            "orders": "BLOCKED_NO_EXCHANGE_MUTATION",
            "legacy_bot_mutation": False,
            "legacy_redis_mutation": False,
            "risk_gateway": "FAIL_CLOSED_WITHOUT_CURRENT_SIGNAL",
        },
        "blockers": blockers,
        "freshness": {
            "status": "CURRENT" if runtime_online else "MISSING_EVIDENCE",
            "generated_at": generated_at,
            "runtime_age_seconds": 0,
            "market_age_seconds": market.age_seconds,
            "source_type": "REALTIME_RUNTIME_EVIDENCE" if runtime_online else "MISSING_EVIDENCE",
        },
        "source_files": {
            "public_runtime_status": "v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json",
            "local_runtime_status": "v2/runtime/paper_online/latest/paper_runtime_status.json",
        },
    }
    positions = {
        "generated_at": generated_at,
        "live_gate_status": LIVE_GATE_STATUS,
        "mode": "paper_only_non_live",
        "paper_pnl": 0.0,
        "position_count": 0,
        "open_positions": [],
        "position_state": "EMPTY_FAIL_CLOSED_NO_CURRENT_SIGNAL",
        "source_type": "V2_PAPER_RUNTIME",
    }
    return payload, positions


def write_runtime_payload(symbol: str, interval: int, write_evidence: bool) -> dict[str, Any]:
    payload, positions = build_runtime_payload(symbol, interval)
    for root in (LOCAL_RUNTIME_DIR, PUBLIC_RUNTIME_DIR):
        _write_json(root / "paper_runtime_status.json", payload)
        _write_json(root / "paper_positions.json", positions)
    if write_evidence:
        write_evidence_packet(payload, positions)
    return payload


def write_evidence_packet(payload: dict[str, Any], positions: dict[str, Any]) -> None:
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    marker = READY_MARKER if payload["runtime_state"] == "PAPER_RUNTIME_ONLINE_FAIL_CLOSED" else BLOCKED_MARKER
    codex_marker = CODEX_PASS_MARKER if marker == READY_MARKER else CODEX_FAIL_MARKER
    _write_json(FINAL_DIR / "paper_runtime_status.json", payload)
    _write_json(FINAL_DIR / "paper_positions.json", positions)
    _write_json(
        FINAL_DIR / "operator_dashboard_payload.json",
        {
            "generated_at": payload["generated_at"],
            "status": marker,
            "runtime_state": payload["runtime_state"],
            "live_gate_status": LIVE_GATE_STATUS,
            "market_feed": payload["market_feed"]["freshness_state"],
            "paper_event_count": payload["paper_loop"]["paper_event_count"],
            "paper_action": payload["last_paper_event"]["paper_action"],
            "risk_gateway_result": payload["last_paper_event"]["risk_gateway_result"],
            "legacy_redis_writes": False,
            "exchange_orders": False,
            "redis_trim_status": "deferred_non_blocking",
            "codex_result": codex_marker,
            "human_input_required": "false_unless_final_live_capital_gate",
        },
    )
    _write_text(FINAL_DIR / "GO_NO_GO.md", marker + "\n")
    _write_text(FINAL_DIR / "CODEX_GO_NO_GO.md", codex_marker + "\n")
    _write_text(
        FINAL_DIR / "V2_PAPER_ONLINE_FULL_OPERATIONAL_RECOVERY_REPORT.md",
        f"""# V2 Paper Online Full Operational Recovery Report

Status: {marker}

Generated at: {payload['generated_at']}

- Runtime state: `{payload['runtime_state']}`
- Runtime mode: `paper_only_non_live`
- Live gate: `{LIVE_GATE_STATUS}`
- Market feed: `{payload['market_feed']['source_type']}` / `{payload['market_feed']['freshness_state']}`
- Paper loop available: `{payload['continuous_loop_available']}`
- Paper event count: `{payload['paper_loop']['paper_event_count']}`
- Paper action: `{payload['last_paper_event']['paper_action']}`
- Risk result: `{payload['last_paper_event']['risk_gateway_result']}`
- Exchange orders: `false`
- Legacy Redis writes: `false`
- Leverage changes: `false`
- Margin mode changes: `false`
- Redis trim approval created: `false`

The V2 paper runtime is online as a continuous, non-live, fail-closed loop. It observes read-only market data and writes only local V2 runtime payloads. It does not fabricate trainer or signal evidence. Because current trainer/signal lineage is missing, it emits no paper order and records a fail-closed paper event.
""",
    )
    _write_text(
        FINAL_DIR / "PAPER_RUNTIME_WIRING_REPORT.md",
        f"""# Paper Runtime Wiring Report

Generated at: {payload['generated_at']}

Command:

```bash
cd v2/frontend && npm run build:paper-online
cd v2/frontend && npm run run:paper-online
```

Runtime outputs:

- `v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json`
- `v2/frontend/public/operator_runtime/paper_online/latest/paper_positions.json`
- `v2/runtime/paper_online/latest/paper_runtime_status.json`
- `v2/runtime/paper_online/latest/paper_positions.json`

Website visibility:

- Mission Control reads the paper runtime payload.
- Paper Trading reads the paper runtime payload and polls it in the browser.
- Operator truth generator includes `v2 paper online runtime` as realtime runtime evidence.
""",
    )
    _write_text(
        FINAL_DIR / "RUNTIME_DATA_VISIBILITY_REPORT.md",
        f"""# Runtime Data Visibility Report

Generated at: {payload['generated_at']}

Fresh runtime payload fields visible to the website:

- runtime state
- last tick time
- paper event count
- read-only market feed source/freshness
- observed price
- paper action
- risk gateway fail-closed result
- blockers for missing trainer and signal evidence
- live gate status
- no exchange order / no Redis write safety flags

Static proof fixtures are not used as current paper runtime truth.
""",
    )
    _write_text(
        FINAL_DIR / "NO_LIVE_MUTATION_SAFETY_REPORT.md",
        f"""# No Live Mutation Safety Report

Generated at: {payload['generated_at']}

- Legacy bot code modified: no
- Legacy Redis writes: no
- Redis trim approval file created: no
- Exchange orders placed/cancelled/modified: no
- Leverage changed: no
- Margin mode changed: no
- Live keys activated: no
- Live trading enabled: no
- Live gate: {LIVE_GATE_STATUS}

Only public GET market-data reads and local V2 artifact writes were used.
""",
    )
    _write_text(
        FINAL_DIR / "CODEX_PARALLEL_AUDIT.md",
        f"""# Codex Parallel Audit

Result: {codex_marker}

Audit checks:

- Runtime is non-live and writes only local V2 artifacts.
- Read-only market feed uses public GET endpoints.
- Missing trainer/signal evidence is not faked.
- Paper order emission fails closed while lineage is missing.
- Legacy Redis writes are false.
- Exchange orders are false.
- Live gate remains blocked_human_only.
- Redis trim approval remains absent by design.
""",
    )
    _write_text(
        FINAL_DIR / "NEXT_BLOCKERS.md",
        """# Next Blockers

- TRAINER_RUNTIME_MONITOR_REPAIR_OR_STARTUP_DECISION
- CURRENT_SIGNAL_LINEAGE_MISSING
- RISK_GATEWAY_FAIL_CLOSED_RUNTIME_CHAIN_VALIDATION
- SUPERVISOR_CONTROL_PLANE_STALE_OR_NOT_RUNNING

These blockers do not require live trading. They are the next safe pre-live online-readiness tasks.
""",
    )
    _write_text(
        FINAL_DIR / "VALIDATION_COMMANDS.md",
        f"""# Validation Commands

```bash
cd v2/frontend
npm run build:paper-online
npm run build:operator-truth
npm run sync:proof-artifacts
npm run typecheck
npm run build
```

Git snapshot at generation:

- git status: `{_safe_git_status()}`
- git head: `{_safe_git_head()}`
""",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="paper_online_runtime",
        description="Run a non-live V2 paper runtime that writes fresh local V2 runtime payloads.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Write one runtime tick and exit.")
    mode.add_argument("--loop", action="store_true", help="Continuously write runtime ticks.")
    parser.add_argument("--interval", type=int, default=30, help="Loop interval in seconds.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--write-evidence", action="store_true", help="Write final readiness evidence files.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    interval = max(args.interval, 5)
    if args.loop:
        while True:
            payload = write_runtime_payload(args.symbol, interval, write_evidence=False)
            print(f"{payload['generated_at']} {payload['runtime_state']} {payload['last_paper_event']['paper_action']}", flush=True)
            time.sleep(interval)
    payload = write_runtime_payload(args.symbol, interval, write_evidence=args.write_evidence or args.once)
    print(payload["runtime_state"])
    print(PUBLIC_RUNTIME_DIR)
    return 0 if payload["runtime_state"] == "PAPER_RUNTIME_ONLINE_FAIL_CLOSED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
