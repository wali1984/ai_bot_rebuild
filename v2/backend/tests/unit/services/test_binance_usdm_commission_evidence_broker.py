from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from v2.backend.app.services import binance_usdm_commission_evidence_broker as broker
from v2.backend.app.services import binance_usdm_leverage_bracket_evidence as bracket
from v2.backend.app.services.native_trainer import (
    binance_usdm_commission_capture_v1 as capture,
)
from v2.backend.app.services.native_trainer import causal_cost_evidence_v1
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)

_API_KEY = "synthetic-readonly-key-never-persist"
_API_SECRET = "synthetic-readonly-secret-never-persist"  # noqa: S105
_HMAC_KEY = b"separate-broker-evidence-key-at-least-32-bytes"
_RAW_TEMPLATE = (
    '{{"symbol":"{symbol}","makerCommissionRate":"0.00020000",'
    '"takerCommissionRate":"0.00040000","rpiCommissionRate":"0.00010000"}}'
)


class _Clock:
    def __init__(self, start: datetime, *, step_ms: int = 10) -> None:
        self.current = start
        self.step = timedelta(milliseconds=step_ms)

    def __call__(self) -> datetime:
        value = self.current
        self.current += self.step
        return value


class _Response:
    def __init__(self, content: bytes) -> None:
        self.status_code = 200
        self.content = content
        self.headers: dict[str, str] = {}


class _Redis:
    """Minimal exact interpreter for the broker's two bounded Lua scripts."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def eval(self, script: str, key_count: int, *args: Any) -> Any:
        if script == broker._CLAIM_LUA:  # noqa: SLF001
            assert key_count == 1
            key, claim, pacing_ms = args
            if key in self.values:
                return [0, self.ttls[key]]
            self.values[key] = str(claim)
            self.ttls[key] = int(pacing_ms)
            return [1, int(pacing_ms)]
        if script == broker._PUBLISH_CAS_LUA:  # noqa: SLF001
            assert key_count == 2
            key, version_key, proposed_clock, version, payload, ttl_ms = args
            prior = self.values.get(str(version_key))
            if prior is not None:
                prior_clock = int(prior.split(":", 1)[0])
                if prior_clock > int(proposed_clock):
                    return -1
                if prior_clock == int(proposed_clock):
                    if self.values.get(str(key)) == payload and prior == version:
                        return 2
                    return -2
            self.values[str(key)] = str(payload)
            self.values[str(version_key)] = str(version)
            self.ttls[str(key)] = int(ttl_ms)
            self.ttls[str(version_key)] = int(ttl_ms)
            return 1
        raise AssertionError("unexpected Lua script")


class _UniverseRedis:
    def __init__(
        self,
        payload: bytes,
        *,
        pttl_ms: int = 60_000,
        payload_byte_count: int | None = None,
        server_at: datetime | None = None,
    ) -> None:
        self.payload = payload
        self.pttl_ms = pttl_ms
        self.payload_byte_count = (
            len(payload) if payload_byte_count is None else payload_byte_count
        )
        self.server_at = server_at or datetime(2026, 7, 22, 5, 0, 1, tzinfo=UTC)

    def eval(self, script: str, key_count: int, *args: Any) -> list[Any]:
        assert script == broker._DYNAMIC_UNIVERSE_READ_LUA  # noqa: SLF001
        assert key_count == 1
        assert args == (
            broker.DYNAMIC_COMMISSION_UNIVERSE_KEY,
            broker.MAX_DYNAMIC_UNIVERSE_PAYLOAD_BYTES,
        )
        return [
            b"string",
            self.payload_byte_count,
            self.payload,
            self.pttl_ms,
            str(int(self.server_at.timestamp())).encode(),
            self.server_at.microsecond,
        ]


def _store(tmp_path: Path) -> ImmutableSourcePayloadStore:
    return ImmutableSourcePayloadStore(tmp_path / "commission-cas")


def test_default_store_accepts_concrete_absolute_path_and_rejects_relative(
    tmp_path: Path,
) -> None:
    store = broker.default_commission_broker_store(tmp_path.absolute())

    assert store.root_path == tmp_path.absolute() / "commission-evidence-cas"
    with pytest.raises(
        broker.CommissionEvidenceBrokerError,
        match="COMMISSION_BROKER_DATA_ROOT_INVALID",
    ):
        broker.default_commission_broker_store(Path("relative"))


def _context(*, hmac_key: bytes = _HMAC_KEY) -> bracket.EvidenceSecurityContext:
    return bracket.build_evidence_security_context(
        trader_id="trader-fixture",
        credential_ref="TRADER_BINANCE_READONLY",
        base_url="https://fapi.binance.com",
        credential_account_specific=True,
        hmac_key=hmac_key,
        auth_key_id="commission-broker-test-v1",
    )


def _adapter() -> SimpleNamespace:
    return SimpleNamespace(
        api_key=_API_KEY,
        api_secret=_API_SECRET,
        base_url="https://fapi.binance.com",
    )


def _allow_budget(**kwargs: Any) -> dict[str, Any]:
    assert kwargs == {
        "endpoint": "GET /fapi/v1/commissionRate",
        "fallback_reason": broker.FALLBACK_REASON,
        "role": "signed_read_recovery",
        "request_weight": 20,
        "require_shared_budget": True,
    }
    return {
        "request_allowed": True,
        "request_weight": 20,
        "shared_budget_required": True,
        "budget_scope": "host_redis",
        "rest_used_as_primary": False,
        "transport_role": "fallback_only",
    }


def _capture_factory(http_calls: list[dict[str, Any]], *, raw_override: bytes | None = None):
    def factory(**kwargs: Any) -> capture.BinanceUSDMCommissionCaptureTokenV1:
        def http_get(**request: Any) -> _Response:
            http_calls.append(dict(request))
            symbol = request["params"]["symbol"]
            raw = raw_override or _RAW_TEMPLATE.format(symbol=symbol).encode("ascii")
            return _Response(raw)

        return capture.capture_binance_usdm_commission_rate_v1(
            **kwargs,
            http_get=http_get,
        )

    return factory


def _publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    symbols: tuple[str, ...] = ("BTCUSDT",),
    start_at: datetime | None = None,
) -> tuple[
    dict[str, Any],
    _Redis,
    ImmutableSourcePayloadStore,
    bracket.EvidenceSecurityContext,
    list[dict[str, Any]],
    _Clock,
]:
    monkeypatch.setattr(capture, "binance_rest_fallback_decision", _allow_budget)
    redis = _Redis()
    store = _store(tmp_path)
    context = _context()
    calls: list[dict[str, Any]] = []
    clock = _Clock(start_at or datetime(2026, 7, 22, 5, 0, tzinfo=UTC))
    result = broker.capture_and_publish_next_commission_evidence(
        adapter=_adapter(),
        redis_client=redis,
        store=store,
        security_context=context,
        symbols=symbols,
        environ={"BINANCE_REST_FALLBACK_BUDGET_PER_MINUTE": "120"},
        now_fn=clock,
        capture_function=_capture_factory(calls),
    )
    return result, redis, store, context, calls, clock


def test_adaptive_plan_rotates_one_priority_gap_under_exact_weight_budget() -> None:
    redis = _Redis()
    context = _context()
    symbols = tuple(f"COIN{index:03d}USDT" for index in range(159))

    plan = broker.build_adaptive_rotation_plan(
        redis,
        security_context=context,
        symbols=symbols,
        priority_symbols=(symbols[87],),
        environ={"BINANCE_REST_FALLBACK_BUDGET_PER_MINUTE": "120"},
        now_fn=lambda: datetime(2026, 7, 22, 5, 0, tzinfo=UTC),
    )

    assert plan.selected_symbol == symbols[87]
    assert plan.cache_missing_count == 159
    assert plan.calls_per_minute == 6
    assert plan.pacing_ms == 10_000
    assert plan.observed_capture_sample_count == 0
    assert plan.observed_capture_max_ms == 0
    assert plan.projected_turn_ms == 10_000
    assert plan.projected_revisit_ms == 1_590_000
    assert plan.refresh_interval_seconds == 1_600
    assert plan.continuous_coverage_feasible is False


def test_dynamic_rotation_universe_atomically_excludes_invalid_symbol_metadata() -> None:
    payload = json.dumps(
        {
            "generated_utc": "2026-07-22T05:00:00Z",
            "symbols": ["BTCUSDT", "币安人生USDT", "ETHUSDT"],
        },
        sort_keys=True,
    ).encode()

    selected = broker.read_adaptive_commission_rotation_universe(
        _UniverseRedis(payload)
    )

    assert selected["status"] == "READY"
    assert selected["symbols"] == ("BTCUSDT", "ETHUSDT")
    assert selected["rejected_symbols"] == ("币安人生USDT",)
    assert selected["source_pttl_ms"] == 60_000
    assert selected["selection_metadata_only"] is True
    assert selected["trainer_authority"] is False
    assert selected["live_authority"] is False


def test_dynamic_universe_lua_normalizes_redis_status_reply_before_type_check() -> None:
    script = broker._DYNAMIC_UNIVERSE_READ_LUA  # noqa: SLF001

    assert "local redis_type_reply = redis.call('TYPE', KEYS[1])" in script
    assert "if type(redis_type_reply) == 'table' then" in script
    assert "redis_type = redis_type_reply['ok']" in script
    assert "redis_type == 'string'" in script


@pytest.mark.parametrize(
    ("redis_client", "expected_status"),
    [
        (
            _UniverseRedis(
                b'{"generated_utc":"2026-07-22T05:00:00Z","symbols":["BTCUSDT"]}',
                pttl_ms=0,
            ),
            "COMMISSION_BROKER_DYNAMIC_UNIVERSE_SOURCE_INVALID",
        ),
        (
            _UniverseRedis(
                b"",
                payload_byte_count=broker.MAX_DYNAMIC_UNIVERSE_PAYLOAD_BYTES + 1,
            ),
            "COMMISSION_BROKER_DYNAMIC_UNIVERSE_SOURCE_INVALID",
        ),
        (
            _UniverseRedis(
                b'{"generated_utc":"2026-07-22T05:00:02Z","symbols":["BTCUSDT"]}',
            ),
            "COMMISSION_BROKER_DYNAMIC_UNIVERSE_CLOCK_INVALID",
        ),
    ],
)
def test_dynamic_rotation_universe_stale_oversized_or_future_source_defers(
    redis_client: _UniverseRedis,
    expected_status: str,
) -> None:
    selected = broker.read_adaptive_commission_rotation_universe(redis_client)

    assert selected == {
        "status": expected_status,
        "symbols": (),
        "rejected_symbols": (),
    }


def test_159_symbol_invocation_executes_exactly_one_read_only_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    symbols = tuple(f"COIN{index:03d}USDT" for index in range(159))
    result, redis, store, context, calls, _clock = _publish(
        tmp_path,
        monkeypatch,
        symbols=symbols,
    )

    assert result["status"] == "READY"
    assert result["request_count"] == 1
    assert result["request_weight"] == 20
    assert len(calls) == 1
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "https://fapi.binance.com/fapi/v1/commissionRate"
    assert calls[0]["params"]["symbol"] == symbols[0]
    assert not any(
        fragment in calls[0]["url"]
        for fragment in ("/order", "/leverage", "/marginType", "/cancel", "/transfer")
    )
    assert result["places_real_order"] is False
    assert result["order_submitted"] is False
    assert result["leverage_mutated"] is False
    assert result["margin_mutated"] is False
    assert redis.get(broker.redis_key(symbols[0], security_context=context)) is not None
    assert store.max_payload_bytes > 0


def test_pacing_claim_prevents_second_http_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, redis, store, context, calls, clock = _publish(tmp_path, monkeypatch)
    assert result["request_count"] == 1

    deferred = broker.capture_and_publish_next_commission_evidence(
        adapter=_adapter(),
        redis_client=redis,
        store=store,
        security_context=context,
        symbols=("BTCUSDT",),
        environ={"BINANCE_REST_FALLBACK_BUDGET_PER_MINUTE": "120"},
        now_fn=clock,
        capture_function=_capture_factory(calls),
    )

    assert deferred["status"] == "DEFERRED"
    assert deferred["request_executed"] is False
    assert deferred["request_count"] == 0
    assert len(calls) == 1


def test_rotation_adapts_revisit_to_authenticated_observed_capture_duration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _result, redis, _store_value, context, _calls, clock = _publish(
        tmp_path,
        monkeypatch,
    )

    plan = broker.build_adaptive_rotation_plan(
        redis,
        security_context=context,
        symbols=("BTCUSDT",),
        environ={"BINANCE_REST_FALLBACK_BUDGET_PER_MINUTE": "120"},
        now_fn=clock,
    )

    assert plan.observed_capture_sample_count == 1
    assert plan.observed_capture_max_ms == 40
    assert plan.projected_turn_ms == 10_040
    assert plan.projected_revisit_ms == 10_040
    assert plan.refresh_interval_seconds == 21
    assert plan.continuous_coverage_feasible is True


def test_exact_raw_response_is_cas_persisted_and_never_put_in_redis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, redis, store, context, _calls, _clock = _publish(tmp_path, monkeypatch)
    raw = _RAW_TEMPLATE.format(symbol="BTCUSDT").encode("ascii")
    digest = hashlib.sha256(raw).hexdigest()

    assert result["raw_response_sha256"] == digest
    assert store.get(digest, expected_byte_count=len(raw)) == raw
    envelope_text = redis.get(broker.redis_key("BTCUSDT", security_context=context))
    assert envelope_text is not None
    envelope = json.loads(envelope_text)
    assert envelope["raw_response_stored_in_redis"] is False
    assert envelope["raw_response_sha256"] == digest
    assert raw.decode("ascii") not in envelope_text
    persisted = envelope_text
    for path in (tmp_path / "commission-cas" / "sha256").glob("*/*"):
        persisted += path.read_bytes().decode("utf-8", errors="ignore")
    for secret in (_API_KEY, _API_SECRET, _HMAC_KEY.decode("ascii")):
        assert secret not in persisted


def test_malformed_response_is_still_stored_before_json_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(capture, "binance_rest_fallback_decision", _allow_budget)
    malformed = b'{"symbol":"BTCUSDT","unexpected":true}'
    store = _store(tmp_path)

    with pytest.raises(
        capture.BinanceUSDMCommissionCaptureV1ValidationError,
        match="COMMISSION_CAPTURE_RESPONSE_EXACT_FOUR_FIELD_SHAPE_REQUIRED",
    ):
        broker.capture_and_publish_next_commission_evidence(
            adapter=_adapter(),
            redis_client=_Redis(),
            store=store,
            security_context=_context(),
            symbols=("BTCUSDT",),
            environ={"BINANCE_REST_FALLBACK_BUDGET_PER_MINUTE": "120"},
            now_fn=_Clock(datetime(2026, 7, 22, 5, 0, tzinfo=UTC)),
            capture_function=_capture_factory([], raw_override=malformed),
        )

    assert store.get(
        hashlib.sha256(malformed).hexdigest(),
        expected_byte_count=len(malformed),
    ) == malformed


def test_credentialless_reader_returns_exact_causal_cost_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _result, redis, store, context, _calls, clock = _publish(tmp_path, monkeypatch)
    decision = datetime(2026, 7, 22, 5, 0, 15, tzinfo=UTC)

    selected = broker.read_authenticated_commission_evidence(
        redis,
        store=store,
        security_context=context,
        symbol="BTCUSDT",
        decision_time=decision,
        now_fn=clock,
    )

    assert selected["status"] == "READY"
    evidence = selected["evidence"]
    assert isinstance(evidence, broker.CredentiallessCommissionEvidence)
    assert evidence.exchange_credentials_read is False
    fee_bps, source, receipt, _objects = causal_cost_evidence_v1._validate_fee_evidence(
        store=store,
        artifact_bytes=evidence.fee_artifact_bytes,
        raw_response_bytes=evidence.raw_response_bytes,
        receipt=evidence.fee_schedule_receipt,
        symbol="BTCUSDT",
        decision_at=decision,
    )
    assert fee_bps == pytest.approx(4.0)
    assert source["request_path"] if "request_path" in source else True
    assert receipt["receipt_sha256"] == evidence.fee_receipt_sha256
    consumer_receipt = json.loads(evidence.broker_consumer_receipt_bytes)
    supplied_hmac = consumer_receipt.pop("evidence_hmac_sha256")
    assert hmac.compare_digest(
        supplied_hmac,
        hmac.new(
            _HMAC_KEY,
            broker._CONSUMER_READ_RECEIPT_HMAC_DOMAIN  # noqa: SLF001
            + broker._canonical_bytes(consumer_receipt),  # noqa: SLF001
            hashlib.sha256,
        ).hexdigest(),
    )
    assert consumer_receipt["broker_cas_object_count"] == 8
    assert consumer_receipt["decision_time"] == evidence.decision_time
    assert consumer_receipt["broker_envelope_sha256"] == (
        evidence.broker_envelope_sha256
    )
    assert evidence.broker_consumer_receipt_sha256 == hashlib.sha256(
        evidence.broker_consumer_receipt_bytes
    ).hexdigest()
    assert evidence.trainer_authority is False
    assert evidence.live_authority is False


def test_wrong_hmac_or_past_decision_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _result, redis, store, context, _calls, clock = _publish(tmp_path, monkeypatch)
    wrong_context = _context(hmac_key=b"different-independent-hmac-key-at-least-32-bytes")
    future_decision = datetime(2026, 7, 22, 5, 0, 15, tzinfo=UTC)

    wrong_key = broker.read_authenticated_commission_evidence(
        redis,
        store=store,
        security_context=wrong_context,
        symbol="BTCUSDT",
        decision_time=future_decision,
        now_fn=clock,
    )
    past_decision = broker.read_authenticated_commission_evidence(
        redis,
        store=store,
        security_context=context,
        symbol="BTCUSDT",
        decision_time=datetime(2026, 7, 22, 4, 59, tzinfo=UTC),
        now_fn=clock,
    )

    assert wrong_key["status"] == "COMMISSION_BROKER_EVIDENCE_HMAC_MISMATCH"
    assert wrong_key["evidence"] is None
    assert past_decision["status"] == "COMMISSION_BROKER_DECISION_TEMPORAL_ADMISSION_FAILED"
    assert past_decision["evidence"] is None


def test_noncanonical_but_hmac_valid_redis_envelope_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _result, redis, store, context, _calls, clock = _publish(tmp_path, monkeypatch)
    key = broker.redis_key("BTCUSDT", security_context=context)
    redis.values[key] = json.dumps(json.loads(redis.values[key]), indent=2)

    selected = broker.read_authenticated_commission_evidence(
        redis,
        store=store,
        security_context=context,
        symbol="BTCUSDT",
        decision_time=datetime(2026, 7, 22, 5, 0, 15, tzinfo=UTC),
        now_fn=clock,
    )

    assert selected == {
        "status": "COMMISSION_BROKER_REDIS_EVIDENCE_NOT_CANONICAL",
        "evidence": None,
    }


def test_monotonic_redis_cas_rejects_older_authenticated_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _result, redis, _store_value, context, _calls, _clock = _publish(
        tmp_path,
        monkeypatch,
    )
    key = broker.redis_key("BTCUSDT", security_context=context)
    current = json.loads(redis.values[key])
    current["broker_generated_at"] = "2026-07-22T04:59:59.000000Z"
    current["broker_available_at"] = "2026-07-22T04:59:59.100000Z"
    broker._seal(current, security_context=context)  # noqa: SLF001

    with pytest.raises(
        broker.CommissionEvidenceBrokerError,
        match="COMMISSION_BROKER_REDIS_CAS_OLDER_THAN_CURRENT",
    ):
        broker._publish_cas(  # noqa: SLF001
            redis,
            security_context=context,
            symbol="BTCUSDT",
            payload=current,
            ttl_ms=1_000,
        )


def test_budget_below_route_weight_blocks_before_capture(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    with pytest.raises(
        broker.CommissionEvidenceBrokerError,
        match="COMMISSION_BROKER_RATE_BUDGET_BELOW_ONE_REQUEST",
    ):
        broker.capture_and_publish_next_commission_evidence(
            adapter=_adapter(),
            redis_client=_Redis(),
            store=_store(tmp_path),
            security_context=_context(),
            symbols=("BTCUSDT",),
            environ={"BINANCE_REST_FALLBACK_BUDGET_PER_MINUTE": "19"},
            capture_function=_capture_factory(calls),
        )

    assert calls == []


def test_publication_hmac_and_fingerprint_use_separate_domains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _result, redis, _store_value, context, _calls, _clock = _publish(
        tmp_path,
        monkeypatch,
    )
    envelope = json.loads(redis.values[broker.redis_key("BTCUSDT", security_context=context)])

    assert envelope["evidence_hmac_sha256"] != envelope[
        "credential_binding_fingerprint_sha256"
    ]
    assert envelope["content_checksum_sha256"] != envelope["evidence_hmac_sha256"]
    assert envelope["exchange_key_permissions_proven_by_connector"] is False
    assert envelope["credential_ref_read_only_assertion_semantics"] == (
        "OPERATOR_USAGE_LABEL_NOT_BINANCE_PERMISSION_PROOF"
    )
