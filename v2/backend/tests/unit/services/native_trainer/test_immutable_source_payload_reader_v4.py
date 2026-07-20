from __future__ import annotations

import hashlib
import os
import socket
from dataclasses import replace
from pathlib import Path
from typing import NoReturn, cast

import pytest

from v2.backend.app.services.native_trainer.immutable_source_payload_reader_v4 import (
    ImmutableSourcePayloadReaderV4,
    ImmutableSourcePayloadReaderV4IntegrityError,
    ImmutableSourcePayloadReaderV4NotFoundError,
    ImmutableSourcePayloadReaderV4ValidationError,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
)


def _harness(
    tmp_path: Path,
    *,
    payload: bytes = b"\x00exact immutable source payload\xff\r\n",
) -> tuple[
    ImmutableSourcePayloadReaderV4,
    SourcePayloadAddress,
    Path,
    bytes,
]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    root = tmp_path / "source-payload-cas"
    store = ImmutableSourcePayloadStore(root)
    address = store.put(payload)
    return (
        ImmutableSourcePayloadReaderV4(str(root)),
        address,
        store.path_for(address.payload_sha256),
        payload,
    )


def _fd_count() -> int:
    return len(os.listdir("/proc/self/fd"))


class _CallerComparisonTrap:
    def __eq__(self, _other: object) -> bool:
        raise RuntimeError("SECRET_FROM_CALLER_COMPARISON")

    def __ne__(self, _other: object) -> bool:
        raise RuntimeError("SECRET_FROM_CALLER_COMPARISON")


class _CallerStringTrap(str):
    def __bool__(self) -> bool:
        raise RuntimeError("SECRET_FROM_CALLER_PATH")


def _tree_snapshot(root: Path) -> dict[str, tuple[object, ...]]:
    result: dict[str, tuple[object, ...]] = {}
    for path in (root, *sorted(root.rglob("*"))):
        value = path.lstat()
        content_digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        result[str(path.relative_to(root))] = (
            int(value.st_dev),
            int(value.st_ino),
            int(value.st_size),
            int(value.st_mtime_ns),
            int(value.st_ctime_ns),
            int(value.st_mode),
            int(value.st_uid),
            int(value.st_nlink),
            content_digest,
        )
    return result


def test_authentic_store_object_reads_as_detached_exact_bytes(tmp_path: Path) -> None:
    reader, address, _path, payload = _harness(tmp_path)

    result = reader.read(
        address.payload_sha256,
        expected_byte_count=len(payload),
        address=address,
    )

    assert type(result) is bytes
    assert result == payload
    assert result is not payload


def test_constructor_and_missing_read_create_nothing(tmp_path: Path) -> None:
    root = tmp_path / "must-not-be-created"

    reader = ImmutableSourcePayloadReaderV4(str(root))

    assert not root.exists()
    with pytest.raises(ImmutableSourcePayloadReaderV4NotFoundError):
        reader.read("0" * 64)
    assert not root.exists()


def test_constructor_and_read_invoke_no_mutating_or_network_primitive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader, address, path, payload = _harness(tmp_path)
    root = path.parents[2]
    before = _tree_snapshot(root)

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("read-only reader invoked a forbidden primitive")

    for name in (
        "mkdir",
        "chmod",
        "fchmod",
        "fsync",
        "fdatasync",
        "write",
        "pwrite",
        "truncate",
        "ftruncate",
        "rename",
        "replace",
        "unlink",
        "remove",
        "link",
        "symlink",
    ):
        if hasattr(os, name):
            monkeypatch.setattr(os, name, forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)

    second_reader = ImmutableSourcePayloadReaderV4(str(root))
    assert second_reader.read(address.payload_sha256, address=address) == payload
    assert reader.read(address.payload_sha256, address=address) == payload
    assert _tree_snapshot(root) == before


@pytest.mark.parametrize(
    ("root", "reason"),
    [
        (Path("/not-an-exact-string"), "exact_string_required"),
        ("relative/cas", "absolute_required"),
        ("/", "root_invalid"),
        ("/safe/../escaped-cas", "traversal_forbidden"),
        ("/safe/nul\x00cas", "nul_forbidden"),
        ("/safe/invalid-\ud800", "utf8_invalid"),
        ("/" + "x" * 4096, "too_long"),
        (str(Path("/").joinpath(*(f"p{index}" for index in range(129)))), "too_deep"),
    ],
)
def test_root_path_is_exact_absolute_bounded_and_non_traversing(
    root: object,
    reason: str,
) -> None:
    with pytest.raises(ImmutableSourcePayloadReaderV4ValidationError, match=reason):
        ImmutableSourcePayloadReaderV4(root)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "root",
    [
        _CallerStringTrap("/attacker-controlled"),
        Path(_CallerStringTrap("/attacker-controlled")),
    ],
)
def test_polymorphic_root_material_is_rejected_before_caller_code_can_run(
    root: object,
) -> None:
    with pytest.raises(
        ImmutableSourcePayloadReaderV4ValidationError,
        match="root_exact_string_required",
    ) as captured:
        ImmutableSourcePayloadReaderV4(root)  # type: ignore[arg-type]

    assert "SECRET" not in str(captured.value)


@pytest.mark.parametrize(
    "digest",
    [
        "0" * 63,
        "0" * 65,
        "A" * 64,
        "../" + "0" * 61,
        "/" + "0" * 63,
        "00/" + "0" * 61,
        "0" * 63 + "\x00",
    ],
)
def test_digest_must_be_exact_lowercase_hex_without_path_material(
    tmp_path: Path,
    digest: str,
) -> None:
    reader, _address, _path, _payload = _harness(tmp_path)

    with pytest.raises(
        ImmutableSourcePayloadReaderV4ValidationError,
        match="sha256_invalid",
    ):
        reader.read(digest)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            lambda address: replace(address, schema_version="wrong-schema"),
            "address_schema_mismatch",
        ),
        (
            lambda address: replace(address, payload_sha256="0" * 64),
            "address_digest_mismatch",
        ),
        (
            lambda address: replace(address, payload_byte_count=1),
            "address_byte_count_mismatch",
        ),
        (
            lambda address: replace(address, relative_path="sha256/../escape"),
            "address_relative_path_mismatch",
        ),
    ],
)
def test_supplied_address_must_exactly_match_derived_address(
    tmp_path: Path,
    mutation: object,
    reason: str,
) -> None:
    reader, address, _path, _payload = _harness(tmp_path)
    mutate = mutation
    assert callable(mutate)
    changed = mutate(address)

    with pytest.raises(ImmutableSourcePayloadReaderV4ValidationError, match=reason):
        reader.read(
            address.payload_sha256,
            expected_byte_count=address.payload_byte_count,
            address=changed,
        )


def test_address_count_must_be_exact_int_and_agree_with_explicit_count(
    tmp_path: Path,
) -> None:
    reader, address, _path, _payload = _harness(tmp_path)
    bool_count = replace(address, payload_byte_count=True)

    with pytest.raises(
        ImmutableSourcePayloadReaderV4ValidationError,
        match="byte_count_invalid",
    ):
        reader.read(address.payload_sha256, address=bool_count)
    with pytest.raises(
        ImmutableSourcePayloadReaderV4ValidationError,
        match="address_byte_count_mismatch",
    ):
        reader.read(
            address.payload_sha256,
            expected_byte_count=address.payload_byte_count + 1,
            address=address,
        )


@pytest.mark.parametrize(
    ("field_name", "reason"),
    [
        ("schema_version", "address_schema_invalid"),
        ("payload_sha256", "address_digest_invalid"),
        ("relative_path", "address_relative_path_invalid"),
    ],
)
def test_address_fields_reject_caller_objects_before_comparison(
    tmp_path: Path,
    field_name: str,
    reason: str,
) -> None:
    reader, address, _path, _payload = _harness(tmp_path)
    caller_object = cast(str, _CallerComparisonTrap())
    if field_name == "schema_version":
        changed = replace(address, schema_version=caller_object)
    elif field_name == "payload_sha256":
        changed = replace(address, payload_sha256=caller_object)
    else:
        changed = replace(address, relative_path=caller_object)

    with pytest.raises(
        ImmutableSourcePayloadReaderV4ValidationError,
        match=reason,
    ) as captured:
        reader.read(address.payload_sha256, address=changed)

    assert "SECRET" not in str(captured.value)


def test_malformed_exact_address_container_is_totalized(tmp_path: Path) -> None:
    reader, address, _path, _payload = _harness(tmp_path)
    malformed = object.__new__(SourcePayloadAddress)

    with pytest.raises(
        ImmutableSourcePayloadReaderV4ValidationError,
        match="address_fields_invalid",
    ) as captured:
        reader.read(address.payload_sha256, address=malformed)

    assert "AttributeError" not in str(captured.value)


def test_missing_object_and_wrong_expected_count_fail_closed(tmp_path: Path) -> None:
    reader, address, _path, _payload = _harness(tmp_path)
    missing_digest = address.payload_sha256[:2] + "0" * 62
    if missing_digest == address.payload_sha256:
        missing_digest = address.payload_sha256[:2] + "1" * 62

    with pytest.raises(ImmutableSourcePayloadReaderV4NotFoundError):
        reader.read(missing_digest)
    with pytest.raises(
        ImmutableSourcePayloadReaderV4IntegrityError,
        match="stored_byte_count_mismatch",
    ):
        reader.read(
            address.payload_sha256,
            expected_byte_count=address.payload_byte_count + 1,
        )


def test_same_address_with_wrong_content_fails_digest_verification(tmp_path: Path) -> None:
    reader, address, path, payload = _harness(tmp_path)
    path.chmod(0o600)
    path.write_bytes(b"X" * len(payload))
    path.chmod(0o400)

    with pytest.raises(
        ImmutableSourcePayloadReaderV4IntegrityError,
        match="sha256_mismatch",
    ):
        reader.read(address.payload_sha256)


@pytest.mark.parametrize("attack", ["object", "root", "shard"])
def test_symlink_substitution_is_rejected_without_following_target(
    tmp_path: Path,
    attack: str,
) -> None:
    reader, address, path, _payload = _harness(tmp_path)
    root = path.parents[2]
    if attack == "object":
        target = tmp_path / "object-target"
        path.rename(target)
        path.symlink_to(target)
        attacked_reader = reader
    elif attack == "root":
        alias = tmp_path / "root-alias"
        alias.symlink_to(root, target_is_directory=True)
        attacked_reader = ImmutableSourcePayloadReaderV4(str(alias))
    else:
        shard_target = tmp_path / "shard-target"
        path.parent.rename(shard_target)
        path.parent.symlink_to(shard_target, target_is_directory=True)
        attacked_reader = reader

    with pytest.raises(ImmutableSourcePayloadReaderV4IntegrityError):
        attacked_reader.read(address.payload_sha256)


def test_hardlink_and_non_private_modes_are_rejected(tmp_path: Path) -> None:
    hardlink_reader, hardlink_address, hardlink_path, _payload = _harness(tmp_path / "hardlink")
    os.link(hardlink_path, hardlink_path.with_name("attacker-hardlink"))
    with pytest.raises(
        ImmutableSourcePayloadReaderV4IntegrityError,
        match="hardlink_forbidden",
    ):
        hardlink_reader.read(hardlink_address.payload_sha256)

    object_reader, object_address, object_path, _payload = _harness(tmp_path / "object-mode")
    object_path.chmod(0o600)
    with pytest.raises(
        ImmutableSourcePayloadReaderV4IntegrityError,
        match="object_mode_mismatch",
    ):
        object_reader.read(object_address.payload_sha256)

    root_reader, root_address, root_path, _payload = _harness(tmp_path / "root-mode")
    root_path.parents[2].chmod(0o750)
    with pytest.raises(
        ImmutableSourcePayloadReaderV4IntegrityError,
        match="directory_mode_mismatch",
    ):
        root_reader.read(root_address.payload_sha256)


@pytest.mark.parametrize("attack", ["identity", "content"])
def test_concurrent_object_identity_or_content_change_is_detected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
) -> None:
    reader, address, path, payload = _harness(tmp_path)
    original_pread = os.pread
    attacked = False

    def attacking_pread(descriptor: int, count: int, offset: int) -> bytes:
        nonlocal attacked
        if not attacked:
            attacked = True
            if attack == "identity":
                displaced = path.with_name("displaced-object")
                path.rename(displaced)
                path.write_bytes(payload)
                path.chmod(0o400)
            else:
                path.chmod(0o600)
                path.write_bytes(b"Z" * len(payload))
                path.chmod(0o400)
        return original_pread(descriptor, count, offset)

    monkeypatch.setattr(os, "pread", attacking_pread)
    with pytest.raises(ImmutableSourcePayloadReaderV4IntegrityError):
        reader.read(address.payload_sha256, address=address)
    assert attacked is True


def test_os_errors_are_totalized_without_secret_text_and_fds_are_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader, address, _path, _payload = _harness(tmp_path)
    original_open = os.open
    before_fds = _fd_count()

    def failing_namespace_open(
        path: str | bytes,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if path == "sha256":
            raise PermissionError("SECRET_OPERATOR_PATH_AND_TOKEN")
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", failing_namespace_open)
    with pytest.raises(ImmutableSourcePayloadReaderV4IntegrityError) as captured:
        reader.read(address.payload_sha256)

    assert str(captured.value) == "immutable_source_payload_directory_open_failed"
    assert "SECRET" not in str(captured.value)
    assert _fd_count() == before_fds
