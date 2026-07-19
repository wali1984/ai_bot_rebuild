from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import pytest

from v2.backend.app.services.paper_trade_management import paper_position_state_envelope as state

EVENT_TIME = "2026-07-19T12:00:00.000000Z"
GENERATED_AT = "2026-07-19T12:00:00.100000Z"
ATTEMPTED_AT = "2026-07-19T12:00:00.500000Z"
POINTER_AT = datetime(2026, 7, 19, 12, 0, 1, tzinfo=UTC)
AVAILABLE_AT = datetime(2026, 7, 19, 12, 0, 2, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 7, 19, 12, 0, 3, tzinfo=UTC)
BLOCKED_AT = datetime(2026, 7, 19, 12, 0, 4, tzinfo=UTC)
SESSION_ID = "paper_session_current"
TTL_SECONDS = 30 * 24 * 60 * 60


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _session_payload(
    session_id: str = SESSION_ID,
    *,
    nonce: str = "reset_nonce_1",
) -> bytes:
    return json.dumps(
        {
            "schema_version": "v2_paper_3000_session_v1",
            "paper_session_id": session_id,
            "reset_session_id": session_id,
            "session_nonce": nonce,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }
    ).encode()


def _row(
    *,
    symbol: str = "BTCUSDT",
    position_id: str = "paper_pos_BTCUSDT",
    generation_id: str = "generation-btc-1",
    side: str = "long",
    session_id: str = SESSION_ID,
) -> dict[str, object]:
    return {
        "position_id": position_id,
        "position_generation_id": generation_id,
        "symbol": symbol,
        "side": side,
        "position_state": "OPEN_POSITION",
        "paper_session_id": session_id,
        "session_id": session_id,
        "reset_session_id": session_id,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "unrealized_pnl_bps": 12.5,
    }


def _legacy_bytes(rows: list[object]) -> bytes:
    # Intentionally mirrors the existing non-canonical legacy list ABI.
    return json.dumps(rows).encode()


def _artifact(
    rows: list[object] | None = None,
    *,
    event_time: str = EVENT_TIME,
    generated_at: str = GENERATED_AT,
    previous_generation_id: str = "GENESIS",
    session_id: str = SESSION_ID,
    session_payload_bytes: bytes | None = None,
    authorized_reset_predecessor_head_token_bytes: bytes | None = None,
) -> state.PaperPositionStateGeneration:
    return state.build_paper_position_state_generation(
        legacy_payload_bytes=_legacy_bytes(rows or []),
        session_payload_bytes=(
            session_payload_bytes
            if session_payload_bytes is not None
            else _session_payload(session_id)
        ),
        paper_session_id=session_id,
        state_event_time=event_time,
        state_generated_at=generated_at,
        previous_generation_id=previous_generation_id,
        authorized_reset_predecessor_head_token_bytes=(
            authorized_reset_predecessor_head_token_bytes
        ),
    )


def _redis_time_parts(value: datetime) -> tuple[bytes, bytes]:
    return str(int(value.timestamp())).encode(), str(value.microsecond).encode()


class FakeAtomicRedis:
    redis_response_mode = state.RAW_REDIS_SCRIPT_RESPONSE_MODE

    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.ttls: dict[str, int] = {}
        self.calls: list[tuple[str, tuple[str, ...], tuple[object, ...]]] = []
        self.pointer_time = POINTER_AT
        self.available_time = AVAILABLE_AT
        self.observed_time = OBSERVED_AT
        self.blocked_time = BLOCKED_AT
        self.generation_readback_override: object | None = None
        self.pointer_readback_override: object | None = None
        self.available_receipt_override: object | None = None
        self.blocked_readback_override: object | None = None
        self.blocked_head_after_override: object | None = None
        self.advance_head_before_available: bytes | None = None
        self.raise_generation_once = False
        self.raise_ready_once = False
        self.raise_ready_after_commit_once = False
        self.raise_available_once = False
        self.raise_blocked = False
        self.generation_response_as_tuple = False

    def install_inputs(
        self,
        artifact: state.PaperPositionStateGeneration,
        *,
        ttl_ms: int = TTL_SECONDS * 1_000,
        session_ttl_ms: int = -1,
    ) -> None:
        self.values[state.PAPER_POSITIONS_LEGACY_KEY] = artifact.legacy_payload_bytes
        self.values[state.PAPER_OPEN_POSITIONS_LEGACY_KEY] = artifact.legacy_payload_bytes
        self.values[state.PAPER_SESSION_REDIS_KEY] = artifact.session_payload_bytes
        self.ttls[state.PAPER_POSITIONS_LEGACY_KEY] = ttl_ms
        self.ttls[state.PAPER_OPEN_POSITIONS_LEGACY_KEY] = ttl_ms
        self.ttls[state.PAPER_SESSION_REDIS_KEY] = session_ttl_ms

    def _ready(self, keys: tuple[str, ...], args: tuple[object, ...]) -> list[object]:
        if self.raise_ready_once:
            self.raise_ready_once = False
            raise RuntimeError("simulated pointer transport failure")
        generation_key, positions_key, open_positions_key, session_key, head_key, pointer_key = keys
        generation_expected = args[0]
        legacy_expected = args[1]
        session_expected = args[2]
        expected_head = args[3]
        target_head = args[4]
        pointer = args[5]
        absent_sentinel = args[6]
        assert type(generation_expected) is bytes
        assert type(legacy_expected) is bytes
        assert type(session_expected) is bytes
        assert type(expected_head) is bytes
        assert type(target_head) is bytes
        assert type(pointer) is bytes
        assert type(absent_sentinel) is bytes

        code = 0
        if generation_key not in self.values:
            code = 1
        elif self.values[generation_key] != generation_expected:
            code = 2
        elif positions_key not in self.values:
            code = 3
        elif self.values[positions_key] != legacy_expected:
            code = 4
        elif open_positions_key not in self.values:
            code = 5
        elif self.values[open_positions_key] != legacy_expected:
            code = 6
        elif session_key not in self.values:
            code = 7
        elif self.values[session_key] != session_expected:
            code = 8
        dependency_ttl = min(
            self.ttls.get(generation_key, -2),
            self.ttls.get(positions_key, -2),
            self.ttls.get(open_positions_key, -2),
        )
        session_ttl = self.ttls.get(session_key, -2)
        if code == 0 and session_ttl != -1:
            if session_ttl <= 2:
                code = 9
            else:
                dependency_ttl = min(dependency_ttl, session_ttl)
        if code == 0 and dependency_ttl <= 2:
            code = 9

        current_head = self.values.get(head_key)
        current_pointer = self.values.get(pointer_key)
        idempotent = 0
        if code == 0 and current_head == target_head:
            if current_pointer is None:
                code = 13
            elif current_pointer != pointer:
                code = 14
            else:
                idempotent = 1
        elif code == 0 and expected_head == absent_sentinel:
            if current_head is not None:
                code = 11
            elif current_pointer is not None:
                code = 19
        elif code == 0:
            if current_head is None:
                code = 10
            elif current_head != expected_head:
                code = 12

        applied_ttl = -2
        if code == 0 and idempotent == 0:
            applied_ttl = dependency_ttl - 1
            self.values[pointer_key] = pointer
            self.values[head_key] = target_head
            self.ttls[pointer_key] = applied_ttl
            self.ttls[head_key] = applied_ttl
        elif code == 0:
            applied_ttl = min(self.ttls.get(head_key, -2), self.ttls.get(pointer_key, -2))
            if applied_ttl <= 1 or applied_ttl > dependency_ttl:
                code = 15

        pointer_readback: object = self.values.get(pointer_key)
        if self.pointer_readback_override is not None:
            pointer_readback = self.pointer_readback_override
        head_readback: object = self.values.get(head_key)
        seconds, micros = _redis_time_parts(self.pointer_time)
        response = [
            code,
            idempotent,
            pointer_readback,
            head_readback,
            applied_ttl,
            self.ttls.get(pointer_key, -2),
            self.ttls.get(head_key, -2),
            seconds,
            micros,
        ]
        if self.raise_ready_after_commit_once and code == 0:
            self.raise_ready_after_commit_once = False
            raise RuntimeError("simulated response loss after pointer commit")
        return response

    def _available(self, keys: tuple[str, ...], args: tuple[object, ...]) -> list[object]:
        if self.raise_available_once:
            self.raise_available_once = False
            raise RuntimeError("simulated availability transport failure")
        (
            generation_key,
            positions_key,
            open_positions_key,
            session_key,
            head_key,
            pointer_key,
            receipt_key,
        ) = keys
        generation_expected, legacy_expected, session_expected, target_head, pointer = args
        assert all(
            type(value) is bytes
            for value in (
                generation_expected,
                legacy_expected,
                session_expected,
                target_head,
                pointer,
            )
        )
        if self.advance_head_before_available is not None:
            self.values[head_key] = self.advance_head_before_available

        code = 0
        if generation_key not in self.values:
            code = 1
        elif self.values[generation_key] != generation_expected:
            code = 2
        elif positions_key not in self.values:
            code = 3
        elif self.values[positions_key] != legacy_expected:
            code = 4
        elif open_positions_key not in self.values:
            code = 5
        elif self.values[open_positions_key] != legacy_expected:
            code = 6
        elif session_key not in self.values:
            code = 7
        elif self.values[session_key] != session_expected:
            code = 8
        elif head_key not in self.values:
            code = 10
        elif self.values[head_key] != target_head:
            code = 12
        elif pointer_key not in self.values:
            code = 13
        elif self.values[pointer_key] != pointer:
            code = 14
        dependency_ttl = min(
            self.ttls.get(generation_key, -2),
            self.ttls.get(positions_key, -2),
            self.ttls.get(open_positions_key, -2),
            self.ttls.get(head_key, -2),
            self.ttls.get(pointer_key, -2),
        )
        session_ttl = self.ttls.get(session_key, -2)
        if code == 0 and session_ttl != -1:
            if session_ttl <= 1:
                code = 18
            else:
                dependency_ttl = min(dependency_ttl, session_ttl)
        if code == 0 and dependency_ttl <= 1:
            code = 18

        created = 0
        if code == 0 and receipt_key not in self.values:
            receipt = (
                f"{int(self.available_time.timestamp())}:{self.available_time.microsecond}"
            ).encode()
            self.values[receipt_key] = receipt
            self.ttls[receipt_key] = dependency_ttl - 1
            created = 1
        receipt_readback: object = self.values.get(receipt_key)
        if self.available_receipt_override is not None:
            receipt_readback = self.available_receipt_override
        seconds, micros = _redis_time_parts(self.observed_time)
        return [
            code,
            created,
            receipt_readback,
            self.ttls.get(receipt_key, -2),
            seconds,
            micros,
        ]

    def __call__(
        self,
        script: str,
        keys: tuple[str, ...],
        args: tuple[state.ScriptArgument, ...],
    ) -> object:
        self.calls.append((script, keys, args))
        if script == state.GENERATION_PUBLISH_LUA:
            if self.raise_generation_once:
                self.raise_generation_once = False
                raise RuntimeError("simulated generation transport failure")
            key = keys[0]
            expected = args[0]
            ttl = args[1]
            assert type(expected) is bytes
            assert type(ttl) is int
            created = key not in self.values
            if created:
                self.values[key] = expected
                self.ttls[key] = ttl
            generation_readback: object = self.values.get(key)
            if self.generation_readback_override is not None:
                generation_readback = self.generation_readback_override
            response: list[object] = [
                int(created),
                generation_readback,
                self.ttls.get(key, -2),
            ]
            return tuple(response) if self.generation_response_as_tuple else response

        if script == state.READY_POINTER_PUBLISH_LUA:
            return self._ready(keys, args)

        if script == state.AVAILABLE_AT_OBSERVE_LUA:
            return self._available(keys, args)

        if script == state.BLOCKED_ATTEMPT_PUBLISH_LUA:
            if self.raise_blocked:
                raise RuntimeError("simulated blocked evidence failure")
            evidence_key, head_key = keys
            evidence = args[0]
            ttl = args[1]
            assert type(evidence) is bytes
            assert type(ttl) is int
            head_before: object = self.values.get(head_key)
            created = evidence_key not in self.values
            if created:
                self.values[evidence_key] = evidence
                self.ttls[evidence_key] = ttl
            readback: object = self.values.get(evidence_key)
            if self.blocked_readback_override is not None:
                readback = self.blocked_readback_override
            head_after: object = self.values.get(head_key)
            if self.blocked_head_after_override is not None:
                head_after = self.blocked_head_after_override
            seconds, micros = _redis_time_parts(self.blocked_time)
            return [
                int(created),
                readback,
                self.ttls.get(evidence_key, -2),
                head_before,
                head_after,
                seconds,
                micros,
            ]
        raise AssertionError("unexpected script")


def _publish(
    artifact: state.PaperPositionStateGeneration,
    fake: FakeAtomicRedis,
) -> state.PaperPositionStatePublicationResult:
    return state.publish_paper_position_state_generation(
        artifact,
        execute_script=fake,
        ttl_seconds=TTL_SECONDS,
        publication_attempted_at=ATTEMPTED_AT,
    )


def _install_and_publish(
    artifact: state.PaperPositionStateGeneration,
    fake: FakeAtomicRedis,
) -> state.PaperPositionStatePublicationResult:
    fake.install_inputs(artifact)
    return _publish(artifact, fake)


def _child(
    parent: state.PaperPositionStateGeneration,
    *,
    symbol: str,
    position_id: str,
    generation_id: str,
    event_suffix: int,
) -> state.PaperPositionStateGeneration:
    return _artifact(
        [
            _row(
                symbol=symbol,
                position_id=position_id,
                generation_id=generation_id,
                session_id=parent.paper_session_id,
            )
        ],
        event_time=f"2026-07-19T12:00:00.{event_suffix:06d}Z",
        generated_at=f"2026-07-19T12:00:00.{event_suffix + 100000:06d}Z",
        previous_generation_id=parent.producer_generation_id,
        session_id=parent.paper_session_id,
        session_payload_bytes=parent.session_payload_bytes,
    )


def test_empty_state_is_externally_session_bound_hash_bound_and_nonconsumable() -> None:
    artifact = _artifact()
    envelope = json.loads(artifact.generation_payload_bytes)
    material = envelope["state_material"]

    assert artifact.empty_state is True
    assert artifact.row_count == 0
    assert material["rows"] == []
    assert material["canonical_rows_sha256"] == hashlib.sha256(b"[]").hexdigest()
    assert material["state_available_at"] is None
    assert material["paper_session_binding"] == {
        "schema_version": state.PAPER_POSITION_SESSION_BINDING_SCHEMA_VERSION,
        "paper_session_id": SESSION_ID,
        "session_key": state.PAPER_SESSION_REDIS_KEY,
        "session_payload_sha256": hashlib.sha256(artifact.session_payload_bytes).hexdigest(),
        "session_payload_byte_count": len(artifact.session_payload_bytes),
        "session_binding_token_sha256": artifact.session_binding_token_sha256,
        "exact_session_key_read_required_at_pointer_commit": True,
    }
    assert material["safety"] == {
        "schema_version": state.PAPER_POSITION_SAFETY_SCHEMA_VERSION,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "trainer_consumable": False,
        "durable_pit_evidence": False,
        "durable_generation_immutability_verified": False,
        "cas_readback_verified": False,
        "ledger_postcommit_readback_verified": False,
    }
    assert (
        envelope["state_material_sha256"] == hashlib.sha256(_canonical_bytes(material)).hexdigest()
    )


def test_membership_projection_is_canonical_while_external_bytes_remain_exact() -> None:
    eth = _row(
        symbol="ETHUSDT",
        position_id="paper_pos_ETHUSDT",
        generation_id="generation-eth-1",
        side="short",
    )
    btc = _row()
    first = _artifact([eth, btc])
    second = _artifact([btc, eth])
    first_rows = json.loads(first.generation_payload_bytes)["state_material"]["rows"]

    assert [row["symbol"] for row in first_rows] == ["BTCUSDT", "ETHUSDT"]
    assert set(first_rows[0]) == state._MEMBERSHIP_ROW_FIELDS  # noqa: SLF001
    assert first.generation_payload_bytes == second.generation_payload_bytes
    assert first.producer_generation_id == second.producer_generation_id
    assert first.legacy_payload_sha256 != second.legacy_payload_sha256


@pytest.mark.parametrize(
    ("rows", "reason"),
    [
        (["not-a-row"], "POSITION_ROW_NOT_MAPPING"),
        ([{**_row(), "position_id": None}], "POSITION_POSITION_ID_INVALID"),
        ([{**_row(), "symbol": "btcusdt"}], "POSITION_SYMBOL_INVALID"),
        ([{**_row(), "side": "flat"}], "POSITION_SIDE_INVALID"),
        ([{**_row(), "side": []}], "POSITION_SIDE_INVALID"),
        ([{**_row(), "position_state": "CLOSED"}], "POSITION_STATE_NOT_OPEN"),
        ([{**_row(), "paper_session_id": "other"}], "POSITION_PAPER_SESSION_MISMATCH"),
        ([{**_row(), "session_id": "other"}], "POSITION_PAPER_SESSION_ALIAS_CONFLICT"),
        ([{**_row(), "paper_only": 1}], "POSITION_NOT_EXPLICITLY_PAPER_ONLY"),
        ([{**_row(), "routes_to_live": None}], "POSITION_ROUTES_TO_LIVE_NOT_FALSE"),
        ([{**_row(), "places_real_order": 0}], "POSITION_PLACES_REAL_ORDER_NOT_FALSE"),
        ([_row(), _row()], "POSITION_IDENTITY_DUPLICATE"),
    ],
)
def test_malformed_membership_rows_fail_closed(rows: list[object], reason: str) -> None:
    with pytest.raises(state.PaperPositionStateValidationError, match=reason):
        _artifact(rows)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ({"paper_session_id": None}, "PAPER_SESSION_PAYLOAD_IDENTITY_MISMATCH"),
        ({"reset_session_id": "other"}, "PAPER_SESSION_PAYLOAD_IDENTITY_CONFLICT"),
        ({"reset_session_id": []}, "PAPER_SESSION_PAYLOAD_IDENTITY_INVALID"),
        ({"paper_only": False}, "PAPER_SESSION_PAYLOAD_NOT_EXPLICITLY_PAPER_ONLY"),
        ({"routes_to_live": True}, "PAPER_SESSION_PAYLOAD_ROUTES_TO_LIVE_NOT_FALSE"),
        ({"places_real_order": True}, "PAPER_SESSION_PAYLOAD_PLACES_REAL_ORDER_NOT_FALSE"),
    ],
)
def test_session_binding_payload_must_prove_exact_paper_session(
    mutation: dict[str, object], reason: str
) -> None:
    payload = json.loads(_session_payload())
    payload.update(mutation)
    with pytest.raises(state.PaperPositionStateValidationError, match=reason):
        _artifact(session_payload_bytes=json.dumps(payload).encode())


def test_ready_publication_uses_atomic_head_cas_and_postcommit_redis_receipt() -> None:
    artifact = _artifact([_row()])
    fake = FakeAtomicRedis()
    result = _install_and_publish(artifact, fake)

    assert result.status == "READY"
    assert result.head_cas_status == "COMMITTED_TO_TARGET"
    assert result.latest_pointer_mutation_status == "MUTATED_TO_TARGET"
    assert result.latest_pointer_mutated_by_publication is True
    assert result.availability_receipt_status == "VERIFIED"
    assert result.publication_attempted_at == ATTEMPTED_AT
    assert result.state_available_at == "2026-07-19T12:00:02.000000Z"
    assert result.pointer_readback_verified_at == "2026-07-19T12:00:01.000000Z"
    assert result.availability_receipt_observed_at == "2026-07-19T12:00:03.000000Z"
    assert result.redis_atomic_predecessor_head_cas_verified is True
    assert result.redis_generation_set_nx_exact_readback_verified is True
    assert result.durable_generation_immutability_verified is False
    assert result.trainer_consumable is False
    assert result.attempt_evidence_written is False
    pointer = json.loads(result.pointer_payload_bytes or b"{}")
    assert pointer["status"] == "READY"
    assert pointer["state"]["state_available_at"] is None
    assert pointer["state"]["availability_receipt"]["receipt_key"] == (
        artifact.availability_receipt_key
    )
    assert pointer["generation"]["durable_generation_immutability_verified"] is False
    assert pointer["head_cas"]["atomic_predecessor_head_cas_verified"] is True
    assert pointer["paper_session_binding"]["session_payload_sha256"] == (
        artifact.session_payload_sha256
    )
    assert fake.values[state.PAPER_POSITION_STATE_HEAD_KEY] == artifact.target_head_token_bytes
    assert fake.values[state.PAPER_POSITION_STATE_POINTER_KEY] == result.pointer_payload_bytes
    assert len(fake.calls) == 3


def test_persistent_session_ttl_is_valid_while_finite_dependencies_bound_pointer() -> None:
    artifact = _artifact([_row()])
    fake = FakeAtomicRedis()
    fake.install_inputs(artifact, session_ttl_ms=-1)

    result = _publish(artifact, fake)

    assert result.status == "READY"
    assert fake.ttls[state.PAPER_SESSION_REDIS_KEY] == -1
    assert result.pointer_ttl_ms == TTL_SECONDS * 1_000 - 1
    assert fake.ttls[artifact.availability_receipt_key] == result.pointer_ttl_ms - 1


def test_finite_session_ttl_still_bounds_pointer_and_availability_receipt() -> None:
    artifact = _artifact([_row()])
    fake = FakeAtomicRedis()
    fake.install_inputs(artifact, session_ttl_ms=10_000)

    result = _publish(artifact, fake)

    assert result.status == "READY"
    assert result.pointer_ttl_ms == 9_999
    assert fake.ttls[artifact.availability_receipt_key] == 9_998


def test_exact_retry_is_idempotent_without_refresh_or_new_availability_clock() -> None:
    artifact = _artifact([_row()])
    fake = FakeAtomicRedis()
    first = _install_and_publish(artifact, fake)
    fake.ttls[artifact.generation_key] -= 5_000
    fake.ttls[state.PAPER_POSITION_STATE_HEAD_KEY] -= 5_000
    fake.ttls[state.PAPER_POSITION_STATE_POINTER_KEY] -= 5_000
    fake.ttls[artifact.availability_receipt_key] -= 5_000
    fake.available_time = datetime(2026, 7, 19, 12, 0, 30, tzinfo=UTC)

    second = _publish(artifact, fake)

    assert first.status == second.status == "READY"
    assert second.head_cas_status == "IDEMPOTENT_TARGET_CONFIRMED"
    assert second.latest_pointer_mutation_status == "ALREADY_TARGET"
    assert second.latest_pointer_mutated_by_publication is False
    assert second.generation_created is False
    assert second.state_available_at == first.state_available_at
    assert first.pointer_ttl_ms is not None
    assert second.pointer_ttl_ms is not None
    assert second.pointer_ttl_ms < first.pointer_ttl_ms


def test_stale_generation_and_blocked_attempt_cannot_regress_or_hide_newer_ready() -> None:
    g1 = _artifact([_row()])
    fake = FakeAtomicRedis()
    assert _install_and_publish(g1, fake).status == "READY"
    g2 = _child(
        g1,
        symbol="ETHUSDT",
        position_id="paper_pos_ETHUSDT",
        generation_id="generation-eth-2",
        event_suffix=200000,
    )
    assert _install_and_publish(g2, fake).status == "READY"
    g2_pointer = fake.values[state.PAPER_POSITION_STATE_POINTER_KEY]
    g2_head = fake.values[state.PAPER_POSITION_STATE_HEAD_KEY]

    fake.install_inputs(g1)
    stale = _publish(g1, fake)

    assert stale.status == "BLOCKED"
    assert stale.rejection_reasons == ("GENESIS_REQUIRES_ABSENT_HEAD",)
    assert stale.head_cas_status == "REJECTED_BEFORE_MUTATION"
    assert stale.attempt_evidence_written is True
    assert stale.latest_pointer_mutation_status == "NOT_MUTATED"
    assert stale.latest_pointer_mutated_by_publication is False
    assert stale.blocked_evidence_mutated_latest_pointer is False
    assert fake.values[state.PAPER_POSITION_STATE_POINTER_KEY] == g2_pointer
    assert fake.values[state.PAPER_POSITION_STATE_HEAD_KEY] == g2_head
    assert (
        json.loads(stale.attempt_evidence_payload_bytes or b"{}")[
            "latest_pointer_mutated_by_publication"
        ]
        is False
    )


def test_fork_from_same_predecessor_has_one_winner_and_loser_cannot_clobber() -> None:
    g1 = _artifact([_row()])
    fake = FakeAtomicRedis()
    assert _install_and_publish(g1, fake).status == "READY"
    left = _child(
        g1,
        symbol="ETHUSDT",
        position_id="paper_pos_ETHUSDT",
        generation_id="generation-left",
        event_suffix=210000,
    )
    right = _child(
        g1,
        symbol="SOLUSDT",
        position_id="paper_pos_SOLUSDT",
        generation_id="generation-right",
        event_suffix=220000,
    )
    assert _install_and_publish(left, fake).status == "READY"
    winning_pointer = fake.values[state.PAPER_POSITION_STATE_POINTER_KEY]
    winning_head = fake.values[state.PAPER_POSITION_STATE_HEAD_KEY]

    loser = _install_and_publish(right, fake)

    assert loser.status == "BLOCKED"
    assert loser.rejection_reasons == ("EXPECTED_PREDECESSOR_HEAD_MISMATCH",)
    assert fake.values[state.PAPER_POSITION_STATE_POINTER_KEY] == winning_pointer
    assert fake.values[state.PAPER_POSITION_STATE_HEAD_KEY] == winning_head


def test_arbitrary_nonexistent_predecessor_is_rejected() -> None:
    fake_previous = f"paper_positions_state_v2_{'0' * 64}"
    artifact = _artifact([_row()], previous_generation_id=fake_previous)
    fake = FakeAtomicRedis()

    result = _install_and_publish(artifact, fake)

    assert result.status == "BLOCKED"
    assert result.rejection_reasons == ("EXPECTED_PREDECESSOR_HEAD_MISSING",)
    assert state.PAPER_POSITION_STATE_POINTER_KEY not in fake.values
    assert state.PAPER_POSITION_STATE_HEAD_KEY not in fake.values


def test_genesis_requires_both_head_and_pointer_absent() -> None:
    artifact = _artifact([_row()])
    fake = FakeAtomicRedis()
    fake.install_inputs(artifact)
    stale_pointer = _canonical_bytes({"status": "stale"})
    fake.values[state.PAPER_POSITION_STATE_POINTER_KEY] = stale_pointer
    fake.ttls[state.PAPER_POSITION_STATE_POINTER_KEY] = TTL_SECONDS * 1_000

    result = _publish(artifact, fake)

    assert result.status == "BLOCKED"
    assert result.rejection_reasons == ("GENESIS_REQUIRES_ABSENT_POINTER",)
    assert fake.values[state.PAPER_POSITION_STATE_POINTER_KEY] == stale_pointer
    assert state.PAPER_POSITION_STATE_HEAD_KEY not in fake.values


def test_protocol_prevents_aba_by_rejecting_old_target_after_head_advanced() -> None:
    g1 = _artifact([_row()])
    fake = FakeAtomicRedis()
    assert _install_and_publish(g1, fake).status == "READY"
    g2 = _child(
        g1,
        symbol="ETHUSDT",
        position_id="paper_pos_ETHUSDT",
        generation_id="generation-eth-2",
        event_suffix=230000,
    )
    assert _install_and_publish(g2, fake).status == "READY"

    fake.install_inputs(g1)
    old_target_retry = _publish(g1, fake)
    fake.install_inputs(g2)
    current_target_retry = _publish(g2, fake)

    assert old_target_retry.status == "BLOCKED"
    assert current_target_retry.status == "READY"
    assert current_target_retry.head_cas_status == "IDEMPOTENT_TARGET_CONFIRMED"
    assert fake.values[state.PAPER_POSITION_STATE_HEAD_KEY] == g2.target_head_token_bytes


def test_session_reset_requires_exact_old_head_and_atomically_transitions_to_new_session() -> None:
    old = _artifact([_row()])
    fake = FakeAtomicRedis()
    assert _install_and_publish(old, fake).status == "READY"
    old_pointer = fake.values[state.PAPER_POSITION_STATE_POINTER_KEY]
    old_head = fake.values[state.PAPER_POSITION_STATE_HEAD_KEY]
    new_session_id = "paper_session_after_reset"
    new_session_payload = _session_payload(new_session_id, nonce="reset_nonce_2")
    unauthorized = _artifact(
        [],
        session_id=new_session_id,
        session_payload_bytes=new_session_payload,
    )
    fake.install_inputs(unauthorized)
    unauthorized_result = _publish(unauthorized, fake)
    assert unauthorized_result.rejection_reasons == ("GENESIS_REQUIRES_ABSENT_HEAD",)
    assert unauthorized_result.latest_pointer_mutated_by_publication is False
    assert fake.values[state.PAPER_POSITION_STATE_POINTER_KEY] == old_pointer
    assert fake.values[state.PAPER_POSITION_STATE_HEAD_KEY] == old_head

    authorized = _artifact(
        [],
        session_id=new_session_id,
        session_payload_bytes=new_session_payload,
        authorized_reset_predecessor_head_token_bytes=old_head,
    )
    fake.install_inputs(authorized)
    reset_result = _publish(authorized, fake)
    reset_retry = _publish(authorized, fake)

    assert old_pointer != fake.values[state.PAPER_POSITION_STATE_POINTER_KEY]
    assert reset_result.status == "READY"
    assert reset_result.head_cas_status == "COMMITTED_TO_TARGET"
    assert authorized.session_transition_mode == state.AUTHORIZED_SESSION_RESET_HEAD_CAS
    assert authorized.expected_head_token_bytes == old_head
    assert (
        authorized.authorized_reset_predecessor_head_token_sha256
        == hashlib.sha256(old_head).hexdigest()
    )
    assert fake.values[state.PAPER_POSITION_STATE_HEAD_KEY] == authorized.target_head_token_bytes
    assert reset_retry.status == "READY"
    assert reset_retry.head_cas_status == "IDEMPOTENT_TARGET_CONFIRMED"

    fake.values[state.PAPER_POSITIONS_LEGACY_KEY] = old.legacy_payload_bytes
    fake.values[state.PAPER_OPEN_POSITIONS_LEGACY_KEY] = old.legacy_payload_bytes
    stale_old_session = _publish(old, fake)
    assert stale_old_session.rejection_reasons == ("PAPER_SESSION_EXACT_BYTES_MISMATCH",)

    successor = _child(
        authorized,
        symbol="SOLUSDT",
        position_id="paper_pos_SOLUSDT",
        generation_id="generation-new-session-successor",
        event_suffix=250000,
    )
    assert _install_and_publish(successor, fake).status == "READY"
    successor_pointer = fake.values[state.PAPER_POSITION_STATE_POINTER_KEY]
    successor_head = fake.values[state.PAPER_POSITION_STATE_HEAD_KEY]
    fake.install_inputs(authorized)
    stale_reset_replay = _publish(authorized, fake)
    assert stale_reset_replay.rejection_reasons == ("EXPECTED_PREDECESSOR_HEAD_MISMATCH",)
    assert fake.values[state.PAPER_POSITION_STATE_POINTER_KEY] == successor_pointer
    assert fake.values[state.PAPER_POSITION_STATE_HEAD_KEY] == successor_head


def test_reset_authorization_cannot_bypass_same_session_or_successor_chain() -> None:
    old = _artifact([_row()])
    with pytest.raises(
        state.PaperPositionStateValidationError,
        match="AUTHORIZED_RESET_REQUIRES_DIFFERENT_PAPER_SESSION_ID",
    ):
        _artifact(
            [],
            session_payload_bytes=_session_payload(SESSION_ID, nonce="reset_nonce_changed_only"),
            authorized_reset_predecessor_head_token_bytes=old.target_head_token_bytes,
        )
    with pytest.raises(
        state.PaperPositionStateValidationError,
        match="AUTHORIZED_RESET_REQUIRES_GENESIS_GENERATION",
    ):
        _artifact(
            [],
            previous_generation_id=old.producer_generation_id,
            authorized_reset_predecessor_head_token_bytes=old.target_head_token_bytes,
        )


def test_authorized_reset_head_validator_rejects_same_id_with_different_nonce() -> None:
    old = _artifact([_row()])
    nonce_only_epoch = _artifact(
        [],
        session_payload_bytes=_session_payload(
            SESSION_ID,
            nonce="validator_nonce_changed_only",
        ),
    )
    assert nonce_only_epoch.session_binding_token_sha256 != old.session_binding_token_sha256

    with pytest.raises(
        state.PaperPositionStateValidationError,
        match="AUTHORIZED_RESET_REQUIRES_DIFFERENT_PAPER_SESSION_ID",
    ):
        state._validated_authorized_reset_head_token(  # noqa: SLF001
            old.target_head_token_bytes,
            requested_paper_session_id=nonce_only_epoch.paper_session_id,
            current_session_binding_token_sha256=(nonce_only_epoch.session_binding_token_sha256),
        )


def test_publication_blocks_same_id_nonce_reset_without_any_redis_mutation() -> None:
    old = _artifact([_row()])
    fake = FakeAtomicRedis()
    assert _install_and_publish(old, fake).status == "READY"
    old_head = fake.values[state.PAPER_POSITION_STATE_HEAD_KEY]
    valid_new_session_id = "paper_session_valid_reset_target"
    valid_reset = _artifact(
        [],
        session_id=valid_new_session_id,
        session_payload_bytes=_session_payload(
            valid_new_session_id,
            nonce="valid_reset_nonce",
        ),
        authorized_reset_predecessor_head_token_bytes=old_head,
    )
    forged_same_id_reset = replace(
        valid_reset,
        paper_session_id=SESSION_ID,
        session_payload_bytes=_session_payload(
            SESSION_ID,
            nonce="forged_nonce_only_reset",
        ),
    )
    values_before = dict(fake.values)
    ttls_before = dict(fake.ttls)
    calls_before = tuple(fake.calls)
    assert valid_reset.availability_receipt_key not in values_before

    with pytest.raises(
        state.PaperPositionStateValidationError,
        match="AUTHORIZED_RESET_REQUIRES_DIFFERENT_PAPER_SESSION_ID",
    ):
        _publish(forged_same_id_reset, fake)

    assert fake.values == values_before
    assert fake.ttls == ttls_before
    assert tuple(fake.calls) == calls_before
    assert fake.values[state.PAPER_POSITION_STATE_HEAD_KEY] == old_head
    assert (
        fake.values[state.PAPER_POSITION_STATE_POINTER_KEY]
        == values_before[state.PAPER_POSITION_STATE_POINTER_KEY]
    )
    assert fake.values[state.PAPER_SESSION_REDIS_KEY] == old.session_payload_bytes
    assert valid_reset.availability_receipt_key not in fake.values


def test_empty_state_cannot_publish_without_external_session_key_proof() -> None:
    artifact = _artifact([])
    fake = FakeAtomicRedis()
    fake.values[state.PAPER_POSITIONS_LEGACY_KEY] = artifact.legacy_payload_bytes
    fake.values[state.PAPER_OPEN_POSITIONS_LEGACY_KEY] = artifact.legacy_payload_bytes
    fake.ttls[state.PAPER_POSITIONS_LEGACY_KEY] = TTL_SECONDS * 1_000
    fake.ttls[state.PAPER_OPEN_POSITIONS_LEGACY_KEY] = TTL_SECONDS * 1_000

    result = _publish(artifact, fake)

    assert result.status == "BLOCKED"
    assert result.rejection_reasons == ("PAPER_SESSION_KEY_MISSING",)


def test_available_at_race_fails_closed_without_clobbering_advanced_head() -> None:
    artifact = _artifact([_row()])
    fake = FakeAtomicRedis()
    fake.install_inputs(artifact)
    advanced_head = _canonical_bytes({"advanced": True})
    fake.advance_head_before_available = advanced_head

    result = _publish(artifact, fake)

    assert result.status == "BLOCKED"
    assert result.rejection_reasons == ("EXPECTED_PREDECESSOR_HEAD_MISMATCH",)
    assert fake.values[state.PAPER_POSITION_STATE_HEAD_KEY] == advanced_head
    assert result.head_cas_status == "COMMITTED_TO_TARGET"
    assert result.latest_pointer_mutated_by_publication is True
    assert result.availability_receipt_status == "REJECTED_BEFORE_WRITE"
    assert result.blocked_evidence_mutated_latest_pointer is False


def test_ready_response_loss_reports_unknown_commit_while_target_may_be_committed() -> None:
    artifact = _artifact([_row()])
    fake = FakeAtomicRedis()
    fake.install_inputs(artifact)
    fake.raise_ready_after_commit_once = True

    result = _publish(artifact, fake)

    assert result.status == "BLOCKED"
    assert result.rejection_reasons == ("READY_POINTER_SCRIPT_EXECUTION_FAILED",)
    assert result.head_cas_status == "COMMIT_OUTCOME_UNKNOWN"
    assert result.latest_pointer_mutation_status == "UNKNOWN"
    assert result.latest_pointer_mutated_by_publication is None
    assert result.availability_receipt_status == "NOT_ATTEMPTED"
    assert result.redis_atomic_predecessor_head_cas_verified is False
    assert fake.values[state.PAPER_POSITION_STATE_HEAD_KEY] == artifact.target_head_token_bytes
    assert fake.values[state.PAPER_POSITION_STATE_POINTER_KEY] == state._ready_pointer_bytes(  # noqa: SLF001
        artifact
    )
    evidence = json.loads(result.attempt_evidence_payload_bytes or b"{}")
    assert evidence["head_cas_status"] == "COMMIT_OUTCOME_UNKNOWN"
    assert evidence["latest_pointer_mutated_by_publication"] is None
    assert evidence["blocked_evidence_mutated_latest_pointer"] is False


def test_postcommit_readback_mismatch_never_claims_precommit_rejection() -> None:
    artifact = _artifact([_row()])
    fake = FakeAtomicRedis()
    fake.install_inputs(artifact)
    fake.pointer_readback_override = b"unexpected postcommit pointer bytes"

    result = _publish(artifact, fake)

    assert result.status == "BLOCKED"
    assert result.rejection_reasons == ("READY_POINTER_EXACT_READBACK_MISMATCH",)
    assert result.head_cas_status == "COMMIT_OUTCOME_UNKNOWN"
    assert result.latest_pointer_mutation_status == "UNKNOWN"
    assert result.latest_pointer_mutated_by_publication is None
    assert fake.values[state.PAPER_POSITION_STATE_HEAD_KEY] == artifact.target_head_token_bytes


def test_availability_response_loss_is_distinct_from_pointer_commit_outcome() -> None:
    artifact = _artifact([_row()])
    fake = FakeAtomicRedis()
    fake.install_inputs(artifact)
    fake.raise_available_once = True

    result = _publish(artifact, fake)

    assert result.status == "BLOCKED"
    assert result.rejection_reasons == ("AVAILABLE_AT_SCRIPT_EXECUTION_FAILED",)
    assert result.head_cas_status == "COMMITTED_TO_TARGET"
    assert result.latest_pointer_mutation_status == "MUTATED_TO_TARGET"
    assert result.latest_pointer_mutated_by_publication is True
    assert result.availability_receipt_status == "OUTCOME_UNKNOWN"
    assert artifact.availability_receipt_key not in fake.values


def test_redis_pointer_clock_before_generated_state_fails_closed() -> None:
    artifact = _artifact([_row()])
    fake = FakeAtomicRedis()
    fake.install_inputs(artifact)
    fake.pointer_time = datetime(2026, 7, 19, 12, 0, 0, 50_000, tzinfo=UTC)

    result = _publish(artifact, fake)

    assert result.status == "BLOCKED"
    assert result.rejection_reasons == ("STATE_GENERATED_AT_AFTER_POINTER_READBACK",)
    assert result.head_cas_status == "COMMITTED_TO_TARGET"
    assert result.latest_pointer_mutation_status == "MUTATED_TO_TARGET"
    assert result.latest_pointer_mutated_by_publication is True
    assert fake.values[state.PAPER_POSITION_STATE_HEAD_KEY] == artifact.target_head_token_bytes


def test_publication_attempt_clock_after_pointer_reports_committed_target_truthfully() -> None:
    artifact = _artifact([_row()])
    fake = FakeAtomicRedis()
    fake.install_inputs(artifact)
    fake.pointer_time = datetime(2026, 7, 19, 12, 0, 0, 300_000, tzinfo=UTC)

    result = _publish(artifact, fake)

    assert result.status == "BLOCKED"
    assert result.rejection_reasons == ("PUBLICATION_ATTEMPTED_AT_AFTER_POINTER_READBACK",)
    assert result.head_cas_status == "COMMITTED_TO_TARGET"
    assert result.latest_pointer_mutated_by_publication is True
    assert result.availability_receipt_status == "NOT_ATTEMPTED"
    assert fake.values[state.PAPER_POSITION_STATE_HEAD_KEY] == artifact.target_head_token_bytes


def test_availability_clock_order_failure_reports_present_unverified_receipt() -> None:
    artifact = _artifact([_row()])
    fake = FakeAtomicRedis()
    fake.install_inputs(artifact)
    fake.available_time = datetime(2026, 7, 19, 12, 0, 0, 900_000, tzinfo=UTC)

    result = _publish(artifact, fake)

    assert result.status == "BLOCKED"
    assert result.rejection_reasons == ("AVAILABLE_AT_CLOCK_ORDER_INVALID",)
    assert result.head_cas_status == "COMMITTED_TO_TARGET"
    assert result.latest_pointer_mutated_by_publication is True
    assert result.availability_receipt_status == "PRESENT_UNVERIFIED"
    assert artifact.availability_receipt_key in fake.values
    assert result.state_available_at is None
    assert result.availability_receipt_observed_at is None


def test_generation_collision_is_blocked_without_durable_immutability_claim() -> None:
    artifact = _artifact([_row()])
    fake = FakeAtomicRedis()
    fake.install_inputs(artifact)
    fake.values[artifact.generation_key] = b"different expiring redis bytes"
    fake.ttls[artifact.generation_key] = TTL_SECONDS * 1_000

    result = _publish(artifact, fake)

    assert result.status == "BLOCKED"
    assert result.rejection_reasons == ("GENERATION_SET_NX_COLLISION",)
    assert result.head_cas_status == "NOT_ATTEMPTED"
    assert result.latest_pointer_mutation_status == "NOT_MUTATED"
    assert result.latest_pointer_mutated_by_publication is False
    assert result.redis_generation_set_nx_exact_readback_verified is False
    assert result.durable_generation_immutability_verified is False


def test_safety_material_is_fresh_and_cannot_be_upgraded_by_shared_mutation() -> None:
    first = _artifact([_row()])
    first_envelope = json.loads(first.generation_payload_bytes)
    first_envelope["state_material"]["safety"]["trainer_consumable"] = True
    first_pointer = json.loads(state._ready_pointer_bytes(first))  # noqa: SLF001
    first_pointer["safety"]["trainer_consumable"] = True

    second = _artifact([_row()])
    second_envelope = json.loads(second.generation_payload_bytes)
    second_pointer = json.loads(state._ready_pointer_bytes(second))  # noqa: SLF001

    assert second_envelope["state_material"]["safety"]["trainer_consumable"] is False
    assert second_pointer["safety"]["trainer_consumable"] is False
    assert not hasattr(state, "_SAFETY_FLAGS")


def test_artifact_tamper_and_result_replace_forgery_are_rejected() -> None:
    artifact = _artifact([_row()])
    fake = FakeAtomicRedis()
    tampered = replace(artifact, target_head_token_bytes=b"forged")
    with pytest.raises(
        state.PaperPositionStateValidationError,
        match="GENERATION_ARTIFACT_RECOMPUTATION_MISMATCH",
    ):
        _install_and_publish(tampered, fake)

    ready = _install_and_publish(artifact, FakeAtomicRedis())
    for changes in (
        {"status": "BLOCKED"},
        {"trainer_consumable": True},
        {"pointer_payload_bytes": b"{}"},
        {"durable_generation_immutability_verified": True},
    ):
        with pytest.raises(
            state.PaperPositionStatePublicationError,
            match="PUBLICATION_RESULT_FACTORY_REQUIRED",
        ):
            replace(ready, **changes)


def test_decoded_redis_executor_is_rejected_before_any_script_can_run() -> None:
    artifact = _artifact([_row()])
    fake = FakeAtomicRedis()
    fake.redis_response_mode = "REDIS_EVAL_DECODED_TEXT_DECODE_RESPONSES_TRUE_V1"
    fake.install_inputs(artifact)

    with pytest.raises(
        state.PaperPositionStateValidationError,
        match="RAW_REDIS_SCRIPT_EXECUTOR_REQUIRED",
    ):
        _publish(artifact, fake)

    assert fake.calls == []
    assert artifact.generation_key not in fake.values
    assert state.PAPER_POSITION_STATE_HEAD_KEY not in fake.values


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("tuple_response", "GENERATION_SCRIPT_RESPONSE_INVALID"),
        ("string_readback", "GENERATION_READBACK_TYPE_INVALID"),
        ("bool_created", "GENERATION_CREATED_FLAG_INVALID"),
        ("oversized_readback", "GENERATION_READBACK_TYPE_INVALID"),
    ],
)
def test_exact_builtin_redis_response_types_and_bounds_are_enforced(
    mutation: str, reason: str
) -> None:
    artifact = _artifact([_row()])
    fake = FakeAtomicRedis()
    fake.install_inputs(artifact)
    if mutation == "tuple_response":
        fake.generation_response_as_tuple = True
    elif mutation == "string_readback":
        fake.generation_readback_override = artifact.generation_payload_bytes.decode()
    elif mutation == "bool_created":
        original = fake.__call__

        def bool_created(
            script: str,
            keys: tuple[str, ...],
            args: tuple[state.ScriptArgument, ...],
        ) -> object:
            result = original(script, keys, args)
            if script == state.GENERATION_PUBLISH_LUA and type(result) is list:
                result[0] = True
            return result

        bool_created.redis_response_mode = state.RAW_REDIS_SCRIPT_RESPONSE_MODE  # type: ignore[attr-defined]
        fake_call = cast(state.AtomicScriptExecutor, bool_created)
        result = state.publish_paper_position_state_generation(
            artifact,
            execute_script=fake_call,
            ttl_seconds=TTL_SECONDS,
            publication_attempted_at=ATTEMPTED_AT,
        )
        assert result.rejection_reasons == (reason,)
        return
    else:
        fake.generation_readback_override = b"x" * (state.MAX_GENERATION_PAYLOAD_BYTES + 1)

    result = _publish(artifact, fake)

    assert result.status == "BLOCKED"
    assert result.rejection_reasons == (reason,)


def test_blocked_attempt_readback_or_head_claim_failure_does_not_claim_evidence() -> None:
    artifact = _artifact([_row()])
    fake = FakeAtomicRedis()
    fake.install_inputs(artifact)
    fake.values[artifact.generation_key] = b"collision"
    fake.ttls[artifact.generation_key] = TTL_SECONDS * 1_000
    fake.blocked_head_after_override = b"forged different head"

    result = _publish(artifact, fake)

    assert result.status == "BLOCKED"
    assert result.attempt_evidence_written is False
    assert result.attempt_evidence_payload_bytes is None
    assert result.rejection_reasons == (
        "BLOCKED_ATTEMPT_EVIDENCE_WRITE_FAILED",
        "GENERATION_SET_NX_COLLISION",
    )


def test_script_surface_is_bounded_and_uses_only_expected_keys() -> None:
    artifact = _artifact([_row()])
    fake = FakeAtomicRedis()
    result = _install_and_publish(artifact, fake)

    assert result.status == "READY"
    assert [call[0] for call in fake.calls] == [
        state.GENERATION_PUBLISH_LUA,
        state.READY_POINTER_PUBLISH_LUA,
        state.AVAILABLE_AT_OBSERVE_LUA,
    ]
    assert fake.calls[1][1] == (
        artifact.generation_key,
        state.PAPER_POSITIONS_LEGACY_KEY,
        state.PAPER_OPEN_POSITIONS_LEGACY_KEY,
        state.PAPER_SESSION_REDIS_KEY,
        state.PAPER_POSITION_STATE_HEAD_KEY,
        state.PAPER_POSITION_STATE_POINTER_KEY,
    )
    assert len(fake.calls[1][2]) == 7
    assert len(fake.calls[2][1]) == 7
    assert len(fake.calls[2][2]) == 5
