from __future__ import annotations

import hashlib
import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from v2.backend.app.cli.v2_adaptive_policy_shadow_runtime import (
    CALIBRATION_KEY,
    INTENTS_KEY,
    LATEST_KEY,
    PAPER_STATUS_KEY,
    REGISTRY_KEY,
    STATUS_KEY,
    AdaptivePolicyShadowArchiveV2,
    AdaptivePolicyShadowRuntimeError,
    _canonical_json,
    _is_pending_feature_snapshot,
    process_once,
)
from v2.backend.app.services.adaptive_system import adaptive_hard_validator_v2
from v2.backend.app.services.adaptive_system import adaptive_objective_v2
from v2.backend.tests.unit.services.adaptive_system.test_adaptive_policy_shadow_v2 import (
    _calibration,
    _feature_snapshot,
    _intent,
    _registry,
)

_PRIVATE = Ed25519PrivateKey.from_private_bytes(
    hashlib.sha256(b"adaptive-shadow-runtime-cli-test-validator").digest()
)
_SEED = _PRIVATE.private_bytes(
    serialization.Encoding.Raw,
    serialization.PrivateFormat.Raw,
    serialization.NoEncryption(),
)
_PUBLIC_HEX = _PRIVATE.public_key().public_bytes(
    serialization.Encoding.Raw,
    serialization.PublicFormat.Raw,
).hex()


class _Pipeline:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values
        self.pending: list[tuple[str, str]] = []

    def set(self, key: str, value: str) -> _Pipeline:
        self.pending.append((key, value))
        return self

    def execute(self) -> list[bool]:
        for key, value in self.pending:
            self.values[key] = value
        return [True] * len(self.pending)


class _Redis:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = {
            key: value if isinstance(value, str) else json.dumps(value)
            for key, value in values.items()
        }

    def mget(self, keys: tuple[str, ...]) -> list[str | None]:
        return [self.values.get(key) for key in keys]

    def pipeline(self, *, transaction: bool) -> _Pipeline:
        assert transaction is True
        return _Pipeline(self.values)


@pytest.fixture(autouse=True)
def _validator_anchor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        adaptive_objective_v2,
        "CANONICAL_HARD_VALIDATOR_PUBLIC_KEY_HEX",
        _PUBLIC_HEX,
    )
    monkeypatch.setattr(
        adaptive_hard_validator_v2,
        "CANONICAL_HARD_VALIDATOR_PUBLIC_KEY_HEX",
        _PUBLIC_HEX,
    )


def _client() -> _Redis:
    return _Redis(
        {
            INTENTS_KEY: [_intent()],
            PAPER_STATUS_KEY: {
                "paper_only": True,
                "open_position_count": 0,
                "generated_utc": "1970-01-01T00:58:20.000Z",
            },
            CALIBRATION_KEY: _calibration(),
            REGISTRY_KEY: _registry(),
        }
    )


def test_process_once_persists_every_candidate_with_zero_reference_disagreements(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    archive = AdaptivePolicyShadowArchiveV2(
        (state_root / "shadow_decisions_v2.sqlite3").resolve()
    )
    client = _client()

    status = process_once(
        client=client,
        archive=archive,
        state_root=state_root,
        feature_archive_root=(tmp_path / "features").resolve(),
        validator_seed=_SEED,
        generated_at_ms=4_000_000,
        snapshot_loader=lambda _snapshot_id, _root: _feature_snapshot(),
    )

    assert status["status"] == "PASS_SHADOW"
    assert status["source_candidate_count"] == 1
    assert len(status["source_candidate_ids_sha256"]) == 64
    assert len(status["source_intents_sha256"]) == 64
    assert len(status["persisted_record_keys_sha256"]) == 64
    assert status["production_decisions_persisted"] == 1
    assert status["adaptive_shadow_decisions_persisted"] == 1
    assert status["candidate_coverage"] == 1.0
    assert status["unexplained_candidate_drop_count"] == 0
    assert status["production_reference_disagreement_count"] == 0
    assert status["archive"]["verified"] is True
    assert status["archive"]["inserted"] == 1
    assert status["adaptive_policy_authoritative"] is False
    assert status["exchange_action_taken"] is False
    latest = json.loads(client.values[LATEST_KEY])
    assert latest["candidate_count"] == 1
    assert len(latest["actions"]) == 1
    assert latest["actions"][0]["execution_authority"] is False
    assert json.loads(client.values[STATUS_KEY]) == status

    duplicate = process_once(
        client=client,
        archive=archive,
        state_root=state_root,
        feature_archive_root=(tmp_path / "features").resolve(),
        validator_seed=_SEED,
        generated_at_ms=4_100_000,
        snapshot_loader=lambda _snapshot_id, _root: _feature_snapshot(),
    )
    assert duplicate["archive"]["inserted"] == 1
    assert duplicate["archive"]["duplicates"] == 0
    assert duplicate["archive"]["row_count"] == 2

    exact_replay = process_once(
        client=client,
        archive=archive,
        state_root=state_root,
        feature_archive_root=(tmp_path / "features").resolve(),
        validator_seed=_SEED,
        generated_at_ms=4_100_000,
        snapshot_loader=lambda _snapshot_id, _root: _feature_snapshot(),
    )
    assert exact_replay["archive"]["inserted"] == 0
    assert exact_replay["archive"]["duplicates"] == 1
    assert exact_replay["archive"]["row_count"] == 2


def test_process_once_persists_exact_fail_closed_disposition_during_exposure(
    tmp_path: Path,
) -> None:
    client = _client()
    intents = json.loads(client.values[INTENTS_KEY])
    intents[0]["paper_cycle_reservation_snapshot"] = {}
    intents[0]["paper_cycle_reservation_snapshot_hash"] = None
    client.values[INTENTS_KEY] = json.dumps(intents)
    paper_status = json.loads(client.values[PAPER_STATUS_KEY])
    paper_status["open_position_count"] = 1
    client.values[PAPER_STATUS_KEY] = json.dumps(paper_status)
    state_root = tmp_path / "state"
    archive = AdaptivePolicyShadowArchiveV2(
        (state_root / "shadow_decisions_v2.sqlite3").resolve()
    )

    status = process_once(
        client=client,
        archive=archive,
        state_root=state_root,
        feature_archive_root=(tmp_path / "features").resolve(),
        validator_seed=_SEED,
        generated_at_ms=4_000_000,
        snapshot_loader=lambda _snapshot_id, _root: _feature_snapshot(),
    )

    assert status["status"] == "PASS_SHADOW"
    assert status["source_candidate_count"] == 1
    assert status["production_decisions_persisted"] == 1
    assert status["adaptive_shadow_decisions_persisted"] == 1
    assert status["candidate_coverage"] == 1.0
    assert status["unexplained_candidate_drop_count"] == 0
    assert status["directional_action_disposition_count"] == 4
    assert status["hard_blocked_directional_action_count"] == 4
    assert status["physical_plan_unavailable_count"] == 4
    assert status["production_reference_disagreement_count"] == 0
    latest = json.loads(client.values[LATEST_KEY])
    assert latest["actions"][0]["selected_action"] == "remain_flat"
    assert latest["actions"][0]["target_notional_usd"] == 0.0
    with sqlite3.connect(archive.path) as connection:
        record = json.loads(
            connection.execute(
                "SELECT record_json FROM shadow_records WHERE row_index=1"
            ).fetchone()[0]
        )
    assert len(record["action_dispositions"]) == 5
    blockers = {
        reason
        for disposition in record["action_dispositions"]
        for reason in disposition["blocking_reasons"]
    }
    assert blockers == {
        "PHYSICAL_PLAN_UNAVAILABLE:reservation.derived:object_required"
    }
    assert record["production_reference_parity"] == {
        "status": "PASS",
        "disagreement_count": 0,
    }
    assert record["exchange_action_taken"] is False


def test_process_once_persists_typed_flat_when_every_action_is_hard_blocked(
    tmp_path: Path,
) -> None:
    client = _client()
    intents = json.loads(client.values[INTENTS_KEY])
    intents[0]["feed_integrity_pass"] = False
    client.values[INTENTS_KEY] = json.dumps(intents)
    state_root = tmp_path / "state"
    archive = AdaptivePolicyShadowArchiveV2(
        (state_root / "shadow_decisions_v2.sqlite3").resolve()
    )

    status = process_once(
        client=client,
        archive=archive,
        state_root=state_root,
        feature_archive_root=(tmp_path / "features").resolve(),
        validator_seed=_SEED,
        generated_at_ms=4_000_000,
        snapshot_loader=lambda _snapshot_id, _root: _feature_snapshot(),
    )

    assert status["candidate_coverage"] == 1.0
    assert status["hard_blocked_typed_flat_count"] == 1
    assert status["selected_directional_action_count"] == 0
    assert status["production_reference_disagreement_count"] == 0
    latest = json.loads(client.values[LATEST_KEY])
    assert latest["actions"][0]["selected_action"] == "remain_flat"
    assert latest["actions"][0]["target_notional_usd"] == 0.0
    assert latest["actions"][0]["execution_authority"] is False
    with sqlite3.connect(archive.path) as connection:
        record = json.loads(
            connection.execute(
                "SELECT record_json FROM shadow_records WHERE row_index=1"
            ).fetchone()[0]
        )
    assert all(
        disposition["blocking_reasons"]
        for disposition in record["action_dispositions"]
    )
    assert "HARD_CONSTRAINT_BLOCKED_NONEXECUTING" in record[
        "selected_adaptive_action"
    ]["decision_rationale_codes"]
    assert record["selected_objective_input"]["hard_constraints_satisfied"] is False
    assert record["routes_to_live"] is False
    assert record["places_real_order"] is False
    assert record["exchange_action_taken"] is False


def test_archive_tampering_is_detected(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    archive = AdaptivePolicyShadowArchiveV2(
        (state_root / "shadow_decisions_v2.sqlite3").resolve()
    )
    process_once(
        client=_client(),
        archive=archive,
        state_root=state_root,
        feature_archive_root=(tmp_path / "features").resolve(),
        validator_seed=_SEED,
        generated_at_ms=4_000_000,
        snapshot_loader=lambda _snapshot_id, _root: _feature_snapshot(),
    )
    with sqlite3.connect(archive.path) as connection:
        connection.execute(
            "UPDATE shadow_records SET record_json='{}' WHERE row_index=1"
        )

    with pytest.raises(AdaptivePolicyShadowRuntimeError, match="mismatch"):
        archive.verify()


def test_missing_source_projection_fails_closed(tmp_path: Path) -> None:
    client = _client()
    del client.values[CALIBRATION_KEY]
    archive = AdaptivePolicyShadowArchiveV2(
        (tmp_path / "state" / "shadow_decisions_v2.sqlite3").resolve()
    )

    with pytest.raises(AdaptivePolicyShadowRuntimeError, match="missing"):
        process_once(
            client=client,
            archive=archive,
            state_root=tmp_path / "state",
            feature_archive_root=(tmp_path / "features").resolve(),
            validator_seed=_SEED,
            generated_at_ms=4_000_000,
            snapshot_loader=lambda _snapshot_id, _root: _feature_snapshot(),
        )


def test_pending_feature_snapshot_classifier_matches_process_once_race(
    tmp_path: Path,
) -> None:
    """The persistent ``--loop`` must retry (not fail-closed) exactly the race
    where ``process_once`` cannot yet find a durable feature snapshot for an
    already-published intent — the feature-snapshot archiver and the intent
    publisher are independent producers, and the archiver reliably catches up
    within the next tick or two."""
    archive = AdaptivePolicyShadowArchiveV2(
        (tmp_path / "state" / "shadow_decisions_v2.sqlite3").resolve()
    )
    with pytest.raises(AdaptivePolicyShadowRuntimeError, match="missing_or_unverified") as excinfo:
        process_once(
            client=_client(),
            archive=archive,
            state_root=tmp_path / "state",
            feature_archive_root=(tmp_path / "features").resolve(),
            validator_seed=_SEED,
            generated_at_ms=4_000_000,
            snapshot_loader=lambda _snapshot_id, _root: None,
        )
    assert _is_pending_feature_snapshot(excinfo.value)


def test_pending_feature_snapshot_classifier_rejects_unrelated_failures(
    tmp_path: Path,
) -> None:
    """Any other fail-closed condition (missing source projection here) must
    stay fail-closed — the retry carve-out is scoped to the one transient
    archive-ordering race, never to a real evidence-integrity gap."""
    client = _client()
    del client.values[CALIBRATION_KEY]
    archive = AdaptivePolicyShadowArchiveV2(
        (tmp_path / "state" / "shadow_decisions_v2.sqlite3").resolve()
    )
    with pytest.raises(AdaptivePolicyShadowRuntimeError, match="missing") as excinfo:
        process_once(
            client=client,
            archive=archive,
            state_root=tmp_path / "state",
            feature_archive_root=(tmp_path / "features").resolve(),
            validator_seed=_SEED,
            generated_at_ms=4_000_000,
            snapshot_loader=lambda _snapshot_id, _root: _feature_snapshot(),
        )
    assert not _is_pending_feature_snapshot(excinfo.value)
    assert not _is_pending_feature_snapshot(
        RuntimeError("feature_snapshot:x:missing_or_unverified")
    )


def test_exact_decimal_venue_values_are_losslessly_serialized() -> None:
    assert _canonical_json({"price": Decimal("0.00008110")}) == (
        '{"price":"0.00008110"}'
    )
    with pytest.raises(TypeError, match="nonfinite"):
        _canonical_json({"price": Decimal("NaN")})


def test_future_source_cycle_timestamp_fails_closed(tmp_path: Path) -> None:
    client = _client()
    status = json.loads(client.values[PAPER_STATUS_KEY])
    status["generated_utc"] = "1970-01-01T01:23:20.000Z"
    client.values[PAPER_STATUS_KEY] = json.dumps(status)
    archive = AdaptivePolicyShadowArchiveV2(
        (tmp_path / "state" / "shadow_decisions_v2.sqlite3").resolve()
    )

    with pytest.raises(AdaptivePolicyShadowRuntimeError, match="future_time_forbidden"):
        process_once(
            client=client,
            archive=archive,
            state_root=tmp_path / "state",
            feature_archive_root=(tmp_path / "features").resolve(),
            validator_seed=_SEED,
            generated_at_ms=4_000_000,
            snapshot_loader=lambda _snapshot_id, _root: _feature_snapshot(),
        )
