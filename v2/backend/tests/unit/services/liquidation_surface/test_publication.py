from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
import redis
from v2.backend.app.services.liquidation_surface import (
    CandleObservation,
    LeverageBracket,
    MarkPriceObservation,
    OpenInterestObservation,
    SurfacePublicationIntegrityError,
    SurfacePublicationValidationError,
    SurfaceRequest,
    VerifiedLiquidationSurface,
    build_liquidation_surface,
    build_surface_publication_security_context,
    publish_liquidation_surface,
    reopen_latest_liquidation_surface,
)

VENUE = "binance_usdm"
SYMBOL = "BTCUSDT"
TIMEFRAME = "5m"
BASE_MS = 1_800_000_000_000
AS_OF_MS = BASE_MS + 1_000_000
GENERATED_AT_MS = AS_OF_MS + 100
SCOPE_METADATA = {
    "credential_binding_id": "mainnet:trainer:PRIMARY_BINANCE_READONLY",
    "exchange_environment": "mainnet",
    "base_url_origin": "https://fapi.binance.com",
    "evidence_auth_key_id": "liquidation-evidence-v1",
    "credential_account_specific": True,
}


def _security_context(*, key: bytes = b"publication-test-key-material-0001"):
    return build_surface_publication_security_context(
        scope_metadata=SCOPE_METADATA,
        hmac_key=key,
        auth_key_id="surface-publication-v1",
    )


def _candle(index: int) -> CandleObservation:
    open_time = BASE_MS + index * 300_000
    close_time = open_time + 299_999
    return CandleObservation(
        venue=VENUE,
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        open_time_ms=open_time,
        close_time_ms=close_time,
        event_time_ms=close_time,
        ingested_at_ms=close_time + 10,
        available_at_ms=close_time + 20,
        is_final=True,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
        quote_volume=10_000.0,
        taker_buy_quote_volume=6_000.0,
        source_key=f"v2:market:ohlcv_closed:binance:{SYMBOL}:{TIMEFRAME}",
        source_sha256="a" * 64,
    )


def _open_interest(index: int, value: float) -> OpenInterestObservation:
    cutoff = _candle(index).close_time_ms + 1
    return OpenInterestObservation(
        venue=VENUE,
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        feature_cutoff_ms=cutoff,
        event_time_ms=cutoff + 100,
        ingested_at_ms=cutoff + 110,
        available_at_ms=cutoff + 120,
        is_final=True,
        value=value,
        unit="base_asset",
        source_key=f"latest:coinank:open_interest:{SYMBOL}:{TIMEFRAME}",
        source_sha256="b" * 64,
    )


def _mark(offset_ms: int) -> MarkPriceObservation:
    event_time = AS_OF_MS + offset_ms
    return MarkPriceObservation(
        venue=VENUE,
        symbol=SYMBOL,
        event_time_ms=event_time,
        ingested_at_ms=event_time + 10,
        available_at_ms=event_time + 20,
        price=100.0,
        source_key=f"v2:market:mark_price:{SYMBOL}",
        source_sha256="c" * 64,
    )


def _bracket() -> LeverageBracket:
    return LeverageBracket(
        venue=VENUE,
        symbol=SYMBOL,
        bracket_id=1,
        notional_floor=0.0,
        notional_cap=1_000_000_000.0,
        initial_leverage=20,
        maintenance_margin_rate=0.004,
        cumulative_maintenance_amount=0.0,
        fetched_at_ms=AS_OF_MS - 1_000,
        ingested_at_ms=AS_OF_MS - 900,
        available_at_ms=AS_OF_MS - 800,
        expires_at_ms=AS_OF_MS + 600_000,
        source_key="v2:binance_usdm:leverage_bracket:scope:BTCUSDT",
        source_sha256="d" * 64,
    )


def _surface(
    *,
    as_of_ms: int = AS_OF_MS,
    generated_at_ms: int = GENERATED_AT_MS,
    brackets: tuple[LeverageBracket, ...] | None = None,
) -> dict[str, Any]:
    return build_liquidation_surface(
        SurfaceRequest(
            venue=VENUE,
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            as_of_time_ms=as_of_ms,
            generated_at_ms=generated_at_ms,
            candles=(_candle(0), _candle(1), _candle(2)),
            mark_prices=(_mark(-1_000), _mark(-100)),
            open_interest=(
                _open_interest(0, 100.0),
                _open_interest(1, 120.0),
                _open_interest(2, 140.0),
            ),
            leverage_brackets=(_bracket(),) if brackets is None else brackets,
        )
    )


def _surface_for_redis_clock(generated_at_ms: int) -> dict[str, Any]:
    as_of_time_ms = generated_at_ms - 1
    latest_final_close_ms = (as_of_time_ms // 300_000) * 300_000 - 1
    candle_delta = latest_final_close_ms - _candle(2).close_time_ms
    current_delta = as_of_time_ms - AS_OF_MS

    def shifted_candle(index: int) -> CandleObservation:
        row = _candle(index)
        return replace(
            row,
            open_time_ms=row.open_time_ms + candle_delta,
            close_time_ms=row.close_time_ms + candle_delta,
            event_time_ms=row.event_time_ms + candle_delta,
            ingested_at_ms=row.ingested_at_ms + candle_delta,
            available_at_ms=row.available_at_ms + candle_delta,
        )

    def shifted_open_interest(index: int, value: float) -> OpenInterestObservation:
        row = _open_interest(index, value)
        return replace(
            row,
            feature_cutoff_ms=row.feature_cutoff_ms + candle_delta,
            event_time_ms=row.event_time_ms + candle_delta,
            ingested_at_ms=row.ingested_at_ms + candle_delta,
            available_at_ms=row.available_at_ms + candle_delta,
        )

    def shifted_mark(offset_ms: int) -> MarkPriceObservation:
        row = _mark(offset_ms)
        return replace(
            row,
            event_time_ms=row.event_time_ms + current_delta,
            ingested_at_ms=row.ingested_at_ms + current_delta,
            available_at_ms=row.available_at_ms + current_delta,
        )

    bracket = _bracket()
    shifted_bracket = replace(
        bracket,
        fetched_at_ms=bracket.fetched_at_ms + current_delta,
        ingested_at_ms=bracket.ingested_at_ms + current_delta,
        available_at_ms=bracket.available_at_ms + current_delta,
        expires_at_ms=bracket.expires_at_ms + current_delta,
    )
    return build_liquidation_surface(
        SurfaceRequest(
            venue=VENUE,
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            as_of_time_ms=as_of_time_ms,
            generated_at_ms=generated_at_ms,
            candles=(shifted_candle(0), shifted_candle(1), shifted_candle(2)),
            mark_prices=(shifted_mark(-60_000), shifted_mark(-10_000)),
            open_interest=(
                shifted_open_interest(0, 100.0),
                shifted_open_interest(1, 120.0),
                shifted_open_interest(2, 140.0),
            ),
            leverage_brackets=(shifted_bracket,),
        )
    )


def _refresh_model_hash(payload: dict[str, Any]) -> dict[str, Any]:
    material = dict(payload)
    material.pop("surface_payload_sha256", None)
    payload["surface_payload_sha256"] = hashlib.sha256(
        json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return payload


class FakeRedis:
    def __init__(self, *, now_ms: int = GENERATED_AT_MS + 200, clock_step_ms: int = 1):
        self.now_ms = now_ms
        self.clock_step_ms = clock_step_ms
        self.values: dict[str, bytes] = {}
        self.expires_at_ms: dict[str, int] = {}
        self.eval_calls: list[str] = []
        self.commit_hook: Any = None
        self.confirm_hook: Any = None

    @staticmethod
    def _bytes(value: object) -> bytes:
        if isinstance(value, bytes):
            return value
        return str(value).encode("utf-8")

    @staticmethod
    def _text(value: object) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    def _clock(self) -> tuple[str, str]:
        current = self.now_ms
        self.now_ms += self.clock_step_ms
        return str(current // 1000), str((current % 1000) * 1000)

    def _pttl(self, key: str) -> int:
        return self.expires_at_ms.get(key, -1) - self.now_ms

    def eval(self, script: str, numkeys: int, *keys_and_args: object) -> list[object]:
        keys = [str(value) for value in keys_and_args[:numkeys]]
        args = list(keys_and_args[numkeys:])
        if "liquidation_surface_read_pointer_v1" in script:
            self.eval_calls.append("read_pointer")
            value = self.values.get(keys[0])
            sec, usec = self._clock()
            if value is None:
                return ["MISSING", "", sec, usec]
            return ["POINTER", value, sec, usec]

        if "liquidation_surface_prepare_archive_v1" in script:
            self.eval_calls.append("prepare")
            archive_key, receipt_key = keys
            raw = self._bytes(args[0])
            archive_ttl = int(args[1])
            current = self.values.get(archive_key)
            if current is not None and current != raw:
                return ["ERROR", "SURFACE_ARCHIVE_IDENTITY_CONFLICT"]
            status = "ADOPTED" if current is not None else "PREPARED"
            self.values[archive_key] = raw
            self.expires_at_ms[archive_key] = self.now_ms + archive_ttl * 1000
            existing_receipt = self.values.get(receipt_key, b"")
            sec, usec = self._clock()
            return [status, existing_receipt, sec, usec]

        if "liquidation_surface_commit_receipt_v1" in script:
            self.eval_calls.append("commit")
            if self.commit_hook is not None:
                hook, self.commit_hook = self.commit_hook, None
                hook(self, keys, args)
            archive_key, receipt_key, observation_key, trainer_key = keys
            raw = self._bytes(args[0])
            receipt = self._bytes(args[1])
            pointer = self._bytes(args[2])
            pointer_text = self._text(pointer)
            sort_prefix = self._text(args[3])
            expected_observation = self._text(args[4])
            expected_trainer = self._text(args[5])
            eligible = self._text(args[6]) == "1"
            receipt_ttl = int(args[7])
            if self.values.get(archive_key) != raw:
                return ["ERROR", "SURFACE_ARCHIVE_CHANGED_BEFORE_RECEIPT_COMMIT"]

            def current(key: str) -> str:
                value = self.values.get(key)
                return "__MISSING__" if value is None else value.decode("utf-8")

            observation_current = current(observation_key)
            trainer_current = current(trainer_key)
            if observation_current != expected_observation:
                return ["ERROR", "SURFACE_OBSERVATION_POINTER_PREDECESSOR_MISMATCH"]
            if eligible and trainer_current != expected_trainer:
                return ["ERROR", "SURFACE_TRAINER_POINTER_PREDECESSOR_MISMATCH"]
            for existing in (observation_current, trainer_current if eligible else "__MISSING__"):
                if existing in {"__MISSING__", pointer_text}:
                    continue
                existing_prefix = existing[: len(sort_prefix)]
                if existing_prefix > sort_prefix:
                    return ["ERROR", "SURFACE_LATEST_POINTER_REGRESSION_REJECTED"]
                if existing_prefix == sort_prefix:
                    return ["ERROR", "SURFACE_LATEST_POINTER_EQUAL_CLOCK_CONFLICT"]
            old_receipt = self.values.get(receipt_key)
            if old_receipt is not None and old_receipt != receipt:
                return ["ERROR", "SURFACE_RECEIPT_IDENTITY_CONFLICT"]
            status = "IDEMPOTENT" if old_receipt is not None else "COMMITTED"
            self.values[receipt_key] = receipt
            self.expires_at_ms[receipt_key] = self.now_ms + receipt_ttl * 1000
            self.values[observation_key] = pointer
            self.expires_at_ms[observation_key] = self.now_ms + receipt_ttl * 1000
            if eligible:
                self.values[trainer_key] = pointer
                self.expires_at_ms[trainer_key] = self.now_ms + receipt_ttl * 1000
            sec, usec = self._clock()
            return [status, sec, usec]

        if "liquidation_surface_reopen_publication_v1" in script:
            self.eval_calls.append("reopen")
            archive_key, receipt_key, pointer_key = keys
            expected = self._bytes(args[0])
            if self.values.get(pointer_key) != expected:
                return ["ERROR", "SURFACE_LATEST_POINTER_CHANGED_DURING_REOPEN"]
            archive = self.values.get(archive_key)
            receipt = self.values.get(receipt_key)
            if archive is None:
                return ["ERROR", "SURFACE_ARCHIVE_MISSING"]
            if receipt is None:
                return ["ERROR", "SURFACE_RECEIPT_MISSING"]
            sec, usec = self._clock()
            return [
                "REOPENED",
                archive,
                receipt,
                self._pttl(archive_key),
                self._pttl(receipt_key),
                self._pttl(pointer_key),
                sec,
                usec,
            ]

        if "liquidation_surface_postvalidation_confirm_v1" in script:
            self.eval_calls.append("confirm")
            if self.confirm_hook is not None:
                hook, self.confirm_hook = self.confirm_hook, None
                hook(self, keys, args)
            archive_key, receipt_key, pointer_key = keys
            expected_pointer = self._bytes(args[0])
            expected_archive = self._bytes(args[1])
            expected_receipt = self._bytes(args[2])
            if self.values.get(pointer_key) != expected_pointer:
                return ["ERROR", "SURFACE_POINTER_CHANGED_AFTER_VALIDATION"]
            if self.values.get(archive_key) != expected_archive:
                return ["ERROR", "SURFACE_ARCHIVE_CHANGED_AFTER_VALIDATION"]
            if self.values.get(receipt_key) != expected_receipt:
                return ["ERROR", "SURFACE_RECEIPT_CHANGED_AFTER_VALIDATION"]
            if (
                self._pttl(archive_key) <= self._pttl(receipt_key)
                or self._pttl(archive_key) <= self._pttl(pointer_key)
                or self._pttl(receipt_key) < self._pttl(pointer_key)
                or self._pttl(receipt_key) <= 0
                or self._pttl(pointer_key) <= 0
            ):
                return ["ERROR", "SURFACE_PUBLICATION_TTL_RELATIONSHIP_INVALID"]
            sec, usec = self._clock()
            return ["CONFIRMED", sec, usec]

        raise AssertionError("unexpected script")


@pytest.fixture()
def real_redis_client(tmp_path: Path) -> Iterator[redis.Redis]:
    executable = shutil.which("redis-server")
    if executable is None:
        pytest.skip("redis-server is required for the liquidation publication Lua test")
    socket_path = str(tmp_path / "redis.sock")
    process = subprocess.Popen(  # noqa: S603 - fixed local test executable/arguments
        [
            executable,
            "--port",
            "0",
            "--save",
            "",
            "--appendonly",
            "no",
            "--unixsocket",
            socket_path,
            "--unixsocketperm",
            "700",
            "--dir",
            str(tmp_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 5.0
    client: redis.Redis | None = None
    while time.monotonic() < deadline:
        try:
            client = redis.Redis(unix_socket_path=socket_path, decode_responses=False)
            if client.ping():
                break
        except (OSError, redis.RedisError):
            time.sleep(0.02)
    else:
        process.terminate()
        process.wait(timeout=5)
        pytest.fail("ephemeral redis-server did not become ready")
    assert client is not None
    client.flushdb()
    try:
        yield client
    finally:
        client.close()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_real_redis_lua_publish_idempotent_replay_and_reopen(
    real_redis_client: redis.Redis,
) -> None:
    seconds, microseconds = real_redis_client.time()
    generated_at_ms = seconds * 1_000 + (microseconds + 999) // 1_000
    context = _security_context()
    surface = _surface_for_redis_clock(generated_at_ms)

    first = publish_liquidation_surface(
        real_redis_client,
        surface,
        security_context=context,
    )
    replay = publish_liquidation_surface(
        real_redis_client,
        surface,
        security_context=context,
    )
    reopened = reopen_latest_liquidation_surface(
        real_redis_client,
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        security_context=context,
    )

    assert first.trainer_authority is False
    assert first.trainer_authority_reason == (
        "TRAINER_SOURCE_ADMISSION_AND_DECISION_TIME_REVALIDATION_REQUIRED"
    )
    assert replay.surface_id == first.surface_id
    assert replay.receipt_sha256 == first.receipt_sha256
    assert reopened.surface_id == first.surface_id
    assert reopened.trainer_authority is False
    assert real_redis_client.pttl(first.surface_archive_key) > real_redis_client.pttl(
        first.surface_receipt_key
    )


def test_real_redis_replay_never_lets_pointer_outlive_receipt(
    real_redis_client: redis.Redis,
) -> None:
    seconds, microseconds = real_redis_client.time()
    generated_at_ms = seconds * 1_000 + (microseconds + 999) // 1_000
    context = _security_context()
    surface = _surface_for_redis_clock(generated_at_ms)
    published = publish_liquidation_surface(
        real_redis_client,
        surface,
        security_context=context,
    )

    for _iteration in range(128):
        publish_liquidation_surface(
            real_redis_client,
            surface,
            security_context=context,
        )
        receipt_deadline = int(
            real_redis_client.execute_command("PEXPIRETIME", published.surface_receipt_key)
        )
        pointer_deadline = int(
            real_redis_client.execute_command("PEXPIRETIME", published.latest_pointer_key)
        )
        assert pointer_deadline <= receipt_deadline


def test_real_redis_reopen_rejects_pointer_ttl_outliving_receipt(
    real_redis_client: redis.Redis,
) -> None:
    seconds, microseconds = real_redis_client.time()
    generated_at_ms = seconds * 1_000 + (microseconds + 999) // 1_000
    context = _security_context()
    published = publish_liquidation_surface(
        real_redis_client,
        _surface_for_redis_clock(generated_at_ms),
        security_context=context,
    )
    receipt_pttl = real_redis_client.pttl(published.surface_receipt_key)
    assert real_redis_client.pexpire(published.latest_pointer_key, receipt_pttl + 1_000)

    with pytest.raises(
        SurfacePublicationIntegrityError,
        match="SURFACE_PUBLICATION_TTL_RELATIONSHIP_INVALID",
    ):
        reopen_latest_liquidation_surface(
            real_redis_client,
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            security_context=context,
        )


def test_eligible_surface_requires_hmac_receipt_and_postvalidation_reopen() -> None:
    client = FakeRedis()
    verified = publish_liquidation_surface(
        client,
        _surface(),
        security_context=_security_context(),
    )

    assert verified.trainer_authority is False
    assert verified.pointer_class == "trainer_eligible"
    assert verified.payload["trainer_authority"] is False
    assert verified.payload["postcommit_receipt_bound"] is True
    assert verified.payload["available_at"] == verified.consumer_reopened_at_ms
    assert verified.redis_reopened_at_ms <= verified.consumer_reopened_at_ms
    assert verified.receipt["trainer_authority"] is False
    assert verified.receipt["archived_trainer_authority"] is False
    assert len(verified.receipt["receipt_hmac_sha256"]) == 64
    archived = json.loads(client.values[verified.surface_archive_key])
    assert archived["trainer_authority"] is False
    assert archived["available_at"] is None
    assert client.eval_calls == [
        "read_pointer",
        "read_pointer",
        "prepare",
        "commit",
        "reopen",
        "confirm",
    ]


def test_verified_payload_and_receipt_are_deeply_immutable() -> None:
    verified = publish_liquidation_surface(
        FakeRedis(),
        _surface(),
        security_context=_security_context(),
    )

    with pytest.raises(TypeError):
        verified.payload["current_price"] = 1.0  # type: ignore[index]
    with pytest.raises(TypeError):
        verified.receipt["trainer_authority"] = True  # type: ignore[index]
    assert isinstance(verified.payload["long_levels"], tuple)
    with pytest.raises(AttributeError):
        verified.payload["long_levels"].append({"price": 1.0})


def test_postvalidation_rejects_pointer_ttl_outliving_receipt() -> None:
    client = FakeRedis()

    def invert_ttls(store: FakeRedis, keys: list[str], _args: list[object]) -> None:
        store.expires_at_ms[keys[2]] = store.expires_at_ms[keys[1]] + 1

    client.confirm_hook = invert_ttls
    with pytest.raises(
        SurfacePublicationIntegrityError,
        match="SURFACE_PUBLICATION_TTL_RELATIONSHIP_INVALID",
    ):
        publish_liquidation_surface(
            client,
            _surface(),
            security_context=_security_context(),
        )


def test_degraded_publication_advances_observation_not_trainer_pointer() -> None:
    client = FakeRedis()
    context = _security_context()
    eligible = publish_liquidation_surface(client, _surface(), security_context=context)
    degraded = publish_liquidation_surface(
        client,
        _surface(
            as_of_ms=AS_OF_MS + 50,
            generated_at_ms=GENERATED_AT_MS + 50,
            brackets=(),
        ),
        security_context=context,
    )

    assert degraded.trainer_authority is False
    assert degraded.pointer_class == "observation"
    assert degraded.trainer_authority_reason == "CURRENT_EXCHANGE_BRACKET_EVIDENCE_MISSING"
    latest_trainer = reopen_latest_liquidation_surface(
        client,
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        security_context=context,
    )
    latest_observation = reopen_latest_liquidation_surface(
        client,
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        security_context=context,
        trainer_eligible_only=False,
    )
    assert latest_trainer.surface_id == eligible.surface_id
    assert latest_trainer.trainer_authority is False
    assert latest_observation.surface_id == degraded.surface_id
    assert latest_observation.trainer_authority is False


def test_observation_reopen_never_grants_authority_even_for_eligible_payload() -> None:
    client = FakeRedis()
    context = _security_context()
    publish_liquidation_surface(client, _surface(), security_context=context)

    observed = reopen_latest_liquidation_surface(
        client,
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        security_context=context,
        trainer_eligible_only=False,
    )

    assert observed.trainer_authority is False
    assert observed.trainer_authority_reason == "TRAINER_ELIGIBLE_POINTER_REOPEN_REQUIRED"


def test_exact_idempotent_retry_preserves_receipt_and_refreshes_ttls() -> None:
    client = FakeRedis()
    context = _security_context()
    first = publish_liquidation_surface(client, _surface(), security_context=context)
    first_expiry = client.expires_at_ms[first.surface_receipt_key]
    second = publish_liquidation_surface(client, _surface(), security_context=context)

    assert second.surface_id == first.surface_id
    assert second.receipt_sha256 == first.receipt_sha256
    assert second.archive_postcommit_at_ms == first.archive_postcommit_at_ms
    assert client.expires_at_ms[first.surface_receipt_key] > first_expiry


def test_hmac_context_mismatch_fails_closed() -> None:
    client = FakeRedis()
    good = _security_context()
    publish_liquidation_surface(client, _surface(), security_context=good)

    with pytest.raises(SurfacePublicationIntegrityError, match="SURFACE_RECEIPT_HMAC_INVALID"):
        reopen_latest_liquidation_surface(
            client,
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            security_context=_security_context(key=b"different-publication-test-key-01"),
        )


def test_account_scope_keeps_receipts_and_pointers_isolated() -> None:
    client = FakeRedis()
    first_context = _security_context()
    second_metadata = {**SCOPE_METADATA, "credential_binding_id": "mainnet:trainer:SECOND"}
    second_context = build_surface_publication_security_context(
        scope_metadata=second_metadata,
        hmac_key=b"second-publication-test-key-000001",
        auth_key_id="surface-publication-v1",
    )
    first = publish_liquidation_surface(client, _surface(), security_context=first_context)
    second = publish_liquidation_surface(client, _surface(), security_context=second_context)

    assert first.surface_id == second.surface_id
    assert first.surface_archive_key == second.surface_archive_key
    assert first.surface_receipt_key != second.surface_receipt_key
    assert first.latest_pointer_key != second.latest_pointer_key


def test_archive_byte_mutation_is_detected() -> None:
    client = FakeRedis()
    context = _security_context()
    verified = publish_liquidation_surface(client, _surface(), security_context=context)
    client.values[verified.surface_archive_key] += b" "

    with pytest.raises(SurfacePublicationIntegrityError):
        reopen_latest_liquidation_surface(
            client,
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            security_context=context,
        )


def test_receipt_rehash_without_hmac_key_is_detected() -> None:
    client = FakeRedis()
    context = _security_context()
    verified = publish_liquidation_surface(client, _surface(), security_context=context)
    receipt = json.loads(client.values[verified.surface_receipt_key])
    receipt["accuracy_class"] = "FORGED"
    unsigned = dict(receipt)
    unsigned.pop("receipt_sha256")
    unsigned.pop("receipt_hmac_sha256")
    receipt["receipt_sha256"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    client.values[verified.surface_receipt_key] = json.dumps(
        receipt, sort_keys=True, separators=(",", ":")
    ).encode()

    with pytest.raises(SurfacePublicationIntegrityError, match="SURFACE_RECEIPT_HMAC_INVALID"):
        reopen_latest_liquidation_surface(
            client,
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            security_context=context,
        )


def test_pointer_predecessor_race_is_rejected() -> None:
    client = FakeRedis()

    def race(store: FakeRedis, keys: list[str], _args: list[object]) -> None:
        store.values[keys[2]] = (
            f"{AS_OF_MS + 1:019d}:{GENERATED_AT_MS + 1:019d}:v2_lsurf_{'f' * 64}"
        ).encode()

    client.commit_hook = race
    with pytest.raises(
        SurfacePublicationIntegrityError,
        match="SURFACE_OBSERVATION_POINTER_PREDECESSOR_MISMATCH",
    ):
        publish_liquidation_surface(
            client,
            _surface(),
            security_context=_security_context(),
        )


def test_stale_writer_cannot_regress_latest_pointer() -> None:
    client = FakeRedis(now_ms=GENERATED_AT_MS + 500)
    context = _security_context()
    newer = _surface(as_of_ms=AS_OF_MS + 100, generated_at_ms=GENERATED_AT_MS + 100)
    publish_liquidation_surface(client, newer, security_context=context)

    with pytest.raises(
        SurfacePublicationIntegrityError,
        match="SURFACE_LATEST_POINTER_REGRESSION_REJECTED",
    ):
        publish_liquidation_surface(client, _surface(), security_context=context)


def test_equal_clock_different_payload_is_a_conflict() -> None:
    client = FakeRedis()
    context = _security_context()
    first = _surface()
    second = _refresh_model_hash({**first, "source_input_sha256": "e" * 64})
    publish_liquidation_surface(client, first, security_context=context)

    with pytest.raises(
        SurfacePublicationIntegrityError,
        match="SURFACE_LATEST_POINTER_EQUAL_CLOCK_CONFLICT",
    ):
        publish_liquidation_surface(client, second, security_context=context)


def test_postvalidation_state_change_is_detected() -> None:
    client = FakeRedis()

    def corrupt(store: FakeRedis, keys: list[str], _args: list[object]) -> None:
        store.values[keys[0]] += b" "

    client.confirm_hook = corrupt
    with pytest.raises(
        SurfacePublicationIntegrityError,
        match="SURFACE_ARCHIVE_CHANGED_AFTER_VALIDATION",
    ):
        publish_liquidation_surface(
            client,
            _surface(),
            security_context=_security_context(),
        )


def test_adaptive_validity_is_inclusive_and_bracket_expiry_is_exclusive() -> None:
    context = _security_context()
    surface = _surface()
    adaptive_until = surface["adaptive_source_valid_until"]
    inclusive = FakeRedis(now_ms=adaptive_until, clock_step_ms=0)
    verified = publish_liquidation_surface(inclusive, surface, security_context=context)
    assert verified.consumer_reopened_at_ms == adaptive_until

    bracket_surface = _surface(
        brackets=(
            replace(
                _bracket(),
                expires_at_ms=GENERATED_AT_MS + 100,
            ),
        )
    )
    bracket_expiry = bracket_surface["bracket_valid_until"]
    exclusive = FakeRedis(now_ms=bracket_expiry, clock_step_ms=0)
    with pytest.raises(SurfacePublicationIntegrityError, match="SURFACE_BRACKET_EVIDENCE_EXPIRED"):
        publish_liquidation_surface(exclusive, bracket_surface, security_context=context)


def test_positive_authority_and_self_hash_tampering_are_rejected_before_redis() -> None:
    context = _security_context()
    forged = _surface()
    forged["trainer_authority"] = True
    forged = _refresh_model_hash(forged)
    client = FakeRedis()
    with pytest.raises(
        SurfacePublicationValidationError,
        match="SURFACE_PUBLICATION_CANDIDATE_CONTRACT_INVALID",
    ):
        publish_liquidation_surface(client, forged, security_context=context)
    assert client.eval_calls == []

    bad_hash = _surface()
    bad_hash["current_price"] = 101.0
    with pytest.raises(
        SurfacePublicationValidationError,
        match="SURFACE_PUBLICATION_MODEL_PAYLOAD_SHA256_MISMATCH",
    ):
        publish_liquidation_surface(client, bad_hash, security_context=context)


def test_missing_trainer_pointer_does_not_fall_back_to_observation() -> None:
    client = FakeRedis()
    context = _security_context()
    publish_liquidation_surface(
        client,
        _surface(brackets=()),
        security_context=context,
    )

    with pytest.raises(SurfacePublicationIntegrityError, match="SURFACE_LATEST_POINTER_MISSING"):
        reopen_latest_liquidation_surface(
            client,
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            security_context=context,
        )


def test_security_context_rejects_short_keys_and_secret_metadata_fields() -> None:
    with pytest.raises(
        SurfacePublicationValidationError,
        match="SURFACE_PUBLICATION_HMAC_KEY_MISSING_OR_TOO_SHORT",
    ):
        build_surface_publication_security_context(
            scope_metadata=SCOPE_METADATA,
            hmac_key=b"short",
            auth_key_id="surface-publication-v1",
        )
    with pytest.raises(
        SurfacePublicationValidationError,
        match="SURFACE_PUBLICATION_SCOPE_METADATA_CONTAINS_SECRET_FIELD",
    ):
        build_surface_publication_security_context(
            scope_metadata={**SCOPE_METADATA, "api_secret": "must-not-enter-scope"},
            hmac_key=b"publication-test-key-material-0001",
            auth_key_id="surface-publication-v1",
        )


def test_reopen_rejects_oversized_timeframe_key_token_before_redis() -> None:
    client = FakeRedis()
    with pytest.raises(
        SurfacePublicationValidationError,
        match="SURFACE_PUBLICATION_TIMEFRAME_INVALID",
    ):
        reopen_latest_liquidation_surface(
            client,
            symbol=SYMBOL,
            timeframe=f"{'1' * 16}m",
            security_context=_security_context(),
        )
    assert client.eval_calls == []


def test_verified_result_cannot_be_constructed_by_callers() -> None:
    with pytest.raises(
        SurfacePublicationValidationError,
        match="SURFACE_PUBLICATION_FACTORY_CONSTRUCTION_REQUIRED",
    ):
        VerifiedLiquidationSurface(
            surface_id=f"v2_lsurf_{'a' * 64}",
            surface_archive_key="archive",
            surface_receipt_key="receipt",
            latest_pointer_key="pointer",
            publication_scope_sha256="b" * 64,
            pointer_class="trainer_eligible",
            archive_payload_sha256="c" * 64,
            receipt_sha256="d" * 64,
            archive_postcommit_at_ms=1,
            redis_reopened_at_ms=2,
            consumer_reopened_at_ms=3,
            trainer_authority=True,
            trainer_authority_reason="forged",
            payload={
                "postcommit_receipt_bound": True,
                "trainer_authority": True,
                "available_at": 3,
            },
            receipt={},
            _construction_token=object(),
        )


def test_verified_result_rejects_dataclass_replacement_of_reopen_evidence() -> None:
    client = FakeRedis()
    verified = publish_liquidation_surface(
        client,
        _surface(),
        security_context=_security_context(),
    )
    mutations = (
        {"surface_id": f"v2_lsurf_{'e' * 64}"},
        {"latest_pointer_key": f"{verified.latest_pointer_key}:forged"},
        {"redis_reopened_at_ms": verified.redis_reopened_at_ms - 1},
        {"trainer_authority_reason": "FORGED"},
        {"receipt": MappingProxyType({**dict(verified.receipt), "forged": True})},
    )

    for mutation in mutations:
        with pytest.raises(
            SurfacePublicationValidationError,
            match="VERIFIED_SURFACE_AUTHORITY_OR_CLOCK_INVALID",
        ):
            replace(verified, **mutation)
