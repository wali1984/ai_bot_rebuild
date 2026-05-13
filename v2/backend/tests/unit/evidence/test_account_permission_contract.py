from __future__ import annotations

from datetime import datetime, timezone

from v2.backend.app.evidence.account_permission_contract import classify_account_payloads


def test_unknown_trade_permission_blocks_canary() -> None:
    result = classify_account_payloads(
        now=datetime(2026, 5, 13, tzinfo=timezone.utc),
        payloads={
            "account.json": {
                "generated_at": "2026-05-13T00:00:00Z",
                "account": "read_only",
            }
        },
    )

    assert result.trade_permission_status == "TRADE_PERMISSION_EVIDENCE_PRESENT_READONLY"
    assert "TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY" in result.canary_blockers
    assert result.canary_ready is False


def test_missing_margin_and_leverage_block_canary() -> None:
    result = classify_account_payloads(
        now=datetime(2026, 5, 13, tzinfo=timezone.utc),
        payloads={
            "account.json": {
                "generated_at": "2026-05-13T00:00:00Z",
                "trade_capable": True,
            }
        },
    )

    assert "ISOLATED_MARGIN_EVIDENCE_MISSING" in result.canary_blockers
    assert "LEVERAGE_CAP_EVIDENCE_MISSING" in result.canary_blockers
    assert "V2_ORDER_METHODS_FAIL_CLOSED" in result.classifications
