from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import traceback
from collections.abc import ItemsView, Iterator, Mapping
from dataclasses import FrozenInstanceError, asdict
from pathlib import Path

import pytest

from v2.backend.app.services.native_trainer.sampling_plan_keyring import (
    MAX_SAMPLING_PLAN_KEY_RING_BYTES,
    SAMPLING_PLAN_KEY_RING_SCHEMA_VERSION,
    SamplingPlanKeyResolutionError,
    SamplingPlanKeyRing,
    SamplingPlanKeyRingIntegrityError,
    SamplingPlanKeyRingValidationError,
    load_sampling_plan_key_ring,
)

OLD_KEY = b"old-key-material-is-private-32bytes!"
NEW_KEY = b"new-key-material-is-private-32bytes!"
HOSTILE_MARKER = "hostile-mapping-sensitive-material-must-never-escape"


class _AdversarialKeyMapping(Mapping[str, bytes]):
    def __init__(
        self,
        items: list[tuple[str, bytes]],
        *,
        reported_length: int = 1,
        len_error: bool = False,
        items_error: bool = False,
        iteration_error: bool = False,
    ) -> None:
        self._items = tuple(items)
        self._values = dict(items)
        self._reported_length = reported_length
        self._len_error = len_error
        self._items_error = items_error
        self._iteration_error = iteration_error
        self.len_calls = 0
        self.items_calls = 0

    def __getitem__(self, key: str) -> bytes:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        if self._iteration_error:
            raise RuntimeError(HOSTILE_MARKER)
        return iter(key_id for key_id, _key_bytes in self._items)

    def __len__(self) -> int:
        self.len_calls += 1
        if self._len_error:
            raise RuntimeError(HOSTILE_MARKER)
        return self._reported_length

    def items(self) -> ItemsView[str, bytes]:
        self.items_calls += 1
        if self._items_error:
            raise RuntimeError(HOSTILE_MARKER)
        return super().items()


def _record(secret: bytes, *, encoding: str = "base64") -> dict[str, str]:
    if encoding == "base64":
        value = base64.b64encode(secret).decode("ascii")
    elif encoding == "hex":
        value = secret.hex()
    else:
        value = "unsupported"
    return {"encoding": encoding, "value": value}


def _payload(
    *,
    active_key_id: str = "sampling-plan-2026-07",
    keys: dict[str, object] | None = None,
    schema_version: str = SAMPLING_PLAN_KEY_RING_SCHEMA_VERSION,
) -> dict[str, object]:
    return {
        "active_key_id": active_key_id,
        "keys": keys if keys is not None else {"sampling-plan-2026-07": _record(NEW_KEY)},
        "schema_version": schema_version,
    }


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _write_private(path: Path, payload: bytes | dict[str, object]) -> Path:
    path.parent.chmod(0o700)
    raw = payload if isinstance(payload, bytes) else _canonical_bytes(payload)
    path.write_bytes(raw)
    path.chmod(0o600)
    return path


def test_loads_explicit_base64_and_hex_keys_as_immutable_bytes(
    tmp_path: Path,
) -> None:
    path = _write_private(
        tmp_path / "sampling-plan-key-ring.json",
        _payload(
            active_key_id="new/key@2026-07",
            keys={
                "old:key.2026-06": _record(OLD_KEY, encoding="hex"),
                "new/key@2026-07": _record(NEW_KEY),
            },
        ),
    )

    ring = load_sampling_plan_key_ring(path)

    assert ring.active_key_id == "new/key@2026-07"
    assert ring.active_key == NEW_KEY
    assert type(ring.active_key) is bytes
    assert ring.resolve("old:key.2026-06") == OLD_KEY
    assert ring("new/key@2026-07") == NEW_KEY
    assert callable(ring.resolver)
    with pytest.raises(TypeError):
        ring.active_key[0] = 0  # type: ignore[index]
    with pytest.raises(AttributeError, match="sampling_plan_key_ring_is_immutable"):
        ring.active_key_id = "other"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        ring.status.active_key_id = "other"  # type: ignore[misc]


def test_in_memory_type_cannot_bypass_key_contract_or_mutability() -> None:
    with pytest.raises(
        SamplingPlanKeyRingValidationError,
        match="sampling_plan_hmac_key_invalid",
    ):
        SamplingPlanKeyRing(
            active_key_id="active",
            keys={"active": bytearray(b"x" * 32)},
        )
    with pytest.raises(
        SamplingPlanKeyRingValidationError,
        match="sampling_plan_active_key_missing",
    ):
        SamplingPlanKeyRing(
            active_key_id="missing",
            keys={"retained": b"x" * 32},
        )


def test_constructor_snapshots_items_once_without_calling_hostile_len() -> None:
    keys = _AdversarialKeyMapping(
        [("active", b"x" * 32)],
        reported_length=10_000,
        len_error=True,
    )

    ring = SamplingPlanKeyRing(active_key_id="active", keys=keys)

    assert ring.active_key == b"x" * 32
    assert keys.items_calls == 1
    assert keys.len_calls == 0
    assert HOSTILE_MARKER not in repr(ring)
    assert HOSTILE_MARKER not in repr(ring.status)


def test_constructor_uses_snapshot_cardinality_not_hostile_len() -> None:
    keys = _AdversarialKeyMapping(
        [(f"retained-{index}", b"x" * 32) for index in range(129)],
        reported_length=1,
    )

    with pytest.raises(
        SamplingPlanKeyRingValidationError,
        match="sampling_plan_retained_keys_exceeded",
    ):
        SamplingPlanKeyRing(active_key_id="retained-0", keys=keys)

    assert keys.items_calls == 1
    assert keys.len_calls == 0


def test_constructor_rejects_duplicate_ids_before_dict_materialization() -> None:
    keys = _AdversarialKeyMapping(
        [("active", b"x" * 32), ("active", b"y" * 32)],
        reported_length=1,
    )

    with pytest.raises(
        SamplingPlanKeyRingValidationError,
        match="sampling_plan_auth_key_id_duplicate",
    ):
        SamplingPlanKeyRing(active_key_id="active", keys=keys)

    assert keys.items_calls == 1
    assert keys.len_calls == 0


@pytest.mark.parametrize("failure", ["items", "iteration"])
def test_hostile_mapping_exceptions_are_fixed_and_secret_free(
    failure: str,
) -> None:
    keys = _AdversarialKeyMapping(
        [("active", b"x" * 32)],
        items_error=failure == "items",
        iteration_error=failure == "iteration",
    )

    with pytest.raises(SamplingPlanKeyRingValidationError) as captured:
        SamplingPlanKeyRing(active_key_id="active", keys=keys)

    rendered = "".join(
        traceback.format_exception(
            type(captured.value),
            captured.value,
            captured.value.__traceback__,
        )
    )
    assert str(captured.value) == "sampling_plan_retained_keys_invalid"
    assert HOSTILE_MARKER not in rendered
    assert HOSTILE_MARKER not in repr(captured.value)
    assert keys.items_calls == 1
    assert keys.len_calls == 0


@pytest.mark.parametrize("mode", [0o604, 0o610, 0o601, 0o677])
def test_rejects_every_group_or_other_file_permission_bit(
    tmp_path: Path,
    mode: int,
) -> None:
    path = _write_private(tmp_path / f"key-ring-{mode:o}.json", _payload())
    path.chmod(mode)

    with pytest.raises(
        SamplingPlanKeyRingIntegrityError,
        match="sampling_plan_key_ring_private_mode_required",
    ):
        load_sampling_plan_key_ring(path)


@pytest.mark.parametrize("mode", [0o720, 0o707])
def test_rejects_group_or_other_writable_immediate_parent(
    tmp_path: Path,
    mode: int,
) -> None:
    path = _write_private(tmp_path / "key-ring.json", _payload())
    tmp_path.chmod(mode)
    try:
        with pytest.raises(
            SamplingPlanKeyRingIntegrityError,
            match="sampling_plan_key_ring_parent_writable_by_others",
        ):
            load_sampling_plan_key_ring(path)
    finally:
        tmp_path.chmod(0o700)


def test_rejects_symlink_and_hardlink_key_ring_paths(tmp_path: Path) -> None:
    target = _write_private(tmp_path / "target.json", _payload())
    symlink = tmp_path / "symlink.json"
    symlink.symlink_to(target)

    with pytest.raises(SamplingPlanKeyRingIntegrityError):
        load_sampling_plan_key_ring(symlink)

    hardlink = tmp_path / "hardlink.json"
    os.link(target, hardlink)
    with pytest.raises(
        SamplingPlanKeyRingIntegrityError,
        match="sampling_plan_key_ring_hardlink_forbidden",
    ):
        load_sampling_plan_key_ring(target)


def test_rejects_symlink_in_parent_chain(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir(mode=0o700)
    path = _write_private(real_parent / "key-ring.json", _payload())
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(SamplingPlanKeyRingIntegrityError):
        load_sampling_plan_key_ring(linked_parent / path.name)


def test_rejects_non_regular_file(tmp_path: Path) -> None:
    directory = tmp_path / "key-ring.json"
    directory.mkdir(mode=0o700)

    with pytest.raises(
        SamplingPlanKeyRingIntegrityError,
        match="sampling_plan_key_ring_not_regular_file",
    ):
        load_sampling_plan_key_ring(directory)


def test_requires_explicit_absolute_path(tmp_path: Path) -> None:
    path = _write_private(tmp_path / "key-ring.json", _payload())

    with pytest.raises(
        SamplingPlanKeyRingValidationError,
        match="sampling_plan_key_ring_explicit_path_required",
    ):
        load_sampling_plan_key_ring(str(path))  # type: ignore[arg-type]
    with pytest.raises(
        SamplingPlanKeyRingValidationError,
        match="sampling_plan_key_ring_absolute_path_required",
    ):
        load_sampling_plan_key_ring(Path("relative-key-ring.json"))


def test_missing_secure_path_capability_fails_with_fixed_redacted_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_private(tmp_path / "key-ring.json", _payload())
    with monkeypatch.context() as scoped:
        scoped.setattr(
            "v2.backend.app.services.native_trainer.sampling_plan_keyring.os.supports_dir_fd",
            frozenset(),
        )
        with pytest.raises(SamplingPlanKeyRingIntegrityError) as captured:
            load_sampling_plan_key_ring(path)

    assert str(captured.value) == ("sampling_plan_key_ring_platform_capability_unsupported")


def test_runtime_not_implemented_path_operation_is_fixed_and_secret_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_private(tmp_path / "key-ring.json", _payload())

    def _unsupported_open(*_args: object, **_kwargs: object) -> int:
        raise NotImplementedError(HOSTILE_MARKER)

    with monkeypatch.context() as scoped:
        scoped.setattr(
            "v2.backend.app.services.native_trainer.sampling_plan_keyring._require_secure_path_capabilities",
            lambda: None,
        )
        scoped.setattr(
            "v2.backend.app.services.native_trainer.sampling_plan_keyring.os.open",
            _unsupported_open,
        )
        with pytest.raises(SamplingPlanKeyRingIntegrityError) as captured:
            load_sampling_plan_key_ring(path)

    rendered = "".join(
        traceback.format_exception(
            type(captured.value),
            captured.value,
            captured.value.__traceback__,
        )
    )
    assert str(captured.value) == ("sampling_plan_key_ring_platform_capability_unsupported")
    assert HOSTILE_MARKER not in rendered
    assert HOSTILE_MARKER not in repr(captured.value)


def test_rejects_parent_owned_by_another_effective_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_private(tmp_path / "key-ring.json", _payload())
    actual_euid = os.geteuid()
    monkeypatch.setattr(
        "v2.backend.app.services.native_trainer.sampling_plan_keyring.os.geteuid",
        lambda: actual_euid + 1,
    )

    with pytest.raises(
        SamplingPlanKeyRingIntegrityError,
        match="sampling_plan_key_ring_parent_owner_mismatch",
    ):
        load_sampling_plan_key_ring(path)


def test_rejects_file_owned_by_another_effective_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_private(tmp_path / "key-ring.json", _payload())
    actual_euid = os.geteuid()
    monkeypatch.setattr(
        "v2.backend.app.services.native_trainer.sampling_plan_keyring.os.geteuid",
        lambda: actual_euid + 1,
    )
    # Isolate the file-owner branch after the separate parent-owner test above.
    monkeypatch.setattr(
        "v2.backend.app.services.native_trainer.sampling_plan_keyring._validate_trusted_parent",
        lambda _parent_fd, *, expected_owner_uid: None,
    )

    with pytest.raises(
        SamplingPlanKeyRingIntegrityError,
        match="sampling_plan_key_ring_owner_mismatch",
    ):
        load_sampling_plan_key_ring(path)


def test_rejects_duplicate_keys_at_every_json_level(tmp_path: Path) -> None:
    encoded = base64.b64encode(NEW_KEY).decode("ascii")
    duplicate_top = (
        '{"active_key_id":"active","active_key_id":"active",'
        f'"keys":{{"active":{{"encoding":"base64","value":"{encoded}"}}}},'
        f'"schema_version":"{SAMPLING_PLAN_KEY_RING_SCHEMA_VERSION}"}}'
    ).encode("ascii")
    duplicate_nested = (
        '{"active_key_id":"active",'
        f'"keys":{{"active":{{"encoding":"base64","encoding":"base64",'
        f'"value":"{encoded}"}}}},'
        f'"schema_version":"{SAMPLING_PLAN_KEY_RING_SCHEMA_VERSION}"}}'
    ).encode("ascii")

    for index, raw in enumerate((duplicate_top, duplicate_nested)):
        path = _write_private(tmp_path / f"duplicate-{index}.json", raw)
        with pytest.raises(
            SamplingPlanKeyRingValidationError,
            match="sampling_plan_key_ring_duplicate_json_key",
        ):
            load_sampling_plan_key_ring(path)


@pytest.mark.parametrize(
    "raw",
    [
        b"not-json",
        b"\xff",
        b"{}\n",
        b'{"active_key_id":"active","keys":{},"schema_version":NaN}',
    ],
)
def test_rejects_malformed_non_utf8_nonfinite_or_noncanonical_payloads(
    tmp_path: Path,
    raw: bytes,
) -> None:
    path = _write_private(tmp_path / f"malformed-{hash(raw)}.json", raw)

    with pytest.raises(SamplingPlanKeyRingValidationError):
        load_sampling_plan_key_ring(path)


def test_rejects_oversized_file_before_json_parse(tmp_path: Path) -> None:
    path = _write_private(
        tmp_path / "oversized.json",
        b"x" * (MAX_SAMPLING_PLAN_KEY_RING_BYTES + 1),
    )

    with pytest.raises(
        SamplingPlanKeyRingIntegrityError,
        match="sampling_plan_key_ring_file_size_invalid",
    ):
        load_sampling_plan_key_ring(path)


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (
            _payload(schema_version="unknown"),
            "sampling_plan_key_ring_schema_invalid",
        ),
        (
            _payload(active_key_id="contains space"),
            "sampling_plan_active_key_id_invalid",
        ),
        (
            _payload(keys={"contains space": _record(NEW_KEY)}),
            "sampling_plan_auth_key_id_invalid",
        ),
        (
            _payload(keys={}),
            "sampling_plan_retained_keys_invalid",
        ),
        (
            _payload(keys={"sampling-plan-2026-07": _record(b"too-short")}),
            "sampling_plan_hmac_key_too_short",
        ),
        (
            _payload(
                keys={
                    "sampling-plan-2026-07": {
                        "encoding": "hex",
                        "value": NEW_KEY.hex().upper(),
                    }
                }
            ),
            "sampling_plan_key_encoding_invalid",
        ),
        (
            _payload(
                keys={
                    "sampling-plan-2026-07": {
                        "encoding": "base64",
                        "value": base64.b64encode(b"x" * 32).decode("ascii").rstrip("="),
                    }
                }
            ),
            "sampling_plan_key_encoding_invalid",
        ),
        (
            _payload(
                keys={
                    "sampling-plan-2026-07": {
                        "encoding": "raw",
                        "value": NEW_KEY.hex(),
                    }
                }
            ),
            "sampling_plan_key_encoding_invalid",
        ),
        (
            _payload(
                keys={
                    "sampling-plan-2026-07": {
                        "encoding": "hex",
                        "value": NEW_KEY.hex(),
                        "unexpected": True,
                    }
                }
            ),
            "sampling_plan_key_record_shape_invalid",
        ),
        (
            _payload(
                active_key_id="not-retained",
                keys={"sampling-plan-2026-07": _record(NEW_KEY)},
            ),
            "sampling_plan_active_key_missing",
        ),
    ],
)
def test_rejects_invalid_schema_ids_encodings_and_key_sets(
    tmp_path: Path,
    payload: dict[str, object],
    reason: str,
) -> None:
    path = _write_private(tmp_path / f"invalid-{reason}.json", payload)

    with pytest.raises(SamplingPlanKeyRingValidationError, match=reason):
        load_sampling_plan_key_ring(path)


def test_unknown_historical_key_fails_closed_without_echoing_id(
    tmp_path: Path,
) -> None:
    path = _write_private(tmp_path / "key-ring.json", _payload())
    ring = load_sampling_plan_key_ring(path)
    unknown = "retired-secret-id"

    with pytest.raises(SamplingPlanKeyResolutionError) as captured:
        ring.resolver(unknown)

    assert str(captured.value) == "sampling_plan_auth_key_id_unknown"
    assert unknown not in str(captured.value)


def test_rotation_keeps_old_key_available_for_historical_verification(
    tmp_path: Path,
) -> None:
    path = _write_private(
        tmp_path / "key-ring.json",
        _payload(
            active_key_id="old",
            keys={"old": _record(OLD_KEY)},
        ),
    )
    old_ring = load_sampling_plan_key_ring(path)
    signed_payload = b"archived-authenticated-sampling-plan"
    old_tag = hmac.new(
        old_ring.active_key,
        signed_payload,
        hashlib.sha256,
    ).digest()

    _write_private(
        path,
        _payload(
            active_key_id="new",
            keys={
                "new": _record(NEW_KEY),
                "old": _record(OLD_KEY),
            },
        ),
    )
    rotated_ring = load_sampling_plan_key_ring(path)

    assert rotated_ring.active_key_id == "new"
    assert hmac.compare_digest(
        hmac.new(
            rotated_ring.resolver("old"),
            signed_payload,
            hashlib.sha256,
        ).digest(),
        old_tag,
    )


def test_status_repr_errors_and_fingerprint_disclose_no_key_material(
    tmp_path: Path,
) -> None:
    path = _write_private(
        tmp_path / "key-ring.json",
        _payload(keys={"sampling-plan-2026-07": _record(NEW_KEY)}),
    )
    ring = load_sampling_plan_key_ring(path)
    secret_text = NEW_KEY.decode("ascii")
    encoded_forms = {
        secret_text,
        NEW_KEY.hex(),
        base64.b64encode(NEW_KEY).decode("ascii"),
    }
    exposed = repr(ring) + repr(ring.status) + repr(asdict(ring.status))

    with pytest.raises(SamplingPlanKeyResolutionError) as captured:
        ring.resolve("unknown")
    exposed += str(captured.value) + repr(captured.value)

    assert all(secret not in exposed for secret in encoded_forms)

    changed_secret_path = _write_private(
        tmp_path / "changed-secret-same-public-config.json",
        _payload(keys={"sampling-plan-2026-07": _record(b"z" * len(NEW_KEY))}),
    )
    changed_secret_ring = load_sampling_plan_key_ring(changed_secret_path)
    assert (
        changed_secret_ring.status.public_configuration_fingerprint
        == ring.status.public_configuration_fingerprint
    )


def test_json_parse_error_traceback_does_not_echo_secret_payload(
    tmp_path: Path,
) -> None:
    secret_text = NEW_KEY.decode("ascii")
    path = _write_private(
        tmp_path / "malformed-secret.json",
        ("{" + secret_text).encode("ascii"),
    )

    with pytest.raises(SamplingPlanKeyRingValidationError) as captured:
        load_sampling_plan_key_ring(path)

    rendered = "".join(
        traceback.format_exception(
            type(captured.value),
            captured.value,
            captured.value.__traceback__,
        )
    )
    assert secret_text not in rendered


def test_path_swap_during_descriptor_read_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_private(tmp_path / "key-ring.json", _payload())
    replacement = _write_private(
        tmp_path / "replacement.json",
        _payload(
            active_key_id="replacement",
            keys={"replacement": _record(OLD_KEY)},
        ),
    )
    real_read = os.read
    swapped = False

    def _swapping_read(descriptor: int, count: int) -> bytes:
        nonlocal swapped
        chunk = real_read(descriptor, count)
        if not swapped:
            swapped = True
            os.replace(replacement, path)
        return chunk

    monkeypatch.setattr(
        "v2.backend.app.services.native_trainer.sampling_plan_keyring.os.read",
        _swapping_read,
    )

    with pytest.raises(
        SamplingPlanKeyRingIntegrityError,
        match="sampling_plan_key_ring_file_binding_changed",
    ):
        load_sampling_plan_key_ring(path)


def test_file_mutation_during_descriptor_read_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_private(tmp_path / "key-ring.json", _payload())
    real_read = os.read
    mutated = False

    def _mutating_read(descriptor: int, count: int) -> bytes:
        nonlocal mutated
        chunk = real_read(descriptor, count)
        if not mutated:
            mutated = True
            with path.open("ab") as stream:
                stream.write(b" ")
        return chunk

    monkeypatch.setattr(
        "v2.backend.app.services.native_trainer.sampling_plan_keyring.os.read",
        _mutating_read,
    )

    with pytest.raises(
        SamplingPlanKeyRingIntegrityError,
        match="sampling_plan_key_ring_file_changed_during_read",
    ):
        load_sampling_plan_key_ring(path)


def test_status_fingerprint_changes_when_public_rotation_metadata_changes(
    tmp_path: Path,
) -> None:
    first = load_sampling_plan_key_ring(
        _write_private(
            tmp_path / "first.json",
            _payload(active_key_id="old", keys={"old": _record(OLD_KEY)}),
        )
    )
    rotated = load_sampling_plan_key_ring(
        _write_private(
            tmp_path / "rotated.json",
            _payload(
                active_key_id="new",
                keys={"new": _record(NEW_KEY), "old": _record(OLD_KEY)},
            ),
        )
    )

    assert first.status.retained_key_ids == ("old",)
    assert rotated.status.retained_key_ids == ("new", "old")
    assert (
        first.status.public_configuration_fingerprint
        != rotated.status.public_configuration_fingerprint
    )
