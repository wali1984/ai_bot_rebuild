"""V2 native trainer dataset insufficient-evidence classification remediation CLI.

Verifies that the dataset quality report classifies rows with
``label=insufficient_evidence`` as ``INSUFFICIENT_EVIDENCE`` and not
under ``LABEL_MISSING``, then emits the remediation packet artifacts
(GO_NO_GO marker, status JSON, report, operator dashboard payload).

This packet is analysis-only. It does not enable live or canary, does
not approve legacy shutdown or Redis trim, does not claim native
trainer readiness, does not weaken the paper-fill gate, and does not
write any non-``v2:*`` Redis key.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))


PACKET_DIR_REL = (
    "claude_worklog/final_readiness/"
    "v2_native_trainer_dataset_insufficient_evidence_classification_remediation/latest"
)
PUBLIC_DIR_REL = (
    "v2/frontend/public/"
    "v2_native_trainer_dataset_insufficient_evidence_classification_remediation/latest"
)
DATASET_STATUS_REL = (
    "claude_worklog/final_readiness/"
    "v2_native_trainer_dataset_and_baseline_model/latest/"
    "v2_native_trainer_dataset_status.json"
)

GO_NO_GO_READY = (
    "V2_NATIVE_TRAINER_DATASET_INSUFFICIENT_EVIDENCE_CLASSIFICATION_REMEDIATION_READY"
)
GO_NO_GO_BLOCKED = (
    "V2_NATIVE_TRAINER_DATASET_INSUFFICIENT_EVIDENCE_CLASSIFICATION_REMEDIATION_BLOCKED"
)

LIVE_GATE_BLOCKED = "blocked_human_only"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safety_block() -> dict[str, Any]:
    return {
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "did_not_modify_legacy_tree": True,
        "did_not_stop_legacy_runtime": True,
        "did_not_stop_v2_runtime": True,
        "did_not_stop_report_center": True,
        "did_not_stop_replay_miner": True,
        "did_not_stop_codex_governors": True,
        "did_not_write_old_redis_keys": True,
        "did_not_call_exchange_mutation": True,
        "did_not_expose_raw_api_keys": True,
        "did_not_weaken_paper_fill_gate": True,
        "did_not_claim_trainer_native_readiness": True,
        "did_not_claim_checkpoint_compatibility": True,
        "did_not_claim_model_parity": True,
        "did_not_claim_production_readiness": True,
        "did_not_claim_edge_proven": True,
        "did_not_use_raw_legacy_redis_as_current_truth": True,
        "did_not_auto_rewrite_git_history": True,
        "did_not_create_approval_token": True,
    }


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _verify_classification(status_doc: dict[str, Any]) -> dict[str, Any]:
    quality = status_doc.get("quality_report") or {}
    classifications = quality.get("classifications") or {}
    label_distribution = quality.get("label_distribution") or {}

    label_insufficient_count = int(
        label_distribution.get("insufficient_evidence") or 0
    )
    classification_insufficient_count = int(
        classifications.get("INSUFFICIENT_EVIDENCE") or 0
    )
    classification_label_missing_count = int(
        classifications.get("LABEL_MISSING") or 0
    )
    reported_insufficient_rows = int(
        quality.get("insufficient_evidence_rows") or 0
    )
    reported_label_missing_rows = int(
        quality.get("label_missing_rows") or 0
    )

    checks = {
        "label_distribution_matches_classification_insufficient_evidence": (
            label_insufficient_count == classification_insufficient_count
        ),
        "headline_counter_matches_classification_insufficient_evidence": (
            reported_insufficient_rows == classification_insufficient_count
        ),
        "label_missing_does_not_count_insufficient_evidence": (
            reported_label_missing_rows == classification_label_missing_count
            and reported_label_missing_rows
            != label_insufficient_count
            or label_insufficient_count == 0
        ),
        "no_insufficient_evidence_rows_hidden_under_label_missing": (
            classification_insufficient_count >= label_insufficient_count
        ),
    }
    return {
        "label_insufficient_count": label_insufficient_count,
        "classification_insufficient_count": classification_insufficient_count,
        "classification_label_missing_count": classification_label_missing_count,
        "reported_insufficient_rows": reported_insufficient_rows,
        "reported_label_missing_rows": reported_label_missing_rows,
        "checks": checks,
        "all_checks_passed": all(checks.values()),
    }


def _render_report(verification: dict[str, Any], go_no_go: str) -> str:
    lines = []
    lines.append(
        "# V2 Native Trainer Dataset — Insufficient-Evidence "
        "Classification Remediation\n\n"
    )
    lines.append(f"GO/NO-GO: {go_no_go}\n\n")
    lines.append(
        "live_gate=blocked_human_only. live_symbols=[]. approves_live=false."
        " trainer_native_readiness_claimed=false."
        " checkpoint_compatibility_claimed=false."
        " model_parity_claimed=false."
        " production_readiness_claimed=false."
        " edge_proven=false.\n\n"
    )
    lines.append("## Codex blocker addressed\n")
    lines.append(
        "Codex previously failed `V2_NATIVE_TRAINER_DATASET_AND_BASELINE_MODEL_READY`"
        " with `INSUFFICIENT_EVIDENCE_ROWS_COLLAPSED_INTO_LABEL_MISSING`.\n"
        "Rows whose label is `insufficient_evidence` are now classified as"
        " `INSUFFICIENT_EVIDENCE` and counted separately from"
        " `LABEL_MISSING`.\n\n"
    )
    lines.append("## Verification counts (post-remediation)\n")
    lines.append(
        f"- label_distribution.insufficient_evidence: "
        f"{verification['label_insufficient_count']}\n"
        f"- classifications.INSUFFICIENT_EVIDENCE: "
        f"{verification['classification_insufficient_count']}\n"
        f"- classifications.LABEL_MISSING: "
        f"{verification['classification_label_missing_count']}\n"
        f"- insufficient_evidence_rows: "
        f"{verification['reported_insufficient_rows']}\n"
        f"- label_missing_rows: "
        f"{verification['reported_label_missing_rows']}\n\n"
    )
    lines.append("## Checks\n")
    for name, ok in verification["checks"].items():
        lines.append(f"- {name}: {ok}\n")
    lines.append(f"\nall_checks_passed: {verification['all_checks_passed']}\n\n")
    lines.append("## Code changes\n")
    lines.append(
        "- `v2/backend/app/services/native_trainer/dataset_builder.py::_classify_row`"
        " — explicit `insufficient_evidence` label now maps to"
        " `ROW_INSUFFICIENT_EVIDENCE`.\n"
        "- `v2/backend/app/services/native_trainer/dataset_builder.py::build_rows_from_replay_bundles`"
        " — same fix for replay-bundle-derived rows.\n"
        "- Regression tests added in"
        " `v2/backend/tests/integration/cli/test_v2_native_trainer_dataset_and_baseline_model.py`"
        " covering: label classification mapping, quality-counter separation,"
        " baseline evaluator excluding insufficient-evidence rows, and"
        " replay-bundle row classification.\n\n"
    )
    lines.append("## What this packet did NOT do\n")
    lines.append(
        "- Did not claim V2_NATIVE_TRAINER_READY or V2_NATIVE_TRAINER_ACTIVE.\n"
        "- Did not claim checkpoint compatibility.\n"
        "- Did not claim policy-architecture parity.\n"
        "- Did not claim production readiness.\n"
        "- Did not claim edge proven.\n"
        "- Did not weaken the paper-fill gate.\n"
        "- Did not write any non-v2:* Redis key.\n"
        "- Did not call the exchange.\n"
        "- Did not enable production trading or canary.\n"
        "- Did not approve legacy shutdown or Redis trim.\n"
        "- Did not modify legacy or V2 runtime.\n"
        "- Did not load or log any API credential value.\n"
        "- Did not auto-rewrite git history.\n"
        "- Did not create an approval token.\n"
    )
    return "".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Remediate the Codex blocker INSUFFICIENT_EVIDENCE_ROWS_"
            "COLLAPSED_INTO_LABEL_MISSING by verifying the refreshed "
            "dataset quality classification and emitting the remediation "
            "packet artifacts."
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Override the repository root used to locate inputs and outputs.",
    )
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    status_path = repo_root / DATASET_STATUS_REL
    if not status_path.exists():
        print(json.dumps({
            "go_no_go": GO_NO_GO_BLOCKED,
            "blocker": "dataset_status_payload_missing",
            "missing_path": str(status_path),
        }, indent=2, sort_keys=True))
        return 2
    status_doc = json.loads(status_path.read_text(encoding="utf-8"))
    verification = _verify_classification(status_doc)
    go_no_go = (
        GO_NO_GO_READY if verification["all_checks_passed"] else GO_NO_GO_BLOCKED
    )

    packet_dir = repo_root / PACKET_DIR_REL
    public_dir = repo_root / PUBLIC_DIR_REL

    remediation_status = {
        "schema_version": (
            "v2_native_trainer_dataset_insufficient_evidence_"
            "classification_remediation_v1_status"
        ),
        "generated_at": _utc_now_iso(),
        "go_no_go": go_no_go,
        "codex_prior_fail": (
            "V2_NATIVE_TRAINER_DATASET_BASELINE_MODEL_CODEX_FAIL "
            "INSUFFICIENT_EVIDENCE_ROWS_COLLAPSED_INTO_LABEL_MISSING"
        ),
        "verification": verification,
        "dataset_status_source": str(status_path.relative_to(repo_root)),
        **_safety_block(),
    }

    dashboard = {
        "schema_version": (
            "v2_native_trainer_dataset_insufficient_evidence_"
            "classification_remediation_v1_operator_dashboard_payload"
        ),
        "generated_at": _utc_now_iso(),
        "go_no_go": go_no_go,
        "safety_scoreboard": _safety_block(),
        "summary": {
            "label_insufficient_count": verification["label_insufficient_count"],
            "classification_insufficient_count": (
                verification["classification_insufficient_count"]
            ),
            "classification_label_missing_count": (
                verification["classification_label_missing_count"]
            ),
            "reported_insufficient_rows": (
                verification["reported_insufficient_rows"]
            ),
            "reported_label_missing_rows": (
                verification["reported_label_missing_rows"]
            ),
            "all_checks_passed": verification["all_checks_passed"],
        },
        "trainer_native_readiness_claimed": False,
        "v2_native_trainer_ready": False,
        "checkpoint_compatibility_claimed": False,
        "model_parity_claimed": False,
        "production_readiness_claimed": False,
        "edge_proven": False,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
    }

    report = _render_report(verification, go_no_go)

    paths_written: list[Path] = []
    p1 = packet_dir / "dataset_insufficient_evidence_classification_status.json"
    _atomic_write_json(p1, remediation_status)
    paths_written.append(p1)

    p2 = packet_dir / "operator_dashboard_payload.json"
    _atomic_write_json(p2, dashboard)
    paths_written.append(p2)

    p3 = (
        packet_dir
        / "V2_NATIVE_TRAINER_DATASET_INSUFFICIENT_EVIDENCE_CLASSIFICATION_REMEDIATION_REPORT.md"
    )
    _atomic_write_text(p3, report)
    paths_written.append(p3)

    p4 = packet_dir / "GO_NO_GO.md"
    _atomic_write_text(p4, go_no_go + "\n")
    paths_written.append(p4)

    p5 = public_dir / "operator_dashboard_payload.json"
    _atomic_write_json(p5, dashboard)
    paths_written.append(p5)

    p6 = public_dir / "dataset_insufficient_evidence_classification_status.json"
    _atomic_write_json(p6, remediation_status)
    paths_written.append(p6)

    print(json.dumps({
        "go_no_go": go_no_go,
        "verification": verification,
        "paths_written": [str(p) for p in paths_written],
    }, indent=2, sort_keys=True))
    return 0 if verification["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
