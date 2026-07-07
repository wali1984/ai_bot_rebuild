from __future__ import annotations

from v2.backend.app.cli.v2_validate_paper_position_ledger import _open_position_rows


def test_open_position_rows_prefers_accepted_ledger_over_standalone_positions() -> None:
    archive = {
        "keys": {
            "v2:paper:positions": {
                "payload": [
                    {
                        "position_id": "paper_pos_SYNUSDT",
                        "symbol": "SYNUSDT",
                        "entry_price": 0.5,
                    }
                ]
            },
            "v2:paper:ledger": {
                "payload": {
                    "accepted": [
                        {
                            "intent_id": "signal-btc-1m",
                            "signal_id": "signal-btc-1m",
                            "symbol": "BTCUSDT",
                            "side": "long",
                            "entry_price": 100.0,
                            "fill_price": 100.0,
                            "quantity": 8.0,
                        }
                    ]
                }
            },
        }
    }

    rows = _open_position_rows(archive)

    assert len(rows) == 1
    assert rows[0]["intent_id"] == "signal-btc-1m"
    assert rows[0]["symbol"] == "BTCUSDT"
