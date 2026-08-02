"""Retrain the paper serving checkpoint and (optionally) activate it.

This is the missing orchestrator for the serving-model lane.  The individual
stages already existed as library functions but nothing chained them, so the
paper serving model stayed frozen at whatever generation was last activated by
hand.  The chain is:

    1. TRAIN     ``train_serving_checkpoint_v2`` fits ``serving_model_v3`` on the
                 PIT-safe, purged, chronologically split serving dataset.  The
                 trainer itself refuses to emit a checkpoint whose validation
                 partition has a zero directional rate, a single-action
                 collapse, non-finite outputs, or a zero
                 ``selected_directional_positive_edge_rate``.
    2. SMOKE     ``evaluate_current_universe`` scores the frozen checkpoint over
                 the current eligible universe without publishing a prediction
                 or an intent, and reports ``activation_eligible``.
    3. GATE      the smoke result must be activation-eligible AND show a
                 positive directional net-edge rate.  This module never
                 overrides the gate; it only reports it.
    4. REGISTER  ``register_candidate`` publishes the candidate bundle.
    5. ACTIVATE  ``activate`` advances the paper registry generation under a
                 compare-and-set, recording a rollback pointer and receipt.
                 ``activate`` independently re-checks the activation reasons, so
                 a checkpoint that fails the gate cannot be activated even if
                 this module were wrong.

Cohort binding: the serving runtime rejects every prediction whose checkpoint is
not the one named by the governed economic cohort records
(``COHORT_CHECKPOINT_MISMATCH``).  Registry activation alone does NOT rebind
those records, so activating an unbound checkpoint silently drops publication to
zero.  The gate therefore refuses to activate a checkpoint the cohort does not
name; rebinding the cohort is a governed operator step, not something this
module mints.

Safety: paper lane only.  Nothing here places, cancels or modifies an exchange
order, and no stage runs unless explicitly requested -- the default invocation
trains and reports without mutating the registry at all.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    REQUIRED_DECISION_TIMEFRAMES,
)
from v2.backend.app.services.prediction_serving.checkpoint_registry import (
    activate,
    read_active,
    register_candidate,
)
from v2.backend.app.services.prediction_serving.serving_activation_v2 import (
    evaluate_current_universe,
)
from v2.backend.app.services.prediction_serving.serving_checkpoint_trainer_v2 import (
    train_serving_checkpoint_v2,
)

SCHEMA_VERSION = "serving_checkpoint_retrain_and_activate_v1"
PAPER_LANE = "paper"
ECONOMIC_COHORT_KEY = "v2:paper:economic_evaluation_cohort"
LEGACY_COHORT_KEY = "v2:paper:provisional_cohort_activation"
DEFAULT_EVIDENCE_ROOT = Path("/home/wali/ai_bot_local_data/gen5_snapshot_backfill_v1/evidence")
DEFAULT_DATASET_PATH = DEFAULT_EVIDENCE_ROOT / "serving_compatible_dataset_gen5.json"
DEFAULT_MANIFEST_PATH = DEFAULT_EVIDENCE_ROOT / "serving_compatible_dataset_manifest_gen5.json"
DEFAULT_OUTPUT_DIR = Path(".local_models/serving_checkpoints_v2")

# The eight proofs ``checkpoint_registry`` requires before an activation is
# allowed.  Mirrored here only so the report can name the blocking proof; the
# registry remains the authority.
REQUIRED_SMOKE_PROOFS = (
    "checkpoint_hash_valid",
    "manifest_hash_valid",
    "feature_abi_valid",
    "calibration_valid",
    "train_serve_parity_valid",
    "shadow_prediction_valid",
    "no_live_authority",
    "rollback_ready",
)


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve_symbols(client: Any, explicit: Sequence[str] | None) -> list[str]:
    if explicit:
        return [symbol.strip().upper() for symbol in explicit if symbol.strip()]
    from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

    return [str(symbol).upper() for symbol in resolve_symbols()]


def cohort_binding_reasons(cohorts: dict[str, Any], checkpoint_id: str) -> list[str]:
    """Block activation unless the governed cohort records name this checkpoint.

    The serving runtime rejects every prediction under a checkpoint the cohort
    does not name, so activating without a rebind takes publication to zero.
    """
    reasons: list[str] = []
    for label, key in (("ECONOMIC", ECONOMIC_COHORT_KEY), ("LEGACY", LEGACY_COHORT_KEY)):
        record = cohorts.get(key)
        if not isinstance(record, dict):
            reasons.append(f"{label}_COHORT_RECORD_MISSING")
            continue
        if str(record.get("checkpoint_id") or "") != checkpoint_id:
            reasons.append(f"{label}_COHORT_DOES_NOT_BIND_CHECKPOINT")
    return reasons


def _read_cohorts(client: Any) -> dict[str, Any]:
    cohorts: dict[str, Any] = {}
    for key in (ECONOMIC_COHORT_KEY, LEGACY_COHORT_KEY):
        raw = client.get(key)
        try:
            cohorts[key] = json.loads(raw) if raw else None
        except (TypeError, ValueError):
            cohorts[key] = None
    return cohorts


def _gate_reasons(smoke: dict[str, Any]) -> list[str]:
    """Name every proof that blocks activation, for the operator report."""
    reasons = [
        f"SMOKE_{proof.upper()}_NOT_PROVEN"
        for proof in REQUIRED_SMOKE_PROOFS
        if smoke.get(proof) is not True
    ]
    try:
        positive_edge_rate = float(smoke.get("serving_smoke_positive_directional_edge_rate"))
    except (TypeError, ValueError):
        positive_edge_rate = 0.0
    if positive_edge_rate <= 0.0:
        reasons.append("SMOKE_POSITIVE_DIRECTIONAL_EDGE_RATE_NOT_POSITIVE")
    if smoke.get("directional_net_edge_model_valid") is not True:
        reasons.append("SMOKE_DIRECTIONAL_NET_EDGE_MODEL_INVALID")
    return sorted(set(reasons))


def run_once(
    *,
    client: Any,
    dataset_path: Path,
    manifest_path: Path,
    output_dir: Path,
    symbols: Sequence[str],
    timeframes: Sequence[str],
    register: bool,
    do_activate: bool,
    activated_by: str,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": _utc_now(),
        "lane": PAPER_LANE,
        "dataset_path": str(dataset_path),
        "manifest_path": str(manifest_path),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
        "live_gate": "blocked_human_only",
        "registered": False,
        "activated": False,
    }

    active_before = read_active(client, lane=PAPER_LANE)
    report["active_generation_before"] = (
        int(active_before.get("registry_generation", 0)) if active_before else 0
    )
    report["active_checkpoint_id_before"] = (
        active_before.get("checkpoint_id") if active_before else None
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    bundle, meta, weight_path = train_serving_checkpoint_v2(
        dataset_path=dataset_path,
        manifest_path=manifest_path,
        output_dir=output_dir,
    )
    report["stage_train"] = {
        "checkpoint_id": bundle.checkpoint_id,
        "model_architecture": bundle.model_architecture,
        "weight_file_path": str(weight_path),
        "training_metrics": meta.get("training_metrics"),
        "checkpoint_classification": meta.get("checkpoint_classification"),
    }

    manifest = json.loads(manifest_path.read_text())
    smoke = evaluate_current_universe(
        client,
        bundle=bundle,
        manifest=manifest,
        symbols=symbols,
        timeframes=timeframes,
    )
    report["stage_smoke"] = smoke

    gate_reasons = _gate_reasons(smoke)
    cohort_reasons = cohort_binding_reasons(_read_cohorts(client), bundle.checkpoint_id)
    report["cohort_binding_reasons"] = cohort_reasons
    gate_reasons = sorted(set(gate_reasons) | set(cohort_reasons))
    report["gate_reasons"] = gate_reasons
    report["gate_passed"] = not gate_reasons

    if not gate_reasons and register:
        report["stage_register"] = register_candidate(client, bundle, lane=PAPER_LANE)
        report["registered"] = True

    if not gate_reasons and do_activate:
        receipt = activate(
            client,
            bundle,
            lane=PAPER_LANE,
            activated_by=activated_by,
            activation_reason="RETRAINED_SERVING_CHECKPOINT_PASSED_CURRENT_UNIVERSE_SMOKE",
            serving_smoke_result=smoke,
            expected_generation=report["active_generation_before"],
        )
        report["activated"] = True
        report["stage_activate"] = {
            "registry_generation": getattr(receipt, "registry_generation", None),
            "previous_generation": getattr(receipt, "previous_generation", None),
            "checkpoint_id": bundle.checkpoint_id,
        }

    active_after = read_active(client, lane=PAPER_LANE)
    report["active_generation_after"] = (
        int(active_after.get("registry_generation", 0)) if active_after else 0
    )
    report["active_checkpoint_id_after"] = (
        active_after.get("checkpoint_id") if active_after else None
    )
    if not gate_reasons:
        report["status"] = "ACTIVATED" if report["activated"] else "GATE_PASSED_NO_MUTATION_REQUESTED"
    else:
        report["status"] = "BLOCKED_GATE_NOT_PASSED"
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-path", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--manifest-path", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--redis-url", default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    )
    parser.add_argument("--symbol", action="append", dest="symbols")
    parser.add_argument(
        "--timeframe", action="append", dest="timeframes", choices=list(REQUIRED_DECISION_TIMEFRAMES)
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help="publish the trained bundle as the paper candidate (no activation)",
    )
    parser.add_argument(
        "--activate",
        action="store_true",
        help="advance the paper serving generation when the smoke gate passes",
    )
    parser.add_argument("--activated-by", default="v2_serving_checkpoint_retrain_and_activate")
    parser.add_argument("--report-path", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    import redis

    client = redis.Redis.from_url(
        arguments.redis_url, decode_responses=True, socket_connect_timeout=3
    )
    symbols = _resolve_symbols(client, arguments.symbols)
    if not symbols:
        print(json.dumps({"status": "BLOCKED", "reason": "NO_ELIGIBLE_SYMBOLS"}), flush=True)
        return 2
    timeframes = list(arguments.timeframes or REQUIRED_DECISION_TIMEFRAMES)

    report = run_once(
        client=client,
        dataset_path=arguments.dataset_path,
        manifest_path=arguments.manifest_path,
        output_dir=arguments.output_dir,
        symbols=symbols,
        timeframes=timeframes,
        register=arguments.register or arguments.activate,
        do_activate=arguments.activate,
        activated_by=arguments.activated_by,
    )
    if arguments.report_path:
        arguments.report_path.parent.mkdir(parents=True, exist_ok=True)
        arguments.report_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str))
    print(json.dumps(report, indent=2, sort_keys=True, default=str), flush=True)
    return 0 if report["status"] != "BLOCKED_GATE_NOT_PASSED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
