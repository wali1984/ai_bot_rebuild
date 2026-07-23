from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from v2.backend.app.cli import v2_native_rl_masa_ppo_cuda_trainer_loop as cli


def test_cli_wires_external_durable_roots_and_consumer_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def run_cycle(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            go_no_go="PAPER_SHADOW_TEST",
            predictions=[],
            lineages=[],
            paths_written=(),
            status={"cuda_active": False},
        )

    monkeypatch.setattr(cli, "resolve_symbols", lambda: ["BTCUSDT"])
    monkeypatch.setattr(cli, "run_hybrid_trainer_cycle", run_cycle)

    model_dir = tmp_path / ".local_models" / "hybrid"
    replay_root = tmp_path / "immutable-replay"
    cursor_root = tmp_path / "consumer-cursors"
    counterfactual = tmp_path / "counterfactual.sqlite3"
    labels = tmp_path / "labels.sqlite3"
    receipts = tmp_path / "behavior-receipts"

    assert (
        cli.main(
            [
                "--no-redis",
                "--symbols",
                "BTCUSDT",
                "--timeframes",
                "5m",
                "--model-dir",
                str(model_dir),
                "--trusted-replay-archive-root",
                str(replay_root),
                "--trusted-replay-cursor-root",
                str(cursor_root),
                "--counterfactual-archive-path",
                str(counterfactual),
                "--canonical-5m-label-archive-path",
                str(labels),
                "--behavior-receipt-archive-root",
                str(receipts),
            ]
        )
        == 0
    )

    config = captured["config"]
    assert config.model_dir == model_dir.resolve()
    assert captured["publish"] is False
    assert captured["trusted_replay_archive_root"] == replay_root.resolve()
    assert captured["trusted_replay_cursor_root"] == cursor_root.resolve()
    assert captured["counterfactual_archive_path"] == counterfactual.resolve()
    assert captured["canonical_5m_label_archive_path"] == labels.resolve()
    assert captured["behavior_receipt_archive_root"] == receipts.resolve()
