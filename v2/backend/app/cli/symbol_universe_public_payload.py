from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from v2.backend.app.services.adaptive_symbol_selection import (
    select_adaptive_symbol_universe,
)
from v2.backend.app.services.adaptive_symbol_selection_runtime import (
    build_runtime_selection_evidence,
)
from v2.backend.app.services.symbol_universe.service import (
    DYNAMIC_SYMBOL_SOURCES,
    SYMBOL_SELECTION_SCORE_FACTORS,
    SymbolUniverseService,
)
from v2.backend.app.services.v2_symbol_runtime_universe import (
    PREFERRED_MAJOR_SYMBOLS,
    is_valid_runtime_symbol,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
V2_ROOT = REPO_ROOT / "v2"
PUBLIC_DIR = V2_ROOT / "frontend" / "public" / "operator_runtime" / "symbol_universe" / "latest"
LOCAL_DIR = V2_ROOT / "runtime" / "symbol_universe" / "latest"
FINAL_DIR = REPO_ROOT / "claude_worklog" / "final_readiness" / "symbol_universe_public_payload" / "latest"
PAYLOAD_NAME = "symbol_universe_status.json"
EDGE_ATTRIBUTION_PATH = (
    V2_ROOT
    / "frontend/public/operator_runtime/"
    "v2_dynamic_93_edge_recovery_and_signal_quality_burndown/latest/"
    "v2_dynamic_93_by_symbol_edge_attribution.json"
)

LIVE_GATE_STATUS = "blocked_human_only"
ADAPTIVE_SCOPE_ACTIVATION_ENV = "V2_ADAPTIVE_SYMBOL_SCOPES_ACTIVE"
ADAPTIVE_SCOPE_CONSUMERS_BOUND_ENV = "V2_ADAPTIVE_SYMBOL_SCOPE_CONSUMERS_BOUND"
ADAPTIVE_SCOPE_DEFAULT_BLOCKER = "default_off_requires_explicit_operator_activation"
ADAPTIVE_SCOPE_CONSUMER_BLOCKER = (
    "scope_aware_training_paper_and_position_management_consumers_not_bound"
)
SYMBOL_UNIVERSE_CONTRACT = "SYMBOL_UNIVERSE_CONTRACT_REQUIRED"
SYMBOL_UNIVERSE_SERVICE_PATH = "v2/backend/app/services/symbol_universe/service.py"
LEGACY_ACTIVE_SYMBOL_SOURCE = "legacy_config.py_SYMBOLS_current_25"
ACTIVE_PAPER_POSITION_SOURCE_PATHS = (
    Path("v2/frontend/public/operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json"),
    Path("v2/frontend/public/operator_runtime/v2_paper_trade_management/latest/paper_lifecycle_state.json"),
)


def iso_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


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


def _preferred_first(symbols: Iterable[str]) -> list[str]:
    normalized = {
        str(symbol or "").strip().upper()
        for symbol in symbols
        if is_valid_runtime_symbol(str(symbol or "").strip().upper())
    }
    return [
        *[symbol for symbol in PREFERRED_MAJOR_SYMBOLS if symbol in normalized],
        *sorted(normalized - set(PREFERRED_MAJOR_SYMBOLS)),
    ]


def _preferred_then_ranked(
    ranked: Iterable[str],
    candidates: Iterable[str],
) -> list[str]:
    allowed = {
        str(symbol or "").strip().upper()
        for symbol in candidates
        if is_valid_runtime_symbol(str(symbol or "").strip().upper())
    }
    out: list[str] = []
    seen: set[str] = set()
    for raw in (*PREFERRED_MAJOR_SYMBOLS, *tuple(ranked), *tuple(sorted(allowed))):
        symbol = str(raw or "").strip().upper()
        if symbol in allowed and symbol not in seen:
            seen.add(symbol)
            out.append(symbol)
    return out


def _previous_adaptive_state(payload: Any) -> Mapping[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    state = payload.get("adaptive_symbol_selection")
    return state if isinstance(state, Mapping) else None


def _runtime_evidence_summary(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {
            "status": "not_collected",
            "schema_version": None,
            "metrics": {},
            "source_contract": {},
        }
    rows = payload.get("evidence_rows")
    return {
        "status": "collected" if isinstance(rows, list) else "invalid",
        "schema_version": payload.get("schema_version"),
        "decision_time": payload.get("decision_time"),
        "metrics": payload.get("metrics") if isinstance(payload.get("metrics"), Mapping) else {},
        "source_contract": (
            payload.get("source_contract")
            if isinstance(payload.get("source_contract"), Mapping)
            else {}
        ),
        "places_real_order": False,
        "writes_redis": False,
    }


def _bind_evidence_to_current_candidates(
    evidence_rows: Iterable[Any],
    *,
    allowed_symbols: set[str],
) -> list[Any]:
    """Fail closed when evidence asserts an out-of-scope exchange identity.

    Runtime rows are normally collected from ``allowed_symbols`` already, but
    the public payload builder is also called directly by tests and startup
    tooling.  A row-level ``exchange_confirmed`` boolean must therefore never
    be able to override the publisher's current discovered + exchange-confirmed
    authority.
    """

    bound_rows: list[Any] = []
    for raw in evidence_rows:
        if not isinstance(raw, Mapping):
            bound_rows.append(raw)
            continue
        row = dict(raw)
        symbol = str(row.get("symbol") or "").strip().upper()
        if symbol not in allowed_symbols:
            row["exchange_confirmed"] = False
            existing = row.get("source_blockers")
            blockers = (
                [str(item) for item in existing if str(item)]
                if isinstance(existing, (list, tuple, set))
                else []
            )
            blockers.append(
                "symbol_not_in_current_exchange_confirmed_discovered_candidate_set"
            )
            row["source_blockers"] = sorted(set(blockers))
        bound_rows.append(row)
    return bound_rows


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


def build_payload(
    root: Path = REPO_ROOT,
    *,
    generated_at: str | None = None,
    adaptive_runtime_evidence: Mapping[str, Any] | None = None,
    previous_adaptive_state: Mapping[str, Any] | None = None,
    activate_adaptive_scopes: bool = False,
    adaptive_scope_consumers_bound: bool = False,
) -> dict[str, Any]:
    generated_at = generated_at or iso_now()
    if (
        type(activate_adaptive_scopes) is not bool
        or type(adaptive_scope_consumers_bound) is not bool
    ):
        raise ValueError("adaptive_scope_activation_flag_must_be_boolean")
    adaptive_scope_activation_active = (
        activate_adaptive_scopes and adaptive_scope_consumers_bound
    )
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
    # Preference is ordering-only: never add a major that failed discovery,
    # exchange confirmation, or the existing scope-evidence checks.  Keep the
    # authoritative legacy scopes consistent with adaptive and resolver output
    # while adaptive selection remains shadow/default-off.
    training = _preferred_first(training)
    paper = _preferred_first(paper)
    live_data = _preferred_first(live_data)
    confirmed_set = set(binance_confirmed)
    discovered_set = set(discovered)
    data_collection_candidates = {
        symbol
        for symbol in (confirmed_set & discovered_set)
        if confirmed_set and is_valid_runtime_symbol(symbol)
    }
    evidence_rows_raw = (
        adaptive_runtime_evidence.get("evidence_rows")
        if isinstance(adaptive_runtime_evidence, Mapping)
        else None
    )
    evidence_rows = (
        _bind_evidence_to_current_candidates(
            evidence_rows_raw,
            allowed_symbols=data_collection_candidates,
        )
        if isinstance(evidence_rows_raw, list)
        else []
    )
    selection_decision_time = (
        adaptive_runtime_evidence.get("decision_time")
        if isinstance(adaptive_runtime_evidence, Mapping)
        else generated_at
    ) or generated_at
    publisher_generated_clock = _parse_generated_ts({"generated_at": generated_at})
    selection_decision_clock = _parse_generated_ts(
        {"generated_at": selection_decision_time}
    )
    if isinstance(adaptive_runtime_evidence, Mapping) and (
        publisher_generated_clock is None
        or selection_decision_clock is None
        or publisher_generated_clock <= selection_decision_clock
    ):
        raise ValueError(
            "symbol_universe_generated_at_must_follow_adaptive_selection_decision_time"
        )
    adaptive_selection = select_adaptive_symbol_universe(
        evidence_rows,
        decision_time=selection_decision_time,
        previous_state=previous_adaptive_state,
    )
    data_collection_symbols = _preferred_then_ranked(
        adaptive_selection["training_ranked_symbols"],
        data_collection_candidates,
    )
    adaptive_training_symbols = list(adaptive_selection["training_selected_symbols"])
    adaptive_paper_new_entry_symbols = list(adaptive_selection["trading_selected_symbols"])
    active_position_management_symbols = _preferred_first(active_paper_symbols)
    if adaptive_scope_activation_active:
        # Open positions remain visible only in the management/live-data scope.
        # The existing downstream paper worker interprets ``paper_symbols`` as
        # new-entry capable, so management-only symbols must never be unioned
        # into either authoritative candidate field.
        training = list(adaptive_training_symbols)
        paper = list(adaptive_paper_new_entry_symbols)
        live_data = list(active_position_management_symbols)
        rejected_training = sorted(set(requested_training) - set(training))
        rejected_paper = sorted(set(requested_paper) - set(paper))
        rejected_live_data = sorted(set(active_paper_symbols) - set(live_data))
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
        "data_collection_symbols": data_collection_symbols,
        "training_symbols": training,
        "paper_symbols": paper,
        "live_data_symbols": live_data,
        "adaptive_training_eligible_symbols": adaptive_selection[
            "training_eligible_symbols"
        ],
        "adaptive_trading_eligible_symbols": adaptive_selection[
            "trading_eligible_symbols"
        ],
        "adaptive_training_selected_symbols": adaptive_training_symbols,
        "adaptive_paper_new_entry_symbols": adaptive_paper_new_entry_symbols,
        "active_position_management_symbols": active_position_management_symbols,
        "active_position_retention_grants_new_entry_eligibility": False,
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
            "adaptive_candidate_source": (
                "exchange_confirmed_discovered_symbols_not_worker_requested_scopes"
            ),
        },
        "adaptive_symbol_selection": adaptive_selection,
        "adaptive_runtime_evidence": _runtime_evidence_summary(
            adaptive_runtime_evidence
        ),
        "adaptive_clock_contract": {
            "selection_decision_time": adaptive_selection["decision_time"],
            "publisher_generated_at": generated_at,
            "selection_decision_precedes_publisher_generation": (
                selection_decision_clock is not None
                and publisher_generated_clock is not None
                and selection_decision_clock < publisher_generated_clock
            ),
            "decision_time_is_not_generated_at": (
                str(selection_decision_time) != str(generated_at)
            ),
        },
        "adaptive_scope_activation": {
            "requested": activate_adaptive_scopes,
            "scope_aware_consumers_bound": adaptive_scope_consumers_bound,
            "active": adaptive_scope_activation_active,
            "default_on": False,
            "activation_env": ADAPTIVE_SCOPE_ACTIVATION_ENV,
            "scope_aware_consumers_bound_env": ADAPTIVE_SCOPE_CONSUMERS_BOUND_ENV,
            "activation_blocked_reason": (
                None
                if adaptive_scope_activation_active
                else (
                    ADAPTIVE_SCOPE_CONSUMER_BLOCKER
                    if activate_adaptive_scopes
                    else ADAPTIVE_SCOPE_DEFAULT_BLOCKER
                )
            ),
            "authoritative_training_source": (
                "adaptive_training_selected_only"
                if adaptive_scope_activation_active
                else "legacy_requested_scope_evidence_unchanged"
            ),
            "authoritative_paper_source": (
                "adaptive_trading_selected_only"
                if adaptive_scope_activation_active
                else "legacy_requested_scope_evidence_unchanged"
            ),
            "paper_new_entry_symbols": adaptive_paper_new_entry_symbols,
            "retained_open_position_symbols": active_position_management_symbols,
            "retained_open_positions_are_new_entry_eligible": False,
        },
        "adaptive_rankings_are_opportunity_and_feasibility_candidates_not_forecasts": True,
        "adaptive_guaranteed_return_claim": False,
        "adaptive_guaranteed_1000x_claim": False,
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


def collect_runtime_adaptive_evidence(symbols: list[str]) -> dict[str, Any]:
    """Collect bounded local evidence; failure returns an empty fail-closed set."""

    try:
        import redis

        reader = redis.Redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=False,
            socket_connect_timeout=1.0,
            socket_timeout=2.0,
        )
        edge_payload = _read_json(EDGE_ATTRIBUTION_PATH)
        return build_runtime_selection_evidence(
            reader,
            symbols,
            edge_payload=edge_payload if isinstance(edge_payload, Mapping) else None,
        )
    except Exception as exc:
        # The public publisher must remain available even when local evidence is
        # unavailable.  Empty rows are intentional: selector admission then
        # fails closed and the default-off legacy scopes remain unchanged.
        return {
            "schema_version": "v2_adaptive_symbol_selection_runtime_evidence_v1",
            "decision_time": iso_now(),
            "evidence_rows": [],
            "metrics": {
                "requested_symbol_count": len(symbols),
                "evidence_row_count": 0,
                "collection_error": type(exc).__name__,
            },
            "source_contract": {
                "status": "collection_failed_fail_closed",
            },
            "places_real_order": False,
            "writes_redis": False,
            "selection_is_execution_authorization": False,
        }


def _activation_from_env() -> bool:
    return os.environ.get(ADAPTIVE_SCOPE_ACTIVATION_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _scope_aware_consumers_bound_from_env() -> bool:
    return os.environ.get(ADAPTIVE_SCOPE_CONSUMERS_BOUND_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish the V2 Symbol Universe public payload.")
    parser.add_argument("--write", action="store_true")
    parser.add_argument(
        "--activate-adaptive-scopes",
        action="store_true",
        help=(
            "Explicitly replace authoritative training/paper scopes with the "
            "strict adaptive selections. Default is OFF."
        ),
    )
    parser.add_argument(
        "--confirm-scope-aware-consumers-bound",
        action="store_true",
        help=(
            "Second explicit activation guard: confirm training, paper-entry, "
            "and open-position management consumers use their distinct scopes."
        ),
    )
    args = parser.parse_args(argv)
    activation_requested = args.activate_adaptive_scopes or _activation_from_env()
    scope_aware_consumers_bound = (
        args.confirm_scope_aware_consumers_bound
        or _scope_aware_consumers_bound_from_env()
    )
    previous_payload = _read_json(PUBLIC_DIR / PAYLOAD_NAME)
    previous_state = _previous_adaptive_state(previous_payload)
    # First pass resolves exchange-confirmed discovery candidates only.  It
    # does not consume worker-requested training/paper scopes as rank evidence.
    base_payload = build_payload(
        generated_at=iso_now(),
        previous_adaptive_state=previous_state,
        activate_adaptive_scopes=False,
        adaptive_scope_consumers_bound=False,
    )
    runtime_evidence = collect_runtime_adaptive_evidence(
        list(base_payload["data_collection_symbols"])
    )
    payload = build_payload(
        generated_at=iso_now(),
        adaptive_runtime_evidence=runtime_evidence,
        previous_adaptive_state=previous_state,
        activate_adaptive_scopes=activation_requested,
        adaptive_scope_consumers_bound=scope_aware_consumers_bound,
    )
    if args.write:
        write_payload(payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
