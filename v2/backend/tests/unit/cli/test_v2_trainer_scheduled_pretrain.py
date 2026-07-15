from __future__ import annotations

from app.cli import v2_trainer_scheduled_pretrain as scheduled


def test_scheduled_pretrain_passes_risk_gate_to_h2l(monkeypatch) -> None:
    captured: dict[str, object] = {}
    training_rows = list(range(80))
    heldout_rows = list(range(10))

    monkeypatch.setattr(scheduled, "_gpu_free_vram_mb", lambda: None)
    monkeypatch.setattr(
        scheduled,
        "load_h2l_heldout_examples",
        lambda **_kwargs: (
            heldout_rows,
            training_rows,
            {"cache_hit": True},
        ),
    )
    monkeypatch.setattr(
        scheduled,
        "run_batch_training",
        lambda *_args, **_kwargs: {
            "trained_model": object(),
            "epochs_run": 1,
            "best_epoch": 1,
            "best_validation_loss": 1.0,
            "stopped_early": False,
            "gpu": {},
            "rows_per_second": 1.0,
        },
    )
    monkeypatch.setattr(
        scheduled,
        "save_offline_weights",
        lambda *_args, **_kwargs: {"checkpoint_id": "offline"},
    )
    monkeypatch.setattr(scheduled, "_publish", lambda _status: None)

    def fake_run_h2l(**kwargs):
        captured.update(kwargs)
        return {
            "decision": "DRY_RUN_OFFLINE_WINS_PASS_CONFIRM_TO_PROMOTE",
            "promoted": False,
            "risk_adjusted_validation": {"gate": {"required": True, "passed": True}},
        }

    monkeypatch.setattr(scheduled, "run_h2l", fake_run_h2l)

    status = scheduled.run_scheduled_pretrain(
        symbols=["BTCUSDT"],
        timeframes=["5m"],
        train_rows=80,
        heldout_rows=10,
        epochs=1,
        steps_per_epoch=1,
        batch_size=4,
        early_stop_patience=1,
        min_epochs=1,
        min_improvement=1.0,
        offline_dir="offline",
        live_dir="live",
        cache_path="cache.pkl",
        auto_promote=False,
        auto_restart=False,
        require_risk_gate=True,
        min_sortino=0.5,
        max_cvar_loss_bps=25.0,
    )

    assert status["require_risk_gate"] is True
    assert captured["require_risk_gate"] is True
    assert captured["min_sortino"] == 0.5
    assert captured["max_cvar_loss_bps"] == 25.0


def test_gpu_busy_aborts_gracefully_before_training(monkeypatch) -> None:
    """Regression (2026-07-15 00:46 run): a concurrent offline trainer held
    9GiB VRAM and the scheduled run crashed with CUDA OOM (unit failed,
    exit 1). Insufficient free VRAM must abort gracefully BEFORE training so
    the timer retries later."""
    from v2.backend.app.cli import v2_trainer_scheduled_pretrain as sp

    monkeypatch.setattr(sp, "_gpu_free_vram_mb", lambda: 900.0)
    monkeypatch.setattr(sp, "_publish", lambda status: None)
    monkeypatch.setattr(
        sp, "load_h2l_heldout_examples",
        lambda **kw: ([object()] * 100, [object()] * 500, {"cache_hit": True}),
    )
    called = {"train": False}

    def _no_train(*a, **kw):
        called["train"] = True
        raise AssertionError("training must not start when GPU is busy")

    monkeypatch.setattr(sp, "run_batch_training", _no_train)
    status = sp.run_scheduled_pretrain(
        symbols=["BTCUSDT"], timeframes=["1m"], train_rows=500, heldout_rows=100,
        epochs=1, steps_per_epoch=1, batch_size=64, early_stop_patience=2,
        min_epochs=1, min_improvement=0.0, offline_dir="x", live_dir="y",
        cache_path=None, auto_promote=False, auto_restart=False,
        require_risk_gate=True, min_sortino=0.0, max_cvar_loss_bps=None,
    )
    assert status["phase"] == "ABORT_GPU_BUSY_INSUFFICIENT_VRAM"
    assert called["train"] is False
    assert status["gpu_free_vram_mb"] == 900.0


def test_gpu_telemetry_unavailable_proceeds(monkeypatch) -> None:
    """No nvidia-smi (None) must not block the run."""
    from v2.backend.app.cli import v2_trainer_scheduled_pretrain as sp

    monkeypatch.setattr(sp, "_gpu_free_vram_mb", lambda: None)
    monkeypatch.setattr(sp, "_publish", lambda status: None)
    monkeypatch.setattr(
        sp, "load_h2l_heldout_examples",
        lambda **kw: ([object()] * 100, [object()] * 500, {"cache_hit": True}),
    )
    seen = {}

    def _train_marker(*a, **kw):
        seen["train_started"] = True
        raise RuntimeError("stop_after_gate_check")

    monkeypatch.setattr(sp, "run_batch_training", _train_marker)
    try:
        sp.run_scheduled_pretrain(
            symbols=["BTCUSDT"], timeframes=["1m"], train_rows=500, heldout_rows=100,
            epochs=1, steps_per_epoch=1, batch_size=64, early_stop_patience=2,
            min_epochs=1, min_improvement=0.0, offline_dir="x", live_dir="y",
            cache_path=None, auto_promote=False, auto_restart=False,
            require_risk_gate=True, min_sortino=0.0, max_cvar_loss_bps=None,
        )
    except RuntimeError as exc:
        assert str(exc) == "stop_after_gate_check"
    assert seen.get("train_started") is True
