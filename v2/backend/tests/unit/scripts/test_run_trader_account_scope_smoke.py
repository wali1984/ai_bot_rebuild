from __future__ import annotations

import json
from pathlib import Path

from scripts.run_trader_account_scope_smoke import build_report, main


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _valid_auth_payload() -> dict:
    return {
        "users": [
            {
                "id": "user-wajidali1984",
                "email": "wajidali1984@hotmail.com",
                "username": "wajidali1984",
                "role": "trader",
                "trader_id": "trader-wajidali1984",
                "paper_account_id": "paper-wajidali1984",
                "password_hash": "$2b$not-output",
                "is_active": False,
                "exchange_accounts": [
                    {
                        "id": "binance-wajidali1984",
                        "trader_id": "trader-wajidali1984",
                        "paper_account_id": "paper-wajidali1984",
                        "exchange": "binance",
                        "label": "Wajid Ali Binance Futures",
                        "account_type": "usd_m_futures",
                        "mode": "read_only",
                        "credential_ref": "ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY",
                        "read_only": True,
                        "live_trading_enabled": False,
                        "status": "credential_source_pending",
                    }
                ],
            },
            {
                "id": "user-second",
                "email": "second@example.com",
                "username": "second",
                "role": "trader",
                "trader_id": "trader-second",
                "paper_account_id": "paper-second",
                "password_hash": "$2b$not-output",
                "is_active": True,
                "exchange_accounts": [
                    {
                        "id": "binance-second",
                        "trader_id": "trader-second",
                        "paper_account_id": "paper-second",
                        "exchange": "binance",
                        "mode": "read_only",
                        "read_only": True,
                        "live_trading_enabled": False,
                        "status": "credential_source_pending",
                    }
                ],
            },
        ]
    }


def _valid_accounts_payload() -> dict:
    return {
        "accounts": [
            {
                "trader_id": "trader-wajidali1984",
                "paper_account_id": "paper-wajidali1984",
                "currency": "USDT",
                "positions": [],
                "orders": [],
                "executions": [],
                "signals": [],
            },
            {
                "trader_id": "trader-second",
                "paper_account_id": "paper-second",
                "currency": "USDT",
                "positions": [],
                "orders": [],
                "executions": [],
                "signals": [],
            },
        ]
    }


def test_trader_account_scope_smoke_passes_for_scoped_multi_trader_files(tmp_path: Path) -> None:
    auth_path = _write(tmp_path / "auth_users.json", _valid_auth_payload())
    accounts_path = _write(tmp_path / "trader_accounts.json", _valid_accounts_payload())

    report = build_report(auth_users_path=auth_path, trader_accounts_path=accounts_path)

    assert report["status"] == "passed"
    assert report["checks"]["paper_account_ids_unique_across_traders"] is True
    assert report["checks"]["initial_trader_scope_present"] is True
    assert report["checks"]["initial_trader_repository_scope_present"] is True
    assert report["live_trading_enabled"] is False
    assert report["exchange_mutation_enabled"] is False
    assert report["contains_credentials"] is False
    serialized = json.dumps(report).lower()
    assert "alphaforge_binance_wajidali1984_readonly" not in serialized
    assert "password_hash" not in serialized


def test_trader_account_scope_smoke_fails_duplicate_paper_account(tmp_path: Path) -> None:
    payload = _valid_auth_payload()
    payload["users"][1]["paper_account_id"] = "paper-wajidali1984"
    auth_path = _write(tmp_path / "auth_users.json", payload)
    accounts_path = _write(tmp_path / "trader_accounts.json", _valid_accounts_payload())

    report = build_report(auth_users_path=auth_path, trader_accounts_path=accounts_path)

    assert report["status"] == "failed"
    assert "paper_account_ids_unique_across_traders" in report["failure_reasons"]
    assert report["summary"]["duplicate_paper_account_ids"] == ["paper-wajidali1984"]


def test_trader_account_scope_smoke_fails_duplicate_trader_id(tmp_path: Path) -> None:
    payload = _valid_auth_payload()
    payload["users"][1]["trader_id"] = "trader-wajidali1984"
    auth_path = _write(tmp_path / "auth_users.json", payload)
    accounts_path = _write(tmp_path / "trader_accounts.json", _valid_accounts_payload())

    report = build_report(auth_users_path=auth_path, trader_accounts_path=accounts_path)

    assert report["status"] == "failed"
    assert "trader_ids_unique_across_users" in report["failure_reasons"]
    assert report["summary"]["duplicate_trader_ids"] == ["trader-wajidali1984"]


def test_trader_account_scope_smoke_fails_live_or_writable_exchange_account(tmp_path: Path) -> None:
    payload = _valid_auth_payload()
    payload["users"][0]["exchange_accounts"][0]["read_only"] = False
    payload["users"][0]["exchange_accounts"][0]["live_trading_enabled"] = True
    auth_path = _write(tmp_path / "auth_users.json", payload)
    accounts_path = _write(tmp_path / "trader_accounts.json", _valid_accounts_payload())

    report = build_report(auth_users_path=auth_path, trader_accounts_path=accounts_path)

    assert report["status"] == "failed"
    assert "exchange_accounts_read_only" in report["failure_reasons"]
    assert "exchange_accounts_live_disabled" in report["failure_reasons"]


def test_trader_account_scope_smoke_fails_wrong_exchange_paper_scope(tmp_path: Path) -> None:
    payload = _valid_auth_payload()
    payload["users"][0]["exchange_accounts"][0]["paper_account_id"] = "paper-other"
    auth_path = _write(tmp_path / "auth_users.json", payload)
    accounts_path = _write(tmp_path / "trader_accounts.json", _valid_accounts_payload())

    report = build_report(auth_users_path=auth_path, trader_accounts_path=accounts_path)

    assert report["status"] == "failed"
    assert "exchange_accounts_match_owner_scope" in report["failure_reasons"]


def test_trader_account_scope_smoke_cli_writes_artifact(tmp_path: Path) -> None:
    auth_path = _write(tmp_path / "auth_users.json", _valid_auth_payload())
    accounts_path = _write(tmp_path / "trader_accounts.json", _valid_accounts_payload())
    output_path = tmp_path / "scope-smoke.json"

    code = main([
        "--auth-users-path",
        str(auth_path),
        "--trader-accounts-path",
        str(accounts_path),
        "--output",
        str(output_path),
    ])

    assert code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "passed"
    assert payload["summary"]["trader_user_count"] == 2
    assert payload["public_market_data_only"] is True
    assert payload["live_trading_enabled"] is False
