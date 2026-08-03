"""Budget-authorized HTTP transport for legacy Moralis read paths.

Every provider request reserves its estimated compute units in the durable
Redis authority before dispatch.  Every received response is reconciled from
its headers regardless of HTTP status.  Once dispatch begins, transport
failure is ambiguous and the conservative reservation remains charged.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import httpx
from app.services.smart_money_wallets.rate_limit import (
    MORALIS_TIMEOUT_SECONDS,
    MoralisRateLimiter,
)

DEFAULT_BASE_URL = "https://deep-index.moralis.io/api/v2.2"
DEFAULT_USER_AGENT = "aibot-v2-moralis-client/1.0 (+httpx)"


@dataclass(frozen=True)
class MoralisBudgetedHttpResult:
    """A secret-free request outcome with explicit CU-accounting evidence."""

    endpoint_id: str
    http_status: int | None
    payload: Any
    headers: dict[str, object]
    error_class: str | None
    request_dispatched: bool
    reserved_cu: int
    accounted_cu: int
    reconciliation_applied: bool

    @property
    def ok(self) -> bool:
        return (
            self.reconciliation_applied
            and self.http_status is not None
            and 200 <= int(self.http_status) <= 299
        )


def budgeted_moralis_get_json(
    *,
    api_key: str,
    endpoint_id: str,
    path: str,
    estimated_cu: int,
    limiter: MoralisRateLimiter,
    params: Mapping[str, object] | None = None,
    base_url: str = DEFAULT_BASE_URL,
    timeout_seconds: float = MORALIS_TIMEOUT_SECONDS,
    http_client: Any | None = None,
) -> MoralisBudgetedHttpResult:
    """Issue one GET only after durable CU reservation.

    The caller may inject an HTTP client for tests.  A failure raised from the
    ``get`` call is treated as possibly delivered; only failure while creating
    the owned client is provably pre-dispatch and eligible for a refund.
    """

    if not str(api_key or "").strip():
        return _result(
            endpoint_id=endpoint_id,
            error_class="API_KEY_MISSING",
        )

    decision = limiter.allow_request(estimated_cu=estimated_cu)
    if not decision.allowed:
        return _result(
            endpoint_id=endpoint_id,
            error_class=decision.reason,
        )
    if decision.reservation is None:
        # This helper exists specifically for real provider paths.  A local
        # in-memory allowance is not durable across processes or restarts.
        return _result(
            endpoint_id=endpoint_id,
            error_class="CU_LEDGER_REQUIRED",
        )

    reserved_cu = int(decision.reservation.reserved_cu)
    client = http_client
    close_client = client is None
    try:
        if client is None:
            client = httpx.Client(timeout=timeout_seconds)
    except Exception as exc:  # noqa: BLE001 - exact class is returned, never the secret/message
        refunded_cu = limiter.refund_pending(request_was_not_sent=True)
        return MoralisBudgetedHttpResult(
            endpoint_id=endpoint_id,
            http_status=None,
            payload=None,
            headers={},
            error_class=type(exc).__name__,
            request_dispatched=False,
            reserved_cu=reserved_cu,
            accounted_cu=0 if refunded_cu == reserved_cu else reserved_cu,
            reconciliation_applied=refunded_cu == reserved_cu,
        )

    try:
        response = client.get(
            f"{base_url.rstrip('/')}/{path.lstrip('/')}",
            headers={
                "X-API-Key": str(api_key),
                "accept": "application/json",
                "User-Agent": DEFAULT_USER_AGENT,
            },
            params=dict(params or {}),
        )
        headers = {str(key): value for key, value in response.headers.items()}
        limiter.observe_response(response.status_code)
        reconciliation = limiter.reconcile_response(
            reservation=decision.reservation,
            headers=headers,
            estimated_cu=estimated_cu,
            http_status=response.status_code,
        )
        payload = _safe_json(response) if reconciliation.applied else None
        return MoralisBudgetedHttpResult(
            endpoint_id=endpoint_id,
            http_status=int(response.status_code),
            payload=payload,
            headers=headers,
            error_class=None if reconciliation.applied else reconciliation.reason,
            request_dispatched=True,
            reserved_cu=reserved_cu,
            accounted_cu=(
                int(reconciliation.actual_cu) if reconciliation.applied else reserved_cu
            ),
            reconciliation_applied=bool(reconciliation.applied),
        )
    except Exception as exc:  # noqa: BLE001 - delivery is ambiguous after get() begins
        limiter.observe_response(None)
        retention = limiter.retain_ambiguous_reservation(decision.reservation)
        return MoralisBudgetedHttpResult(
            endpoint_id=endpoint_id,
            http_status=None,
            payload=None,
            headers={},
            error_class=type(exc).__name__,
            request_dispatched=True,
            reserved_cu=reserved_cu,
            accounted_cu=reserved_cu,
            reconciliation_applied=bool(retention is not None and retention.applied),
        )
    finally:
        if close_client:
            with suppress(Exception):
                client.close()


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:  # noqa: BLE001 - malformed provider JSON is a data outcome
        return None


def _result(
    *,
    endpoint_id: str,
    error_class: str,
) -> MoralisBudgetedHttpResult:
    return MoralisBudgetedHttpResult(
        endpoint_id=endpoint_id,
        http_status=None,
        payload=None,
        headers={},
        error_class=error_class,
        request_dispatched=False,
        reserved_cu=0,
        accounted_cu=0,
        reconciliation_applied=False,
    )
