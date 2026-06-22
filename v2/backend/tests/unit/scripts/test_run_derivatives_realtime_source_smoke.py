from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from scripts.run_derivatives_realtime_source_smoke import build_report, main


def _write_safe_evidence(tmp_path: Path) -> tuple[Path, Path]:
    derivatives = tmp_path / "derivatives.json"
    safety = tmp_path / "safety.json"
    derivatives.write_text(
        json.dumps(
            {
                "funding_realtime_verified": True,
                "open_interest_realtime_verified": True,
                "liquidation_source_verified": True,
                "long_short_source_verified": True,
                "basis_source_verified": True,
                "exchange_comparison_verified": True,
                "freshness_enforced": True,
                "stale_marking_verified": True,
                "source_labels_verified": True,
                "no_static_presented_as_live": True,
            }
        ),
        encoding="utf-8",
    )
    safety.write_text(
        json.dumps(
            {
                "fake_live_data_detected": False,
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
                "live_submit_available": False,
                "live_cancel_available": False,
            }
        ),
        encoding="utf-8",
    )
    return derivatives, safety


def test_derivatives_realtime_source_smoke_passes_for_safe_evidence(tmp_path: Path) -> None:
    derivatives, safety = _write_safe_evidence(tmp_path)

    report = build_report(derivative_evidence_paths=[derivatives], safety_evidence_paths=[safety])

    assert report["derivatives_realtime_source_status"] == "passed"
    assert report["funding_realtime_verified"] is True
    assert report["open_interest_realtime_verified"] is True
    assert report["liquidation_source_verified"] is True
    assert report["long_short_source_verified"] is True
    assert report["freshness_enforced"] is True
    assert report["fake_live_data_detected"] is False
    assert report["live_trading_enabled"] is False
    assert report["exchange_mutation_enabled"] is False
    assert report["missing_fields"] == []


def test_derivatives_realtime_source_smoke_fails_without_required_evidence(tmp_path: Path) -> None:
    _derivatives, safety = _write_safe_evidence(tmp_path)

    report = build_report(derivative_evidence_paths=[], safety_evidence_paths=[safety])

    assert report["derivatives_realtime_source_status"] == "failed"
    assert "funding_realtime_verified" in report["missing_fields"]
    assert any("No derivatives realtime/source evidence" in warning for warning in report["warnings"])


def test_derivatives_realtime_source_smoke_fails_on_fake_live_or_live_mutation(tmp_path: Path) -> None:
    derivatives, safety = _write_safe_evidence(tmp_path)
    safety.write_text(
        json.dumps(
            {
                "fake_live_data_detected": True,
                "live_trading_enabled": True,
                "exchange_mutation_enabled": True,
                "live_submit_available": True,
                "live_cancel_available": True,
            }
        ),
        encoding="utf-8",
    )

    report = build_report(derivative_evidence_paths=[derivatives], safety_evidence_paths=[safety])

    assert report["derivatives_realtime_source_status"] == "failed"
    assert "no_fake_live_data" in report["missing_fields"]
    assert "live_trading_disabled" in report["missing_fields"]
    assert "exchange_mutation_disabled" in report["missing_fields"]
    assert "live_submit_unavailable" in report["missing_fields"]
    assert "live_cancel_unavailable" in report["missing_fields"]


def test_derivatives_realtime_source_smoke_cli_writes_artifact(tmp_path: Path) -> None:
    derivatives, safety = _write_safe_evidence(tmp_path)
    output = tmp_path / "artifact" / "derivatives-source.json"

    exit_code = main(
        [
            "--derivative-evidence-path",
            str(derivatives),
            "--safety-evidence-path",
            str(safety),
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["derivatives_realtime_source_status"] == "passed"
    assert payload["source"] == "local_derivatives_realtime_source_smoke"
    assert payload["source_type"] == "local_smoke"
    assert payload["mode"] == "read_only"
    assert payload["live_trading_enabled"] is False
    assert payload["exchange_mutation_enabled"] is False
