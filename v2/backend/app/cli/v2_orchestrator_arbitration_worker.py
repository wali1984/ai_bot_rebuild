"""V2 orchestrator arbitration worker (PaperOnly CLI).

Standalone CLI that exercises the
``v2.backend.app.services.orchestrator_arbitration`` package and writes a
public operator-runtime status payload at::

  v2/frontend/public/operator_runtime/v2_orchestrator_arbitration/latest/
    v2_orchestrator_arbitration_status.json

Hard invariants:
  - ``live_gate == "blocked_human_only"``
  - ``live_symbols == []``
  - ``approves_live is False``
  - No Redis client imported, no exchange SDK imported, no network IO.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from v2.backend.app.services.orchestrator_arbitration import (
    DeconflictResult,
    OrchestratorArbitrationService,
    Proposal,
    StreamRouter,
    V2Signal,
    deconflict_signals,
    validate_signal,
)
from v2.backend.app.services.orchestrator_arbitration.proposal import (
    DEFAULT_MAX_AGE_SECONDS,
)
from v2.backend.app.services.orchestrator_arbitration.service import (
    ArbitrationResult,
    SERVICE_ID,
)


WORKER_ID = "v2_orchestrator_arbitration"
REPO_ROOT = Path(__file__).resolve().parents[4]
PUBLIC_RUNTIME_DIR = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "operator_runtime"
    / WORKER_ID
    / "latest"
)
PUBLIC_STATUS_FILE = PUBLIC_RUNTIME_DIR / f"{WORKER_ID}_status.json"


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _proposal_from_dict(payload: Mapping[str, Any]) -> Optional[Proposal]:
    try:
        return Proposal(
            proposal_id=str(payload["proposal_id"]),
            symbol=str(payload["symbol"]).upper(),
            side=str(payload["side"]).lower(),
            confidence_calibrated=float(payload["confidence_calibrated"]),
            expected_move_after_cost_bps=float(
                payload["expected_move_after_cost_bps"]
            ),
            generated_utc=str(payload["generated_utc"]),
            source=str(payload["source"]),
            freshness_seconds=float(payload["freshness_seconds"]),
            model_version=str(payload["model_version"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _signal_from_dict(payload: Mapping[str, Any]) -> Optional[V2Signal]:
    try:
        return validate_signal(dict(payload))
    except ValueError:
        return None


def _load_inputs_file(
    path: Optional[Path],
) -> Dict[str, List[Mapping[str, Any]]]:
    if path is None:
        return {"proposals": [], "signals": []}
    if not path.exists():
        return {"proposals": [], "signals": []}
    blob = _read_json(path)
    if not isinstance(blob, dict):
        return {"proposals": [], "signals": []}
    proposals_raw = blob.get("proposals") or []
    signals_raw = blob.get("signals") or []
    if not isinstance(proposals_raw, list):
        proposals_raw = []
    if not isinstance(signals_raw, list):
        signals_raw = []
    return {
        "proposals": [p for p in proposals_raw if isinstance(p, dict)],
        "signals": [s for s in signals_raw if isinstance(s, dict)],
    }


def run_once(args: argparse.Namespace) -> Dict[str, Any]:
    run_ts = iso_now()
    max_age = max(1, int(getattr(args, "max_age_seconds", DEFAULT_MAX_AGE_SECONDS)))
    inputs_path = (
        Path(args.inputs_file) if getattr(args, "inputs_file", None) else None
    )
    inputs = _load_inputs_file(inputs_path)

    service = OrchestratorArbitrationService(
        max_age_seconds=max_age,
        stream_router=StreamRouter(),
    )

    proposals: List[Proposal] = []
    for raw in inputs["proposals"]:
        proposal = _proposal_from_dict(raw)
        if proposal is not None:
            proposals.append(proposal)

    signals: List[V2Signal] = []
    for raw in inputs["signals"]:
        signal = _signal_from_dict(raw)
        if signal is not None:
            signals.append(signal)

    arbitration_result: ArbitrationResult = service.arbitrate(proposals)
    deconflict_result: DeconflictResult = deconflict_signals(signals)

    status = service.current_paper_only_status(
        last_arbitration=arbitration_result,
        last_deconflict=deconflict_result,
    )
    status["worker_id"] = WORKER_ID
    status["last_run_ts"] = run_ts
    status["inputs_source_path"] = str(inputs_path) if inputs_path else ""
    status["inputs_proposal_count"] = len(proposals)
    status["inputs_signal_count"] = len(signals)
    status["service_id"] = SERVICE_ID
    status["exchange_action_taken"] = False
    status["network_io_performed"] = False
    status["redis_client_imported"] = False
    if bool(getattr(args, "write_evidence", False)) and not bool(
        getattr(args, "no_write", False)
    ):
        write_status(status)
    return status


def write_status(status: Mapping[str, Any]) -> None:
    PUBLIC_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    body = json.dumps(status, indent=2, sort_keys=True, default=str)
    PUBLIC_STATUS_FILE.write_text(body)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=WORKER_ID)
    parser.add_argument(
        "--inputs-file",
        default=None,
        help=(
            "Optional path to a JSON file containing { 'proposals': [...], "
            "'signals': [...] }. Omitting it yields an empty arbitration "
            "result and a MISSING_EVIDENCE_CANNOT_COMPARE deconflict reason."
        ),
    )
    parser.add_argument(
        "--max-age-seconds",
        type=int,
        default=DEFAULT_MAX_AGE_SECONDS,
        help="Stale boundary (seconds); proposals older than this score -inf.",
    )
    parser.add_argument(
        "--write-evidence",
        action="store_true",
        help="Write public operator_runtime status JSON.",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Disable writing the public payload even if --write-evidence is set.",
    )
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    if not args.once:
        args.once = True
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    status = run_once(args)
    if not status.get("live_blocked", True):
        return 2
    if status.get("approves_live"):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
