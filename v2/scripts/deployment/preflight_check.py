from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from v2.backend.app.services.symbol_universe.service import (
    DYNAMIC_SYMBOL_SOURCES,
    LEGACY_ACTIVE_SYMBOLS_25,
    SYMBOL_SELECTION_SCORE_FACTORS,
    SymbolUniverseService,
)


LIVE_GATE_STATUS = "blocked_human_only"
SYMBOL_UNIVERSE_CONTRACT = "SYMBOL_UNIVERSE_CONTRACT_REQUIRED"
SYMBOL_UNIVERSE_SERVICE_PATH = "v2/backend/app/services/symbol_universe/service.py"
WORKER_ID = "v2_p2_deployment_helpers"


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _as_symbol_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        items: Iterable[Any] = [value]
    elif isinstance(value, list):
        items = value
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


def _symbol_payload_candidates(root: Path) -> List[Path]:
    return [
        root / "v2/frontend/public/operator_runtime/symbol_universe/latest/symbol_universe_status.json",
        root / "v2/frontend/public/symbol_universe/latest/symbol_universe_status.json",
    ]


def _load_symbol_payload(root: Path) -> Tuple[Dict[str, Any], Optional[str]]:
    for candidate in _symbol_payload_candidates(root):
        if candidate.exists():
            data = _read_json(candidate)
            try:
                rel = str(candidate.relative_to(root))
            except ValueError:
                rel = str(candidate)
            return (data if isinstance(data, dict) else {}), rel
    return {}, None


def _selection_evidence_present(payload: Dict[str, Any]) -> bool:
    evidence = (
        payload.get("symbol_selection_evidence")
        or payload.get("selection_evidence_paths")
        or payload.get("operator_selected_symbol_scope")
    )
    if isinstance(evidence, (dict, list)):
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
    reasons: List[str] = []
    if not evidence_present:
        reasons.append("missing_symbol_selection_evidence")
    if not binance_confirmed:
        reasons.append("missing_binance_usdm_confirmation")
    if discovered and set(requested) >= set(discovered):
        reasons.append("requested_scope_matches_or_contains_all_discovered_symbols")

    allowed = set(legacy_active) & set(binance_confirmed)
    accepted = sorted(set(requested) & allowed) if evidence_present else []
    if discovered and set(requested) >= set(discovered):
        accepted = []
    rejected = sorted(set(requested) - set(accepted))
    return accepted, rejected, reasons


def build_symbol_scope(root: Path) -> Dict[str, Any]:
    payload, payload_path = _load_symbol_payload(root)
    service = SymbolUniverseService()
    canonical_legacy_active = service.legacy_active_symbols()
    public_legacy_active = _as_symbol_list(payload.get("legacy_active_symbols"))
    legacy_matches = not public_legacy_active or public_legacy_active == canonical_legacy_active

    evidence_gaps: List[str] = []
    if not payload_path:
        evidence_gaps.append("missing_symbol_universe_public_payload")
    if public_legacy_active and not legacy_matches:
        evidence_gaps.append("public_payload_legacy_active_symbols_mismatch_ignored")

    discovered = _as_symbol_list(
        payload.get("discovered_symbols")
        or payload.get("symbols_discovered")
        or payload.get("all_discovered_symbols")
    )
    dynamic_discovered = _as_symbol_list(
        payload.get("dynamic_discovered_symbols")
        or payload.get("dynamic_symbols")
        or discovered
    )
    if not discovered and dynamic_discovered:
        discovered = list(dynamic_discovered)
    binance_confirmed = _as_symbol_list(
        payload.get("binance_usdm_confirmed_symbols")
        or payload.get("binance_usdm_tradable_symbols")
    )
    evidence_present = _selection_evidence_present(payload)
    requested_training = _as_symbol_list(payload.get("training_symbols"))
    requested_paper = _as_symbol_list(payload.get("paper_symbols"))
    training_symbols, rejected_training, training_reasons = _sanitize_selected_symbols(
        requested_training,
        legacy_active=canonical_legacy_active,
        discovered=discovered,
        binance_confirmed=binance_confirmed,
        evidence_present=evidence_present,
    )
    paper_symbols, rejected_paper, paper_reasons = _sanitize_selected_symbols(
        requested_paper,
        legacy_active=canonical_legacy_active,
        discovered=discovered,
        binance_confirmed=binance_confirmed,
        evidence_present=evidence_present,
    )
    evidence_gaps.extend(training_reasons)
    evidence_gaps.extend(paper_reasons)
    live_blocked = _as_symbol_list(payload.get("live_blocked_symbols"))
    if not live_blocked:
        live_blocked = sorted(set(dynamic_discovered or discovered or canonical_legacy_active))

    return {
        "symbol_universe_contract": SYMBOL_UNIVERSE_CONTRACT,
        "symbol_universe_source_path": payload_path or SYMBOL_UNIVERSE_SERVICE_PATH,
        "symbol_universe_public_payload_status": "PRESENT" if payload_path else "MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD",
        "legacy_active_symbols": canonical_legacy_active,
        "legacy_active_symbol_source": "legacy_config.py_SYMBOLS_current_25",
        "symbol_universe_legacy_active_payload_matches_service": legacy_matches,
        "symbol_universe_payload_legacy_active_symbols": public_legacy_active,
        "symbol_universe_payload_evidence_gaps": sorted(set(evidence_gaps)),
        "discovered_symbols": discovered,
        "dynamic_discovered_symbols": dynamic_discovered,
        "dynamic_symbol_sources": list(DYNAMIC_SYMBOL_SOURCES),
        "observed_symbols": [],
        "training_symbols": training_symbols,
        "paper_symbols": paper_symbols,
        "requested_training_symbols": requested_training,
        "requested_paper_symbols": requested_paper,
        "rejected_training_symbols": rejected_training,
        "rejected_paper_symbols": rejected_paper,
        "symbol_selection_evidence_present": evidence_present,
        "live_symbols": [],
        "live_blocked_symbols": live_blocked,
        "binance_usdm_confirmed_symbols": binance_confirmed,
        "coinank_symbols_tradability": "market_intelligence_only_until_binance_usdm_confirmed",
        "symbol_scope_policy": "do_not_train_or_trade_all_discovered_symbols_automatically",
        "passive_monitor_all_discovered_symbols": True,
        "train_all_discovered_symbols": False,
        "trade_all_discovered_symbols": False,
        "live_symbol_policy": "none_live_blocked_human_only",
        "symbol_selection_score_factors": list(SYMBOL_SELECTION_SCORE_FACTORS),
    }


def run_preflight(
    *,
    root: Path,
    paper_only: bool,
    mode: str = "paper",
) -> Tuple[int, Dict[str, Any]]:
    root = root.resolve()
    approval = root / "claude_worklog/approvals/APPROVED_FINAL_LIVE_TINY_CANARY_ONLY.md"
    trim_approval = root / "claude_worklog/approvals/APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID_1777222885206_0_ONLY.md"
    python_bin = root / ".venv/bin/python3"
    state_path = root / "claude_worklog/final_readiness/v2_worker_porting_orchestrator/latest/worker_porting_state.json"

    blockers: List[str] = []
    if not paper_only:
        blockers.append("paper_only_flag_required")
    if mode != "paper":
        blockers.append("non_paper_mode_forbidden")
    if approval.exists():
        blockers.append("final_live_approval_token_present")
    if trim_approval.exists():
        blockers.append("redis_trim_approval_present")
    if not root.exists():
        blockers.append("workspace_missing")
    if not python_bin.exists():
        blockers.append("venv_python_missing")

    worker_state = _read_json(state_path) if state_path.exists() else {}
    if isinstance(worker_state, dict):
        gate = worker_state.get("live_gate") or worker_state.get("current_gate_state")
        if gate and gate != LIVE_GATE_STATUS:
            blockers.append(f"live_gate_not_blocked:{gate}")
        token = worker_state.get("final_approval_token")
        if token and token != "absent":
            blockers.append(f"final_approval_token_not_absent:{token}")

    symbol_scope = build_symbol_scope(root)
    payload: Dict[str, Any] = {
        "worker_id": WORKER_ID,
        "generated_at": iso_now(),
        "status": "PASS" if not blockers else "BLOCKED",
        "blockers": blockers,
        "paper_only": paper_only,
        "mode": mode,
        "live_gate": LIVE_GATE_STATUS,
        "live_enabled": False,
        "legacy_touched": False,
        "old_redis_write": False,
        "exchange_action": False,
        "leverage_or_margin_change": False,
        "approval_token_absent": not approval.exists(),
        "redis_trim_approval_absent": not trim_approval.exists(),
        "workspace": str(root),
        **symbol_scope,
    }
    return (0 if not blockers else 2), payload


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="v2_deployment_preflight_check")
    parser.add_argument("--paper-only", action="store_true")
    parser.add_argument("--mode", default="paper")
    parser.add_argument("--root", default=str(default_repo_root()))
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    code, payload = run_preflight(
        root=Path(args.root),
        paper_only=bool(args.paper_only),
        mode=str(args.mode),
    )
    text = json.dumps(payload, indent=2, sort_keys=True)
    print(text if args.json else f"V2_DEPLOYMENT_PREFLIGHT_{payload['status']}: {text}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
