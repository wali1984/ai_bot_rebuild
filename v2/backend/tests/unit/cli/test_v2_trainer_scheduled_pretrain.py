from __future__ import annotations

from app.cli import v2_trainer_scheduled_pretrain as scheduled


def test_scheduled_pretrain_passes_risk_gate_to_h2l(monkeypatch) -> None:
    captured: dict[str, object] = {}
    training_rows = list(range(80))
    heldout_rows = list(range(10))

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
