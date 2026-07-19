from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from claude_worklog.tools import parallel_capacity_scheduler as module


def _event(name: str, **extra: object) -> bytes:
    return json.dumps({"event": name, **extra}).encode("utf-8")


def test_read_text_reads_only_the_requested_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "large.txt"
    path.write_bytes(b"a" * (module.MAX_TEXT_READ_CHARS + 1_000_000))

    def forbidden_read_text(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("whole-file Path.read_text must not be used")

    monkeypatch.setattr(Path, "read_text", forbidden_read_text)

    assert module.read_text(path, 37) == "a" * 37
    assert len(module.read_text(path, module.MAX_TEXT_READ_CHARS + 1)) == (
        module.MAX_TEXT_READ_CHARS
    )
    assert module.read_text(path, 0) == ""
    assert module.read_text(path, -1) == ""
    assert module.read_text(path, True) == ""


def test_tail_reader_returns_complete_lines_newest_first(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_bytes(b"first\nsecond\n\nthird\n")

    assert module._tail_event_lines_newest(path) == [
        b"third",
        b"",
        b"second",
        b"first",
    ]


def test_tail_reader_drops_a_byte_cap_truncated_leading_line(
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.jsonl"
    path.write_bytes(b"old\n" + (b"x" * 40) + b"\nnew\n")

    assert module._tail_event_lines_newest(path, max_bytes=12) == [b"new"]


def test_tail_reader_counts_oversized_lines_inside_last_n_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "events.jsonl"
    path.write_bytes(b"older\n123456789\nnewest\n")
    monkeypatch.setattr(module, "EVENT_LINE_MAX_BYTES", 8)

    assert module._tail_event_lines_newest(path, max_lines=2) == [
        b"newest",
        b"",
    ]


def test_latest_event_matching_uses_only_the_last_line_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "events.jsonl"
    rows = [_event("target", sequence=0)]
    rows.extend(_event("noise", sequence=index) for index in range(2_001))
    path.write_bytes(b"\n".join(rows) + b"\n")
    monkeypatch.setattr(module, "EVENTS", path)

    assert module.latest_event_matching("target") == {}

    with path.open("ab") as handle:
        handle.write(_event("target", sequence=2_002) + b"\n")
    assert module.latest_event_matching("target") == {
        "event": "target",
        "sequence": 2_002,
    }


def test_latest_event_matching_ignores_a_large_sparse_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "events.jsonl"
    with path.open("wb") as handle:
        handle.write(_event("old_target") + b"\n")
        handle.seek(module.EVENT_TAIL_MAX_BYTES * 8)
        handle.write(b"discarded_partial_line\n")
        handle.write(_event("recent_target", sequence=7) + b"\n")
    monkeypatch.setattr(module, "EVENTS", path)

    assert module.latest_event_matching("target") == {
        "event": "recent_target",
        "sequence": 7,
    }


def test_latest_event_matching_bounds_invalid_raw_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "events.jsonl"
    raw = "target:" + ("s" * (module.EVENT_RAW_FALLBACK_MAX_CHARS + 100))
    path.write_text(raw + "\n", encoding="utf-8")
    monkeypatch.setattr(module, "EVENTS", path)

    result = module.latest_event_matching("target")

    assert result["raw"] == raw[: module.EVENT_RAW_FALLBACK_MAX_CHARS]
    assert result["raw_truncated"] is True


@pytest.mark.parametrize(
    ("max_lines", "max_bytes"),
    [(0, 1), (-1, 1), (True, 1), (1, 0), (1, -1), (1, True)],
)
def test_tail_reader_rejects_invalid_resource_bounds(
    tmp_path: Path,
    max_lines: int,
    max_bytes: int,
) -> None:
    path = tmp_path / "events.jsonl"
    path.write_bytes(b"event\n")

    assert (
        module._tail_event_lines_newest(
            path,
            max_lines=max_lines,
            max_bytes=max_bytes,
        )
        == []
    )


def test_tail_reader_clamps_caller_bounds_to_hard_module_caps() -> None:
    class RecordingFile(BytesIO):
        def __init__(self, payload: bytes) -> None:
            super().__init__(payload)
            self.read_sizes: list[int | None] = []

        def read(self, size: int | None = -1) -> bytes:
            self.read_sizes.append(size)
            return super().read(size)

        def __exit__(self, *args: object) -> None:
            return None

    payload = b"\n".join(
        _event("noise", sequence=index)
        for index in range(module.EVENT_TAIL_MAX_LINES + 1)
    )
    recording_file = RecordingFile(payload)

    class RecordingPath:
        def open(self, mode: str) -> RecordingFile:
            assert mode == "rb"
            return recording_file

    path: Any = RecordingPath()
    lines = module._tail_event_lines_newest(
        path,
        max_lines=module.EVENT_TAIL_MAX_LINES * 100,
        max_bytes=module.EVENT_TAIL_MAX_BYTES * 100,
    )

    assert len(lines) == module.EVENT_TAIL_MAX_LINES
    assert recording_file.read_sizes
    assert all(size is not None for size in recording_file.read_sizes)
    assert (
        max(size for size in recording_file.read_sizes if size is not None)
        <= module.EVENT_TAIL_MAX_BYTES
    )


def test_resource_bounds_reject_hostile_class_and_int_subclass_without_hooks(
    tmp_path: Path,
) -> None:
    class HostileBound:
        calls = 0

        def __getattribute__(self, name: str) -> Any:
            if name == "__class__":
                type(self).calls += 1
                raise RuntimeError("SENSITIVE_BOUND_CLASS_SECRET")
            return super().__getattribute__(name)

    class HostileInt(int):
        calls = 0

        def __getattribute__(self, name: str) -> Any:
            if name == "__class__":
                type(self).calls += 1
                raise RuntimeError("SENSITIVE_BOUND_CLASS_SECRET")
            return super().__getattribute__(name)

    path = tmp_path / "events.jsonl"
    path.write_bytes(b"event\n")
    cases: list[tuple[type[Any], Any]] = [
        (HostileBound, HostileBound()),
        (HostileInt, HostileInt(1)),
    ]
    for hostile_type, hostile in cases:
        hostile_type.calls = 0
        assert module.read_text(path, hostile) == ""
        assert module._tail_event_lines_newest(path, max_lines=hostile) == []
        assert module._tail_event_lines_newest(path, max_bytes=hostile) == []
        assert hostile_type.calls == 0
