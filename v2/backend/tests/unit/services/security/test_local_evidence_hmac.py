from __future__ import annotations

import json

import pytest
from v2.backend.app.services.security import local_evidence_hmac as auth
from v2.backend.app.services.security.local_evidence_runtime_credentials import (
    MARK_ACTIVE_KEY_ID_ENV,
    MARK_CREDENTIAL_PREFIX,
    MARK_RETAINED_KEY_IDS_ENV,
    SYSTEMD_CREDENTIALS_DIRECTORY_ENV,
    RuntimeHmacKeyRing,
    load_mark_keyring_from_systemd_credentials,
    require_disjoint_authentication_keys,
)

OLD_ID = "mark-2026-06"
NEW_ID = "mark-2026-07"
OLD_KEY = b"o" * 32
NEW_KEY = b"n" * 32
PAPER_KEY = b"p" * 32


def _seal(*, key_id: str = NEW_ID, key: bytes = NEW_KEY) -> dict[str, object]:
    return auth.seal_hmac_sha256(
        {"schema_version": "unit_v1", "value": 7, "paper_only": True},
        trust_domain=auth.MARK_RECEIPT_TRUST_DOMAIN,
        authentication_key_id=key_id,
        authentication_key=key,
    )


def test_exact_canonical_payload_and_constant_time_tag_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _seal()
    original = auth.hmac.compare_digest
    comparisons: list[tuple[object, object]] = []

    def observed_compare(left: object, right: object) -> bool:
        comparisons.append((left, right))
        return original(left, right)  # type: ignore[arg-type]

    monkeypatch.setattr(auth.hmac, "compare_digest", observed_compare)
    assert auth.verify_hmac_sha256(
        payload,
        expected_trust_domain=auth.MARK_RECEIPT_TRUST_DOMAIN,
        authentication_keys={NEW_ID: NEW_KEY},
        reason_prefix="UNIT",
    ) == []
    assert any(left == payload[auth.AUTH_TAG_FIELD] for left, _ in comparisons)

    with pytest.raises(
        auth.LocalEvidenceAuthenticationError,
        match="NOT_CANONICAL_JSON",
    ):
        auth.seal_hmac_sha256(
            {"value": float("nan")},
            trust_domain=auth.MARK_RECEIPT_TRUST_DOMAIN,
            authentication_key_id=NEW_ID,
            authentication_key=NEW_KEY,
        )
    with pytest.raises(
        auth.LocalEvidenceAuthenticationError,
        match="NOT_STRING_KEYED_MAPPING",
    ):
        auth.seal_hmac_sha256(
            {1: "ambiguous"},  # type: ignore[dict-item]
            trust_domain=auth.MARK_RECEIPT_TRUST_DOMAIN,
            authentication_key_id=NEW_ID,
            authentication_key=NEW_KEY,
        )


def test_recomputed_plain_hash_and_wrong_key_cannot_forge_authority() -> None:
    payload = _seal()
    forged = dict(payload)
    forged["value"] = 999
    # An attacker can recompute any public SHA field, but not the HMAC tag.
    forged["evidence_sha256"] = auth.canonical_json_bytes(
        {"attacker": "controlled"}
    ).hex()[:64]
    reasons = auth.verify_hmac_sha256(
        forged,
        expected_trust_domain=auth.MARK_RECEIPT_TRUST_DOMAIN,
        authentication_keys={NEW_ID: NEW_KEY},
        reason_prefix="UNIT",
    )
    assert "UNIT_AUTH_TAG_MISMATCH" in reasons

    wrong_key_reasons = auth.verify_hmac_sha256(
        payload,
        expected_trust_domain=auth.MARK_RECEIPT_TRUST_DOMAIN,
        authentication_keys={NEW_ID: b"w" * 32},
        reason_prefix="UNIT",
    )
    assert "UNIT_AUTH_TAG_MISMATCH" in wrong_key_reasons


def test_key_id_rotation_accepts_retained_old_key_but_not_unknown_key() -> None:
    old_payload = _seal(key_id=OLD_ID, key=OLD_KEY)
    rotated_ring = RuntimeHmacKeyRing(
        active_key_id=NEW_ID,
        keys={NEW_ID: NEW_KEY, OLD_ID: OLD_KEY},
    )
    assert auth.verify_hmac_sha256(
        old_payload,
        expected_trust_domain=auth.MARK_RECEIPT_TRUST_DOMAIN,
        authentication_keys=rotated_ring.keys,
        reason_prefix="UNIT",
    ) == []

    new_payload = _seal(
        key_id=rotated_ring.active_key_id,
        key=rotated_ring.signing_key,
    )
    old_only_reasons = auth.verify_hmac_sha256(
        new_payload,
        expected_trust_domain=auth.MARK_RECEIPT_TRUST_DOMAIN,
        authentication_keys={OLD_ID: OLD_KEY},
        reason_prefix="UNIT",
    )
    assert "UNIT_AUTH_KEY_UNAVAILABLE" in old_only_reasons


def test_domain_separation_and_key_material_reuse_fail_closed() -> None:
    mark_payload = _seal()
    reasons = auth.verify_hmac_sha256(
        mark_payload,
        expected_trust_domain=auth.PAPER_AUTHORITY_TRUST_DOMAIN,
        authentication_keys={NEW_ID: NEW_KEY},
        reason_prefix="UNIT",
    )
    assert "UNIT_AUTH_TRUST_DOMAIN_INVALID" in reasons
    assert "UNIT_AUTH_TAG_MISMATCH" in reasons

    mark_ring = RuntimeHmacKeyRing(
        active_key_id="mark-v1",
        keys={"mark-v1": NEW_KEY},
    )
    paper_ring = RuntimeHmacKeyRing(
        active_key_id="paper-v1",
        keys={"paper-v1": PAPER_KEY},
    )
    require_disjoint_authentication_keys([mark_ring, paper_ring])
    reused = RuntimeHmacKeyRing(
        active_key_id="paper-reused",
        keys={"paper-reused": NEW_KEY},
    )
    with pytest.raises(
        auth.LocalEvidenceAuthenticationError,
        match="REUSED_ACROSS_TRUST_DOMAINS",
    ):
        require_disjoint_authentication_keys([mark_ring, reused])
    with pytest.raises(
        auth.LocalEvidenceAuthenticationError,
        match="REUSED_ACROSS_TRUST_DOMAINS",
    ):
        require_disjoint_authentication_keys(
            [mark_ring, paper_ring],
            forbidden_keys=[PAPER_KEY],
        )


def test_systemd_keyring_loader_has_no_environment_secret_fallback_and_rotates(
    tmp_path,
) -> None:
    for key_id, key in ((NEW_ID, NEW_KEY), (OLD_ID, OLD_KEY)):
        (tmp_path / f"{MARK_CREDENTIAL_PREFIX}.{key_id}").write_bytes(key + b"\n")
    environ = {
        SYSTEMD_CREDENTIALS_DIRECTORY_ENV: str(tmp_path),
        MARK_ACTIVE_KEY_ID_ENV: NEW_ID,
        MARK_RETAINED_KEY_IDS_ENV: f"{NEW_ID},{OLD_ID}",
        # Deliberately ignored: secret environment values are not a supported
        # input to the loader.
        "V2_MARK_EVIDENCE_HMAC_KEY": "attacker-env-fallback",
    }
    ring = load_mark_keyring_from_systemd_credentials(environ=environ)

    assert ring.active_key_id == NEW_ID
    assert ring.signing_key == NEW_KEY
    assert ring.keys[OLD_ID] == OLD_KEY
    assert "attacker-env-fallback" not in json.dumps(ring.safe_metadata())

    missing_credential_env = {
        **environ,
        SYSTEMD_CREDENTIALS_DIRECTORY_ENV: str(tmp_path / "missing"),
    }
    with pytest.raises(auth.LocalEvidenceAuthenticationError):
        load_mark_keyring_from_systemd_credentials(
            environ=missing_credential_env
        )
