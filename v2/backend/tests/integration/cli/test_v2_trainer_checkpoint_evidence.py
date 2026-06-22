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
