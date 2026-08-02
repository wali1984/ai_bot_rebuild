"""The readiness-proof cache must be an optimisation, never a trust shortcut.

The proof is O(total archive bytes) and dominated the trainer's wall clock. It
is now reused, but only while the archive's on-disk content identity is
unchanged -- so a cache hit must be provably equivalent to recomputing, and any
write, tamper or replacement must force a fresh proof.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from v2.backend.app.services import durable_paper_evidence_archive as mod
from v2.backend.app.services.durable_paper_evidence_archive import (
    ArchiveCandidate,
    DurablePaperEvidenceArchive,
)

STREAM = "unit_test_stream_v1"
SOURCE_KEY = "v2:unit:test:source"


@pytest.fixture(autouse=True)
def _clear_cache():
    mod._READINESS_PROOF_CACHE.clear()
    yield
    mod._READINESS_PROOF_CACHE.clear()


def _archive(tmp_path: Path, rows: int = 3) -> DurablePaperEvidenceArchive:
    archive = DurablePaperEvidenceArchive(tmp_path / "evidence.sqlite3", stream_id=STREAM)
    archive.append_unique(
        ArchiveCandidate(
            record_id=f"rec-{i}",
            sort_key=f"{i:04d}",
            payload={"i": i, "source_key": SOURCE_KEY},
        )
        for i in range(rows)
    )
    return archive


def _proof(archive: DurablePaperEvidenceArchive) -> dict:
    return archive.verified_replacement_readiness(source_key=SOURCE_KEY)


def test_repeated_proofs_are_served_from_cache_when_archive_is_unchanged(tmp_path) -> None:
    archive = _archive(tmp_path)
    first = _proof(archive)
    second = _proof(archive)
    assert first["readiness_proof_served_from_cache"] is False
    assert second["readiness_proof_served_from_cache"] is True
    # A cache hit must be indistinguishable from recomputation.
    assert second["archive_chain_sha256"] == first["archive_chain_sha256"]
    assert second["readiness_verified"] == first["readiness_verified"]
    assert second["rejection_reasons"] == first["rejection_reasons"]


def test_an_append_invalidates_the_cache(tmp_path) -> None:
    archive = _archive(tmp_path)
    _proof(archive)
    archive.append_unique([ArchiveCandidate(record_id="rec-new", sort_key="9999", payload={"i": 99})])
    after = _proof(archive)
    assert after["readiness_proof_served_from_cache"] is False


def test_direct_row_tampering_forces_a_fresh_proof(tmp_path) -> None:
    """The critical property: a cache hit must never mask a mutated archive."""
    archive = _archive(tmp_path)
    _proof(archive)
    assert _proof(archive)["readiness_proof_served_from_cache"] is True
    fingerprint_before = archive._archive_content_fingerprint()

    connection = sqlite3.connect(str(archive.path))
    connection.execute(
        "UPDATE evidence_records SET payload_json = ? WHERE record_id = ?",
        ('{"i": "tampered"}', "rec-1"),
    )
    connection.commit()
    connection.close()

    # The mutation changes the archive's content identity, so the next proof is
    # recomputed against the tampered bytes instead of being served from cache.
    assert archive._archive_content_fingerprint() != fingerprint_before
    assert _proof(archive)["readiness_proof_served_from_cache"] is False


def test_cache_is_scoped_per_source_key(tmp_path) -> None:
    archive = _archive(tmp_path)
    _proof(archive)
    other = archive.verified_replacement_readiness(source_key="v2:unit:test:other")
    assert other["readiness_proof_served_from_cache"] is False


def test_cache_can_be_disabled(tmp_path, monkeypatch) -> None:
    archive = _archive(tmp_path)
    monkeypatch.setattr(mod, "DURABLE_ARCHIVE_READINESS_PROOF_CACHE", False)
    assert _proof(archive)["readiness_proof_served_from_cache"] is False
    assert _proof(archive)["readiness_proof_served_from_cache"] is False


def test_unreadable_archive_never_serves_a_cached_proof(tmp_path, monkeypatch) -> None:
    archive = _archive(tmp_path)
    _proof(archive)
    # No fingerprint => no reuse, fail toward recomputation.
    monkeypatch.setattr(
        DurablePaperEvidenceArchive, "_archive_content_fingerprint", lambda self: None
    )
    assert _proof(archive)["readiness_proof_served_from_cache"] is False


def test_fingerprint_tracks_writes(tmp_path) -> None:
    archive = _archive(tmp_path)
    before = archive._archive_content_fingerprint()
    archive.append_unique([ArchiveCandidate(record_id="rec-x", sort_key="8888", payload={"i": 8})])
    assert archive._archive_content_fingerprint() != before


def test_cache_does_not_grow_without_bound(tmp_path) -> None:
    archive = _archive(tmp_path)
    for i in range(mod._READINESS_PROOF_CACHE_MAX_ENTRIES + 5):
        archive.verified_replacement_readiness(source_key=f"key-{i}")
    assert len(mod._READINESS_PROOF_CACHE) <= mod._READINESS_PROOF_CACHE_MAX_ENTRIES
