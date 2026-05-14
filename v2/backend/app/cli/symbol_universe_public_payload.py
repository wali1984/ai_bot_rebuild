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
    binance_confirmed, binance_sources = _union(worker_payloads, "binance_usdm_confirmed_symbols", "tradable_symbols")
    legacy_active = service.legacy_active_symbols()
    if not discovered:
        discovered = sorted({identity.canonical_symbol_id.upper() for identity in service.all_discovered_symbols()})
    if not dynamic_discovered:
        dynamic_discovered = list(discovered)
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
    source_paths = sorted(set(discovered_sources + dynamic_sources + observed_sources + training_sources + paper_sources + binance_sources))
    evidence_gaps = sorted(set(training_blockers + paper_blockers))
    if not binance_confirmed:
        evidence_gaps.append("missing_binance_usdm_confirmed_symbols")

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
        "requested_training_symbols": requested_training,
        "requested_paper_symbols": requested_paper,
        "rejected_training_symbols": rejected_training,
        "rejected_paper_symbols": rejected_paper,
        "symbol_selection_evidence": {
            "training_source_paths": training_sources,
            "paper_source_paths": paper_sources,
            "binance_confirmation_source_paths": binance_sources,
        },
        "symbol_universe_payload_evidence_gaps": sorted(set(evidence_gaps)),
        "binance_usdm_confirmed_symbols": binance_confirmed,
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
