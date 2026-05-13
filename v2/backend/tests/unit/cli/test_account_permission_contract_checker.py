from __future__ import annotations

from pathlib import Path

from v2.backend.app.cli.account_permission_contract_checker import build_status


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def test_checker_reads_public_evidence_and_blocks_missing_margin(tmp_path) -> None:
    _write(
        tmp_path / "v2/frontend/public/account_permission_and_soak/latest/operator_dashboard_payload.json",
        """
        {
          "generated_at": "2026-05-13T00:00:00Z",
          "trade_capable": true,
          "max_leverage": 3
        }
        """,
    )

    payload = build_status(tmp_path)

    assert payload["live_gate"] == "blocked_human_only"
    assert payload["margin_evidence_status"] == "ISOLATED_MARGIN_EVIDENCE_MISSING"
    assert payload["canary_ready"] is False
    assert payload["exchange_mutation_performed"] is False
