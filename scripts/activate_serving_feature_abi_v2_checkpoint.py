#!/usr/bin/env python3
"""Governed, paper-only activation for a qualified ServingFeatureABIV2 bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli.v2_paper_provisional_prediction_publisher import (  # noqa: E402
    COHORT_ACTIVATION_KEY,
    read_json_key,
    redis_client,
)
from v2.backend.app.services.prediction_serving.checkpoint_registry import (  # noqa: E402
    activate,
    read_active,
    register_candidate,
    rollback,
)
from v2.backend.app.services.prediction_serving.serving_activation_v2 import (  # noqa: E402
    load_checkpoint_bundle,
)

ECONOMIC_COHORT_KEY = "v2:paper:economic_evaluation_cohort"
MINIMUM_NATURAL_DIRECTIONAL_CLOSES = 5


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bundle",
        type=Path,
        default=REPO_ROOT
        / "goal_state/PERMANENT_SYSTEM_RECOVERY/serving_checkpoint_bundle_v2.json",
    )
    parser.add_argument(
        "--parity-report",
        type=Path,
        default=REPO_ROOT
        / "goal_state/PERMANENT_SYSTEM_RECOVERY/train_serve_feature_parity_report.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT
        / "goal_state/PERMANENT_SYSTEM_RECOVERY/governed_activation_receipt_v2.json",
    )
    parser.add_argument("--redis-url", default="redis://127.0.0.1:6379/0")
    args = parser.parse_args()

    client = redis_client(args.redis_url)
    bundle = load_checkpoint_bundle(args.bundle)
    smoke = json.loads(args.parity_report.read_text())
    if smoke.get("checkpoint_id") != bundle.checkpoint_id:
        raise ValueError("PARITY_REPORT_CHECKPOINT_MISMATCH")
    if smoke.get("activation_eligible") is not True:
        raise ValueError("PARITY_REPORT_NOT_ACTIVATION_ELIGIBLE")

    margin = read_json_key(client, "v2:paper:account_margin_status")
    if not isinstance(margin, dict) or margin.get("invariant_holds") is not True:
        raise ValueError("PAPER_ACCOUNTING_INVARIANT_NOT_PROVEN")
    if int(margin.get("open_position_count") or 0) != 0:
        raise ValueError("ACTIVATION_REQUIRES_FLAT_PAPER_BOOK")
    initial_equity = float(margin["equity_usd"])

    previous = read_active(client, lane="paper")
    previous_generation = int((previous or {}).get("registry_generation") or 0)
    register_candidate(client, bundle, lane="paper")
    receipt = activate(
        client,
        bundle,
        lane="paper",
        activated_by="codex_permanent_system_recovery",
        activation_reason="SERVING_FEATURE_ABI_V2_CURRENT_UNIVERSE_PARITY_PASS",
        serving_smoke_result=smoke,
        expected_generation=previous_generation,
    )
    activated_at = receipt.activated_at
    cohort_material = {
        "checkpoint_generation": receipt.registry_generation,
        "checkpoint_id": bundle.checkpoint_id,
        "activated_at": activated_at,
        "initial_equity_usd": initial_equity,
    }
    cohort_id = "paper_serving_abi_v2:" + _canonical_sha256(cohort_material)[:24]
    economic_cohort = {
        "schema_version": "paper_economic_evaluation_cohort_v2",
        "cohort_id": cohort_id,
        "checkpoint_generation": receipt.registry_generation,
        "checkpoint_id": bundle.checkpoint_id,
        "checkpoint_bundle_sha256": bundle.content_sha256(),
        "feature_abi_sha256": bundle.feature_abi_sha256,
        "window_type": "CHECKPOINT_GENERATION_NATURAL_DIRECTIONAL_CLOSES",
        "window_size": MINIMUM_NATURAL_DIRECTIONAL_CLOSES,
        "minimum_natural_directional_closes": MINIMUM_NATURAL_DIRECTIONAL_CLOSES,
        "cost_basis": "DECISION_TIME_EXACT_ROUND_TRIP_COST_PLUS_REALIZED_EXECUTION",
        "eligibility_rules": [
            "natural_directional_canonical_prediction",
            "standard_orchestrator_and_canonical_risk_allow",
            "standard_paper_fill_and_reduce_only_close",
            "same_checkpoint_generation_and_cohort_id",
            "exclude_engineering_canary_and_replay",
            "complete_cost_and_lineage_evidence",
        ],
        "g11_g13_g14_same_window_required": True,
        "activated_at": activated_at,
        "initial_equity_usd": initial_equity,
        "paper_only": True,
        "live_eligible": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    legacy_cohort = {
        "schema_version": "paper_provisional_cohort_activation_v2",
        "paper_strategy_cohort_id": cohort_id,
        "checkpoint_id": bundle.checkpoint_id,
        "paper_cohort_activation_utc": activated_at,
        "paper_cohort_initial_equity_usd": initial_equity,
        "manifest_id": bundle.training_manifest_id,
        "feature_abi_sha256": bundle.feature_abi_sha256,
        "checkpoint_generation": receipt.registry_generation,
        "economic_evaluation_cohort_id": cohort_id,
        "paper_only": True,
        "live_eligible": False,
        "routes_to_live": False,
        "places_real_order": False,
    }
    try:
        pipe = client.pipeline()
        pipe.multi()
        pipe.set(ECONOMIC_COHORT_KEY, json.dumps(economic_cohort, sort_keys=True))
        pipe.set(COHORT_ACTIVATION_KEY, json.dumps(legacy_cohort, sort_keys=True))
        results = pipe.execute()
        if results != [True, True]:
            raise RuntimeError(f"COHORT_ATOMIC_WRITE_NOT_ACKNOWLEDGED:{results!r}")
    except Exception:
        rollback(
            client,
            lane="paper",
            rolled_back_by="codex_permanent_system_recovery",
            reason="COHORT_BINDING_FAILED_AFTER_ACTIVATION",
        )
        raise

    result = {
        "schema_version": "governed_serving_feature_abi_v2_activation_v1",
        "activation_receipt": receipt.to_dict(),
        "economic_cohort": economic_cohort,
        "legacy_serving_cohort": legacy_cohort,
        "previous_checkpoint_available_for_rollback": bool(
            receipt.rollback_checkpoint_id
        ),
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
