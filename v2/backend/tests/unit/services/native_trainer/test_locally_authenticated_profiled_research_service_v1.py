from __future__ import annotations

import hashlib
import hmac
import types
from pathlib import Path

import pytest

from v2.backend.app.services.native_trainer import (
    locally_authenticated_profiled_research_service_v1 as service,
)
from v2.backend.app.services.native_trainer.authenticated_profiled_resident_runtime_credentials_v1 import (  # noqa: E501
    AuthenticatedProfiledResidentLocalRoleCredentialsV1,
    AuthenticatedProfiledResidentRuntimeCredentialsV1,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (
    V2HybridCheckpointManager,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint_lifecycle import (  # noqa: E501
    LOCAL_PROFILED_RESEARCH_TRAINER_LEASE_OWNER_ROLE,
    checkpoint_lifecycle_lease,
    require_active_checkpoint_lifecycle_lease,
)

_LOCAL_KEY = b"local-research-service-test-key-material-000001"


def _authorization_contract() -> dict[str, object]:
    material: dict[str, object] = {
        "domain": service.LOCAL_PROFILED_RESEARCH_AUTHORIZATION_DOMAIN,
        "schema_version": "local_profiled_research_optimizer_authorization_v1",
        "authorization_key_id": "local-research-v1",
        "corpus_contract_sha256": "1" * 64,
        "ordered_example_fingerprints_sha256": "2" * 64,
        "manifest_id": "3" * 64,
        "manifest_observation_time": "2026-07-22T20:00:00.000000Z",
        "admitted_example_count": 18,
        "local_research_non_promotable": True,
        "external_witness_verified": False,
    }
    tag = hmac.new(
        _LOCAL_KEY,
        service.LOCAL_PROFILED_RESEARCH_AUTHORIZATION_DOMAIN.encode("ascii")
        + b"\0"
        + service._canonical_bytes(material),  # noqa: SLF001
        hashlib.sha256,
    ).hexdigest()
    return {
        "local_research_auth_key_id": material["authorization_key_id"],
        "corpus_contract_sha256": material["corpus_contract_sha256"],
        "ordered_example_fingerprints_sha256": material[
            "ordered_example_fingerprints_sha256"
        ],
        "manifest_id": material["manifest_id"],
        "manifest_observation_time": material["manifest_observation_time"],
        "manifest_admitted_example_count": material["admitted_example_count"],
        "local_research_non_promotable": True,
        "external_witness_verified": False,
        "authorization_tag": tag,
        "authorization_receipt_sha256": service.stable_sha256(
            {**material, "authorization_tag": tag}
        ),
    }


def _config(tmp_path: Path) -> service.LocallyAuthenticatedProfiledResearchServiceConfigV1:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    (tmp_path / "repo").mkdir()
    return service.LocallyAuthenticatedProfiledResearchServiceConfigV1(
        repo_root=(tmp_path / "repo").absolute(),
        publisher_status_path=(tmp_path / "publisher-status.json").absolute(),
        feature_ledger_path=(tmp_path / "ledger.sqlite3").absolute(),
        label_archive_path=(tmp_path / "labels.sqlite3").absolute(),
        trusted_immutable_cost_store_root=(tmp_path / "cost-cas").absolute(),
        runtime_root=runtime.absolute(),
        model_dir=(tmp_path / ".local_models" / "model").absolute(),
        status_path=(runtime / "status.json").absolute(),
        manifest_auth_key_id="manifest-v1",
        local_research_auth_key_id="local-research-v1",
        page_limit=256,
        scan_limit=250_000,
        validation_fraction=0.2,
        optimizer_input_byte_budget=8 * 1024 * 1024,
        state_resource_budget_bytes=64 * 1024 * 1024,
        checkpoint_serialization_byte_budget=128 * 1024 * 1024,
        interval_seconds=30.0,
    )


def _credentials(
    *,
    local_key: bytes | None = _LOCAL_KEY,
) -> AuthenticatedProfiledResidentRuntimeCredentialsV1:
    return AuthenticatedProfiledResidentRuntimeCredentialsV1(
        local_roles=AuthenticatedProfiledResidentLocalRoleCredentialsV1(
            state_hmac_key=b"state-service-test-key-material-0000000001",
            manifest_hmac_key=b"manifest-service-test-key-material-00000002",
            head_hmac_key=b"head-service-test-key-material-00000000003",
            epoch_hmac_key=b"epoch-service-test-key-material-0000000004",
        ),
        local_research_hmac_key=local_key,
    )


def _result() -> service.LocallyAuthenticatedProfiledResearchCycleResultV1:
    return service.LocallyAuthenticatedProfiledResearchCycleResultV1(
        classification=service.LOCAL_PROFILED_RESEARCH_CHECKPOINT_PUBLISHED,
        publisher_status_sha256="1" * 64,
        publisher_cycle_completed_at="2026-07-22T20:00:00.000000Z",
        publisher_discovered_symbol_count=163,
        publisher_eligible_symbol_count=76,
        publisher_published_symbol_count=18,
        manifest_id="2" * 64,
        manifest_observation_time="2026-07-22T20:00:00.000000Z",
        manifest_total_profiled_samples=20,
        manifest_admitted_example_count=18,
        manifest_label_unavailable_count=2,
        manifest_ordered_entry_identities_sha256="3" * 64,
        corpus_contract_sha256="4" * 64,
        authorization_receipt_sha256="5" * 64,
        base_checkpoint_id="base-checkpoint",
        candidate_checkpoint_id="candidate-checkpoint",
        candidate_checkpoint_generation=2,
        candidate_source_manifest_id="2" * 64,
        candidate_source_manifest_observation_time="2026-07-22T20:00:00.000000Z",
        candidate_source_manifest_exact_match=True,
        candidate_source_corpus_entry_identity_equivalent=True,
        optimizer_execution_completed=True,
        checkpoint_publication_completed=True,
        already_published=False,
        checkpoint_artifact_verified=True,
        local_research_non_promotable=True,
        external_witness_verified=False,
        checkpoint_write_authorized=False,
        **service._DOWNSTREAM_FALSE,  # noqa: SLF001
    )


def test_once_service_writes_running_then_hmac_authenticated_safe_result(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    credentials = _credentials()
    writes: list[dict[str, object]] = []

    assert (
        service.run_locally_authenticated_profiled_research_service_v1(
            config,
            credentials,
            once=True,
            cycle_runner=lambda _config, _credentials: _result(),
            writer=lambda _config, payload: writes.append(dict(payload)),
            emit=lambda _payload: None,
        )
        == 0
    )

    assert len(writes) == 2
    assert writes[0]["classification"] == service.LOCAL_PROFILED_RESEARCH_CYCLE_RUNNING
    final = writes[1]
    assert final["classification"] == service.LOCAL_PROFILED_RESEARCH_CHECKPOINT_PUBLISHED
    assert final["external_witness_verified"] is False
    assert final["local_research_non_promotable"] is True
    assert all(final[name] is False for name in service._DOWNSTREAM_FALSE)  # noqa: SLF001
    unsigned = {
        key: value
        for key, value in final.items()
        if key
        not in {
            "status_sha256",
            "status_auth_tag",
            "status_local_hmac_verified_at_write",
        }
    }
    encoded = service._canonical_bytes(unsigned)  # noqa: SLF001
    assert final["status_sha256"] == hashlib.sha256(encoded).hexdigest()
    assert final["status_auth_tag"] == hmac.new(
        _LOCAL_KEY,
        b"v2/native-trainer/local-profiled-research-service-status/v1\0" + encoded,
        hashlib.sha256,
    ).hexdigest()


def test_missing_dedicated_local_authorizer_fails_before_cycle(
    tmp_path: Path,
) -> None:
    called = False

    def forbidden_cycle(
        *_args: object,
    ) -> service.LocallyAuthenticatedProfiledResearchCycleResultV1:
        nonlocal called
        called = True
        raise AssertionError("cycle must not run")

    with pytest.raises(
        service.LocallyAuthenticatedProfiledResearchServiceV1Error,
        match="LOCAL_PROFILED_RESEARCH_AUTHORIZATION_CREDENTIAL_REQUIRED",
    ):
        service.run_locally_authenticated_profiled_research_service_v1(
            _config(tmp_path),
            _credentials(local_key=None),
            once=True,
            cycle_runner=forbidden_cycle,
        )
    assert called is False


def test_publisher_status_reader_uses_keyword_only_verified_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    expected = object()
    received: dict[str, object] = {}

    def reader(*, status_path: Path) -> object:
        received["status_path"] = status_path
        return expected

    monkeypatch.setattr(
        service,
        "read_verified_profiled_base_publisher_cycle_status_v1",
        reader,
    )

    assert service._read_publisher_status(config) is expected  # noqa: SLF001
    assert received == {"status_path": config.publisher_status_path}


def test_local_optimizer_reason_is_preserved_in_fail_closed_status(
    tmp_path: Path,
) -> None:
    writes: list[dict[str, object]] = []

    def fail_cycle(
        *_args: object,
    ) -> service.LocallyAuthenticatedProfiledResearchCycleResultV1:
        raise service.LocallyAuthenticatedProfiledResearchServiceV1Error(
            "PROFILED_LOCAL_RESEARCH_INPUT_BUDGET_EXCEEDED"
        )

    assert (
        service.run_locally_authenticated_profiled_research_service_v1(
            _config(tmp_path),
            _credentials(),
            once=True,
            cycle_runner=fail_cycle,
            writer=lambda _config, payload: writes.append(dict(payload)),
            emit=lambda _payload: None,
        )
        == 1
    )
    assert len(writes) == 2
    assert writes[-1]["classification"] == service.LOCAL_PROFILED_RESEARCH_FAIL_CLOSED
    assert writes[-1]["error"] == {
        "error_type": "LocallyAuthenticatedProfiledResearchServiceV1Error",
        "reason_codes": ["PROFILED_LOCAL_RESEARCH_INPUT_BUDGET_EXCEEDED"],
    }


def test_status_must_be_inside_exact_private_runtime_root(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with pytest.raises(
        service.LocallyAuthenticatedProfiledResearchServiceV1Error,
        match="LOCAL_PROFILED_RESEARCH_CONFIG_INVALID",
    ):
        service.LocallyAuthenticatedProfiledResearchServiceConfigV1(
            **{
                name: getattr(config, name)
                for name in config.__dataclass_fields__  # type: ignore[attr-defined]
                if name != "status_path"
            },
            status_path=(tmp_path / "outside.json").absolute(),
        )


def test_local_candidate_store_shares_causal_parent_but_is_a_distinct_store(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    root_manager = V2HybridCheckpointManager(config.model_dir)
    research_manager = V2HybridCheckpointManager(config.candidate_model_dir)

    assert research_manager._causal_root == root_manager.model_dir  # noqa: SLF001
    assert research_manager._causal_store == (  # noqa: SLF001
        service.LOCAL_PROFILED_RESEARCH_CANDIDATE_DIRECTORY
    )
    assert research_manager.model_dir != root_manager.model_dir


def test_local_research_role_acquires_shared_causal_lifecycle_lease(
    tmp_path: Path,
) -> None:
    model_dir = (tmp_path / ".local_models" / "model").absolute()

    with checkpoint_lifecycle_lease(
        model_dir,
        owner_role=LOCAL_PROFILED_RESEARCH_TRAINER_LEASE_OWNER_ROLE,
    ) as receipt:
        require_active_checkpoint_lifecycle_lease(
            receipt,
            model_dir=model_dir / service.LOCAL_PROFILED_RESEARCH_CANDIDATE_DIRECTORY,
            owner_role=LOCAL_PROFILED_RESEARCH_TRAINER_LEASE_OWNER_ROLE,
        )
        assert receipt.causal_root == str(model_dir)
        assert receipt.checkpoint_write_authorized is False
        assert receipt.serving_authorized is False
        assert receipt.trading_authorized is False


@pytest.mark.parametrize(
    "tampered_field",
    ("authorization_tag", "authorization_receipt_sha256"),
)
def test_recovery_recomputes_local_authorization_and_rejects_forgery(
    tampered_field: str,
) -> None:
    contract = _authorization_contract()
    service._verify_local_research_authorization_contract(  # noqa: SLF001
        contract,
        expected_auth_key_id="local-research-v1",
        authorization_hmac_key=_LOCAL_KEY,
    )
    contract[tampered_field] = "f" * 64

    with pytest.raises(
        service.LocallyAuthenticatedProfiledResearchServiceV1Error,
        match="LOCAL_PROFILED_RESEARCH_AUTHORIZATION_CONTRACT_INVALID",
    ):
        service._verify_local_research_authorization_contract(  # noqa: SLF001
            contract,
            expected_auth_key_id="local-research-v1",
            authorization_hmac_key=_LOCAL_KEY,
        )


def test_same_entry_corpus_with_different_observation_is_not_reported_as_exact() -> None:
    manifest = types.SimpleNamespace(
        manifest_path=Path("/runtime/manifests/current.json"),
        manifest_id="a" * 64,
        metadata_sha256="b" * 64,
        observation_context_sha256="c" * 64,
        entry_chain_head_sha256="d" * 64,
        ordered_entry_identities_sha256="e" * 64,
        feature_ledger_high_water_sha256="1" * 64,
        label_archive_high_water_sha256="2" * 64,
        observation_time="2026-07-22T21:00:00.000000Z",
        total_profiled_samples=20,
        admitted_example_count=18,
        label_unavailable_count=2,
    )
    contract = {
        "manifest_path": "/runtime/manifests/old.json",
        "manifest_id": "f" * 64,
        "manifest_metadata_sha256": "3" * 64,
        "manifest_observation_context_sha256": "4" * 64,
        "manifest_entry_chain_head_sha256": "5" * 64,
        "manifest_ordered_entry_identities_sha256": "e" * 64,
        "manifest_feature_ledger_high_water_sha256": "1" * 64,
        "manifest_label_archive_high_water_sha256": "2" * 64,
        "manifest_observation_time": "2026-07-22T20:00:00.000000Z",
        "manifest_total_profiled_samples": 20,
        "manifest_admitted_example_count": 18,
        "manifest_label_unavailable_count": 2,
    }

    exact, entry_equivalent = service._manifest_contract_match(  # noqa: SLF001
        contract=contract,
        manifest=manifest,
    )

    assert exact is False
    assert entry_equivalent is True
