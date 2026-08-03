from __future__ import annotations

import pytest

from tools.apply_closed_trades_restore import _merge_restore_rows


def test_closed_trades_restore_rows_are_stamped_and_idempotent() -> None:
    payload = {
        "paper_session_id": "paper_session_a",
        "row_count": 2,
        "rows": [
            {"symbol": "AEROUSDT", "side": "long", "position_id": "paper_pos_AEROUSDT"},
            {"symbol": "AEROUSDT", "side": "short", "position_id": "paper_pos_AEROUSDT"},
        ],
    }

    session, candidates, to_add = _merge_restore_rows([], payload, recorded_utc="2026-07-08T00:00:00+00:00")

    assert session == "paper_session_a"
    assert len(candidates) == 2
    assert len(to_add) == 2
    assert {row["restore_dedup_key"] for row in to_add} == {
        "recon_close_0_AEROUSDT",
        "recon_close_1_AEROUSDT",
    }
    assert all(row["reconstructed_from_artifacts"] is True for row in to_add)
    assert all(row["counts_as_strict_preemptive_evidence"] is False for row in to_add)
    assert all(row["counts_as_live_readiness_evidence"] is False for row in to_add)
    assert all(row["counts_as_a_plus_evidence"] is False for row in to_add)
    assert all(row["preemptive_decision_backfilled"] is True for row in to_add)

    _, _, second_to_add = _merge_restore_rows(
        to_add,
        payload,
        recorded_utc="2026-07-08T00:01:00+00:00",
    )
    assert second_to_add == []


def test_closed_trades_restore_rejects_row_count_mismatch() -> None:
    payload = {
        "paper_session_id": "paper_session_a",
        "row_count": 2,
        "rows": [{"symbol": "BTCUSDT"}],
    }

    with pytest.raises(ValueError, match="row_count mismatch"):
        _merge_restore_rows([], payload, recorded_utc="2026-07-08T00:00:00+00:00")

