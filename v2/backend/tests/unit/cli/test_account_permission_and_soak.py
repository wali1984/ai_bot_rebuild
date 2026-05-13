from __future__ import annotations

from datetime import datetime, timezone

from v2.backend.app.cli.account_permission_and_soak import (
    build_account_evidence,
    build_canary_readiness,
    build_trade_permission_evidence,
    mutation_methods_fail_closed,
    summarize_event_gaps,
)


def test_trade_permission_classifier_blocks_unknown_account_and_proves_fail_closed() -> None:
    account = {"account_evidence_status": "READONLY_ACCOUNT_EVIDENCE_MISSING"}
    payload = {
        "feed_health": {"order_capability": "BLOCKED"},
        "api_key_permission_status": [{"status": "not_configured", "order_capability": "BLOCKED"}],
    }

    evidence = build_trade_permission_evidence(account, payload)

    assert evidence["trade_permission_status"] == "TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY"
    assert evidence["canary_blocker"] is True
    assert evidence["order_methods_fail_closed"] is True
    assert evidence["cancel_methods_fail_closed"] is True
    assert evidence["leverage_methods_fail_closed"] is True
    assert evidence["margin_methods_fail_closed"] is True


def test_readonly_account_stale_payload_blocks_canary() -> None:
    evidence = build_account_evidence(
        datetime(2026, 5, 13, tzinfo=timezone.utc),
        {
            "generated_at": "2026-05-10T00:00:00Z",
            "exchange_account_status": [
                {
                    "exchange": "Binance USD-M",
                    "key_status": "not_configured",
                    "account_read_status": "missing",
                }
            ],
        },
    )

    assert evidence["account_evidence_status"] == "READONLY_ACCOUNT_EVIDENCE_STALE"
    assert evidence["canary_blocker"] is True
    assert "EVIDENCE_PROVIDER_REQUIRED" in evidence["classifications"]


def test_canary_readiness_remains_false_until_soak_and_account_evidence_are_complete() -> None:
    readiness = build_canary_readiness(
        {"status_6h": "PAPER_SHADOW_6H_PENDING", "status_24h": "PAPER_SHADOW_24H_PENDING"},
        {"account_evidence_status": "READONLY_ACCOUNT_EVIDENCE_STALE"},
        {"trade_permission_status": "TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY"},
        {"sufficient_for_canary": False},
        {"classification": "WEEKLY_LOSS_GATE_RUNTIME_PROVEN"},
    )

    assert readiness["canary_ready"] is False
    assert "PAPER_SHADOW_6H_PENDING" in readiness["remaining_blockers"]
    assert "TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY" in readiness["remaining_blockers"]


def test_mutation_stubs_fail_closed() -> None:
    result = mutation_methods_fail_closed()

    assert result["create_" + "order"] is True
    assert result["cancel_" + "order"] is True
    assert result["change_" + "leverage"] is True
    assert result["change_" + "margin"] is True


def test_event_gap_summary_detects_continuous_observation() -> None:
    summary = summarize_event_gaps(
        [
            {"generated_at": "2026-05-13T00:00:00Z"},
            {"generated_at": "2026-05-13T00:00:30Z"},
            {"generated_at": "2026-05-13T00:01:00Z"},
        ]
    )

    assert summary["continuous"] is True
    assert summary["max_gap_seconds"] == 30
