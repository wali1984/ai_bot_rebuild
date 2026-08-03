"""File-backed trader paper-account repository.

This is a safe local repository for trader-scoped paper/read-only account
state. It does not store exchange secrets, does not call an exchange, and does
not enable live order submit/cancel. Local paper order staging, cancel, and
explicit manual fill only mutate this repository. Missing balances or positions
remain missing instead of being fabricated.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.domain.governance.audit_chain import chain_local_paper_audit_event
from app.services.paper_audit_ledger import append_local_paper_audit_event


LOCAL_TRADER_ACCOUNT_REPOSITORY_KIND = "local_file"
SQL_TRADER_ACCOUNT_REPOSITORY_KIND = "sqlalchemy"


class TraderPaperAccount(TypedDict, total=False):
    trader_id: str
    paper_account_id: str
    currency: str
    equity: float | None
    realized_pnl: float | None
    unrealized_pnl: float | None
    positions: list[dict[str, Any]]
    orders: list[dict[str, Any]]
    executions: list[dict[str, Any]]
    signals: list[dict[str, Any]]
    audit_events: list[dict[str, Any]]
    source_status: str
    created_at: str
    updated_at: str


def _repo_root() -> Path:
    return Path(os.environ.get("V2_REPO_ROOT", "/home/wali/Desktop/AI BOT REBUILD"))


def _default_store_path() -> Path:
    repo_root = _repo_root()
    if (repo_root / "backend" / "app").exists():
        return repo_root / "backend" / "trader_accounts.json"
    return repo_root / "v2" / "backend" / "trader_accounts.json"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _production_environment() -> bool:
    return os.environ.get("ALPHAFORGE_ENV", "").strip().lower() in {"prod", "production"}


def _repository_backend() -> str:
    backend = os.environ.get("ALPHAFORGE_TRADER_ACCOUNT_REPOSITORY_BACKEND", "local_file").strip().lower()
    if backend in {"sqlalchemy", "database", "db"}:
        return SQL_TRADER_ACCOUNT_REPOSITORY_KIND
    return LOCAL_TRADER_ACCOUNT_REPOSITORY_KIND


def _repository_database_url() -> str:
    return os.environ.get("ALPHAFORGE_TRADER_ACCOUNT_DATABASE_URL", "").strip()


def _repository_db_auto_create_enabled() -> bool:
    return os.environ.get("ALPHAFORGE_TRADER_ACCOUNT_DB_AUTO_CREATE", "").strip().lower() in {"1", "true", "yes", "on"}


def _scope_smoke_artifact_path() -> Path | None:
    configured = os.environ.get("ALPHAFORGE_TRADER_ACCOUNT_SCOPE_SMOKE_ARTIFACT", "").strip()
    return Path(configured) if configured else None


def _production_repository_smoke_artifact_path() -> Path | None:
    configured = os.environ.get("ALPHAFORGE_PRODUCTION_TRADER_REPOSITORY_SMOKE_ARTIFACT", "").strip()
    return Path(configured) if configured else None


def _production_repository_smoke_evidence() -> dict[str, Any]:
    artifact_path = _production_repository_smoke_artifact_path()
    if artifact_path is None:
        return {
            "configured": False,
            "valid": False,
            "status": "pending",
            "warnings": ["Production trader repository smoke artifact is not configured"],
        }
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warnings": [f"Production trader repository smoke artifact could not be read: {exc}"],
        }
    if not isinstance(payload, dict):
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warnings": ["Production trader repository smoke artifact must be a JSON object"],
        }
    status_value = str(payload.get("status") or payload.get("production_trader_repository_smoke_status") or "").strip().lower()
    required_true = (
        "durable_user_repository",
        "durable_trader_account_repository",
        "account_writer_persistence",
        "activity_writer_persistence",
        "row_level_trader_isolation",
        "paper_account_uniqueness",
        "migration_applied",
        "backup_restore_verified",
    )
    required_false = ("contains_credentials", "live_trading_enabled", "exchange_mutation_enabled")
    valid = (
        status_value in {"pass", "passed", "ok", "verified"}
        and all(payload.get(field) is True for field in required_true)
        and all(payload.get(field) is False for field in required_false)
        and not payload.get("missing_fields")
    )
    warnings = list(payload.get("warnings") or []) if isinstance(payload.get("warnings"), list) else []
    if not valid:
        warnings.append(
            "Production trader repository smoke artifact must prove durable repositories, writer persistence, row-level isolation, backup/restore, migrations, no credentials, and disabled live/exchange mutation"
        )
    return {
        "configured": True,
        "valid": valid,
        "status": "verified" if valid else "invalid",
        "durable_user_repository": payload.get("durable_user_repository") is True,
        "durable_trader_account_repository": payload.get("durable_trader_account_repository") is True,
        "account_writer_persistence": payload.get("account_writer_persistence") is True,
        "activity_writer_persistence": payload.get("activity_writer_persistence") is True,
        "row_level_trader_isolation": payload.get("row_level_trader_isolation") is True,
        "paper_account_uniqueness": payload.get("paper_account_uniqueness") is True,
        "migration_applied": payload.get("migration_applied") is True,
        "backup_restore_verified": payload.get("backup_restore_verified") is True,
        "contains_credentials": payload.get("contains_credentials") is True,
        "live_trading_enabled": payload.get("live_trading_enabled"),
        "exchange_mutation_enabled": payload.get("exchange_mutation_enabled"),
        "warnings": [str(warning) for warning in warnings],
    }


def _trader_account_scope_smoke_evidence() -> dict[str, Any]:
    artifact_path = _scope_smoke_artifact_path()
    if artifact_path is None:
        return {
            "configured": False,
            "valid": False,
            "status": "pending",
            "warnings": ["Multi-trader account-scope smoke artifact is not configured"],
        }
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warnings": [f"Multi-trader account-scope smoke artifact could not be read: {exc}"],
        }
    if not isinstance(payload, dict):
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warnings": ["Multi-trader account-scope smoke artifact must be a JSON object"],
        }
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    required_checks = (
        "auth_users_loaded",
        "trader_users_have_scope",
        "paper_account_ids_unique_across_traders",
        "exchange_accounts_match_owner_scope",
        "exchange_accounts_read_only",
        "exchange_accounts_live_disabled",
        "exchange_accounts_secret_free",
        "repository_accounts_have_scope",
        "repository_account_scopes_unique",
        "initial_trader_scope_present",
    )
    checks_passed = all(checks.get(check) is True for check in required_checks)
    status_value = str(payload.get("status") or payload.get("trader_account_scope_status") or "").strip().lower()
    public_only = payload.get("public_market_data_only") is True
    contains_credentials = payload.get("contains_credentials") is True
    live_disabled = payload.get("live_trading_enabled") is False
    exchange_disabled = payload.get("exchange_mutation_enabled") is False
    valid = (
        status_value in {"pass", "passed", "ok", "verified"}
        and checks_passed
        and public_only
        and not contains_credentials
        and live_disabled
        and exchange_disabled
    )
    warnings = list(payload.get("warnings") or []) if isinstance(payload.get("warnings"), list) else []
    if not valid:
        warnings.append(
            "Multi-trader account-scope smoke artifact must prove scoped users/accounts, paper-account uniqueness, read-only/live-disabled exchange metadata, no credentials, and disabled exchange mutation"
        )
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return {
        "configured": True,
        "valid": valid,
        "status": "verified" if valid else "invalid",
        "checks_passed": checks_passed,
        "public_market_data_only": public_only,
        "contains_credentials": contains_credentials,
        "live_trading_enabled": payload.get("live_trading_enabled"),
        "exchange_mutation_enabled": payload.get("exchange_mutation_enabled"),
        "user_count": summary.get("user_count"),
        "trader_user_count": summary.get("trader_user_count"),
        "repository_account_count": summary.get("repository_account_count"),
        "warnings": [str(warning) for warning in warnings],
    }


def _number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _matches_account(account: dict[str, Any], trader_id: str | None, paper_account_id: str | None) -> bool:
    if not trader_id or not paper_account_id:
        return False
    return account.get("trader_id") == trader_id and account.get("paper_account_id") == paper_account_id


def _integrity_report(accounts: list[TraderPaperAccount]) -> dict[str, Any]:
    paper_owners: dict[str, set[str]] = {}
    scope_counts: dict[str, int] = {}
    for account in accounts:
        trader_id = str(account.get("trader_id") or "").strip()
        paper_account_id = str(account.get("paper_account_id") or "").strip()
        if paper_account_id:
            paper_owners.setdefault(paper_account_id, set()).add(trader_id or "missing_trader_id")
        if trader_id and paper_account_id:
            scope_key = f"{trader_id}:{paper_account_id}"
            scope_counts[scope_key] = scope_counts.get(scope_key, 0) + 1
    duplicate_paper_account_ids = sorted(
        paper_account_id
        for paper_account_id, owners in paper_owners.items()
        if len(owners) > 1
    )
    duplicate_account_scopes = sorted(
        scope_key
        for scope_key, count in scope_counts.items()
        if count > 1
    )
    ok = not duplicate_paper_account_ids and not duplicate_account_scopes
    return {
        "status": "ok" if ok else "conflict",
        "account_count": len(accounts),
        "unique_paper_account_scope": not duplicate_paper_account_ids,
        "duplicate_paper_account_ids": duplicate_paper_account_ids,
        "duplicate_account_scopes": duplicate_account_scopes,
        "repository_kind": LOCAL_TRADER_ACCOUNT_REPOSITORY_KIND,
        "production_repository": False,
        "contains_credentials": False,
        "live_trading_enabled": False,
        "exchange_mutation_enabled": False,
    }


def _readiness_report(accounts: list[TraderPaperAccount]) -> dict[str, Any]:
    integrity = _integrity_report(accounts)
    scope_smoke = _trader_account_scope_smoke_evidence()
    production_smoke = _production_repository_smoke_evidence()
    missing_fields = [
        "production_database_repository",
        "durable_tenant_constraints",
        "production_writer_validation",
        "migration_plan",
        "backup_restore_policy",
        "durable_retention_policy",
        "trader_account_scope_smoke_current_validation",
    ]
    if not scope_smoke["valid"]:
        missing_fields.append("trader_account_scope_smoke_artifact")
    if not production_smoke["valid"]:
        missing_fields.append("production_trader_repository_smoke_artifact")
    return {
        "status": "partial_local_repository",
        "repository_kind": LOCAL_TRADER_ACCOUNT_REPOSITORY_KIND,
        "production_repository": False,
        "durable_database_repository": False,
        "tenant_isolation_status": "local_scope_enforced" if integrity["status"] == "ok" else "local_scope_conflict",
        "unique_paper_account_scope": integrity["unique_paper_account_scope"],
        "paper_account_uniqueness_enforced": True,
        "trader_scope_required": True,
        "account_count": integrity["account_count"],
        "supported_local_domains": [
            "portfolio",
            "positions",
            "orders",
            "executions",
            "signals",
            "audit_events",
        ],
        "production_writer_validation": "pending",
        "migration_status": "pending",
        "backup_restore_status": "missing",
        "retention_policy_status": "local_only",
        "trader_account_scope_smoke_artifact_configured": bool(scope_smoke["configured"]),
        "trader_account_scope_smoke_artifact_valid": bool(scope_smoke["valid"]),
        "trader_account_scope_smoke_status": "artifact_present_pending_current_validation"
        if scope_smoke["valid"]
        else "missing",
        "trader_account_scope_smoke_evidence": scope_smoke,
        "production_trader_repository_smoke_artifact_configured": bool(production_smoke["configured"]),
        "production_trader_repository_smoke_artifact_valid": bool(production_smoke["valid"]),
        "production_trader_repository_smoke_status": "artifact_present_pending_current_validation"
        if production_smoke["valid"]
        else "missing",
        "production_trader_repository_smoke_evidence": production_smoke,
        "contains_credentials": False,
        "live_trading_enabled": False,
        "exchange_mutation_enabled": False,
        "missing_fields": missing_fields,
        "warnings": [
            "Local file repository is partial evidence only",
            "Production trader/account repositories and writer validation are pending",
            "Multi-trader account-scope smoke artifacts are artifact-present pending current validation only",
            "Production trader repository smoke artifacts are artifact-present pending current validation only",
            "No exchange secrets are stored",
            "No live exchange mutation is enabled",
            *[str(warning) for warning in scope_smoke["warnings"]],
            *[str(warning) for warning in production_smoke["warnings"]],
        ],
    }


class TraderAccountRepository:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(os.environ.get("ALPHAFORGE_TRADER_ACCOUNT_STORE", _default_store_path()))
        self._lock = threading.Lock()

    def _read(self) -> list[TraderPaperAccount]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        accounts = payload.get("accounts") if isinstance(payload, dict) else None
        return accounts if isinstance(accounts, list) else []

    def _write(self, accounts: list[TraderPaperAccount]) -> None:
        if _production_environment():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="production_trader_account_repository_required",
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps({"accounts": accounts}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def ensure_seed_accounts(self) -> None:
        if _production_environment():
            return
        enabled = os.environ.get("ALPHAFORGE_SEED_INITIAL_TRADER", "true").strip().lower()
        if enabled in {"0", "false", "no", "off"}:
            return
        trader_id = os.environ.get("ALPHAFORGE_INITIAL_TRADER_ID", "trader-wajidali1984").strip()
        paper_account_id = os.environ.get("ALPHAFORGE_INITIAL_TRADER_PAPER_ACCOUNT_ID", "paper-wajidali1984").strip()
        if not trader_id or not paper_account_id:
            return
        with self._lock:
            accounts = self._read()
            if any(
                account.get("trader_id") == trader_id
                or account.get("paper_account_id") == paper_account_id
                for account in accounts
            ):
                return
            now = _now()
            accounts.append(
                {
                    "trader_id": trader_id,
                    "paper_account_id": paper_account_id,
                    "currency": "USDT",
                    "equity": None,
                    "realized_pnl": None,
                    "unrealized_pnl": None,
                    "positions": [],
                    "orders": [],
                    "executions": [],
                    "signals": [],
                    "audit_events": [],
                    "source_status": "repository_seeded_balance_pending",
                    "created_at": now,
                    "updated_at": now,
                }
            )
            self._write(accounts)

    def get_account(self, *, trader_id: str | None, paper_account_id: str | None) -> TraderPaperAccount | None:
        self.ensure_seed_accounts()
        if not trader_id and not paper_account_id:
            return None
        return next(
            (
                account
                for account in self._read()
                if _matches_account(account, trader_id, paper_account_id)
            ),
            None,
        )

    def list_accounts(self) -> list[TraderPaperAccount]:
        self.ensure_seed_accounts()
        return self._read()

    def integrity_report(self) -> dict[str, Any]:
        self.ensure_seed_accounts()
        return _integrity_report(self._read())

    def readiness_report(self) -> dict[str, Any]:
        self.ensure_seed_accounts()
        return _readiness_report(self._read())

    def upsert_account(
        self,
        *,
        trader_id: str,
        paper_account_id: str,
        currency: str = "USDT",
        equity: float | None = None,
        realized_pnl: float | None = None,
        unrealized_pnl: float | None = None,
        positions: list[dict[str, Any]] | None = None,
        orders: list[dict[str, Any]] | None = None,
        executions: list[dict[str, Any]] | None = None,
        signals: list[dict[str, Any]] | None = None,
        audit_events: list[dict[str, Any]] | None = None,
        source_status: str = "manual_paper_repository_update",
    ) -> TraderPaperAccount:
        if not trader_id or not paper_account_id:
            raise ValueError("trader_id and paper_account_id are required")
        with self._lock:
            accounts = self._read()
            for account in accounts:
                if (
                    account.get("paper_account_id") == paper_account_id
                    and account.get("trader_id") != trader_id
                ):
                    raise ValueError("paper_account_id is already assigned to another trader")
            matching_indices = [
                index
                for index, account in enumerate(accounts)
                if _matches_account(account, trader_id, paper_account_id)
            ]
            if len(matching_indices) > 1:
                raise ValueError("paper_account_id has duplicate local repository rows")
            now = _now()
            next_account: TraderPaperAccount = {
                "trader_id": trader_id,
                "paper_account_id": paper_account_id,
                "currency": currency or "USDT",
                "equity": equity,
                "realized_pnl": realized_pnl,
                "unrealized_pnl": unrealized_pnl,
                "positions": positions or [],
                "orders": orders or [],
                "executions": executions or [],
                "signals": signals or [],
                "audit_events": audit_events or [],
                "source_status": source_status,
                "created_at": now,
                "updated_at": now,
            }
            for index, account in enumerate(accounts):
                if _matches_account(account, trader_id, paper_account_id):
                    next_account["created_at"] = account.get("created_at", now)
                    if positions is None and isinstance(account.get("positions"), list):
                        next_account["positions"] = account["positions"]
                    if orders is None and isinstance(account.get("orders"), list):
                        next_account["orders"] = account["orders"]
                    if executions is None and isinstance(account.get("executions"), list):
                        next_account["executions"] = account["executions"]
                    if signals is None and isinstance(account.get("signals"), list):
                        next_account["signals"] = account["signals"]
                    if audit_events is None and isinstance(account.get("audit_events"), list):
                        next_account["audit_events"] = account["audit_events"]
                    accounts[index] = next_account
                    self._write(accounts)
                    return next_account
            accounts.append(next_account)
            self._write(accounts)
            return next_account

    def append_paper_order(
        self,
        *,
        trader_id: str,
        paper_account_id: str,
        order: dict[str, Any],
    ) -> dict[str, Any]:
        if not trader_id or not paper_account_id:
            raise ValueError("trader_id and paper_account_id are required")
        with self._lock:
            accounts = self._read()
            now = _now()
            for index, account in enumerate(accounts):
                if not _matches_account(account, trader_id, paper_account_id):
                    continue
                current = dict(account)
                orders = current.get("orders") if isinstance(current.get("orders"), list) else []
                audit_events = current.get("audit_events") if isinstance(current.get("audit_events"), list) else []
                order_id = f"paper-{uuid4().hex[:12]}"
                audit_id = f"paper-audit-{uuid4().hex[:12]}"
                next_order = {
                    **order,
                    "id": order_id,
                    "order_id": order_id,
                    "trader_id": trader_id,
                    "paper_account_id": paper_account_id,
                    "audit_id": audit_id,
                    "audit_event": "paper_order_staged_local",
                    "time": now,
                    "created_at": now,
                    "updated_at": now,
                    "status": "open",
                    "mode": "paper",
                    "filled": 0,
                    "exchange_mutation_enabled": False,
                    "live_transport_enabled": False,
                }
                audit_event = chain_local_paper_audit_event(
                    {
                        "id": audit_id,
                        "audit_id": audit_id,
                        "audit_event": "paper_order_staged_local",
                        "action": "stage",
                        "order_id": order_id,
                        "trader_id": trader_id,
                        "paper_account_id": paper_account_id,
                        "mode": "paper",
                        "created_at": now,
                        "source": "Local paper repository audit",
                        "exchange_mutation_enabled": False,
                        "live_transport_enabled": False,
                    },
                    existing_events=audit_events,
                )
                append_local_paper_audit_event(audit_event)
                current["orders"] = [next_order, *orders]
                current["audit_events"] = [audit_event, *audit_events][:1000]
                current["updated_at"] = now
                current["source_status"] = "paper_order_repository_update"
                accounts[index] = current
                self._write(accounts)
                return next_order
        raise ValueError("paper account not found")

    def cancel_paper_order(
        self,
        *,
        trader_id: str,
        paper_account_id: str,
        order_id: str,
        reason: str = "Paper cancel requested",
    ) -> dict[str, Any]:
        if not trader_id or not paper_account_id or not order_id:
            raise ValueError("trader_id, paper_account_id, and order_id are required")
        with self._lock:
            accounts = self._read()
            now = _now()
            for account_index, account in enumerate(accounts):
                if not _matches_account(account, trader_id, paper_account_id):
                    continue
                current = dict(account)
                orders = current.get("orders") if isinstance(current.get("orders"), list) else []
                audit_events = current.get("audit_events") if isinstance(current.get("audit_events"), list) else []
                for order_index, order in enumerate(orders):
                    if not isinstance(order, dict):
                        continue
                    if order.get("id") != order_id and order.get("order_id") != order_id:
                        continue
                    status = str(order.get("status", "")).lower()
                    if status in {"filled", "canceled", "cancelled", "expired", "rejected"}:
                        raise ValueError("paper order is not cancelable")
                    next_order = dict(order)
                    audit_id = f"paper-audit-{uuid4().hex[:12]}"
                    next_order.update(
                        {
                            "status": "canceled",
                            "reason": reason,
                            "audit_id": audit_id,
                            "audit_event": "paper_order_canceled_local",
                            "canceled_at": now,
                            "updated_at": now,
                            "exchange_mutation_enabled": False,
                            "live_transport_enabled": False,
                        }
                    )
                    audit_event = chain_local_paper_audit_event(
                        {
                            "id": audit_id,
                            "audit_id": audit_id,
                            "audit_event": "paper_order_canceled_local",
                            "action": "cancel",
                            "order_id": order.get("order_id") or order.get("id"),
                            "trader_id": trader_id,
                            "paper_account_id": paper_account_id,
                            "mode": "paper",
                            "reason": reason,
                            "created_at": now,
                            "source": "Local paper repository audit",
                            "exchange_mutation_enabled": False,
                            "live_transport_enabled": False,
                        },
                        existing_events=audit_events,
                    )
                    append_local_paper_audit_event(audit_event)
                    orders[order_index] = next_order
                    current["orders"] = orders
                    current["audit_events"] = [audit_event, *audit_events][:1000]
                    current["updated_at"] = now
                    current["source_status"] = "paper_order_repository_update"
                    accounts[account_index] = current
                    self._write(accounts)
                    return next_order
        raise ValueError("paper order not found")

    def fill_paper_order(
        self,
        *,
        trader_id: str,
        paper_account_id: str,
        order_id: str,
        price: float | None = None,
        quantity: float | None = None,
        reason: str = "Manual paper fill",
    ) -> dict[str, Any]:
        if not trader_id or not paper_account_id or not order_id:
            raise ValueError("trader_id, paper_account_id, and order_id are required")
        with self._lock:
            accounts = self._read()
            now = _now()
            for account_index, account in enumerate(accounts):
                if not _matches_account(account, trader_id, paper_account_id):
                    continue
                current = dict(account)
                orders = current.get("orders") if isinstance(current.get("orders"), list) else []
                executions = current.get("executions") if isinstance(current.get("executions"), list) else []
                positions = current.get("positions") if isinstance(current.get("positions"), list) else []
                audit_events = current.get("audit_events") if isinstance(current.get("audit_events"), list) else []
                for order_index, order in enumerate(orders):
                    if not isinstance(order, dict):
                        continue
                    if order.get("id") != order_id and order.get("order_id") != order_id:
                        continue
                    status = str(order.get("status", "")).lower()
                    if status in {"filled", "canceled", "cancelled", "expired", "rejected"}:
                        raise ValueError("paper order is not fillable")
                    order_quantity = _number(order.get("quantity")) or _number(order.get("size")) or 0.0
                    already_filled = _number(order.get("filled")) or 0.0
                    remaining = max(0.0, order_quantity - already_filled)
                    fill_quantity = _number(quantity) if quantity is not None else remaining
                    fill_price = _number(price) if price is not None else None
                    if fill_price is None:
                        fill_price = _number(order.get("price"))
                    if fill_price is None and order_quantity > 0:
                        notional = _number(order.get("notional"))
                        fill_price = notional / order_quantity if notional is not None else None
                    if fill_quantity is None or fill_quantity <= 0 or fill_quantity > remaining:
                        raise ValueError("invalid paper fill quantity")
                    if fill_price is None or fill_price <= 0:
                        raise ValueError("invalid paper fill price")

                    symbol = str(order.get("symbol") or "").upper() or "UNKNOWN"
                    side = str(order.get("side") or "").lower()
                    if side not in {"buy", "sell"}:
                        raise ValueError("invalid paper order side")
                    signed_fill = fill_quantity if side == "buy" else -fill_quantity
                    next_filled = already_filled + fill_quantity
                    fill_notional = fill_quantity * fill_price
                    execution_id = f"paper-fill-{uuid4().hex[:12]}"
                    audit_id = f"paper-audit-{uuid4().hex[:12]}"
                    execution = {
                        "id": execution_id,
                        "execution_id": execution_id,
                        "audit_id": audit_id,
                        "audit_event": "paper_order_filled_local",
                        "order_id": order.get("order_id") or order.get("id"),
                        "time": now,
                        "created_at": now,
                        "symbol": symbol,
                        "side": side,
                        "price": fill_price,
                        "size": fill_quantity,
                        "quantity": fill_quantity,
                        "fee": fill_notional * 0.0004,
                        "slippage": 0,
                        "source": "Local paper fill writer",
                        "risk_result": "Paper fill writer only",
                        "reason": reason,
                        "mode": "paper",
                        "trader_id": trader_id,
                        "paper_account_id": paper_account_id,
                        "exchange_mutation_enabled": False,
                        "live_transport_enabled": False,
                    }
                    audit_event = chain_local_paper_audit_event(
                        {
                            "id": audit_id,
                            "audit_id": audit_id,
                            "audit_event": "paper_order_filled_local",
                            "action": "fill",
                            "order_id": order.get("order_id") or order.get("id"),
                            "execution_id": execution_id,
                            "trader_id": trader_id,
                            "paper_account_id": paper_account_id,
                            "symbol": symbol,
                            "side": side,
                            "price": fill_price,
                            "quantity": fill_quantity,
                            "mode": "paper",
                            "reason": reason,
                            "created_at": now,
                            "source": "Local paper repository audit",
                            "exchange_mutation_enabled": False,
                            "live_transport_enabled": False,
                        },
                        existing_events=audit_events,
                    )
                    append_local_paper_audit_event(audit_event)

                    next_order = dict(order)
                    next_order.update(
                        {
                            "filled": next_filled,
                            "status": "filled" if next_filled >= order_quantity else "partially_filled",
                            "average_fill_price": fill_price,
                            "last_fill_at": now,
                            "updated_at": now,
                            "audit_id": audit_id,
                            "audit_event": "paper_order_filled_local",
                            "exchange_mutation_enabled": False,
                            "live_transport_enabled": False,
                            "reason": "Paper order filled" if next_filled >= order_quantity else "Paper order partially filled",
                        }
                    )
                    orders[order_index] = next_order

                    next_positions: list[dict[str, Any]] = []
                    applied = False
                    for position in positions:
                        if not isinstance(position, dict):
                            continue
                        if str(position.get("symbol", "")).upper() != symbol:
                            next_positions.append(position)
                            continue
                        current_side = str(position.get("side") or "").lower()
                        current_quantity = _number(position.get("signed_quantity"))
                        if current_quantity is None:
                            absolute_quantity = _number(position.get("quantity")) or _number(position.get("size")) or 0.0
                            current_quantity = -absolute_quantity if current_side in {"short", "sell"} else absolute_quantity
                        current_entry = _number(position.get("entry_price")) or _number(position.get("entry")) or fill_price
                        new_quantity = current_quantity + signed_fill
                        if abs(new_quantity) < 1e-12:
                            applied = True
                            continue
                        if current_quantity == 0 or (current_quantity > 0 and signed_fill > 0) or (current_quantity < 0 and signed_fill < 0):
                            average_entry = (
                                (abs(current_quantity) * current_entry + abs(signed_fill) * fill_price)
                                / (abs(current_quantity) + abs(signed_fill))
                            )
                        elif abs(signed_fill) > abs(current_quantity):
                            average_entry = fill_price
                        else:
                            average_entry = current_entry
                        next_positions.append(
                            {
                                **position,
                                "symbol": symbol,
                                "trader_id": trader_id,
                                "paper_account_id": paper_account_id,
                                "side": "Long" if new_quantity > 0 else "Short",
                                "quantity": abs(new_quantity),
                                "signed_quantity": new_quantity,
                                "entry_price": average_entry,
                                "current_price": fill_price,
                                "notional": abs(new_quantity) * fill_price,
                                "unrealized_pnl": 0,
                                "unrealized_pnl_pct": 0,
                                "mode": "paper",
                                "opened_utc": position.get("opened_utc") or now,
                                "updated_at": now,
                                "source": "Local paper fill writer",
                            }
                        )
                        applied = True
                    if not applied and abs(signed_fill) > 0:
                        next_positions.append(
                            {
                                "symbol": symbol,
                                "trader_id": trader_id,
                                "paper_account_id": paper_account_id,
                                "side": "Long" if signed_fill > 0 else "Short",
                                "quantity": abs(signed_fill),
                                "signed_quantity": signed_fill,
                                "entry_price": fill_price,
                                "current_price": fill_price,
                                "notional": abs(signed_fill) * fill_price,
                                "unrealized_pnl": 0,
                                "unrealized_pnl_pct": 0,
                                "mode": "paper",
                                "opened_utc": now,
                                "updated_at": now,
                                "source": "Local paper fill writer",
                            }
                        )

                    current["orders"] = orders
                    current["executions"] = [execution, *executions]
                    current["positions"] = next_positions
                    current["audit_events"] = [audit_event, *audit_events][:1000]
                    current["updated_at"] = now
                    current["source_status"] = "paper_fill_repository_update"
                    accounts[account_index] = current
                    self._write(accounts)
                    return {"order": next_order, "execution": execution, "positions": next_positions}
        raise ValueError("paper order not found")


class SqlAlchemyTraderAccountRepository(TraderAccountRepository):
    def __init__(self, database_url: str | None = None) -> None:
        super().__init__(path=None)
        self.database_url = database_url if database_url is not None else _repository_database_url()

    def _require_database_url(self) -> str:
        if not self.database_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="trader_account_database_url_required",
            )
        return self.database_url

    def _ensure_schema(self, database_url: str) -> None:
        if not _repository_db_auto_create_enabled():
            return
        engine = create_engine(database_url, future=True)
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS alphaforge_trader_paper_accounts (
                        scope_key VARCHAR(256) PRIMARY KEY,
                        trader_id VARCHAR(128) NOT NULL,
                        paper_account_id VARCHAR(128) NOT NULL UNIQUE,
                        updated_at VARCHAR(64) NOT NULL,
                        payload_json TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_alphaforge_trader_paper_accounts_trader_id
                    ON alphaforge_trader_paper_accounts (trader_id)
                    """
                )
            )

    def _read(self) -> list[TraderPaperAccount]:
        database_url = self._require_database_url()
        try:
            self._ensure_schema(database_url)
            engine = create_engine(database_url, future=True)
            with engine.begin() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT payload_json
                        FROM alphaforge_trader_paper_accounts
                        ORDER BY trader_id ASC, paper_account_id ASC
                        """
                    )
                ).fetchall()
        except SQLAlchemyError as exc:
            if _production_environment():
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="trader_account_repository_unavailable",
                ) from exc
            return []
        accounts: list[TraderPaperAccount] = []
        for row in rows:
            try:
                payload = json.loads(row[0])
            except (TypeError, ValueError):
                continue
            if isinstance(payload, dict):
                accounts.append(payload)  # type: ignore[arg-type]
        return accounts

    def _write(self, accounts: list[TraderPaperAccount]) -> None:
        database_url = self._require_database_url()
        try:
            self._ensure_schema(database_url)
            engine = create_engine(database_url, future=True)
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM alphaforge_trader_paper_accounts"))
                for account in accounts:
                    trader_id = str(account.get("trader_id") or "").strip()
                    paper_account_id = str(account.get("paper_account_id") or "").strip()
                    if not trader_id or not paper_account_id:
                        continue
                    conn.execute(
                        text(
                            """
                            INSERT INTO alphaforge_trader_paper_accounts (
                                scope_key,
                                trader_id,
                                paper_account_id,
                                updated_at,
                                payload_json
                            )
                            VALUES (
                                :scope_key,
                                :trader_id,
                                :paper_account_id,
                                :updated_at,
                                :payload_json
                            )
                            """
                        ),
                        {
                            "scope_key": f"{trader_id}:{paper_account_id}",
                            "trader_id": trader_id,
                            "paper_account_id": paper_account_id,
                            "updated_at": str(account.get("updated_at") or _now()),
                            "payload_json": json.dumps(
                                account,
                                sort_keys=True,
                                separators=(",", ":"),
                                ensure_ascii=True,
                                default=str,
                            ),
                        },
                    )
        except SQLAlchemyError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="trader_account_repository_unavailable",
            ) from exc

    def integrity_report(self) -> dict[str, Any]:
        report = _integrity_report(self._read() if self.database_url else [])
        report.update(
            {
                "repository_kind": SQL_TRADER_ACCOUNT_REPOSITORY_KIND,
                "production_repository": bool(self.database_url),
                "database_url_configured": bool(self.database_url),
            }
        )
        return report

    def readiness_report(self) -> dict[str, Any]:
        report = _readiness_report(self._read() if self.database_url else [])
        missing_fields = [
            field
            for field in report["missing_fields"]
            if field != "production_database_repository" or not self.database_url
        ]
        report.update(
            {
                "status": "sqlalchemy_repository_configured"
                if self.database_url
                else "sqlalchemy_repository_missing_database_url",
                "repository_kind": SQL_TRADER_ACCOUNT_REPOSITORY_KIND,
                "production_repository": bool(self.database_url),
                "durable_database_repository": bool(self.database_url),
                "database_url_configured": bool(self.database_url),
                "migration_status": "auto_create_enabled" if _repository_db_auto_create_enabled() else "alembic_required",
                "retention_policy_status": "pending",
                "missing_fields": missing_fields,
                "warnings": [
                    "SQLAlchemy trader account repository is paper/read-only state only",
                    "Production writer validation, migrations, backup/restore, and retention policy remain pending",
                    "No exchange secrets are stored",
                    "No live exchange mutation is enabled",
                ],
            }
        )
        return report


def get_trader_account_repository() -> TraderAccountRepository:
    if _repository_backend() == SQL_TRADER_ACCOUNT_REPOSITORY_KIND:
        return SqlAlchemyTraderAccountRepository()
    return TraderAccountRepository()
