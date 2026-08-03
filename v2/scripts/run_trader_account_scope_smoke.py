#!/usr/bin/env python3
"""Generate a read-only multi-trader account-scope smoke artifact.

The runner inspects supplied local auth-user and trader-account repository JSON
files and writes a safe summary artifact. It never creates users, never reads
exchange secrets from environment variables, never calls an exchange, and never
enables live trading.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SENSITIVE_KEYS = {
    "api_key",
    "api_secret",
    "secret",
    "private_key",
    "access_token",
    "refresh_token",
    "password",
    "password_hash",
    "token",
}

DEFAULT_INITIAL_EMAIL = "wajidali1984@hotmail.com"
DEFAULT_INITIAL_TRADER_ID = "trader-wajidali1984"
DEFAULT_INITIAL_PAPER_ACCOUNT_ID = "paper-wajidali1984"
DEFAULT_INITIAL_EXCHANGE_ACCOUNT_ID = "binance-wajidali1984"


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def read_json(path: Path | None) -> tuple[Any | None, str | None]:
    if path is None:
        return None, None
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, f"File not found: {path}"
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON in {path}: {exc}"
    except OSError as exc:
        return None, f"Could not read {path}: {exc}"


def sequence(payload: Any, key: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get(key)
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def normalized_text(value: Any) -> str:
    return str(value or "").strip()


def has_sensitive_value(payload: Any, *, allow_password_hash: bool = False) -> bool:
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).lower()
            if lowered in SENSITIVE_KEYS and value not in (None, ""):
                if allow_password_hash and lowered == "password_hash":
                    continue
                return True
            if has_sensitive_value(value, allow_password_hash=allow_password_hash):
                return True
    elif isinstance(payload, list):
        return any(has_sensitive_value(item, allow_password_hash=allow_password_hash) for item in payload)
    return False


def safe_user_summary(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": normalized_text(user.get("id")) or None,
        "email": normalized_text(user.get("email")).lower() or None,
        "role": normalized_text(user.get("role")) or None,
        "trader_id": normalized_text(user.get("trader_id")) or None,
        "paper_account_id": normalized_text(user.get("paper_account_id")) or None,
        "is_active": bool(user.get("is_active")),
        "exchange_account_count": len(user.get("exchange_accounts") if isinstance(user.get("exchange_accounts"), list) else []),
    }


def build_report(
    *,
    auth_users_path: Path | None,
    trader_accounts_path: Path | None,
    expected_email: str = DEFAULT_INITIAL_EMAIL,
    expected_trader_id: str = DEFAULT_INITIAL_TRADER_ID,
    expected_paper_account_id: str = DEFAULT_INITIAL_PAPER_ACCOUNT_ID,
    expected_exchange_account_id: str = DEFAULT_INITIAL_EXCHANGE_ACCOUNT_ID,
) -> dict[str, Any]:
    generated = utc_now()
    auth_payload, auth_error = read_json(auth_users_path)
    account_payload, account_error = read_json(trader_accounts_path)
    users = sequence(auth_payload, "users")
    accounts = sequence(account_payload, "accounts")
    warnings: list[str] = []
    missing_fields: list[str] = []

    if auth_error:
        warnings.append(auth_error)
        missing_fields.append("auth_users")
    if trader_accounts_path is not None and account_error:
        warnings.append(account_error)
        missing_fields.append("trader_accounts")
    if not users:
        missing_fields.append("users")

    paper_owners: dict[str, set[str]] = {}
    trader_owners: dict[str, set[str]] = {}
    user_scope_errors: list[str] = []
    exchange_scope_errors: list[str] = []
    live_exchange_accounts: list[str] = []
    writable_exchange_accounts: list[str] = []
    credential_value_exposures: list[str] = []

    for user in users:
        user_id = normalized_text(user.get("id")) or normalized_text(user.get("email")) or "unknown-user"
        role = normalized_text(user.get("role"))
        trader_id = normalized_text(user.get("trader_id"))
        paper_account_id = normalized_text(user.get("paper_account_id"))
        if role == "trader" and (not trader_id or not paper_account_id):
            user_scope_errors.append(user_id)
        if trader_id:
            trader_owners.setdefault(trader_id, set()).add(user_id)
        if paper_account_id:
            paper_owners.setdefault(paper_account_id, set()).add(trader_id or "missing_trader_id")
        exchange_accounts = user.get("exchange_accounts") if isinstance(user.get("exchange_accounts"), list) else []
        for index, exchange_account in enumerate(exchange_accounts):
            if not isinstance(exchange_account, dict):
                continue
            account_id = normalized_text(exchange_account.get("id")) or f"{user_id}:exchange:{index}"
            if (
                not trader_id
                or not paper_account_id
                or normalized_text(exchange_account.get("trader_id")) != trader_id
                or normalized_text(exchange_account.get("paper_account_id")) != paper_account_id
            ):
                exchange_scope_errors.append(account_id)
            if exchange_account.get("read_only") is not True:
                writable_exchange_accounts.append(account_id)
            if exchange_account.get("live_trading_enabled") is not False:
                live_exchange_accounts.append(account_id)
            if has_sensitive_value(exchange_account):
                credential_value_exposures.append(account_id)

    repository_scope_errors: list[str] = []
    repository_duplicate_scopes: list[str] = []
    repository_scope_counts: dict[str, int] = {}
    for account in accounts:
        trader_id = normalized_text(account.get("trader_id"))
        paper_account_id = normalized_text(account.get("paper_account_id"))
        if not trader_id or not paper_account_id:
            repository_scope_errors.append(paper_account_id or trader_id or "unknown-account")
            continue
        scope_key = f"{trader_id}:{paper_account_id}"
        repository_scope_counts[scope_key] = repository_scope_counts.get(scope_key, 0) + 1
    repository_duplicate_scopes = sorted(scope for scope, count in repository_scope_counts.items() if count > 1)

    duplicate_paper_account_ids = sorted(
        paper_account_id for paper_account_id, owners in paper_owners.items() if len(owners) > 1
    )
    duplicate_trader_ids = sorted(
        trader_id for trader_id, owners in trader_owners.items() if len(owners) > 1
    )
    initial_user = next(
        (user for user in users if normalized_text(user.get("email")).lower() == expected_email.lower()),
        None,
    )
    initial_user_summary = safe_user_summary(initial_user) if initial_user else None
    initial_exchange_accounts = (
        initial_user.get("exchange_accounts")
        if isinstance(initial_user, dict) and isinstance(initial_user.get("exchange_accounts"), list)
        else []
    )
    initial_exchange = next(
        (
            account
            for account in initial_exchange_accounts
            if isinstance(account, dict) and normalized_text(account.get("id")) == expected_exchange_account_id
        ),
        None,
    )
    initial_trader_ok = bool(
        initial_user
        and normalized_text(initial_user.get("trader_id")) == expected_trader_id
        and normalized_text(initial_user.get("paper_account_id")) == expected_paper_account_id
        and isinstance(initial_exchange, dict)
        and normalized_text(initial_exchange.get("trader_id")) == expected_trader_id
        and normalized_text(initial_exchange.get("paper_account_id")) == expected_paper_account_id
        and initial_exchange.get("read_only") is True
        and initial_exchange.get("live_trading_enabled") is False
    )
    if not initial_trader_ok:
        missing_fields.append("initial_trader_scope")

    repository_rows_for_initial_scope = [
        account
        for account in accounts
        if normalized_text(account.get("trader_id")) == expected_trader_id
        and normalized_text(account.get("paper_account_id")) == expected_paper_account_id
    ]
    repository_initial_scope_present = bool(repository_rows_for_initial_scope) if trader_accounts_path is not None else None
    if trader_accounts_path is not None and not repository_initial_scope_present:
        missing_fields.append("initial_trader_repository_scope")

    status = "passed"
    failure_reasons: list[str] = []
    checks = {
        "auth_users_loaded": bool(users),
        "trader_users_have_scope": not user_scope_errors,
        "trader_ids_unique_across_users": not duplicate_trader_ids,
        "paper_account_ids_unique_across_traders": not duplicate_paper_account_ids,
        "exchange_accounts_match_owner_scope": not exchange_scope_errors,
        "exchange_accounts_read_only": not writable_exchange_accounts,
        "exchange_accounts_live_disabled": not live_exchange_accounts,
        "exchange_accounts_secret_free": not credential_value_exposures,
        "repository_accounts_have_scope": not repository_scope_errors,
        "repository_account_scopes_unique": not repository_duplicate_scopes,
        "initial_trader_scope_present": initial_trader_ok,
        "initial_trader_repository_scope_present": repository_initial_scope_present,
        "public_market_data_only": True,
    }
    for name, passed in checks.items():
        if passed is False:
            status = "failed"
            failure_reasons.append(name)

    if has_sensitive_value({"users": users}, allow_password_hash=True):
        status = "failed"
        failure_reasons.append("auth_store_contains_raw_secret_like_values")

    return {
        "status": status,
        "trader_account_scope_status": status,
        "source": "local auth/trader repository files",
        "source_type": "repository" if users else "unavailable",
        "mode": "read_only",
        "endpoint": "scripts/run_trader_account_scope_smoke.py",
        "timestamp": generated,
        "received_at": generated,
        "stale": False,
        "missing_fields": sorted(set(missing_fields)),
        "warnings": warnings,
        "failure_reasons": failure_reasons,
        "checks": checks,
        "summary": {
            "user_count": len(users),
            "trader_user_count": sum(1 for user in users if normalized_text(user.get("role")) == "trader"),
            "repository_account_count": len(accounts),
            "duplicate_trader_ids": duplicate_trader_ids,
            "duplicate_paper_account_ids": duplicate_paper_account_ids,
            "user_scope_errors": user_scope_errors,
            "exchange_scope_errors": exchange_scope_errors,
            "writable_exchange_accounts": writable_exchange_accounts,
            "live_exchange_accounts": live_exchange_accounts,
            "credential_value_exposures": credential_value_exposures,
            "repository_scope_errors": repository_scope_errors,
            "repository_duplicate_scopes": repository_duplicate_scopes,
            "initial_user": initial_user_summary,
            "initial_trader_repository_scope_present": repository_initial_scope_present,
        },
        "artifact_paths": {
            "auth_users_path": str(auth_users_path) if auth_users_path else None,
            "trader_accounts_path": str(trader_accounts_path) if trader_accounts_path else None,
        },
        "public_market_data_only": True,
        "contains_credentials": False,
        "live_trading_enabled": False,
        "exchange_mutation_enabled": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a read-only multi-trader account-scope smoke check")
    parser.add_argument("--auth-users-path", required=True, type=Path)
    parser.add_argument("--trader-accounts-path", type=Path)
    parser.add_argument("--expected-email", default=DEFAULT_INITIAL_EMAIL)
    parser.add_argument("--expected-trader-id", default=DEFAULT_INITIAL_TRADER_ID)
    parser.add_argument("--expected-paper-account-id", default=DEFAULT_INITIAL_PAPER_ACCOUNT_ID)
    parser.add_argument("--expected-exchange-account-id", default=DEFAULT_INITIAL_EXCHANGE_ACCOUNT_ID)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    report = build_report(
        auth_users_path=args.auth_users_path,
        trader_accounts_path=args.trader_accounts_path,
        expected_email=args.expected_email,
        expected_trader_id=args.expected_trader_id,
        expected_paper_account_id=args.expected_paper_account_id,
        expected_exchange_account_id=args.expected_exchange_account_id,
    )
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
