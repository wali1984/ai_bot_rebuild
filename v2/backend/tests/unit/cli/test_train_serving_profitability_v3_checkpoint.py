from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.train_serving_profitability_v3_checkpoint import (
    _prepare_evidence_directory,
    _write_immutable_json,
)


def test_evidence_write_is_fsynced_immutable_and_idempotent(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    _prepare_evidence_directory(evidence_dir)
    target = evidence_dir / "report.json"

    first_sha = _write_immutable_json(target, {"safe": True})
    replay_sha = _write_immutable_json(target, {"safe": True})

    assert replay_sha == first_sha
    assert hashlib.sha256(target.read_bytes()).hexdigest() == first_sha
    with pytest.raises(ValueError, match="EVIDENCE_COLLISION_WITH_DIFFERENT_BYTES"):
        _write_immutable_json(target, {"safe": False})
    assert target.read_text() == '{\n  "safe": true\n}\n'


def test_evidence_write_rejects_nonfinite_json(tmp_path: Path) -> None:
    _prepare_evidence_directory(tmp_path)

    with pytest.raises(ValueError, match="Out of range float values"):
        _write_immutable_json(tmp_path / "report.json", {"value": float("nan")})
