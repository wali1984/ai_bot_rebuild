from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from v2.backend.app.services import (
    binance_unified_websocket_transport as fallback_policy,
)
from v2.backend.app.services import binance_usdm_leverage_bracket_evidence as mod
from v2.backend.app.services.execution import binance_usdm_adapter as adapter_mod

NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
CONSUMER_NOW = NOW + timedelta(minutes=5)
TEST_HMAC_KEY = "test-only-bracket-evidence-hmac-key-32-bytes-minimum"
TEST_HMAC_KEY_ID = "test-bracket-key-v1"


def _security_context(
    *,
    trader_id: str = "trader-test",
    credential_ref: str = "TEST_BINANCE_READONLY",
    base_url: str = mod.MAINNET_BASE_URL,
    hmac_key: str = TEST_HMAC_KEY,
    auth_key_id: str = TEST_HMAC_KEY_ID,
) -> mod.EvidenceSecurityContext:
    return mod.build_evidence_security_context(
        trader_id=trader_id,
        credential_ref=credential_ref,
        base_url=base_url,
        credential_account_specific=True,
        hmac_key=hmac_key,
        auth_key_id=auth_key_id,
    )


SECURITY = _security_context()


def _row(symbol: str = "BTCUSDT", **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "symbol": symbol,
        "notionalCoef": 1.5,
        "brackets": [
            {
                "bracket": 1,
                "initialLeverage": 75,
                "notionalFloor": 0,
                "notionalCap": 10_000,
                "maintMarginRatio": 0.0065,
                "cum": 0,
            },
            {
                "bracket": 2,
                "initialLeverage": 50,
                "notionalFloor": 10_000,
                "notionalCap": 50_000,
                "maintMarginRatio": 0.01,
                "cum": 35,
            },
        ],
    }
    row.update(overrides)
    return row


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def set(self, key: str, value: str, *, ex: int) -> bool:
        self.values[key] = value
        self.ttls[key] = ex
        return True

    def get(self, key: str) -> str | None:
        return self.values.get(key)


class FakeAdapter:
    def __init__(
        self,
        response: Any,
        *,
        status: str = "SIGNED_READ_EXECUTED",
        base_url: str = mod.MAINNET_BASE_URL,
    ) -> None:
        self.response = response
        self.status = status
        self.base_url = base_url
        self.calls: list[dict[str, Any]] = []

    def signed_get(
        self,
        path: str,
        params: dict[str, Any] | None,
        *,
        execute: bool,
        fallback_reason: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "path": path,
                "params": params,
                "execute": execute,
                "fallback_reason": fallback_reason,
            }
        )
        return {
            "status": self.status,
            "http_status_code": 200,
            "response_json": self.response,
            # These exchange credentials/signatures must never be propagated.
            "headers": {"X-MBX-APIKEY": "DO_NOT_STORE"},
            "params_redacted": {"signature": "DO_NOT_STORE"},
        }


class FakeSharedBudgetRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.reserve_calls: list[tuple[str, int, int, int]] = []

    def ttl(self, _key: str) -> int:
        return -2

    def eval(
        self,
        _script: str,
        key_count: int,
        key: str,
        request_weight: int,
        budget: int,
        ttl_ms: int,
    ) -> list[int]:
        assert key_count == 1
        self.reserve_calls.append((key, request_weight, budget, ttl_ms))
        current = self.counts.get(key, 0)
        proposed = current + request_weight
        if proposed > budget:
            return [0, current, ttl_ms]
        self.counts[key] = proposed
        return [1, proposed, ttl_ms]


class SequenceClock:
    def __init__(self, *values: datetime) -> None:
        self.values = list(values)

    def __call__(self) -> datetime:
        return self.values.pop(0)


def _cache(
    redis: FakeRedis,
    *,
    row: dict[str, Any] | None = None,
    security_context: mod.EvidenceSecurityContext = SECURITY,
) -> dict[str, Any]:
    payload = mod.build_symbol_evidence(
        row or _row(),
        security_context=security_context,
        fetched_at=NOW,
        freshness_seconds=600,
        cache_ttl_seconds=900,
    )
    redis.set(
        mod.redis_key(payload["symbol"], security_context=security_context),
        json.dumps(payload),
        ex=900,
    )
    return payload


def _select(
    redis: FakeRedis,
    *,
    security_context: mod.EvidenceSecurityContext = SECURITY,
    symbol: str = "BTCUSDT",
    candidate_notional: Any = 100,
    decision_time: Any = CONSUMER_NOW,
    now_fn: Any = None,
) -> dict[str, Any]:
    return mod.select_paper_bracket_evidence(
        redis,
        security_context=security_context,
        symbol=symbol,
        candidate_notional=candidate_notional,
        decision_time=decision_time,
        now_fn=now_fn or (lambda: CONSUMER_NOW),
    )


def test_security_context_requires_safe_exact_account_environment_and_auth() -> None:
    assert mod.SCHEMA_VERSION == "v2_binance_usdm_leverage_bracket_evidence_v3"
    assert mod.STATUS_SCHEMA_VERSION == "v2_binance_usdm_leverage_bracket_evidence_status_v3"
    assert SECURITY.exchange_environment == "mainnet"
    assert SECURITY.base_url_origin == mod.MAINNET_BASE_URL
    assert SECURITY.binding_id == ("mainnet:trader-test:TEST_BINANCE_READONLY")
    assert TEST_HMAC_KEY not in repr(SECURITY)
    assert TEST_HMAC_KEY not in json.dumps(SECURITY.safe_metadata())

    with pytest.raises(
        mod.LeverageBracketEvidenceError,
        match="EVIDENCE_HMAC_KEY_MISSING_OR_TOO_SHORT",
    ):
        _security_context(hmac_key="too-short")
    with pytest.raises(mod.LeverageBracketEvidenceError, match="CREDENTIAL_REF_UNSAFE"):
        _security_context(credential_ref="unsafe:credential")
    with pytest.raises(
        mod.LeverageBracketEvidenceError,
        match="BINANCE_BASE_URL_ENVIRONMENT_UNRECOGNIZED",
    ):
        _security_context(base_url="https://example.com")
    with pytest.raises(
        mod.LeverageBracketEvidenceError,
        match="BINANCE_BASE_URL_NOT_SAFE_ORIGIN",
    ):
        _security_context(base_url="https://fapi.binance.com:bad")


def test_security_context_from_env_fails_closed_when_key_or_key_id_missing() -> None:
    common: dict[str, Any] = {
        "trader_id": "trader-test",
        "credential_ref": "TEST_BINANCE_READONLY",
        "base_url": mod.MAINNET_BASE_URL,
        "credential_account_specific": True,
    }
    with pytest.raises(mod.LeverageBracketEvidenceError):
        mod.evidence_security_context_from_env(**common, environ={})
    with pytest.raises(mod.LeverageBracketEvidenceError):
        mod.evidence_security_context_from_env(
            **common,
            environ={mod.HMAC_KEY_ENV: TEST_HMAC_KEY},
        )


def test_redis_keys_are_exactly_account_and_environment_scoped() -> None:
    other = _security_context(credential_ref="OTHER_BINANCE_READONLY")
    testnet = _security_context(base_url=mod.TESTNET_BASE_URL)

    assert mod.redis_key("btcusdt", security_context=SECURITY) == (
        "v2:binance_usdm:leverage_bracket:mainnet:" "trader-test:TEST_BINANCE_READONLY:BTCUSDT"
    )
    assert mod.redis_status_key(security_context=SECURITY) == (
        "v2:binance_usdm:leverage_bracket_status:mainnet:" "trader-test:TEST_BINANCE_READONLY"
    )
    key = mod.redis_key("BTCUSDT", security_context=SECURITY)
    assert mod.allowed_redis_key(key, security_context=SECURITY) is True
    assert mod.allowed_redis_key(key, security_context=other) is False
    assert mod.allowed_redis_key(key, security_context=testnet) is False


def test_build_symbol_evidence_is_sealed_account_scoped_and_read_only() -> None:
    payload = mod.build_symbol_evidence(
        _row(),
        security_context=SECURITY,
        fetched_at=NOW,
        freshness_seconds=600,
        cache_ttl_seconds=900,
    )

    assert payload["schema_version"] == mod.SCHEMA_VERSION
    assert payload["symbol"] == "BTCUSDT"
    assert payload["source"] == mod.SOURCE
    assert payload["security_type"] == "USER_DATA"
    assert payload["exchange_environment"] == "mainnet"
    assert payload["credential_binding_id"] == SECURITY.binding_id
    assert payload["evidence_auth_key_id"] == TEST_HMAC_KEY_ID
    assert payload["notionalCoef"] == 1.5
    assert payload["brackets"][0]["notionalFloor"] == 0.0
    assert payload["brackets"][1]["maintMarginRatio"] == 0.01
    assert payload["fetch_started_at"] == "2026-07-17T12:00:00.000000Z"
    assert payload["fetched_at"] == "2026-07-17T12:00:00.000000Z"
    assert payload["generated_at"] == "2026-07-17T12:00:00.000000Z"
    assert payload["ingested_at"] == "2026-07-17T12:00:00.000000Z"
    assert payload["available_at"] == "2026-07-17T12:00:00.000000Z"
    assert payload["expires_at"] == "2026-07-17T12:10:00.000000Z"
    assert payload["cache_expires_at"] == "2026-07-17T12:15:00.000000Z"
    assert "IMMEDIATELY_BEFORE_FINAL_SEAL_AND_ATOMIC_REDIS_SET" in payload["available_at_semantics"]
    assert "NOT_A_REDIS_COMMIT_ACK" in payload["available_at_semantics"]
    assert len(payload["content_checksum_sha256"]) == 64
    assert len(payload["evidence_hmac_sha256"]) == 64
    assert payload["maintenance_margin_formula"] == ("MAX(0,NOTIONAL*maintMarginRatio-cum)")
    assert payload["places_real_order"] is False
    assert payload["leverage_mutated"] is False
    assert payload["margin_mutated"] is False
    assert payload["raw_response_stored"] is False
    assert payload["credential_fields_stored"] is False
    assert payload["safe_binding_identifiers_stored"] is True
    assert payload["exchange_api_key_stored"] is False
    assert payload["exchange_api_secret_stored"] is False
    assert payload["signed_request_fields_stored"] is False
    assert TEST_HMAC_KEY not in json.dumps(payload)


def test_build_symbol_evidence_preserves_absent_optional_notional_coefficient() -> None:
    row = _row()
    row.pop("notionalCoef")

    payload = mod.build_symbol_evidence(
        row,
        security_context=SECURITY,
        fetched_at=NOW,
    )

    assert payload["notionalCoef"] is None


def test_build_symbol_evidence_distinguishes_and_orders_publication_times() -> None:
    payload = mod.build_symbol_evidence(
        _row(),
        security_context=SECURITY,
        fetch_started_at=NOW,
        fetched_at=NOW + timedelta(seconds=1),
        generated_at=NOW + timedelta(seconds=2),
        ingested_at=NOW + timedelta(seconds=3),
        available_at=NOW + timedelta(seconds=4),
    )
    assert payload["fetch_started_at"] == "2026-07-17T12:00:00.000000Z"
    assert payload["fetched_at"] == "2026-07-17T12:00:01.000000Z"
    assert payload["generated_at"] == "2026-07-17T12:00:02.000000Z"
    assert payload["ingested_at"] == "2026-07-17T12:00:03.000000Z"
    assert payload["available_at"] == "2026-07-17T12:00:04.000000Z"

    with pytest.raises(
        mod.LeverageBracketEvidenceError,
        match="PUBLICATION_TIMESTAMP_ORDER_INVALID",
    ):
        mod.build_symbol_evidence(
            _row(),
            security_context=SECURITY,
            fetched_at=NOW,
            generated_at=NOW - timedelta(microseconds=1),
        )


@pytest.mark.parametrize(
    "bad_row",
    [
        _row(brackets=[]),
        _row(
            brackets=[
                {
                    "bracket": 1,
                    "initialLeverage": 75,
                    "notionalFloor": 0,
                    "notionalCap": 10_000,
                    "maintMarginRatio": 0,
                    "cum": 0,
                }
            ]
        ),
        _row(
            brackets=[
                {
                    "bracket": 1,
                    "initialLeverage": 75,
                    "notionalFloor": 10,
                    "notionalCap": 10_000,
                    "maintMarginRatio": 0.0065,
                    "cum": 0,
                }
            ]
        ),
        _row(notionalCoef=float("nan")),
    ],
)
def test_build_symbol_evidence_rejects_malformed_source_rows(
    bad_row: dict[str, Any],
) -> None:
    with pytest.raises(mod.LeverageBracketEvidenceError):
        mod.build_symbol_evidence(
            bad_row,
            security_context=SECURITY,
            fetched_at=NOW,
        )


def test_build_rejects_invalid_binance_cum_recurrence() -> None:
    row = _row()
    row["brackets"][1]["cum"] = 34
    with pytest.raises(
        mod.LeverageBracketEvidenceError,
        match="BRACKET_CUM_RECURRENCE_INVALID",
    ):
        mod.build_symbol_evidence(
            row,
            security_context=SECURITY,
            fetched_at=NOW,
        )


def test_fetch_uses_exact_read_only_signed_get_and_scoped_cache() -> None:
    redis = FakeRedis()
    adapter = FakeAdapter([_row()])

    status = mod.fetch_and_cache_leverage_brackets(
        adapter=adapter,
        redis_client=redis,
        security_context=SECURITY,
        symbols=["btcusdt"],
        execute=True,
        freshness_seconds=600,
        cache_ttl_seconds=900,
        now_fn=lambda: NOW,
    )

    assert status["status"] == "READY"
    assert status["symbols_published"] == ["BTCUSDT"]
    assert status["credential_binding_id"] == SECURITY.binding_id
    assert adapter.calls == [
        {
            "path": "/fapi/v1/leverageBracket",
            "params": {"symbol": "BTCUSDT"},
            "execute": True,
            "fallback_reason": mod.REST_FALLBACK_REASON,
        }
    ]
    key = mod.redis_key("BTCUSDT", security_context=SECURITY)
    assert redis.ttls[key] == 900
    stored = json.loads(redis.values[key])
    serialized_cache = json.dumps(redis.values)
    assert stored["brackets"][0]["initialLeverage"] == 75
    assert "DO_NOT_STORE" not in serialized_cache
    assert "X-MBX-APIKEY" not in serialized_cache
    assert TEST_HMAC_KEY not in serialized_cache
    assert stored["places_real_order"] is False


def test_real_adapter_shared_budget_charges_once_and_blocks_exhausted_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_budget = FakeSharedBudgetRedis()
    http_calls: list[dict[str, Any]] = []

    class FakeHTTPClient:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 10.0

        def __enter__(self) -> FakeHTTPClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def get(
            self,
            url: str,
            *,
            params: dict[str, Any],
            headers: dict[str, str],
        ) -> Any:
            http_calls.append({"url": url, "params": params, "headers": headers})
            return adapter_mod.httpx.Response(200, json=[_row()])

    monkeypatch.setenv(fallback_policy.REST_FALLBACK_ENV, "true")
    monkeypatch.setenv(fallback_policy.REST_FALLBACK_BUDGET_PER_MINUTE_ENV, "1")
    monkeypatch.setattr(fallback_policy, "_REST_BUDGET_REDIS_CLIENT", shared_budget)
    monkeypatch.setattr(fallback_policy, "_REST_BUDGET_REDIS_TRIED", True)
    monkeypatch.setattr(adapter_mod.httpx, "Client", FakeHTTPClient)

    redis = FakeRedis()
    adapter = adapter_mod.BinanceUSDMAdapter(
        api_key=TEST_HMAC_KEY_ID,
        api_secret=f"{TEST_HMAC_KEY}-exchange",
        base_url=mod.MAINNET_BASE_URL,
    )
    first_status = mod.fetch_and_cache_leverage_brackets(
        adapter=adapter,
        redis_client=redis,
        security_context=SECURITY,
        symbols=["BTCUSDT"],
        execute=True,
        now_fn=lambda: NOW,
    )

    assert first_status["status"] == "READY"
    assert len(http_calls) == 1
    assert len(shared_budget.reserve_calls) == 1
    _key, request_weight, budget, ttl_ms = shared_budget.reserve_calls[0]
    assert _key.startswith(fallback_policy.REST_FALLBACK_BUDGET_REDIS_KEY_PREFIX)
    assert request_weight == 1
    assert budget == 1
    assert ttl_ms == 120_000
    assert sum(shared_budget.counts.values()) == 1
    assert "binance_rest_fallback_decision" in mod.REST_FALLBACK_BUDGET_GUARD_OWNER

    second_status = mod.fetch_and_cache_leverage_brackets(
        adapter=adapter,
        redis_client=redis,
        security_context=SECURITY,
        symbols=["BTCUSDT"],
        execute=True,
        now_fn=lambda: NOW,
    )

    assert second_status["status"] == "BLOCKED"
    assert second_status["reason"].startswith(
        "ADAPTER_STATUS_REST_FALLBACK_BLOCKED_WEBSOCKET_PRIMARY"
    )
    assert len(http_calls) == 1
    assert len(shared_budget.reserve_calls) == 2
    assert sum(shared_budget.counts.values()) == 1


def test_fetch_records_distinct_pipeline_timestamps_in_order() -> None:
    redis = FakeRedis()
    clock = SequenceClock(
        NOW,
        NOW + timedelta(seconds=1),
        NOW + timedelta(seconds=2),
        NOW + timedelta(seconds=3),
        NOW + timedelta(seconds=4),
        NOW + timedelta(seconds=5),
    )
    status = mod.fetch_and_cache_leverage_brackets(
        adapter=FakeAdapter([_row()]),
        redis_client=redis,
        security_context=SECURITY,
        symbols=["BTCUSDT"],
        now_fn=clock,
    )
    stored = json.loads(redis.values[mod.redis_key("BTCUSDT", security_context=SECURITY)])
    assert status["status"] == "READY"
    assert stored["fetch_started_at"] == "2026-07-17T12:00:00.000000Z"
    assert stored["fetched_at"] == "2026-07-17T12:00:01.000000Z"
    assert stored["generated_at"] == "2026-07-17T12:00:02.000000Z"
    assert stored["ingested_at"] == "2026-07-17T12:00:03.000000Z"
    assert stored["available_at"] == "2026-07-17T12:00:04.000000Z"


def test_fetch_rejects_publication_clock_regression_before_cache_write() -> None:
    redis = FakeRedis()
    clock = SequenceClock(
        NOW,
        NOW + timedelta(seconds=1),
        NOW + timedelta(seconds=2),
        NOW + timedelta(seconds=3),
        NOW + timedelta(seconds=2),
        NOW + timedelta(seconds=4),
    )
    status = mod.fetch_and_cache_leverage_brackets(
        adapter=FakeAdapter([_row()]),
        redis_client=redis,
        security_context=SECURITY,
        symbols=["BTCUSDT"],
        now_fn=clock,
    )
    assert status["status"] == "MALFORMED"
    assert status["invalid_symbols"] == ["BTCUSDT"]
    assert redis.get(mod.redis_key("BTCUSDT", security_context=SECURITY)) is None


def test_fetch_multiple_symbols_uses_one_all_symbol_call_and_filters() -> None:
    redis = FakeRedis()
    adapter = FakeAdapter([_row(), _row("ETHUSDT")])

    status = mod.fetch_and_cache_leverage_brackets(
        adapter=adapter,
        redis_client=redis,
        security_context=SECURITY,
        symbols=["ETHUSDT", "BTCUSDT"],
        now_fn=lambda: NOW,
    )

    assert status["status"] == "READY"
    assert status["symbols_published"] == ["BTCUSDT", "ETHUSDT"]
    assert adapter.calls[0]["params"] is None
    assert len(adapter.calls) == 1


def test_fetch_missing_requested_symbol_is_partial_and_has_no_key() -> None:
    redis = FakeRedis()
    status = mod.fetch_and_cache_leverage_brackets(
        adapter=FakeAdapter([_row()]),
        redis_client=redis,
        security_context=SECURITY,
        symbols=["BTCUSDT", "ETHUSDT"],
        now_fn=lambda: NOW,
    )

    assert status["status"] == "PARTIAL"
    assert status["missing_symbols"] == ["ETHUSDT"]
    assert redis.get(mod.redis_key("ETHUSDT", security_context=SECURITY)) is None


def test_fetch_missing_security_context_fails_before_adapter_and_redis() -> None:
    redis = FakeRedis()
    adapter = FakeAdapter([_row()])
    status = mod.fetch_and_cache_leverage_brackets(
        adapter=adapter,
        redis_client=redis,
        security_context=None,
        symbols=["BTCUSDT"],
        now_fn=lambda: NOW,
    )
    assert status["status"] == "BLOCKED"
    assert status["reason"] == "EVIDENCE_SECURITY_CONTEXT_REQUIRED"
    assert adapter.calls == []
    assert redis.values == {}


@pytest.mark.parametrize(
    ("freshness_seconds", "cache_ttl_seconds"),
    [(0, 900), (600, 599), (None, 900)],
)
def test_fetch_invalid_freshness_contract_fails_before_adapter(
    freshness_seconds: Any,
    cache_ttl_seconds: Any,
) -> None:
    adapter = FakeAdapter([_row()])
    status = mod.fetch_and_cache_leverage_brackets(
        adapter=adapter,
        redis_client=FakeRedis(),
        security_context=SECURITY,
        symbols=["BTCUSDT"],
        freshness_seconds=freshness_seconds,
        cache_ttl_seconds=cache_ttl_seconds,
        now_fn=lambda: NOW,
    )
    assert status["status"] == "BLOCKED"
    assert status["reason"] == "INVALID_FRESHNESS_OR_CACHE_TTL_CONTRACT"
    assert adapter.calls == []


def test_fetch_wrong_adapter_environment_fails_before_signed_read() -> None:
    adapter = FakeAdapter([_row()], base_url=mod.TESTNET_BASE_URL)
    redis = FakeRedis()
    status = mod.fetch_and_cache_leverage_brackets(
        adapter=adapter,
        redis_client=redis,
        security_context=SECURITY,
        symbols=["BTCUSDT"],
        now_fn=lambda: NOW,
    )
    assert status["status"] == "BLOCKED"
    assert status["reason"] == "ADAPTER_ENVIRONMENT_BINDING_MISMATCH"
    assert adapter.calls == []


def test_fetch_adapter_block_is_fail_closed_and_writes_only_scoped_status() -> None:
    redis = FakeRedis()
    status = mod.fetch_and_cache_leverage_brackets(
        adapter=FakeAdapter([_row()], status="REST_FALLBACK_BLOCKED_WEBSOCKET_PRIMARY"),
        redis_client=redis,
        security_context=SECURITY,
        symbols=["BTCUSDT"],
        now_fn=lambda: NOW,
    )

    assert status["status"] == "BLOCKED"
    assert status["reason"].startswith("ADAPTER_STATUS_")
    assert redis.get(mod.redis_key("BTCUSDT", security_context=SECURITY)) is None
    assert redis.get(mod.redis_status_key(security_context=SECURITY)) is not None


def test_fetch_does_not_call_adapter_without_redis() -> None:
    adapter = FakeAdapter([_row()])
    status = mod.fetch_and_cache_leverage_brackets(
        adapter=adapter,
        redis_client=None,
        security_context=SECURITY,
        symbols=["BTCUSDT"],
        now_fn=lambda: NOW,
    )

    assert status["status"] == "BLOCKED"
    assert status["reason"] == "REDIS_UNAVAILABLE_NO_FETCH_ATTEMPTED"
    assert adapter.calls == []


def test_consumer_selects_floor_inclusive_cap_exclusive_and_exact_formula() -> None:
    redis = FakeRedis()
    _cache(redis)

    first = _select(redis, candidate_notional=9_999.99)
    second = _select(redis, candidate_notional=10_000)

    assert first["allowed"] is True
    assert first["evidence_usable"] is True
    assert first["allowed_semantics"] == ("BRACKET_EVIDENCE_USABLE_ONLY_NOT_TRADE_ADMISSION")
    assert first["selected_bracket"] == 1
    assert first["maintenance_margin_rate"] == 0.0065
    assert first["max_initial_leverage"] == 75
    assert second["allowed"] is True
    assert second["selected_bracket"] == 2
    assert second["maintenance_margin_rate"] == 0.01
    assert second["maintenance_margin_cum"] == 35.0
    assert second["maintenance_margin_estimate_for_candidate_notional"] == 65.0
    assert second["max_initial_leverage"] == 50
    assert second["notional_coef"] == 1.5
    assert second["consumer_observed_at"] == "2026-07-17T12:05:00.000000Z"
    assert second["current_checked_at"] == "2026-07-17T12:05:00.000000Z"


@pytest.mark.parametrize(
    ("decision_time", "now", "expected"),
    [
        (
            NOW - timedelta(microseconds=1),
            CONSUMER_NOW,
            "LEVERAGE_BRACKET_EVIDENCE_AVAILABLE_AFTER_DECISION_TIME",
        ),
        (
            NOW + timedelta(minutes=10),
            NOW + timedelta(minutes=10),
            "LEVERAGE_BRACKET_EVIDENCE_STALE_AT_DECISION_TIME",
        ),
        (
            datetime(2026, 7, 17, 12, 5),
            CONSUMER_NOW,
            "DECISION_TIME_INVALID_OR_NAIVE",
        ),
    ],
)
def test_consumer_rejects_future_stale_and_naive_decision_time(
    decision_time: datetime,
    now: datetime,
    expected: str,
) -> None:
    redis = FakeRedis()
    _cache(redis)
    result = _select(redis, decision_time=decision_time, now_fn=lambda: now)
    assert result["allowed"] is False
    assert result["status"] == expected
    assert result["maintenance_margin_rate"] is None


def test_consumer_enforces_current_clock_and_current_freshness() -> None:
    redis = FakeRedis()
    _cache(redis)

    stale_now = _select(
        redis,
        decision_time=NOW + timedelta(minutes=1),
        now_fn=lambda: NOW + timedelta(minutes=10),
    )
    assert stale_now["status"] == "LEVERAGE_BRACKET_EVIDENCE_STALE_AT_CURRENT_TIME"

    future_decision = _select(
        redis,
        decision_time=NOW + timedelta(minutes=6),
        now_fn=lambda: NOW + timedelta(minutes=5),
    )
    assert future_decision["status"] == "DECISION_TIME_AFTER_CONSUMER_OBSERVED_AT"

    regression = _select(
        redis,
        decision_time=NOW + timedelta(minutes=1),
        now_fn=SequenceClock(
            NOW + timedelta(minutes=5),
            NOW + timedelta(minutes=4),
        ),
    )
    assert regression["status"] == "CONSUMER_CLOCK_REGRESSION"


def test_consumer_rejects_naive_consumer_and_current_clocks() -> None:
    redis = FakeRedis()
    _cache(redis)

    naive_observed = _select(
        redis,
        decision_time=NOW + timedelta(minutes=1),
        now_fn=lambda: datetime(2026, 7, 17, 12, 5),
    )
    assert naive_observed["status"] == "CONSUMER_OBSERVED_AT_INVALID_OR_NAIVE"

    naive_current = _select(
        redis,
        decision_time=NOW + timedelta(minutes=1),
        now_fn=SequenceClock(
            NOW + timedelta(minutes=5),
            datetime(2026, 7, 17, 12, 5),
        ),
    )
    assert naive_current["status"] == "CURRENT_CHECKED_AT_INVALID_OR_NAIVE"


def test_consumer_rejects_tamper_even_when_checksum_is_recomputed() -> None:
    redis = FakeRedis()
    payload = _cache(redis)
    payload["brackets"][0]["maintMarginRatio"] = 0.007
    payload["content_checksum_sha256"] = mod._content_checksum(payload)
    redis.set(
        mod.redis_key("BTCUSDT", security_context=SECURITY),
        json.dumps(payload),
        ex=900,
    )

    result = _select(redis)
    assert result["status"] == "LEVERAGE_BRACKET_EVIDENCE_MALFORMED"
    assert result["validation_error_code"] == "EVIDENCE_HMAC_MISMATCH"


@pytest.mark.parametrize("binding_variant", ["account", "environment"])
def test_consumer_requires_exact_account_and_environment_binding(
    binding_variant: str,
) -> None:
    redis = FakeRedis()
    payload = _cache(redis)
    wrong = (
        _security_context(credential_ref="OTHER_BINANCE_READONLY")
        if binding_variant == "account"
        else _security_context(base_url=mod.TESTNET_BASE_URL)
    )
    # The scoped lookup cannot accidentally see the original account's value.
    assert _select(redis, security_context=wrong)["status"] == ("LEVERAGE_BRACKET_EVIDENCE_MISSING")
    # Even a copied value under the wrong key is rejected by exact binding.
    redis.set(
        mod.redis_key("BTCUSDT", security_context=wrong),
        json.dumps(payload),
        ex=900,
    )
    copied = _select(redis, security_context=wrong)
    assert copied["status"] == "LEVERAGE_BRACKET_EVIDENCE_MALFORMED"
    assert copied["validation_error_code"].startswith("SECURITY_BINDING_MISMATCH_")


def test_consumer_rejects_missing_simple_tamper_and_out_of_range() -> None:
    missing = _select(FakeRedis())
    assert missing["status"] == "LEVERAGE_BRACKET_EVIDENCE_MISSING"

    tampered = FakeRedis()
    payload = _cache(tampered)
    payload["brackets"][0]["maintMarginRatio"] = 0.99
    tampered.set(
        mod.redis_key("BTCUSDT", security_context=SECURITY),
        json.dumps(payload),
        ex=900,
    )
    tampered_result = _select(tampered)
    assert tampered_result["status"] == "LEVERAGE_BRACKET_EVIDENCE_MALFORMED"
    assert tampered_result["validation_error_code"] == "CONTENT_CHECKSUM_MISMATCH"

    valid = FakeRedis()
    _cache(valid)
    outside = _select(valid, candidate_notional=50_000)
    assert outside["status"] == "CANDIDATE_NOTIONAL_OUTSIDE_REPORTED_BRACKETS"
    assert outside["allowed"] is False


@pytest.mark.parametrize("candidate_notional", [None, 0, -1, float("nan"), float("inf")])
def test_consumer_rejects_invalid_candidate_notional(
    candidate_notional: Any,
) -> None:
    redis = FakeRedis()
    _cache(redis)
    result = _select(redis, candidate_notional=candidate_notional)
    assert result["status"] == "CANDIDATE_NOTIONAL_INVALID"
    assert result["allowed"] is False
