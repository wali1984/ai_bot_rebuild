"""V2 account/position read-only monitor.

This standalone worker emits public account and position evidence for
operator readiness checks. It uses only read-only exchange endpoints,
keeps simulated paper positions out of real account evidence, and keeps
the live gate permanently blocked.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from v2.backend.app.services.account_position_monitor.service import (
    ACCOUNT_ENDPOINT,
    POSITION_RISK_ENDPOINT,
    BinanceFuturesReadOnlyClient,
    ExchangeReadError,
    LIVE_GATE_STATUS,
    MISSING_EVIDENCE,
    RateLimitError,
    ReadOnlyContractError,
    ReadOnlyCredentials,
    anonymized_position_sample,
    collect_account_position_evidence,
)
from v2.backend.app.services.symbol_universe.service import (
    DYNAMIC_SYMBOL_SOURCES,
    LEGACY_ACTIVE_SYMBOLS_25,
    SYMBOL_SELECTION_SCORE_FACTORS,
    SymbolUniverseService,
)


WORKER_ID = "v2_account_position_monitor"
SYMBOL_UNIVERSE_CONTRACT = "SYMBOL_UNIVERSE_CONTRACT_REQUIRED"
SYMBOL_UNIVERSE_SERVICE_PATH = "v2/backend/app/services/symbol_universe/service.py"
EXCHANGE_CALL_INVARIANT = "READONLY_ACCOUNT_AND_POSITION_ENDPOINTS_ONLY"
SOURCE_ENDPOINT_VERSIONS = [ACCOUNT_ENDPOINT, POSITION_RISK_ENDPOINT]
LEGACY_ACTIVE_SYMBOL_SOURCE = "legacy_reference/config.py SYMBOLS via SymbolUniverseService"

REPO_ROOT = Path(__file__).resolve().parents[4]
V2_ROOT = REPO_ROOT / "v2"
PUBLIC_RUNTIME_DIR = (
    V2_ROOT / "frontend" / "public" / "operator_runtime" / WORKER_ID / "latest"
)
LOCAL_RUNTIME_DIR = V2_ROOT / "runtime" / WORKER_ID / "latest"
WORKER_STATUS_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "emergency_v2_runtime_migration"
    / "latest"
    / "workers"
)

PUBLIC_STATUS_FILE = PUBLIC_RUNTIME_DIR / f"{WORKER_ID}_status.json"
LOCAL_STATUS_FILE = LOCAL_RUNTIME_DIR / f"{WORKER_ID}_status.json"
WORKER_STATUS_FILE = WORKER_STATUS_DIR / f"{WORKER_ID}_status.json"

PAPER_POSITION_CANDIDATE_PATHS = [
    V2_ROOT / "frontend" / "public" / "operator_runtime" / "paper_online" / "latest" / "paper_runtime_status.json",
    V2_ROOT / "frontend" / "public" / "operator_runtime" / "v2_paper_execution_worker" / "latest" / "v2_paper_execution_worker_status.json",
    V2_ROOT / "frontend" / "public" / "v2_paper_online_recovery" / "latest" / "paper_positions.json",
]

SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES = [
    V2_ROOT
    / "frontend"
    / "public"
    / "operator_runtime"
    / "symbol_universe"
    / "latest"
    / "symbol_universe_status.json",
    V2_ROOT / "frontend" / "public" / "symbol_universe" / "latest" / "symbol_universe_status.json",
]

LEGACY_SOURCE_PATHS = [
    "legacy_reference/monitor_portfolio.py",
    "legacy_reference/monitor_portfolio_primary.py",
    "legacy_reference/monitor_portfolio_asjad.py",
    "legacy_reference/trading/position_reporter.py",
    "legacy_reference/utils/unified_position_loader.py",
    "legacy_reference/config.py",
]

REQUIRED_PUBLIC_PAYLOAD_FIELDS = (
    "worker_id",
    "last_run_ts",
    "last_successful_account_fetch_ts",
    "last_successful_positions_fetch_ts",
    "credentials_status_one_of_PRESENT_MISSING_INVALID",
    "account_state_one_of_FRESH_STALE_MISSING",
    "open_positions_count",
    "open_positions_sample_anonymized",
    "margin_mode_evidence_or_MISSING_EVIDENCE",
    "leverage_evidence_or_MISSING_EVIDENCE",
    "maintenance_margin_ratio_pct",
    "account_margin_ratio_status",
    "source_endpoint_versions",
    "freshness_seconds",
    "symbol_universe_contract",
    "symbol_universe_source_path",
    "legacy_active_symbols",
    "discovered_symbols",
    "observed_symbols",
    "training_symbols",
    "paper_symbols",
    "live_blocked_symbols",
    "binance_usdm_confirmed_symbols",
    "legacy_active_symbol_source",
    "dynamic_discovered_symbols",
    "dynamic_symbol_sources",
    "live_symbols",
    "passive_monitor_all_discovered_symbols",
    "train_all_discovered_symbols",
    "trade_all_discovered_symbols",
    "live_symbol_policy",
    "symbol_selection_score_factors",
)


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: Any) -> Optional[dt.datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except ValueError:
        return None


def freshness_seconds_for(*timestamps: Any) -> Optional[int]:
    parsed = [parse_iso(value) for value in timestamps]
    parsed = [value for value in parsed if value is not None]
    if not parsed:
        return None
    newest = max(parsed)
    return max(0, int((dt.datetime.now(dt.timezone.utc) - newest).total_seconds()))


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _as_symbol_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        items: List[Any] = [value]
    elif isinstance(value, list):
        items = list(value)
    else:
        return []
    out: List[str] = []
    for raw in items:
        if isinstance(raw, dict):
            raw = raw.get("canonical_symbol_id") or raw.get("symbol") or raw.get("legacy_symbol")
        text = str(raw or "").strip().upper()
        if text:
            out.append(text)
    return sorted(set(out))


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _load_symbol_universe_public_payload() -> Tuple[Dict[str, Any], Optional[str]]:
    for candidate in SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES:
        if candidate.exists():
            data = _read_json(candidate)
            return (data if isinstance(data, dict) else {}), _rel(candidate)
    return {}, None


def build_symbol_scope(
    *,
    observed_symbols: List[str],
    input_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    overrides = input_overrides or {}
    public_payload, public_path = _load_symbol_universe_public_payload()
    source_payload: Dict[str, Any] = public_payload if public_payload else overrides

    legacy_seed = _as_symbol_list(
        source_payload.get("legacy_active_symbols")
        or overrides.get("legacy_active_symbols")
        or LEGACY_ACTIVE_SYMBOLS_25
    )
    universe_service = SymbolUniverseService(legacy_active_symbols=legacy_seed)

    discovered = _as_symbol_list(
        source_payload.get("discovered_symbols")
        or source_payload.get("symbols_discovered")
        or source_payload.get("all_discovered_symbols")
    )
    if not discovered:
        discovered = sorted(
            {
                identity.canonical_symbol_id.upper()
                for identity in universe_service.all_discovered_symbols()
                if getattr(identity, "canonical_symbol_id", None)
            }
        )
    dynamic_discovered = _as_symbol_list(
        source_payload.get("dynamic_discovered_symbols")
        or source_payload.get("dynamic_symbols")
        or overrides.get("dynamic_discovered_symbols")
        or discovered
    )
    if not discovered and dynamic_discovered:
        discovered = list(dynamic_discovered)

    training_symbols = _as_symbol_list(
        source_payload.get("training_symbols") or overrides.get("training_symbols")
    )
    paper_symbols = _as_symbol_list(
        source_payload.get("paper_symbols") or overrides.get("paper_symbols")
    )
    observed = _as_symbol_list(observed_symbols)
    binance_confirmed = _as_symbol_list(
        source_payload.get("binance_usdm_confirmed_symbols")
        or source_payload.get("tradable_symbols")
        or overrides.get("binance_usdm_confirmed_symbols")
    )
    live_blocked = sorted(set(binance_confirmed or discovered or universe_service.legacy_active_symbols()))

    return {
        "symbol_universe_contract": SYMBOL_UNIVERSE_CONTRACT,
        "symbol_universe_source_path": SYMBOL_UNIVERSE_SERVICE_PATH,
        "symbol_universe_public_payload_status": (
            "PRESENT" if public_path else "MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD"
        ),
        "symbol_universe_public_payload_path": public_path or "",
        "legacy_active_symbols": universe_service.legacy_active_symbols(),
        "legacy_active_symbol_source": LEGACY_ACTIVE_SYMBOL_SOURCE,
        "discovered_symbols": discovered,
        "dynamic_discovered_symbols": dynamic_discovered,
        "dynamic_symbol_sources": list(DYNAMIC_SYMBOL_SOURCES),
        "observed_symbols": observed,
        "training_symbols": training_symbols,
        "paper_symbols": paper_symbols,
        "live_symbols": [],
        "live_blocked_symbols": live_blocked,
        "binance_usdm_confirmed_symbols": binance_confirmed,
        "live_symbol_policy": "live_symbols_empty_while_live_gate_blocked_human_only",
        "passive_monitor_all_discovered_symbols": True,
        "train_all_discovered_symbols": False,
        "trade_all_discovered_symbols": False,
        "coinank_symbols_directly_tradable": False,
        "coinank_tradability_policy": "CoinAnk-only symbols remain intelligence candidates until Binance USD-M confirmation exists.",
        "symbol_selection_score_factors": list(SYMBOL_SELECTION_SCORE_FACTORS),
    }


def _paper_position_payload_status() -> Dict[str, Any]:
    for candidate in PAPER_POSITION_CANDIDATE_PATHS:
        if candidate.exists():
            return {
                "paper_positions_source_path": _rel(candidate),
                "paper_positions_payload_present": True,
                "paper_positions_ignored_for_real_account": True,
            }
    return {
        "paper_positions_source_path": "",
        "paper_positions_payload_present": False,
        "paper_positions_ignored_for_real_account": True,
    }


def build_missing_credentials_status(credentials: ReadOnlyCredentials) -> Dict[str, Any]:
    now = iso_now()
    symbol_scope = build_symbol_scope(observed_symbols=[])
    status: Dict[str, Any] = {
        "worker_id": WORKER_ID,
        "generated_at": now,
        "last_run_ts": now,
        "last_successful_account_fetch_ts": "",
        "last_successful_positions_fetch_ts": "",
        "credentials_status_one_of_PRESENT_MISSING_INVALID": credentials.status,
        "credentials_status": credentials.status,
        "account_state_one_of_FRESH_STALE_MISSING": "MISSING",
        "open_positions_count": 0,
        "open_positions_sample_anonymized": [],
        "margin_mode_evidence_or_MISSING_EVIDENCE": MISSING_EVIDENCE,
        "leverage_evidence_or_MISSING_EVIDENCE": MISSING_EVIDENCE,
        "maintenance_margin_ratio_pct": None,
        "account_margin_ratio_status": "MISSING_EVIDENCE",
        "source_endpoint_versions": list(SOURCE_ENDPOINT_VERSIONS),
        "freshness_seconds": None,
        "live_gate": LIVE_GATE_STATUS,
        "current_gate_state": LIVE_GATE_STATUS,
        "current_gate_state_must_equal_blocked_human_only": True,
        "gate_always_blocked_invariant": True,
        "live_blocked": True,
        "exchange_call_invariant": EXCHANGE_CALL_INVARIANT,
        "exchange_action_taken": False,
        "exchange_mutation_performed": False,
        "fail_closed": True,
        "fail_closed_reason": "MISSING_CREDENTIALS",
        "runtime_evidence_status": "MISSING_CREDENTIALS",
        "missing_runtime_evidence": True,
        "trade_permission_status": "TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY",
        "account_snapshot": {},
        "positions": [],
        "legacy_source_paths": list(LEGACY_SOURCE_PATHS),
        "canary_ready": False,
        "canary_blockers": [
            "MISSING_CREDENTIALS",
            "ISOLATED_MARGIN_EVIDENCE_MISSING",
            "LEVERAGE_CAP_EVIDENCE_MISSING",
            "CANARY_BLOCKED_BY_ACCOUNT_EVIDENCE",
        ],
    }
    status.update(symbol_scope)
    status.update(_paper_position_payload_status())
    return status


def build_exchange_error_status(
    *,
    credentials: ReadOnlyCredentials,
    reason: str,
    observed_symbols: Optional[List[str]] = None,
) -> Dict[str, Any]:
    now = iso_now()
    status = build_missing_credentials_status(credentials)
    status.update(
        {
            "last_run_ts": now,
            "generated_at": now,
            "credentials_status_one_of_PRESENT_MISSING_INVALID": credentials.status,
            "credentials_status": credentials.status,
            "fail_closed_reason": reason,
            "runtime_evidence_status": reason,
            "canary_blockers": [
                reason,
                "ISOLATED_MARGIN_EVIDENCE_MISSING",
                "LEVERAGE_CAP_EVIDENCE_MISSING",
                "CANARY_BLOCKED_BY_ACCOUNT_EVIDENCE",
            ],
        }
    )
    status.update(build_symbol_scope(observed_symbols=observed_symbols or []))
    return status


def build_success_status(
    *,
    credentials: ReadOnlyCredentials,
    evidence: Dict[str, Any],
) -> Dict[str, Any]:
    positions = list(evidence.get("positions") or [])
    observed_symbols = [str(position.get("symbol") or "") for position in positions]
    account_ts = evidence.get("account_fetch_ts") or ""
    positions_ts = evidence.get("positions_fetch_ts") or ""
    margin_evidence = evidence.get("margin_mode_evidence") or MISSING_EVIDENCE
    leverage_evidence = evidence.get("leverage_evidence") or MISSING_EVIDENCE
    blockers: List[str] = []
    if margin_evidence == MISSING_EVIDENCE:
        blockers.append("ISOLATED_MARGIN_EVIDENCE_MISSING")
    if leverage_evidence == MISSING_EVIDENCE:
        blockers.append("LEVERAGE_CAP_EVIDENCE_MISSING")
    trade_permission_status = str(
        evidence.get("trade_permission_status") or "TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY"
    )
    account_snapshot = evidence.get("account_snapshot") or {}
    margin_ratio = account_snapshot.get("maintenance_margin_ratio_pct")
    if trade_permission_status != "TRADE_PERMISSION_EVIDENCE_PRESENT_TRADING_CAPABLE":
        blockers.append("TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY")
    if blockers:
        blockers.append("CANARY_BLOCKED_BY_ACCOUNT_EVIDENCE")

    now = iso_now()
    status: Dict[str, Any] = {
        "worker_id": WORKER_ID,
        "generated_at": now,
        "last_run_ts": now,
        "last_successful_account_fetch_ts": account_ts,
        "last_successful_positions_fetch_ts": positions_ts,
        "credentials_status_one_of_PRESENT_MISSING_INVALID": credentials.status,
        "credentials_status": credentials.status,
        "account_state_one_of_FRESH_STALE_MISSING": "FRESH",
        "open_positions_count": len(positions),
        "open_positions_sample_anonymized": anonymized_position_sample(positions),
        "margin_mode_evidence_or_MISSING_EVIDENCE": margin_evidence,
        "leverage_evidence_or_MISSING_EVIDENCE": leverage_evidence,
        "maintenance_margin_ratio_pct": margin_ratio,
        "account_margin_ratio_status": "PRESENT" if margin_ratio is not None else "MISSING_EVIDENCE",
        "source_endpoint_versions": list(SOURCE_ENDPOINT_VERSIONS),
        "freshness_seconds": freshness_seconds_for(account_ts, positions_ts),
        "live_gate": LIVE_GATE_STATUS,
        "current_gate_state": LIVE_GATE_STATUS,
        "current_gate_state_must_equal_blocked_human_only": True,
        "gate_always_blocked_invariant": True,
        "live_blocked": True,
        "exchange_call_invariant": EXCHANGE_CALL_INVARIANT,
        "exchange_action_taken": False,
        "exchange_mutation_performed": False,
        "fail_closed": False,
        "fail_closed_reason": "",
        "runtime_evidence_status": "PRESENT",
        "missing_runtime_evidence": False,
        "trade_permission_status": trade_permission_status,
        "account_snapshot": account_snapshot,
        "positions": positions,
        "legacy_source_paths": list(LEGACY_SOURCE_PATHS),
        "canary_ready": False,
        "canary_blockers": sorted(set(blockers)),
    }
    status.update(build_symbol_scope(observed_symbols=observed_symbols))
    status.update(_paper_position_payload_status())
    return status


def write_status_payload(status: Dict[str, Any]) -> None:
    for path in (PUBLIC_STATUS_FILE, LOCAL_STATUS_FILE, WORKER_STATUS_FILE):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="run one read-only monitor cycle")
    parser.add_argument("--loop", action="store_true", help="run continuously")
    parser.add_argument("--interval", type=float, default=60.0, help="loop sleep interval in seconds")
    parser.add_argument("--readonly-only", action="store_true", default=True)
    return parser.parse_args(argv)


def run_once(
    args: argparse.Namespace,
    *,
    client: Any = None,
    credentials: Optional[ReadOnlyCredentials] = None,
    sleep_func: Any = time.sleep,
) -> Dict[str, Any]:
    credentials = credentials or ReadOnlyCredentials.from_env()
    if not credentials.is_present and client is None:
        status = build_missing_credentials_status(credentials)
        write_status_payload(status)
        return status

    try:
        active_client = client or BinanceFuturesReadOnlyClient(credentials=credentials)
        evidence = collect_account_position_evidence(client=active_client, sleep_func=sleep_func)
        status = build_success_status(credentials=credentials, evidence=evidence)
    except RateLimitError:
        status = build_exchange_error_status(credentials=credentials, reason="RATE_LIMITED")
    except ReadOnlyContractError:
        status = build_exchange_error_status(credentials=credentials, reason="READONLY_CONTRACT_FAILED")
    except ExchangeReadError:
        status = build_exchange_error_status(credentials=credentials, reason="EXCHANGE_READ_FAILED")
    write_status_payload(status)
    return status


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if not args.loop:
        args.once = True
    while True:
        status = run_once(args)
        if not args.loop:
            return 2 if status.get("fail_closed") else 0
        time.sleep(max(1.0, float(args.interval)))


if __name__ == "__main__":
    sys.exit(main())
