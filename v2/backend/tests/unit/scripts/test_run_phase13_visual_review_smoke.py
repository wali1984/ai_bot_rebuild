from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from scripts.run_phase13_visual_review_smoke import REQUIRED_ROUTES, REQUIRED_VIEWPORTS, build_report, main


def _passing_row(route: str, viewport: str) -> dict[str, object]:
    width, height = viewport.split("x")
    return {
        "route": route,
        "viewport": viewport,
        "width": int(width),
        "height": int(height),
        "status": "PASS",
        "screenshot_exists": True,
        "human_reviewed": True,
        "visual_reviewed": True,
        "visual_pass": True,
        "professional_visual_pass": True,
        "copy_checked": True,
        "forbidden_strings_absent": True,
        "no_overflow": True,
        "responsive_pass": True,
        "data_honesty_checked": True,
        "missing_data_states_checked": True,
        "forbidden_strings_visible": False,
        "live_trading_enabled": False,
        "exchange_mutation_enabled": False,
    }


def _write_full_review(tmp_path: Path) -> Path:
    artifact = tmp_path / "phase13-review.json"
    artifact.write_text(
        json.dumps(
            {
                "screenshots": [
                    _passing_row(route, viewport)
                    for route in sorted(REQUIRED_ROUTES)
                    for viewport in sorted(REQUIRED_VIEWPORTS)
                ]
            }
        ),
        encoding="utf-8",
    )
    return artifact


def test_phase13_visual_review_smoke_passes_for_full_review_matrix(tmp_path: Path) -> None:
    artifact = _write_full_review(tmp_path)

    report = build_report(review_artifact_paths=[artifact])

    assert report["phase13_visual_review_status"] == "passed"
    assert report["covered_route_viewport_count"] == report["required_route_viewport_count"]
    assert report["missing_pairs"] == []
    assert report["failed_rows"] == []
    assert report["forbidden_strings_visible"] is False
    assert report["live_trading_enabled"] is False
    assert report["exchange_mutation_enabled"] is False
    assert report["missing_fields"] == []


def test_phase13_visual_review_smoke_fails_for_missing_matrix_pair(tmp_path: Path) -> None:
    artifact = tmp_path / "phase13-review.json"
    rows = [
        _passing_row(route, viewport)
        for route in sorted(REQUIRED_ROUTES)
        for viewport in sorted(REQUIRED_VIEWPORTS)
    ]
    rows.pop()
    artifact.write_text(json.dumps({"screenshots": rows}), encoding="utf-8")

    report = build_report(review_artifact_paths=[artifact])

    assert report["phase13_visual_review_status"] == "failed"
    assert "full_route_viewport_visual_review_matrix" in report["missing_fields"]
    assert report["missing_pairs"]


def test_phase13_visual_review_smoke_fails_for_forbidden_or_live_flags(tmp_path: Path) -> None:
    artifact = tmp_path / "phase13-review.json"
    rows = [
        _passing_row(route, viewport)
        for route in sorted(REQUIRED_ROUTES)
        for viewport in sorted(REQUIRED_VIEWPORTS)
    ]
    rows[0]["forbidden_strings_visible"] = True
    rows[1]["live_trading_enabled"] = True
    rows[2]["exchange_mutation_enabled"] = True
    artifact.write_text(json.dumps({"screenshots": rows}), encoding="utf-8")

    report = build_report(review_artifact_paths=[artifact])

    assert report["phase13_visual_review_status"] == "failed"
    assert "no_forbidden_public_trader_strings" in report["missing_fields"]
    assert "live_trading_disabled" in report["missing_fields"]
    assert "exchange_mutation_disabled" in report["missing_fields"]


def test_phase13_visual_review_smoke_cli_writes_artifact(tmp_path: Path) -> None:
    artifact = _write_full_review(tmp_path)
    output = tmp_path / "artifact" / "phase13-review-smoke.json"

    exit_code = main(["--review-artifact-path", str(artifact), "--output", str(output)])

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["phase13_visual_review_status"] == "passed"
    assert payload["source"] == "local_phase13_visual_review_smoke"
    assert payload["source_type"] == "local_smoke"
    assert payload["mode"] == "read_only"
    assert payload["live_trading_enabled"] is False
    assert payload["exchange_mutation_enabled"] is False
