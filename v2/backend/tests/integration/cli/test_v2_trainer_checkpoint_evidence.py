from __future__ import annotations

from pathlib import Path


def test_trainer_checkpoint_evidence_selects_latest_real_legacy_roles(tmp_path: Path) -> None:
    from v2.backend.app.services.rl_core.trainer_checkpoint_evidence import (
        STATUS_PRESENT,
        WEIGHTS_NOT_LOADED,
        build_trainer_checkpoint_evidence,
    )

    ppo = tmp_path / "ppo_checkpoint_1772163701.zip"
    masa = tmp_path / "masa_checkpoint_1772262146.pkl"
    ent = tmp_path / "enterprise_modules_1772163701.pt"
    ppo.write_bytes(b"FAKEPPO")
    masa.write_bytes(b"FAKEMASA")
    ent.write_bytes(b"FAKEENT")
    payload = build_trainer_checkpoint_evidence([tmp_path])
    assert payload["checkpoint_evidence_status"] == STATUS_PRESENT
    assert payload["candidate_count"] == 3
    assert payload["selected_checkpoint_id"] == "masa_checkpoint_1772262146"
    assert payload["selected_by_role"]["latest_ppo"]["checkpoint_id"] == "ppo_checkpoint_1772163701"
    assert payload["selected_by_role"]["latest_masa"]["checkpoint_id"] == "masa_checkpoint_1772262146"
    assert payload["selected_by_role"]["latest_enterprise_modules"]["checkpoint_id"] == "enterprise_modules_1772163701"
    assert payload["checkpoint_weight_status"] == WEIGHTS_NOT_LOADED
    assert payload["weight_deserialization_performed"] is False
    assert payload["model_weights_loaded_into_v2_process"] is False
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []


def test_trainer_checkpoint_evidence_prefers_verified_native_safe_npz_for_active_status(tmp_path: Path) -> None:
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (
        V2HybridCheckpointManager,
    )
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
        V2HybridPolicyModel,
    )
    from v2.backend.app.services.rl_core.trainer_checkpoint_evidence import (
        NATIVE_WEIGHT_LOADED,
        build_trainer_checkpoint_evidence,
    )

    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    legacy = legacy_root / "ppo_checkpoint_1772163701.zip"
    legacy.write_bytes(b"FAKEPPO")
    native_dir = tmp_path / ".local_models/v2_native_rl_masa_ppo"
    manager = V2HybridCheckpointManager(native_dir)
    model = V2HybridPolicyModel(input_dim=8)
    manifest = manager.write_checkpoint(
        model=model,
        input_dim=model.input_dim,
        device=model.device,
        cuda_active=model.cuda_active,
        write_weight_blob=True,
    )

    payload = build_trainer_checkpoint_evidence(
        [legacy_root],
        native_model_dir=native_dir,
    )

    assert payload["selected_checkpoint_id"] == "ppo_checkpoint_1772163701"
    assert payload["active_checkpoint_id"] == manifest.checkpoint_id
    assert payload["active_checkpoint_source"] == "V2_SAFE_NATIVE_NPZ"
    assert payload["active_checkpoint_weight_status"] == NATIVE_WEIGHT_LOADED
    assert payload["checkpoint_weight_status"] == NATIVE_WEIGHT_LOADED
    assert payload["checkpoint_blocker"] is None
    assert payload["native_model_weights_load_verified"] is True
    assert payload["safe_npz_weight_load_verified"] is True
    assert payload["model_weights_loaded_scope"] == "checkpoint_evidence_safe_npz_probe"
    assert payload["pickle_deserialized"] is False
    assert payload["live_gate"] == "blocked_human_only"
