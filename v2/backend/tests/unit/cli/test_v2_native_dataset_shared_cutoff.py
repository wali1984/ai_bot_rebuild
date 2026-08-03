from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from v2.backend.app.services.native_trainer.dataset_builder import DatasetBuildResult


def _capture_dataset_calls(monkeypatch, module):
    captured: dict[str, datetime] = {}

    def load_labels(*_args, training_observed_at, **_kwargs):
        captured["labels"] = training_observed_at
        return []

    def build_universe(*_args, training_observed_at, **_kwargs):
        captured["universe"] = training_observed_at
        return DatasetBuildResult()

    def build_replay(*_args, training_observed_at, **_kwargs):
        captured["replay"] = training_observed_at
        return []

    monkeypatch.setattr(module, "load_label_rows", load_labels)
    monkeypatch.setattr(module, "build_dataset_for_universe", build_universe)
    monkeypatch.setattr(module, "build_rows_from_replay_bundles", build_replay)
    return captured


def _assert_one_aware_cutoff(captured: dict[str, datetime]) -> None:
    assert set(captured) == {"labels", "universe", "replay"}
    cutoff = captured["labels"]
    assert cutoff.tzinfo is not None
    assert cutoff.utcoffset() is not None
    assert captured["universe"] is cutoff
    assert captured["replay"] is cutoff


def test_dataset_builder_cli_uses_one_aware_observation_cutoff(
    monkeypatch,
    tmp_path,
) -> None:
    from v2.backend.app.cli import v2_native_trainer_dataset_builder as module

    captured = _capture_dataset_calls(monkeypatch, module)
    monkeypatch.setattr(module, "emit_dataset_artifacts", lambda **_kwargs: [])

    assert module.main(["--repo-root", str(tmp_path), "--no-redis"]) == 0
    _assert_one_aware_cutoff(captured)


def test_baseline_rebuild_uses_one_aware_observation_cutoff(
    monkeypatch,
    tmp_path,
) -> None:
    from v2.backend.app.cli import v2_native_trainer_baseline_evaluator as module
    from v2.backend.app.services.native_trainer import dataset_builder

    captured = _capture_dataset_calls(monkeypatch, module)
    monkeypatch.setattr(
        dataset_builder,
        "emit_dataset_artifacts",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        module,
        "evaluate_all_baselines",
        lambda *_args, **_kwargs: SimpleNamespace(
            publishable_baseline_available=False,
            trained_model=None,
            train_count=0,
            validation_count=0,
        ),
    )
    monkeypatch.setattr(
        module,
        "emit_packet",
        lambda **_kwargs: SimpleNamespace(go_no_go="BLOCKED", paths_written=[]),
    )

    assert module.main(
        [
            "--repo-root",
            str(tmp_path),
            "--rebuild-dataset",
            "--no-redis",
            "--no-publish",
        ]
    ) == 0
    _assert_one_aware_cutoff(captured)


def test_training_live_loop_cycle_uses_one_aware_observation_cutoff(
    monkeypatch,
    tmp_path,
) -> None:
    from v2.backend.app.cli import v2_trainer_training_live_loop as module

    captured = _capture_dataset_calls(monkeypatch, module)
    monkeypatch.setattr(module, "_connect_redis", lambda: None)
    monkeypatch.setattr(module, "emit_dataset_artifacts", lambda **_kwargs: [])
    monkeypatch.setattr(
        module,
        "evaluate_all_baselines",
        lambda *_args, **_kwargs: SimpleNamespace(
            publishable_baseline_available=False,
            trained_model=None,
        ),
    )
    monkeypatch.setattr(
        module,
        "emit_packet",
        lambda **_kwargs: SimpleNamespace(go_no_go="BLOCKED", paths_written=[]),
    )
    monkeypatch.setattr(module, "_write_json", lambda *_args, **_kwargs: None)

    payload = module.run_once(
        repo_root=tmp_path,
        write_v2_redis=False,
    )

    assert payload["dataset_rebuilt"] is True
    _assert_one_aware_cutoff(captured)
