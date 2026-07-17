from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from v2.backend.app.services.symbol_universe.service import (
    DYNAMIC_SYMBOL_SOURCES,
    LEGACY_ACTIVE_SYMBOLS_25,
    SYMBOL_SELECTION_SCORE_FACTORS,
    SymbolUniverseService,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
V2_ROOT = REPO_ROOT / "v2"
PUBLIC_DIR = V2_ROOT / "frontend" / "public" / "operator_runtime" / "symbol_universe" / "latest"
LOCAL_DIR = V2_ROOT / "runtime" / "symbol_universe" / "latest"
FINAL_DIR = REPO_ROOT / "claude_worklog" / "final_readiness" / "symbol_universe_public_payload" / "latest"
PAYLOAD_NAME = "symbol_universe_status.json"

LIVE_GATE_STATUS = "blocked_human_only"
SYMBOL_UNIVERSE_CONTRACT = "SYMBOL_UNIVERSE_CONTRACT_REQUIRED"
SYMBOL_UNIVERSE_SERVICE_PATH = "v2/backend/app/services/symbol_universe/service.py"
LEGACY_ACTIVE_SYMBOL_SOURCE = "legacy_config.py_SYMBOLS_current_25"
ACTIVE_PAPER_POSITION_SOURCE_PATHS = (
    Path("v2/frontend/public/operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json"),
    Path("v2/frontend/public/operator_runtime/v2_paper_trade_management/latest/paper_lifecycle_state.json"),
)


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _as_symbols(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        items: Iterable[Any] = [value]
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, Mapping)):
        items = value
    else:
        return []
    out: list[str] = []
    for raw in items:
        if isinstance(raw, Mapping):
            raw = raw.get("canonical_symbol_id") or raw.get("symbol") or raw.get("legacy_symbol")
        text = str(raw or "").strip().upper()
        if text:
            out.append(text)
    return sorted(set(out))


def _collect_payloads(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    base = root / "v2" / "frontend" / "public" / "operator_runtime"
    if not base.exists():
        return []
    payloads: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(base.glob("*/latest/*status.json")):
        if "symbol_universe/latest" in str(path):
            continue
        data = _read_json(path)
        if isinstance(data, dict):
            payloads.append((path, data))
    return payloads


def _union(payloads: list[tuple[Path, dict[str, Any]]], *keys: str) -> tuple[list[str], list[str]]:
    symbols: set[str] = set()
    sources: set[str] = set()
    for path, payload in payloads:
        before = set(symbols)
        for key in keys:
            symbols.update(_as_symbols(payload.get(key)))
        if symbols != before:
            sources.add(_rel(path, REPO_ROOT))
    return sorted(symbols), sorted(sources)


# Exchange-wide Binance USD-M TRADING list published by the dynamic symbol
# discovery loop (derived from /fapi/v1/exchangeInfo status == TRADING).
EXCHANGE_TRADABLE_AUTHORITY_KEY = "binance_usdm_tradable_symbols"
# Tradability is a point-in-time exchange fact; an authority snapshot older
# than this cannot prune (fail open to the sticky union rather than eject
# symbols on stale evidence).
EXCHANGE_TRADABLE_AUTHORITY_MAX_AGE_SECONDS = 24 * 3600
# Sanity floor: a full USD-M exchangeInfo TRADING list has hundreds of
# perpetuals. A dated payload carrying only a handful of symbols under this
# key is a scoped/broken list, not the exchange-wide truth — using it as the
# prune authority would collapse the whole universe.
EXCHANGE_TRADABLE_AUTHORITY_MIN_COUNT = 100


def _parse_generated_ts(payload: Mapping[str, Any]) -> dt.datetime | None:
    for field in ("generated_utc", "generated_at", "generated_est"):
        value = payload.get(field)
        if not isinstance(value, str) or not value:
            continue
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed
    return None


def _freshest_exchange_tradable(
    payloads: list[tuple[Path, dict[str, Any]]],
) -> dict[str, Any] | None:
    """Newest exchange-wide Binance USD-M TRADING set among worker payloads.

    Exchange tradability is a point-in-time fact: unioning confirmed lists
    across historical worker payloads makes tradability sticky forever, so a
    delisted/settled contract never leaves the adaptive universe (2026-07-16
    incident: IPUSDT kept re-entering via a stale signal-lineage confirmed
    list plus the trainer echoing its own resolved universe, while Binance
    REST klines showed 199 hours of zero-volume flat candles). Only a dated,
    exchange-wide ``binance_usdm_tradable_symbols`` list qualifies as prune
    authority; the newest fresh one wins.
    """
    best: dict[str, Any] | None = None
    best_ts: dt.datetime | None = None
    now = dt.datetime.now(dt.timezone.utc)
    for path, payload in payloads:
        symbols = _as_symbols(payload.get(EXCHANGE_TRADABLE_AUTHORITY_KEY))
        if len(symbols) < EXCHANGE_TRADABLE_AUTHORITY_MIN_COUNT:
            continue
        generated = _parse_generated_ts(payload)
        if generated is None:
            # Undated payloads cannot assert *current* tradability.
            continue
        age_seconds = (now - generated).total_seconds()
        if age_seconds > EXCHANGE_TRADABLE_AUTHORITY_MAX_AGE_SECONDS:
            continue
        if best_ts is None or generated > best_ts:
            best_ts = generated
            best = {
                "symbols": symbols,
                "symbol_count": len(symbols),
                "generated_at": generated.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "age_seconds": int(age_seconds),
                "source_path": _rel(path, REPO_ROOT),
                "authority_key": EXCHANGE_TRADABLE_AUTHORITY_KEY,
            }
    return best


def _selected_subset(
    requested: list[str],
    *,
    discovered: list[str],
    binance_confirmed: list[str],
    evidence_sources: list[str],
) -> tuple[list[str], list[str], list[str]]:
    blockers: list[str] = []
    if not requested:
        return [], [], blockers
    if not evidence_sources:
        blockers.append("missing_symbol_selection_evidence")
    if not binance_confirmed:
        blockers.append("missing_binance_usdm_confirmation")
    if discovered and set(requested) >= set(discovered):
        blockers.append("requested_scope_matches_or_contains_all_discovered_symbols")
    allowed = set(binance_confirmed) if binance_confirmed else set()
    accepted = sorted(set(requested) & allowed) if not blockers else []
    rejected = sorted(set(requested) - set(accepted))
    return accepted, rejected, blockers


def _active_paper_position_symbols(root: Path) -> tuple[list[str], list[str]]:
    symbols: set[str] = set()
    sources: set[str] = set()
    for relative_path in ACTIVE_PAPER_POSITION_SOURCE_PATHS:
        path = root / relative_path
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue
        rows: list[Any] = []
        for key in ("open_positions", "positions"):
            value = payload.get(key)
            if isinstance(value, list):
                rows.extend(value)
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            is_open = row.get("open_position") is True or str(row.get("position_state") or "").lower().endswith("_open")
            if not is_open and relative_path.name == "paper_lifecycle_state.json":
                # Lifecycle open_positions rows are already scoped to open positions.
                is_open = "open_positions" in payload and row in payload.get("open_positions", [])
            symbol = str(row.get("symbol") or "").strip().upper()
            if is_open and symbol:
                symbols.add(symbol)
                sources.add(_rel(path, REPO_ROOT))
    return sorted(symbols), sorted(sources)


def build_payload(root: Path = REPO_ROOT, *, generated_at: str | None = None) -> dict[str, Any]:
    generated_at = generated_at or iso_now()
    service = SymbolUniverseService()
    worker_payloads = _collect_payloads(root)
    discovered, discovered_sources = _union(
        worker_payloads,
        "discovered_symbols",
        "dynamic_discovered_symbols",
        "observed_symbols",
        "binance_usdm_confirmed_symbols",
    )
    dynamic_discovered, dynamic_sources = _union(worker_payloads, "dynamic_discovered_symbols", "discovered_symbols")
    observed, observed_sources = _union(worker_payloads, "observed_symbols", "symbol")
    requested_training, training_sources = _union(worker_payloads, "training_symbols")
    requested_paper, paper_sources = _union(worker_payloads, "paper_symbols")
    binance_confirmed, binance_sources = _union(
        worker_payloads,
        "binance_usdm_confirmed_symbols",
        "binance_usdm_tradable_symbols",
        "tradable_symbols",
    )
    # Adaptive universe hygiene: prune the sticky confirmed union down to the
    # freshest exchange-wide TRADING list so delisted/settled contracts leave
    # the universe instead of being re-confirmed forever by stale worker
    # payloads (and by workers echoing their own resolved universe back).
    tradable_authority = _freshest_exchange_tradable(worker_payloads)
    binance_delisted_pruned: list[str] = []
    if tradable_authority is not None:
        tradable_set = set(tradable_authority["symbols"])
        binance_delisted_pruned = sorted(set(binance_confirmed) - tradable_set)
        if binance_delisted_pruned:
            binance_confirmed = sorted(set(binance_confirmed) & tradable_set)
    active_paper_symbols, active_paper_sources = _active_paper_position_symbols(root)
    if active_paper_symbols:
        requested_training = sorted(set(requested_training) | set(active_paper_symbols))
        requested_paper = sorted(set(requested_paper) | set(active_paper_symbols))
        training_sources = sorted(set(training_sources) | set(active_paper_sources))
        paper_sources = sorted(set(paper_sources) | set(active_paper_sources))
    legacy_active = service.legacy_active_symbols()
    if not discovered:
        discovered = sorted({identity.canonical_symbol_id.upper() for identity in service.all_discovered_symbols()})
    if not dynamic_discovered:
        dynamic_discovered = list(discovered)
    if active_paper_symbols:
        discovered = sorted(set(discovered) | set(active_paper_symbols))
        observed = sorted(set(observed) | set(active_paper_symbols))
    training, rejected_training, training_blockers = _selected_subset(
        requested_training,
        discovered=discovered,
        binance_confirmed=binance_confirmed,
        evidence_sources=training_sources,
    )
    paper, rejected_paper, paper_blockers = _selected_subset(
        requested_paper,
        discovered=discovered,
        binance_confirmed=binance_confirmed,
        evidence_sources=paper_sources,
    )
    live_data, rejected_live_data, live_data_blockers = _selected_subset(
        active_paper_symbols,
        discovered=discovered,
        binance_confirmed=binance_confirmed,
        evidence_sources=active_paper_sources,
    )
    source_paths = sorted(set(discovered_sources + dynamic_sources + observed_sources + training_sources + paper_sources + binance_sources))
    evidence_gaps = sorted(set(training_blockers + paper_blockers + live_data_blockers))
    if not binance_confirmed:
        evidence_gaps.append("missing_binance_usdm_confirmed_symbols")
    if tradable_authority is None:
        evidence_gaps.append("binance_usdm_tradability_authority_missing_or_stale_confirmed_union_unpruned")

    return {
        "generated_at": generated_at,
        "source": "V2_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD",
        "source_paths": source_paths or [SYMBOL_UNIVERSE_SERVICE_PATH],
        "symbol_universe_contract": SYMBOL_UNIVERSE_CONTRACT,
        "symbol_universe_source_path": SYMBOL_UNIVERSE_SERVICE_PATH,
        "legacy_active_symbols": legacy_active,
        "legacy_active_symbol_source": LEGACY_ACTIVE_SYMBOL_SOURCE,
        "legacy_active_symbols_are_full_universe": False,
        "discovered_symbols": discovered,
        "dynamic_discovered_symbols": dynamic_discovered,
        "dynamic_symbol_sources": list(DYNAMIC_SYMBOL_SOURCES),
        "observed_symbols": observed,
        "training_symbols": training,
        "paper_symbols": paper,
        "live_data_symbols": live_data,
        "requested_training_symbols": requested_training,
        "requested_paper_symbols": requested_paper,
        "requested_live_data_symbols": active_paper_symbols,
        "rejected_training_symbols": rejected_training,
        "rejected_paper_symbols": rejected_paper,
        "rejected_live_data_symbols": rejected_live_data,
        "active_paper_position_symbols": active_paper_symbols,
        "active_paper_position_source_paths": active_paper_sources,
        "symbol_selection_evidence": {
            "training_source_paths": training_sources,
            "paper_source_paths": paper_sources,
            "live_data_source_paths": active_paper_sources,
            "binance_confirmation_source_paths": binance_sources,
        },
        "symbol_universe_payload_evidence_gaps": sorted(set(evidence_gaps)),
        "binance_usdm_confirmed_symbols": binance_confirmed,
        "binance_usdm_tradability_authority": (
            {key: value for key, value in tradable_authority.items() if key != "symbols"}
            if tradable_authority is not None
            else None
        ),
        "binance_usdm_delisted_pruned_symbols": binance_delisted_pruned,
        "coinank_symbols_directly_tradable": False,
        "coinank_symbols_tradability": "market_intelligence_only_until_binance_usdm_confirmed",
        "live_symbols": [],
        "live_blocked_symbols": sorted(set(binance_confirmed or discovered or legacy_active)),
        "live_gate": LIVE_GATE_STATUS,
        "live_symbol_policy": "none_live_blocked_human_only",
        "passive_monitor_all_discovered_symbols": True,
        "train_all_discovered_symbols": False,
        "trade_all_discovered_symbols": False,
        "symbol_scope_policy": "do_not_train_or_trade_all_discovered_symbols_automatically",
        "symbol_selection_score_factors": list(SYMBOL_SELECTION_SCORE_FACTORS),
    }


def write_payload(payload: Mapping[str, Any]) -> None:
    for directory in (PUBLIC_DIR, LOCAL_DIR, FINAL_DIR):
        _write_json(directory / PAYLOAD_NAME, payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish the V2 Symbol Universe public payload.")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    payload = build_payload()
    if args.write:
        write_payload(payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
