from __future__ import annotations

import hashlib
import hmac
import io
import json
import logging
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from v2.backend.app.services.native_trainer import (
    binance_usdm_commission_capture_v1 as capture,
)
from v2.backend.app.services.native_trainer import causal_cost_evidence_v1
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)

_SYMBOL = "BTCUSDT"
_API_KEY = "unit-api-key-do-not-persist"
_API_SECRET = "unit-api-secret-do-not-persist"  # noqa: S105 - synthetic test value
_FINGERPRINT_KEY = b"separate-local-fingerprint-key-32-bytes-minimum"
_FALLBACK_REASON = "TRAINER_CAUSAL_FEE_CAPTURE_NO_WS_METHOD"
_RAW = (
    b'{"symbol":"BTCUSDT","makerCommissionRate":"0.00020000",'
    b'"takerCommissionRate":"0.00040000","rpiCommissionRate":"0.00010000"}'
)


class _Response:
    def __init__(
        self,
        content: bytes,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}


class _UrlopenResponse:
    def __init__(self, content: bytes, *, status_code: int = 200) -> None:
        self._content = content
        self.status = status_code
        self.headers: dict[str, str] = {}
        self.closed = False

    def read(self, limit: int) -> bytes:
        assert limit == capture.MAX_RAW_RESPONSE_BYTES + 1
        return self._content

    def close(self) -> None:
        self.closed = True


class _TrackingBody(io.BytesIO):
    def __init__(self, value: bytes) -> None:
        super().__init__(value)
        self.read_limits: list[int] = []
        self.closed_by_transport = False

    def read(self, size: int = -1) -> bytes:
        self.read_limits.append(size)
        return super().read(size)

    def close(self) -> None:
        self.closed_by_transport = True
        super().close()


class _Clock:
    def __init__(self, *values: datetime) -> None:
        self.values = list(values)
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        if not self.values:
            raise AssertionError("unexpected clock call")
        return self.values.pop(0)


def _store(tmp_path: Path) -> ImmutableSourcePayloadStore:
    return ImmutableSourcePayloadStore(tmp_path / "cas")


def _policy(
    store: ImmutableSourcePayloadStore,
    *,
    symbol: str = _SYMBOL,
    refresh_interval_seconds: int = 900,
) -> capture.BinanceUSDMCommissionRefreshPolicyTokenV1:
    return capture.build_binance_usdm_commission_refresh_policy_v1(
        store=store,
        symbol=symbol,
        policy_id="adaptive-fee-refresh",
        policy_version="v17",
        refresh_interval_seconds=refresh_interval_seconds,
        adaptive_input_receipt_sha256="a" * 64,
        generated_at="2026-07-21T11:59:50.000000Z",
        available_at="2026-07-21T11:59:50.100000Z",
        recorded_at="2026-07-21T11:59:50.200000Z",
    )


def _binding(
    *,
    api_key: str = _API_KEY,
    api_secret: str = _API_SECRET,
    account_specific: bool = True,
    read_only_ref: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        trader_id="trader-fixture",
        credential_ref="TRADER_BINANCE_READONLY",
        api_key=api_key,
        api_secret=api_secret,
        api_key_name="TRADER_BINANCE_READONLY_API_KEY",
        api_secret_name="TRADER_BINANCE_READONLY_API_SECRET",  # noqa: S106
        account_specific=account_specific,
        read_only_ref=read_only_ref,
        is_configured=bool(api_key and api_secret),
    )


def _allowed_decision(observed: list[dict[str, Any]] | None = None):
    def decide(**kwargs: Any) -> dict[str, Any]:
        if observed is not None:
            observed.append(dict(kwargs))
        return {
            "request_allowed": True,
            "request_weight": 20,
            "shared_budget_required": True,
            "budget_scope": "host_redis",
            "rest_used_as_primary": False,
            "transport_role": "fallback_only",
        }

    return decide


def _capture(
    monkeypatch: pytest.MonkeyPatch,
    store: ImmutableSourcePayloadStore,
    *,
    response: _Response | None = None,
    http_calls: list[dict[str, Any]] | None = None,
    budget_calls: list[dict[str, Any]] | None = None,
    binding: SimpleNamespace | None = None,
    clock: _Clock | None = None,
) -> capture.BinanceUSDMCommissionCaptureTokenV1:
    monkeypatch.setattr(
        capture,
        "resolve_binance_credential_binding",
        lambda: binding or _binding(),
    )
    monkeypatch.setattr(
        capture,
        "binance_rest_fallback_decision",
        _allowed_decision(budget_calls),
    )
    monkeypatch.setattr(
        capture,
        "report_binance_rest_response",
        lambda **_kwargs: True,
    )
    calls = http_calls if http_calls is not None else []

    def http_get(**kwargs: Any) -> _Response:
        calls.append(dict(kwargs))
        return response or _Response(_RAW)

    resolved_clock = clock or _Clock(
        datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC),
        datetime(2026, 7, 21, 12, 0, 0, 100_000, tzinfo=UTC),
        datetime(2026, 7, 21, 12, 0, 0, 200_000, tzinfo=UTC),
    )
    return capture.capture_binance_usdm_commission_rate_v1(
        store=store,
        symbol=_SYMBOL,
        refresh_policy=_policy(store),
        fallback_reason=_FALLBACK_REASON,
        credential_fingerprint_hmac_key=_FINGERPRINT_KEY,
        now_fn=resolved_clock,
        http_get=http_get,
    )


def test_factory_performs_exactly_one_signed_get_and_one_shared_weight_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    http_calls: list[dict[str, Any]] = []
    budget_calls: list[dict[str, Any]] = []

    token = _capture(
        monkeypatch,
        store,
        http_calls=http_calls,
        budget_calls=budget_calls,
    )

    assert budget_calls == [
        {
            "endpoint": "GET /fapi/v1/commissionRate",
            "fallback_reason": _FALLBACK_REASON,
            "role": "signed_read_recovery",
            "request_weight": 20,
            "require_shared_budget": True,
        }
    ]
    assert len(http_calls) == 1
    request = http_calls[0]
    assert request["method"] == "GET"
    assert request["url"] == "https://fapi.binance.com/fapi/v1/commissionRate"
    assert request["headers"] == {"X-MBX-APIKEY": _API_KEY}
    unsigned = {"symbol": _SYMBOL, "timestamp": 1_784_635_200_000}
    expected_signature = hmac.new(
        _API_SECRET.encode(),
        urlencode(unsigned).encode(),
        hashlib.sha256,
    ).hexdigest()
    assert request["params"] == {**unsigned, "signature": expected_signature}
    assert all(
        mutation not in request["url"]
        for mutation in ("/order", "/leverage", "/marginType", "/cancel")
    )
    assert token.request_weight == 20
    assert token.shared_budget_required is True
    assert token.read_only is True
    assert token.contract["places_real_order"] is False
    assert token.contract["leverage_mutated"] is False
    assert token.contract["margin_mutated"] is False


def test_exact_raw_bytes_are_immutable_and_artifact_is_causal_cost_compatible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    token = _capture(monkeypatch, store)

    assert token.raw_response_bytes == _RAW
    assert token.raw_response_sha256 == hashlib.sha256(_RAW).hexdigest()
    assert (
        store.get(
            token.raw_response_sha256,
            expected_byte_count=len(_RAW),
        )
        == _RAW
    )
    assert token.maker_commission_bps == pytest.approx(2.0)
    assert token.taker_commission_bps == pytest.approx(4.0)
    assert token.rpi_commission_bps == pytest.approx(1.0)
    fee_value, source, receipt, _objects = causal_cost_evidence_v1._validate_fee_evidence(
        store=store,
        artifact_bytes=token.fee_artifact_bytes,
        raw_response_bytes=token.raw_response_bytes,
        receipt=token.fee_schedule_receipt,
        symbol=_SYMBOL,
        decision_at=datetime(2026, 7, 21, 12, 5, tzinfo=UTC),
    )
    assert fee_value == pytest.approx(4.0)
    assert source["fallback_used"] is False
    assert receipt["receipt_sha256"] == token.fee_receipt_sha256


def test_no_secret_signature_or_credential_value_is_persisted_or_returned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    http_calls: list[dict[str, Any]] = []
    token = _capture(monkeypatch, store, http_calls=http_calls)
    signature = http_calls[0]["params"]["signature"]

    exposed = (
        repr(token)
        + json.dumps(token.contract, sort_keys=True)
        + token.fee_artifact_bytes.decode()
        + token.fee_receipt_bytes.decode()
        + token.sanitized_request_identity_bytes.decode()
        + token._refresh_policy.artifact_bytes.decode()
        + token._refresh_policy.receipt_bytes.decode()
    )
    for object_path in (tmp_path / "cas" / "sha256").glob("*/*"):
        exposed += object_path.read_bytes().decode("utf-8", errors="ignore")
    for secret in (_API_KEY, _API_SECRET, _FINGERPRINT_KEY.decode(), signature):
        assert secret not in exposed
    assert (
        token.credential_binding_fingerprint_sha256 != hashlib.sha256(_API_KEY.encode()).hexdigest()
    )
    assert token.contract["fee_artifact"]["sanitized_request_identity_sha256"] == (
        hashlib.sha256(token.sanitized_request_identity_bytes).hexdigest()
    )


def test_explicit_protected_binding_bypasses_ambient_credential_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    monkeypatch.setattr(
        capture,
        "resolve_binance_credential_binding",
        lambda: pytest.fail("ambient environment and repository files must not be resolved"),
    )
    monkeypatch.setattr(capture, "binance_rest_fallback_decision", _allowed_decision())
    http_calls: list[dict[str, Any]] = []

    token = capture.capture_binance_usdm_commission_rate_v1(
        store=store,
        symbol=_SYMBOL,
        refresh_policy=_policy(store),
        fallback_reason=_FALLBACK_REASON,
        credential_fingerprint_hmac_key=_FINGERPRINT_KEY,
        credential_binding=_binding(),
        now_fn=_Clock(
            datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC),
            datetime(2026, 7, 21, 12, 0, 0, 100_000, tzinfo=UTC),
            datetime(2026, 7, 21, 12, 0, 0, 200_000, tzinfo=UTC),
        ),
        http_get=lambda **kwargs: (http_calls.append(dict(kwargs)) or _Response(_RAW)),
    )

    assert token.read_only is True
    assert token.trainer_authority is False
    assert token.prediction_authority is False
    assert token.paper_authority is False
    assert token.live_authority is False
    assert len(http_calls) == 1
    assert http_calls[0]["method"] == "GET"
    assert http_calls[0]["url"] == "https://fapi.binance.com/fapi/v1/commissionRate"


def test_default_transport_never_logs_signed_url_or_api_credentials_at_info(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _store(tmp_path)
    monkeypatch.setattr(capture, "binance_rest_fallback_decision", _allowed_decision())
    observed: dict[str, Any] = {}

    def fake_urlopen(request: Any, *, timeout: float) -> _UrlopenResponse:
        observed["request"] = request
        observed["timeout"] = timeout
        response = _UrlopenResponse(_RAW)
        observed["response"] = response
        return response

    def fake_build_opener(*handlers: Any) -> SimpleNamespace:
        observed["handlers"] = handlers
        return SimpleNamespace(open=fake_urlopen)

    monkeypatch.setattr(capture.urllib.request, "build_opener", fake_build_opener)
    monkeypatch.setenv("HTTP_PROXY", "http://forbidden-proxy.invalid:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://forbidden-proxy.invalid:8080")
    monkeypatch.setenv("NO_PROXY", "")
    caplog.set_level(logging.INFO)

    token = capture.capture_binance_usdm_commission_rate_v1(
        store=store,
        symbol=_SYMBOL,
        refresh_policy=_policy(store),
        fallback_reason=_FALLBACK_REASON,
        credential_fingerprint_hmac_key=_FINGERPRINT_KEY,
        credential_binding=_binding(),
        now_fn=_Clock(
            datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC),
            datetime(2026, 7, 21, 12, 0, 0, 100_000, tzinfo=UTC),
            datetime(2026, 7, 21, 12, 0, 0, 200_000, tzinfo=UTC),
        ),
    )

    request = observed["request"]
    parsed_query = parse_qs(urlsplit(request.full_url).query)
    signature = parsed_query["signature"][0]
    request_headers = {key.lower(): value for key, value in request.header_items()}
    assert request.get_method() == "GET"
    assert request_headers["x-mbx-apikey"] == _API_KEY
    assert len(observed["handlers"]) == 2
    assert isinstance(observed["handlers"][0], capture.urllib.request.ProxyHandler)
    assert observed["handlers"][0].proxies == {}
    assert isinstance(observed["handlers"][1], capture._NoRedirectHandler)  # noqa: SLF001
    assert observed["handlers"][1].redirect_request(object()) is None
    assert observed["timeout"] == 10.0
    assert observed["response"].closed is True
    assert token.read_only is True
    assert not [
        record
        for record in caplog.records
        if record.name == "httpx" or record.name.startswith("httpcore")
    ]
    rendered_logs = caplog.text
    for secret in (_API_KEY, _API_SECRET, signature):
        assert secret not in rendered_logs


@pytest.mark.parametrize("status_code", [418, 429])
def test_default_transport_snapshots_http_error_without_logging_or_redirecting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    status_code: int,
) -> None:
    store = _store(tmp_path)
    monkeypatch.setattr(capture, "binance_rest_fallback_decision", _allowed_decision())
    cooldown_reports: list[dict[str, Any]] = []

    def report(**kwargs: Any) -> bool:
        cooldown_reports.append(dict(kwargs))
        return True

    monkeypatch.setattr(capture, "report_binance_rest_response", report)
    body = _TrackingBody(b"x" * (capture.MAX_RAW_RESPONSE_BYTES + 100))
    observed: dict[str, Any] = {"open_calls": 0}

    def raise_http_error(request: Any, *, timeout: float) -> None:
        observed["open_calls"] += 1
        observed["request"] = request
        observed["timeout"] = timeout
        raise capture.urllib.error.HTTPError(
            request.full_url,
            status_code,
            "sanitized-test-http-error",
            {"Retry-After": "181.5"},
            body,
        )

    def fake_build_opener(*handlers: Any) -> SimpleNamespace:
        observed["handlers"] = handlers
        return SimpleNamespace(open=raise_http_error)

    monkeypatch.setattr(capture.urllib.request, "build_opener", fake_build_opener)
    monkeypatch.setenv("HTTP_PROXY", "http://forbidden-proxy.invalid:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://forbidden-proxy.invalid:8080")
    caplog.set_level(logging.INFO)

    with pytest.raises(
        capture.BinanceUSDMCommissionCaptureV1RateLimitError,
        match=rf"COMMISSION_CAPTURE_BINANCE_HTTP_{status_code}_SHARED_COOLDOWN_ARMED",
    ):
        capture.capture_binance_usdm_commission_rate_v1(
            store=store,
            symbol=_SYMBOL,
            refresh_policy=_policy(store),
            fallback_reason=_FALLBACK_REASON,
            credential_fingerprint_hmac_key=_FINGERPRINT_KEY,
            credential_binding=_binding(),
            now_fn=_Clock(
                datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC),
                datetime(2026, 7, 21, 12, 0, 0, 100_000, tzinfo=UTC),
            ),
        )

    request = observed["request"]
    signature = parse_qs(urlsplit(request.full_url).query)["signature"][0]
    request_headers = {key.lower(): value for key, value in request.header_items()}
    assert request_headers["x-mbx-apikey"] == _API_KEY
    assert observed["open_calls"] == 1
    assert observed["timeout"] == 10.0
    assert len(observed["handlers"]) == 2
    assert isinstance(observed["handlers"][0], capture.urllib.request.ProxyHandler)
    assert observed["handlers"][0].proxies == {}
    redirect_handler = observed["handlers"][1]
    assert isinstance(redirect_handler, capture._NoRedirectHandler)  # noqa: SLF001
    assert redirect_handler.redirect_request(object()) is None
    assert body.read_limits == [capture.MAX_RAW_RESPONSE_BYTES + 1]
    assert body.closed_by_transport is True
    assert cooldown_reports == [
        {"status_code": status_code, "retry_after_seconds": 181.5}
    ]
    for secret in (_API_KEY, _API_SECRET, signature):
        assert secret not in caplog.text


def test_global_fallback_enable_is_required_before_budget_or_http(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    policy = _policy(store)
    monkeypatch.delenv("BINANCE_REST_FALLBACK_ALLOWED", raising=False)
    monkeypatch.setattr(capture, "resolve_binance_credential_binding", _binding)
    http_calls: list[dict[str, Any]] = []

    with pytest.raises(
        capture.BinanceUSDMCommissionCaptureV1ValidationError,
        match="COMMISSION_CAPTURE_REST_FALLBACK_OR_SHARED_BUDGET_BLOCKED",
    ):
        capture.capture_binance_usdm_commission_rate_v1(
            store=store,
            symbol=_SYMBOL,
            refresh_policy=policy,
            fallback_reason=_FALLBACK_REASON,
            credential_fingerprint_hmac_key=_FINGERPRINT_KEY,
            now_fn=_Clock(datetime(2026, 7, 21, 12, 0, tzinfo=UTC)),
            http_get=lambda **kwargs: http_calls.append(kwargs),
        )
    assert http_calls == []


def test_explicit_fallback_reason_is_required_without_budget_or_http(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    monkeypatch.setattr(capture, "resolve_binance_credential_binding", _binding)
    budget_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        capture,
        "binance_rest_fallback_decision",
        _allowed_decision(budget_calls),
    )
    with pytest.raises(
        capture.BinanceUSDMCommissionCaptureV1ValidationError,
        match="COMMISSION_CAPTURE_EXPLICIT_FALLBACK_REASON_REQUIRED",
    ):
        capture.capture_binance_usdm_commission_rate_v1(
            store=store,
            symbol=_SYMBOL,
            refresh_policy=_policy(store),
            fallback_reason="",
            credential_fingerprint_hmac_key=_FINGERPRINT_KEY,
            http_get=lambda **_kwargs: pytest.fail("HTTP must not run"),
        )
    assert budget_calls == []


def test_shared_budget_denial_blocks_before_http(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    monkeypatch.setattr(capture, "resolve_binance_credential_binding", _binding)
    budget_calls: list[dict[str, Any]] = []

    def deny(**kwargs: Any) -> dict[str, Any]:
        budget_calls.append(kwargs)
        return {"request_allowed": False}

    monkeypatch.setattr(capture, "binance_rest_fallback_decision", deny)
    with pytest.raises(
        capture.BinanceUSDMCommissionCaptureV1ValidationError,
        match="COMMISSION_CAPTURE_REST_FALLBACK_OR_SHARED_BUDGET_BLOCKED",
    ):
        capture.capture_binance_usdm_commission_rate_v1(
            store=store,
            symbol=_SYMBOL,
            refresh_policy=_policy(store),
            fallback_reason=_FALLBACK_REASON,
            credential_fingerprint_hmac_key=_FINGERPRINT_KEY,
            now_fn=_Clock(datetime(2026, 7, 21, 12, 0, tzinfo=UTC)),
            http_get=lambda **_kwargs: pytest.fail("HTTP must not run"),
        )
    assert len(budget_calls) == 1
    assert budget_calls[0]["request_weight"] == 20
    assert budget_calls[0]["require_shared_budget"] is True


@pytest.mark.parametrize("status_code", [418, 429])
def test_rate_limit_response_arms_shared_cooldown_once_without_json_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    store = _store(tmp_path)
    monkeypatch.setattr(capture, "resolve_binance_credential_binding", _binding)
    monkeypatch.setattr(
        capture,
        "binance_rest_fallback_decision",
        _allowed_decision(),
    )
    reports: list[dict[str, Any]] = []

    def report(**kwargs: Any) -> bool:
        reports.append(kwargs)
        return True

    monkeypatch.setattr(capture, "report_binance_rest_response", report)
    http_calls = 0

    def http_get(**_kwargs: Any) -> _Response:
        nonlocal http_calls
        http_calls += 1
        return _Response(
            b"not-json-and-must-not-be-parsed",
            status_code=status_code,
            headers={"Retry-After": "181.5"},
        )

    with pytest.raises(
        capture.BinanceUSDMCommissionCaptureV1RateLimitError,
        match=rf"COMMISSION_CAPTURE_BINANCE_HTTP_{status_code}_SHARED_COOLDOWN_ARMED",
    ):
        capture.capture_binance_usdm_commission_rate_v1(
            store=store,
            symbol=_SYMBOL,
            refresh_policy=_policy(store),
            fallback_reason=_FALLBACK_REASON,
            credential_fingerprint_hmac_key=_FINGERPRINT_KEY,
            now_fn=_Clock(
                datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
                datetime(2026, 7, 21, 12, 0, 0, 1, tzinfo=UTC),
            ),
            http_get=http_get,
        )
    assert http_calls == 1
    assert reports == [{"status_code": status_code, "retry_after_seconds": 181.5}]


def test_rate_limit_fails_closed_when_shared_cooldown_cannot_persist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    monkeypatch.setattr(capture, "resolve_binance_credential_binding", _binding)
    monkeypatch.setattr(capture, "binance_rest_fallback_decision", _allowed_decision())
    monkeypatch.setattr(capture, "report_binance_rest_response", lambda **_kwargs: False)
    with pytest.raises(
        capture.BinanceUSDMCommissionCaptureV1RateLimitError,
        match="COMMISSION_CAPTURE_SHARED_COOLDOWN_PERSISTENCE_FAILED",
    ):
        capture.capture_binance_usdm_commission_rate_v1(
            store=store,
            symbol=_SYMBOL,
            refresh_policy=_policy(store),
            fallback_reason=_FALLBACK_REASON,
            credential_fingerprint_hmac_key=_FINGERPRINT_KEY,
            now_fn=_Clock(
                datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
                datetime(2026, 7, 21, 12, 0, 0, 1, tzinfo=UTC),
            ),
            http_get=lambda **_kwargs: _Response(b"{}", status_code=429),
        )


@pytest.mark.parametrize(
    "raw",
    [
        b'{"symbol":"BTCUSDT","makerCommissionRate":"0.1","takerCommissionRate":"0.2"}',
        b'{"symbol":"BTCUSDT","makerCommissionRate":"0.1","takerCommissionRate":"0.2","rpiCommissionRate":"0.3","extra":"x"}',
        b'{"symbol":"ETHUSDT","makerCommissionRate":"0.1","takerCommissionRate":"0.2","rpiCommissionRate":"0.3"}',
        b'{"symbol":"BTCUSDT","makerCommissionRate":0.1,"takerCommissionRate":"0.2","rpiCommissionRate":"0.3"}',
        b'{"symbol":"BTCUSDT","symbol":"BTCUSDT","makerCommissionRate":"0.1","takerCommissionRate":"0.2","rpiCommissionRate":"0.3"}',
    ],
)
def test_exact_current_four_field_response_shape_is_mandatory_without_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw: bytes,
) -> None:
    store = _store(tmp_path)
    with pytest.raises(capture.BinanceUSDMCommissionCaptureV1ValidationError):
        _capture(monkeypatch, store, response=_Response(raw))
    # The exact raw bytes were captured before the shape/parser rejected them.
    assert store.path_for(hashlib.sha256(raw).hexdigest()).is_file()


def test_http_200_is_required_without_using_error_payload_as_fee(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(
        capture.BinanceUSDMCommissionCaptureV1ValidationError,
        match="COMMISSION_CAPTURE_HTTP_200_REQUIRED",
    ):
        _capture(
            monkeypatch,
            _store(tmp_path),
            response=_Response(_RAW, status_code=500),
        )


def test_transport_exception_is_not_chained_and_cannot_leak_signed_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    monkeypatch.setattr(capture, "resolve_binance_credential_binding", _binding)
    monkeypatch.setattr(capture, "binance_rest_fallback_decision", _allowed_decision())

    def fail(**kwargs: Any) -> None:
        raise RuntimeError(f"leak {_API_KEY} {_API_SECRET} {kwargs['params']['signature']}")

    with pytest.raises(capture.BinanceUSDMCommissionCaptureV1TransportError) as caught:
        capture.capture_binance_usdm_commission_rate_v1(
            store=store,
            symbol=_SYMBOL,
            refresh_policy=_policy(store),
            fallback_reason=_FALLBACK_REASON,
            credential_fingerprint_hmac_key=_FINGERPRINT_KEY,
            now_fn=_Clock(datetime(2026, 7, 21, 12, 0, tzinfo=UTC)),
            http_get=fail,
        )
    assert str(caught.value) == "COMMISSION_CAPTURE_HTTP_GET_FAILED"
    assert caught.value.__cause__ is None
    assert _API_KEY not in repr(caught.value)
    assert _API_SECRET not in repr(caught.value)


def test_cas_tampering_is_detected_on_every_token_readback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    token = _capture(monkeypatch, store)
    object_path = store.path_for(token.raw_response_sha256)
    object_path.chmod(0o600)
    object_path.write_bytes(b"tampered")
    with pytest.raises(capture.BinanceUSDMCommissionCaptureV1IntegrityError):
        _ = token.contract


def test_token_field_and_clock_tampering_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _capture(monkeypatch, _store(tmp_path))
    with pytest.raises(capture.BinanceUSDMCommissionCaptureV1Error):
        _ = replace(token, raw_response_bytes=b"{}").contract
    with pytest.raises(capture.BinanceUSDMCommissionCaptureV1Error):
        _ = replace(
            token,
            response_observed_at="2026-07-21T11:59:59.000000Z",
        ).contract


def test_refresh_policy_is_explicit_durable_adaptive_and_safety_bounded(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    policy = _policy(store, refresh_interval_seconds=3_599)
    artifact = policy.artifact
    receipt = policy.receipt
    assert artifact["refresh_interval_seconds"] == 3_599
    assert artifact["static_market_threshold_used"] is False
    assert artifact["fallback_used"] is False
    assert artifact["adaptive_input_receipt_sha256"] == "a" * 64
    assert receipt["receipt_kind"] == "DURABLE_CAS_APPEND"
    assert receipt["receipt_sha256"] == policy.receipt_sha256
    assert (
        store.get(
            policy.receipt_address.payload_sha256,
            expected_byte_count=policy.receipt_address.payload_byte_count,
        )
        == policy.receipt_bytes
    )
    with pytest.raises(
        capture.BinanceUSDMCommissionCaptureV1ValidationError,
        match="COMMISSION_REFRESH_INTERVAL_OUTSIDE_IMMUTABLE_SAFETY_HORIZON",
    ):
        _policy(store, refresh_interval_seconds=3_601)


def test_refresh_policy_clock_and_token_tampering_fail_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(
        capture.BinanceUSDMCommissionCaptureV1ValidationError,
        match="COMMISSION_REFRESH_POLICY_CLOCK_ORDER_INVALID",
    ):
        capture.build_binance_usdm_commission_refresh_policy_v1(
            store=store,
            symbol=_SYMBOL,
            policy_id="adaptive-fee-refresh",
            policy_version="v17",
            refresh_interval_seconds=900,
            adaptive_input_receipt_sha256="a" * 64,
            generated_at="2026-07-21T11:59:50.200000Z",
            available_at="2026-07-21T11:59:50.100000Z",
            recorded_at="2026-07-21T11:59:50.300000Z",
        )
    policy = _policy(store)
    with pytest.raises(capture.BinanceUSDMCommissionCaptureV1Error):
        _ = replace(policy, receipt_sha256="b" * 64).receipt


@pytest.mark.parametrize(
    "binding",
    [
        _binding(api_key="", api_secret=""),
        _binding(account_specific=False),
        _binding(read_only_ref=False),
    ],
)
def test_invalid_credential_binding_fails_before_budget_or_http(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    binding: SimpleNamespace,
) -> None:
    store = _store(tmp_path)
    budget_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(capture, "resolve_binance_credential_binding", lambda: binding)
    monkeypatch.setattr(
        capture,
        "binance_rest_fallback_decision",
        _allowed_decision(budget_calls),
    )
    with pytest.raises(capture.BinanceUSDMCommissionCaptureV1ValidationError):
        capture.capture_binance_usdm_commission_rate_v1(
            store=store,
            symbol=_SYMBOL,
            refresh_policy=_policy(store),
            fallback_reason=_FALLBACK_REASON,
            credential_fingerprint_hmac_key=_FINGERPRINT_KEY,
            http_get=lambda **_kwargs: pytest.fail("HTTP must not run"),
        )
    assert budget_calls == []


def test_policy_must_preexist_request_and_match_symbol(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    monkeypatch.setattr(capture, "resolve_binance_credential_binding", _binding)
    monkeypatch.setattr(capture, "binance_rest_fallback_decision", _allowed_decision())
    with pytest.raises(
        capture.BinanceUSDMCommissionCaptureV1ValidationError,
        match="COMMISSION_CAPTURE_REFRESH_POLICY_NOT_AVAILABLE_AT_REQUEST",
    ):
        capture.capture_binance_usdm_commission_rate_v1(
            store=store,
            symbol=_SYMBOL,
            refresh_policy=_policy(store),
            fallback_reason=_FALLBACK_REASON,
            credential_fingerprint_hmac_key=_FINGERPRINT_KEY,
            now_fn=_Clock(datetime(2026, 7, 21, 11, 0, tzinfo=UTC)),
            http_get=lambda **_kwargs: pytest.fail("HTTP must not run"),
        )
    with pytest.raises(
        capture.BinanceUSDMCommissionCaptureV1ValidationError,
        match="COMMISSION_CAPTURE_REFRESH_POLICY_SYMBOL_MISMATCH",
    ):
        capture.capture_binance_usdm_commission_rate_v1(
            store=store,
            symbol=_SYMBOL,
            refresh_policy=_policy(store, symbol="ETHUSDT"),
            fallback_reason=_FALLBACK_REASON,
            credential_fingerprint_hmac_key=_FINGERPRINT_KEY,
            http_get=lambda **_kwargs: pytest.fail("HTTP must not run"),
        )


def test_shared_scope_contract_cannot_be_spoofed_as_process_local(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    monkeypatch.setattr(capture, "resolve_binance_credential_binding", _binding)

    def local_only(**_kwargs: Any) -> dict[str, Any]:
        return {
            "request_allowed": True,
            "request_weight": 20,
            "shared_budget_required": True,
            "budget_scope": "process_local",
            "rest_used_as_primary": False,
            "transport_role": "fallback_only",
        }

    monkeypatch.setattr(capture, "binance_rest_fallback_decision", local_only)
    with pytest.raises(
        capture.BinanceUSDMCommissionCaptureV1IntegrityError,
        match="COMMISSION_CAPTURE_SHARED_BUDGET_DECISION_INVALID",
    ):
        capture.capture_binance_usdm_commission_rate_v1(
            store=store,
            symbol=_SYMBOL,
            refresh_policy=_policy(store),
            fallback_reason=_FALLBACK_REASON,
            credential_fingerprint_hmac_key=_FINGERPRINT_KEY,
            now_fn=_Clock(datetime(2026, 7, 21, 12, 0, tzinfo=UTC)),
            http_get=lambda **_kwargs: pytest.fail("HTTP must not run"),
        )
