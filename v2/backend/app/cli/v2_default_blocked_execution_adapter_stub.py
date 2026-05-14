"""V2 default blocked execution adapter stub — CLI worker.

This is the worker-layer refusal surface for execution actions, sitting
above the API-layer ``LiveBlockGuardMiddleware``
(``v2/backend/app/api/middleware/live_block_guard.py``). The worker:

  * instantiates :class:`DefaultBlockedExecutionAdapter`, whose mutation
    methods all raise :class:`BlockedGateNotApprovedError` with code
    ``BLOCKED_GATE_NOT_APPROVED`` before evaluating any argument;
  * reads the V2 Symbol Universe contract (or classifies it
    ``MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD`` and falls back to the
    service contract);
  * emits a single public status payload exposing only the adapter's
    own disabled state — never any exchange data.

Hard rules (asserted by tests):
  - The worker and service source contain no Binance, ccxt, or Redis
    import and no Redis writer call.
  - The worker and service source contain no literal exchange mutation
    method references.
  - The stub state is one of ``DISABLED`` or ``BLOCKED``, never
    ``ACTIVE``.
  - The live gate is permanently ``blocked_human_only``; no codepath
    here can change it.
  - The Symbol Universe contract is emitted on every payload; the
    25-symbol legacy active subset is exposed as
    ``legacy_active_symbols`` and is never the full universe.

Legacy baseline:
    claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/
    workers/v2_p2_default_blocked_execution_adapter_stub_LEGACY_BASELINE_ANALYSIS.md
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from v2.backend.app.services.default_blocked_execution_adapter.service import (
    ALLOWED_STUB_STATES,
    DefaultBlockedExecutionAdapter,
    ERROR_CODE,
    LIVE_GATE_STATUS,
    MUTATION_METHODS,
    STATE_BLOCKED,
    STATE_DISABLED,
)
from v2.backend.app.services.symbol_universe.service import (
    DYNAMIC_SYMBOL_SOURCES,
    LEGACY_ACTIVE_SYMBOLS_25,
    SYMBOL_SELECTION_SCORE_FACTORS,
    SymbolUniverseService,
)


WORKER_ID = "v2_default_blocked_execution_adapter"
SYMBOL_UNIVERSE_CONTRACT = "SYMBOL_UNIVERSE_CONTRACT_REQUIRED"
SYMBOL_UNIVERSE_SERVICE_PATH = "v2/backend/app/services/symbol_universe/service.py"
EXCHANGE_CALL_INVARIANT = "NO_REAL_EXCHANGE_CALL_FROM_DEFAULT_BLOCKED_ADAPTER"

# Audit-only legacy source paths. These are *not* read by this worker;
# they are emitted in the public payload so the GUI can link the
# refusal surface back to the legacy mutation surface it replaces.
LEGACY_EXECUTION_SOURCE_PATHS: List[str] = [
    "legacy_reference/trading/base_executor.py",
    "legacy_reference/trading/trader.py",
    "legacy_reference/trading/maker_execution.py",
    "legacy_reference/trading/depth_execution_gate.py",
    "legacy_reference/trading/execution_engine.py",
]

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

SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES: List[Path] = [
    V2_ROOT
    / "frontend"
    / "public"
    / "operator_runtime"
    / "symbol_universe"
    / "latest"
    / "symbol_universe_status.json",
    V2_ROOT
    / "frontend"
    / "public"
    / "symbol_universe"
    / "latest"
    / "symbol_universe_status.json",
]


REQUIRED_PUBLIC_PAYLOAD_FIELDS: Tuple[str, ...] = (
    "worker_id",
    "stub_state_one_of_DISABLED_OR_BLOCKED_NEVER_ACTIVE",
    "blocked_call_attempts_total",
    "blocked_call_breakdown_by_method",
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
    "symbol_universe_legacy_active_payload_matches_service",
    "symbol_universe_payload_evidence_gaps",
    "symbol_selection_evidence_present",
    "rejected_training_symbols",
    "rejected_paper_symbols",
)


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_ms() -> int:
    return int(time.time() * 1000)


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


def _load_symbol_universe_public_payload() -> Tuple[Dict[str, Any], Optional[str]]:
    for candidate in SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES:
        if candidate.exists():
            data = _read_json(candidate)
            try:
                rel_str = str(candidate.relative_to(REPO_ROOT))
            except ValueError:
                rel_str = str(candidate)
            return (data if isinstance(data, dict) else {}), rel_str
    return {}, None


def _selection_evidence_present(source_payload: Dict[str, Any]) -> bool:
    evidence = (
        source_payload.get("symbol_selection_evidence")
        or source_payload.get("selection_evidence_paths")
        or source_payload.get("operator_selected_symbol_scope")
    )
    if isinstance(evidence, dict):
        return bool(evidence)
    if isinstance(evidence, list):
        return bool(evidence)
    return bool(evidence)


def _sanitize_selected_symbols(
    requested: List[str],
    *,
    legacy_active: List[str],
    discovered: List[str],
    binance_confirmed: List[str],
    evidence_present: bool,
) -> Tuple[List[str], List[str], List[str]]:
    if not requested:
        return [], [], []

    allowed = set(legacy_active) & set(binance_confirmed)
    rejected_reasons: List[str] = []
    if not evidence_present:
        rejected_reasons.append("missing_symbol_selection_evidence")
    if not binance_confirmed:
        rejected_reasons.append("missing_binance_usdm_confirmation")
    if discovered and set(requested) >= set(discovered):
        rejected_reasons.append("requested_scope_matches_or_contains_all_discovered_symbols")

    accepted = sorted(set(requested) & allowed) if evidence_present else []
    if discovered and set(requested) >= set(discovered):
        accepted = []

    rejected = sorted(set(requested) - set(accepted))
    return accepted, rejected, rejected_reasons


def build_symbol_scope() -> Dict[str, Any]:
    public_payload, public_path = _load_symbol_universe_public_payload()
    source_payload: Dict[str, Any] = public_payload if public_payload else {}

    universe_service = SymbolUniverseService()
    canonical_legacy_active = universe_service.legacy_active_symbols()
    public_legacy_active = _as_symbol_list(source_payload.get("legacy_active_symbols"))
    legacy_payload_matches_service = (
        not public_legacy_active or public_legacy_active == canonical_legacy_active
    )
    evidence_gaps: List[str] = []
    if public_legacy_active and not legacy_payload_matches_service:
        evidence_gaps.append("public_payload_legacy_active_symbols_mismatch_ignored")

    discovered = _as_symbol_list(
        source_payload.get("discovered_symbols")
        or source_payload.get("symbols_discovered")
        or source_payload.get("all_discovered_symbols")
    )
    dynamic_discovered = _as_symbol_list(
        source_payload.get("dynamic_discovered_symbols")
        or source_payload.get("dynamic_symbols")
        or discovered
    )
    if not discovered and dynamic_discovered:
        discovered = list(dynamic_discovered)
    training_symbols = _as_symbol_list(source_payload.get("training_symbols"))
    paper_symbols = _as_symbol_list(source_payload.get("paper_symbols"))
    binance_confirmed = _as_symbol_list(
        source_payload.get("binance_usdm_confirmed_symbols")
        or source_payload.get("binance_usdm_tradable_symbols")
    )
    selection_evidence_present = _selection_evidence_present(source_payload)
    requested_training_symbols = _as_symbol_list(source_payload.get("training_symbols"))
    requested_paper_symbols = _as_symbol_list(source_payload.get("paper_symbols"))
    training_symbols, rejected_training_symbols, training_reasons = (
        _sanitize_selected_symbols(
            requested_training_symbols,
            legacy_active=canonical_legacy_active,
            discovered=discovered,
            binance_confirmed=binance_confirmed,
            evidence_present=selection_evidence_present,
        )
    )
    paper_symbols, rejected_paper_symbols, paper_reasons = _sanitize_selected_symbols(
        requested_paper_symbols,
        legacy_active=canonical_legacy_active,
        discovered=discovered,
        binance_confirmed=binance_confirmed,
        evidence_present=selection_evidence_present,
    )
    for reason in sorted(set(training_reasons + paper_reasons)):
        evidence_gaps.append(reason)

    live_blocked = _as_symbol_list(source_payload.get("live_blocked_symbols"))
    if not live_blocked:
        live_blocked = sorted(
            set(
                dynamic_discovered
                or discovered
                or canonical_legacy_active
            )
        )

    return {
        "symbol_universe_contract": SYMBOL_UNIVERSE_CONTRACT,
        "symbol_universe_source_path": public_path or SYMBOL_UNIVERSE_SERVICE_PATH,
        "symbol_universe_public_payload_status": (
            "PRESENT" if public_path else "MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD"
        ),
        "legacy_active_symbols": canonical_legacy_active,
        "symbol_universe_legacy_active_payload_matches_service": (
            legacy_payload_matches_service
        ),
        "symbol_universe_payload_legacy_active_symbols": public_legacy_active,
        "symbol_universe_payload_evidence_gaps": sorted(set(evidence_gaps)),
        "legacy_active_symbol_source": "legacy_config.py_SYMBOLS_current_25",
        "discovered_symbols": discovered,
        "dynamic_discovered_symbols": dynamic_discovered,
        "dynamic_symbol_sources": list(DYNAMIC_SYMBOL_SOURCES),
        "observed_symbols": [],
        "training_symbols": training_symbols,
        "paper_symbols": paper_symbols,
        "requested_training_symbols": requested_training_symbols,
        "requested_paper_symbols": requested_paper_symbols,
        "rejected_training_symbols": rejected_training_symbols,
        "rejected_paper_symbols": rejected_paper_symbols,
        "symbol_selection_evidence_present": selection_evidence_present,
        "live_symbols": [],
        "live_blocked_symbols": live_blocked,
        "binance_usdm_confirmed_symbols": binance_confirmed,
        "coinank_symbols_tradability": (
            "market_intelligence_only_until_binance_usdm_confirmed"
        ),
        "symbol_scope_policy": (
            "do_not_train_or_trade_all_discovered_symbols_automatically"
        ),
        "passive_monitor_all_discovered_symbols": True,
        "train_all_discovered_symbols": False,
        "trade_all_discovered_symbols": False,
        "live_symbol_policy": "none_live_blocked_human_only",
        "symbol_selection_score_factors": list(SYMBOL_SELECTION_SCORE_FACTORS),
    }


def _content_hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]


def build_status(
    *,
    adapter: DefaultBlockedExecutionAdapter,
    symbol_scope: Dict[str, Any],
    run_started_ts: str,
) -> Dict[str, Any]:
    snapshot = adapter.state_snapshot()
    status: Dict[str, Any] = {
        "worker_id": WORKER_ID,
        "last_run_ts": run_started_ts,
        "stub_state_one_of_DISABLED_OR_BLOCKED_NEVER_ACTIVE": snapshot[
            "stub_state_one_of_DISABLED_OR_BLOCKED_NEVER_ACTIVE"
        ],
        "allowed_stub_states": snapshot["allowed_stub_states"],
        "mutation_methods": snapshot["mutation_methods"],
        "blocked_call_attempts_total": snapshot["blocked_call_attempts_total"],
        "blocked_call_breakdown_by_method": snapshot[
            "blocked_call_breakdown_by_method"
        ],
        "live_gate": LIVE_GATE_STATUS,
        "current_gate_state": LIVE_GATE_STATUS,
        "current_gate_state_must_equal_blocked_human_only": True,
        "gate_always_blocked_invariant": True,
        "exchange_client_present": False,
        "exchange_action_taken": False,
        "exchange_call_invariant": EXCHANGE_CALL_INVARIANT,
        "error_code_on_call": ERROR_CODE,
        "fail_closed": True,
        "freshness_seconds": 0,
        "legacy_execution_source_paths": list(LEGACY_EXECUTION_SOURCE_PATHS),
        "live_block_guard_dependency": (
            "v2/backend/app/api/middleware/live_block_guard.py"
        ),
        "live_blocked": True,
        **symbol_scope,
    }
    status["content_hash"] = _content_hash(
        {k: v for k, v in status.items() if k != "last_run_ts"}
    )
    return status


def write_status(status: Dict[str, Any]) -> None:
    PUBLIC_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    WORKER_STATUS_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(status, indent=2, sort_keys=True, default=str)
    PUBLIC_STATUS_FILE.write_text(payload)
    LOCAL_STATUS_FILE.write_text(payload)
    WORKER_STATUS_FILE.write_text(payload)


def run_once(args: argparse.Namespace) -> Dict[str, Any]:
    run_started_ts = iso_now()
    adapter = DefaultBlockedExecutionAdapter()
    symbol_scope = build_symbol_scope()
    status = build_status(
        adapter=adapter,
        symbol_scope=symbol_scope,
        run_started_ts=run_started_ts,
    )
    if not args.no_write:
        write_status(status)
    return status


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=WORKER_ID)
    parser.add_argument(
        "--once",
        action="store_true",
        help="run a single iteration and exit",
    )
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="emit a single status snapshot",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="dry-run; do not write any payload to disk",
    )
    args = parser.parse_args(argv)
    if not args.once and not args.status_only:
        args.status_only = True
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    run_once(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
