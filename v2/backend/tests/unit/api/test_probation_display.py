from app.api.v2.probation_display import probation_gate_display_status


def test_probation_gate_display_status_accumulates_waiting_gate() -> None:
    assert (
        probation_gate_display_status(
            {
                "status": "PROBATION_5_TRADE_GATE_WAITING_OR_BLOCKED",
                "closed_count": 1,
                "required_closed_count": 5,
            }
        )
        == "ACCUMULATING_1_OF_5"
    )


def test_probation_gate_display_status_preserves_terminal_gate_status() -> None:
    assert (
        probation_gate_display_status(
            {
                "status": "PROBATION_5_CLOSE_GATE_PASS",
                "closed_count": 5,
                "required_closed_count": 5,
            }
        )
        == "PROBATION_5_CLOSE_GATE_PASS"
    )


def test_probation_gate_display_status_reads_legacy_check_count() -> None:
    assert (
        probation_gate_display_status(
            {
                "status": "PROBATION_5_TRADE_GATE_WAITING_OR_BLOCKED",
                "checks": {"closed_probation_trades": 3},
                "window": 5,
            }
        )
        == "ACCUMULATING_3_OF_5"
    )
